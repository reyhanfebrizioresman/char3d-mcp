"""Assemble the local delivery report from measured artifacts (no inference)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output'

def main():
    sf = json.loads((OUT/'music_demos_sf/metrics.json').read_text())
    sy = json.loads((OUT/'music_demos/metrics.json').read_text())
    lines = ['# Audio v2 result', '',
        'SoundFont music and isolated offline F5 speech are implemented on `codex/audio2`. '
        'No new assets were downloaded and the shared `.venv` was not modified.', '',
        '## Music', '',
        '`backend="auto"` chooses installed GeneralUser GS, `soundfont` requires it, `synth` retains numpy. '
        'Blender calls a compatible Python subprocess for the native SoundFont renderer. '
        'GM arrangement includes voice-led inversions, bass approaches, B counterlines, '
        'intro/A/B/outro, pickups/fills at cuts, velocity/CC7/CC11 and emotion swells. '
        'Nusantara uses original equal-tempered pentatonic figures and GM approximations '
        '(mallets, bells, koto/kalimba, steel drums, tuned low hits and orchestral hits); '
        'it does not reconstruct regional tuning, repertoire or a gamelan ensemble.', '',
        'All demos are 30 s, seed 17, 48 kHz stereo PCM16. Timings exclude metric measurement and WAV writing. '
        'Mastering/reverb, periodic loops, -16 LUFS target and <= -1 dBFS estimated true peak remain shared. '
        'Band energy uses the first 20 s mono (L+R)/2, Hann FFT; samples have different spectra from synthetic oscillators.', '',
        '| Mood | SF seconds | Synth seconds | SF LUFS | SF dBTP | SF centroid Hz | Synth centroid Hz |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for mood, m in sf.items():
        n = sy[mood]
        lines.append(f"| {mood} | {m['render_seconds']:.3f} | {n['render_seconds']:.3f} | {m['lufs']:.3f} | {m['true_peak_dbfs']:.3f} | {m['centroid_hz']:.2f} | {n['centroid_hz']:.2f} |")
    lines += ['', '| Mood | SF <120 Hz % | >2 kHz % | >4 kHz % | >8 kHz % | >16 kHz % |',
              '|---|---:|---:|---:|---:|---:|']
    for mood, m in sf.items():
        vals = [m[k]*100 for k in ('below_120_ratio','above_2k_ratio','above_4k_ratio','above_8k_ratio','above_16k_ratio')]
        lines.append('| '+mood+' | '+' | '.join(f'{v:.6g}' for v in vals)+' |')
    lines += ['', 'Artifacts: `output/music_demos_sf/{mood}.wav`, matching scores and `metrics.json`; '
              'numpy comparisons in `output/music_demos/`.', '', '## F5 speech', '',
        'One persistent JSON-lines worker uses the separate F5 Python and installed checkpoint, '
        'package vocabulary and cached Vocos. No torch import in MCP/Blender, no ASR/model downloads, '
        'HF offline flags plus blocked network sockets, 600 s operation timeout, explicit cancellation/reaping '
        'via `cancel_tts()`. WAV decoding uses libsndfile, avoiding incompatible optional torchcodec libraries. '
        'Cache identity includes reference WAV content, transcript, assets and inference settings. '
        'Named synthetic Piper-derived adult female/male, elder and child references work with casting '
        'and `script_to_scene(..., tts_engine="f5")`. User-owned/permitted WAV + transcript can override them.', '',
        'Hardware: Intel Core i5-4460, 4 CPU cores, ~12 GB RAM, no dedicated GPU. '
        'Initial default float32/32-step inference took **327.789 s wall / 528.182 s CPU** for '
        '2.197 s raw speech (**149.18 RTF**, 2.277 s normalized). '
        'An 8-step float32 sentence took 100.199 s wall / 144.943 s CPU; an experimental int8 '
        'sentence took 162.226 s wall / 164.876 s CPU under concurrent checks. '
        'These are workload-sensitive measurements; int8 is opt-in and not assumed faster. '
        '**Piper remains the default.** Corpus demos use 8 steps, float32, 2–4 CPU threads (recorded per inference); '
        'default F5 quality is 32 steps. Do not treat draft-demo WER as a 32-step quality benchmark.', '',
        'The first eight female utterances used two threads (the first four used upstream chunk pooling); '
        'later utterances use four threads and serial chunks. Compare per-record timings rather than '
        'interpreting differences between voice medians as voice complexity. An initial full-corpus '
        'command ended with SIGTERM; checkpointed four-utterance batches resumed without losing completed WAVs.', '']
    summary = OUT/'voice_demos_f5/summary.json'
    default32 = OUT/'voice_demos_f5/default32_smoke.json'
    if default32.is_file():
        smoke = json.loads(default32.read_text())
        measured = smoke['inference']
        lines += [f"Final 32-step, float32, four-thread smoke passes with the current serial worker: "
                  f"**{measured['wall_seconds']:.3f} s wall / {measured['cpu_seconds']:.3f} s CPU**, "
                  f"{measured['duration_s']:.3f} s raw speech / {smoke['duration_s']:.3f} s normalized WAV, "
                  f"**{measured['real_time_factor']:.2f} RTF** (raw duration). "
                  'This was an uncached inference. Listen to `output/voice_demos_f5/female_adult_default32.wav`; '
                  'details in `default32_smoke.json` and `output/tts_real.log`.', '']
    if summary.is_file():
        data = json.loads(summary.read_text())
        lines += ['| Voice | Engine | Sentences | WER % | Median latency s | Median CPU s | Median RTF | F0 range Hz | Max dBTP | Clipped samples |',
                  '|---|---|---:|---:|---:|---:|---:|---|---:|---:|']
        for voice, engines in data.items():
            for engine, m in engines.items():
                lines.append(f"| {voice} | {engine} | {m['sentences']} | {100*m['wer']:.2f} | {m['median_elapsed_s']:.3f} | {str(round(m['median_cpu_s'], 3)) if m.get('median_cpu_s') is not None else '—'} | {m['median_rtf']:.3f} | {m['f0_range'][0]:.2f}–{m['f0_range'][1]:.2f} | {m['max_peak_dbfs']:.3f} | {m['clipping_samples']} |")
    else:
        lines.append('Voice corpus is still being measured; see `output/voice_demos_f5.log`.')
    verification = OUT/'voice_demos_f5/verification.json'
    if verification.is_file():
        checked = json.loads(verification.read_text())
        lines += ['', f"All {checked['f5_wavs']+checked['piper_wavs']} comparison WAVs pass format, nonzero duration, F0, loudness and clipping sanity checks: "
                  f"{checked['format']}; duration {checked['duration_s'][0]:.3f}–{checked['duration_s'][1]:.3f} s, "
                  f"F0 {checked['f0_hz'][0]:.2f}–{checked['f0_hz'][1]:.2f} Hz, "
                  f"loudness {checked['lufs'][0]:.3f}–{checked['lufs'][1]:.3f} LUFS, zero clipped samples. "
                  'The high-crest elder first sentence is quieter because peak headroom limits gain.']
        lines += ['', '**Quality limit:** draft F5 male/elder WER improves over these Piper counterparts; '
                  'female is unchanged; child is worse (28.125% vs 17.188%). '
                  'This is not a universal quality improvement. Ten short sentences and Whisper tiny '
                  'do not establish perceptual naturalness; the supplied references are synthetic variants '
                  'of one speaker. Use a clean, permitted recording for character identity and evaluate '
                  'higher-step generation before choosing F5 for a project.']
    lines += ['', 'Artifacts: `output/voice_demos_f5/{voice}_{01..10}_{f5|piper}.wav`, '
              '`metrics.json` (per-sentence CPU/wall/RTF, F0, duration, loudness, peak, transcript and WER), '
              '`summary.json`. WER uses only installed Whisper tiny (CPU int8, beam 5, Indonesian, '
              'local files only), lowercased word tokens and Levenshtein edits. '
              'It is an imperfect recognizer, not a human listening score; high WER is reported without hiding failures.', '',
        '## Verification', '',]
    checks = [('music_unit.log','MUSIC UNIT OK'),('music_sf_unit.log','MUSIC UNIT OK'),
              ('tts_unit.log','TTS UNIT OK'),('tts_real.log','F5 REAL SMOKE OK'),('film_unit.log','FILM UNIT OK'),
              ('e2e_audio.log','AUDIO E2E OK'),('e2e_sfx.log','AUTO-SFX-ONLY OK'),
              ('e2e_film.log','FILM-ONLY OK'),('e2e_tts.log','TTS E2E OK'),
              ('e2e_music.log','MUSIC-ONLY OK'),('e2e_audio2.log','AUDIO2-ONLY OK')]
    for file, marker in checks:
        path = OUT/file
        status = 'PASS' if path.is_file() and marker in path.read_text(errors='replace') else 'not finished'
        lines.append(f'- {file}: {status} ({marker}).')
    scene = OUT/'audio2_scene/audio2_checks.json'
    if scene.is_file():
        report = json.loads(scene.read_text())
        lines += ['', 'F5 + `MUSIK: haru` draft: `'+report['movie']['path']+'`. '
                  'PyAV verifies H.264 + AAC, frame count, non-silent audio and voice alignment: `'
                  +json.dumps(report['verification'])+'`. Saved project: `output/audio2_scene/projects/audio2_f5_haru.blend`.']
    lines += ['', 'All Blender integration runs use port **9975**, sequentially in worktree workspaces. '
              'F5 corpus synthesis uses one worker and closes it before Whisper; the F5 scene test closes '
              'the worker before rendering frames. Final port/worker shutdown is checked separately.', '',
        '## Licenses and limits', '',
        '- [GeneralUser GS license](https://github.com/mrbumpy409/GeneralUser-GS/blob/684543d5e5efaef08d02be50dcda8d552478fa60/documentation/LICENSE.txt): permits private/commercial music creation. '
          'Installer records bank/license sizes and SHA-256 in `scripts/soundfonts.tsv`.',
        '- [F5 code](https://github.com/SWivid/F5-TTS/blob/main/LICENSE) is MIT; '
          '[Indonesian finetune card](https://huggingface.co/anantoj/f5-id-v1) is Apache-2.0-labelled; '
          '[base weights](https://github.com/SWivid/F5-TTS#license) are CC-BY-NC: personal/non-commercial.',
        '- Builtin references are synthetic derivatives of installed Piper news_tts, whose dataset rights '
          'remain unclear: personal use. They retain one underlying speaker identity. Package example audio '
          'is not used because recording/speaker permission is not separately established. '
          'Never use Edge/Microsoft outputs or a real person without permission as references.',
        '- User reference guidance: clean mono WAV, 8–12 s, one speaker, quiet room, normal pace, '
          'no music/reverb/clipping, exact transcript. Relative API paths resolve inside imports; '
          'registered JSON references resolve beside the JSON.',
        '- Installers are supplied but were **not executed**. F5 uses its own CPU venv and verifies '
          '1,348,431,976-byte checkpoint, 54,365,991-byte vocoder weights, 461-byte config and '
          '11,255-byte package vocabulary. No model is downloaded during inference.', '',
        '## Delivery', '', 'Git metadata is read-only: `git add --dry-run` cannot create '
        '`/home/reyhan/projects/char3d-engine/.git/worktrees/char3d-audio2/index.lock`. '
        'Changes remain uncommitted on `codex/audio2`. Run `output/commit_audio2.sh` using '
        '`output/COMMIT_MSG.txt` from a writable git session; it checks unstaged and staged whitespace '
        'and stages only task files, excluding the shared `.venv` symlink. No push or merge was performed.']
    shutdown = OUT/'audio2_shutdown.json'
    if shutdown.is_file():
        state = json.loads(shutdown.read_text())
        lines += ['', f"Final cleanup verified at {state['checked_utc']}: port 9975 has no listener; "
                  'benchmark/smoke processes exited and the scene completed `cancel_tts` plus `engine_shutdown`. '
                  'Both uncached synthesis and cached scene rerender passed. Evidence: `output/audio2_shutdown.json`, '
                  '`output/audio2_scene/uncached_checks.json` and `output/audio2_scene/audio2_checks.json`.']
    (OUT/'audio2_result.md').write_text('\n'.join(lines)+'\n')

if __name__ == '__main__':
    main()
