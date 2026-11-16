"""Live palm attachments in Blender; temporary sampled world transforms for glTF."""
from contextlib import contextmanager
import json
import time

import bpy
from mathutils import Matrix, Vector

from . import command, anim
from .fingers import HandRig, set_hand_pose
from .talk import _rig_of, _fcurves
from .util import obj_or_raise, vec


def _prop(name):
    obj = obj_or_raise(name)
    while obj.parent and obj.parent.get("c3d_prop_kind"):
        obj = obj.parent
    return obj


def _palm(rig, side, hands=None):
    """Palm center and axes in hand-bone space, inferred from proximal finger heads."""
    hands = hands or HandRig(rig)
    bone = anim.semantic_map(rig).get(f"hand.{side}")
    if bone is None:
        raise ValueError(f"{rig.name} has no recognisable hand on side {side}")
    hand = rig.data.bones[bone]
    inv = hand.matrix_local.inverted()
    ch = hands.fingers.get(side, {})
    knuckles = [rig.data.bones[chain[0]].head_local for f, chain in ch.items() if f != "thumb"]
    center = (sum(knuckles, Vector())/len(knuckles)+hand.head_local)/2 if knuckles else hand.head_local.lerp(hand.tail_local, 0.55)
    center = inv @ center
    normal = hands.palm_local(side, bone) or Vector((0, 0, 1))
    center += normal*0.008
    along = (inv.to_3x3() @ (rig.data.bones[ch["index"][0]].head_local -
                            rig.data.bones[ch["pinky"][0]].head_local)).normalized() if (
        "index" in ch and "pinky" in ch) else Vector((1 if side == "R" else -1, 0, 0))
    # Prop Z points toward the thumb (upright in a neutral power grip); X exits the palm.
    x = normal.normalized()
    z = (along-x*along.dot(x)).normalized()
    y = z.cross(x).normalized()
    frame = Matrix((x, y, z)).transposed().to_4x4()
    frame.translation = center
    return bone, frame


def _constant(obj):
    if obj.animation_data and obj.animation_data.action:
        for fc in _fcurves(obj.animation_data.action):
            for k in fc.keyframe_points:
                k.interpolation = "CONSTANT"


def _key_object(obj, f):
    obj.rotation_mode = "QUATERNION"
    for path in ("location", "rotation_quaternion", "scale"):
        obj.keyframe_insert(path, frame=f)


def _constraint(obj):
    return next((c for c in obj.constraints if c.name.startswith("char3d_hold")), None)


@command("hold_prop")
def hold_prop(character, prop, hand="right", start_frame=None, end_frame=None, grip="auto"):
    started = time.perf_counter()
    if hand not in ("left", "right"):
        raise ValueError("hand must be left or right")
    if grip not in ("auto", "fist", "cup", "relaxed", "open"):
        raise ValueError("grip must be auto, fist, cup, relaxed or open")
    rig, obj = _rig_of(character), _prop(prop)
    if obj == rig or rig in obj.children_recursive or obj in rig.children_recursive:
        raise ValueError("prop must be separate from the character hierarchy")
    sc = bpy.context.scene
    start = int(start_frame) if start_frame is not None else sc.frame_current
    end = int(end_frame) if end_frame is not None else None
    if start < sc.frame_start or (end is not None and end < start):
        raise ValueError("invalid hold frame range")
    if _constraint(obj):
        raise ValueError("prop already has an attachment; use a separate prop for another hold")
    side = "R" if hand == "right" else "L"
    hands = HandRig(rig)
    bone, palm = _palm(rig, side, hands)
    sc.frame_set(start)
    original = obj.matrix_world.copy()
    helper = bpy.data.objects.new(f"{obj.name}_palm", None)
    bpy.context.scene.collection.objects.link(helper)
    helper["c3d_hold_helper"] = True
    if obj.get("c3d_role") == "environment":
        helper["c3d_role"] = "environment"
    helper.parent, helper.parent_type, helper.parent_bone = rig, "BONE", bone
    # Blender bone parenting uses the bone tail; _palm uses its head.
    parent_scale = (rig.matrix_world @ rig.pose.bones[bone].matrix).to_scale()
    prop_scale = original.to_scale()
    local_scale = Vector(tuple(prop_scale[i]/parent_scale[i] for i in range(3)))
    helper.matrix_basis = (Matrix.Translation((0, -rig.data.bones[bone].length, 0)) @ palm @
                           Matrix.Diagonal((*local_scale, 1)))
    helper.empty_display_size = 0.015
    con = obj.constraints.new("COPY_TRANSFORMS")
    con.name = "char3d_hold"
    con.target = helper
    # Preserve placement before pickup. The on/off channel is a step, without drift.
    con.influence = 0
    con.keyframe_insert("influence", frame=start-1)
    obj.matrix_world = original
    _key_object(obj, start-1)
    con.influence = 1
    con.keyframe_insert("influence", frame=start)
    _key_object(obj, start)
    obj["c3d_hold_character"] = rig.name
    obj["c3d_hold_hand"] = hand
    obj["c3d_hold_start"] = start
    obj["c3d_hold_palm"] = json.dumps(list(palm.translation))
    kind = obj.get("c3d_prop_kind", "")
    cupped = grip == "cup" or (grip == "auto" and kind == "cup")
    shape = ("beat" if kind in ("phone", "book") else "fist") if grip == "auto" else (
        "fist" if grip == "cup" else grip)
    strength = 0.78 if cupped else 1.0
    if hands.fingers.get(side):
        finish = end if end is not None else max(start, sc.frame_end)
        finger_names = [n for chain in hands.fingers[side].values() for n in chain]
        paths = {f'pose.bones["{n}"].{p}' for n in finger_names
                 for p in ("rotation_euler", "rotation_quaternion", "rotation_axis_angle")}
        action = rig.animation_data.action if rig.animation_data else None
        for fc in _fcurves(action):
            if fc.data_path in paths:
                for k in reversed(list(fc.keyframe_points)):
                    if start <= k.co.x <= finish:
                        fc.keyframe_points.remove(k, fast=True)
                fc.update()
        set_hand_pose(rig.name, shape=shape, strength=strength, side=hand, frame=start, keyframe=True)
        if finish > start:
            set_hand_pose(rig.name, shape=shape, strength=strength, side=hand, frame=finish, keyframe=True)
    if end is not None:
        con.influence = 1
        con.keyframe_insert("influence", frame=end)
        release_prop(rig.name, obj.name, frame=end+1)
    _constant(obj)
    sc.frame_set(start)
    bpy.context.view_layer.update()
    return {"character": rig.name, "prop": obj.name, "hand": hand, "bone": bone,
            "frames": [start, end], "grip": shape, "grip_strength": strength,
            "finger_bones": sum(map(len, hands.fingers.get(side, {}).values())),
            "palm_local": vec(palm.translation), "attachment": "live palm constraint",
            "gltf": "world transforms sampled at export, including release; include prop or character",
            "bake_seconds": round(time.perf_counter()-started, 3)}


@command("release_prop")
def release_prop(character, prop, frame, place_at=None):
    rig, obj = _rig_of(character), _prop(prop)
    con = _constraint(obj)
    if con is None or obj.get("c3d_hold_character") != rig.name:
        raise ValueError("prop is not held by this character")
    f = int(frame)
    if f < obj["c3d_hold_start"]:
        raise ValueError("release frame precedes pickup")
    point = None
    if place_at is not None:
        from .environment import _vector
        point = _vector(place_at, "place_at")
    sc = bpy.context.scene
    # Capture exactly the attachment at release, even after later arm animation.
    sc.frame_set(f)
    bpy.context.view_layer.update()
    world = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
    if point is not None:
        world.translation = point
    con.influence = 1
    con.keyframe_insert("influence", frame=f-1)
    con.influence = 0
    con.keyframe_insert("influence", frame=f)
    bpy.context.view_layer.update()
    obj.matrix_world = world
    _key_object(obj, f)
    obj["c3d_hold_release"] = f
    _constant(obj)
    sc.frame_set(f)
    bpy.context.view_layer.update()
    return {"character": rig.name, "prop": obj.name, "frame": f, "location": vec(world.translation),
            "physics": False}


@contextmanager
def export_attachments(objects):
    """Temporarily sample constraints into world keys, leaving live scene/actions intact."""
    sc = bpy.context.scene
    frame = sc.frame_current
    saved = []
    try:
        for obj in objects:
            con = _constraint(obj)
            if con is None:
                continue
            samples = []
            for f in range(sc.frame_start, sc.frame_end+1):
                sc.frame_set(f)
                samples.append(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy())
            action = obj.animation_data.action if obj.animation_data else None
            slot = obj.animation_data.action_slot if obj.animation_data else None
            saved.append((obj, action, slot, obj.matrix_basis.copy(), con, con.mute))
            obj.animation_data_create()
            obj.animation_data.action = bpy.data.actions.new(obj.name+"_export_hold")
            con.mute = True
            previous = None
            for f, m in zip(range(sc.frame_start, sc.frame_end+1), samples):
                obj.matrix_world = m
                obj.rotation_mode = "QUATERNION"
                if previous is not None and previous.dot(obj.rotation_quaternion) < 0:
                    obj.rotation_quaternion.negate()
                previous = obj.rotation_quaternion.copy()
                _key_object(obj, f)
            for fc in _fcurves(obj.animation_data.action):
                for k in fc.keyframe_points:
                    k.interpolation = "LINEAR"
        sc.frame_set(frame)
        yield
    finally:
        for obj, action, slot, basis, con, muted in saved:
            temp = obj.animation_data.action
            obj.animation_data.action = action
            if slot is not None:
                obj.animation_data.action_slot = slot
            con.mute = muted
            obj.matrix_basis = basis
            if temp and temp.users == 0:
                bpy.data.actions.remove(temp)
        sc.frame_set(frame)
