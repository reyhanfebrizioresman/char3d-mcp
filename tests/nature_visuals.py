"""Offline visual evidence. Only CHAR3D_PORT=9997; one engine, never installs assets.

Run --baseline before changing the old park, then --sets --bench --clips.
Clips render in-process frames and encode with PyAV, avoiding a second Blender.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.append('/usr/lib/python3/dist-packages')
from mcp_server.blender_client import BlenderClient

WORK = ROOT / 'output'
SHEETS = WORK / 'nature_sheets'


def connect():
    if os.environ.get('CHAR3D_PORT') != '9997':
        raise SystemExit('Use CHAR3D_PORT=9997 CHAR3D_WORKSPACE=$PWD/output')
    os.environ['CHAR3D_ALLOW_PYTHON'] = '1'
    os.environ['CHAR3D_RENDER_CALIB'] = str(WORK / 'nature_render_speed.json')
    # The sandbox's home cache is read-only; keep software shader/thumbnail
    # caches in the assigned workspace so every isolated process can reuse them.
    os.environ['XDG_CACHE_HOME'] = str(WORK / 'cache')
    os.environ['MESA_SHADER_CACHE_DIR'] = str(WORK / 'cache' / 'mesa')
    os.environ['LP_NUM_THREADS'] = '8'
    SHEETS.mkdir(parents=True, exist_ok=True)
    return BlenderClient()


def py(c, code):
    return c.call('run_python', code=code)['result']


def setup_code():
    return f'''import importlib,os,shutil
module='bl_ext.user_default.mpfb'
source=os.path.join(bpy.utils.extension_path_user(module),'data')
home={str(WORK / 'mpfb_test')!r}
os.makedirs(home,exist_ok=True)
if not os.path.isdir(os.path.join(home,'data')): shutil.copytree(source,os.path.join(home,'data'))
cls=importlib.import_module(module+'._preferences').MpfbPreferences
if 'bl_rna' not in cls.__dict__: bpy.utils.register_class(cls)
a=bpy.context.preferences.addons.get(module)
if a is None:
    a=bpy.context.preferences.addons.new();a.module=module
a.preferences.mpfb_user_data=home
sc=bpy.context.scene
sc.render.threads_mode='FIXED';sc.render.threads=8
sc.render.resolution_x=960;sc.render.resolution_y=540
result=True
'''


def setup(c):
    return py(c,setup_code())


def build(c, preset):
    c.call('scene_info')
    c.call('new_scene', frame_end=72)
    setup(c)
    r = c.call('script_to_scene', script=dict(environment=preset, characters=[
        dict(id='Ana', gender=0, age=28, race={'asian': 1}, hair='ponytail01',
             clothes=['female_casualsuit01', 'shoes01']),
        dict(id='Budi', gender=1, age=30, race={'asian': 1}, hair='short02',
             clothes=['male_casualsuit01', 'shoes01'])], beats=[
        dict(say='Ana', text='Indah sekali!'), dict(say='Budi', text='Mari bersama.')]),
        subtitles=False, sound=False, seed=14, lighting='overcast')
    assert all(v['realistic'] for v in r['characters'].values()), r
    for shot in r['shots']:
        c.call('delete_shot', name=shot['camera'])
    for name, shot, subject, start, end, angle in [
        ('NatureWide', 'wide', ['Ana_rig', 'Budi_rig'], 1, 23, 0),
        ('NatureMedium', 'medium', ['Ana_rig'], 24, 47, 30),
        ('NatureClose', 'close_up', ['Budi_rig'], 48, 72, -30)]:
        c.call('camera_shot', subject=subject, shot=shot, name=name,
               start_frame=start, end_frame=end, angle=angle, elevation=7 if shot == 'wide' else 3,
               face_coverage=True, action_line=['Ana_rig', 'Budi_rig'])
    c.call('set_timeline', frame_start=1, frame_end=72)
    c.call('cinematic_look', preset='none')
    c.call('save_project', path=f'nature_{preset}.blend')
    return r


def still(c, name, frame=12, width=512):
    start = time.perf_counter()
    r = c.call('render_preview', camera='scene', engine='eevee', frame=frame,
               width=width, height=round(width * 9 / 16), filename=name + '.png')
    elapsed = time.perf_counter() - start
    print('STILL', name, round(elapsed, 3), flush=True)
    return r['path'], elapsed


def baseline(c):
    if (ROOT/'engine/nature').is_dir():
        raise RuntimeError('--baseline belongs to the pre-kit checkout; use --legacy-bench with its saved nature_legacy_park.blend fixture')
    r = build(c, 'park')
    c.call('save_project', path='nature_legacy_park.blend')
    samples = [still(c, f'nature_legacy_park_{i}', frame=32, width=w)[1]
               for i, w in enumerate((320, 960, 960))]
    (WORK / 'nature_baseline.json').write_text(json.dumps(dict(
        preset='legacy_park', samples=samples, seconds_per_frame=sum(samples[1:]) / 2,
        build=r, resolution=[960, 540], samples_per_pixel=16), indent=2))
    print('BASELINE OK', samples, flush=True)


def sheet(images, filename):
    from PIL import Image, ImageDraw
    w,h=512,288
    canvas=Image.new('RGB',(w*len(images),h*3+32),'#192026')
    draw=ImageDraw.Draw(canvas)
    for col,(look,paths) in enumerate(images.items()):
        draw.text((col*w+12,8),look,fill='white')
        for row,path in enumerate(paths):
            with Image.open(path) as im: canvas.paste(im.resize((w,h)),(col*w,32+row*h))
    canvas.save(filename)


def sets(c,environments,looks=None,reuse=False,refresh=False,resume=False):
    if refresh and resume: raise ValueError('Refresh changes the fixture; resume only an unchanged saved fixture')
    target=WORK/'nature_visuals.json'
    results=json.loads(target.read_text()) if target.exists() else {}
    for preset in environments:
        if reuse and (WORK/'projects'/f'nature_{preset}.blend').exists():
            c.call('scene_info');c.call('open_project',path=f'nature_{preset}.blend')
            py(c,"from engine.nature.blender import upgrade_saved_motion\nresult=len(upgrade_saved_motion())")
            if preset in ('riverside','mountain_village'):
                py(c,"from engine.commands.outdoor import outdoor_root\nfrom engine.nature.blender import install_night_fill\nresult=install_night_fill(outdoor_root()).name")
            if refresh:
                matrix=py(c,"from engine.commands.outdoor import outdoor_root\nresult=[list(row) for row in outdoor_root().matrix_world]")
                updated=c.call('set_environment',preset=preset,subject=['Ana_rig','Budi_rig'],variant=14)
                py(c,f"from mathutils import Matrix\nbpy.data.objects[{updated['root']!r}].matrix_world=Matrix({matrix!r})\nresult=True")
            c.call('set_lighting',preset='overcast',subject=['Ana_rig','Budi_rig'])
            c.call('cinematic_look',preset='none')
            c.call('save_project',path=f'nature_{preset}.blend')
            built=results.get(preset,{}).get('build',{})
        else: built=build(c,preset)
        images=results.get(preset,{}).get('images',{});times=results.get(preset,{}).get('times',{})
        results[preset]=dict(images=images,times=times,build=built)
        target.write_text(json.dumps(results,indent=2))
        for look in (looks or ['none','golden_hour','misty_morning']+(['night'] if preset in ('riverside','mountain_village') else [])):
            c.call('cinematic_look',preset=look)
            if look=='night':
                c.call('add_nature',kind='fireflies',location=[0,5,0],seed=17,
                       area=[14,12],params=dict(count=45,height=1.3))
                c.call('save_project',path=f'nature_night_{preset}.blend')
            images[look]=[];times[look]=[]
            for frame,label in ((12,'wide'),(32,'medium'),(56,'close')):
                name=f'nature_{preset}_{look}_{label}'
                existing=WORK/'renders'/(name+'.png')
                if resume and existing.exists():
                    path,elapsed=str(existing),None
                    print('REUSE',name,flush=True)
                else: path,elapsed=still(c,name,frame)
                images[look].append(path);times[look].append(elapsed)
            sheet(images,SHEETS/f'{preset}.png')
            results[preset]=dict(images=images,times=times,build=built)
            target.write_text(json.dumps(results,indent=2))
            print('SHEET',SHEETS/f'{preset}.png',flush=True)
            if look=='night': c.call('clear_nature')


def bench(c,environments):
    target=WORK/'nature_benchmark.json'
    results=json.loads(target.read_text()) if target.exists() else {}
    base=json.loads((WORK/'nature_baseline.json').read_text())['seconds_per_frame']
    for preset in environments:
        c.call('scene_info');c.call('open_project',path=f'nature_{preset}.blend')
        py(c,"from engine.nature.blender import upgrade_saved_motion\nresult=len(upgrade_saved_motion())")
        c.call('save_project',path=f'nature_{preset}.blend')
        c.call('cinematic_look',preset='none')
        samples=[still(c,f'nature_bench_{preset}_{i}',32,w)[1] for i,w in enumerate((320,960,960))]
        spf=sum(samples[1:])/2
        stats=py(c,"result=dict(objects=len(bpy.context.scene.objects),mesh_vertices=sum(len(o.data.vertices) for o in bpy.context.scene.objects if o.type=='MESH'),threads=bpy.context.scene.render.threads)")
        results[preset]=dict(seconds_per_frame=spf,ratio=spf/base,samples=samples,
                             resolution=[960,540],samples_per_pixel=16,scene=stats,
                             lighting='overcast',look='none',software_gl_threads=8)
        target.write_text(json.dumps(results,indent=2))
        print('BENCH',preset,results[preset],flush=True)


def clips(c,environments):
    import av
    from PIL import Image
    target=WORK/'nature_clips.json'
    results=json.loads(target.read_text()) if target.exists() else {}
    for preset in environments:
        c.call('scene_info');c.call('open_project',path=f'nature_{preset}.blend')
        py(c,"from engine.nature.blender import upgrade_saved_motion\nresult=len(upgrade_saved_motion())")
        c.call('set_weather',kind='wind',intensity=.7,wind=[1.8,.5,0],seed=14)
        # Close drifting petals and an overhead flock keep the motion readable
        # against dense canopies in this deliberately compact wide-shot fixture.
        c.call('add_nature',kind='falling_petals',location=[0,4,0],seed=31,
               params=dict(area=[12,12],count=55,height=5))
        c.call('add_nature',kind='birds_flock',seed=32,params=dict(count=8,
            path=[[0,6,3.6],[4,9,4.0],[0,12,4.5],[-4,9,3.8]]))
        for shot in c.call('list_shots')['shots']: c.call('delete_shot',name=shot['camera'])
        c.call('camera_shot',subject=['Ana_rig','Budi_rig'],shot='wide',
               name='NatureMotion',start_frame=1,end_frame=73,angle=0,elevation=7)
        c.call('set_timeline',frame_start=1,frame_end=73)
        c.call('cinematic_look',preset='golden_hour')
        c.call('save_project',path=f'nature_motion_{preset}.blend')
        path=WORK/'renders'/f'nature_motion_{preset}.mp4'
        start=time.perf_counter()
        # In-process workbench sequence: only one Blender alive. 3 s at 12 fps,
        # sampled every two 24fps scene frames preserves physical animation speed.
        movie=av.open(str(path),'w');stream=movie.add_stream('libx264',rate=12)
        stream.width=512;stream.height=288;stream.pix_fmt='yuv420p'
        try:
            for frame in range(1,73,2):
                rendered=c.call('render_preview',camera='scene',engine='workbench',frame=frame,
                    width=512,height=288,filename=f'nature_clip_{preset}_{frame:04}.png')
                with Image.open(rendered['path']) as im:
                    video=av.VideoFrame.from_image(im.convert('RGB'))
                    for packet in stream.encode(video): movie.mux(packet)
            for packet in stream.encode(): movie.mux(packet)
        finally: movie.close()
        elapsed=time.perf_counter()-start
        results[preset]=dict(path=str(path),seconds=elapsed,frames=36,duration_s=3,
            seconds_per_frame=elapsed/36,quality='draft workbench, saved scene motion',size=[512,288])
        target.write_text(json.dumps(results,indent=2))
        print('CLIP',results[preset],flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', action='store_true')
    p.add_argument('--sets',action='store_true')
    p.add_argument('--bench',action='store_true')
    p.add_argument('--clips',action='store_true')
    p.add_argument('--only',nargs='+')
    p.add_argument('--looks',nargs='+')
    p.add_argument('--reuse',action='store_true')
    p.add_argument('--legacy-bench',action='store_true')
    p.add_argument('--refresh-set',action='store_true')
    p.add_argument('--resume',action='store_true',help='Reuse existing stills only for the same unchanged saved fixture')
    p.add_argument('--check-motion',action='store_true')
    args = p.parse_args()
    c = connect()
    try:
        if args.baseline:
            baseline(c)
        if args.check_motion:
            from PIL import Image,ImageChops,ImageStat
            c.call('scene_info');c.call('open_project',path='nature_park.blend')
            c.call('cinematic_look',preset='none')
            old,_=still(c,'nature_motion_legacy',32)
            changed=py(c,"from engine.nature.blender import upgrade_saved_sway\nresult=upgrade_saved_sway()")
            new,_=still(c,'nature_motion_nodes',32)
            difference=ImageChops.difference(Image.open(old).convert('RGB'),Image.open(new).convert('RGB'))
            mean=sum(ImageStat.Stat(difference).mean)/3
            assert mean<.25,(mean,changed)
            c.call('save_project',path='nature_park.blend')
            (WORK/'nature_motion_equivalence.json').write_text(json.dumps(dict(
                objects=len(changed),mean_absolute_rgb_difference=mean,images=[old,new]),indent=2))
            print('NATURE MOTION EQUIVALENCE OK',len(changed),mean,flush=True)
        if args.legacy_bench:
            c.call('scene_info');c.call('open_project',path='nature_legacy_park.blend')
            c.call('set_lighting',preset='overcast',subject=['Ana_rig','Budi_rig'])
            c.call('save_project',path='nature_legacy_park.blend')
            samples=[still(c,f'nature_legacy_park_overcast_{i}',frame=32,width=w)[1]
                     for i,w in enumerate((320,960,960))]
            record=json.loads((WORK/'nature_baseline.json').read_text())
            record['original_studio_samples']=record['samples']
            record.update(samples=samples,seconds_per_frame=sum(samples[1:])/2,lighting='overcast')
            (WORK/'nature_baseline.json').write_text(json.dumps(record,indent=2))
        from engine.nature.presets import PRESETS,UPGRADED
        environments=args.only or [*UPGRADED,*PRESETS]
        if args.sets: sets(c,environments,args.looks,args.reuse,args.refresh_set,args.resume)
        if args.bench: bench(c,environments)
        if args.clips: clips(c,args.only or ['park','pine_forest','lakeside','mountain_village'])
    finally:
        c.stop()
