"""Floor navigation: smooth root routes, rate-limited turns and planted footsteps."""
import bisect
import math
import time

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import command, anim
from .gaze import head_frame
from .footlock import _intervals, _legs, _smoothstep, _sole_points, foot_lock
from .util import obj_or_raise
from .terrain import GroundQuery, smooth_heights, sole_footprint
from .navigation import Planner, validate_options

TURN_RATE = math.radians(100)       # maximum body yaw per second, independent of speed
SHARP_TURN = math.radians(100)      # stop and step around corners sharper than this
MAX_FRAMES = 24000


def _angle(a, b):
    """Shortest signed rotation from a to b."""
    return (b - a + math.pi) % (2 * math.pi) - math.pi


def _yaw(direction):
    return math.atan2(direction.x, -direction.y)


def _terrain_forward(rig, smap):
    """Exact world heading, including arbitrary object yaw (retarget facing snaps axes)."""
    mw = rig.matrix_world
    left = (mw @ rig.data.bones[smap["thigh.L"]].head_local -
            mw @ rig.data.bones[smap["thigh.R"]].head_local)
    return Vector((left.y, -left.x, 0)).normalized()


def _point(value, size=2):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f"expected a {size}D point in meters")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
           for x in value):
        raise ValueError("point coordinates must be finite numbers")
    return Vector((*value, 0.0)) if size == 2 else Vector(value)


def _start(rig, frame, ground=None):
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
    base_forward = (_terrain_forward(rig, smap) if ground else
                    anim._facing(rig, smap).inverted() @ Vector((0, -1, 0)))
    forward = hips.to_quaternion() @ rest.to_quaternion().inverted() @ base_forward
    pos = hips.translation.copy()
    pos.z = 0.0
    feet = {s: (mw @ rig.pose.bones[smap[f"foot.{s}"]].matrix).copy() for s in "LR"}
    return start, pos, _yaw(forward), feet


def _anatomical_yaw(rig):
    """Actual body heading, without mocap's cardinal-axis rest-frame snapping."""
    return _yaw(head_frame(rig, "hips")[1] @ Vector((0, -1, 0)))


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


def _curves(points, safe=None):
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
        if safe is not None and not safe([p for p, _ in samples]):
            # A shortcut is safe as a line, but Hermite tangents can cut its
            # inside corner. Keep the existing stepping-turn machinery there.
            for a, b in zip(pts, pts[1:]):
                out.extend(_curves([a, b]))
        else:
            out.append(samples)
    return out


def _turn(keys, yaw, terrain=False):
    t, pos, old = keys[-1]
    delta = _angle(old, yaw)
    if abs(delta) < 1e-6:
        return
    duration = (max(0.3, abs(delta) / TURN_RATE + 0.15) if terrain else
                max(0.25, 1.5 * abs(delta) / TURN_RATE))
    count = max(2, int(math.ceil(duration * 48)))
    for i in range(1, count + 1):
        u = i / count
        if terrain:
            ramp = 0.15 / duration
            progress = (u*u/(2*ramp) if u < ramp else
                        1-ramp - (1-u)**2/(2*ramp) if u > 1-ramp else u-ramp/2)
            progress /= 1-ramp
        else:
            progress = _smoothstep(u)
        keys.append((t + duration*u, pos.copy(), old + delta*progress))


def _route(pos, yaw, points, velocity, ground=None, fps=24, speed=1.0, safe=None):
    keys = [(0.0, pos.copy(), yaw)]
    distance = 0.0
    for curve in _curves(points, safe) if len(points) > 1 else []:
        _turn(keys, curve[0][1], terrain=ground is not None)
        lengths = [0.0]
        for (a, _ya), (b, _yb) in zip(curve, curve[1:]):
            lengths.append(lengths[-1] + (b - a).length)
        limits = [velocity] * len(curve)
        if ground is not None:
            for i, (p, heading) in enumerate(curve):
                tread, slope = ground.gait(p, heading)
                # Bound vertical travel too: a fast downhill run must leave room
                # for the IK hips adjustment within the 4 cm/frame height budget.
                limits[i] = (min(velocity, tread * fps / max(2, round(0.4*fps/speed)) * 0.9)
                             if tread else min(velocity / (1 + 0.6*slope),
                                               0.65 / max(slope, 1e-6)))
            # Spatial acceleration bounds anticipate stairs and ease out onto landings.
            for indices in (range(1, len(curve)), range(len(curve)-2, -1, -1)):
                for i in indices:
                    j = i-1 if indices.step > 0 else i+1
                    limits[i] = min(limits[i], math.sqrt(limits[j]**2 + 3*abs(lengths[i]-lengths[j])))
        for i, (p, heading) in enumerate(curve[1:], 1):
            ds = lengths[i] - lengths[i - 1]
            mid = (lengths[i] + lengths[i - 1]) / 2
            # Accelerate/decelerate over roughly one step; shorter foot placements
            # supply the lower speed at tight corners.
            accel = velocity * 0.7
            v = min(limits[i], limits[i-1], math.sqrt(2*accel*max(mid, 0.001)),
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


def _arrival_samples(keys, fps, half_step):
    """Finish stepping with the body instead of after it.

    The lead foot lands at the final stance and the trailing foot closes beside it
    about .3 s before the decelerating hips stop; the body then glides over both
    planted feet. Steps are spread evenly over the travel (shorter as it slows).
    """
    samples, arrival = _samples(keys, fps, half_step)
    glide = max(2, round(.3 * fps))
    hold = max(4, round(fps / 4))
    shortest = max(2, round(.6 * half_step))
    final = max(arrival - glide, 2 * shortest)
    count = max(2, min(round(final / half_step), final // shortest))
    length = max(arrival, final + glide) + hold + 1
    samples = (samples + [samples[-1]] * length)[:length]
    phases = [float(count)] * length
    boundaries = [round(step * final / count) for step in range(count + 1)]
    for step, (first, last) in enumerate(zip(boundaries, boundaries[1:])):
        for frame in range(first, last):
            phases[frame] = step + (frame - first) / (last - first)
    return samples, max(0, final - half_step), phases


def _walk_half_step(d, velocity, fps, speed):
    """Natural adult steps are ~0.37 x stature; keep that length as speed scales cadence."""
    natural = velocity / speed
    return max(2, round(fps * .37 * d["H"] / natural / speed))


def _terrain_samples(keys, fps, clip, speed, ground):
    """Continuous half-step phase lets cadence change without restarting a foot swing."""
    active = int(math.ceil(keys[-1][0] * fps))
    times = [k[0] for k in keys]
    samples, phases, runs = [], [0.0], []
    half = _half_step(clip, fps, speed)
    walk_mix = 0.0
    finish = None
    for i in range(MAX_FRAMES + 1):
        t = min(i/fps, times[-1])
        j = max(0, bisect.bisect_right(times, t)-1)
        a, b = keys[j], keys[min(j+1, len(keys)-1)]
        u = (t-a[0])/(b[0]-a[0]) if b[0] > a[0] else 0.0
        p, yaw = a[1].lerp(b[1], u), a[2]+(b[2]-a[2])*u
        samples.append((p, yaw))
        tread, slope = ground.gait(p, yaw)
        moving = (b[1]-a[1]).length > 1e-7 and i < active
        desired = (max(2, round(0.4*fps/speed)) if tread else
                   max(2, round(_half_step(clip, fps, speed)/(1+0.9*slope))))
        if not moving:
            desired = max(2, round((0.2 if i >= active else 0.27)*fps/speed))
        half += max(-0.8, min(0.8, desired-half))
        walk_mix += max(-0.15, min(0.15, float(bool(tread) or not moving)-walk_mix))
        runs.append(1-walk_mix if clip == "run" else 0.0)
        if i:
            phases.append(phases[-1]+1/half)
        if i == active:
            finish = math.ceil(phases[-1])+2
        if finish is not None and phases[-1] >= finish:
            hold = max(4, round(fps/6))
            if i + hold > MAX_FRAMES:
                break
            samples.extend([(p.copy(), yaw) for _ in range(hold)])
            phases.extend([phases[-1]]*hold)
            runs.extend([0.0]*hold)
            return samples, active, phases, runs
    raise ValueError(f"route exceeds {MAX_FRAMES} frames; split it into shorter paths")


def _support_side(rig, initial):
    """The lower initial foot keeps supporting first (see _footsteps)."""
    legs, _smap = _legs(rig)
    heights = {s: min((initial[s] @ p).z for p in _sole_points(rig, legs[s], 0.0)) for s in "LR"}
    return min(heights, key=heights.get)


HEEL_STRIKE = math.radians(12)      # toes up as the heel lands
HEEL_RISE = math.radians(15)        # heel up about the toe edge before push-off


def _pitched(position, rotation, pivot, axis, angle):
    """Rotate a foot (ankle position, world rotation) about a sole point in foot space."""
    turn = Quaternion(axis, angle)
    point = position + rotation @ pivot
    return point + turn @ (position - point), turn @ rotation


def _roll_feet(track, swings, sole_points, rest, rest_yaw, fps, scale=1.0):
    """Heel strike -> flat foot -> heel rise, pivoting on the sole so planted edges never slip.

    track holds (ankle, rotation) per frame with flat contacts; swings lists (lift, land).
    """
    n = len(track)
    strike, rise = HEEL_STRIKE * scale, HEEL_RISE * scale
    local_forward = rest.inverted() @ Vector((math.sin(rest_yaw), -math.cos(rest_yaw), 0))
    heel = min(sole_points, key=local_forward.dot)
    toe = max(sole_points, key=local_forward.dot)
    flat = [(p.copy(), q.copy()) for p, q in track]

    def axis(i):
        forward = flat[i][1] @ local_forward
        forward.z = 0
        return forward.normalized().cross(Vector((0, 0, 1)))

    # Contacts: before the first lift, between each land and the next lift, after the last land.
    stances = []
    edges = [None, *[land for _lift, land in swings]]
    lifts = [lift for lift, _land in swings] + [None]
    for land, lift in zip(edges, lifts):
        stances.append((0 if land is None else land, n - 1 if lift is None else lift,
                        land is not None, lift is not None))
    pose = {}
    for begin, end, strikes, rises in stances:
        length = end - begin
        if length <= 0:
            continue
        strike_frames = max(1, min(round(.1 * fps), length // 3))
        rise_frames = max(1, min(round(.45 * length), length - (strike_frames if strikes else 0)))
        for i in range(begin, end + 1):
            p, q = flat[i]
            if strikes and i - begin < strike_frames:
                angle = strike * (1 - _smoothstep((i - begin) / strike_frames))
                pose[i] = _pitched(p, q, heel, axis(i), angle)
            elif rises and end - i < rise_frames:
                angle = -rise * _smoothstep(1 - (end - i) / rise_frames)
                pose[i] = _pitched(p, q, toe, axis(i), angle)
            else:
                pose[i] = (p.copy(), q.copy())
    for lift, land in swings:
        if land <= lift:
            continue
        started = lift > 0 or lift in pose and pose[lift][1] != flat[lift][1]
        start_offset = pose[lift][0] - flat[lift][0] if started and lift in pose else Vector()
        start_angle = -rise if started else 0.0
        end_offset = pose[land][0] - flat[land][0] if land in pose else Vector()
        for i in range(lift + 1, land):
            u = (i - lift) / (land - lift)
            angle = (start_angle * (1 - _smoothstep(u / .4)) +
                     strike * _smoothstep((u - .45) / .55))
            p, q = flat[i]
            w = _smoothstep(u)
            turn = Quaternion(axis(i), angle)
            pose[i] = (p + start_offset.lerp(end_offset, w), turn @ q)
    for i, value in pose.items():
        track[i] = value
    # Rolling frames touch the floor on an edge; "contacts" stay the flat, fixed foot.
    return {i for i, (p, q) in pose.items() if q != flat[i][1]}


def _footsteps(rig, samples, initial, half, start, run=False, ground=None, phases=None, runs=None,
               arrive=False, roll=False, roll_scale=1.0, stance=None, track_width=None):
    """Alternate planted supports and lifted swings; contacts freeze position AND yaw.

    arrive lands the last two steps side by side at the final stance (ankle centres at
    most `stance` m apart). roll adds a heel strike and a heel rise about the sole's
    heel/toe edges (flat ground only), scaled by roll_scale. track narrows the ankle
    centres of every other landing to at most `track_width` m apart (walking step width).
    """
    smap = anim.semantic_map(rig)
    mw = rig.matrix_world
    root = (mw @ rig.data.bones[smap["hips"]].matrix_local).translation
    rest_yaw = _yaw(_terrain_forward(rig, smap) if ground else
                    anim._facing(rig, smap).inverted() @ Vector((0, -1, 0)))
    n = len(samples)
    # Stop stepping only on a full gait boundary, after the feet have gathered.
    sc = bpy.context.scene
    fps = sc.render.fps / sc.render.fps_base
    stop = n - 1 - max(4, round(fps / (6 if phases is not None else 4)))
    boundaries = ([0] + [i for i in range(1, stop+1) if int(phases[i]) > int(phases[i-1])]
                  if phases is not None else list(range(0, stop+1, half)))
    flight = max(1, round(0.2*half)) if run else 0
    legs, _smap = _legs(rig)
    initial_height = {s: min((initial[s] @ p).z for p in _sole_points(rig, legs[s], 0.0))
                      for s in "LR"}
    support = min(initial_height, key=initial_height.get)
    targets, contacts, footfalls = {}, {}, []
    for side in "LR":
        rest = mw @ rig.data.bones[smap[f"foot.{side}"]].matrix_local
        sole = _sole_points(rig, legs[side], mw.translation.z)
        sweep_sole = sole_footprint(sole, rest.to_quaternion()) if ground is not None else sole
        offset = rest.translation - root
        offset.z = 0.0
        lateral = Vector((0, 0, 1)).cross(Vector((math.sin(rest_yaw), -math.cos(rest_yaw), 0)))

        def narrowed(limit):
            # A rest A-pose stands wider than people walk or stop; narrow toward `limit`.
            width = offset.dot(lateral)
            if not limit or abs(width) <= limit / 2:
                return offset.copy()
            return offset - lateral * (width - math.copysign(limit / 2, width))

        settled, stepping = narrowed(stance), narrowed(track_width)

        def landing(frame, duration, final=False):
            p, yaw = samples[min(frame + (duration-flight)//2, n - 1)]
            q = Quaternion((0, 0, 1), yaw - rest_yaw)
            ankle = p + q @ (settled if final else stepping)
            ankle.z = rest.translation.z - mw.translation.z
            rotation = q @ rest.to_quaternion()
            if ground is None:
                return ankle, rotation
            # Search along the heading for a whole-sole landing, never across a nosing.
            # A millimeter grid resolves even a foot nearly as long as the tread.
            forward = Vector((math.sin(yaw), -math.cos(yaw), 0))
            for j in range(351):
                for sign in ((1,) if j == 0 else (1, -1)):
                    candidate = ankle + forward * (j * 0.001 * sign)
                    fitted, qr, error, _height = ground.fit(candidate, rotation, sole)
                    if error < 0.002:
                        return fitted, qr
            raise ValueError("no whole-sole landing within 0.35 m; widen treads or adjust route")

        anchor = (initial[side].translation.copy(), initial[side].to_quaternion())
        if ground is not None:
            up = Vector((0, 0, 1))
            normal = anchor[1] @ (rest.to_quaternion().inverted() @ up)
            flat = normal.rotation_difference(up) @ anchor[1]
            p, q, error, _height = ground.fit(anchor[0], flat, sole)
            if error > 0.015:
                raise ValueError("initial foot straddles a terrain edge; move the character onto a flat tread")
            anchor = p, q
        # Initial supports start where the preceding animation actually left them.
        first_land = 2 if side == support else 1
        track, mask = [None]*n, [True]*n
        cursor = 0
        swings = []
        for step in range(first_land, len(boundaries), 2):
            land = boundaries[step]
            duration = land - boundaries[step-1]
            local_run = runs[land] if runs is not None else float(run)
            flight = max(1, round(0.2*duration)) if local_run > 0.5 else 0
            lift = max(0, boundaries[step-1] - flight)
            for i in range(cursor, lift + 1):
                track[i] = anchor
            # The last two steps gather at the final stance while the hips still glide.
            gather = arrive and step >= len(boundaries) - 2
            goal = landing(n - 1 if gather else land, duration, final=gather)
            swings.append((lift, land))
            swing = []
            for i in range(lift, land + 1):
                u = (i - lift) / (land - lift)
                w = _smoothstep(u)
                p = anchor[0].lerp(goal[0], w)
                p.z += (0.075 + 0.045*local_run) * math.sin(math.pi*u)**2
                track[i] = (p, anchor[1].slerp(goal[1], w))
                mask[i] = i in (lift, land)
                swing.append(i)
            if ground is not None:
                # Sample the entire swept sole, including between video frames. A smooth
                # envelope reaches >=3 cm over every edge, and zero at planted endpoints.
                needed = 0.0
                for k in range((land-lift)*4 + 1):
                    u = k / ((land-lift)*4)
                    w = _smoothstep(u)
                    p = anchor[0].lerp(goal[0], w)
                    p.z += (0.075 + 0.045*local_run) * math.sin(math.pi*u)**2
                    q = anchor[1].slerp(goal[1], w)
                    pts = [p + q @ v for v in sweep_sole]
                    gap = max(ground.sample(v.x, v.y)[0] - v.z for v in pts)
                    envelope = math.sin(math.pi*u)**0.5
                    if envelope > 1e-5:
                        clearance = 0.032 * min(1.0, min(u, 1-u)/0.12)
                        needed = max(needed, (gap + clearance)/envelope)
                for i in swing:
                    u = (i-lift)/(land-lift)
                    track[i][0].z += max(0, needed) * math.sin(math.pi*u)**0.5
            anchor, cursor = goal, land + 1
        for i in range(cursor, n):
            track[i] = anchor
        if roll and ground is None and swings:
            for i in _roll_feet(track, swings, sole_points=sole, rest=rest.to_quaternion(),
                                rest_yaw=rest_yaw, fps=fps, scale=roll_scale):
                mask[i] = False
        footfalls.extend((start + land, side) for _lift, land in swings)
        # An incoming locomotion clip can leave the first swinging foot airborne.
        mask[0] = True if ground is not None else abs(initial_height[side]) < 0.02
        targets[side] = track
        contacts[side] = [[start+a, start+b] for a, b in _intervals(mask, fill=0, min_len=1)]
    return targets, contacts, sorted(footfalls)


def _bake_motion(rig, start, samples, active, initial_feet, clip, speed, ground=None,
                 phases=None, runs=None, _world_route=False, gait=None):
    began = time.perf_counter()
    sc = bpy.context.scene
    fps = sc.render.fps / sc.render.fps_base
    gait = gait or {}
    half = gait.get("half") or _half_step(clip, fps, speed)
    amp = gait.get("amp", 1.0)
    weight = gait.get("weight", 0.0)
    support_sign = 1.0 if _support_side(rig, initial_feet) == "L" else -1.0
    end = start + len(samples) - 1
    prev = anim._sample_pose(rig, start)
    hips_name = anim.semantic_map(rig)["hips"]
    root_rest = (rig.matrix_world @ rig.data.bones[hips_name].matrix_local).translation
    root_heights = []
    settle = (max(1, len(samples)-1-active-max(4, round(fps/6)))
              if phases is not None else 2*half)
    if ground is None:
        query = GroundQuery()
        ground = query if query.objects else None
    if ground is not None:
        heights = smooth_heights([ground.sample(p.x, p.y)[0] for p, _yaw in samples], half//2)
        samples = [(Vector((p.x, p.y, z)), yaw) for (p, yaw), z in zip(samples, heights)]

    # The proxy is authored facing -Y (canonical); world route offsets and headings
    # are turned into that frame, and _drive turns the result back to the rig's yaw.
    turn = anim.rig_yaw(rig)
    undo = Matrix.Rotation(-turn, 3, "Z")

    def author(basic, lm, direct, carry):
        d, rest_deg = anim._dims(lm), anim._arm_rest_deg(lm)
        mw = basic.matrix_world
        basic_map = {b: b for b in anim.BASIC_BONES}
        rest_yaw = _yaw(_terrain_forward(basic, basic_map) if ground else
                        anim._facing(basic, basic_map).inverted() @ Vector((0, -1, 0)))
        previous = {}
        for i, (pos, yaw) in enumerate(samples):
            f = start + i
            sc.frame_set(f)
            phase = phases[i]*half if phases is not None else i
            # Footsteps land on half-step boundaries; with "align" the clip's widest
            # stride, lowest bob and full arm swing coincide with that double support.
            phase += gait.get("phase_offset", 0.0) * half
            rots, (_x, up, _fwd) = anim.CLIPS[clip][0](phase, 2*half, d, rest_deg, amp)
            if clip == "run" and runs is not None:
                walk, (_x, walk_up, _fwd) = anim.CLIPS["walk"][0](phase, 2*half, d, rest_deg, amp)
                rots = {b: [walk.get(b, (0, 0, 0))[k]*(1-runs[i])+v[k]*runs[i] for k in range(3)]
                        for b, v in rots.items()}
                up = walk_up*(1-runs[i]) + up*runs[i]
            w = _smoothstep(i / half) * (1 - _smoothstep((i - active) / settle))
            relaxed = anim._resolve(anim.RELAXED, rest_deg)
            rots = {b: [relaxed.get(b, (0, 0, 0))[k]*(1-w) + v[k]*w for k in range(3)]
                    for b, v in rots.items()}
            rots["hips"] = (0, 0, 0)
            if weight and phases is not None and ground is None:
                # In-place steps: lean the trunk over the supporting foot mid-step and
                # let the pelvis settle ~1.2 cm as each foot lands (weight transfer).
                lean = math.sin(math.pi * phases[i]) * support_sign * w
                spine = list(rots.get("spine", (0, 0, 0)))
                spine[2] -= 3.5 * weight * lean      # Z+ leans to the character's right
                rots["spine"] = spine
                up -= .012 * weight * (.5 + .5 * math.cos(2 * math.pi * phases[i]))
            if ground is not None:
                a, b = max(0, i-half), min(len(samples)-1, i+half)
                delta = samples[b][0] - samples[a][0]
                slope = math.atan2(delta.z, max(math.hypot(delta.x, delta.y), 0.01))
                rots["spine"] = (max(-3.0, min(7.0, math.degrees(slope)*0.2)), 0, 0)
                rots["toe.L"] = rots["toe.R"] = (0, 0, 0)
                up = pos.z - rig.matrix_world.translation.z + up*0.2*w - 0.035*_smoothstep(i/half)
                root_heights.append(root_rest.z + up)
            # _drive retargets offsets from the proxy rest onto the target rest.
            # Rigify's torso control need not share the proxy pelvis' rest head.
            offset = undo @ Vector((pos.x - root_rest.x, pos.y - root_rest.y, 0.0))
            anim._key_basic(basic, f, rots,
                            (offset.x, up if ground else up*w, -offset.y))
            bpy.context.view_layer.update()
            hp = basic.pose.bones["hips"]
            world = mw @ hp.matrix
            q = Quaternion((0, 0, 1), yaw - turn - rest_yaw) @ world.to_quaternion()
            anim._set_world_rot(basic, hp, q)
            anim._key_rot(hp, f, previous)

    info = anim._drive(rig, author, start, end, start, canonical=True)
    fade = anim._crossfade(rig, prev, start, end)
    if fade:
        info["crossfade"] = fade
    if fade or ground is not None or _world_route:
        # The route already starts at the preceding pose's heading and limits yaw
        # over time. Blending that moving heading from a frozen pose delays the turn,
        # then speeds it up to catch the route. Keep the planned world yaw while
        # retaining the crossfade's tilt and the rest of the blended body pose.
        smap = anim.semantic_map(rig)
        mw = rig.matrix_world
        rest = (mw @ rig.data.bones[hips_name].matrix_local).to_quaternion()
        forward = (_terrain_forward(rig, smap) if ground else
                   anim._facing(rig, smap).inverted() @ Vector((0, -1, 0)))
        previous = {}
        fix_frames = (start, end) if ground is not None or _world_route else fade["frames"]
        for f in range(fix_frames[0], fix_frames[1] + 1):
            sc.frame_set(f)
            hp = rig.pose.bones[hips_name]
            q = (mw @ hp.matrix).to_quaternion()
            heading = (_anatomical_yaw(rig) if _world_route else
                       _yaw(q @ rest.inverted() @ forward))
            correction = Quaternion((0, 0, 1), _angle(heading, samples[f - start][1]))
            loc = None
            if ground is not None:
                # Cached mannequin landmarks can precede an object transform. Retarget
                # still supplies the body pose; restore absolute world route coordinates
                # and heading on the final rig, independent of proxy rest orientation.
                pos = samples[f-start][0]
                loc = Vector((pos.x, pos.y, root_heights[f-start]))
            elif _world_route:
                # Paired approaches need absolute world routes even when a proxy's
                # rest orientation predates an object transform. Keep walk bob Z.
                pos = samples[f-start][0]
                loc = Vector((pos.x, pos.y, (mw @ hp.matrix).translation.z))
            anim._set_world_rot(rig, hp, correction @ q, loc)
            anim._key_rot(hp, f, previous)
            if ground is not None or _world_route:
                hp.keyframe_insert("location", frame=f, group=hips_name)
        bpy.context.view_layer.update()
    targets, contacts, footfalls = _footsteps(rig, samples, initial_feet, half, start, run=clip == "run",
                                   ground=ground, phases=phases, runs=runs,
                                   arrive=gait.get("arrive", False), roll=gait.get("roll", False),
                                   roll_scale=gait.get("roll_scale", 1.0), stance=gait.get("stance"),
                                   track_width=gait.get("track"))
    lock = foot_lock(rig, start, end, floor=0.0, contacts=contacts, foot_targets=targets,
                     ground=ground)
    info["foot_lock"] = {"contacts": contacts, "max_ik_error_m": lock["max_ik_error_m"],
                         "hips_lowered_max_m": lock["hips_lowered_max_m"]}
    info["footfalls"] = [{"frame": f, "side": side, "character": rig.name} for f, side in footfalls]
    if ground is not None:
        info["foot_lock"].update({k: lock[k] for k in
            ("ground_heights", "max_penetration_m", "min_swing_clearance_m")})
        info["terrain"] = {"objects": [o.name for o in ground.objects],
                           "gait": "run/walk" if clip == "run" and any(
                               ground.gait(p, yaw)[0] for p, yaw in samples) else clip,
                           "bake_seconds": round(time.perf_counter()-began, 3)}
    anim._extend_range(end)
    sc.frame_set(end)
    return {"armature": rig.name, "frames": [start, end], "next_start_frame": end + 1,
            "duration_seconds": round((end-start)/fps, 3),
            "max_turn_rate_deg_s": math.degrees(TURN_RATE), **info}


def _fk_dependencies(rig):
    """Bones needed to evaluate the generated Rigify FK controls, transitively."""
    pending = list(anim.semantic_map(rig).values())
    drivers = list(rig.animation_data.drivers) if rig.animation_data else []
    paths = [(pb.path_from_id(), pb.name) for pb in rig.pose.bones]

    def inputs(fc):
        names = []
        for v in fc.driver.variables:
            for t in v.targets:
                if t.id != rig:
                    continue
                if getattr(t, "bone_target", ""):
                    names.append(t.bone_target)
                else:
                    names.extend(name for path, name in paths if t.data_path.startswith(path))
        return names

    for fc in drivers:
        if not fc.data_path.startswith("pose.bones["):
            pending.extend(inputs(fc))
    needed = set()
    while pending:
        name = pending.pop()
        if name in needed or name not in rig.pose.bones:
            continue
        needed.add(name)
        pb = rig.pose.bones[name]
        if pb.parent:
            pending.append(pb.parent.name)
        for fc in drivers:
            if fc.data_path.startswith(pb.path_from_id()):
                pending.extend(inputs(fc))
        for c in pb.constraints:
            for target, subtarget in (("target", "subtarget"), ("pole_target", "pole_subtarget")):
                if getattr(c, target, None) == rig:
                    pending.append(getattr(c, subtarget, ""))
            if c.type == "ARMATURE":
                pending.extend(t.subtarget for t in c.targets if t.target == rig)
    return needed


def _bake(rig, start, samples, active, initial_feet, clip, speed, ground=None,
          phases=None, runs=None, _world_route=False, gait=None):
    """Generated FK rigs need bone evaluation, not repeated skin deformation."""
    began = time.perf_counter()
    hidden, muted, drivers = [], [], []
    kind = rig.get("c3d_rig_type", "")
    if ground is not None and kind == "rigify":
        # Hundreds of face/deform constraints do not feed the FK body controls.
        # Keep their dependency closure live and defer the rest until keys are baked.
        needed = _fk_dependencies(rig)
        prefixes = tuple(rig.pose.bones[b].path_from_id() for b in needed)
        if rig.animation_data:
            for fc in rig.animation_data.drivers:
                if (fc.data_path.startswith("pose.bones[") and
                        not fc.data_path.startswith(prefixes) and not fc.mute):
                    drivers.append(fc)
                    fc.mute = True
        for pb in rig.pose.bones:
            if pb.name not in needed:
                for c in pb.constraints:
                    if not c.mute:
                        muted.append(c)
                        c.mute = True
    if ground is not None and (kind in ("basic", "rigify") or kind.startswith("mpfb_")):
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH" and not obj.hide_viewport and any(
                    m.type == "ARMATURE" and m.object == rig for m in obj.modifiers):
                hidden.append(obj)
                obj.hide_viewport = True
    try:
        result = _bake_motion(rig, start, samples, active, initial_feet, clip, speed,
                              ground, phases, runs, _world_route, gait)
    finally:
        for fc in drivers:
            fc.mute = False
        for c in muted:
            c.mute = False
        for obj in hidden:
            obj.hide_viewport = False
        if hidden or muted or drivers:
            bpy.context.view_layer.update()
    if ground is not None:
        result["terrain"]["bake_seconds"] = round(time.perf_counter()-began, 3)
    return result


def _speed(value):
    if isinstance(value, bool) or not math.isfinite(value) or not 0.1 <= value <= 4.0:
        raise ValueError("speed must be finite and between 0.1 and 4.0")
    return float(value)


def _phase_offset(rig, feet):
    """Footsteps land on half-step boundaries and the support foot lands on even ones.

    Shift the clip a quarter cycle so its widest stride, lowest bob and full arm swing
    coincide with those double supports, with the landing leg's thigh forward.
    """
    return .5 if _support_side(rig, feet) == "L" else -.5


STANCE = .115                         # relaxed stop: ankle centres ~0.2 m apart at 1.75 m
TRACK = .09                           # walking step width: ankle centres ~0.16 m apart
TURN_STEP_S = .33                     # in-place turns take short, quick steps
GAZE_LIMIT = math.radians(60)         # anticipation never exceeds a comfortable head yaw
# (role, lead seconds, share of the heading change still to come at that lead).
# Eyes/head lead, the neck follows ~3 frames later and the chest ~6 frames later;
# the pelvis follows the route itself. A 90-degree corner peaks near 45 degrees of head yaw.
GAZE_CHAIN = (("chest", .25, .15), ("neck", .38, .30), ("head", .50, .45))


def _lead_gaze(rig, start, samples, fps):
    """Turn head, then neck, then chest toward the heading the body reaches later.

    The body still follows the route; only the upper chain anticipates bends,
    corner turns and the final facing, then releases as the body catches up.
    """
    smap = anim.semantic_map(rig)
    chain = [(rig.pose.bones[smap[r]], lead, w) for r, lead, w in GAZE_CHAIN
             if smap.get(r) and smap[r] in rig.pose.bones]
    n = len(samples)
    if not chain or n < 3:
        return {"lead_s": GAZE_CHAIN[-1][1], "max_deg": 0.0}
    width = max(1, round(.1 * fps))
    signals = []
    for bone, lead, share in chain:
        ahead = max(1, round(lead * fps))
        raw = [max(-GAZE_LIMIT, min(GAZE_LIMIT, _angle(samples[i][1], samples[min(n - 1, i + ahead)][1])))
               for i in range(n)]
        # Smooth twice with a short box so each joint eases in/out instead of snapping.
        for _ in range(2):
            raw = [sum(raw[max(0, i - width):i + width + 1]) / len(raw[max(0, i - width):i + width + 1])
                   for i in range(n)]
        signals.append([v * share for v in raw])
    head_total = [sum(sig[i] for sig in signals) for i in range(n)]
    peak = max(abs(v) for v in head_total)
    if peak < math.radians(.5):
        return {"lead_s": GAZE_CHAIN[-1][1], "max_deg": 0.0}
    sc = bpy.context.scene
    mw = rig.matrix_world
    previous = {}
    up = Vector((0, 0, 1))
    for i in range(n):
        if all(abs(sig[i]) < 1e-4 for sig in signals):
            continue
        frame = start + i
        sc.frame_set(frame)
        for (bone, _lead, _share), sig in zip(chain, signals):
            current = (mw @ bone.matrix).to_quaternion()
            anim._set_world_rot(rig, bone, Quaternion(up, sig[i]) @ current)
            bpy.context.view_layer.update()
            anim._key_rot(bone, frame, previous)
    bpy.context.view_layer.update()
    return {"lead_s": GAZE_CHAIN[-1][1], "max_deg": round(math.degrees(peak), 2)}


def _settle_chest(rig, brake, end, yaw, fps):
    """After the closing step the chest carries forward ~3.5 degrees, then rights itself."""
    name = anim.semantic_map(rig).get("chest") or anim.semantic_map(rig).get("spine")
    if not name or name not in rig.pose.bones:
        return
    sc = bpy.context.scene
    bone = rig.pose.bones[name]
    mw = rig.matrix_world
    forward = Vector((math.sin(yaw), -math.cos(yaw), 0))
    left = Vector((0, 0, 1)).cross(forward)
    lead, follow = max(1, round(.13 * fps)), max(1, round(.30 * fps))
    previous = {}
    for frame in range(max(sc.frame_start, brake - lead), end + 1):
        inertia = (_smoothstep((frame - brake + lead) / follow) *
                   (1 - _smoothstep((frame - brake + lead - follow) / max(1, end - brake + lead - follow))))
        if inertia <= 1e-4:
            continue
        sc.frame_set(frame)
        current = (mw @ bone.matrix).to_quaternion()
        anim._set_world_rot(rig, bone, Quaternion(left, math.radians(3.5 * inertia)) @ current)
        anim._key_rot(bone, frame, previous)
    bpy.context.view_layer.update()


@command("walk_path")
def walk_path(armature, points, clip="walk", start_frame=None, speed=1.0, face_end=None,
              avoid="auto", ignore=None, _world_route=False, _plant_at_arrival=False):
    """Walk/run through XY targets; static obstacle detours by default.

    avoid=False preserves the old route. auto/True plan only on intersection;
    blocked targets snap to free cells with warnings, unreachable paths raise.
    ignore names exclude objects and descendants, e.g. a sit_on approach chair.
    """
    ignored = validate_options(avoid, ignore)
    if clip not in ("walk", "run"):
        raise ValueError('clip must be "walk" or "run"')
    speed = _speed(speed)
    if not isinstance(points, (list, tuple)) or not 1 <= len(points) <= 1000:
        raise ValueError("points must contain 1..1000 floor XY points")
    destinations = [_point(p) for p in points]
    rig = anim._target(armature)
    saved_frame = bpy.context.scene.frame_current
    try:
        query = GroundQuery()
        ground = query if query.objects else None
        start, pos, yaw, feet = _start(rig, start_frame, ground)
        if _world_route:
            yaw = _anatomical_yaw(rig)
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
        planner = None
        avoided = False
        planning_seconds = 0.0
        if avoid is not False:
            began = time.perf_counter()
            bpy.context.scene.frame_set(start)
            planner = Planner(rig, route, query, ignored, start)
            planned = planner.plan(route, _curves)
            avoided = planner.detours > 0
            route = planned
            planning_seconds = time.perf_counter()-began
        keys, distance = _route(pos, yaw, route, velocity, ground, fps, speed,
                                planner.curve_free if avoided else None)
        if face_end is not None:
            target = _target_yaw(face_end, route[-1], start + math.ceil(keys[-1][0]*fps), keys[-1][2])
            _turn(keys, target, terrain=ground is not None)
        # Flat walks use stature-scaled cadence, heel-to-toe feet and an arrival that
        # finishes stepping as the body settles. Terrain keeps whole-sole treads.
        # (_plant_at_arrival is retained for callers; flat ground always arrives.)
        flat = ground is None
        half = (_walk_half_step(d, velocity, fps, speed) if flat and clip == "walk"
                else _half_step(clip, fps, speed))
        phases = runs = None
        if not flat:
            samples, active, phases, runs = _terrain_samples(keys, fps, clip, speed, ground)
        else:
            samples, active, phases = _arrival_samples(keys, fps, half)
        gait = {"half": half, "arrive": flat, "roll": flat and clip == "walk",
                "phase_offset": _phase_offset(rig, feet), "stance": STANCE * d["H"],
                "track": TRACK * d["H"] if flat else None}
        navigation = (planner.report(route, samples, avoided) if planner else
                      {"avoided": False, "detours": 0, "path_points": [list(p)[:2] for p in route],
                       "clearance_m": None, "warnings": []})
        navigation["planning_seconds"] = round(planning_seconds, 6)
        result = _bake(rig, start, samples, active, feet, clip, speed, ground=ground,
                       phases=phases, runs=runs, _world_route=_world_route, gait=gait)
        result["gaze_lead"] = _lead_gaze(rig, start, samples, fps)
        footfalls = result["footfalls"]
        if flat and footfalls and footfalls[-1]["frame"] < result["frames"][1]:
            _settle_chest(rig, footfalls[-1]["frame"], result["frames"][1], samples[-1][1], fps)
        return {**result, "clip": clip, "distance_m": round(distance, 4),
                "natural_speed_m_s": round(velocity, 3), "destination": list(route[-1])[:2],
                **navigation}
    finally:
        bpy.context.scene.frame_set(saved_frame)


@command("turn_to")
def turn_to(armature, target, start_frame=None, avoid="auto", ignore=None, _world_route=False):
    """Turn in place; reject a blocked body envelope unless avoid=False or ignored."""
    ignored = validate_options(avoid, ignore)
    rig = anim._target(armature)
    saved_frame = bpy.context.scene.frame_current
    try:
        query = GroundQuery()
        ground = query if query.objects else None
        start, pos, yaw, feet = _start(rig, start_frame, ground)
        if _world_route:
            yaw = _anatomical_yaw(rig)
        planner = None
        planning_seconds = 0.0
        if avoid is not False:
            began = time.perf_counter()
            bpy.context.scene.frame_set(start)
            planner = Planner(rig, [pos], query, ignored, start)
            planner.plan([pos], _curves, escape=False)
            planning_seconds = time.perf_counter()-began
        heading = _target_yaw(target, pos, start, yaw)
        keys = [(0.0, pos, yaw)]
        _turn(keys, heading)
        fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
        flat = ground is None
        gait = {"phase_offset": _phase_offset(rig, feet)}
        if flat:
            # Short quick steps with little leg/arm swing, a light heel roll, and no idle
            # tail: the last two steps gather as the rotation finishes.
            d = anim._dims(anim._rig_landmarks(rig, anim.semantic_map(rig)))
            half = max(2, round(TURN_STEP_S * fps))
            samples, active, phases = _arrival_samples(keys, fps, half)
            gait.update(half=half, arrive=True, roll=True, roll_scale=.5, amp=.35, weight=1.0,
                        stance=STANCE * d["H"], track=STANCE * d["H"])
        else:
            half = _half_step("walk", fps, 1.0)
            samples, active = _samples(keys, fps, half)
            phases = None
        navigation = (planner.report([pos], samples, False) if planner else
                      {"avoided": False, "detours": 0, "path_points": [list(pos)[:2]],
                       "clearance_m": None, "warnings": []})
        navigation["planning_seconds"] = round(planning_seconds, 6)
        result = _bake(rig, start, samples, active, feet, "walk", 1.0, ground=ground,
                       phases=phases, _world_route=_world_route, gait=gait)
        result["gaze_lead"] = _lead_gaze(rig, start, samples, fps)
        return {**result, "distance_m": 0.0, "turn_degrees": round(math.degrees(_angle(yaw, heading)), 3),
                **navigation}
    finally:
        bpy.context.scene.frame_set(saved_frame)
