"""Offline MP4/PNG inspection in the existing MCP Python (PyAV/numpy)."""
import json
import math
import os
from pathlib import Path
import time
import wave
import numpy as np
from .review import issue, score, sound_checks, audio_metrics, report_text


def write_wav(path, samples):
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((samples.shape[1], 2, 48000, 0, 'NONE', 'not compressed'))
        wav.writeframes(np.round(np.clip(samples, -1, 1)*32767).astype('<i2').tobytes())


def audio_segments(samples, lines, directory, fps=24, first=1):
    result = []
    for i, line in enumerate(lines):
        if not line.get('text'):
            continue
        a = max(0, round((line['start']-first)/fps*48000))
        b = min(len(samples), round((line['end']+1-first)/fps*48000))
        if b <= a:
            continue
        path = str(Path(directory)/f'asr_{i:03d}.wav')
        write_wav(path, samples[a:b])
        result.append(dict(path=path, text=line['text'], frame=line['start'], character=line.get('speaker')))
    return result


def review_video(path, lines=None):
    import av
    started = time.perf_counter(); path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    output = path.parent/(path.stem+'_review'); output.mkdir(exist_ok=True)
    # Separate streams so decoding one never consumes the other stream's packets.
    observations, black, frozen = [], [], []
    vstart, vend, frame_count, last, run, blackrun = None, 0., 0, None, None, None
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type=='video'), None)
        if stream is None:
            raise ValueError('File has no video stream')
        fps = float(stream.average_rate or 24)
        for frame in container.decode(stream):
            t = float(frame.pts*frame.time_base) if frame.pts is not None else frame_count/fps
            if vstart is None:
                vstart = t
            vend = t+1/fps; frame_count += 1
            rgb = frame.reformat(width=96, height=54, format='rgb24').to_ndarray().astype(np.float32)/255
            y = rgb @ np.array([.2126,.7152,.0722])
            observations.append(dict(time=round(t,4), mean=float(y.mean()), color=rgb.mean(axis=(0,1)).tolist()))
            if np.mean(y < .025) > .98:
                if blackrun is None: blackrun = t
            elif blackrun is not None:
                if t-blackrun >= .25: black.append([blackrun,t])
                blackrun = None
            delta = float(np.mean(abs(rgb-last))) if last is not None else 1
            if delta < .0003:
                if run is None: run = t-1/fps
            elif run is not None:
                if t-run > 4: frozen.append([run,t])
                run = None
            last = rgb
    if blackrun is not None and vend-blackrun >= .25: black.append([blackrun,vend])
    if run is not None and vend-run > 4: frozen.append([run,vend])
    chunks, astart, aend = [], None, 0.
    audio_gaps=[];audio_cursor=None
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type=='audio'), None)
        if stream:
            resampler = av.AudioResampler(format='fltp', layout='stereo', rate=48000)
            for frame in container.decode(stream):
                if astart is None:
                    astart = float(frame.pts*frame.time_base) if frame.pts is not None else 0.
                for converted in resampler.resample(frame):
                    data=converted.to_ndarray().T
                    at=float(converted.pts*converted.time_base) if converted.pts is not None else (audio_cursor or astart or 0.)
                    if audio_cursor is not None and at-audio_cursor>.05:
                        audio_gaps.append([audio_cursor,at])
                    chunks.append((at,data));audio_cursor=at+len(data)/48000
            for converted in resampler.resample(None):
                data=converted.to_ndarray().T
                at=float(converted.pts*converted.time_base) if converted.pts is not None else (audio_cursor or astart or 0.)
                chunks.append((at,data));audio_cursor=at+len(data)/48000
    aend=max((at+len(data)/48000 for at,data in chunks),default=0.)
    origin=vstart or 0.
    samples=np.zeros((max(0,round((aend-origin)*48000)),2),np.float32)
    for at,data in chunks:
        offset=round((at-origin)*48000);trim=max(0,-offset);start=max(0,offset)
        count=min(len(data)-trim,len(samples)-start)
        if count>0:samples[start:start+count]=data[trim:trim+count]
    metrics = audio_metrics(samples); issues = sound_checks(metrics)
    if not chunks:
        issues.append(issue('missing_audio', 'sound', 'warn', 'The rendered file has no audio stream.'))
    if chunks and abs((vend-(vstart or 0))-len(samples)/48000) > max(.15, 2/fps):
        issues.append(issue('av_duration', 'continuity', 'error', 'Audio and picture durations differ.',
                            dict(video_s=vend-(vstart or 0),audio_s=len(samples)/48000)))
    for a,b in audio_gaps:
        issues.append(issue('audio_timestamp_gap','sound','error','Audio timestamps contain an unencoded gap.',dict(seconds=round(b-a,4)),time=round(a,4)))
    for a,b in black:
        issues.append(issue('black_frames', 'readability', 'warn', 'A near-black interval needs visual review (it may be an intended fade).', dict(seconds=round(b-a,3)), time=round(a,3)))
    for a,b in frozen:
        issues.append(issue('frozen_frames', 'performance', 'warn', 'Decoded picture barely changes for more than four seconds.',dict(seconds=round(b-a,3),mae_threshold=.0003), time=round(a,3)))
    if len(samples):
        hop = 4800; n = len(samples)//hop
        rms = np.sqrt(np.mean(samples[:n*hop].reshape(n,hop,2)**2,axis=(1,2)))
        quiet = rms < 10**(-65/20)
        spans = []; begin = None
        for i,on in enumerate([*quiet,False]):
            if on and begin is None: begin=i
            if not on and begin is not None:
                a,b=begin/10,i/10
                if b-a>=.3 and a>.1 and b < len(samples)/48000-.1: spans.append([a,b])
                begin=None
        for a,b in spans:
            expected = any((l['start']-1)/fps < b and (l['end']-1)/fps > a for l in (lines or []))
            issues.append(issue('audio_dropout','sound','warn' if expected else 'info',
                                'Near-zero audio inside the file; compare with the intended silence map.',dict(seconds=b-a,overlaps_speech=expected),time=a))
    total, scores = score(issues)
    report = dict(kind='video',path=str(path),score=total,scores=scores,issues=issues,audio=metrics,
                  frames=frame_count,video_duration_s=round(vend-(vstart or 0),4),audio_duration_s=round(len(samples)/48000,4),
                  contact_sheet=None,strips=[],limits=['Decoded-file measurements; no cast, geometry or licence inference from pixels',
                  'Near-black/frozen/dropout intervals can be deliberate; LUFS/true peak are approximate'],timings=dict(total=round(time.perf_counter()-started,4)))
    if lines:
        report['asr_segments'] = audio_segments(samples,lines,output,fps)
    report['report_md'] = str(output/'review.md')
    Path(report['report_md']).write_text(report_text(report),encoding='utf-8')
    (output/'review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    import sys
    mode, input_path, output_path = sys.argv[1:4]
    spec=json.loads(Path(input_path).read_text())
    result=review_video(**spec)
    Path(output_path).write_text(json.dumps(result),encoding='utf-8')
