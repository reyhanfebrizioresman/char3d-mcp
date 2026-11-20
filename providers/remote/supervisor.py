"""Durable local supervisor: owns leases, watchdog, SSH reattachment and delivery.

Runs detached from MCP. State contains IDs/quotes, never provider responses or keys.
Cleanup is retried until acknowledged, including after a restart.
"""
import copy
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time

from engine.render_metrics import frame_times
from .cloud import Cloud
from .config import RemoteError, clean_env, digest, read_json, write_json
from .jobs import TERMINAL, engine_key
from .transport import ROOT, SSH, file_hash


def bundle(child, t, seconds):
    files = dict(child.get('remote_assets', {}))
    files.update({'scene.blend': child['blend'], 'worker.py': str(ROOT/'engine/remote_worker.py'),
                  'compose.py': str(ROOT/'engine/compose_subtitles.py')})
    overlays, transitions = copy.deepcopy(child['overlays']), copy.deepcopy(child['transitions'])
    for i, ov in enumerate(overlays):
        name = f'overlays/{i}.png'
        files[name] = ov['path']
        ov['path'] = name
    handles = []
    for i, trans in enumerate(transitions):
        if trans['kind'] == 'crossfade':
            trans['movie'] = f'handle_{i}_'
            start = child['frames'][0]
            handles.append({'path': trans['movie'], 'camera': trans['camera'],
                            'frames': [trans['start']+start-1, trans['end']+start-1]})
    spec = dict(blender=t['blender'], blender_version=child['blender_version'], device=t['device'],
        threads=t['threads'], start=child['frames'][0], frames=child['frames'][1]-child['frames'][0]+1,
        size=child['size'], fps=child['fps'], audio=child['audio'], handles=handles,
        overlays=overlays, transitions=transitions, max_seconds=seconds,
        idle_timeout_s=t['idle_timeout_s'], crf='HIGH' if child['quality'] in ('final', 'cycles') else 'MEDIUM')
    return files, spec


def verify(path, frames, size, audio=False):
    import av
    try:
        with av.open(str(path)) as container:
            if not container.streams.video:
                raise ValueError('missing video')
            stream = container.streams.video[0]
            if [stream.width, stream.height] != size:
                raise ValueError('wrong dimensions')
            n = sum(1 for _ in container.decode(video=0))
            if n != frames:
                raise ValueError('wrong decoded frame count')
        if audio:
            with av.open(str(path)) as container:
                if not container.streams.audio or not any(container.decode(audio=0)):
                    raise ValueError('missing/invalid audio')
        return {'frames': n, 'size': size, 'audio': audio, 'decoder': 'PyAV'}
    except Exception:
        raise RemoteError('Downloaded movie failed PyAV verification (frames, dimensions or audio)') from None


class Supervisor:
    def __init__(self, path):
        self.path = Path(path)
        self.state = read_json(path)
        self.state.setdefault('scenes', copy.deepcopy(self.state['prepared']['job'].get('scenes', [])))
        self.t = self.state['target']
        self.cloud = Cloud(self.t['kind']) if self.t['kind'] != 'ssh' else None
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.active_ssh = None
        self.active_id = None
        self.child_proc = None
        self.last_progress = time.monotonic()
        self.watch_done = threading.Event()

    def save(self, **updates):
        with self.lock:
            self.state.update(updates)
            write_json(self.path, self.state)

    def caps(self):
        q = self.state['quote']
        seconds = q['max_hours']*3600
        if q['max_budget_usd'] is not None and q['hourly_price_usd']:
            # Reserve 30 seconds for API shutdown. Includes provisioning and transfer.
            seconds = min(seconds, q['max_budget_usd']/q['hourly_price_usd']*3600)
        return max(0, seconds-30)

    def watchdog(self):
        while not self.watch_done.wait(.5):
            elapsed = time.time()-self.state.get('lease_started', self.state['started'])
            capped = elapsed >= self.caps()
            idle = time.monotonic()-self.last_progress >= self.t['idle_timeout_s']
            if (self.path.parent/'cancel').exists() or capped or idle:
                self.stop.set()
                self.save(error='Budget/time cap reached' if capped else 'Idle watchdog expired' if idle else 'Render cancelled')
                if self.child_proc and self.child_proc.poll() is None:
                    self.child_proc.terminate()
                # Paid teardown must not wait for an unreachable SSH connection.
                if self.cloud:
                    self.cleanup_cloud()
                if self.active_ssh and self.active_id and not self.cloud:
                    try:
                        self.active_ssh.rpc('cancel', id=self.active_id)
                    except RemoteError:
                        pass
                return

    def check(self):
        if (self.path.parent/'cancel').exists():
            self.stop.set()
        if time.time()-self.state.get('lease_started', self.state['started']) >= self.caps():
            self.save(error='Budget/time cap reached')
            self.stop.set()
        if self.stop.is_set():
            raise InterruptedError(self.state.get('error', 'Render cancelled'))

    def provision(self):
        if not self.cloud or not self.state['prepared']['children']:
            return self.t
        label = self.state.setdefault('lease_label', 'char3d-'+self.state['id'])
        if not self.state.get('lease_started'):
            fresh = self.cloud.quote(self.t)
            if (fresh['offer_id'] != self.state['offer']['offer_id'] or
                    fresh['hourly_price_usd'] > self.state['offer']['hourly_price_usd']+1e-8):
                raise RemoteError('Provider offer/price changed; obtain and confirm a new quote')
            self.save(lease_label=label, lease_started=time.time(), stage='create', creation_uncertain=True)
            # No automatic retry of a non-idempotent paid create. Ambiguous responses
            # are reconciled by unique label in cleanup, never by creating again.
            ident = self.cloud.create(self.t, self.state['offer'], label)
            self.save(instance_id=ident, creation_uncertain=False, cleanup_pending=True)
            self.cloud.attach_key(self.t, ident)
        elif not self.state.get('instance_id'):
            found = self.cloud.find(label)
            if not found:
                raise RemoteError('Ambiguous paid create; cleanup reconciliation required')
            self.save(instance_id=str(found[0]['id']), creation_uncertain=False, cleanup_pending=True)
        self.save(stage='wait_ssh')
        while True:
            self.check()
            data = self.cloud.inspect(self.state['instance_id'])
            connection = self.cloud.connection(self.t, data, self.state['quote']['hourly_price_usd'])
            if connection:
                self.save(ssh_host=connection['host'], ssh_port=connection['port'])
                try:
                    SSH(connection).rpc('probe', blender=connection['blender'])
                    return connection
                except RemoteError:
                    pass
            self.stop.wait(2)

    def cleanup_cloud(self):
        if not self.cloud or not self.state.get('lease_started'):
            return True
        if self.state.get('lease_finished'):
            return True
        # Serialize watchdog/finally cleanup. A provider 404 is an acknowledged deletion.
        with self.lock:
            try:
                ident = self.state.get('instance_id')
                if ident:
                    try:
                        data = self.cloud.inspect(ident)
                        self.state['billing'] = self.cloud.billing(data)
                    except RemoteError:
                        pass
                    self.cloud.terminate(ident)
                for item in self.cloud.find(self.state['lease_label']):
                    self.cloud.terminate(str(item['id']))
                if self.state.get('creation_uncertain') and time.time()-self.state['lease_started'] < 600:
                    self.save(cleanup_pending=True)
                    return False
                self.save(cleanup_pending=False, cleanup_error=None, lease_finished=time.time(), remote_jobs=[])
                if ident:
                    try:
                        bill = self.cloud.final_billing(ident, self.state['lease_started'])
                        if bill:
                            self.save(billing={**self.state.get('billing', {}), **bill})
                    except RemoteError:
                        pass  # Billing can lag; failure never delays instance deletion.
                return True
            except RemoteError:
                self.save(cleanup_pending=True, cleanup_error='Provider cleanup not acknowledged; retrying')
                return False

    def cleanup_remote(self):
        """Persist SSH cleanup too, so cancellation/errors do not strand snapshots."""
        pending = list(self.state.get('remote_jobs', []))
        for entry in pending[:]:
            try:
                ssh = SSH(entry['connection'])
                report = ssh.rpc('status', id=entry['id'])
                if report['status'] not in TERMINAL and report['status'] != 'missing':
                    ssh.rpc('cancel', id=entry['id'])
                    continue
                if report['status'] != 'missing':
                    ssh.rpc('cleanup', id=entry['id'], cache_bytes=self.t['cache_bytes'])
                pending.remove(entry)
            except RemoteError:
                pass
        self.save(remote_jobs=pending, cleanup_pending=bool(pending),
                  cleanup_error='SSH cleanup pending; reconnecting' if pending else None)
        return not pending

    def cost(self):
        elapsed = (self.state.get('lease_finished') or time.time())-self.state.get('lease_started', self.state['started'])
        self.save(elapsed_s=round(time.time()-self.state['started'], 1),
                  cost_so_far_usd=round(elapsed/3600*self.state['quote']['hourly_price_usd'], 6))

    def cleanup_local(self):
        for child in self.state['prepared']['children']:
            Path(child['blend']).unlink(missing_ok=True)
            if child.get('subs_dir'):
                shutil.rmtree(child['subs_dir'], ignore_errors=True)

    def learn(self, child, remote, log):
        times = frame_times(log)
        if len(times) > 3:
            times = times[1:]
        measured = statistics.median(times) if times else remote.get('timing', {}).get('render_s', 0)/max(1, child['frames'][1]-child['frames'][0]+1)
        if self.state.get('calibration'):
            measured *= .85
        if measured <= 0 or not child['model_spf']:
            return
        speed_path = self.path.parents[2]/'speed.json'
        with open(speed_path.with_suffix('.lock'), 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = read_json(speed_path, {})
            key = digest([self.state['target_name'], self.t, engine_key(child['quality'])])
            old = data.get(key, {})
            ratio = min(100, max(.001, measured/child['model_spf']))
            factor = math.sqrt(old['factor']*ratio) if old else ratio
            data[key] = dict(factor=factor, samples=old.get('samples', 0)+1,
                             measured_s_per_frame=measured, updated=time.time())
            write_json(speed_path, data)
        self.save(learned_speed=data[key])

    def render_child(self, ssh, child, index):
        ident = self.state['id']+'_'+str(index)
        self.active_id = ident
        self.active_ssh = ssh
        completed = self.state.get('completed', [])
        if index in completed and Path(child['path']).is_file():
            return
        self.save(stage=f'scene {index+1}/{len(self.state["prepared"]["children"])}', active_remote_id=ident)
        files, spec = bundle(child, ssh.target, max(1, self.caps()-(time.time()-self.state.get('lease_started', self.state['started']))))
        probe = ssh.rpc('probe', blender=ssh.target['blender'])
        if not probe.get('rsync', True):
            raise RemoteError('Install rsync on the remote worker')
        version = '.'.join(map(str, child['blender_version']))
        if not probe['version'].startswith('Blender '+version):
            raise RemoteError('Blender version mismatch; install the exact local version on target')
        self.check()
        mapping = ssh.upload(files, self.path.parents[2]/'blobs')
        self.check()
        entries = self.state.get('remote_jobs', [])
        if not any(e['id'] == ident for e in entries):
            self.save(remote_jobs=entries+[dict(id=ident, connection=ssh.target)], cleanup_pending=True)
        ssh.rpc('start', id=ident, files=mapping, spec=spec, max_parallel=self.t['max_parallel'])
        last = None
        while True:
            self.check()
            try:
                remote = ssh.rpc('status', id=ident)
            except RemoteError:
                self.save(stage='reconnecting (remote worker keeps rendering)')
                self.stop.wait(2)
                continue
            self.cost()
            if remote.get('progress') != last:
                last = remote.get('progress')
                self.last_progress = time.monotonic()
            progress = remote.get('progress', '0/1')
            eta = max(0, self.state['quote']['estimated_runtime_s']-remote.get('elapsed_s', 0))
            if self.state['kind'] == 'film':
                scenes = self.state['scenes']
                for scene in scenes:
                    if scene.get('job_id') == child['id']:
                        scene.update(status='running', progress=progress, eta_s=eta)
                stages = sum(s['status'] in ('done', 'reused') for s in scenes)
                self.save(scenes=scenes, progress=f'{stages}/{len(scenes)+1}',
                          progress_unit='stages', frame_progress=progress)
            else:
                self.save(progress=progress, progress_unit='frames')
            self.save(device=remote.get('device', self.t['device']), gpu=remote.get('gpu'), eta_s=eta)
            if remote['status'] in TERMINAL:
                break
            if remote['status'] == 'missing':
                raise RemoteError('Remote job disappeared; no automatic paid replacement')
            self.stop.wait(.5)
        local_log = self.path.parent/f'scene{index}.log'
        ssh.download(ident, 'render.log', local_log)
        if remote['status'] != 'done':
            raise RemoteError(remote.get('error', 'Remote worker failed'))
        dest = Path(child['path'])
        part = dest.with_suffix('.remote.part.mp4')
        # Retried downloads retain partial bytes and never touch the delivered output.
        while True:
            self.check()
            try:
                ssh.download(ident, 'result.mp4', part)
                break
            except RemoteError:
                self.save(stage='reconnecting (download)')
                self.stop.wait(2)
        if file_hash(part) != remote['sha256']:
            raise RemoteError('Downloaded movie checksum mismatch')
        checked = verify(part, spec['frames'], child['size'], child['audio'])
        os.replace(part, dest)
        self.learn(child, remote, local_log.read_text(errors='replace'))
        for scene in self.state.get('scenes', []):
            if scene.get('job_id') == child['id']:
                scene['status'] = 'done'
        self.save(completed=completed+[index], verified=checked)
        try:
            ssh.rpc('cleanup', id=ident, cache_bytes=self.t['cache_bytes'])
            remaining = [e for e in self.state.get('remote_jobs', []) if e['id'] != ident]
            self.save(remote_jobs=remaining, cleanup_pending=bool(remaining) or bool(self.cloud))
        except RemoteError:
            pass  # Durable finally/restart cleanup retries; the verified clip is kept.
        self.active_id = None

    def compose(self, prepared):
        self.save(stage='compose film locally')
        spec = prepared['compose']
        directory = Path(prepared['job']['directory'])
        path = directory/'remote_compose.json'
        write_json(path, spec)
        with open(directory/'remote_compose.log', 'wb') as log:
            self.child_proc = subprocess.Popen([prepared['blender'], '-b', '--factory-startup',
                '--disable-autoexec', '-t', str(self.t['threads']), '--python-exit-code', '1',
                '--python', str(ROOT/'engine/compose_film.py'), '--', str(path)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=clean_env())
        while self.child_proc.poll() is None:
            self.check()
            self.stop.wait(.5)
        if self.child_proc.returncode:
            raise RemoteError('Local film composition failed; see remote_compose.log')
        movie = sorted(directory.glob('composed_*.mp4'))[-1]
        checked = verify(movie, spec['frames'], [spec['width'], spec['height']], True)
        os.replace(movie, prepared['job']['path'])
        self.save(verified=checked)

    def run(self):
        if self.state['status'] in TERMINAL:
            while not self.cleanup_cloud():
                time.sleep(5)
            while not self.cleanup_remote():
                time.sleep(5)
            self.cleanup_local()
            return
        self.save(status='running')
        watcher = threading.Thread(target=self.watchdog, daemon=True)
        watcher.start()
        try:
            self.check()
            t = self.provision()
            ssh = SSH(t) if self.state['prepared']['children'] else None
            for index, child in enumerate(self.state['prepared']['children']):
                self.render_child(ssh, child, index)
            # Paid compute is released before any local film composition.
            if not self.cleanup_cloud():
                raise RemoteError('Provider cleanup pending; composition deferred')
            prepared = self.state['prepared']
            if prepared['kind'] == 'film':
                self.compose(prepared)
            job = prepared['job']
            if prepared['kind'] == 'film':
                count = len(job['scenes'])+1
            else:
                bounds = job.get('frames') or prepared['children'][0]['frames']
                count = bounds[1]-bounds[0]+1
            self.save(status='done', stage='done', bytes=Path(job['path']).stat().st_size,
                      credits=job.get('credits'), subtitles=job.get('subtitles'),
                      scenes=[dict(s, status='reused' if s.get('reused') else 'done')
                              for s in job.get('scenes', [])], progress=f'{count}/{count}', eta_s=0,
                      has_audio=self.state.get('verified', {}).get('audio', False))
        except InterruptedError:
            self.save(status='cancelled')
        except Exception as exc:
            # Provider exceptions are sanitized by Cloud; unexpected failures have no repr/traceback.
            self.save(status='failed', error=str(exc) if isinstance(exc, RemoteError) else
                      'Remote supervisor failed ('+type(exc).__name__+'); credentials redacted')
        finally:
            if self.child_proc and self.child_proc.poll() is None:
                self.child_proc.terminate()
                try:
                    self.child_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.child_proc.kill()
                    self.child_proc.wait()
            if self.active_ssh and self.active_id and self.state['status'] != 'done':
                try:
                    self.active_ssh.rpc('cancel', id=self.active_id)
                except RemoteError:
                    pass  # Remote TTL remains active even if SSH is unreachable.
            while not self.cleanup_cloud():
                self.cost()
                time.sleep(5)
            while not self.cleanup_remote():
                time.sleep(2)
            self.watch_done.set()
            watcher.join(timeout=20)
            self.cost()
            self.cleanup_local()


def main(path):
    with open(Path(path).parent/'worker.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        supervisor = Supervisor(path)
        signal.signal(signal.SIGTERM, lambda *args: supervisor.stop.set())
        signal.signal(signal.SIGINT, lambda *args: supervisor.stop.set())
        supervisor.run()


if __name__ == '__main__':
    main(sys.argv[1])
