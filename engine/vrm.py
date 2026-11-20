"""VRM 0/1 semantic adapters, independent of Blender and add-on installation."""
import re
import numpy as np

BONES = {'hips':'hips', 'spine':'spine', 'chest':'chest', 'neck':'neck', 'head':'head'}
for side, suffix in (('left','L'), ('right','R')):
    for vrm, char3d in (('Shoulder','shoulder'), ('UpperArm','upper_arm'),
                         ('LowerArm','forearm'), ('Hand','hand'), ('UpperLeg','thigh'),
                         ('LowerLeg','shin'), ('Foot','foot'), ('Toes','toe')):
        BONES[side+vrm] = char3d+'.'+suffix


def camel(value):
    return re.sub(r'_([a-z])', lambda m:m[1].upper(), value)


def bone_map(humanoid):
    source = {camel(k):v for k,v in humanoid.items() if v}
    mapped = {target:source[key] for key,target in BONES.items() if key in source}
    # Upper chest is optional. Prefer the higher chest when present.
    if source.get('upperChest'):
        mapped['chest'] = source['upperChest']
    fingers = {}
    for side, suffix in (('left','L'), ('right','R')):
        for finger in ('thumb','index','middle','ring','little'):
            segments = ('Metacarpal','Proximal','Distal') if finger == 'thumb' and side+'ThumbMetacarpal' in source else ('Proximal','Intermediate','Distal')
            chain = [source.get(side+finger.capitalize()+part) for part in segments]
            if all(chain):
                fingers.setdefault(suffix,{})['pinky' if finger=='little' else finger] = chain
    return mapped, fingers


def addon_bones(extension):
    """Read VRM add-on 4.x's documented property groups (duck-typed for tests)."""
    if not str(extension.spec_version).startswith('1'):
        return {b.bone:b.node.bone_name for b in extension.vrm0.humanoid.human_bones if b.node.bone_name}
    humanoid = extension.vrm1.humanoid.human_bones
    keys = list(BONES)+['upperChest','leftEye','rightEye']
    keys += [side+finger+part for side in ('left','right')
             for finger in ('Thumb','Index','Middle','Ring','Little')
             for part in ('Metacarpal','Proximal','Intermediate','Distal')]
    result = {}
    for key in keys:
        entry = getattr(humanoid,re.sub(r'(?<!^)([A-Z])',r'_\1',key).lower(),None)
        if entry and entry.node.bone_name:
            result[key] = entry.node.bone_name
    return result


def addon_expressions(extension):
    result = {}
    if str(extension.spec_version).startswith('1'):
        preset = extension.vrm1.expressions.preset
        for name in EXPRESSIONS:
            attr = re.sub(r'(?<!^)([A-Z])',r'_\1',name).lower()
            entry = getattr(preset,attr,None)
            if entry:
                binds = [(b.node.mesh_object_name,b.index,b.weight) for b in entry.morph_target_binds]
                if binds:
                    result[name] = binds
    else:
        for group in extension.vrm0.blend_shape_master.blend_shape_groups:
            if group.binds:
                name = group.preset_name
                if name.lower() in ('','unknown'):
                    name = getattr(group,'name',name)
                result[name] = [(b.mesh.mesh_object_name,b.index,b.weight) for b in group.binds]
    return result


# Each canonical key is a weighted sum of imported authored expression bindings.
# The five vowels approximate absent consonants; no absent motion is invented.
EXPRESSIONS = {
    'aa': {'aa_02':1., 'aa_ah_ax_01':.55, 'ay_11':.8, 'aw_09':.7, 'jawOpen':1., 'h_12':.2, 'k_g_ng_20':.25},
    'ih': {'y_iy_ih_ix_06':1., 's_z_15':.35, 'd_t_n_19':.3, 'l_14':.3, 'th_dh_17':.3},
    'ou': {'w_uw_07':1., 'mouthPucker':1., 'r_13':.3, 'sh_ch_jh_zh_16':.35},
    'ee': {'ey_eh_uh_04':1., 'er_05':.6},
    'oh': {'ow_08':1., 'ao_03':.8, 'oy_10':.7, 'mouthFunnel':1.},
    'blink': {'eyeBlinkLeft':.5, 'eyeBlinkRight':.5},
    'blinkLeft': {'eyeBlinkLeft':1.}, 'blinkRight': {'eyeBlinkRight':1.},
    'happy': {'mouthSmileLeft':.5, 'mouthSmileRight':.5},
    'relaxed': {'mouthDimpleLeft':.5, 'mouthDimpleRight':.5},
    'angry': {'browDownLeft':.5, 'browDownRight':.5},
    'sad': {'mouthFrownLeft':.5, 'mouthFrownRight':.5, 'browInnerUp':.15},
    'surprised': {'eyeWideLeft':.5, 'eyeWideRight':.5, 'browOuterUpLeft':.15, 'browOuterUpRight':.15},
    'lookLeft': {'eyeLookOutLeft':.5, 'eyeLookInRight':.5},
    'lookRight': {'eyeLookInLeft':.5, 'eyeLookOutRight':.5},
    'lookUp': {'eyeLookUpLeft':.5, 'eyeLookUpRight':.5},
    'lookDown': {'eyeLookDownLeft':.5, 'eyeLookDownRight':.5},
}
ALIASES = dict(a='aa', i='ih', u='ou', e='ee', o='oh', joy='happy', sorrow='sad', fun='relaxed',
               blink_l='blinkLeft', blink_r='blinkRight', lookup='lookUp', lookdown='lookDown',
               lookleft='lookLeft', lookright='lookRight')


def expression_map(expressions):
    """{VRM preset: [(mesh, shape, weight 0..1)]} -> canonical bindings."""
    normalized = {}
    for name, binds in expressions.items():
        key = ALIASES.get(name.lower(), next((k for k in EXPRESSIONS if k.lower()==name.lower()),name))
        normalized[key] = binds
    result = {}
    for preset, channels in EXPRESSIONS.items():
        for channel, scale in channels.items():
            if preset == 'blink' and normalized.get('blinkLeft' if channel.endswith('Left') else 'blinkRight'):
                continue
            for mesh, shape, weight in normalized.get(preset, []):
                result.setdefault(channel, []).append((mesh,shape,float(weight)*scale))
    return result


def eye_rotation_delta(points, center, axis, angle, weights):
    """Bake an eye-bone look into a native morph, preserving partial skin weights."""
    p = np.asarray(points)-np.asarray(center)
    axis = np.asarray(axis,dtype=float);axis /= np.linalg.norm(axis)
    rotated = p*np.cos(angle)+np.cross(axis,p)*np.sin(angle)+np.outer(p@axis,axis)*(1-np.cos(angle))
    return (rotated-p)*np.asarray(weights)[:,None]
