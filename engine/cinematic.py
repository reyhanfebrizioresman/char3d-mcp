"""Blender-free cinematic vocabulary, validation and render-cost model.

Values are art direction, in meters/degrees/linear color. No scene is touched here.
"""
import copy
import math

PRESETS = {
    'golden_hour': dict(elevation=9, azimuth=220, sun_energy=2.0, sun_color=(1, .69, .38),
        sky_strength=.055, sky_tint=(1, .89, .73), haze=.007, rays=.65, bloom=.10,
        grade=dict(exposure=-.15, contrast=1.09, saturation=1.02, temperature=.08, teal_orange=True)),
    'sunset': dict(elevation=2, azimuth=205, sun_energy=1.2, sun_color=(1, .40, .22),
        sky_strength=.075, sky_tint=(1, .60, .78), haze=.009, rays=.5, bloom=.14,
        grade=dict(contrast=1.07, saturation=.97, tint=.07)),
    'misty_morning': dict(elevation=18, azimuth=135, sun_energy=.8, sun_color=(.87, .94, 1),
        sky_strength=.06, sky_tint=(.73, .87, 1), haze=.018, rays=.35, bloom=.07,
        grade=dict(contrast=.96, saturation=.85, temperature=-.07, lifted_blacks=.008)),
    'blue_hour': dict(elevation=-5, azimuth=220, sun_energy=.20, sun_color=(.42, .61, 1),
        sky_strength=.014, sky_tint=(.12, .23, .65), haze=.006, rays=.35, bloom=.18,
        grade=dict(contrast=1.10, saturation=.94, temperature=-.10)),
    'night': dict(elevation=-12, azimuth=150, sun_energy=.6, sun_color=(.40, .57, 1),
        sky_strength=.006, sky_tint=(.035, .075, .25), haze=.005, rays=.4, bloom=.23,
        grade=dict(contrast=1.12, saturation=.88, temperature=-.09)),
    'overcast_soft': dict(elevation=50, azimuth=140, sun_energy=.35, sun_color=(.9, .95, 1),
        sky_strength=.025, sky_tint=(.72, .82, .94), haze=.003, rays=0., bloom=.035,
        grade=dict(contrast=1.03, saturation=.92)),
    'dreamy': dict(elevation=12, azimuth=210, sun_energy=1.2, sun_color=(1, .80, .68),
        sky_strength=.07, sky_tint=(.88, .75, 1), haze=.010, rays=.4, bloom=.27,
        particles='dust', grade=dict(contrast=.96, saturation=.86, tint=.06, lifted_blacks=.016)),
    'epic': dict(elevation=16, azimuth=225, sun_energy=2.5, sun_color=(1, .79, .50),
        sky_strength=.026, sky_tint=(.56, .68, .88), haze=.012, rays=1., bloom=.12,
        grade=dict(contrast=1.19, saturation=.90, teal_orange=True, vignette=.16)),
    'studio_film': dict(elevation=30, azimuth=140, sun_energy=.8, sun_color=(1, .86, .72),
        sky_strength=.03, sky_tint=(.78, .86, 1), haze=.004, rays=.4, bloom=.09,
        grade=dict(contrast=1.09, saturation=.95, temperature=.025, grain=.0015)),
}
ALIASES = {
    'senja': 'sunset', 'matahari terbenam': 'sunset', 'sunset': 'sunset',
    'sore keemasan': 'golden_hour', 'jam emas': 'golden_hour', 'keemasan': 'golden_hour',
    'pagi berkabut': 'misty_morning', 'pagi': 'misty_morning',
    'jam biru': 'blue_hour', 'petang': 'blue_hour', 'malam': 'night',
    'mendung': 'overcast_soft', 'mendung lembut': 'overcast_soft',
    'mimpi': 'dreamy', 'mimpi indah': 'dreamy', 'epik': 'epic',
    'studio': 'studio_film', 'film studio': 'studio_film',
    'tanpa': 'none', 'normal': 'none', 'tidak ada': 'none',
}
# Conservative CPU Eevee factors; measurements and conditions live in AGENTS.md.
COST = {'none': 1.0,
 'golden_hour': 1.35,
 'sunset': 1.35,
 'misty_morning': 1.4,
 'blue_hour': 1.5,
 'night': 1.65,
 'overcast_soft': 1.3,
 'dreamy': 1.45,
 'epic': 1.5,
 'studio_film': 1.3}
GRADE_LIMITS = dict(exposure=(-8, 8), contrast=(0, 3), saturation=(0, 3),
    temperature=(-1, 1), tint=(-1, 1), lifted_blacks=(0, .2),
    vignette=(0, 1), chromatic_aberration=(0, .02), grain=(0, .03))


def number(value, label, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{label} must be finite in {lo}..{hi}')
    return float(value)


def preset_name(value):
    if not isinstance(value, str):
        raise ValueError('look preset must be a string')
    key = ' '.join(value.strip().casefold().replace('_', ' ').replace('-', ' ').split())
    resolved = ALIASES.get(key, key.replace(' ', '_'))
    if resolved not in (*PRESETS, 'none'):
        raise ValueError(f'look must be one of {list(PRESETS) + ["none"]} or an Indonesian alias')
    return resolved


def resolve(preset='golden_hour', intensity=1., haze=None, god_rays=None, bloom=None,
            dof='auto', particles=None, grade=None, sun=None, clear=False):
    if not isinstance(clear, bool):
        raise ValueError('clear must be a boolean')
    name = 'none' if clear else preset_name(preset)
    intensity = number(intensity, 'intensity', 0, 1)
    if name == 'none':
        return dict(preset='none', intensity=0.)
    cfg = copy.deepcopy(PRESETS[name])
    cfg.update(preset=name, intensity=intensity)
    cfg['haze'] = cfg['haze'] if haze is None or haze is True else number(0 if haze is False else haze, 'haze density', 0, .1)
    for key, value in (('rays', god_rays), ('bloom', bloom)):
        if value is not None:
            cfg[key] = float(value) if isinstance(value, bool) else number(value, key, 0, 1)
    if (not isinstance(dof, (str, bool))) or dof not in ('auto', 'off', True, False):
        raise ValueError('dof must be auto, off, true or false')
    cfg['dof'] = 'auto' if dof in ('auto', True) else 'off'
    options = {'kind': cfg.get('particles', 'none'), 'count': 100, 'seed': 17}
    if particles is not None:
        if isinstance(particles, bool):
            options['kind'] = 'dust' if particles else 'none'
        elif isinstance(particles, str):
            options['kind'] = particles
        elif isinstance(particles, dict) and not set(particles) - set(options):
            options.update(particles)
        else:
            raise ValueError('particles accepts a kind or {kind, count, seed}')
    if options['kind'] not in ('none', 'dust', 'pollen', 'petals', 'embers'):
        raise ValueError('particles kind must be none/dust/pollen/petals/embers')
    for key, lo, hi in (('count', 0, 500), ('seed', 0, 2147483647)):
        if isinstance(options[key], bool) or not isinstance(options[key], int) or not lo <= options[key] <= hi:
            raise ValueError(f'particles {key} must be an integer in {lo}..{hi}')
    cfg['particles'] = options
    cfg['grade'].setdefault('vignette', .09)
    if grade is not None:
        if not isinstance(grade, dict) or set(grade) - set(GRADE_LIMITS) - {'teal_orange'}:
            raise ValueError('unknown cinematic grade key')
        for key, value in grade.items():
            if key == 'teal_orange':
                if not isinstance(value, bool):
                    raise ValueError('teal_orange must be boolean')
                cfg['grade'][key] = value
            else:
                cfg['grade'][key] = number(value, key, *GRADE_LIMITS[key])
    if sun is not None:
        if not isinstance(sun, dict) or set(sun) - {'elevation', 'azimuth'}:
            raise ValueError('sun accepts elevation and azimuth in degrees')
        for key, value in sun.items():
            cfg[key] = number(value, 'sun '+key, -90 if key == 'elevation' else -360, 90 if key == 'elevation' else 360)
    return cfg


def look_spec(value):
    """Normalize script string/dict look. None intentionally costs exactly zero."""
    if value is None:
        return None
    if isinstance(value, str):
        return resolve(value)
    if not isinstance(value, dict):
        raise ValueError('look must be a preset string, options dict or None')
    # A normalized plan can be parsed again by the MCP and engine layers.
    if 'sky_strength' in value:
        value = dict(value)
        value = dict(preset=value['preset'], intensity=value['intensity'], haze=value['haze'],
            god_rays=value['rays'], bloom=value['bloom'], dof=value['dof'],
            particles=value['particles'], grade=value['grade'],
            sun={k: value[k] for k in ('elevation', 'azimuth')})
    try:
        return resolve(**value)
    except TypeError as exc:
        raise ValueError(f'invalid look options: {exc}') from None


def cost_factor(cfg, engine):
    if not cfg or engine == 'BLENDER_WORKBENCH' or cfg['preset'] == 'none':
        return 1.
    extra = .10 if cfg['particles']['kind'] != 'none' and cfg['preset'] != 'dreamy' else 0
    return 1 + (COST[cfg['preset']] - 1 + extra) * cfg['intensity']
