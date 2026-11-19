"""Real film acceptance, called in isolation by e2e_smoke --film-only."""
import asyncio
import json
import os
from pathlib import Path
import re
import shutil

from test_film import SCRIPT

ROOT = Path(__file__).resolve().parents[1]


async def run(call, text_of):
    import av
    import numpy as np
    (ROOT/'output').mkdir(exist_ok=True)
    (ROOT/'output/film_script.txt').write_text(SCRIPT)
    clay_only = os.environ.get('CHAR3D_AUDIO_CLAY_ONLY') == '1'
    draft_size = dict(width=320 if clay_only else 640, height=180 if clay_only else 360)

    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[0])

    await data('scene_info')
    # Configure writable MPFB test data/logs through the shared new_scene hook,
    # then initialize its services before the film's internal factory resets.
    await call('new_scene', frame_end=2)
    await data('mpfb_assets')
    initial = await data('scene_info')
    parsed = await data('script_to_film', script=SCRIPT, name='film_acceptance', build=False, language='id', seed=7)
    assert parsed == await data('script_to_film', script=SCRIPT, name='film_acceptance', build=False, language='id', seed=7)
    assert initial == await data('scene_info'), 'Planning changed editor scene'
    assert parsed['voices'] and len(parsed['plan']['scenes']) == 3
    if os.environ.get('CHAR3D_FILM_RESUME') == '1':
        built = {'built': True, 'cache_hits': 1}
    else:
        built = await data('script_to_film', script=SCRIPT, name='film_acceptance', language='id', seed=7)
    manifest = await data('film_info', name='film_acceptance')
    assert built['built'] and manifest['built'] and len(manifest['scenes']) == 3
    assert built.get('generated_files') or built['cache_hits']
    a, b, c = manifest['scenes']
    assert all(all(char['realistic'] for char in s['characters'].values()) for s in manifest['scenes'])
    assert a['appearance']['ANA']['hair'] == b['appearance']['ANA']['hair'] == c['appearance']['ANA']['hair']
    assert a['appearance']['BUDI'] == b['appearance']['BUDI'] == c['appearance']['BUDI']
    assert b['appearance']['ANA'] == c['appearance']['ANA']
    assert a['appearance']['ANA']['outfit'] == 'casual' and b['appearance']['ANA']['outfit'] == 'formal'
    assert len(manifest['voices']) == 2
    stills = []
    for s in manifest['scenes']:
        assert Path(s['project']).is_file()
        await data('open_film_scene', name=manifest['name'], index=s['index'])
        info = await data('scene_info')
        assert info['film']['index'] == s['index']
        assert info['cinematic_look']['preset'] == s['look']['preset']
        state = (await data('run_blender_python', code="import json\nresult=json.loads(bpy.context.scene['char3d_film'])"))['result']
        assert len(state['film']['scenes']) == 3 and state['film']['voices'] == manifest['voices']
        await data('run_blender_python', code="bpy.context.scene.render.threads_mode='FIXED'\nbpy.context.scene.render.threads=4\nbpy.context.scene.eevee.taa_render_samples=8\nresult=True")
        quick = await data('render_frames', frames=[8], camera='scene', engine_name='workbench', size=256)
        assert Path(quick['path']).is_file()
        suffix = 'clay' if clay_only else 'eevee'
        target = ROOT / 'output' / f'film_scene_{s["index"]:02d}_{suffix}.png'
        if clay_only:
            shutil.copyfile(quick['path'], target)
        elif not ((os.environ.get('CHAR3D_FILM_RESUME') == '1' or os.environ.get('CHAR3D_FILM_SKIP_STILLS') == '1') and target.exists()):
            rendered = await data('render_frames', frames=[8], camera='scene', engine_name='eevee', size=384)
            shutil.copyfile(rendered['path'], target)
        stills.append(target)
    # Estimates and render preparation preserve unsaved editor objects/poses.
    before = await data('scene_info')
    opts = await data('film_render_options', name=manifest['name'], quality='draft')
    after = await data('scene_info')
    assert before == after
    assert len(opts['scenes']) == 3 and len(opts['options']) == 6
    assert all(opts['options'][i]['total_s'] <= opts['options'][i+1]['total_s'] for i in range(5))
    movie = await data('render_film', name=manifest['name'], path='film_acceptance.mp4',
                       quality='draft', **draft_size)
    for _ in range(600):
        movie = await data('render_status', job_id=movie['job_id'])
        if movie['status'] != 'running':
            break
        await asyncio.sleep(.5)
    assert movie['status'] == 'done', movie
    assert before == await data('scene_info'), 'Render changed editor state'
    expected = sum(s['frames'][1]-s['frames'][0]+1+s['card_frames'] for s in manifest['scenes'])-sum(s['overlap_frames'] for s in manifest['scenes'])
    assert movie['frames'] == [1,expected]
    with av.open(movie['path']) as clip:
        assert len(clip.streams.audio) == 1 and abs(clip.duration/1e6-expected/24) <= .05
        frames = [f.to_ndarray(format='rgb24') for f in clip.decode(video=0)]
    assert len(frames) == expected
    with av.open(movie['path']) as clip:
        sound = list(clip.decode(audio=0))
    for previous, following in zip(sound, sound[1:]):
        assert abs(float(following.pts*following.time_base-(previous.pts*previous.time_base+previous.samples/previous.sample_rate))) < 1/24000
    audio = np.concatenate([f.to_ndarray().reshape(-1) for f in sound])
    assert np.max(np.abs(audio)) > .05
    # The dip's center is black, including subtitles; the card lasts before park.
    boundary = c['segment_start']
    assert frames[boundary-1].mean() < 3, (boundary, frames[boundary-1].mean())
    assert frames[boundary+6].mean() > frames[boundary-1].mean()+5
    card_frame = b['segment_start']+b['transition_frames']+3
    assert frames[card_frame-1].std() > 15, 'Title card text missing'
    srt = Path(movie['subtitles']['srt']).read_text()
    times = re.findall(r'(\d\d):(\d\d):(\d\d),(\d\d\d) -->', srt)
    seconds = [int(h)*3600+int(m)*60+int(s)+int(ms)/1000 for h,m,s,ms in times]
    assert len(seconds) == 6 and seconds == sorted(seconds)
    for i, scene in enumerate(manifest['scenes']):
        assert scene['film_frames'][0]/24-.05 <= seconds[2*i] <= (scene['film_frames'][0]+12)/24
    # Unchanged scenes are reused; composition still runs with global captions.
    reuse = await data('render_film', name=manifest['name'], path='film_acceptance_resume.mp4',
                       quality='draft', **draft_size, wait=True)
    assert reuse['status'] == 'done' and all(s['reused'] for s in reuse['scenes'])
    cancel = await data('render_film', name=manifest['name'], path='film_cancelled.mp4',
                        quality='draft', **draft_size, resume=False)
    cancelled = await data('cancel_render', job_id=cancel['job_id'])
    assert cancelled['status'] == 'cancelled'
    assert all(s['status'] != 'done' for s in cancelled['scenes'])
    # A one-scene rebuild keeps the other blend files byte-identical.
    import hashlib
    untouched = [hashlib.sha256(Path(s['project']).read_bytes()).hexdigest() for s in (a,b)]
    rebuilt = await data('script_to_film', script=SCRIPT, name=manifest['name'], language='id', seed=7, scene_index=3)
    assert rebuilt['built']
    assert untouched == [hashlib.sha256(Path(s['project']).read_bytes()).hexdigest() for s in (a,b)]
    # Save an edited project: only that blend's content hash becomes invalid.
    from engine.film_plan import content_hash
    settings = dict(quality='draft', resolution=None, **draft_size, vertical=False, renderer_version=2)
    old_hash = content_hash(c['project'], settings)
    await data('open_film_scene', name=manifest['name'], index=3)
    await data('add_title', text='Sampai besok', style='corner', duration_s=.5, name='FilmEdit')
    await data('render_frames', frames=[5], camera='scene', engine_name='workbench', size=256)
    await data('save_project', path=c['project'])
    assert content_hash(c['project'], settings) != old_hash
    assert (await data('film_info', name=manifest['name']))['frames'] == manifest['frames']
    await data('remove_graphics', name='FilmEdit')
    await data('save_project', path=c['project'])
    movie = await data('render_film', name=manifest['name'], path='film_acceptance.mp4',
                       quality='draft', **draft_size, wait=True)
    assert movie['status'] == 'done' and [s['reused'] for s in movie['scenes']] == [True, True, False]
    manifest = await data('film_info', name=manifest['name'])
    rows = []
    for path in stills:
        with av.open(str(path)) as source:
            rows.append(next(source.decode(video=0)).to_ndarray(format='rgb24'))
    height = max(im.shape[0] for im in rows)
    sheet = np.full((height+24, sum(im.shape[1] for im in rows), 3), 20, dtype=np.uint8)
    x = 0
    for im in rows:
        sheet[24:24+im.shape[0],x:x+im.shape[1]] = im
        x += im.shape[1]
    sheet_path = ROOT/'output/film_contact_sheet.png'
    with av.open(str(sheet_path), 'w', format='image2') as image:
        stream = image.add_stream('png', rate=1)
        stream.width, stream.height, stream.pix_fmt = sheet.shape[1], sheet.shape[0], 'rgb24'
        for packet in stream.encode(av.VideoFrame.from_ndarray(sheet, format='rgb24')):
            image.mux(packet)
        for packet in stream.encode():
            image.mux(packet)
    result = dict(movie=movie,manifest=manifest,stills=list(map(str,stills)),sheet=str(sheet_path),
                  expected_frames=expected, audio_frames=len(sound), srt_starts=seconds,
                  boundaries=[s['film_frames'] for s in manifest['scenes']],resume=reuse)
    (ROOT/'output/film_e2e_results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print(f'FILM E2E OK: 3 MPFB/Piper scenes | {expected} frames | continuous AAC | SRT offsets | dissolve + dip + card | continuity + outfit | resume/cancel/edit hash', flush=True)
