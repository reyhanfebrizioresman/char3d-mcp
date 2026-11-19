"""Reproducible offline F5/Piper comparison, then Whisper-tiny quality measurements.

Only installed models are used. Run with .venv/bin/python tests/audio2_demos.py.
F5 worker is closed BEFORE loading Whisper to bound resident RAM.
"""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
from providers.tts import TTS, audio
from providers.tts.f5 import BUILTINS
from engine.music.dsp import loudness, true_peak

SENTENCES = [
    'Selamat pagi. Apa kabar hari ini?',
    'Saya senang bisa bertemu dengan kalian.',
    'Tolong buka pintu dan tutup jendela itu.',
    'Ibu membeli lima buah mangga di pasar.',
    'Kita akan berangkat setelah hujan berhenti.',
    'Jangan lupa membawa buku dan pensil.',
    'Terima kasih atas bantuan yang sangat berarti.',
    'Di mana kamu menyimpan kunci rumah?',
    'Mereka bermain bersama di taman sore ini.',
    'Semoga perjalanan kita berjalan dengan lancar.',
]


def checkpoint(path, value):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')
    os.replace(temporary, path)


def wer(expected, actual):
    tokenize = lambda s: re.findall(r'\w+', s.lower())
    ref, hyp = tokenize(expected), tokenize(actual)
    row = list(range(len(hyp)+1))
    for i, a in enumerate(ref, 1):
        nxt = [i]
        for j, b in enumerate(hyp, 1):
            nxt.append(min(nxt[-1]+1, row[j]+1, row[j-1]+(a != b)))
        row = nxt
    return row[-1], len(ref)


def main():
    folder = ROOT/'output/voice_demos_f5'
    folder.mkdir(parents=True, exist_ok=True)
    measure_only = '--measure-only' in sys.argv
    if not measure_only or not (folder/'settings.json').exists():
        (folder/'settings.json').write_text(json.dumps(dict(
            steps=int(os.environ.get('CHAR3D_F5_STEPS','32')),
            threads=int(os.environ.get('CHAR3D_F5_THREADS','2')),
            quantize=os.environ.get('CHAR3D_F5_QUANTIZE','0'),
            whisper='tiny, CPU int8, beam_size=5, local_files_only, Indonesian',
            notes='Synthetic Piper references; F5 base and Piper reference restrictions apply.'), indent=2)+'\n')
    manifest = folder/'metrics.json'
    results = json.loads(manifest.read_text()) if manifest.is_file() else {}
    service = TTS(ROOT/'output')
    generated = 0
    batch_limit = int(os.environ.get('CHAR3D_F5_BENCH_BATCH', '0'))
    class BatchComplete(Exception):
        pass
    try:
        if measure_only:
            raise BatchComplete()
        for name, cfg in BUILTINS.items():
            results.setdefault(name, [])
            existing = {r['index']: r for r in results[name]}
            for index, text in enumerate(SENTENCES, 1):
                if batch_limit and generated >= batch_limit:
                    raise BatchComplete()
                record = existing.get(index, dict(index=index, text=text))
                for engine in ('piper', 'f5'):
                    target = folder/f'{name}_{index:02d}_{engine}.wav'
                    if target.is_file() and engine in record:
                        continue
                    start = time.perf_counter()
                    result = service.synthesize(text, engine=engine,
                        voice=f'f5:{name}' if engine == 'f5' else 'piper:id_ID-news_tts-medium',
                        pitch=0 if engine == 'f5' else cfg['pitch'], rate=cfg.get('rate', 1.) if engine == 'piper' else 1.)
                    if engine == 'f5':
                        generated += 1
                    elapsed = time.perf_counter()-start
                    shutil.copyfile(service.workspace/'imports'/result['path'], target)
                    x, rate = audio.read(target)
                    stereo = np.column_stack((x, x))
                    # Meter mono as one channel (stereo duplication would add 3 LU).
                    measured_lufs = loudness(stereo)-3.0103
                    record[engine] = dict(path=str(target), duration_s=len(x)/rate,
                        f0_hz=round(audio.median_f0(x, rate), 2), rms=float(np.sqrt(np.mean(x*x))),
                        lufs=round(measured_lufs, 3), true_peak_dbfs=round(20*np.log10(max(true_peak(stereo), 1e-12)), 3),
                        clipping_samples=int(np.sum(abs(x) >= .999)), elapsed_s=round(elapsed, 3),
                        real_time_factor=round(elapsed/(len(x)/rate), 3), cached=result['cached'],
                        inference=result.get('inference'))
                    print(name, index, engine, json.dumps(record[engine]), flush=True)
                existing[index] = record
                results[name] = list(existing.values())
                checkpoint(manifest, results)
    except BatchComplete:
        if not measure_only:
            print('F5 BENCH BATCH COMPLETE; rerun to resume', flush=True)
            return
    finally:
        service.close()
    from faster_whisper import WhisperModel
    model = WhisperModel('tiny', device='cpu', compute_type='int8', local_files_only=True, cpu_threads=2)
    for name, records in results.items():
        for record in records:
            for engine in ('piper', 'f5'):
                measured = record[engine]
                if 'wer' not in measured:
                    x, sr = audio.read(measured['path'])
                    x = audio.resample(x, round(len(x)*16000/sr)).astype(np.float32)
                    segments, _ = model.transcribe(x, language='id', beam_size=5, vad_filter=False,
                                                   condition_on_previous_text=False)
                    transcript = ' '.join(s.text.strip() for s in segments)
                    errors, words = wer(record['text'], transcript)
                    measured.update(transcript=transcript, word_errors=errors, word_count=words, wer=errors/words)
                    print('ASR',name,record['index'],engine,measured['wer'],transcript,flush=True)
            checkpoint(manifest, results)
    summary = {}
    for name, records in results.items():
        summary[name] = {}
        for engine in ('piper','f5'):
            entries = [r[engine] for r in records]
            summary[name][engine] = dict(sentences=len(entries),
                wer=sum(e['word_errors'] for e in entries)/sum(e['word_count'] for e in entries),
                median_elapsed_s=float(np.median([e['elapsed_s'] for e in entries])),
                median_cpu_s=float(np.median([e['inference']['cpu_seconds'] for e in entries])) if engine == 'f5' else None,
                median_rtf=float(np.median([e['real_time_factor'] for e in entries])),
                f0_range=[min(e['f0_hz'] for e in entries),max(e['f0_hz'] for e in entries)],
                max_peak_dbfs=max(e['true_peak_dbfs'] for e in entries),
                clipping_samples=sum(e['clipping_samples'] for e in entries))
    checkpoint(folder/'summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)

if __name__ == '__main__':
    main()
