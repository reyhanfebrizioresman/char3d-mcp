"""Retarget one continuous walking take and settle into a grounded stance."""

import math
from pathlib import Path
from statistics import median

import bpy
from mathutils import Matrix, Quaternion, Vector

from engine import context
from . import anim, command
from .fingers import HandRig
from .footlock import _legs, _smoothstep, _sole_points, foot_lock
from .performance import (UP, animation_edit, blend_swing_corrections, bone_map,
                          floor_of, ground_shoe, heading, number, point, refine_shoes,
                          shoe_samples, stance_anchor, start_at)
from .talk import _rig_of
from .util import obj_or_raise, vec


BODY_MOTION = {
    "hips": .88, "spine": .82, "chest": .88, "neck": .68, "head": .78,
    "shoulder.L": .62, "shoulder.R": .62, "upper_arm.L": .94, "upper_arm.R": .94,
    "forearm.L": .88, "forearm.R": .88,
}
LEGS = tuple(f"{part}.{side}" for side in "LR" for part in ("thigh", "shin", "foot"))


@command("walk_approach")
def walk_approach(armature, path, destination, source_frames, contacts, start_frame=None,
                  sole_mesh=None, floor=None, arm_swing=5.0, stance_width=None, _origin=None):
    """Fit a level-ground BVH walk-and-stop take to a humanoid and a world XY destination."""
    scene = bpy.context.scene
    rig = _rig_of(armature)
    names = bone_map(rig, ("hips", "chest", "head", *LEGS))
    mesh = obj_or_raise(sole_mesh) if sole_mesh is not None else None
    if mesh is not None and mesh.type != "MESH":
        raise ValueError("sole_mesh must name a mesh containing both shoes")
    start = start_at(scene, rig, start_frame)
    floor = floor_of(rig, floor)
    xy = point(destination, 2, "destination")
    swing = number(arm_swing, "arm_swing", 0, 20)
    width = number(stance_width, "stance_width", .04, .65) if stance_width is not None else None
    first, last, intervals = contact_ranges(source_frames, contacts)
    file = Path(context.resolve(path, "imports"))
    if file.suffix.lower() != ".bvh" or not file.is_file():
        raise ValueError("path must name a readable BVH under imports or an absolute BVH path")
    fps = scene.render.fps / scene.render.fps_base
    end = start + last - first
    footfalls = sorted((start + a, side) for side, ranges in intervals.items() for a, _ in ranges if a)
    if not footfalls or end - footfalls[-1][0] < 2:
        raise ValueError("the take needs a footfall followed by at least two standing frames")

    with animation_edit(scene, start, rig):
        scene.frame_set(start)
        forward, lateral = heading(rig)
        target = Vector((xy.x, xy.y, floor))
        if _origin is not None:
            forward = Vector((xy.x - _origin.x, xy.y - _origin.y, 0)).normalized()
            lateral = UP.cross(forward)
        legs, _ = _legs(rig)
        leg = leg_length(rig, names)
        rest_floor = floor_of(rig, None)
        anim.apply_pose(rig.name, "relaxed", frame=start, keyframe=False)
        mw = rig.matrix_world
        roles = [role for role in BODY_MOTION if role in names]
        neutral = {role: rig.pose.bones[names[role]].matrix_basis.to_quaternion() for role in roles}
        upright_z = (mw @ rig.pose.bones[names["hips"]].head).z + floor - rest_floor + .012 * leg
        ankles = {s: mw @ rig.pose.bones[names[f"foot.{s}"]].matrix for s in "LR"}
        if mesh is not None:
            soles, groups = shoe_samples(mesh, ankles, lateral)
        else:
            soles = {s: _sole_points(rig, chain, rest_floor) for s, chain in legs.items()}

        before = set(bpy.data.objects)
        source = None
        try:
            bpy.ops.import_anim.bvh(filepath=str(file), use_fps_scale=True, rotate_mode="QUATERNION",
                                    update_scene_duration=False, update_scene_fps=False)
            source = next((obj for obj in bpy.data.objects if obj not in before and obj.type == "ARMATURE"), None)
            if source is None or source.animation_data is None or source.animation_data.action is None:
                raise ValueError("BVH has no animated armature")
            smap = bone_map(source, ("hips", "head", *LEGS))
            if last > math.ceil(source.animation_data.action.frame_range[1]):
                raise ValueError("source_frames extend beyond the BVH at scene FPS")
            turn = math.atan2(forward.x, -forward.y)
            facing = Quaternion(UP, turn) @ anim._facing(source, smap)
            scale = leg / leg_length(source, smap)
            samples, heights = captured_feet(scene, source, smap, first, last, intervals, fps)
            delta = facing @ (samples[-1]["hips"] - samples[0]["hips"]) * scale
            if delta.dot(forward) <= .08:
                raise ValueError("BVH range must contain forward travel")
            # The centre continues forward briefly over the already planted feet.
            motion_end = target + forward * (.032 * leg)
            stretch = 1.0
            if _origin is not None:
                desired = Vector((motion_end.x - _origin.x, motion_end.y - _origin.y, 0))
                yaw = math.atan2(delta.cross(desired).z, delta.dot(desired))
                facing = Quaternion(UP, yaw) @ facing
                delta = Quaternion(UP, yaw) @ delta
                stretch = desired.length / delta.xy.length
            hip_rest = mw @ rig.data.bones[names["hips"]].head_local
            carry = motion_end - hip_rest - delta
            carry.z = floor - rest_floor - .017 * leg - delta.z
            info = anim.bake_retarget(source, rig, smap, names, first, last, start,
                                      carry=carry, root_scale=scale, facing=facing)
        finally:
            for obj in [o for o in bpy.data.objects if o not in before]:
                data = obj.data
                action = obj.animation_data.action if obj.animation_data else None
                bpy.data.objects.remove(obj, do_unlink=True)
                if data is not None and isinstance(data, bpy.types.Armature) and not data.users:
                    bpy.data.armatures.remove(data)
                if action and not action.users:
                    bpy.data.actions.remove(action)

        settings = {s: [world_rotation(scene, rig, names[f"foot.{s}"], f)
                        for f in range(start, end + 1)] for s in "LR"}
        standing = target.copy()
        standing.z = upright_z

        def fit_travel(position):
            offset = (position - motion_end).dot(forward) * (stretch - 1)
            return position + forward * offset

        polish_body(scene, rig, names, neutral, standing, start, end, footfalls, swing, lateral, fps, fit_travel)

        targets = {}
        width = width if width is not None else .253 * leg
        for side, sign in (("L", 1), ("R", -1)):
            q = quiet_foot(settings[side], ankles[side].to_quaternion(), footfalls[-1][0] - start, fps)
            positions = [fit_travel(motion_end + facing @ (sample[side] - samples[-1]["hips"]) * scale)
                         for sample in samples]
            landing = target + forward * ((-.029 + .022 * sign) * leg) + lateral * (width / 2 * sign)
            shift_final_footfall(positions, intervals[side], landing)
            corrections = planted_shifts(positions, q, soles[side], intervals[side])
            targets[side] = [ground_shoe(p + d, rot, soles[side], floor + h * scale)
                             for p, d, rot, h in zip(positions, corrections, q, heights[side])]
        absolute = {s: [[a + start, b + start] for a, b in ranges] for s, ranges in intervals.items()}
        lock = foot_lock(rig, start, end, floor=floor, terrain=False, contacts=absolute, foot_targets=targets)
        if mesh is not None:
            refine_shoes(scene, mesh, start, targets, soles, groups, intervals)
            refined = foot_lock(rig, start, end, floor=floor, terrain=False,
                                contacts=absolute, foot_targets=targets, adjust_hips=False)
            lock["max_ik_error_m"] = refined["max_ik_error_m"]
        orient_hands(scene, rig, names, start, end)
        anim._extend_range(end)
        scene.frame_set(end)
        actual = mw @ rig.pose.bones[names["hips"]].head
    return {**info, "armature": rig.name, "next_start_frame": end + 1, "source_file": file.name,
            "destination": vec(actual.xy), "foot_lock": lock,
            "footfalls": [{"frame": frame, "side": side, "character": rig.name} for frame, side in footfalls],
            "distance_m": round(delta.xy.length * stretch, 4), "fps": fps}


def contact_ranges(source_frames, contacts):
    if (not isinstance(source_frames, (list, tuple)) or len(source_frames) != 2 or
        any(type(f) is not int for f in source_frames)):
        raise ValueError("source_frames must be [first, last] at scene FPS")
    first, last = source_frames
    if not 1 <= first < last or last - first >= 24000:
        raise ValueError("source_frames must be positive and span fewer than 24000 frames")
    if not isinstance(contacts, dict) or set(contacts) != {"L", "R"}:
        raise ValueError("contacts must specify source frame intervals for L and R")
    result = {}
    for side, pairs in contacts.items():
        if not isinstance(pairs, (list, tuple)) or not pairs:
            raise ValueError(f"contacts for {side} must be nonempty")
        prior = first - 2
        result[side] = []
        for pair in pairs:
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                any(type(f) is not int for f in pair)):
                raise ValueError(f"each contact on {side} must be [first, last]")
            a, b = pair
            if not first <= a <= b <= last or a <= prior + 1:
                raise ValueError(f"contact intervals on {side} must be ordered and separated by a swing")
            result[side].append((a - first, b - first))
            prior = b
        if prior != last:
            raise ValueError(f"last {side} contact must include the final standing frame")
    return first, last, result


def leg_length(rig, names):
    points = [rig.matrix_world @ rig.data.bones[names[f"{role}.L"]].head_local
              for role in ("thigh", "shin", "foot")]
    length = sum((b - a).length for a, b in zip(points, points[1:]))
    if length < 1e-6:
        raise ValueError(f"{rig.name} has a degenerate leg")
    return length


def world_rotation(scene, rig, name, frame):
    scene.frame_set(frame)
    return (rig.matrix_world @ rig.pose.bones[name].matrix).to_quaternion()


def captured_feet(scene, source, names, first, last, intervals, fps):
    mw = source.matrix_world
    legs, _ = _legs(source)
    floor = min((mw @ source.data.bones[chain["toe"] or chain["foot"]].tail_local).z
                for chain in legs.values())
    soles = {s: _sole_points(source, chain, floor) for s, chain in legs.items()}
    samples, heights = [], {s: [] for s in "LR"}
    for frame in range(first, last + 1):
        scene.frame_set(frame)
        sample = {"hips": mw @ source.pose.bones[names["hips"]].head}
        for side in "LR":
            foot = mw @ source.pose.bones[names[f"foot.{side}"]].matrix
            sample[side] = foot.translation.copy()
            heights[side].append(min((foot @ p).z for p in soles[side]))
        samples.append(sample)
    for side, values in heights.items():
        floor = median(values[-max(1, round(.43 * fps)):])
        for i, height in enumerate(values):
            distance = min(max(a - i, i - b, 0) for a, b in intervals[side])
            values[i] = max(0, height - floor) * _smoothstep(distance / max(1, .13 * fps))
    return samples, heights


def average_rotation(rotations):
    reference = rotations[0]
    total = Vector((0.0, 0.0, 0.0, 0.0))
    for q in rotations:
        total += Vector(q) if reference.dot(q) >= 0 else -Vector(q)
    return Quaternion(tuple(total)).normalized()


def polish_body(scene, rig, names, neutral, standing, start, end, footfalls, arm_swing, lateral, fps, fit_travel):
    mw = rig.matrix_world
    bones = {role: rig.pose.bones[names[role]] for role in neutral}
    hip = bones["hips"]
    rotations, roots = [], []
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        rotations.append({role: bone.matrix_basis.to_quaternion() for role, bone in bones.items()})
        roots.append(fit_travel(mw @ hip.head))
    brake = footfalls[-1][0]
    previous_footfall = footfalls[-2][0] if len(footfalls) > 1 else start
    gait = rotations[:max(1, brake - start - round(.10 * fps))]
    center = {role: average_rotation([pose[role] for pose in gait]) for role in bones}
    final_delta = standing - roots[-1]
    forward = lateral.cross(UP)
    beginning = roots[previous_footfall - start].dot(forward)
    travel = roots[-1].dot(forward) - beginning

    def fit_position(root):
        progress = _smoothstep((root.dot(forward) - beginning) / travel) if travel > 1e-6 else 0.0
        return root + Vector((final_delta.x, final_delta.y, 0)) * progress

    positions = [fit_position(p) for p in roots]
    stop_origin = positions[brake - start]
    speed_sample = max(start, brake - 3)
    speed = (stop_origin - positions[speed_sample - start]).dot(forward) / max(1, brake - speed_sample)
    stop_distance = (standing - stop_origin).dot(forward)
    previous = {}
    for i, (pose, position) in enumerate(zip(rotations, positions)):
        frame = start + i
        scene.frame_set(frame)
        relax = _smoothstep((frame - brake) / (end - brake))
        for role, bone in bones.items():
            delta = center[role].inverted() @ pose[role]
            strength = BODY_MOTION[role] * (1 - relax)
            assign_rotation(bone, neutral[role] @ Quaternion().slerp(delta, strength))
            anim._key_rot(bone, frame, previous)
        if frame > brake:
            eased = stop_ease(stop_distance, speed, frame - brake, end - brake)
            position += forward * (stop_origin.dot(forward) + eased - position.dot(forward))
        position.z = (1 - relax) * position.z + relax * standing.z
        bpy.context.view_layer.update()
        anim._set_world_rot(rig, hip, (mw @ hip.matrix).to_quaternion(), position)
        hip.keyframe_insert("location", frame=frame, group=hip.name)
        bpy.context.view_layer.update()

        lead = max(1, round(.13 * fps))
        follow = max(1, round(.30 * fps))
        inertia = (_smoothstep((frame - brake + lead) / follow) *
                   (1 - _smoothstep((frame - brake + lead - follow) / max(1, end - brake + lead - follow))))
        add_rotation(rig, bones["chest"], lateral, 3.2 * inertia, frame, previous)
        bpy.context.view_layer.update()
        sway = shoulder_swing(frame, footfalls, fps)
        for side, sign in (("L", 1), ("R", -1)):
            bone = bones.get(f"upper_arm.{side}")
            if bone is not None:
                add_rotation(rig, bone, lateral, arm_swing * sway * sign, frame, previous)


def assign_rotation(bone, q):
    mode = bone.rotation_mode
    # Preserve the caller's rotation mode and existing animation channels.
    if mode == "QUATERNION":
        bone.rotation_quaternion = q
    elif mode == "AXIS_ANGLE":
        axis, angle = q.to_axis_angle()
        bone.rotation_axis_angle = (angle, *axis)
    else:
        bone.rotation_euler = q.to_euler(mode, bone.rotation_euler)


def add_rotation(rig, bone, axis, degrees, frame, previous):
    current = (rig.matrix_world @ bone.matrix).to_quaternion()
    anim._set_world_rot(rig, bone, Quaternion(axis, math.radians(degrees)) @ current)
    anim._key_rot(bone, frame, previous)


def stop_ease(distance, speed, elapsed, duration):
    t = elapsed / duration
    tangent = max(0, min(speed * duration, 3 * distance))
    return distance * _smoothstep(t) + tangent * t * (1 - t) ** 2


def shoulder_swing(frame, footfalls, fps):
    first, first_side = footfalls[0]
    last, last_side = footfalls[-1]
    period = max(1, footfalls[1][0] - first) if len(footfalls) > 1 else max(1, round(.55 * fps))
    tail = max(1, last - footfalls[-2][0]) if len(footfalls) > 1 else period
    knots = [(first - period, "R" if first_side == "L" else "L"), *footfalls,
             (last + tail, "R" if last_side == "L" else "L")]
    for (a, sa), (b, sb) in zip(knots, knots[1:]):
        if a <= frame <= b and a < b:
            phase = (1 - math.cos(math.pi * (frame - a) / (b - a))) / 2
            beginning, ending = (1 if sa == "L" else -1), (1 if sb == "L" else -1)
            envelope = (1 - .82 * _smoothstep((frame - last + tail) / tail))
            envelope *= 1 - _smoothstep((frame - last) / max(1, .33 * fps))
            return ((1 - phase) * beginning + phase * ending) * envelope
    return 0.0


def shift_final_footfall(positions, contacts, goal):
    offset = goal - positions[-1]
    offset.z = 0
    if len(contacts) == 1 and contacts[0][0] == 0:
        return
    before = contacts[-2][1] if len(contacts) > 1 else -1
    plant = contacts[-1][0]
    for i in range(before + 1, len(positions)):
        positions[i] += offset * _smoothstep((i - before) / (plant - before))


def quiet_foot(rotations, flat, settled, fps):
    local_up = flat.inverted() @ UP
    last = rotations[-1]
    final = (last @ local_up).rotation_difference(UP) @ last
    eased = []
    for i, q in enumerate(rotations):
        before, after = rotations[max(0, i - 1)], rotations[min(len(rotations) - 1, i + 1)]
        filtered = q.slerp(before.slerp(after, .5), .24)
        eased.append(filtered.slerp(final, _smoothstep((i - settled - .17 * fps) / max(1, .26 * fps))))
    return eased


def planted_shifts(positions, rotations, sole, intervals):
    corrections = [Vector() for _ in positions]
    for begin, end in intervals:
        anchor = stance_anchor(begin, end, len(positions))
        for step, edge in ((1, end), (-1, begin)):
            location = positions[anchor]
            for i in range(anchor + step, edge + step, step):
                before = rotations[i - step]
                pivot = min(sole, key=(before.inverted() @ UP).dot)
                location = location + before @ pivot - rotations[i] @ pivot
                corrections[i] = location - positions[i]
                corrections[i].z = 0
    blend_swing_corrections(corrections, intervals)
    return corrections


def orient_hands(scene, rig, names, start, end):
    hands = HandRig(rig)
    mw = rig.matrix_world
    previous = {}
    poses, bases = {}, {}
    along = Vector((0, 1, 0))
    for side in "LR":
        palm = hands.palm_local(side, names.get(f"hand.{side}"))
        if palm is None or f"forearm.{side}" not in names:
            continue
        palm = (palm - along * palm.dot(along)).normalized()
        bases[side] = Matrix((along, palm, along.cross(palm))).transposed()
        poses.update(hands.rotations(side, "relaxed", .7))
    if not bases:
        return
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        left = (mw @ rig.pose.bones[names["thigh.L"]].head -
                mw @ rig.pose.bones[names["thigh.R"]].head).normalized()
        for side, base in bases.items():
            wrist = rig.pose.bones[names[f"hand.{side}"]]
            elbow = rig.pose.bones[names[f"forearm.{side}"]]
            direction = (mw @ wrist.head - mw @ elbow.head).normalized()
            medial = -left if side == "L" else left
            palm = (medial - direction * medial.dot(direction)).normalized()
            world = Matrix((direction, palm, direction.cross(palm))).transposed()
            anim._set_world_rot(rig, wrist, (world @ base.transposed()).to_quaternion())
            anim._key_rot(wrist, frame, previous)
        if frame in (start, end):
            for name, pose in poses.items():
                bone = rig.pose.bones[name]
                assign_rotation(bone, pose)
                anim._key_rot(bone, frame, previous)
