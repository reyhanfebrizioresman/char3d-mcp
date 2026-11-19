"""Isolated real MCP review evidence, used by e2e_smoke --review-only."""
import json
import os
from pathlib import Path
import time
import textwrap


async def run(call,text_of):
    root=Path(__file__).resolve().parents[1];work=root/'output';report={}
    async def data(tool,**args):
        if tool=='run_blender_python':args['code']=textwrap.dedent(args['code'])
        start=time.monotonic(); result=json.loads(text_of(await call(tool,**args))[0])
        report.setdefault('calls',[]).append(dict(tool=tool,seconds=round(time.monotonic()-start,4)))
        print('REVIEW CHECK',tool,report['calls'][-1]['seconds'],flush=True)
        return result
    def save(): (work/'review_e2e.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    await data('scene_info')
    await data('new_scene',frame_end=2)
    # Bulk rejection must agree with the original exact BVH casts, including
    # transformed/non-uniform meshes and rays parallel to bounds planes.
    proof=await data('run_blender_python',code='''
import numpy as np
from mathutils import Vector
from engine.commands.occlusion import _Mesh
from engine.commands import dispatch
bpy.ops.mesh.primitive_cube_add(location=(.3,.5,1),rotation=(.2,.4,.6),scale=(.5,1.2,.8))
obj=bpy.context.object
bpy.context.view_layer.update()
probe=_Mesh(obj,bpy.context.evaluated_depsgraph_get(),1.8)
rng=np.random.default_rng(17)
targets=np.vstack([rng.uniform(-3,3,(600,3)),[(0,-4,1),(0,4,1),(2,-4,1)]])
errors=0
for origin in (Vector((0,-4,1)),obj.location.copy(),Vector((2,0,0))):
    exact=np.array([probe.hit(origin,Vector(t)) for t in targets])
    errors+=int(np.count_nonzero(exact!=probe.hits(origin,targets)))
dispatch('camera_shot',dict(subject=[obj.name],shot='full',start_frame=1,end_frame=12,name='ReviewBinding',avoid_occlusion=False))
marker=bpy.context.scene.timeline_markers.new('ReviewReturn',frame=14)
marker.camera=bpy.data.objects['ReviewBinding']
dispatch('camera_shot',dict(subject=[obj.name],shot='full',start_frame=1,end_frame=24,name='ReviewBinding',avoid_occlusion=False))
bindings_preserved=marker.camera is bpy.data.objects['ReviewBinding']
bpy.context.scene.timeline_markers.remove(marker)
dispatch('delete_shot',dict(name='ReviewBinding'))
bpy.data.objects.remove(obj,do_unlink=True)
result=dict(rays=3*len(targets),errors=errors,bindings_preserved=bindings_preserved)
''')
    assert proof['result']['errors']==0 and proof['result']['bindings_preserved'],proof
    report['geometry_proof']=proof['result']
    if os.environ.get('CHAR3D_REVIEW_REUSE'):
        await data('open_project',path='review_fault.blend')
    else:
        script=dict(title='Review faults',environment='living_room',music=None,characters=[
            dict(id='Ana',gender=0,hair='bob01',clothes=['female_casualsuit01','shoes01']),
            dict(id='Budi',gender=1,hair='short01',clothes=['male_casualsuit01','shoes01'])],beats=[
            dict(do='camera',shot='medium',subject='Ana'),dict(do='pause',seconds=.5),
            dict(do='camera',shot='medium',subject='Ana'),dict(say='Ana',text='Halo Budi, senang bertemu lagi.'),
            dict(do='camera',shot='medium',subject='Budi'),dict(say='Budi',text='Aku juga senang. Mari duduk bersama.'),
            dict(do='pause',seconds=23)])
        built=await data('script_to_scene',script=script,language='id',look='none',music=None)
        assert all(c['realistic'] for c in built['characters'].values()),built['warnings']
        report['built']=built
        cast=[c['rig'] for c in built['characters'].values()]
        # A wide trajectory deliberately labelled/commissioned as medium is an undersized-subject fault.
        frame=built['plan']['beats'][4]['frames'][0]
        tiny=await data('camera_shot',subject=[cast[1]],shot='extreme_wide',move='static',angle=20,
                        start_frame=frame,end_frame=built['frames'][1],name='FaultTiny',avoid_occlusion=False)
        await data('run_blender_python',code=f'''
    import json
    from engine.commands.talk import _data_curves
    for rig_name in {cast!r}:
        rig=bpy.data.objects[rig_name]
        for mesh in [o for o in rig.children_recursive if o.type=='MESH' and o.data.shape_keys]:
            for fc in _data_curves(mesh.data.shape_keys):
                if 'eyeBlink' in fc.data_path:
                    for point in fc.keyframe_points: point.co.y=0
            for key in mesh.data.shape_keys.key_blocks:
                if 'eyeBlink' in key.name: key.value=0
    cam=bpy.data.objects['FaultTiny']
    cam['c3d_shot']['shot_size']='medium'
    args=json.loads(cam['c3d_shot_args']);args['shot']='medium';cam['c3d_shot_args']=json.dumps(args)
    bpy.context.scene.render.threads_mode='FIXED';bpy.context.scene.render.threads=4
    result=True
    ''')
        await data('auto_music',mood='calm',backend='synth',seed=7)
        await data('duck_music',amount_db=0)
        await data('add_subtitles',style='classic',lines=[dict(text='Caption deliberately rushed through a tiny reading window.',start=24,end=24.3)],max_words=3)
        await data('save_project',path='review_fault.blend')
    report['quick']=await data('review_scene',level='quick',size=192)
    before=await data('review_scene',level='standard',size=256)
    report['before']=before
    expected={'jump_cut':'camera','short_shot':'rhythm','missing_blink':'performance','small_subject':'camera',
              'subtitle_speed':'readability','music_ducking':'sound'}
    for rule,category in expected.items():
        assert any(i['id'].split(':')[0]==rule and i['category']==category and i['severity']=='warn' for i in before['issues']),(rule,before['issues'])
    after=await data('review_scene',level='standard',fix=True,size=256)
    report['after']=after;save()
    assert after['fix_rounds']==1
    remaining={i['id'].split(':')[0] for i in after['issues']}
    assert not {'missing_blink','subtitle_speed','music_ducking','jump_cut','small_subject'}&remaining,after['issues']
    assert 'short_shot' in remaining
    assert all(i['fix'] for i in after['issues'] if i['id'].split(':')[0] in ('short_shot','long_static','face_turned'))
    await data('save_project',path='review_fixed.blend')
    # Draft is intentionally short; serial_video runs the native worker with editor stopped.
    draft=await data('render_video',path='review_fault_draft.mp4',quality='draft',width=384,height=216,
                     frame_start=1,frame_end=48,wait=True)
    report['video']=await data('review_video',path=draft['path'])
    report['credits']=await data('credits')
    content=Path(report['credits']['path']).read_text()
    assert 'CC0' in content and 'Piper' in content and 'GPL-3.0' in content and 'Font' in content
    assert Path(draft['path']).with_name('CREDITS.txt').is_file()
    for language,cues in [('id',('[KAMERA: medium Ana, push in]','[MUSIK: tegang]','[HENING 1 detik]','[KAMERA: otomatis]')),
                          ('en',('[CAMERA: medium Ana, push in]','[MUSIC: tense]','[SILENCE 1 second]','[CAMERA: auto]'))]:
        await data('new_scene',frame_end=2)
        script='LOKASI: living_room\n'+cues[0]+'\nAna (female, 28): Halo.\n'+cues[1]+'\n'+cues[2]+'\nBudi (male, 30): Selamat datang.\n'+cues[3]+'\nAna: Terima kasih.'
        parsed=await data('script_to_scene',script=script,build=False,voice=False)
        assert not parsed['plan']['warnings'],parsed['plan']['warnings']
        built=await data('script_to_scene',script=script,voice=False,sound=True,language='id',look='none')
        assert built['director_cues']['silences']
        assert built['music']['cue_sections']
        await data('render_frames',frames=[2],camera='scene',size=192)
        report['cues_'+language]=built
    await data('new_scene',frame_end=2)
    film_script='''JUDUL: Review two scenes
Ana (female, 28)
Budi (male, 30)
SCENE 1: Opening
LOKASI: living_room
Ana: Halo Budi.
Budi: Selamat pagi.
[pause 1 second]
[TRANSITION: dissolve 0.5 seconds, J-cut 0.4]
SCENE 2: Return
LOKASI: living_room
Ana: Sampai bertemu lagi.
Budi: Aku tunggu.
[pause 1 second]
'''
    film=await data('script_to_film',script=film_script,name='ReviewFilm',voice=False,music=None,look='none')
    report['film_build']=film
    origin=await data('scene_info')
    review=await data('review_film',name='ReviewFilm',level='quick',size=192)
    assert len(review['scenes'])==2 and review['contact_sheet']
    restored=await data('scene_info')
    assert origin==restored,'review_film did not restore editor'
    movie=await data('render_film',name='ReviewFilm',path='review_jcut.mp4',quality='draft',width=320,height=180,wait=True)
    assert movie['status']=='done',movie
    report['jcut_movie']=movie
    import av
    with av.open(movie['path']) as clip:
        assert len(list(clip.decode(video=0)))==movie['frames'][1]
    report['film']=review
    report['film_credits']=await data('credits',name='ReviewFilm')
    save()
    print('REVIEW E2E OK',flush=True)
