"""Matched Eevee footwear weight review; original/new weights on identical poses."""
import json,os,re,sys,time,hashlib,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from mcp_server.blender_client import BlenderClient
from walk_round8_review import montage
QA='''
import os,sys
sys.path.insert(0,os.environ['CHAR3D_QA_SCRIPTS'])
import qa_check
rig=bpy.data.objects['Shoe_rig']
# Full body/skin QA is retained by walk_round14_asset_checks on all three
# benchmark bodies. This catalogue matrix adds shoe/pants QA plus Eevee
# inspection of the exposed skin/collar, without repeating head/torso QA.
result=qa_check.run(objects=[o.name for o in rig.children_recursive if o.type=='MESH' and not o.hide_render and o.get('c3d_garment_category') in ('shoes','bottom')],profile='render')
'''
CAPTURE='''
from engine.commands import mpfb
original=mpfb._rigid_sole_weights
mpfb._review_weights={}
def capture(parts,rig):
 old={o.name:[[(o.vertex_groups[g.group].name,g.weight) for g in v.groups] for v in o.data.vertices] for o in parts if o.get('c3d_garment_category')=='shoes'}
 result=original(parts,rig)
 new={o.name:[[(o.vertex_groups[g.group].name,g.weight) for g in v.groups] for v in o.data.vertices] for o in parts if o.name in old}
 mpfb._review_weights={'v13':old,'v16':new}
 return result
mpfb._rigid_sole_weights=capture

from engine.commands import render as preview
if not hasattr(preview,'_r14_original_setup'):
 preview._r14_original_setup=preview._setup_engine
 def shoe_setup(sc,engine):
  preview._r14_original_setup(sc,engine)
  if engine=='eevee' and sc.camera and sc.camera.name.startswith('ShoeReviewCamera'):
   sc.eevee.taa_render_samples=4
   sc.eevee.shadow_ray_count=1
   sc.eevee.shadow_step_count=4
   sc.eevee.use_raytracing=False
   for o in sc.objects:
    if o.type=='LIGHT' and hasattr(o.data,'use_shadow_jitter'):o.data.use_shadow_jitter=False
 preview._setup_engine=shoe_setup
result={'eevee_samples':4,'shadow_ray_count':1,'shadow_step_count':4,'resolution':[512,512],'threads':bpy.context.scene.render.threads}

result=True
'''
SET_WEIGHTS='''
from engine.commands import mpfb
for name,vertices in mpfb._review_weights[LABEL].items():
 o=bpy.data.objects[name]
 for g in o.vertex_groups:g.remove(list(range(len(o.data.vertices))))
 for i,weights in enumerate(vertices):
  for n,w in weights:
   group=o.vertex_groups.get(n) or o.vertex_groups.new(name=n)
   group.add([i],w,'REPLACE')
bpy.context.view_layer.update()
result=True
'''
CAMERA='''
from engine.commands import anim
from mathutils import Vector
rig=bpy.data.objects['Shoe_rig'];sm=anim.semantic_map(rig);sc=bpy.context.scene
sc.frame_set(FRAME)
foot=rig.matrix_world @ rig.pose.bones[sm['foot.L']].matrix
rest=rig.matrix_world @ rig.data.bones[sm['foot.L']].matrix_local
fw=foot.to_quaternion() @ rest.to_quaternion().inverted() @ Vector((0,-1,0));fw.z=0;fw.normalize()
centre=foot.translation+fw*.045;centre.z=.105
axis=Vector((-fw.y,fw.x,0))
if ANGLE=='three_quarter':axis=(axis-fw*.8).normalized()
cam=sc.objects.get('ShoeReviewCamera')
if cam is None:
 cam=bpy.data.objects.new('ShoeReviewCamera',bpy.data.cameras.new('ShoeReviewCamera'));sc.collection.objects.link(cam)
cam.data.type='ORTHO';cam.data.ortho_scale=.52
cam.location=centre+axis*2+Vector((0,0,.35));cam.rotation_euler=(centre-cam.location).to_track_quat('-Z','Y').to_euler();sc.camera=cam
sc.render.resolution_x=512;sc.render.resolution_y=512;sc.render.resolution_percentage=100
sc.eevee.taa_render_samples=8
result=True
'''

def cache_signature(catalog):
 files=('engine/commands/mpfb.py','engine/commands/walk.py','engine/commands/footlock.py','engine/commands/anim.py','engine/rigid_sole.py','engine/shoe_contact.py')
 return dict(schema=1,physics={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files},
             camera=hashlib.sha256(CAMERA.encode()).hexdigest(),catalog=catalog,
             build=dict(gender=1,age=32,hair=None,face=False),route=[[0,-2.5]],resolution=[512,512])

def valid_png(path):
 try:
  header=path.read_bytes()[:24]
  if header[:8]!=b'\x89PNG\r\n\x1a\n' or struct.unpack('>II',header[16:24])!=(512,512):return False
  import av
  with av.open(str(path)) as stream:next(stream.decode(video=0))
  return True
 except Exception:return False

def main():
 assert os.environ['CHAR3D_PORT']=='9977';c=BlenderClient();w=Path(c.workspace);records={};paths=[];labels=[];began=time.perf_counter()
 try:
  c.call('scene_info');catalog=c.call('mpfb_assets');meta=catalog['clothing_metadata'];all_shoes=catalog['clothing_categories'].get('shoes',[])
  requested=[n for n in ('shoes01','shoes02','shoes03','shoes04','shoes05','shoes06') if n in all_shoes]
  missing=[]
  for kind,pattern in [('flats','flats'),('sneaker','sneaker|trainer'),('ankle_boot','ankle.*boot')]:
   found=next((n for n in all_shoes if re.search(pattern,n+' '+str(meta.get(n,{}).get('display_name',''))+' '+str(meta.get(n,{}).get('tags',[])),re.I)),None)
   if found and found not in requested:requested.append(found)
   if not found:missing.append(kind)
  trousers=[n for n,m in meta.items() if m['category']=='pants' and not re.search('short|brief|capri',n,re.I)]
  if not trousers:trousers=[n for n,m in meta.items() if m['category']=='bottom' and 'pant' in n]
  pants=next((n for n in trousers if 'jeans' in n),trousers[0] if trousers else None)
  assert pants,'Long trousers not installed'
  catalog_record=dict(shoes=all_shoes,requested=requested,pants=pants,unavailable_categories=missing)
  (w/'shoe_catalog.json').write_text(json.dumps(catalog_record,indent=2))
  signature=cache_signature(catalog_record);stamp=w/'shoe_render_cache.json'
  resume='--resume' in sys.argv
  if resume:assert stamp.exists() and json.loads(stamp.read_text())==signature,'Unverified/stale footwear render cache'
  stamp.write_text(json.dumps(signature,indent=2))
  c.call('run_python',code=CAPTURE)
  for rig in ('game_engine','mixamo'):
   for shoe in requested:
    key=rig+'/'+shoe;record=dict(images=[],errors=[]);records[key]=record
    try:
     c.call('new_scene',fps=24)
     built=c.call('create_realistic_human',name='Shoe',gender=1,age=32,rig=rig,clothes=[pants,shoe],hair=None,face=False)
     record['build']=built
     nav=c.call('walk_path',armature=built['armature'],points=[[0,-2.5]],start_frame=1,avoid=False)
     # Choose one full mid-route support and its actual strike/release.
     events=[e for e in nav['support_events'] if e['side']=='L'];e=next((e for e in events if e['land']>20),events[0]);land=e['land']
     following=next((v for v in events if v['land']>land),None)
     release=following['lift'] if following else max(land+1,nav['frames'][1]-8)
     profile=c.call('run_python',code=f'''
import math
from engine.commands import anim,walk
from engine.commands.footlock import _legs,_sole_points
rig=bpy.data.objects['Shoe_rig'];sm=anim.semantic_map(rig);mw=rig.matrix_world
neutral=walk._terrain_forward(rig,sm).normalized();axis=neutral.cross(Vector((0,0,1)))
fr=mw @ rig.data.bones[sm['foot.L']].matrix_local;sr=mw @ rig.data.bones[sm['shin.L']].matrix_local
def signed(a,b,axis):
 a=a-axis*a.dot(axis);b=b-axis*b.dot(axis)
 return math.degrees(math.atan2(axis.dot(a.cross(b)),a.dot(b)))
reference=signed(fr.translation-sr.translation,neutral,axis);values=[]
for f in range({land},{release}+1):
 bpy.context.scene.frame_set(f)
 foot=mw @ rig.pose.bones[sm['foot.L']].matrix;shin=mw @ rig.pose.bones[sm['shin.L']].matrix
 fw=foot.to_quaternion() @ fr.to_quaternion().inverted() @ neutral
 a=Vector((fw.x,fw.y,0)).normalized().cross(Vector((0,0,1)))
 values.append(dict(frame=f,plantarflexion_deg=reference-signed(foot.translation-shin.translation,fw,a)))
result=values
''')['result']
     mid=min(profile,key=lambda x:x['plantarflexion_deg'])['frame']
     frames={'heel_strike':land,'mid_stance_max_dorsiflexion':mid,'toe_off':release}
     extreme=max(profile,key=lambda x:x['plantarflexion_deg'])['frame']
     if extreme not in frames.values():frames['max_plantarflexion']=extreme
     record['ankle_profile']=profile
     record['nav']=nav;record['frames']=frames
     c.call('set_lighting',preset='studio',subject=[built['armature']])
     c.call('save_project',path=f'shoe_v16_{rig}_{shoe}.blend')
     for phase,f in frames.items():
      qa={}
      for angle in ('side','three_quarter'):
       c.call('run_python',code=CAMERA.replace('FRAME',repr(f)).replace('ANGLE',repr(angle)))
       pair={label:w/'renders'/f'shoe_{rig}_{shoe}_{phase}_{angle}_{label}_f{f:04d}.png' for label in ('v13','v16')}
       cached=resume and all(valid_png(p) for p in pair.values())
       for label in ('v13','v16'):
        c.call('run_python',code=SET_WEIGHTS.replace('LABEL',repr(label)))
        if angle=='side':qa[label]=c.call('run_python',code=QA)['result']
        output=str(pair[label]) if cached else c.call('render_frames',frames=[f],camera='scene',size=512,engine='eevee',prefix=f'shoe_{rig}_{shoe}_{phase}_{angle}_{label}')['frames'][0]['path']
        record['images'].append(dict(path=output,phase=phase,angle=angle,label=label,frame=f,cached=cached))
        paths.append(output);labels.append(f"{shoe} / {'game' if rig=='game_engine' else rig}\n{phase}\n{angle} / {label}")
      def categories(q):return {re.sub(r'\(\d+ overlapping coplanar tri pairs\)','(coplanar)',s) for s in q['errors']}
      added=sorted(categories(qa['v16'])-categories(qa['v13']))
      record.setdefault('qa',{})[phase]=dict(before=qa['v13'],after=qa['v16'],new_error_categories=added)
      record['errors'].extend(phase+': '+s for s in added)
     record['pass']=not record['errors']
    except Exception as exc:record['errors'].append(str(exc));record['pass']=False
    if record['images']:
     montage([x['path'] for x in record['images']],
             [f"{shoe} / {'game' if rig=='game_engine' else rig}\n{x['phase']}\n{x['angle']} / {x['label']}" for x in record['images']],
             w/f'shoe_review_{rig}_{shoe}.png','4x','256x256+3+10')
    (w/'shoe_visuals.json').write_text(json.dumps(dict(seconds=time.perf_counter()-began,cases=records),indent=2))
    print(key,len(record['images']),'images',record['errors'],flush=True)
  if paths:montage(paths,labels,w/'walk_shoe_weights_v13_v16.png','8x','256x256+3+10')
  assert all(r['pass'] for r in records.values()),'See shoe_visuals.json'
  print('SHOE EEVEE MATRIX FINISHED',len(paths),time.perf_counter()-began,flush=True)
 finally:c.stop()
if __name__=='__main__':main()
