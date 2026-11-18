"""Pure Python cinematic contract (no bpy, network or assets)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.cinematic import PRESETS, COST, resolve, look_spec, cost_factor, preset_name
from engine.script_plan import parse_script
from engine.render_metrics import frame_times, progress_cursor
import math


def main():
    for name in PRESETS:
        cfg = resolve(name)
        assert cfg['preset'] == name and cfg['dof'] == 'auto'
        assert 1 <= cost_factor(cfg, 'BLENDER_EEVEE') <= 2
        assert cost_factor(cfg, 'BLENDER_WORKBENCH') == 1
        assert cost_factor(resolve(name, intensity=0), 'BLENDER_EEVEE') == 1
        assert look_spec(cfg) == cfg
        assert resolve(name)['particles']['kind'] == ('dust' if name == 'dreamy' else 'none')
    assert set(COST) == {*PRESETS, 'none'}
    for alias, name in [('senja', 'sunset'), ('matahari terbenam', 'sunset'),
                        ('pagi berkabut', 'misty_morning'), ('malam', 'night'),
                        ('mimpi', 'dreamy'), ('epik', 'epic'), ('JAM EMAS', 'golden_hour')]:
        assert preset_name(alias) == name
        for header in ('SUASANA', 'LOOK', 'MOOD'):
            p = parse_script(f'{header}: {alias}\nANA: Halo!')
            assert p['look']['preset'] == name
            assert parse_script(p)['look'] == p['look']
    base = parse_script('ANA: Halo!')
    assert base['look'] is None and base['recommended_look'] == 'studio_film'
    assert parse_script('LOKASI: taman\nANA: Halo!')['recommended_look'] == 'golden_hour'
    assert parse_script('LOOK: malam\nANA: Halo!', look='senja')['look']['preset'] == 'sunset'
    assert parse_script('LOOK: malam\nANA: Halo!', look='none')['look']['preset'] == 'none'
    assert look_spec(None) is None and cost_factor(None, 'BLENDER_EEVEE') == 1
    assert resolve(clear=True)['preset'] == 'none'
    cfg = resolve('golden_hour', intensity=.5, haze=.012, god_rays=False, bloom=.2,
                  dof=False, particles={'kind': 'petals', 'count': 18, 'seed': 3},
                  sun={'elevation': 8, 'azimuth': 220}, grade={'contrast': 1.2, 'grain': .001})
    assert cfg['rays'] == 0 and cfg['dof'] == 'off' and cfg['azimuth'] == 220
    assert cfg['grade']['contrast'] == 1.2 and cfg['particles']['count'] == 18
    assert cfg == look_spec(cfg)
    for bad in [dict(preset='oops'), dict(intensity=float('nan')), dict(intensity=True),
                dict(intensity=-.1), dict(haze=.2), dict(bloom=4), dict(god_rays=-1),
                dict(dof='face'), dict(particles={'seed': -1}), dict(particles={'count': 5000}),
                dict(particles={'kind': 'rain'}), dict(particles={'surprise': 1}),
                dict(sun={'elevation': 100}), dict(sun={'azimuth': float('inf')}),
                dict(sun={'color': [1, 0, 0]}), dict(grade={'contrast': -1}),
                dict(grade={'teal_orange': 3}), dict(grade={'arbitrary': 1})]:
        try:
            resolve(**bad)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)
    # Overrides must never mutate shared defaults or the caller's dictionaries.
    resolve('dreamy', grade={'exposure': .5}, particles={'seed': 8})
    assert 'exposure' not in resolve('dreamy')['grade']
    assert resolve('dreamy')['particles']['seed'] == 17
    modern = '\n'.join(f'{stamp}  render | Video append frame {i+1}' for i,stamp in enumerate(
        ['00:39.250','00:54.230','01:08.789','01:23.093']))
    assert all(math.isclose(a,b,abs_tol=1e-6) for a,b in zip(frame_times(modern),[39.25,14.98,14.559,14.304]))
    assert progress_cursor(modern)==5
    legacy='Fra: 7 Mem: 10M\nTime: 00:12.34\nFra: 8\nTime: 01:02:03.45'
    assert frame_times(legacy)==[12.34,3723.45] and progress_cursor(legacy)==8
    assert frame_times('Time: ...\nTime: 00:01.0')==[1.0]
    assert frame_times('not rendered')==[] and progress_cursor('not rendered') is None
    print('CINEMATIC UNIT OK')


if __name__ == '__main__':
    main()
