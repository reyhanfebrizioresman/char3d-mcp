"""Visual acceptance fixtures, MCP on 9972, one Blender, no downloads.

CHAR3D_PORT=9972 .venv/bin/python tests/filmstyle_visuals.py --quick
Use --sheets, --bench, --faces for complete evidence. All stills <=512 px.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path
from filmstyle_support import connection, ROOT

import os
OUT = ROOT/os.environ.get('FILMSTYLE_OUTPUT', 'output/filmstyle')
CAST = ['Ana_rig', 'Budi_rig']
SCRIPT = {'characters': [
    dict(id='Ana', gender=0, age=28, race={'asian': 1}, hair='ponytail01',
         clothes=['female_casualsuit01', 'shoes01']),
    dict(id='Budi', gender=1, age=31, race={'asian': 1}, hair='short02',
         clothes=['male_casualsuit01', 'shoes01'])], 'beats': [
    {'say': 'Ana', 'text': 'Mama bawa peta. Wah, hebat!'},
    {'say': 'Budi', 'text': 'Hmm, mungkin kita bersama?'}]}


def sheet(rows, path, size=384):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        # Use the installed system Pillow without installing into the shared venv.
        import inspect, subprocess
        code = 'import json,sys\n'+inspect.getsource(sheet)+'\nsheet(**json.load(sys.stdin))'
        subprocess.run(['/usr/bin/python3', '-c', code], input=json.dumps(dict(rows=rows,path=str(path),size=size)),
                       text=True, check=True)
        return
    w, h = size, round(size*9/16)
    canvas = Image.new('RGB', (w*len(rows[0]), (h+28)*len(rows)), '#162029')
    draw = ImageDraw.Draw(canvas)
    for y, row in enumerate(rows):
        for x, (label, filename) in enumerate(row):
            with Image.open(filename) as image:
                canvas.paste(image.resize((w, h)), (x*w, y*(h+28)+28))
            draw.text((x*w+8, y*(h+28)+8), label, fill='#f8dcad')
    canvas.save(path)


async def podcast_mics(data):
    info = await data('scene_info')
    for obj in info['objects']:
        if obj['type'] == 'MESH' and 'Env_podcast_studio_mic_' in obj['name']:
            location = list(obj['location'])
            location[2] -= .3
            await data('transform_object', name=obj['name'], location=location)


async def build(data):
    await data('scene_info')
    await data('new_scene', frame_end=2)
    result = await data('script_to_scene', script=SCRIPT, subtitles=False, sound=False,
                        voice=False, seed=17, lighting='soft', life=0)
    assert all(c['realistic'] for c in result['characters'].values()), result['warnings']
    await data('set_timeline', frame_start=1, frame_end=192, fps=24)
    # Remove script coverage to create explicit comparison cameras.
    for item in (await data('list_shots'))['shots']:
        await data('delete_shot', name=item['camera'])
    await data('set_environment', preset='podcast_studio', subject=CAST)
    await podcast_mics(data)
    await data('set_lighting', preset='soft', subject=CAST)
    for i, (size, subjects) in enumerate([('wide', CAST), ('medium', CAST), ('close_up', [CAST[0]])]):
        await data('camera_shot', subject=subjects, shot=size, angle=0,
                   start_frame=i*64+1, end_frame=(i+1)*64, name='Film'+size,
                   depth_of_field=False, avoid_occlusion=True)
    await data('save_project', path='filmstyle/actors.blend')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'build.json').write_text(json.dumps(result, indent=2))


async def still(data, camera, name, style, look, frame=32, width=384):
    await data('render_style', style=style)
    await data('cinematic_look', preset=look)
    t = time.perf_counter()
    result = await data('render_preview', camera=camera, frame=frame, width=width,
                        height=round(width*9/16), engine_name='eevee')
    print('STILL', name, round(time.perf_counter()-t, 2), flush=True)
    import shutil
    target=OUT/'stills'/(name+'.png')
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(result['path'],target)
    return str(target)


async def batch(data, python, setting, look, style, cameras):
    """Keep one finally-protected render context for the unchanged three-view sheet."""
    await data('render_style', style=style)
    await data('cinematic_look', preset=look)
    folder=OUT/'stills'
    folder.mkdir(parents=True,exist_ok=True)
    paths=await python(f'''
        import os,time
        from engine.commands.render_style import applied_style
        from engine.commands.cinematic import applied_look
        from engine.commands.weather import refresh_weather
        sc=bpy.context.scene;r=sc.render
        saved=(r.engine,sc.camera,r.resolution_x,r.resolution_y,r.resolution_percentage,
               r.filepath,r.image_settings.file_format,r.image_settings.media_type,sc.frame_current)
        markers=[(m,m.camera) for m in sc.timeline_markers if m.camera]
        result={{}}
        try:
            sc.frame_set(32);refresh_weather()
            for marker,_ in markers:marker.camera=None
            r.engine='BLENDER_EEVEE';sc.eevee.taa_render_samples=16
            r.resolution_x=384;r.resolution_y=216;r.resolution_percentage=100
            r.image_settings.media_type='IMAGE';r.image_settings.file_format='PNG'
            with applied_look(sc),applied_style(sc):
                for camera in {cameras!r}:
                    t=time.perf_counter()
                    sc.camera=bpy.data.objects[camera]
                    r.filepath=os.path.join({str(folder)!r},'filmstyle_{setting}_{look}_'+camera+'_{style}.png')
                    bpy.ops.render.render(write_still=True)
                    result[camera]=dict(path=r.filepath,seconds=time.perf_counter()-t)
        finally:
            for marker,camera in markers:marker.camera=camera
            (r.engine,sc.camera,r.resolution_x,r.resolution_y,r.resolution_percentage,
             r.filepath,r.image_settings.file_format,r.image_settings.media_type,frame)=saved
            sc.frame_set(frame)
    ''')
    import hashlib
    assert len({hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() for item in paths.values()})==len(paths), 'duplicate camera images'
    for camera,item in paths.items():print('BATCH',setting,look,style,camera,round(item['seconds'],2),flush=True)
    return paths


async def main(args):
    OUT.mkdir(parents=True, exist_ok=True)
    async with connection() as (call, data, python):
        if args.rebuild or not (ROOT/'output/projects/filmstyle/actors.blend').exists():
            await build(data)
        else:
            await data('scene_info')
            await data('open_project', path='filmstyle/actors.blend')
        if args.quick:
            rows = []
            for camera in ('Filmmedium', 'Filmclose_up'):
                row = []
                for style in ('none', 'animated_film'):
                    name = 'quick_'+camera+'_'+style
                    row.append((style+' / '+camera, await still(data, camera, name, style, 'golden_hour')))
                rows.append(row)
            sheet(rows, OUT/'quick.png')
        if args.sheets:
            report_path=OUT/'stills.json'
            report = json.loads(report_path.read_text()) if report_path.exists() else {}
            for setting in ('park', 'rice_terraces', 'lantern_lake', 'podcast_studio'):
                if args.only and setting != args.only: continue
                await data('open_project', path='filmstyle/actors.blend')
                if setting == 'lantern_lake':
                    from providers.director.world import offline
                    recipe = offline('lantern lake', 17)['recipe']
                    await data('clear_environment')
                    await data('compose_world', recipe=recipe)
                else:
                    await data('set_environment', preset=setting, subject=CAST, density=.6)
                if setting == 'podcast_studio': await podcast_mics(data)
                await data('set_lighting', preset='soft', subject=CAST)
                rows = []
                report.setdefault(setting, {})
                for look in ('golden_hour', 'misty_morning' if setting == 'rice_terraces' else 'night'):
                    cameras=('Filmwide','Filmmedium','Filmclose_up')
                    for style in ('none','animated_film'):
                        # A render may finish before an interrupted MCP batch
                        # returns. Recover those completed PNGs on a retry.
                        if args.resume:
                            for camera in cameras:
                                key=f'filmstyle_{setting}_{look}_{camera}_{style}'
                                path=OUT/'stills'/(key+'.png')
                                if path.exists():report[setting][key]=str(path)
                        missing=[camera for camera in cameras if not args.resume or
                                 not Path(report[setting].get(f'filmstyle_{setting}_{look}_{camera}_{style}','missing')).exists()]
                        if missing:
                            rendered=await batch(data,python,setting,look,style,missing)
                            for camera,item in rendered.items():
                                report[setting][f'filmstyle_{setting}_{look}_{camera}_{style}']=item['path']
                            report_path.write_text(json.dumps(report,indent=2))
                    for camera in cameras:
                        rows.append([(f'{look} / {camera} / {style}',report[setting][f'filmstyle_{setting}_{look}_{camera}_{style}'])
                                     for style in ('none','animated_film')])
                sheet(rows, OUT/(setting+'.png'))
                await data('save_project', path='filmstyle/'+setting+'.blend')
                (OUT/'stills.json').write_text(json.dumps(report, indent=2))
        if args.bench:
            benchmark_path=OUT/'benchmark.json'
            results=json.loads(benchmark_path.read_text()) if benchmark_path.exists() else {}
            for setting in ('podcast_studio', 'park'):
                if args.only and setting!=args.only:continue
                path = ROOT/f'output/projects/filmstyle/{setting}.blend'
                await data('open_project', path=str(path if path.exists() else ROOT/'output/projects/filmstyle/actors.blend'))
                if not path.exists():
                    await data('set_environment', preset=setting, subject=CAST, density=.6)
                await data('cinematic_look', preset='golden_hour')
                results[setting] = {}
                # Bookended paired trials, same camera/resolution/16 samples.
                for style in ('none', 'animated_film', 'none'):
                    samples, cpu_samples = [], []
                    for repeat in range(3):
                        cpu = await python('import time\nresult=time.process_time()')
                        t = time.perf_counter()
                        await still(data, 'Filmclose_up', f'bench_{setting}_{style}_{repeat}', style, 'golden_hour', width=512)
                        samples.append(time.perf_counter()-t)
                        cpu_samples.append((await python('import time\nresult=time.process_time()'))-cpu)
                        print('CPU_TRIAL',setting,style,repeat,round(cpu_samples[-1],2),flush=True)
                    results[setting].setdefault(style, []).append(samples)
                    results[setting].setdefault('cpu_'+style, []).append(cpu_samples)
                    benchmark_path.write_text(json.dumps(results,indent=2))
                base = sum(sum(x[1:])/2 for x in results[setting]['none'])/2
                styled = sum(results[setting]['animated_film'][0][1:])/2
                results[setting].update(baseline_s=base, styled_s=styled, ratio=styled/base,
                                        width=512, height=288, samples=16, threads=8,
                    baseline_cpu_s=sum(sum(x[1:])/2 for x in results[setting]['cpu_none'])/2,
                    styled_cpu_s=sum(results[setting]['cpu_animated_film'][0][1:])/2)
                results[setting]['cpu_ratio']=results[setting]['styled_cpu_s']/results[setting]['baseline_cpu_s']
                (OUT/'benchmark.json').write_text(json.dumps(results, indent=2))
        if args.faces:
            await faces(data, python,args.variant,args.resume,args.chunk)


async def faces(data, python, variant=None, resume=False, chunk=None):
    import av
    import contextlib
    import itertools
    from fractions import Fraction
    meta_path=OUT/'faces_base.json'
    if resume and meta_path.exists():
        meta=json.loads(meta_path.read_text())
        audio,proof=meta['audio'],meta['proof']
    else:
        await data('scene_info')
        await data('new_scene', frame_end=2)
        built = await data('script_to_scene', script={**SCRIPT, 'environment': 'podcast_studio'},
                           subtitles=False, sound=False, voice=True, seed=17, lighting='soft', life=1)
        assert built['frames'][1] <= 192, built['frames']
        await data('set_timeline', frame_start=1, frame_end=192, fps=24)
        await podcast_mics(data)
        # Face acceptance uses a plain studio background. Detailed environment
        # shading is covered separately by the four-set style sheets.
        await data('clear_environment')
        await data('render_style', style='animated_film')
        await data('cinematic_look', preset='studio_film', haze=False, dof='off')
        # Speaker/listener portraits through the same conversation.
        for item in (await data('list_shots'))['shots']:
            await data('delete_shot', name=item['camera'])
        listener_end=min(160,max(73,next(line['start'] for line in built['lines'] if line['speaker']==CAST[1])+24))
        for a, b, size, subjects, angle in ((1, listener_end, 'close_up', [CAST[0]], 45),
                                           (listener_end+1, 192, 'close_up', [CAST[1]], -45)):
            await data('camera_shot', subject=subjects, shot=size, start_frame=a, end_frame=b,
                       name='Life'+str(a), angle=angle, avoid_occlusion=True)
        audio = [dict(path=item['path'], frame=item['frames'][0])
                 for item in (await data('list_audio'))['strips'] if item['kind']=='voice']
        plans=[]
        for i,rig in enumerate(CAST):
            plans.append(await data('face_life',character=rig,frame_start=1,frame_end=192,
                                    intensity=1,seed=17+11*i,listen_to=CAST[1-i]))
        closures=await python('''
            from engine.commands.face import _basemesh
            from engine.commands.talk import _fcurves
            sk=_basemesh('Ana_rig').data.shape_keys
            curve=next(fc for fc in _fcurves(sk.animation_data.action) if fc.data_path=='key_blocks["p_b_m_21"].value')
            peaks=[]
            for f in range(2,128):
                if curve.evaluate(f)>.8 and curve.evaluate(f)>=curve.evaluate(f-1) and curve.evaluate(f)>=curve.evaluate(f+1):
                    if not peaks or f-peaks[-1]>6:peaks.append(f)
            assert peaks
            result=peaks
        ''')
        closures=([f for f in closures if f>=25] or closures[:1])[:3]
        visible_blinks=[b['frame'] for b in plans[0]['blinks'] if 25<=b['frame']<=listener_end]+[b['frame'] for b in plans[1]['blinks'] if b['frame']>listener_end]
        assert visible_blinks
        blink=visible_blinks[0]
        reaction=next((r['frame'] for r in plans[0]['reactions'] if 25<=r['frame']<=listener_end),listener_end-4)
        gaze=next((h['micro'] for h in plans[1]['gaze_holds'] if h['micro']>listener_end),151)
        proof=[('m/b/p',f) for f in closures]+[('brow',plans[0]['accents'][0]),('blink',blink),
               ('listener',reaction),('gaze',gaze),('pause/breath',177)]
        proof=[(label,min(192,max(1,round(f)))) for label,f in proof]
        # Freeze the new build's body/articulation once; toggle only the additive life
        # layer, including its blink schedule, for an exact component comparison.
        for rig in CAST:
            await data('face_life',character=rig,frame_start=1,frame_end=192,intensity=0)
        await data('save_project', path='filmstyle/life_base.blend')
        meta_path.write_text(json.dumps(dict(audio=audio,proof=proof,built=built),indent=2))
    evidence_path=OUT/'faces.json'
    # Sample at 12 fps; labels identify the actual rendered scene frame.
    proof=[(label,49 if label=='brow' else
            max(1,f-1) if label=='listener' and f%2==0 else min(191,f|1)) for label,f in proof]
    evidence=json.loads(evidence_path.read_text()) if resume and evidence_path.exists() else {}
    variants=(0.,) if variant=='off' else (1.,) if variant=='on' else (0.,1.)
    if chunk is not None and variant is None:
        raise ValueError('--chunk requires --variant')
    for life in variants:
        await data('open_project', path='filmstyle/life_base.blend')
        reports = []
        for i, rig in enumerate(CAST):
            reports.append(await data('face_life', character=rig, frame_start=1, frame_end=192,
                                      intensity=life, seed=17+11*i, listen_to=CAST[1-i]))
        await data('save_project', path=f'filmstyle/life_{int(life)}.blend')
        # Sample eight seconds at 12 fps. Render in one engine, with checkpoints.
        a,b=(1,192) if chunk is None else (1+64*chunk,64*(chunk+1))
        prefix=f'native_life_{int(life)}_'+('' if chunk is None else f'part{chunk}_')
        rendered = await python(f'''
            import os, time, json, glob, resource
            from engine.render_movie import main as render_movie
            sc=bpy.context.scene
            sc.render.engine='BLENDER_EEVEE'
            sc.eevee.taa_render_samples=8
            sc.render.resolution_x=320;sc.render.resolution_y=180;sc.render.resolution_percentage=100
            sc.frame_start={a};sc.frame_end={b};sc.frame_step=2;sc.render.fps=12
            sc.render.image_settings.media_type='VIDEO';sc.render.image_settings.file_format='FFMPEG'
            sc.render.ffmpeg.format='MPEG4';sc.render.ffmpeg.codec='H264'
            sc.render.ffmpeg.constant_rate_factor='HIGH';sc.render.ffmpeg.audio_codec='NONE'
            sc.render.filepath={str(OUT/prefix)!r}
            # Evaluate the temporary lighting from the same pose in every part;
            # render(animation=True) then advances to the requested frame range.
            sc.frame_set(1)
            spec={str(OUT/(prefix+'handles.json'))!r}
            with open(spec,'w') as f:json.dump(dict(handles=[]),f)
            started=time.perf_counter()
            memory=[]
            def sample(*args):
                memory.append(dict(frame=sc.frame_current,maxrss_kb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
                with open(spec+'.memory.json','w') as f:json.dump(memory,f)
            bpy.app.handlers.render_post.append(sample)
            try:render_movie(spec)
            finally:bpy.app.handlers.render_post.remove(sample)
            movies=sorted(glob.glob(sc.render.filepath+'*.mp4'),key=os.path.getmtime)
            assert movies
            result=dict(movie=movies[-1],seconds=time.perf_counter()-started)
        ''')
        if chunk is not None:
            parts_path=OUT/f'life_{int(life)}_parts.json'
            parts=json.loads(parts_path.read_text()) if resume and parts_path.exists() else {}
            parts[str(chunk)]=rendered
            parts_path.write_text(json.dumps(parts,indent=2))
            if not {'0','1','2'}<=parts.keys():
                print('FACE CHUNK SAVED',chunk,flush=True)
                return
            rendered=dict(movies=[parts[str(i)]['movie'] for i in range(3)],
                          seconds=sum(item['seconds'] for item in parts.values()))
        else:
            rendered['movies']=[rendered['movie']]
        frame_paths={}
        path = OUT/f'life_{int(life)}.mp4'
        with contextlib.ExitStack() as stack:
            sources=[stack.enter_context(av.open(p)) for p in rendered['movies']]
            movie=stack.enter_context(av.open(str(path),'w'))
            audio_stream = movie.add_stream('aac', rate=48000) if audio else None
            if audio_stream: audio_stream.layout='mono'
            stream = movie.add_stream('libx264', rate=12)
            stream.width, stream.height, stream.pix_fmt = 320, 180, 'yuv420p'
            stream.options = {'crf': '18', 'preset': 'fast'}
            count=0
            frames=itertools.chain.from_iterable(source.decode(video=0) for source in sources)
            for i, frame in enumerate(frames):
                count+=1
                f=1+2*i
                if f in {n for _,n in proof}:
                    filename=OUT/f'life_{int(life)}_{f:04d}.png'
                    with av.open(str(filename),'w',format='image2') as still:
                        png=still.add_stream('png');png.width=320;png.height=180;png.pix_fmt='rgb24'
                        for packet in png.encode(frame.reformat(format='rgb24')):still.mux(packet)
                        for packet in png.encode():still.mux(packet)
                    frame_paths[str(f)]=str(filename)
                frame.pts, frame.time_base = i, Fraction(1, 12)
                for packet in stream.encode(frame): movie.mux(packet)
            assert count==96,count
            for packet in stream.encode(): movie.mux(packet)
            if audio_stream:
                import wave
                import numpy as np
                samples = np.zeros(8*48000, dtype=np.int32)
                for item in audio:
                    with wave.open(item['path']) as wav:
                        assert wav.getframerate()==48000 and wav.getnchannels()==1
                        source=np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
                    start=round((item['frame']-1)/24*48000)
                    end=min(len(samples),start+len(source))
                    samples[start:end]+=source[:end-start]
                pcm=np.clip(samples,-32768,32767).astype(np.int16)
                frame=av.AudioFrame.from_ndarray(pcm[None,:],format='s16',layout='mono')
                frame.sample_rate=48000;frame.pts=0;frame.time_base=Fraction(1,48000)
                for packet in audio_stream.encode(frame):movie.mux(packet)
                for packet in audio_stream.encode():movie.mux(packet)
        evidence[str(int(life))] = dict(video=str(path),reports=reports,frames=frame_paths,audio=audio,proof=proof,
            source_frame_start=1,duration_s=8,native_movies=rendered['movies'],render_seconds=rendered['seconds'])
        (OUT/'faces.json').write_text(json.dumps(evidence, indent=2))
    if {'0','1'}<=evidence.keys():
        blink=next(f for label,f in proof if label=='blink')
        blink_frames=sorted({max(1,min(191,blink+d)) for d in (-4,-2,0,2,4)})
        # Resume can select a nearby sample at a camera boundary. Extract both
        # rows from their finished movies so labels and actual frames agree.
        for item in evidence.values():
            with av.open(item['video']) as movie:
                for i,frame in enumerate(movie.decode(video=0)):
                    f=item['source_frame_start']+2*i
                    if f not in {n for _,n in proof} | set(blink_frames):continue
                    filename=OUT/(Path(item['video']).stem+f'_{f:04d}.png')
                    with av.open(str(filename),'w',format='image2') as still:
                        png=still.add_stream('png');png.width=320;png.height=180;png.pix_fmt='rgb24'
                        for packet in png.encode(frame.reformat(format='rgb24')):still.mux(packet)
                        for packet in png.encode():still.mux(packet)
                    item['frames'][str(f)]=str(filename)
            item['proof']=proof
        evidence_path.write_text(json.dumps(evidence,indent=2))
        strips=[[(f'life={life} {label} / {f}',evidence[life]['frames'][str(f)]) for label,f in proof]
                for life in ('0','1')]
        sheet(strips,OUT/'faces.png',size=320)
        sheet([[(f'life={life} blink / {f}',evidence[life]['frames'][str(f)]) for f in blink_frames]
               for life in ('0','1')],OUT/'blink_strip.png',size=320)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for flag in ('quick', 'sheets', 'bench', 'faces', 'rebuild'):
        p.add_argument('--'+flag, action='store_true')
    p.add_argument('--variant',choices=['off','on'])
    p.add_argument('--chunk',type=int,choices=[0,1,2])
    p.add_argument('--resume',action='store_true')
    p.add_argument('--only', choices=['park','rice_terraces','lantern_lake','podcast_studio'])
    asyncio.run(main(p.parse_args()))
