"""MPFB rest proportions and portable original toon materials."""
import json

import bpy
import numpy as np
from mathutils import Vector

from ..toon import RestMap, iris_pixels


def coords(data):
    values = np.empty(len(data)*3, dtype=np.float32)
    data.foreach_get('co', values)
    return values.reshape(-1, 3)


def neutral_coords(obj):
    """Fitted phenotype without active articulation/expression/life layers."""
    if not obj.data.shape_keys:
        return coords(obj.data.vertices)
    keys = obj.data.shape_keys.key_blocks
    points = coords(keys[0].data)
    for key in keys[1:]:
        if key.name.startswith('$'):
            points += (coords(key.data)-coords(key.relative_key.data))*key.value
    return points


def transform_family(body, meshes, mapping, rig=None, refit=True):
    """Map every relative morph in the same space; preserve authored skin weights."""
    for obj in meshes:
        matrix = body.matrix_world.inverted() @ obj.matrix_world
        inverse = matrix.inverted()
        forward_array, inverse_array = np.array(matrix), np.array(inverse)

        def mapped(data):
            points = coords(data) @ forward_array[:3,:3].T+forward_array[:3,3]
            values = (mapping(points) @ inverse_array[:3,:3].T+inverse_array[:3,3]).astype(np.float32)
            data.foreach_set('co', values.ravel())

        if obj.data.shape_keys:
            for key in obj.data.shape_keys.key_blocks:
                mapped(key.data)
        mapped(obj.data.vertices)
        obj.data.update()
    if rig:
        matrix = body.matrix_world.inverted() @ rig.matrix_world
        inverse = matrix.inverted()
        active = bpy.context.view_layer.objects.active
        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            endpoints = [(b, matrix @ b.head, matrix @ b.tail) for b in rig.data.edit_bones]
            for bone, head, tail in endpoints:
                points = mapping([head, tail])
                bone.head, bone.tail = inverse @ Vector(points[0]), inverse @ Vector(points[1])
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.context.view_layer.objects.active = active
    if rig and refit:
        rig.pop('c3d_landmarks', None)
        from .anim import _rig_landmarks, semantic_map
        from .mpfb import RIGIFY_DEF
        bones = RIGIFY_DEF if rig.get('c3d_rig_type') == 'rigify' else semantic_map(rig)
        landmarks = _rig_landmarks(rig, bones)
        rig['c3d_landmarks'] = json.dumps({k: list(v) for k, v in landmarks.items()})
        body['c3d_landmarks'] = rig['c3d_landmarks']
    bpy.context.view_layer.update()


def anatomy(body, meshes, points=None):
    # HM08's documented dimension vertices. Work from the fitted Basis, not the
    # helper cages (hair/skirts extend outside the actual head/body).
    points = neutral_coords(body) if points is None else points
    bottom, top, chin = points[13137, 2], points[881, 2], points[791, 2]
    from .materials import _role
    eyes = next((o for o in meshes if _role(o, body) == 'eyes'), None)
    centers = []
    if eyes:
        matrix = body.matrix_world.inverted() @ eyes.matrix_world
        ep = np.array([matrix @ v.co for v in eyes.data.vertices])
        for sign in (-1, 1):
            part = ep[ep[:, 0]*sign > 0]
            centers.append((part.min(axis=0)+part.max(axis=0))/2)
    if len(centers) != 2:
        centers = [(-.03, -.08, chin+(top-chin)*.56), (.03, -.08, chin+(top-chin)*.56)]
    return float(bottom), float(top), float(chin), centers


def stylize(body, meshes, rig, style):
    prefit = body.get('c3d_toon_prefit')
    if prefit:
        skin = tuple(json.loads(prefit)['skin'])
    else:
        skin = sampled_skin(body)
        fit_proportions(body,meshes,rig,style)
    blink_report = calibrate_blinks(body,meshes) if body.data.shape_keys else {}
    body['c3d_style'] = style
    if rig:
        rig['c3d_style'] = style
    material_report = toon_materials(body, meshes, skin=skin)
    bottom, top, chin, _ = anatomy(body, meshes)
    body['c3d_head_ratio'] = float((top-bottom)/(top-chin))
    return dict(style=style, head_ratio=body['c3d_head_ratio'], head_height_m=top-chin,
                sampled_skin_rgb=skin, blink=blink_report, recommended_render_style='anime', materials=material_report)


def sampled_skin(body):
    from .materials import _image, _pixels
    from ..materials import srgb_to_linear
    source = _image(body.material_slots[0].material)
    if source:
        # A broad atlas median excludes lips, facial hair and tiny dark texels.
        # Fixed meter cheek ROIs are unsuitable for short MPFB phenotypes.
        samples = _pixels(source).reshape(-1,4)[::256,:3]
        valid = samples[(samples.max(axis=1)-samples.min(axis=1)<.65)&(samples.mean(axis=1)>.08)&(samples.mean(axis=1)<.95)]
        rgb = np.median(valid if len(valid) else samples,axis=0)
        skin = srgb_to_linear(rgb) if source.colorspace_settings.name=='sRGB' else tuple(rgb)
    else:
        skin = tuple(body.material_slots[0].material.diffuse_color[:3])
    return tuple(float(v) for v in skin)


def fit_proportions(body,meshes,rig,style,refit=True):
    bottom, top, chin, eyes = anatomy(body, meshes)
    mapping = RestMap(style, bottom, top, chin, eyes)
    transform_family(body, meshes, mapping, rig,refit=refit)
    body['c3d_toon_head_scale'] = mapping.scale


def prefit_rigify(body,style,face=True):
    """Fit the metarig before Rigify creates length-dependent face mechanisms."""
    rig = body.parent
    meshes = [o for o in rig.children_recursive if o.type=='MESH']
    body['c3d_source'] = 'mpfb'
    if face:
        from .face import _ensure_face
        _ensure_face(body)
    skin = sampled_skin(body)
    fit_proportions(body,meshes,rig,style,refit=False)
    body['c3d_toon_prefit'] = json.dumps(dict(style=style,skin=skin))


def calibrate_blinks(body, meshes):
    """Fit closed upper lids to lower margins after eye enlargement.

    MPFB's stock targets can overrun a short phenotype's lid margin. A small
    smooth rest-space correction carries the same fix to eyelashes/brows.
    """
    from ..toon import LID_PAIRS
    keys = body.data.shape_keys.key_blocks
    basis = coords(keys[0].data)
    report = {}
    for side,pairs in LID_PAIRS.items():
        channel = 'eyeBlink'+('Left' if side=='L' else 'Right')
        if channel not in keys:
            continue
        closed = coords(keys[channel].data)
        anchors = basis[[i for i,j in pairs]]
        corrections = np.zeros((len(pairs),3))
        for n,(i,j) in enumerate(pairs):
            corrections[n,2] = closed[j,2]-closed[i,2]
            corrections[n,1] = min(basis[i,1],basis[j,1])-.0003-closed[i,1]
        radius = max(.004,np.ptp(anchors[:,0])*.6)
        def kernel(points):
            return np.exp(-np.square(np.asarray(points)[:,None,:]-anchors[None,:,:]).sum(axis=2)/(2*radius*radius))
        coefficients = np.linalg.solve(kernel(anchors)+np.eye(len(anchors))*1e-8,corrections)
        from .materials import _role
        for obj in meshes:
            if not obj.data.shape_keys or channel not in obj.data.shape_keys.key_blocks:
                continue
            local_keys = obj.data.shape_keys.key_blocks
            base = coords(local_keys[0].data)
            target = coords(local_keys[channel].data)
            matrix = body.matrix_world.inverted() @ obj.matrix_world
            forward,inverse = np.array(matrix),np.array(matrix.inverted())
            points = base @ forward[:3,:3].T+forward[:3,3]
            # Upper moving lid only. Lower rims, cheeks and eyeballs stay intact.
            movement = (target-base) @ forward[:3,:3].T
            gate = np.clip(-movement[:,2]/(.006*body.get('c3d_toon_head_scale',1.)),0,1)
            offset = (kernel(points) @ coefficients)*gate[:,None]
            target += (offset @ inverse[:3,:3].T).astype(np.float32)
            if _role(obj,body)=='eyes':
                # Enlarged rigid inserts otherwise peek through the thin closed
                # lids. A continuous native morph recesses just this eye behind
                # the lid; there is no visibility switch or alpha animation.
                selected = points[:,0]*(1 if side=='L' else -1)>0
                depth = float(np.ptp(points[selected,1]))*.8
                recess = np.array([0.,depth,0.]) @ inverse[:3,:3].T
                target[selected] = base[selected]+recess.astype(np.float32)
            local_keys[channel].data.foreach_set('co',target.ravel())
        closed = coords(keys[channel].data)
        report[side] = float(max(abs(closed[i,2]-closed[j,2]) for i,j in pairs))
    return report


def image(name, pixels):
    h, w = pixels.shape[:2]
    result = bpy.data.images.new(name, width=w, height=h, alpha=True)
    # PNG/glTF base-colour textures are sRGB. Encode linear pigment now so the
    # packed image keeps its appearance in both Blender and external viewers.
    result.colorspace_settings.name = 'sRGB'
    encoded = np.asarray(pixels, dtype=np.float32).copy()
    rgb = np.clip(encoded[:,:,:3],0,1)
    encoded[:,:,:3] = np.where(rgb<=.0031308,rgb*12.92,1.055*rgb**(1/2.4)-.055)
    result.pixels.foreach_set(encoded.ravel())
    result.pack()
    return result


def uv_image(obj, colors, size=512):
    """Rasterize vertex albedo to existing UVs, keeping glTF's plain PBR graph."""
    me = obj.data
    me.calc_loop_triangles()
    pixels = np.ones((size, size, 4), dtype=np.float32)
    pixels[:, :, :3] = np.median(colors, axis=0)
    uv = me.uv_layers.active.data
    for tri in me.loop_triangles:
        if obj.get('c3d_source')=='mpfb' and any(i>=13380 for i in tri.vertices):
            continue  # HM08 fitting cages must not overwrite the skin UV atlas.
        t = np.array([uv[i].uv for i in tri.loops])*(size-1)
        lo = np.maximum(0, np.floor(t.min(axis=0)).astype(int))
        hi = np.minimum(size-1, np.ceil(t.max(axis=0)).astype(int))
        if np.any(hi < lo):
            continue
        y, x = np.mgrid[lo[1]:hi[1]+1, lo[0]:hi[0]+1]
        matrix = np.vstack((t.T, np.ones(3)))
        if abs(np.linalg.det(matrix)) < 1e-8:
            continue
        weights = np.stack((x, y, np.ones_like(x)), axis=-1) @ np.linalg.inv(matrix).T
        inside = weights.min(axis=-1) >= -.025
        rgb = weights @ colors[list(tri.vertices)]
        tile = pixels[lo[1]:hi[1]+1, lo[0]:hi[0]+1, :3]
        tile[inside] = rgb[inside]
    return image('c3d_toon.skin.'+obj.name, pixels)


def toon_materials(body, meshes, skin=None, hair=None, iris=None):
    from .materials import _role, _image, _pixels, _sample_skin, _eye_frame, _hair_color
    from ..materials import srgb_to_linear
    frame = _eye_frame(meshes, body)
    skin = skin or _sample_skin(body, body.material_slots[0].material, frame[0])
    skin = np.clip(skin, 0., .8)
    hair = hair or _hair_color(meshes, body) or (.035, .023, .02)
    atlas = image('c3d_toon.original_iris.'+body.name, iris_pixels(color=iris or (.16, .38, .64)))
    _, top, chin, centers = anatomy(body, meshes)
    changed = []
    for obj in meshes:
        role = _role(obj, body)
        if role in ('mouth', 'accessory'):
            continue
        tex = None
        if role == 'skin':
            p = coords(obj.data.shape_keys.key_blocks[0].data if obj.data.shape_keys else obj.data.vertices)
            _, top, chin, centers = anatomy(body, meshes)
            h = top-chin
            ez = np.mean(centers, axis=0)[2]
            blush = np.exp(-.5*((np.abs(p[:, 0])-.22*h)/(.13*h))**2
                           -.5*((p[:, 2]-ez+.15*h)/(.10*h))**2)
            blush *= 1-smooth_front(p[:, 1], centers)
            colors = np.asarray(skin)[None, :]*(1-blush[:, None]*.16)+np.array([.65,.16,.18])*blush[:, None]*.16
            tex = uv_image(obj, colors)
        elif role == 'eyes':
            tex = atlas
            uv = obj.data.uv_layers.get('c3d_toon_iris') or obj.data.uv_layers.new(name='c3d_toon_iris')
            # One planar iris per eye, with white outside its circular limbus.
            matrix = body.matrix_world.inverted() @ obj.matrix_world
            ep = np.array([matrix @ v.co for v in obj.data.vertices])
            _, _, _, centers = anatomy(body, meshes)
            radius = .045*(top-chin)
            for loop in obj.data.loops:
                pt = ep[loop.vertex_index]
                center = min(centers, key=lambda c: abs(c[0]-pt[0]))
                uv.data[loop.index].uv = ((pt[0]-center[0])/(2*radius)+.5, (pt[2]-center[2])/(2*radius)+.5)
        for slot in obj.material_slots:
            old = slot.material
            if not old:
                continue
            mat = bpy.data.materials.new('c3d_toon.'+role+'.'+old.name)
            mat.use_nodes = True
            mat['c3d_toon_role'] = role
            bsdf = mat.node_tree.nodes.get('Principled BSDF')
            color = tuple(skin) if role == 'skin' else tuple(hair) if role in ('hair','brows') else tuple(old.diffuse_color[:3])
            source = _image(old)
            if role == 'clothes' and source:
                px = _pixels(source).reshape(-1,4)[::max(1,len(source.pixels)//(4*1024))]
                color = srgb_to_linear(np.median(px[:, :3], axis=0)) if source.colorspace_settings.name=='sRGB' else tuple(np.median(px[:, :3],axis=0))
            mat.diffuse_color = (*color, 1)
            bsdf.inputs['Base Color'].default_value = (*color, 1)
            bsdf.inputs['Roughness'].default_value = .75
            bsdf.inputs['Specular IOR Level'].default_value = .15
            if tex:
                node = mat.node_tree.nodes.new('ShaderNodeTexImage')
                node.image = tex
                node.extension = 'EXTEND'
                mat.node_tree.links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
                if role == 'eyes':
                    coords_node = mat.node_tree.nodes.new('ShaderNodeUVMap')
                    coords_node.uv_map = 'c3d_toon_iris'
                    mat.node_tree.links.new(coords_node.outputs[0],node.inputs['Vector'])
            if role in ('hair','brows'):
                # Keep authored cutout, discard photographic strand albedo.
                opacity = _image(old, 'opacity') or source
                if opacity:
                    node = mat.node_tree.nodes.new('ShaderNodeTexImage')
                    node.image = opacity
                    mat.node_tree.links.new(node.outputs['Color' if _image(old,'opacity') else 'Alpha'],bsdf.inputs['Alpha'])
                    mat.surface_render_method = 'DITHERED'
            slot.link, slot.material = 'OBJECT', mat
            changed.append(mat.name)
    return dict(quality='toon', materials=changed, original_iris=True, pores=False)


def smooth_front(y, centers):
    from ..toon import smooth
    return smooth((y-float(np.mean(centers, axis=0)[1])-.01)/.04)
