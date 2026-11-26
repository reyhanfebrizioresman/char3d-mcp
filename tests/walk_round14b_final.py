"""One serial Devodo final suite, completing all stages even after a failed gate."""
import json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];w=Path(os.environ['CHAR3D_WORKSPACE'])
assert str(w)=='/opt/char3d/walk_round14_output' and os.environ['CHAR3D_PORT']=='9977'
stages=[('build_identity',['tests/walk_round14_build_checks.py']),
 ('benchmark_varied',['tests/walk_benchmark.py','--label','v17']),
 ('benchmark_symmetric',['tests/walk_benchmark.py','--label','v17','--rhythm','symmetric']),
 ('gait_four_families',['tests/walk_gait_checks.py']),('rig_shod_unshod',['tests/walk_round14_rigs.py']),
 ('navigation',['tests/nav_round7_e2e.py','nav','avoid','terrain']),
 ('standing',['tests/standing_performance_checks.py']),('steady',['tests/walk_round10_steady.py']),
 ('mpfb_smoke',['tests/e2e_smoke.py','--mpfb-only']),('toon_unit',['tests/test_toon.py']),
 ('asset_qa',['tests/walk_round14_asset_checks.py']),('shoe_visuals',['tests/walk_round14_shoes.py']),
 ('review',['tests/walk_round8_review.py','--label','v17','--prepare','--render']),
 ('evidence',['tests/walk_round14_evidence.py']),('report',['tests/walk_round14b_report.py',str(w)])]
results=[];began=time.perf_counter()
for name,args in stages:
 started=time.perf_counter();print('START',name,flush=True)
 with (w/f'final_{name}.log').open('w') as log:
  p=subprocess.run([sys.executable,*args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 results.append(dict(stage=name,returncode=p.returncode,seconds=time.perf_counter()-started,command=args))
 (w/'final_suite.json').write_text(json.dumps(dict(seconds=time.perf_counter()-began,stages=results,finished=False),indent=2))
 print('END',name,p.returncode,results[-1]['seconds'],flush=True)
(w/'final_suite.json').write_text(json.dumps(dict(seconds=time.perf_counter()-began,stages=results,finished=True),indent=2))
print('FINAL SUITE FINISHED',time.perf_counter()-began,flush=True)
