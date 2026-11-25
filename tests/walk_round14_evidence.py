"""Matched v13/v16 native contact/touchdown and multi-angle asset review."""
import json,math,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from mcp_server.blender_client import BlenderClient
from walk_round11_evidence import CAMERA
from walk_round8_review import montage
work=Path(os.environ['CHAR3D_WORKSPACE']);client=BlenderClient();call=client.call
reports={v:json.loads((work/f'walk_benchmark_{v}.json').read_text()) for v in ('v13','v16')}
for c in reports['v13']['cases'].values():c['project']=str(work/'baseline/projects'/Path(c['project']).name)
COLOR='''
from engine.shoe_contact import calibrate
rig=bpy.data.objects['Gait_rig'];patches=calibrate(rig)
colors={'heel':(.15,.35,.95,1),'arch':(.65,.25,.75,1),'ball':(.1,.7,.25,1),'toe':(1,.4,.06,1)}
for name,sides in patches:
 ob=bpy.data.objects[name];region_vertices={k:set(v) for k,v in sides['L']['regions'].items()};slots={}
 for k,col in colors.items():
  mat=bpy.data.materials.new(k);mat.diffuse_color=col;ob.data.materials.append(mat);slots[k]=len(ob.data.materials)-1
 for face in ob.data.polygons:
  hits={k:sum(i in ids for i in face.vertices) for k,ids in region_vertices.items()};k=max(hits,key=hits.get)
  if hits[k]:face.material_index=slots[k]
result=True
'''
def camera(foot,min_scale=.5):
 fw=[b-a for a,b in zip(foot['heel_m'],foot['toe_m'])];fw[2]=0;length=math.hypot(*fw[:2]);fw=[v/length for v in fw]
 centre=[(a+b)/2 for a,b in zip(foot['heel_m'],foot['toe_m'])];centre[2]=.06
 call('run_python',code=CAMERA.replace('SCALE',repr(max(min_scale,1.8*length))).replace('CENTRE',repr(centre)).replace('FORWARD',repr(fw)).replace('AXIS',repr([-fw[1],fw[0],0])))
def touchdown():
 paths=[];labels=[]
 for label in ('v13','v16'):
  c=reports[label]['cases']['male/straight_1.0'];land=next(s['land'] for s in c['steps'] if s['side']=='L' and s['complete_cycle'] and s['land']>20)
  foot=c['rows'][land-c['rows'][0]['frame']]['feet']['L'];call('open_project',path=c['project']);call('scene_info');camera(foot,min_scale=.65)
  frames=list(range(land-3,land+3));images=call('render_frames',frames=frames,camera='scene',objects=['Gait_rig'],size=512,engine='workbench',prefix='r14_touchdown_'+label)['frames']
  for f,image in zip(frames,images):
   paths.append(image['path']);z=c['rows'][f-c['rows'][0]['frame']]['feet']['L']['contact_regions_m']['heel']
   labels.append(f'{label} F{f} / {f-land:+d} strike\nheel {z*1000:+.2f} mm')
 montage(paths,labels,work/'walk_touchdown_v13_v16.png','6x2','512x320+4+12')

try:
 began=time.perf_counter();call('scene_info');paths=[];labels=[]
 if '--touchdown-only' in sys.argv:
  touchdown()
  (work/'touchdown_framing_fix.json').write_text(json.dumps(dict(reason='Keep full heel visible at F-3; no video or benchmark rerun',min_ortho_scale_m=.65,seconds=time.perf_counter()-began)))
  print('TOUCHDOWN FRAMING FIXED',time.perf_counter()-began,flush=True)
  raise SystemExit(0)
 environment=call('run_python',code="import os,sys\nsys.path.insert(0,os.environ['CHAR3D_QA_SCRIPTS'])\nimport env_report\nresult=env_report.run()")['result']
 (work/'blender_environment_v16.json').write_text(json.dumps(environment,indent=2))
 for body in ('male','male_tall_heavy'):
  for phase in ('heel_strike','mid_stance','pre_swing'):
   for label in ('v13','v16'):
    c=reports[label]['cases'][body+'/straight_1.0'];step=next(s for s in c['steps'] if s['side']=='L' and s['complete_cycle'] and s['land']>20)
    f=step['land'] if phase=='heel_strike' else step['phases'][phase]['frame'];foot=c['rows'][f-c['rows'][0]['frame']]['feet']['L']
    call('open_project',path=c['project']);call('scene_info');camera(foot);call('run_python',code=COLOR)
    image=call('render_frames',frames=[f],camera='scene',objects=['Gait_rig'],size=512,engine='workbench',prefix=f'r14_contact_{body}_{label}_{phase}')['frames'][0]['path']
    r=foot['contact_regions_m'];paths.append(image);labels.append(f'{body} {label} L {phase} F{f}\nheel {r["heel"]*1000:+.2f} / ball {r["ball"]*1000:+.2f} / toe {r["toe"]*1000:+.2f} mm\nBlue heel / green ball / orange toe; purple arch excluded')
 montage(paths,labels,work/'walk_contact_regions_v13_v16.png','2x6','512x320+4+12')
 touchdown()
 qa={}
 for body in ('male','female_short','male_tall_heavy'):
  c=reports['v16']['cases'][body+'/straight_1.0'];step=next(s for s in c['steps'] if s['complete_cycle']);f=step['phases']['peak_swing']['frame']
  call('open_project',path=c['project']);call('scene_info');qa[body]={}
  for mode in ('random','wire'):
   dest=work/'renders'/f'qa_v16_{body}_{mode}.png'
   qa[body][mode]=call('run_python',code=f'''
import sys,os
sys.path.insert(0,os.environ['CHAR3D_QA_SCRIPTS'])
import review_shots
bpy.context.scene.frame_set({f})
rig=bpy.data.objects['Gait_rig'];objects=[o.name for o in bpy.context.scene.objects if o.type=='MESH' and not o.hide_render and any(m.type=='ARMATURE' and m.object==rig for m in o.modifiers)]
result=review_shots.run(objects=objects,out={str(dest)!r},views=['front','right','back','three_quarter'],mode={mode!r},res=256)
''')['result']
 (work/'qa_visual_sheets_v16.json').write_text(json.dumps(qa,indent=2))
 (work/'evidence_timing.json').write_text(json.dumps(dict(seconds=time.perf_counter()-began)))
 print('CONTACT / TOUCHDOWN / MULTI-ANGLE QA RENDERED',time.perf_counter()-began,flush=True)
finally:client.stop()
