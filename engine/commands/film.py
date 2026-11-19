"""Saved scene projects, film manifests and a serial render queue."""
import copy
import glob
import json
import os
import re
import subprocess
import time
import uuid

import bpy

from . import command, dispatch
from .. import context
from ..film_plan import parse_film, layout, content_hash, offset_captions

PROP = 'char3d_film'


def manifest_path(name):
    if not isinstance(name, str) or not name.strip() or name in ('.', '..') or '/' in name or '\\' in name:
        raise ValueError('Film name must be a nonempty name without path separators')
    slug = re.sub(r'[^\w.-]+', '_', name.strip())[:100]
    return context.resolve(f'{slug}/film.json', 'projects')


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path+'.tmp', 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    os.replace(path+'.tmp', path)


def _read(name):
    if name is None:
        name = json.loads(bpy.context.scene.get(PROP, '{}')).get('name')
        if name is None:
            raise ValueError('No active film; pass name or open_film_scene first')
    path = manifest_path(name)
    with open(path) as stream:
        value = json.load(stream)
    return value, path


def _active():
    from .video import JOBS
    return any(j.get('kind') == 'film' and j['status'] == 'running' for j in JOBS.values())


def _embed(manifest, index, path):
    bpy.context.scene[PROP] = json.dumps({'name': manifest['name'], 'index': index,
        'manifest': path, 'film': manifest}, ensure_ascii=False)


@command('script_to_film')
def script_to_film(script, name=None, environment=None, lighting='studio', camera='mixed',
                   subtitles=True, language='auto', seed=0, build=True, sound=True,
                   look=None, body_language=True, scene_index=None, _plan=None, music='auto'):
    plan = copy.deepcopy(_plan) if _plan else parse_film(script, name, environment, seed,
        bpy.context.scene.render.fps, look, lighting, music)
    if not build:
        return {'plan': plan, 'kind': 'film', 'built': False, 'frames': plan['estimated_frames'],
                'duration_s': plan['duration_s'], 'warnings': plan['warnings']}
    if _active():
        raise ValueError('Wait for or cancel the current film render before rebuilding')
    path = manifest_path(plan['name'])
    options = dict(camera=camera, subtitles=subtitles, language=language, seed=seed,
                   sound=sound, body_language=body_language, music=music)
    # Validate every scene through the original pipeline before clearing the editor.
    for scene in plan['scenes']:
        dispatch('script_to_scene', dict(script=scene['plan'], lighting=scene['lighting'], build=False, **options))
    manifest = copy.deepcopy(plan)
    manifest.update(manifest=path, options=options, built=False, status='building')
    if scene_index is not None:
        if type(scene_index) is not int or not 1 <= scene_index <= len(plan['scenes']):
            raise ValueError('scene_index is one-based and must refer to an existing scene')
        old, _ = _read(plan['name'])
        if not old.get('built'):
            raise ValueError('Build all scenes successfully before rebuilding one scene')
        if old.get('voices') != plan.get('voices'):
            raise ValueError('Voice casting changed; build all scenes to preserve voice continuity')
        if len(old['scenes']) != len(plan['scenes']):
            raise ValueError('Scene count changed; build all scenes')
        # Other projects may be manually edited. Do not replace their saved metadata.
        for i, source in enumerate(old['scenes']):
            if i != scene_index-1:
                if source.get('source_hash') != plan['scenes'][i]['source_hash']:
                    raise ValueError(f'Scene {i+1} also changed (possibly costume continuity); build all scenes')
                manifest['scenes'][i] = source
    for scene in manifest['scenes']:
        scene['project'] = os.path.join(os.path.dirname(path), f'scene_{scene["index"]:02d}.blend')
        if scene_index is None or scene['index'] == scene_index:
            scene['status'] = 'pending'
    _write(path, manifest)
    try:
        for scene in manifest['scenes']:
            if scene_index and scene['index'] != scene_index:
                continue
            scene['status'] = 'building'
            _write(path, manifest)
            dispatch('new_scene', {'fps': plan['fps'], 'frame_end': 2})
            result = dispatch('script_to_scene', dict(script=scene['plan'], lighting=scene['lighting'],
                character_seeds=scene['character_seeds'], **options))
            scene.update(frames=result['frames'], duration_s=result['duration_s'], characters=result['characters'],
                         shots=result['shots'], warnings=result['warnings'], status='built', timings=result['timings'])
            scene['music'] = result.get('music')
            # Store the resolved build parameters as continuity evidence, including exact garments.
            if all(c['realistic'] for c in result['characters'].values()):
                scene['appearance'] = {ident: char.pop('appearance') for ident, char in result['characters'].items()}
            _embed(manifest, scene['index'], path)
            dispatch('save_project', {'path': scene['project']})
            _write(path, manifest)
        manifest['frames'] = layout(manifest['scenes'], plan['fps'])
        manifest['warnings'] = list(dict.fromkeys(plan['warnings'] + [w for s in manifest['scenes'] for w in s.get('warnings', [])]))
        manifest.update(duration_s=round(manifest['frames'][1]/plan['fps'], 3), built=True, status='built')
        _write(path, manifest)
        # Each blend carries the complete, final manifest. Opening it also finds the newer JSON.
        for scene in manifest['scenes']:
            if scene_index and scene['index'] != scene_index:
                continue
            dispatch('open_project', {'path': scene['project']})
            _embed(manifest, scene['index'], path)
            dispatch('save_project', {'path': scene['project']})
    except Exception as exc:
        manifest.update(status='failed', error=str(exc))
        _write(path, manifest)
        raise
    manifest, _ = _read(plan['name'])
    return {'kind': 'film', 'built': True, 'plan': plan, 'film': manifest, 'manifest': path,
            'frames': manifest['frames'], 'duration_s': manifest['duration_s'], 'warnings': manifest['warnings']}


@command('film_info')
def film_info(name=None):
    if name is None:
        active = json.loads(bpy.context.scene.get(PROP, '{}'))
        name = active.get('name')
        if name is None:
            films = []
            for p in sorted(glob.glob(context.resolve('*/film.json', 'projects'))):
                with open(p) as stream:
                    films.append(json.load(stream))
            return {'films': films}
    manifest, _ = _read(name)
    return manifest


@command('open_film_scene')
def open_film_scene(name, index):
    manifest, path = _read(name)
    if type(index) is not int or not 1 <= index <= len(manifest['scenes']):
        raise ValueError('Scene index is one-based')
    scene = manifest['scenes'][index-1]
    result = dispatch('open_project', {'path': scene['project']})
    _embed(manifest, index, path)
    return dict(result, film=name, index=index, manifest=path)


def saved_scene(path):
    """Called by save_project for a film project, including manually edited timelines."""
    active = json.loads(bpy.context.scene.get(PROP, '{}'))
    if not active or os.path.realpath(path) != os.path.realpath(active['film']['scenes'][active['index']-1]['project']):
        return
    manifest, filename = _read(active['name'])
    scene = manifest['scenes'][active['index']-1]
    sc = bpy.context.scene
    if sc.render.fps / sc.render.fps_base != manifest['fps']:
        raise ValueError('Film scenes must keep the film fps; rebuild the film to change fps')
    scene.update(frames=[sc.frame_start, sc.frame_end], duration_s=(sc.frame_end-sc.frame_start+1)/manifest['fps'])
    scene['look'] = json.loads(sc.get('char3d_cinematic_look', 'null'))
    scene['weather'] = sc.get('c3d_weather_kind', 'clear')
    scene['environment'] = next((o['c3d_environment_preset'] for o in sc.objects if o.get('c3d_environment_preset')), None)
    manifest['frames'] = layout(manifest['scenes'], manifest['fps'])
    manifest['duration_s'] = manifest['frames'][1]/manifest['fps']
    _write(filename, manifest)
    _embed(manifest, active['index'], filename)


@command('film_render_options')
def film_render_options(name=None, quality='final', vertical=False, calibrate=False):
    from . import video
    manifest, _ = _read(name)
    name = manifest['name']
    if not manifest.get('built'):
        raise ValueError('Build all scenes before estimating film renders')
    engine = video.QUALITY.get(quality)
    if not engine:
        raise ValueError('Unknown render quality')
    # Build stores render options per scene; refresh them from saved projects for edits.
    origin = _snapshot_editor()
    reports = []
    try:
        for scene in manifest['scenes']:
            dispatch('open_project', {'path': scene['project']})
            reports.append(dispatch('render_options', {'quality': quality, 'vertical': vertical,
                'calibrate': calibrate and not reports}))
    finally:
        _restore_editor(origin)
    options = []
    for i, choice in enumerate(reports[0]['options']):
        total = sum(r['options'][i]['total_s'] for r in reports) + manifest['frames'][1]*.1
        options.append(dict(choice, total_s=round(total), total=video._fmt_duration(total)))
    return dict(kind='film', name=name, quality=quality, frames=manifest['frames'],
        duration_s=manifest['duration_s'], options=options, machine_speed=reports[0]['machine_speed'],
        scenes=[dict(index=s['index'], name=s['name'], **r) for s, r in zip(manifest['scenes'], reports)])


def _snapshot_editor():
    directory = context.resolve('jobs')
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, 'film_editor_'+uuid.uuid4().hex+'.blend')
    original = bpy.context.scene.get('char3d_editor_source', bpy.data.filepath)
    from .io import _absolute_external_paths
    _absolute_external_paths()
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    return path, original


def _restore_editor(origin):
    path, original = origin
    dispatch('open_project', {'path': path})
    # BlendData.filepath is read-only. Keep the logical editor path separately;
    # saving always uses save_project's explicit destination. Relative assets were
    # remapped by Blender when writing the snapshot and remain correctly anchored.
    bpy.context.scene['char3d_editor_source'] = original
    os.remove(path)


@command('render_film')
def render_film(name=None, path='film.mp4', quality='draft', resolution=None, width=None,
                height=None, vertical=False, subtitles=True, wait=False, resume=True):
    from . import video, subtitles as subs
    if quality not in video.QUALITY:
        raise ValueError('Unknown render quality')
    if quality != 'draft' and not resolution and not (width and height):
        raise ValueError('Choose a resolution with film_render_options before preview/final rendering')
    if any(j['status'] == 'running' for j in video.JOBS.values()):
        raise ValueError('Wait for or cancel the active render first; film workers run serially')
    manifest, _ = _read(name)
    name = manifest['name']
    if not manifest.get('built'):
        raise ValueError('Build all scenes before rendering the film')
    output = context.resolve(path, 'renders')
    if not output.lower().endswith('.mp4'):
        output += '.mp4'
    os.makedirs(os.path.dirname(output), exist_ok=True)
    ident = 'film_'+uuid.uuid4().hex[:12]
    directory = context.resolve('jobs/'+ident)
    os.makedirs(directory)
    settings = dict(quality=quality, resolution=resolution, width=width, height=height, vertical=vertical)
    job = dict(kind='film', id=ident, name=name, path=output, status='running', stage='prepare',
               started=time.time(), quality=quality, scenes=[], manifest=manifest, directory=directory,
               frames=manifest['frames'], overlays=[], chunks=[], children=[], size=None)
    origin = _snapshot_editor()
    try:
        for scene in manifest['scenes']:
            dispatch('open_project', {'path': scene['project']})
            sc = bpy.context.scene
            if sc.render.fps / sc.render.fps_base != manifest['fps']:
                raise ValueError('All saved film projects must use the film fps')
            scene['frames'] = [sc.frame_start, sc.frame_end]
        job['frames'] = layout(manifest['scenes'], manifest['fps'])
        for scene in manifest['scenes']:
            dispatch('open_project', {'path': scene['project']})
            sc = bpy.context.scene
            size = video._output_size(sc, quality, width, height, resolution, vertical)
            pixels = [round(size[0]*size[2]/100), round(size[1]*size[2]/100)]
            if job['size'] and job['size'] != pixels:
                raise ValueError('Scene dimensions differ; choose a common film resolution')
            job['size'] = pixels
            from .music import PROP as MUSIC_PROP, scene_context
            from .audio import _sound_strips, _speech_ranges
            scene['score'] = json.loads(sc.get(MUSIC_PROP, 'null'))
            if not any(s.get(MUSIC_PROP) and not s.mute for s in _sound_strips(sc)):
                scene['score'] = None
            _mood, scene['score_cuts'], scene['score_emotions'] = scene_context(sc)
            scene['speech'] = _speech_ranges(sc)
            # The film gets one independent score covering cards and cuts. Mute
            # only owned preview music in temporary worker snapshots.
            for strip in _sound_strips(sc):
                if strip.get(MUSIC_PROP):
                    strip.mute = True
            key = content_hash(scene['project'], dict(settings, renderer_version=2))
            cache = context.resolve(f'film_cache/{key}.mp4', 'renders')
            reuse = bool(resume and os.path.isfile(cache) and os.path.getsize(cache))
            entry = dict(index=scene['index'], name=scene['name'], path=cache, hash=key,
                         status='reused' if reuse else 'pending', reused=reuse)
            job['scenes'].append(entry)
            if not reuse:
                child = dispatch('render_video', dict(path=cache, subtitles=False, _defer=True, **settings))
                entry['job_id'] = child['job_id']
                job['children'].append(child['job_id'])
            if subtitles and subs.get_config(sc):
                overlays, chunks = subs.build(sc, *pixels, sc.frame_start, sc.frame_end,
                                              os.path.join(directory, f'subs{scene["index"]}'))
                offset = scene['subtitle_offset_frames']
                for ov in overlays:
                    ov['scene_index'] = scene['index']
                    ov['start'] += offset
                    ov['end'] += offset
                    if ov.get('keys'):
                        ov['keys'] = [[f+offset, *rest] for f, *rest in ov['keys']]
                job['overlays'].extend(overlays)
                for shifted in offset_captions(chunks, offset-sc.frame_start+1):
                    # Subtitle chunks hold individual scene-frame word times.
                    shifted['start'] = max(scene['film_frames'][0], shifted['start'])
                    shifted['end'] = min(scene['film_frames'][1]+1, shifted['end'])
                    job['chunks'].append(shifted)
            if scene.get('card'):
                from .graphics import draw_title
                card = dispatch('add_title', {'text': scene['card']['text'], 'style': 'center',
                    'duration_s': scene['card']['duration_s'], 'name': '__FilmCard', 'animation': 'none'})
                png = os.path.join(directory, f'card{scene["index"]}.png')
                draw_title(png, *pixels, card)
                scene['card_png'] = png
        from ..music.film import score_film
        job['music'] = score_film(manifest['scenes'], manifest['fps'], job['frames'][1],
                                 context.resolve('audio/music/generated', 'imports'))
        if job['chunks']:
            srt = os.path.splitext(output)[0]+'.srt'
            count = subs.write_srt(srt, sorted(job['chunks'], key=lambda c: c['start']), manifest['fps'], 1, job['frames'][1])
            job['subtitles'] = {'srt': srt, 'captions': count}
        else:
            stale = os.path.splitext(output)[0]+'.srt'
            if os.path.isfile(stale):
                os.remove(stale)
    except Exception:
        for child in job['children']:
            video.cancel_render(child)
        raise
    finally:
        _restore_editor(origin)
    job['estimate'] = {'total_s': sum(video.JOBS[c]['estimate']['total_s'] for c in job['children']) + job['frames'][1]*.1}
    video.JOBS[ident] = job
    if wait:
        while job['status'] == 'running':
            _advance(job)
            time.sleep(.1)
    return report(job)


def _compose(job):
    fps = job['manifest']['fps']
    spec = dict(width=job['size'][0], height=job['size'][1], fps=fps, frames=job['frames'][1],
                out_base=os.path.join(job['directory'], 'composed_'), overlays=job['overlays'],
                music=job.get('music'),
                scenes=[dict(s, movie=e['path']) for s, e in zip(job['manifest']['scenes'], job['scenes'])])
    path = os.path.join(job['directory'], 'compose.json')
    _write(path, spec)
    log = os.path.join(job['directory'], 'compose.log')
    script = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'compose_film.py')
    with open(log, 'wb') as stream:
        job['proc'] = subprocess.Popen([bpy.app.binary_path, '-b', '--factory-startup', '-t', '4',
            '--python-exit-code', '1', '--python', script, '--', path], stdout=stream,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    job.update(stage='compose', log=log)


def _advance(job):
    from . import video
    if job['status'] != 'running':
        return
    try:
        if job['stage'] == 'compose':
            code = job['proc'].poll()
            if code is None:
                return
            movies = glob.glob(os.path.join(job['directory'], 'composed_*.mp4'))
            if code or not movies:
                raise RuntimeError('Film composition failed: '+job['log'])
            os.replace(movies[0], job['path'])
            job.update(status='done', bytes=os.path.getsize(job['path']), finished=time.time())
            return
        for entry in job['scenes']:
            if entry['status'] in ('done', 'reused'):
                continue
            child = video.JOBS[entry['job_id']]
            if child['status'] == 'queued':
                video._launch(child)
                entry['status'] = 'running'
            data = video._report(child)
            entry['progress'] = data.get('progress', '0/1')
            entry['eta_s'] = data.get('eta_s', child.get('estimate', {}).get('total_s', 0))
            job['stage'] = f'scene {entry["index"]}/{len(job["scenes"])}'
            if child['status'] == 'failed':
                raise RuntimeError(data.get('error') or 'Scene render failed: '+child['log'])
            if child['status'] != 'done':
                return
            entry['status'] = 'done'
            break  # Next tick starts the next worker, after this worker has exited.
        else:
            _compose(job)
    except Exception as exc:
        job.update(status='failed', error=str(exc), finished=time.time())
        for child_id in job['children']:
            child = video.JOBS[child_id]
            if child['status'] in ('queued', 'running'):
                video.cancel_render(child_id)


def tick():
    from .video import JOBS
    for job in list(JOBS.values()):
        if job.get('kind') == 'film':
            _advance(job)


def report(job):
    from . import video
    _advance(job)
    done = sum(s['status'] in ('done', 'reused') for s in job['scenes'])
    total = len(job['scenes'])+1
    if job['status'] == 'done':
        done = total
    elapsed = (job.get('finished') or time.time())-job['started']
    eta = job['frames'][1]*.1
    for scene in job['scenes']:
        if scene['status'] == 'running':
            eta += scene.get('eta_s', 0)
        elif scene['status'] == 'pending':
            child = video.JOBS[scene['job_id']]
            frames = child['frames'][1]-child['frames'][0]+1+child['graphics']['handle_frames']
            eta += child['model_spf']*video._factor(video.QUALITY[child['quality']][0])*frames
    if job['stage'] == 'compose':
        try:
            with open(job['log']) as stream:
                cursor = video.progress_cursor(stream.read()) or 0
            eta = max(0, job['frames'][1]-cursor)*.1
        except OSError:
            pass
    if job['status'] != 'running':
        eta = 0
    return {k: v for k, v in dict(job_id=job['id'], kind='film', name=job['name'], status=job['status'],
        path=job['path'], stage=job['stage'], quality=job['quality'], size=job['size'], frames=job['frames'],
        progress=f'{done}/{total}', progress_unit='stages', scenes=job['scenes'], elapsed_s=round(elapsed, 1),
        eta_s=round(eta, 1), estimate=job['estimate'],
        bytes=job.get('bytes'), subtitles=job.get('subtitles'), music=job.get('music'), has_audio=job.get('status') == 'done',
        error=job.get('error')).items() if v is not None}


def cancel(job):
    from . import video
    if job['status'] != 'running':
        return report(job)
    job.update(status='cancelled', finished=time.time())
    if job.get('proc') and job['proc'].poll() is None:
        job['proc'].terminate()
        job['proc'].wait(timeout=10)
    for child in job['children']:
        if video.JOBS[child]['status'] in ('queued', 'running'):
            video.cancel_render(child)
    for scene in job['scenes']:
        if scene['status'] in ('pending', 'running'):
            scene['status'] = 'cancelled'
    return report(job)


def shutdown():
    from .video import JOBS
    for job in list(JOBS.values()):
        if job.get('kind') == 'film' and job['status'] == 'running':
            cancel(job)
