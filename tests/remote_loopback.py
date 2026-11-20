#!/usr/bin/env python3
"""Fake ssh/rsync executables; execute the *real* SSH protocol in a local directory."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import base64
import re


def translate(path):
    prefix = os.environ.get('CHAR3D_WINDOWS_ROOT')
    if prefix:
        norm = str(path).replace('\\', '/')
        remote = 'D:/char3d/Remote render'
        if norm == remote or norm.startswith(remote+'/'):
            return str(Path(prefix)/norm[len(remote):].lstrip('/'))
    return path


def ps_argv(command):
    script = base64.b64decode(command.split('-EncodedCommand ',1)[1]).decode('utf-16le')
    if script == '[Console]::Write($env:OS)':
        return None
    assert "UTF8Encoding($false)" in script and '[Console]::In.ReadToEnd()' in script
    call = script.split('$wire | & ',1)[1].rsplit('; exit $LASTEXITCODE',1)[0]
    return [x.replace("''", "'") for x in re.findall(r"'((?:[^']|'')*)'",call)]


def main():
    args = sys.argv[1:]
    name = Path(sys.argv[0]).name
    record = os.environ.get('CHAR3D_LOOPBACK_RECORD')
    if name == 'ssh':
        assert args[0] == '-F' and 'BatchMode=yes' in args and 'StrictHostKeyChecking=yes' in args
        command = args[-1]
        windows = bool(os.environ.get('CHAR3D_WINDOWS_ROOT'))
        if command == 'ver':
            if windows and os.environ.get('CHAR3D_WINDOWS_SHELL') != 'powershell':
                print('Microsoft Windows [Version 10.0.26100]\r')
                return 0
            return 1
        if command == 'uname -s':
            if not windows:
                print('Linux')
                return 0
            return 1
        encoded = command.startswith('powershell ')
        argv = ps_argv(command) if encoded else None
        if encoded and argv is None:
            if windows:
                print('Windows_NT',end='')
                return 0
            return 127
        body = sys.stdin.read()
        req = json.loads(body)
        if record:
            with open(record, 'a') as stream:
                stream.write(json.dumps({'tool': 'ssh', 'action': req['action'], 'encoded':encoded})+'\n')
        if req['action'] == 'status' and os.environ.get('CHAR3D_LOOPBACK_DROP'):
            marker = Path(os.environ['CHAR3D_LOOPBACK_DROP'])
            if not marker.exists():
                marker.touch()
                return 255
        if req['action'] == 'start':
            for filename in json.loads(os.environ.get('CHAR3D_LOOPBACK_HIDE', '[]')):
                path = Path(filename)
                if path.exists():
                    path.rename(str(path)+'.hidden')
        if windows:
            assert encoded and len(command)<8191
            req['root'] = translate(req['root'])
            if req['action']=='probe': req['blender']=os.environ['CHAR3D_LOOPBACK_BLENDER']
            if req['action']=='start': req['spec']['blender']=os.environ['CHAR3D_LOOPBACK_BLENDER']
            argv[0] = sys.executable
            p = subprocess.run(argv,input=json.dumps(req),text=True,capture_output=True)
            if req['action']=='probe' and not p.returncode:
                reply=json.loads(p.stdout)
                reply.update(os='windows',rsync=False,version='Blender 5.2.3 LTS',
                    gpus=[{'name':'NVIDIA GeForce GTX 750 Ti (emulated inventory)', 'vram_bytes':4*2**30}])
                print(json.dumps(reply,ensure_ascii=False)+'\r')
            else:
                sys.stdout.write(p.stdout)
                sys.stderr.write(p.stderr)
        else:
            p = subprocess.run(command, shell=True, input=body, text=True)
        return p.returncode
    if name == 'scp':
        assert args[0]=='-F' and 'BatchMode=yes' in args and 'StrictHostKeyChecking=yes' in args
        assert '-O' not in args, 'Legacy SCP shell protocol is unsafe for Windows paths'
        paths=args[args.index('--')+1:]
        def local(value):
            return Path(translate(value.split(':',1)[1] if value.startswith('loopback:') else value))
        dest=local(paths[-1]); sources=[local(p) for p in paths[:-1]]
        folder=paths[-1].endswith('/')
        if folder: dest.mkdir(parents=True,exist_ok=True)
        for source in sources:
            out=dest/source.name if folder else dest
            out.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,out)
        if record:
            with open(record,'a') as stream:
                stream.write(json.dumps({'tool':'scp','blobs':[p.name for p in sources if re.fullmatch('[0-9a-f]{64}',p.name)]})+'\n')
        return 0
    assert name == 'rsync'
    assert '-e' in args and 'ssh -F ' in args[args.index('-e')+1]
    source, dest = args[args.index('--')+1:]
    remote = lambda s: s.split(':', 1)[1] if ':' in s else s
    source, dest = Path(remote(source)), Path(remote(dest))
    listing = next((s.split('=', 1)[1] for s in args if s.startswith('--files-from=')), None)
    if listing:
        names = Path(listing).read_text().splitlines()
        dest.mkdir(parents=True, exist_ok=True)
        for member in names:
            shutil.copy2(source/member, dest/member)
        if record:
            with open(record, 'a') as stream:
                stream.write(json.dumps({'tool': 'rsync', 'blobs': names})+'\n')
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    return 0


if __name__ == '__main__':
    sys.exit(main())
