"""Animation: pose library, procedural clips, world-space retargeting, mocap import.

Everything is authored once on the 21-bone *basic* skeleton (see rig.BASIC). Other rigs
(Rigify, imported Mixamo/CMU/... skeletons) are driven through `retarget`, which copies
world-space rotation deltas bone by bone, aligning rest poses (T vs A pose) and facing.

Pose/clip values are local XYZ Euler degrees on basic bones, written in LEFT-side
convention for both sides (.R values are mirrored: y and z negated). Upper-arm Z is
relative to a T-pose (0 = horizontal, -90 = down, +90 = up), whatever the rest pose is.
"""
import json
import math
import os
from functools import wraps

import bpy
from mathutils import Matrix, Quaternion, Vector

from .. import context
from ..motion_library import FLOOR, MOTIONS, cycle_frames, total_frames, score
from . import command
from . import rig as rigmod
from .util import obj_or_raise

# ----------------------------------------------------------------------------- bone maps
BASIC_BONES = list(rigmod.BASIC)

BASIC_TO_RIGIFY = {"hips": "torso", "chest": "chest", "neck": "neck", "head": "head"}
for _s in "LR":
    BASIC_TO_RIGIFY.update({
        f"shoulder.{_s}": f"shoulder.{_s}", f"upper_arm.{_s}": f"upper_arm_fk.{_s}",
        f"forearm.{_s}": f"forearm_fk.{_s}", f"hand.{_s}": f"hand_fk.{_s}",
        f"thigh.{_s}": f"thigh_fk.{_s}", f"shin.{_s}": f"shin_fk.{_s}",
        f"foot.{_s}": f"foot_fk.{_s}", f"toe.{_s}": f"toe_fk.{_s}",
    })

# name heuristics for foreign skeletons (Mixamo, CMU BVH, Unreal, Unity, MakeHuman...)
_ALIASES = {
    "hips": ["hips", "pelvis", "hip", "root_hips"],
    "spine": ["spine", "lowerback", "spine01", "abdomen", "spine_01"],
    "chest": ["spine2", "chest", "spine1", "spine02", "spine_02", "upperchest", "spine03"],
    "neck": ["neck", "neck01", "neck1", "neck_01"],
    "head": ["head"],
    "shoulder": ["{s}shoulder", "{s}collar", "clavicle{s}", "{s}clavicle", "shoulder{s}"],
    "upper_arm": ["{s}arm", "{s}shldr", "{s}upperarm", "upperarm{s}", "{s}uparm", "arm{s}"],
    "forearm": ["{s}forearm", "{s}lowerarm", "lowerarm{s}", "forearm{s}", "{s}lowarm"],
    "hand": ["{s}hand", "hand{s}"],
    "thigh": ["{s}upleg", "{s}thigh", "{s}upperleg", "thigh{s}", "upperleg{s}", "{s}hip"],
    "shin": ["{s}leg", "{s}shin", "{s}lowerleg", "calf{s}", "{s}calf", "shin{s}", "lowerleg{s}", "{s}knee"],
    "foot": ["{s}foot", "foot{s}", "{s}ankle"],
    "toe": ["{s}toebase", "{s}toe", "ball{s}", "toe{s}", "{s}toes", "{s}ball"],
}
_SIDE_TOKENS = {"L": ["left", "l"], "R": ["right", "r"]}


def _norm(name):
    name = name.split(":")[-1].lower()
    for ch in "_-. ":
        name = name.replace(ch, "")
    return name


def heuristic_map(rig):
    """basic bone name -> bone name in `rig`, guessed from common naming schemes."""
    if all(b in rig.pose.bones for b in BASIC_BONES):
        return {b: b for b in BASIC_BONES}
    lookup = {}
    for b in rig.data.bones:
        lookup.setdefault(_norm(b.name), b.name)
    out = {}
    for key, pats in _ALIASES.items():
        sides = ("L", "R") if any("{s}" in p for p in pats) else (None,)
        for side in sides:
            target = f"{key}.{side}" if side else key
            for pat in pats:
                cands = [pat] if side is None else [pat.format(s=t) for t in _SIDE_TOKENS[side]]
                hit = next((lookup[c] for c in cands if c in lookup), None)
                if hit:
                    out[target] = hit
                    break
    return out


def semantic_map(rig):
    kind = rig.get("c3d_rig_type")
    if kind == "basic":
        return {b: b for b in BASIC_BONES}
    if kind == "rigify":
        return {k: v for k, v in BASIC_TO_RIGIFY.items() if v in rig.pose.bones}
    return heuristic_map(rig)


# Limb joints only: Rigify torso/neck controls sit away from the DEF joints the
# landmarks were measured on, while FK limb controls share their heads.
_LANDMARK_BONES = {**{f"{k}.{s}": f"{b}.{s}" for s in "LR" for k, b in (
                       ("shoulder", "upper_arm"), ("elbow", "forearm"), ("wrist", "hand"),
                       ("hip", "thigh"), ("knee", "shin"), ("ankle", "foot"))}}


def _follow_rig(rig, smap, stored):
    """Stored landmarks are world positions from when the rig was built. Re-place them
    rigidly on the rig's current rest joints, so a rig moved/rotated afterwards (e.g.
    transform_object to face a partner) still gets a proxy facing its real front."""
    import numpy as np
    keys = [k for k, b in _LANDMARK_BONES.items()
            if k in stored and b in smap and smap[b] in rig.data.bones]
    if len(keys) < 4:
        return stored
    mw = rig.matrix_world
    now = np.array([list(mw @ rig.data.bones[smap[_LANDMARK_BONES[k]]].head_local) for k in keys])
    old = np.array([list(stored[k]) for k in keys])
    if np.abs(now - old).max() < 1e-5:
        return stored                                  # unmoved: exactly as before
    # Similarity fit (Umeyama): rotation, translation and the rig's uniform scale.
    co, cn = old.mean(axis=0), now.mean(axis=0)
    a, b = old - co, now - cn
    u, sv, vt = np.linalg.svd(a.T @ b)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    rot = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    scale = float((sv * [1.0, 1.0, d]).sum() / max((a * a).sum(), 1e-12))
    moved = scale * a @ rot.T + cn
    if np.linalg.norm(moved - now, axis=1).max() > 0.03:
        return stored                                  # not a rigid move: keep old data
    R, c0, c1 = Matrix(rot.tolist()) * scale, Vector(co.tolist()), Vector(cn.tolist())
    return {k: R @ (v - c0) + c1 for k, v in stored.items()}


def _rig_landmarks(rig, smap):
    """Landmarks for building a basic proxy that matches `rig`'s proportions."""
    if rig.get("c3d_landmarks"):
        stored = {k: Vector(v) for k, v in json.loads(rig["c3d_landmarks"]).items()}
        return _follow_rig(rig, smap, stored)
    need = ["hips", "spine", "chest", "neck", "head"] + [
        f"{b}.{s}" for b in ("shoulder", "upper_arm", "forearm", "hand", "thigh", "shin", "foot")
        for s in "LR"]
    missing = [n for n in need if n not in smap]
    if missing:
        raise ValueError(f"cannot recognise humanoid bones {missing} in {rig.name}; "
                         "pass bone_map={basic_name: your_bone}")
    mw = rig.matrix_world

    def head(n):
        return mw @ rig.data.bones[smap[n]].head_local

    def tail(n):
        return mw @ rig.data.bones[smap[n]].tail_local

    lm = {
        "hips": head("hips"), "waist": head("spine"), "chest": head("chest"),
        "neck_base": head("neck"), "chin": head("head"), "head_top": tail("head"),
    }
    lm["upper_chest"] = lm["chest"].lerp(lm["neck_base"], 0.5)
    lm["neck"] = lm["neck_base"].lerp(lm["chin"], 0.5)
    lm["head_center"] = lm["chin"].lerp(lm["head_top"], 0.5)
    for s in "LR":
        lm[f"clavicle.{s}"] = head(f"shoulder.{s}")
        lm[f"shoulder.{s}"] = head(f"upper_arm.{s}")
        lm[f"elbow.{s}"] = head(f"forearm.{s}")
        lm[f"wrist.{s}"] = head(f"hand.{s}")
        lm[f"hand_tip.{s}"] = tail(f"hand.{s}")
        lm[f"hip.{s}"] = head(f"thigh.{s}")
        lm[f"knee.{s}"] = head(f"shin.{s}")
        lm[f"ankle.{s}"] = head(f"foot.{s}")
        if f"toe.{s}" in smap:
            lm[f"ball.{s}"], lm[f"toe_tip.{s}"] = head(f"toe.{s}"), tail(f"toe.{s}")
        else:
            lm[f"ball.{s}"] = tail(f"foot.{s}")
            lm[f"toe_tip.{s}"] = lm[f"ball.{s}"] + (lm[f"ball.{s}"] - lm[f"ankle.{s}"]) * 0.4
        lm[f"heel.{s}"] = Vector((lm[f"ankle.{s}"].x, lm[f"ankle.{s}"].y + 0.05, 0.0))
    return lm


# ----------------------------------------------------------------------------- pose data
def _arm_rest_deg(lm):
    sh, el = Vector(lm["shoulder.L"]), Vector(lm["elbow.L"])
    d = el - sh
    return math.degrees(math.atan2(-d.z, max(abs(d.x), 1e-6)))


RELAXED = {"upper_arm.L": [0, 0, -78], "upper_arm.R": [0, 0, -78],
           "forearm.L": [12, 0, 0], "forearm.R": [12, 0, 0]}

POSES = {
    "rest": ({}, "Rest pose of the rig (A-pose for create_human characters)."),
    "t_pose": ({"upper_arm.L": [0, 0, 0], "upper_arm.R": [0, 0, 0]}, "Arms horizontal."),
    "relaxed": (RELAXED, "Standing, arms hanging naturally."),
    "wave": ({**RELAXED, "upper_arm.R": [0, 0, 45], "forearm.R": [0, 0, 70],
              "head": [0, 0, 6]}, "Right hand raised, waving hello."),
    "cheer": ({"upper_arm.L": [0, 0, 70], "upper_arm.R": [0, 0, 70],
               "forearm.L": [0, 0, 15], "forearm.R": [0, 0, 15], "head": [-12, 0, 0],
               "chest": [-8, 0, 0]}, "Both arms up in a V, chest lifted."),
    "point_forward": ({**RELAXED, "upper_arm.R": [80, 0, 0], "forearm.R": [5, 0, 0]},
                      "Right arm pointing straight ahead."),
    "hands_on_hips": ({"upper_arm.L": [-12, 0, -42], "upper_arm.R": [-12, 0, -42],
                       "forearm.L": [10, 0, -75], "forearm.R": [10, 0, -75]},
                      "Confident stance, fists on hips."),
    "thinking": ({**RELAXED, "upper_arm.R": [65, 0, -82], "forearm.R": [135, 0, 0],
                  "head": [8, 0, -6], "spine": [4, 0, 0]}, "Hand to chin, head tilted."),
    "crouch": ({**RELAXED, "spine": [20, 0, 0], "thigh.L": [75, 0, 0], "thigh.R": [75, 0, 0],
                "shin.L": [-110, 0, 0], "shin.R": [-110, 0, 0], "foot.L": [35, 0, 0],
                "foot.R": [35, 0, 0], "upper_arm.L": [30, 0, -70], "upper_arm.R": [30, 0, -70],
                "forearm.L": [40, 0, 0], "forearm.R": [40, 0, 0]},
               "Squatting low (use with hips offset down: hips_drop).", ),
    "sit": ({**RELAXED, "thigh.L": [90, 0, 0], "thigh.R": [90, 0, 0], "shin.L": [-90, 0, 0],
             "shin.R": [-90, 0, 0], "forearm.L": [35, 0, 0], "forearm.R": [35, 0, 0]},
            "Seated on a chair-height surface."),
    "fight_stance": ({"spine": [8, -15, 0], "head": [0, 15, 0],
                      "upper_arm.L": [55, 0, -45], "upper_arm.R": [35, 0, -60],
                      "forearm.L": [110, 0, 0], "forearm.R": [120, 0, 0],
                      "thigh.L": [20, 0, 6], "shin.L": [-25, 0, 0],
                      "thigh.R": [-12, 0, 6], "shin.R": [-15, 0, 0]}, "Boxing guard."),
    "run_pose": ({"spine": [12, 0, 0], "thigh.L": [55, 0, 0], "shin.L": [-80, 0, 0],
                  "thigh.R": [-30, 0, 0], "shin.R": [-50, 0, 0],
                  "upper_arm.L": [-40, 0, -75], "upper_arm.R": [45, 0, -75],
                  "forearm.L": [80, 0, 0], "forearm.R": [80, 0, 0]}, "Mid-stride sprint."),
}
POSE_HIPS_DROP = {"crouch": 0.30, "sit": 0.24}   # fraction of hip height


def _resolve(spec, rest_deg):
    """Library spec (left-side convention, arm Z relative to T-pose) -> basic eulers."""
    out = {}
    for bone, (x, y, z) in spec.items():
        if bone.startswith("upper_arm"):
            z = z + rest_deg
        if bone.endswith(".R"):
            y, z = -y, -z
        out[bone] = (x, y, z)
    return out


# ----------------------------------------------------------------------------- keying
def _hips_local(rig, offset):
    """(side, up, forward) world-space offset -> hips bone local location.
    char3d: side = +X, up = +Z, forward = -Y."""
    side, up, fwd = offset
    world = Vector((side, -fwd, up))
    rest = rig.data.bones["hips"].matrix_local.to_3x3()
    return rest.inverted() @ (rig.matrix_world.to_3x3().inverted() @ world)


def _key_basic(rig, frame, rots, hips_loc=(0, 0, 0)):
    """Key every basic bone at `frame` (unlisted bones go to rest)."""
    for name in BASIC_BONES:
        pb = rig.pose.bones[name]
        pb.rotation_mode = "XYZ"
        x, y, z = rots.get(name, (0, 0, 0))
        pb.rotation_euler = (math.radians(x), math.radians(y), math.radians(z))
        pb.keyframe_insert("rotation_euler", frame=frame, group=name)
    hp = rig.pose.bones["hips"]
    hp.location = _hips_local(rig, hips_loc)
    hp.keyframe_insert("location", frame=frame, group="hips")


def _pose_basic(rig, rots, hips_loc=(0, 0, 0)):
    for name in BASIC_BONES:
        pb = rig.pose.bones[name]
        pb.rotation_mode = "XYZ"
        x, y, z = rots.get(name, (0, 0, 0))
        pb.rotation_euler = (math.radians(x), math.radians(y), math.radians(z))
        pb.location = (0, 0, 0)
    rig.pose.bones["hips"].location = _hips_local(rig, hips_loc)


def _dims(lm):
    leg = (lm["hip.L"] - lm["knee.L"]).length + (lm["knee.L"] - lm["ankle.L"]).length
    return {"leg": leg, "hip_h": lm["hips"].z - min(lm["heel.L"].z, lm["toe_tip.L"].z),
            "H": lm["head_top"].z - lm["heel.L"].z}


# ----------------------------------------------------------------------------- clips
# body travel per step relative to the leg sweep (tuned so planted feet barely slide)
STRIDE_SCALE = {"walk": 1.25, "run": 1.3}


def _walk_like(i, T, d, rest, amp, run=False):
    p = 2 * math.pi * i / T
    s = math.sin(p)
    A = (38 if run else 24) * amp
    knee_amp = (85 if run else 48) * amp
    # knee flexes in swing only: straight from heel strike (thigh fully forward, p = pi/2)
    # until just before toe-off; peak flexion early in swing (~73 % of the gait cycle)
    lift = lambda ph: max(0.0, math.cos(ph + 0.15)) ** 1.6  # noqa: E731
    spec = {
        "thigh.L": [A * s, 0, 0], "thigh.R": [-A * s, 0, 0],
        "shin.L": [-(6 + knee_amp * lift(p)), 0, 0],
        "shin.R": [-(6 + knee_amp * lift(p + math.pi)), 0, 0],
        "foot.L": [10 * s * amp, 0, 0], "foot.R": [-10 * s * amp, 0, 0],
        "upper_arm.L": [-(30 if run else 18) * s * amp, 0, -72 if run else -78],
        "upper_arm.R": [(30 if run else 18) * s * amp, 0, -72 if run else -78],
        "forearm.L": [(75 if run else 15) + 10 * max(0, -s), 0, 0],
        "forearm.R": [(75 if run else 15) + 10 * max(0, s), 0, 0],
        "spine": [(12 if run else 3), 4 * s * amp, 0],
        "hips": [0, -6 * s * amp, 0],
        "head": [-(6 if run else 2), -3 * s * amp, 0],
    }
    bob = (0.035 if run else 0.018) * d["hip_h"] * amp
    stride = 2 * d["leg"] * math.sin(math.radians(A)) * STRIDE_SCALE["run" if run else "walk"]
    forward = 2 * stride * i / T     # one cycle = two steps
    up = bob * math.cos(2 * p) - (0.04 if run else 0.01) * d["hip_h"]
    return _resolve(spec, rest), (0.0, up, forward)


def _idle(i, T, d, rest, amp):
    p = 2 * math.pi * i / T
    spec = {**RELAXED,
            "spine": [2 * math.sin(p) * amp, 0, 0], "chest": [1.5 * math.sin(p) * amp, 0, 0],
            "head": [1.5 * math.sin(p + 1), 4 * math.sin(p / 2) * amp, 0],
            "upper_arm.L": [2 * math.sin(p) * amp, 0, -78], "upper_arm.R": [2 * math.sin(p) * amp, 0, -78],
            "thigh.L": [0, 0, 2], "thigh.R": [0, 0, 2]}
    return _resolve(spec, rest), (0.0, 0.004 * d["hip_h"] * math.sin(p), 0.0)


def _wave(i, T, d, rest, amp):
    p = 2 * math.pi * i / T * 2   # two waves per cycle
    spec = {**POSES["wave"][0], "forearm.R": [0, 0, 70 + 22 * math.sin(p) * amp],
            "head": [0, 0, 6 + 2 * math.sin(p)]}
    return _resolve(spec, rest), (0.0, 0.0, 0.0)


def _cheer(i, T, d, rest, amp):
    p = 2 * math.pi * i / T * 2
    b = max(0.0, math.sin(p))
    spec = {**POSES["cheer"][0], "upper_arm.L": [0, 0, 60 + 15 * b * amp],
            "upper_arm.R": [0, 0, 60 + 15 * b * amp]}
    return _resolve(spec, rest), (0.0, 0.05 * d["hip_h"] * b * amp, 0.0)


def _head_motion(axis, deg):
    def clip(i, T, d, rest, amp):
        p = 2 * math.pi * i / T * 2
        rot = [0, 0, 0]
        rot[axis] = deg * math.sin(p) * amp
        return _resolve({**RELAXED, "head": rot}, rest), (0.0, 0.0, 0.0)
    return clip


JUMP_KEYS = [  # (t 0..1, pose spec, hips up as fraction of hip height)
    (0.00, RELAXED, 0.0),
    (0.22, {**RELAXED, "spine": [25, 0, 0], "thigh.L": [55, 0, 0], "thigh.R": [55, 0, 0],
            "shin.L": [-80, 0, 0], "shin.R": [-80, 0, 0], "foot.L": [25, 0, 0], "foot.R": [25, 0, 0],
            "upper_arm.L": [-45, 0, -75], "upper_arm.R": [-45, 0, -75]}, -0.18),
    (0.35, {"upper_arm.L": [0, 0, 70], "upper_arm.R": [0, 0, 70], "foot.L": [-30, 0, 0],
            "foot.R": [-30, 0, 0], "head": [-8, 0, 0]}, 0.10),
    (0.55, {"upper_arm.L": [0, 0, 60], "upper_arm.R": [0, 0, 60], "thigh.L": [35, 0, 0],
            "thigh.R": [35, 0, 0], "shin.L": [-55, 0, 0], "shin.R": [-55, 0, 0]}, 0.32),
    (0.75, {**RELAXED, "spine": [20, 0, 0], "thigh.L": [50, 0, 0], "thigh.R": [50, 0, 0],
            "shin.L": [-75, 0, 0], "shin.R": [-75, 0, 0], "foot.L": [25, 0, 0],
            "foot.R": [25, 0, 0], "upper_arm.L": [30, 0, -60], "upper_arm.R": [30, 0, -60]}, -0.15),
    (1.00, RELAXED, 0.0),
]


def _jump(i, T, d, rest, amp):
    t = i / T
    for (t0, s0, h0), (t1, s1, h1) in zip(JUMP_KEYS, JUMP_KEYS[1:]):
        if t0 <= t <= t1:
            u = (t - t0) / (t1 - t0)
            u = u * u * (3 - 2 * u)   # smoothstep
            bones = set(s0) | set(s1)
            spec = {b: [a + (bb - a) * u for a, bb in zip(s0.get(b, [0, 0, 0]), s1.get(b, [0, 0, 0]))]
                    for b in bones}
            h = (h0 + (h1 - h0) * u) * d["hip_h"] * amp
            return _resolve(spec, rest), (0.0, h, 0.0)
    return _resolve(RELAXED, rest), (0.0, 0.0, 0.0)


CLIPS = {  # name: (fn, frames per cycle at 24 fps, loops?, description)
    "idle": (_idle, 96, True, "Breathing, subtle sway, arms relaxed."),
    "walk": (_walk_like, 32, True, "Walk cycle moving forward (-Y). Two steps per cycle."),
    "run": (lambda i, T, d, r, a: _walk_like(i, T, d, r, a, run=True), 18, True,
            "Run cycle moving forward, torso leaning."),
    "wave": (_wave, 36, True, "Right-hand wave."),
    "cheer": (_cheer, 30, True, "Arms up, bouncing celebration."),
    "jump": (_jump, 40, False, "Crouch, jump up, land (one shot)."),
    "nod": (_head_motion(0, 14), 30, True, "Head nodding yes."),
    "head_shake": (_head_motion(1, 25), 30, True, "Head shaking no."),
}


def _motion_clip(name):
    def sample(i, period, dimensions, rest, amplitude):
        spec, offsets = score(name, i/period, amplitude)
        return _resolve(spec, rest), tuple(v*dimensions["H"] for v in offsets)
    return sample


for _name, _meta in MOTIONS.items():
    CLIPS[_name] = (_motion_clip(_name), _meta["frames_per_cycle"], _meta["loops"], _meta["description"])
    if _name not in POSES:
        _time = 1. if _name in ("lie_down", "sit_floor", "fall_down") else .45
        POSES[_name] = (score(_name, _time)[0], _meta["description"])


# ----------------------------------------------------------------------------- retarget
def _depth(rig, bone):
    return len(rig.data.bones[bone].parent_recursive)


def _facing(src, smap):
    """Rotation taking the source rig's (left, up, back) frame to char3d's (+X, +Z, +Y)."""
    mw = src.matrix_world

    def head(n):
        return mw @ src.data.bones[smap[n]].head_local
    left = (head("thigh.L") - head("thigh.R")).normalized()
    upper = smap.get("head") or smap.get("neck") or smap.get("chest")
    up = (mw @ src.data.bones[upper].head_local) - head("hips")
    up = (up - left * up.dot(left)).normalized()
    back = up.cross(left)
    S = Matrix((left, up, back)).transposed()        # columns = source axes
    T = Matrix(((1, 0, 0), (0, 0, 1), (0, 1, 0))).transposed()
    return _snap_axes(T @ S.transposed()).to_quaternion()


def _snap_axes(m):
    """Mocap/rig files use canonical axes; snap the facing rotation to the nearest
    90-degree rotation so a slightly leaning rest pose doesn't tilt the whole motion."""
    snapped = Matrix.Identity(3)
    used = set()
    for col in range(3):
        v = [m[r][col] for r in range(3)]
        r = max((i for i in range(3) if i not in used), key=lambda i: abs(v[i]))
        used.add(r)
        for i in range(3):
            snapped[i][col] = 0.0
        snapped[r][col] = 1.0 if v[r] > 0 else -1.0
    if abs(snapped.determinant() - 1.0) > 1e-6:
        return m   # not a clean axis permutation: keep the measured rotation
    return snapped


def _set_world_rot(rig, pb, q, loc=None):
    m = pb.matrix.copy()
    mw = rig.matrix_world
    world = mw @ m
    new = Matrix.LocRotScale(loc if loc is not None else world.translation, q,
                             world.to_scale())
    pb.matrix = mw.inverted() @ new


def _key_rot(pb, frame, prev):
    mode = pb.rotation_mode
    if mode == "QUATERNION":
        q = pb.rotation_quaternion.copy()
        if prev.get(pb.name) is not None and prev[pb.name].dot(q) < 0:
            q.negate()
            pb.rotation_quaternion = q
        prev[pb.name] = q
        pb.keyframe_insert("rotation_quaternion", frame=frame, group=pb.name)
    elif mode == "AXIS_ANGLE":
        pb.keyframe_insert("rotation_axis_angle", frame=frame, group=pb.name)
    else:
        e = pb.matrix_basis.to_euler(mode, prev.get(pb.name) or pb.rotation_euler)
        pb.rotation_euler = e
        prev[pb.name] = e.copy()
        pb.keyframe_insert("rotation_euler", frame=frame, group=pb.name)


def bake_retarget(src, tgt, src_map, tgt_map, frame_start, frame_end, dest_start=None,
                  in_place=False, align_rest=True, root_scale=None, key=True,
                  root_mode="first", carry=None, align_bones=(), facing=None):
    """root_mode "first": root motion relative to the source's first frame (mocap);
    "rest": relative to the source rest pose (proxy rigs that already include carry).
    carry: world offset added to the root (continue from where the previous clip ended)."""
    """Copy animation src -> tgt over [frame_start, frame_end], keyed from dest_start."""
    sc = bpy.context.scene
    dest_start = frame_start if dest_start is None else dest_start
    names = [b for b in BASIC_BONES if b in src_map and b in tgt_map]
    if "hips" not in names:
        raise ValueError("both rigs need a recognisable hips bone")
    names.sort(key=lambda b: _depth(tgt, tgt_map[b]))
    # facing: explicit rotation from the source's frame to the target's world frame
    # (a canonical proxy authored facing -Y for a rotated rig); None measures it.
    F = _facing(src, src_map) if facing is None else facing
    Fm = F.to_matrix()
    swm, twm = src.matrix_world, tgt.matrix_world

    def rest_q(rig, mw, bone):
        return (mw @ rig.data.bones[bone].matrix_local).to_quaternion()

    s_rest = {b: rest_q(src, swm, src_map[b]) for b in names}
    t_rest = {b: rest_q(tgt, twm, tgt_map[b]) for b in names}
    align = {}
    for b in names:
        if (not align_rest and b not in align_bones) or b in ("hips", "spine", "chest"):
            align[b] = Quaternion()
            continue
        sb, tb = src.data.bones[src_map[b]], tgt.data.bones[tgt_map[b]]
        sd = Fm @ (swm.to_3x3() @ (sb.tail_local - sb.head_local)).normalized()
        td = (twm.to_3x3() @ (tb.tail_local - tb.head_local)).normalized()
        align[b] = td.rotation_difference(sd)

    if root_scale is None:
        def leg(rig, mw, m):
            return sum((mw.to_3x3() @ (rig.data.bones[m[b]].tail_local - rig.data.bones[m[b]].head_local)).length
                       for b in ("thigh.L", "shin.L") if b in m)
        sl, tl = leg(src, swm, src_map), leg(tgt, twm, tgt_map)
        root_scale = tl / sl if sl > 1e-6 else 1.0
    t_hips_rest = (twm @ tgt.data.bones[tgt_map["hips"]].matrix_local).translation

    for b in names:
        tgt.pose.bones[tgt_map[b]].location = (0, 0, 0)
    levels = {}
    for b in names:
        levels.setdefault(_depth(tgt, tgt_map[b]), []).append(b)
    prev, root_ref = {}, None
    for f in range(int(frame_start), int(frame_end) + 1):
        sc.frame_set(f)
        cur = {b: swm @ src.pose.bones[src_map[b]].matrix for b in names}
        if root_ref is None:
            root_ref = ((swm @ src.data.bones[src_map["hips"]].matrix_local).translation
                        if root_mode == "rest" else cur["hips"].translation.copy())
        for lvl in sorted(levels):
            for b in levels[lvl]:
                delta = F @ (cur[b].to_quaternion() @ s_rest[b].inverted()) @ F.inverted()
                q = delta @ align[b] @ t_rest[b]
                loc = None
                if b == "hips":
                    off = Fm @ (cur["hips"].translation - root_ref) * root_scale
                    if in_place:
                        off.x = off.y = 0.0
                    if carry is not None:
                        off = off + carry
                    loc = t_hips_rest + off
                _set_world_rot(tgt, tgt.pose.bones[tgt_map[b]], q, loc)
            bpy.context.view_layer.update()
        frame = dest_start + (f - frame_start)
        if not key:
            continue
        for b in names:
            pb = tgt.pose.bones[tgt_map[b]]
            _key_rot(pb, frame, prev)
            if b == "hips":
                pb.keyframe_insert("location", frame=frame, group=pb.name)
    return {"frames": [dest_start, dest_start + (frame_end - frame_start)], "bones": len(names),
            "root_scale": round(root_scale, 4)}


# ----------------------------------------------------------------------------- driving any rig
def _target(armature):
    rig = obj_or_raise(armature)
    if rig.type != "ARMATURE":
        raise TypeError(f"{armature} is not an ARMATURE")
    return rig


ARM_ALIGN = ("forearm.L", "forearm.R", "hand.L", "hand.R")


def _straighten_arms(lm):
    """Some rigs (MPFB/MakeHuman) rest with the elbows bent ~45 deg forward. The clip and
    pose library assume a straight A-pose arm, so the proxy gets straight arms and the
    retarget aligns forearm/hand rest directions (ARM_ALIGN) instead of copying the bend."""
    lm = dict(lm)
    for s in "LR":
        sh, el, wr = lm[f"shoulder.{s}"], lm[f"elbow.{s}"], lm[f"wrist.{s}"]
        upper, fore = (el - sh).normalized(), wr - el
        if fore.length < 1e-6 or fore.normalized().angle(upper) < math.radians(5):
            continue
        q = fore.normalized().rotation_difference(upper)
        lm[f"wrist.{s}"] = el + upper * fore.length
        lm[f"hand_tip.{s}"] = lm[f"wrist.{s}"] + q @ (lm[f"hand_tip.{s}"] - wr)
    return lm


def _landmark_yaw(lm):
    """Rest heading of a rig from its hip landmarks (0 = facing -Y, the char3d front)."""
    left = lm["hip.L"] - lm["hip.R"]
    yaw = math.atan2(left.y, left.x) if left.xy.length > 1e-6 else 0.0
    return yaw if abs(yaw) > 1e-6 else 0.0


def rig_yaw(rig):
    """The yaw _drive(canonical=True) undoes when it builds a proxy for `rig`."""
    if rig.get("c3d_rig_type") == "basic" or all(b in rig.pose.bones for b in BASIC_BONES):
        return 0.0          # basic rigs are driven directly, never through a proxy
    bpy.context.view_layer.update()
    return _landmark_yaw(_rig_landmarks(rig, semantic_map(rig)))


def _proxy_for(rig, canonical=False):
    """Basic proxy matching the rig's proportions. canonical=True builds it facing -Y
    (the rig's yaw undone around its hips) so clip/pose authoring, whose local bone
    axes assume the char3d front, is right for rotated rigs; returns that yaw too."""
    smap = semantic_map(rig)
    bpy.context.view_layer.update()   # world landmarks need a current matrix_world
    lm = _straighten_arms(_rig_landmarks(rig, smap))
    yaw = 0.0
    if canonical:
        yaw = _landmark_yaw(lm)
        if yaw:
            pivot = Vector((lm["hips"].x, lm["hips"].y, 0.0))
            undo = Matrix.Rotation(-yaw, 3, "Z")
            lm = {k: pivot + undo @ (v - pivot) for k, v in lm.items()}
    proxy = rigmod._build_basic(lm, "__c3d_proxy")
    return proxy, smap, lm, yaw


def _drop(obj):
    act = obj.animation_data.action if obj.animation_data else None
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.armatures.remove(data)
    if act and act.users == 0:
        bpy.data.actions.remove(act)


def _carry(rig, smap, frame):
    """Horizontal root offset the rig has at frame-1 (where the previous clip ended)."""
    sc = bpy.context.scene
    hips = smap.get("hips")
    if (hips is None or frame <= sc.frame_start or not rig.animation_data
            or not rig.animation_data.action):
        return Vector((0.0, 0.0, 0.0))
    sc.frame_set(frame - 1)
    mw = rig.matrix_world
    now = (mw @ rig.pose.bones[hips].matrix).translation
    rest = (mw @ rig.data.bones[hips].matrix_local).translation
    sc.frame_set(frame)
    return Vector((now.x - rest.x, now.y - rest.y, 0.0))


def _drive(rig, author, frame_start, frame_end, dest_start, in_place=False, key=True,
           canonical=False):
    """Run author(basic_rig, landmarks, direct) on the rig itself (basic rigs) or on a
    proportion-matched basic proxy that is then retargeted onto the rig."""
    if rig.get("c3d_rig_type") == "basic" or all(b in rig.pose.bones for b in BASIC_BONES):
        ident = {b: b for b in BASIC_BONES}
        lm = _rig_landmarks(rig, ident)
        carry = _carry(rig, ident, dest_start) if key else Vector((0, 0, 0))
        author(rig, lm, True, carry)
        return {"via": "direct", "continues_from": [round(carry.x, 3), round(carry.y, 3)]}
    smap = semantic_map(rig)
    carry = _carry(rig, smap, dest_start) if key else Vector((0, 0, 0))
    proxy, smap, lm, yaw = _proxy_for(rig, canonical)
    facing, world_carry = None, carry.copy()
    if yaw:
        # Author in the canonical frame, then turn the motion back to the rig's yaw.
        carry = Matrix.Rotation(-yaw, 3, "Z") @ carry
        facing = Quaternion(Vector((0.0, 0.0, 1.0)), yaw)
    try:
        author(proxy, lm, False, carry)
        info = bake_retarget(proxy, rig, {b: b for b in BASIC_BONES}, smap, frame_start,
                             frame_end, dest_start, in_place=in_place, align_rest=False,
                             root_scale=1.0, key=key, root_mode="rest", align_bones=ARM_ALIGN,
                             facing=facing)
        info["continues_from"] = [round(world_carry.x, 3), round(world_carry.y, 3)]
    finally:
        _drop(proxy)
    info["via"] = "proxy-retarget"
    return info


def _extend_range(end):
    sc = bpy.context.scene
    sc.frame_end = max(sc.frame_end, int(end))


# ----------------------------------------------------------------------------- commands
@command("list_animations")
def list_animations():
    return {
        "poses": {k: v[1] for k, v in POSES.items()},
        "clips": {k: {"frames_per_cycle": v[1], "loops": v[2], "description": v[3],
                      "category": "locomotion" if k in ("walk", "run", "jump") else "gesture",
                      "required_props": [], "required_seat": False, **MOTIONS.get(k, {})}
                  for k, v in CLIPS.items()},
    }


@command("apply_pose")
def apply_pose(armature, pose, frame=None, keyframe=False):
    if pose not in POSES:
        raise ValueError(f"unknown pose '{pose}'. Available: {sorted(POSES)}")
    rig = _target(armature)
    sc = bpy.context.scene
    f = int(frame) if frame is not None else sc.frame_current
    sc.frame_set(f)
    lower = None
    if pose in MOTIONS:
        from .motion import validate, seated_samples
        validate(rig, pose, f, "full")
        lower = seated_samples(rig, pose, f, f)

    def author(basic, lm, direct, carry):
        rots = _resolve(POSES[pose][0], _arm_rest_deg(lm)) if pose != "rest" else {}
        drop = POSE_HIPS_DROP.get(pose, 0.0) * _dims(lm)["hip_h"]
        loc = (carry.x, -drop, -carry.y)
        if pose in MOTIONS:
            time = 1. if pose in ("lie_down", "sit_floor", "fall_down") else .45
            spec, off = score(pose, time)
            rots = _resolve(spec, _arm_rest_deg(lm))
            loc = (carry.x+off[0]*_dims(lm)["H"], off[1]*_dims(lm)["H"], -carry.y+off[2]*_dims(lm)["H"])
        if keyframe and direct:
            _key_basic(basic, f, rots, loc)
        else:
            _pose_basic(basic, rots, loc)
        bpy.context.view_layer.update()

    info = _drive(rig, author, f, f, f, key=bool(keyframe), canonical=True)
    if pose in MOTIONS:
        from .motion import finish
        info.update(finish(rig, pose, f, f, 1, 1., lower=lower, lock=False, keyed=keyframe,
                           pose_time=1. if pose in ("lie_down", "sit_floor", "fall_down") else .45))
    bpy.context.view_layer.update()
    return {"armature": rig.name, "pose": pose, "frame": f, "keyed": bool(keyframe), **info}


FOOT_LOCK_CLIPS = ("walk", "run", "jump")
# clips whose contacts are known from the choreography: (t0, t1) fractions of the clip
CLIP_CONTACTS = {"jump": ((0.0, 0.36), (0.70, 1.0))}


# ----------------------------------------------------------------------------- crossfades
BLEND_DEG_PER_FRAME = 9.0     # auto blend length: ~9 deg of the biggest joint change per frame
BLEND_RANGE = (4, 18)         # frames at 24 fps


def _auto_blend(rig, prev, start, end):
    """Blend length from how far the new clip's first pose is from the previous pose."""
    sc = bpy.context.scene
    k = sc.render.fps / 24.0
    sc.frame_set(start)
    worst = 0.0
    for name in _keyed_at(rig, start):
        pb = rig.pose.bones.get(name)
        if pb is None or name not in prev:
            continue
        qa = prev[name].to_quaternion()
        qb = pb.matrix_basis.to_quaternion()
        worst = max(worst, math.degrees(qa.rotation_difference(qb).angle) % 360)
    worst = min(worst, 360 - worst) if worst > 180 else worst
    lo, hi = BLEND_RANGE
    n = int(round(min(max(worst / BLEND_DEG_PER_FRAME, lo), hi) * k))
    return max(1, min(n, end - start)), round(worst, 1)


def _has_keys_before(rig, frame):
    from .talk import _fcurves
    act = rig.animation_data.action if rig.animation_data else None
    for fc in _fcurves(act):
        if fc.data_path.startswith("pose.bones[") and any(k.co.x < frame - 0.5 for k in fc.keyframe_points):
            return True
    return False


def _sample_pose(rig, frame):
    """Local pose of every bone at `frame` (the end of the previous clip), or None when the
    rig has no animation before it (nothing to blend from)."""
    if not _has_keys_before(rig, frame):
        return None
    sc = bpy.context.scene
    cur = sc.frame_current
    sc.frame_set(frame - 1)
    pose = {pb.name: pb.matrix_basis.copy() for pb in rig.pose.bones}
    sc.frame_set(cur)
    return pose


def _keyed_at(rig, frame):
    """{bone: {"location", "rotation", "scale"}} channels keyed exactly at `frame`."""
    from .talk import _fcurves
    act = rig.animation_data.action if rig.animation_data else None
    out = {}
    for fc in _fcurves(act):
        dp = fc.data_path
        if not dp.startswith('pose.bones["'):
            continue
        if not any(abs(k.co.x - frame) < 0.5 for k in fc.keyframe_points):
            continue
        name, prop = dp[len('pose.bones["'):].split('"]', 1)
        prop = prop.lstrip(".")
        kind = "rotation" if prop.startswith("rotation") else prop
        out.setdefault(name, set()).add(kind)
    return out


def _crossfade(rig, prev, start, end, blend=None):
    """Blend the first frames of the clip just keyed at [start, end] from the previous
    clip's last pose (prev) - rotations slerped, locations/scales lerped, eased.
    blend None = automatic length from the size of the pose change."""
    if prev is None or (blend is not None and blend <= 0):
        return None
    sc = bpy.context.scene
    chans = _keyed_at(rig, start)
    if not chans:
        return None
    change = None
    if blend is None:
        blend, change = _auto_blend(rig, prev, start, end)
    n = min(int(blend), end - start)
    keyprev = {}
    for i in range(n):
        f = start + i
        u = (i + 1) / (n + 1)
        w = u * u * (3 - 2 * u)            # weight of the new clip
        sc.frame_set(f)
        for name, kinds in chans.items():
            pb = rig.pose.bones.get(name)
            if pb is None or name not in prev:
                continue
            a, b = prev[name], pb.matrix_basis
            la, ra, sa = a.decompose()
            lb, rb, sb = b.decompose()
            if ra.dot(rb) < 0:
                rb.negate()
            m = Matrix.LocRotScale(la.lerp(lb, w), ra.slerp(rb, w), sa.lerp(sb, w))
            pb.matrix_basis = m
            if "rotation" in kinds:
                _key_rot(pb, f, keyprev)
            if "location" in kinds:
                pb.keyframe_insert("location", frame=f, group=name)
            if "scale" in kinds:
                pb.keyframe_insert("scale", frame=f, group=name)
    bpy.context.view_layer.update()
    out = {"frames": [start, start + n - 1], "blend_frames": n, "bones": len(chans)}
    if change is not None:
        out["largest_joint_change_deg"] = change
    return out


def _lock(rig, f0, f1, contacts=None):
    from .footlock import foot_lock
    r = foot_lock(rig, f0, f1, contacts=contacts)
    return {"contacts": {s: v["contacts"] for s, v in r["feet"].items()},
            "hips_lowered_max_m": r["hips_lowered_max_m"],
            **{k: r[k] for k in ("ground_heights", "max_penetration_m", "min_swing_clearance_m") if k in r}}


def _motion_evaluation(fn):
    @wraps(fn)
    def wrapped(armature, clip, *args, **kwargs):
        if clip in MOTIONS:
            from .script_scene import _bones_only
            with _bones_only():
                return fn(armature, clip, *args, **kwargs)
        return fn(armature, clip, *args, **kwargs)
    return wrapped


@command("animate")
@_motion_evaluation
def animate(armature, clip, start_frame=1, cycles=2, speed=1.0, amplitude=1.0,
            in_place=False, foot_lock=None, blend_frames=None, bpm=None, phase="full"):
    """Key a procedural clip on any humanoid rig starting at start_frame.
    foot_lock: None = auto (walk/run/jump, not in_place), True/False to force.
    blend_frames: crossfade from the pose the rig has at start_frame-1 when there is earlier
    animation (None = automatic 4-18 frames from the size of the change; 0 = hard cut)."""
    if clip not in CLIPS:
        raise ValueError(f"unknown clip '{clip}'. Available: {sorted(CLIPS)}")
    fn, period, loops, _desc = CLIPS[clip]
    rig = _target(armature)
    sc = bpy.context.scene
    fps_scale = sc.render.fps / sc.render.fps_base / 24.0
    T = max(4, int(round(period * fps_scale / max(speed, 0.05))))
    if not math.isfinite(amplitude) or not 0 <= amplitude <= 2:
        raise ValueError("amplitude must be finite in 0..2")
    if clip in MOTIONS:
        from .motion import validate, seated_samples, finish
        T = cycle_frames(clip, fps_scale*24, speed, bpm)
        validate(rig, clip, int(start_frame), phase)
    elif bpm is not None or phase != "full":
        raise ValueError("bpm needs a dance clip; phase needs kneel")
    n = T * (max(1, int(cycles)) if loops else 1)
    if clip in MOTIONS:
        n = total_frames(clip, cycles, fps_scale*24, speed, bpm)
    sample_period = n/max(1, int(cycles)) if bpm is not None else T
    if n > 24000:
        raise ValueError("animation is limited to 24000 frames; split and chain clips")
    start = int(start_frame)
    end = start + n
    lower = seated_samples(rig, clip, start, end) if clip in MOTIONS else None
    heading = 0.
    relative_origin = clip in MOTIONS and _has_keys_before(rig, start) and (clip == "get_up" or (clip == "kneel" and phase in ("hold", "up")))
    if clip in MOTIONS:
        from .gaze import head_frame
        sc.frame_set(start-1 if _has_keys_before(rig, start) else start)
        smap = semantic_map(rig)
        left = head_frame(rig, "hips")[1] @ Vector((1, 0, 0))
        rest_left = rig.matrix_world.to_3x3() @ (rig.data.bones[smap["thigh.L"]].head_local-
                                                rig.data.bones[smap["thigh.R"]].head_local)
        heading = math.atan2(left.y, left.x)-math.atan2(rest_left.y, rest_left.x)

    def author(basic, lm, direct, carry):
        d, rest = _dims(lm), _arm_rest_deg(lm)
        previous = {}
        planted = None
        for i in range(n + 1):
            rots, (x, up, fwd) = fn(i if loops else min(i, T), sample_period, d, rest, amplitude)
            if clip == "kneel" and phase != "full":
                spec, offsets = score(clip, min(i/T, 1), amplitude, phase)
                rots = _resolve(spec, rest)
                x, up, fwd = (v*d["H"] for v in offsets)
            if relative_origin:
                _, origin = score(clip, 0, amplitude, phase)
                x -= origin[0]*d["H"]
                fwd -= origin[2]*d["H"]
            if in_place:
                fwd = 0.0
            if clip in MOTIONS and heading:
                off = Matrix.Rotation(heading, 3, "Z") @ Vector((x, -fwd, 0))
                x, fwd = off.x, -off.y
            if direct and clip in MOTIONS:
                left = (lm["hip.L"]-lm["hip.R"])
                left.z = 0
                left.normalize()
                front = Vector((left.y, -left.x, 0))
                world = left*x+front*fwd
                x, fwd = world.x, -world.y
            _key_basic(basic, start + i, rots, (x + carry.x, up, fwd - carry.y))
            if clip in MOTIONS and abs(heading) > 1e-6:
                bpy.context.view_layer.update()
                hp = basic.pose.bones["hips"]
                q = (basic.matrix_world @ hp.matrix).to_quaternion()
                _set_world_rot(basic, hp, Quaternion((0, 0, 1), heading) @ q)
                _key_rot(hp, start+i, previous)
            if clip in ("kneel", "pick_up"):
                # Let the pelvis travel over the folded legs while the ankle
                # positions stay planted. Measure on the proportion-matched
                # skeleton, rather than assuming equal thigh/calf lengths.
                bpy.context.view_layer.update()
                feet = [(basic.matrix_world @ basic.pose.bones[f"foot.{s}"].matrix).translation.copy()
                        for s in "LR"]
                if planted is None:
                    planted = feet
                correction = sum((a-b for a, b in zip(planted, feet)), Vector())/2
                correction.z = 0
                hp = basic.pose.bones["hips"]
                world = basic.matrix_world @ hp.matrix
                _set_world_rot(basic, hp, world.to_quaternion(), world.translation+correction)
                hp.keyframe_insert("location", frame=start+i, group="hips")

    blend = None if blend_frames is None else int(blend_frames)
    prev = _sample_pose(rig, start) if blend != 0 else None
    info = _drive(rig, author, start, end, start, in_place=in_place, canonical=True)
    _extend_range(end)
    # Contact IK can substantially change the arms beyond the proxy pose.
    # Measure/blend that completed performance; floor clips must instead blend
    # before their final skin-to-ground correction.
    contact_blend = clip in MOTIONS and clip not in FLOOR
    fade = None if contact_blend else _crossfade(rig, prev, start, end, blend)
    if fade:
        info["crossfade"] = fade
    lock = foot_lock if foot_lock is not None else (clip in FOOT_LOCK_CLIPS and not in_place)
    if clip in MOTIONS:
        info.update(finish(rig, clip, start, end, sample_period, amplitude, lower,
                           lock=foot_lock is not False))
        if contact_blend:
            fade = _crossfade(rig, prev, start, end, blend)
            if fade:
                info["crossfade"] = fade
                if lower is None and foot_lock is not False:
                    if MOTIONS[clip]["category"] == "dance":
                        from .motion import _dance_feet, _landmarks
                        height, _ = _landmarks(rig, semantic_map(rig))
                        info["foot_lock"] = _dance_feet(rig, start, end, sample_period, height)
                    else:
                        info["foot_lock"] = _lock(rig, start, end, info["foot_lock"]["contacts"])
        if bpm is not None:
            info.update(bpm=bpm, effective_bpm=round(4*60*fps_scale*24/sample_period, 5),
                        cycle_frames_exact=sample_period)
        info["phase"] = phase
        return {"armature": rig.name, "clip": clip, "frames": [start, end], "cycle_frames": T,
                "next_start_frame": end+1, **info}
    if lock:
        contacts = None
        if clip in CLIP_CONTACTS:
            iv = [[start + int(round(a * n)), start + int(round(b * n))]
                  for a, b in CLIP_CONTACTS[clip]]
            contacts = {"L": iv, "R": iv}
        info["foot_lock"] = _lock(rig, start, end, contacts)
    elif fade and foot_lock is not False and not in_place:
        # coming out of another clip into a standing one: the feet re-gather during the
        # blend - the planted one stays put, the moving one finishes its step - and then
        # stay where they landed for the rest of the clip (no pop when the blend ends)
        try:
            info["foot_lock"] = _lock(rig, start, end)
        except ValueError:
            pass   # rig without recognisable legs
    return {"armature": rig.name, "clip": clip, "frames": [start, end], "cycle_frames": T,
            "next_start_frame": end + 1, **info}


@command("retarget_animation")
def retarget_animation(source, target, bone_map=None, frame_start=None, frame_end=None,
                       dest_start=None, in_place=False, blend_frames=None):
    """Copy animation from one humanoid armature to another (world-space, rest-aligned)."""
    src, tgt = _target(source), _target(target)
    smap = heuristic_map(src) if src.get("c3d_rig_type") is None else semantic_map(src)
    if bone_map:
        smap.update(bone_map)
    tmap = semantic_map(tgt)
    act = src.animation_data.action if src.animation_data else None
    if act is None:
        raise ValueError(f"{source} has no animation")
    fs = int(frame_start if frame_start is not None else act.frame_range[0])
    fe = int(frame_end if frame_end is not None else act.frame_range[1])
    ds = fs if dest_start is None else int(dest_start)
    carry = _carry(tgt, tmap, ds)
    blend = None if blend_frames is None else int(blend_frames)
    prev = _sample_pose(tgt, ds) if blend != 0 else None
    info = bake_retarget(src, tgt, smap, tmap, fs, fe, ds, in_place=in_place, carry=carry)
    info["continues_from"] = [round(carry.x, 3), round(carry.y, 3)]
    _extend_range(info["frames"][1])
    fade = _crossfade(tgt, prev, info["frames"][0], info["frames"][1], blend)
    if fade:
        info["crossfade"] = fade
    info["mapped"] = {b: [smap[b], tmap[b]] for b in BASIC_BONES if b in smap and b in tmap}
    return info


@command("import_mocap")
def import_mocap(path, armature, start_frame=1, in_place=False, bone_map=None,
                 frame_start=None, frame_end=None, keep_source=False, foot_lock=True,
                 blend_frames=None):
    """Import a BVH/FBX/GLB motion file and retarget it onto `armature`."""
    path = context.resolve(path, "imports")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    tgt = _target(armature)
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".bvh":
        bpy.ops.import_anim.bvh(filepath=path, update_scene_fps=False, update_scene_duration=False)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise ValueError("mocap must be .bvh, .fbx, .glb or .gltf")
    new = [o for o in bpy.data.objects if o not in before]
    src = next((o for o in new if o.type == "ARMATURE"), None)
    if src is None:
        raise ValueError("no armature found in the motion file")
    try:
        info = retarget_animation(src.name, tgt.name, bone_map=bone_map, frame_start=frame_start,
                                  frame_end=frame_end, dest_start=int(start_frame),
                                  in_place=in_place, blend_frames=blend_frames)
    finally:
        if not keep_source:
            acts = {o.animation_data.action for o in new
                    if o.animation_data and o.animation_data.action}
            for o in new:
                if o.name in bpy.data.objects:
                    bpy.data.objects.remove(o, do_unlink=True)
            for act in acts:
                if act.users == 0:
                    bpy.data.actions.remove(act)
    info["source_file"] = path
    if tgt.animation_data and tgt.animation_data.action:
        sources = json.loads(tgt.animation_data.action.get('c3d_import_sources', '[]'))
        tgt.animation_data.action['c3d_import_sources'] = json.dumps(sorted(set(sources + [path])))
    info["next_start_frame"] = info["frames"][1] + 1
    if foot_lock and not in_place:
        info["foot_lock"] = _lock(tgt, info["frames"][0], info["frames"][1])
    return info


@command("clear_animation")
def clear_animation(armature, reset_pose=True):
    rig = _target(armature)
    # Rigify's deform chains are driven by F-curves on this same AnimData.
    # Removing the container also removes those structural rig drivers.
    if rig.animation_data:
        rig.animation_data.action = None
        for track in list(rig.animation_data.nla_tracks):
            rig.animation_data.nla_tracks.remove(track)
    if "c3d_seat_events" in rig:
        del rig["c3d_seat_events"]
    if reset_pose:
        rig["c3d_seat_active"] = False
        for pb in rig.pose.bones:
            pb.location = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.rotation_euler = (0, 0, 0)
            pb.scale = (1, 1, 1)
    return {"armature": rig.name, "cleared": True}
