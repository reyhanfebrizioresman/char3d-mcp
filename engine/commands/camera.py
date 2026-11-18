"""Cinematic cameras: shot sizes, named camera moves, multi-shot timelines.

A shot = one camera object whose motion is baked frame by frame (location, rotation,
lens), framed on a subject (character meshes) that may itself be moving. Each shot binds a
timeline marker at its start frame, so consecutive shots cut automatically in renders.

Angles: azimuth 0 = in front of the subject (camera on -Y looking +Y), +90 = the
subject's left side (+X), 180 = behind. Elevation in degrees above the focus point.
"""
import json
import math
import time

import bpy
from mathutils import Euler, Vector

from . import command
from .util import RENDERABLE, is_helper, obj_or_raise, scene_bounds
from .occlusion import VisibilityProbe, adjusted, fit_frame, framing_targets, sample_frames
from .gaze import head_frame

# shot size: (visible height as multiple of subject height, aim height fraction, lens mm)
SHOTS = {
    "extreme_wide": (6.0, 0.45, 24),
    "wide": (2.6, 0.48, 28),
    "full": (1.25, 0.52, 35),
    "medium_full": (0.85, 0.62, 40),
    "medium": (0.6, 0.72, 50),
    "medium_close": (0.42, 0.8, 65),
    "close_up": (0.24, 0.9, 85),
    "extreme_close_up": (0.14, 0.905, 100),
}


def _ease(u, kind):
    u = max(0.0, min(1.0, u))
    if kind == "linear":
        return u
    if kind == "ease_in":
        return u * u
    if kind == "ease_out":
        return 1 - (1 - u) ** 2
    return u * u * (3 - 2 * u)


def _lerp(a, b, u):
    return a + (b - a) * u


# Each move maps eased progress u (0..1) and intensity k to adjustments:
#   dist (x shot distance), az/el (deg added), lift (x subject height), side (x height,
#   camera-right), aim_side / aim_up (x height), lens (x base lens), follow (bool)
def _m(**kw):
    return kw


MOVES = {
    "static": (lambda u, k: _m(), "Locked-off camera."),
    "push_in": (lambda u, k: _m(dist=_lerp(1 + 0.25 * k, 1.0, u)), "Slow, subtle move toward the subject."),
    "dolly_in": (lambda u, k: _m(dist=_lerp(1 + 0.7 * k, 1.0, u)), "Camera travels toward the subject."),
    "dolly_out": (lambda u, k: _m(dist=_lerp(1.0, 1 + 0.7 * k, u)), "Camera travels away from the subject."),
    "pull_out": (lambda u, k: _m(dist=_lerp(1.0, 1 + 2.5 * k, u), el=_lerp(0, 15 * k, u)),
                 "Big reveal pulling back and up."),
    "orbit_left": (lambda u, k: _m(az=_lerp(0, 90 * k, u)), "Circle around the subject to its left."),
    "orbit_right": (lambda u, k: _m(az=_lerp(0, -90 * k, u)), "Circle around the subject to its right."),
    "arc": (lambda u, k: _m(az=_lerp(-30 * k, 30 * k, u), dist=_lerp(1.15, 1.0, u)),
            "Gentle half-circle sweep while easing in."),
    "crane_up": (lambda u, k: _m(el=_lerp(-8, 35 * k, u), lift=_lerp(-0.2, 0.5 * k, u)),
                 "Camera rises while keeping the subject in frame."),
    "crane_down": (lambda u, k: _m(el=_lerp(35 * k, -8, u), lift=_lerp(0.5 * k, -0.2, u)),
                   "Camera descends from above."),
    "truck_left": (lambda u, k: _m(side=_lerp(0.6 * k, -0.6 * k, u), aim_side=_lerp(0.6 * k, -0.6 * k, u)),
                   "Camera slides sideways (to camera-left), parallel to the subject."),
    "truck_right": (lambda u, k: _m(side=_lerp(-0.6 * k, 0.6 * k, u), aim_side=_lerp(-0.6 * k, 0.6 * k, u)),
                    "Camera slides sideways (to camera-right)."),
    "pan_left": (lambda u, k: _m(aim_side=_lerp(0.8 * k, 0.0, u)), "Camera turns from the right onto the subject."),
    "pan_right": (lambda u, k: _m(aim_side=_lerp(-0.8 * k, 0.0, u)), "Camera turns from the left onto the subject."),
    "tilt_up": (lambda u, k: _m(aim_up=_lerp(-0.45 * k, 0.0, u)), "Camera tilts from the feet up to the subject."),
    "tilt_down": (lambda u, k: _m(aim_up=_lerp(0.5 * k, 0.0, u)), "Camera tilts down from above onto the subject."),
    "zoom_in": (lambda u, k: _m(lens=_lerp(1.0, 1 + 0.8 * k, u), to_face=u),
                "Optical zoom in (lens change, camera fixed), ending on the face."),
    "crash_zoom": (lambda u, k: _m(lens=_lerp(1.0, 1 + 2.2 * k, _crash(u)), to_face=_crash(u)),
                   "Violent fast zoom onto the face at the start of the shot, then hold."),
    "dolly_zoom": (lambda u, k: _m(dist=_lerp(1.0, 1 + 1.2 * k, u), lens=_lerp(1.0, 1 + 1.2 * k, u)),
                   "Vertigo effect: dolly out while zooming in, subject size stays."),
    "handheld": (lambda u, k: _m(shake=0.6 * k), "Static framing with documentary hand-held shake."),
    "tracking": (lambda u, k: _m(follow=True), "Camera travels with a moving subject, keeping the framing."),
    "tracking_side": (lambda u, k: _m(follow=True, az_abs=90), "Side-on tracking shot (great for walks/runs)."),
    "drone_reveal": (lambda u, k: _m(az=_lerp(160, 0, u), el=_lerp(50, 8, u), dist=_lerp(1.7, 1.0, u),
                                     lift=_lerp(0.8, 0, u)),
                     "Sweep from high behind the subject down to a frontal view."),
}


def _crash(u):
    return _ease(min(1.0, u / 0.18), "ease_in")


def _subjects(names):
    if names:
        objs = []
        for n in names:
            o = obj_or_raise(n)
            if o.type == "ARMATURE":   # use the meshes it deforms
                objs += [c for c in o.children_recursive if c.type in RENDERABLE]
                objs += [m for m in bpy.context.scene.objects
                         if m.type == "MESH" and any(md.type == "ARMATURE" and md.object == o
                                                     for md in m.modifiers) and m not in objs]
            else:
                objs.append(o)
        return objs
    return [o for o in bpy.context.scene.objects
            if o.type in RENDERABLE and o.visible_get() and not is_helper(o)
            and o.get("c3d_role") not in {"ground", "environment", "weather"}]


def _noise(t, seed):
    return (math.sin(t * 1.7 + seed) * 0.5 + math.sin(t * 3.1 + seed * 2.3) * 0.3
            + math.sin(t * 7.3 + seed * 0.7) * 0.2)


def _shot_name():
    i = 1
    while f"Shot{i}" in bpy.data.objects:
        i += 1
    return f"Shot{i}"


@command("list_camera_moves")
def list_camera_moves():
    return {"moves": {k: v[1] for k, v in MOVES.items()},
            "shot_sizes": {k: f"frames ~{v[0]}x subject height, {v[2]}mm" for k, v in SHOTS.items()}}


@command("camera_shot")
def camera_shot(subject=None, shot="medium", move="static", start_frame=1, end_frame=72,
                angle=20.0, elevation=5.0, intensity=1.0, ease="ease_in_out", lens=None,
                handheld=0.0, roll=0.0, depth_of_field=None, f_stop=2.8, name=None,
                avoid_occlusion="auto", angle_limits=None, action_line=None, require_composition=False,
                face_coverage=False, coverage_turns=None):
    """Create a baked shot and cut marker, preserving composition while clearing faces.
    False keeps old framing. angle_limits/action_line constrain internal dialog coverage.
    """
    if shot not in SHOTS:
        raise ValueError(f"shot must be one of {list(SHOTS)}")
    if move not in MOVES:
        raise ValueError(f"move must be one of {list(MOVES)}")
    if avoid_occlusion != "auto" and type(avoid_occlusion) is not bool:
        raise ValueError('avoid_occlusion must be "auto", True or False')
    sc = bpy.context.scene
    start, end = int(start_frame), int(end_frame)
    if end <= start:
        raise ValueError("end_frame must be after start_frame")
    targets = _subjects(subject)
    if not targets:
        raise ValueError("no subject geometry to frame")

    name = name or _shot_name()
    old = bpy.data.objects.get(name)
    if old:
        cam_data = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        if cam_data.users == 0:
            bpy.data.cameras.remove(cam_data)
    cam_data = bpy.data.cameras.new(name)
    cam = bpy.data.objects.new(name, cam_data)
    sc.collection.objects.link(cam)
    cam["c3d_shot"] = {"subject": subject, "shot": shot, "move": move}
    cam["c3d_focus_turns"] = json.dumps(coverage_turns or [])
    if depth_of_field is not None:
        cam["c3d_dof_explicit"] = bool(depth_of_field)
    cam.rotation_mode = "XYZ"

    aspect = sc.render.resolution_y / sc.render.resolution_x
    sensor_v = cam_data.sensor_width * min(1.0, aspect)
    action_side = 1.0
    if face_coverage and action_line and len(action_line) >= 2:
        sc.frame_set(sc.frame_start)
        axis = head_frame(bpy.data.objects[action_line[1]])[0] - head_frame(bpy.data.objects[action_line[0]])[0]
        action_side = 1.0 if axis.x >= 0 else -1.0
    sc.frame_set(start)
    lo, hi = scene_bounds(targets)
    H = max(hi.z - lo.z, 0.05)

    def design(size):
        frac_h, aim_frac, default_lens = SHOTS[size]
        base_lens = float(lens or default_lens)
        probe = VisibilityProbe(targets, size, H, None if face_coverage else angle_limits, action_line)
        if face_coverage and len(probe.rigs) == 1:
            probe.face_limit = 45.0
        samples = set(sample_frames(start, end, sc.render.fps / sc.render.fps_base))
        trajectory = []
        fn = MOVES[move][0]
        smooth_focus, prev_rot = None, None
        base_focus = None
        for f in range(start, end + 1):
            sc.frame_set(f)
            lo, hi = scene_bounds(targets)
            focus = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z + (hi.z - lo.z) * aim_frac))
            smooth_focus = focus if smooth_focus is None else smooth_focus.lerp(focus, 0.25)
            if base_focus is None:
                base_focus = smooth_focus.copy()
            u = _ease((f - start) / (end - start), ease)
            p = fn(u, float(intensity))
            follow = p.get("follow", False)
            anchor = smooth_focus if follow else base_focus

            lens_mm = base_lens * p.get("lens", 1.0)
            dist_base = (H * frac_h / 2) / (sensor_v / 2 / base_lens)
            dist = dist_base * p.get("dist", 1.0)
            az = math.radians(p["az_abs"] if "az_abs" in p else angle + p.get("az", 0.0))
            el = math.radians(elevation + p.get("el", 0.0))
            offset = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
            right = Vector((math.cos(az), math.sin(az), 0.0))
            pos = anchor + offset * dist + Vector((0, 0, p.get("lift", 0.0) * H)) + right * p.get("side", 0.0) * H
            aim = smooth_focus + right * p.get("aim_side", 0.0) * H \
                + Vector((0, 0, p.get("aim_up", 0.0) * H))
            if move in ("static", "handheld", "pan_left", "pan_right", "tilt_up", "tilt_down",
                        "zoom_in", "crash_zoom"):
                aim = base_focus + right * p.get("aim_side", 0.0) * H + Vector((0, 0, p.get("aim_up", 0.0) * H))

            if face_coverage and probe.rigs:
                frames = [head_frame(r) for r in sorted(probe.rigs, key=lambda r: r.name)]
                normal = Vector((math.sin(math.radians(angle)), -math.cos(math.radians(angle)), 0))
                if action_line and len(action_line) >= 2:
                    axis = head_frame(bpy.data.objects[action_line[1]])[0] - head_frame(bpy.data.objects[action_line[0]])[0]
                    side = Vector((axis.y, -axis.x, 0)) * action_side
                    if side.length > 1e-6:
                        normal = side.normalized()
                if len(frames) == 1:
                    head_pos, orient = frames[0]
                    forward = orient @ Vector((0, -1, 0))
                    direction = (forward + normal * 0.35).normalized()
                    # Face-relative coverage follows root turns and seating, even
                    # for a nominally static shot. Preserve the designed eye line.
                    aim = Vector((head_pos.x, head_pos.y, focus.z))
                else:
                    direction = normal
                    # Mixed standing/seated bounds otherwise aim below the desk
                    # and let foreground screens cover a face. Frame the heads.
                    aim = Vector((focus.x, focus.y, sum(p.z for p, _ in frames) / len(frames) - 0.12 * H))
                    active = next((t['speaker'] for t in (coverage_turns or [])
                                   if t['start'] <= f <= t['end']), None)
                    if active:
                        speaker_forward = head_frame(bpy.data.objects[active])[1] @ Vector((0, -1, 0))
                        candidate = (normal + speaker_forward * 0.4).normalized()
                        # Favor the current speaker only while every face still
                        # fits inside the two-shot's frontal visibility cone.
                        if all((q @ Vector((0, -1, 0))).angle(candidate) <= math.radians(73)
                               for _, q in frames):
                            direction = candidate
                    lateral = Vector((-direction.y, direction.x, 0)).normalized()
                    span = max(p.dot(lateral) for p, _ in frames) - min(p.dot(lateral) for p, _ in frames)
                    dist = max(dist, (span + 0.3 * H) * lens_mm / cam_data.sensor_width)
                pos = aim + direction * dist
                pos.z += math.sin(el) * dist

            if "to_face" in p:   # zooms drift the aim from the shot's focus up to the face
                aim = aim + Vector((0, 0, (0.92 - aim_frac) * H * max(0.0, p["to_face"])))
            rot = (aim - pos).to_track_quat("-Z", "Y").to_euler("XYZ", prev_rot or Euler())
            shake = float(handheld) + p.get("shake", 0.0)
            if shake:
                t = f / sc.render.fps
                rot.x += math.radians(1.2 * shake * _noise(t, 1.0))
                rot.y += math.radians(0.6 * shake * _noise(t, 4.0))
                rot.z += math.radians(1.2 * shake * _noise(t, 7.0))
                pos = pos + Vector((_noise(t, 2.0), _noise(t, 5.0), _noise(t, 9.0))) * 0.01 * shake * H
            if roll:
                rot.y += math.radians(roll)
            prev_rot = rot.copy()
            trajectory.append((f, pos.copy(), aim.copy(), rot.copy(), lens_mm, focus.copy()))
            if f in samples:
                probe.capture(f, pos, aim, rot, lens_mm)
        return trajectory, probe

    trajectory, probe = design(shot)
    adjustment, occlusion = probe.resolve(avoid_occlusion is not False, elevation, require_composition=require_composition)
    used_size = shot
    wider = {"extreme_close_up": "close_up", "close_up": "medium_close",
             "medium_close": "medium", "medium": "medium_full"}
    if avoid_occlusion is not False and "warning" in occlusion and shot in wider:
        wider_trajectory, wider_probe = design(wider[shot])
        wider_adjustment, wider_report = wider_probe.resolve(True, elevation, require_composition=True)
        # A one-step fallback has to pass composition too, even if its face was
        # already clear and resolve deliberately preserved the original keys.
        if "warning" not in wider_report and wider_probe.accepts(wider_probe.measure(wider_adjustment)):
            wider_report["before"] = occlusion["before"]
            wider_report["frame_coverage_before"] = occlusion["frame_coverage_before"]
            wider_report["adjusted"].insert(0, "shot_size="+wider[shot])
            wider_report["seconds"] += occlusion["seconds"]
            trajectory, probe = wider_trajectory, wider_probe
            adjustment, occlusion = wider_adjustment, wider_report
            used_size = wider[shot]
        else:
            occlusion["seconds"] += wider_report["seconds"]
    cam["c3d_shot"]["shot_size"] = used_size

    adjustment_started = time.perf_counter()
    prev_rot = None
    lenses = []
    for f, pos, aim, rot, mm, focus in trajectory:
        if adjustment is not None:
            sc.frame_set(f)
            groups = probe.points()
            targets_screen = framing_targets(pos, rot, mm, groups, probe.sensor, used_size)
            pos, aim = adjusted(pos, aim, H, adjustment)
            rot, mm = fit_frame(pos, rot, mm, groups, probe.sensor, targets_screen)
            rot = rot.to_quaternion().to_euler("XYZ", prev_rot or rot)
        prev_rot = rot.copy()
        lenses.append(mm)
        cam.location, cam.rotation_euler = pos, rot
        cam_data.lens = mm
        cam_data.clip_start = 0.05
        cam_data.clip_end = max(200.0, (aim-pos).length * 10)
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
        cam_data.keyframe_insert("lens", frame=f)
        if depth_of_field:
            cam_data.dof.use_dof = True
            cam_data.dof.aperture_fstop = float(f_stop)
            cam_data.dof.focus_distance = (focus-pos).length
            cam_data.dof.keyframe_insert("focus_distance", frame=f)
    occlusion["seconds"] = round(occlusion["seconds"] + time.perf_counter()-adjustment_started, 4)
    cam["c3d_occlusion"] = json.dumps(occlusion)

    # timeline: cut to this camera at its start frame
    replaced = []
    for m in [m for m in sc.timeline_markers if m.name == name or m.frame == start]:
        if m.name != name:
            replaced.append(m.name)     # two cuts on one frame would be ambiguous
        sc.timeline_markers.remove(m)
    marker = sc.timeline_markers.new(name, frame=start)
    marker.camera = cam
    if sc.camera is None or start <= sc.frame_start:
        sc.camera = cam
    sc.frame_end = max(sc.frame_end, end)
    sc.frame_set(start)
    return {"camera": cam.name, "shot": shot, "move": move, "frames": [start, end],
            "next_start_frame": end + 1, "subject_height": round(H, 3),
            "occlusion": occlusion, "shot_size": used_size,
            "replaced_shots_at_start_frame": replaced,
            "lens_mm": [round(lenses[0], 1), round(lenses[-1], 1)]}


@command("list_shots")
def list_shots():
    sc = bpy.context.scene
    marks = sorted(((m.frame, m.name, m.camera.name if m.camera else None)
                    for m in sc.timeline_markers), key=lambda x: x[0])
    shots = []
    for i, (frame, name, cam) in enumerate(marks):
        end = marks[i + 1][0] - 1 if i + 1 < len(marks) else sc.frame_end
        meta = bpy.data.objects[cam].get("c3d_shot") if cam and cam in bpy.data.objects else None
        shots.append({"marker": name, "camera": cam, "frames": [frame, end],
                      "info": dict(meta) if meta else None})
    return {"frame_range": [sc.frame_start, sc.frame_end], "fps": sc.render.fps, "shots": shots}


@command("delete_shot")
def delete_shot(name):
    sc = bpy.context.scene
    for m in [m for m in sc.timeline_markers if m.name == name]:
        sc.timeline_markers.remove(m)
    cam = bpy.data.objects.get(name)
    if cam:
        data = cam.data
        bpy.data.objects.remove(cam, do_unlink=True)
        if data and data.users == 0:
            bpy.data.cameras.remove(data)
    return list_shots()


@command("set_timeline")
def set_timeline(frame_start=None, frame_end=None, fps=None):
    sc = bpy.context.scene
    if frame_start is not None:
        sc.frame_start = int(frame_start)
    if frame_end is not None:
        sc.frame_end = int(frame_end)
    if fps is not None:
        sc.render.fps = int(fps)
    return {"frame_range": [sc.frame_start, sc.frame_end], "fps": sc.render.fps,
            "seconds": round((sc.frame_end - sc.frame_start + 1) / sc.render.fps, 2)}
