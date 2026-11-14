"""Facial expressions, lip sync and blinking via ARKit face units + Microsoft visemes.

Works on any mesh whose shape keys use ARKit names (jawOpen, mouthSmileLeft, ...) and/or
Microsoft viseme names (aa_02, p_b_m_21, ...). MPFB humans get them from the CC0
faceunits01 / visemes01 packs (loaded on demand); child meshes of the same rig
(eyebrows, eyelashes, eyes) carry interpolated copies and are driven together.
"""
import random
import re

import bpy

from . import command
from .util import obj_or_raise

ARKIT = [
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "eyeBlinkLeft", "eyeBlinkRight",
    "eyeLookDownLeft", "eyeLookDownRight", "eyeLookInLeft", "eyeLookInRight", "eyeLookOutLeft",
    "eyeLookOutRight", "eyeLookUpLeft", "eyeLookUpRight", "eyeSquintLeft", "eyeSquintRight",
    "eyeWideLeft", "eyeWideRight", "jawForward", "jawLeft", "jawOpen", "jawRight", "mouthClose",
    "mouthDimpleLeft", "mouthDimpleRight", "mouthFrownLeft", "mouthFrownRight", "mouthFunnel",
    "mouthLeft", "mouthLowerDownLeft", "mouthLowerDownRight", "mouthPressLeft", "mouthPressRight",
    "mouthPucker", "mouthRight", "mouthRollLower", "mouthRollUpper", "mouthShrugLower",
    "mouthShrugUpper", "mouthSmileLeft", "mouthSmileRight", "mouthStretchLeft",
    "mouthStretchRight", "mouthUpperUpLeft", "mouthUpperUpRight", "noseSneerLeft",
    "noseSneerRight", "tongueOut",
]
VISEMES = [
    "aa_02", "aa_ah_ax_01", "ao_03", "aw_09", "ay_11", "d_t_n_19", "er_05", "ey_eh_uh_04",
    "f_v_18", "h_12", "k_g_ng_20", "l_14", "ow_08", "oy_10", "p_b_m_21", "r_13",
    "sh_ch_jh_zh_16", "sil_00", "s_z_15", "th_dh_17", "w_uw_07", "y_iy_ih_ix_06",
]


def _both(prefix, value, suffix=""):
    return {f"{prefix}Left{suffix}": value, f"{prefix}Right{suffix}": value}


EXPRESSIONS = {
    "neutral": {},
    "smile": {**_both("mouthSmile", 0.7), **_both("cheekSquint", 0.4), **_both("eyeSquint", 0.2)},
    "big_smile": {**_both("mouthSmile", 1.0), "jawOpen": 0.3, **_both("cheekSquint", 0.7),
                  **_both("eyeSquint", 0.5), **_both("mouthUpperUp", 0.3)},
    "laugh": {**_both("mouthSmile", 1.0), "jawOpen": 0.55, **_both("cheekSquint", 0.8),
              **_both("eyeSquint", 0.7), "browInnerUp": 0.2, **_both("mouthUpperUp", 0.4)},
    "sad": {"browInnerUp": 0.8, **_both("mouthFrown", 0.7), "mouthShrugLower": 0.35,
            **_both("mouthPress", 0.2), **_both("eyeLookDown", 0.25)},
    "angry": {**_both("browDown", 0.9), **_both("noseSneer", 0.5), **_both("eyeSquint", 0.4),
              **_both("mouthPress", 0.5), **_both("mouthFrown", 0.3), "jawForward": 0.1},
    "furious": {**_both("browDown", 1.0), **_both("noseSneer", 0.8), **_both("eyeWide", 0.3),
                "jawOpen": 0.35, **_both("mouthStretch", 0.5), **_both("mouthUpperUp", 0.6)},
    "surprised": {"browInnerUp": 0.9, **_both("browOuterUp", 0.9), **_both("eyeWide", 0.8),
                  "jawOpen": 0.5, "mouthFunnel": 0.2},
    "fear": {"browInnerUp": 1.0, **_both("browOuterUp", 0.5), **_both("eyeWide", 0.9),
             **_both("mouthStretch", 0.6), "jawOpen": 0.2},
    "disgust": {**_both("noseSneer", 0.9), **_both("mouthUpperUp", 0.7), **_both("browDown", 0.4),
                **_both("eyeSquint", 0.3), **_both("mouthFrown", 0.3)},
    "smirk": {"mouthSmileLeft": 0.6, "mouthDimpleLeft": 0.4, "browDownRight": 0.2,
              "eyeSquintLeft": 0.2},
    "wink_left": {"eyeBlinkLeft": 1.0, "cheekSquintLeft": 0.4, "mouthSmileLeft": 0.45},
    "wink_right": {"eyeBlinkRight": 1.0, "cheekSquintRight": 0.4, "mouthSmileRight": 0.45},
    "eyes_closed": {**_both("eyeBlink", 1.0)},
    "pout": {"mouthPucker": 0.9, "mouthFunnel": 0.3, "browInnerUp": 0.3},
    "kiss": {"mouthPucker": 1.0, "mouthFunnel": 0.5, **_both("eyeBlink", 0.6)},
    "thinking": {"browDownRight": 0.35, "browInnerUp": 0.3, "mouthPressLeft": 0.4, "mouthLeft": 0.3,
                 **_both("eyeLookUp", 0.45)},
    "shout": {"jawOpen": 0.85, **_both("browDown", 0.6), **_both("mouthStretch", 0.4),
              **_both("noseSneer", 0.3), **_both("mouthUpperUp", 0.4)},
    "sleepy": {**_both("eyeBlink", 0.6), "jawOpen": 0.05, "browInnerUp": 0.15},
    "look_left": {"eyeLookOutLeft": 0.8, "eyeLookInRight": 0.8},
    "look_right": {"eyeLookOutRight": 0.8, "eyeLookInLeft": 0.8},
    "look_up": {**_both("eyeLookUp", 0.8), "browInnerUp": 0.2},
    "look_down": {**_both("eyeLookDown", 0.8)},
    "tongue_out": {"tongueOut": 1.0, "jawOpen": 0.4, **_both("eyeSquint", 0.3)},
}

# letters (and digraphs first) -> viseme; works for English and Indonesian-like spelling
DIGRAPHS = {"sh": "sh_ch_jh_zh_16", "ch": "sh_ch_jh_zh_16", "sy": "sh_ch_jh_zh_16",
            "th": "th_dh_17", "ng": "k_g_ng_20", "ny": "y_iy_ih_ix_06", "oo": "w_uw_07",
            "ee": "y_iy_ih_ix_06", "ai": "ay_11", "au": "aw_09", "oi": "oy_10", "ou": "w_uw_07"}
LETTERS = {"a": "aa_02", "e": "ey_eh_uh_04", "i": "y_iy_ih_ix_06", "y": "y_iy_ih_ix_06",
           "o": "ow_08", "u": "w_uw_07", "w": "w_uw_07", "b": "p_b_m_21", "p": "p_b_m_21",
           "m": "p_b_m_21", "f": "f_v_18", "v": "f_v_18", "t": "d_t_n_19", "d": "d_t_n_19",
           "n": "d_t_n_19", "l": "l_14", "r": "r_13", "s": "s_z_15", "z": "s_z_15",
           "c": "sh_ch_jh_zh_16", "j": "sh_ch_jh_zh_16", "x": "s_z_15", "k": "k_g_ng_20",
           "g": "k_g_ng_20", "q": "k_g_ng_20", "h": "h_12"}
VOWEL_VISEMES = {"aa_02", "ey_eh_uh_04", "y_iy_ih_ix_06", "ow_08", "w_uw_07", "ay_11", "aw_09",
                 "oy_10"}


def text_tokens(text):
    """Text -> list of viseme names (and "sil_00" for pauses), digraphs first."""
    tokens = []
    s = text.lower()
    i = 0
    while i < len(s):
        two = s[i:i + 2]
        if two in DIGRAPHS:
            tokens.append(DIGRAPHS[two])
            i += 2
            continue
        ch = s[i]
        if ch in LETTERS:
            tokens.append(LETTERS[ch])
        elif ch in ".!?;:":
            tokens += ["sil_00"] * 4
        elif ch in ",-":
            tokens += ["sil_00"] * 2
        elif ch.isspace():
            tokens.append("sil_00")
        i += 1
    return tokens


def key_viseme(meshes, vis, t0, t1, weight):
    """Ramp a viseme in at t0 and out after t1 (frames, float)."""
    if vis == "sil_00":
        return
    _set(meshes, {vis: 0.0}, int(round(t0)) - 1)
    _set(meshes, {vis: weight}, int(round(t0)))
    if t1 - t0 > 2:
        _set(meshes, {vis: weight}, int(round(t1)) - 1)
    _set(meshes, {vis: 0.0}, int(round(t1)) + 1)


# ----------------------------------------------------------------------------- targets
def _basemesh(name):
    obj = obj_or_raise(name)
    if obj.type == "ARMATURE":
        meshes = [c for c in obj.children_recursive if c.type == "MESH"]
        base = next((m for m in meshes if m.get("c3d_kind") == "humanoid"), None)
        if base is None:
            base = max(meshes, key=lambda m: len(m.data.shape_keys.key_blocks) if m.data.shape_keys else 0,
                       default=None)
        if base is None:
            raise ValueError(f"{name} has no child mesh")
        return base
    if obj.type != "MESH":
        raise TypeError(f"{name} is a {obj.type}; pass the character mesh or its armature")
    return obj


def _ensure_face(base):
    keys = base.data.shape_keys.key_blocks if base.data.shape_keys else {}
    if "jawOpen" in keys and "aa_02" in keys:
        return False
    if base.get("c3d_source") != "mpfb":
        if "jawOpen" in keys:
            return False
        raise ValueError(f"{base.name} has no ARKit face shape keys. Expressions work on "
                         "create_realistic_human characters or meshes with ARKit blendshapes.")
    from .mpfb import _services
    _services()
    from bl_ext.user_default.mpfb.services.faceservice import FaceService
    if not FaceService.is_faceunits01_installed(force_recheck=True):
        raise RuntimeError("faceunits01/visemes01 packs are not installed "
                           "(scripts/install_mpfb.sh installs them).")
    FaceService.load_targets(base, load_microsoft_visemes=True, load_meta_visemes=False,
                             load_arkit_faceunits=True)
    FaceService.interpolate_targets(base)
    return True


def _face_meshes(base):
    """Base mesh + sibling meshes under the same rig that share face shape keys."""
    out = [base]
    root = base.parent if base.parent and base.parent.type == "ARMATURE" else None
    if root:
        for m in root.children_recursive:
            if m is not base and m.type == "MESH" and m.data.shape_keys:
                names = m.data.shape_keys.key_blocks.keys()
                if any(n in names for n in ARKIT + VISEMES):
                    out.append(m)
    return out


def _set(meshes, values, frame=None):
    """Set shape key values on every mesh that has them (optionally keyframing)."""
    for m in meshes:
        kb = m.data.shape_keys.key_blocks
        for name, v in values.items():
            k = kb.get(name)
            if k is None:
                continue
            k.slider_max = max(k.slider_max, 1.0)
            k.value = float(v)
            if frame is not None:
                k.keyframe_insert("value", frame=int(frame))


def _key_current(meshes, names, frame):
    for m in meshes:
        kb = m.data.shape_keys.key_blocks
        for name in names:
            k = kb.get(name)
            if k is not None:
                k.keyframe_insert("value", frame=int(frame))


# ----------------------------------------------------------------------------- commands
@command("list_expressions")
def list_expressions():
    return {"expressions": {k: sorted(v) for k, v in EXPRESSIONS.items()},
            "face_units": ARKIT, "visemes": VISEMES}


@command("set_expression")
def set_expression(character, expression="neutral", units=None, strength=1.0, clear=True,
                   frame=None, keyframe=False, transition_frames=6):
    """Apply a named expression (and/or raw ARKit unit weights) to a character's face."""
    if expression and expression not in EXPRESSIONS:
        raise ValueError(f"unknown expression '{expression}'. Available: {sorted(EXPRESSIONS)}")
    base = _basemesh(character)
    loaded = _ensure_face(base)
    meshes = _face_meshes(base)
    values = {k: v * float(strength) for k, v in EXPRESSIONS.get(expression or "neutral", {}).items()}
    for k, v in (units or {}).items():
        if k not in ARKIT:
            raise ValueError(f"unknown face unit '{k}'. Use names from list_expressions.")
        values[k] = float(v)
    if clear:
        values = {**{k: 0.0 for k in ARKIT}, **values}
    sc = bpy.context.scene
    f = int(frame) if frame is not None else sc.frame_current
    if keyframe and transition_frames and f - int(transition_frames) >= sc.frame_start:
        sc.frame_set(f - int(transition_frames))       # hold the previous face until here
        _key_current(meshes, values.keys(), f - int(transition_frames))
    sc.frame_set(f)
    _set(meshes, values, f if keyframe else None)
    active = {k: round(v, 3) for k, v in values.items() if v}
    return {"character": base.name, "expression": expression, "frame": f, "keyed": bool(keyframe),
            "active_units": active, "meshes": [m.name for m in meshes],
            "loaded_face_targets": loaded}


@command("lip_sync")
def lip_sync(character, text, start_frame=1, chars_per_second=14.0, strength=0.9,
             expression=None):
    """Keyframe visemes from text (rough letter-to-mouth-shape mapping)."""
    base = _basemesh(character)
    _ensure_face(base)
    meshes = _face_meshes(base)
    fps = bpy.context.scene.render.fps
    step = fps / float(chars_per_second)
    tokens = text_tokens(text)
    # merge consecutive duplicates so held sounds don't stutter
    merged = []
    for t in tokens:
        if merged and merged[-1][0] == t:
            merged[-1][1] += 1
        else:
            merged.append([t, 1])
    start = int(start_frame)
    zero = {v: 0.0 for v in VISEMES}
    _set(meshes, zero, start)
    t = float(start) + 1
    for vis, count in merged:
        t0 = t
        t1 = t + step * count
        w = strength if vis in VOWEL_VISEMES else strength * 0.75
        key_viseme(meshes, vis, t0, t1, w)   # ramps within ~1 frame of its own letters
        t = t1
    end = int(round(t)) + 2
    _set(meshes, zero, end)
    if expression:
        set_expression(character, expression, frame=start, keyframe=True, transition_frames=0)
    sc = bpy.context.scene
    sc.frame_end = max(sc.frame_end, end)
    words = len(re.findall(r"\w+", text))
    return {"character": base.name, "frames": [start, end], "next_start_frame": end + 1,
            "seconds": round((end - start) / fps, 2), "words": words,
            "mouth_shapes": len([m for m in merged if m[0] != "sil_00"])}


@command("auto_blink")
def auto_blink(character, frame_start=None, frame_end=None, interval_seconds=3.5, seed=7):
    """Add natural blinks (~every interval_seconds, jittered) over a frame range."""
    base = _basemesh(character)
    _ensure_face(base)
    meshes = _face_meshes(base)
    sc = bpy.context.scene
    fs = int(frame_start if frame_start is not None else sc.frame_start)
    fe = int(frame_end if frame_end is not None else sc.frame_end)
    fps = sc.render.fps
    rng = random.Random(seed)
    f = fs + int(fps * rng.uniform(0.5, interval_seconds))
    blinks = []
    names = ("eyeBlinkLeft", "eyeBlinkRight")
    while f + 6 <= fe:
        _set(meshes, dict.fromkeys(names, 0.0), f)
        _set(meshes, dict.fromkeys(names, 1.0), f + 2)
        _set(meshes, dict.fromkeys(names, 1.0), f + 3)
        _set(meshes, dict.fromkeys(names, 0.0), f + 6)
        blinks.append(f)
        f += int(fps * interval_seconds * rng.uniform(0.6, 1.4))
    return {"character": base.name, "blinks": blinks}
