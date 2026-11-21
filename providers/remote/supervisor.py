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
import uuid
from contextlib import contextmanager

from engine.render_metrics import frame_times
from engine.render_compat import check_version, memory_warning
from .cloud import Cloud
from .config import RemoteError, clean_env, digest, read_json, write_json, render_profile
from .jobs import TERMINAL, engine_key
from .transport import ROOT, SSH, Unreachable, file_hash
from .local import LocalWorker
from .checkpoints import mirror, seeds
from engine.remote_frames import read_index, provenance


class SwitchEndpoint(Exception):
    pass


def bundle(child, t, seconds):
    seconds=min(seconds,t.get('max_hours',4)*3600)
    files = dict(child.get('remote_assets', {}))
    files.update({'scene.blend': child['blend'], 'worker.py': str(ROOT/'engine/remote_worker.py'),
                  'compose.py': str(ROOT/'engine/compose_subtitles.py'),
                  'render_compat.py': str(ROOT/'engine/render_compat.py'),
                  'remote_frames.py':str(ROOT/'engine/remote_frames.py'),
                  'encode.py':str(ROOT/'engine/encode_remote.py')})
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
        blender_version_policy=t.get('blender_version', 'minor'),
        estimated_vram_bytes=child.get('scene_memory', {}).get('estimated_vram_bytes'),
        threads=t['threads'], start=child['frames'][0], frames=child['frames'][1]-child['frames'][0]+1,
        size=child['size'], fps=child['fps'], audio=child['audio'], handles=handles,
        overlays=overlays, transitions=transitions, max_seconds=seconds,
        idle_timeout_s=t['idle_timeout_s'], crf='HIGH' if child['quality'] in ('final', 'cycles') else 'MEDIUM')
    spec['durable']=True
    # A process restart must not grant another full TTL to the same attempt.
    spec['deadline_at']=time.time()+seconds
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
        self.last_progress_wall=self.state.get('last_progress_at',self.state.get('attempt_started',self.state['started']))
        self.reason=None
        self.state.setdefault('attempt',uuid.uuid4().hex)
        self.current_name=self.state.get('initial_endpoint',self.state['target_name'])
        self.watch_done = threading.Event()

    def log(self,event,**fields):
        entry=dict(at=time.time(),event=event,job_id=self.state['id'],**fields)
        data=(json.dumps(entry,ensure_ascii=True)+'\n').encode()
        fd=os.open(self.path.parent/'supervisor.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        try:os.write(fd,data)
        finally:os.close(fd)

    def save(self, **updates):
        with self.lock:
            with open(self.path.parent/'state.lock','w') as state_lock:
                fcntl.flock(state_lock,fcntl.LOCK_EX)
                current=read_json(self.path,self.state)
                if current.get('attempt') and current['attempt']!=self.state['attempt']:
                    return  # A requested resume owns the next generation.
                previous={k:current.get(k) for k in ('status','stage','error','cleanup_pending')}
                current.update(updates);current['attempt']=self.state['attempt']
                self.state=current;write_json(self.path,current)
            changes={k:self.state.get(k) for k,v in previous.items() if self.state.get(k)!=v}
            if changes:self.log('transition',**changes)

    def progress(self):
        self.last_progress=time.monotonic();self.last_progress_wall=time.time()
        self.save(last_progress_at=self.last_progress_wall)

    def caps(self):
        q = self.state['quote']
        seconds = q['max_hours']*3600
        if q['max_budget_usd'] is not None and q['hourly_price_usd']:
            # Reserve 30 seconds for API shutdown. Includes provisioning and transfer.
            seconds = min(seconds, q['max_budget_usd']/q['hourly_price_usd']*3600)
        return max(0, seconds-30)

    def watchdog(self):
        while not self.watch_done.wait(.5):
            elapsed = time.time()-self.state.get('lease_started', self.state.get('attempt_started',self.state['started']))
            capped = elapsed >= self.caps()
            idle = max(time.monotonic()-self.last_progress,time.time()-self.last_progress_wall) >= self.t['idle_timeout_s']
            if (self.path.parent/'cancel').exists() or capped or idle:
                self.reason='Budget/time cap reached' if capped else 'Idle watchdog expired' if idle else 'Render cancelled'
                self.stop.set()
                # No SSH, provider request, or shared state lock is permitted here.
                # This independent record is visible even while the main RPC times out.
                write_json(self.path.parent/'watchdog.json',dict(at=time.time(),error=self.reason,
                    attempt=self.state['attempt'],last_progress_at=self.last_progress_wall))
                self.log('watchdog_expired',error=self.reason,last_progress_at=self.last_progress_wall)
                if self.child_proc and self.child_proc.poll() is None:
                    self.child_proc.terminate()
                return

    def check(self):
        if (self.path.parent/'cancel').exists():
            self.stop.set()
        if time.time()-self.state.get('lease_started', self.state.get('attempt_started',self.state['started'])) >= self.caps():
            self.reason='Budget/time cap reached'
            self.stop.set()
        if self.stop.is_set():
            raise InterruptedError(self.reason or self.state.get('error') or 'Render cancelled')

    @contextmanager
    def slot(self):
        if self.current_name!=self.state['target_name']:
            yield
            return
        directory=self.path.parents[2]/'slots';directory.mkdir(exist_ok=True)
        held=None
        try:
            while held is None:
                for i in range(self.t['max_parallel']):
                    candidate=open(directory/(digest(self.state['target_name'])+f'_{i}.lock'),'w')
                    try:fcntl.flock(candidate,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:candidate.close()
                    else:held=candidate;break
                if held is None:
                    self.check();self.save(status='queued',stage='waiting for target slot')
                    if self.t['kind']=='ssh':
                        try:SSH(self.t).rpc('ping')
                        except RemoteError:
                            if self.state.get('fallback'):self.current_name=self.state['fallback'];break
                            raise RemoteError('Target unreachable while waiting for slot; check WireGuard/VPN and SSH')
                    self.stop.wait(1)
            yield
        finally:
            if held:held.close()

    def endpoint(self,name):
        if name=='local':
            t=dict(self.t,kind='local',device='cpu',os='linux',host='local',
                blender=self.state['prepared']['blender'],remote_dir=str(self.path.parent/'local_worker'))
            return LocalWorker(t)
        if name==self.state['target_name']:return SSH(self.t)
        return SSH(self.state['fallback_target'])

    def unreachable(self, error):
        since=self.state.get('offline_since') or time.time()
        age=time.time()-since
        stage=('target offline since '+time.strftime('%H:%M:%S',time.localtime(since))
               if age>=self.t.get('offline_grace_s',150) else 'reconnecting (target unreachable)')
        self.save(stage=stage,offline_since=since,offline_target=self.current_name,
            reconnect_attempts=self.state.get('reconnect_attempts',0)+1)
        if age>=self.t.get('offline_grace_s',150) and self.state.get('fallback'):
            fallback=self.state['fallback']
            self.log('fallback_selected',source=self.current_name,destination=fallback,offline_since=since)
            self.current_name=fallback;self.progress()
            self.save(fallback_used=fallback,stage='fallback to '+fallback)
            return True
        return False

    def reachable(self):
        if self.state.get('offline_since') and self.current_name==self.state.get('offline_target',self.current_name):
            self.log('target_reconnected',target=self.current_name)
            self.save(offline_since=None,stage='rendering on '+self.current_name)
        now=time.time()
        updates=dict(last_seen_by_target={**self.state.get('last_seen_by_target',{}),self.current_name:now})
        if self.current_name==self.state['target_name']:
            updates.update(last_seen=now,last_seen_target=self.current_name)
        else:updates['fallback_last_seen']=now
        self.save(**updates)

    def operation(self, endpoint, operation):
        """Retry an unreachable endpoint, but fail promptly on an agent/disk error."""
        while True:
            self.check()
            try:
                result=operation()
                self.reachable()
                return result
            except RemoteError as exc:
                if 'max_parallel' in str(exc):
                    self.save(stage='waiting for target slot on '+self.current_name)
                    try:endpoint.rpc('ping')
                    except RemoteError:
                        if self.unreachable(exc):raise SwitchEndpoint()
                    self.stop.wait(1);continue
                if not isinstance(exc,Unreachable):
                    try:endpoint.rpc('ping')
                    except RemoteError:pass
                    else:raise exc
                if self.current_name==self.state.get('fallback'):
                    raise RemoteError('Fallback target unreachable: '+str(exc)) from None
                if self.unreachable(exc):raise SwitchEndpoint()
                self.stop.wait(.5)

    def request(self, endpoint, action, **params):
        return self.operation(endpoint,lambda:endpoint.rpc(action,**params))

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
                        self.save(billing=self.cloud.billing(data))
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
                ssh = LocalWorker(entry['connection']) if entry['connection'].get('kind')=='local' else SSH(entry['connection'])
                report = ssh.rpc('status', id=entry['id'])
                if report['status'] not in TERMINAL and report['status'] != 'missing':
                    ssh.rpc('cancel', id=entry['id'],attempt=entry.get('attempt'))
                    continue
                if report['status'] != 'missing':
                    if self.state['status']=='done':
                        ssh.rpc('cleanup', id=entry['id'],attempt=entry.get('attempt'),cache_bytes=self.t['cache_bytes'])
                    else:
                        self.state.setdefault('retained_remote_jobs',[]).append(entry)
                self.state.setdefault('cleanup_acknowledgements',[]).append(
                    dict(id=entry['id'],attempt=entry.get('attempt'),at=time.time(),status=report['status'],
                         frames_retained=self.state['status']!='done' and report['status']!='missing'))
                pending.remove(entry)
            except RemoteError:
                pass
        cloud_pending=bool(self.cloud and self.state.get('lease_started') and not self.state.get('lease_finished'))
        self.save(remote_jobs=pending, cleanup_pending=bool(pending) or cloud_pending,
                  cleanup_error=('SSH cleanup pending; target has not acknowledged cancellation/cleanup'
                      if pending else self.state.get('cleanup_error') if cloud_pending else None),
                  cleanup_acknowledgements=self.state.get('cleanup_acknowledgements',[]),
                  retained_remote_jobs=self.state.get('retained_remote_jobs',[]))
        return not pending

    def cost(self):
        elapsed = (self.state.get('lease_finished') or time.time())-self.state.get('lease_started', self.state['started'])
        self.save(elapsed_s=round(time.time()-self.state['started'], 1),
                  cost_so_far_usd=round(elapsed/3600*self.state['quote']['hourly_price_usd'], 6))

    def cleanup_local(self):
        if self.state['status']!='done':return
        for child in self.state['prepared']['children']:
            Path(child['blend']).unlink(missing_ok=True)
            if child.get('subs_dir'):
                shutil.rmtree(child['subs_dir'], ignore_errors=True)

    def learn(self, child, remote, log, name=None, target=None):
        times = remote.get('timing',{}).get('frame_seconds') or frame_times(log)
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
            key = digest([name or self.state['target_name'], render_profile(target or self.t), engine_key(child['quality'])])
            old = data.get(key, {})
            ratio = min(100, max(.001, measured/child['model_spf']))
            factor = math.sqrt(old['factor']*ratio) if old else ratio
            data[key] = dict(factor=factor, samples=old.get('samples', 0)+1,
                             measured_s_per_frame=measured, updated=time.time(),
                             vram_bytes=self.state.get('vram_bytes'), gpus=self.state.get('gpus', []))
            write_json(speed_path, data)
        self.save(learned_speed=data[key])

    def render_child(self, ssh, child, index):
        while True:
            endpoint=ssh if self.current_name==self.state['target_name'] else self.endpoint(self.current_name)
            try:return self.render_endpoint(endpoint,child,index)
            except SwitchEndpoint:continue

    def render_endpoint(self, ssh, child, index):
        name=self.current_name
        ident = self.state['id']+'_'+str(index)+('' if name==self.state['target_name'] else '_fallback')
        self.active_id = ident
        self.active_ssh = ssh
        completed = self.state.get('completed', [])
        if index in completed and Path(child['path']).is_file():
            return
        self.save(status='running',stage=f'scene {index+1}/{len(self.state["prepared"]["children"])} on {name}', active_remote_id=ident)
        files, spec = bundle(child, ssh.target, max(1, self.caps()-(time.time()-self.state.get('lease_started', self.state.get('attempt_started',self.state['started'])))))
        spool=self.path.parent/f'frames_{index}';spool.mkdir(exist_ok=True)
        files.update(seeds(spool))
        spec.update(endpoint=name,attempt=self.state['attempt'])
        probe = self.request(ssh,'probe', blender=ssh.target['blender'])
        system = probe.get('os', ssh.target.get('os', 'linux'))
        if system != 'windows' and not probe.get('rsync', True):
            raise RemoteError('Install rsync on the remote worker')
        try:
            policy=self.t if name==self.state['target_name'] else ssh.target
            warnings = check_version(child['blender_version'], probe['version'], policy.get('blender_version', 'minor'))
        except ValueError as exc:
            raise RemoteError(str(exc)) from None
        gpus = probe.get('gpus', [])
        vram = min((g['vram_bytes'] for g in gpus if g.get('vram_bytes')), default=None)
        if vram is None and ssh.target.get('vram_gb'):
            vram = int(ssh.target['vram_gb']*2**30)
        spec.update(gpus=gpus, vram_bytes=vram)
        if ssh.target['device'] != 'cpu':
            warnings += memory_warning(spec.get('estimated_vram_bytes'), vram)
        self.save(warnings=list(dict.fromkeys(self.state.get('warnings', [])+warnings)),
            target_os=system, blender_remote_version=probe['version'], gpus=gpus, vram_bytes=vram,
            vram_source='nvidia-smi' if gpus else 'target config' if vram else 'unavailable',
            estimated_vram_bytes=spec.get('estimated_vram_bytes'))
        self.check()
        mapping = self.operation(ssh,lambda:ssh.upload(files, self.path.parents[2]/'blobs'))
        self.check()
        entries = self.state.get('remote_jobs', [])
        if not any(e['id'] == ident and e.get('attempt')==self.state['attempt'] for e in entries):
            self.save(remote_jobs=entries+[dict(id=ident, connection=ssh.target,attempt=self.state['attempt'])], cleanup_pending=True)
        parallel=ssh.target['max_parallel']
        remote=self.request(ssh,'start', id=ident, files=mapping, spec=spec, max_parallel=parallel)
        if self.state.get('resuming'):
            remote=self.request(ssh,'resume',id=ident,files=mapping,spec=spec,max_parallel=parallel)
        last = -1
        restarts=0
        while True:
            self.check()
            remote=self.request(ssh,'status',id=ident)
            self.cost()
            if remote.get('durable'):
                index_data,changed=self.operation(ssh,lambda:mirror(ssh,ident,spool,self.progress))
                self.save(frame_sources=provenance(index_data),
                    scene_frame_sources={**self.state.get('scene_frame_sources',{}),str(index):provenance(index_data)},
                    checkpoint_frames=sum(e.get('channel')=='main' for e in index_data['files'].values()))
                count=len(index_data['files'])
            else:
                try:count=int(remote.get('progress','0/1').split('/')[0])
                except ValueError:count=0
            if count>last:
                last=count;self.progress()
            if remote.get('status')=='missing' or (remote.get('status')=='failed' and remote.get('recoverable')):
                if restarts>=3:raise RemoteError('Remote worker repeatedly died; resume_job can retry later')
                restarts+=1;self.log('worker_restart',target=name,number=restarts,frames=count)
                self.save(worker_restarts=self.state.get('worker_restarts',0)+1)
                if remote['status']=='missing':
                    files.update(seeds(spool))
                    mapping=self.operation(ssh,lambda:ssh.upload(files,self.path.parents[2]/'blobs'))
                    self.request(ssh,'start',id=ident,files=mapping,spec=spec,max_parallel=parallel)
                else:self.request(ssh,'resume',id=ident,files=mapping,spec=spec,max_parallel=parallel)
                continue
            progress = remote.get('progress', '0/1')
            eta = max(0, self.state['quote']['estimated_runtime_s']-remote.get('elapsed_s', 0))
            if name=='local':
                # Snapshot estimates already use the normal local calibration.
                factor=child.get('estimate',{}).get('seconds_per_frame',child['model_spf'])
                done=int(remote.get('progress','0/1').split('/')[0])
                eta=max(0,spec['frames']-done)*factor
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
            self.save(warnings=list(dict.fromkeys(self.state.get('warnings', [])+remote.get('warnings', []))))
            if remote['status'] in TERMINAL:
                break
            self.stop.wait(.5)
        local_log = self.path.parent/f'scene{index}.log'
        self.operation(ssh,lambda:ssh.download(ident, 'render.log', local_log))
        if remote['status'] != 'done':
            raise RemoteError(remote.get('error', 'Remote worker failed'))
        dest = Path(child['path'])
        part = dest.with_suffix('.remote.part.mp4')
        # Retried downloads retain partial bytes and never touch the delivered output.
        self.operation(ssh,lambda:ssh.download(ident, 'result.mp4', part))
        if file_hash(part) != remote['sha256']:
            raise RemoteError('Downloaded movie checksum mismatch')
        checked = verify(part, spec['frames'], child['size'], child['audio'])
        os.replace(part, dest)
        if name=='local':self.learn_local(child,remote)
        else:self.learn(child, remote, local_log.read_text(errors='replace'),name,ssh.target)
        for scene in self.state.get('scenes', []):
            if scene.get('job_id') == child['id']:
                scene['status'] = 'done'
        self.save(completed=completed+[index], verified=checked,scenes=self.state.get('scenes',[]))
        try:
            ssh.rpc('cleanup', id=ident,attempt=self.state['attempt'],cache_bytes=self.t['cache_bytes'])
            remaining = [e for e in self.state.get('remote_jobs', []) if e['id'] != ident]
            acknowledgements=self.state.get('cleanup_acknowledgements',[])+[dict(id=ident,
                attempt=self.state['attempt'],at=time.time(),status='done',frames_retained=False)]
            self.save(remote_jobs=remaining, cleanup_pending=bool(remaining) or bool(self.cloud),
                      cleanup_acknowledgements=acknowledgements)
        except RemoteError:
            pass  # Durable finally/restart cleanup retries; the verified clip is kept.
        self.active_id = None

    def learn_local(self, child, remote):
        measured=remote.get('timing',{}).get('frame_seconds',[])
        if not measured:return
        value=statistics.median(measured[1:] or measured)
        predicted=child.get('model_spf')
        if not predicted:return
        path=Path(os.environ.get('CHAR3D_RENDER_CALIB') or Path.home()/'.cache/char3d/render_speed.json')
        data=read_json(path,{})
        key=engine_key(child['quality']);old=data.get(key,{})
        ratio=max(.01,min(100,value/predicted))
        factor=math.sqrt(old['factor']*ratio) if old else ratio
        data[key]=dict(factor=factor,samples=old.get('samples',0)+1,
            updated=time.strftime('%Y-%m-%d %H:%M:%S'),last=dict(source='render',
            measured_s_per_frame=value,model_s_per_frame=predicted,quality=child['quality']))
        write_json(path,data)
        self.save(learned_speed=dict(engine=key,factor=factor,measured_s_per_frame=value,source='local fallback'))

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
            self.cleanup_cloud()
            self.cleanup_remote()
            self.cleanup_local()
            return
        self.save(status='running',cleanup_protocol=2)
        watcher = threading.Thread(target=self.watchdog, daemon=True)
        watcher.start()
        try:
            with self.slot():
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
        except InterruptedError as exc:
            self.save(status='cancelled',error=str(exc),terminal_at=time.time())
        except Exception as exc:
            # Provider exceptions are sanitized by Cloud; unexpected failures have no repr/traceback.
            self.save(status='cancelled' if self.stop.is_set() else 'failed',terminal_at=time.time(),
                error=(self.reason or 'Render cancelled') if self.stop.is_set() else str(exc) if isinstance(exc, RemoteError) else
                      'Remote supervisor failed ('+type(exc).__name__+'); credentials redacted')
        finally:
            self.watch_done.set()
            watcher.join(timeout=1)
            if self.child_proc and self.child_proc.poll() is None:
                self.child_proc.terminate()
                try:
                    self.child_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.child_proc.kill()
                    self.child_proc.wait()
            self.cleanup_cloud()
            self.cleanup_remote()
            self.cost()
            self.cleanup_local()


def main(path):
    with open(Path(path).parent/'worker.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        while True:
            supervisor = Supervisor(path)
            signal.signal(signal.SIGTERM, lambda *args: supervisor.stop.set())
            signal.signal(signal.SIGINT, lambda *args: supervisor.stop.set())
            supervisor.run()
            state=read_json(path)
            if state['status'] not in TERMINAL:continue
            if not state.get('cleanup_pending'):break
            time.sleep(2)


if __name__ == '__main__':
    main(sys.argv[1])
