"""Pure film contracts. No Blender, downloads, audio reads or file writes."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.film_plan import parse_film, transition, layout, is_film, offset_captions
from engine.script_plan import parse_script

SCRIPT = '''JUDUL: Pertemuan Kembali
ANA (perempuan, 28, rambut bob, kasual)
BUDI (laki-laki, 30, rambut pendek, kasual)
ADEGAN 1: Kafe — pagi
LOKASI: cafe_terrace
SUASANA: pagi berkabut
ANA: Halo, Budi!
BUDI: Selamat pagi.
[TRANSISI: dissolve 0.5 detik]
ADEGAN 2: Taman — sore
LOKASI: taman
SUASANA: senja
CUACA: berangin
KARTU: Sore harinya...
[Ana berganti baju formal]
BUDI: Indah sekali.
ANA: Mari pulang.
[TRANSISI: dip_black 0.5 detik]
SCENE 3: Jalan — malam
LOCATION: street
LOOK: night
ANA: Sampai jumpa!
BUDI: Sampai besok.
'''


def main():
    single = 'JUDUL: Lama\nLOKASI: park\nANA (perempuan): Halo!'
    before = parse_script(single)
    assert not is_film(single)
    p = parse_film(SCRIPT, seed=7)
    assert p == parse_film(SCRIPT, seed=7)
    assert json.loads(json.dumps(p)) == p
    assert parse_script(single) == before
    assert len(p['scenes']) == 3
    a, b, c = p['scenes']
    assert [s['environment'] for s in p['scenes']] == ['cafe_terrace', 'park', 'city_street']
    assert [s['look']['preset'] for s in p['scenes']] == ['misty_morning', 'sunset', 'night']
    assert b['weather'] == 'wind' and b['card']['duration_s'] == 2
    assert a['plan']['characters'][0]['outfit'] == 'casual'
    assert b['plan']['characters'][0]['outfit'] == c['plan']['characters'][0]['outfit'] == 'formal'
    assert a['plan']['characters'][1] == b['plan']['characters'][1] == c['plan']['characters'][1]
    assert a['character_seeds'] == b['character_seeds'] == c['character_seeds']
    assert b['segment_start'] == a['film_frames'][1]+1-12
    assert b['film_frames'][0] == b['segment_start']+48
    assert c['segment_start'] == b['film_frames'][1]+1
    assert c['audio_offset_frames'] == c['subtitle_offset_frames'] == c['film_frames'][0]-1
    assert p['estimated_frames'][1] == sum(s['estimated_frames'][1]+s['card_frames'] for s in p['scenes'])-12
    assert not p['warnings'], p['warnings']
    for script in (SCRIPT, {'characters': [{'id':'A'}], 'scenes': []}):
        try:
            parse_script(script)
        except ValueError as e:
            assert 'script_to_film' in str(e)
        else:
            raise AssertionError('Single-scene parser accepted film')
    subset = {'characters': [{'id':'A'}, {'id':'B', 'outfit':'casual'}], 'scenes': [
        {'beats':[{'say':'B','text':'First.'}]},
        {'beats':[{'say':'A','text':'Second.'}]},
        {'beats':[{'do':'outfit','who':'B','outfit':'winter'}, {'say':'B','text':'Third.'}]}]}
    source = copy.deepcopy(subset)
    p = parse_film(subset, seed=8)
    assert subset == source
    assert [s['cast'] for s in p['scenes']] == [['B'], ['A'], ['B']]
    assert p['scenes'][0]['character_seeds']['B'] == p['scenes'][2]['character_seeds']['B'] == 109
    assert p['scenes'][0]['plan']['characters'][0]['outfit'] == 'casual'
    assert p['scenes'][2]['plan']['characters'][0]['outfit'] == 'winter'
    assert transition('fade_white 1 second') == {'kind':'fade_white','duration_s':1}
    for value in ('wipe', 'dissolve -1', {'kind':'crossfade','duration_s':float('nan')}):
        try:
            transition(value)
        except ValueError:
            pass
        else:
            raise AssertionError(value)
    scenes = [{'frames':[1,48], 'transition_in':transition()},
              {'frames':[10,57], 'transition_in':transition('dissolve 1')}]
    assert layout(scenes) == [1,72]
    assert scenes[1]['film_frames'] == [25,72]
    short_dip = [{'frames':[1,4], 'transition_in':transition()},
                 {'frames':[1,4], 'transition_in':transition('dip_black 0.05')}]
    assert layout(short_dip) == [1,8] and short_dip[1]['transition_frames'] == 3
    assert offset_captions([{'start':1,'end':12}],24) == [{'start':25,'end':36}]
    try:
        parse_film(SCRIPT.replace('dissolve 0.5', 'dissolve 10'))
    except ValueError:
        pass
    else:
        raise AssertionError('oversized transition accepted')
    assert parse_film('SCENE: One\nA: First.\nSCENE: Two\nA: Last.')['scenes'][1]['cast'] == ['A']
    assert parse_film('SCENE 1: One\nA (female): First.\nSCENE 2: Two\nA: Last.')['characters'][0]['gender'] == 0
    print('FILM UNIT OK')


if __name__ == '__main__':
    main()
