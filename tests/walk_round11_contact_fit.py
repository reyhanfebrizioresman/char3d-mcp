"""Cached-pose rigid-contact feasibility diagnostic; no keys or asset edits.

This tests constant pitch/roll/Z fits to the OBSERVED skinned outsole over one
flat contact. It is not a proof about all possible alternative IK solutions.
"""
import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mcp_server.blender_client import BlenderClient


def main():
    assert os.environ.get('CHAR3D_PORT')=='9977'
    engine=BlenderClient();call=engine.call;work=Path(engine.workspace);report={}
    try:
        call('scene_info')
        cases=json.loads((work/'walk_benchmark_v13.json').read_text())['cases']
        for body in ('male','female_short','male_tall_heavy'):
            c=cases[body+'/straight_1.0'];rows=c['rows'];first=rows[0]['frame']
            candidates=[]
            for side in 'LR':
                for a,b in c['nav']['foot_lock']['contacts'][side]:
                    if a<30 or b-a<3:continue
                    feet=[rows[f-first]['feet'][side] for f in range(a,b+1)]
                    span=max(p['contact_regions_m'][r] for p in feet for r in ('heel','ball'))-min(p['mesh_low_m'] for p in feet)
                    candidates.append((span,side,a,b))
            _,side,a,b=max(candidates)
            call('open_project',path=c['project']);call('scene_info')
            report[body]=call('run_python',code=f'''
import math,numpy as np
from engine.shoe_contact import calibrate,vertices
from engine.commands import anim
rig=bpy.data.objects['Gait_rig'];sm=anim.semantic_map(rig);patches=calibrate(rig)
hidden=[o for o in bpy.context.scene.objects if o.type=='MESH' and not o.hide_viewport and o.get('c3d_garment_category')!='shoes']
for o in hidden:o.hide_viewport=True
frames=[]
for f in range({a},{b}+1):
 bpy.context.scene.frame_set(f)
 ankle=(rig.matrix_world @ rig.pose.bones[sm['foot.'+{side!r}]].matrix).translation
 frame=[]
 for name,sides in patches:
  ids=sides[{side!r}]
  if not ids['all']:continue
  xyz=vertices(bpy.data.objects[name])-np.array(ankle)
  # World XY tilt search spans the same pitch/roll plane at any fixed yaw.
  frame.append((xyz[ids['all']],{{k:xyz[v] for k,v in ids['regions'].items() if k in ('heel','ball')}},ankle.z))
 frames.append(frame)
def fit(pitch,roll):
 p,r=map(math.radians,(pitch,roll));axis=np.array([math.cos(p)*math.sin(r),math.sin(p),math.cos(p)*math.cos(r)])
 low=float('inf');high=-float('inf')
 for frame in frames:
  mins={{'heel':float('inf'),'ball':float('inf')}}
  for xyz,areas,z in frame:
   low=min(low,float((xyz @ axis).min())+z)
   for k,points in areas.items():mins[k]=min(mins[k],float((points @ axis).min())+z)
  high=max(high,*mins.values())
 dz=max(-.00194,min(.00194,-(high+low)/2))
 return dict(pitch_deg=pitch,roll_deg=roll,required_band_m=high-low,
             bounded_z_m=dz,bounded_contact_error_m=max(high+dz,-low-dz),
             offset_interval_m=[-.002-low,.002-high],feasible_2mm=high-low<=.004)
neutral=fit(0,0);best=best_bounded=neutral
for pitch in np.linspace(-10,10,81):
 for roll in np.linspace(-5,5,41):
  candidate=fit(float(pitch),float(roll))
  if candidate['required_band_m']<best['required_band_m']:best=candidate
  if candidate['bounded_contact_error_m']<best_bounded['bounded_contact_error_m']:best_bounded=candidate
for o in hidden:o.hide_viewport=False
result=dict(side={side!r},contact=[{a},{b}],neutral=neutral,best=best,best_bounded=best_bounded,
 limitation='Rigidly reorienting already observed deformed mesh. Does not re-solve skinning/IK or prove global pose infeasibility.')
''')['result']
            print(body,report[body],flush=True)
        (work/'rigid_contact_fit.json').write_text(json.dumps(report,indent=2)+'\n')
    finally:engine.stop()


if __name__=='__main__':main()
