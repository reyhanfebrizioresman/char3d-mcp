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

import bpy
from mathutils import Matrix, Quaternion, Vector

from .. import context
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


def _rig_landmarks(rig, smap):
    """Landmarks for building a basic proxy that matches `rig`'s proportions."""
    if rig.get("c3d_landmarks"):
        return {k: Vector(v) for k, v in json.loads(rig["c3d_landmarks"]).items()}
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
def _walk_like(i, T, d, rest, amp, run=False):
    p = 2 * math.pi * i / T
    s, c = math.sin(p), math.cos(p)
    A = (38 if run else 24) * amp
    knee_amp = (85 if run else 48) * amp
    lift = lambda ph: max(0.0, math.cos(ph + 0.7)) ** 1.6  # noqa: E731
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
    stride = 2 * d["leg"] * math.sin(math.radians(A)) * (0.95 if run else 0.9)
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
                  root_mode="first", carry=None):
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
    F = _facing(src, src_map)
    Fm = F.to_matrix()
    swm, twm = src.matrix_world, tgt.matrix_world

    def rest_q(rig, mw, bone):
        return (mw @ rig.data.bones[bone].matrix_local).to_quaternion()

    s_rest = {b: rest_q(src, swm, src_map[b]) for b in names}
    t_rest = {b: rest_q(tgt, twm, tgt_map[b]) for b in names}
    align = {}
    for b in names:
        if not align_rest or b in ("hips", "spine", "chest"):
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


def _proxy_for(rig):
    smap = semantic_map(rig)
    lm = _rig_landmarks(rig, smap)
    proxy = rigmod._build_basic(lm, "__c3d_proxy")
    return proxy, smap, lm


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


def _drive(rig, author, frame_start, frame_end, dest_start, in_place=False, key=True):
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
    proxy, smap, lm = _proxy_for(rig)
    try:
        author(proxy, lm, False, carry)
        info = bake_retarget(proxy, rig, {b: b for b in BASIC_BONES}, smap, frame_start,
                             frame_end, dest_start, in_place=in_place, align_rest=False,
                             root_scale=1.0, key=key, root_mode="rest")
        info["continues_from"] = [round(carry.x, 3), round(carry.y, 3)]
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
        "clips": {k: {"frames_per_cycle": v[1], "loops": v[2], "description": v[3]}
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

    def author(basic, lm, direct, carry):
        rots = _resolve(POSES[pose][0], _arm_rest_deg(lm)) if pose != "rest" else {}
        drop = POSE_HIPS_DROP.get(pose, 0.0) * _dims(lm)["hip_h"]
        loc = (carry.x, -drop, -carry.y)
        if keyframe and direct:
            _key_basic(basic, f, rots, loc)
        else:
            _pose_basic(basic, rots, loc)
        bpy.context.view_layer.update()

    info = _drive(rig, author, f, f, f, key=bool(keyframe))
    bpy.context.view_layer.update()
    return {"armature": rig.name, "pose": pose, "frame": f, "keyed": bool(keyframe), **info}


@command("animate")
def animate(armature, clip, start_frame=1, cycles=2, speed=1.0, amplitude=1.0,
            in_place=False):
    """Key a procedural clip on any humanoid rig starting at start_frame."""
    if clip not in CLIPS:
        raise ValueError(f"unknown clip '{clip}'. Available: {sorted(CLIPS)}")
    fn, period, loops, _desc = CLIPS[clip]
    rig = _target(armature)
    fps_scale = bpy.context.scene.render.fps / 24.0
    T = max(4, int(round(period * fps_scale / max(speed, 0.05))))
    n = T * (max(1, int(cycles)) if loops else 1)
    start = int(start_frame)
    end = start + n

    def author(basic, lm, direct, carry):
        d, rest = _dims(lm), _arm_rest_deg(lm)
        for i in range(n + 1):
            rots, (x, up, fwd) = fn(i if loops else min(i, T), T, d, rest, amplitude)
            if in_place:
                fwd = 0.0
            _key_basic(basic, start + i, rots, (x + carry.x, up, fwd - carry.y))

    info = _drive(rig, author, start, end, start, in_place=in_place)
    _extend_range(end)
    return {"armature": rig.name, "clip": clip, "frames": [start, end], "cycle_frames": T,
            "next_start_frame": end + 1, **info}


@command("retarget_animation")
def retarget_animation(source, target, bone_map=None, frame_start=None, frame_end=None,
                       dest_start=None, in_place=False):
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
    info = bake_retarget(src, tgt, smap, tmap, fs, fe, ds, in_place=in_place, carry=carry)
    info["continues_from"] = [round(carry.x, 3), round(carry.y, 3)]
    _extend_range(info["frames"][1])
    info["mapped"] = {b: [smap[b], tmap[b]] for b in BASIC_BONES if b in smap and b in tmap}
    return info


@command("import_mocap")
def import_mocap(path, armature, start_frame=1, in_place=False, bone_map=None,
                 frame_start=None, frame_end=None, keep_source=False):
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
                                  in_place=in_place)
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
    info["next_start_frame"] = info["frames"][1] + 1
    return info


@command("clear_animation")
def clear_animation(armature, reset_pose=True):
    rig = _target(armature)
    rig.animation_data_clear()
    if reset_pose:
        for pb in rig.pose.bones:
            pb.location = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.rotation_euler = (0, 0, 0)
            pb.scale = (1, 1, 1)
    return {"armature": rig.name, "cleared": True}
