"""Real CC0 VRoid performance contracts. Called by e2e_smoke --vrm-actors-only."""
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/vrm_actors'
SCRIPT={
 'title':'Kabar Baik','environment':'podcast_studio',
 'characters':[{'id':'Nara','vrm':'vrm/HairSample_Female.vrm','gender':0,'age':27},
               {'id':'Bayu','vrm':'vrm/HairSample_Male.vrm','gender':1,'age':29}],
 'beats':[{'say':'Nara','text':'Bayu, lihat! Akhirnya karakter kita bisa bergerak.','emotion':'smile'},
          {'say':'Bayu','text':'Serius? Wah, bagus sekali! Ekspresinya ikut berubah.','emotion':'surprised'},
          {'say':'Nara','text':'Berhasil. Sekarang giliran kamu!','emotion':'smile'}]}

async def checks(tool):
    assert os.environ.get('CHAR3D_PORT')=='9976','VRM actors own only engine port 9976'
    assert Path(os.environ['CHAR3D_WORKSPACE']).resolve()==(ROOT/'output').resolve()
    OUT.mkdir(exist_ok=True,parents=True)
    reuse=os.environ.get('CHAR3D_VRM_ACTORS_REUSE_PERFORMANCE')=='1'
    report=json.loads((OUT/'e2e_progress.json').read_text()) if reuse else {}
    async def call(name,**args):
        print('VRM ACTORS',name,flush=True)
        result=await tool(name,**args)
        report.setdefault('calls',[]).append(dict(tool=name,result=result))
        (OUT/'e2e_progress.json').write_text(json.dumps(report,indent=2,default=str))
        return result
    async def python(code):return (await call('run_blender_python',code=code))['result']
    if reuse:
        assert (ROOT/'output/projects/vrm_actors/performance.blend').is_file()
        assert any(c['tool']=='export_asset' for c in report['calls'])
        return await finish(call,report,json.loads((OUT/'build.json').read_text()))
    await call('scene_info')
    await call('new_scene',frame_end=2)
    before=await call('scene_info')
    plan=await call('script_to_scene',script=SCRIPT,build=False,language='id')
    after=await call('scene_info')
    assert before==after,'parse-only mutated scene'
    assert all(c['vrm_meta']['licence']=='CC0' for c in plan['plan']['characters'])
    built=await call('script_to_scene',script=SCRIPT,camera='directed',look='studio_film',style='anime',
                     seed=44,tts_engine='piper',language='id',sound=True,music='warm',subtitles=True)
    (OUT/'build.json').write_text(json.dumps(built,indent=2))
    rigs=[c['rig'] for c in built['characters'].values()]
    assert all(c.get('source')=='vrm' and abs(c['normalization']['ground_z'])<1e-5 for c in built['characters'].values())
    assert len(built['lines'])==3 and built['shots'] and built['voices']
    assert built['generated_files'] or built['cache_hits']
    assert all(built['secondary_motion'][r]['chains']>0 for r in rigs)
    await call('save_project',path='vrm_actors/kabar_anime.blend')
    await call('credits',path='../vrm_actors/CREDITS.txt')
    # Verify authored morphs, head/eye/face landmarks, skeleton and fingers move.
    measured=await python(f'''import json,numpy as np,hashlib
from engine.commands.face_geometry import FaceGeometry
from engine.commands.anim import semantic_map
from engine.commands.talk import _data_curves
result={{}}
for name in {rigs!r}:
 r=bpy.data.objects[name];face=next(o for o in r.children_recursive if o.type=='MESH' and o.get('c3d_kind')=='humanoid')
 keys=face.data.shape_keys.key_blocks
 fg=FaceGeometry(r,1.7);points=fg.points()
 mouth_slots={{i for i,s in enumerate(face.material_slots) if s.material and 'facemouth' in s.material.name.lower()}}
 mouth_ids=sorted({{i for p in face.data.polygons if p.material_index in mouth_slots for i in p.vertices}})
 mouth_eye_delta=max((keys['eyeWideLeft'].data[i].co-keys[0].data[i].co).length for i in mouth_ids)
 result[name]=dict(bones=len(r.data.bones),vertices=sum(len(o.data.vertices) for o in r.children_recursive if o.type=='MESH'),
  hips_connected=r.data.bones[semantic_map(r)['hips']].use_connect,
  gaze_degrees=json.loads(r['c3d_vrm_gaze_degrees']),
  weights_sha256=hashlib.sha256(repr([(o.name,[(v.index,[(g.group,g.weight) for g in v.groups]) for v in o.data.vertices]) for o in r.children_recursive if o.type=='MESH']).encode()).hexdigest(),
  head=semantic_map(r)['head'],sites=list(fg.sites),mouth=list(sum(points['mouth'],Vector())/len(points['mouth'])),
  eye=list(points['eye']),width=fg.width,curves=len(_data_curves(r)),mouth_eye_delta_m=mouth_eye_delta,
  morphs={{n:float(np.max(np.linalg.norm(np.array([v.co[:] for v in keys[n].data])-np.array([v.co[:] for v in keys[0].data]),axis=1))) for n in ('jawOpen','mouthSmileLeft','eyeBlinkLeft','eyeWideLeft')}})
''')
    assert all(min(v['morphs'].values())>.0001 and v['curves']>30 and v['width']>.03 for v in measured.values()),measured
    assert not any(v['hips_connected'] for v in measured.values()),measured
    assert all(v['gaze_degrees']==dict(In=8.,Out=12.,Up=10.,Down=10.) for v in measured.values()),measured
    assert all(v['mouth_eye_delta_m']<1e-8 for v in measured.values()),'Listener eye reactions moved mouth geometry'
    report['measurements']=measured
    # All three desk sets and their seating/stand-up paths use the imported rigs.
    for environment in ('podcast_studio','office','news_desk'):
        await call('open_project',path='vrm_actors/kabar_anime.blend')
        await call('set_timeline',frame_end=36)
        await call('set_environment',preset=environment,subject=rigs)
        stage=await call('stage_dialog',characters=rigs)
        assert stage.get('desk') or stage.get('staging') or any('seat' in str(v).lower() for v in stage.values()),stage
        await call('stand_up',character=rigs[0],start_frame=1,transition_frames=20)
        await call('render_views',objects=[rigs[0]],size=256)
    await call('open_project',path='vrm_actors/kabar_anime.blend')
    await call('clear_environment')
    # Extend after dialog so its speech/face/gesture layers remain in the scene.
    frame=built['frames'][1]+1
    await call('set_timeline',frame_end=frame+24)
    for r in rigs:
        await call('stand_up',character=r,start_frame=frame,transition_frames=20)
    walk=await call('walk_path',armature=rigs[0],points=[[-.25,-.6]],start_frame=frame+24,avoid=False)
    frame=walk['frames'][1]+4
    for kind in ('handshake','hug'):
        interaction=await call('interact',a=rigs[0],b=rigs[1],kind=kind,start_frame=frame,approach=True,hold_seconds=.3)
        frame=interaction['frames']['end']+4
    prop=await call('add_prop',kind='cup',location=[0,-1,0])
    await call('hold_prop',character=rigs[0],prop=prop['root'],hand='right',start_frame=frame)
    fingers=await call('set_hand_pose',character=rigs[1],shape='peace',side='left',frame=frame,keyframe=True)
    assert fingers['bones']>=12,fingers
    await call('set_timeline',frame_end=frame+24)
    for r in rigs:
        motion=await call('secondary_motion',character=r,parts=['hair','clothes'],frame_start=1,frame_end=frame+24)
        assert motion['native_vrm'] and motion['chains']>0
    await call('resolve_collisions',characters=rigs,frame_start=frame,frame_end=frame+12)
    await call('auto_sfx',characters=rigs,seed=44)
    await call('render_views',objects=rigs,size=256)
    asset=await call('export_asset',path='vrm_actors/performance.glb',objects=rigs,max_influences=4)
    from engine.vrm import read_document
    document=read_document(asset['path'])
    assert document.get('skins') and document.get('animations') and len(document.get('images',[]))>3
    weights=await python(f'''import hashlib
result=dict((name,hashlib.sha256(repr([(o.name,[(v.index,[(g.group,g.weight) for g in v.groups]) for v in o.data.vertices]) for o in bpy.data.objects[name].children_recursive if o.type=='MESH']).encode()).hexdigest()) for name in {rigs!r})''')
    assert all(weights[n]==measured[n]['weights_sha256'] for n in rigs),'Performance/export changed authored weights'
    await call('save_project',path='vrm_actors/performance.blend')
    return await finish(call,report,built)


async def finish(call,report,built):
    # A film imports once, then reuses a packed native actor template; wardrobe is ignored.
    film=await call('script_to_film',script={'title':'VRM continuity','characters':[SCRIPT['characters'][0]],'scenes':[
        {'beats':[{'say':'Nara','text':'Halo.'}]},
        {'beats':[{'do':'outfit','who':'Nara','outfit':'winter'},{'say':'Nara','text':'Kembali.'}]}]},
        voice=False,sound=False,music=None,life=0,camera='none')
    scenes=film['film']['scenes']
    assert scenes[0]['characters']['Nara']['actor_import']=='VRM add-on'
    assert scenes[1]['characters']['Nara']['actor_import']=='cached native actor'
    assert any('outfit change ignored' in w for w in film['warnings'])
    await call('new_scene',frame_end=2)
    direct=await call('dialog',characters=SCRIPT['characters'],lines=[
        {'speaker':'Nara','text':'Halo, Bayu!'}, {'speaker':'Bayu','text':'Wah, bagus!'}],
        voice=True,tts_engine='piper',language='id',camera='directed',seed=44)
    assert len(direct['actors'])==2 and direct['shots'] and direct['voices']
    assert all(v['native_vrm'] for v in direct['secondary_motion'].values())
    await call('open_project',path='vrm_actors/kabar_anime.blend')
    (OUT/'e2e.json').write_text(json.dumps(report,indent=2,default=str))
    print('VRM ACTORS E2E OK',flush=True)
    return built

async def run(call,text_of):
    async def tool(name,**args):
        value=await call(name,**args)
        if name=='render_views':
            # The public MCP tool returns the four rendered images plus JSON.
            return [json.loads(t) for t in text_of(value)]
        return json.loads(text_of(value)[0])
    await checks(tool)
