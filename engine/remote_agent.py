"""Standalone SSH job supervisor (system Python, stdlib only). Shipped by transport.

No listener, provider token, repo, MPFB or Python package installation on the worker.
RPC uses SSH stdin. Render processes live beyond an SSH disconnect, with a local TTL.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

TERMINAL = ('done', 'failed', 'cancelled')


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def write(path, value):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value))
    os.replace(tmp, path)


def safe_path(root, name):
    p = root / name
    if p.resolve().is_relative_to(root.resolve()) and name and not Path(name).is_absolute():
        return p
    raise ValueError('Invalid job member path')


def hash_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def prune(root, cap):
    blobs = sorted((p for p in (root/'blobs').glob('*') if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in blobs)
    for p in blobs:
        if total <= cap:
            break
        if p.stat().st_nlink == 1:
            total -= p.stat().st_size
            p.unlink()


def rpc(req):
    root = Path(req['root'])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    (root/'blobs').mkdir(exist_ok=True)
    action = req['action']
    if action == 'missing':
        return {'missing': [h for h in req['hashes'] if not re.fullmatch('[0-9a-f]{64}', h)
                            or not (root/'blobs'/h).is_file() or hash_file(root/'blobs'/h) != h]}
    if action == 'probe':
        if sys.platform != 'linux' or sys.version_info < (3, 9):
            raise RuntimeError('Worker requires Linux and system Python 3.9+')
        p = subprocess.run([req['blender'], '--version'], capture_output=True, text=True, timeout=30)
        if p.returncode:
            raise RuntimeError('Blender unavailable')
        return {'version': p.stdout.splitlines()[0], 'python': sys.version.split()[0],
                'rsync': bool(shutil.which('rsync'))}
    ident = req['id']
    if not re.fullmatch('[a-zA-Z0-9_-]+', ident):
        raise ValueError('Invalid job id')
    directory = root/'jobs'/ident
    if action == 'start':
        (root/'jobs').mkdir(exist_ok=True)
        with open(root/'queue.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (directory/'status.json').exists():
                return read(directory/'status.json')
            active = [read(p, {}) for p in (root/'jobs').glob('*/status.json')]
            if sum(s.get('status') not in TERMINAL for s in active) >= req['max_parallel']:
                raise RuntimeError('Target max_parallel reached')
            directory.mkdir(mode=0o700, exist_ok=True)
            for name, h in req['files'].items():
                if not re.fullmatch('[0-9a-f]{64}', h) or hash_file(root/'blobs'/h) != h:
                    raise ValueError('Blob verification failed')
                dest = safe_path(directory, name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    os.link(root/'blobs'/h, dest)
            (directory/'agent.py').write_text(SOURCE)
            write(directory/'spec.json', req['spec'])
            write(directory/'status.json', {'status': 'starting', 'progress': '0/1'})
            with open(directory/'agent.log', 'wb') as log:
                p = subprocess.Popen([sys.executable, str(directory/'agent.py'), 'run', str(directory)],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            write(directory/'pid.json', p.pid)
            return {'status': 'starting', 'pid': p.pid}
    if action == 'status':
        state = read(directory/'status.json', {'status': 'missing'})
        pid = read(directory/'pid.json')
        if pid and state['status'] not in TERMINAL and state['status'] != 'missing':
            try:
                live = str(directory).encode() in Path(f'/proc/{pid}/cmdline').read_bytes()
            except OSError:
                live = False
            if not live:
                worker = read(directory/'worker_pid.json')
                try:
                    owned = worker and str(directory).encode() in Path(f'/proc/{worker}/cmdline').read_bytes()
                    if owned:
                        os.kill(worker, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                state.update(status='failed', error='Remote supervisor exited; owned worker stopped')
                write(directory/'status.json', state)
        return state
    if action == 'cancel':
        (directory/'cancel').touch()
        return {'cancel_requested': True}
    if action == 'cleanup':
        if read(directory/'status.json', {}).get('status') not in TERMINAL:
            raise RuntimeError('Cannot clean an active job')
        shutil.rmtree(directory, ignore_errors=True)
        prune(root, req['cache_bytes'])
        return {'cleaned': True}
    raise ValueError('Unknown remote action')


def run(directory):
    os.chdir(directory)
    directory = Path(directory)
    spec = read('spec.json')
    started = time.monotonic()
    stop = False

    def stopping(*args):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    state = {'status': 'running', 'stage': 'render', 'progress': f"0/{spec['frames']}"}
    proc = None

    def execute(command, logname, stage):
        nonlocal proc
        logpath = Path(logname)
        last_size, changed = -1, time.monotonic()
        with open(logpath, 'wb') as stream:
            proc = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        write('worker_pid.json', proc.pid)
        while proc.poll() is None:
            now = time.monotonic()
            size = logpath.stat().st_size
            if size != last_size:
                last_size, changed = size, now
            if stop or Path('cancel').exists():
                raise InterruptedError('Render cancelled')
            if now-started > spec['max_seconds']:
                raise TimeoutError('Remote time/budget cap reached')
            if now-changed > spec['idle_timeout_s']:
                raise TimeoutError('Remote idle watchdog expired')
            text = logpath.read_text(errors='replace')[-262144:]
            cursor = [int(n)+1 for n in re.findall(r'Video append frame\s+(\d+)', text)]
            cursor += [int(n) for n in re.findall(r'\bFra:\s*(\d+)', text)]
            done = min(spec['frames'], max(0, max(cursor, default=spec['start'])-spec['start']))
            state.update(stage=stage, progress=f'{done}/{spec["frames"]}',
                         elapsed_s=round(now-started, 1))
            state.update(read('device.json', {}))
            write('status.json', state)
            time.sleep(.5)
        if proc.returncode:
            raise RuntimeError('Blender worker failed; see downloaded render.log')

    try:
        command = [spec['blender'], '-b', '--factory-startup', '--disable-autoexec', str(directory/'scene.blend'),
                   '-t', str(spec['threads']), '--python-exit-code', '1', '--python',
                   str(directory/'worker.py'), '--', str(directory/'spec.json')]
        execute(command, 'render.log', 'render')
        movies = sorted(Path('.').glob('raw_*.mp4'))
        if not movies:
            raise RuntimeError('Worker produced no MP4')
        movie = movies[-1]
        if spec.get('overlays') or spec.get('transitions'):
            compose = dict(movie=str(movie.resolve()), out_base=str(directory/'composed_'),
                width=spec['size'][0], height=spec['size'][1], fps=spec['fps'], frames=spec['frames'],
                audio=spec['audio'], crf=spec['crf'], overlays=spec['overlays'], transitions=spec['transitions'])
            # Blender appends the frame range to outgoing-camera handles too.
            for trans in compose['transitions']:
                if trans['kind'] == 'crossfade':
                    found = list(Path('.').glob(Path(trans['movie']).stem+'*.mp4'))
                    trans['movie'] = str(found[-1].resolve())
            write('compose.json', compose)
            execute([spec['blender'], '-b', '--factory-startup', '--disable-autoexec', '-t', str(spec['threads']),
                     '--python-exit-code', '1', '--python', str(directory/'compose.py'), '--',
                     str(directory/'compose.json')], 'compose.log', 'compose')
            movie = sorted(Path('.').glob('composed_*.mp4'))[-1]
        os.replace(movie, 'result.mp4')
        state.update(status='done', progress=f'{spec["frames"]}/{spec["frames"]}',
                     sha256=hash_file('result.mp4'), bytes=Path('result.mp4').stat().st_size,
                     timing=read('timing.json', {}))
    except Exception as exc:
        state.update(status='cancelled' if isinstance(exc, InterruptedError) else 'failed', error=str(exc))
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        state['elapsed_s'] = round(time.monotonic()-started, 1)
        write('status.json', state)


if __name__ == '__main__':
    if sys.argv[1] == 'run':
        run(sys.argv[2])
    else:
        try:
            print(json.dumps(rpc(json.load(sys.stdin))))
        except Exception as exc:
            print(json.dumps({'rpc_error': str(exc)}))
            sys.exit(1)
