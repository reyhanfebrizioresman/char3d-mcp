"""Shared helpers for a character's grounded approach and standing actions."""

import math
from contextlib import contextmanager
from statistics import median

import bpy
from mathutils import Vector

from . import anim
from .footlock import _smoothstep
from .gaze import head_frame


UP = Vector((0, 0, 1))


def number(value, label, low=None, high=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f"{label} is outside the supported range")
    return float(value)


def point(value, size, label):
    if not isinstance(value, (tuple, list)) or len(value) != size:
        raise ValueError(f"{label} must contain {size} coordinates")
    return Vector(tuple(number(axis, label) for axis in value))


def start_at(scene, rig, start_frame):
    if start_frame is None:
        action = rig.animation_data.action if rig.animation_data else None
        return max(scene.frame_start, math.floor(action.frame_range[1]) + 1) if action else scene.frame_start
    if type(start_frame) is not int or start_frame < scene.frame_start:
        raise ValueError("start_frame must be an integer at or after scene start")
    return start_frame


def bone_map(rig, roles):
    names = anim.semantic_map(rig)
    missing = [role for role in roles if role not in names]
    if missing:
        raise ValueError(f"{rig.name} needs these humanoid bones: {', '.join(missing)}")
    return names


def floor_of(rig, floor):
    if floor is not None:
        return number(floor, "floor")
    local = rig.get("c3d_vrm_ground_local")
    return (rig.matrix_world @ Vector(local)).z if local is not None else rig.matrix_world.translation.z


def heading(rig):
    _, orientation = head_frame(rig, "hips")
    forward = orientation @ Vector((0, -1, 0))
    forward.z = 0
    if forward.length < 1e-6:
        raise ValueError(f"{rig.name} must be upright")
    forward.normalize()
    return forward, UP.cross(forward)


def ground_shoe(position, rotation, sole, height):
    return Vector((position.x, position.y, height - sole_height(sole, rotation))), rotation


def sole_height(sole, rotation):
    vertical = rotation.inverted() @ UP
    return min(p.dot(vertical) for p in sole)


def mesh_points(mesh):
    evaluated = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return [evaluated.matrix_world @ v.co for v in evaluated.data.vertices]


def shoe_samples(mesh, ankles, lateral):
    """Track a fixed vertex partition so crossover poses cannot swap shoes."""
    points = mesh_points(mesh)
    center = (ankles["L"].translation + ankles["R"].translation) / 2
    groups = {"L": [], "R": []}
    for index, p in enumerate(points):
        side = "L" if (p - center).dot(lateral) > 0 else "R"
        groups[side].append(index)
    if not all(groups.values()):
        raise ValueError("sole_mesh must contain both shoes")
    soles = {}
    for side, group in groups.items():
        low = min(points[i].z for i in group)
        inverse = ankles[side].inverted()
        soles[side] = [inverse @ points[i] for i in group if points[i].z < low + .055]
    return soles, groups


def refine_shoes(scene, mesh, start, targets, soles, groups, contacts):
    """Fit the evaluated outsole vertically and subtract residual planted slip."""
    evaluated = []
    for index in range(len(targets["L"])):
        scene.frame_set(start + index)
        points = mesh_points(mesh)
        if evaluated and len(points) != len(evaluated[0]):
            raise ValueError("sole_mesh must retain its vertex topology while walking")
        evaluated.append(points)
    for side, indices in groups.items():
        lows = [min(points[i].z for i in indices) for points in evaluated]
        corrections = [Vector() for _ in evaluated]
        intervals = contacts[side]
        for begin, end in intervals:
            accumulated = {begin: Vector()}
            for f in range(begin + 1, end + 1):
                old, new = evaluated[f - 1], evaluated[f]
                planted = [i for i in indices if old[i].z - lows[f - 1] < .002 and new[i].z - lows[f] < .002]
                slip = Vector((median(new[i].x - old[i].x for i in planted),
                               median(new[i].y - old[i].y for i in planted), 0)) if planted else Vector()
                accumulated[f] = accumulated[f - 1] + slip
            anchor = stance_anchor(begin, end, len(evaluated))
            for f in range(begin, end + 1):
                delta = accumulated[anchor] - accumulated[f]
                corrections[f] = delta if delta.length <= .028 else delta.normalized() * .028
        blend_swing_corrections(corrections, intervals)
        for f, (position, rotation) in enumerate(targets[side]):
            height_error = position.z + sole_height(soles[side], rotation) - lows[f]
            targets[side][f] = (position + corrections[f] + UP * height_error, rotation)


def stance_anchor(begin, end, count):
    if begin == 0:
        return 0
    if end == count - 1:
        return end
    return (begin + end) // 2


def blend_swing_corrections(corrections, intervals):
    edges = [(-1, intervals[0][0]), *[(b, c) for (_, b), (c, _) in zip(intervals, intervals[1:])]]
    for a, b in edges:
        previous = corrections[a] if a >= 0 else Vector()
        for i in range(a + 1, b):
            corrections[i] = previous.lerp(corrections[b], _smoothstep((i - a) / (b - a)))


@contextmanager
def animation_edit(scene, start, *objects):
    """Keep prior actions intact if evaluation or calibration fails mid-bake."""
    from .interaction import _history, _restore_history

    frame, end = scene.frame_current, scene.frame_end
    saved = []
    try:
        for obj in objects:
            had_animation = obj.animation_data is not None
            ad = obj.animation_data_create()
            action = ad.action
            slot = ad.action_slot.identifier if action and ad.action_slot else None
            bones = {b.name: (b.rotation_mode, b.matrix_basis.copy()) for b in obj.pose.bones} if obj.pose else {}
            saved.append((obj, action, slot, obj.matrix_basis.copy(), bones, had_animation))
            if action:
                ad.action = action.copy()
                if slot:
                    ad.action_slot = next(s for s in ad.action.slots if s.identifier == slot)
        history = _history(objects, start)
        yield
        _restore_history(history)
    except BaseException:
        scene.frame_end = end
        for obj, action, slot, basis, bones, had_animation in reversed(saved):
            ad, working = obj.animation_data, obj.animation_data.action
            ad.action = action
            if slot:
                ad.action_slot = next(s for s in action.slots if s.identifier == slot)
            obj.matrix_basis = basis
            for name, (mode, matrix) in bones.items():
                obj.pose.bones[name].rotation_mode = mode
                obj.pose.bones[name].matrix_basis = matrix
            if working and working != action and not working.users:
                bpy.data.actions.remove(working)
            if not had_animation:
                obj.animation_data_clear()
        raise
    else:
        for obj, action, _, _, _, _ in saved:
            if action and not action.users:
                name = action.name
                bpy.data.actions.remove(action)
                obj.animation_data.action.name = name
    finally:
        scene.frame_set(frame)
