"""Resume cached final renders after the missing-montage fallback is available."""
import json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];w=Path(os.environ['CHAR3D_WORKSPACE'])
assert str(w)=='/opt/char3d/walk_round14_output' and os.environ['CHAR3D_PORT']=='9977'
while True:
 try:suite=json.loads((w/'final_suite.json').read_text());ready=suite.get('rechecks_finished')
 except (FileNotFoundError,json.JSONDecodeError):ready=False
 if ready:break
 time.sleep(5)
stages=[('shoe_visuals',['tests/walk_round14_shoes.py','--resume']),
        ('review',['tests/walk_round8_review.py','--label','v16','--render','--resume'])]
if next(r['returncode'] for r in suite['stages'] if r['stage']=='evidence'):
 stages.append(('evidence',['tests/walk_round14_evidence.py']))
results=[]
for name,args in stages:
 start=time.perf_counter();print('RENDER RESUME START',name,flush=True)
 with (w/f'resume_{name}.log').open('w') as log:
  p=subprocess.run([sys.executable,*args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 results.append(dict(stage=name,command=args,returncode=p.returncode,seconds=time.perf_counter()-start))
 (w/'render_resumes.json').write_text(json.dumps(results,indent=2));print('RENDER RESUME END',results[-1],flush=True)
suite=json.loads((w/'final_suite.json').read_text());suite.update(render_resumes=results,render_resumes_finished=True)
(w/'final_suite.json').write_text(json.dumps(suite,indent=2));print('RENDER RESUMES FINISHED',flush=True)
