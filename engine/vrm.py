"""VRM 0/1 semantic adapters, independent of Blender and add-on installation."""
import re
import json
import os
import struct
from pathlib import Path
import numpy as np


WARDROBE = ('hair', 'clothes', 'outfit', 'beard', 'assets', 'accessories')


def gaze_degrees(document):
    """Maximum authored eye rotations, not the target-input angular range."""
    extensions=document.get('extensions',{})
    v1=extensions.get('VRMC_vrm',{}).get('lookAt',{})
    v0=extensions.get('VRM',{}).get('firstPerson',{})
    result={}
    for direction,field,default in (('In','HorizontalInner',20.),('Out','HorizontalOuter',20.),
                                    ('Up','VerticalUp',17.1887),('Down','VerticalDown',17.1887)):
        value=(v1.get('rangeMap'+field,{}).get('outputScale',default) if v1 else
               v0.get('lookAt'+field,{}).get('yRange',default))
        try:value=float(value)
        except (TypeError,ValueError):value=default
        result[direction]=float(np.clip(value,0.,89.)) if np.isfinite(value) else default
    return result


def face_regions(heights, eye, mouth, brow_indices=()):
    """Localize authored whole-face presets for independent semantic layers.

    No new motion is invented: these masks select the existing authored delta.
    In particular, an eye-only listener reaction must never animate the lips.
    """
    gap = float(eye-mouth)
    if not np.isfinite(gap) or gap < .005:
        raise ValueError('facial eye/mouth anchors must be ordered and separated')
    heights = np.asarray(heights, dtype=float)
    def smooth(value):
        t = np.clip(value, 0., 1.)
        return t*t*(3-2*t)
    upper = smooth((heights-(mouth+.25*gap))/(.6*gap))
    brow = smooth((heights-(eye+.20*gap))/(.35*gap))
    if len(brow_indices):brow[np.asarray(brow_indices,dtype=int)] = 1.
    return dict(mouth=1-upper, eye=upper*(1-brow), brow=brow)


def dialog_declarations(characters):
    """Normalize optional VRM dict actors for the existing-rig dialog API."""
    entries = [c for c in characters or [] if isinstance(c, dict)]
    if not entries:
        return characters, [], {}
    if any(not c.get('vrm') for c in entries):
        raise ValueError('dialog dict actors require id and vrm; existing actors use rig names')
    from .script_plan import parse_script
    plan = parse_script({'characters': entries, 'beats': [{'do':'pause', 'seconds':1}]})
    normalized = {c['id'].casefold():c for c in plan['characters']}
    return [normalized[c['id'].casefold()] if isinstance(c, dict) else c for c in characters], plan['warnings'], normalized


def actor_path(value, workspace=None):
    """Resolve an actor strictly inside imports, including symlink targets.

    Bare filenames prefer imports/vrm. Planning may reference a missing file;
    building subsequently requires it. No directories or files are created here.
    """
    if not isinstance(value, str) or not value.strip() or Path(value).suffix.lower() != '.vrm':
        raise ValueError('vrm must be a nonempty .vrm path under imports/')
    if workspace is None:
        from . import context
        workspace = context.WORKSPACE or os.environ.get('CHAR3D_WORKSPACE', 'output')
    workspace = Path(workspace).expanduser().resolve()
    root = (workspace / 'imports').resolve()
    if not root.is_relative_to(workspace):
        raise ValueError('workspace imports/ must not resolve outside the workspace')
    path = Path(value).expanduser()
    if not path.is_absolute():
        if len(path.parts) == 1:
            preferred = root / 'vrm' / path
            path = preferred if preferred.is_file() else root / path
        else:
            path = root / path
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError('VRM actor path must stay under workspace imports/ (including symlinks)')
    return path, path.relative_to(root).as_posix()


def read_document(path):
    """Read only the bounded GLB JSON chunk; never load embedded textures/geometry."""
    with open(path, 'rb') as stream:
        header = stream.read(20)
        if len(header) != 20:
            raise ValueError('truncated VRM GLB header')
        magic, version, total, length, kind = struct.unpack('<4sIIII', header)
        if magic != b'glTF' or version != 2 or kind != 0x4e4f534a or not 0 < length <= 32*1024*1024 or total < 20+length:
            raise ValueError('invalid VRM GLB JSON header')
        raw = stream.read(length)
        if len(raw) != length:
            raise ValueError('truncated VRM JSON')
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError('VRM JSON must be an object')
        return document


def metadata(path):
    """Embedded declarations are provenance, not verification of a rights grant."""
    doc = read_document(path)
    ext = doc.get('extensions', {})
    if not isinstance(ext, dict):
        raise ValueError('invalid VRM extensions')
    v1 = 'VRMC_vrm' in ext
    source = ext.get('VRMC_vrm' if v1 else 'VRM', {})
    if not isinstance(source, dict):
        raise ValueError('invalid VRM extension')
    meta = source.get('meta', {})
    if not isinstance(meta, dict) or not meta:
        raise ValueError('VRM humanoid metadata missing')
    return dict(status='embedded', version='1.0' if v1 else '0.x',
                title=meta.get('name' if v1 else 'title', 'Untitled'),
                author=meta.get('authors' if v1 else 'author', 'Unknown'),
                licence=meta.get('licenseUrl' if v1 else 'licenseName', 'unverified'),
                licence_url=meta.get('licenseUrl' if v1 else 'otherLicenseUrl', ''),
                declarations=meta)


def actor_declaration(char, warnings):
    """Normalize VRM casting without Blender or importing a model."""
    path, relative = actor_path(char['vrm'])
    char['vrm'] = relative
    try:
        meta = metadata(path)
    except (OSError, ValueError, TypeError, KeyError):
        meta = dict(status='unverified', title='unverified', author='unverified', licence='unverified')
    char['vrm_meta'] = meta
    hints = ' '.join((path.stem, str(meta.get('title', '')))).replace('_', ' ')
    # Gender/age are optional voice hints, never a change to the imported body.
    declared = meta.get('declarations', {})
    if 'gender' not in char:
        hint = str(declared.get('sex', declared.get('gender', hints)))
        if re.search(r'\b(female|woman|girl)\b', hint, re.I) or '女性' in hint:
            char['gender'] = 0
        elif re.search(r'\b(male|man|boy)\b', hint, re.I) or '男性' in hint:
            char['gender'] = 1
        else:
            warnings.append(f"{char['id']}: VRM has no sex hint; voice casting uses unspecified gender (override gender)")
    if 'age' not in char:
        if isinstance(declared.get('age'), (int, float)):
            char['age'] = declared['age']
        else:
            warnings.append(f"{char['id']}: VRM has no age hint; voice casting defaults to adult 28 (override age)")
    for key in (*WARDROBE, 'look', 'style', 'materials', 'skin', 'race', 'height', 'weight', 'muscle', 'proportions'):
        if key in char:
            warnings.append(f"{char['id']}: {key} ignored for VRM actor; authored appearance persists")
            del char[key]

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


# VRoid faces also carry per-region authored keys (Fcl_EYE_Joy, Fcl_BRW_Sorrow,
# Fcl_MTH_Fun...). Where present, emotion units bind straight to those designed
# anime shapes instead of masked whole-face presets (whose smile opened the mouth
# and whose surprise barely changed the eyes). Two sides share symmetric keys.
VROID_REGIONS = {
    'mouthSmileLeft': (('Fcl_MTH_Fun', .5),), 'mouthSmileRight': (('Fcl_MTH_Fun', .5),),
    'cheekSquintLeft': (('Fcl_EYE_Joy_L', .8),), 'cheekSquintRight': (('Fcl_EYE_Joy_R', .8),),
    'eyeSquintLeft': (('Fcl_EYE_Joy_L', .4),), 'eyeSquintRight': (('Fcl_EYE_Joy_R', .4),),
    'eyeWideLeft': (('Fcl_EYE_Surprised', .5),), 'eyeWideRight': (('Fcl_EYE_Surprised', .5),),
    'browInnerUp': (('Fcl_BRW_Sorrow', 1.),),
    'browOuterUpLeft': (('Fcl_BRW_Surprised', .5),), 'browOuterUpRight': (('Fcl_BRW_Surprised', .5),),
    'browDownLeft': (('Fcl_BRW_Angry', .5),), 'browDownRight': (('Fcl_BRW_Angry', .5),),
    'mouthFrownLeft': (('Fcl_MTH_Sorrow', .5),), 'mouthFrownRight': (('Fcl_MTH_Sorrow', .5),),
}


def vroid_region_binds(mesh_name, key_names):
    """{channel: [(mesh, key, weight)]} for authored VRoid region keys (case-insensitive suffix)."""
    found = {}
    for name in key_names:
        tail = name.rsplit('_Fcl_', 1)
        if len(tail) == 2:
            found.setdefault('Fcl_'+tail[1].lower(), name)
        elif name.lower().startswith('fcl_'):
            found.setdefault(name.lower(), name)
    result = {}
    for channel, parts in VROID_REGIONS.items():
        binds = [(mesh_name, found['Fcl_'+key[4:].lower()], weight) for key, weight in parts
                 if 'Fcl_'+key[4:].lower() in found]
        if len(binds) == len(parts):
            result[channel] = binds
    return result


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
