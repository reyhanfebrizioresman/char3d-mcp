"""Pure style grammar/performance tests; no Blender or downloaded assets."""
import copy
import json
import math
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.face_life import score, intensity, pulse
from engine.filmstyle import style_name, palette, LIGHT_MASSES
from engine.script_plan import parse_script
from engine.film_plan import parse_film


def main():
    assert all(style_name(v) == 'animated_film' for v in ('animated_film', 'film_animasi', 'animasi'))
    assert LIGHT_MASSES[0] == (0, 0)  # Never introduce a glowing night floor.
    assert all(a[0] < b[0] and a[1] < b[1] for a, b in zip(LIGHT_MASSES, LIGHT_MASSES[1:]))
    assert palette('night')[1][2] > palette('night')[1][0]
    assert palette('golden_hour')[1][0] > palette('golden_hour')[1][2]
    assert palette('night') != palette('misty_morning') != palette('golden_hour')
    for header in ('GAYA', 'STYLE'):
        p = parse_script(f'{header}: animasi\nANA: Halo!')
        assert p['style'] == 'animated_film' and len(p['characters']) == 1
        assert parse_script(f'{header}: animasi\nANA: Halo!', style='none')['style'] == 'none'
    assert 'style' not in parse_script('ANA: Halo!')
    film = parse_film('GAYA: animasi\nANA (perempuan, 28)\nADEGAN 1: Taman\nANA: Halo!\nADEGAN 2: Rumah\nSTYLE: film\nANA: Hmm.')
    assert [s['plan']['style'] for s in film['scenes']] == ['animated_film', 'film']
    assert all(s['plan']['style'] == 'clay' for s in parse_film(film_to_source(), style='clay')['scenes'])
    words = [('Mama', 10, 20), ('bawa', 25, 35), ('peta.', 40, 50), ('Hebat!', 68, 85)]
    emotions = [dict(frames=[5, 90], emotion='joy', strength=.6)]
    others = [([('Mungkin?', 105, 130), ('bersama!', 140, 170)],
               [dict(frames=[100, 180], emotion='thinking', strength=.5)])]
    state = random.getstate()
    args = dict(start=1, end=192, fps=24, words=words, emotions=emotions,
                listeners=others, cuts=[64, 128], turns=[102], seed=17)
    source = copy.deepcopy(args)
    first = score(**args)
    assert score(**args) == first and args == source and state == random.getstate()
    assert score(**{**args, 'seed': 18}) != first
    assert first['reactions'] and first['holds'] and first['blinks']
    authored = [b['frame'] for b in first['blinks']]
    combined = score(**args, existing_blinks=authored)
    assert not combined['blinks']
    assert not score(**args, blink=False)['blinks']
    assert all(math.isfinite(v) and abs(v) <= 2 for _, values in first['frames'] for v in values.values())
    for f, values in first['frames']:
        if any(a-.15*24 <= f <= b+.22*24 for _, a, b in words):
            assert all(v == 0 for k, v in values.items() if k.startswith(('jaw', 'mouth')))
        assert not any(k in values for k in ('p_b_m_21', 'mouthClose', 'mouthFunnel', 'mouthPucker'))
    zero = score(**args, amount=0)
    assert all(v == 0 for _, values in zero['frames'] for v in values.values())
    double = score(**args, amount=2)
    for (_, a), (_, b) in zip(first['frames'], double['frames']):
        assert all(abs(b[k]-2*v) < 1e-12 for k, v in a.items())
    assert pulse(10, 10, 4, 5) == 1 and pulse(0, 10, 4, 5) == 0
    for value in (-1, 2.01, float('nan'), float('inf')):
        try: intensity(value)
        except ValueError: pass
        else: raise AssertionError(value)
    for value in ('bad', None, 3):
        try: style_name(value)
        except ValueError: pass
        else: raise AssertionError(value)
    # Emotion changes blink spacing without any global RNG or mouth changes.
    calm = score(1, 600, 24, emotions=[dict(frames=[1, 600], emotion='sad')])
    fear = score(1, 600, 24, emotions=[dict(frames=[1, 600], emotion='fear')])
    assert len(fear['blinks']) > len(calm['blinks'])
    json.dumps(first, allow_nan=False)
    print('FILMSTYLE UNIT OK')


def film_to_source():
    return dict(characters=[{'id': 'Ana'}], scenes=[{'beats': [{'say': 'Ana', 'text': 'Halo'}]},
                                                  {'style': 'film', 'beats': [{'say': 'Ana', 'text': 'Ya'}]}])


if __name__ == '__main__': main()
