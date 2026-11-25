"""Independent shod/unshod MPFB coverage; finish every rig even after failures."""
import json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from mcp_server.blender_client import BlenderClient
from walk_gait_checks import check

def main():
 assert os.environ['CHAR3D_PORT']=='9977';c=BlenderClient();w=Path(c.workspace);report={}
 if '--resume-failed' in sys.argv:report=json.loads((w/'rig_shod_unshod.json').read_text())
 try:
  c.call('scene_info')
  for rig in ('game_engine','rigify','mixamo','default','cmu_mb'):
   for shod in (False,True):
    key=rig+('/shod' if shod else '/unshod');began=time.perf_counter()
    if key in report and not report[key]['failures']:continue
    try:
     c.call('new_scene',fps=24)
     h=c.call('create_realistic_human',name='Sign',gender=1,age=32,rig=rig,hair=None,clothes=['shoes03'] if shod else [],face=False)
     nav=c.call('walk_path',armature=h['armature'],points=[[0,-5]],start_frame=1,avoid=False);v=check(c.call,h['armature'],nav);fail=[]
     v['native_hold_m']=c.call('run_python',code=f'''
import numpy as np
from engine.shoe_contact import vertices
rig=bpy.data.objects[{h['armature']!r}]
meshes=[o for o in rig.children_recursive if o.type=='MESH' and not o.hide_render]
bpy.context.scene.frame_set({nav['frames'][1]})
anchors={{o.name:vertices(o) for o in meshes}};maximum=0.
for f in range({nav['frames'][1]}-3,{nav['frames'][1]}+1):
 bpy.context.scene.frame_set(f)
 for o in meshes:
  points=vertices(o)
  if len(points)!=len(anchors[o.name]):raise ValueError('Changing hold topology')
  if len(points):maximum=max(maximum,float(np.linalg.norm(points-anchors[o.name],axis=1).max()))
result=maximum
''')['result']
     # The visible four-frame hold is evaluated on native meshes. Keep raw
     # control-bone rotation diagnostics, including unweighted Rigify helpers.
     for field,limit in [('flat_drift_m',.005),('toe_support_drift_m',.005),('penetration_m',.002),('flat_floor_m',.002),('flat_rotation_rad',.002),('knee_step_deg',17.5),('destination_error_m',.01),('joint_hold_m',.001),('native_hold_m',.001)]:
      if v[field]>limit:fail.append(field)
     if shod and v['mesh_penetration_m']>.002:fail.append('mesh_penetration_m')
     for s in 'LR':
      if not v['progression_by_side_deg'][s] or not all(5<=a<=10 for a in v['progression_by_side_deg'][s]):fail.append(s+'_FPA')
     report[key]=dict(nav=nav,measured=v,failures=fail,seconds=time.perf_counter()-began)
    except Exception as e:report[key]=dict(error=str(e),failures=['exception'])
    (w/'rig_shod_unshod.json').write_text(json.dumps(report,indent=2));print(key,report[key]['failures'] or 'PASS',flush=True)
  assert all(not v['failures'] for v in report.values()),'See rig_shod_unshod.json'
 finally:c.stop()
if __name__=='__main__':main()
