"""Composition vocabulary shared by script parsing, environment commands and docs."""

PRESETS = ('blossom_garden','pine_forest','lakeside','riverside','rice_terraces','mountain_village')
UPGRADED = ('park','beach')
ALIASES = {'kebun bunga':'blossom_garden','taman sakura':'blossom_garden',
           'taman bunga':'blossom_garden','blossom garden':'blossom_garden',
           'hutan':'pine_forest','hutan pinus':'pine_forest','forest':'pine_forest',
           'danau':'lakeside','tepi danau':'lakeside','lake':'lakeside','mountain lake':'lakeside',
           'sungai':'riverside','tepi sungai':'riverside','river':'riverside',
           'sawah':'rice_terraces','sawah bertingkat':'rice_terraces','rice terraces':'rice_terraces','rice field':'rice_terraces',
           'desa':'mountain_village','desa pegunungan':'mountain_village','village':'mountain_village','kampung':'mountain_village'}


def resolve_alias(value):
    if not isinstance(value,str): return value
    key=' '.join(value.strip().casefold().replace('_',' ').replace('-',' ').split())
    return ALIASES.get(key, key.replace(' ','_') if key.replace(' ','_') in PRESETS else value)


def cost_factor(preset, density=1., engine='BLENDER_EEVEE'):
    """Conservative estimate floor; per-machine speed learning removes this once."""
    preset=resolve_alias(preset)
    if engine=='BLENDER_WORKBENCH' or preset not in (*PRESETS,*UPGRADED): return 1.
    floors=dict(park=1.50,beach=1.15,blossom_garden=1.45,pine_forest=1.35,
                lakeside=1.25,riverside=1.30,rice_terraces=1.25,mountain_village=1.35)
    return 1+(floors[preset]-1)*(.5+.5*density)
