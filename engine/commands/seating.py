"""Seat-aware FK baking with shared analytic limb IK (meters, world Z up)."""
import json
import math
import time

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from . import command, anim
from .footlock import _ik_knee, _rotate_bone, _sole_points, _legs, _smoothstep
from .talk import _rig_of, _fcurves
from .util import obj_or_raise, vec


def _start(rig, frame, transition):
    sc = bpy.context.scene
    if type(transition) is not int or not 1 <= transition <= 1000:
        raise ValueError("transition_frames must be an integer in 1..1000")
    action = rig.animation_data.action if rig.animation_data else None
    f = int(frame) if frame is not None else (int(action.frame_range[1])+1 if action else sc.frame_start)
    if f < sc.frame_start:
        raise ValueError("start_frame must be at or after scene start")
    sc.frame_set(f-1 if anim._has_keys_before(rig, f) else f)
    return f


def _seat(name, index):
    obj = obj_or_raise(name)
    anchor = bpy.data.objects.get(obj.get("c3d_seat_anchor", ""))
    if anchor is None and "c3d_seat_centers" in obj:
        anchor = obj
    if anchor is None and obj.type == "EMPTY":
        positions = [(part, i) for part in obj.children_recursive
                     if "c3d_seat_centers" in part
                     for i in range(len(json.loads(part["c3d_seat_centers"])))]
        if positions:
            if type(index) is not int or not 0 <= index < len(positions):
                raise ValueError(f"seat_index must be in 0..{len(positions)-1}")
            anchor, index = positions[index]
    if anchor is not None:
        centers = json.loads(anchor["c3d_seat_centers"])
        if type(index) is not int or not 0 <= index < len(centers):
            raise ValueError(f"seat_index must be in 0..{len(centers)-1}")
        mw = anchor.matrix_world
        center = mw @ Vector(centers[index])
        front = mw.to_3x3() @ Vector(anchor["c3d_seat_front"])
        floor = (mw @ Vector((0, 0, anchor["c3d_seat_floor"]))).z
        arms = [mw @ Vector(p) for p in json.loads(anchor.get("c3d_seat_armrests", "[]"))]
    else:
        if obj.type != "MESH":
            raise ValueError("seat must be a seat root/part or mesh")
        if index != 0:
            raise ValueError("unmarked meshes have only seat_index=0")
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = ev.to_mesh()
        try:
            pts = [ev.matrix_world @ v.co for v in mesh.vertices]
            top = max(p.z for p in pts)
            cap = [p for p in pts if p.z > top-0.005]
            center = sum(cap, Vector()) / len(cap)
        finally:
            ev.to_mesh_clear()
        front = obj.matrix_world.to_3x3() @ Vector((0, -1, 0))
        floor, arms = bpy.context.scene.get("c3d_seat_floor", 0.0), []
    if abs(front.z) > 0.05 * front.length:
        raise ValueError("tilted seats are not supported (seat front must be horizontal)")
    front.z = 0
    front.normalize()
    return center, front, float(floor), arms


def _world(rig, smap):
    return {b: (rig.matrix_world @ rig.pose.bones[n].matrix).copy() for b, n in smap.items()}


def _rest_front(rig, smap):
    mw = rig.matrix_world
    left = (mw @ rig.data.bones[smap["thigh.L"]].head_local -
            mw @ rig.data.bones[smap["thigh.R"]].head_local)
    return Vector((left.y, -left.x, 0)).normalized()


def _put(rig, smap, mats):
    for b in sorted(mats, key=lambda b: anim._depth(rig, smap[b])):
        m = mats[b]
        anim._set_world_rot(rig, rig.pose.bones[smap[b]], m.to_quaternion(),
                            m.translation if b == "hips" else None)
        bpy.context.view_layer.update()


def _chain(rig, names, target, pole, rotation=None):
    """Shared footlock two-bone IK, also suitable for an elbow/wrist chain."""
    a, b, c = [rig.pose.bones[n] for n in names]
    mw = rig.matrix_world
    H, K, A = [(mw @ p.matrix).translation for p in (a, b, c)]
    knee = _ik_knee(H, target, (K-H).length, (A-K).length, pole)
    _rotate_bone(rig, a, K-H, knee-H)
    bpy.context.view_layer.update()
    K, A = [(mw @ p.matrix).translation for p in (b, c)]
    _rotate_bone(rig, b, A-K, target-K)
    bpy.context.view_layer.update()
    if rotation is not None:
        anim._set_world_rot(rig, c, rotation)
        bpy.context.view_layer.update()
    return ((mw @ c.matrix).translation-target).length


def _body_samples(rig, smap):
    """Cache posterior pelvis vertex indices in evaluated REST topology, once per seat.

    A world-space height slab alone accidentally sees calves on tall seats. Selecting
    anatomical samples before deformation keeps calibration independent of knee bending.
    """
    mode = rig.data.pose_position
    rig.data.pose_position = "REST"
    bpy.context.view_layer.update()
    mw = rig.matrix_world
    hip = sum((mw @ rig.data.bones[smap[f"thigh.{s}"]].head_local for s in "LR"), Vector())/2
    forward = _rest_front(rig, smap)
    left = Vector((-forward.y, forward.x, 0))
    samples = {}
    try:
        for obj in rig.children_recursive:
            if obj.type != "MESH" or obj.hide_render or obj.get("c3d_role") == "environment":
                continue
            if rig.get('c3d_rig_type') == 'vrm' and not obj.get('c3d_vrm_body'):
                continue
            ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = ev.to_mesh()
            try:
                co = np.empty(len(mesh.vertices)*3)
                mesh.vertices.foreach_get("co", co)
                mat = np.asarray(ev.matrix_world)
                delta = co.reshape(-1, 3) @ mat[:3, :3].T + mat[:3, 3]-np.asarray(hip)
                use = ((delta[:, 2] > -0.20) & (delta[:, 2] < 0.15)
                       & (np.abs(delta @ np.asarray(left)) < 0.24)
                       & (delta @ np.asarray(forward) < 0.035))
                if rig.get('c3d_rig_type') == 'vrm':
                    from .vrm_actor import skin_slots
                    slots=skin_slots(obj)
                    ids={i for p in mesh.polygons if p.material_index in slots for i in p.vertices}
                    skin=np.zeros(len(mesh.vertices),dtype=bool)
                    if ids:skin[list(ids)]=True
                    if np.count_nonzero(use & skin)>=8:
                        use &= skin
                if use.any():
                    samples[obj.name] = np.flatnonzero(use)
            finally:
                ev.to_mesh_clear()
    finally:
        rig.data.pose_position = mode
        bpy.context.view_layer.update()
    return samples


def _contact_height(rig, center, front, samples):
    """Lowest evaluated body/clothing vertex around the posterior pelvis, excluding legs/hands.

    foreach_get + numpy avoids per-vertex Python work, including on subdivided bodies.
    The narrow posterior slab excludes knees even on short/stocky mannequins.
    """
    left = Vector((-front.y, front.x, 0))
    deps = bpy.context.evaluated_depsgraph_get()
    lows = []
    for name, indices in samples.items():
        obj = bpy.data.objects[name]
        ev = obj.evaluated_get(deps)
        mesh = ev.to_mesh()
        try:
            co = np.empty(len(mesh.vertices)*3, dtype=np.float64)
            mesh.vertices.foreach_get("co", co)
            mw = np.asarray(ev.matrix_world)
            pts = co.reshape(-1, 3)[indices] @ mw[:3, :3].T + mw[:3, 3]
            delta = pts-np.asarray(center)
            x, y = delta @ np.asarray(left), delta @ np.asarray(front)
            use = ((np.abs(x) < 0.22) & (y > -0.19) & (y < 0.045)
                   & (pts[:, 2] > center.z-0.30) & (pts[:, 2] < center.z+0.25))
            if use.any():
                lows.append(float(pts[use, 2].min()))
        finally:
            ev.to_mesh_clear()
    if not lows:
        raise ValueError("cannot measure buttock contact: character needs a visible body mesh")
    return min(lows)


def _feet(rig, smap, center, front, floor):
    """Flat sole targets, with knees forward and shins nearly vertical on standard chairs."""
    mw = rig.matrix_world
    legs, _ = _legs(rig)
    rest_forward = _rest_front(rig, smap)
    yaw = math.atan2(front.x, -front.y)-math.atan2(rest_forward.x, -rest_forward.y)
    turn = Quaternion((0, 0, 1), yaw)
    out = {}
    for s, leg in legs.items():
        thigh, shin, foot = [rig.pose.bones[leg[k]] for k in ("thigh", "shin", "foot")]
        H, K, A = [(mw @ p.matrix).translation for p in (thigh, shin, foot)]
        l1, l2 = (K-H).length, (A-K).length
        rest = mw @ foot.bone.matrix_local
        q = turn @ rest.to_quaternion()
        sole = _sole_points(rig, leg, mw.translation.z)
        height = -min((q @ (p * rest.to_scale().x)).z for p in sole)
        dz = H.z-(floor+height+l2)
        forward = math.sqrt(max(l1*l1-dz*dz, (l1*0.45)**2))
        target = H+front*forward
        target.z = floor+height
        out[s] = (target, q)
    return out


def _key(rig, smap, f, prev):
    for n in smap.values():
        pb = rig.pose.bones[n]
        anim._key_rot(pb, f, prev)
    rig.pose.bones[smap["hips"]].keyframe_insert("location", frame=f, group=smap["hips"])


def _bake(rig, smap, initial, target, feet, front, f0, transition, standing=False):
    if rig.get('c3d_rig_type') == 'vrm' and any(o.type == 'MESH' and not o.hide_viewport and any(m.type=='ARMATURE' for m in o.modifiers)
            for o in rig.children_recursive):
        # The contact solve above uses skin; this final pass keys only bones.
        # Avoid evaluating VRoid outline geometry after every IK bone update.
        from .script_scene import _bones_only
        with _bones_only():
            return _bake(rig, smap, initial, target, feet, front, f0, transition, standing)
    sc = bpy.context.scene
    end = f0+transition
    hold = max(sc.frame_end, end)
    previous, error = {}, 0.0
    paths = {f'pose.bones["{n}"].{p}' for n in smap.values()
             for p in ("rotation_euler", "rotation_quaternion", "rotation_axis_angle")}
    paths.add(f'pose.bones["{smap["hips"]}"].location')
    if rig.animation_data and rig.animation_data.action:
        for fc in _fcurves(rig.animation_data.action):
            if fc.data_path in paths:
                for k in reversed(list(fc.keyframe_points)):
                    if f0 <= k.co.x <= hold:
                        fc.keyframe_points.remove(k, fast=True)
                fc.update()
    # Sparse holds stay constant beyond the scene end and keep append semantics.
    frames = list(range(f0, end+1)) + ([hold] if hold > end else [])
    for f in frames:
        sc.frame_set(f)
        t = _smoothstep((f-f0)/transition)
        mats = {}
        for b in target:
            a, z = initial[b], target[b]
            m = a.to_quaternion().slerp(z.to_quaternion(), t).to_matrix().to_4x4()
            m.translation = a.translation.lerp(z.translation, t)
            if b == "hips":
                # Anticipation leans the torso forward; translation eases back/down to the seat.
                m.translation += front * (0.045*math.sin(math.pi*t))
            mats[b] = m
        _put(rig, smap, mats)
        for s, (pos, q) in feet.items():
            # Transition gathers feet smoothly; the entire seated/standing hold is planted.
            a = initial[f"foot.{s}"]
            p = a.translation.lerp(pos, t)
            rot = a.to_quaternion().slerp(q, t)
            error = max(error, _chain(rig, [smap[f"{b}.{s}"] for b in ("thigh", "shin", "foot")],
                                      p, front, rot))
        _key(rig, smap, f, previous)
    # Dense transition samples use linear interpolation (no Bezier overshoot at contact).
    for fc in _fcurves(rig.animation_data.action):
        for k in fc.keyframe_points:
            if f0 <= k.co.x <= hold:
                k.interpolation = "LINEAR"
    anim._extend_range(hold)
    sc.frame_set(end)
    return {"frames": [f0, hold], "transition_end": end, "next_start_frame": hold+1,
            "max_ik_error_m": round(error, 5)}


def _desk_top(point, reach=0.45):
    """Highest desk/table surface under point (world XY) within reach below/above it."""
    best = None
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.get("c3d_prop_kind") not in ("desk", "table") or not obj.visible_get():
            continue
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        xs, ys = [c.x for c in corners], [c.y for c in corners]
        if not (min(xs) + 0.03 <= point.x <= max(xs) - 0.03 and min(ys) + 0.03 <= point.y <= max(ys) - 0.03):
            continue
        top = max(c.z for c in corners)
        if abs(top - point.z) < reach and (best is None or top > best):
            best = top
    return best


def _flat_hand(palm, fingers):
    """World hand-bone rotation with bone +Y along fingers and the palm facing down."""
    from mathutils import Matrix
    y = Vector((0, 1, 0))
    p = (palm - y*palm.dot(y)).normalized()
    local = Matrix((y, p, y.cross(p))).transposed()
    f = Vector((fingers.x, fingers.y, 0)).normalized()
    n = Vector((0, 0, -1))
    world = Matrix((f, n, f.cross(n))).transposed()
    return (world @ local.transposed()).to_quaternion()


def _rest_tilt(q, fingers, medial):
    """A resting hand is not perfectly flat: the thumb side lifts ~20 degrees and the
    fingertips ~15 degrees. Flat, the thumb sank ~3 cm and the fingertips ~1 cm into
    the desk; tilted, the palm, fingers and thumb all clear it by a few millimetres."""
    z = Vector((0, 0, 1))
    f = Vector((fingers.x, fingers.y, 0)).normalized()
    m = Vector((medial.x, medial.y, 0)).normalized()
    roll = math.radians(15) * (1 if f.cross(m).z > 0 else -1)
    return Quaternion(f.cross(z).normalized(), math.radians(10)) @ Quaternion(f, roll) @ q


def _desk_gap(rig, side, chain):
    """Lowest evaluated hand/finger skin above the desk top (m), or None.

    Hand thickness differs per character, so a fixed wrist height left male hands
    floating ~1.5 cm while others touched. Mask modifiers are disabled briefly so
    evaluated vertex indices match the rest mesh's vertex groups."""
    from .fingers import HandRig
    from .materials import _family
    try:
        _, body, _ = _family(rig.name)
    except ValueError:
        return None
    bones = {chain[-1]} | {b for ch in HandRig(rig).fingers.get(side, {}).values() for b in ch}
    deform = {b.name for b in rig.data.bones if b.use_deform}
    names = {g.index: g.name for g in body.vertex_groups if g.name in deform}
    picked = []
    for v in body.data.vertices:
        groups = [g for g in v.groups if g.group in names]
        if groups and names[max(groups, key=lambda g: g.weight).group] in bones:
            picked.append(v.index)
    if not picked:
        return None
    masks = [m for m in body.modifiers if m.type == "MASK" and m.show_viewport]
    for m in masks:
        m.show_viewport = False
    try:
        bpy.context.view_layer.update()
        ev = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = ev.to_mesh()
        try:
            if len(mesh.vertices) != len(body.data.vertices):
                return None
            co = np.empty(len(mesh.vertices) * 3)
            mesh.vertices.foreach_get("co", co)
        finally:
            ev.to_mesh_clear()
    finally:
        for m in masks:
            m.show_viewport = True
        bpy.context.view_layer.update()
    mw = np.array(body.matrix_world)
    pts = co.reshape(-1, 3)[picked] @ mw[:3, :3].T + mw[:3, 3]
    gaps = []
    for x, y, z in pts:
        top = _desk_top(Vector((x, y, z)))
        if top is not None:
            gaps.append(z - top)
    return min(gaps) if gaps else None


def _desk_rest(rig, smap, side, sign, front, left):
    """Palm target resting on the desk in front of a seated shoulder, or None."""
    mw = rig.matrix_world
    upper, fore = (rig.pose.bones[smap[f"{b}.{side}"]] for b in ("upper_arm", "forearm"))
    shoulder = (mw @ upper.matrix).translation
    length = (upper.bone.length + fore.bone.length) * mw.to_scale().x
    for ahead in (0.50, 0.46, 0.42, 0.36, 0.30):
        p = shoulder + front * ahead * length / 0.55 - left * sign * 0.05
        top = _desk_top(Vector((p.x, p.y, shoulder.z - 0.35)))
        if top is None:
            continue
        p.z = top + 0.026
        if (p - shoulder).length < 0.96 * length:
            return p
    return None


@command("sit_on")
def sit_on(character, seat, start_frame=None, transition_frames=20, seat_index=0, hands="thighs", collisions=True):
    started = time.perf_counter()
    if hands not in ("thighs", "lap", "armrests", "desk", "none"):
        raise ValueError("hands must be thighs, lap, armrests, desk or none")
    rig = _rig_of(character)
    bpy.context.view_layer.update()
    center, front, floor, arms = _seat(seat, seat_index)
    if hands == "armrests" and not arms:
        raise ValueError("this seat has no armrests; use thighs, lap or none")
    f0 = _start(rig, start_frame, transition_frames)
    smap = anim.semantic_map(rig)
    initial = _world(rig, smap)
    samples = _body_samples(rig, smap)
    arm_basis = {n: rig.pose.bones[n].matrix_basis.copy() for b, n in smap.items()
                 if b.split(".")[0] in ("shoulder", "upper_arm", "forearm", "hand")}
    anim.apply_pose(rig.name, "sit", frame=f0)
    pose = _world(rig, smap)
    old = pose["hips"].translation.copy()
    rest = rig.matrix_world @ rig.data.bones[smap["hips"]].matrix_local
    rest_front = _rest_front(rig, smap)
    direction = pose["hips"].to_quaternion() @ rest.to_quaternion().inverted() @ rest_front
    yaw = math.atan2(front.x, -front.y)-math.atan2(direction.x, -direction.y)
    turn = Quaternion((0, 0, 1), yaw)
    hip = center+Vector((0, 0, 0.10))
    for b, m in pose.items():
        m.translation = hip+turn @ (m.translation-old)
        q = turn @ m.to_quaternion()
        m2 = q.to_matrix().to_4x4()
        m2.translation = m.translation
        pose[b] = m2
    _put(rig, smap, pose)
    # A small recline (or desk lean), independent of rig-local bone roll.
    spine = smap.get("spine") or smap.get("chest")
    if spine:
        pb = rig.pose.bones[spine]
        left = Vector((-front.y, front.x, 0))
        # Lean onto a desk (shoulders come forward over it); otherwise recline.
        anim._set_world_rot(rig, pb, Quaternion(left, math.radians(9 if hands == "desk" else -5)) @
                            (rig.matrix_world @ pb.matrix).to_quaternion())
        bpy.context.view_layer.update()
    for _ in range(12):
        feet = _feet(rig, smap, center, front, floor)
        for s, (p, q) in feet.items():
            _chain(rig, [smap[f"{b}.{s}"] for b in ("thigh", "shin", "foot")], p, front, q)
        z = _contact_height(rig, center, front, samples)
        if abs(center.z-z) < 0.0001:
            break
        pb = rig.pose.bones[smap["hips"]]
        m = rig.matrix_world @ pb.matrix
        m.translation.z += center.z-z
        anim._set_world_rot(rig, pb, m.to_quaternion(), m.translation)
        bpy.context.view_layer.update()
    feet = _feet(rig, smap, center, front, floor)
    for s, (p, q) in feet.items():
        _chain(rig, [smap[f"{b}.{s}"] for b in ("thigh", "shin", "foot")], p, front, q)
    left = Vector((-front.y, front.x, 0))
    if hands != "none":
        for s, sign in (("L", 1), ("R", -1)):
            H = (rig.matrix_world @ rig.pose.bones[smap[f"thigh.{s}"]].matrix).translation
            p = H+front*(0.22 if hands == "thighs" else 0.12)+Vector((0, 0, 0.10))
            pole = left*sign-front*0.2
            rest = _desk_rest(rig, smap, s, sign, front, left) if hands == "desk" else None
            if rest is not None:
                p, pole = rest, left*sign*0.7-front*0.35-Vector((0, 0, 0.9))
            if hands == "lap":
                p -= left*sign*0.07
            if hands == "armrests":
                reachable = min(arms, key=lambda a: (a-p).length)
                if (reachable-H).length < 0.60:
                    p = reachable+Vector((0, 0, 0.03))
            hand = rig.pose.bones[smap[f"hand.{s}"]]
            q = (rig.matrix_world @ hand.matrix).to_quaternion()
            from .fingers import HandRig
            palm = HandRig(rig).palm_local(s, hand.name)
            if palm is not None and rest is not None:
                # Flat on the desk: palm down, fingers forward and slightly inward.
                fingers = (front - left*sign*0.3).normalized()
                q = _rest_tilt(_flat_hand(palm, fingers), fingers, -left*sign)
            elif palm is not None:
                q = (q @ palm).rotation_difference(Vector((0, 0, -1))) @ q
            chain = [smap[f"{b}.{s}"] for b in ("upper_arm", "forearm", "hand")]
            if rest is not None:
                from .fingers import HandRig
                fingers_rig = HandRig(rig)
                if s in fingers_rig.fingers:   # the shape desk staging keys afterwards
                    fingers_rig.apply(s, "open", 1.0, {b: Matrix.Translation(rig.pose.bones[b].location)
                                                       for ch in fingers_rig.fingers[s].values() for b in ch})
            _chain(rig, chain, p, pole, q)
            if rest is not None:
                # Settle the lowest skin point 3 mm above the desk for this hand's thickness.
                gap = _desk_gap(rig, s, chain)
                if gap is not None and abs(gap - 0.003) > 0.001:
                    p = p - Vector((0, 0, gap - 0.003))
                    _chain(rig, chain, p, pole, q)
    if hands == "none":
        for n, basis in arm_basis.items():
            rig.pose.bones[n].matrix_basis = basis
        bpy.context.view_layer.update()
    target = _world(rig, smap)
    info = _bake(rig, smap, initial, target, feet, front, f0, transition_frames)
    from .sfx import record_seat_event
    record_seat_event(rig, "sit", seat, f0, info["transition_end"])
    rig["c3d_seated"] = json.dumps({"seat": seat, "front": list(front), "floor": floor,
                                    "center": list(center), "seat_index": seat_index})
    rig["c3d_seat_active"] = True
    from .collision import automatic
    collision_report = automatic(collisions, [rig.name], f0, info['frames'][1])
    contact = _contact_height(rig, center, front, samples)
    return {"character": rig.name, "seat": seat, "seat_index": seat_index, "hands": hands,
            "seat_surface_z": round(center.z, 5), "buttock_z": round(contact, 5),
            "seat_center": vec(center), "seat_front": vec(front),
            "contact_error_m": round(contact-center.z, 5), "floor": floor,
            "feet": {s: vec(p) for s, (p, q) in feet.items()}, **info,
            "collisions": collision_report, "bake_seconds": round(time.perf_counter()-started, 3)}


@command("stand_up")
def stand_up(character, start_frame=None, transition_frames=20):
    started = time.perf_counter()
    rig = _rig_of(character)
    if not rig.get("c3d_seated"):
        raise ValueError("character has no saved seat; call sit_on first")
    seat = json.loads(rig["c3d_seated"])
    front, center = Vector(seat["front"]), Vector(seat["center"])
    f0 = _start(rig, start_frame, transition_frames)
    smap = anim.semantic_map(rig)
    initial = _world(rig, smap)
    anim.apply_pose(rig.name, "relaxed", frame=f0)
    target = _world(rig, smap)
    old = target["hips"].translation.copy()
    rest_front = _rest_front(rig, smap)
    turn = Quaternion((0, 0, 1), math.atan2(front.x, -front.y)-math.atan2(rest_front.x, -rest_front.y))
    hip = center+front*0.43
    hip.z = (rig.matrix_world @ rig.data.bones[smap["hips"]].matrix_local).translation.z
    hip.z += seat["floor"]-rig.matrix_world.translation.z
    for b, m in target.items():
        p = hip+turn @ (m.translation-old)
        m2 = (turn @ m.to_quaternion()).to_matrix().to_4x4()
        m2.translation = p
        target[b] = m2
    feet = {s: (target[f"foot.{s}"].translation, target[f"foot.{s}"].to_quaternion()) for s in "LR"}
    info = _bake(rig, smap, initial, target, feet, front, f0, transition_frames, True)
    rig["c3d_seat_active"] = False
    from .sfx import record_seat_event
    record_seat_event(rig, "stand", seat["seat"], f0, info["transition_end"])
    return {"character": rig.name, "standing_pelvis_z": round(hip.z, 5), **info,
            "bake_seconds": round(time.perf_counter()-started, 3)}
