"""Isolated MCP toon integration checks. No optional model downloads."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import struct
import io

import av
import numpy as np


LIDS = '''
import numpy as np
from engine.commands.toon import coords,anatomy
from engine.commands.materials import _family
from engine.commands.materials import _role
from engine.commands.face import _set,_face_meshes
from mathutils import Vector
from mathutils.bvhtree import BVHTree
root,body,meshes=_family(CHARACTER)
keys=body.data.shape_keys.key_blocks
helper_state_error=max((abs(k.value-keys[k.name].value) for o in meshes if o.get('c3d_toon_sources') and o.data.shape_keys for k in o.data.shape_keys.key_blocks if k.name in keys),default=0.)
assert helper_state_error<.00001,helper_state_error
for obj in meshes:
 data=[obj.data.vertices]+([key.data for key in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else [])
 assert all(np.isfinite(coords(points)).all() for points in data),obj.name
p=coords(keys[0].data)
_,top,chin,eyes=anatomy(body,meshes)
from engine.toon import LID_PAIRS
report={}
for side,pairs in LID_PAIRS.items():
 blink=coords(keys['eyeBlink'+('Left' if side=='L' else 'Right')].data)
 report[side]=dict(pairs=pairs,blink_gap_m=max(abs(float(blink[i,2]-blink[j,2])) for i,j in pairs),blink_gap3d_m=max(float(np.linalg.norm(blink[i]-blink[j])) for i,j in pairs),open_gap_m=max(abs(float(p[i,2]-p[j,2])) for i,j in pairs))
jaw=coords(keys['aa_02'].data)-p
states=[(m,m.show_viewport) for m in body.modifiers if m.type=='MASK']
try:
 for m,_ in states:m.show_viewport=False
 bpy.context.view_layer.update()
 ev=body.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh()
 q=coords(mesh.vertices)
 assert len(q)==len(p)
 head=(p[:13380,2]>chin)
 rest_error=float(np.max(np.linalg.norm(q[:13380][head]-p[:13380][head],axis=1)))
 ev.to_mesh_clear()
finally:
 for m,value in states:m.show_viewport=value
eye=next(m for m in meshes if _role(m,body)=='eyes')
reference=np.array([eye.matrix_world @ v.co for v in eye.data.vertices])
centers=[]
for sign in (-1,1):
 part=reference[reference[:,0]*sign>0]
 centers.append(((part.min(axis=0)+part.max(axis=0))/2,np.ptp(part,axis=0)))
def bvh(obj):
 ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh()
 tree=BVHTree.FromPolygons([obj.matrix_world @ v.co for v in mesh.vertices],[list(f.vertices) for f in mesh.polygons])
 ev.to_mesh_clear()
 return tree
visibility={}
try:
 for state,value in (('open',0.),('closed',1.)):
  _set(_face_meshes(body),dict(eyeBlinkLeft=value,eyeBlinkRight=value))
  bpy.context.view_layer.update();skin_bvh,eye_bvh=bvh(body),bvh(eye)
  visible=0
  for center,extent in centers:
   for dx in (-.45,-.25,0,.25,.45):
    for dz in (-.20,-.10,0,.10,.20):
     origin=Vector((center[0]+dx*extent[0],center[1]-.5,center[2]+dz*extent[2]))
     face=skin_bvh.ray_cast(origin,Vector((0,1,0)))
     globe=eye_bvh.ray_cast(origin,Vector((0,1,0)))
     visible+=int(globe[0] is not None and (face[0] is None or globe[3]<face[3]-.0001))
  visibility[state]=visible
finally:
 _set(_face_meshes(body),dict(eyeBlinkLeft=0.,eyeBlinkRight=0.))
result=dict(lids=report,helper_state_error=helper_state_error,visible_eye_samples=visibility,rest_face_error_m=rest_error,mouth_open_m=float(np.max(np.linalg.norm(jaw,axis=1))),height_m=float(top-min(p[:13380,2])),head_ratio=float((top-min(p[:13380,2]))/(top-chin)))
'''

PHOTO_MOCK = '''
import json,os
import numpy as np
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from engine import context
from engine.commands import photo
from engine.commands.toon import coords,neutral_coords
from engine.commands.materials import _family
from engine.photo_fit import project
body=next(o for o in bpy.context.scene.objects if o.get('c3d_source')=='mpfb' and o.get('c3d_style')=='anime')
root,body,meshes=_family(body.name)
neutral=neutral_coords(body)
cutouts={m.name:m.material_slots[0].material.get('c3d_toon_cutout') for m in meshes if m.material_slots and m.material_slots[0].material.get('c3d_toon_cutout')}
ids,vertices=photo.correspondence(neutral,body,meshes)
pairs=photo.modifier_deltas(body)
known=np.linspace(-.15,.2,len(photo.MODIFIERS))
delta=np.einsum('m,mnc->nc',abs(known),np.array([pairs[i,1] if c>=0 else pairs[i,0] for i,c in enumerate(known)]))
camera=[550,0,128,float(128+550*np.mean(neutral[vertices,2]))]
points=np.tile([128.,128.],(66,1))
points[ids]=project((neutral+delta)[vertices],camera)
inference=dict(landmarks=points.tolist(),confidence=[1.]*66)
filename=os.path.join(context.WORKSPACE,'imports','toon_synthetic_photo.png')
im=bpy.data.images.new('Synthetic permitted face fixture',width=256,height=256)
im.pixels.foreach_set(np.tile([.65,.48,.38,1.],256*256).astype(np.float32))
im.filepath_raw=filename;im.file_format='PNG';im.save()
jpeg=filename.removesuffix('.png')+'.jpg'
im.filepath_raw=jpeg;im.file_format='JPEG';im.save();bpy.data.images.remove(im)
assert photo.decode(jpeg).shape==(256,256,3)
try:photo.face_from_photo(root.name,'toon_synthetic_photo.png',consent=False)
except ValueError as exc:assert 'consent=True' in str(exc)
else:raise AssertionError('consent not enforced')
with patch.dict(os.environ,{'CHAR3D_FACE_MODEL_DIR':os.path.join(context.WORKSPACE,'models','missing_test_models')}):
 try:photo.face_from_photo(root.name,'toon_synthetic_photo.png',consent=True)
 except RuntimeError as exc:assert 'install_face_landmarks.sh' in str(exc)
 else:raise AssertionError('missing model not detected')
def fake_inference(command,**kwargs):
 assert Path(command[3]).is_relative_to(Path(context.WORKSPACE)/'imports')
 assert np.load(command[3],allow_pickle=False).shape==(256,256,3)
 Path(command[4]).write_text(json.dumps(inference))
 return SimpleNamespace(returncode=0,stderr='')
with patch.object(photo.subprocess,'run',side_effect=fake_inference):
 assert photo.infer(photo.decode(filename),'mocked models')['landmarks']==inference['landmarks']
with patch.object(photo.subprocess,'run',return_value=SimpleNamespace(returncode=1,stderr='mock failure')):
 try:photo.infer(photo.decode(filename),'mocked models')
 except RuntimeError:pass
 else:raise AssertionError('inference failure missing')
with patch.object(photo,'model_files',return_value=[]),patch.object(photo,'infer',return_value=inference),patch('engine.commands.photo_review.likeness_check',return_value=dict(score=None,redetected=False,reason='Mocked ONNX unit fixture')):
 report=photo.face_from_photo(root.name,'toon_synthetic_photo.png',consent=True)
 assert report['local_only'] and not report['texture'] and report['fit_error_px']<10,report
 report_texture=photo.face_from_photo(root.name,'toon_synthetic_photo.png',strength=.3,texture=True,consent=True)
 assert report_texture['texture']
 for name,image in cutouts.items():
  assert bpy.data.objects[name].material_slots[0].material.get('c3d_toon_cutout')==image,'photo repaint lost toon hair alpha'
assert 'eyeBlinkLeft' in body.data.shape_keys.key_blocks and 'aa_02' in body.data.shape_keys.key_blocks
assert not any(x.startswith('.face-local-') for x in os.listdir(os.path.join(context.WORKSPACE,'imports')))
states=[(m,m.show_viewport) for m in body.modifiers if m.type=='MASK']
try:
 for m,_ in states:m.show_viewport=False
 bpy.context.view_layer.update();ev=body.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh()
 expected=neutral_coords(body);actual=coords(mesh.vertices)
 # Script actors can already be posed; the dedicated fresh realistic checks
 # below assert identity skinning after the fit, including generated Rigify.
 rest_error=float(np.max(np.linalg.norm(actual[:13380]-expected[:13380],axis=1))) if len(actual)==len(expected) else -1
 ev.to_mesh_clear()
finally:
 for m,value in states:m.show_viewport=value
result=dict(photo=report,texture=report_texture,rest_error_m=rest_error)
'''


async def real_photo_checks(call,text_of,rig='game_engine'):
    async def data(tool,**args):
        return json.loads(text_of(await call(tool,**args))[0])
    await call('scene_info')
    await call('new_scene',frame_end=24)
    await call('create_realistic_human',name='PhotoReal',gender=0,race={'asian':1},rig=rig,
               hair='short02',clothes=['female_casualsuit01','shoes01'])
    code=PHOTO_MOCK.replace("body=next(o for o in bpy.context.scene.objects if o.get('c3d_source')=='mpfb' and o.get('c3d_style')=='anime')", "body=bpy.data.objects['PhotoReal']")
    code=code.replace("not report['texture']", "report['texture']")
    report=(await data('run_blender_python',code=code))['result']
    assert 0<=report['rest_error_m']<.003,report
    asset=await data('export_asset',path='toon_photo_real_'+rig+'.glb',objects=['PhotoReal_rig'],max_influences=4)
    raw=Path(asset['path']).read_bytes();length=struct.unpack_from('<I',raw,12)[0]
    gltf=json.loads(raw[20:20+length])
    cached=Path(report['texture']['look']['texture']['path']).stem
    photo_images={i for i,im in enumerate(gltf.get('images',[])) if im.get('name','').startswith('c3d_local_photo_projection') or im.get('name')==cached}
    assert photo_images,gltf.get('images')
    assert any(gltf['textures'][m['pbrMetallicRoughness']['baseColorTexture']['index']]['source'] in photo_images for m in gltf['materials'] if m.get('pbrMetallicRoughness',{}).get('baseColorTexture'))
    iris_images={i for i,im in enumerate(gltf.get('images',[])) if im.get('name','').startswith('c3d_photo.iris.')}
    assert iris_images,gltf.get('images')
    assert any(gltf['textures'][m.get('pbrMetallicRoughness',{}).get('baseColorTexture',{}).get('index',0)]['source'] in iris_images for m in gltf['materials'] if m.get('pbrMetallicRoughness',{}).get('baseColorTexture'))
    assert any('jawOpen' in m.get('extras',{}).get('targetNames',[]) for m in gltf['meshes'])
    await call('render_preview',objects=['PhotoReal_rig'],engine_name='workbench',width=320,height=320)
    output=Path(__file__).resolve().parents[1]/'output'
    (output/('toon_photo_real_'+rig+'_checks.json')).write_text(json.dumps(dict(report=report,export=asset),indent=2))
    print('TOON PHOTO REALISTIC E2E OK | '+rig+' | neutral phenotype fit + enhanced skin calibration + projected texture in GLB',flush=True)


async def run(call, text_of):
    async def data(tool, **args):
        print('TOON CHECK',tool,flush=True)
        return json.loads(text_of(await call(tool, **args))[0])

    async def still(name,**args):
        result=await data('render_preview',**args)
        target=output/'renders'/name
        shutil.copyfile(result['path'],target)
        # Scene-camera previews currently drop explicit height in the MCP wrapper.
        # Use named cameras below and check PNG dimensions, not requested size.
        pixels=struct.unpack('>II',target.read_bytes()[16:24])
        assert max(pixels)<=(512 if args.get('engine_name')=='eevee' else 384),(name,pixels)
        return str(target)

    assert os.environ.get('CHAR3D_PORT') == '9971', 'toon checks require port 9971'
    if os.environ.get('CHAR3D_TOON_PHOTO_ONLY'):
        for rig in ('game_engine','rigify'):
            await real_photo_checks(call,text_of,rig)
        return
    output = Path(__file__).resolve().parents[1]/'output'
    # Explicit resume for CPU-only runs interrupted by the session supervisor.
    # Use only when the engine sources/fixtures have not changed since checkpoint.
    checkpoint=output/'toon_checks.json'
    resume=os.environ.get('CHAR3D_TOON_RESUME')=='1'
    source_hash=hashlib.sha256(b''.join((output.parent/p).read_bytes() for p in (
        'engine/toon.py','engine/commands/toon.py','engine/toon_refine.py',
        'engine/commands/toon_refine.py','engine/commands/toon_render.py',
        'engine/commands/render_style.py'))).hexdigest()
    evidence = json.loads(checkpoint.read_text()) if resume and checkpoint.exists() else {'source_hash':source_hash}
    assert evidence.get('source_hash')==source_hash,'Checkpoint engine sources changed; run without CHAR3D_TOON_RESUME'
    for style, heads, rig in (('anime', 6.75,'game_engine'), ('cartoon',4.75,'rigify'), ('chibi',2.8,'game_engine')):
        if style in evidence:
            print('TOON RESUME previously verified',style,flush=True)
            continue
        await call('scene_info')
        await call('new_scene')
        name = style.capitalize();arm=name+'_rig'
        built = await data('create_realistic_human', name=name, style=style, gender=0,rig=rig,
                           race={'asian':1}, hair='short02', clothes=['female_casualsuit01','shoes01'])
        assert abs(built['stylized']['head_ratio']-heads) < .1, built
        assert built['height_m']>1 and built['height_m']<2.1,built
        assert (await data('run_blender_python',code="result=bpy.context.scene.get('char3d_render_style')"))['result'] is None
        await call('render_views', objects=[arm], size=320,views=['front','right','back','three_quarter'])
        await call('save_project',path='toon_'+style+'_precheck.blend')
        measurements=(await data('run_blender_python',code=LIDS.replace('CHARACTER',repr(arm))))['result']
        print('TOON MEASURE',style,measurements,flush=True)
        assert measurements['mouth_open_m']>.005,measurements
        assert measurements['rest_face_error_m']<.003,measurements
        assert measurements['visible_eye_samples']['open']>=4 and measurements['visible_eye_samples']['closed']==0,measurements
        for side,lid in measurements['lids'].items():
            assert lid['open_gap_m']>.003 and lid['blink_gap_m']<.001,(style,side,lid)
        await call('apply_pose',armature=arm,pose='relaxed')
        await call('set_lighting', preset='soft', subject=[arm])
        await call('render_style', style='anime')
        front=await still('toon_'+style+'_front.png',objects=[arm],view='front',engine_name='eevee',width=384,height=384)
        portrait=await data('camera_shot',subject=[arm],shot='close_up',angle=25,start_frame=1,end_frame=24)
        quarter=await still('toon_'+style+'_three_quarter.png',camera=portrait['camera'],engine_name='eevee',width=384,height=384)
        await call('save_project', path='toon_'+style+'_rest.blend')
        await call('run_blender_python',code="hidden=[o for o in bpy.context.scene.objects if o.type=='MESH' and not o.hide_viewport]\nbpy.context.scene['toon_test_hidden']=[o.name for o in hidden]\nfor o in hidden:o.hide_viewport=True\nresult=True")
        wave=await data('animate',armature=arm,clip='wave',cycles=1,start_frame=1)
        await call('set_hand_pose',character=arm,shape='peace',side='right',frame=18,keyframe=True)
        await call('run_blender_python',code="for name in bpy.context.scene.pop('toon_test_hidden',[]): bpy.data.objects[name].hide_viewport=False\nresult=True")
        walk=await data('walk_path',armature=arm,points=[[0,-.35]],start_frame=wave['next_start_frame'],avoid=False)
        assert .25<walk['distance_m']<.45,walk
        # Size the chair from the actual lower leg instead of adult meters.
        # A tall adult chair cannot keep a short toon character's soles planted.
        chair_fit=(await data('run_blender_python',code="""
from engine.commands.anim import semantic_map
rig=bpy.data.objects[ARMATURE];sm=semantic_map(rig)
shin=rig.data.bones[sm['shin.L']].length
ankle=(rig.matrix_world @ rig.data.bones[sm['foot.L']].head_local).z-rig.matrix_world.translation.z
result=.92*(shin+max(0,ankle))/.515
""".replace('ARMATURE',repr(arm))))['result']
        chair=await data('add_prop',kind='chair',location=[0,-.35,0],scale=chair_fit)
        seat=await data('sit_on',character=arm,seat=chair['root'],start_frame=walk['next_start_frame'])
        assert abs(seat['contact_error_m'])<.003 and seat['max_ik_error_m']<.01,seat
        assert not seat['collisions'].get('garments'), 'Fitted clothing must retain its authored weights'
        speech=await data('lip_sync',character=arm,text='Mama buka pintu. Halo semuanya!',language='id',start_frame=seat['next_start_frame'])
        await call('set_expression',character=arm,expression='smile',strength=.35,frame=speech['frames'][0],keyframe=True)
        await call('set_timeline',frame_end=speech['frames'][1]+24)
        blink=await data('auto_blink',character=arm,interval_seconds=1.5)
        assert blink['blinks'],blink
        await call('talk_gestures',character=arm,frame_start=speech['frames'][0],frame_end=speech['frames'][1])
        await call('talk_motion',character=arm,frame_start=speech['frames'][0],frame_end=speech['frames'][1])
        await call('render_frames',frames=[18,round(sum(walk['frames'])/2),seat['frames'][-1],speech['frames'][0]+10],objects=[arm],size=320,view='three_quarter')
        await call('set_expression',character=arm,expression='eyes_closed',strength=1,frame=speech['frames'][1]+12,keyframe=True,transition_frames=0)
        await call('render_frames',frames=[speech['frames'][1]+12],objects=[arm],size=320,view='front')
        if style=='anime':
            peak=next(p['frame'] for p in speech['phonemes'] if p['viseme']=='aa_02' and p['frame'] is not None)
            face_shot=await data('camera_shot',subject=[arm],shot='close_up',angle=15,start_frame=speech['frames'][0],end_frame=speech['frames'][1]+20)
            await still('toon_anime_mouth_open.png',camera=face_shot['camera'],engine_name='workbench',frame=peak,width=320,height=320)
            await still('toon_anime_blink.png',camera=face_shot['camera'],engine_name='workbench',frame=speech['frames'][1]+12,width=320,height=320)
        glb=await data('export_asset',path='toon_'+style+'.glb',objects=[arm],max_influences=4)
        with open(glb['path'],'rb') as stream:raw=stream.read()
        length=struct.unpack_from('<I',raw,12)[0];gltf=json.loads(raw[20:20+length])
        morphs=[m for m in gltf['meshes'] if any(p.get('targets') for p in m['primitives'])]
        assert morphs and any('eyeBlinkLeft' in m.get('extras',{}).get('targetNames',[]) for m in morphs),glb
        assert gltf.get('animations') and gltf.get('skins'),glb
        # Check exported PNG colour encoding, independently of Blender's shader.
        material=next(m for m in gltf['materials'] if m['name'].startswith('c3d_toon.skin.'))
        texture=gltf['textures'][material['pbrMetallicRoughness']['baseColorTexture']['index']]
        embedded=gltf['images'][texture['source']]
        view=gltf['bufferViews'][embedded['bufferView']]
        binary=raw[28+length:]
        png=binary[view.get('byteOffset',0):view.get('byteOffset',0)+view['byteLength']]
        with av.open(io.BytesIO(png)) as decoded:
            pixel=next(decoded.decode(video=0)).to_ndarray(format='rgb24')[0,0]
        # Compare the exported texture with the calibrated PBR pigment, not
        # the raw scan sample before exposure normalization.
        color=np.array(built['stylized']['materials']['skin_rgb_linear'])
        expected=np.where(color<=.0031308,color*12.92,1.055*color**(1/2.4)-.055)*255
        assert np.max(abs(pixel-expected))<4,(pixel,expected)
        await call('save_project',path='toon_'+style+'.blend')
        evidence[style]=dict(build=built,measurements=measurements,stills=[front,quarter],wave=wave,walk=walk,seat=seat,blink=blink,export=glb)
        (output/'toon_checks.json').write_text(json.dumps(evidence,indent=2))
    await call('new_scene')
    script='GAYA: anime\nMUSIK: none\nANA (perempuan, anime, rambut pendek): Halo!\nBUDI (pria, kartun, rambut pendek): Hai!'
    scene=await data('script_to_scene',script=script,name='ToonScene',voice=False,sound=False,music=None,subtitles=False)
    inspect=await data('run_blender_python',code="result={o.name:o.get('c3d_style') for o in bpy.context.scene.objects if o.type=='ARMATURE' and not o.get('c3d_role')}")
    assert {'anime','cartoon'}<=set(inspect['result'].values()),inspect
    await call('render_frames',frames=[12],camera='scene',size=320)
    await call('save_project',path='toon_script.blend')
    evidence['script']=scene
    contact=await data('interact',a=scene['characters']['ANA']['rig'],b=scene['characters']['BUDI']['rig'],kind='handshake')
    assert contact['contact_error_m']<.03,contact
    await call('render_frames',frames=[contact['frames']['contact']],camera='scene',size=320)
    evidence['interaction']=contact
    assert (await data('run_blender_python',code="""
from unittest.mock import patch
from engine.commands.vrm import import_vrm
with patch('engine.commands.vrm.addon_utils.modules',return_value=[]):
 try:import_vrm('mock.vrm')
 except RuntimeError as exc:assert 'install_vrm.sh' in str(exc)
 else:raise AssertionError('missing VRM add-on not detected')
result=True
"""))['result']
    evidence['photo_mock']=(await data('run_blender_python',code=PHOTO_MOCK))['result']
    await call('render_frames',frames=[12],camera='scene',size=320)
    print('TOON PHOTO MOCK E2E OK | actual MPFB modifiers + local decode + projection + consent + missing models',flush=True)
    for rig in ('game_engine','rigify'):
        await real_photo_checks(call,text_of,rig)
    # The opt-out path has no facial keys, but still needs a skinned lid line.
    await call('scene_info')
    await call('new_scene')
    optout=await data('create_realistic_human',name='NoFace',style='anime',face=False,
                      clothes=['female_casualsuit01','shoes01'])
    assert optout.get('face_rig') is None,optout
    await call('render_preview',objects=['NoFace_rig'],width=320,height=320)
    try:
        await call('set_expression',character='NoFace_rig',expression='smile')
    except RuntimeError as exc:
        assert 'face=False' in str(exc),exc
    else:
        raise AssertionError('frozen opt-out must reject late unfitted facial targets')
    evidence['face_false']=optout
    (output/'toon_checks.json').write_text(json.dumps(evidence,indent=2))
    print('TOON E2E OK', flush=True)
