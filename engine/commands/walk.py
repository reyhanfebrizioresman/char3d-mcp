"""Floor navigation: smooth root routes, rate-limited turns and planted footsteps."""
import bisect
import math

import bpy
from mathutils import Quaternion, Vector

from . import command, anim
from .footlock import _intervals, _legs, _smoothstep, _sole_points, foot_lock
from .util import obj_or_raise

TURN_RATE = math.radians(100)       # maximum body yaw per second, independent of speed
SHARP_TURN = math.radians(100)      # stop and step around corners sharper than this
MAX_FRAMES = 24000


def _angle(a, b):
    """Shortest signed rotation from a to b."""
    return (b - a + math.pi) % (2 * math.pi) - math.pi


def _yaw(direction):
    return math.atan2(direction.x, -direction.y)


def _point(value, size=2):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f"expected a {size}D point in meters")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
           for x in value):
        raise ValueError("point coordinates must be finite numbers")
    return Vector((*value, 0.0)) if size == 2 else Vector(value)


def _start(rig, frame):
    sc = bpy.context.scene
    act = rig.animation_data.action if rig.animation_data else None
    start = int(frame) if frame is not None else (
        int(act.frame_range[1]) + 1 if act else sc.frame_start)
    if start < sc.frame_start:
        raise ValueError("start_frame must be at or after the scene start")
    smap = anim.semantic_map(rig)
    if "hips" not in smap:
        raise ValueError(f"{rig.name}: no recognisable hips bone")
    sc.frame_set(start - 1 if anim._has_keys_before(rig, start) else start)
    mw = rig.matrix_world
    hips = mw @ rig.pose.bones[smap["hips"]].matrix
    rest = mw @ rig.data.bones[smap["hips"]].matrix_local
    base_forward = anim._facing(rig, smap).inverted() @ Vector((0, -1, 0))
    forward = hips.to_quaternion() @ rest.to_quaternion().inverted() @ base_forward
    pos = hips.translation.copy()
    pos.z = 0.0
    feet = {s: (mw @ rig.pose.bones[smap[f"foot.{s}"]].matrix).copy() for s in "LR"}
    return start, pos, _yaw(forward), feet


def _target_yaw(target, origin, frame, fallback):
    """Resolve a facing target once, at the frame the facing move begins."""
    if isinstance(target, str):
        sc = bpy.context.scene
        sc.frame_set(frame)
        if target == "camera":
            markers = [m for m in sc.timeline_markers if m.camera and m.frame <= frame]
            obj = max(markers, key=lambda m: m.frame).camera if markers else sc.camera
            if obj is None:
                raise ValueError("no scene camera: create a camera_shot first")
        else:
            obj = obj_or_raise(target)
        point = obj.matrix_world.translation
    else:
        if not isinstance(target, (list, tuple)) or len(target) not in (2, 3):
            raise ValueError('target must be a 2D/3D point, object name or "camera"')
        point = _point(target, len(target))
    direction = point - origin
    direction.z = 0.0
    return _yaw(direction) if direction.length > 1e-6 else fallback


def _curves(points):
    """Piecewise cubic Hermite curves through every point; split at pivot corners.

    Shared bounded tangents round ordinary corners without a Catmull-Rom loop at
    duplicate points or reversals. Each returned section starts and ends at rest.
    """
    cuts = [0]
    for i in range(1, len(points) - 1):
        a, b = points[i] - points[i - 1], points[i + 1] - points[i]
        if a.normalized().dot(b.normalized()) < math.cos(SHARP_TURN):
            cuts.append(i)
    cuts.append(len(points) - 1)
    out = []
    for first, last in zip(cuts, cuts[1:]):
        pts = points[first:last + 1]
        tangents = [pts[1] - pts[0]]
        for i in range(1, len(pts) - 1):
            a, b = pts[i] - pts[i - 1], pts[i + 1] - pts[i]
            tangents.append((a.normalized() + b.normalized()).normalized()
                            * min(a.length, b.length))
        tangents.append(pts[-1] - pts[-2])
        samples = []
        for a, b, ta, tb in zip(pts, pts[1:], tangents, tangents[1:]):
            count = max(8, int(math.ceil((b - a).length / 0.035)))
            for k in range(count + 1):
                if samples and k == 0:
                    continue
                u = k / count
                p = ((2*u**3 - 3*u**2 + 1)*a + (u**3 - 2*u**2 + u)*ta
                     + (-2*u**3 + 3*u**2)*b + (u**3 - u**2)*tb)
                v = ((6*u**2 - 6*u)*a + (3*u**2 - 4*u + 1)*ta
                     + (-6*u**2 + 6*u)*b + (3*u**2 - 2*u)*tb)
                samples.append((p, _yaw(v)))
        out.append(samples)
    return out


def _turn(keys, yaw):
    t, pos, old = keys[-1]
    delta = _angle(old, yaw)
    if abs(delta) < 1e-6:
        return
    duration = max(0.25, 1.5 * abs(delta) / TURN_RATE)
    count = max(2, int(math.ceil(duration * 48)))
    for i in range(1, count + 1):
        u = i / count
        keys.append((t + duration*u, pos.copy(), old + delta*_smoothstep(u)))


def _route(pos, yaw, points, velocity):
    keys = [(0.0, pos.copy(), yaw)]
    distance = 0.0
    for curve in _curves(points) if len(points) > 1 else []:
        _turn(keys, curve[0][1])
        lengths = [0.0]
        for (a, _ya), (b, _yb) in zip(curve, curve[1:]):
            lengths.append(lengths[-1] + (b - a).length)
        for i, (p, heading) in enumerate(curve[1:], 1):
            ds = lengths[i] - lengths[i - 1]
            mid = (lengths[i] + lengths[i - 1]) / 2
            # Accelerate/decelerate over roughly one step. Cadence stays regular;
            # shorter foot placements supply the lower speed at tight corners.
            accel = velocity * 0.7
            v = min(velocity, math.sqrt(2*accel*max(mid, 0.001)),
                    math.sqrt(2*accel*max(lengths[-1] - mid, 0.001)))
            t, _p, old = keys[-1]
            delta = _angle(old, heading)
            dt = max(ds / v, abs(delta) / TURN_RATE, 1e-5)
            keys.append((t + dt, p, old + delta))
        distance += lengths[-1]
    return keys, distance


def _samples(keys, fps, half_step):
    active = int(math.ceil(keys[-1][0] * fps))
    # Two final steps gather the feet at the destination, then hold both feet still.
    end = int(math.ceil(max(active, 1) / (2*half_step))) * 2*half_step + 2*half_step
    end += max(4, round(fps / 4))
    if end > MAX_FRAMES:
        raise ValueError(f"route exceeds {MAX_FRAMES} frames; split it into shorter paths")
    times = [k[0] for k in keys]
    samples = []
    for i in range(end + 1):
        t = min(i / fps, times[-1])
        j = max(0, bisect.bisect_right(times, t) - 1)
        a = keys[j]
        b = keys[min(j + 1, len(keys) - 1)]
        u = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
        samples.append((a[1].lerp(b[1], u), a[2] + (b[2] - a[2])*u))
    return samples, active


def _half_step(clip, fps, speed):
    return max(2, int(round(anim.CLIPS[clip][1]*fps/(48*speed))))


def _footsteps(rig, samples, initial, half, start, run=False):
    """Alternate planted supports and lifted swings; contacts freeze position AND yaw."""
    smap = anim.semantic_map(rig)
    mw = rig.matrix_world
    root = (mw @ rig.data.bones[smap["hips"]].matrix_local).translation
    rest_yaw = _yaw(anim._facing(rig, smap).inverted() @ Vector((0, -1, 0)))
    n = len(samples)
    # Stop stepping only on a full gait boundary, after the feet have gathered.
    sc = bpy.context.scene
    stop = n - 1 - max(4, round(sc.render.fps / sc.render.fps_base / 4))
    flight = max(1, round(0.2*half)) if run else 0
    legs, _smap = _legs(rig)
    initial_height = {s: min((initial[s] @ p).z for p in _sole_points(rig, legs[s], 0.0))
                      for s in "LR"}
    support = min(initial_height, key=initial_height.get)
    targets, contacts = {}, {}
    for side in "LR":
        rest = mw @ rig.data.bones[smap[f"foot.{side}"]].matrix_local
        offset = rest.translation - root
        offset.z = 0.0

        def landing(frame):
            p, yaw = samples[min(frame + (half-flight)//2, n - 1)]
            q = Quaternion((0, 0, 1), yaw - rest_yaw)
            ankle = p + q @ offset
            ankle.z = rest.translation.z - mw.translation.z
            return ankle, q @ rest.to_quaternion()

        anchor = (initial[side].translation.copy(), initial[side].to_quaternion())
        # Initial supports start where the preceding animation actually left them.
        first_land = 2*half if side == support else half
        track, mask = [None]*n, [True]*n
        cursor = 0
        for land in range(first_land, stop + 1, 2*half):
            lift = max(0, land - half - flight)
            for i in range(cursor, lift + 1):
                track[i] = anchor
            goal = landing(land)
            for i in range(lift, land + 1):
                u = (i - lift) / (land - lift)
                w = _smoothstep(u)
                p = anchor[0].lerp(goal[0], w)
                p.z += (0.12 if run else 0.075) * math.sin(math.pi*u)**2
                track[i] = (p, anchor[1].slerp(goal[1], w))
                mask[i] = i in (lift, land)
            anchor, cursor = goal, land + 1
        for i in range(cursor, n):
            track[i] = anchor
        # An incoming locomotion clip can leave the first swinging foot airborne.
        mask[0] = abs(initial_height[side]) < 0.02
        targets[side] = track
        contacts[side] = [[start+a, start+b] for a, b in _intervals(mask, fill=0, min_len=1)]
    return targets, contacts


def _bake(rig, start, samples, active, initial_feet, clip, speed):
    sc = bpy.context.scene
    fps = sc.render.fps / sc.render.fps_base
    half = _half_step(clip, fps, speed)
    end = start + len(samples) - 1
    prev = anim._sample_pose(rig, start)
    hips_name = anim.semantic_map(rig)["hips"]
    root_rest = (rig.matrix_world @ rig.data.bones[hips_name].matrix_local).translation

    def author(basic, lm, direct, carry):
        d, rest_deg = anim._dims(lm), anim._arm_rest_deg(lm)
        mw = basic.matrix_world
        rest_yaw = _yaw(anim._facing(basic, {b: b for b in anim.BASIC_BONES}).inverted()
                        @ Vector((0, -1, 0)))
        previous = {}
        for i, (pos, yaw) in enumerate(samples):
            f = start + i
            sc.frame_set(f)
            rots, (_x, up, _fwd) = anim.CLIPS[clip][0](i, 2*half, d, rest_deg, 1.0)
            w = _smoothstep(i / half) * (1 - _smoothstep((i - active) / (2*half)))
            relaxed = anim._resolve(anim.RELAXED, rest_deg)
            rots = {b: [relaxed.get(b, (0, 0, 0))[k]*(1-w) + v[k]*w for k in range(3)]
                    for b, v in rots.items()}
            rots["hips"] = (0, 0, 0)
            # _drive retargets offsets from the proxy rest onto the target rest.
            # Rigify's torso control need not share the proxy pelvis' rest head.
            anim._key_basic(basic, f, rots,
                            (pos.x - root_rest.x, up*w, root_rest.y - pos.y))
            bpy.context.view_layer.update()
            hp = basic.pose.bones["hips"]
            world = mw @ hp.matrix
            q = Quaternion((0, 0, 1), yaw - rest_yaw) @ world.to_quaternion()
            anim._set_world_rot(basic, hp, q)
            anim._key_rot(hp, f, previous)

    info = anim._drive(rig, author, start, end, start)
    fade = anim._crossfade(rig, prev, start, end)
    if fade:
        info["crossfade"] = fade
    targets, contacts = _footsteps(rig, samples, initial_feet, half, start, run=clip == "run")
    lock = foot_lock(rig, start, end, floor=0.0, contacts=contacts, foot_targets=targets)
    info["foot_lock"] = {"contacts": contacts, "max_ik_error_m": lock["max_ik_error_m"],
                         "hips_lowered_max_m": lock["hips_lowered_max_m"]}
    anim._extend_range(end)
    sc.frame_set(end)
    return {"armature": rig.name, "frames": [start, end], "next_start_frame": end + 1,
            "duration_seconds": round((end-start)/fps, 3),
            "max_turn_rate_deg_s": math.degrees(TURN_RATE), **info}


def _speed(value):
    if isinstance(value, bool) or not math.isfinite(value) or not 0.1 <= value <= 4.0:
        raise ValueError("speed must be finite and between 0.1 and 4.0")
    return float(value)


@command("walk_path")
def walk_path(armature, points, clip="walk", start_frame=None, speed=1.0, face_end=None):
    """Walk/run through absolute floor XY targets, then stand (optionally face a target)."""
    if clip not in ("walk", "run"):
        raise ValueError('clip must be "walk" or "run"')
    speed = _speed(speed)
    if not isinstance(points, (list, tuple)) or not 1 <= len(points) <= 1000:
        raise ValueError("points must contain 1..1000 floor XY points")
    destinations = [_point(p) for p in points]
    rig = anim._target(armature)
    saved_frame = bpy.context.scene.frame_current
    try:
        start, pos, yaw, feet = _start(rig, start_frame)
        route = [pos]
        for p in destinations:
            if (p - route[-1]).length > 1e-5:
                route.append(p)
        lm = anim._rig_landmarks(rig, anim.semantic_map(rig))
        d = anim._dims(lm)
        stride = 2*d["leg"]*math.sin(math.radians(38 if clip == "run" else 24))*anim.STRIDE_SCALE[clip]
        velocity = 2*stride*24/anim.CLIPS[clip][1]*speed
        fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
        length = sum((b - a).length for a, b in zip(route, route[1:]))
        if length / velocity * fps > MAX_FRAMES:
            raise ValueError(f"route exceeds {MAX_FRAMES} frames; split it into shorter paths")
        keys, distance = _route(pos, yaw, route, velocity)
        if face_end is not None:
            target = _target_yaw(face_end, route[-1], start + math.ceil(keys[-1][0]*fps), keys[-1][2])
            _turn(keys, target)
        half = _half_step(clip, fps, speed)
        samples, active = _samples(keys, fps, half)
        result = _bake(rig, start, samples, active, feet, clip, speed)
        return {**result, "clip": clip, "distance_m": round(distance, 4),
                "natural_speed_m_s": round(velocity, 3), "destination": list(route[-1])[:2]}
    finally:
        bpy.context.scene.frame_set(saved_frame)


@command("turn_to")
def turn_to(armature, target, start_frame=None):
    """Turn in place toward a point, object or scene camera with alternating steps."""
    rig = anim._target(armature)
    saved_frame = bpy.context.scene.frame_current
    try:
        start, pos, yaw, feet = _start(rig, start_frame)
        heading = _target_yaw(target, pos, start, yaw)
        keys = [(0.0, pos, yaw)]
        _turn(keys, heading)
        fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
        half = _half_step("walk", fps, 1.0)
        samples, active = _samples(keys, fps, half)
        result = _bake(rig, start, samples, active, feet, "walk", 1.0)
        return {**result, "distance_m": 0.0, "turn_degrees": round(math.degrees(_angle(yaw, heading)), 3)}
    finally:
        bpy.context.scene.frame_set(saved_frame)
