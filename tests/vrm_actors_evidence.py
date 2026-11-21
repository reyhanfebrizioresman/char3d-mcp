"""Resumable, offline VRM evidence. Only the owned char3d engine on 9976.

Run --phase stills, --phase portraits --actor Nara --look studio_film,
--phase video, --phase qa, --phase sheets. Never starts Blender directly.
"""
import argparse,asyncio,json,os,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
assert os.environ.get('CHAR3D_PORT')=='9976','Evidence owns only port 9976'
assert Path(os.environ['CHAR3D_WORKSPACE']).resolve()==ROOT/'output'
os.environ['CHAR3D_ALLOW_PYTHON']='1'
os.environ.setdefault('MESA_SHADER_CACHE_DIR',str(ROOT/'output/mesa_cache_vrm'))
from mcp_server import server as api
from vrm_actors_checks import SCRIPT
OUT=ROOT/'output/vrm_actors'

async def tool(tool_name,**args):
    print('EVIDENCE',tool_name,flush=True)
    if tool_name=='render_views':
        engine=args.pop('engine_name',args.pop('engine','workbench'))
        size=args.pop('size',320)
        return [await api.run('render_preview',view=view,width=size,height=size,engine=engine,**args)
                for view in ('front','right','back','three_quarter')]
    if tool_name in ('render_preview','render_views','render_frames'):
        if 'engine_name' in args:args['engine']=args.pop('engine_name')
        return await api.run(tool_name,**args)
    return await getattr(api,tool_name)(**args)
async def python(code):return (await tool('run_blender_python',code=code))['result']
class ToolSession:
    async def call_tool(self,name,params=None):
        from mcp.types import CallToolResult,TextContent
        value=await tool(name,**(params or {}))
        return CallToolResult(content=[TextContent(type='text',text=json.dumps(value))])
def save(name,value):(OUT/name).write_text(json.dumps(value,indent=2,default=str))
async def settings():
    await python("""from engine.commands import render
bpy.context.scene.render.threads_mode='FIXED'
bpy.context.scene.render.threads=6
if not getattr(render,'_vrm_samples_override',False):
 original=render._setup_engine
 def setup(scene,engine,_original=original):
  _original(scene,engine)
  if engine=='eevee':scene.eevee.taa_render_samples=8
 render._setup_engine=setup
 render._vrm_samples_override=True
result=True""")
async def contact_sheet(path,items,columns=6,size=256,aspect=1):
    return await python(f"from engine.commands.review_sheet import sheet\nresult=sheet({dict(path=str(path),items=items,columns=columns,size=size,aspect=aspect)!r})")

async def portrait_camera(rig,angle):
    cam=await tool('camera_shot',subject=[rig],shot='close_up',angle=angle,lens=85,
                   depth_of_field=False,avoid_occlusion=False,start_frame=1,end_frame=24,name='Portrait')
    measured=await python(f"""import math
from bpy_extras.object_utils import world_to_camera_view
from engine.commands.face_geometry import FaceGeometry
from engine.commands.gaze import head_frame
r=bpy.data.objects[{rig!r}];sc=bpy.context.scene
sc.render.resolution_x=256;sc.render.resolution_y=256;sc.render.resolution_percentage=100
points=FaceGeometry(r,1.7).points();center=(points['chin']+points['crown'])/2
orient=head_frame(r)[1];a=math.radians({angle})
direction=orient @ Vector((math.sin(a),-math.cos(a),0))
camera=bpy.data.objects[{cam['camera']!r}];camera.animation_data_clear()
distance=(points['crown']-points['chin']).length*1.3*camera.data.lens/camera.data.sensor_width
position=center+direction*distance
matrix=(center-position).to_track_quat('-Z','Y').to_matrix().to_4x4();matrix.translation=position
camera.matrix_world=matrix;bpy.context.view_layer.update()
projected=[world_to_camera_view(sc,camera,p) for p in points['fit']]
box=[min(p.x for p in projected),min(p.y for p in projected),max(p.x for p in projected),max(p.y for p in projected)]
assert min(box[:2])>.02 and max(box[2:])<.98,box
result=dict(angle={angle},face_fit_box=box,distance_m=distance)
""")
    return cam,measured

async def build(args):
    await tool('new_scene',frame_end=2)
    result=await tool('script_to_scene',script=SCRIPT,camera='directed',look='studio_film',style='anime',
                      seed=44,tts_engine='piper',language='id',sound=True,music='warm',subtitles=True)
    save('build.json',result)
    await tool('save_project',path='vrm_actors/kabar_anime.blend')

async def review(args):
    await tool('open_project',path='vrm_actors/kabar_anime.blend');await settings()
    built=json.loads((OUT/'build.json').read_text())
    frames=sorted({min(s['frames'][1],s['frames'][0]+6) for s in built['shots']} |
                  {(s['frames'][0]+s['frames'][1])//2 for s in built['shots']})
    before=await tool('review_scene',level='standard',sheet=True,engine='workbench',size=256,frames=frames)
    save('review_before.json',before)
    fixed=[];seen=set()
    # One targeted round. Preserve the protected seating contacts; a full-scene
    # collision retry cannot resolve a chair envelope by changing root/feet.
    for issue in before['issues']:
        if issue['category'] not in ('readability','camera'):continue
        for action in issue.get('fix',[]):
            key=json.dumps(action,sort_keys=True)
            if key in seen:continue
            seen.add(key)
            result=await tool(action['tool'],**action['args'])
            fixed.append(dict(action,status='applied',result=result))
    await tool('save_project',path='vrm_actors/kabar_anime_fixed.blend')
    after=await tool('review_scene',level='standard',sheet=True,engine='workbench',size=256,frames=frames)
    after.update(before=dict(score=before['score'],scores=before['scores'],contact_sheet=before['contact_sheet']),
                 fixed=fixed,fix_rounds=1,fix_scope='One targeted camera/caption/title round; protected seat contacts retained')
    save('review_after.json',after)

async def stills(args):
    await tool('open_project',path='vrm_actors/kabar_anime_fixed.blend');await settings()
    built=json.loads((OUT/'build.json').read_text())
    # Review fixes may recut; use the actual saved markers after correction.
    shots=await tool('list_shots');save('shots_after.json',shots)
    frames=sorted({min(s['frames'][1],s['frames'][0]+6) for s in shots['shots']} |
                  {(s['frames'][0]+s['frames'][1])//2 for s in shots['shots']})
    for style in (args.style,):
        await tool('render_style',style=style)
        await tool('save_project',path=f'vrm_actors/kabar_{style}_fixed.blend')
        folder=OUT/style;folder.mkdir(exist_ok=True)
        items=[];rendered_count=0
        for frame in frames:
            target=folder/f'f{frame:04d}.png'
            if not target.exists():
                result=await tool('render_frames',frames=[frame],camera='scene',engine='eevee',size=960,subtitles=True,graphics=True)
                shutil.copyfile(result['frames'][0]['path'],target)
                rendered_count+=1
                if args.limit and rendered_count>=args.limit and any(not (folder/f'f{f:04d}.png').exists() for f in frames):return
            items.append(dict(path=str(target),label=f'{style} / frame {frame}',frame=frame))
        save(f'{style}_stills.json',items)
        await contact_sheet(folder/'sheet.png',items,columns=2,size=480,aspect=9/16)
    await tool('open_project',path='vrm_actors/kabar_anime_fixed.blend')
    # Preserve native GLB materials/weights/morphs, verify files separately.
    await tool('export_asset',path='vrm_actors/kabar.glb',objects=[c['rig'] for c in built['characters'].values()],max_influences=4)
    await tool('credits',path='../vrm_actors/CREDITS.txt')

async def portraits(args):
    char=next(c for c in SCRIPT['characters'] if c['id']==args.actor)
    await tool('new_scene',frame_end=2)
    built=await tool('script_to_scene',script={'characters':[char],'beats':[{'do':'pause','seconds':1}]},
                     voice=False,sound=False,music=None,camera='none',life=0,collisions=False)
    rig=built['characters'][args.actor]['rig'];await settings()
    await python(f"rig=bpy.data.objects[{rig!r}]\nfor o in [rig,*rig.children_recursive]:\n if o.animation_data:o.animation_data_clear()\n if o.type=='MESH' and o.data.shape_keys:\n  o.data.shape_keys.animation_data_clear()\n  for k in o.data.shape_keys.key_blocks:k.value=0\nresult=True")
    await tool('apply_pose',armature=rig,pose='relaxed')
    await tool('set_lighting',preset='studio',subject=[rig])
    await tool('cinematic_look',preset=args.look)
    await tool('render_style',style='anime')
    folder=OUT/'portraits_close'/args.actor/args.look;folder.mkdir(exist_ok=True,parents=True)
    expressions=[('neutral',{}),('smile',{}),('neutral',{'jawOpen':1}),('neutral',{'mouthFunnel':1}),('surprised',{}),('eyes_closed',{})]
    names=['neutral','smile','A','O','surprised','blink']
    all_items=[];cameras=[]
    for angle in (0,35,-55):
        await tool('set_expression',character=rig,expression='neutral')
        cam,measured=await portrait_camera(rig,angle);cameras.append(measured)
        items=[]
        # Keep one reversible shader scope across the six poses at this camera.
        # Recompiling identical temporary shaders for every morph is expensive
        # in software Eevee. Nothing is saved while the scope is active.
        await python("""from engine.commands import vrm_render,render_style
sc=bpy.context.scene;sc.render.engine='BLENDER_EEVEE'
sc.render.resolution_x=256;sc.render.resolution_y=256;sc.render.resolution_percentage=100
ctx=vrm_render.applied(sc,render_style.get_config(sc));ctx.__enter__()
bpy.app.driver_namespace['_vrm_evidence_scope']=ctx
result=True""")
        for label,(expression,units) in zip(names,expressions):
            await tool('set_expression',character=rig,expression=expression,units=units or None)
            target=folder/f'{angle}_{label}.png'
            if not target.exists():
                still=await tool('render_preview',camera=cam['camera'],engine='eevee',width=256,height=256,
                                 filename=str(target))
                assert Path(still['path']).is_file()
            items.append(dict(path=str(target),frame=1,label=f'{args.actor} {args.look} {angle}: {label}'))
        await python("bpy.app.driver_namespace.pop('_vrm_evidence_scope').__exit__(None,None,None)\nresult=True")
        await contact_sheet(folder/f'row_{angle}.png',items)
        all_items.extend(items)
    save(f'portraits_{args.actor}_{args.look}.json',all_items)
    save(f'portrait_cameras_{args.actor}_{args.look}.json',cameras)
    # Four-look shader matrix, including style none and animated_film.
    if args.look=='studio_film':
        await tool('set_expression',character=rig,expression='neutral')
        cam,_=await portrait_camera(rig,35)
        items=[]
        for look in ('studio_film','golden_hour','blue_hour','night'):
            await tool('cinematic_look',preset=look)
            for style in ('none','anime','animated_film'):
                await tool('render_style',style=style)
                target=folder/f'matrix_{look}_{style}.png'
                if not target.exists():await tool('render_preview',camera=cam['camera'],engine='eevee',width=256,height=256,filename=str(target))
                items.append(dict(path=str(target),frame=1,label=f'{args.actor}: {look} / {style}'))
        await contact_sheet(folder/'looks.png',items,columns=3)
        save(f'looks_{args.actor}.json',items)

async def normals(args):
    await tool('open_project',path='vrm_actors/kabar_anime.blend');await settings()
    await tool('render_style',style='anime')
    folder=OUT/'normals';folder.mkdir(exist_ok=True)
    before=folder/'native.png';after=folder/'flat_field.png'
    result=await python(f"""from engine.commands import vrm_render,render
original=vrm_render.head_field
try:
 vrm_render.head_field=lambda *args:None
 result=render.render_preview(camera='scene',frame=94,engine='eevee',width=512,height=288,filename={str(before)!r})
finally:vrm_render.head_field=original
""")
    await tool('render_preview',camera='scene',frame=94,engine='eevee',width=512,height=288,filename=str(after))
    await contact_sheet(folder/'comparison.png',[dict(path=str(before),label='Authored mesh normals',frame=94),
                         dict(path=str(after),label='Head-following flat face field',frame=94)],columns=2,size=512,aspect=9/16)
    save('normal_comparison.json',dict(before=str(before),after=str(after),frame=94,samples=8,
                                      method='Same pose/camera/materials; only the temporary skin normal field changes'))

async def performance_views(args):
    report=json.loads((OUT/'e2e.json').read_text())
    await tool('open_project',path='vrm_actors/performance.blend');await settings()
    # Compatibility with earlier evidence fixtures that left an unheld test cup
    # in mid-air. COPY_TRANSFORMS controls the held interval independently.
    held=await python("""from engine.commands.talk import _data_curves
result=[]
for o in bpy.context.scene.objects:
 if o.get('c3d_hold_character'):
  inv=o.matrix_world.inverted()
  floor=-min((inv@child.matrix_world@Vector(p)).z for child in [o,*o.children_recursive] if child.type=='MESH' for p in child.bound_box)
  o.location.z=floor
  for curve in _data_curves(o):
   if curve.data_path=='location' and curve.array_index==2:
    for k in curve.keyframe_points:k.co.y=k.handle_left.y=k.handle_right.y=floor
  result.append(o.name)
""")
    if held:
        meshes=await python(f"result=[c.name for name in {held!r} for c in [bpy.data.objects[name],*bpy.data.objects[name].children_recursive] if c.type=='MESH']")
        await tool('set_material',objects=meshes,color=[.025,.18,.55],roughness=.35,name='EvidenceCupBlue')
    folder=OUT/'performance';folder.mkdir(exist_ok=True)
    items=[]
    for call in report['calls']:
        if call['tool']!='interact':continue
        row=call['result'];frame=row['frames']['contact']
        for angle in (0,90):
            cam=await tool('camera_shot',subject=['Nara_rig','Bayu_rig'],shot='medium_full',angle=angle,
                           depth_of_field=False,avoid_occlusion=False,start_frame=frame,end_frame=frame+1,
                           name=f"Performance_{row['kind']}_{angle}")
            target=folder/f"{row['kind']}_{angle}.png"
            if not target.exists():await tool('render_preview',camera=cam['camera'],frame=frame,engine='eevee',width=512,height=512,filename=str(target))
            items.append(dict(path=str(target),frame=frame,label=f"{row['kind']} / {angle} degrees / f{frame}"))
    if held:
        frame=await python('result=bpy.context.scene.frame_end')
        await tool('apply_pose',armature='Nara_rig',pose='wave',frame=frame,keyframe=True)
        camera=await tool('camera_shot',subject=[held[0]],shot='wide',angle=90,lens=70,
                          depth_of_field=False,avoid_occlusion=False,start_frame=frame,end_frame=frame+1,name='HeldCup')
        await python(f"""p=bpy.data.objects[{held[0]!r}];sc=bpy.context.scene;sc.frame_set({frame})
points=[c.matrix_world@Vector(v) for c in [p,*p.children_recursive] if c.type=='MESH' for v in c.bound_box]
center=Vector(tuple((min(v[i] for v in points)+max(v[i] for v in points))/2 for i in range(3)))
out=center-p.matrix_world.translation;out.z=0
if out.length<.001:out=p.matrix_world.to_3x3().col[0].copy()
out=(out.normalized()+out.normalized().cross(Vector((0,0,1)))*.5).normalized()
position=center+out*.48+Vector((0,0,.06))
cam=bpy.data.objects[{camera['camera']!r}];cam.animation_data_clear()
matrix=(center-position).to_track_quat('-Z','Y').to_matrix().to_4x4();matrix.translation=position
cam.matrix_world=matrix;result=True""")
        target=folder/'held_cup.png'
        await tool('render_preview',camera=camera['camera'],frame=frame,engine='eevee',width=512,height=512,filename=str(target))
        items.append(dict(path=str(target),frame=frame,label='Native right hand / held cup'))
    await tool('save_project',path='vrm_actors/performance.blend')
    await tool('export_asset',path='vrm_actors/performance.glb',objects=['Nara_rig','Bayu_rig'],max_influences=4)
    await contact_sheet(folder/'sheet.png',items,columns=2,size=384,aspect=1)
    save('performance_stills.json',items)

async def video(args):
    await tool('open_project',path='vrm_actors/kabar_anime_fixed.blend')
    await settings()
    from serial_video import render
    response=await render(ToolSession(),dict(path='../vrm_actors/kabar_draft.mp4',quality='draft',width=960,height=540))
    job=json.loads(response.content[0].text);save('video_job.json',job)
    assert job['status']=='done',job
    save('review_video.json',await tool('review_video',path=job['path']))

async def qa(args):
    await tool('open_project',path='vrm_actors/kabar_anime_fixed.blend')
    contact=await python("""import json
from engine.commands.seating import _body_samples
from engine.commands.anim import semantic_map
result={}
bpy.context.scene.frame_set(1)
for rig in [o for o in bpy.context.scene.objects if o.type=='ARMATURE']:
 seat=json.loads(rig['c3d_seated']);heights=[]
 for name,ids in _body_samples(rig,semantic_map(rig)).items():
  obj=bpy.data.objects[name].evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=obj.to_mesh()
  heights.extend((obj.matrix_world @ mesh.vertices[int(i)].co).z for i in ids)
  obj.to_mesh_clear()
 result[rig.name]=dict(body_low_z=min(heights),seat_z=seat['center'][2],gap_m=min(heights)-seat['center'][2])
assert all(abs(row['gap_m'])<.02 for row in result.values()),result
""")
    save('seat_contact.json',contact)
    result=await python("import sys\nsys.path.insert(0,'/home/reyhan/.codex/skills/blender-asset-qa/scripts')\nimport qa_check\nrigs=[o for o in bpy.data.objects if o.type=='ARMATURE']\nresult={r.name:qa_check.run(objects=[o.name for o in r.children_recursive if o.type=='MESH' and not o.hide_render],profile='render',max_tris=30000) for r in rigs}")
    save('asset_qa.json',result)
    await settings()
    items=[]
    for actor in ('Nara','Bayu'):
        views=await tool('render_views',objects=[actor+'_rig'],size=384,engine='eevee')
        for view,row in zip(('front','right','back','three_quarter'),views):
            target=OUT/f'qa_{actor}_{view}.png';shutil.copyfile(row['path'],target)
            items.append(dict(path=str(target),label=f'{actor}: {view}',frame=1))
    await contact_sheet(OUT/'asset_views.png',items,columns=4,size=384)
    save('asset_views.json',items)
    save('render_cleanup.json',await python("result=dict(objects=[o.name for o in bpy.data.objects if o.name.startswith('__c3d_vrm_')],materials=[m.name for m in bpy.data.materials if m.name.startswith('__c3d_vrm_')])\nassert not result['objects'] and not result['materials'],result"))

async def sheets(args):
    items=[]
    reference=Path('/home/reyhan/projects/char3d-engine/output/kabar_v2')
    originals=sorted(reference.glob('f*.png'))
    for style in ('anime','animated_film'):
        rendered=json.loads((OUT/f'{style}_stills.json').read_text())
        pairs=[]
        for i,frame in enumerate(rendered):
            original=originals[min(len(originals)-1,round(i*(len(originals)-1)/max(1,len(rendered)-1)))]
            pairs.extend([dict(path=str(original),label=f'MPFB reference: {original.name}',frame=0),frame])
        await contact_sheet(OUT/f'mpfb_vs_vrm_{style}.png',pairs,columns=2,size=480,aspect=9/16)

async def mixed(args):
    await tool('new_scene',frame_end=24)
    from e2e_smoke import isolate_mpfb
    await isolate_mpfb(ToolSession())
    h=await tool('create_realistic_human',name='Real',gender=0,hair='bob01',clothes=['female_casualsuit01','shoes01'])
    rig=h['armature'];await tool('apply_pose',armature=rig,pose='relaxed')
    await tool('set_lighting',preset='studio',subject=[rig]);await tool('cinematic_look',preset='studio_film')
    await tool('camera_shot',subject=[rig],shot='close_up',angle=25,lens=85,depth_of_field=False,start_frame=1,end_frame=24,name='Identity')
    await settings();report={}
    for style in ('none','anime','animated_film'):
        await tool('render_style',style=style)
        target=OUT/f'mpfb_current_{style}.png'
        await tool('render_preview',camera='Identity',engine='eevee',width=256,height=256,filename=str(target))
        baseline=OUT/f'mpfb_baseline_{style}.png'
        await python(f'''import types,sys
from pathlib import Path
from engine.commands import render
from engine.commands import REGISTRY
registry_style=REGISTRY['render_style']
module=types.ModuleType('engine.commands.__vrm_baseline');module.__package__='engine.commands'
exec(Path({str(OUT/'baseline_render_style.py')!r}).read_text(),module.__dict__)
old=render.applied_style
try:
 render.applied_style=module.applied_style
 render.render_preview(camera='Identity',engine='eevee',width=256,height=256,filename={str(baseline)!r})
finally:
 render.applied_style=old
 REGISTRY['render_style']=registry_style
result=True''')
        import av,numpy as np
        def pixels(p):
            with av.open(str(p)) as image:return next(image.decode(video=0)).to_ndarray(format='rgb24')
        difference=np.abs(pixels(target).astype(int)-pixels(baseline).astype(int))
        report[style]=dict(max_channel_error=int(difference.max()),different_channels=int(np.count_nonzero(difference)))
        assert not difference.any(),report
    await tool('transform_object',name=rig,location=[-.7,0,0])
    vrm=await tool('script_to_scene',script={'characters':[SCRIPT['characters'][0]],'beats':[{'do':'pause','seconds':1}]},
                   voice=False,sound=False,music=None,life=0,collisions=False,camera='none')
    vrig=vrm['characters']['Nara']['rig'];await tool('transform_object',name=vrig,location=[.7,0,0])
    await tool('set_lighting',preset='studio',subject=[rig,vrig])
    await tool('camera_shot',subject=[rig,vrig],shot='medium',start_frame=1,end_frame=24,name='Mixed')
    items=[]
    for style in ('none','anime','animated_film'):
        await tool('render_style',style=style)
        target=OUT/f'mixed_{style}.png'
        await tool('render_preview',camera='Mixed',engine='eevee',width=512,height=288,filename=str(target))
        items.append(dict(path=str(target),label=f'MPFB + VRM: {style}',frame=1))
    await contact_sheet(OUT/'mixed.png',items,columns=3,size=384,aspect=9/16)
    save('realistic_identity.json',report)

async def main(args):
    OUT.mkdir(exist_ok=True,parents=True)
    try:
        await tool('scene_info')
        await globals()[args.phase](args)
    finally:await api.engine_shutdown()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['normals','performance_views','build','review','stills','portraits','video','qa','sheets','mixed'],required=True)
    p.add_argument('--limit',type=int,default=0,help='maximum new stills in this resumable batch')
    p.add_argument('--style',choices=['anime','animated_film'],default='anime')
    p.add_argument('--actor',choices=['Nara','Bayu'],default='Nara');p.add_argument('--look',choices=['studio_film','blue_hour'],default='studio_film')
    asyncio.run(main(p.parse_args()))
