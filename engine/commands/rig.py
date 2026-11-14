"""Humanoid auto-rigging: landmarks -> armature (basic or Rigify) -> automatic skin weights.

rig_type="basic":  21 deform bones, game/mocap friendly, pose with plain FK rotations.
rig_type="rigify": full Rigify control rig (IK/FK, ~700 bones) for animation in Blender.
"""
import json
import math

import addon_utils
import bpy
from mathutils import Vector

from . import command
from .landmarks import CENTER, SIDE, human_landmarks, mirror
from .util import obj_or_raise

# basic skeleton: bone -> (head landmark, tail landmark, parent)
BASIC = {
    "hips": ("hips", "waist", None),
    "spine": ("waist", "chest", "hips"),
    "chest": ("chest", "neck_base", "spine"),
    "neck": ("neck_base", "chin", "chest"),
    "head": ("chin", "head_top", "neck"),
}
for _s in ("L", "R"):
    BASIC.update({
        f"shoulder.{_s}": (f"clavicle.{_s}", f"shoulder.{_s}", "chest"),
        f"upper_arm.{_s}": (f"shoulder.{_s}", f"elbow.{_s}", f"shoulder.{_s}"),
        f"forearm.{_s}": (f"elbow.{_s}", f"wrist.{_s}", f"upper_arm.{_s}"),
        f"hand.{_s}": (f"wrist.{_s}", f"hand_tip.{_s}", f"forearm.{_s}"),
        f"thigh.{_s}": (f"hip.{_s}", f"knee.{_s}", "hips"),
        f"shin.{_s}": (f"knee.{_s}", f"ankle.{_s}", f"thigh.{_s}"),
        f"foot.{_s}": (f"ankle.{_s}", f"ball.{_s}", f"shin.{_s}"),
        f"toe.{_s}": (f"ball.{_s}", f"toe_tip.{_s}", f"foot.{_s}"),
    })

# Rigify metarig bone -> (head landmark, tail landmark)
RIGIFY_FIT = {
    "spine": ("hips", "waist"), "spine.001": ("waist", "chest"),
    "spine.002": ("chest", "upper_chest"), "spine.003": ("upper_chest", "neck_base"),
    "spine.004": ("neck_base", "neck"), "spine.005": ("neck", "chin"),
    "spine.006": ("chin", "head_top"),
}
for _s in ("L", "R"):
    RIGIFY_FIT.update({
        f"shoulder.{_s}": (f"clavicle.{_s}", f"shoulder.{_s}"),
        f"upper_arm.{_s}": (f"shoulder.{_s}", f"elbow.{_s}"),
        f"forearm.{_s}": (f"elbow.{_s}", f"wrist.{_s}"),
        f"hand.{_s}": (f"wrist.{_s}", f"hand_tip.{_s}"),
        f"thigh.{_s}": (f"hip.{_s}", f"knee.{_s}"),
        f"shin.{_s}": (f"knee.{_s}", f"ankle.{_s}"),
        f"foot.{_s}": (f"ankle.{_s}", f"ball.{_s}"),
        f"toe.{_s}": (f"ball.{_s}", f"toe_tip.{_s}"),
    })
RIGIFY_DROP_PREFIX = ("palm", "f_", "thumb", "breast")


# --------------------------------------------------------------------------- helpers
def _world_verts(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    mw = ev.matrix_world
    return [mw @ v.co for v in ev.data.vertices]


def _estimate(obj):
    """Guess landmarks for an arbitrary standing humanoid mesh (faces -Y, Z up, T/A pose)."""
    vs = _world_verts(obj)
    if not vs:
        raise ValueError(f"{obj.name} has no vertices")
    lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
    hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
    H = hi.z - lo.z
    cx = (lo.x + hi.x) / 2
    torso = [v for v in vs if 0.45 * H < v.z - lo.z < 0.75 * H and abs(v.x - cx) < 0.12 * H]
    cy = sorted(v.y for v in torso)[len(torso) // 2] if torso else (lo.y + hi.y) / 2

    base = human_landmarks(H, heads=7.5, arm_angle=35.0)
    lm = {k: (v[0] + cx, v[1] + cy, v[2] + lo.z) for k, v in base.items()}

    # arms: aim each arm chain from the shoulder to the farthest vertex on that side
    for side, sign in (("L", 1), ("R", -1)):
        far = max(vs, key=lambda v: sign * (v.x - cx))
        reach = sign * (far.x - cx)
        if reach < 0.2 * H:   # arms down along the body: keep proportional guess
            continue
        tip_band = [v for v in vs if sign * (v.x - cx) > reach - 0.03 * H]
        tip = Vector((far.x, sum(v.y for v in tip_band) / len(tip_band),
                      sum(v.z for v in tip_band) / len(tip_band)))
        sh = Vector(lm[f"shoulder.{side}"])
        span = tip - sh
        total = 0.215 + 0.17 + 0.125
        el = sh + span * (0.215 / total) + Vector((0, 0.012 * H, 0))
        wr = sh + span * ((0.215 + 0.17) / total)
        lm[f"elbow.{side}"], lm[f"wrist.{side}"], lm[f"hand_tip.{side}"] = tuple(el), tuple(wr), tuple(tip)

    # feet: toe tip = most forward low vertex on each side
    for side, sign in (("L", 1), ("R", -1)):
        low = [v for v in vs if v.z - lo.z < 0.06 * H and sign * (v.x - cx) > 0]
        if low:
            toe = min(low, key=lambda v: v.y)
            heel = max(low, key=lambda v: v.y)
            x = sum(v.x for v in low) / len(low)
            a = lm[f"ankle.{side}"]
            lm[f"ankle.{side}"] = (x, a[1], a[2])
            lm[f"knee.{side}"] = (x, lm[f"knee.{side}"][1], lm[f"knee.{side}"][2])
            lm[f"toe_tip.{side}"] = (x, toe.y, lo.z + 0.01 * H)
            lm[f"ball.{side}"] = (x, toe.y + 0.35 * (heel.y - toe.y), lo.z + 0.015 * H)
            lm[f"heel.{side}"] = (x, heel.y, lo.z + 0.004 * H)
    return lm


def _landmarks(mesh, overrides=None):
    stored = mesh.get("c3d_landmarks")
    lm = json.loads(stored) if stored else _estimate(mesh)
    if overrides:
        lm.update({k: tuple(v) for k, v in overrides.items()})
        lm = mirror({k: v for k, v in lm.items()
                     if not (k.endswith(".R") and k[:-2] + ".L" in overrides and k not in overrides)})
    missing = [k for k in CENTER + [f"{s}.{x}" for s in SIDE for x in "LR"] if k not in lm]
    if missing:
        raise ValueError(f"missing landmarks: {missing}")
    return {k: Vector(v) for k, v in lm.items()}, ("stored" if stored else "estimated")


def _ctx(active, selected):
    return bpy.context.temp_override(active_object=active, object=active,
                                     selected_objects=selected, selected_editable_objects=selected)


def _mode(obj, mode):
    vl = bpy.context.view_layer
    if vl.objects.active and vl.objects.active is not obj and vl.objects.active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    vl.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode=mode)


def _orient(eb):
    """Bone Z axis points to the character's front (-Y); feet/toes get Z up instead.
    Result: bending elbows/knees/spine = rotation around the bone's local X axis."""
    d = (eb.tail - eb.head).normalized()
    eb.align_roll(Vector((0, 0, 1)) if abs(d.y) > 0.7 else Vector((0, -1, 0)))


def _build_basic(lm, name):
    arm = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, arm)
    bpy.context.scene.collection.objects.link(rig)
    rig.show_in_front = True
    _mode(rig, "EDIT")
    for bone, (h, t, parent) in BASIC.items():
        eb = arm.edit_bones.new(bone)
        eb.head, eb.tail = lm[h], lm[t]
        _orient(eb)
    for bone, (h, _t, parent) in BASIC.items():
        if parent:
            eb = arm.edit_bones[bone]
            eb.parent = arm.edit_bones[parent]
            eb.use_connect = (eb.parent.tail - eb.head).length < 1e-4
    _mode(rig, "OBJECT")
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
    return rig


def _build_rigify(lm, name):
    addon_utils.enable("rigify", default_set=True)
    vl = bpy.context.view_layer
    if vl.objects.active and vl.objects.active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.armature_human_metarig_add()
    meta = vl.objects.active
    meta.name = f"{name}_metarig"
    arm = meta.data
    _mode(meta, "EDIT")
    eb = arm.edit_bones
    # remove face, fingers, breasts (mesh has no geometry for them)
    face = eb.get("face")
    drop = set(face.children_recursive + [face]) if face else set()
    drop |= {b for b in eb if b.name.startswith(RIGIFY_DROP_PREFIX)}
    for b in drop:
        eb.remove(b)
    for bone, (h, t) in RIGIFY_FIT.items():
        b = eb[bone]
        b.head, b.tail = lm[h], lm[t]
    for s in ("L", "R"):
        hips, hip = lm["hips"], lm[f"hip.{s}"]
        p = eb[f"pelvis.{s}"]
        p.head = hips
        p.tail = hips + Vector((hip.x - hips.x, -0.05, 0.07)) * 1.0
        heel, hx = lm[f"heel.{s}"], 0.025 * (lm["head_top"].z - lm["heel.L"].z)
        h2 = eb[f"heel.02.{s}"]
        h2.head = heel + Vector((-hx, 0, 0))
        h2.tail = heel + Vector((hx, 0, 0))
    _mode(meta, "OBJECT")
    arm.rigify_rig_basename = name
    for o in bpy.context.selected_objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = meta
    meta.select_set(True)
    bpy.ops.pose.rigify_generate()  # no context override: Rigify switches active object itself
    rig = bpy.data.objects.get(name) or bpy.context.view_layer.objects.active
    bpy.data.objects.remove(meta, do_unlink=True)
    # default limbs to FK so set_pose rotations on *_fk controls work directly
    for pb in rig.pose.bones:
        if "IK_FK" in pb.keys():
            pb["IK_FK"] = 1.0
    return rig


def _deform_bones(rig):
    return [b.name for b in rig.data.bones if b.use_deform]


def _fill_unweighted(mesh, rig):
    """Give vertices that bone-heat missed a full weight to the nearest deform bone."""
    mw, rw = mesh.matrix_world, rig.matrix_world
    segs = []
    for b in rig.data.bones:
        if b.use_deform:
            segs.append((b.name, rw @ b.head_local, rw @ b.tail_local))
    groups = {vg.name: vg for vg in mesh.vertex_groups}
    fixed = 0
    for v in mesh.data.vertices:
        if sum(g.weight for g in v.groups if mesh.vertex_groups[g.group].name in groups) > 1e-4:
            continue
        p = mw @ v.co
        best, bd = None, 1e9
        for name, a, b in segs:
            ab = b - a
            t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-9)))
            d = (a + ab * t - p).length
            if d < bd:
                best, bd = name, d
        vg = groups.get(best) or mesh.vertex_groups.new(name=best)
        groups[best] = vg
        vg.add([v.index], 1.0, "REPLACE")
        fixed += 1
    return fixed


def _bind(mesh, rig):
    for m in [m for m in mesh.modifiers if m.type == "ARMATURE"]:
        mesh.modifiers.remove(m)
    mesh.vertex_groups.clear()
    mesh.parent = None
    with _ctx(rig, [mesh, rig]):
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    fixed = _fill_unweighted(mesh, rig)
    _limit_and_normalize(mesh, rig)
    return fixed


def _limit_and_normalize(mesh, rig, limit=4):
    """Game-engine friendly weights: at most `limit` deform influences, summing to 1."""
    deform = set(_deform_bones(rig))
    gi = {vg.index: vg for vg in mesh.vertex_groups if vg.name in deform}
    for v in mesh.data.vertices:
        ws = sorted(((g.weight, g.group) for g in v.groups if g.group in gi),
                    reverse=True)
        keep, drop = ws[:limit], ws[limit:]
        for _w, gidx in drop:
            gi[gidx].remove([v.index])
        total = sum(w for w, _ in keep)
        if total > 1e-6:
            for w, gidx in keep:
                gi[gidx].add([v.index], w / total, "REPLACE")


# --------------------------------------------------------------------------- commands
@command("estimate_landmarks")
def estimate_landmarks(mesh):
    """Landmarks auto_rig_humanoid would use for this mesh (stored or estimated)."""
    obj = obj_or_raise(mesh)
    lm, source = _landmarks(obj)
    return {"source": source, "landmarks": {k: [round(c, 4) for c in v] for k, v in lm.items()}}


@command("auto_rig_humanoid")
def auto_rig_humanoid(mesh, rig_type="basic", landmarks=None, name=None):
    obj = obj_or_raise(mesh)
    if obj.type != "MESH":
        raise TypeError(f"{mesh} is a {obj.type}, expected a MESH")
    if rig_type not in ("basic", "rigify"):
        raise ValueError("rig_type must be 'basic' or 'rigify'")
    lm, source = _landmarks(obj, landmarks)
    name = name or f"{obj.name}_rig"
    old = bpy.data.objects.get(name)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    rig = _build_basic(lm, name) if rig_type == "basic" else _build_rigify(lm, name)
    rig.name = name
    fixed = _bind(obj, rig)
    obj["c3d_rig"] = rig.name
    rig["c3d_rig_type"] = rig_type
    report = validate_rig(obj.name)
    report.update({"armature": rig.name, "rig_type": rig_type, "landmark_source": source,
                   "nearest_bone_filled_vertices": fixed})
    return report


@command("validate_rig")
def validate_rig(mesh):
    obj = obj_or_raise(mesh)
    mod = next((m for m in obj.modifiers if m.type == "ARMATURE" and m.object), None)
    if mod is None:
        return {"ok": False, "issues": [f"{mesh} has no armature modifier (not rigged)"]}
    rig = mod.object
    deform = set(_deform_bones(rig))
    gi = {vg.index: vg.name for vg in obj.vertex_groups if vg.name in deform}
    zero, max_inf, used = 0, 0, set()
    for v in obj.data.vertices:
        ws = [(gi[g.group], g.weight) for g in v.groups if g.group in gi and g.weight > 1e-4]
        if not ws:
            zero += 1
        max_inf = max(max_inf, len(ws))
        used.update(n for n, _ in ws)
    n = len(obj.data.vertices)
    issues = []
    if zero:
        issues.append(f"{zero}/{n} vertices have no deform weight")
    unused = sorted(deform - used)
    if len(unused) > len(deform) * 0.5:
        issues.append(f"{len(unused)} of {len(deform)} deform bones influence no vertices")
    if max_inf > 4:
        issues.append(f"max {max_inf} influences per vertex (game engines usually allow 4)")
    return {
        "ok": not zero,
        "mesh": obj.name,
        "armature": rig.name,
        "rig_type": rig.get("c3d_rig_type", "unknown"),
        "bones_total": len(rig.data.bones),
        "deform_bones": len(deform),
        "vertices": n,
        "unweighted_vertices": zero,
        "max_influences": max_inf,
        "unused_deform_bones": unused[:20],
        "issues": issues,
    }


@command("list_bones")
def list_bones(armature, deform_only=False, contains=None, limit=200):
    rig = obj_or_raise(armature)
    if rig.type != "ARMATURE":
        raise TypeError(f"{armature} is not an ARMATURE")
    out = []
    for b in rig.data.bones:
        if deform_only and not b.use_deform:
            continue
        if contains and contains.lower() not in b.name.lower():
            continue
        out.append({"name": b.name, "parent": b.parent.name if b.parent else None,
                    "deform": b.use_deform})
    return {"armature": rig.name, "count": len(out), "bones": out[:limit]}


@command("set_pose")
def set_pose(armature, bones=None, reset=False, frame=None, keyframe=False):
    """bones: {"bone": [rx, ry, rz]} (local XYZ Euler degrees) or
    {"bone": {"rotation_deg": [...], "location": [...], "scale": [...]}}."""
    rig = obj_or_raise(armature)
    if rig.type != "ARMATURE":
        raise TypeError(f"{armature} is not an ARMATURE")
    sc = bpy.context.scene
    if frame is not None:
        sc.frame_set(int(frame))
    if reset:
        for pb in rig.pose.bones:
            pb.location = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.rotation_euler = (0, 0, 0)
            pb.scale = (1, 1, 1)
    unknown = []
    for name, spec in (bones or {}).items():
        pb = rig.pose.bones.get(name)
        if pb is None:
            unknown.append(name)
            continue
        if isinstance(spec, (list, tuple)):
            spec = {"rotation_deg": spec}
        if "rotation_deg" in spec:
            pb.rotation_mode = "XYZ"
            pb.rotation_euler = [math.radians(a) for a in spec["rotation_deg"]]
        if "location" in spec:
            pb.location = spec["location"]
        if "scale" in spec:
            pb.scale = spec["scale"]
        if keyframe:
            f = sc.frame_current
            for path in ("rotation_euler", "location", "scale"):
                pb.keyframe_insert(path, frame=f)
    bpy.context.view_layer.update()
    if unknown:
        raise KeyError(f"unknown bones {unknown}. Use list_bones to see names.")
    return {"armature": rig.name, "frame": sc.frame_current, "posed": list((bones or {}).keys())}
