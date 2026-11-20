"""Validated, JSON-only appearance recipes; no images are embedded or uploaded."""
import copy
import math

MODIFIER_NAMES=('head-scale-horiz','head-scale-vert','chin-width','chin-height',
                'nose-scale-horiz','nose-scale-vert','mouth-scale-horiz','mouth-scale-vert',
                'l-eye-scale','r-eye-scale','eyebrows-trans-up')


def validate_look(value):
    if not isinstance(value,dict) or type(value.get('version')) is not int or value.get('version')!=1:
        raise ValueError('look must be a version=1 face_from_photo look recipe')
    value=copy.deepcopy(value)
    for field in ('modifiers','colors_srgb','assets'):
        if not isinstance(value.get(field,{}),dict):raise ValueError('look '+field+' must be a dict')
    from .toon import style_name
    value['style']=style_name(value.get('style','realistic'))
    if type(value.get('seed',0)) is not int:raise ValueError('look seed must be an integer')
    strength=value.get('color_strength',1.)
    if isinstance(strength,bool) or not isinstance(strength,(int,float)) or not math.isfinite(strength) or not 0<=strength<=1:raise ValueError('Invalid look colour strength')
    for name,weight in value.get('modifiers',{}).items():
        if name not in MODIFIER_NAMES or isinstance(weight,bool) or not isinstance(weight,(int,float)) or not math.isfinite(weight) or abs(weight)>1:
            raise ValueError('Invalid look face modifier: '+str(name))
    for name,color in value.get('colors_srgb',{}).items():
        if name not in ('skin','hair','iris') or not isinstance(color,(list,tuple)) or len(color)!=3 or not all(isinstance(c,(int,float)) and not isinstance(c,bool) and math.isfinite(c) and 0<=c<=1 for c in color):
            raise ValueError('look colours must be finite sRGB triples in 0..1')
    phenotype=value.get('phenotype',{})
    if not isinstance(phenotype,dict):raise ValueError('look phenotype must be a dict')
    for k,v in phenotype.items():
        if k=='race':
            if not isinstance(v,dict) or not v or set(v)-{'african','asian','caucasian'} or not all(isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x) and 0<=x<=1 for x in v.values()) or sum(v.values())<=0:raise ValueError('Invalid look race weights')
        elif k not in ('gender','age','muscle','weight','height','proportions') or isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=(90 if k=='age' else 1):
            raise ValueError('Invalid look phenotype: '+k)
    for k,v in value.get('assets',{}).items():
        if k not in ('hair','beard','glasses','skin','eyes','eyebrows','eyelashes') or (v is not None and not isinstance(v,str)):
            raise ValueError('Invalid look asset: '+str(k))
    fitting=value.get('asset_fit',{})
    if not isinstance(fitting,dict) or any(k not in ('hair','beard','glasses') or v!='surface' for k,v in fitting.items()):
        raise ValueError('Invalid look asset fitting mode')
    if value.get('texture') is not None:
        if not isinstance(value['texture'],dict) or not isinstance(value['texture'].get('path'),str):raise ValueError('Invalid look texture reference')
    return value
