"""Standalone SSH job supervisor (system Python, stdlib only). Shipped by transport.

No listener, provider token, repo, MPFB or Python package installation on the worker.
RPC uses SSH stdin. Render processes live beyond an SSH disconnect, with a local TTL.
"""
from contextlib import contextmanager
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
import uuid

WINDOWS = os.name == 'nt'

TERMINAL = ('done', 'failed', 'cancelled')


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def write(path, value):
    path = Path(path)
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        for attempt in range(40):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(.025)  # Windows readers/virus scanners can hold a file briefly.
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def queue_lock(path):
    with open(path, 'a+b') as stream:
        if WINDOWS:
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(.05)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if WINDOWS:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def process_token(pid):
    """Windows PID + kernel creation time; never kill a reused/unrelated PID."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, int(pid))
    if not handle:
        return None
    try:
        if kernel.WaitForSingleObject(handle, 0) != 258:
            return None
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, *map(ctypes.byref, (created, exited, system, user))):
            raise RuntimeError('Cannot identify owned Windows process')
        return {'pid': int(pid), 'created': str((created.dwHighDateTime << 32) | created.dwLowDateTime)}
    finally:
        kernel.CloseHandle(handle)


def pid_record(pid):
    if not WINDOWS:
        return pid
    record = process_token(pid)
    if record is None:
        return {'pid': int(pid), 'exited': True}
    return record


def owned_process(record, directory):
    if WINDOWS:
        return isinstance(record, dict) and process_token(record['pid']) == record
    if not isinstance(record, int):
        return False
    try:
        return str(directory).encode() in Path(f'/proc/{record}/cmdline').read_bytes()
    except OSError:
        return False


def stop_tree(record, directory):
    if not owned_process(record, directory):
        return
    if WINDOWS:
        result = subprocess.run(['taskkill.exe', '/PID', str(record['pid']), '/T', '/F'],
            capture_output=True, timeout=15, creationflags=0x08000000)
        if result.returncode and owned_process(record, directory):
            raise RuntimeError('Could not stop the owned Windows worker tree')
    else:
        try:
            os.kill(record, signal.SIGKILL)
        except ProcessLookupError:
            pass


def detach_options(breakaway=True):
    # Windows OpenSSH runs each session in a job object that kills its processes when
    # the connection closes; CREATE_BREAKAWAY_FROM_JOB keeps the supervisor alive.
    if not WINDOWS:
        return {'start_new_session': True}
    return {'creationflags': 0x00000008 | 0x00000200 | (0x01000000 if breakaway else 0)}


def worker_options():
    return {'creationflags': 0x00000200 | 0x08000000} if WINDOWS else {}


def gpu_inventory():
    binary = shutil.which('nvidia-smi')
    if not binary and WINDOWS:
        candidate = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/nvidia-smi.exe'
        binary = str(candidate) if candidate.is_file() else None
    if not binary:
        return []
    try:
        result = subprocess.run([binary, '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10,
            **({'creationflags': 0x08000000} if WINDOWS else {}))
        if result.returncode:
            return []
        return [dict(name=name.strip(), vram_bytes=int(float(size.strip())*2**20), source='nvidia-smi')
                for name, size in (row.rsplit(',', 1) for row in result.stdout.splitlines() if row.strip())]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


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
    pinned = {h for p in (root/'jobs').glob('*/files.json') for h in read(p, {}).values()}
    blobs = sorted((p for p in (root/'blobs').glob('*') if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in blobs)
    for p in blobs:
        if total <= cap:
            break
        if p.stat().st_nlink == 1 and p.name not in pinned:
            total -= p.stat().st_size
            p.unlink()


def rpc(req):
    root = Path(req['root'])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not WINDOWS:
        os.chmod(root, 0o700)
    (root/'blobs').mkdir(exist_ok=True)
    action = req['action']
    if action == 'ping':
        return {'reachable':True,'os':'windows' if WINDOWS else 'linux','time':time.time()}
    if action in ('stage_upload', 'finish_upload', 'discard_upload'):
        token = req['token']
        if not re.fullmatch('[0-9a-f]{32}', token):
            raise ValueError('Invalid upload token')
        stage = root/'uploads'/token
        if action == 'stage_upload':
            stage.mkdir(parents=True, exist_ok=True)
            # Interrupted SCP staging never becomes a cache blob. Expire abandoned
            # batches after a day; current transfers have a two-minute timeout.
            for old in stage.parent.iterdir():
                if old != stage and old.is_dir() and time.time()-old.stat().st_mtime > 86400:
                    shutil.rmtree(old)
        elif action == 'discard_upload':
            shutil.rmtree(stage, ignore_errors=True)
        else:
            try:
                # Idempotent for a retried request: blobs already moved and verified
                # by an earlier attempt are accepted.
                pending = [h for h in req['hashes'] if not (
                    re.fullmatch('[0-9a-f]{64}', h) and not (stage/h).exists()
                    and (root/'blobs'/h).exists() and hash_file(root/'blobs'/h) == h)]
                for h in pending:
                    if not re.fullmatch('[0-9a-f]{64}', h) or hash_file(stage/h) != h:
                        raise ValueError('Uploaded blob SHA-256 mismatch')
                for h in pending:
                    os.replace(stage/h, root/'blobs'/h)
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        return {'ok': True}
    if action == 'missing':
        return {'missing': [h for h in req['hashes'] if not re.fullmatch('[0-9a-f]{64}', h)
                            or not (root/'blobs'/h).is_file() or hash_file(root/'blobs'/h) != h]}
    if action == 'probe':
        if (not WINDOWS and sys.platform != 'linux') or sys.version_info < (3, 9):
            raise RuntimeError('Worker requires Linux/Windows and system Python 3.9+')
        p = subprocess.run([req['blender'], '--version'], capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=30, **worker_options())
        if p.returncode:
            raise RuntimeError('Blender unavailable')
        return {'version': p.stdout.splitlines()[0], 'python': sys.version.split()[0],
                'rsync': bool(shutil.which('rsync')), 'os': 'windows' if WINDOWS else 'linux',
                'gpus': gpu_inventory()}
    ident = req['id']
    if not re.fullmatch('[a-zA-Z0-9_-]+', ident):
        raise ValueError('Invalid job id')
    directory = root/'jobs'/ident
    if action == 'frames':
        return read(directory/'frames.json',{'version':1,'files':{}})
    if action in ('start','resume'):
        (root/'jobs').mkdir(exist_ok=True)
        with queue_lock(root/'queue.lock'):
            if (directory/'status.json').exists() and action=='start':
                return read(directory/'status.json')
            if action=='resume':
                old=read(directory/'status.json',{})
                if (old.get('status')=='done' or
                        (old.get('status') not in TERMINAL and owned_process(read(directory/'pid.json'),directory))):
                    settings=read(directory/'spec.json',{})
                    if req.get('spec',{}).get('attempt'):
                        settings['attempt']=req['spec']['attempt'];write(directory/'spec.json',settings)
                        old['attempt']=settings['attempt'];write(directory/'status.json',old)
                    (directory/'cancel').unlink(missing_ok=True)
                    return old
                if not read(directory/'spec.json',{}).get('durable'):
                    raise RuntimeError('Legacy direct-MP4 job cannot restart durably')
                req=dict(req,files=req.get('files',read(directory/'files.json',{})),
                         spec=req.get('spec',read(directory/'spec.json')))
                (directory/'cancel').unlink(missing_ok=True)
            active = [read(p, {}) for p in (root/'jobs').glob('*/status.json') if p.parent!=directory]
            if sum(s.get('status') not in TERMINAL for s in active) >= req['max_parallel']:
                raise RuntimeError('Target max_parallel reached')
            directory.mkdir(mode=0o700, exist_ok=True)
            p = None
            try:
                write(directory/'status.json', {'status': 'starting', 'progress': '0/1'})
                write(directory/'files.json', req['files'])
                for name, h in req['files'].items():
                    if not re.fullmatch('[0-9a-f]{64}', h) or hash_file(root/'blobs'/h) != h:
                        raise ValueError('Blob verification failed')
                    dest = safe_path(directory, name)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if name=='frames.json' and dest.exists():
                        # The remote disk may contain newer frames than the mirror.
                        continue
                    if dest.exists() and hash_file(dest)!=h:dest.unlink()
                    if not dest.exists():
                        try:
                            os.link(root/'blobs'/h, dest)
                        except OSError:
                            shutil.copyfile(root/'blobs'/h, dest)
                (directory/'agent.py').write_text(SOURCE, encoding='utf-8')
                write(directory/'spec.json', req['spec'])
                with open(directory/'agent.log', 'wb') as log:
                    command = [sys.executable, str(directory/'agent.py'), 'run', str(directory)]
                    try:
                        p = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                             stderr=subprocess.STDOUT, **detach_options())
                    except PermissionError:
                        # A job without JOB_OBJECT_LIMIT_BREAKAWAY_OK refuses breakaway.
                        p = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                             stderr=subprocess.STDOUT, **detach_options(False))
                write(directory/'pid.json', pid_record(p.pid))
            except Exception:
                if p and p.poll() is None:
                    # This Popen still owns the process handle, even if recording a
                    # PID failed. Do not leave an untracked supervisor running.
                    p.kill()
                    p.wait()
                write(directory/'status.json', {'status': 'failed', 'error': 'Could not prepare/start remote supervisor'})
                raise
            return {'status': 'starting', 'pid': p.pid}
    if action == 'status':
        state = read(directory/'status.json', {'status': 'missing'})
        pid = read(directory/'pid.json')
        if pid and state['status'] not in TERMINAL and state['status'] != 'missing':
            live = owned_process(pid, directory)
            if not live:
                worker = read(directory/'worker_pid.json')
                stop_tree(worker, directory)
                state.update(status='failed', error='Remote supervisor exited; owned worker stopped')
                state['recoverable']=bool(read(directory/'spec.json',{}).get('durable'))
                write(directory/'status.json', state)
        return state
    if action == 'cancel':
        if req.get('attempt') and read(directory/'spec.json',{}).get('attempt')!=req['attempt']:
            return {'acknowledged':True,'superseded':True}
        (directory/'cancel').touch()
        if WINDOWS:
            stop_tree(read(directory/'worker_pid.json'), directory)
        return {'cancel_requested': True,'acknowledged':True,'at':time.time()}
    if action == 'cleanup':
        if req.get('attempt') and read(directory/'spec.json',{}).get('attempt')!=req['attempt']:
            return {'cleaned':True,'superseded':True}
        if read(directory/'status.json', {}).get('status') not in TERMINAL:
            raise RuntimeError('Cannot clean an active job')
        for attempt in range(40):
            try:
                shutil.rmtree(directory)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt == 39:
                    raise RuntimeError('Worker files still in use; retry cleanup') from None
                time.sleep(.05)
        prune(root, req['cache_bytes'])
        return {'cleaned': True,'at':time.time()}
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
    state = {'status': 'running', 'stage': 'render', 'progress': f"0/{spec['frames']}",
             'durable':bool(spec.get('durable')),'attempt':spec.get('attempt')}
    proc = None

    def execute(command, logname, stage):
        nonlocal proc
        logpath = Path(logname)
        last_size, changed = -1, time.monotonic()
        with open(logpath, 'wb') as stream:
            proc = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, **worker_options())
        write('worker_pid.json', pid_record(proc.pid))
        while proc.poll() is None:
            now = time.monotonic()
            size = logpath.stat().st_size
            if size != last_size:
                last_size, changed = size, now
            if stop or Path('cancel').exists():
                raise InterruptedError('Render cancelled')
            if now-started > spec['max_seconds'] or time.time()>spec.get('deadline_at',float('inf')):
                raise TimeoutError('Remote time/budget cap reached')
            if now-changed > spec['idle_timeout_s']:
                raise TimeoutError('Remote idle watchdog expired')
            text = logpath.read_text(encoding='utf-8', errors='replace')[-262144:]
            cursor = [int(n)+1 for n in re.findall(r'Video append frame\s+(\d+)', text)]
            cursor += [int(n) for n in re.findall(r'\bFra:\s*(\d+)', text)]
            done = min(spec['frames'], max(0, max(cursor, default=spec['start'])-spec['start']))
            state.update(stage=stage, progress=f'{done}/{spec["frames"]}',
                         elapsed_s=round(now-started, 1))
            state.update(read('device.json', {}))
            if spec.get('durable'):
                index=read('frames.json',{'files':{}})
                done=sum(e.get('channel')=='main' for e in index['files'].values())
                state.update(progress=f'{done}/{spec["frames"]}',durable=True,frames_done=done)
            write('status.json', state)
            time.sleep(.5)
        if stop or Path('cancel').exists():
            raise InterruptedError('Render cancelled')
        if proc.returncode:
            raise RuntimeError('Blender worker failed; see downloaded render.log')

    try:
        command = [spec['blender'], '-b', '--factory-startup', '--disable-autoexec', str(directory/'scene.blend'),
                   '-t', str(spec['threads']), '--python-exit-code', '1', '--python',
                   str(directory/'worker.py'), '--', str(directory/'spec.json')]
        execute(command, 'render.log', 'render')
        if spec.get('durable'):
            execute([spec['blender'],'-b','--factory-startup','--disable-autoexec','-t',str(spec['threads']),
                '--python-exit-code','1','--python',str(directory/'encode.py'),'--',str(directory/'spec.json')],
                'encode.log','encode durable frames')
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
        if proc and proc.poll() is not None:
            # Windows native crash exit codes are positive NTSTATUS values, unlike
            # POSIX signal exits. Retry unexpected worker exits on the same lease;
            # cancellation and TTL/idle expiry must never restart automatically.
            state['recoverable']=bool(spec.get('durable') and proc.returncode and isinstance(exc,RuntimeError))
    finally:
        if proc and proc.poll() is None:
            if WINDOWS:
                stop_tree(read('worker_pid.json'), directory)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        state['elapsed_s'] = round(time.monotonic()-started, 1)
        write('status.json', state)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    if sys.argv[1] == 'run':
        run(sys.argv[2])
    else:
        try:
            print(json.dumps(rpc(json.load(sys.stdin))))
        except Exception as exc:
            print(json.dumps({'rpc_error': str(exc)}))
            sys.exit(1)
