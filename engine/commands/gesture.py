"""Speech-driven arm and hand gestures, layered over existing body animation.

Each gesture is a target HAND POSITION relative to the base of the neck (in fractions of
the character's height; it rotates with the chest; +X = character's left, -Y = forward, +Z = up). A two-bone analytic IK
places the elbow (pointing down/back/out), the upper arm and forearm are aimed with minimal
rotation from their current pose, and the hand simply follows the forearm. Targets follow the
chest every frame, so gestures stay attached while the torso moves. Outside speech the arms
blend back to their base animation.
"""
import math
import random

import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import command
from .anim import _key_rot, semantic_map
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
STYLES = {  # (gesture probability per emphasis, amplitude, weights per gesture)
    "calm": (0.55, 0.65, {"beat": 5, "beat_both": 1, "open_palms": 2, "sweep": 1, "point": 0}),
    "presenter": (0.85, 1.0, {"beat": 4, "beat_both": 2, "open_palms": 3, "sweep": 2, "point": 1}),
    "energetic": (1.0, 1.3, {"beat": 3, "beat_both": 3, "open_palms": 3, "sweep": 3, "point": 2}),
}


def _blend(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _scale(rest, pose, amp):
    return tuple(r + (p - r) * amp for r, p in zip(rest, pose))


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


@command("talk_gestures")
def talk_gestures(character, frame_start=None, frame_end=None, style="presenter", hands="both",
                  intensity=1.0, seed=5):
    """Add speech-timed arm gestures (beats, open palms, sweeps, points) over a range."""
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

    # ---- speech rhythm
    env, sources = _audio_activity(f0, f1)
    source = "audio:" + ",".join(sources) if sources else None
    if env.max() <= 1e-6:
        try:
            env = _viseme_activity(_basemesh(rig.name), f0, f1)
            source = "lip_sync_keys"
        except (ValueError, RuntimeError):
            pass
    if env.max() <= 1e-6:
        raise ValueError("no speech found in the range: add audio (lip_sync_audio/add_audio) "
                         "or lip_sync first")
    env = _smooth(env / env.max(), 7)
    n = len(env)
    peaks = _peaks(env, fps, min_gap_s=0.55)
    phrases = _phrases(env, fps, gap_s=0.6)

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
            w[i] = max(w[i], 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t))))

    # ---- choose gestures on emphasis peaks
    sides = {"both": ("R", "L"), "right": ("R",), "left": ("L",)}[hands]
    names, wts = zip(*[(k, v) for k, v in weights.items() if v > 0])
    events = []
    last_side = None
    for p in peaks:
        if w[p] < 0.5 or rng.random() > prob:
            continue
        g = rng.choices(names, wts)[0]
        kind = GESTURES[g][0]
        if kind == "both" and hands == "both":
            use = ("L", "R")
        else:
            options = [s for s in sides if s != last_side] or list(sides)
            use = (rng.choice(options),)
            last_side = use[0]
        events.append((p, g, use, rng.uniform(0.75, 1.0) * env[p]))

    # ---- per-frame hand targets (chest space, fractions of height), right-hand convention
    def targets_at(i):
        out = {"R": TALK_REST, "L": TALK_REST}
        breath = 0.006 * math.sin(2 * math.pi * (f0 + i) / (fps * 3.2))
        out = {s: (v[0], v[1], v[2] + breath) for s, v in out.items()}
        for p, g, use, strength in events:
            _kind, prep, stroke = GESTURES[g]
            prep_len, hold, back = 6, 3, 11
            d = i - p
            if -prep_len - 5 <= d < -prep_len:           # rise to the preparation
                t, frm, to = (d + prep_len + 5) / 5, "rest", "prep"
            elif -prep_len <= d < 0:                     # stroke lands on the stressed syllable
                t, frm, to = (d + prep_len) / prep_len, "prep", "stroke"
            elif 0 <= d < hold:
                t, frm, to = 1.0, "stroke", "stroke"
            elif hold <= d < hold + back:                # retract
                t, frm, to = (d - hold) / back, "stroke", "rest"
            else:
                continue
            t = 0.5 - 0.5 * math.cos(math.pi * t)
            k = amp * strength
            sel = {"rest": TALK_REST, "prep": _scale(TALK_REST, prep, k),
                   "stroke": _scale(TALK_REST, stroke, k)}
            for s in use:
                out[s] = _blend(sel[frm], sel[to], t)
        return out

    smap = semantic_map(rig)
    chain = {s: (smap.get(f"upper_arm.{s}"), smap.get(f"forearm.{s}")) for s in ("L", "R")}
    if not all(all(c) for c in chain.values()):
        raise ValueError(f"cannot find arm bones on {rig.name}")
    chest_b = smap.get("chest") or smap.get("spine")
    neck_b = smap.get("neck")
    if not chest_b or not neck_b:
        raise ValueError(f"cannot find chest/neck bones on {rig.name}")
    twm = rig.matrix_world
    bones = rig.data.bones
    seg = {s: ((bones[u].tail_local - bones[u].head_local).length,
               (bones[f].tail_local - bones[f].head_local).length) for s, (u, f) in chain.items()}
    lm_top = max(b.tail_local.z for b in bones)
    lm_low = min(b.head_local.z for b in bones)
    H = max(lm_top - lm_low, 0.5) * twm.to_scale().z * 1.08   # bones stop a bit below head top
    keyed = [b for c in chain.values() for b in c]

    base = {}
    for i in range(n):                       # pass 1: untouched base pose of the arm bones
        sc.frame_set(f0 + i)
        base[f0 + i] = {b: rig.pose.bones[b].matrix_basis.copy() for b in keyed}
    prev = {}
    for i in range(n):
        f = f0 + i
        sc.frame_set(f)
        for b in keyed:
            rig.pose.bones[b].matrix_basis = base[f][b]
        bpy.context.view_layer.update()
        if w[i] > 1e-3:
            chest = twm @ rig.pose.bones[chest_b].matrix
            c_rot = chest.to_quaternion() @ (twm @ bones[chest_b].matrix_local).to_quaternion().inverted()
            c_rot = twm.to_quaternion().inverted() @ c_rot @ twm.to_quaternion()
            origin = (twm @ rig.pose.bones[neck_b].matrix).translation   # base of the neck
            tg = targets_at(i)
            for s, (ub, fb) in chain.items():
                x, y, z = tg[s]
                if s == "L":
                    x = -x
                local = Vector((x, y, z)) * H
                hand = origin + twm.to_quaternion() @ (c_rot @ local)
                pole = twm.to_quaternion() @ (c_rot @ Vector((0.45 if s == "L" else -0.45, 0.35, -1.0)))
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
        for b in keyed:
            _key_rot(rig.pose.bones[b], f, prev)
    sc.frame_set(f0)
    return {"character": rig.name, "frames": [f0, f1], "driven_by": source, "style": style,
            "gestures": [{"frame": f0 + p, "type": g, "hands": list(u)} for p, g, u, _s in events],
            "talking_frames": int((w > 0.5).sum()), "arm_bones": keyed}
