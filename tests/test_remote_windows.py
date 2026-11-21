"""Windows SSH/SCP command layer and native lifecycle contracts, without a PC/account."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import remote_agent as agent
from engine.render_compat import check_version, memory_warning
from providers.remote.config import RemoteError, targets, write_json, read_json
from providers.remote.supervisor import Supervisor
from providers.remote.transport import SSH, file_hash, powershell_command
from remote_loopback import ps_argv


def reject(call, fragment=''):
    try:
        call()
    except (RemoteError, ValueError, RuntimeError) as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError('Expected rejection')


def transport_checks(root):
    root.mkdir(parents=True)
    t=dict(kind='ssh',host='pc',port=22,user='reyhan febrizio r',jump_host='reyhan',os='windows',
        shell='cmd',remote_dir=r'D:\char3d\Remote render',
        python="C:\\Users\\Reyhan Febrizio R\\O'Brien ü\\Python312\\python.exe",
        blender=r'C:\Users\Reyhan Febrizio R\Blender\blender.exe')
    remote=root/'Windows directory ü'
    calls=[]
    corrupt=False
    shell='cmd'

    def path(value):
        value=value.replace('\\','/')
        return remote/value.removeprefix('D:/char3d/Remote render').lstrip('/')

    def run(argv, **kwargs):
        calls.append((argv,kwargs))
        assert argv[1]=='-F' and 'BatchMode=yes' in argv and 'StrictHostKeyChecking=yes' in argv
        if argv[0]=='ssh':
            command=argv[-1]
            if command=='ver':
                return SimpleNamespace(returncode=0 if shell=='cmd' else 1,stdout='Microsoft Windows\r\n' if shell=='cmd' else '',stderr='')
            assert command.startswith('powershell -NoProfile -NonInteractive -EncodedCommand ')
            script=base64.b64decode(command.split()[-1]).decode('utf-16le')
            if script=='[Console]::Write($env:OS)':
                return SimpleNamespace(returncode=0,stdout='Windows_NT',stderr='')
            assert len(command)<8191 and kwargs['encoding']=='utf-8'
            args=ps_argv(command)
            assert args[0]==t['python'] and args[1:3]==['-X','utf8'] and args[-1]=='rpc'
            assert 'reyhan febrizio r'==argv[argv.index('-l')+1]
            req=json.loads(kwargs['input'])
            assert base64.b64decode(req.pop('_agent')).decode('utf-8')==Path(agent.__file__).read_text()
            req['root']=str(path(req['root']))
            try:
                result=agent.rpc(req)
                return SimpleNamespace(returncode=0,stdout='\ufeff'+json.dumps(result,ensure_ascii=False)+'\r\n',stderr='')
            except Exception as exc:
                return SimpleNamespace(returncode=1,stdout=json.dumps({'rpc_error':str(exc)}),stderr='')
        assert argv[0]=='scp' and '-O' not in argv and '-P' in argv
        assert 'User="reyhan febrizio r"' in argv and any('ProxyCommand=ssh -F ' in a for a in argv)
        args=argv[argv.index('--')+1:]
        def local(s):
            return path(s.split(':',1)[1]) if s.startswith('pc:') else Path(s)
        dest=local(args[-1]); folder=args[-1].endswith('/')
        if folder: dest.mkdir(parents=True,exist_ok=True)
        for source in args[:-1]:
            source=local(source); out=dest/source.name if folder else dest
            out.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,out)
            if corrupt: out.write_bytes(b'corrupt')
        return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')

    with patch('providers.remote.transport.run_bounded',side_effect=run):
        ssh=SSH(t)
        files={}
        for name in ('scene.blend','textures/é.png'):
            source=root/Path(name).name
            source.write_bytes(name.encode()*100)
            files[name]=str(source)
        mapping=ssh.upload(files,root/'cache')
        assert len([c for c,_ in calls if c[0]=='scp'])==1
        assert all(file_hash(remote/'blobs'/h)==h for h in mapping.values())
        ssh.upload(files,root/'cache')
        assert len([c for c,_ in calls if c[0]=='scp'])==1, 'Cached blob uploaded again'
        h=next(iter(mapping.values()))
        (remote/'blobs'/h).write_bytes(b'broken cache')
        ssh.upload(files,root/'cache')
        assert file_hash(remote/'blobs'/h)==h
        assert len([c for c,_ in calls if c[0]=='scp'])==2
        movie=remote/'jobs/job/result.mp4'
        movie.parent.mkdir(parents=True)
        movie.write_bytes('verified later by PyAV ü'.encode())
        dest=root/'download with spaces ü.mp4'
        ssh.download('job','result.mp4',dest)
        assert dest.read_bytes()==movie.read_bytes()
        source=root/'bad.png'; source.write_bytes(b'new blob')
        corrupt=True
        reject(lambda:ssh.upload({'bad.png':str(source)},root/'cache'),'SHA-256')
        assert not (remote/'blobs'/file_hash(source)).exists() and not list((remote/'uploads').iterdir())
        corrupt=False
        for shell in ('cmd','powershell'):
            detected=SSH(dict(t,os='auto'))
            assert detected.detect_os()=='windows'
        script="[Console]::Write('é 中文 $x; %TEMP%')"
        assert base64.b64decode(powershell_command(script).split()[-1]).decode('utf-16le')==script
    print('windows: cmd/PowerShell detection, UTF-16LE quoting, spaces/UTF-8, SCP cache/hash/download OK')


def lifecycle_checks(root):
    identities={100:{'pid':100,'created':'1000'},101:{'pid':101,'created':'1010'}}
    taskkills=[]
    lock_calls=[]
    msvcrt=SimpleNamespace(LK_NBLCK=1,LK_UNLCK=2,locking=lambda *args:lock_calls.append(args))
    fake=SimpleNamespace(pid=100)
    agent.SOURCE=Path(agent.__file__).read_text(encoding='utf-8')
    def run(command,**kwargs):
        assert command[:1]==['taskkill.exe'] and command[-2:]==['/T','/F'] and '/IM' not in command
        taskkills.append(command)
        return SimpleNamespace(returncode=0)
    with patch.object(agent,'WINDOWS',True), patch.dict(sys.modules,{'msvcrt':msvcrt}), \
         patch.object(agent,'process_token',side_effect=lambda pid:identities.get(pid)), \
         patch.object(agent.subprocess,'run',side_effect=run), \
         patch.object(agent.subprocess,'Popen',return_value=fake) as spawn:
        blob=root/'blobs';blob.mkdir(parents=True)
        source=blob/('0'*64);source.write_bytes(b'dummy')
        h=agent.hash_file(source);source.rename(blob/h)
        req=dict(root=str(root),action='start',id='windows_job',files={'scene.blend':h},spec={},max_parallel=1)
        with patch.object(agent.os,'link',side_effect=PermissionError('No hardlinks')):
            agent.rpc(req)
        agent.prune(root,1)
        assert (blob/h).exists(), 'Active copied assets were evicted from the cache'
        assert spawn.call_args.kwargs['creationflags']==0x01000208 and 'start_new_session' not in spawn.call_args.kwargs
        directory=root/'jobs/windows_job'
        assert read_json(directory/'pid.json')==identities[100] and lock_calls
        agent.rpc(req)
        assert spawn.call_count==1, 'Reattach launched another supervisor'
        write_json(directory/'worker_pid.json',identities[101])
        agent.rpc(dict(root=str(root),action='cancel',id='windows_job'))
        assert taskkills[-1]==['taskkill.exe','/PID','101','/T','/F']
        taskkills.clear()
        identities[101]={'pid':101,'created':'reused'}
        agent.stop_tree({'pid':101,'created':'1010'},directory)
        assert not taskkills, 'Unrelated reused PID was killed'
        identities.pop(100)
        state=agent.rpc(dict(root=str(root),action='status',id='windows_job'))
        assert state['status']=='failed'
        agent.rpc(dict(root=str(root),action='cleanup',id='windows_job',cache_bytes=1))
        assert not directory.exists()
        (blob/h).write_bytes(b'dummy')
        with patch.object(agent.subprocess,'Popen',side_effect=OSError('fake detach failure')):
            try: agent.rpc(dict(req,id='broken_start'))
            except OSError: pass
            else: raise AssertionError('Spawn failure accepted')
        assert read_json(root/'jobs/broken_start/status.json')['status']=='failed'
        agent.rpc(dict(root=str(root),action='cleanup',id='broken_start',cache_bytes=1))
        assert not (root/'jobs/broken_start').exists()

    # Run the real agent loop with fake Win32 child processes. TTL, idle, cancel,
    # spawn failure and worker failure must stop only this worker and write terminal state.
    original=Path.cwd()
    for mode in ('ttl','idle','cancel','worker_fail','spawn_fail','done'):
        directory=root/mode;directory.mkdir()
        spec=dict(blender=r'C:\Program Files\Blender\blender.exe',threads=4,frames=4,start=1,
                  max_seconds=.1 if mode=='ttl' else 100,idle_timeout_s=.1 if mode=='idle' else 100,
                  audio=False,size=[32,32],fps=24,overlays=[],transitions=[])
        write_json(directory/'spec.json',spec)
        if mode=='cancel': (directory/'cancel').touch()
        class Proc:
            pid=101
            returncode=1 if mode=='worker_fail' else 0 if mode=='done' else None
            def poll(self): return self.returncode
            def wait(self,**kwargs): return self.returncode
            def terminate(self): self.returncode=-9
            def kill(self): self.returncode=-9
        proc=Proc();clock=[0.]
        def now(): clock[0]+=1.;return clock[0]
        def launch(command,**kwargs):
            assert kwargs['creationflags']==0x08000200 and 'start_new_session' not in kwargs
            if mode=='spawn_fail': raise OSError('fake CreateProcess failure')
            if mode=='done':
                Path('raw_0001-0004.mp4').write_bytes(b'fake output; transport verification tested separately')
            return proc
        def kill(command,**kwargs):
            assert command==['taskkill.exe','/PID','101','/T','/F']
            proc.returncode=-9
            return SimpleNamespace(returncode=0)
        try:
            with patch.object(agent,'WINDOWS',True), patch.object(agent,'process_token',return_value={'pid':101,'created':'x'}), \
                 patch.object(agent.subprocess,'Popen',side_effect=launch),patch.object(agent.subprocess,'run',side_effect=kill), \
                 patch.object(agent.time,'monotonic',side_effect=now),patch.object(agent.time,'sleep'):
                agent.run(str(directory))
        finally:
            os.chdir(original)
        state=read_json(directory/'status.json')
        assert state['status']==('done' if mode=='done' else 'cancelled' if mode=='cancel' else 'failed'), state
        if mode in ('ttl','idle','cancel'): assert proc.returncode==-9
    print('windows: detach, lock, PID identity/reuse, worker-tree cancel, TTL/idle/failure cleanup OK')


def policy_checks(root):
    assert check_version([5,2,4],'Blender 5.2.4 LTS','exact')==[]
    assert check_version([5,2,4],'Blender 5.2.3 LTS')[0].startswith('Blender patch differs')
    reject(lambda:check_version([5,2,4],'Blender 5.2.3','exact'),'mismatch')
    reject(lambda:check_version([5,2,4],'Blender 5.3.0'),'mismatch')
    reject(lambda:check_version([5,2,4],'Blender 4.2.4'),'mismatch')
    assert 'lower resolution' in memory_warning(6*2**30,4*2**30)[0]
    assert memory_warning(2*2**30,4*2**30)==[]
    cfg=dict(kind='ssh',host='pc',user='reyhan febrizio r',os='windows',shell='powershell',
        remote_dir=r'D:\char3d\remote',python=r'C:\Users\Reyhan Febrizio R\Python312\python.exe',
        blender=r'C:\Program Files\Blender\blender.exe',device='optix',vram_gb=4)
    write_json(root/'targets.json',{'pc':cfg})
    with patch.dict(os.environ,{'CHAR3D_REMOTE_CONFIG':str(root)}):
        t=targets()['pc']
        assert t['blender_version']=='minor' and t['user']==cfg['user']
        for bad in (dict(cfg,remote_dir='D:\\'),dict(cfg,remote_dir=r'D:\a\..\b'),dict(cfg,shell='bash')):
            write_json(root/'targets.json',{'pc':bad})
            reject(targets)
    child=dict(blend='snapshot',blender_version=[5,2,4],overlays=[],transitions=[],frames=[1,4],
        size=[320,180],fps=24,audio=False,quality='preview',scene_memory={'estimated_vram_bytes':6*2**30})
    path=root/'jobs/id/state.json'
    state=dict(id='remote_test',target=t,target_name='pc',kind='video',started=time.time(),
        prepared={'job':{},'children':[child]},quote={'max_hours':1,'max_budget_usd':None,'hourly_price_usd':0})
    write_json(path,state)
    class Probe:
        target=t
        def rpc(self,*args,**kwargs):
            return dict(version='Blender 5.2.3 LTS',os='windows',rsync=False,
                gpus=[{'name':'NVIDIA GeForce GTX 750 Ti','vram_bytes':4*2**30}])
        def upload(self,*args): raise RemoteError('stop after probe')
    supervisor=Supervisor(path)
    reject(lambda:supervisor.render_child(Probe(),child,0),'stop after probe')
    result=read_json(path)
    assert result['vram_bytes']==4*2**30 and len(result['warnings'])==2
    supervisor.t['blender_version']='exact'
    reject(lambda:supervisor.render_child(Probe(),child,0),'mismatch')
    with patch.object(agent.shutil,'which',return_value='nvidia-smi.exe'), \
         patch.object(agent.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='NVIDIA GeForce GTX 750 Ti, 4096\r\n')):
        assert agent.gpu_inventory()[0]['vram_bytes']==4*2**30
    print('windows: minor/exact refusal, GTX 750 Ti VRAM inventory and report warnings OK')


def compose_path_checks(root):
    # Windows Blender resolves drive-less relative strip paths against the drive
    # root, so the agent must hand compose absolute overlay files (2026-11 PC bug).
    job=root/'job';(job/'overlays').mkdir(parents=True)
    (job/'overlays/0.png').write_bytes(b'png')
    spec=dict(size=[640,360],fps=24,frames=12,audio=True,crf='MEDIUM',transitions=[],
              overlays=[dict(path='overlays/0.png',start=1,end=6)])
    compose=agent.compose_spec(spec,job,job/'raw_0001-0012.mp4')
    path=Path(compose['overlays'][0]['path'])
    assert path.is_absolute() and path==(job/'overlays/0.png').resolve() and path.is_file(), compose
    assert spec['overlays'][0]['path']=='overlays/0.png', 'spec must not be mutated'
    assert Path(compose['movie']).is_absolute() and compose['out_base']==str(job/'composed_')
    print('windows: compose receives absolute overlay paths OK')


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        compose_path_checks(root/'compose')
        transport_checks(root/'transport')
        lifecycle_checks(root/'lifecycle')
        policy_checks(root/'policy')
    print('REMOTE WINDOWS UNIT OK')


if __name__=='__main__': main()
