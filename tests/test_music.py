"""Pure composition/DSP contracts and acoustic checks. No Blender/network/models.

--demos writes 30 seconds of every palette, JSON scores and measured metrics.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.music import (ALIASES, PALETTES, RATE, compose, infer_mood, instrument,
                          loudness, metrics, render, settings, spectral_metrics, true_peak, write_cached)
from engine.music.film import duck_envelope, score_film
from engine.script_plan import parse_script
from engine.film_plan import parse_film


class MusicTests(unittest.TestCase):
    def test_aliases_and_headers(self):
        for alias, canonical in ALIASES.items():
            p = parse_script(f'MUSIK: {alias}\nANA: Halo.')
            if canonical == 'none':
                self.assertIsNone(p['music'])
            elif canonical != 'auto':
                self.assertEqual(p['music']['mood'], canonical)
        p = parse_script('MUSIC: romantic\nANA: Halo.')
        self.assertEqual(parse_script(p)['music'], p['music'])
        self.assertIsNone(parse_script(p, music=None)['music'])
        self.assertEqual(parse_script(p, music='sad')['music']['mood'], 'sad')
        f = parse_film('MUSIK: ceria\nANA (female, 28)\nADEGAN: A\nANA: Hai!\nADEGAN: B\nMUSIC: tanpa\nANA: Oh.')
        self.assertEqual(f['scenes'][0]['music']['mood'], 'happy')
        self.assertIsNone(f['scenes'][1]['music'])
        self.assertIsNone(parse_film(dict(characters=[{'id': 'Ana'}], music='warm', scenes=[
            {'music': None, 'beats': [{'say': 'Ana', 'text': 'Hi.'}]}]))['scenes'][0]['music'])
        self.assertTrue(all(s['music'] is None for s in parse_film(
            'ANA (female, 28)\nSCENE: A\nANA: Hai!\nSCENE: B\nANA: Hai!', music=None)['scenes']))

    def test_context_and_validation(self):
        self.assertEqual(infer_mood(look='golden_hour'), 'warm')
        self.assertEqual(infer_mood(look={'preset': 'night'}), 'mysterious')
        self.assertEqual(infer_mood(weather='rain'), 'nostalgic')
        self.assertEqual(infer_mood([{'text': 'Saya sedih sekali.'}], look='epic'), 'sad')
        self.assertEqual(infer_mood([{'text': 'Saya tidak senang.'}], look='night'), 'mysterious')
        for kwargs in ({'duration': -1}, {'duration': float('nan')}, {'tempo': 0}, {'key': 'H minor'},
                       {'intensity': 1.1}, {'seed': 2.1}, {'mood': 'blah'}, {'sections': [{'frame': -2}]}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                compose(**kwargs)

    def test_grammar_determinism_and_voiceleading(self):
        self.assertLess(len(compose(30, 'epic', intensity=.1)['events']),
                        len(compose(30, 'epic', intensity=.95)['events']))
        for mood in PALETTES:
            s = compose(30, mood, seed=13, cuts=[49, 145], emotions=[{'frame': 192, 'emotion': 'sad', 'strength': .8}])
            self.assertEqual(s, compose(30, mood, seed=13, cuts=[49, 145], emotions=[{'frame': 192, 'emotion': 'sad', 'strength': .8}]))
            self.assertNotEqual(s['events'], compose(30, mood, seed=14)['events'])
            allowed = {(s['tonic']+n) % 12 for n in s['scale']}
            for e in s['events']:
                if e['instrument'] not in ('kick', 'snare', 'rim', 'hat', 'shaker', 'tom', 'frame_drum'):
                    self.assertIn(e['note'] % 12, allowed)
                self.assertTrue(0 <= e['time'] < 30)
            for a, b in zip(s['chords'], s['chords'][1:]):
                self.assertLessEqual(sum(abs(x-y) for x, y in zip(a['notes'], b['notes'])), 24)
            self.assertEqual(s['chords'][-1]['degree'], 0)
            self.assertEqual({e['frame'] for e in s['accents']}, {49, 145})
            self.assertEqual([f['name'] for f in s['sections']], ['intro', 'A', 'B', 'outro'])

    def test_keys_registers_and_orchestration(self):
        self.assertEqual({settings(m, seed=17)['tonic'] for m in PALETTES}, set(range(12)))
        for mood in PALETTES:
            self.assertEqual({settings(mood, seed=s)['tonic'] for s in range(12)}, set(range(12)))
        scores = [compose(20, m, seed=17) for m in PALETTES]
        self.assertGreaterEqual(len({tuple(s['instruments']) for s in scores}), 10)
        self.assertGreater(max(len(s['events']) for s in scores), min(len(s['events']) for s in scores)*2)
        for s in scores:
            self.assertTrue(all(31 <= e['note'] <= 46 for e in s['events'] if e['role'] == 'bass'))
        self.assertEqual(settings('warm', seed=24, key='D minor')['key'], 'D minor')

    def test_spectral_measurement_and_oscillator_folding(self):
        from engine.music.dsp import saw, _bandlimit
        t = np.arange(RATE)/RATE
        x = sum(a*np.sin(2*np.pi*f*t) for a, f in ((.5, 60), (.4, 3000), (.3, 6000), (.2, 11000)))
        m = spectral_metrics(np.column_stack((x, x)))
        for key, power in (('below_120_ratio', .25), ('above_2k_ratio', .29),
                           ('above_4k_ratio', .13), ('above_8k_ratio', .04)):
            self.assertAlmostEqual(m[key], power/.54, delta=1e-5)
        results = {}
        for hz in (1837, 3901, 6599):
            # Integer-cycle tones avoid pitch/window leakage. Energy outside all
            # legal harmonics measures folded aliases INSIDE the audible band.
            freq = np.fft.rfftfreq(RATE, 1/RATE)
            legal = np.zeros(len(freq), bool)
            for harmonic in range(1, int(16000/hz)+1):
                legal |= abs(freq-hz*harmonic) <= 3
            legal[:4] = True
            def folded(signal):
                p = abs(np.fft.rfft(signal*np.hanning(len(signal))))**2
                return float(p[~legal].sum()/p.sum())
            corrected = folded(saw(hz, 1))
            naive = folded(_bandlimit(2*((t*hz) % 1)-1))
            self.assertLess(corrected, 1e-5, (hz, corrected))
            self.assertLess(corrected, naive/100, (hz, corrected, naive))
            results[hz] = dict(polyblep_2x_folded_ratio=corrected, naive_folded_ratio=naive)
        (ROOT/'output/music_review').mkdir(parents=True, exist_ok=True)
        (ROOT/'output/music_review/aliasing.json').write_text(json.dumps(results, indent=2)+'\n')

    def test_pcm_duration_cache_and_loops(self):
        with self.assertRaises(ValueError):
            compose(5, loop=True, tempo=120)
        s = compose(4.125, 'happy', seed=11)
        x = render(s)
        self.assertEqual(x.shape, (198000, 2))
        self.assertTrue(np.array_equal(x, render(s)))
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_cached(x, directory)
            self.assertEqual((path, digest), write_cached(x, directory))
            with wave.open(path, 'rb') as wav:
                self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (48000, 2, 2))
                pcm = wav.readframes(wav.getnframes())
                self.assertEqual(hashlib.sha256(pcm).hexdigest(), digest)
        for mood in ('warm', 'nusantara'):
            s = compose(8, mood, loop=True)
            x = render(s)
            self.assertLess(np.max(np.abs(x[-1]-x[0])), 4e-5)
            edge_rms = np.sqrt(np.mean(np.concatenate((x[:2400], x[-2400:]))**2))
            self.assertGreater(edge_rms, np.sqrt(np.mean(x*x))*.2)
            # Test the actual join, not all sample slopes: legitimate 8–14 kHz
            # percussion/partials can have large adjacent-sample differences.
            joined = np.tile(x, (2, 1))
            self.assertLess(np.max(abs(joined[len(x)]-joined[len(x)-1])), 4e-5)

    def test_loudness_and_pitch(self):
        t = np.arange(RATE)/RATE
        sine = np.tile((.1*np.sin(2*np.pi*1000*t))[:, None], (1, 2))
        self.assertAlmostEqual(loudness(sine), -20, delta=.2)
        self.assertAlmostEqual(true_peak(sine), .1, delta=.0001)
        # FFT peak is measured from rendered timbres, not event metadata.
        for kind in ('piano', 'epiano', 'pad', 'strings', 'bass', 'pluck', 'bell', 'metallophone'):
            x = instrument(kind, 69, 1.5, .5, seed=9)
            self.assertLess(max(abs(x[0]), abs(x[-1])), 1e-7)
            spec = abs(np.fft.rfft(x[4800:]*np.hanning(len(x)-4800)))
            freq = np.fft.rfftfreq(len(x)-4800, 1/RATE)
            peak = freq[np.argmax(spec)]
            self.assertLess(abs(1200*np.log2(peak/440)), 18, (kind, peak))

    def test_acoustic_quality_all_moods(self):
        measured = {}
        for mood in PALETTES:
            score = compose(20, mood, seed=17)
            m = metrics(render(score), score)
            measured[mood] = m
            self.assertAlmostEqual(m['lufs'], -16, delta=.6, msg=(mood, m))
            self.assertLessEqual(m['true_peak_dbfs'], -1, (mood, m))
            self.assertTrue(5 < m['crest_db'] < 23, (mood, m))
            self.assertLess(m['above_16k_ratio'], 2e-7, (mood, m))
            self.assertTrue(350 < m['centroid_hz'] < 5000, (mood, m))
            self.assertGreater(m['key_energy_ratio'], .80, (mood, m))
            self.assertLess(m['tempo_error_pct'], 7, (mood, m))
            self.assertTrue(.005 < m['bass_ratio'] < .65, (mood, m))
            self.assertGreater(m['mid_ratio'], .3, (mood, m))
            self.assertEqual(m['spectral_seconds'], 20)
            self.assertLess(m['below_30_ratio'], .01, (mood, m))
            if mood in ('happy', 'tense', 'epic', 'playful', 'nusantara'):
                self.assertTrue(.15 < m['below_120_ratio'] < .45, (mood, m))
                self.assertTrue(.08 < m['above_2k_ratio'] < .40, (mood, m))
                self.assertGreater(m['above_4k_ratio'], .02, (mood, m))
                self.assertGreater(m['above_8k_ratio'], .003, (mood, m))
            elif mood in ('mysterious', 'dreamy'):
                self.assertGreater(m['above_2k_ratio'], .10, (mood, m))
                self.assertGreater(m['above_4k_ratio'], .025, (mood, m))
                self.assertGreater(m['above_8k_ratio'], .003, (mood, m))
            else:
                self.assertGreater(m['above_2k_ratio'], .03, (mood, m))
                self.assertGreater(m['above_4k_ratio'], .005, (mood, m))
                self.assertGreater(m['above_8k_ratio'], .0007, (mood, m))
        centroids = [m['centroid_hz'] for m in measured.values()]
        self.assertGreater(max(centroids)/min(centroids), 2)
        self.assertGreater(max(centroids)-min(centroids), 900)

    def test_film_continuity_and_duck(self):
        grid = np.arange(1, 241)
        gain = duck_envelope(grid, [[25, 49], [55, 75]], 24)
        self.assertAlmostEqual(gain[30], 10**(-12/20))
        self.assertEqual(gain[52], gain[30])
        scenes = []
        for i, mood in enumerate(('warm', 'warm', 'sad')):
            cfg = dict(settings(mood), seed=0, volume=.35, intensity=.6, fade_in=.1, fade_out=.1)
            scenes.append(dict(score=cfg, frames=[1, 96], segment_start=i*96+1,
                               film_frames=[i*96+1, (i+1)*96], speech=[[25, 49]], score_cuts=[], score_emotions=[]))
        with tempfile.TemporaryDirectory() as directory:
            report = score_film(scenes, 24, 288, directory)
            self.assertEqual(len(report['sections']), 2)
            self.assertEqual(report['sections'][1]['transition'], 'crossfade')
            with wave.open(report['path']) as wav:
                x = np.frombuffer(wav.readframes(wav.getnframes()), '<i2').reshape(-1, 2)/32768
            for seconds in (4, 8):
                at = round(seconds*RATE)
                self.assertGreater(np.sqrt(np.mean(x[at-1200:at+1200]**2)), .0005)
                self.assertLess(np.max(abs(np.diff(x[at-240:at+240], axis=0))), .10)


def demos():
    directory = ROOT/'output/music_demos'
    directory.mkdir(parents=True, exist_ok=True)
    results = {}
    for mood in PALETTES:
        start = time.perf_counter()
        score = compose(30, mood, seed=17)
        x = render(score)
        path, digest = write_cached(x, directory)
        target = directory/f'{mood}.wav'
        shutil.copyfile(path, target)
        os.remove(path)
        with wave.open(str(target), 'rb') as wav:
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), '<i2').reshape(-1, 2)/32768
        results[mood] = dict(path=str(target), hash=digest, **metrics(pcm, score),
                             tempo=score['tempo'], key=score['key'], render_seconds=round(time.perf_counter()-start, 2))
        (directory/f'{mood}.json').write_text(json.dumps(score, indent=2)+'\n')
        print(mood, json.dumps(results[mood]), flush=True)
    (directory/'metrics.json').write_text(json.dumps(results, indent=2)+'\n')


if __name__ == '__main__':
    if '--demos' in sys.argv:
        demos()
    else:
        if not unittest.main(exit=False).result.wasSuccessful():
            sys.exit(1)
        print('MUSIC UNIT OK')
