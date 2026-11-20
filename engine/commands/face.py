"""Facial expressions, lip sync and blinking via ARKit face units + Microsoft visemes.

Works on any mesh whose shape keys use ARKit names (jawOpen, mouthSmileLeft, ...) and/or
Microsoft viseme names (aa_02, p_b_m_21, ...). MPFB humans get them from the CC0
faceunits01 / visemes01 packs (loaded on demand); child meshes of the same rig
(eyebrows, eyelashes, eyes) carry interpolated copies and are driven together.
"""
import json
import math
import random
import re

import bpy

from . import command
from .util import obj_or_raise
from ..phonemes import choose_language, timed_phonemes, viseme_frames

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
LETTERS = {"a": "aa_02", "e": "ey_eh_uh_04", "é": "ey_eh_uh_04", "i": "y_iy_ih_ix_06", "y": "y_iy_ih_ix_06",
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


# ARKit-only imports need articulator approximations instead of Microsoft targets.
MOUTH_UNITS = ("jawOpen", "mouthClose", "mouthFunnel", "mouthPucker", "mouthRollLower",
               "mouthPressLeft", "mouthPressRight")
ARKIT_VISEMES = {
    "aa_02": {"jawOpen": 0.7}, "aa_ah_ax_01": {"jawOpen": 0.3},
    "ao_03": {"jawOpen": 0.4, "mouthFunnel": 0.55},
    "ey_eh_uh_04": {"jawOpen": 0.35}, "er_05": {"jawOpen": 0.2, "mouthPucker": 0.2},
    "y_iy_ih_ix_06": {"jawOpen": 0.18},
    "w_uw_07": {"jawOpen": 0.15, "mouthPucker": 0.8, "mouthFunnel": 0.3},
    "ow_08": {"jawOpen": 0.32, "mouthFunnel": 0.7, "mouthPucker": 0.45},
    "aw_09": {"jawOpen": 0.5, "mouthFunnel": 0.35},
    "oy_10": {"jawOpen": 0.3, "mouthPucker": 0.4}, "ay_11": {"jawOpen": 0.5},
    "h_12": {"jawOpen": 0.15}, "r_13": {"jawOpen": 0.18, "mouthPucker": 0.15},
    "l_14": {"jawOpen": 0.22}, "s_z_15": {"jawOpen": 0.08},
    "sh_ch_jh_zh_16": {"jawOpen": 0.15, "mouthPucker": 0.25},
    "th_dh_17": {"jawOpen": 0.18}, "f_v_18": {"jawOpen": 0.04, "mouthRollLower": 0.85},
    "d_t_n_19": {"jawOpen": 0.15}, "k_g_ng_20": {"jawOpen": 0.2},
    "p_b_m_21": {"mouthClose": 1.0, "mouthPressLeft": 0.3, "mouthPressRight": 0.3},
}


def _clear_mouth_keys(meshes, start, end, names=VISEMES):
    """Remove previous mouth animation in the replacement interval, preserving other keys."""
    from .talk import _fcurves
    paths = {f'key_blocks["{name}"].value' for name in names}
    for mesh in meshes:
        sk = mesh.data.shape_keys
        action = sk.animation_data.action if sk.animation_data else None
        for fc in _fcurves(action):
            if fc.data_path in paths:
                for key in reversed(list(fc.keyframe_points)):
                    if start <= key.co.x <= end:
                        fc.keyframe_points.remove(key, fast=True)
                fc.update()


def key_phonemes(meshes, words, start, end, fps, strength, language, loudness=None):
    """Replace mouth keys in this range with smooth phoneme targets on all face meshes."""
    from .talk import _fcurves
    events = timed_phonemes(words, language)
    names = VISEMES + list(MOUTH_UNITS)
    paths = {f'key_blocks["{name}"].value' for name in names}
    _clear_mouth_keys(meshes, start, end, names)
    for frame, target in viseme_frames(events, start, end, fps, strength, loudness):
        for mesh in meshes:
            keys = mesh.data.shape_keys.key_blocks
            values = dict.fromkeys(names, 0.0)
            for vis, weight in target.items():
                if vis in keys:
                    values[vis] = weight
                    # MPFB's bilabial target leaves a small lip seam; close it without
                    # the large displacement of a full ARKit mouthClose target.
                    if vis == "p_b_m_21":
                        values["mouthClose"] += 0.1 * weight
                    elif vis == "w_uw_07":
                        values["mouthPucker"] += 0.65 * weight
                else:
                    for name, value in ARKIT_VISEMES.get(vis, {}).items():
                        values[name] = min(1.0, values[name] + weight * value)
            _set([mesh], values, frame)
    for mesh in meshes:
        sk = mesh.data.shape_keys
        action = sk.animation_data.action if sk.animation_data else None
        for fc in _fcurves(action):
            if fc.data_path in paths:
                for key in fc.keyframe_points:
                    if start <= key.co.x <= end:
                        key.interpolation = "LINEAR"
    return events


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
    if base.get('c3d_source')=='mpfb' and base.get('c3d_style','realistic')!='realistic':
        raise ValueError('This stylized MPFB character was built with face=False. Recreate it with face=True before facial animation; targets must be fitted before rest proportions are frozen.')
    if base.get("c3d_source") != "mpfb":
        if "jawOpen" in keys or (base.get('c3d_source') == 'vrm' and any(k in keys for k in ARKIT+VISEMES)):
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


# Expression corners are separate from articulation (jaw, funnel, pucker, press,
# tongue and visemes). Blinks and gaze also belong to their own animation layers.
EMOTION_UNITS = [k for k in ARKIT if k.startswith((
    "brow", "cheek", "nose", "eyeWide", "eyeSquint", "mouthSmile", "mouthFrown", "mouthDimple"))]


def _emotion_values(expression, strength, question=False, intensity=1.0):
    values = {k: min(1.0, max(0.0, EXPRESSIONS[expression].get(k, 0.0) * strength))
              for k in EMOTION_UNITS}
    if question:
        for name, weight in (("browInnerUp", 0.12), ("browOuterUpLeft", 0.08),
                             ("browOuterUpRight", 0.08)):
            values[name] = min(1.0, values[name] + weight * intensity)
    return values


def _clear_emotion_keys(meshes, start, end):
    """Replace this layer only; keep speech, blink, gaze and out-of-range keys."""
    from .talk import _fcurves
    for mesh in meshes:
        sk = mesh.data.shape_keys
        action = sk.animation_data.action if sk.animation_data else None
        paths = {sk.key_blocks[k].path_from_id("value") for k in EMOTION_UNITS
                 if k in sk.key_blocks}
        for fc in _fcurves(action):
            if fc.data_path not in paths:
                continue
            # Blender's RNA references are invalidated when points are removed.
            for i in range(len(fc.keyframe_points) - 1, -1, -1):
                key = fc.keyframe_points[i]
                if start <= key.co.x <= end:
                    fc.keyframe_points.remove(key, fast=True)
            fc.update()


@command("auto_expression")
def auto_expression(character, frame_start=None, frame_end=None, base="smile",
                    base_strength=0.35, intensity=1.0, language="auto", cues=None):
    """Key sentence emotions from stored speech words, preserving articulation and blinks."""
    from .emotion import EXPRESSION, classify, sentences
    from .semantic import load_words
    if base not in EXPRESSIONS:
        raise ValueError(f"unknown base expression '{base}'. Use list_expressions.")
    if language not in ("auto", "id", "ms", "en"):
        raise ValueError("language must be 'auto', 'id', 'ms' or 'en'")
    if not math.isfinite(base_strength) or not 0 <= base_strength <= 1:
        raise ValueError("base_strength must be between 0 and 1")
    if not math.isfinite(intensity) or intensity < 0:
        raise ValueError("intensity must be finite and non-negative")
    sc = bpy.context.scene
    fs = int(frame_start if frame_start is not None else sc.frame_start)
    fe = int(frame_end if frame_end is not None else sc.frame_end)
    if fe < fs:
        raise ValueError("frame_end must be >= frame_start")
    forced = []
    for cue in cues or []:
        if not {"frame", "expression", "strength"} <= cue.keys():
            raise ValueError("each cue needs frame, expression and strength")
        if cue["expression"] not in EXPRESSIONS:
            raise ValueError(f"unknown cue expression '{cue['expression']}'. Use list_expressions.")
        strength = float(cue["strength"])
        if not math.isfinite(strength) or not 0 <= strength <= 1:
            raise ValueError("cue strength must be between 0 and 1")
        frame = int(cue["frame"])
        if fs <= frame <= fe:
            forced.append((frame, cue["expression"], strength))

    mesh = _basemesh(character)
    fps = sc.render.fps / sc.render.fps_base
    anticipation = max(1, round(0.2 * fps))
    blend = max(1, round(0.15 * fps))
    relax = max(1, round(0.3 * fps))
    events = []
    for words in sentences(load_words(mesh)):
        start, end = words[0][1], max(w[2] for w in words)
        if end < fs or start > fe:
            continue
        emotion, strength, question = classify(words, language)
        expression = base if emotion == "base" else EXPRESSION[emotion]
        strength = base_strength if emotion == "base" else min(1.0, strength * intensity)
        peak = max(fs, round(start) - anticipation)
        events.append({"sentence": " ".join(w[0] for w in words), "emotion": emotion,
                       "expression": expression, "strength": round(strength, 3),
                       "sentence_frames": [round(start, 2), round(end, 2)],
                       "frames": [peak, min(fe, max(peak, round(end)))],
                       "question": question, "source": "text"})
    text_events = list(events)
    for frame, expression, strength in forced:
        candidates = [e for e in text_events if e["frames"][0] <= frame <= e["sentence_frames"][1]]
        containing = min(candidates, key=lambda e: abs(frame - e["frames"][0]), default=None)
        if containing is not None:
            events = [e for e in events if e is not containing]
        events.append({"sentence": containing["sentence"] if containing else "",
                       "emotion": expression, "expression": expression, "strength": strength,
                       "sentence_frames": containing["sentence_frames"] if containing else None,
                       "frames": [frame, min(fe, max(frame, round(containing["sentence_frames"][1]))
                                             if containing else frame + round(0.6 * fps))],
                       "question": False, "source": "cue"})
    if not events:
        raise ValueError("no word times in the range: run lip_sync or lip_sync_audio with "
                         "text/whisper timing first, or supply cues")
    # Last event at a frame wins (explicit cues follow inferred sentences).
    events = sorted({e["frames"][0]: e for e in events}.values(), key=lambda e: e["frames"][0])
    _ensure_face(mesh)
    meshes = _face_meshes(mesh)
    _clear_emotion_keys(meshes, fs, fe)
    baseline = _emotion_values(base, base_strength)
    current = sc.frame_current
    last = fs

    def key(values, frame, transition=0):
        set_expression(character, expression=None, units=values, clear=False, frame=frame,
                       keyframe=True, transition_frames=transition)

    try:
        key(baseline, fs)
        for i, event in enumerate(events):
            peak, end = event["frames"]
            next_peak = events[i + 1]["frames"][0] if i + 1 < len(events) else None
            hold = max(peak, min(end, next_peak - blend)) if next_peak is not None else end
            values = _emotion_values(event["expression"], event["strength"],
                                     event["question"], intensity)
            key(values, peak, min(blend, peak - last))
            key(values, hold)
            event["frames"][1] = hold
            last = hold
            # Short gaps blend directly to the next emotion. Longer pauses settle
            # to the base, leaving room for the next sentence's anticipation.
            room = (next_peak - blend if next_peak is not None else fe) - hold
            tail_values = values
            if room >= relax or (next_peak is None and room > 0):
                last = min(hold + relax, fe)
                key(baseline, last, last - hold)
                tail_values = baseline
                event["relax_frame"] = last
            else:
                event["relax_frame"] = None
        # Hold the final state to the boundary even when later animation exists.
        if last < fe:
            key(tail_values, fe)
    finally:
        sc.frame_set(current)
    previous = json.loads(mesh.get('char3d_emotions', '[]'))
    kept = [e for e in previous if (e.get('relax_frame') or e['frames'][1]) < fs or e['frames'][0] > fe]
    mesh['char3d_emotions'] = json.dumps(sorted(kept+events, key=lambda e: e['frames'][0]))
    return {"character": mesh.name, "frames": [fs, fe], "language": language,
            "base": base, "base_strength": base_strength, "intensity": intensity,
            "sentences": events, "keyed_units": EMOTION_UNITS,
            "meshes": [m.name for m in meshes]}


@command("lip_sync")
def lip_sync(character, text, start_frame=1, chars_per_second=14.0, strength=0.9,
             expression=None, language=None, detail="phoneme"):
    """Keyframe timed ID/MS/English phonemes; detail=word keeps legacy letter timing."""
    if detail not in ("phoneme", "word"):
        raise ValueError("detail must be phoneme or word")
    if float(chars_per_second) <= 0:
        raise ValueError("chars_per_second must be positive")
    language = choose_language(text, language)
    base = _basemesh(character)
    _ensure_face(base)
    meshes = _face_meshes(base)
    fps = bpy.context.scene.render.fps
    step = fps / float(chars_per_second)
    tokens = text_tokens(text)
    start = int(start_frame)
    end = int(round(start + 1 + len(tokens) * step)) + 2
    from .semantic import store_words, text_word_frames
    word_frames = text_word_frames(text, start, step, text_tokens)
    if detail == "phoneme":
        if expression:
            set_expression(character, expression, frame=start, keyframe=True, transition_frames=0)
        phones = key_phonemes(meshes, word_frames, start, end, fps, strength, language)
        store_words(base, word_frames, start, end)
        bpy.context.scene.frame_end = max(bpy.context.scene.frame_end, end)
        return {"character": base.name, "frames": [start, end], "next_start_frame": end + 1,
                "seconds": round((end - start) / fps, 2), "words": len(word_frames),
                "mouth_shapes": len(phones), "detail": detail, "language": language,
                "phonemes": phones}
    # merge consecutive duplicates so held sounds don't stutter
    merged = []
    for t in tokens:
        if merged and merged[-1][0] == t:
            merged[-1][1] += 1
        else:
            merged.append([t, 1])
    _clear_mouth_keys(meshes, start, end)
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
    store_words(base, word_frames, start, end)
    return {"character": base.name, "frames": [start, end], "next_start_frame": end + 1,
            "seconds": round((end - start) / fps, 2), "words": words,
            "mouth_shapes": len([m for m in merged if m[0] != "sil_00"]),
            "detail": detail, "language": language, "phonemes": []}


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
