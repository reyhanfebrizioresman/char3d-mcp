"""Command-facing adapter; validated geometry comes from engine.nature."""
import inspect
import json

from . import command
from ..nature import GENERATORS
from ..nature.core import integer, number


@command('nature_catalog')
def nature_catalog():
    return dict(generators={name: dict(parameters=str(inspect.signature(fn)),
        description=(fn.__doc__ or '').strip()) for name,fn in GENERATORS.items()},
        units='meters; Z up; all positions local to the returned root',
        seeds='local RNG, integer 0..2147483647; identical inputs produce identical recipes',
        limits='density capped at 18000 grass clumps; 3000 flowers; 500 petals; 60 birds',
        motion='saved analytic drivers/geometry nodes; no simulations or per-frame LOD switches')


@command('add_nature')
def add_nature(kind, location=(0,0,0), rotation_z=0., scale=1., seed=0, params=None, name=None,
               camera_aware=True,area=None,density=None,season=None):
    from .environment import _Builder, _vector
    from ..nature.blender import realize
    if kind not in GENERATORS: raise ValueError(f'kind must be one of {list(GENERATORS)}')
    integer(seed,'seed',0,2147483647)
    location=_vector(location,'location')
    number(rotation_z,'rotation_z',-36000,36000);number(scale,'scale',.001,100)
    if params is not None and not isinstance(params,dict): raise ValueError('params must be a dict')
    params=dict(params or {})
    accepted=inspect.signature(GENERATORS[kind]).parameters
    for label,value in (('area',area),('density',density),('season',season)):
        if value is not None:
            if label not in accepted: raise ValueError(f'{kind} does not use {label}; inspect nature_catalog')
            params[label]=value
    if 'seed' in params: raise ValueError('pass seed as the top-level argument')
    requested=dict(params)
    if not isinstance(camera_aware,bool): raise ValueError('camera_aware must be boolean')
    from ..nature.camera import coverage, weight
    bounds=coverage() if camera_aware else None
    lod=weight(location,bounds)
    if kind in ('grass_field','flowers','reeds'):
        base=inspect.signature(GENERATORS[kind]).parameters['density'].default
        if 'density' in params: base=number(params['density'],'density',0,200)
        params['density']=base*lod
    elif kind=='tree' and bounds is not None:
        params['detail']=max(.25,number(params.get('detail',1.),'detail',.25,1)*lod)
    try: asset=GENERATORS[kind](seed=seed,**params)
    except TypeError as exc: raise ValueError(f'invalid {kind} params: {exc}') from None
    vertices=sum(len(p.vertices) for p in asset.parts)
    if vertices>1200000: raise ValueError('asset exceeds 1200000 vertices; reduce density/area')
    b=_Builder(name or kind,location,scale,rotation=rotation_z,seed=seed)
    b.root['c3d_nature_root']=True;b.root['c3d_nature']=True
    b.root['c3d_nature_recipe']=json.dumps(dict(api=1,kind=kind,seed=seed,params=requested,
        camera_aware=camera_aware,lod_weight=lod))
    objects=realize(b,asset)
    return {**b.result(),'kind':kind,'seed':seed,'vertices':vertices,
            'parts':objects,'metadata':asset.metadata,'lod':dict(weight=lod,coverage=bounds,
                policy='build-time camera union; fixed through the saved animation')}


@command('clear_nature')
def clear_nature():
    from ..nature.blender import cleanup
    import bpy
    removed=[]
    roots=[o for o in bpy.context.scene.objects if o.get('c3d_nature_root')]
    for root in roots:
        for obj in [*reversed(root.children_recursive),root]:
            removed.append(obj.name);bpy.data.objects.remove(obj,do_unlink=True)
    for pool in (bpy.data.meshes,bpy.data.materials,bpy.data.lights):
        for item in list(pool):
            if (item.get('c3d_environment') or item.get('c3d_nature')) and not item.users: pool.remove(item)
    cleanup()
    return dict(removed=removed,count=len(removed))
