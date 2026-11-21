"""Offline regression tests for bounded I/O, truthful cleanup and durable rendering."""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from providers.remote.config import RemoteError,write_json,read_json,render_profile,digest
from providers.remote.jobs import RemoteRenders
from providers.remote.supervisor import Supervisor,verify,bundle
from providers.remote.transport import SSH,Unreachable
from providers.remote.process import run_bounded
from providers.remote.local import LocalWorker
from engine.remote_frames import read_index
from engine import remote_agent


def reject(fn,fragment):
    try:fn()
    except RemoteError as exc:assert fragment in str(exc),str(exc)
    else:raise AssertionError('Expected rejection')


def basic(root):
    t=dict(kind='ssh',host='fake',os='linux',device='cpu',remote_dir=str(root/'worker'),
        blender='/blender',max_parallel=1,threads=2,max_hours=1,idle_timeout_s=.1,
        startup_seconds=.1,cache_bytes=2**20,offline_grace_s=.1)
    state=dict(id='remote_robust',status='running',kind='video',target_name='fake',target=t,
        attempt='attempt1',started=time.time(),attempt_started=time.time(),prepared={'job':{},'children':[]},
        quote={'max_hours':1,'max_budget_usd':None,'hourly_price_usd':0},cleanup_pending=True,
        remote_jobs=[{'id':'remote_robust_0','connection':t,'attempt':'attempt1'}])
    p=root/'jobs/remote_robust/state.json';write_json(p,state)
    return t,state,p


def units():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        # A ProxyCommand child inherits the output pipe and ignores SIGTERM. The
        # entire owned group must die, rather than hanging during timeout drainage.
        pidfile=root/'grandchild'
        code=('import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c",'
              '"import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"]); '
              f'open({str(pidfile)!r},"w").write(str(p.pid)); time.sleep(60)')
        before=time.monotonic()
        try:run_bounded([sys.executable,'-c',code],timeout=.2)
        except subprocess.TimeoutExpired:pass
        else:raise AssertionError('Hung SSH did not time out')
        assert time.monotonic()-before<2
        if pidfile.exists():
            stat=Path('/proc')/pidfile.read_text()/'stat'
            assert not stat.exists() or stat.read_text().split()[2]=='Z'
        ssh=SSH(dict(host='fake',jump_host='reyhan',remote_dir='/tmp/test',os='linux',
            connect_timeout_s=3,server_alive_interval_s=2,server_alive_count_max=2,rpc_timeout_s=.2))
        proxy=next(s for s in ssh.args if s.startswith('ProxyCommand='))
        assert all(v in proxy for v in ('-F ','BatchMode=yes','StrictHostKeyChecking=yes',
                                       'ConnectTimeout=3','ServerAliveInterval=2','ServerAliveCountMax=2'))
        with patch('providers.remote.transport.run_bounded',side_effect=subprocess.TimeoutExpired('ssh',.2)) as run:
            reject(lambda:ssh.rpc('ping'),'timed out')
            assert run.call_count==1 and run.call_args.kwargs['timeout']<=.2
        old=dict(kind='ssh',host='fake',device='cpu')
        assert digest(['fake',old])==digest(['fake',render_profile(dict(old,rpc_timeout_s=1,offline_grace_s=150))])
        print('robust: hung SSH/ProxyCommand process group bounded; no multiplied retry deadline')

        t,state,path=basic(root)
        supervisor=Supervisor(path)
        supervisor.last_progress=time.monotonic()-.2
        supervisor.last_progress_wall=time.time()-.2
        endpoint=Mock();supervisor.active_ssh=endpoint;supervisor.active_id='owned'
        before=time.monotonic()
        with supervisor.lock:
            thread=threading.Thread(target=supervisor.watchdog)
            thread.start();thread.join(1.5)
            assert not thread.is_alive(), 'Watchdog blocked on state lock or cancel RPC'
        assert time.monotonic()-before<1.5 and endpoint.rpc.call_count==0
        fired=read_json(path.parent/'watchdog.json')
        assert fired['error']=='Idle watchdog expired' and fired['at']>=before+time.time()-time.monotonic()-2
        class Engine:workspace=str(root)
        manager=RemoteRenders(SimpleNamespace(workspace=str(root.parent)))
        # Manager report/wait must not turn a terminal timeout into hours of cleanup wait.
        manager.root=root
        with patch.object(manager,'_launch'):
            report=manager.wait('remote_robust')
        assert report['status']=='cancelled' and report['cleanup_pending'] and report['watchdog_at']
        with patch('providers.remote.supervisor.SSH') as fake:
            fake.return_value.rpc.side_effect=RemoteError('offline')
            assert not supervisor.cleanup_remote()
        assert read_json(path)['cleanup_pending'] and read_json(path)['remote_jobs']
        # Only a successful response proving absence can clear pending cleanup.
        with patch('providers.remote.supervisor.SSH') as fake:
            fake.return_value.rpc.return_value={'status':'missing'}
            assert supervisor.cleanup_remote()
        assert read_json(path)['cleanup_acknowledgements']
        legacy=read_json(path)
        legacy.update(status='cancelled',remote_jobs=[],cleanup_pending=False,
            cleanup_acknowledgements=[],active_remote_id='remote_robust_0')
        write_json(path,legacy)
        with patch.object(manager,'_launch'):
            assert manager.report('remote_robust')['cleanup_pending'], 'Legacy false was mistaken for an acknowledgement'
        print('robust: watchdog fires independently of locks/I/O; wait returns terminal with pending cleanup')

        t,state,path=basic(root/'suspend')
        t['idle_timeout_s']=900;state['target']=t;write_json(path,state)
        supervisor=Supervisor(path);supervisor.last_progress_wall=time.time()-1000
        supervisor.last_progress=time.monotonic()
        thread=threading.Thread(target=supervisor.watchdog);thread.start();thread.join(1.5)
        assert not thread.is_alive() and supervisor.stop.is_set()
        print('robust: wall/monotonic idle deadline also catches controller sleep/restart')

        t,state,path=basic(root/'reconnect')
        state['target']['idle_timeout_s']=10;write_json(path,state)
        supervisor=Supervisor(path);last_progress=supervisor.last_progress_wall
        endpoint=Mock()
        endpoint.rpc.side_effect=[Unreachable('dropped'),Unreachable('dropped'),{'status':'running'}]
        assert supervisor.request(endpoint,'status')['status']=='running'
        assert supervisor.last_progress_wall==last_progress, 'Reachability must not disguise a slow/stuck frame'
        events=[json.loads(line) for line in (path.parent/'supervisor.log').read_text().splitlines()]
        assert any('target offline since' in e.get('stage','') for e in events)
        assert any(e['event']=='target_reconnected' for e in events)
        assert read_json(path)['offline_since'] is None and read_json(path)['last_seen']
        primary_seen=supervisor.state['last_seen'];supervisor.current_name='local';supervisor.reachable()
        assert supervisor.state['last_seen']==primary_seen and supervisor.state['fallback_last_seen']
        supervisor.current_name='fake'
        endpoint.rpc.side_effect=[RemoteError('disk full'),{'reachable':True}]
        reject(lambda:supervisor.request(endpoint,'start'),'disk full')
        assert endpoint.rpc.call_count==5, 'Agent errors must not masquerade as offline retries'
        print('robust: offline/reconnect transitions logged; healthy slow frame does not reset idle deadline')

        # Restarted remote workers retain the original absolute deadline, even
        # though their process-local monotonic clock starts fresh.
        directory=root/'expired_worker';directory.mkdir()
        write_json(directory/'spec.json',dict(blender='/fake/blender',threads=1,frames=1,start=1,
            max_seconds=3600,deadline_at=time.time()-1,idle_timeout_s=900,durable=True))
        class Process:
            pid=999999;returncode=None
            def poll(self):return self.returncode
            def terminate(self):self.returncode=-15
            def kill(self):self.returncode=-9
            def wait(self,**kwargs):return self.returncode
        process=Process();original=Path.cwd()
        try:
            with patch.object(remote_agent.subprocess,'Popen',return_value=process), \
                 patch.object(remote_agent,'pid_record',return_value={'pid':999999}), \
                 patch.object(remote_agent,'WINDOWS',False):
                remote_agent.run(str(directory))
        finally:os.chdir(original)
        assert 'time/budget cap' in read_json(directory/'status.json')['error']
        assert process.returncode==-15
        assert not read_json(directory/'status.json').get('recoverable')
        process.returncode=0xC0000005  # Windows access-violation exit, not a POSIX signal.
        try:
            with patch.object(remote_agent.subprocess,'Popen',return_value=process), \
                 patch.object(remote_agent,'pid_record',return_value={'pid':999999}):
                remote_agent.run(str(directory))
        finally:os.chdir(original)
        assert read_json(directory/'status.json')['recoverable']
        print('robust: remote worker restart cannot extend the original attempt TTL')

        win=root/'windows_attempts';jobdir=win/'jobs/owned';jobdir.mkdir(parents=True)
        write_json(jobdir/'spec.json',{'attempt':'new-generation'})
        write_json(jobdir/'worker_pid.json',{'pid':123,'created':'verified-token'})
        with patch.object(remote_agent,'WINDOWS',True),patch.object(remote_agent,'stop_tree') as stop_tree:
            stale=dict(root=str(win),id='owned',attempt='old-generation')
            assert remote_agent.rpc(dict(stale,action='cancel'))['superseded']
            assert remote_agent.rpc(dict(stale,action='cleanup'))['superseded']
            assert not stop_tree.called and not (jobdir/'cancel').exists()
            assert remote_agent.rpc(dict(stale,attempt='new-generation',action='cancel'))['acknowledged']
            stop_tree.assert_called_once_with({'pid':123,'created':'verified-token'},jobdir)
        print('robust: stale cleanup cannot kill the resumed Windows job generation')

        cfg=root/'config';cfg.mkdir()
        write_json(cfg/'targets.json',{'fake':dict(kind='ssh',host='fake',os='linux',remote_dir='/tmp/fake'),
            'other':dict(kind='ssh',host='other',os='linux',remote_dir='/tmp/other'),
            'paid':dict(kind='runpod',gpu_type='fake',image='fake',public_key='/tmp/key.pub',
                        max_budget_usd=1,max_hourly_usd=1,device='cuda')})
        engine=SimpleNamespace(workspace=str(root/'preflight'),call=Mock())
        with patch.dict(os.environ,{'CHAR3D_REMOTE_CONFIG':str(cfg)}):
            manager=RemoteRenders(engine)
            with patch.object(manager,'_consent',return_value=True),patch('providers.remote.jobs.SSH') as fake:
                fake.return_value.rpc.side_effect=RemoteError('offline')
                reject(lambda:manager.start('video','fake',{}),'preflight')
                assert not engine.call.called
                reject(lambda:manager.start('video','fake',{},fallback='paid'),'forbidden')
            with patch.object(manager,'_consent',side_effect=lambda name,*a:name=='fake'):
                answer=manager.start('video','fake',{},fallback='other')
                assert answer['status']=='consent_required' and answer['target']=='other'
        print('robust: dead preflight fails before snapshots/queue; unpaid fallback and upload consent enforced')

        # A queued job rechecks health rather than waiting behind a dead slot owner.
        t,state,path=basic(root/'queue');state['target']['idle_timeout_s']=5;write_json(path,state)
        a=Supervisor(path);b=Supervisor(path)
        with a.slot(),patch('providers.remote.supervisor.SSH') as fake:
            fake.return_value.rpc.side_effect=RemoteError('offline')
            def waiting():
                with b.slot():pass
            reject(waiting,'unreachable')
        print('robust: queued/offline target fails fast with max_parallel=1')
    print('REMOTE ROBUST UNIT OK')


async def integration():
    os.environ['CHAR3D_PORT']='9969';os.environ['CHAR3D_WORKSPACE']=str(ROOT/'output')
    os.environ['CHAR3D_ALLOW_PYTHON']='1'
    os.environ['CHAR3D_RENDER_CALIB']=str(ROOT/'output/robust_local_speed.json')
    from mcp_server import server as api
    import wave,math,struct
    await api.scene_info();await api.new_scene(frame_end=6)
    await api.add_primitive(kind='cube',name='DurableCube',location=[0,0,.5])
    await api.camera_shot(subject=['DurableCube'],shot='full',start_frame=1,end_frame=3)
    await api.camera_shot(subject=['DurableCube'],shot='medium',start_frame=4,end_frame=6)
    await api.set_lighting(preset='studio',subject=['DurableCube'])
    await api.add_transition(at_frame=4,kind='crossfade',duration_s=2/24)
    await api.add_subtitles(lines=[{'text':'Durable frames','start':0,'end':.25}])
    await api.add_title(text='Resume',duration_s=.1,style='corner')
    wav=ROOT/'output/imports/robust.wav';wav.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(wav),'wb') as out:
        out.setparams((1,2,24000,0,'NONE','not compressed'))
        out.writeframes(b''.join(struct.pack('<h',int(4000*math.sin(i*.1)))for i in range(6000)))
    await api.add_audio(path=str(wav))
    await api.render_preview(camera='scene',width=160,height=90)
    prepared=[]
    for label in ('fallback','death','resume'):
        prepared.append(await api.run('prepare_remote_render',kind='video',params=dict(
            path=f'robust_{label}.mp4',quality='draft',width=320,height=180,frame_start=1,frame_end=6)))
    await api.engine_shutdown()
    results=[]
    try:
        base=ROOT/'output/robust_integration';base.mkdir(exist_ok=True)
        for label,job in zip(('fallback','death','resume'),prepared):
            directory=Path(tempfile.mkdtemp(prefix=label+'_',dir=base))
            t=dict(kind='ssh',host='fake',os='linux',remote_dir=str(directory/'worker'),
                blender=job['blender'],device='cpu',max_parallel=1,threads=2,max_hours=1,
                idle_timeout_s=60,cache_bytes=2**30,offline_grace_s=.1)
            ident='remote_robust_'+label
            path=directory/'jobs'/ident/'state.json'
            state=dict(id=ident,status='queued',kind='video',target_name='fake',target=t,
                attempt='generation1',started=time.time(),attempt_started=time.time(),last_progress_at=time.time(),
                prepared=job,path=job['job']['path'],quality='draft',scenes=[],
                quote={'max_hours':1,'max_budget_usd':None,'hourly_price_usd':0,'estimated_runtime_s':20},
                fallback='local' if label=='fallback' else None,cleanup_pending=False)
            write_json(path,state)
            _,spec=bundle(job['children'][0],t,2)
            assert time.time()<spec['deadline_at']<=time.time()+2
            online=[True];triggered=[False];original_records={}
            class Endpoint(LocalWorker):
                def rpc(self,action,**kwargs):
                    if not online[0]:
                        if action=='status':
                            try:run_bounded([sys.executable,'-c','import time; time.sleep(60)'],timeout=.05)
                            except subprocess.TimeoutExpired:raise Unreachable('injected hung SSH mid-render') from None
                        raise Unreachable('injected link drop')
                    return super().rpc(action,**kwargs)
                def download(self,remote_id,name,dest):
                    if not online[0]:raise RemoteError('injected link drop')
                    super().download(remote_id,name,dest)
                    if name.startswith('frames/main/') and not triggered[0]:
                        spool=path.parent/'frames_0'
                        if len(read_index(spool)['files'])>=1:
                            triggered[0]=True
                            original_records.update(copy.deepcopy(read_index(spool)['files']))
                            if label=='death':
                                remote_dir=Path(t['remote_dir'])/'jobs'/remote_id
                                remote_agent.stop_tree(read_json(remote_dir/'worker_pid.json'),remote_dir)
                            elif label=='resume':(path.parent/'cancel').touch()
                            else:
                                super().rpc('cancel',id=remote_id,attempt='generation1')
                                until=time.monotonic()+15
                                while super().rpc('status',id=remote_id)['status'] not in ('done','failed','cancelled'):
                                    assert time.monotonic()<until;time.sleep(.1)
                                online[0]=False
            with patch('providers.remote.supervisor.SSH',side_effect=lambda config:Endpoint(config)):
                supervisor=Supervisor(path);await asyncio.to_thread(supervisor.run)
                state=read_json(path)
                assert triggered[0], 'Failure injection did not run'
                if label=='fallback':
                    assert state['status']=='done' and state['cleanup_pending'],state
                    assert 'fake' in state['frame_sources'] and 'local' in state['frame_sources'],state
                    online[0]=True
                    until=time.monotonic()+15
                    while not Supervisor(path).cleanup_remote():
                        assert time.monotonic()<until;await asyncio.sleep(.1)
                    assert not read_json(path)['cleanup_pending']
                elif label=='death':
                    assert state['status']=='done' and state['worker_restarts']>=1,state
                else:
                    assert state['status']=='cancelled',state
                    online[0]=True
                    until=time.monotonic()+15
                    while not Supervisor(path).cleanup_remote():
                        assert time.monotonic()<until;await asyncio.sleep(.1)
                    manager=RemoteRenders(SimpleNamespace(workspace=str(directory)))
                    manager.root=directory
                    with patch.object(manager,'_launch'):
                        manager.resume_job(ident)
                    supervisor=Supervisor(path);await asyncio.to_thread(supervisor.run)
                    state=read_json(path)
                    assert state['status']=='done',state
                assert state['verified']['frames']==6 and state['verified']['audio']
                for name,entry in original_records.items():
                    assert read_index(path.parent/'frames_0')['files'][name]==entry, 'Completed frame was rendered again'
                assert Path(job['job']['subtitles']['srt']).exists() and job['job']['credits']
                verify(state['path'],6,[160,90],True)
                results.append(dict(case=label,status=state['status'],sources=state.get('frame_sources'),
                                    restarts=state.get('worker_restarts'),verified=state['verified']))
                print('robust integration:',label,results[-1],flush=True)
        assert Path(os.environ['CHAR3D_RENDER_CALIB']).exists(), 'Local fallback did not learn local speed'
        write_json(ROOT/'output/remote_robust_integration.json',results)
        print('REMOTE ROBUST INTEGRATION OK: partial frames + local fallback MP4/AAC/handles; worker restart; cancel/resume',flush=True)
    finally:
        await api.engine_shutdown()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--integration',action='store_true')
    args=parser.parse_args()
    if args.integration:asyncio.run(integration())
    else:units()
