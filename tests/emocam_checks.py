"""Small real MCP scenes; directed/mixed evidence uses the same scripts and voices."""
import json
import os
from pathlib import Path

SCENES = (
    ('argument', [
        ('Ana', 'Aku marah sekali! Kamu menyembunyikan kabar itu dariku. Mengapa?', 'angry'),
        ('Budi', 'Aku takut membuatmu kecewa. Maaf, seharusnya aku bicara sejak kemarin.', 'fear'),
        ('Ana', 'Kita harus saling percaya. Aku kesal, tetapi sekarang aku mau mendengar.', 'angry'),
        ('Budi', 'Terima kasih sudah mendengar. Kita akan menyelesaikan ini bersama.', 'smile')]),
    ('reunion', [
        ('Ana', 'Akhirnya kamu kembali. Aku senang kita bisa duduk bersama lagi.', 'smile'),
        ('Budi', 'Aku juga rindu. Tetapi ada kabar sedih. Ibu sudah tiada sebelum aku pulang.', 'sad'),
        ('Ana', 'Maaf, aku ikut sedih. Kamu boleh bercerita pelan-pelan, aku ada di sini.', 'sad'),
        ('Budi', 'Terima kasih. Rasanya hangat bisa pulang dan bertemu denganmu lagi.', 'smile')]),
    ('good_news', [
        ('Ana', 'Aku membawa sebuah surat. Coba dengarkan kabar yang baru datang pagi ini.', 'thinking'),
        ('Budi', 'Wah, ternyata kita diterima! Beasiswa itu untuk kita berdua. Aku senang sekali!', 'surprised'),
        ('Ana', 'Serius? Luar biasa! Akhirnya kerja keras kita membuahkan hasil yang indah.', 'big_smile'),
        ('Budi', 'Iya, kita berangkat bersama. Terima kasih sudah percaya sejak awal.', 'smile')]),
)


async def run(call, text_of):
    assert os.environ['CHAR3D_PORT']=='9972', 'Emocam evidence is restricted to 9972'
    root=Path(os.environ['CHAR3D_WORKSPACE'])/'emocam'
    root.mkdir(parents=True,exist_ok=True)
    async def data(tool, **args):
        return json.loads(text_of(await call(tool,**args))[0])
    evidence=json.loads((root/'comparison.json').read_text()) if os.environ.get('CHAR3D_EMOCAM_CASE') and (root/'comparison.json').is_file() else []
    for name, lines in SCENES:
        if os.environ.get('CHAR3D_EMOCAM_CASE') not in (None, name):
            continue
        script=dict(characters=[dict(id='Ana',gender=0,age=28,hair='short02',clothes=['female_casualsuit01','shoes01']),
                                dict(id='Budi',gender=1,age=30,hair='short02',clothes=['male_casualsuit01','shoes01'])],
                    beats=[dict(say=who,text=text,emotion=emotion) for who,text,emotion in lines])
        evidence=[e for e in evidence if e['name']!=name]
        pair={}
        for coverage in ('directed','mixed'):
            print(f'EMOCAM CHECK {name} {coverage}',flush=True)
            await call('scene_info')
            cached=root/f'{name}_directed_build.json'
            if coverage=='mixed' or cached.is_file() and os.environ.get('CHAR3D_EMOCAM_REUSE'):
                built=json.loads(cached.read_text())
                if isinstance(built['characters'], list):
                    built['characters']={n.removesuffix('_rig'): dict(rig=n,mesh=n.removesuffix('_rig'),realistic=True) for n in built['characters']}
                await call('open_project',path=f'emocam/{name}_directed.blend')
                recut=await data('run_blender_python',code=f"""
from engine.commands.dialog import dialog_direct
from engine.commands.camera import list_shots, delete_shot
from engine.commands.emocam import reactions
names={[c['rig'] for c in built['characters'].values()]!r}
for shot in list_shots()['shots']:
    if shot['camera'] in bpy.data.objects: delete_shot(shot['camera'])
reactions([],names,1,{built['frames'][1]})
result=dialog_direct({built['lines']!r},characters=names,camera={coverage!r},
    expression=None,motion=False,blink=False,gestures=None,idle=False,
    frame_start=1,frame_end={built['frames'][1]},shot_prefix='Emocam')
""")
                built.update({k:v for k,v in recut['result'].items() if k!='characters'})
            else:
                await call('new_scene',frame_end=2)
                built=await data('script_to_scene',script=script,camera=coverage,language='id',seed=11,
                                 voice=True,sound=True,subtitles=False,music=None,look='studio_film')
            (root/f'{name}_{coverage}_build.json').write_text(json.dumps(built,ensure_ascii=False,indent=2))
            await call('save_project',path=f'emocam/{name}_{coverage}.blend')
            reviewed=await data('review_scene',level='standard',sheet=True,size=256,engine='workbench',
                                frames=[(s['frames'][0]+s['frames'][1])//2 for s in built['shots']])
            (root/f'{name}_{coverage}_review.json').write_text(json.dumps(reviewed,ensure_ascii=False,indent=2))
            pair[coverage]=dict(score=reviewed['score'],stats=reviewed['camera'],sheet=reviewed['contact_sheet'],
                                issues=reviewed['issues'],shots=built['shots'])
            (root/'comparison.json').write_text(json.dumps(evidence+[dict(name=name,**pair)],ensure_ascii=False,indent=2))
            if coverage=='directed':
                assert built['emotion_curve'] and built['reactions'], built
                roles={s.get('reason',{}).get('role') for s in built['shots']}
                assert {'establish','reaction','OTS'}<=roles,roles
                assert all(s.get('reason',{}).get('emotion') for s in built['shots'])
                sample=await data('run_blender_python',code=f'''
from engine.commands.face import _basemesh
result=[]
for event in {built['reactions']!r}:
    bpy.context.scene.frame_set(event['peak'])
    base=_basemesh(event['character'])
    keys=[k for k in base.data.shape_keys.key_blocks if k.name.startswith('__c3d_reaction_')]
    delta=max((abs(k.value) for k in keys),default=0.)
    result.append(dict(character=event['character'],frame=event['peak'],delta=delta))
''')
                assert any(s['delta']>.05 for s in sample['result']),sample
                pair[coverage]['reaction_deltas']=sample['result']
                faults=[i for i in reviewed['issues'] if i['category'] in ('camera','rhythm') and i['severity'] in ('warn','error')]
                assert not faults,(name,faults)
                assert reviewed['score']>=90,(name,reviewed['score'],reviewed['issues'])
        evidence.append(dict(name=name,**pair))
        (root/'comparison.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
        print(f"EMOCAM {name}: directed {pair['directed']['score']} / mixed {pair['mixed']['score']} | "
              f"shots {pair['directed']['stats']['shot_count']} / {pair['mixed']['stats']['shot_count']}",flush=True)
    # Listener-focus evidence; mirrored standing/seated OTS stills follow below.
    if os.environ.get('CHAR3D_EMOCAM_CASE') not in (None, 'good_news'):
        return
    await call('open_project',path='emocam/good_news_directed.blend')
    built=json.loads((root/'good_news_directed_build.json').read_text())
    reaction=next((r for r in built['reactions'] if r['expression']=='surprised'), built['reactions'][0])
    proof=await data('run_blender_python',code=f"""
from engine.commands.cinematic import _focus, _eye
from engine.commands.camera import list_shots
sc=bpy.context.scene
shot=next(s for s in list_shots()['shots'] if s['frames'][0]<={reaction['peak']}<=s['frames'][1])
cam=bpy.data.objects[shot['camera']]
objects,actions=[],[]
a=shot['frames'][0]
try:
    _focus(sc,cam,objects,actions)
    target=cam.data.dof.focus_object
    assert target and cam.get('c3d_focus_from')
    sc.frame_set(a)
    incoming=(target.matrix_world.translation-_eye(bpy.data.objects[{reaction['speaker']!r}])).length
    sc.frame_set(a+8)
    focused=(target.matrix_world.translation-_eye(bpy.data.objects[{reaction['character']!r}])).length
    assert incoming<.02 and focused<.02,(incoming,focused)
    result=dict(incoming_error_m=incoming,listener_error_m=focused)
finally:
    cam.data.dof.focus_object=None
    cam.data.dof.use_dof=False
    for obj in objects: bpy.data.objects.remove(obj,do_unlink=True)
    for action in actions:
        if action.users==0: bpy.data.actions.remove(action)
""")
    (root/'focus_proof.json').write_text(json.dumps(proof,indent=2))
    if not os.environ.get('CHAR3D_EMOCAM_NO_STILLS'):
        final=await call('render_frames',frames=[reaction['peak']],camera='scene',
                         engine_name='eevee',size=384,prefix=str(root/'final'))
        (root/'final_stills.json').write_text(json.dumps(text_of(final),ensure_ascii=False,indent=2))
    from ots_checks import run as ots_checks
    await ots_checks(call,text_of)
    print('EMOCAM E2E OK',flush=True)
