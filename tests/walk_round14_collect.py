"""Collect only final evidence and native projects; SHA-256 manifest before pull."""
import hashlib,json,os
from pathlib import Path
w=Path('/opt/char3d/walk_round14_output');assert Path(os.environ['CHAR3D_WORKSPACE'])==w
suite=json.loads((w/'final_suite.json').read_text());assert suite.get('finished')
assert suite.get('all_work_finished'),'Coverage or render packaging is still running'
d=w/'delivery';d.mkdir(exist_ok=True)
def link(p,target):
 target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():target.unlink()
 os.link(p,target)
for p in w.iterdir():
 if p.is_file() and p.suffix in ('.json','.log','.mp4','.png','.svg','.md'):link(p,d/p.name)
for directory in ('renders','exports'):
 if (w/directory).exists():
  for p in (w/directory).rglob('*'):
   if p.is_file():link(p,d/directory/p.relative_to(w/directory))
for p in (w/'projects').glob('*.blend'):link(p,d/'projects'/p.name)
for name in ('round14_final.log','round14_build_recheck.log','round14_preview_quality.log','round14_render_resume.log','round14_finish.log'):
 p=Path('/opt/char3d/runs')/name
 if p.exists():link(p,d/name)
manifest={str(p.relative_to(d)):dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in d.rglob('*') if p.is_file() and p.name!='delivery_manifest.json'}
(d/'delivery_manifest.json').write_text(json.dumps(manifest,indent=2))
print('COLLECTED',len(manifest),'files',sum(v['bytes'] for v in manifest.values()),'bytes',flush=True)
