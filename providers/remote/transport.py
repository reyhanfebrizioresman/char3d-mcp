"""System SSH and rsync only; user's config/keys/agent, stdin JSON, no passwords."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from .config import RemoteError, clean_env

ROOT = Path(__file__).resolve().parents[2]


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


class SSH:
    def __init__(self, target):
        self.target = target
        self.args = ['ssh', '-F', str(Path('~/.ssh/config').expanduser()), '-o', 'BatchMode=yes',
                     '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=10',
                     '-o', 'ServerAliveCountMax=3', '-o', 'StrictHostKeyChecking=yes']
        if target.get('port'):
            self.args += ['-p', str(target['port'])]
        if target.get('jump_host'):
            # Explicit ProxyCommand ensures the jump also ignores /etc/ssh/config.
            jump = ['ssh', '-F', str(Path('~/.ssh/config').expanduser()), '-o', 'BatchMode=yes',
                    '-o', 'StrictHostKeyChecking=yes', '-W', '%h:%p', target['jump_host']]
            self.args += ['-o', 'ProxyCommand=' + shlex.join(jump)]
        self.host = (target.get('user', '')+'@' if target.get('user') else '')+target['host']

    def rpc(self, action, **args):
        source = (ROOT/'engine/remote_agent.py').read_bytes()
        bootstrap = "import base64; SOURCE=base64.b64decode("+repr(base64.b64encode(source).decode())+").decode(); exec(compile(SOURCE,'remote_agent.py','exec'))"
        command = shlex.join(['python3', '-c', bootstrap, 'rpc'])
        try:
            p = subprocess.run(self.args+[self.host, command],
                input=json.dumps(dict(action=action, root=self.target['remote_dir'], **args)),
                capture_output=True, text=True, timeout=60, env=clean_env())
        except (OSError, subprocess.TimeoutExpired):
            raise RemoteError('SSH unavailable or timed out; job can be reattached') from None
        try:
            result = json.loads(p.stdout)
        except ValueError:
            raise RemoteError('SSH failed; check host key, BatchMode, config and Python 3') from None
        if p.returncode or result.get('rpc_error'):
            raise RemoteError('Remote command failed: '+result.get('rpc_error', 'SSH transport error'))
        return result

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
            with tempfile.NamedTemporaryFile(mode='w') as listing:
                listing.write('\n'.join(missing)+'\n')
                listing.flush()
                self.rsync(str(blob_dir)+'/', self.host+':'+self.target['remote_dir']+'/blobs/',
                           '--ignore-times', '--files-from='+listing.name)
        return mapping

    def download(self, ident, name, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        self.rsync(self.host+':'+self.target['remote_dir']+'/jobs/'+ident+'/'+name, str(dest))
