"""Owner-operated, checksum-pinned optional assets. No automatic dependencies."""
import argparse
import csv
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('kind',choices=('vrm','face'))
    p.add_argument('--dry-run',action='store_true',help='Print plan only; no network, filesystem writes or Blender')
    p.add_argument('--yes',action='store_true')
    p.add_argument('--install',action='store_true',help='VRM: also install verified extension through Blender CLI (stop engines first)')
    args = p.parse_args()
    if args.kind=='face' and args.install:
        p.error('--install applies only to the VRM extension; face files are placed directly in the model directory')
    root = Path(__file__).resolve().parents[1]
    manifest = Path(__file__).with_name('toon_assets.tsv')
    with manifest.open() as stream:
        rows = [r for r in csv.DictReader(stream,delimiter='\t') if r['kind']==args.kind]
    destination = (Path(os.environ.get('CHAR3D_FACE_MODEL_DIR',str(Path.home()/'.local/share/char3d/face'))) if args.kind=='face'
                   else Path(os.environ.get('CHAR3D_VRM_DOWNLOAD_DIR',str(root/'output/installers'))))
    destination=destination.expanduser()
    for row in rows:
        print(f"{row['file']} | version {row['version']} | {row['bytes']} bytes ({row['approximate_size']})")
        print(f"URL: {row['url']}\nLicence: {row['licence']}\nSHA-256: {row['sha256'] or 'UNRECORDED — owner must fill manifest'}")
    print('Destination:',destination)
    if args.kind=='face':
        print('OpenSeeFace code/model licence: https://github.com/emilianavt/OpenSeeFace/blob/master/LICENSE')
        print('Uses existing numpy/onnxruntime CPU. No pip install, torch, OpenCV or Pillow.')
    else:
        print('Install from Disk in Blender 4.2+ preferences, or rerun with --install after stopping engines.')
    if args.dry_run:
        print('TOON INSTALL DRY RUN OK (no downloads or writes)')
        return
    if not rows or any(not re.fullmatch(r'[a-f0-9]{64}',r['sha256']) or not r['bytes'].isdigit() or int(r['bytes'])<=0 for r in rows):
        p.error('Record approved SHA-256 and exact byte sizes in scripts/toon_assets.tsv first; nothing downloaded.')
    if not args.yes and input('Download and verify these optional assets'+(' and install the VRM extension' if args.install else '')+'? [y/N] ').lower()!='y':
        sys.exit('Cancelled; nothing downloaded.')
    destination.mkdir(parents=True,exist_ok=True)
    for row in rows:
        target = destination/row['file']
        def verify(path):
            if path.stat().st_size!=int(row['bytes']):
                raise ValueError('Size mismatch: '+str(path))
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream,'sha256').hexdigest()
            if digest!=row['sha256']:
                raise ValueError('SHA-256 mismatch: '+str(path))
        if target.exists():
            verify(target)
        else:
            temporary = target.with_suffix(target.suffix+'.part')
            try:
                with urllib.request.urlopen(row['url'],timeout=60) as response,temporary.open('wb') as stream:
                    shutil.copyfileobj(response,stream)
                verify(temporary)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        print('VERIFIED',target)
        if args.kind=='vrm' and args.install:
            blender = os.environ.get('CHAR3D_BLENDER',str(Path.home()/'.local/opt/blender/blender'))
            subprocess.run([blender,'-b','--factory-startup','--command','extension','install-file',
                            '-r','user_default','-e',str(target.resolve())],check=True,cwd='/tmp')
    print('TOON INSTALL OK:',destination)


if __name__=='__main__':
    main()
