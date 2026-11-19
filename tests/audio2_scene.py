"""MCP F5 + MUSIK:haru -> clay MP4, with decoded AAC and mix verification."""
import json
import os
from pathlib import Path
import wave

import av
import numpy as np


async def run(call, text_of):
    assert os.environ.get('CHAR3D_PORT') == '9975'
    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[-1])
    await data('scene_info')
    await call('new_scene', frame_end=24)
    script = ('JUDUL: Suara dan Kenangan\nMUSIK: haru\n'
              'ANA (perempuan, 28, rambut bob): Saya senang bisa bertemu dengan kalian.')
    parsed = await data('script_to_scene', script=script, build=False, tts_engine='f5', language='id')
    assert parsed['plan']['music']['mood'] == 'sad' and not parsed['generated_files']
    built = await data('script_to_scene', script=script, tts_engine='f5', language='id',
                       sound=False, body_language=False, subtitles=True)
    assert len(built['generated_files']) == 1, built
    assert built['generated_files'][0]['engine'] == 'f5', built
    assert built['music']['renderer']['backend'] == 'soundfont', built['music']
    strips = (await data('list_audio'))['strips']
    assert {s['kind'] for s in strips} == {'voice', 'music'}, strips
    rig = next(iter(built['characters'].values()))['rig']
    await call('camera_shot', subject=[rig], shot='medium', start_frame=1,
               end_frame=built['frames'][1], name='Audio2VoiceMedium')
    await call('render_preview', camera='scene', engine_name='workbench', width=320, height=180)
    await call('save_project', path='audio2_f5_haru.blend')
    # The speech is baked now; free the F5 model before the frame renderer.
    await data('cancel_tts')
    movie = await data('render_video', path='audio2_f5_haru.mp4', quality='draft',
                       width=320, height=180, wait=True)
    assert movie['status'] == 'done', movie
    with av.open(movie['path']) as clip:
        assert clip.streams.audio[0].codec_context.name == 'aac'
        assert clip.streams.video[0].codec_context.name == 'h264'
        video_frames = clip.streams.video[0].frames
        assert video_frames == built['frames'][1]
    from providers.tts.audio import read
    workspace = Path(os.environ['CHAR3D_WORKSPACE'])
    rendered, rate = read(movie['path'])
    source, _ = read(workspace/'imports'/built['generated_files'][0]['path'])
    line = built['lines'][0]
    expected = round((line['start']-1)/24*rate)
    lo = max(0, expected-round(.12*rate))
    segment = rendered[lo:expected+len(source)+round(.12*rate)]
    nfft = 1 << (len(segment)+len(source)-2).bit_length()
    corr = np.fft.irfft(np.fft.rfft(segment,nfft)*np.fft.rfft(source[::-1],nfft),nfft)
    at = int(np.argmax(corr[len(source)-1:len(segment)]))
    found = segment[at:at+len(source)]
    correlation = float(np.dot(found,source)/np.sqrt(np.dot(found,found)*np.dot(source,source)))
    offset_s = (lo+at-expected)/rate
    assert abs(offset_s) < 1/24 and correlation > .75, (offset_s,correlation)
    assert float(np.sqrt(np.mean(rendered**2))) > .005
    assert built['music']['ducking']['speech_ranges']
    report = dict(build=built, strips=strips, movie=movie,
                  verification=dict(video_frames=video_frames,audio_rate=rate,
                      correlation=correlation,offset_s=offset_s,peak=float(np.max(abs(rendered)))))
    (workspace/'audio2_checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print('AUDIO2 F5/HARU E2E OK',json.dumps(report['verification']),movie['path'],flush=True)
