"""Small real MCP music/film check, run on the isolated 9974 or audio-v2 9975 port."""
import json
import os
from pathlib import Path
import wave

import av
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def decode(path):
    with av.open(str(path)) as movie:
        stream = movie.streams.audio[0]
        rate = stream.rate
        frames = list(movie.decode(audio=0))
        # Verify timestamps/sample count: no AAC gap at a scene cut or card.
        for a, b in zip(frames, frames[1:]):
            assert abs(b.time-(a.time+a.samples/rate)) < 2/rate
        return np.concatenate([f.to_ndarray().mean(axis=0) for f in frames]), rate


async def check_dialogue_ducking(data, call, workspace):
    await call('new_scene', frame_end=120)
    rate = 48000
    position = np.arange(4 * rate) / rate
    signal = .25 * np.sin(2 * np.pi * 220 * position)
    signal *= ((.4 <= position) & (position < .9)) | ((2.4 <= position) & (position < 2.9))
    fixture = workspace / 'imports' / 'dialogue_pause.wav'
    fixture.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(fixture), 'wb') as wav:
        wav.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        # Antiphase stereo still contains speech.
        wav.writeframes((np.column_stack((signal, -signal)) * 32767).astype('<i2').tobytes())

    speaker = (await data('add_primitive', kind='cube', name='VoiceOwner'))['name']
    bed = await data('add_audio', path=fixture.name, kind='music', loop=True, volume=.3)
    voice = await data('add_audio', path=fixture.name, start_frame=13)
    await call('run_blender_python', code=f'''
from engine.commands.audio import _sound_strips
from engine.commands.semantic import store_words
sc = bpy.context.scene
voice = next(s for s in _sound_strips(sc) if s.name == {voice['strip']!r})
voice.frame_final_start, voice.frame_final_end = 24, 81
voice['char3d_speaker'] = {speaker!r}
store_words(bpy.data.objects[{speaker!r}], [('pause', 48, 52)], 24, 81)
''')
    ducking = await data('duck_music', music_strip=bed['strip'])
    assert ducking['speech_ranges'] == [[24, 35], [70, 81]], ducking
    inspection = await data('run_blender_python', code=f'''
from engine.commands.audio import _sound_strips, _volume_curve
strips = _sound_strips(bpy.context.scene)
bed = next(s for s in strips if s.name == {bed['strip']!r})
result = [_volume_curve(bed).evaluate(f) for f in (29, 53, 76)]
next(s for s in strips if s.name == {voice['strip']!r}).mute = True
''')
    assert np.allclose(inspection['result'], [.3 * 10 ** (-12 / 20), .3, .3 * 10 ** (-12 / 20)])
    assert not (await data('duck_music'))['speech_ranges'], 'muted dialogue must leave music at full gain'
    await call('remove_audio', name=voice['strip'])
    assert (await data('duck_music'))['speech_ranges'] == [[48, 52]]
    print('DIALOGUE DUCK OK | stereo, trim, pause, mute and words-only', flush=True)


async def run(call, text_of):
    assert os.environ.get('CHAR3D_PORT') in ('9974', '9975'), 'music integration requires an isolated test port'

    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[-1])

    await data('scene_info')
    await check_dialogue_ducking(data, call, Path(os.environ.get('CHAR3D_WORKSPACE', ROOT / 'output')))
    await call('new_scene', frame_end=2)
    clothes = ['female_casualsuit01', 'shoes01']
    script = dict(characters=[dict(id='Ana', gender=0, hair=None, clothes=clothes)], beats=[
        dict(do='pause', seconds=1), dict(say='Ana', text='Sedih sekali.', emotion='sad'), dict(do='pause', seconds=3)])
    parsed = await data('script_to_scene', script=script, build=False, sound=False)
    assert parsed['plan']['music']['mood'] == 'sad'
    built = await data('script_to_scene', script=script, sound=False, subtitles=False, body_language=False)
    assert built['music']['mood'] == 'sad' and built['music']['ducking']['speech_ranges']
    final = built['frames'][1]
    await call('render_preview', camera='scene', engine_name='workbench', width=160, height=90)
    await call('camera_shot', subject=[built['characters']['Ana']['rig']], shot='medium',
               start_frame=49, end_frame=final, name='ScoreCut')
    await call('add_title', text='Musik', start_s=3, duration_s=.5)
    result = await data('auto_music', seed=17, fade_in=.1, fade_out=.1)
    assert {49, 73} <= {a['frame'] for a in result['accents']}, result
    # Inspect actual volume keys, ownership and persisted sentence metadata.
    inspection = await data('run_blender_python', code='''
from engine.commands.audio import _sound_strips, _volume_curve
from engine.commands.music import PROP
st=next(s for s in _sound_strips(bpy.context.scene) if s.get(PROP))
curve=_volume_curve(st)
result=dict(owner=bool(st.get(PROP)), values={str(f):curve.evaluate(f) for f in [10,30,100]},
            kind=st['char3d_audio_kind'], frames=[st.frame_final_start,st.frame_final_end],
            emotions=any(o.get('char3d_emotions') for o in bpy.context.scene.objects))
''')
    values = inspection['result']['values']
    assert values['30'] < values['10']*.30, values
    assert inspection['result']['emotions']
    again = await data('auto_music', seed=17, fade_in=.1, fade_out=.1)
    assert result['hash'] == again['hash'] and len(again['removed']) == 1
    listing = (await data('list_audio'))['strips']
    assert len([s for s in listing if s['kind'] == 'music']) == 1
    manual = await data('add_audio', path=result['path'], kind='music', volume=.001)
    await call('save_project', path='music_check.blend')
    await call('new_scene')
    await call('open_project', path='music_check.blend')
    cleared = await data('auto_music', clear=True)
    assert len(cleared['removed']) == 1
    assert manual['strip'] in {s['name'] for s in (await data('list_audio'))['strips']}
    # Real two-scene draft: shared identity, distinct moods and a scored title card.
    scenes = []
    for i, (mood, text) in enumerate((('warm', 'Halo.'), ('sad', 'Sedih sekali.'))):
        scenes.append(dict(name=mood, music=mood, card={'text': 'Kemudian', 'duration_s': .5} if i else None,
            beats=[dict(do='pause', seconds=.8), dict(say='Ana', text=text), dict(do='pause', seconds=2)]))
    film_script = dict(characters=[dict(id='Ana', gender=0, hair=None, clothes=clothes)], scenes=scenes)
    film = await data('script_to_film', script=film_script, name='music_transition', sound=False,
                      subtitles=False, body_language=False, seed=17)
    voices = []
    for scene in film['film']['scenes']:
        await call('open_film_scene', name='music_transition', index=scene['index'])
        for strip in (await data('list_audio'))['strips']:
            if strip['kind'] == 'voice':
                if strip['path'].startswith('//'):
                    strip['path'] = str((Path(scene['project']).parent/strip['path'][2:]).resolve())
                voices.append(dict(strip, offset=scene['film_frames'][0]-1))
    await call('render_preview', camera='scene', engine_name='workbench', width=160, height=90)
    movie = await data('render_film', name='music_transition', path='music_transition.mp4', quality='draft',
                       width=320, height=180, subtitles=False, wait=True)
    assert movie['status'] == 'done', movie
    report = movie['music']
    assert len(report['sections']) == 2
    audio, rate = decode(movie['path'])
    with wave.open(report['path']) as wav:
        source = np.frombuffer(wav.readframes(wav.getnframes()), '<i2').reshape(-1, 2).mean(axis=1)/32768
    cut_frame = film['film']['scenes'][1]['segment_start']
    at = round((cut_frame-1)/24*rate)
    window = audio[at-round(.1*rate):at+round(.1*rate)]
    assert np.sqrt(np.mean(window**2)) > .0005, 'silent music at scene cut/card'
    assert np.max(abs(np.diff(window))) < .15, 'click at scene cut'
    # Silent windows contain only the composed score. PCM and AAC must correlate,
    # including across the card/cut, proving the score survives the final mux.
    speech = report['speech_ranges']
    errors, correlations = [], []
    for start in np.arange(.3, len(source)/48000-.3, .25):
        frame = start*24+1
        if any(a-8 <= frame <= b+12 for a, b in speech):
            continue
        lo, hi = round(start*48000), round((start+.15)*48000)
        decoded = audio[lo:hi]
        original = source[lo:hi]
        if len(decoded) != len(original) or np.std(original) < .0001:
            continue
        correlations.append(float(np.corrcoef(decoded, original)[0, 1]))
        errors.append(float(np.sqrt(np.mean((decoded-original)**2))))
    assert len(correlations) >= 3 and min(correlations) > .90, correlations
    # Music alone carries the exact speech duck. Reconstruct the un-ducked
    # envelope from its composition recipe and compare gain inside/outside speech.
    from engine.music.film import duck_envelope
    envelope = duck_envelope(np.arange(1, movie['frames'][1]+1), speech, 24)
    assert abs(envelope.min()-10**(-12/20)) < 1e-8 and envelope.max() == 1
    # Independently separate known speech and music in the final AAC via least
    # squares. The coefficient on the UN-ducked score must be near -12 dB.
    voice_track = np.zeros(len(source))
    for strip in voices:
        with wave.open(strip['path']) as wav:
            voice = np.frombuffer(wav.readframes(wav.getnframes()), '<i2').astype(float)/32768
        start = round((strip['frames'][0]-1+strip['offset'])/24*48000)
        count = min(len(voice), len(voice_track)-start,
                    round((strip['frames'][1]-strip['frames'][0]+1)/24*48000))
        voice_track[start:start+count] += voice[:count]
    sample_frames = np.arange(len(source))/48000*24+1
    duck = duck_envelope(sample_frames, speech, 24)
    mask = (duck < .252) & (np.abs(voice_track) > .002)
    design = np.column_stack((voice_track[mask], source[mask]/duck[mask]))
    coefficients = np.linalg.lstsq(design, audio[:len(source)][mask], rcond=None)[0]
    assert .18 < coefficients[1] < .33, coefficients
    evidence = dict(scene=result, inspected=inspection['result'], film=movie, cut_frame=cut_frame,
                    decoded_samples=len(audio), rate=rate, aac_correlations=correlations,
                    aac_rmse=errors, cut_rms=float(np.sqrt(np.mean(window**2))),
                    cut_max_delta=float(np.max(abs(np.diff(window)))), duck_gain=float(envelope.min()),
                    decoded_voice_gain=float(coefficients[0]), decoded_music_duck_gain=float(coefficients[1]))
    (ROOT/'output/music_integration.json').write_text(json.dumps(evidence, indent=2)+'\n')
    print('MUSIC E2E OK | auto sad | cut/title accents | -12 dB duck | replace/clear/save/open | 2-scene AAC continuous', flush=True)
