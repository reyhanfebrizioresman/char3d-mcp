"""Pure tone/parameter/cost checks. No Blender, network or asset downloads."""
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.materials import FABRICS, TONES, age_years, cost_factor, fabric_kind, options, skin_profile, srgb_to_linear, luminance, iris_color, look_albedo_gain


def main():
    for name, tone in TONES.items():
        p = skin_profile(tone['color'])
        assert 0 < p['radius'][2] < p['radius'][1] < p['radius'][0]
        assert .0005 < p['scale'] < .002
        assert 0 < p['sss'] < .25
        assert .15 < p['specular'] < .4
        assert .4 < p['roughness'] < .6, name
    # Smooth interpolation at both tone boundaries; no discrete ethnicity switch.
    for y in (.065, .22, .48):
        a = skin_profile([y-1e-7]*3)
        b = skin_profile([y+1e-7]*3)
        for key in ('sss', 'scale', 'roughness', 'redness'):
            assert abs(a[key]-b[key]) < 1e-5, (key, a, b)
    young = skin_profile([.3]*3, age=8)
    elder = skin_profile([.3]*3, age=80)
    assert young['pore_distance'] < elder['pore_distance']
    assert elder['roughness'] > young['roughness']
    assert skin_profile([.3]*3, detail=0)['pore_distance'] == 0
    # Strong normalization must never invert light/medium tone ordering.
    previous = -1
    for i in range(1, 1001):
        rgb = [i/1000]*3
        profile = skin_profile(rgb)
        actual = luminance([c*t*profile['albedo_gain'] for c,t in zip(rgb,profile['albedo_tint'])])
        assert actual > previous
        assert abs(actual-profile['albedo_luminance']) < 1e-10
        previous = actual
    dark = skin_profile([.04]*3)
    fair = skin_profile([.6795426,.4286905,.2831488])
    assert dark['albedo_gain'] == 1 and .1 < fair['albedo_gain'] < .2
    for preset in ('golden_hour','night','misty_morning','studio_film'):
        assert look_albedo_gain(dark,dict(preset=preset,intensity=1)) == 1
        assert look_albedo_gain(fair,dict(preset=preset,intensity=0)) == fair['albedo_gain']
        assert fair['albedo_gain'] <= look_albedo_gain(fair,dict(preset=preset,intensity=1)) <= fair['albedo_ceiling']
    brown = iris_color([.0648,.00368,.000304])
    assert 0 < brown[2] < brown[1] < brown[0] < .08
    assert brown[0]/brown[1] < 2.5
    blue = iris_color([.02,.08,.4], brown=False)
    assert blue[2] > blue[1] > blue[0]
    assert options()['quality'] == 'enhanced'
    assert abs(srgb_to_linear([.5]*3)[0]-.21404114) < 1e-7
    assert [age_years(v) for v in (0,.1875,.5,1)] == [1,11,25,90]
    assert options(skin_tone='dark')['skin_tone'] == 'dark'
    assert options(skin_tone=[.2,.1,.05])['skin_tone'] == [.2,.1,.05]
    invalid = [dict(quality='cinematic'), dict(skin_tone='orange'), dict(skin_tone=[1,2,3]),
               dict(skin_tone=[.1,.2]), dict(skin_tone=True), dict(skin_detail=-1),
               dict(hair_detail=3), dict(skin_detail=math.nan), dict(hair_detail=math.inf),
               dict(skin_detail=True)]
    for args in invalid:
        try:
            options(**args)
        except ValueError:
            pass
        else:
            raise AssertionError(args)
    names = {'cotton':'polo_shirt','denim':'blue_jeans','wool':'wool_pants',
             'knit':'fisherman_sweater','silk':'satin_dress','leather':'ankle_boots'}
    for kind, name in names.items():
        assert fabric_kind(name) == kind
        assert 0 < FABRICS[kind]['bump'] < .0002
    assert cost_factor(0,10,'BLENDER_EEVEE') == 1
    assert cost_factor(10,10,'BLENDER_WORKBENCH') == 1
    assert cost_factor(10,10,'BLENDER_EEVEE','clay') == 1
    assert cost_factor(10,10,'BLENDER_EEVEE','anime') == 1
    assert 1 < cost_factor(5,10,'BLENDER_EEVEE') < 1.25
    assert cost_factor(10,10,'CYCLES','film') == 1.15
    assert cost_factor(10,10,'BLENDER_EEVEE','anime',.5) == 1.075
    from engine.script_plan import parse_script
    for material in ('mpfb', 'enhanced'):
        plan = parse_script(dict(characters=[dict(id='A',materials=material)], beats=[dict(say='A',text='Halo')]))
        assert plan['characters'][0]['materials'] == material
    print('MATERIALS UNIT OK')


if __name__ == '__main__':
    main()
