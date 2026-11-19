"""Public render-style names, shared by the pure screenplay parsers and Blender."""
ALIASES = {'toon': 'anime', 'film_animasi': 'animated_film', 'animasi': 'animated_film'}
STYLES = ('none', 'anime', 'toon', 'clay', 'film', 'noir', 'vintage',
          'animated_film', 'film_animasi', 'animasi')

# Four broad light masses, with eased transitions and a continuous gradient
# underneath. Black remains black, including in moonlit environments.
LIGHT_MASSES = ((0., 0.), (.055, .12), (.12, .18), (.22, .39), (.34, .43),
                (.46, .68), (.61, .72), (.80, .99), (1., 1.08))


def palette(look=None):
    """Shadow/key multipliers in linear RGB; keep every look's light direction."""
    if look in ('night', 'blue_hour'):
        return (.48, .59, .88), (.82, .90, 1.)
    if look in ('sunset', 'dreamy'):
        return (.65, .48, .75), (1., .86, .76)
    if look in ('misty_morning', 'overcast_soft'):
        return (.56, .69, .83), (.95, .99, 1.)
    return (.48, .62, .80), (1., .94, .80)


def style_name(value):
    if not isinstance(value, str) or value not in STYLES:
        raise ValueError(f'style must be one of {STYLES}')
    return ALIASES.get(value, value)
