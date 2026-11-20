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
    calibrate_bilabials(body)
    simplify_brows(body,meshes)
    ink_lids(body,meshes)
    material_report = toon_materials(body, meshes, skin=skin)
    bottom, top, chin, _ = anatomy(body, meshes)
    body['c3d_head_ratio'] = float((top-bottom)/(top-chin))
    return dict(style=style, head_ratio=body['c3d_head_ratio'], head_height_m=top-chin,
                sampled_skin_rgb=skin, blink=blink_report, measurements=face_metrics(body,meshes),
                before=json.loads(body.get('c3d_toon_before','{}')),
                recommended_render_style='anime', materials=material_report)


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
            from ..toon import smooth
            blush *= (1-smooth_front(p[:, 1], centers))*smooth((p[:,2]-chin)/(.16*h))
            colors = np.asarray(skin)[None, :]*(1-blush[:, None]*.16)+np.array([.65,.16,.18])*blush[:, None]*.16
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
            if obj.get('c3d_toon_lid_ink'):color=(.012,.009,.016)
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
            if role in ('hair','brows'):
                brow=obj.get('c3d_toon_brow_image')
                part=obj.get('c3d_material_part',obj.name).lower()
                if 'eyelash' in part and not obj.get('c3d_toon_lid_ink'):
                    # Native lid ribbons replace the noisy stock lash cards.
                    bsdf.inputs['Alpha'].default_value=0.
                else:
                    cached_cutout=old.get('c3d_toon_cutout')
                    opacity=brow or cached_cutout or _image(old,'opacity') or source
                    if opacity:
                        node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=opacity
                        if brow:
                            uvnode=mat.node_tree.nodes.new('ShaderNodeUVMap');uvnode.uv_map='c3d_toon_brow'
                            mat.node_tree.links.new(uvnode.outputs[0],node.inputs['Vector'])
                        if not brow and not cached_cutout:
                            separate=_image(old,'opacity') is not None
                            pixels=_pixels(opacity).reshape(opacity.size[1],opacity.size[0],4)
                            mask=(pixels[:,:,:3].mean(2) if separate else pixels[:,:,3])>.32
                            rgba=np.ones_like(pixels);rgba[:,:,3]=mask.astype(np.float32)
                            node.image=image('c3d_toon.clean_cutout.'+obj.name,rgba)
                        if not brow:mat['c3d_toon_cutout']=node.image
                        node.name='Opacity Texture'
                        mat.node_tree.links.new(node.outputs['Alpha'],bsdf.inputs['Alpha'])
                mat.surface_render_method='DITHERED'
            slot.link, slot.material = 'OBJECT', mat
            changed.append(mat.name)
    return dict(quality='toon', materials=changed, original_iris=True, pores=False)


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
    ink['c3d_toon_lid_ink']=True;ink['c3d_material_part']='eyelashes';ink['c3d_source']='mpfb'
    for key in keys:
        target=ink.shape_key_add(name=key.name,from_mix=False)
        target.data.foreach_set('co',(coords(key.data)[sources]+offsets).astype(np.float32).ravel())
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
    """Thin arched brows, with smooth original alpha instead of photographed hairs."""
    _,top,chin,eyes=anatomy(body,meshes);h=top-chin
    from .materials import _role
    for obj in meshes:
        if 'eyebrow' not in obj.get('c3d_material_part',obj.name).lower():continue
        basis=coords(obj.data.shape_keys.key_blocks[0].data if obj.data.shape_keys else obj.data.vertices)
        changed=[]
        for data in ([obj.data.vertices]+[k.data for k in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else [obj.data.vertices]):
            p=coords(data)
            for sign in (-1,1):
                selection=basis[:,0]*sign>0
                center=np.mean(basis[selection],axis=0)
                p[selection,2]=center[2]+(p[selection,2]-center[2])*.50
            data.foreach_set('co',p.ravel())
        uv=obj.data.uv_layers.get('c3d_toon_brow') or obj.data.uv_layers.new(name='c3d_toon_brow')
        for sign in (-1,1):
            selection=basis[:,0]*sign>0;lo=basis[selection].min(0);hi=basis[selection].max(0)
            for loop in obj.data.loops:
                pt=basis[loop.vertex_index]
                if pt[0]*sign>0:uv.data[loop.index].uv=((pt[0]-lo[0])/(hi[0]-lo[0]),(pt[2]-lo[2])/max(1e-6,hi[2]-lo[2]))
        y,x=np.mgrid[0:128,0:256];x=x/255;y=y/127
        arc=.45+.20*np.sin(x*np.pi)
        alpha=((abs(y-arc)<.14*np.sin(np.pi*x)**.35)&(x>.02)&(x<.98)).astype(np.float32)
        rgba=np.ones((128,256,4),np.float32);rgba[:,:,:3]=(.035,.022,.018);rgba[:,:,3]=alpha
        obj['c3d_toon_brow_image']=image('c3d_toon.simple_brow',rgba)


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
