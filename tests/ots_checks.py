"""Real OTS geometry: four lit views, mirrored shoulders and clean-cut continuity."""
import json
import os
from pathlib import Path
import shutil


async def run(call, text_of):
    assert os.environ.get('CHAR3D_PORT') == '9972', 'OTS checks require isolated port 9972'
    root = Path(os.environ['CHAR3D_WORKSPACE'])/'ots_polish'
    root.mkdir(exist_ok=True,parents=True)
    async def data(tool, **args):
        return json.loads(text_of(await call(tool,**args))[0])
    stored=root/('geometry_workbench.json' if os.environ.get('CHAR3D_EMOCAM_NO_STILLS') else 'measurements.json')
    evidence=json.loads(stored.read_text()) if stored.is_file() else {}
    for variant, frame in (('standing',70),('seated',45)):
        if os.environ.get('CHAR3D_OTS_VARIANT') not in (None, variant):
            continue
        await call('scene_info')
        await call('open_project',path='emocam/good_news_directed.blend')
        await call('run_blender_python',code="bpy.context.scene.render.threads_mode='FIXED'\nbpy.context.scene.render.threads=4\nbpy.context.scene.eevee.taa_render_samples=8\nresult=True")
        if variant == 'seated':
            await data('run_blender_python',code='''
from engine.commands import dispatch
from engine.commands.anim import clear_animation
sc=bpy.context.scene
sc.frame_set(1)
sc.frame_end=96
for name,az in [('Ana_rig',35),('Budi_rig',-35)]:
    rig=bpy.data.objects[name]
    clear_animation(name)
    dispatch('apply_pose',dict(armature=name,pose='relaxed'))
    chair=dispatch('add_prop',dict(kind='chair',location=[rig.location.x,rig.location.y,0],rotation_z=az))
    dispatch('sit_on',dict(character=name,seat=chair['root'],start_frame=1))
for name,peer,sign in [('Ana_rig','Budi_rig',1),('Budi_rig','Ana_rig',-1)]:
    dispatch('talk_motion',dict(character=name,frame_start=25,frame_end=70,
        look_at=[dict(frame_start=25,frame_end=70,target=peer,cheat_deg=35,side_sign=sign)],
        look_at_camera=False,life=0))
sc.frame_start=25
result=True
''')
        await call('set_lighting',preset='soft',subject=['Ana_rig','Budi_rig'])
        rows=[]
        for who,peer,label in (('Ana_rig','Budi_rig','a'),('Budi_rig','Ana_rig','b')):
            name=f'Polish_{variant}_{label}'
            shot=await data('camera_shot',subject=[who],foreground=peer,shot='ots',
                            start_frame=frame,end_frame=frame+24,name=name,
                            action_line=['Ana_rig','Budi_rig'])
            assert not shot['occlusion'].get('warning'),shot
            fg=shot['occlusion']['foreground']
            assert all(.20<=s['width']<=.35 and s['head_angle']>=115 for s in fg),fg
            assert all(.29<=p[1]<=.38 for p in shot['occlusion']['face_screen']),shot
            assert shot['occlusion']['after']<=.05 and 50<=shot['lens_mm'][0]<=85,shot
            clean=await data('camera_shot',subject=[who],shot='medium_close',
                start_frame=frame+25,end_frame=frame+49,name=name+'_clean',
                face_coverage=True,action_line=['Ana_rig','Budi_rig'],require_composition=True)
            check=await data('run_blender_python',code=f'''
import math,json
from engine.commands.gaze import head_frame
from engine.commands.ots import eye_point,shoulder_site
from engine.review import camera_checks
from engine.commands.cinematic import _focus
from mathutils import Vector
sc=bpy.context.scene
rig=bpy.data.objects[{who!r}];peer=bpy.data.objects[{peer!r}]
cam=bpy.data.objects[{name!r}];clean=bpy.data.objects[{(name+'_clean')!r}]
sides=[];angles=[]
for camera,frame in [(cam,{frame}),(cam,{frame+12}),(cam,{frame+24}),(clean,{frame+25})]:
    sc.frame_set(frame)
    p,q=[head_frame(bpy.data.objects[n])[0] for n in ['Ana_rig','Budi_rig']]
    pos=camera.matrix_world.translation
    sides.append((q-p).cross(pos-p).z)
    delta=pos-head_frame(rig)[0]
    angles.append(math.degrees(math.atan2(delta.x,-delta.y)))
change=abs((angles[2]-angles[3]+180)%360-180)
views=[dict(name='OTS',frames=[{frame},{frame+24}],subject=[{who!r}],size='medium_close',angle=angles[0],angle_end=angles[2],action_side=sides[0],move='static'),
       dict(name='clean',frames=[{frame+25},{frame+49}],subject=[{who!r}],size='medium_close',angle=angles[3],action_side=sides[3],move='static')]
assert min(sides)*max(sides)>0,sides
assert not [i for i in camera_checks(views) if i['severity']!='info'],views
sc.frame_set({frame+12})
objects,actions=[],[]
try:
    _focus(sc,cam,objects,actions)
    bpy.context.view_layer.update()
    focus=cam.data.dof.focus_object.matrix_world.translation
    assert (focus-eye_point(rig)).length<.005,(focus,eye_point(rig))
    subject_distance=(focus-cam.location).length
    partner_distance=(eye_point(peer)-cam.location).length
    assert subject_distance-partner_distance>.5,(subject_distance,partner_distance)
    result=dict(side_samples=sides,angle_change_deg=change,shoulder=cam['c3d_ots_shoulder'],
                focus_error_m=(focus-eye_point(rig)).length,subject_distance=subject_distance,
                foreground_distance=partner_distance,f_stop=cam.data.dof.aperture_fstop)
finally:
    cam.data.dof.focus_object=None;cam.data.dof.use_dof=False
    for obj in objects:bpy.data.objects.remove(obj,do_unlink=True)
    for action in actions:
        if action.users==0:bpy.data.actions.remove(action)
''')
            engine='workbench' if os.environ.get('CHAR3D_EMOCAM_NO_STILLS') else 'eevee'
            image=await data('render_preview',camera=name,frame=frame+12,width=384 if engine=='workbench' else 512,
                             height=216 if engine=='workbench' else 288,engine_name=engine)
            path=root/f'{variant}_{label}_{engine}.png'
            shutil.copyfile(image['path'],path)
            rows.append(dict(subject=who,partner=peer,shot=shot,clean=clean,
                             measurements=check['result'],still=str(path)))
        assert rows[0]['measurements']['shoulder'] != rows[1]['measurements']['shoulder'],rows
        assert rows[0]['measurements']['side_samples'][0]*rows[1]['measurements']['side_samples'][0]>0,rows
        assert rows[0]['shot']['occlusion']['foreground'][0]['side'] != rows[1]['shot']['occlusion']['foreground'][0]['side']
        evidence[variant]=rows
        stored.write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
        await call('save_project',path=f'ots_polish/{variant}.blend')
    print('OTS GEOMETRY OK',flush=True)
    return evidence


if __name__ == '__main__':
    import asyncio
    import argparse
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    parser=argparse.ArgumentParser()
    parser.add_argument('--variant',choices=['standing','seated'])
    args=parser.parse_args()
    if args.variant:os.environ['CHAR3D_OTS_VARIANT']=args.variant
    async def main():
        root=Path(__file__).resolve().parents[1]
        params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(root),
            env=dict(os.environ,CHAR3D_ALLOW_PYTHON='1'))
        async with stdio_client(params) as (r,w),ClientSession(r,w) as session:
            await session.initialize()
            async def call(tool,**params):
                result=await session.call_tool(tool,params)
                assert not result.isError,result
                print('OTS CHECK',tool,flush=True)
                return result
            try:
                await run(call,lambda result:[b.text for b in result.content if b.type=='text'])
            finally:
                await call('engine_shutdown')
    asyncio.run(main())
