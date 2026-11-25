"""Finish four-family coverage and readable sheets after cached render resumes."""
import json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
w=Path(os.environ['CHAR3D_WORKSPACE']);assert str(w)=='/opt/char3d/walk_round14_output' and os.environ['CHAR3D_PORT']=='9977'
while True:
 try:suite=json.loads((w/'final_suite.json').read_text());ready=suite.get('render_resumes_finished')
 except (FileNotFoundError,json.JSONDecodeError):ready=False
 if ready:break
 time.sleep(5)
if '--sheets-only' in sys.argv:
 coverage=json.loads((w/'rig_fpa_metrics.json').read_text())
 assert set(coverage)=={'mpfb_game_engine','basic','rigify','mpfb_mixamo'}
 assert (w/'gait_contract_failures.json').exists()
 record=dict(stage='gait_four_families_complete',returncode=1,seconds=None,reused_completed_log='gait_all_families_completion.log')
else:
 started=time.perf_counter()
 with (w/'gait_all_families_completion.log').open('w') as log:
  completed=subprocess.run([sys.executable,'tests/walk_gait_checks.py'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 record=dict(stage='gait_four_families_complete',returncode=completed.returncode,seconds=time.perf_counter()-started)
suite=json.loads((w/'final_suite.json').read_text());suite['coverage_completion']=record
(w/'final_suite.json').write_text(json.dumps(suite,indent=2))
# Formatting only: preserve the rendered 512 px source images, wrap long labels.
from walk_round8_review import montage
visuals=json.loads((w/'shoe_visuals.json').read_text());paths=[];labels=[]
for key,r in visuals['cases'].items():
 rig,shoe=key.split('/',1);rp=[];rl=[]
 for item in r['images']:
  text=f"{shoe} / {'game' if rig=='game_engine' else rig}\n{item['phase']}\n{item['angle']} / {item['label']}"
  rp.append(item['path']);rl.append(text)
 if rp:montage(rp,rl,w/f'shoe_review_{rig}_{shoe}.png','4x','256x256+3+10')
 paths+=rp;labels+=rl
if paths:montage(paths,labels,w/'walk_shoe_weights_v13_v16.png','8x','256x256+3+10')
suite['all_work_finished']=True;(w/'final_suite.json').write_text(json.dumps(suite,indent=2));print('ALL WORK FINISHED',record,flush=True)
