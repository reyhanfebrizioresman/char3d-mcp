"""Grounded single-character button press with fingertip contact."""

import math
from contextlib import contextmanager

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import anim, command
from .fingers import HandRig
from .footlock import _smoothstep, foot_lock
from .gaze import head_frame
from .performance import UP, animation_edit, bone_map, floor_of, heading, number, point, start_at
from .seating import _chain, _flat_hand
from .talk import _rig_of
from .util import obj_or_raise


PRESS_HAND = {"thumb": (25, 19, 12), "index": (2, 1, 1), "middle": (10, 19, 12),
              "ring": (14, 24, 15), "pinky": (18, 27, 19), "spread": 0}
LEGS = tuple(f"{part}.{side}" for side in "LR" for part in ("thigh", "shin", "foot"))


@command("press_button")
def press_button(character, button, start_frame=None, hand="left", target=None, travel=.010,
                 hold_seconds=.33, tip_mesh=None, floor=None):
    """Press a vertical button cap from a standing pose, preserving both supports."""
    if hand not in ("left", "right"):
        raise ValueError("hand must be left or right")
    side = hand[0].upper()
    scene = bpy.context.scene
    rig, cap = _rig_of(character), obj_or_raise(button)
    if cap.type != "MESH":
        raise ValueError("button must name the movable mesh cap")
    names = bone_map(rig, ("hips", "chest", "head", *LEGS,
                          *(f"{role}.{side}" for role in ("upper_arm", "forearm", "hand"))))
    skin = obj_or_raise(tip_mesh) if tip_mesh is not None else None
    if skin is not None and skin.type != "MESH":
        raise ValueError("tip_mesh must be a skinned mesh")
    anchor = point(target, 3, "target") if target is not None else None
    travel = number(travel, "travel", 0, .1)
    hold = number(hold_seconds, "hold_seconds", 0, 5)
    floor = floor_of(rig, floor)
    start = start_at(scene, rig, start_frame)
    fps = scene.render.fps / scene.render.fps_base

    def span(seconds):
        return max(1, round(seconds * fps))

    reach_lag = span(1 / 6)
    contact = start + reach_lag + span(2 / 3)
    pressed = contact + span(.2)
    release = pressed + round(hold * fps)
    free = release + span(.2)
    finish = free + span(.8)
    end = finish + span(.45)
    with animation_edit(scene, start, rig, cap), unmask_skin(skin):
        scene.frame_set(start)
        forward, lateral = heading(rig)
        outward = lateral if side == "L" else -lateral
        mw = rig.matrix_world
        cap_origin = cap.matrix_world.translation.copy()
        if anchor is None:
            corners = [cap.matrix_world @ Vector(c) for c in cap.bound_box]
            anchor = sum(corners, Vector()) / 8
            anchor.z = max(c.z for c in corners)
        anchor += UP * .0006

        wrist_names = [names[f"{role}.{side}"] for role in ("upper_arm", "forearm", "hand")]
        shoulder, elbow, wrist = [rig.pose.bones[name] for name in wrist_names]
        reach = (mw @ elbow.head - mw @ shoulder.head).length + (mw @ wrist.head - mw @ elbow.head).length
        if ((mw @ shoulder.head) - anchor).length > reach + wrist.length + .20:
            raise ValueError("button is beyond this character's standing reach")
        hands = HandRig(rig)
        index = hands.fingers.get(side, {}).get("index", [])
        finger = index[-1] if index else None
        pad = fingertip_vertices(rig, skin, finger) if skin is not None else None
        palm = hands.palm_local(side, wrist.name)
        posed_fingers = hands.rotations(side, PRESS_HAND)

        foot_report = shift_weight(scene, rig, names, floor, forward, outward,
                                   start, contact, pressed, free, finish, end)
        scene.frame_set(start)
        head, chest = [rig.pose.bones[names[key]] for key in ("head", "chest")]
        collar = rig.pose.bones.get(names.get(f"shoulder.{side}", ""))
        animated = [head, chest, shoulder, elbow, wrist, *(rig.pose.bones[name] for name in posed_fingers)]
        if collar is not None:
            animated.append(collar)
        bases = {b.name: b.matrix_basis.copy() for b in animated}
        previous, errors = {}, []
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            for bone in animated:
                bone.matrix_basis = bases[bone.name]
            bpy.context.view_layer.update()
            withdrawal = 1 - _smoothstep((frame - free) / (finish - free))
            weight = (_smoothstep((frame - start - reach_lag) / (contact - start - reach_lag))
                      if frame <= contact else withdrawal)
            look = _smoothstep((frame - start) / span(.375)) if frame <= contact else withdrawal
            lead = (_smoothstep((frame - start) / max(1, contact - start - 2))
                    if frame <= contact else 1 - _smoothstep((frame - free - 2) / (finish - free)))
            depression = (_smoothstep((frame - contact) / (pressed - contact))
                          if frame <= pressed else 1 - _smoothstep((frame - release) / (free - release)))
            load = _smoothstep((frame - contact + 1) / (pressed - contact + 2))
            load *= 1 - _smoothstep((frame - release - 2) / (free - release + 2))
            breathe = .65 * math.sin(2 * math.pi * (frame - start) / span(2.875))
            breathe *= _smoothstep((frame - start) / span(.29))
            sign = 1 if side == "L" else -1
            pitch = Quaternion(lateral, math.radians(8 * lead + 1.5 * load + breathe))
            yaw = Quaternion(UP, math.radians((3 * lead + 1.2 * load) * sign))
            anim._set_world_rot(rig, chest, yaw @ pitch @ (mw @ chest.matrix).to_quaternion())
            bpy.context.view_layer.update()
            if collar is not None:
                turn = Quaternion(UP, math.radians((-3.8 * lead - 2.2 * load) * sign))
                lift = Quaternion(forward, math.radians((1.3 * lead - 1.1 * load) * sign))
                anim._set_world_rot(rig, collar, turn @ lift @ (mw @ collar.matrix).to_quaternion())
                bpy.context.view_layer.update()
            center, direction = head_frame(rig)
            current = (mw @ head.matrix).to_quaternion()
            delta = (direction @ Vector((0, -1, 0))).rotation_difference((anchor - center).normalized())
            anim._set_world_rot(rig, head, current.slerp(delta @ current, .60 * look))
            origin = mw @ wrist.head
            rotation = (mw @ wrist.matrix).to_quaternion()
            aim = anchor - (mw @ shoulder.head)
            aim.z = 0
            aim = aim.normalized() if aim.length > 1e-6 else forward
            if palm is not None:
                flat = _flat_hand(palm, aim)
            else:
                # Basic rigs still have a hand bone. Point its tip at the cap,
                # while preserving the starting wrist twist without finger axes.
                hand_axis = rotation @ Vector((0, 1, 0))
                flat = hand_axis.rotation_difference(aim) @ rotation
            desired = Quaternion(aim.cross(UP), math.radians(-13 + 4 * load)) @ flat
            rotation = rotation.slerp(desired, weight)
            for name, pose in posed_fingers.items():
                b = rig.pose.bones[name]
                loc, rest, scale = bases[name].decompose()
                b.matrix_basis = Matrix.LocRotScale(loc, rest.slerp(pose, weight), scale)
            anim._set_world_rot(rig, wrist, rotation)
            bpy.context.view_layer.update()
            offset = contact_point(rig, wrist, finger, skin, pad) - (mw @ wrist.head)
            depressed = anchor - UP * (travel * depression)
            arc = math.sin(math.pi * weight)
            wrist_target = origin.lerp(depressed - offset, weight) + (UP * .071 + outward * .025) * arc
            pole = (outward * (.69 - .22 * load) - UP * .9 - forward * (.27 - .11 * load)).normalized()
            if weight > 0:
                _chain(rig, wrist_names, wrist_target, pole, rotation)
            if contact <= frame <= free:
                for _ in range(2):
                    error = depressed - contact_point(rig, wrist, finger, skin, pad)
                    if error.length < .0002:
                        break
                    wrist_target += error
                    _chain(rig, wrist_names, wrist_target, pole, rotation)
                errors.append((depressed - contact_point(rig, wrist, finger, skin, pad)).length)
            for bone in animated:
                anim._key_rot(bone, frame, previous)
            cap_pose = cap.matrix_world.copy()
            cap_pose.translation = cap_origin - UP * (travel * depression)
            cap.matrix_world = cap_pose
            cap.keyframe_insert("location", frame=frame, group=cap.name)
        maximum = max(errors)
        if maximum > .02:
            raise ValueError(f"{rig.name} cannot reach {cap.name} in this stance (error {maximum:.3f} m)")
        anim._extend_range(end)
    from .collision import record_contact
    record_contact(rig, side, contact, free, "interaction:press_button", other=cap.name)
    return {"armature": rig.name, "button": cap.name, "hand": hand,
            "frames": {"start": start, "reach": start + reach_lag, "contact": contact,
                       "pressed": pressed, "released": free, "end": end},
            "next_start_frame": end + 1, "contact_site": "skin" if pad else "index" if finger else "hand",
            "contact_error_m": round(maximum, 6), "foot_ik_error_m": foot_report["max_ik_error_m"],
            "travel_m": travel}


def shift_weight(scene, rig, names, floor, forward, outward, start, contact, pressed, free, finish, end):
    scene.frame_set(start)
    mw = rig.matrix_world
    hips = rig.pose.bones[names["hips"]]
    world = mw @ hips.matrix
    targets = {}
    for side in "LR":
        foot = mw @ rig.pose.bones[names[f"foot.{side}"]].matrix
        targets[side] = [(foot.translation.copy(), foot.to_quaternion())] * (end - start + 1)
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        enter = _smoothstep((frame - start) / (contact - start))
        leave = 1 - _smoothstep((frame - free) / (finish - free))
        load = _smoothstep((frame - contact) / (pressed - contact)) * leave * enter
        stance = (outward * .011 + forward * .006 - UP * .003) * enter * leave
        position = world.translation + stance - UP * (.0025 * load)
        anim._set_world_rot(rig, hips, world.to_quaternion(), position)
        hips.keyframe_insert("location", frame=frame, group=hips.name)
    return foot_lock(rig, start, end, floor=floor, terrain=False, adjust_hips=False,
                     contacts={s: [[start, end]] for s in "LR"}, foot_targets=targets)


@contextmanager
def unmask_skin(mesh):
    masks = [m for m in mesh.modifiers if m.type == "MASK" and m.show_viewport] if mesh is not None else []
    try:
        for modifier in masks:
            modifier.show_viewport = False
        if masks:
            bpy.context.view_layer.update()
        yield
    finally:
        for modifier in masks:
            modifier.show_viewport = True
        if masks:
            bpy.context.view_layer.update()


def fingertip_vertices(rig, skin, finger):
    group = skin.vertex_groups.get(finger) if finger else None
    if group is None:
        raise ValueError("tip_mesh needs skin weights for the last index-finger bone")
    bone = rig.data.bones[finger]
    world = rig.matrix_world.to_3x3() @ (bone.tail_local - bone.head_local)
    direction = (skin.matrix_world.to_3x3().transposed() @ world).normalized()
    ranked = [(vertex.co.dot(direction), vertex.index) for vertex in skin.data.vertices
              if any(w.group == group.index and w.weight > .47 for w in vertex.groups)]
    if len(ranked) < 4:
        raise ValueError("tip_mesh needs at least four weighted fingertip vertices")
    return [index for _, index in sorted(ranked)[-12:]]


def contact_point(rig, wrist, finger, skin, pad):
    if pad:
        evaluated = skin.evaluated_get(bpy.context.evaluated_depsgraph_get())
        if len(evaluated.data.vertices) != len(skin.data.vertices):
            raise ValueError("tip_mesh must preserve vertex topology")
        points = sorted((evaluated.matrix_world @ evaluated.data.vertices[i].co for i in pad),
                        key=lambda p: p.z)
        return sum(points[:3], Vector()) / 3
    bone = rig.pose.bones[finger] if finger else wrist
    return rig.matrix_world @ bone.tail
