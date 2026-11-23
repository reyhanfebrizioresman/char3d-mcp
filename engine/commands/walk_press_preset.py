"""Preview an approach and button press without editing the working scene."""

import math
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import bpy
from mathutils import Quaternion, Vector

from engine import context
from . import anim, command
from .button_press import fingertip_vertices, press_button
from .face import _basemesh
from .fingers import HandRig
from .navigation import Planner, validate_options
from .performance import UP, bone_map, heading
from .sfx import auto_sfx
from .talk import _rig_of
from .terrain import GroundQuery
from .util import obj_or_raise, vec
from .video import render_video
from .walk import _curves, turn_to, walk_path
from .walk_approach import leg_length, walk_approach


CAPTURE = "mocap/16_34.bvh"
CAPTURE_CONTACTS = {"L": ((14, 34), (48, 86)), "R": ((3, 19), (31, 54), (64, 86))}


@contextmanager
def _preview_scene(rig, button, token):
    window = bpy.context.window
    original = window.scene
    active = bpy.context.view_layer.objects.active
    existing = set(bpy.data.user_map())
    staged = {obj: obj.matrix_basis.copy() for obj in original.objects if obj.animation_data}
    tag = "_c3d_preview_" + token
    try:
        rig[tag], button[tag] = "rig", "button"
        bpy.ops.scene.new(type="FULL_COPY")
        scene = window.scene
        copied = {obj[tag]: obj for obj in scene.objects if tag in obj}
        if scene == original or set(copied) != {"rig", "button"}:
            raise RuntimeError("Could not copy the scene for preview")
        scene.name = "Walk and press preview"
        for obj in copied.values():
            del obj[tag]
        yield scene, copied["rig"], copied["button"]
    finally:
        for obj in (rig, button):
            if tag in obj:
                del obj[tag]
        window.scene = original
        bpy.context.view_layer.objects.active = active
        created = set(bpy.data.user_map()) - existing
        if created:
            bpy.data.batch_remove(ids=created)
        # A scene switch can re-evaluate the active keys over a manually staged
        # transform. Keep the working scene at the pose it had on entry.
        for obj, basis in staged.items():
            if obj.matrix_basis != basis:
                obj.matrix_basis = basis
        bpy.context.view_layer.update()


def _cap_top(cap):
    evaluated = cap.evaluated_get(bpy.context.evaluated_depsgraph_get())
    corners = [evaluated.matrix_world @ Vector(c) for c in evaluated.bound_box]
    center = sum(corners, Vector()) / len(corners)
    center.z = max(p.z for p in corners)
    return center


def _stance(rig, cap, target, hand, ground):
    names = bone_map(rig, ("hips", "head", *(f"{role}.{s}" for s in "LR"
                     for role in ("thigh", "shin", "foot", "upper_arm", "forearm", "hand"))))
    mw = rig.matrix_world
    bones = rig.pose.bones
    hips = mw @ bones[names["hips"]].head
    height = (mw @ bones[names["head"]].tail).z - mw.translation.z
    facing, left = heading(rig)
    direction = target - hips
    direction.z = 0
    if hand == "auto":
        hand = "left" if direction.dot(left) >= 0 else "right"
    side = hand[0].upper()
    forward = direction.normalized() if direction.length > .001 else facing
    arm = [bones[names[f"{role}.{side}"]] for role in ("upper_arm", "forearm", "hand")]
    shoulder, elbow, wrist = (mw @ bone.head for bone in arm)
    reach = (elbow - shoulder).length + (wrist - elbow).length + (mw @ arm[-1].tail - wrist).length
    if abs(target.z - shoulder.z) >= reach + .065 and not ground.objects:
        raise ValueError("Tinggi tombol di luar jangkauan karakter. Pindahkan tombol mendekati tinggi tangan.")
    offset = shoulder - hips
    side_offset = offset.dot(left)
    forward_offset = offset.dot(facing)
    distance = min(.29 * height, .86 * math.sqrt(max(.023, reach ** 2 - (target.z - shoulder.z) ** 2)))
    origin = Vector((*hips.xy, 0))
    center = Vector((*target.xy, 0))
    planner = Planner(rig, [origin, center], ground, validate_options("auto", [cap.name]), 1)
    start_floor = ground.sample(*origin.xy)[0]
    for angle in (0, 30, -30, 60, -60, 90, -90, 120, -120, 150, -150, 180):
        approach = Quaternion(UP, math.radians(angle)) @ forward
        candidate = center - approach * distance - UP.cross(approach) * (side_offset * .45)
        if angle == 0 and direction.length < distance:
            candidate = origin
        route = planner.plan([origin, candidate], _curves)
        landing = route[-1]
        aim = center - landing
        aim = aim.normalized() if aim.length > .001 else forward
        shoulder_at_landing = landing + aim * forward_offset + UP.cross(aim) * side_offset
        shoulder_at_landing.z = shoulder.z + ground.sample(*landing.xy)[0] - start_floor
        if (target - shoulder_at_landing).length <= reach + .065:
            destination = Vector((*landing.xy, hips.z))
            return hips, destination, height, approach, hand, route
    raise ValueError("Tidak ada titik berdiri yang aman dan cukup dekat untuk menekan tombol.")


def _camera(scene, name, focus, offset, scale, frame):
    data = bpy.data.cameras.new(name)
    data.type = "ORTHO"
    data.ortho_scale = scale
    camera = bpy.data.objects.new(name, data)
    scene.collection.objects.link(camera)
    camera.location = focus + offset
    camera.rotation_euler = (-offset).to_track_quat("-Z", "Y").to_euler()
    scene.timeline_markers.new(name, frame=frame).camera = camera
    return camera


def _preview_cameras(scene, start, destination, target, height, forward, cut):
    travel = destination - start
    travel.z = 0
    along = travel.length
    course = travel.normalized() if along > .055 else forward
    side = -UP.cross(course)
    focus = (start + target) / 2
    focus.z = start.z + height * .06
    offset = max(3, height * 2.6, along * 1.5)
    width = max(height * 2.25, (target - start).xy.length + height * .9)
    main = _camera(scene, "Approach", focus, offset * side + course * (offset * .23) + UP * (height * .23), width, 1)
    focus = (destination + target) / 2 + UP * (height * .14)
    close_width = max(height * 1.15, (target - destination).xy.length + height * .7)
    _camera(scene, "Button contact", focus, -UP.cross(forward) * 3 + forward * .7 + UP * .55, close_width, cut)
    scene.camera = main


def _capture_approach(actor, start, target, route, facing, fps):
    """Use the local annotated take for a clear route that fits its stride."""
    if not Path(context.resolve(CAPTURE, "imports")).is_file():
        return None
    leg = leg_length(actor, anim.semantic_map(actor))
    if len(route) != 2:
        return None
    travel = route[-1] - route[0]
    aim = Vector((*target.xy, 0)) - route[-1]
    direction = travel.normalized()
    if (not 1.7 * leg <= travel.length <= 3.25 * leg or facing.dot(direction) < .92
            or aim.normalized().dot(direction) < .92):
        return None
    shoes = next((o.name for o in actor.children_recursive if o.type == "MESH"
                  and "shoe" in o.name.lower()), None)

    def sample(frame):
        return round((frame - 1) * fps / 30) + 1

    contacts = {s: [[sample(a), sample(b)] for a, b in pairs] for s, pairs in CAPTURE_CONTACTS.items()}
    try:
        return walk_approach(actor.name, CAPTURE, list(route[-1].xy), [sample(3), sample(86)],
                             contacts, start_frame=1, sole_mesh=shoes, _origin=start)
    except ValueError:
        # Invalid take metadata or an incompatible shoe mesh can use the built-in gait.
        return None


def _tip_mesh(actor, hand):
    index = HandRig(actor).fingers.get(hand[0].upper(), {}).get("index")
    if index:
        try:
            mesh = _basemesh(actor.name)
            if not any(mod.type in ("SUBSURF", "REMESH", "NODES") and mod.show_viewport for mod in mesh.modifiers):
                fingertip_vertices(actor, mesh, index[-1])
                return mesh.name
        except ValueError:
            pass
    return None


@command("preview_walk_press")
def preview_walk_press(character, button, hand="auto"):
    """Place a grounded approach and press relative to a chosen cap at preview time."""
    if hand not in ("auto", "left", "right"):
        raise ValueError("Pilih tangan otomatis, kiri, atau kanan.")
    rig, cap = _rig_of(character), obj_or_raise(button)
    if cap.type != "MESH" or any(mod.type == "ARMATURE" for mod in cap.modifiers):
        raise ValueError("Pilih mesh tutup tombol yang terpisah dari karakter.")
    source = bpy.context.scene
    if rig.name not in source.objects or cap.name not in source.objects:
        raise ValueError("Karakter dan tombol harus berada di adegan aktif.")
    cap_world, actor_world = cap.matrix_world.copy(), rig.matrix_world.copy()
    token = uuid4().hex[:12]
    with _preview_scene(rig, cap, token) as (scene, actor, button_copy):
        scene.frame_set(scene.frame_start)
        button_copy.animation_data_clear()
        button_copy.matrix_world = cap_world
        anim.clear_animation(actor.name)
        actor.matrix_world = actor_world
        scene.timeline_markers.clear()
        if scene.sequence_editor:
            scene.sequence_editor_clear()
        for key in tuple(scene.keys()):
            if key.startswith(("char3d_script_", "char3d_graphic", "char3d_film")):
                del scene[key]
        scene.frame_start = 1
        scene.frame_set(1)
        anim.apply_pose(actor.name, "relaxed", frame=1)
        bpy.context.view_layer.update()
        target = _cap_top(button_copy)
        ground = GroundQuery()
        start, destination, height, forward, use_hand, route = _stance(actor, button_copy, target, hand, ground)
        fps = scene.render.fps / scene.render.fps_base
        facing, _ = heading(actor)
        motion = "procedural"
        if (destination - start).xy.length >= .055:
            walk = None if ground.objects else _capture_approach(actor, start, target, route, facing, fps)
            if walk:
                motion = "mocap"
            else:
                walk = walk_path(actor.name, [list(destination.xy)], start_frame=1, speed=1.05,
                                 face_end=list(target.xy), ignore=[button_copy.name], _world_route=True,
                                 _plant_at_arrival=True)
        elif facing.dot(forward) < .97:
            walk = turn_to(actor.name, list(target.xy), start_frame=1,
                           ignore=[button_copy.name], _world_route=True)
            walk["destination"] = vec(start.xy)
        else:
            walk = {"frames": [1, 1], "distance_m": 0, "destination": vec(start.xy)}
        arrival = walk["frames"][1]
        press = press_button(actor.name, button_copy.name, start_frame=arrival + max(2, round(fps * .12)),
                             hand=use_hand, target=list(target), tip_mesh=_tip_mesh(actor, use_hand))
        if arrival > 1:
            footfalls = walk.get("footfalls")
            if footfalls is None:
                footfalls = [{"character": actor.name, "frame": first, "side": side}
                             for side, intervals in walk["foot_lock"]["contacts"].items()
                             for first, _ in intervals if first > 1]
            auto_sfx(characters=[actor.name], kinds=["footsteps"], footfalls=footfalls, surface="tile", volume=.55)
        final_position = Vector((*walk["destination"], start.z))
        cut = max(arrival + 1, press["frames"]["contact"] - round(.27 * fps))
        _preview_cameras(scene, start, final_position, target, height, forward, cut)
        scene.frame_set(1)
        result = render_video(path=f"preview-jalan-tekan-{token}.mp4", frame_start=1,
                              frame_end=press["frames"]["end"], quality="draft", width=1024, height=576,
                              wait=False, subtitles=False, credits=False)
        result["performance"] = {"character": rig.name, "button": cap.name, "target": vec(target),
                                 "destination": walk["destination"], "distance_m": walk["distance_m"],
                                 "arrival_frame": arrival, "pressed_frame": press["frames"]["pressed"],
                                 "hand": use_hand, "motion": motion,
                                 "contact_error_m": press["contact_error_m"],
                                 "foot_ik_error_m": press["foot_ik_error_m"]}
        return result
