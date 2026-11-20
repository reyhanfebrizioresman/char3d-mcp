"""Consented synthetic MPFB portraits, real CPU ONNX and same-view comparisons."""
import json,shutil
from pathlib import Path
import av
import numpy as np
from engine.photo_landmarks import detect,model_directory
from engine.looks import MODIFIER_NAMES
from engine.photo_fit import likeness_geometry
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/toon_round3'
CASES=[dict(seed=11,gender=0,age=25,race={'caucasian':1},hair='short02',yaw=0,
            colors=dict(skin=[.72,.53,.40],iris=[.15,.40,.65],hair=[.09,.045,.02])),
       dict(seed=23,gender=1,age=45,race={'african':1},hair='short01',yaw=6,
            colors=dict(skin=[.34,.22,.16],iris=[.30,.20,.09],hair=[.025,.018,.015])),
       dict(seed=37,gender=0,age=65,race={'asian':1},hair='short02',yaw=-6,
            colors=dict(skin=[.64,.48,.34],iris=[.12,.30,.14],hair=[.22,.20,.18]))]

SETUP='''
import numpy as np,json
from mathutils import Matrix,Vector
from engine.commands.photo import modifier_deltas,displace,paint,correspondence
from engine.commands.toon import neutral_coords,anatomy
from engine.commands.materials import _family
root,body,meshes=_family('Source_rig')
bpy.context.scene.view_settings.exposure=-1.5
known=np.array(KNOWN)
pairs=modifier_deltas(body);p=neutral_coords(body)
delta=np.einsum('m,mnc->nc',abs(known),np.array([pairs[i,1] if c>=0 else pairs[i,0] for i,c in enumerate(known)]))
displace(body,meshes,delta,p)
paint(body,meshes,None,COLORS,None,1.,False)
p=neutral_coords(body);_,top,chin,_=anatomy(body,meshes)
head=p[(p[:,2]>=chin)&(p[:,2]<=top)];lo=head.min(0);hi=head.max(0)
lo[2]-=(top-chin)*.04;hi[2]+=(top-chin)*.12
mesh=bpy.data.meshes.new('PhotoBounds');mesh.from_pydata([(x,y,z) for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2])],[],[])
o=bpy.data.objects.new(mesh.name,mesh);bpy.context.collection.objects.link(o);o.hide_render=True
result=True
'''
CAMERA='''
from bpy_extras.object_utils import world_to_camera_view
from engine.commands.photo import correspondence
from engine.commands.toon import neutral_coords
from engine.commands.materials import _family
from mathutils import Vector
root,body,meshes=_family('Source_rig');p=neutral_coords(body);ids,vertices=correspondence(p,body,meshes)
cam=bpy.context.scene.camera
scene=bpy.context.scene;old_resolution=(scene.render.resolution_x,scene.render.resolution_y)
scene.render.resolution_x=scene.render.resolution_y=224
points=[world_to_camera_view(bpy.context.scene,cam,body.matrix_world@Vector(p[i])) for i in vertices]
scene.render.resolution_x,scene.render.resolution_y=old_resolution
result=dict(matrix=[list(row) for row in cam.matrix_world],lens=cam.data.lens,sensor_width=cam.data.sensor_width,
            ids=ids,projected=[[float(q.x*224),float((1-q.y)*224)] for q in points])
'''

async def run(call,python,still,index):
    case=CASES[index];seed=case['seed'];rng=np.random.default_rng(seed)
    known=rng.uniform(-.25,.25,11);known[2]=.20 if index==0 else -.20
    await call('new_scene',frame_end=48)
    base={k:case[k] for k in ('gender','age','race')};catalog=await call('mpfb_assets')
    extras={}
    if index==1 and 'wdg_scruffy_beard' in catalog['assets'].get('beards',[]):extras['beard']='wdg_scruffy_beard'
    if index==2 and 'toigo_round_glasses_leopard' in catalog['assets'].get('clothes',[]):extras['glasses']='toigo_round_glasses_leopard'
    clothes=[('female' if case['gender']==0 else 'male')+'_casualsuit01','shoes01']
    await call('new_scene',frame_end=48)
    # Inference inputs must expose both eyes. Case C supplies glasses as an
    # explicit look trait afterwards, independently of the unoccluded photo.
    source=await call('create_realistic_human',name='Source',hair=case['hair'],clothes=clothes,beard=extras.get('beard'),seed=seed,**base)
    await python(SETUP.replace('KNOWN',repr(known.tolist())).replace('COLORS',repr(case['colors'])))
    await call('render_views',objects=['Source_rig'],size=256)
    await call('set_lighting',preset='soft',subject=['Source_rig'])
    shot=await call('camera_shot',subject=['PhotoBounds'],shot='medium_full',lens=85,angle=case['yaw'],depth_of_field=False,avoid_occlusion=False,start_frame=1,end_frame=48)
    image=await call('render_preview',camera=shot['camera'],engine_name='eevee',width=224,height=224)
    relative=f'round3/source_{seed}.png';path=ROOT/'output/imports'/relative;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(image['path'],path)
    shutil.copyfile(path,OUT/f'face_{seed}_source.png')
    calibration=await python(CAMERA.replace("cam=bpy.context.scene.camera",f"cam=bpy.data.objects[{shot['camera']!r}]"))
    with av.open(str(path)) as container:rgb=next(container.decode(video=0)).to_ndarray(format='rgb24')/255
    inference=detect(rgb,model_directory(ROOT/'output'))
    observed=np.array(inference['landmarks'])[calibration['ids']]
    landmark_error=float(np.linalg.norm(observed-np.array(calibration['projected']),axis=1).mean())
    result=dict(case=case,provided_traits=extras,source_glasses=False,exposure_ev=-1.5,source_landmarks=inference['landmarks'],source_projection=calibration,true_modifiers=dict(zip(MODIFIER_NAMES,known.tolist())),ground_truth_landmark_error_px=landmark_error,source_confidence=float(np.mean(inference['confidence'])),fits={})
    for style in ('realistic','anime'):
        await call('new_scene',frame_end=48)
        await call('create_realistic_human',name='Fitted',style=style,hair=None,clothes=clothes,seed=seed,**base)
        await python('bpy.context.scene.view_settings.exposure=-1.5\nresult=True')
        traits={'hair':case['hair'],**extras}
        report=await call('face_from_photo',character='Fitted_rig',image=relative,consent=True,texture=(index==0) if style=='realistic' else None,traits=traits,seed=seed)
        assert style=='realistic' or not report['texture'],report
        recovered=np.array([report['modifiers'][name] for name in MODIFIER_NAMES])
        expected=known*(.55 if style!='realistic' else 1.)
        coefficient_rmse=float(np.sqrt(np.mean((recovered-expected)**2)))
        colour_error={name:float(np.sqrt(np.mean((np.array(report['colors_srgb'][name])-case['colors'][name])**2))) for name in case['colors']}
        from_camera=f"""
from mathutils import Matrix
camdata=bpy.data.cameras.new('PhotoSameView');camdata.lens={calibration['lens']!r};camdata.sensor_width={calibration['sensor_width']!r}
cam=bpy.data.objects.new(camdata.name,camdata);bpy.context.collection.objects.link(cam)
cam.matrix_world=Matrix({calibration['matrix']!r});bpy.context.scene.camera=cam
result=cam.name
"""
        camera=await python(from_camera)
        if style=='anime':
            # Keep viewing angle/lens while framing the larger stylized head.
            # An unchanged realistic camera clips its chin and defeats detection.
            bounds=SETUP[SETUP.index('p=neutral_coords(body);_,top'):]
            await python("import numpy as np\nfrom engine.commands.materials import _family\nfrom engine.commands.toon import neutral_coords,anatomy\nroot,body,meshes=_family('Fitted_rig')\n"+bounds)
            framed=await call('camera_shot',subject=['PhotoBounds'],shot='medium_full',lens=85,angle=case['yaw'],depth_of_field=False,avoid_occlusion=False,start_frame=1,end_frame=48)
            camera=framed['camera']
        await call('set_lighting',preset='soft',subject=['Fitted_rig'])
        fitted=await call('render_preview',camera=camera,engine_name='eevee',width=224,height=224)
        dst=OUT/f'face_{seed}_{style}.png';shutil.copyfile(fitted['path'],dst)
        with av.open(str(dst)) as container:fitted_rgb=next(container.decode(video=0)).to_ndarray(format='rgb24')/255
        try:
            again=detect(fitted_rgb,model_directory(ROOT/'output'))
            likeness=dict(likeness_geometry(inference['landmarks'],again['landmarks']),redetected=True)
        except ValueError as exc:likeness=dict(score=None,redetected=False,reason=str(exc))
        likeness['framing']='same viewing angle/lens, head bounds' if style=='anime' else 'identical source camera'
        values=dict(report=report,modifier_rmse=coefficient_rmse,color_srgb_rmse=colour_error,same_view_likeness=likeness)
        await call('save_project',path=f'round3_face_{seed}_{style}.blend')
        # Rebuild from JSON, with the same base traits and native geometry.
        coordinates=await python("from engine.commands.toon import neutral_coords\nfrom engine.commands.materials import _family\nimport numpy as np\nroot,body,meshes=_family('Fitted_rig');np.save('"+str(OUT/f'face_{seed}_{style}_fitted.npy')+"',neutral_coords(body));np.savez('"+str(OUT/f'face_{seed}_{style}_family.npz')+"',**{o.name.replace('Fitted',''):neutral_coords(o) for o in meshes})\nresult=True")
        await call('create_realistic_human',name='Replay',style=style,look=json.loads(json.dumps(report['look'])),clothes=clothes,location=[2,0,0])
        error=await python("from engine.commands.toon import neutral_coords\nimport numpy as np\np=np.load('"+str(OUT/f'face_{seed}_{style}_fitted.npy')+"');q=neutral_coords(bpy.data.objects['Replay']);result=float(np.max(np.linalg.norm(p-q,axis=1)))")
        assert error<.0005,(style,error)
        values['recipe_rebuild_error_m']=error
        values['recipe_part_errors_m']=await python("import numpy as np\nfrom engine.commands.toon import neutral_coords\nfrom engine.commands.materials import _family\nroot,body,meshes=_family('Replay_rig');stored=np.load('"+str(OUT/f'face_{seed}_{style}_family.npz')+"');result={o.name.replace('Replay',''):float(np.max(np.linalg.norm(stored[o.name.replace('Replay','')]-neutral_coords(o),axis=1))) for o in meshes if o.name.replace('Replay','') in stored and stored[o.name.replace('Replay','')].shape==neutral_coords(o).shape}")
        assert max(values['recipe_part_errors_m'].values())<.0005,values['recipe_part_errors_m']
        result['fits'][style]=values
        (OUT/f'face_{seed}.json').write_text(json.dumps(result,indent=2))
        print('REAL FACE CASE OK',seed,style,'mod RMSE',coefficient_rmse,'same-view likeness',likeness,flush=True)
    (OUT/f'face_{seed}.json').write_text(json.dumps(result,indent=2))
    if index==0:
        recipe=result['fits']['anime']['report']['look']
        await call('new_scene',frame_end=24)
        scripted=await call('script_to_scene',script=dict(characters=[dict(id='Actor',look=recipe,clothes=clothes)],
            beats=[dict(do='pause',who='Actor',seconds=.25)]),camera='none',voice=False,sound=False,
            music=None,subtitles=False,body_language=False,life=0)
        rebuilt=await python("from engine.commands.toon import neutral_coords\nimport numpy as np,json\np=np.load('"+str(OUT/f'face_{seed}_anime_fitted.npy')+"');body=next(o for o in bpy.context.scene.objects if o.get('c3d_source')=='mpfb');result=dict(error_m=float(np.max(np.linalg.norm(p-neutral_coords(body),axis=1))),style=body.get('c3d_style'),recipe=json.loads(body['c3d_look_recipe']))")
        assert rebuilt['error_m']<.0005 and rebuilt['style']=='anime',rebuilt
        result['script_recipe_rebuild']=rebuilt
        (OUT/f'face_{seed}.json').write_text(json.dumps(result,indent=2))
    return result


def sheet():
    from toon_polish import read,save,label
    pixels=np.full((3*250,3*224,3),28,np.uint8)
    for row,case in enumerate(CASES):
        for col,style in enumerate(('source','realistic','anime')):
            pixels[row*250+26:(row+1)*250,col*224:(col+1)*224]=read(OUT/f"face_{case['seed']}_{style}.png")
            label(pixels,chr(65+row)+' '+style,col*224+5,row*250+5)
    save(OUT/'faces.png',pixels)
    print('REAL FACE COMPARISON SHEET OK',OUT/'faces.png')
