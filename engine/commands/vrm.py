"""Import through VRM Add-on for Blender, then bake portable char3d morph aliases."""
import json

import addon_utils
import bpy
import numpy as np

from ..vrm import addon_bones, addon_expressions, bone_map, expression_map, eye_rotation_delta, face_regions
from .toon import coords

INSTALL = ('VRM Add-on for Blender is required for .vrm (0.x/1.0). '
           'Run scripts/install_vrm.sh, install its verified extension ZIP in Blender, '
           'then restart the char3d engine. No runtime downloads.')


def enable_addon():
    modules = [m.__name__ for m in addon_utils.modules()
               if m.__name__ == 'io_scene_vrm' or m.__name__.endswith('.vrm')]
    if not modules:
        raise RuntimeError(INSTALL)
    for name in modules:
        # VRM 4.x consults its in-memory preferences even in factory startup.
        # Register that entry without saving user preferences to disk.
        addon_utils.enable(name, default_set=True)


def import_vrm(path):
    enable_addon()
    try:
        operator = bpy.ops.import_scene.vrm
        operator.get_rna_type()
    except (AttributeError,RuntimeError):
        raise RuntimeError(INSTALL) from None
    if 'FINISHED' not in operator('EXEC_DEFAULT', filepath=path):
        raise RuntimeError('VRM add-on cancelled import; inspect model validity/licence requirements.')


def setup(rig):
    extension = getattr(rig.data, 'vrm_addon_extension', None)
    if extension is None:
        raise RuntimeError('VRM add-on imported an armature without VRM metadata')
    v1 = str(extension.spec_version).startswith('1')
    source = addon_bones(extension)
    mapped, fingers = bone_map(source)
    rig['c3d_bone_map'] = json.dumps(mapped)
    rig['c3d_finger_map'] = json.dumps(fingers)
    rig['c3d_rig_type'] = 'vrm'
    rig['c3d_vrm_version'] = '1.0' if v1 else '0.x'
    # Some VRoid files connect hips to a non-humanoid Root at the same point.
    # char3d writes locomotion/seating translation on hips; Blender silently
    # ignores that translation on a connected bone. Disconnect without moving
    # either endpoint, changing bind matrices or replacing the authored rig.
    hips = rig.data.bones.get(mapped.get('hips', ''))
    if hips and hips.use_connect:
        selected = list(bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active
        try:
            for obj in selected:obj.select_set(False)
            rig.select_set(True)
            bpy.context.view_layer.objects.active = rig
            bpy.ops.object.mode_set(mode='EDIT')
            rig.data.edit_bones[mapped['hips']].use_connect = False
        finally:
            if rig.mode != 'OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            rig.select_set(False)
            for obj in selected:obj.select_set(True)
            bpy.context.view_layer.objects.active = active
    from .vrm_secondary import snapshot
    spring_chains = snapshot(rig)
    from .anim import _rig_landmarks
    # VRM permits omitted chest/neck/shoulder bones. Infer proxy landmarks only;
    # do not invent deform bones or send two semantic channels to the same bone.
    extraction = dict(mapped)
    for target,fallback in (('chest','spine'),('neck','head'),('shoulder.L','upper_arm.L'),('shoulder.R','upper_arm.R')):
        if target not in extraction and fallback in extraction:
            extraction[target] = extraction[fallback]
    landmarks = _rig_landmarks(rig,extraction)
    if 'chest' not in mapped:
        landmarks['chest'] = landmarks['waist'].lerp(landmarks['chin'],.5)
        landmarks['upper_chest'] = landmarks['chest'].lerp(landmarks['chin'],.55)
    if 'neck' not in mapped:
        landmarks['neck_base'] = landmarks['chest'].lerp(landmarks['chin'],.75)
        landmarks['neck'] = landmarks['neck_base'].lerp(landmarks['chin'],.5)
    for side in 'LR':
        if 'shoulder.'+side not in mapped:
            landmarks['clavicle.'+side] = landmarks['upper_chest'].lerp(landmarks['shoulder.'+side],.25)
    rig['c3d_landmarks'] = json.dumps({k:list(v) for k,v in landmarks.items()})
    expressions = addon_expressions(extension)
    warnings = ['Material/UV expression binds stay in VRM metadata; char3d aliases cover morphs only.']
    # Native spring simulation stays disabled: deterministic offline animation.
    spring = getattr(extension, 'spring_bone1', None)
    if spring and hasattr(spring,'enable_animation'):
        spring.enable_animation = False
    channels = expression_map(expressions)
    created = []
    meshes = [m for m in rig.children_recursive if m.type == 'MESH']
    for mesh in meshes:
        mesh['c3d_source'] = 'vrm'
        mesh['c3d_rig'] = rig.name
    hip_name = mapped.get('hips')
    def pelvis_vertices(mesh):
        group = mesh.vertex_groups.get(hip_name) if hip_name else None
        return sum(any(g.group == group.index and g.weight > .1 for g in v.groups)
                   for v in mesh.data.vertices) if group else 0
    body = max(meshes, key=pelvis_vertices, default=None)
    if body and pelvis_vertices(body):body['c3d_vrm_body'] = True
    created += bone_gaze(rig,meshes,source,set(channels))
    faces = []
    for mesh in [m for m in meshes if m.data.shape_keys]:
        keys = mesh.data.shape_keys.key_blocks
        basis = coords(keys[0].data)
        regions = semantic_regions(mesh, rig, source, basis)
        for channel, binds in channels.items():
            if channel in keys:
                continue
            delta = np.zeros_like(basis)
            matched = False
            for objname, shape, weight in binds:
                if objname != mesh.name or shape not in keys:
                    continue
                target = keys[shape]
                delta += (coords(target.data)-coords(target.relative_key.data))*weight
                matched = True
            if matched:
                region = ('mouth' if channel.startswith(('mouthSmile','mouthDimple','mouthFrown')) else
                          'eye' if channel.startswith('eyeWide') else 'brow' if channel.startswith('brow') else None)
                if regions is not None and region:
                    delta *= regions[region][:,None]
                key = mesh.shape_key_add(name=channel, from_mix=False)
                key.relative_key = keys[0]
                key.data.foreach_set('co',(basis+delta).ravel())
                # Blender can initialize newly added keys at one. Uncontrolled
                # vowel aliases would then all deform the imported face at once.
                key.value = 0.0
                created.append(channel)
        if regions is not None:
            mesh['c3d_vrm_semantic_regions'] = True
        if any(k in mesh.data.shape_keys.key_blocks for k in channels) or any(k.startswith('eyeLook') for k in mesh.data.shape_keys.key_blocks.keys()):
            # _ensure_face recognizes native aliases without trying MPFB downloads.
            mesh['c3d_source'] = 'vrm'
            mesh['c3d_rig'] = rig.name
            faces.append(mesh)
    if faces:
        max(faces,key=lambda m:len(m.data.shape_keys.key_blocks))['c3d_kind'] = 'humanoid'
    warnings += ['VRM models carry their own licences; the user must have permission to use this model.',
                 'VRM hair/clothing springs can be baked with secondary_motion; vowel-only rigs approximate consonants.',
                 'Combined Blink cannot provide independent winks; absent expressions remain unavailable.']
    return dict(armature=rig.name, version=rig['c3d_vrm_version'], mapped_bones=mapped, spring_chains=spring_chains,
                semantic_face_regions=[m.name for m in meshes if m.get('c3d_vrm_semantic_regions')],
                finger_sides=sorted(fingers), expression_channels=sorted(set(created)), warnings=warnings)


def semantic_regions(mesh, rig, source, basis):
    """Calibrate known VRoid face regions from mouth/brow materials and eye bones.

    Generic VRM layouts retain their original whole-preset aliases. Original
    authored keys, including all eyelid/iris closure geometry, stay untouched.
    """
    def vertices(word):
        slots={i for i,s in enumerate(mesh.material_slots) if s.material and word in s.material.name.lower()}
        return sorted({i for p in mesh.data.polygons if p.material_index in slots for i in p.vertices})
    mouth=vertices('facemouth');brow=vertices('facebrow')
    if not mouth:return None
    eyes=[rig.data.bones[source[k]].head_local for k in ('leftEye','rightEye')
          if source.get(k) and source[k] in rig.data.bones]
    if not mouth or not eyes:return None
    up=(rig.data.bones[source['head']].head_local-rig.data.bones[source['hips']].head_local).normalized()
    transform=np.asarray(rig.matrix_world.inverted() @ mesh.matrix_world)
    points=basis @ transform[:3,:3].T + transform[:3,3]
    heights=points @ np.asarray(up)
    eye=float(np.mean([p.dot(up) for p in eyes]))
    mouth_height=float((heights[mouth].min()+heights[mouth].max())/2)
    if not np.isfinite(eye-mouth_height) or eye-mouth_height<.005:return None
    regions=face_regions(heights,eye,mouth_height,brow)
    regions['eye'][mouth]=0.;regions['brow'][mouth]=0.;regions['mouth'][mouth]=1.
    return regions


def bone_gaze(rig,meshes,source,reserved=()):
    """VRoid usually declares bone look-at instead of look expression binds."""
    from ..vrm import read_document,gaze_degrees
    import math
    try:document=read_document(rig.get('c3d_import_source',''))
    except (OSError,ValueError,TypeError):document={}
    limits=gaze_degrees(document)
    rig['c3d_vrm_gaze_degrees']=json.dumps(limits)
    created = []
    up = (rig.data.bones[source['head']].head_local-rig.data.bones[source['hips']].head_local).normalized()
    left = (rig.data.bones[source['leftUpperArm']].head_local-rig.data.bones[source['rightUpperArm']].head_local).normalized()
    for side,identifier in (('Left','leftEye'),('Right','rightEye')):
        name = source.get(identifier)
        if not name or name not in rig.data.bones:
            continue
        center = rig.data.bones[name].head_local
        for mesh in meshes:
            group = mesh.vertex_groups.get(name)
            if group is None:
                continue
            weights = np.array([sum(g.weight for g in v.groups if g.group==group.index) for v in mesh.data.vertices])
            if not np.any(weights):
                continue
            if mesh.data.shape_keys is None:
                mesh.shape_key_add(name='Basis',from_mix=False)
            keys = mesh.data.shape_keys.key_blocks
            base = coords(keys[0].data)
            matrix = np.array(rig.matrix_world.inverted() @ mesh.matrix_world)
            inverse = np.linalg.inv(matrix)
            points = base @ matrix[:3,:3].T+matrix[:3,3]
            sign=1 if side=='Left' else -1
            for direction,axis,angle in (('Out',up,sign*math.radians(limits['Out'])),
                                         ('In',up,-sign*math.radians(limits['In'])),
                                         ('Up',left,-math.radians(limits['Up'])),
                                         ('Down',left,math.radians(limits['Down']))):
                channel = 'eyeLook'+direction+side
                if channel in keys or channel in reserved:
                    continue
                delta = eye_rotation_delta(points,center,axis,angle,weights) @ inverse[:3,:3].T
                key = mesh.shape_key_add(name=channel,from_mix=False)
                key.relative_key = keys[0]
                key.data.foreach_set('co',(base+delta).astype(np.float32).ravel())
                key.value = 0.0
                created.append(channel)
    return created
