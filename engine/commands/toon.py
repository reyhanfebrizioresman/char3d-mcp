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
        fitted=json.loads(prefit)
        skin = tuple(fitted['skin'])
        reference=fitted.get('skin_reference',skin)
    else:
        skin = sampled_skin(body)
        from .materials import _sample_skin,_eye_frame
        reference=tuple(body.get('c3d_toon_scan_reference')) if body.get('c3d_toon_scan_reference') is not None else _sample_skin(body,body.material_slots[0].material,_eye_frame(meshes,body)[0])
        fit_proportions(body,meshes,rig,style)
    smooth_head(body)
    round_jaw(body)
    fit_hair(body,meshes)
    lift_smile(body,meshes)
    fit_mouth(body,meshes)
    fit_ankles(body,meshes)
    blink_report = calibrate_blinks(body,meshes) if body.data.shape_keys else {}
    body['c3d_style'] = style
    if rig:
        rig['c3d_style'] = style
    calibrate_bilabials(body)
    simplify_brows(body,meshes)
    ink_lids(body,meshes)
    from ..toon_appearance import scan_pigment
    pigment,gain=scan_pigment(skin,reference)
    material_report = toon_materials(body, meshes, skin=tuple(pigment),hair=body.get('c3d_toon_requested_hair_rgb'))
    # Native PBR/export uses the same scan correction as realistic skin. The
    # unlit/cel shaders retain half that log exposure correction, applied only
    # to temporary shader copies; photo/recipe paint has no scan compensation.
    style_gain=gain**-.5
    for slot in body.material_slots:
        if slot.material and slot.material.get('c3d_toon_role')=='skin':
            slot.material['c3d_toon_scan_style_gain']=style_gain
    material_report.update(scan_value_gain=gain,toon_value_gain=style_gain,scan_reference_rgb=list(reference))
    head_surface(body)
    bottom, top, chin, _ = anatomy(body, meshes)
    body['c3d_head_ratio'] = float((top-bottom)/(top-chin))
    return dict(style=style, head_ratio=body['c3d_head_ratio'], head_height_m=top-chin,
                sampled_skin_rgb=skin, blink=blink_report, measurements=face_metrics(body,meshes),
                before=json.loads(body.get('c3d_toon_before','{}')),
                recommended_render_style='anime', materials=material_report)


def asset_hair_color(path):
    """Keep the requested asset's pigment when choosing an eye-safe variant."""
    from pathlib import Path
    from .materials import _pixels
    from ..materials import srgb_to_linear
    asset=Path(path)
    material=next((line.split(maxsplit=1)[1] for line in asset.read_text().splitlines() if line.startswith('material ')),None)
    if not material:return None
    matpath=asset.parent/material
    texture=next((line.split(maxsplit=1)[1] for line in matpath.read_text().splitlines() if line.startswith('diffuseTexture ')),None)
    if not texture:return None
    im=bpy.data.images.load(str(matpath.parent/texture),check_existing=True)
    try:
        px=_pixels(im).reshape(-1,4)[::251];px=px[px[:,3]>.6,:3]
        return tuple(float(v) for v in srgb_to_linear(np.median(px,0))) if len(px) else None
    finally:
        if im.users==0:bpy.data.images.remove(im)


def sampled_skin(body):
    from .materials import _image, _pixels
    from ..materials import srgb_to_linear
    source = _image(body.material_slots[0].material)
    if source:
        # Sample fitted facial UVs, rather than unrelated atlas background,
        # body shadows or a periodic column stride. Keep authored tone order.
        p=neutral_coords(body);h=float(p[881,2]-p[791,2])
        ez=float(p[[24,66,6808,6850],2].mean());ey=float(p[[24,66,6808,6850],1].mean())
        cheek=(abs(p[:,0])>.12*h)&(abs(p[:,0])<.29*h)&(p[:,2]>ez-.23*h)&(p[:,2]<ez-.09*h)&(p[:,1]<ey+.06*h)
        w,hh=source.size;pixels=_pixels(source).reshape(hh,w,4)
        uv=body.data.uv_layers.active.data
        loops=[i for i,loop in enumerate(body.data.loops) if loop.vertex_index<13380 and cheek[loop.vertex_index]]
        if loops:
            xy=np.array([uv[i].uv for i in loops])*[w,hh]
            xy=np.clip(xy.astype(int),[0,0],[w-1,hh-1]);samples=pixels[xy[:,1],xy[:,0],:3]
        else:samples=pixels.reshape(-1,4)[::251,:3]
        rgb = np.median(samples,axis=0)
        skin = srgb_to_linear(rgb) if source.colorspace_settings.name=='sRGB' else tuple(rgb)
    else:
        skin = tuple(body.material_slots[0].material.diffuse_color[:3])
    return tuple(float(v) for v in skin)


def fit_proportions(body,meshes,rig,style,refit=True):
    bottom, top, chin, eyes = anatomy(body, meshes)
    joints={}
    if rig:
        from .anim import heuristic_map
        names=heuristic_map(rig)
        matrix=body.matrix_world.inverted() @ rig.matrix_world
        for side in 'LR':
            for landmark,bone in (('shoulder','upper_arm'),('wrist','hand')):
                name=names.get(bone+'.'+side)
                if name:joints[landmark+'.'+side]=list(matrix @ rig.data.bones[name].head_local)
    body['c3d_toon_before']=json.dumps(face_metrics(body,meshes))
    mapping = RestMap(style, bottom, top, chin, eyes, joints=joints)
    transform_family(body, meshes, mapping, rig,refit=refit)
    fit_eye_depth(body,meshes)
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
    from .materials import _sample_skin,_eye_frame
    reference=tuple(body.get('c3d_toon_scan_reference')) if body.get('c3d_toon_scan_reference') is not None else _sample_skin(body,body.material_slots[0].material,_eye_frame(meshes,body)[0])
    fit_proportions(body,meshes,rig,style,refit=False)
    body['c3d_toon_prefit'] = json.dumps(dict(style=style,skin=skin,skin_reference=reference))


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
            corrections[n] = closed[j]-closed[i]
            if i!=j:corrections[n,1] -= .00003
        radius = max(.004,np.ptp(anchors[:,0])*.6)
        def kernel(points):
            return np.exp(-np.square(np.asarray(points)[:,None,:]-anchors[None,:,:]).sum(axis=2)/(2*radius*radius))
        # Positive normalized kernels avoid extrapolation ripples on the nose
        # and brow. The actual boundary is pinned exactly below.
        coefficients = corrections
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
            if obj is body:
                gate[[i for i,j in pairs]]=1.
                gate[[j for i,j in pairs]]=0.
            influence=kernel(points)
            falloff=np.max(influence,axis=1)
            offset=((influence @ coefficients)/np.maximum(influence.sum(1,keepdims=True),1e-12))*falloff[:,None]*gate[:,None]
            target += (offset @ inverse[:3,:3].T).astype(np.float32)
            if obj is body:
                for upper,lower in pairs:
                    target[upper]=closed[lower]
                    if upper!=lower:target[upper,1]-=.00003
            if _role(obj,body)=='eyes':
                # Enlarged rigid inserts otherwise peek through the thin closed
                # lids. A continuous native morph recesses just this eye behind
                # the lid; there is no visibility switch or alpha animation.
                selected = points[:,0]*(1 if side=='L' else -1)>0
                depth = float(np.ptp(points[selected,1]))*.8
                recess = np.array([0.,depth,0.]) @ inverse[:3,:3].T
                target=base.copy()  # a unilateral blink must leave the other eye neutral
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
    skin = np.asarray(skin,dtype=float)
    skin *= min(1.,1/max(1.,float(np.max(skin))))
    hair = hair or _hair_color(meshes, body) or (.035, .023, .02)
    hair=tuple(np.asarray(hair)*max(1.,.025/max(.0001,max(hair))))
    atlas = image('c3d_toon.original_iris.'+body.name, iris_pixels(color=iris or (.16, .38, .64)))
    _, top, chin, centers = anatomy(body, meshes)
    changed = []
    for obj in meshes:
        role = _role(obj, body)
        if role == 'accessory':
            continue
        tex = None
        if role == 'skin':
            p = coords(obj.data.shape_keys.key_blocks[0].data if obj.data.shape_keys else obj.data.vertices)
            _, top, chin, centers = anatomy(body, meshes)
            h = top-chin
            ez = np.mean(centers, axis=0)[2]
            blush = np.exp(-.5*((np.abs(p[:, 0])-.22*h)/(.13*h))**2
                           -.5*((p[:, 2]-ez+.15*h)/(.10*h))**2)
            from ..toon import smooth
            blush *= (1-smooth_front(p[:, 1], centers))*smooth((p[:,2]-chin)/(.16*h))
            # Soft cheek value modulation, without mixing a fixed pink pigment.
            colors = np.asarray(skin)[None, :]*(1+blush[:,None]*.08)
            colors /= np.maximum(1.,colors.max(axis=1,keepdims=True))
            tex = uv_image(obj, colors)
        elif role == 'eyes':
            tex = atlas
            uv = obj.data.uv_layers.get('c3d_toon_iris') or obj.data.uv_layers.new(name='c3d_toon_iris')
            # One planar iris per eye, with white outside its circular limbus.
            matrix = body.matrix_world.inverted() @ obj.matrix_world
            ep = np.array([matrix @ v.co for v in obj.data.vertices])
            _, _, _, centers = anatomy(body, meshes)
            radius = (.085 if body.get('c3d_style')=='anime' else .095)*(top-chin)
            for loop in obj.data.loops:
                pt = ep[loop.vertex_index]
                center = min(centers, key=lambda c: abs(c[0]-pt[0]))
                uv.data[loop.index].uv = ((pt[0]-center[0])/(2*radius)+.5, (pt[2]-center[2])/(2*radius)+.5)
        for slot_index,slot in enumerate(obj.material_slots):
            old = slot.material
            if not old:
                continue
            mat = bpy.data.materials.new('c3d_toon.'+role+'.'+old.name)
            mat.use_nodes = True
            mat['c3d_toon_role'] = role
            bsdf = mat.node_tree.nodes.get('Principled BSDF')
            color = tuple(skin) if role == 'skin' else tuple(hair) if role in ('hair','brows') else tuple(old.diffuse_color[:3])
            source = _image(old)
            if role=='mouth':
                color=(.12,.035,.04)
                if 'teeth' in obj.name.lower() and source:
                    from ..toon_appearance import downsample_rgba
                    raw=_pixels(source).reshape(source.size[1],source.size[0],4)
                    small=downsample_rgba(raw,128)
                    tooth=(small[:,:,0]>.6)&(small[:,:,1]>.5)&(small[:,:,2]>.45)
                    small[:,:,:3]=np.where(tooth[:,:,None],[.66,.61,.53],[.10,.025,.033])
                    tex=image('c3d_toon.mouth.'+obj.name,small)
            if role=='clothes':tex=None
            if role=='hair':
                from ..toon_appearance import downsample_rgba
                original=old.get('c3d_toon_hair_albedo') or source
                if original:
                    raw=_pixels(original).reshape(original.size[1],original.size[0],4)
                    small=downsample_rgba(raw,128)
                    brightness=small[:,:,:3]@[.2126,.7152,.0722]
                    valid=small[:,:,3]>.5
                    pivot=float(np.median(brightness[valid])) if valid.any() else .1
                    # Broad clump values rather than photographic strand grain.
                    variation=np.clip(brightness/max(.003,pivot),.65,1.35)
                    pigment=np.ones_like(small);pigment[:,:,:3]=np.asarray(hair)*variation[:,:,None]
                    tex=image('c3d_toon.hair_clumps.'+obj.name,pigment)
            if role == 'clothes' and source and obj.data.uv_layers:
                from ..toon_appearance import downsample_rgba,visible_albedo
                # The old stride sampled x=0 on every 1024-wide row: atlas
                # background replaced a blue printed shirt with white/grey.
                original=old.get('c3d_toon_source_albedo') or source
                pixels=_pixels(original).reshape(original.size[1],original.size[0],4)
                linear=pixels.copy()
                if original.colorspace_settings.name=='sRGB':
                    linear[:,:,:3]=np.where(pixels[:,:,:3]<=.04045,pixels[:,:,:3]/12.92,((pixels[:,:,:3]+.055)/1.055)**2.4)
                small=downsample_rgba(linear)
                obj.data.calc_loop_triangles();uvs=obj.data.uv_layers.active.data
                triangles=np.array([[list(uvs[i].uv) for i in tri.loops] for tri in obj.data.loop_triangles if tri.material_index==slot_index])
                color,_=visible_albedo(small,triangles)
                tex=image('c3d_toon.garment_albedo.'+obj.name,small)
            elif role=='clothes' and old.get('c3d_toon_flat_color') is not None:
                color=tuple(old['c3d_toon_flat_color'])
            if obj.get('c3d_toon_lid_ink') or obj.get('c3d_toon_brow_ink'):color=(.012,.009,.016)
            mat['c3d_toon_flat_color']=[float(v) for v in color]
            if role=='skin':mat['c3d_toon_head_height']=float(top-chin)
            if role=='hair' and original:mat['c3d_toon_hair_albedo']=original
            if role=='clothes' and source and tex:
                mat['c3d_toon_source_albedo']=old.get('c3d_toon_source_albedo') or source
            mat.diffuse_color = (*color, 1)
            bsdf.inputs['Base Color'].default_value = (*color, 1)
            bsdf.inputs['Roughness'].default_value = .75
            bsdf.inputs['Specular IOR Level'].default_value = .15
            if tex:
                node = mat.node_tree.nodes.new('ShaderNodeTexImage')
                node.image = tex
                node.name='Diffuse Texture'
                node.extension = 'EXTEND'
                mat.node_tree.links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
                if role == 'eyes':
                    coords_node = mat.node_tree.nodes.new('ShaderNodeUVMap')
                    coords_node.uv_map = 'c3d_toon_iris'
                    mat.node_tree.links.new(coords_node.outputs[0],node.inputs['Vector'])
            if role=='mouth' and tex:
                mat.node_tree.links.new(node.outputs['Alpha'],bsdf.inputs['Alpha'])
                mat.surface_render_method='DITHERED'
            if role in ('hair','brows','clothes'):
                brow=obj.get('c3d_toon_brow_image')
                part=obj.get('c3d_material_part',obj.name).lower()
                if 'eyelash' in part and not obj.get('c3d_toon_lid_ink'):
                    # Native lid ribbons replace the noisy stock lash cards.
                    bsdf.inputs['Alpha'].default_value=0.
                else:
                    cached_cutout=old.get('c3d_toon_cutout')
                    opacity=brow or cached_cutout or _image(old,'opacity') or source
                    if role=='clothes' and opacity and np.min(_pixels(opacity).reshape(-1,4)[:,3])>.99 and not _image(old,'opacity'):opacity=None
                    if opacity:
                        node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=opacity
                        if brow:
                            uvnode=mat.node_tree.nodes.new('ShaderNodeUVMap');uvnode.uv_map='c3d_toon_brow'
                            mat.node_tree.links.new(uvnode.outputs[0],node.inputs['Vector'])
                        if not brow and not cached_cutout:
                            separate=_image(old,'opacity') is not None
                            pixels=_pixels(opacity).reshape(opacity.size[1],opacity.size[0],4)
                            if role=='hair':
                                from ..toon_appearance import downsample_rgba
                                pixels=downsample_rgba(pixels,256)
                            mask=(pixels[:,:,:3].mean(2) if separate else pixels[:,:,3])>.32
                            rgba=np.ones_like(pixels);rgba[:,:,3]=mask.astype(np.float32)
                            node.image=image('c3d_toon.clean_cutout.'+obj.name,rgba)
                        if not brow:mat['c3d_toon_cutout']=node.image
                        node.name='Opacity Texture'
                        mat.node_tree.links.new(node.outputs['Alpha'],bsdf.inputs['Alpha'])
                mat.surface_render_method='DITHERED'
            slot.link, slot.material = 'OBJECT', mat
            changed.append(mat.name)
    return dict(quality='toon', materials=changed, original_iris=True, pores=False,
                skin_rgb_linear=[float(v) for v in skin])


def smooth_front(y, centers):
    from ..toon import smooth
    return smooth((y-float(np.mean(centers, axis=0)[1])-.01)/.04)


def ink_lids(body, meshes):
    """Original upper/lower lid ribbons with the body's native morphs/weights.

    No drivers, frame handlers or opaque inverted hull over the eyes. Vertex
    sources are the authored HM08 lid margins, so ink follows the actual blink.
    """
    from ..toon import LID_PAIRS,lid_taper
    old=next((o for o in meshes if o.get('c3d_toon_lid_ink')),None)
    if old:return
    keys=body.data.shape_keys.key_blocks if body.data.shape_keys else []
    basis=coords(keys[0].data if keys else body.data.vertices);_,top,chin,_=anatomy(body,meshes);h=top-chin
    sources=[];offsets=[];faces=[]
    for pairs in LID_PAIRS.values():
        for upper,thickness in ((True,.012),(False,.0025)):
            indices=list(dict.fromkeys(pair[0 if upper else 1] for pair in pairs))
            if not upper:indices=indices[3:-3]
            start=len(sources)
            for position,i in enumerate(indices):
                taper=float(lid_taper(position/(len(indices)-1)))
                for edge in (0,1):
                    sources.append(i)
                    offsets.append([0,-.006*h,(1 if upper else -1)*thickness*h*edge*taper])
            for j in range(len(indices)-1):
                a=start+2*j;faces.append((a,a+2,a+3,a+1))
    offsets=np.asarray(offsets)
    # Upper lashes sit on the skin surface rather than disappearing into the
    # brow-side lid bulge. The same static rest offset is carried by every morph.
    from mathutils.bvhtree import BVHTree
    tree=BVHTree.FromPolygons([Vector(v) for v in basis],
                             [list(f.vertices) for f in body.data.polygons if all(i<13380 for i in f.vertices)])
    for index,(source,offset) in enumerate(zip(sources,offsets)):
        point=basis[source]+offset
        hit=tree.ray_cast(Vector((point[0],point[1]-2.,point[2])),Vector((0,1,0)))
        if hit[0] is not None:
            offsets[index,1]+=min(0.,hit[0].y-.0003*h-point[1])
    me=bpy.data.meshes.new(body.name+'.lid_ink')
    me.from_pydata((basis[sources]+offsets).tolist(),[],faces);me.update()
    ink=bpy.data.objects.new(body.name+'.lid_ink',me);bpy.context.collection.objects.link(ink)
    ink.parent=body.parent;ink.matrix_world=body.matrix_world.copy()
    ink['c3d_toon_sources']=json.dumps([[i] for i in sources]);ink['c3d_toon_offsets']=json.dumps(offsets.tolist())
    ink['c3d_toon_lid_ink']=True;ink['c3d_material_part']='eyelashes';ink['c3d_source']='toon_helper'
    for key in keys:
        target=ink.shape_key_add(name=key.name,from_mix=False)
        target.data.foreach_set('co',(coords(key.data)[sources]+offsets).astype(np.float32).ravel())
        target.slider_min=key.slider_min;target.slider_max=key.slider_max
        target.value=key.value
    for group in body.vertex_groups:
        ink.vertex_groups.new(name=group.name)
    for v,source in enumerate(sources):
        for g in body.data.vertices[source].groups:
            ink.vertex_groups[g.group].add([v],g.weight,'REPLACE')
    rig=body.find_armature()
    if rig:
        modifier=ink.modifiers.new('Native skin','ARMATURE');modifier.object=rig
    mat=bpy.data.materials.new('c3d_toon.lid_ink');mat.diffuse_color=(.012,.009,.016,1)
    mat.use_nodes=True;bsdf=mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value=mat.diffuse_color
    bsdf.inputs['Roughness'].default_value=1.;bsdf.inputs['Specular IOR Level'].default_value=0
    ink.data.materials.append(mat);meshes.append(ink)


def simplify_brows(body, meshes):
    """One original skinned ribbon per brow, without overlapping alpha cards."""
    for obj in meshes:
        if 'eyebrow' in obj.get('c3d_material_part',obj.name).lower():
            obj.hide_render=True;obj.hide_viewport=True
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,meshes);h=top-chin
    from ..toon import LID_PAIRS,lid_taper
    from mathutils.bvhtree import BVHTree
    body.data.calc_loop_triangles()
    triangles=np.array([tuple(t.vertices) for t in body.data.loop_triangles if max(t.vertices)<13380])
    tree=BVHTree.FromPolygons([Vector(v) for v in p],triangles.tolist(),all_triangles=True)
    sources=[];weights=[];offsets=[];faces=[]
    for side,pairs in LID_PAIRS.items():
        lid=p[[i for i,j in pairs]];lo,hi=lid[:,0].min(),lid[:,0].max()
        z=float(lid[:,2].max()+.065*h);start=len(sources)
        for t in np.linspace(.08,.92,12):
            x=lo+(hi-lo)*t;zz=z+.014*h*np.sin(np.pi*t)
            hit,_normal,index,_distance=tree.ray_cast(Vector((x,-5,zz)),Vector((0,1,0)))
            if hit is None:raise RuntimeError('Could not fit simple brow to the head surface')
            ids=triangles[index];q=p[ids]
            w=np.linalg.lstsq(np.vstack((q.T,np.ones(3))),np.r_[hit,1.],rcond=None)[0]
            w=np.clip(w,0,1);w/=w.sum()
            for edge in (-1,1):
                sources.append(ids.tolist());weights.append(w.tolist())
                offsets.append([0,-.003*h,edge*.002*h*float(lid_taper(t))])
        for j in range(11):
            k=start+2*j;faces.append((k,k+2,k+3,k+1))
    sources=np.array(sources);weights=np.array(weights);offsets=np.array(offsets)
    points=(p[sources]*weights[:,:,None]).sum(1)+offsets
    me=bpy.data.meshes.new(body.name+'.simple_brows');me.from_pydata(points.tolist(),[],faces);me.update()
    obj=bpy.data.objects.new(me.name,me);bpy.context.collection.objects.link(obj)
    obj.parent=body.parent;obj.matrix_world=body.matrix_world.copy()
    obj['c3d_source']='toon_helper';obj['c3d_material_part']='simple_brows';obj['c3d_toon_brow_ink']=True
    obj['c3d_toon_sources']=json.dumps(sources.tolist());obj['c3d_toon_source_weights']=json.dumps(weights.tolist());obj['c3d_toon_offsets']=json.dumps(offsets.tolist())
    if body.data.shape_keys:
        for key in body.data.shape_keys.key_blocks:
            target=obj.shape_key_add(name=key.name,from_mix=False)
            values=(coords(key.data)[sources]*weights[:,:,None]).sum(1)+offsets
            target.data.foreach_set('co',values.astype(np.float32).ravel())
            target.slider_min=key.slider_min;target.slider_max=key.slider_max
            target.value=key.value
    for group in body.vertex_groups:obj.vertex_groups.new(name=group.name)
    for vertex,(ids,w) in enumerate(zip(sources,weights)):
        combined={}
        for i,factor in zip(ids,w):
            for group in body.data.vertices[int(i)].groups:combined[group.group]=combined.get(group.group,0)+group.weight*float(factor)
        for group,weight in combined.items():
            if weight>0:obj.vertex_groups[group].add([vertex],weight,'REPLACE')
    rig=body.find_armature()
    if rig:obj.modifiers.new('Native skin','ARMATURE').object=rig
    mat=bpy.data.materials.new('c3d_toon.simple_brow');mat.diffuse_color=(.025,.018,.012,1);mat.use_nodes=True
    mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=mat.diffuse_color
    obj.data.materials.append(mat);meshes.append(obj)


LIP_PAIRS=((520,540),(521,538),(7267,7282))


def face_metrics(body,meshes):
    """Rest mesh measurements in meters, excluding hair and fitting cages."""
    from ..toon import LID_PAIRS
    p=neutral_coords(body);bottom,top,chin,eyes=anatomy(body,meshes,p);h=top-chin
    face=p[:13380];front=face[(face[:,2]>chin+.15*h)&(face[:,2]<chin+.85*h)&
                              (face[:,1]<np.mean(eyes,axis=0)[1]+.04*h)]
    width=float(np.ptp(front[:,0]))
    rims=np.array(LID_PAIRS['R']);eye_width=float(np.ptp(p[rims.ravel(),0]))
    eye_height=float(max(p[rims[:,0],2])-min(p[rims[:,1],2]))
    gaps={}
    if body.data.shape_keys:
        keys=body.data.shape_keys.key_blocks
        for name in ('aa_02','ow_08','p_b_m_21'):
            if name not in keys:continue
            key=keys[name];q=p+coords(key.data)-coords(key.relative_key.data)
            if name=='p_b_m_21' and 'mouthClose' in keys:
                close=keys['mouthClose'];q+=.1*(coords(close.data)-coords(close.relative_key.data))
            gaps[name]=float(max(abs(q[a,2]-q[b,2]) for a,b in LIP_PAIRS))
    return dict(head_ratio=float((top-bottom)/h),face_height_m=h,face_width_m=width,
                eye_height_m=eye_height,eye_width_m=eye_width,
                eye_height_face_height=eye_height/h,eye_width_face_width=eye_width/width,
                lip_gap_m=gaps)


def fit_eye_depth(body,meshes):
    """Flatten toon eye inserts behind the lid rim so gaze cannot paint over skin."""
    from ..toon import LID_PAIRS
    from .materials import _role
    basis=neutral_coords(body);_,top,chin,_=anatomy(body,meshes);h=top-chin
    for obj in meshes:
        if _role(obj,body)!='eyes':continue
        matrix=body.matrix_world.inverted() @ obj.matrix_world
        m=np.array(matrix);inv=np.array(matrix.inverted())
        p=coords(obj.data.shape_keys.key_blocks[0].data if obj.data.shape_keys else obj.data.vertices)
        reference=p @ m[:3,:3].T+m[:3,3]
        fits=[]
        for side,sign in (('R',-1),('L',1)):
            selected=reference[:,0]*sign>0
            center=(reference[selected,1].min()+reference[selected,1].max())*.5
            front=(reference[selected,1].min()-center)*.45+center
            rim=max(basis[i,1] for pair in LID_PAIRS[side] for i in pair)
            fits.append((selected,center,rim+.002*h-front))
        for data in [obj.data.vertices]+([k.data for k in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else []):
            q=coords(data) @ m[:3,:3].T+m[:3,3]
            for selected,center,offset in fits:q[selected,1]=center+(q[selected,1]-center)*.45+offset
            data.foreach_set('co',((q @ inv[:3,:3].T+inv[:3,3]).astype(np.float32)).ravel())


def calibrate_bilabials(body):
    """Close the native M/B/P lip seam including lip_sync's 10% mouthClose layer."""
    keys=body.data.shape_keys.key_blocks if body.data.shape_keys else {}
    if 'p_b_m_21' not in keys or 'mouthClose' not in keys:return
    basis=coords(keys[0].data);target=coords(keys['p_b_m_21'].data)
    mix=target+.1*(coords(keys['mouthClose'].data)-basis)
    pairs=np.array(LIP_PAIRS);anchors=basis[pairs[:,0]]
    delta=mix[pairs[:,1],2]-mix[pairs[:,0],2]
    radius=.008*float(body.get('c3d_toon_head_scale',1))
    def kernel(points):return np.exp(-np.square(points[:,None,:]-anchors).sum(2)/(2*radius*radius))
    coef=np.linalg.solve(kernel(anchors)+np.eye(len(anchors))*1e-7,delta)
    lower=float(basis[pairs[:,1],2].mean());upper=float(basis[pairs[:,0],2].mean())
    from ..toon import smooth
    gate=smooth((basis[:,2]-lower)/max(.0001,upper-lower))
    gate[pairs[:,0]]=1;gate[pairs[:,1]]=0
    target[:,2]+=kernel(basis) @ coef*gate
    keys['p_b_m_21'].data.foreach_set('co',target.ravel())


def smooth_head(body):
    """Fixed linear rest smoothing on cheeks/forehead, preserving all lid/lip rims."""
    from ..toon import smooth,LID_PAIRS
    p=neutral_coords(body);_,top,chin,_=anatomy(body,[]);h=top-chin
    edges=np.array([tuple(e.vertices) for e in body.data.edges],int)
    edges=edges[(edges<13380).all(1)]
    a,b=np.r_[edges[:,0],edges[:,1]],np.r_[edges[:,1],edges[:,0]]
    weight=smooth((p[:,2]-chin)/(.1*h))*(1-smooth((p[:,2]-top+.05*h)/(.05*h)))
    weight[13380:]=0
    protect={i for pairs in LID_PAIRS.values() for pair in pairs for i in pair}
    protect.update(i for pair in LIP_PAIRS for i in pair)
    protect.update((881,791,13137))
    # Fade the constraint over four rings. A hard protected/unprotected border
    # beside the lids had left a notch at the cheek/jaw transition.
    distance=np.full(len(p),5);distance[list(protect)]=0
    for level in range(1,5):
        near=(distance[a]<level)&(distance[b]>level)
        distance[b[near]]=level
    weight*=smooth(distance/4.)
    degree=np.bincount(a,minlength=len(p));valid=degree>0
    for data in [body.data.vertices]+([k.data for k in body.data.shape_keys.key_blocks] if body.data.shape_keys else []):
        q=coords(data)
        # Taubin pairs smooth without repeatedly shrinking the head silhouette.
        for _ in range(8):
            for amount in (.48,-.49):
                sums=np.zeros_like(q);np.add.at(sums,a,q[b]);mean=sums/np.maximum(degree[:,None],1)
                q+=(mean-q)*weight[:,None]*valid[:,None]*amount
        data.foreach_set('co',q.astype(np.float32).ravel())
    for face in body.data.polygons:face.use_smooth=True
    body.data.update()


def round_jaw(body):
    """Fill the local cheek/jaw notch without changing topology or articulation."""
    import bmesh
    from mathutils.bvhtree import BVHTree
    from ..toon import smooth,LID_PAIRS
    p=neutral_coords(body);_,top,chin,_=anatomy(body,[]);h=top-chin
    ey=float(p[[24,66,6808,6850],1].mean());u=(p[:,2]-chin)/h
    selected=(np.arange(len(p))<13380)&(u>=0)&(u<=1)&(abs(p[:,0])<.40*h)&(p[:,1]<ey+.40*h)
    bm=bmesh.new()
    try:
        vertices=[bm.verts.new(Vector(v)) for v in p[selected]]
        bmesh.ops.convex_hull(bm,input=vertices,use_existing_faces=False);bm.normal_update()
        hull=BVHTree.FromBMesh(bm)
        weight=smooth((u-.025)/.10)*(1-smooth((u-.34)/.19))
        weight*=smooth((abs(p[:,0])-.10*h)/(.12*h))*(1-smooth((abs(p[:,0])-.33*h)/(.06*h)))
        weight*=1-smooth((p[:,1]-ey-.12*h)/(.20*h));weight[13380:]=0
        for pairs in LID_PAIRS.values():
            weight[list({i for pair in pairs for i in pair})]=0
        delta=np.zeros_like(p)
        for i in np.flatnonzero(weight>.001):
            point,normal,index,distance=hull.find_nearest(Vector(p[i]))
            if point is not None:
                delta[i]=(np.asarray(point)-p[i])*weight[i]*min(1.,.05*h/max(1e-9,distance))
    finally:bm.free()
    for data in [body.data.vertices]+([key.data for key in body.data.shape_keys.key_blocks] if body.data.shape_keys else []):
        data.foreach_set('co',(coords(data)+delta).astype(np.float32).ravel())
    body['c3d_toon_jaw_round_m']=float(np.max(np.linalg.norm(delta,axis=1)))


def head_surface(body):
    """Render subdivision, with creased body edges retaining the non-head surface.

    Viewport level zero retains HM08 index correspondence, native morph export,
    weights and photo fitting. Saved renders use two Catmull-Clark levels.
    """
    p=neutral_coords(body);_,top,chin,_=anatomy(body,[]);h=top-chin
    eye_y=float(p[[24,66,6808,6850],1].mean())
    omit=[]
    for face in body.data.polygons:
        if any(i>=13380 for i in face.vertices):continue
        center=p[list(face.vertices)].mean(0)
        if abs(center[0])<.23*h and center[1]<eye_y+.035*h and chin+.30*h<center[2]<top-.15*h:
            omit.append(face.index)
    # Facial ink is authored by lids/brows and the mouth contour. The expanded
    # silhouette shell must not leak a black stroke down a tiny nose bridge.
    body['c3d_toon_outline_omit']=omit
    body['c3d_toon_outline_face_count']=len(body.data.polygons)
    from ..toon import smooth
    crease=body.data.attributes.get('crease_edge') or body.data.attributes.new('crease_edge','FLOAT','EDGE')
    values=[]
    from ..toon import LID_PAIRS
    rims={i for pairs in LID_PAIRS.values() for pair in pairs for i in pair}
    for edge in body.data.edges:
        i,j=edge.vertices
        value=1-float(smooth((min(p[i,2],p[j,2])-chin+.12*h)/(.18*h)))
        neck=smooth((min(p[i,2],p[j,2])-chin+.42*h)/(.30*h))
        neck*=1-smooth((max(abs(p[i,0]),abs(p[j,0]))-.23*h)/(.10*h))
        value*=1-float(neck)
        if i>=13380 or j>=13380 or i in rims or j in rims:value=1.
        values.append(value)
    crease.data.foreach_set('value',np.asarray(values,np.float32))
    mod=body.modifiers.get('__c3d_toon_head_surface') or body.modifiers.new('__c3d_toon_head_surface','SUBSURF')
    mod.levels=0;mod.render_levels=2;mod.subdivision_type='CATMULL_CLARK'
    body['c3d_toon_surface']='render subdivision 2; creased non-head; portable base uses smooth normals/rest smoothing'


def fit_hair(body,meshes):
    """Shorten only front fringe over the eye window; retain skin/morph weights."""
    from .materials import _role
    from ..toon import smooth,LID_PAIRS
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,meshes,p);h=top-chin
    ez=float(np.mean(eyes,0)[2]);ey=float(np.mean(eyes,0)[1])
    outer=max(abs(float(p[i,0])) for pairs in LID_PAIRS.values() for pair in pairs for i in pair)
    for obj in meshes:
        if _role(obj,body)!='hair':continue
        m=np.array(body.matrix_world.inverted()@obj.matrix_world);inv=np.linalg.inv(m)
        source=coords(obj.data.shape_keys.key_blocks[0].data if obj.data.shape_keys else obj.data.vertices)
        q=source@m[:3,:3].T+m[:3,3]
        front=1-smooth((q[:,1]-ey-.015*h)/(.10*h))
        window=1-smooth((abs(q[:,0])-outer-.035*h)/(.12*h))
        # Uneven tips keep a broad clump edge; the lowest point clears the brow.
        floor=ez+h*(.16+.012*np.cos(q[:,0]/h*38))
        lift=np.maximum(0,floor-q[:,2])*front*window
        delta=np.zeros_like(q);delta[:,2]=lift;delta=delta@inv[:3,:3].T
        for data in [obj.data.vertices]+([k.data for k in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else []):
            data.foreach_set('co',(coords(data)+delta).astype(np.float32).ravel())
        obj['c3d_toon_fringe_lift_m']=float(lift.max())
        obj.data.update()


def fit_mouth(body,meshes):
    """Keep teeth/tongue behind the lip plane and below the nose for all morphs."""
    from .materials import _role
    p=neutral_coords(body);upper,lower=p[520],p[540];center=(upper+lower)*.5
    _,top,chin,_=anatomy(body,meshes);h=top-chin
    mouth_parts=[o for o in meshes if _role(o,body)=='mouth']
    body_keys=body.data.shape_keys.key_blocks if body.data.shape_keys else {}
    for obj in mouth_parts:
        matrix=body.matrix_world.inverted()@obj.matrix_world;m=np.array(matrix);inv=np.array(matrix.inverted())
        base=coords(obj.data.vertices)@m[:3,:3].T+m[:3,3]
        mid=(base.min(0)+base.max(0))*.5
        # The broad original dentition needs a smaller vertical envelope too.
        blocks=[(obj.data.vertices,None)]+([(k.data,k.name) for k in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else [])
        for data,name in blocks:
            q=coords(data)@m[:3,:3].T+m[:3,3]
            face=coords(body_keys[name].data) if name is not None and name in body_keys else p
            lips=np.array(LIP_PAIRS)
            low=float(face[lips[:,1],2].min());high=float(face[lips[:,0],2].max())
            target_center=(low+high)*.5
            half=max(.004*h,abs(high-low)*.42)
            q[:,0]*=.78
            q[:,0]*=min(1.,.07*h/max(.0001,float(np.max(abs(q[:,0])))))
            q[:,2]=np.clip(target_center+(q[:,2]-mid[2])*.48,target_center-half,target_center+half)
            lip_plane=float(face[lips.ravel(),1].max())
            # The stock dental proxies are ~8 cm deep: merely recessing their
            # fronts leaves their backs outside a flattened toon jaw, visible
            # below the chin during a nod. Keep the whole volume behind the lips.
            q[:,1]=np.clip(q[:,1]+.045*h,lip_plane+.045*h,lip_plane+.09*h)
            data.foreach_set('co',((q@inv[:3,:3].T+inv[:3,3]).astype(np.float32)).ravel())


def lift_smile(body,meshes):
    from .materials import _role
    from ..toon import smooth
    p=neutral_coords(body);_,top,chin,_=anatomy(body,meshes);h=top-chin
    mouth_z=float((p[520,2]+p[540,2])*.5)
    mouth_y=float((p[520,1]+p[540,1])*.5)
    for obj in meshes:
        if not obj.data.shape_keys or _role(obj,body)=='mouth':continue
        matrix=np.array(body.matrix_world.inverted()@obj.matrix_world)
        keys=obj.data.shape_keys.key_blocks
        for name in ('mouthSmileLeft','mouthSmileRight'):
            if name not in keys:continue
            key=keys[name];base=coords(key.relative_key.data);delta=coords(key.data)-base
            points=base@matrix[:3,:3].T+matrix[:3,3]
            mouth=np.exp(-.5*(points[:,0]/(.15*h))**4-.5*((points[:,2]-mouth_z)/(.07*h))**2)
            mouth*=1-smooth((points[:,1]-mouth_y-.03*h)/(.20*h))
            authored=np.linalg.norm(delta,axis=1)*mouth
            mean_x=float(np.dot(points[:,0],authored)/max(1e-12,authored.sum()))
            sign=np.sign(mean_x) if abs(mean_x)>.003*h else (1 if name.endswith('Left') else -1)
            corners=smooth(abs(points[:,0])/(.06*h))*smooth(sign*points[:,0]/(.02*h))
            # Keep the centre steady: native centre lift can cancel the corner
            # rise on a small mouth. The bounded, smooth curve stays on the face.
            delta[:,2]=delta[:,2]*(1-mouth)+.032*h*corners*mouth
            delta[:,0]*=1+.35*corners*mouth
            delta[:,2]=np.clip(delta[:,2],-.055*h,.055*h)
            # The stock smile's broad cheek pull reintroduced the contour notch
            # at full expression. Keep articulation at the lips, soften it at
            # the outer cheek/jaw silhouette on every fitted proxy.
            profile=smooth((abs(points[:,0])-.16*h)/(.10*h))
            profile*=np.exp(-((points[:,2]-mouth_z)/(.25*h))**4)
            profile*=1-smooth((points[:,1]-mouth_y-.03*h)/(.20*h))
            delta*=1-.85*profile[:,None]
            key.data.foreach_set('co',(base+delta).ravel())


def fit_ankles(body,meshes):
    """Tuck stock shoe uppers under worn trousers; sole/contact stays unchanged."""
    from .materials import _role
    if not any('pants' in o.name.lower() or 'casualsuit' in o.name.lower() for o in meshes):return
    for obj in meshes:
        if not any(n in obj.name.lower() for n in ('shoes','boots')):continue
        base=coords(obj.data.vertices)
        centers={sign:np.median(base[base[:,0]*sign>0],axis=0) for sign in (-1,1)}
        from ..toon import smooth
        gate=smooth((base[:,2]-base[:,2].min()-.045)/.055)
        for data in [obj.data.vertices]+([k.data for k in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else []):
            p=coords(data)
            for sign in (-1,1):
                select=base[:,0]*sign>0;center=centers[sign]
                p[select,:2]=center[:2]+(p[select,:2]-center[:2])*(1-.38*gate[select,None])
            data.foreach_set('co',p.ravel())
        # Shoe tops are covered by the trousers but can leak through authored
        # torn-denim openings. Delete those hidden uppers in Blender edit mode,
        # which remaps every native shape key and skin group consistently.
        threshold=float(base[:,2].min()+np.ptp(base[:,2])*.40)
        active=bpy.context.view_layer.objects.active
        selected=list(bpy.context.selected_objects)
        try:
            for item in selected:item.select_set(False)
            obj.select_set(True);bpy.context.view_layer.objects.active=obj
            obj.active_shape_key_index=0
            bpy.ops.object.mode_set(mode='EDIT')
            import bmesh
            bm=bmesh.from_edit_mesh(obj.data)
            for vertex in bm.verts:vertex.select=vertex.co.z>threshold
            bmesh.update_edit_mesh(obj.data)
            bpy.ops.mesh.delete(type='VERT')
        finally:
            if obj.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            obj.select_set(False)
            for item in selected:item.select_set(True)
            bpy.context.view_layer.objects.active=active


def sync_ink(body,meshes):
    """Update native helper targets after a photo/rest fit; retain animation curves."""
    for obj in meshes:
        if not obj.get('c3d_toon_sources'):continue
        sources=np.array(json.loads(obj['c3d_toon_sources']),int)
        weights=np.array(json.loads(obj.get('c3d_toon_source_weights','[]')))
        if not weights.size:weights=np.ones(sources.shape)
        offsets=np.array(json.loads(obj['c3d_toon_offsets']))
        keys=body.data.shape_keys.key_blocks
        for data,source in [(obj.data.vertices,keys[0].data)]+[(k.data,keys[k.name].data) for k in obj.data.shape_keys.key_blocks if k.name in keys]:
            values=(coords(source)[sources]*weights[:,:,None]).sum(1)+offsets
            data.foreach_set('co',values.astype(np.float32).ravel())
        for key in obj.data.shape_keys.key_blocks:
            if key.name in keys:
                source=keys[key.name]
                key.slider_min=source.slider_min;key.slider_max=source.slider_max
                key.value=source.value
