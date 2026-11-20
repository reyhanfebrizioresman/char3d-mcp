"""MCP-side remote render API. Quotes are immutable, expiring, single-use plans."""
import copy
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from .cloud import Cloud
from .config import RemoteError, config_dir, target, targets, digest, positive, read_json, write_json, clean_env
from .transport import file_hash

PRIVACY = ('Uploads a Blender scene snapshot, referenced textures/user images, fonts, '
           'voice/music/Foley WAVs and caption/title images to this target. '
           'The SSH target retains a bounded content cache; use a private remote_dir. '
           'Provider API keys and SSH private keys are never uploaded.')
TERMINAL = ('done', 'failed', 'cancelled')


def engine_key(quality):
    return {'draft': 'workbench', 'preview': 'eevee', 'final': 'eevee', 'cycles': 'cycles'}[quality]


class RemoteRenders:
    def __init__(self, engine):
        self.engine = engine
        self.root = Path(engine.workspace)/'remote'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def factor(self, name, quality, t):
        e = read_json(self.root/'speed.json', {}).get(digest([name, t, engine_key(quality)]), {})
        return e.get('factor', 1.), e

    def options(self, kind, name, params, calibrate=False, consent_upload=False,
                confirm_cost=False, quote_id=None, max_budget_usd=None, max_hours=None):
        t = target(name)
        params = {k: v for k, v in params.items() if v is not None}
        quality = params.get('quality', 'final')
        info = self.engine.call('film_render_options' if kind == 'film' else 'render_options',
                                **params, calibrate=False, _remote_estimate=True)
        if calibrate:
            mid = sum(info['frames'])//2
            test = dict(quality=quality, resolution='480p', frame_start=mid, frame_end=mid,
                        path='remote_calibration.mp4', subtitles=False, credits=False)
            if kind == 'film':
                test['name'] = params.get('name')
            result = self.start('film_calibration' if kind == 'film' else 'video', name, test, consent_upload, confirm_cost, quote_id,
                                max_budget_usd, max_hours, calibration=True)
            if result['status'] != 'done':
                return result
            info['test_frame'] = result
        factor, learned = self.factor(name, quality, t)
        offer = Cloud(t['kind']).quote(t) if t['kind'] != 'ssh' else {
            'gpu_type': t.get('device'), 'hourly_price_usd': float(t.get('hourly_usd', 0))}
        for report in [info]+info.get('scenes', []):
            for choice in report['options']:
                seconds = choice.pop('model_total_s')*factor
                spf = choice.pop('model_spf', None)
                if spf is not None:
                    choice['seconds_per_frame'] = round(spf*factor, 3)
                billed = seconds + t['startup_seconds']
                choice.update(total_s=round(seconds), total=f'~{math.ceil(seconds/60)} min',
                    estimated_cost_usd=round(billed/3600*offer['hourly_price_usd'], 4),
                    hourly_price_usd=offer['hourly_price_usd'])
            report.update(target=name, machine_speed={'measurements': learned.get('samples', 0), 'factor':factor})
        info.update(target=name, device=t['device'], gpu_type=offer['gpu_type'], privacy=PRIVACY,
                    machine_speed={'measurements': learned.get('samples', 0), 'factor': factor},
                    note='Per-target measurements; startup/transfer costs included as an allowance. '
                         'Uncalibrated estimates use conservative CPU defaults; quotes are not invoices.')
        return info

    def _consent(self, name, t, consent_upload):
        path = config_dir()/'remote_consent.json'
        data = read_json(path, {})
        identity = digest([name, t])
        if not data.get(identity):
            if consent_upload is not True:
                return False
            data[identity] = {'at': time.time(), 'privacy': PRIVACY}
            write_json(path, data)
        return True

    def _freeze_assets(self, prepared):
        """A quote owns immutable asset bytes, including later scenes in a film."""
        blobs = self.root/'blobs'
        blobs.mkdir(exist_ok=True)
        for child in prepared['children']:
            frozen = {}
            for name, source in child.get('remote_assets', {}).items():
                h = file_hash(source)
                if Path(name).name.split('.')[0] != h:
                    raise RemoteError('An external asset changed while preparing the snapshot; retry')
                dest = blobs/h
                if not dest.exists() or file_hash(dest) != h:
                    tmp = blobs/(h+'.'+uuid.uuid4().hex+'.tmp')
                    try:
                        shutil.copyfile(source, tmp)
                        if file_hash(tmp) != h:
                            raise RemoteError('An external asset changed while collecting it; retry')
                        os.replace(tmp, dest)
                    finally:
                        tmp.unlink(missing_ok=True)
                frozen[name] = str(dest)
            child['remote_assets'] = frozen

    def start(self, kind, name, params, consent_upload=False, confirm_cost=False,
              quote_id=None, max_budget_usd=None, max_hours=None, calibration=False):
        t = target(name)
        params = {k: v for k, v in params.items() if v is not None and k != 'wait'}
        signature = digest([kind, name, t, params, calibration, max_budget_usd, max_hours])
        if not self._consent(name, t, consent_upload):
            return dict(status='consent_required', target=name, privacy=PRIVACY,
                        instruction='Repeat with consent_upload=True to authorize this target')
        paid = t['kind'] != 'ssh'
        if quote_id:
            if not quote_id.isalnum():
                raise RemoteError('Invalid quote_id')
            pending = self.root/'quotes'/(quote_id+'.json')
            plan = read_json(pending)
            if not plan or plan['signature'] != signature:
                raise RemoteError('Quote does not match this target, render settings and limits')
            if time.time() > plan['quote']['expires_at']:
                raise RemoteError('Quote expired; request a fresh quote without quote_id')
            if confirm_cost is not True:
                return dict(status='quote_required', **plan['quote'])
        else:
            # No provider mutation here. Quote returned before any paid launch is possible.
            if kind == 'film':
                params['_cache_target'] = digest([name, t])
            prepared = self.engine.call('prepare_remote_render', kind=kind, params=params)
            self._freeze_assets(prepared)
            quality = prepared['job']['quality']
            factor, learned = self.factor(name, quality, t)
            seconds = sum(c['model_spf']*factor*(c['frames'][1]-c['frames'][0]+1+
                          c['graphics']['handle_frames']) for c in prepared['children'])
            offer = Cloud(t['kind']).quote(t) if paid and prepared['children'] else {
                'gpu_type': t.get('gpu_type', t['device']), 'hourly_price_usd': float(t.get('hourly_usd', 0))}
            hours = min(positive(max_hours if max_hours is not None else t['max_hours'], 'max_hours'), float(t['max_hours']))
            budget = max_budget_usd if max_budget_usd is not None else t.get('max_budget_usd')
            if budget is not None:
                budget = positive(budget, 'max_budget_usd')
                if t.get('max_budget_usd'):
                    budget = min(budget, float(t['max_budget_usd']))
            estimate = (seconds+t['startup_seconds'])/3600*offer['hourly_price_usd']
            if seconds+t['startup_seconds'] > hours*3600 or (budget is not None and estimate > budget):
                raise RemoteError('Estimated runtime/cost exceeds the target or call budget/time cap')
            quote_id = uuid.uuid4().hex
            quote = dict(quote_id=quote_id, target=name, gpu_type=offer['gpu_type'],
                hourly_price_usd=offer['hourly_price_usd'], estimated_runtime_s=round(seconds, 2),
                startup_allowance_s=t['startup_seconds'], estimated_total_usd=round(estimate, 4),
                max_budget_usd=budget, max_hours=hours, calibration_measurements=learned.get('samples', 0),
                expires_at=time.time()+600, privacy=PRIVACY,
                billing_note='Estimate; compute/storage hourly charges only, taxes excluded. '
                             'No persistent volumes. Provider totals are reported only when available.')
            plan = dict(signature=signature, quote=quote, offer=offer, prepared=prepared,
                        target=t, target_name=name, calibration=calibration)
            pending = self.root/'quotes'/(quote_id+'.json')
            write_json(pending, plan)
            if paid and prepared['children']:
                return dict(status='quote_required', **quote,
                            instruction='Repeat identical call with quote_id and confirm_cost=True')
        with open(self.root/'registry.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not pending.exists():
                raise RemoteError('Quote already consumed')
            active = [read_json(p, {}) for p in (self.root/'jobs').glob('*/state.json')]
            if sum(j.get('target_name') == name and j.get('status') not in TERMINAL for j in active) >= t['max_parallel']:
                raise RemoteError('Target max_parallel reached')
            ident = 'remote_'+uuid.uuid4().hex[:16]
            state_path = self.root/'jobs'/ident/'state.json'
            plan.update(id=ident, kind=kind, status='queued', stage='queued', started=time.time(),
                        path=plan['prepared']['job']['path'], progress='0/1', cleanup_pending=False)
            job = plan['prepared']['job']
            plan.update(quality=job['quality'], size=job.get('size'), frames=job.get('frames'),
                        scenes=copy.deepcopy(job.get('scenes', [])),
                        estimate={'total_s': plan['quote']['estimated_runtime_s']})
            write_json(state_path, plan)
            pending.unlink()
            self._launch(state_path)
        if calibration:
            return self.wait(ident)
        return self.report(ident)

    def _launch(self, path):
        # Avoid starting another interpreter on each status poll; flock remains the
        # authoritative guard against races and PID reuse.
        pid = read_json(path.parent/'supervisor_pid.json')
        if pid:
            try:
                args = Path(f'/proc/{pid}/cmdline').read_bytes()
                if b'providers.remote.supervisor' in args and str(path).encode() in args:
                    return
            except OSError:
                pass
        with open(path.parent/'supervisor.log', 'ab') as log:
            p = subprocess.Popen([sys.executable, '-m', 'providers.remote.supervisor', str(path)],
                cwd=Path(__file__).resolve().parents[2], stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, env=clean_env(), start_new_session=True)
        # Supervisor owns the state file. PID has a separate file to avoid lost updates.
        write_json(path.parent/'supervisor_pid.json', p.pid)

    def report(self, ident):
        if not ident.startswith('remote_') or not ident.replace('_', '').isalnum():
            raise RemoteError('Invalid remote job id')
        path = self.root/'jobs'/ident/'state.json'
        state = read_json(path)
        if not state:
            raise RemoteError('Unknown remote job')
        if state['status'] not in TERMINAL or state.get('cleanup_pending'):
            # A lock in supervisor prevents duplicate work. Reattach after MCP restart/crash.
            self._launch(path)
            state = read_json(path)
        fields = ('kind', 'status', 'stage', 'path', 'quality', 'size', 'frames', 'estimate',
                  'progress', 'frame_progress', 'progress_unit', 'eta_s', 'device', 'gpu', 'instance_id',
                  'ssh_host', 'ssh_port',
                  'scenes', 'cost_so_far_usd', 'elapsed_s', 'billing', 'error', 'bytes',
                  'subtitles', 'credits', 'has_audio', 'cleanup_pending', 'cleanup_error', 'learned_speed', 'verified')
        return dict(job_id=ident, target=state['target_name'],
                    **{k: state[k] for k in fields if k in state}, quote=state['quote'])

    def wait(self, ident):
        while True:
            result = self.report(ident)
            if result['status'] in TERMINAL and not result.get('cleanup_pending'):
                return result
            time.sleep(.5)

    def status(self):
        return [self.report(p.parent.name) for p in (self.root/'jobs').glob('*/state.json')]

    def cancel(self, ident):
        self.report(ident)
        (self.root/'jobs'/ident/'cancel').touch()
        return self.report(ident)

    def list_targets(self):
        running = self.status()
        return {'targets': [dict(name=n, **t) for n, t in targets().items()], 'jobs': running,
                'privacy': PRIVACY}

    def stop_target(self, name):
        target(name)
        return {'target': name, 'jobs': [self.cancel(j['job_id']) for j in self.status()
            if j['target'] == name and (j['status'] not in TERMINAL or j.get('cleanup_pending'))]}
