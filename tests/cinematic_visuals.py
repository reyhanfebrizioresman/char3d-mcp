"""Reproducible cinematic visual/cost evidence on the isolated 9988 engine.

CHAR3D_PORT=9988 CHAR3D_WORKSPACE=$PWD/output .venv/bin/python -u tests/cinematic_visuals.py --sets
--bench: 320px warm-up, then two timed 960x540 / 16 sample indoor+outdoor stills.
--movies: two 3 s / 540p / 12 fps CPU previews, retimed dialog cuts and particles.
Uses installed MPFB assets only. Never uses 9876. Results are gitignored in output/.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.append("/usr/lib/python3/dist-packages")
from mcp_server.blender_client import BlenderClient
from engine.cinematic import PRESETS

if os.environ.get('CHAR3D_PORT') != '9988':
    raise SystemExit('Use CHAR3D_PORT=9988 for these visual checks')
os.environ['CHAR3D_ALLOW_PYTHON'] = '1'
WORK = Path(os.environ.get('CHAR3D_WORKSPACE', ROOT/'output'))
SHEETS = WORK/'cinematic_sheets'
SHEETS.mkdir(parents=True, exist_ok=True)
c = BlenderClient()


def call(cmd, **params):
    start = time.perf_counter()
    result = c.call(cmd, **params)
    print(f'{cmd} {params.get("preset", params.get("path", ""))} {time.perf_counter()-start:.2f}s', flush=True)
    return result


def python(code):
    return call('run_python', code=code)['result']


def setup():
    python(f'''import importlib,os,shutil
module='bl_ext.user_default.mpfb'
source=os.path.join(bpy.utils.extension_path_user(module),'data')
home={str(WORK/'mpfb_test')!r}
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
result=True
''')


def build(preset):
    call('scene_info')
    call('new_scene', frame_end=72)
    setup()
    script = dict(environment=preset, characters=[
        dict(id='Ana',gender=0,age=28,race={'asian':1},hair='ponytail01',clothes=['female_casualsuit01','shoes01']),
        dict(id='Budi',gender=1,age=30,race={'asian':1},hair='short02',clothes=['male_casualsuit01','shoes01'])],
        beats=[dict(say='Ana',text='Indah sekali!'),dict(say='Budi',text='Mari bersama.')])
    result = call('script_to_scene',script=script,subtitles=False,sound=False,seed=14)
    assert all(v['realistic'] for v in result['characters'].values()), result
    for shot in result['shots']:
        call('delete_shot',name=shot['camera'])
    # Coverage follows the live face after dialog gestures; wide shows set atmosphere.
    call('camera_shot',subject=['Ana_rig','Budi_rig'],shot='wide',
         start_frame=1,end_frame=23,name='CineWide',angle=20 if preset=='office' else 0,elevation=10 if preset=='office' else 7,
         face_coverage=preset!='office',action_line=['Ana_rig','Budi_rig'],coverage_turns=result['lines'])
    call('camera_shot',subject=['Ana_rig'],shot='close_up',start_frame=24,end_frame=47,
         name='CineAna',angle=30,elevation=3,face_coverage=True,action_line=['Ana_rig','Budi_rig'])
    call('camera_shot',subject=['Budi_rig'],shot='close_up',start_frame=48,end_frame=72,
         name='CineBudi',angle=-30,elevation=3,face_coverage=True,action_line=['Ana_rig','Budi_rig'])
    call('set_timeline',frame_start=1,frame_end=72)
    python('sc=bpy.context.scene;sc.render.resolution_x=960;sc.render.resolution_y=540;result=True')
    call('save_project',path=f'cinematic_{preset}.blend')
    return result


def sheet(paths, out):
    # Pillow is used only to assemble test evidence, never to fake a scene effect.
    from PIL import Image, ImageDraw
    w,h=512,288
    canvas=Image.new('RGB',(w*len(paths),h*2+38),'#192026')
    draw=ImageDraw.Draw(canvas)
    for col,(look,items) in enumerate(paths.items()):
        draw.text((col*w+14,12),look,fill='#ffffff')
        for row,path in enumerate(items):
            with Image.open(path) as im:
                canvas.paste(im.resize((w,h)),(col*w,38+row*h))
    canvas.save(out)


def sets(environments=None):
    looks = {
        'park':['none','golden_hour','misty_morning','epic'],
        'beach':['none','golden_hour','sunset'],
        'city_street':['none','golden_hour','blue_hour'],
        'cafe_terrace':['none','golden_hour','dreamy'],
        'podcast_studio':['none','studio_film','night'],
        'office':['none','golden_hour','misty_morning'],
        'stage':['none','studio_film','epic'],
    }
    results=json.loads((WORK/'cinematic_visuals.json').read_text()) if (WORK/'cinematic_visuals.json').exists() else {}
    for environment,presets in looks.items():
        if environments and environment not in environments: continue
        project=WORK/'projects'/f'cinematic_{environment}.blend'
        if project.exists() and os.environ.get('CHAR3D_CINE_REUSE'):
            call('open_project',path=str(project))
            built={}
        else:
            built=build(environment)
        images={}
        for preset in presets:
            call('cinematic_look',preset=preset)
            images[preset]=[]
            for frame in (12,32):
                name=f'cinematic_{environment}_{preset}_{frame}.png'
                if (WORK/'renders'/name).exists() and os.environ.get('CHAR3D_CINE_REUSE') and not os.environ.get('CHAR3D_CINE_REFRESH'):
                    path=str(WORK/'renders'/name)
                else:
                    path=call('render_preview',camera='scene',engine='eevee',frame=frame,width=512,height=288,filename=name)['path']
                images[preset].append(path)
        sheet(images,SHEETS/f'{environment}.png')
        results[environment]=dict(images=images,build=built)
        (WORK/'cinematic_visuals.json').write_text(json.dumps(results,indent=2))
        print('SHEET',SHEETS/f'{environment}.png',flush=True)


def refresh_wides(environments):
    results=json.loads((WORK/'cinematic_visuals.json').read_text())
    for environment in environments:
        call('open_project',path=f'cinematic_{environment}.blend')
        call('scene_info')
        result=call('camera_shot',subject=['Ana_rig','Budi_rig'],shot='wide',
                    start_frame=1,end_frame=23,name='CineWide',angle=20 if environment=='office' else 0,
                    elevation=10 if environment=='office' else 7,face_coverage=environment!='office',action_line=['Ana_rig','Budi_rig'])
        call('cinematic_look',clear=True)
        call('save_project',path=f'cinematic_{environment}.blend')
        images=results[environment]['images']
        for preset in images:
            call('cinematic_look',preset=preset)
            frames=(12,32) if environment=='stage' else (12,)
            for frame in frames:
                path=call('render_preview',camera='scene',engine='eevee',frame=frame,
                          width=512,height=288,filename=f'cinematic_{environment}_{preset}_{frame}.png')['path']
                images[preset][0 if frame==12 else 1]=path
        results[environment]['establishing_camera']=result
        sheet(images,SHEETS/f'{environment}.png')
        (WORK/'cinematic_visuals.json').write_text(json.dumps(results,indent=2))
        print('SHEET',SHEETS/f'{environment}.png',flush=True)


def bench(environments=None, presets=None):
    results=json.loads((WORK/'cinematic_benchmark.json').read_text()) if (WORK/'cinematic_benchmark.json').exists() else {}
    for environment in (environments or ('podcast_studio','park')):
        call('open_project',path=f'cinematic_{environment}.blend')
        # Constant close-up, two clothed MPFB humans retained in the same scene.
        # Warm every preset at 320px; mean two full-size calls includes setup/restoration and PNG I/O.
        records=results.get(environment,{})
        for preset in (presets or ['none',*PRESETS]):
            call('cinematic_look',preset=preset)
            elapsed=[]
            for repeat in range(3):
                start=time.perf_counter()
                call('render_preview',camera='scene',engine='eevee',frame=32,width=320 if repeat==0 else 960,
                     height=180 if repeat==0 else 540, filename=f'cinematic_bench_{environment}_{preset}.png')
                elapsed.append(time.perf_counter()-start)
            records[preset]=dict(seconds_per_frame=round(sum(elapsed[1:])/2,3),samples=elapsed)
            records[preset]['ratio']=round(records[preset]['seconds_per_frame']/records['none']['seconds_per_frame'],3)
            print('BENCH',environment,preset,records[preset],flush=True)
            results[environment]=records
            (WORK/'cinematic_benchmark.json').write_text(json.dumps(results,indent=2))


def movies(environments=None):
    import av
    import numpy as np
    reports=json.loads((WORK/'cinematic_movies.json').read_text()) if (WORK/'cinematic_movies.json').exists() else {}
    for environment,preset in [('park','golden_hour'),('podcast_studio','blue_hour')]:
        if environments and environment not in environments: continue
        call('open_project',path=f'cinematic_{environment}.blend')
        call('cinematic_look',preset=preset,particles={'kind':'dust','count':65,'seed':19})
        for shot in call('list_shots')['shots']:
            if shot['camera'] not in ('CineWide','CineAna','CineBudi'):
                call('delete_shot',name=shot['camera'])
        # Keep all three shots and the complete performance in a 3-second CPU
        # preview. Retiming every action preserves duration at 12 rather than 24 fps.
        python('''from engine.commands.talk import _fcurves
import json
sc=bpy.context.scene
for action in bpy.data.actions:
    for curve in _fcurves(action):
        for key in curve.keyframe_points:
            center,left,right=key.co.x,key.handle_left.x,key.handle_right.x
            key.co.x=1+(center-1)/2
            key.handle_left.x=1+(left-1)/2
            key.handle_right.x=1+(right-1)/2
        curve.update()
for marker in sc.timeline_markers:
    marker.frame=1+round((marker.frame-1)/2)
for camera in [o for o in sc.objects if o.type=='CAMERA']:
    turns=json.loads(camera.get('c3d_focus_turns','[]'))
    for turn in turns:
        for key in ('start','end'): turn[key]=1+round((turn[key]-1)/2)
    camera['c3d_focus_turns']=json.dumps(turns)
# Freeze each test camera at a representative composition. The production
# face-coverage camera follows gaze and may reorient when the speaker changes;
# static cameras make these clips isolate atmosphere and live focus continuity.
for name,frame in (('CineWide',3),('CineAna',13),('CineBudi',25)):
    sc.frame_set(frame)
    camera=bpy.data.objects[name]
    matrix=camera.matrix_world.copy()
    lens=camera.data.lens
    camera.animation_data_clear()
    camera.data.animation_data_clear()
    camera.matrix_world=matrix
    camera.data.lens=lens
sc.frame_set(1)
result=True
''')
        call('set_timeline',frame_start=1,frame_end=36,fps=12)
        focus_checks=python('''from engine.commands.cinematic import applied_look, _eye
sc=bpy.context.scene
checks=[]
with applied_look(sc):
    for frame in (3,13,25,35):
        sc.frame_set(frame)
        camera=max((m for m in sc.timeline_markers if m.camera and m.frame<=frame),key=lambda m:m.frame).camera
        rig=bpy.data.objects[camera['c3d_shot']['subject'][0]]
        target=camera.data.dof.focus_object
        bpy.context.view_layer.update()
        error=(target.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.translation-_eye(rig)).length
        checks.append(dict(frame=frame,camera=camera.name,subject=rig.name,
                           fstop=camera.data.dof.aperture_fstop,error_m=error))
result=checks
''')
        assert all(check['error_m']<.001 for check in focus_checks),focus_checks
        assert focus_checks[1]['subject']=='Ana_rig' and focus_checks[2]['subject']=='Budi_rig'
        call('save_project',path=f'cinematic_{preset}_movie.blend')
        start=time.perf_counter()
        opts=call('render_options',quality='preview',frame_start=1,frame_end=36)
        if not opts['machine_speed']['measurements']:
            opts=call('render_options',quality='preview',frame_start=1,frame_end=36,calibrate=True)
        render_started=time.perf_counter()
        report=call('render_video',path=f'cinematic_{preset}_540p.mp4',quality='preview',resolution='540p',
                    frame_start=1,frame_end=36,wait=False,subtitles=False)
        previous_progress=None
        while report['status']=='running':
            time.sleep(5)
            report=c.call('render_status',job_id=report['job_id'])
            if report['progress']!=previous_progress:
                print('MOVIE PROGRESS',preset,report['progress'],report['elapsed_s'],flush=True)
                previous_progress=report['progress']
        report['wall_s']=round(time.perf_counter()-render_started,2)
        report['workflow_wall_s']=round(time.perf_counter()-start,2)
        report['calibration']=opts.get('test_frame')
        report['verification_fps']=12
        report['verification_frames']=36
        report['focus_checks']=focus_checks
        assert report['status']=='done',report
        samples=[]
        deltas=[]
        previous=None
        with av.open(report['path']) as clip:
            stream=clip.streams.video[0]
            assert (stream.width,stream.height)==(960,540)
            assert stream.average_rate==12
            assert abs(float(stream.duration*stream.time_base)-3)<.02
            for i,frame in enumerate(clip.decode(video=0)):
                rgb=frame.to_ndarray(format='rgb24')
                if i in (2,6,10,12,16,22,24,30,34):
                    from PIL import Image
                    path=WORK/'renders'/f'cinematic_movie_{preset}_{i+1}.png'
                    Image.fromarray(rgb).save(path);samples.append(str(path))
                if previous is not None and i not in (12,24):
                    deltas.append(float(np.abs(rgb.astype(float)-previous).mean()))
                previous=rgb.astype(float)
            assert i+1==36
        report['mean_frame_delta']=round(float(np.mean(deltas)),3)
        report['max_frame_delta']=round(max(deltas),3)
        assert report['max_frame_delta']<20, report
        report['samples']=samples
        from PIL import Image, ImageDraw
        contact=Image.new('RGB',(384*3,240*3),'#192026')
        draw=ImageDraw.Draw(contact)
        for n,path in enumerate(samples):
            x,y=(n%3)*384,(n//3)*240
            draw.text((x+10,y+5),Path(path).stem,fill='white')
            with Image.open(path) as image:
                contact.paste(image.resize((384,216)),(x,y+24))
        contact.save(SHEETS/f'movie_{preset}.png')
        reports[preset]=report
        (WORK/'cinematic_movies.json').write_text(json.dumps(reports,indent=2))
        print('MOVIE',preset,json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--sets',action='store_true');p.add_argument('--bench',action='store_true');p.add_argument('--movies',action='store_true')
    p.add_argument('--environments',nargs='*')
    p.add_argument('--presets',nargs='*')
    p.add_argument('--refresh-wides',action='store_true')
    args=p.parse_args()
    if args.refresh_wides: refresh_wides(args.environments or ["podcast_studio","office","stage"])
    if args.sets: sets(args.environments)
    if args.bench: bench(args.environments,args.presets)
    if args.movies: movies(args.environments)
