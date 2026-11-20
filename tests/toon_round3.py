"""Real installed ONNX/VRM checks over isolated MCP, no asset downloads."""
import argparse,asyncio,json,os,shutil,sys
from pathlib import Path
import av
import numpy as np
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from e2e_smoke import text_of,isolate_mpfb
OUT=ROOT/'output/toon_round3'

async def run(mode,index=0,versions=(0,1)):
    assert os.environ.get('CHAR3D_PORT')=='9971'
    OUT.mkdir(parents=True,exist_ok=True)
    params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=dict(os.environ))
    async with stdio_client(params) as (r,w),ClientSession(r,w) as session:
        await session.initialize()
        async def call(tool,**kwargs):
            print('ROUND3',tool,flush=True)
            value=await session.call_tool(tool,kwargs);assert not value.isError,text_of(value)
            data=json.loads(text_of(value)[0])
            if tool=='new_scene':await isolate_mpfb(session)
            return data
        async def python(code):return (await call('run_blender_python',code=code))['result']
        async def still(name,**kwargs):
            image=await call('render_preview',engine_name='eevee',width=256,height=256,**kwargs)
            target=OUT/(name+'.png');shutil.copyfile(image['path'],target);return str(target)
        try:
            await call('scene_info')
            if mode=='vrm':
                results=json.loads((OUT/'vrm_results.json').read_text()) if (OUT/'vrm_results.json').exists() else {}
                for version in versions:
                    await call('new_scene',frame_end=144)
                    built=await call('create_realistic_human',name='Original',style='cartoon',gender=0,hair='short02',clothes=['female_casualsuit01','shoes01'])
                    await call('render_views',objects=[built['armature']],size=256)
                    export=await python(f"import sys\nsys.path.insert(0,{str(ROOT/'tests')!r})\nfrom vrm_roundtrip_fixture import export_original\nresult=export_original({built['armature']!r},{version})")
                    await call('new_scene',frame_end=144)
                    imported=await call('import_model',path=export['path']);info=imported['vrm'][0];rig=info['armature']
                    assert len(info['mapped_bones'])>=20 and info['finger_sides']==['L','R'],info
                    neutral=await python(f"result={{o.name:{{k.name:k.value for k in o.data.shape_keys.key_blocks if k.name in {info['expression_channels']!r} and abs(k.value)>.00001}} for o in bpy.data.objects[{rig!r}].children_recursive if o.type=='MESH' and o.data.shape_keys}}")
                    assert not any(neutral.values()),neutral
                    await call('render_views',objects=[rig],size=256)
                    deformation=await python(f"""
import numpy as np
from engine.commands.face import _basemesh
from engine.commands.toon import coords
body=_basemesh({rig!r});keys=body.data.shape_keys.key_blocks
result={{name:float(np.max(np.linalg.norm(coords(keys[name].data)-coords(keys[name].relative_key.data),axis=1))) for name in ('eyeBlinkLeft','jawOpen','mouthSmileLeft','eyeWideLeft')}}
""")
                    assert min(deformation.values())>.0002,deformation
                    await call('set_lighting',preset='soft',subject=[rig])
                    pose=await call('apply_pose',armature=rig,pose='relaxed')
                    walk=await call('animate',armature=rig,clip='walk',cycles=1,start_frame=1)
                    hand=await call('set_hand_pose',character=rig,shape='peace',side='right',keyframe=True,frame=24)
                    assert hand['bones']>=12,hand
                    # Walk advances the root. Bake the portrait after animation
                    # and follow it, rather than framing an unanimated location.
                    portrait=await call('camera_shot',subject=[rig],shot='close_up',move='tracking',lens=85,angle=25,
                        depth_of_field=False,avoid_occlusion=False,start_frame=1,end_frame=144)
                    await python('bpy.context.scene.frame_set(24)\nresult=True')
                    shots=[]
                    expression_geometry={}
                    for expression in ('smile','surprised'):
                        face=await call('set_expression',character=rig,expression=expression)
                        if expression=='smile':
                            expression_geometry=await python(f"""
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree
from bpy_extras.object_utils import world_to_camera_view
from engine.commands.face import _basemesh
from engine.commands.toon import coords
rig=bpy.data.objects[{rig!r}];body=_basemesh(rig.name);keys=body.data.shape_keys.key_blocks
p=np.array([body.matrix_world@Vector(v) for v in coords(keys[0].data)])
tree=KDTree(len(p))
for i,point in enumerate(p):tree.insert(Vector(point),i)
tree.balance()
reference={export['source_reference']!r}
nearest=[tree.find(Vector(point)) for point in reference['neutral_lips']]
ev=body.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh()
actual=[body.matrix_world@mesh.vertices[index].co for _point,index,_distance in nearest]
ev.to_mesh_clear()
head=rig.pose.bones[{info['mapped_bones']['head']!r}]
unpose=(rig.matrix_world@head.matrix@head.bone.matrix_local.inverted()@rig.matrix_world.inverted()).inverted()
error=max(float(np.linalg.norm(np.array(unpose@point)-expected)) for point,expected in zip(actual,reference['smile_lips']))
scene=bpy.context.scene;camera=bpy.data.objects[{portrait['camera']!r}]
size=(scene.render.resolution_x,scene.render.resolution_y)
scene.render.resolution_x=scene.render.resolution_y=256
projected=[list(world_to_camera_view(scene,camera,point)) for point in actual]
scene.render.resolution_x,scene.render.resolution_y=size
result=dict(rest_match_error_m=max(float(n[2]) for n in nearest),smile_delta_error_m=error,
 projected_lips=projected,frame=scene.frame_current,rig_world=[list(row) for row in rig.matrix_world],
 camera_world=[list(row) for row in camera.matrix_world],landmarks=rig.get('c3d_landmarks'),
 nonzero_original={{k.name:k.value for k in keys if k.name.startswith('Original_') and abs(k.value)>.001}},
 nonzero_aliases={{k.name:k.value for k in keys if not k.name.startswith('Original_') and abs(k.value)>.001}})
""")
                            assert expression_geometry['rest_match_error_m']<.0005,expression_geometry
                            assert expression_geometry['smile_delta_error_m']<.0005,expression_geometry
                            (OUT/f'vrm{version}_framing.json').write_text(json.dumps(expression_geometry,indent=2))
                            projected=np.asarray(expression_geometry['projected_lips'])
                            assert (projected[:,2]>0).all() and ((projected[:,:2].mean(0)>.05)&(projected[:,:2].mean(0)<.95)).all(),expression_geometry
                            diagnostic=await call('render_preview',engine_name='workbench',width=256,height=256,camera=portrait['camera'])
                            shutil.copyfile(diagnostic['path'],OUT/f'vrm{version}_smile_workbench.png')
                        shots.append(await still(f'vrm{version}_{expression}',camera=portrait['camera']))
                        with av.open(shots[-1]) as container:
                            pixels=next(container.decode(video=0)).to_ndarray(format='rgb24')
                        colored=int((np.ptp(pixels.astype(float),axis=2)>20).sum())
                        assert colored>100,('Blank VRM face render',version,expression,colored,expression_geometry)
                    speech=await call('lip_sync',character=rig,text='Mama membuka buku. O, aku senang!',language='id',start_frame=50)
                    blink=await call('auto_blink',character=rig,frame_start=1,frame_end=144,interval_seconds=1.5)
                    motion=await call('talk_motion',character=rig,frame_start=50,frame_end=144)
                    life=await call('face_life',character=rig,frame_start=1,frame_end=144,seed=11)
                    glb=await call('export_asset',path=f'round3_vrm{version}.glb',objects=[rig],max_influences=4)
                    import struct
                    raw=Path(glb['path']).read_bytes();length=struct.unpack_from('<I',raw,12)[0]
                    document=json.loads(raw[20:20+length])
                    assert document.get('skins') and document.get('animations')
                    assert len(document.get('images',[]))>=3,'VRM -> GLB lost portable textures'
                    assert any('jawOpen' in mesh.get('extras',{}).get('targetNames',[]) for mesh in document['meshes'])
                    await call('save_project',path=f'round3_vrm{version}.blend')
                    results[str(version)]=dict(export=export,imported=info,deformation_m=deformation,expression_geometry=expression_geometry,pose=pose,walk=walk,hand=hand,speech=speech,blink=blink,motion=motion,life=life,glb=glb,stills=shots)
                    (OUT/'vrm_results.json').write_text(json.dumps(results,indent=2))
                    print('REAL VRM ROUNDTRIP OK',version,flush=True)
            elif mode=='faces':
                from photo_roundtrip_checks import run as faces
                await faces(call,python,still,index)
            else:raise ValueError(mode)
        finally:await session.call_tool('engine_shutdown',{})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--vrm',action='store_true');parser.add_argument('--vrm-version',type=int,choices=(0,1));parser.add_argument('--face-sheet',action='store_true');parser.add_argument('--face-case',type=int,choices=(0,1,2),default=0);args=parser.parse_args()
    if args.face_sheet:
        from photo_roundtrip_checks import sheet
        sheet()
    elif args.vrm:
        # Release Eevee/add-on caches between formats on the shared CPU machine.
        for version in ((args.vrm_version,) if args.vrm_version is not None else (0,1)):
            asyncio.run(run('vrm',versions=(version,)))
    else:asyncio.run(run('faces',args.face_case))
