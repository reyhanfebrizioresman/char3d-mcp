"""Visual-first world fixtures on port 9998; one Blender, local assets, no downloads.

--stills builds four worlds with two MPFB humans, renders hero/medium/close.
--clips makes two 3-second Eevee clips in the SAME engine and encodes with PyAV.
--only lantern/serpent/whale/islands; --reuse keeps saved art-direction milestones.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from mcp_server.blender_client import BlenderClient
from providers.director.world import offline
from nature_visuals import setup,py
WORK=ROOT/'output';SHEETS=WORK/'world_sheets'/'quality_v2'
CASES={'lantern':'lantern lake','serpent':'serpent gateway','whale':'whale sunset','islands':'floating islands'}


def connect():
 if os.environ.get('CHAR3D_PORT')!='9998':raise SystemExit('Use CHAR3D_PORT=9998')
 os.environ['CHAR3D_ALLOW_PYTHON']='1';os.environ['XDG_CACHE_HOME']=str(WORK/'cache');os.environ['MESA_SHADER_CACHE_DIR']=str(WORK/'cache/mesa');os.environ['LP_NUM_THREADS']='8'
 SHEETS.mkdir(parents=True,exist_ok=True)
 return BlenderClient()


def build(c,name):
 c.call('scene_info');c.call('new_scene',frame_end=96);setup(c)
 r=c.call('script_to_scene',script={'characters':[
  {'id':'Ana','gender':0,'age':28,'race':{'asian':1},'hair':'ponytail01','clothes':['female_casualsuit01','shoes01']},
  {'id':'Budi','gender':1,'age':30,'race':{'asian':1},'hair':'short02','clothes':['male_casualsuit01','shoes01']}],
  'beats':[{'say':'Ana','text':'Indah sekali!'}, {'say':'Budi','text':'Mari bersama.'}]},subtitles=False,sound=False,seed=17,lighting='soft')
 assert all(x['realistic'] for x in r['characters'].values()),r['warnings']
 for shot in c.call('list_shots')['shots']:c.call('delete_shot',name=shot['camera'])
 recipe=offline(CASES[name],17)['recipe']
 result=c.call('compose_world',recipe=recipe)
 place(c,recipe)
 c.call('set_lighting',preset='soft',subject=['Ana_rig','Budi_rig'])
 for character in ('Ana','Budi'):
  c.call('set_expression',character=character+'_rig',expression='smile',strength=.35)
 c.call('set_timeline',frame_start=1,frame_end=96)
 c.call('export_asset',path='world_v2_'+name+'.glb',objects=[result['root']])
 c.call('save_world',name='showcase-'+name)
 c.call('save_project',path='world_v2_'+name+'.blend')
 return result


def place(c,recipe):
 for ident,offset in zip(('Ana_rig','Budi_rig'),recipe['stage']['standing']):
  c.call('transform_object',name=ident,location=[a+b for a,b in zip(recipe['stage']['location'],offset)])


def still(c,name,camera,frame):
 start=time.perf_counter()
 r=c.call('render_preview',camera=camera,engine='eevee',width=512,height=288,frame=frame,filename=f'world_v2_{name}.png')
 print('STILL',name,round(time.perf_counter()-start,2),flush=True)
 return r['path']


def sheets(results):
 from PIL import Image,ImageDraw
 w,h=512,288;canvas=Image.new('RGB',(w*len(results),h*3+52),'#111b22');draw=ImageDraw.Draw(canvas)
 for col,(name,paths) in enumerate(results.items()):
  draw.text((col*w+16,16),name.upper()+' / ORIGINAL WORLD',fill='#f2cf99')
  for row,path in enumerate(paths):
   with Image.open(path) as im:canvas.paste(im.resize((w,h)),(col*w,52+row*h))
 canvas.save(SHEETS/'showcases.png')
 for col,name in enumerate(results):
  canvas.crop((col*w,0,(col+1)*w,h*3+52)).save(SHEETS/(name+'.png'))


def clip(c,name,hero,resume=False):
 import av
 from PIL import Image
 path=WORK/'renders'/f'world_v2_{name}_preview.mp4'
 # Trusted test harness, not recipe input: hold the finally-protected look
 # context across the short clip, avoiding per-frame material/volume copies.
 frames=py(c,f"""import os,time
from engine.commands.render import _setup_engine
from engine.commands.cinematic import applied_look
from engine.commands.render_style import applied_style
sc=bpy.context.scene
saved=(sc.camera,sc.render.engine,sc.render.resolution_x,sc.render.resolution_y,sc.render.resolution_percentage,sc.render.filepath,sc.frame_current,sc.eevee.taa_render_samples)
markers=[(m,m.camera) for m in sc.timeline_markers if m.camera]
paths=[]
try:
 for m,_ in markers:m.camera=None
 sc.camera=bpy.data.objects[{hero!r}]
 _setup_engine(sc,'eevee');sc.eevee.taa_render_samples=8
 sc.render.resolution_x=384;sc.render.resolution_y=216;sc.render.resolution_percentage=100
 sc.render.image_settings.file_format='PNG'
 with applied_look(sc,camera=sc.camera),applied_style(sc):
  for index in range(36):
   sc.frame_set(1+index*2)
   target=os.path.join({str(WORK/'renders')!r},'world_v2_{name}_clip_'+str(index).zfill(3)+'.png')
   if not ({resume!r} and os.path.isfile(target)):
    sc.render.filepath=target;bpy.ops.render.render(write_still=True)
   paths.append(target)
finally:
 sc.camera,sc.render.engine,sc.render.resolution_x,sc.render.resolution_y,sc.render.resolution_percentage,sc.render.filepath,frame,sc.eevee.taa_render_samples=saved
 for m,camera in markers:m.camera=camera
 sc.frame_set(frame)
result=paths
""")
 container=av.open(str(path),'w');stream=container.add_stream('libx264',rate=12);stream.width=384;stream.height=216;stream.pix_fmt='yuv420p';stream.options={'crf':'20'}
 try:
  for index,filename in enumerate(frames):
   with Image.open(filename) as im:v=av.VideoFrame.from_image(im.convert('RGB'))
   v.pts=index
   for packet in stream.encode(v):container.mux(packet)
  for packet in stream.encode():container.mux(packet)
 finally:container.close()
 canvas=Image.new('RGB',(384*3,240*2),'#111b22')
 from PIL import ImageDraw
 draw=ImageDraw.Draw(canvas)
 for i,index in enumerate((0,7,14,21,28,35)):
  x=(i%3)*384;y=(i//3)*240
  with Image.open(frames[index]) as im:canvas.paste(im.convert('RGB'),(x,y+24))
  draw.text((x+10,y+6),f'{name.upper()} / {index/12:.2f} s',fill='#f2cf99')
 canvas.save(SHEETS/(name+'_motion.png'))
 samples=py(c,f"""import json
from mathutils import Vector
sc=bpy.context.scene;saved_frame=sc.frame_current
parts=sorted((o for o in sc.objects if o.type=='MESH' and o.get('c3d_world') and
    (('pectoral_' in o.name or 'fluke_' in o.name) if {name!r}=='whale' else 'rising_lanterns' in o.name)),key=lambda o:o.name)
samples=[]
try:
 for frame in (1,13,25,37,49,61,71):
  sc.frame_set(frame);centers={{}}
  for o in parts[:4]:
   e=o.evaluated_get(bpy.context.evaluated_depsgraph_get());m=e.to_mesh()
   centers[o.name]=list(e.matrix_world@(sum((v.co for v in m.vertices),Vector())/len(m.vertices)))
   e.to_mesh_clear()
  samples.append({{'frame':frame,'centers':centers}})
finally:sc.frame_set(saved_frame)
result=samples
""")
 metrics=WORK/'world_motion_v2.json';record=json.loads(metrics.read_text()) if metrics.exists() else {}
 record[name]=samples;metrics.write_text(json.dumps(record,indent=2))
 print('CLIP DONE',name,str(path),flush=True)
 return str(path)


if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--refresh',action='store_true');p.add_argument('--resume-clips',action='store_true');p.add_argument('--export',action='store_true');p.add_argument('--view',choices=['hero','medium','close','portraits']);p.add_argument('--stills',action='store_true');p.add_argument('--clips',action='store_true');p.add_argument('--reuse',action='store_true');p.add_argument('--only',choices=CASES);args=p.parse_args()
 c=connect();target=WORK/'world_visuals_v2.json';results=json.loads(target.read_text()) if target.exists() else {}
 try:
  for name in ([args.only] if args.only else CASES):
   if args.reuse or args.refresh:
    c.call('scene_info');c.call('open_project',path='world_v2_'+name+'.blend');hero='WorldHero'
    if args.refresh:
     recipe=offline(CASES[name],17)['recipe'];report=c.call('compose_world',recipe=recipe);place(c,recipe);hero=report['hero_camera'];results.setdefault(name,{})['cost']=report['cost']
     c.call('save_world',name='showcase-'+name)
   else:
    report=build(c,name);hero=report['hero_camera'];results.setdefault(name,{})['cost']=report['cost']
   cameras=py(c,"result={key:next(o.name for o in bpy.context.scene.objects if o.type=='CAMERA' and o.get('c3d_world') and o.name.startswith(prefix)) for key,prefix in [('hero','WorldHero'),('medium','WorldMediumHint'),('close','WorldCloseHint')]}")
   hero=cameras['hero']
   c.call('set_lighting',preset='soft',subject=['Ana_rig','Budi_rig'])
   c.call('save_project',path='world_v2_'+name+'.blend')
   if args.export:
    root=py(c,"result=next(o.name for o in bpy.context.scene.objects if o.get('c3d_world_root'))")
    c.call('export_asset',path='world_v2_'+name+'.glb',objects=[root])
   paths=results.get(name,{}).get('images',[])
   if args.stills:
    previous={label:path for label,path in zip(('hero','medium','close'),paths)}
    for label,camera,frame in [(label,cameras[label],60 if name=='whale' and label=='hero' else 12) for label in ('hero','medium','close')]:
     if args.view is None or args.view==label or args.view=='portraits' and label!='hero':previous[label]=still(c,name+'_'+label,camera,frame)
    paths=[previous[label] for label in ('hero','medium','close') if label in previous]
    results.setdefault(name,{})['images']=paths
   if args.clips and name in ('lantern','whale'):results.setdefault(name,{})['clip']=clip(c,name,hero,args.resume_clips)
   target.write_text(json.dumps(results,indent=2))
   sheets({n:r['images'] for n,r in results.items() if r.get('images')})
 finally:c.stop()
