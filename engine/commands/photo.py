"""Consent-gated local face traits from a frontal photograph, on MPFB topology."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import command
from .toon import anatomy, coords, neutral_coords, uv_image
from .. import context
from ..photo_fit import validate, photo_path, fit_modifiers, project, colors, sample_rgb
from ..photo_landmarks import model_files, model_directory

MODIFIERS = (
    ('head/head-scale-horiz-decr','head/head-scale-horiz-incr'),
    ('head/head-scale-vert-decr','head/head-scale-vert-incr'),
    ('chin/chin-width-decr','chin/chin-width-incr'),
    ('chin/chin-height-decr','chin/chin-height-incr'),
    ('nose/nose-scale-horiz-decr','nose/nose-scale-horiz-incr'),
    ('nose/nose-scale-vert-decr','nose/nose-scale-vert-incr'),
    ('mouth/mouth-scale-horiz-decr','mouth/mouth-scale-horiz-incr'),
    ('mouth/mouth-scale-vert-decr','mouth/mouth-scale-vert-incr'),
    ('eyes/l-eye-scale-decr','eyes/l-eye-scale-incr'),
    ('eyes/r-eye-scale-decr','eyes/r-eye-scale-incr'),
    ('eyebrows/eyebrows-trans-down','eyebrows/eyebrows-trans-up'),
)


def decode(path):
    loaded = bpy.data.images.load(str(path),check_existing=False)
    try:
        w,h = loaded.size
        if not w or not h or w*h>24_000_000:
            raise ValueError('Photo must decode and be <=24 megapixels')
        pixels = np.empty(len(loaded.pixels),dtype=np.float32)
        loaded.pixels.foreach_get(pixels)
        # Blender FILE image pixels are encoded sRGB; top-left is ONNX's origin.
        # Blender can expose an RGBA pixel buffer for an RGB JPEG; derive the
        # buffer stride instead of assuming it equals the source channel count.
        channels=len(pixels)//(w*h)
        decoded=pixels.reshape(h,w,channels)[::-1]
        return (np.repeat(decoded[:,:,:1],3,axis=2) if channels<3 else decoded[:,:,:3]).copy()
    finally:
        bpy.data.images.remove(loaded)


def infer(rgb, directory):
    root = Path(__file__).resolve().parents[2]
    python = os.environ.get('CHAR3D_FACE_PYTHON', str(root/'.venv/bin/python'))
    scratch = Path(context.WORKSPACE)/'imports'
    with tempfile.TemporaryDirectory(prefix='.face-local-',dir=scratch) as temporary:
        src,dst = Path(temporary)/'rgb.npy',Path(temporary)/'landmarks.json'
        np.save(src,rgb,allow_pickle=False)
        proc = subprocess.run([python,'-m','engine.photo_landmarks',str(src),str(dst),str(directory)],
                              cwd=root,capture_output=True,text=True,timeout=90)
        if proc.returncode:
            raise RuntimeError('Local ONNX face inference failed: '+(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else 'inference subprocess failed'))
        return json.loads(dst.read_text())


def correspondence(points, body, meshes):
    """HM08 neutral frontal sites; indices are re-fitted on the selected phenotype."""
    bottom,top,chin,eyes = anatomy(body,meshes,points)
    head = top-chin
    ez = np.mean(eyes,axis=0)[2]
    ey = min(p[1] for p in eyes)
    mouth=(points[520]+points[540])*.5
    nose_candidates=np.flatnonzero((np.abs(points[:13380,0])<.025*head)&(points[:13380,2]<ez-.08*head)&(points[:13380,2]>ez-.30*head))
    tip=294
    sites = {8:(0,chin), 0:(-.36*head,ez),16:(.36*head,ez),
             4:(-.28*head,chin+.26*head),12:(.28*head,chin+.26*head),
             6:(-.16*head,chin+.10*head),10:(.16*head,chin+.10*head),
             7:(-.08*head,chin+.025*head),9:(.08*head,chin+.025*head),
             27:(0,ez-.015*head),30:tuple(points[tip,[0,2]]),
             31:(-.075*head,points[tip,2]-.012*head),35:(.075*head,points[tip,2]-.012*head),
             50:(0,points[455,2]),55:(0,points[492,2]),
             58:(-.115*head,mouth[2]),62:(.115*head,mouth[2])}
    for sign,indices in ((-1,(17,21)),(1,(26,22))):
        center=min(eyes,key=lambda p:abs(p[0]-sign*.03))
        for ident,offset in zip(indices,(.07,-.05)):
            sites[ident]=(center[0]+sign*offset*head,ez+.085*head)
    fixed={36:24,37:9,38:54,39:66,40:50,41:36,
           42:6850,43:6838,44:6793,45:6808,46:6820,47:6834,
           8:791,30:int(tip),31:5139,35:11753,50:455,55:492}
    frontal = np.arange(min(13380,len(points)))
    frontal = frontal[(points[frontal,2]>chin-.02)&(points[frontal,1]<ey+.055)]
    ids,vertices = [],[]
    for ident,(x,z) in sorted(sites.items()):
        distances = ((points[frontal,0]-x)**2+(points[frontal,2]-z)**2
                     +.05*(points[frontal,1]-ey)**2)
        vertices.append(fixed.get(ident,int(frontal[distances.argmin()])))
        ids.append(ident)
    for ident,index in sorted(fixed.items()):
        if ident not in ids:ids.append(ident);vertices.append(index)
    return ids,vertices


def modifier_deltas(body):
    from .mpfb import _services
    _services()
    from bl_ext.user_default.mpfb.services import LocationService
    from bl_ext.user_default.mpfb.services.targetservice import TargetService
    root = Path(LocationService.get_mpfb_data('targets'))
    basis = coords(body.data.shape_keys.key_blocks[0].data)
    pairs = []
    for negative,positive in MODIFIERS:
        pair = []
        for name in (negative,positive):
            path = root/(name+'.target.gz')
            key = TargetService.load_target(body,str(path),weight=0,name='__c3d_photo_temp')
            pair.append(coords(key.data)-basis)
            body.shape_key_remove(key)
        pairs.append(pair)
    return np.asarray(pairs)


def displace(body, meshes, delta, neutral):
    """Transfer a static offset to all relative morphs; animation deltas stay intact."""
    tree = KDTree(len(neutral))
    for i,p in enumerate(neutral):
        tree.insert(Vector(p),i)
    tree.balance()
    for obj in meshes:
        matrix = body.matrix_world.inverted() @ obj.matrix_world
        inverse = matrix.inverted().to_3x3()
        reference = coords(obj.data.shape_keys.key_blocks[0].data if obj.data.shape_keys else obj.data.vertices)
        offsets = delta if obj is body else np.array([delta[tree.find(matrix @ Vector(p))[1]] for p in reference])
        offsets = np.array([inverse @ Vector(p) for p in offsets])
        blocks = [k.data for k in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else []
        for data in [obj.data.vertices,*blocks]:
            data.foreach_set('co',(coords(data)+offsets).astype(np.float32).ravel())
        obj.data.update()
    rig = body.find_armature()
    if rig:
        def bone_map(points):
            return np.asarray(points)+np.array([delta[tree.find(Vector(p))[1]] for p in points])
        if rig.get('c3d_rig_type')=='rigify':
            # Generated Rigify constraints retain length-dependent mechanisms.
            # Keep their rest skeleton; refit the skin/contact landmark metadata.
            from .anim import _rig_landmarks
            from .mpfb import RIGIFY_DEF
            stored=_rig_landmarks(rig,RIGIFY_DEF)
            to_body=body.matrix_world.inverted()
            updated={}
            for name,point in stored.items():
                mapped=bone_map([to_body @ Vector(point)])[0]
                updated[name]=list(body.matrix_world @ Vector(mapped))
            rig['c3d_landmarks']=json.dumps(updated)
            body['c3d_landmarks']=rig['c3d_landmarks']
        else:
            from .toon import transform_family
            transform_family(body,[],bone_map,rig)
    bpy.context.view_layer.update()


def paint(body, meshes, rgb, estimate, fit, strength, texture):
    from .materials import _role, _trees, _put, _image, _pixels, _hair_color
    from ..materials import srgb_to_linear
    linear = {k:srgb_to_linear(v) for k,v in estimate.items()}
    from .toon import sampled_skin
    current_skin=body.material_slots[0].material.get('c3d_photo_flat_color') or body.material_slots[0].material.get('c3d_toon_flat_color') or sampled_skin(body)
    hair_mesh=next((m for m in meshes if _role(m,body)=='hair' and m.material_slots),None)
    current_hair = (_hair_color(meshes,body) or tuple(hair_mesh.material_slots[0].material.diffuse_color[:3])
                    if hair_mesh and hair_mesh.material_slots[0].material else (.03,.02,.015))
    if hair_mesh and hair_mesh.material_slots[0].material.get('c3d_toon_flat_color') is not None:current_hair=tuple(hair_mesh.material_slots[0].material['c3d_toon_flat_color'])
    for field,current in (('skin',current_skin),('hair',current_hair)):
        linear[field] = tuple(float(a)*(1-strength)+float(b)*strength for a,b in zip(current,linear[field]))
    if body.get('c3d_style','realistic')!='realistic':
        from .toon import toon_materials
        toon_materials(body,meshes,skin=linear['skin'],hair=linear['hair'],iris=linear['iris'])
    else:
        # Private graph copies preserve enhanced/native material ownership and
        # avoid recoloring other characters sharing an authored MPFB material.
        for obj in meshes:
            role = _role(obj,body)
            if role not in ('skin','hair','brows','eyes'):
                continue
            for slot in obj.material_slots:
                mat = slot.material
                if not mat or not mat.node_tree:
                    continue
                from .materials import _private
                original_source=mat.get('c3d_material_source',mat)
                mat = _private(mat)
                mat['c3d_material_source']=original_source
                mat['c3d_material_role'] = role
                slot.link,slot.material = 'OBJECT',mat
                for tree in _trees(mat.node_tree):
                    for bsdf in tree.nodes:
                        if bsdf.type != 'BSDF_PRINCIPLED':
                            continue
                        if role in ('hair','brows'):
                            _put(tree,bsdf.inputs['Base Color'],(*linear['hair'],1))
                            mat['c3d_photo_flat_color'] = list(linear['hair'])
                            for name,value in (('Roughness',.75),('Specular IOR Level',.15),('Sheen Weight',.05),('Coat Weight',0.)):
                                if name in bsdf.inputs:_put(tree,bsdf.inputs[name],value)
                        elif role=='skin' and not texture:
                            mat.pop('c3d_photo_base_image',None)
                            # Explicit pigment already replaces the scan. Its
                            # scan-specific exposure gain would wash dark skin
                            # out a second time when replaying a photo colour.
                            _put(tree,bsdf.inputs['Base Color'],(*linear['skin'],1.))
                            mat['c3d_photo_flat_color'] = list(linear['skin'])
                        elif role=='eyes':
                            # A new iris pigment must remain recognizable, including
                            # blue/green eyes on the default brown MPFB atlas.
                            from .toon import image
                            from ..toon import iris_pixels
                            atlas=image('c3d_photo.iris.'+body.name,iris_pixels(color=linear['iris']))
                            mat['c3d_photo_iris_image']=atlas
                            eye_uv(obj,body,meshes)
                            node=tree.nodes.new('ShaderNodeTexImage');node.image=atlas;node.extension='EXTEND'
                            uv=tree.nodes.new('ShaderNodeUVMap');uv.uv_map='c3d_photo_iris'
                            tree.links.new(uv.outputs[0],node.inputs['Vector'])
                            _put(tree,bsdf.inputs['Base Color'],node.outputs['Color'])
                            mat['c3d_photo_iris_color']=list(linear['iris'])
    if not texture:
        return
    points = neutral_coords(body)
    projected = project(points,fit['camera'])
    sampled = sample_rgb(rgb,projected)
    sampled = np.where(sampled<=.04045,sampled/12.92,((sampled+.055)/1.055)**2.4)
    _,top,chin,eyes = anatomy(body,meshes)
    ez = np.mean(eyes,axis=0)[2];ey = np.mean(eyes,axis=0)[1];head=top-chin
    from ..toon import smooth
    mask = (1-smooth((np.abs(points[:,0])-.25*head)/(.16*head)))
    mask *= smooth((points[:,2]-chin)/(.13*head))*(1-smooth((points[:,2]-ez-.20*head)/(.16*head)))
    mask *= 1-smooth((points[:,1]-ey)/(.15*head))
    for center in eyes:
        distance = np.sqrt(((points[:,0]-center[0])/(.10*head))**2+((points[:,2]-ez)/(.055*head))**2)
        mask *= smooth((distance-.7)/.5)
    mouth = np.sqrt((points[:,0]/(.13*head))**2+((points[:,2]-ez+.35*head)/(.04*head))**2)
    mask *= smooth((mouth-.6)/.5)
    h,w = rgb.shape[:2]
    mask *= ((projected[:,0]>=0)&(projected[:,0]<w)&(projected[:,1]>=0)&(projected[:,1]<h))
    # Base texture/detail is retained outside the facial projection.
    original = _image(body.material_slots[0].material)
    base = np.tile(linear['skin'],(len(points),1))
    if original and body.data.uv_layers:
        pixels = _pixels(original).reshape(original.size[1],original.size[0],4)
        uv = body.data.uv_layers.active.data
        for loop in body.data.loops:
            u,v = uv[loop.index].uv
            color = pixels[min(original.size[1]-1,max(0,int(v*original.size[1]))),min(original.size[0]-1,max(0,int(u*original.size[0]))),:3]
            base[loop.vertex_index] = srgb_to_linear(color) if original.colorspace_settings.name=='sRGB' else color
    color = base*(1-mask[:,None]*strength)+sampled*mask[:,None]*strength
    texture_image = uv_image(body,color,size=1024)
    texture_image.name = 'c3d_local_photo_projection.'+body.name
    link_skin_texture(body,texture_image)


def eye_uv(obj,body,meshes):
    p=neutral_coords(body);_,top,chin,centers=anatomy(body,meshes)
    radius=max(.001,abs(float(p[24,0]-p[66,0]))*.40)
    uv=obj.data.uv_layers.get('c3d_photo_iris') or obj.data.uv_layers.new(name='c3d_photo_iris')
    matrix=body.matrix_world.inverted()@obj.matrix_world
    for loop in obj.data.loops:
        q=matrix@obj.data.vertices[loop.vertex_index].co
        center=min(centers,key=lambda c:abs(c[0]-q.x))
        uv.data[loop.index].uv=((q.x-center[0])/(2*radius)+.5,(q.z-center[2])/(2*radius)+.5)


def link_skin_texture(body,texture_image):
    from .materials import _trees,_put
    for slot in body.material_slots:
        if not slot.material or not slot.material.node_tree:
            continue
        slot.material['c3d_photo_base_image'] = texture_image
        slot.material.pop('c3d_photo_flat_color',None)
        for tree in _trees(slot.material.node_tree):
            for bsdf in list(tree.nodes):
                if bsdf.type=='BSDF_PRINCIPLED':
                    node = tree.nodes.new('ShaderNodeTexImage');node.image=texture_image
                    _put(tree,bsdf.inputs['Base Color'],node.outputs['Color'])


@command('face_from_photo')
def face_from_photo(character,image,strength=1.,texture=None,consent=False,traits=None,seed=None):
    started=time.monotonic();stages={}
    validate(consent,strength)
    if seed is not None and type(seed) is not int:raise ValueError('seed must be an integer or null')
    traits=traits or {}
    if texture is not None and type(texture) is not bool:
        raise ValueError('texture must be true, false or null (style default)')
    path = photo_path(context.WORKSPACE,image)
    from .materials import _family
    from .face import _basemesh
    if _basemesh(character).get('c3d_source')!='mpfb':
        raise ValueError('face_from_photo requires a realistic or stylized MPFB character with original HM08 topology')
    root,body,meshes = _family(character)
    if len(body.data.vertices)!=19158:
        raise ValueError('face_from_photo requires unmodified MPFB HM08 topology')
    directory = model_directory(context.WORKSPACE)
    model_files(directory)  # Fail before decoding or mutating the character.
    rgb = decode(path)
    landmarks = infer(rgb,directory)
    stages["decode_infer_s"]=round(time.monotonic()-started,3)
    from .face import _ensure_face
    _ensure_face(body)
    # Neutral rest landmarks include phenotype macro keys, exclude expression keys.
    neutral = neutral_coords(body)
    ids,vertices = correspondence(neutral,body,meshes)
    pairs = modifier_deltas(body)
    # Local linearization of paired decr/incr modifiers, refined with the correct
    # sign after each solve. MPFB targets are already in meters via TargetService.
    deltas = (pairs[:,1]-pairs[:,0])*.5
    photo = np.asarray(landmarks['landmarks'])
    confidence = np.asarray(landmarks['confidence'])
    eye_span=float(np.linalg.norm(photo[36:42].mean(0)-photo[42:48].mean(0)))
    regularization=max(1.,eye_span**2*.01)
    fit = fit_modifiers(neutral[vertices],deltas[:,vertices],photo[ids],confidence[ids],regularization=regularization,allow_yaw=True)
    for _ in range(3):
        deltas = np.array([pairs[i,1] if c>=0 else -pairs[i,0] for i,c in enumerate(fit['coefficients'])])
        fit = fit_modifiers(neutral[vertices],deltas[:,vertices],photo[ids],confidence[ids],regularization=regularization,allow_yaw=True)
    stylized = body.get('c3d_style','realistic')!='realistic'
    amount = strength*(.55 if stylized else 1.)
    delta = np.einsum('m,mnc->nc',fit['coefficients']*amount,deltas)
    stages['geometry_fit_s']=round(time.monotonic()-started-stages['decode_infer_s'],3)
    estimate = colors(rgb,photo)
    if 'colors_srgb' in traits:
        from ..looks import validate_look
        override=validate_look(dict(version=1,colors_srgb=traits['colors_srgb']))['colors_srgb']
        estimate.update(override)
    use_texture = not stylized if texture is None else texture
    if strength:
        from .looks import asset_traits
        asset_traits(body,meshes,traits)
        displace(body,meshes,delta,neutral)
        if stylized:
            from .toon import fit_hair
            fit_hair(body,meshes)
        paint(body,meshes,rgb,estimate,fit,strength,use_texture)
        if stylized:
            from .toon import calibrate_blinks,calibrate_bilabials,sync_ink
            calibrate_blinks(body,meshes);calibrate_bilabials(body);sync_ink(body,meshes)
    stages['apply_paint_s']=round(time.monotonic()-started-sum(stages.values()),3)
    applied_error = float(np.sqrt(np.mean(np.sum((project((neutral+delta)[vertices],fit['camera'])-photo[ids])**2,axis=1))))
    report = dict(character=root.name,strength=strength,style=body.get('c3d_style','realistic'),
                  modifiers={p[1].split('/')[-1].removesuffix('-incr'):round(float(c*amount),5) for p,c in zip(MODIFIERS,fit['coefficients'])},
                  fit_error_px=round(applied_error,3),solver_error_px=round(fit['rmse_px'],3),initial_error_px=round(fit['initial_rmse_px'],3),camera_yaw_deg=round(float(np.degrees(fit['camera'][4])),3),camera_pitch_deg=round(float(np.degrees(fit['camera'][5])),3),
                  colors_srgb=estimate,texture=use_texture,consent=True,local_only=True,
                  limits=['Weak-perspective 2D fit with bounded slight yaw; unseen 3D depth remains the MPFB prior.',
                          'Lighting, occlusion and painted hair/eyes bias colour estimates; no identity guarantee.',
                          'Expression and skin weights retained; inspect blinks, lips and hair fit after transfer.'])
    from .looks import save_recipe
    report['look']=save_recipe(body,report,fit['coefficients']*strength,traits,seed)
    assets=report['look'].get('assets',{})
    report['traits']=dict(face_shape=dict(value=report['modifiers'],source='landmark fit'),
        skin_tone=dict(value=estimate['skin'],source='provided' if 'skin' in traits.get('colors_srgb',{}) else 'estimated'),
        eye_colour=dict(value=estimate['iris'],source='provided' if 'iris' in traits.get('colors_srgb',{}) else 'estimated'),
        hair_colour=dict(value=estimate['hair'],source='provided' if 'hair' in traits.get('colors_srgb',{}) else 'estimated'))
    for key,label in (('hair','hair_style'),('beard','beard'),('glasses','glasses')):
        report['traits'][label]=dict(value=assets.get(key),source='provided' if key in traits else 'retained; not inferred by the landmark model')
    from .photo_review import likeness_check
    report['likeness']=likeness_check(root,body,rgb,photo,fit,directory)
    report['likeness_score']=report['likeness']['score']
    stages['review_s']=round(time.monotonic()-started-sum(stages.values()),3)
    report['timings_s']=stages
    body['c3d_photo_fit'] = json.dumps(report)
    return report
