"""Private, user-owned target registry and durable state. No credentials in targets."""
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import shlex
import tempfile


class RemoteError(RuntimeError):
    pass


def config_dir():
    return Path(os.environ.get('CHAR3D_REMOTE_CONFIG', '~/.config/char3d')).expanduser()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def positive(value, name, zero=False):
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise RemoteError(f'{name} must be a finite number') from None
    if not math.isfinite(value) or value < 0 or (not zero and value == 0):
        raise RemoteError(f'{name} must be finite and positive')
    return value


TRANSPORT_FIELDS={'connect_timeout_s','rpc_timeout_s','upload_timeout_s','download_timeout_s',
                  'offline_grace_s','server_alive_interval_s','server_alive_count_max'}


def render_profile(target):
    """Connection policy cannot change rendered pixels or invalidate existing clips."""
    return {key:value for key,value in target.items() if key not in TRANSPORT_FIELDS}


COMMON = {'kind', 'host', 'user', 'port', 'jump_host', 'remote_dir', 'blender', 'device',
          'max_parallel', 'threads', 'hourly_usd', 'max_hours', 'max_budget_usd',
          'idle_timeout_s', 'cache_bytes', 'gpu_type', 'max_hourly_usd', 'image', 'disk_gb',
          'public_key', 'cloud_type', 'startup_seconds', 'os', 'python', 'shell',
          'blender_version', 'vram_gb', 'connect_timeout_s', 'rpc_timeout_s',
          'upload_timeout_s', 'download_timeout_s', 'offline_grace_s',
          'server_alive_interval_s', 'server_alive_count_max'}


def validate_remote_dir(value, system='auto'):
    if not isinstance(value, str) or any(c in value for c in '\n\r\x00'):
        raise RemoteError('Invalid remote_dir')
    win = PureWindowsPath(value)
    windows = win.is_absolute() and bool(re.fullmatch(r'[A-Za-z]:', win.drive))
    if windows:
        if system == 'linux' or '..' in win.parts or len(win.parts) < 2 or any(c in value[2:] for c in ':*?"<>|'):
            raise RemoteError('remote_dir must be a Windows drive directory without .. or wildcards')
    elif system == 'windows' or not value.startswith('/') or '..' in Path(value).parts or ':' in value or str(Path(value)) in ('/', '//'):
        raise RemoteError('remote_dir must be an absolute directory for the target OS, without ..')


def targets():
    data = read_json(config_dir() / 'targets.json', {})
    if not isinstance(data, dict):
        raise RemoteError('targets.json must be an object mapping names to targets')
    result = {}
    for name, raw in data.items():
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name) or name == 'local':
            raise RemoteError('Invalid target name (local is reserved)')
        if not isinstance(raw, dict) or set(raw) - COMMON:
            raise RemoteError(f'{name}: unknown fields; never put keys/passwords in targets.json')
        t = dict(remote_dir='/tmp/char3d', blender='blender', device='cpu', max_parallel=1,
                 threads=4, max_hours=4, idle_timeout_s=900, cache_bytes=2**30,
                 startup_seconds=300, disk_gb=20, connect_timeout_s=10,
                 rpc_timeout_s=30, upload_timeout_s=120, download_timeout_s=120,
                 offline_grace_s=150, server_alive_interval_s=5, server_alive_count_max=2)
        t.update(raw)
        t.setdefault('os', 'auto' if t.get('kind') == 'ssh' else 'linux')
        t.setdefault('shell', 'auto')
        t.setdefault('blender_version', 'minor')
        if t['os'] not in ('auto', 'linux', 'windows'):
            raise RemoteError('os must be auto, linux or windows')
        if t['shell'] not in ('auto', 'cmd', 'powershell'):
            raise RemoteError('shell must be cmd, powershell or auto')
        if t['blender_version'] not in ('exact', 'minor'):
            raise RemoteError('blender_version must be exact or minor')
        if t.get('kind') not in ('ssh', 'runpod', 'vast'):
            raise RemoteError(f'{name}: kind must be ssh, runpod or vast')
        if t['device'] not in ('cpu', 'cuda', 'optix', 'hip'):
            raise RemoteError('device must be cpu, cuda, optix or hip')
        for field in ('host', 'jump_host'):
            if t.get(field) and not re.fullmatch(r'[A-Za-z0-9_.@,:\[\]-]+', t[field]):
                raise RemoteError(f'Invalid {field}')
            if str(t.get(field, '')).startswith('-'):
                raise RemoteError(f'Invalid {field}')
        if 'user' in t and (not isinstance(t['user'], str) or not re.fullmatch(r'[\w .@\\-]+', t['user']) or t['user'].startswith('-')):
            raise RemoteError('Invalid SSH user')
        validate_remote_dir(t['remote_dir'], t['os'])
        for field in ('blender', 'python', 'image'):
            if field in t and (not isinstance(t[field], str) or not t[field] or any(c in t[field] for c in '\n\r\x00')):
                raise RemoteError(f'Invalid {field}')
        for field in ('max_parallel', 'threads', 'disk_gb', 'cache_bytes'):
            if type(t[field]) is not int or t[field] < 1:
                raise RemoteError(f'{field} must be a positive integer')
        if 'port' in t and (type(t['port']) is not int or not 1 <= t['port'] <= 65535):
            raise RemoteError('Invalid SSH port')
        for field in ('max_hours', 'idle_timeout_s', 'startup_seconds'):
            t[field] = positive(t[field], field)
        for field in ('connect_timeout_s', 'rpc_timeout_s', 'upload_timeout_s',
                      'download_timeout_s', 'offline_grace_s', 'server_alive_interval_s', 'server_alive_count_max'):
            t[field] = positive(t[field], field)
        if 'vram_gb' in t:
            t['vram_gb'] = positive(t['vram_gb'], 'vram_gb')
        if t['kind'] == 'ssh':
            if not t.get('host'):
                raise RemoteError(f'{name}: host is required')
            if 'hourly_usd' in t:
                t['hourly_usd'] = positive(t['hourly_usd'], 'hourly_usd', zero=True)
        else:
            if t['os'] != 'linux':
                raise RemoteError('Rented provider targets currently require Linux images')
            for field in ('gpu_type', 'image', 'public_key', 'max_budget_usd', 'max_hourly_usd'):
                if not t.get(field):
                    raise RemoteError(f'{name}: {field} is required for rented GPU targets')
            t['max_budget_usd'] = positive(t['max_budget_usd'], 'max_budget_usd')
            t['max_hourly_usd'] = positive(t['max_hourly_usd'], 'max_hourly_usd')
            if not isinstance(t['public_key'], str) or not t['public_key'].startswith(('/', '~/')):
                raise RemoteError('public_key must be an absolute or ~/ path to a public key file')
            if t.get('cloud_type', 'SECURE') not in ('SECURE', 'COMMUNITY'):
                raise RemoteError('cloud_type must be SECURE or COMMUNITY')
            if t['device'] == 'cpu':
                raise RemoteError('Rented GPU targets require a GPU device')
        result[name] = t
    return result


def target(name):
    try:
        return targets()[name]
    except KeyError:
        raise RemoteError(f'Unknown remote target: {name}') from None


def api_key(kind):
    """Only the private env file; never shell-evaluate it or fall back to process env."""
    path = config_dir() / 'env'
    if not path.is_file():
        raise RemoteError('Add provider key to ~/.config/char3d/env (mode 600)')
    if path.stat().st_mode & 0o077:
        raise RemoteError('Provider env file must have permissions 600')
    wanted = {'runpod': 'RUNPOD_API_KEY', 'vast': 'VAST_API_KEY'}[kind]
    for line in path.read_text().splitlines():
        line = line.strip().removeprefix('export ')
        if line.startswith(wanted + '='):
            try:
                parts = shlex.split(line.split('=', 1)[1], comments=True)
            except ValueError:
                raise RemoteError('Invalid provider env file') from None
            if len(parts) == 1 and parts[0]:
                return parts[0]
    raise RemoteError(f'{wanted} is missing from the private env file')


def clean_env():
    # SSH/agent still works; no API credentials in child process environments.
    return {k: v for k, v in os.environ.items()
            if not any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL'))}
