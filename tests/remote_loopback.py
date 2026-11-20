#!/usr/bin/env python3
"""Fake ssh/rsync executables; execute the *real* SSH protocol in a local directory."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    args = sys.argv[1:]
    name = Path(sys.argv[0]).name
    record = os.environ.get('CHAR3D_LOOPBACK_RECORD')
    if name == 'ssh':
        assert args[0] == '-F' and 'BatchMode=yes' in args and 'StrictHostKeyChecking=yes' in args
        body = sys.stdin.read()
        req = json.loads(body)
        if record:
            with open(record, 'a') as stream:
                stream.write(json.dumps({'tool': 'ssh', 'action': req['action']})+'\n')
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
        p = subprocess.run(args[-1], shell=True, input=body, text=True)
        return p.returncode
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
