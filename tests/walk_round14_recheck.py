"""Recheck only corrected checks after the complete first suite, serially."""
import json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];w=Path(os.environ['CHAR3D_WORKSPACE'])
assert str(w)=='/opt/char3d/walk_round14_output' and os.environ['CHAR3D_PORT']=='9977'
while True:
 try:done=json.loads((w/'final_suite.json').read_text()).get('finished')
 except (FileNotFoundError,json.JSONDecodeError):done=False
 if done:break
 time.sleep(10)
for name in ('sole_build_checks.json','rig_shod_unshod.json'):
 shutil.copy2(w/name,w/Path(name).with_stem(Path(name).stem+'_initial'))
stages=[('build_identity',['tests/walk_round14_build_checks.py','--resume-failed']),
 ('gait_four_families',['tests/walk_gait_checks.py']),
 ('rig_shod_unshod',['tests/walk_round14_rigs.py','--resume-failed'])]
results=[]
for name,args in stages:
 start=time.perf_counter();print('RECHECK START',name,flush=True)
 with (w/f'recheck_{name}.log').open('w') as log:
  p=subprocess.run([sys.executable,*args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 results.append(dict(stage=name,command=args,returncode=p.returncode,seconds=time.perf_counter()-start))
 (w/'rechecks.json').write_text(json.dumps(results,indent=2));print('RECHECK END',results[-1],flush=True)
suite=json.loads((w/'final_suite.json').read_text());suite.update(rechecks=results,rechecks_finished=True)
(w/'final_suite.json').write_text(json.dumps(suite,indent=2))
print('RECHECKS FINISHED',flush=True)
