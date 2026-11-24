"""Supplement the fixed 5 m matrix with 10 m straight cruise on all three fixtures.

The planner accelerates for ~1.43 seconds regardless of speed; the shortest fast
5 m routes cannot contain a full cruise cycle on both sides. No v11 rebake.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from mcp_server.blender_client import BlenderClient
from walk_benchmark import BODIES,summarize


def main():
    assert os.environ.get('CHAR3D_PORT')=='9977'
    engine=BlenderClient();call=engine.call;work=Path(engine.workspace);cases={}
    fingerprint=hashlib.sha256((ROOT/'engine/commands/walk.py').read_bytes()+(ROOT/'engine/walk_gait.py').read_bytes()).hexdigest()
    try:
        call('scene_info')
        call('run_python',code='''
from engine.commands import walk
original=walk.support_headings
def capture(*a,**kw):
 result=original(*a,**kw)
 walk._benchmark_headings=[r[1] for r in result]
 return result
walk.support_headings=capture
result=True
''')
        source=(ROOT/'tests/walk_benchmark_sample.py').read_text()
        for body in BODIES:
            for speed in (.6,1.,1.6):
                call('open_project',path=f'{body}_rest.blend');call('scene_info')
                nav=call('walk_path',armature='Gait_rig',points=[[0,-10]],speed=speed,start_frame=1,avoid=False)
                measured=call('run_python',code=source+f"\nresult=sample('Gait_rig',{nav!r})")['result']
                summary,steps=summarize(nav,measured,speed=speed)
                key=f'{body}/straight_{speed}';cases[key]=dict(source_fingerprint=fingerprint,fixture_sha256=hashlib.sha256((work/'projects'/f'{body}_rest.blend').read_bytes()).hexdigest(),parameters=dict(points=[[0,-10]],speed=speed),nav=nav,summary=summary,steps=steps,**measured)
                call('save_project',path=f'v12_steady_{body}_{speed}.blend')
                (work/'walk_steady_v12.json').write_text(json.dumps(cases,indent=2)+'\n')
                failures=list(summary['failures'])
                for phase,channels in summary['cruise_phase_asymmetry_deg'].items():
                    for channel in ('knee_deg','ankle_plantarflexion_deg'):
                        if channels[channel] is None or channels[channel]>4:
                            failures.append(phase+'_'+channel+'_asymmetry')
                delta=summary['asymmetry_absolute']['step_length_m'];mean=summary['side_means']['L']['step_length_m']
                if delta is None or delta>max(.02,.03*abs(mean or 0)):failures.append('step_length_asymmetry')
                for side in 'LR':
                    for phase,limits in {'pre_swing':(30,40),'toe_off':(35,45)}.items():
                        value=summary['cruise_phase_means'][side][phase]['knee_deg']
                        if value is None or not limits[0]<=value<=limits[1]:failures.append(side+'_'+phase+'_envelope')
                    if summary['swing_metrics'][side]['mid_swing_min_toe_clearance_m']<.01:failures.append(side+'_clearance')
                cases[key]['target_failures']=failures
                print(key,'P0',failures or 'PASS',json.dumps(summary['cruise_phase_means']),flush=True)
        (work/'walk_steady_v12.json').write_text(json.dumps(cases,indent=2)+'\n')
        assert all(not c['target_failures'] for c in cases.values()),{k:c['target_failures'] for k,c in cases.items() if c['target_failures']}
        print('STEADY P0 ALL THREE BODIES / THREE SPEEDS OK',flush=True)
    finally:engine.stop()


if __name__=='__main__':main()
