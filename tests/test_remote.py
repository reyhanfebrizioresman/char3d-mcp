"""Money/consent, official HTTP protocol, transport safety and failure cleanup contracts."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mock_remote import MockCloud
from providers.remote.cloud import Cloud
from providers.remote.config import RemoteError, targets, write_json, read_json, positive
from providers.remote.jobs import RemoteRenders
from providers.remote.supervisor import Supervisor, verify
from providers.remote.transport import SSH, file_hash


def raises(fn, fragment=None):
    try:
        fn()
    except RemoteError as exc:
        assert 'super-private-test-key' not in str(exc)
        if fragment:
            assert fragment in str(exc), str(exc)
    else:
        raise AssertionError('Expected RemoteError')


def movie(path):
    import av
    import numpy as np
    with av.open(str(path), 'w') as container:
        stream = container.add_stream('libx264', rate=24)
        stream.width, stream.height, stream.pix_fmt = 32, 32, 'yuv420p'
        for i in range(4):
            for packet in stream.encode(av.VideoFrame.from_ndarray(np.full((32, 32, 3), i*40, dtype=np.uint8), format='rgb24')):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def main():
    with tempfile.TemporaryDirectory() as tmp, MockCloud() as cloud:
        root = Path(tmp)
        env = root/'env'
        env.write_text('RUNPOD_API_KEY=super-private-test-key\nVAST_API_KEY=super-private-test-key\n')
        env.chmod(0o600)
        public = root/'id.pub'
        public.write_text('ssh-ed25519 AAAAfake user@test')
        t = dict(kind='runpod', gpu_type='Test GPU', image='test:blender', public_key=str(public),
                 device='cuda', max_hourly_usd=.5, max_budget_usd=1, max_hours=1, startup_seconds=1,
                 remote_dir=str(root/'worker'), idle_timeout_s=2)
        write_json(root/'targets.json', {'pod': t, 'vast': dict(t, kind='vast'),
                   'own': dict(kind='ssh', host='loopback', remote_dir=str(root/'worker'))})
        fixture = root/'fixture.mp4'
        movie(fixture)
        checked = verify(fixture, 4, [32,32])
        assert checked['frames'] == 4
        raises(lambda: verify(fixture, 8, [32,32]), 'PyAV')
        raises(lambda: verify(fixture, 4, [64,32]), 'PyAV')
        raises(lambda: positive(float('nan'), 'limit'))
        raises(lambda: positive('super-private-test-key', 'limit'))
        prepared = dict(kind='video', blender='/blender', job={'path': str(root/'out.mp4'), 'quality': 'draft'},
            children=[dict(id='child', path=str(root/'out.mp4'), blend=str(root/'scene.blend'),
                quality='draft', model_spf=.1, frames=[1,4], graphics={'handle_frames': 0},
                blender_version=[5,2,4], remote_assets={}, overlays=[], transitions=[],
                size=[32,32], fps=24, audio=False)])

        class Engine:
            workspace = str(root/'workspace')
            def call(self, *args, **kwargs):
                return copy.deepcopy(prepared)

        class FakeSSH:
            mode = 'done'
            def __init__(self, target):
                self.target = target
            def rpc(self, action, **kwargs):
                if self.mode == 'failure' and action == 'probe':
                    raise RemoteError('SSH unavailable')
                if action == 'probe':
                    return {'version': 'Blender 5.2.4'}
                if action == 'status':
                    if self.mode in ('idle', 'cap', 'budget', 'cancel'):
                        return {'status': 'running', 'progress': '0/4'}
                    if self.mode == 'worker_failure':
                        return {'status': 'failed', 'error': 'Worker failed'}
                    return {'status': 'done', 'progress': '4/4', 'sha256': file_hash(fixture),
                            'timing': {'render_s': .4}}
                return {}
            def upload(self, *args):
                return {}
            def download(self, ident, name, dest):
                if name.endswith('.log'):
                    Path(dest).write_text('Time: 00:00.10\n'*4)
                else:
                    import shutil
                    shutil.copyfile(fixture, dest)

        with patch.dict(os.environ, {'CHAR3D_REMOTE_CONFIG': tmp,
                'CHAR3D_REMOTE_RUNPOD_BASE': cloud.base, 'CHAR3D_REMOTE_VAST_BASE': cloud.base}):
            manager = RemoteRenders(Engine())
            with patch.object(manager, '_launch'), patch('providers.remote.supervisor.SSH', FakeSSH):
                denied = manager.start('video', 'pod', {})
                assert denied['status'] == 'consent_required' and not cloud.calls
                quote = manager.start('video', 'pod', {}, consent_upload=True, confirm_cost=True)
                assert quote['status'] == 'quote_required' and not cloud.instances
                assert not any(m == 'POST' and p.endswith('/pods') for m,p,b in cloud.calls)
                raises(lambda: manager.start('video', 'pod', {'width':32}, quote_id=quote['quote_id'], confirm_cost=True), 'match')
                state = manager.start('video', 'pod', {}, quote_id=quote['quote_id'], confirm_cost=True)
                raises(lambda: manager.start('video', 'pod', {}, quote_id=quote['quote_id'], confirm_cost=True))
                path = manager.root/'jobs'/state['job_id']/'state.json'
                with patch('providers.remote.supervisor.SSH', FakeSSH):
                    Supervisor(path).run()
                report = manager.report(state['job_id'])
                assert report['status'] == 'done' and report['verified']['frames'] == 4, report
                assert report['progress']=='4/4' and report['eta_s']==0
                assert report['billing']['billedSeconds'] == 9 and not cloud.instances
                assert report['billing']['billed_cost_usd']==.001 and report['billing']['billed_seconds']==9
                print('remote: quote -> confirm -> create -> wait -> run -> verify -> terminate (RunPod)')

                for kind in ('runpod', 'vast'):
                    api = Cloud(kind)
                    cfg = targets()['pod' if kind == 'runpod' else 'vast']
                    offer = api.quote(cfg)
                    ident = api.create(cfg, offer, 'standalone')
                    assert api.connection(cfg, api.inspect(ident), .4)['host'] == 'loopback'
                    api.terminate(ident)
                    assert not api.find('standalone')
                cloud.fail = '/graphql'
                raises(lambda: Cloud('runpod').quote(targets()['pod']), 'redacted')
                cloud.fail = None
                cloud.echo_key = True
                raises(lambda: Cloud('runpod').quote(targets()['pod']), 'redacted')
                cloud.echo_key = False
                before = len(cloud.calls)
                raises(lambda: Cloud('runpod').request('GET','/redirect'), 'HTTP 302')
                assert len(cloud.calls) == before+1, 'Redirect followed with credentials'
                env.chmod(0o644)
                raises(lambda: Cloud('runpod').quote(targets()['pod']), '600')
                env.chmod(0o600)
                with patch.dict(os.environ, {'CHAR3D_REMOTE_RUNPOD_BASE':'https://attacker.example'}):
                    raises(lambda: Cloud('runpod'), 'loopback')
                raises(lambda: manager.start('video','pod',{},max_hours=0), 'max_hours')
                raises(lambda: manager.start('video','pod',{},max_budget_usd=.000001), 'cap')
                expired = manager.start('video','pod',{})
                expired_path = manager.root/'quotes'/(expired['quote_id']+'.json')
                data = read_json(expired_path)
                data['quote']['expires_at'] = 0
                write_json(expired_path,data)
                raises(lambda: manager.start('video','pod',{},quote_id=expired['quote_id'],confirm_cost=True),'expired')
                cloud.price = 1
                raises(lambda: Cloud('runpod').quote(targets()['pod']), 'price')
                cloud.price = .4

                for mode in ('done', 'worker_failure', 'idle', 'cap', 'budget', 'cancel', 'failure'):
                    quote = manager.start('video', 'vast', {}, consent_upload=True)
                    state = manager.start('video', 'vast', {}, quote_id=quote['quote_id'], confirm_cost=True)
                    path = manager.root/'jobs'/state['job_id']/'state.json'
                    s = read_json(path)
                    if mode == 'cap':
                        s['quote']['max_hours'] = 30.9/3600
                    if mode == 'budget':
                        s['quote']['max_budget_usd'] = .4*30.9/3600
                    if mode == 'idle':
                        s['target']['idle_timeout_s'] = .6
                    write_json(path,s)
                    FakeSSH.mode = mode
                    supervisor = Supervisor(path)
                    if mode == 'failure':
                        # Fail after the instance ID is recorded, rather than waiting for ready.
                        with patch.object(supervisor, 'render_child', side_effect=RemoteError('SSH failed')):
                            FakeSSH.mode = 'done'
                            supervisor.run()
                    elif mode == 'cancel':
                        import threading
                        timer = threading.Timer(.7, lambda: (path.parent/'cancel').touch())
                        timer.start()
                        supervisor.run()
                        timer.join()
                    else:
                        supervisor.run()
                    assert not cloud.instances, (mode, cloud.instances)
                    assert read_json(path)['status'] == 'done' if mode == 'done' else read_json(path)['status'] in ('failed', 'cancelled'), read_json(path)
                FakeSSH.mode = 'done'
                print('remote: Vast success, worker/SSH failure, idle, time cap, cancellation all terminate')

                # Budget cap independently from hours and cleanup API outage/recovery.
                quote = manager.start('video', 'pod', {}, consent_upload=True)
                state = manager.start('video', 'pod', {}, quote_id=quote['quote_id'], confirm_cost=True)
                path = manager.root/'jobs'/state['job_id']/'state.json'
                supervisor = Supervisor(path)
                supervisor.save(lease_label='cleanup-retry', lease_started=time.time(), creation_uncertain=False)
                ident = supervisor.cloud.create(supervisor.t, supervisor.state['offer'], 'cleanup-retry')
                supervisor.save(instance_id=ident)
                supervisor.state['quote']['max_budget_usd'] = .4*31/3600
                assert abs(supervisor.caps()-1) < .001
                cloud.fail = '/pods/'+ident
                assert not supervisor.cleanup_cloud() and supervisor.state['cleanup_pending']
                cloud.fail = None
                assert supervisor.cleanup_cloud() and not cloud.instances
                supervisor.save(status='failed')
                # The provider accepted create but the HTTP response was lost. Find by
                # unique label and delete, never issue another paid create.
                supervisor.save(lease_label='ambiguous', lease_started=time.time()-601,
                                lease_finished=None, instance_id=None, creation_uncertain=True)
                ident = supervisor.cloud.create(supervisor.t, supervisor.state['offer'], 'ambiguous')
                assert supervisor.cleanup_cloud() and ident not in cloud.instances
                # Public stop_target requests cleanup for every owned lease.
                quote = manager.start('video','vast',{})
                active = manager.start('video','vast',{},quote_id=quote['quote_id'],confirm_cost=True)
                active_path = manager.root/'jobs'/active['job_id']/'state.json'
                owned = Supervisor(active_path)
                owned.save(lease_label='stop-all',lease_started=time.time(),creation_uncertain=False)
                ident = owned.cloud.create(owned.t,owned.state['offer'],'stop-all')
                owned.save(instance_id=ident)
                manager.stop_target('vast')
                Supervisor(active_path).run()
                assert not cloud.instances and read_json(active_path)['status']=='cancelled'
                # Price change fails closed after allocating and still cleans up.
                quote = manager.start('video', 'pod', {})
                state = manager.start('video', 'pod', {}, quote_id=quote['quote_id'], confirm_cost=True)
                path = manager.root/'jobs'/state['job_id']/'state.json'
                cloud.allocated_price = .45
                with patch('providers.remote.supervisor.SSH', FakeSSH):
                    Supervisor(path).run()
                cloud.allocated_price = None
                assert not cloud.instances and read_json(path)['status'] == 'failed'
                # Persisted records and error strings contain no API credential.
                assert all('super-private-test-key' not in p.read_text(errors='replace')
                           for p in manager.root.rglob('*.json'))
                print('remote: price change, budget reserve, cleanup retry, redaction and credential isolation')

            class OptionsEngine(Engine):
                def call(self, cmd, **kwargs):
                    assert cmd == 'render_options' and not kwargs['calibrate'] and kwargs['_remote_estimate']
                    return dict(frames=[1,4], options=[dict(resolution='480p',size='854x480',
                        model_spf=2,model_total_s=8,seconds_per_frame=999)],quality='draft')
            options = RemoteRenders(OptionsEngine()).options('video','own',{'quality':'draft'})
            assert options['options'][0]['total_s']==8 and options['options'][0]['seconds_per_frame']==2
            assert options['options'][0]['estimated_cost_usd']==0

            # Device setup never silently falls back to CPU on a paid GPU target.
            prefs=SimpleNamespace(compute_device_type=None,devices=[SimpleNamespace(type='CPU',name='CPU',use=True),
                SimpleNamespace(type='CUDA',name='Test GPU',use=False)],get_devices=lambda:None)
            scene=SimpleNamespace(render=SimpleNamespace(engine='CYCLES'),cycles=SimpleNamespace(device='CPU'))
            fake_bpy=SimpleNamespace(context=SimpleNamespace(scene=scene,preferences=SimpleNamespace(
                addons={'cycles':SimpleNamespace(preferences=prefs)})))
            with patch.dict(sys.modules,{'bpy':fake_bpy}):
                from engine.remote_worker import setup_device
                assert setup_device('cuda')['gpu']=='Test GPU' and scene.cycles.device=='GPU'
                assert not prefs.devices[0].use and prefs.devices[1].use
                try: setup_device('optix')
                except RuntimeError: pass
                else: raise AssertionError('Missing OptiX silently accepted')

            # Standalone SSH supervisor notices a dead owner and its cache pins
            # active hardlinks while evicting unused blobs.
            from engine.remote_agent import rpc, prune
            worker_root = root/'worker-state'
            (worker_root/'jobs/dead').mkdir(parents=True)
            write_json(worker_root/'jobs/dead/status.json',{'status':'running'})
            write_json(worker_root/'jobs/dead/pid.json',999999999)
            assert rpc(dict(root=str(worker_root),action='status',id='dead'))['status']=='failed'
            rpc(dict(root=str(worker_root),action='cleanup',id='dead',cache_bytes=1))
            (worker_root/'blobs/a').write_bytes(b'1234')
            (worker_root/'blobs/b').write_bytes(b'5678')
            (worker_root/'jobs/active').mkdir()
            os.link(worker_root/'blobs/a',worker_root/'jobs/active/pin')
            prune(worker_root,1)
            assert (worker_root/'blobs/a').exists() and not (worker_root/'blobs/b').exists()

            cfg = targets()['own']
            ssh = SSH(dict(cfg, jump_host='reyhan'))
            assert ssh.args[1:3] == ['-F', str(Path('~/.ssh/config').expanduser())]
            assert any('ProxyCommand=ssh -F ' in v for v in ssh.args)
            assert 'BatchMode=yes' in ssh.args and 'StrictHostKeyChecking=yes' in ssh.args
            bad = dict(t, api_key='secret')
            write_json(root/'targets.json', {'bad':bad})
            raises(targets, 'unknown fields')
    print('REMOTE UNIT OK')


if __name__ == '__main__':
    main()
