"""Apply reusable numeric likeness recipes and explicitly supplied catalog traits."""
import hashlib
import json
from pathlib import Path
import bpy
import numpy as np
from .. import context
from ..looks import MODIFIER_NAMES,validate_look
from ..photo_fit import photo_path


def asset_traits(body,meshes,traits):
    from .mpfb import _catalog,_pick,_services,_repair_part_weights
    from .materials import _role
    if not isinstance(traits,dict) or set(traits)-{'hair','beard','glasses','colors_srgb'}:
        raise ValueError('traits accepts hair, beard, glasses catalog names and colors_srgb')
    settings=json.loads(body.get('c3d_build_look','{}'));assets=settings.setdefault('assets',{})
    cat=_catalog();_a,HumanService,_l=_services()
    # Resolve all requested assets before changing any existing part.
    paths={}
    for kind,category in (('hair','hair'),('beard','beards'),('glasses','clothes')):
        if kind not in traits:continue
        name=traits[kind]
        if name is not None and not isinstance(name,str):raise ValueError('Explicit '+kind+' must be an installed catalog name or null')
        paths[kind]=_pick(cat,category,name) if name else None
    rig=body.find_armature()
    added=False
    for kind in ('hair','beard','glasses'):
        if kind not in traits:continue
        name=traits[kind]
        if name is not None and not isinstance(name,str):raise ValueError('Explicit '+kind+' must be an installed catalog name or null')
        category={'hair':'hair','beard':'beards','glasses':'clothes'}[kind]
        path=paths[kind]
        if assets.get(kind)==name:continue
        oldname=assets.get(kind)
        old=[o for o in meshes if (kind=='hair' and _role(o,body)=='hair' and 'beard' not in o.name.lower()) or
             (kind!='hair' and oldname and oldname in o.name)]
        for obj in old:
            meshes.remove(obj);HumanService.unload_mhclo_asset(body,obj)
        if path:
            obj=HumanService.add_mhclo_asset(path,body,asset_type='Hair' if kind=='hair' else 'Clothes',subdiv_levels=0)
            obj['c3d_material_part']=('hair ' if kind in ('hair','beard') else '')+name
            if kind=='glasses':obj['c3d_garment_category']='glasses'
            if rig:_repair_part_weights([obj],body,rig)
            meshes.append(obj);added=True
        assets[kind]=name
        settings.setdefault('asset_fit',{})[kind]='surface'
    if added and body.data.shape_keys:
        from bl_ext.user_default.mpfb.services.faceservice import FaceService
        FaceService.interpolate_targets(body)
    if added and rig and body.get('c3d_style','realistic')=='realistic' and body.material_slots[0].material.get('c3d_material_profile'):
        from .materials import upgrade_materials
        upgrade_materials(rig.name)
    body['c3d_build_look']=json.dumps(settings)
    bpy.context.view_layer.update()
    return assets


def save_recipe(body,report,coefficients,traits,seed):
    from .materials import _image
    from .photo import MODIFIERS
    recipe=json.loads(body.get('c3d_build_look','{}'))
    recipe.update(version=1,style=body.get('c3d_style','realistic'),seed=seed if seed is not None else recipe.get('seed',0),
                  modifiers={name:round(float(c),8) for name,c in zip(MODIFIER_NAMES,coefficients)},
                  colors_srgb=report['colors_srgb'],color_strength=report['strength'],texture=None)
    if report['texture']:
        image=body.material_slots[0].material.get('c3d_photo_base_image')
        if image:
            pixels=np.empty(len(image.pixels),np.float32);image.pixels.foreach_get(pixels)
            digest=hashlib.sha256(pixels.tobytes()).hexdigest()
            relative='face_looks/'+digest+'.png';root=(Path(context.WORKSPACE)/'imports').resolve()
            folder=(root/'face_looks').resolve()
            if not folder.is_relative_to(root):raise ValueError('look texture directory must stay inside workspace imports/')
            path=folder/(digest+'.png')
            path.parent.mkdir(parents=True,exist_ok=True)
            name=image.name
            image.filepath_raw=str(path);image.file_format='PNG';image.save()
            image.name=name
            recipe['texture']=dict(path=relative,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    recipe=validate_look(recipe)
    body['c3d_look_recipe']=json.dumps(recipe)
    return recipe


def apply_look(root,body,meshes,recipe):
    from .photo import modifier_deltas,displace,paint,link_skin_texture
    from .toon import neutral_coords,calibrate_blinks,calibrate_bilabials,sync_ink
    recipe=validate_look(recipe)
    pairs=modifier_deltas(body)
    coefficients=np.array([recipe.get('modifiers',{}).get(n,0.) for n in MODIFIER_NAMES])
    factor=.55 if body.get('c3d_style','realistic')!='realistic' else 1.
    delta=np.einsum('m,mnc->nc',abs(coefficients)*factor,np.array([pairs[i,1] if c>=0 else pairs[i,0] for i,c in enumerate(coefficients)]))
    if np.any(coefficients):displace(body,meshes,delta,neutral_coords(body))
    if factor!=1:
        from .toon import fit_hair
        fit_hair(body,meshes)
    colors=recipe.get('colors_srgb')
    if colors and recipe.get('color_strength',1.):paint(body,meshes,None,colors,None,recipe.get('color_strength',1.),False)
    texture=recipe.get('texture')
    if texture and body.get('c3d_style','realistic')=='realistic':
        path=photo_path(context.WORKSPACE,texture['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=texture.get('sha256'):raise ValueError('look texture SHA-256 mismatch')
        image=bpy.data.images.load(str(path),check_existing=True);image.pack();link_skin_texture(body,image)
    if factor!=1:
        calibrate_blinks(body,meshes);calibrate_bilabials(body);sync_ink(body,meshes)
    result={**recipe,'style':body.get('c3d_style','realistic')}
    body['c3d_look_recipe']=json.dumps(result)
    return result
