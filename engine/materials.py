"""Blender-free character material profiles. Distances are meters, colors linear.

Tone is estimated from the actual skin texture, never from ethnicity or gender.
These are restrained artistic approximations of epidermal scattering, not measured
optical coefficients. Radius ratios deliberately scatter red farther than blue.
"""
import colorsys
import math

VERSION = 2
TONES = {
    'dark': dict(luminance=.065, radius=(1., .32, .16), scale=.00085, sss=.12, specular=.28,
                 roughness=.48, redness=.045, color=(.16, .065, .035)),
    'medium': dict(luminance=.22, radius=(1., .40, .20), scale=.00105, sss=.12, specular=.24,
                   roughness=.49, redness=.075, color=(.40, .22, .13)),
    'light': dict(luminance=.48, radius=(1., .45, .23), scale=.0010, sss=.08, specular=.20,
                  roughness=.50, redness=.13, color=(.65, .43, .33)),
}
IRIS_SATURATION = .65
IRIS_VALUE = .65
IRIS_TINT = (.75, .85, .40)
# Existing cinematic keys/fills and their high-contrast grade already attenuate
# skin. This is the remaining portrait-normalization strength, not a light gain.
LOOK_NORMALIZATION = dict(golden_hour=.45, sunset=.45, epic=.60, dreamy=.65,
                          night=.15, blue_hour=.30, misty_morning=.80,
                          overcast_soft=.80, studio_film=1.)
FABRICS = {
    'cotton': dict(roughness=.72, sheen=.12, scale=1600., bump=.000035, anisotropy=.05),
    'denim': dict(roughness=.78, sheen=.10, scale=1250., bump=.00006, anisotropy=.12),
    'wool': dict(roughness=.82, sheen=.28, scale=950., bump=.00008, anisotropy=.0),
    'knit': dict(roughness=.79, sheen=.23, scale=700., bump=.00009, anisotropy=.05),
    'silk': dict(roughness=.34, sheen=.32, scale=2200., bump=.000015, anisotropy=.35),
    'leather': dict(roughness=.44, sheen=.02, scale=900., bump=.000055, anisotropy=.0),
}


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be finite in {low}..{high}')
    return float(value)


def options(quality='enhanced', skin_tone=None, skin_detail=1., hair_detail=1.):
    if quality not in ('enhanced', 'mpfb'):
        raise ValueError('quality/materials must be enhanced or mpfb')
    if skin_tone is not None:
        if isinstance(skin_tone, str):
            if skin_tone not in TONES:
                raise ValueError('skin_tone must be light, medium, dark, linear RGB or null')
        elif isinstance(skin_tone, (list, tuple)) and len(skin_tone) == 3:
            skin_tone = [number(v, 'skin_tone RGB', 0, 1) for v in skin_tone]
        else:
            raise ValueError('skin_tone must be light, medium, dark, linear RGB or null')
    return dict(quality=quality, skin_tone=skin_tone,
                skin_detail=number(skin_detail, 'skin_detail', 0, 2),
                hair_detail=number(hair_detail, 'hair_detail', 0, 2))


def luminance(rgb):
    return sum(a*b for a, b in zip(rgb, (.2126, .7152, .0722)))


def srgb_to_linear(rgb):
    return tuple(v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb)


def skin_profile(rgb, age=25, detail=1.):
    """Interpolate without bleaching dark textures or tinting light textures orange."""
    rgb = [number(v, 'skin RGB', 0, 1) for v in rgb]
    age = number(age, 'age', 1, 90)
    detail = number(detail, 'skin_detail', 0, 2)
    y = luminance(rgb)
    a, b = (TONES['dark'], TONES['medium']) if y < .22 else (TONES['medium'], TONES['light'])
    t = min(1., max(0., (y-a['luminance'])/(b['luminance']-a['luminance'])))
    result = {k: a[k]*(1-t)+b[k]*t for k in ('scale', 'sss', 'roughness', 'redness', 'specular')}
    result['radius'] = tuple(x*(1-t)+z*t for x, z in zip(a['radius'], b['radius']))
    # Children have smooth skin; older textures retain their authored wrinkles.
    result['pore_distance'] = .000028 * (.4 if age < 14 else 1 + max(0, age-40)/120) * detail
    result['roughness'] += max(0, age-45)*.0008
    result['luminance'] = y
    # Normalize bright scan reflectance with a monotone toe. A linear falloff
    # of gain can invert light/medium tones; this power curve preserves their
    # luminance ordering and RGB ratios. The darkest scans remain unchanged.
    target = y if y <= .065 else .065 * (y/.065)**.11
    warm = min(1., max(0., (y-.18)/.3))
    # Light scans read grey/ashy once normalized; keep a warm, slightly peachy
    # undertone (more red, less blue) instead of a neutral one.
    result['albedo_tint'] = (1+.12*warm, 1-.01*warm, 1-.07*warm)
    tinted = tuple(c*t for c,t in zip(rgb, result['albedo_tint']))
    result['albedo_gain'] = target/luminance(tinted) if y else 1.
    result['albedo_luminance'] = target
    result['albedo_ceiling'] = min(1., .55/max(max(tinted), .001))
    return result


def look_albedo_gain(profile, config=None):
    """Do not stack the full portrait correction with dim cinematic face keys.

    RGB ratios/textures remain intact. The ceiling prevents compensation from
    exceeding the original texture or a 0.55 sampled linear RGB channel.
    """
    base = profile['albedo_gain']
    ceiling = max(base, profile.get('albedo_ceiling', base))
    if not config or not config.get('intensity', 0) or base == ceiling:
        return base
    amount = LOOK_NORMALIZATION.get(config['preset'], 1.)
    strength = 1 - (1-amount)*config['intensity']
    return ceiling*(base/ceiling)**strength


def iris_color(rgb, brown=True):
    """The shader's hue-preserving correction, also usable for numeric checks."""
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    toned = colorsys.hsv_to_rgb(h, s*(IRIS_SATURATION if brown else .9), v*(IRIS_VALUE if brown else .85))
    return tuple(c*t for c,t in zip(toned, IRIS_TINT if brown else (1., 1., 1.)))


def age_years(macro):
    value = number(macro, 'MPFB age', 0, 1)
    if value <= .1875:
        return 1 + value/.1875*10
    if value <= .5:
        return 11 + (value-.1875)/.3125*14
    return 25 + (value-.5)/.5*65


def fabric_kind(name, category=''):
    text = (name+' '+category).lower()
    for kind, hints in (
        ('cotton', ('canvas', 'cloth_shoe', 'sneaker')),
        ('leather', ('leather', 'boot', 'shoe', 'belt')),
        ('denim', ('denim', 'jean')),
        ('wool', ('wool', 'tweed', 'felt')),
        ('knit', ('knit', 'sweater', 'pullover', 'cardigan', 'sock')),
        ('silk', ('silk', 'satin')),
    ):
        if any(h in text for h in hints):
            return kind
    return 'cotton'


def cost_factor(enhanced, total, engine, style=None, strength=1.):
    """Incremental material cost once, independent of look/nature/grade factors.

    Full clay/toon replace the shader. Do not charge for shaders they bypass.
    The floor includes procedural microdetail and cheap eye coat, no shells/rays.
    """
    if engine == 'BLENDER_WORKBENCH' or not total:
        return 1.
    bypass = strength if style in ('anime', 'toon', 'clay') else 0.
    return 1 + .15 * min(1., max(0., enhanced/total)) * (1-bypass)
