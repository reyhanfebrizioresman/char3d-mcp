"""Consent-gated local face traits from a frontal photograph, on MPFB topology."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import command
from .toon import anatomy, coords, neutral_coords, uv_image
from .. import context
from ..photo_fit import validate, photo_path, fit_modifiers, project, colors, sample_rgb
from ..photo_landmarks import model_files

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
            raise RuntimeError('Local ONNX face inference failed: '+proc.stderr[-1500:])
        return json.loads(dst.read_text())


def correspondence(points, body, meshes):
    """HM08 neutral frontal sites; indices are re-fitted on the selected phenotype."""
    bottom,top,chin,eyes = anatomy(body,meshes,points)
    head = top-chin
    ez = np.mean(eyes,axis=0)[2]
    ey = min(p[1] for p in eyes)
    sites = {8:(0,chin), 0:(-.36*head,ez),16:(.36*head,ez),
             4:(-.27*head,chin+.18*head),12:(.27*head,chin+.18*head),
             27:(0,ez+.04*head),30:(0,ez-.17*head),
             31:(-.075*head,ez-.21*head),35:(.075*head,ez-.21*head),
             50:(0,ez-.32*head),55:(0,ez-.38*head),
             58:(-.12*head,ez-.35*head),62:(.12*head,ez-.35*head)}
    # Image left is character right, which is negative X in char3d's front view.
    for sign,indices in ((-1,(36,39,17,21)),(1,(45,42,26,22))):
        outer,inner,browout,browin = indices
        center = min(eyes,key=lambda p:abs(p[0]-sign*.03))
        sites[outer]=(center[0]+sign*.06*head,ez)
        sites[inner]=(center[0]-sign*.06*head,ez)
        sites[browout]=(center[0]+sign*.06*head,ez+.10*head)
        sites[browin]=(center[0]-sign*.06*head,ez+.10*head)
    frontal = np.arange(min(13380,len(points)))
    frontal = frontal[(points[frontal,2]>chin-.02)&(points[frontal,1]<ey+.055)]
    ids,vertices = [],[]
    for ident,(x,z) in sorted(sites.items()):
        distances = ((points[frontal,0]-x)**2+(points[frontal,2]-z)**2
                     +.05*(points[frontal,1]-ey)**2)
        vertices.append(int(frontal[distances.argmin()]))
        ids.append(ident)
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
    current_skin = tuple(body.material_slots[0].material.diffuse_color[:3])
    hair_mesh=next((m for m in meshes if _role(m,body)=='hair' and m.material_slots),None)
    current_hair = (_hair_color(meshes,body) or tuple(hair_mesh.material_slots[0].material.diffuse_color[:3])
                    if hair_mesh and hair_mesh.material_slots[0].material else (.03,.02,.015))
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
                        elif role=='skin' and not texture:
                            mat.pop('c3d_photo_base_image',None)
                            profile=json.loads(mat.get('c3d_material_profile','{}'))
                            gain=profile.get('albedo_gain',1.)
                            tint=profile.get('albedo_tint',(1,1,1))
                            _put(tree,bsdf.inputs['Base Color'],tuple(v*gain*t for v,t in zip(linear['skin'],tint))+(1,))
                            mat['c3d_photo_flat_color'] = list(linear['skin'])
                        elif role=='eyes':
                            # Preserve white sclera and authored pupil with a tint.
                            from .materials import _source,_mix
                            old = _source(bsdf.inputs['Base Color'])
                            tint = tuple(.6+v*.4 for v in linear['iris'])+(1,)
                            _put(tree,bsdf.inputs['Base Color'],_mix(tree,old,tint,strength,'photo eye tint'))
                            mat['c3d_photo_tint'] = [1-strength+strength*v for v in tint[:3]]
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
    for slot in body.material_slots:
        if not slot.material or not slot.material.node_tree:
            continue
        slot.material['c3d_photo_base_image'] = texture_image
        slot.material.pop('c3d_photo_flat_color',None)
        profile=json.loads(slot.material.get('c3d_material_profile','{}'))
        gain=profile.get('albedo_gain',1.)
        tint=profile.get('albedo_tint',(1,1,1))
        for tree in _trees(slot.material.node_tree):
            for bsdf in list(tree.nodes):
                if bsdf.type=='BSDF_PRINCIPLED':
                    node = tree.nodes.new('ShaderNodeTexImage');node.image=texture_image
                    from .materials import _mix
                    source=(_mix(tree,node.outputs['Color'],tuple(gain*t for t in tint)+(1,),1.,'photo portrait reflectance')
                            if profile else node.outputs['Color'])
                    _put(tree,bsdf.inputs['Base Color'],source)


@command('face_from_photo')
def face_from_photo(character,image,strength=1.,texture=None,consent=False):
    validate(consent,strength)
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
    directory = Path(os.environ.get('CHAR3D_FACE_MODEL_DIR',str(Path(context.WORKSPACE)/'models/face')))
    model_files(directory)  # Fail before decoding or mutating the character.
    rgb = decode(path)
    landmarks = infer(rgb,directory)
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
    fit = fit_modifiers(neutral[vertices],deltas[:,vertices],photo[ids],confidence[ids])
    for _ in range(3):
        deltas = np.array([pairs[i,1] if c>=0 else -pairs[i,0] for i,c in enumerate(fit['coefficients'])])
        fit = fit_modifiers(neutral[vertices],deltas[:,vertices],photo[ids],confidence[ids])
    stylized = body.get('c3d_style','realistic')!='realistic'
    amount = strength*(.55 if stylized else 1.)
    delta = np.einsum('m,mnc->nc',fit['coefficients']*amount,deltas)
    estimate = colors(rgb,photo)
    use_texture = not stylized if texture is None else texture
    if strength:
        displace(body,meshes,delta,neutral)
        paint(body,meshes,rgb,estimate,fit,strength,use_texture)
    applied_error = float(np.sqrt(np.mean(np.sum((project((neutral+delta)[vertices],fit['camera'])-photo[ids])**2,axis=1))))
    report = dict(character=root.name,style=body.get('c3d_style','realistic'),
                  modifiers={p[1].split('/')[-1].removesuffix('-incr'):round(float(c*amount),5) for p,c in zip(MODIFIERS,fit['coefficients'])},
                  fit_error_px=round(applied_error,3),solver_error_px=round(fit['rmse_px'],3),initial_error_px=round(fit['initial_rmse_px'],3),
                  colors_srgb=estimate,texture=use_texture,consent=True,local_only=True,
                  limits=['Frontal weak-perspective 2D fit; unseen 3D depth remains the MPFB prior.',
                          'Lighting, occlusion and painted hair/eyes bias colour estimates; no identity guarantee.',
                          'Expression and skin weights retained; inspect blinks, lips and hair fit after transfer.'])
    body['c3d_photo_fit'] = json.dumps(report)
    return report
