"""User-owned SSH: Linux rsync or Windows SFTP-mode SCP and encoded PowerShell."""
import base64
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shlex
import subprocess
import tempfile
import time
import uuid

from .config import RemoteError, clean_env, validate_remote_dir

ROOT = Path(__file__).resolve().parents[2]


def powershell_command(script):
    # Only this ASCII token crosses cmd.exe/PowerShell's outer command parser.
    return 'powershell -NoProfile -NonInteractive -EncodedCommand '+base64.b64encode(
        script.encode('utf-16le')).decode('ascii')


def ps_literal(value):
    return "'"+str(value).replace("'", "''")+"'"


def remote_path(target, *parts):
    if target.get('os') == 'windows':
        return PureWindowsPath(target['remote_dir']).joinpath(*parts).as_posix()
    return str(Path(target['remote_dir']).joinpath(*parts))


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


class SSH:
    def __init__(self, target):
        self.target = dict(target)
        self.options = ['-F', str(Path('~/.ssh/config').expanduser()), '-o', 'BatchMode=yes',
                     '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=10',
                     '-o', 'ServerAliveCountMax=3', '-o', 'StrictHostKeyChecking=yes']
        if target.get('jump_host'):
            # Explicit ProxyCommand ensures the jump also ignores /etc/ssh/config.
            jump = ['ssh', '-F', str(Path('~/.ssh/config').expanduser()), '-o', 'BatchMode=yes',
                    '-o', 'StrictHostKeyChecking=yes', '-W', '%h:%p', target['jump_host']]
            self.options += ['-o', 'ProxyCommand=' + shlex.join(jump)]
        self.args = ['ssh', *self.options]
        if target.get('port'):
            self.args += ['-p', str(target['port'])]
        if target.get('user'):
            self.args += ['-l', target['user']]
        self.host = target['host']

    def _run(self, command, wire=''):
        # Every agent action is idempotent (start returns an existing job's status), so
        # one retry absorbs an occasional stalled relay/Windows session without a pop.
        for attempt in range(2):
            try:
                return subprocess.run(self.args+[self.host, command], input=wire,
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60, env=clean_env())
            except (OSError, subprocess.TimeoutExpired):
                if attempt:
                    raise RemoteError('SSH unavailable or timed out; job can be reattached') from None
                time.sleep(3)

    def detect_os(self):
        system = self.target.get('os', 'auto')
        if system == 'auto':
            ver = self._run('ver')
            if ver.returncode == 0 and 'windows' in ver.stdout.lower():
                system = 'windows'
            else:
                env = self._run(powershell_command('[Console]::Write($env:OS)'))
                if env.returncode == 0 and 'Windows_NT' in env.stdout:
                    system = 'windows'
                else:
                    linux = self._run('uname -s')
                    if linux.returncode != 0 or linux.stdout.strip() != 'Linux':
                        raise RemoteError('Cannot detect target OS; set os to linux or windows')
                    system = 'linux'
            self.target['os'] = system
        validate_remote_dir(self.target['remote_dir'], system)
        return system

    def rpc(self, action, **args):
        system = self.detect_os()
        source = (ROOT/'engine/remote_agent.py').read_bytes()
        # Source goes over stdin, keeping the encoded command below cmd.exe's 8191
        # character limit even when the standalone agent grows.
        bootstrap = ("import base64,io,json,sys; q=json.load(sys.stdin); "
                     "SOURCE=base64.b64decode(q.pop('_agent')).decode('utf-8'); "
                     "sys.stdin=io.StringIO(json.dumps(q)); exec(compile(SOURCE,'remote_agent.py','exec'))")
        python = self.target.get('python', 'python' if system == 'windows' else 'python3')
        argv = [python, '-X', 'utf8', '-c', bootstrap, 'rpc']
        if system == 'windows':
            script = ("$ErrorActionPreference='Stop'; $utf8=New-Object System.Text.UTF8Encoding($false); "
                      "[Console]::OutputEncoding=$utf8; $OutputEncoding=$utf8; "
                      "$wire=[Console]::In.ReadToEnd(); $wire | & "+' '.join(map(ps_literal, argv))+
                      '; exit $LASTEXITCODE')
            command = powershell_command(script)
        else:
            command = shlex.join(argv)
        wire = json.dumps(dict(action=action, root=self.target['remote_dir'],
            _agent=base64.b64encode(source).decode('ascii'), **args))
        debug = os.environ.get('CHAR3D_REMOTE_DEBUG')
        began = time.monotonic()
        try:
            p = self._run(command, wire)
        except RemoteError:
            if debug:
                with open(debug, 'a', encoding='utf-8') as log:
                    log.write(json.dumps({'action': action, 'timeout_after_s': round(time.monotonic()-began, 1)})+'\n')
            raise
        if debug:
            with open(debug, 'a', encoding='utf-8') as log:
                log.write(json.dumps({'action': action, 'seconds': round(time.monotonic()-began, 1),
                                      'returncode': p.returncode})+'\n')
        try:
            result = json.loads(p.stdout.lstrip('\ufeff'))
        except ValueError:
            if os.environ.get('CHAR3D_REMOTE_DEBUG'):
                # Opt-in diagnostics; wire payloads (scene data) are never written.
                with open(os.environ['CHAR3D_REMOTE_DEBUG'], 'a', encoding='utf-8') as log:
                    log.write(json.dumps({'action': action, 'returncode': p.returncode,
                                          'stdout': p.stdout[-2000:], 'stderr': p.stderr[-2000:]})+'\n')
            raise RemoteError('SSH failed; check host key, BatchMode, config and Python 3') from None
        if p.returncode or result.get('rpc_error'):
            raise RemoteError('Remote command failed: '+result.get('rpc_error', 'SSH transport error'))
        return result

    def scp(self, sources, destination):
        args = ['scp', *self.options]
        if self.target.get('port'):
            args += ['-P', str(self.target['port'])]
        if self.target.get('user'):
            # scp has no ssh-style -l login option (-l means bandwidth). OpenSSH's
            # config parser needs a quoted User value, passed as ONE argv element.
            args += ['-o', 'User='+ps_user(self.target['user'])]
        try:
            p = subprocess.run(args+['--', *map(str, sources), str(destination)], capture_output=True,
                timeout=120, env=clean_env())
        except (OSError, subprocess.TimeoutExpired):
            raise RemoteError('SCP unavailable or timed out; retry missing blobs') from None
        if p.returncode:
            raise RemoteError('SCP failed; check SFTP subsystem, SSH key, path and disk space')

    def endpoint(self, *parts):
        host = '['+self.host.strip('[]')+']' if ':' in self.host else self.host
        return host+':'+remote_path(self.target, *parts)

    def rsync(self, source, dest, *extra):
        try:
            p = subprocess.run(['rsync', '-a', '--protect-args', '--partial', *extra,
                '-e', shlex.join(self.args), '--', source, dest], capture_output=True,
                timeout=120, env=clean_env())
        except (OSError, subprocess.TimeoutExpired):
            raise RemoteError('rsync unavailable or timed out; retry to resume') from None
        if p.returncode:
            raise RemoteError('rsync failed; check SSH access, disk space and remote rsync')

    def upload(self, files, blob_dir):
        blob_dir = Path(blob_dir)
        blob_dir.mkdir(parents=True, exist_ok=True)
        mapping = {}
        for name, path in files.items():
            h = file_hash(path)
            cached = blob_dir/h
            if not cached.exists():
                import shutil
                shutil.copyfile(path, cached)
            mapping[name] = h
        missing = self.rpc('missing', hashes=list(set(mapping.values())))['missing']
        if missing:
            if self.target['os'] == 'windows':
                token = uuid.uuid4().hex
                self.rpc('stage_upload', token=token)
                try:
                    for i in range(0, len(missing), 32):
                        self.scp([blob_dir/h for h in missing[i:i+32]], self.endpoint('uploads', token)+'/')
                    self.rpc('finish_upload', token=token, hashes=missing)
                except RemoteError:
                    try:
                        self.rpc('discard_upload', token=token)
                    except RemoteError:
                        pass
                    raise
            else:
                with tempfile.NamedTemporaryFile(mode='w') as listing:
                    listing.write('\n'.join(missing)+'\n')
                    listing.flush()
                    self.rsync(str(blob_dir)+'/', self.endpoint('blobs')+'/',
                               '--ignore-times', '--files-from='+listing.name)
            if self.rpc('missing', hashes=missing)['missing']:
                raise RemoteError('Transferred blobs failed remote SHA-256 verification')
        return mapping

    def download(self, ident, name, dest):
        self.detect_os()
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        if self.target['os'] == 'windows':
            self.scp([self.endpoint('jobs', ident, name)], dest)
        else:
            self.rsync(self.endpoint('jobs', ident, name), str(dest))


def ps_user(user):
    return '"'+user.replace('\\', '\\\\').replace('"', '\\"')+'"'
