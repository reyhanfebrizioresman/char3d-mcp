"""Reproduce material evidence, exclusively port 9971, one Blender at a time.

CHAR3D_PORT=9971 CHAR3D_WORKSPACE=$PWD/output .venv/bin/python -u tests/materials_visuals.py --stills --bench --clip
--cast Lina / --looks studio soft / --reuse restrict or resume expensive visual work.
Previews <=512 px. Benchmarks include setup/restoration and PNG I/O; warm-ups excluded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.append('/usr/lib/python3/dist-packages')
from mcp_server.blender_client import BlenderClient

if os.environ.get('CHAR3D_PORT') != '9971':
    raise SystemExit('Material verification requires CHAR3D_PORT=9971')
os.environ['CHAR3D_ALLOW_PYTHON'] = '1'
os.environ['CHAR3D_RENDER_CALIB'] = str(ROOT/'output/materials_calibration.json')
WORK = Path(os.environ.get('CHAR3D_WORKSPACE', ROOT/'output'))
os.environ.setdefault('MESA_SHADER_CACHE_DIR',str(WORK/'mesa_cache'))
# Keep llvmpipe from allocating a worker pool for every advertised host CPU.
# Benchmarks inherit the host setting; visual evidence records its own setting.
if '--bench' not in sys.argv:
    os.environ.setdefault('LP_NUM_THREADS','4')
Path(os.environ['MESA_SHADER_CACHE_DIR']).mkdir(parents=True,exist_ok=True)
SHEETS = WORK/'material_sheets'
SHEETS.mkdir(parents=True, exist_ok=True)
c = BlenderClient()
CAST = {
    'Lina':dict(gender=0,age=24,race={'caucasian':1},hair='ponytail01'),
    'Nia':dict(gender=0,age=30,race={'african':1},hair='afro01'),
    'Arman':dict(gender=1,age=34,race={'asian':.6,'caucasian':.4},skin='toigo_light_skin_male_bronze',hair='short02'),
    'Elder':dict(gender=1,age=76,race={'caucasian':1},hair='short01'),
    'Child':dict(gender=0,age=9,race={'asian':.5,'caucasian':.5},hair='ponytail01',height=.3),
    'Mei':dict(gender=0,age=29,race={'asian':1},hair='toigo_curled_under_bob'),
    'Sari':dict(gender=0,age=31,race={'asian':.75,'african':.25},skin='cutoff3d_indian_female_skin',hair='braid01'),
}
LOOKS = ('studio','soft','golden_hour','night','misty_morning')
SHOTS = ('close_up','extreme_close_up','medium')
REVISION = hashlib.sha256((ROOT/'engine/materials.py').read_bytes()+(ROOT/'engine/commands/materials.py').read_bytes()).hexdigest()

# Cache the two real shader graphs while comparing lights. Unused attributes do
# not shade the MPFB variant. Lifecycle/restore assertions use the real command in
# materials_checks.py; benchmarks also use uncached commands in a fresh engine.
COMPARE_CACHE = '''import json
from engine.commands import REGISTRY
from engine.commands.materials import _family, scene_cost_factor
_compare_upgrade=REGISTRY['upgrade_materials']
_compare_new=REGISTRY['new_scene']
_compare_save=REGISTRY['save_project']
_compare_cache={}
def compare_upgrade(character,quality='enhanced',**params):
    if params: return _compare_upgrade(character,quality=quality,**params)
    if character not in _compare_cache:
        result=_compare_upgrade(character,quality=quality)
        if quality=='enhanced':
            root,body,meshes=_family(character)
            slots=[]
            for obj in meshes:
                states=json.loads(obj.get('c3d_material_slots','[]'))
                for i,state in enumerate(states):
                    mat=obj.material_slots[i].material
                    if mat and mat.get('c3d_material_version'):
                        slots.append((obj,i,state['link'],mat))
            _compare_cache[character]=(result,slots)
        return result
    result,slots=_compare_cache[character]
    for obj,i,link,mat in slots:
        slot=obj.material_slots[i]
        if quality=='enhanced':
            slot.link='OBJECT';slot.material=mat
        else:
            slot.link=link
            if link=='OBJECT': slot.material=obj.get('c3d_material_original_'+str(i))
    cost=scene_cost_factor(bpy.context.scene,'BLENDER_EEVEE')
    return dict(result,quality=quality,comparison_cache=True,materials_cost_factor=cost) if quality=='enhanced' else dict(
        character=character,quality=quality,comparison_cache=True,materials_cost_factor=cost)
def compare_new(**params):
    _compare_cache.clear()
    return _compare_new(**params)
def compare_save(**params):
    for mat in bpy.data.materials:
        if mat.get('c3d_material_version'): mat.use_fake_user=False
    return _compare_save(**params)
REGISTRY['upgrade_materials']=compare_upgrade
REGISTRY['new_scene']=compare_new
REGISTRY['save_project']=compare_save
result=True
'''


def call(cmd, **params):
    if cmd == 'render_views':
        size = params.pop('size', 160)
        return [call('render_preview', view=view, width=size, height=size, **params)
                for view in ('front', 'right', 'back', 'three_quarter')]
    start = time.perf_counter()
    r = c.call(cmd, **params)
    print(cmd, params.get('name',params.get('preset',params.get('quality',''))), round(time.perf_counter()-start,2), flush=True)
    return r


def python(code):
    return call('run_python', code=code)['result']


def setup():
    python(f'''import importlib,os,shutil
module='bl_ext.user_default.mpfb'
home={str(WORK/'mpfb_test')!r}
os.makedirs(home,exist_ok=True)
source=os.path.join(bpy.utils.extension_path_user(module),'data')
if not os.path.isdir(os.path.join(home,'data')): shutil.copytree(source,os.path.join(home,'data'))
cls=importlib.import_module(module+'._preferences').MpfbPreferences
if 'bl_rna' not in cls.__dict__: bpy.utils.register_class(cls)
a=bpy.context.preferences.addons.get(module)
if a is None:
    a=bpy.context.preferences.addons.new();a.module=module
a.preferences.mpfb_user_data=home
sc=bpy.context.scene
sc.render.threads_mode='FIXED';sc.render.threads=4
sc.render.resolution_x=512;sc.render.resolution_y=512
result=True
''')


def build(name, extra=False):
    call('scene_info')
    call('new_scene', frame_end=72)
    setup()
    args = dict(CAST[name])
    suit = 'female' if args['gender'] < .5 else 'male'
    clothes = [f'{suit}_casualsuit01','shoes01']
    h = call('create_realistic_human',name=name,**args,clothes=clothes,materials='mpfb')
    call('render_views', objects=[h['armature']],size=160,engine='workbench')
    call('apply_pose',armature=h['armature'],pose='relaxed')
    call('set_expression',character=h['armature'],expression='smile',strength=.25)
    if extra:
        b = call('create_realistic_human',name='Partner',gender=1,age=35,race={'african':.5,'asian':.5},
                 hair='short02',clothes=['male_casualsuit01','shoes01'],location=[.75,.25,0],materials='mpfb')
        call('render_views',objects=[b['armature']],size=160,engine='workbench')
        call('apply_pose',armature=b['armature'],pose='relaxed')
    call('set_lighting',preset='studio',subject=[h['armature']])
    call('camera_shot',subject=[h['armature']],shot='close_up',start_frame=1,end_frame=72,
         name='MaterialPortrait',angle=8,elevation=0,avoid_occlusion=False,depth_of_field=False)
    call('save_project',path=f'materials_{name}{"_pair" if extra else ""}.blend')
    return h


def make_sheet(records, name, shot, looks, tag=None):
    from PIL import Image, ImageDraw
    tile=384
    out=Image.new('RGB',(tile*2,(tile+28)*len(looks)+28),'#20252b')
    d=ImageDraw.Draw(out)
    for col,q in enumerate(('mpfb','enhanced')):
        d.text((col*tile+12,8),name+' | '+q+' | '+shot,fill='white')
        for row,look in enumerate(looks):
            key=f'{name}/{look}/{shot}/{q}'
            if key not in records: continue
            im=Image.open(records[key]['path']).convert('RGB').resize((tile,tile))
            y=28+row*(tile+28)
            out.paste(im,(col*tile,y));d.text((col*tile+12,y+tile+7),look,fill='white')
    path=SHEETS/f'{name}_{tag or shot}.png'
    out.save(path)
    print('SHEET',path,flush=True)


def stills(args):
    if not args.uncached and not args.bench: python(COMPARE_CACHE)
    file=WORK/'materials_visuals.json'
    records=json.loads(file.read_text()) if file.exists() else {}
    for name in args.cast or CAST:
        project=WORK/'projects'/f'materials_{name}.blend'
        if args.reuse and project.exists(): call('open_project',path=str(project))
        else: build(name)
        for look in args.looks or LOOKS:
            call('cinematic_look',clear=True)
            call('set_lighting',preset=look if look in ('studio','soft') else 'studio',subject=[name+'_rig'])
            if look not in ('studio','soft'):
                call('cinematic_look',preset=look)
            for shot in args.shots or SHOTS:
                result=call('camera_shot',subject=[name+'_rig'],shot=shot,start_frame=1,end_frame=72,
                            name='MaterialPortrait',angle=8,elevation=0,avoid_occlusion=False,
                            depth_of_field=None if look not in ('studio','soft') else False)
                assert result['shot_size'] == shot
                for quality in ('mpfb','enhanced'):
                    key=f'{name}/{look}/{shot}/{quality}'
                    if args.reuse and key in records and Path(records[key]['path']).exists() and (
                        quality == 'mpfb' or records[key].get('revision') == REVISION): continue
                    upgraded=call('upgrade_materials',character=name+'_rig',quality=quality)
                    start=time.perf_counter()
                    size = min(args.max_size, 512 if shot == 'extreme_close_up' else 384 if shot == 'close_up' else 256)
                    r=call('render_preview',camera='scene',engine='eevee',width=size,height=size,
                           filename=f'materials_{name}_{look}_{shot}_{quality}.png')
                    records[key]=dict(path=r['path'],size=r['size'],seconds=time.perf_counter()-start,revision=REVISION,
                                      profile=upgraded.get('skin_profile'),sampled_skin_rgb=upgraded.get('sampled_skin_rgb'),
                                      llvmpipe_threads=os.environ.get('LP_NUM_THREADS'))
                    file.write_text(json.dumps(records,indent=2))
            for shot in args.shots or SHOTS:
                make_sheet(records,name,shot,[x for x in LOOKS if f'{name}/{x}/{shot}/enhanced' in records])
        call('upgrade_materials',character=name+'_rig',quality='enhanced')
        call('cinematic_look',clear=True)
        call('save_project',path=f'materials_{name}_enhanced.blend')


def bench(args):
    file=WORK/'materials_benchmark.json'
    records={}
    build('Lina',extra=True)
    python("sc=bpy.context.scene;sc.render.resolution_x=512;sc.render.resolution_y=288;result=True")
    for shot in ('close_up','medium','wide'):
        subjects=['Lina_rig','Partner_rig'] if shot in ('medium','wide') else ['Lina_rig']
        call('camera_shot',subject=subjects,shot=shot,start_frame=1,end_frame=72,
             name='MaterialPortrait',angle=8,elevation=0,avoid_occlusion=False,depth_of_field=False)
        records[shot]={}
        # ABBA order reduces clock/load drift; first frame of each shader is cold.
        for quality in ('mpfb','enhanced','enhanced','mpfb'):
            for name in ('Lina_rig','Partner_rig'):
                call('upgrade_materials',character=name,quality=quality)
            start=time.perf_counter()
            call('render_preview',camera='scene',engine='eevee',width=320,height=180,filename=f'material_warm_{shot}_{quality}.png')
            warm=time.perf_counter()-start
            start=time.perf_counter()
            call('render_preview',camera='scene',engine='eevee',width=512,height=288,filename=f'material_bench_{shot}_{quality}.png')
            elapsed=time.perf_counter()-start
            records[shot].setdefault(quality,[]).append(dict(warm=warm,seconds=elapsed))
            file.write_text(json.dumps(records,indent=2))
        for q in ('mpfb','enhanced'):
            records[shot][q+'_mean']=sum(s['seconds'] for s in records[shot][q])/2
        records[shot]['ratio']=records[shot]['enhanced_mean']/records[shot]['mpfb_mean']
        file.write_text(json.dumps(records,indent=2))
        print('BENCH',shot,records[shot],flush=True)
    call('save_project',path='materials_benchmark.blend')


def repair_resolution_pairs(names=None):
    """A resumed low-memory run may lower size between the two renders of a pair.
    Re-render the larger member at the smaller member's native size for fair sheets.
    """
    from PIL import Image
    file=WORK/'materials_visuals.json'
    if not file.exists(): return
    records=json.loads(file.read_text())
    for name in names or CAST:
        changed=False
        for look in LOOKS:
            for shot in SHOTS:
                keys=[f'{name}/{look}/{shot}/{q}' for q in ('mpfb','enhanced')]
                if not all(k in records for k in keys): continue
                sizes=[Image.open(records[k]['path']).size[0] for k in keys]
                if sizes[0] == sizes[1]: continue
                call('open_project',path=f'materials_{name}.blend')
                call('cinematic_look',clear=True)
                call('set_lighting',preset=look if look in ('studio','soft') else 'studio',subject=[name+'_rig'])
                if look not in ('studio','soft'): call('cinematic_look',preset=look)
                call('camera_shot',subject=[name+'_rig'],shot=shot,start_frame=1,end_frame=72,name='MaterialPortrait',
                     angle=8,elevation=0,avoid_occlusion=False,depth_of_field=None if look not in ('studio','soft') else False)
                quality='mpfb' if sizes[0]>sizes[1] else 'enhanced'
                key=f'{name}/{look}/{shot}/{quality}'
                call('upgrade_materials',character=name+'_rig',quality=quality)
                start=time.perf_counter()
                r=call('render_preview',camera='scene',engine='eevee',width=min(sizes),height=min(sizes),
                       filename=Path(records[key]['path']).name)
                records[key].update(size=r['size'],seconds=time.perf_counter()-start,resolution_repair=True)
                file.write_text(json.dumps(records,indent=2))
                changed=True
        if changed:
            for shot in SHOTS: make_sheet(records,name,shot,LOOKS)


def cycles(args):
    parts=args.compatibility_part
    if 'repair' in parts: repair_resolution_pairs(args.cast)
    names=[name for name in ('Lina','Nia') if not args.cast or name in args.cast]
    file=WORK/'materials_cycles.json'
    records=json.loads(file.read_text()) if args.reuse and file.exists() else {}
    for name in names if 'cycles' in parts else ():
        call('open_project',path=f'materials_{name}.blend')
        call('cinematic_look',clear=True)
        call('set_lighting',preset='studio',subject=[name+'_rig'])
        call('camera_shot',subject=[name+'_rig'],shot='extreme_close_up',name='MaterialPortrait',
             start_frame=1,end_frame=72,angle=8,elevation=0,avoid_occlusion=False,depth_of_field=False)
        for quality in ('mpfb','enhanced'):
            key=f'{name}/cycles/extreme_close_up/{quality}'
            if args.reuse and key in records and Path(records[key]['path']).exists(): continue
            call('upgrade_materials',character=name+'_rig',quality=quality)
            records[key]=call('render_preview',camera='scene',engine='cycles',
                width=256,height=256,filename=f'materials_{name}_cycles_{quality}.png')
            file.write_text(json.dumps(records,indent=2))
        make_sheet(records,name,'extreme_close_up',['cycles'],tag='cycles')
    file=WORK/'materials_film_style.json'
    film=json.loads(file.read_text()) if args.reuse and file.exists() else {}
    for name in names if 'film' in parts else ():
        call('open_project',path=f'materials_{name}.blend')
        call('cinematic_look',clear=True)
        call('set_lighting',preset='studio',subject=[name+'_rig'])
        call('camera_shot',subject=[name+'_rig'],shot='extreme_close_up',name='MaterialPortrait',
             start_frame=1,end_frame=72,angle=8,elevation=0,avoid_occlusion=False,depth_of_field=True,f_stop=8.)
        call('render_style',style='film')
        # Judge the wet iris with a real focal plane on the eyes. The generic
        # shot's head-center focus at f/2.8 can blur the entire face this close.
        python(f'''from mathutils import Vector
from engine.commands.materials import _family,_eye_frame
root,body,meshes=_family({name+'_rig'!r})
z,y,_=_eye_frame(meshes,body)
focus=bpy.data.objects.new('MaterialEyeFocus',None)
bpy.context.scene.collection.objects.link(focus)
focus.location=body.matrix_world @ Vector((0,y,z))
bpy.context.scene.camera.data.dof.focus_object=focus
result=True
''')
        for quality in ('mpfb','enhanced'):
            key=f'{name}/film/extreme_close_up/{quality}'
            if args.reuse and key in film and Path(film[key]['path']).exists(): continue
            call('upgrade_materials',character=name+'_rig',quality=quality)
            film[key]=call('render_preview',camera='scene',engine='eevee',
                width=384,height=384,filename=f'materials_{name}_film_{quality}.png')
            file.write_text(json.dumps(film,indent=2))
        make_sheet(film,name,'extreme_close_up',['film'],tag='film')
        call('render_style',style='none')
    if 'fabrics' not in parts: return
    file=WORK/'materials_fabrics.json'
    fabrics=json.loads(file.read_text()) if args.reuse and file.exists() else {}
    call('open_project',path='materials_Lina.blend')
    call('set_lighting',preset='studio',subject=['Lina_rig'])
    call('camera_shot',subject=['Lina.female_casualsuit01'],shot='close_up',name='MaterialPortrait',
         start_frame=1,end_frame=72,angle=8,elevation=0,avoid_occlusion=False,depth_of_field=False)
    from engine.materials import FABRICS
    for kind in FABRICS:
        if args.reuse and kind in fabrics and Path(fabrics[kind]['path']).exists(): continue
        # Same garment, texture, UV and light: only the supported fabric tag varies.
        python(f"bpy.data.objects['Lina.female_casualsuit01']['c3d_garment_tags']={kind!r};result=True")
        upgraded=call('upgrade_materials',character='Lina_rig')
        assert next(m['fabric'] for m in upgraded['materials'] if m['object']=='Lina.female_casualsuit01') == kind
        fabrics[kind]=call('render_preview',camera='scene',engine='eevee',width=384,height=384,
                          filename=f'materials_fabric_{kind}.png')
        file.write_text(json.dumps(fabrics,indent=2))
    from PIL import Image,ImageDraw
    sheet=Image.new('RGB',(384*3,412*2),'#20252b');draw=ImageDraw.Draw(sheet)
    for i,(kind,item) in enumerate(fabrics.items()):
        x,y=(i%3)*384,(i//3)*412
        sheet.paste(Image.open(item['path']).convert('RGB'),(x,y+28))
        draw.text((x+10,y+8),f"{kind} | rough {FABRICS[kind]['roughness']} | sheen {FABRICS[kind]['sheen']}",fill='white')
    sheet.save(SHEETS/'fabrics.png')
    (WORK/'materials_fabrics.json').write_text(json.dumps(fabrics,indent=2))


def clip(args):
    build('Lina')
    call('upgrade_materials',character='Lina_rig')
    call('set_timeline',frame_start=1,frame_end=36,fps=12)
    call('set_lighting',preset='studio',subject=['Lina_rig'])
    call('camera_shot',subject=['Lina_rig'],shot='extreme_close_up',angle=8,elevation=0,start_frame=1,end_frame=36,
         name='MaterialPortrait',avoid_occlusion=False,depth_of_field=False)
    call('cinematic_look',preset='studio_film',grade={'grain':0})
    # A static character across DISTINCT timeline frames isolates dither/SSS
    # stability from animation and animated film grain.
    paths=[]
    for i in (8,9):
        paths.append(call('render_preview',camera='scene',engine='eevee',frame=i,width=256,height=256,
                          filename=f'materials_static_repeat_{i}.png')['path'])
    from PIL import Image
    import numpy as np
    difference=np.abs(np.asarray(Image.open(paths[0])).astype(float)-np.asarray(Image.open(paths[1])).astype(float))
    static=float(difference.mean())
    hair_static=float(difference[:64,:,:3].mean())
    skin_static=float(difference[80:210,70:200,:3].mean())
    assert max(static,hair_static,skin_static) < 2., f'excessive static-frame flicker: {static}, {hair_static}, {skin_static}'
    call('animate',armature='Lina_rig',clip='idle',start_frame=1)
    call('set_expression',character='Lina_rig',expression='smile',strength=.4,frame=1,keyframe=True)
    call('lip_sync',character='Lina_rig',text='Halo, senang sekali bertemu kalian!',start_frame=1,language='id')
    call('set_timeline',frame_start=1,frame_end=36,fps=12)
    call('auto_blink',character='Lina_rig',frame_start=1,frame_end=36,seed=14)
    call('talk_motion',character='Lina_rig',frame_start=1,frame_end=36)
    call('save_project',path='materials_talking.blend')
    call('render_options',quality='preview')
    job=python("""from engine.commands.video import render_video,JOBS
r=render_video(path='materials_talking_3s.mp4',quality='preview',width=512,height=512,frame_start=1,frame_end=36,_defer=True,subtitles=False)
j=JOBS[r['job_id']]
result=dict(command=j['render_cmd'],blend=j['blend'],base=j['base'],path=j['path'])
""")
    c.stop()
    # Stop a reused editor too before launching its API-prepared movie worker.
    if c._alive(): c._send('shutdown',{},timeout=5)
    time.sleep(1)
    with open(WORK/'materials_clip.log','wb') as log:
        subprocess.run(job['command'],stdout=log,stderr=subprocess.STDOUT,check=True)
    movies=sorted(Path(job['base']).parent.glob(Path(job['base']).name+'*.mp4'))
    movies[-1].replace(job['path'])
    import av
    with av.open(job['path']) as movie:
        frames=[f.to_ndarray(format='rgb24') for f in movie.decode(video=0)]
    assert len(frames)==36
    deltas=[float(np.abs(frames[i].astype(float)-frames[i-1].astype(float)).mean()) for i in range(1,len(frames))]
    from PIL import ImageDraw
    sheet=Image.new('RGB',(256*6,280),'#20252b');draw=ImageDraw.Draw(sheet)
    for col,index in enumerate((0,6,12,18,24,35)):
        sheet.paste(Image.fromarray(frames[index]),(col*256,24));draw.text((col*256+8,7),f'frame {index+1}',fill='white')
    sheet.save(SHEETS/'talking_3s.png')
    (WORK/'materials_clip.json').write_text(json.dumps(dict(path=job['path'],frames=36,fps=12,duration_s=3,
          static_repeat_mae=static,static_hair_mae=hair_static,static_skin_mae=skin_static,adjacent_mae=deltas),indent=2))
    print('MATERIAL CLIP OK',job['path'],'static repeat MAE',static,flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stills',action='store_true');p.add_argument('--bench',action='store_true');p.add_argument('--clip',action='store_true')
    p.add_argument('--cycles',action='store_true')
    p.add_argument('--compatibility-part',nargs='+',choices=('repair','cycles','film','fabrics'),
                   default=('repair','cycles','film','fabrics'),help='split expensive compatibility evidence into resumable batches')
    p.add_argument('--max-size',type=int,choices=(256,384,512),default=384)
    p.add_argument('--uncached',action='store_true',help='rebuild shader copies for every still instead of caching both graphs')
    p.add_argument('--reuse',action='store_true');p.add_argument('--cast',nargs='+',choices=CAST)
    p.add_argument('--looks',nargs='+',choices=LOOKS);p.add_argument('--shots',nargs='+',choices=SHOTS)
    args=p.parse_args()
    try:
        if args.stills: stills(args)
        if args.bench: bench(args)
        if args.cycles: cycles(args)
        if args.clip: clip(args)
    finally:
        c.stop()


if __name__=='__main__': main()
