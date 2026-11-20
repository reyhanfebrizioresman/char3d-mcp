"""Speech-driven arm and hand gestures, layered over existing body animation.

Each gesture is a target HAND POSITION relative to the base of the neck (in fractions of
the character's height; it rotates with the chest; +X = character's left, -Y = forward, +Z = up). A two-bone analytic IK
places the elbow (pointing down/back/out), the upper arm and forearm are aimed with minimal
rotation from their current pose, and the hand follows the forearm unless a gesture asks for a
palm direction (then the forearm and wrist share the twist). Targets follow the chest every
frame, so gestures stay attached while the torso moves. Outside speech the arms blend back to
their base animation.

Two kinds of gestures:
  * beats - rhythm: placed on the loudness peaks of the speech (beat, open palms, sweep, point);
  * semantic - meaning: placed on words with a meaning (see semantic.py) when word times are
    known (lip_sync / lip_sync_audio with whisper or text), e.g. "dua" -> two fingers.
Each hand gets a timeline of key poses; consecutive gestures flow into each other.
"""
import math
import random

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from . import command
from .anim import _key_rot, semantic_map
from .fingers import HandRig, blend_shapes
from .semantic import load_words, match, select
from .talk import _audio_activity, _basemesh, _peaks, _phrases, _rig_of, _smooth, _viseme_activity

# right-hand targets (x is mirrored for the left hand)
TALK_REST = (-0.10, -0.15, -0.25)
GESTURES = {
    # name: (one hand | both, preparation target, stroke target)
    "beat": ("one", (-0.11, -0.17, -0.18), (-0.11, -0.19, -0.27)),
    "beat_both": ("both", (-0.10, -0.17, -0.18), (-0.10, -0.19, -0.27)),
    "open_palms": ("both", (-0.09, -0.15, -0.22), (-0.23, -0.17, -0.17)),
    "sweep": ("one", (-0.06, -0.17, -0.19), (-0.27, -0.12, -0.15)),
    "point": ("one", (-0.10, -0.18, -0.13), (-0.11, -0.33, -0.07)),
}
# finger shapes: (preparation, stroke) per gesture; the speaking posture uses "relaxed"
HAND_SHAPES = {"beat": ("relaxed", "beat"), "beat_both": ("relaxed", "beat"),
               "open_palms": ("relaxed", "palm"), "sweep": ("relaxed", "open"),
               "point": ("relaxed", "point")}
STYLES = {  # (gesture probability per emphasis, amplitude, weights per gesture)
    "calm": (0.55, 0.65, {"beat": 5, "beat_both": 1, "open_palms": 2, "sweep": 1, "point": 0}),
    "presenter": (0.85, 1.0, {"beat": 4, "beat_both": 2, "open_palms": 3, "sweep": 2, "point": 1}),
    "energetic": (1.0, 1.3, {"beat": 3, "beat_both": 3, "open_palms": 3, "sweep": 3, "point": 2}),
}
# semantic gestures: (one | both, prep target, stroke target, (prep shape, stroke shape),
#                     (palm direction, weight) or None, minimum hold in seconds)
PALMS = {"forward": (0, -1, 0), "up": (0, 0, 1), "down": (0, 0, -1), "medial": (1, 0, 0),
         "body": (0, 1, 0)}
SEMANTIC = {
    "one": ("one", (-0.12, -0.15, -0.13), (-0.13, -0.17, -0.02), ("relaxed", "point"), ("forward", 1), 0.5),
    "two": ("one", (-0.12, -0.15, -0.13), (-0.13, -0.17, -0.02), ("relaxed", "peace"), ("forward", 1), 0.5),
    "three": ("one", (-0.12, -0.15, -0.13), (-0.13, -0.17, -0.02), ("relaxed", "three"), ("forward", 1), 0.5),
    "four": ("one", (-0.12, -0.15, -0.13), (-0.13, -0.17, -0.02), ("relaxed", "four"), ("forward", 1), 0.5),
    "five": ("one", (-0.12, -0.15, -0.13), (-0.13, -0.17, -0.02), ("relaxed", "open"), ("forward", 1), 0.5),
    "self": ("one", (-0.09, -0.15, -0.17), (-0.06, -0.10, -0.13), ("relaxed", "palm"), ("body", 1), 0.45),
    "you": ("one", (-0.09, -0.19, -0.21), (-0.08, -0.30, -0.15), ("relaxed", "palm"), ("up", 0.9), 0.4),
    "this": ("one", (-0.10, -0.20, -0.16), (-0.09, -0.26, -0.24), ("relaxed", "point"), ("down", 0.7), 0.35),
    "that": ("one", (-0.12, -0.21, -0.13), (-0.14, -0.28, -0.07), ("relaxed", "point"), ("down", 0.7), 0.4),
    "big": ("both", (-0.10, -0.20, -0.16), (-0.20, -0.18, -0.12), ("relaxed", "open"), ("medial", 0.8), 0.45),
    "small": ("one", (-0.09, -0.20, -0.15), (-0.06, -0.26, -0.09), ("relaxed", "ok"), ("medial", 0.8), 0.45),
    "no": ("both", (-0.04, -0.23, -0.15), (-0.19, -0.24, -0.17), ("relaxed", "palm"), ("down", 1), 0.3),
    "good": ("one", (-0.09, -0.20, -0.17), (-0.07, -0.27, -0.09), ("relaxed", "thumbs_up"), ("medial", 1), 0.5),
    "question": ("both", (-0.10, -0.17, -0.22), (-0.17, -0.21, -0.18), ("relaxed", "open"), ("up", 0.9), 0.4),
    "stop": ("one", (-0.10, -0.20, -0.13), (-0.11, -0.27, -0.04), ("relaxed", "palm"), ("forward", 1), 0.45),
    "up": ("one", (-0.12, -0.20, -0.22), (-0.13, -0.21, 0.02), ("relaxed", "palm"), ("up", 0.8), 0.3),
    "down": ("one", (-0.12, -0.21, -0.07), (-0.12, -0.20, -0.27), ("relaxed", "palm"), ("down", 1), 0.3),
    "together": ("both", (-0.22, -0.20, -0.15), (-0.05, -0.24, -0.15), ("open", "palm"), ("medial", 1), 0.4),
    "think": ("one", (-0.12, -0.15, -0.09), (-0.12, -0.08, 0.06), ("relaxed", "point"), ("forward", 0.6), 0.5),
    "love": ("both", (-0.09, -0.15, -0.17), (-0.05, -0.10, -0.13), ("relaxed", "palm"), ("body", 1), 0.5),
}
SEMANTIC_GAP = {"calm": (1.4, 0.5), "presenter": (1.0, 0.8), "energetic": (0.8, 1.0)}  # (s, sparse p)
REST = None                         # key-pose marker: the speaking posture


def _blend(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _scale(rest, pose, amp):
    return tuple(r + (p - r) * amp for r, p in zip(rest, pose))


def _ease(t):
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


def _ik_elbow(S, H, a, b, pole):
    """Elbow position for a 2-bone chain shoulder S -> hand H with lengths a, b."""
    d_vec = H - S
    d = max(min(d_vec.length, (a + b) * 0.985), abs(a - b) + 1e-4)
    u = d_vec.normalized()
    cos_a = max(-1.0, min(1.0, (a * a + d * d - b * b) / (2 * a * d)))
    perp = pole - u * pole.dot(u)
    if perp.length < 1e-6:
        perp = Vector((0, 0, -1)) - u * u.z
    perp.normalize()
    return S + a * (u * cos_a + perp * math.sqrt(max(0.0, 1 - cos_a * cos_a))), S + u * d


def _aim(rig, pb, target_dir, weight):
    """Rotate pose bone so its Y axis points along target_dir (minimal twist), blended."""
    mw = rig.matrix_world @ pb.matrix
    q_base = mw.to_quaternion()
    y = Vector((mw[0][1], mw[1][1], mw[2][1])).normalized()
    q_goal = y.rotation_difference(target_dir.normalized()) @ q_base
    if q_base.dot(q_goal) < 0:
        q_goal.negate()
    q = q_base.slerp(q_goal, weight)
    pb.matrix = rig.matrix_world.inverted() @ Matrix.LocRotScale(mw.translation, q, mw.to_scale())


def _rot_world(rig, pb, q):
    """Rotate a pose bone by world-space quaternion q about its own head."""
    mw = rig.matrix_world @ pb.matrix
    t = mw.translation.copy()
    new = Matrix.Translation(t) @ q.to_matrix().to_4x4() @ Matrix.Translation(-t) @ mw
    pb.matrix = rig.matrix_world.inverted() @ new


def _palm_world(rig, pb, palm_local):
    return ((rig.matrix_world @ pb.matrix).to_3x3() @ palm_local).normalized()


def _orient_palm(rig, fo_pb, hand_pb, palm_local, target, weight,
                 forearm_share=0.5, max_twist=115.0, max_flex=50.0):
    """Turn the palm toward target: twist shared by forearm and wrist, then a little wrist flex."""
    vl = bpy.context.view_layer
    axis = (rig.matrix_world.to_3x3() @ (fo_pb.tail - fo_pb.head)).normalized()
    now = _palm_world(rig, hand_pb, palm_local)
    a = now - axis * now.dot(axis)
    b = target - axis * target.dot(axis)
    twist = 0.0
    if a.length > 1e-3 and b.length > 1e-3:
        ang = a.normalized().angle(b.normalized())
        sign = 1.0 if a.cross(b).dot(axis) > 0 else -1.0
        twist = sign * min(ang, math.radians(max_twist)) * weight
        _rot_world(rig, fo_pb, Quaternion(axis, twist * forearm_share))
        vl.update()
        _rot_world(rig, hand_pb, Quaternion(axis, twist * (1 - forearm_share)))
        vl.update()
    now = _palm_world(rig, hand_pb, palm_local)
    q = now.rotation_difference(target)
    flex = min(q.angle, math.radians(max_flex)) * weight
    if flex > 1e-4:
        _rot_world(rig, hand_pb, Quaternion(q.axis, flex))
        vl.update()
    return math.degrees(twist), math.degrees(flex)


def _track(events, side):
    """Key poses (frame, state | REST) for one hand; gestures close together flow directly."""
    keys = []
    for ev in sorted((e for e in events if side in e["hands"]), key=lambda e: e["frame"]):
        ek = [(ev["frame"] + o, st) for o, st in ev["keys"]]
        first_pose = ek[1][0]
        keys = [k for k in keys if k[0] <= first_pose - 4]
        if keys and (keys[-1][1] is not REST or keys[-1][0] >= ek[0][0]):
            ek = ek[1:]               # go straight from the previous gesture into this one
        keys += ek
    return keys


def _eval(keys, frame, rest):
    """State at frame: (target, shape, palm (vec, weight) | None)."""
    def st(s):
        return rest if s is REST else s
    if not keys or frame <= keys[0][0]:
        return st(keys[0][1]) if keys else rest
    if frame >= keys[-1][0]:
        return st(keys[-1][1])
    for (fa, sa), (fb, sb) in zip(keys, keys[1:]):
        if fa <= frame < fb:
            a, b = st(sa), st(sb)
            t = _ease((frame - fa) / max(fb - fa, 1e-6))
            pa, pb = a[2], b[2]
            if pa or pb:
                va = Vector(pa[0] if pa else pb[0])
                vb = Vector(pb[0] if pb else pa[0])
                wa, wb = (pa[1] if pa else 0.0), (pb[1] if pb else 0.0)
                v = va.lerp(vb, t)
                palm = (tuple(v.normalized()) if v.length > 1e-6 else tuple(vb), wa + (wb - wa) * t)
            else:
                palm = None
            return _blend(a[0], b[0], t), blend_shapes(a[1], b[1], t), palm
    return rest


def _beat_event(p, g, use, k):
    _kind, prep, stroke = GESTURES[g]
    s_prep, s_stroke = HAND_SHAPES[g]
    pose_p = (_scale(TALK_REST, prep, k), s_prep, None)
    pose_s = (_scale(TALK_REST, stroke, k), s_stroke, None)
    return {"frame": p, "type": g, "hands": use, "kind": "beat",
            "keys": [(-11, REST), (-6, pose_p), (0, pose_s), (3, pose_s), (14, REST)]}


def _semantic_event(p, g, use, hold, word=None):
    _kind, prep, stroke, (s_prep, s_stroke), palm, _hold_s = SEMANTIC[g]
    pv = (PALMS[palm[0]], palm[1]) if palm else None
    pose_p = (prep, s_prep, (pv[0], pv[1] * 0.5) if pv else None)
    pose_s = (stroke, s_stroke, pv)
    hold = max(3, int(hold))
    return {"frame": p, "type": g, "hands": use, "kind": "semantic", "word": word,
            "keys": [(-13, REST), (-6, pose_p), (0, pose_s), (hold, pose_s), (hold + 12, REST)]}


@command("talk_gestures")
def talk_gestures(character, frame_start=None, frame_end=None, style="presenter", hands="both",
                  intensity=1.0, seed=5, fingers=True, semantic=True, cues=None, collisions=True):
    """Add speech-timed arm gestures: beats on stressed syllables plus gestures that show the
    meaning of words (numbers, me/you, big/small, no, good, ...)."""
    if style not in STYLES:
        raise ValueError(f"style must be one of {list(STYLES)}")
    if hands not in ("both", "left", "right"):
        raise ValueError("hands must be 'both', 'left' or 'right'")
    rig = _rig_of(character)
    sc = bpy.context.scene
    fps = sc.render.fps
    f0 = int(frame_start if frame_start is not None else sc.frame_start)
    f1 = int(frame_end if frame_end is not None else sc.frame_end)
    rng = random.Random(seed)
    prob, amp, weights = STYLES[style]
    amp *= float(intensity)
    for c in cues or []:
        if c.get("gesture") not in SEMANTIC:
            raise ValueError(f"cue gesture must be one of {sorted(SEMANTIC)}: {c}")

    # ---- speech rhythm
    env, sources = _audio_activity(f0, f1, rig.name)
    source = "audio:" + ",".join(sources) if sources else None
    base_mesh = None
    try:
        base_mesh = _basemesh(rig.name)
    except Exception:   # mannequins have no face mesh
        pass
    if env.max() <= 1e-6 and base_mesh is not None:
        try:
            env = _viseme_activity(base_mesh, f0, f1)
            source = "lip_sync_keys" if env.max() > 1e-6 else None
        except (ValueError, RuntimeError):
            pass
    if env.max() <= 1e-6 and cues:
        source = "cues"
    if env.max() <= 1e-6 and not cues:
        raise ValueError("no speech found in the range: add audio (lip_sync_audio/add_audio) "
                         "or lip_sync first")
    if env.max() > 1e-6:
        env = _smooth(env / env.max(), 7)
    n = len(env)
    peaks = _peaks(env, fps, min_gap_s=0.55) if env.max() > 0 else []
    phrases = _phrases(env, fps, gap_s=0.6) if env.max() > 0 else []

    # ---- activity weight: 1 while talking (with lead-in / lead-out), 0 otherwise
    w = np.zeros(n)
    lead_in, lead_out = int(fps * 0.5), int(fps * 0.7)
    for a, b in phrases:
        for i in range(max(0, a - lead_in), min(n, b + lead_out)):
            if i < a:
                t = (i - (a - lead_in)) / lead_in
            elif i > b:
                t = 1 - (i - b) / lead_out
            else:
                t = 1.0
            w[i] = max(w[i], _ease(t))

    sides = {"both": ("R", "L"), "right": ("R",), "left": ("L",)}[hands]
    one_hand = ("L",) if hands == "left" else ("R",)

    # ---- semantic gestures on meaningful words (and explicit cues)
    events = []
    words = load_words(base_mesh, f0, f1) if (semantic and base_mesh is not None) else []
    min_gap, sparse = SEMANTIC_GAP[style]
    cands = []
    for idx, g in (match(words) if words else []):
        word, ws, we = words[idx]
        stroke = ws + min(0.12 * fps, 0.35 * (we - ws))          # lands early in the word
        cands.append((int(round(stroke)) - f0, g, word, we - f0))
    picked = select([(c[0], c[1], c[2]) for c in cands], fps, min_gap, rng, sparse)
    ends = {(c[0], c[1]): c[3] for c in cands}
    for p, g, word in picked:
        if not 0 <= p < n:
            continue
        hold = max(SEMANTIC[g][5] * fps, ends[(p, g)] - p + 2)
        use = ("L", "R") if SEMANTIC[g][0] == "both" and hands == "both" else one_hand
        events.append(_semantic_event(p, g, use, min(hold, 1.2 * fps), word))
    for c in cues or []:
        p = int(c["frame"]) - f0
        g = c["gesture"]
        if not 0 <= p < n:
            continue
        side = c.get("hands", "auto")
        use = {"left": ("L",), "right": ("R",), "both": ("L", "R")}.get(
            side, ("L", "R") if SEMANTIC[g][0] == "both" and hands == "both" else one_hand)
        hold = float(c.get("hold_seconds", SEMANTIC[g][5])) * fps
        events = [e for e in events if abs(e["frame"] - p) > 0.6 * fps]   # cue wins
        events.append(_semantic_event(p, g, use, hold, c.get("word")))
    busy = [(e["frame"] + e["keys"][0][0], e["frame"] + e["keys"][-1][0]) for e in events]

    # ---- beats on emphasis peaks (not inside a semantic gesture)
    names, wts = zip(*[(k, v) for k, v in weights.items() if v > 0])
    last_side = None
    for p in peaks:
        if w[p] < 0.5 or rng.random() > prob:
            continue
        g = rng.choices(names, wts)[0]
        if any(a - 4 <= p <= b + 2 for a, b in busy):     # tracks blend the neighbours
            continue
        kind = GESTURES[g][0]
        if kind == "both" and hands == "both":
            use = ("L", "R")
        else:
            options = [s for s in sides if s != last_side] or list(sides)
            use = (rng.choice(options),)
            last_side = use[0]
        events.append(_beat_event(p, g, use, amp * rng.uniform(0.75, 1.0) * env[p]))

    # semantic gestures stay fully on even at a phrase edge
    for e in events:
        if e["kind"] != "semantic":
            continue
        a, b = e["frame"] + e["keys"][0][0], e["frame"] + e["keys"][-1][0]
        for i in range(max(0, a - 6), min(n, b + 6)):
            ramp = 1.0 if a <= i <= b else _ease(1 - (a - i) / 6 if i < a else 1 - (i - b) / 6)
            w[i] = max(w[i], ramp)

    rest_state = (TALK_REST, "relaxed", None)
    tracks = {s: _track(events, s) for s in ("L", "R")}

    smap = semantic_map(rig)
    chain = {s: (smap.get(f"upper_arm.{s}"), smap.get(f"forearm.{s}")) for s in ("L", "R")}
    if not all(all(c) for c in chain.values()):
        raise ValueError(f"cannot find arm bones on {rig.name}")
    chest_b = smap.get("chest") or smap.get("spine")
    neck_b = smap.get("neck")
    if not chest_b or not neck_b:
        raise ValueError(f"cannot find chest/neck bones on {rig.name}")
    twm = rig.matrix_world
    twq = twm.to_quaternion()
    bones = rig.data.bones
    seg = {s: ((bones[u].tail_local - bones[u].head_local).length,
               (bones[f].tail_local - bones[f].head_local).length) for s, (u, f) in chain.items()}
    lm_top = max(b.tail_local.z for b in bones)
    lm_low = min(b.head_local.z for b in bones)
    H = max(lm_top - lm_low, 0.5) * twm.to_scale().z * 1.08   # bones stop a bit below head top
    keyed = [b for c in chain.values() for b in c]
    hand_rig = HandRig(rig) if fingers else None
    finger_bones = hand_rig.bones if hand_rig else []
    hand_b = {s: smap.get(f"hand.{s}") for s in ("L", "R")}
    palm_local = {}
    probe = hand_rig or HandRig(rig)
    for s in ("L", "R"):
        if hand_b[s] and hand_b[s] in rig.pose.bones:
            palm_local[s] = probe.palm_local(s, hand_b[s])
    hand_bones = [hand_b[s] for s in ("L", "R") if palm_local.get(s) is not None]
    all_bones = keyed + hand_bones + finger_bones

    base = {}
    for i in range(n):                       # pass 1: untouched base pose of the arm bones
        sc.frame_set(f0 + i)
        base[f0 + i] = {b: rig.pose.bones[b].matrix_basis.copy() for b in all_bones}
    prev = {}
    max_twist = 0.0
    for i in range(n):
        f = f0 + i
        sc.frame_set(f)
        for b in all_bones:
            rig.pose.bones[b].matrix_basis = base[f][b]
        bpy.context.view_layer.update()
        if w[i] > 1e-3:
            breath = 0.006 * math.sin(2 * math.pi * f / (fps * 3.2))
            state = {s: _eval(tracks[s], i, rest_state) for s in ("L", "R")}
            if hand_rig:
                for side in hand_rig.fingers:
                    hand_rig.apply(side, state[side][1], float(w[i]), base[f])
            chest = twm @ rig.pose.bones[chest_b].matrix
            c_rot = chest.to_quaternion() @ (twm @ bones[chest_b].matrix_local).to_quaternion().inverted()
            c_rot = twq.inverted() @ c_rot @ twq
            origin = (twm @ rig.pose.bones[neck_b].matrix).translation   # base of the neck
            for s, (ub, fb) in chain.items():
                x, y, z = state[s][0]
                mx = -1.0 if s == "L" else 1.0
                local = Vector((x * mx, y, z + breath)) * H
                hand = origin + twq @ (c_rot @ local)
                pole = twq @ (c_rot @ Vector((0.45 if s == "L" else -0.45, 0.35, -1.0)))
                up_pb, fo_pb = rig.pose.bones[ub], rig.pose.bones[fb]
                S = (twm @ up_pb.matrix).translation
                a, b_len = seg[s]
                scale = twm.to_scale().z
                E, Hc = _ik_elbow(S, hand, a * scale, b_len * scale, pole)
                _aim(rig, up_pb, E - S, float(w[i]))
                bpy.context.view_layer.update()
                E_now = (twm @ fo_pb.matrix).translation
                _aim(rig, fo_pb, Hc - E_now, float(w[i]))
                bpy.context.view_layer.update()
                palm = state[s][2]
                if palm and palm[1] > 1e-3 and palm_local.get(s) is not None:
                    pv = Vector((palm[0][0] * mx, palm[0][1], palm[0][2]))
                    target = (twq @ (c_rot @ pv)).normalized()
                    tw, _fl = _orient_palm(rig, fo_pb, rig.pose.bones[hand_b[s]], palm_local[s],
                                           target, float(w[i]) * palm[1])
                    max_twist = max(max_twist, abs(tw))
        for b in all_bones:
            _key_rot(rig.pose.bones[b], f, prev)
    sc.frame_set(f0)
    beats = [e for e in events if e["kind"] == "beat"]
    sem = [e for e in events if e["kind"] == "semantic"]
    from .collision import record_contact, automatic, forget_contacts
    forget_contacts(rig,f0,f1,'semantic:')
    for event in sem:
        if event['type'] in ('self', 'love', 'think'):
            for side in event['hands']:
                record_contact(rig, side, f0+event['frame'],
                    min(f1, f0+event['frame']+event['keys'][3][0]), 'semantic:'+event['type'],
                    part='head' if event['type'] == 'think' else 'chest')
    collision_report = automatic(collisions, [rig.name], f0, f1, parts=['arms', 'props', 'clothes'])
    return {"character": rig.name, "frames": [f0, f1], "driven_by": source, "style": style,
            "gestures": [{"frame": f0 + e["frame"], "type": e["type"], "hands": list(e["hands"])}
                         for e in sorted(beats, key=lambda e: e["frame"])],
            "semantic": [{"frame": f0 + e["frame"], "type": e["type"], "word": e["word"],
                          "hands": list(e["hands"])}
                         for e in sorted(sem, key=lambda e: e["frame"])],
            "words_known": len(words), "talking_frames": int((w > 0.5).sum()),
            "arm_bones": keyed, "hand_bones": hand_bones, "finger_bones": len(finger_bones),
            "max_palm_twist_deg": round(max_twist, 1), 'collisions': collision_report}
