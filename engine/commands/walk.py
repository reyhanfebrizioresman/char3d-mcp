"""Floor navigation: smooth root routes, rate-limited turns and planted footsteps."""
import bisect
import math
import time

import bpy
from mathutils import Quaternion, Vector

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


def _footsteps(rig, samples, initial, half, start, run=False, ground=None, phases=None, runs=None):
    """Alternate planted supports and lifted swings; contacts freeze position AND yaw."""
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
    targets, contacts = {}, {}
    for side in "LR":
        rest = mw @ rig.data.bones[smap[f"foot.{side}"]].matrix_local
        sole = _sole_points(rig, legs[side], mw.translation.z)
        sweep_sole = sole_footprint(sole, rest.to_quaternion()) if ground is not None else sole
        offset = rest.translation - root
        offset.z = 0.0

        def landing(frame, duration):
            p, yaw = samples[min(frame + (duration-flight)//2, n - 1)]
            q = Quaternion((0, 0, 1), yaw - rest_yaw)
            ankle = p + q @ offset
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
        for step in range(first_land, len(boundaries), 2):
            land = boundaries[step]
            duration = land - boundaries[step-1]
            local_run = runs[land] if runs is not None else float(run)
            flight = max(1, round(0.2*duration)) if local_run > 0.5 else 0
            lift = max(0, boundaries[step-1] - flight)
            for i in range(cursor, lift + 1):
                track[i] = anchor
            goal = landing(land, duration)
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
        # An incoming locomotion clip can leave the first swinging foot airborne.
        mask[0] = True if ground is not None else abs(initial_height[side]) < 0.02
        targets[side] = track
        contacts[side] = [[start+a, start+b] for a, b in _intervals(mask, fill=0, min_len=1)]
    return targets, contacts


def _bake_motion(rig, start, samples, active, initial_feet, clip, speed, ground=None,
                 phases=None, runs=None, _world_route=False):
    began = time.perf_counter()
    sc = bpy.context.scene
    fps = sc.render.fps / sc.render.fps_base
    half = _half_step(clip, fps, speed)
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
            rots, (_x, up, _fwd) = anim.CLIPS[clip][0](phase, 2*half, d, rest_deg, 1.0)
            if clip == "run" and runs is not None:
                walk, (_x, walk_up, _fwd) = anim.CLIPS["walk"][0](phase, 2*half, d, rest_deg, 1.0)
                rots = {b: [walk.get(b, (0, 0, 0))[k]*(1-runs[i])+v[k]*runs[i] for k in range(3)]
                        for b, v in rots.items()}
                up = walk_up*(1-runs[i]) + up*runs[i]
            w = _smoothstep(i / half) * (1 - _smoothstep((i - active) / settle))
            relaxed = anim._resolve(anim.RELAXED, rest_deg)
            rots = {b: [relaxed.get(b, (0, 0, 0))[k]*(1-w) + v[k]*w for k in range(3)]
                    for b, v in rots.items()}
            rots["hips"] = (0, 0, 0)
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
            anim._key_basic(basic, f, rots,
                            (pos.x - root_rest.x, up if ground else up*w, root_rest.y - pos.y))
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
    targets, contacts = _footsteps(rig, samples, initial_feet, half, start, run=clip == "run",
                                   ground=ground, phases=phases, runs=runs)
    lock = foot_lock(rig, start, end, floor=0.0, contacts=contacts, foot_targets=targets,
                     ground=ground)
    info["foot_lock"] = {"contacts": contacts, "max_ik_error_m": lock["max_ik_error_m"],
                         "hips_lowered_max_m": lock["hips_lowered_max_m"]}
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
          phases=None, runs=None, _world_route=False):
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
                              ground, phases, runs, _world_route)
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


@command("walk_path")
def walk_path(armature, points, clip="walk", start_frame=None, speed=1.0, face_end=None,
              avoid="auto", ignore=None, _world_route=False):
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
        half = _half_step(clip, fps, speed)
        phases = runs = None
        if ground is not None:
            samples, active, phases, runs = _terrain_samples(keys, fps, clip, speed, ground)
        else:
            samples, active = _samples(keys, fps, half)
        navigation = (planner.report(route, samples, avoided) if planner else
                      {"avoided": False, "detours": 0, "path_points": [list(p)[:2] for p in route],
                       "clearance_m": None, "warnings": []})
        navigation["planning_seconds"] = round(planning_seconds, 6)
        result = _bake(rig, start, samples, active, feet, clip, speed, ground=ground,
                       phases=phases, runs=runs, _world_route=_world_route)
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
        half = _half_step("walk", fps, 1.0)
        samples, active = _samples(keys, fps, half)
        navigation = (planner.report([pos], samples, False) if planner else
                      {"avoided": False, "detours": 0, "path_points": [list(pos)[:2]],
                       "clearance_m": None, "warnings": []})
        navigation["planning_seconds"] = round(planning_seconds, 6)
        result = _bake(rig, start, samples, active, feet, "walk", 1.0, ground=ground,
                       _world_route=_world_route)
        return {**result, "distance_m": 0.0, "turn_degrees": round(math.degrees(_angle(yaw, heading)), 3),
                **navigation}
    finally:
        bpy.context.scene.frame_set(saved_frame)
