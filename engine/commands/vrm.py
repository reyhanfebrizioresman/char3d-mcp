"""Import through VRM Add-on for Blender, then bake portable char3d morph aliases."""
import json

import addon_utils
import bpy
import numpy as np

from ..vrm import addon_bones, addon_expressions, bone_map, expression_map, eye_rotation_delta
from .toon import coords

INSTALL = ('VRM Add-on for Blender is required for .vrm (0.x/1.0). '
           'Run scripts/install_vrm.sh, install its verified extension ZIP in Blender, '
           'then restart the char3d engine. No runtime downloads.')


def import_vrm(path):
    modules = [m.__name__ for m in addon_utils.modules()
               if m.__name__ == 'io_scene_vrm' or m.__name__.endswith('.vrm')]
    if not modules:
        raise RuntimeError(INSTALL)
    for name in modules:
        addon_utils.enable(name, default_set=False)
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
    created += bone_gaze(rig,meshes,source,set(channels))
    faces = []
    for mesh in [m for m in meshes if m.data.shape_keys]:
        keys = mesh.data.shape_keys.key_blocks
        basis = coords(keys[0].data)
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
                key = mesh.shape_key_add(name=channel, from_mix=False)
                key.data.foreach_set('co',(basis+delta).ravel())
                created.append(channel)
        if any(k in mesh.data.shape_keys.key_blocks for k in channels) or any(k.startswith('eyeLook') for k in mesh.data.shape_keys.key_blocks.keys()):
            # _ensure_face recognizes native aliases without trying MPFB downloads.
            mesh['c3d_source'] = 'vrm'
            mesh['c3d_rig'] = rig.name
            faces.append(mesh)
    if faces:
        max(faces,key=lambda m:len(m.data.shape_keys.key_blocks))['c3d_kind'] = 'humanoid'
    warnings += ['VRM models carry their own licences; the user must have permission to use this model.',
                 'Spring bones are static; no VRM physics evaluation. Vowel-only rigs approximate consonants.',
                 'Combined Blink cannot provide independent winks; absent expressions remain unavailable.']
    return dict(armature=rig.name, version=rig['c3d_vrm_version'], mapped_bones=mapped,
                finger_sides=sorted(fingers), expression_channels=sorted(set(created)), warnings=warnings)


def bone_gaze(rig,meshes,source,reserved=()):
    """VRoid usually declares bone look-at instead of look expression binds."""
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
            for direction,axis,angle in (('Out',up,.35 if side=='Left' else -.35),
                                         ('In',up,-.35 if side=='Left' else .35),
                                         ('Up',left,-.3),('Down',left,.3)):
                channel = 'eyeLook'+direction+side
                if channel in keys or channel in reserved:
                    continue
                delta = eye_rotation_delta(points,center,axis,angle,weights) @ inverse[:3,:3].T
                key = mesh.shape_key_add(name=channel,from_mix=False)
                key.data.foreach_set('co',(base+delta).astype(np.float32).ravel())
                created.append(channel)
    return created
