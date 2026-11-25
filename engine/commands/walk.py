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
from ..walk_gait import (DOUBLE_SUPPORT, LOADING_END, MID_STANCE_END, TOE_OFF, SPRING_OMEGA,
                         momentum, step_variation, support_headings, spring_step, knee_velocity_limit, stride_time_map, phase_edges)

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


def _turn(keys, yaw, terrain=False, quick=False):
    t, pos, old = keys[-1]
    delta = _angle(old, yaw)
    if abs(delta) < 1e-6:
        return
    # quick: a deliberate in-place turn_to (180 deg in ~1.4 s, film/mocap reference);
    # route corners keep the 100 deg/s heading limit.
    duration = (max(0.3, abs(delta) / TURN_RATE + 0.15) if terrain else
                max(.45, QUICK_TURN_S * abs(delta) / math.pi) if quick else
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


def _route(pos, yaw, points, velocity, ground=None, fps=24, speed=1.0, safe=None, brake=None):
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
            decel = brake or accel     # brake: m/s^2 for a short, deliberate stop
            v = min(limits[i], limits[i-1], math.sqrt(2*accel*max(mid, 0.001)),
                    math.sqrt(2*decel*max(lengths[-1] - mid, 0.001)))
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


def _arrival_samples(keys, fps, half_step, count=None, last_weight=1.0, brake=None, vary=False, hold_s=.25,
                     close_after=False, rhythm_seed=None):
    """Finish stepping with the body instead of after it.

    The lead foot lands at the final stance and the trailing foot closes beside it
    shortly before the decelerating hips stop; the body then glides over both
    planted feet. Steps are spread evenly over the travel (shorter as it slows);
    count fixes the number of steps and last_weight lengthens the closing step. brake
    (frames) makes the last two steps quick braking steps with a shorter glide.
    Returns samples, active frame, half-step phases and the mean step length in frames.
    """
    samples, arrival = _samples(keys, fps, half_step)
    # Delayed toe-off must not force the lead braking foot far ahead of the
    # decelerating root. Close nearer standstill, retaining time to load both feet.
    glide = max(2, round((.10 if brake else .3) * fps))
    hold = max(4, round(fps * hold_s))
    shortest = max(2, round(.6 * half_step))
    final = max(arrival - glide, 2 * shortest)
    if count is None:
        count = max(2, min(round(final / half_step), final // shortest))
    count = max(2, min(count, final // 2))
    if close_after:
        # A pivot must finish its heading before BOTH closing footfalls.
        # Otherwise the inside foot must land toe-in to face the final yaw,
        # or remain sideways after the body finishes rotating around it.
        boundaries = [round(arrival*i/count) for i in range(count+1)]
        boundaries += [arrival+shortest, arrival+2*shortest]
        final = boundaries[-1]
        count += 2
    length = max(arrival, final + (0 if close_after else glide)) + hold + 1
    samples = (samples + [samples[-1]] * length)[:length]
    if close_after:
        pass
    elif brake and final > 2 * brake + shortest:
        # Cruise steps fill the travel up to the two quick braking steps.
        cruise = final - 2 * brake
        # Never lengthen cruise strides to pay for double support in braking.
        boundaries = list(range(0, cruise, half_step))
        # A tiny residual otherwise creates two compressed shuffles and a
        # deep anticipatory hip drop. Absorb <=2 frames into a long cruise
        # step; otherwise balance the final two transition intervals.
        minimum = min(6, half_step)
        remainder = cruise-boundaries[-1]
        if remainder < minimum and len(boundaries)>1:
            if half_step>=10 and remainder<=2:
                boundaries.pop()
            else:
                boundaries[-1] = round((boundaries[-2]+cruise)/2)
        boundaries += [cruise, cruise + brake, final]
        count = len(boundaries) - 1
    else:
        weights = [1.0] * (count - 1) + [last_weight]
        edges = [0.0]
        for weight in weights:
            edges.append(edges[-1] + weight)
        boundaries = [round(final * e / edges[-1]) for e in edges]
    phases = [float(count)] * length
    for step, (first, last) in enumerate(zip(boundaries, boundaries[1:])):
        for frame in range(first, last):
            phases[frame] = step + (frame - first) / (last - first)
    if vary and rhythm_seed is not None and not close_after:
        # Continuous cycle durations, common to the two feet. Normalize the
        # duration factors to preserve the cruise/brake boundary and destination.
        # <=0.9% raw deviations yield <1.82% after normalization. The engine
        # samples continuous time at its scene FPS, including subframe root and
        # phase lookahead; actual strike frames retain the unavoidable rounding.
        times, _cycles = stride_time_map(boundaries,len(samples),rhythm_seed)
        original_samples, original_phases = list(samples),list(phases)
        for frame,t in enumerate(times[:-1]):
            j = min(len(samples)-2,int(t)); w = t-j
            samples[frame] = (original_samples[j][0].lerp(original_samples[j+1][0],w),
                original_samples[j][1]+_angle(original_samples[j][1],original_samples[j+1][1])*w)
            phases[frame] = original_phases[j]+(original_phases[j+1]-original_phases[j])*w
    if vary and rhythm_seed is not None:
        # Time warping also changes angular velocity. Project the heading onto
        # the route rate bound before sharing yaw budgets with supports.
        angles = [samples[0][1]]
        for _,yaw in samples[1:]: angles.append(angles[-1]+_angle(angles[-1],yaw))
        first_yaw,last_yaw=angles[0],angles[-1]
        cap=TURN_RATE/fps
        for _ in range(2):
            angles[0]=first_yaw
            for i in range(1,len(angles)):
                angles[i]=max(angles[i-1]-cap,min(angles[i-1]+cap,angles[i]))
            angles[-1]=last_yaw
            for i in range(len(angles)-2,-1,-1):
                angles[i]=max(angles[i+1]-cap,min(angles[i+1]+cap,angles[i]))
        samples=[(p,yaw) for (p,_),yaw in zip(samples,angles)]
    return samples, max(0, final - half_step), phases, max(2, round(final / count))


def _walk_half_step(d, velocity, fps, speed):
    """Stature-sized steps, bounded by native leg reach; speed scales cadence."""
    natural = velocity / speed
    return max(2, round(fps * min(.37*d["H"], .75*d["leg"]) / natural / speed))


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
HEEL_RISE = math.radians(52)        # heel up at toe-off; the toe joint stays planted


def _pitched(position, rotation, pivot, axis, angle):
    """Rotate a foot (ankle position, world rotation) about a sole point in foot space."""
    turn = Quaternion(axis, angle)
    point = position + rotation @ pivot
    return point + turn @ (position - point), turn @ rotation


def _roll_feet(track, swings, sole_points, rest, rest_yaw, fps, scale=1.0, ball_pivot=None, headings=None):
    """Heel strike -> flat foot -> ball-joint push, with a planted distal toe.

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
    pose, toe_roll, pitches = {}, {}, {}
    for begin, end, strikes, rises in stances:
        length = end - begin
        if length <= 0:
            continue
        # Stance occupies 60% of a cycle. Loading is 0..10%, the heel starts
        # rising after 43% (late terminal), retaining reach before contralateral landing.
        # The toe then supplies support through 50..60% pre-swing.
        strike_frames = max(1, round(length * LOADING_END / TOE_OFF))
        # A twisting support uses a lower, longer push than straight propulsion.
        # Predict its yaw excursion over this exact stance, shared with landings.
        twisting = (min(1.0, abs(_angle(headings[begin], headings[end]))/math.radians(45))
                    if headings else 0.0)
        rise_frames = max(1, round(length * (TOE_OFF - (.43-.13*twisting)) / TOE_OFF))
        # A walk starting with both feet flat has only the initial overlap to
        # prepare its first push. Do not squeeze a full heel rise into 1–2 frames.
        stance_rise = (rise if strikes else min(rise, math.radians(22)*scale) * min(1.0, length/(.20*fps)))
        stance_rise *= 1-.5*twisting
        for i in range(begin, end + 1):
            p, q = flat[i]
            angle = 0.0
            if strikes and i - begin < strike_frames:
                angle = strike * (1 - _smoothstep((i - begin) / strike_frames))
                pose[i] = _pitched(p, q, heel, axis(i), angle)
            elif rises and end - i < rise_frames:
                push = 1-(end-i)/rise_frames
                # Reserve the final seventeen degrees for the final ball push, after
                # opposite loading, rather than bending terminal stance earlier.
                base_rise = min(stance_rise, math.radians(35)*scale*(1-.5*twisting))
                angle = (-base_rise*_smoothstep(push)
                         -(stance_rise-base_rise)*_smoothstep((push-.7)/.3))
                pivot = ball_pivot if ball_pivot is not None else toe
                pose[i] = _pitched(p, q, pivot, axis(i), angle)
                if ball_pivot is not None:
                    toe_roll[i] = Quaternion(axis(i), -angle)
            else:
                pose[i] = (p.copy(), q.copy())
            pitches[i] = angle
    for lift, land in swings:
        if land <= lift:
            continue
        started = lift > 0 or lift in pose and pose[lift][1] != flat[lift][1]
        start_offset = pose[lift][0] - flat[lift][0] if started and lift in pose else Vector()
        start_angle = pitches.get(lift, 0.0) if started else 0.0
        end_offset = pose[land][0] - flat[land][0] if land in pose else Vector()
        for i in range(lift + 1, land):
            u = (i - lift) / (land - lift)
            angle = (start_angle * (1 - _smoothstep(u / .4)) +
                     strike * _smoothstep((u - .45) / .55))
            p, q = flat[i]
            w = _smoothstep(u)
            turn = Quaternion(axis(i), angle)
            pose[i] = (p + start_offset.lerp(end_offset, w), turn @ q)
            if ball_pivot is not None and angle < 0:
                toe_roll[i] = Quaternion(axis(i), -angle)
    for i, value in pose.items():
        track[i] = value
    # Rolling frames touch the floor on an edge; "contacts" stay the flat, fixed foot.
    return {i for i, (p, q) in pose.items() if q != flat[i][1]}, toe_roll


def _release_lookahead(rig, smap, distance, duration):
    """Fit symmetric footprints to the native leg/ball geometry at release.

    A fixed fraction of a step ignores the foot/leg ratio and the rounded
    opposite-loading interval. Solve the two-support triangle instead; bones
    and support rotations are never edited to impose a joint angle.
    """
    if distance < .01:
        return .5
    mw = rig.matrix_world
    forward = _terrain_forward(rig, smap)
    up = Vector((0,0,1)); axis = forward.cross(up)
    root = mw @ rig.data.bones[smap['hips']].head_local
    measurements=[]
    for side in 'LR':
        h,k,a = [(mw @ rig.data.bones[smap[b+'.'+side]].matrix_local).translation
                 for b in ('thigh','shin','foot')]
        toe=smap.get('toe.'+side)
        if not toe:
            return .5
        ball=mw @ rig.data.bones[toe].head_local
        roll=Quaternion(axis,-HEEL_RISE)
        offset=(ball-a)-roll @ (ball-a)
        measurements.append(((h-k).length,(k-a).length,(h-root).dot(forward),
                             offset.dot(forward),offset.z))
    l1,l2,hip_forward,roll_forward,roll_up = [sum(v[i] for v in measurements)/2 for i in range(5)]
    delay=max(0,round(.2*duration))/duration
    u=delay/2
    knots=((0,9),(.05,18),(.10,11),(.20,7))
    front=11
    for (a,x),(b,y) in zip(knots,knots[1:]):
        if u<=b:
            front=x+(y-x)*_smoothstep((u-a)/(b-a));break
    front_reach=l1*l1+l2*l2+2*l1*l2*math.cos(math.radians(front))
    rear_reach=l1*l1+l2*l2+2*l1*l2*math.cos(math.radians(37.5))
    def reach(fraction):
        x_front=(fraction-delay)*distance-hip_forward
        x_rear=(fraction-1-delay)*distance+roll_forward-hip_forward
        height=math.sqrt(max(0,front_reach-x_front*x_front))
        return x_rear*x_rear+(height-roll_up)**2
    lo,hi=.30,.70
    for _ in range(32):
        mid=(lo+hi)/2
        if reach(mid)>rear_reach:lo=mid
        else:hi=mid
    return (lo+hi)/2


def _footsteps(rig, samples, initial, half, start, run=False, ground=None, phases=None, runs=None,
               arrive=False, roll=False, roll_scale=1.0, stance=None, track_width=None,
               toe_targets=None, support_events=None, toe_out=0.0, cruise=False):
    """Alternate planted supports and lifted swings; contacts freeze position AND yaw.

    arrive lands the last two steps side by side at the final stance (ankle centres at
    most `stance` m apart). roll adds a heel strike and an articulated ball-joint
    push (rigid toe-edge fallback), on flat ground only, scaled by roll_scale. track narrows the ankle
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
    boundaries = (([i for i in phase_edges(phases) if i<=stop] if ground is None and not run else
                   [0]+[i for i in range(1,stop+1) if int(phases[i])>int(phases[i-1])])
                  if phases is not None else list(range(0, stop+1, half)))
    flight = max(1, round(0.2*half)) if run else 0
    legs, _smap = _legs(rig)
    initial_height = {s: min((initial[s] @ p).z for p in _sole_points(rig, legs[s], 0.0))
                      for s in "LR"}
    # A fresh native MPFB pose can have its outsole below the barefoot plane.
    # Chained navigation already has calibrated feet and needs no second lift.
    sole_lift = float(rig.get('c3d_sole_clearance_m', 0.0))
    initial_lift = max(0.0, -min(initial_height.values())) if sole_lift else 0.0
    initial_height = {s: z+initial_lift for s, z in initial_height.items()}
    support = min(initial_height, key=initial_height.get)
    targets, contacts, footfalls = {}, {}, []
    cruise_gait = cruise
    lookaheads = {}
    cruise = max(((b[0] - a[0]).length for a, b in zip(samples, samples[1:])), default=0.0)
    for side in "LR":
        rest = mw @ rig.data.bones[smap[f"foot.{side}"]].matrix_local
        sole = _sole_points(rig, legs[side], mw.translation.z)
        # Calibrate from the anatomical heel-to-toe landmark axis, not bone
        # yaw: basic, Rigify and MPFB can have different rest foot directions.
        sole_axis = rest.to_quaternion() @ (sole[-1] - sole[0])
        sole_yaw = _yaw(sole_axis)
        sweep_sole = sole_footprint(sole, rest.to_quaternion()) if ground is not None else sole
        offset = rest.translation - root
        offset.z = 0.0
        forward = Vector((math.sin(rest_yaw), -math.cos(rest_yaw), 0))
        lateral = Vector((0, 0, 1)).cross(forward)
        if cruise:
            # Rest ankles can sit forward of the pelvis. Footprint lookahead
            # already centres the stance; adding that offset overreaches at landing.
            offset -= forward * offset.dot(forward)

        def narrowed(limit):
            # A rest A-pose stands wider than people walk or stop; narrow toward `limit`.
            width = offset.dot(lateral)
            if not limit or abs(width) <= limit / 2:
                return offset.copy()
            return offset - lateral * (width - math.copysign(limit / 2, width))

        settled = narrowed(stance)

        def stepping(index):
            """Narrow track on straight cruising; open toward the stance in bends/slowing."""
            if not track_width or not stance:
                return narrowed(track_width)
            a, b = max(0, index - half), min(n - 1, index + half)
            turning = abs(_angle(samples[a][1], samples[b][1])) / math.radians(35)
            pace = (samples[b][0] - samples[a][0]).length / max(1, b - a) / cruise if cruise else 1.0
            slowing = (.65 - pace) / .4
            mix = max(0.0, min(1.0, max(turning, slowing)))
            return narrowed(track_width + (stance - track_width) * mix)

        def landing(frame, duration, final=False, touchdown=None):
            # Place cruise feet slightly behind the stance midpoint so the pelvis
            # progresses over the rear leg before opposite loading. This combines
            # with a late ball-joint push, rather than changing any knee target.
            # Runs and whole-sole terrain retain their previous placement.
            if cruise_gait and duration not in lookaheads:
                lookaheads[duration] = _release_lookahead(rig, smap, cruise*duration, duration)
            fraction = lookaheads.get(duration, .48)
            ahead = ((duration-flight)//2 if flight else
                     fraction*duration if cruise_gait else
                     round((.48 if cruise else TOE_OFF)*duration))
            position = min(frame + ahead, n - 1)
            index = int(position)
            p, yaw = samples[index]
            if position > index:
                other_p, other_yaw = samples[index+1]
                p = p.lerp(other_p, position-index)
                yaw += _angle(yaw, other_yaw)*(position-index)
            q = Quaternion((0, 0, 1), yaw - rest_yaw)
            ankle = p + q @ (settled if final else stepping(index))
            if cruise and not final:
                # Check both heel strike and the upcoming support heading. A
                # curved lookahead can otherwise put an outside foot across the
                # current lane even though its offset at the future root is correct.
                sign = 1 if side == "L" else -1
                for check in (frame, index):
                    centre, heading = samples[min(check, n-1)]
                    left = Vector((math.cos(heading), math.sin(heading), 0))
                    gap = sign*(ankle-centre).dot(left)
                    minimum = (track_width or 0)*.45
                    if gap < minimum:
                        ankle += left*(sign*(minimum-gap))
            ankle.z = rest.translation.z - mw.translation.z + sole_lift
            # At -Y facing, L is +X: positive world yaw is left toe-out.
            # Apply one absolute anatomical correction at landing; the anchor
            # stays fixed until the next swing, including through route turns.
            # Position looks ahead, orientation uses touchdown's route heading.
            # Looking ahead in yaw can turn the inside foot anatomically inward.
            heading = samples[min(frame if touchdown is None else touchdown, n-1)][1]
            foot_yaw = heading + (toe_out if side == "L" else -toe_out)
            if final:
                # Braking feet may land parallel. Choose the outward edge of
                # touchdown/final headings so neither endpoint becomes toe-in.
                delta = _angle(heading, samples[-1][1])
                foot_yaw = heading + (max(0., delta) if side == "L" else min(0., delta))
            rotation = (Quaternion((0, 0, 1), _angle(sole_yaw, foot_yaw)) @ rest.to_quaternion()
                        if toe_out else q @ rest.to_quaternion())
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
        anchor[0].z += initial_lift
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
            # Walk: rear toe leaves 10% of a full cycle AFTER the other heel lands.
            # Runs retain flight; whole-sole terrain walks retain the same support overlap.
            delay = min(duration-2, max(0, round(2*DOUBLE_SUPPORT*duration))) if local_run <= .5 else 0
            if cursor == 0 and ground is None and initial_height[side] > .02:
                # A chained clip may already have this foot in flight. Finish
                # that swing immediately; there is no rear support to prolong.
                delay = 0
            lift = max(0, boundaries[step-1] - flight + delay)
            for i in range(cursor, lift + 1):
                track[i] = anchor
            # The last two steps gather at the final stance while the hips still glide.
            gather = arrive and step >= len(boundaries) - 2
            goal = landing(n - 1 if gather else land, duration, final=gather, touchdown=land)
            swings.append((lift, land))
            if support_events is not None:
                support_events.append({"side": side, "lift": start+lift, "land": start+land,
                                       "opposite_land": start+boundaries[step-1]})
            swing = []
            # Quick braking/closing steps are low shuffles, not a full-height
            # swing compressed into a few frames (which snaps the IK knee).
            swing_height = ((0.045 + 0.075*local_run) *
                            (1.0 if local_run > .5 else min(1.0, ((land-lift)/(.36*fps))**2)))
            for i in range(lift, land + 1):
                u = (i - lift) / (land - lift)
                w = _smoothstep(u)
                p = anchor[0].lerp(goal[0], w)
                p.z += swing_height * math.sin(math.pi*u)**2
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
                    p.z += swing_height * math.sin(math.pi*u)**2
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
            toe_name = legs[side].get("toe")
            pivot = (rest.inverted() @ (mw @ rig.data.bones[toe_name].head_local)
                     if toe_name and toe_targets is not None else None)
            rolling, toes = _roll_feet(track, swings, sole_points=sole, rest=rest.to_quaternion(),
                                     rest_yaw=rest_yaw, fps=fps, scale=roll_scale, ball_pivot=pivot,
                                     headings=[yaw for _pos, yaw in samples])
            if toe_targets is not None:
                toe_targets[side] = toes
            for i in rolling:
                mask[i] = False
        footfalls.extend((start + land, side) for _lift, land in swings)
        # An incoming locomotion clip can leave the first swinging foot airborne.
        mask[0] = True if ground is not None else abs(initial_height[side]) < 0.02
        if not mask[0]:
            for i in range((swings[0][0]+1) if swings else n):
                mask[i] = False
        targets[side] = track
        contacts[side] = [[start+a, start+b] for a, b in _intervals(mask, fill=0, min_len=1)]
    return targets, contacts, sorted(footfalls)


def _relax_fingers(rig, start, samples, phases, half):
    """Ease unanimated, unoccupied fingers into a relaxed walking hand."""
    from .fingers import HandRig
    from .talk import _fcurves
    hands = HandRig(rig)
    action = rig.animation_data.action if rig.animation_data else None
    authored = {fc.data_path for fc in _fcurves(action)} if action else set()
    occupied = {o.get("c3d_hold_hand") for o in bpy.context.scene.objects
                if o.get("c3d_hold_character") == rig.name}
    base, goals = {}, {}
    bpy.context.scene.frame_set(start)
    for side in hands.fingers:
        if ("left" if side == "L" else "right") in occupied:
            continue
        for name, q in hands.rotations(side, "relaxed").items():
            if any(path.startswith('pose.bones["'+name+'"]') for path in authored):
                continue
            base[name] = rig.pose.bones[name].matrix_basis.to_quaternion()
            goals[name] = q
    if not goals:
        return
    previous = {}
    for i in range(len(samples)):
        bpy.context.scene.frame_set(start+i)
        w = _smoothstep(i/max(1,half))
        # The cadence signal vanishes with the final phase hold.
        moving = min(1.0, max(0.0, phases[min(i+1,len(phases)-1)]-phases[max(0,i-1)])*half/2)
        curl = 1+.025*math.sin(math.pi*phases[i])*moving
        for name in goals:
            bone = rig.pose.bones[name]
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = base[name].slerp(Quaternion(goals[name].axis, goals[name].angle*curl),w)
            anim._key_rot(bone,start+i,previous)


def _articulate_toes(rig, start, targets, toe_roll):
    """Counter the heel rise at the ball joint, keeping the distal toe flat.

    Author after ankle IK so its foot rotation cannot drag the toe through the
    floor. Missing toe bones retain the rigid toe-edge pivot. Explicit zero keys
    outside the roll prevent interpolation leaking into subsequent flat contacts.
    """
    smap = anim.semantic_map(rig)
    mw = rig.matrix_world
    previous = {}
    joints = []
    for side, rolls in toe_roll.items():
        toe, foot = smap.get(f"toe.{side}"), smap[f"foot.{side}"]
        if not toe or not rolls:
            continue
        relative = ((mw @ rig.data.bones[foot].matrix_local).to_quaternion().inverted() @
                    (mw @ rig.data.bones[toe].matrix_local).to_quaternion())
        joints.append((side, toe, foot, relative, rolls))
    if not joints:
        return
    for i in range(len(next(iter(targets.values())))):
        bpy.context.scene.frame_set(start+i)
        for side, toe, foot, relative, rolls in joints:
            q = (mw @ rig.pose.bones[foot].matrix).to_quaternion()
            anim._set_world_rot(rig, rig.pose.bones[toe], rolls.get(i, Quaternion()) @ q @ relative)
            anim._key_rot(rig.pose.bones[toe], start+i, previous)
    bpy.context.view_layer.update()


def _stance_height(rig, start, targets, events, toe_roll=None, speed=1.0):
    """Vault over support, allowing loading flexion without a future swing drop.

    Fit the pelvis from a bent supporting leg and both legs' reach. Smooth its
    height before fitting the airborne knee arc; a late swing must not drag the
    support knee down. Ankle positions/rolls stay fixed throughout every contact.
    """
    if not events:
        return
    smap = anim.semantic_map(rig)
    mw = rig.matrix_world
    # Minimum airborne ankle height from the actual articulated sole, rather
    # than the inherited swing arc (which itself may cause the braking pop).
    legs, _ = _legs(rig)
    clearance_z = {}
    for side in 'LR':
        sole = _sole_points(rig, legs[side], 0)
        rest = mw @ rig.data.bones[smap['foot.'+side]].matrix_local
        toe = smap.get('toe.'+side)
        if toe:
            toe_rest = mw @ rig.data.bones[toe].matrix_local
            origin = rest.inverted() @ toe_rest.translation
            relative = rest.to_quaternion().inverted() @ toe_rest.to_quaternion()
            distal = [toe_rest.inverted() @ (rest @ p) for p in sole[1:]]
        values = []
        for i, (_p, q) in enumerate(targets[side]):
            offsets = [(q @ p).z for p in sole]
            if toe:
                tq = (toe_roll or {}).get(side,{}).get(i,Quaternion()) @ q @ relative
                offsets[1:] = [(q @ origin).z+(tq @ p).z for p in distal]
            airborne = next((e for e in events if e['side']==side and e['lift'] < start+i < e['land']), None)
            margin = 0.0
            if airborne:
                u = (start+i-airborne['lift'])/(airborne['land']-airborne['lift'])
                margin = .0101*_smoothstep(u/.3)*(1-_smoothstep((u-.7)/.3))
            values.append(-min(offsets)+.00005+margin)
        clearance_z[side] = values
    lengths = {}
    for side in "LR":
        pts = [mw @ rig.data.bones[smap[b+"."+side]].head_local
               for b in ("thigh", "shin", "foot")]
        lengths[side] = ((pts[1]-pts[0]).length, (pts[2]-pts[1]).length)
    lands = sorted(events, key=lambda e: e["land"])
    by_side = {s: [e for e in lands if e["side"] == s] for s in "LR"}
    curve = ((0, 9), (.05, 18), (.10, 11), (.20, 7), (.30, 8), (.50, 12), (.60, 35))

    def flex(knots, u):
        for (a, x), (b, y) in zip(knots, knots[1:]):
            if u <= b:
                return math.radians(x + (y-x)*_smoothstep((u-a)/(b-a)))
        return math.radians(knots[-1][1])

    desired, ceilings, records = [], [], []
    for i in range(len(targets["L"])):
        f = start+i
        bpy.context.scene.frame_set(f)
        hp = rig.pose.bones[smap["hips"]]
        world = mw @ hp.matrix
        hips = {s: (mw @ rig.pose.bones[smap["thigh."+s]].matrix).translation for s in "LR"}
        incoming = [e for e in lands if e["land"] <= f]
        z = world.translation.z
        if incoming:
            e = incoming[-1]
            side = e["side"]
            following = next((v for v in by_side[side] if v["land"] > e["land"]), None)
            cycle = following["land"]-e["land"] if following else 2*(e["land"]-e["opposite_land"])
            angle = flex(curve, (f-e["land"])/max(1, cycle))
            H, A = hips[side], targets[side][i][0]
            l1, l2 = lengths[side]
            xy = (A.x-H.x)**2 + (A.y-H.y)**2
            reach2 = l1*l1+l2*l2+2*l1*l2*math.cos(angle)
            z = A.z+math.sqrt(max(0,reach2-xy))-(H.z-world.translation.z)
        # Release to standing during the two gathering steps.
        release = (1-_smoothstep((f-lands[-2]["land"])/max(1,lands[-1]["land"]-lands[-2]["land"]))
                   if len(lands)>1 else 0)
        desired.append(world.translation.z+(z-world.translation.z)*release)
        caps, swings = [], {}
        for side in "LR":
            H, A = hips[side], targets[side][i][0]
            l1, l2 = lengths[side]
            xy = (A.x-H.x)**2 + (A.y-H.y)**2
            swing = next((e for e in by_side[side] if e["lift"] < f < e["land"]), None)
            swings[side] = swing
            if not swing:
                caps.append(A.z+math.sqrt(max(0,((l1+l2)*.9988)**2-xy))-(H.z-world.translation.z))
        ceilings.append(min(caps) if caps else desired[-1])
        records.append((world, hips, swings))
    # A downward-only velocity envelope anticipates low contact heights. It
    # cannot overshoot a reach ceiling, unlike averaging around a heel strike,
    # and leaves the mid-stance vault intact when no bound is active.
    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    dz = .45/fps
    heights = [min(z, cap) for z, cap in zip(desired, ceilings)]
    for indices in (range(1,len(heights)), range(len(heights)-2,-1,-1)):
        for i in indices:
            j = i-1 if indices.step > 0 else i+1
            heights[i] = min(heights[i], heights[j]+dz)
    # A fixed vertical speed still permits a large angular jump near full
    # extension. Anticipate contact flexion in joint space: lower the pelvis
    # only where a neighbouring supported sample requires more knee bend.
    # Both feet's world targets, route XY and every landing time stay fixed.
    knee_rate = knee_velocity_limit(speed, fps)

    def contact_knee(i, side, floor_only=False):
        world, hips, _ = records[i]
        H = hips[side].copy()
        H.z += heights[i]-world.translation.z
        l1, l2 = lengths[side]
        A = targets[side][i][0].copy()
        if floor_only:
            A.z = clearance_z[side][i]
        d2 = (H-A).length_squared
        return math.acos(max(-1., min(1., (d2-l1*l1-l2*l2)/(2*l1*l2))))

    for _ in range(8):
        changed = False
        # Anticipate the entire articulated swing sole, including its 1 cm
        # middle clearance. An immediate-neighbour bound misses a toe-down
        # foot two frames away in a short closing shuffle.
        required = {s: [contact_knee(i, s, floor_only=bool(records[i][2][s]))
                        for i in range(len(heights))] for s in 'LR'}
        for side in 'LR':
            for indices in (range(1,len(heights)), range(len(heights)-2,-1,-1)):
                for i in indices:
                    j = i-1 if indices.step > 0 else i+1
                    required[side][i] = max(required[side][i], required[side][j]-knee_rate)
        for indices in (range(1,len(heights)), range(len(heights)-2,-1,-1)):
            for i in indices:
                j = i-1 if indices.step > 0 else i+1
                for side in 'LR':
                    if records[i][2][side]:
                        continue
                    # A low incoming swing can still require slightly more
                    # flexion than the nominal heel-strike pose. Anticipate
                    # that floor-limited reach at the fixed landing too.
                    angle = required[side][i]
                    if angle <= contact_knee(i, side)+1e-7:
                        continue
                    world, hips, _ = records[i]
                    H, A = hips[side], targets[side][i][0]
                    l1, l2 = lengths[side]
                    reach2 = l1*l1+l2*l2+2*l1*l2*math.cos(angle)
                    xy = (A.x-H.x)**2+(A.y-H.y)**2
                    z = A.z+math.sqrt(max(0.,reach2-xy))-(H.z-world.translation.z)
                    if z < heights[i]-1e-8:
                        heights[i] = z
                        changed = True
        if not changed:
            break
    # Retain the inherited airborne clearance, but join it continuously to
    # the actual release ankle. Per-frame projection at the first swing frame
    # otherwise snaps a nearly extended turning support into a bent leg.
    airborne = {}
    for i, (world, hips, swings) in enumerate(records):
        for side, swing in swings.items():
            if not swing:
                continue
            u = (start+i-swing["lift"])/(swing["land"]-swing["lift"])
            H, A = hips[side], targets[side][i][0]
            l1, l2 = lengths[side]
            xy = (A.x-H.x)**2+(A.y-H.y)**2
            angle = flex(((0,35),(.35,60),(.50,60),(1,9)), u)
            reach2 = l1*l1+l2*l2+2*l1*l2*math.cos(angle)
            z = max(A.z, heights[i]+H.z-world.translation.z-math.sqrt(max(0,reach2-xy)))
            airborne[side,i] = z
    for i, (world, hips, swings) in enumerate(records):
        f = start+i
        for side, swing in swings.items():
            if not swing:
                continue
            lift = max(0,swing["lift"]-start)
            duration = swing["land"]-swing["lift"]
            join = min(duration-1,max(4,round(.35*duration)))
            z = airborne[side,i]
            if i-lift < join:
                # Blend effective leg length, not absolute ankle height: pelvis
                # progression must not pull the first airborne frame straight.
                def hip_at(index):
                    value = records[index][1][side].copy()
                    value.z += heights[index]-records[index][0].translation.z
                    return value
                H = hip_at(i)
                release_reach = (hip_at(lift)-targets[side][lift][0]).length
                endpoint = targets[side][lift+join][0].copy()
                endpoint.z = airborne[side,lift+join]
                end_reach = (hip_at(lift+join)-endpoint).length
                full = sum(lengths[side])
                release_reach = min(release_reach,full*.9988)
                reach = release_reach+(end_reach-release_reach)*_smoothstep((i-lift)/join)
                A = targets[side][i][0]
                xy = (A.x-H.x)**2+(A.y-H.y)**2
                z = max(A.z,H.z-math.sqrt(max(0,reach*reach-xy)))
            targets[side][i][0].z = z
        world = world.copy()
        world.translation.z = min(heights[i], ceilings[i])
        bpy.context.scene.frame_set(f)
        hp = rig.pose.bones[smap["hips"]]
        hp.matrix = mw.inverted() @ world
        hp.keyframe_insert("location", frame=f, group=hp.name)
    # Short braking swings otherwise compress the 60-degree airborne peak
    # into too few samples to return to the fixed landing. Project their knee
    # arc into the reachable angular envelope between the actual release and
    # landing. Only airborne ankle Z can change; contact/roll poses are exact.
    for side in 'LR':
        l1, l2 = lengths[side]
        def hip_at(i):
            H = records[i][1][side].copy()
            H.z += heights[i]-records[i][0].translation.z
            return H
        def angle_at(i):
            d2 = (hip_at(i)-targets[side][i][0]).length_squared
            return math.acos(max(-1., min(1., (d2-l1*l1-l2*l2)/(2*l1*l2))))
        for ev in by_side[side]:
            a, b = max(0, ev['lift']-start), ev['land']-start
            minimum = [contact_knee(i, side, floor_only=True)
                       if a < i < b else angle_at(i) for i in range(a,b+1)]
            for indices in (range(1,len(minimum)), range(len(minimum)-2,-1,-1)):
                for k in indices:
                    j = k-1 if indices.step > 0 else k+1
                    minimum[k] = max(minimum[k], minimum[j]-knee_rate)
            values = [max(angle_at(i), minimum[i-a]) for i in range(a,b+1)]
            # Upper cones from fixed endpoints preserve a full peak whenever
            # swing duration permits it, but reduce unreachable quick shuffles.
            for k in range(1,len(values)-1):
                values[k] = min(values[k], values[0]+k*knee_rate,
                                values[-1]+(len(values)-1-k)*knee_rate)
            for indices in (range(1,len(values)-1), range(len(values)-2,0,-1)):
                for k in indices:
                    j = k-1 if indices.step > 0 else k+1
                    values[k] = max(values[j]-knee_rate, min(values[j]+knee_rate, values[k]))
            # Round the velocity-cone corners by minimizing local curvature,
            # projected back onto exact endpoints, clearance and rate limits.
            # An active clearance constraint remains explicit, never hidden by
            # smoothing a baked angle after IK.
            for _ in range(4):
                proposed = list(values)
                for k in range(1,len(values)-1):
                    proposed[k] = max(minimum[k], .5*values[k]+.25*(values[k-1]+values[k+1]))
                values = proposed
                for indices in (range(1,len(values)-1),range(len(values)-2,0,-1)):
                    for k in indices:
                        j = k-1 if indices.step>0 else k+1
                        values[k] = max(minimum[k],max(values[j]-knee_rate,min(values[j]+knee_rate,values[k])))
            for k, angle in enumerate(values[1:-1],1):
                i = a+k
                H, A = hip_at(i), targets[side][i][0]
                reach2 = l1*l1+l2*l2+2*l1*l2*math.cos(angle)
                xy = (A.x-H.x)**2+(A.y-H.y)**2
                A.z = max(clearance_z[side][i], H.z-math.sqrt(max(0.,reach2-xy)))
    bpy.context.view_layer.update()


def _swing_ankles(rig, start, targets, events, toe_roll):
    """Shin-relative sagittal swing, preserving authored support and touchdown.

    Whittle, Gait Analysis (4th ed.), ch. 2: plantarflexion after toe-off
    returns to neutral around feet-adjacent, then stays near neutral.
    Solve after leg IK so a world-flat foot cannot masquerade as neutral ankle.
    """
    sm = anim.semantic_map(rig)
    mw = rig.matrix_world
    neutral = _terrain_forward(rig, sm).normalized()
    up = Vector((0, 0, 1))
    for side in 'LR':
        fk, sk = sm['foot.'+side], sm['shin.'+side]
        rest = mw @ rig.data.bones[fk].matrix_local
        rest_shin = rest.translation-(mw @ rig.data.bones[sk].matrix_local).translation
        def signed(a, b, axis):
            a = a-axis*a.dot(axis); b = b-axis*b.dot(axis)
            return math.atan2(axis.dot(a.cross(b)), a.dot(b))
        reference = signed(rest_shin, neutral, neutral.cross(up))
        for ev in (e for e in events if e['side']==side):
            a, b = ev['lift']-start, ev['land']-start
            for i in range(a+1, b):
                bpy.context.scene.frame_set(start+i)
                foot = mw @ rig.pose.bones[fk].matrix
                shin = mw @ rig.pose.bones[sk].matrix
                p, q = targets[side][i]
                fw = q @ rest.to_quaternion().inverted() @ neutral
                axis = Vector((fw.x, fw.y, 0)).normalized().cross(up)
                actual = reference-signed(foot.translation-shin.translation, fw, axis)
                u = (i-a)/(b-a)
                desired = math.radians(15*(1-_smoothstep(u/.5)))
                # Join exact release/heel strike over small end windows.
                weight = _smoothstep(u/.18)*(1-_smoothstep((u-.82)/.18))
                q = Quaternion(axis, (actual-desired)*weight) @ q
                # Toe extension releases after support, rather than holding a ski tip.
                toe_roll.get(side, {}).pop(i, None)
                # The following knee/sole solve handles vertical clearance jointly.
                targets[side][i] = p, q


def _mesh_floor_guard(rig, start, targets, contacts, events, toe_roll):
    """Bounded, local IK correction from the evaluated shoe, never body offsets.

    A contact receives ONE constant ankle correction (<=1.94 mm), so its world
    anchor and rotation remain frozen. Rolling corrections ease toward the
    surrounding anchors; swing clearance is measured on the actual mesh.
    Residuals beyond this small budget are reported rather than moving the rig.
    """
    from engine.shoe_contact import calibrate, measure
    patches = calibrate(rig)
    if not patches:
        return None
    shoes = [bpy.data.objects[name] for name,_ in patches]
    hidden = [o for o in shoes if o.hide_viewport]
    try:
        for o in hidden: o.hide_viewport = False
        lows = {s:[] for s in 'LR'}
        for i in range(len(targets['L'])):
            bpy.context.scene.frame_set(start+i)
            values = measure(patches)
            for s in 'LR': lows[s].append(values[s].get('mesh',float('inf')))
        shifts = {s:[0.]*len(targets[s]) for s in 'LR'}
        for s in 'LR':
            fixed = set()
            for a,b in contacts[s]:
                a,b = a-start,b-start
                dz = min(.00194,max(0.,-.00165-min(lows[s][a:b+1])))
                for i in range(a,b+1):
                    shifts[s][i] = dz
                    fixed.add(i)
            for i in range(len(targets[s])):
                if i not in fixed:
                    shifts[s][i] = min(.00194,max(0.,-.00165-lows[s][i]))
            # Raise neighbouring free samples in advance; fixed anchors never
            # inherit a changing framewise displacement from this smoothing.
            for indices in (range(1,len(shifts[s])),range(len(shifts[s])-2,-1,-1)):
                for i in indices:
                    j = i-1 if indices.step>0 else i+1
                    if i not in fixed: shifts[s][i] = max(shifts[s][i],shifts[s][j]-.00045)
            for i,dz in enumerate(shifts[s]): targets[s][i][0].z += dz
        if max(max(v) for v in shifts.values()) > 0:
            foot_lock(rig,start,start+len(targets['L'])-1,floor=0.,contacts=contacts,
                      foot_targets=targets,adjust_hips=False)
            _articulate_toes(rig,start,targets,toe_roll)
        return dict(max_ankle_correction_m=max(max(v) for v in shifts.values()),
                    corrections_m=shifts, budget_m=.00194,
                    method='evaluated mesh; constant per flat contact; bounded rolling IK')
    finally:
        for o in hidden: o.hide_viewport = True


def _bake_motion(rig, start, samples, active, initial_feet, clip, speed, ground=None,
                 phases=None, runs=None, _world_route=False, gait=None):
    began = time.perf_counter()
    sc = bpy.context.scene
    fps = sc.render.fps / sc.render.fps_base
    gait = gait or {}
    if phases is not None and ground is None and clip == "walk":
        samples[:] = support_headings(samples, phases, fps,
                                      math.radians(195) if gait.get("weight") else TURN_RATE)
    sole_lift = gait.get("sole_lift", 0.0)
    half = gait.get("half") or _half_step(clip, fps, speed)
    amp = gait.get("amp", 1.0)
    weight = gait.get("weight", 0.0)
    pelvis_gait = gait.get("pelvis", False) and phases is not None and ground is None
    inertia = momentum(samples, fps) if pelvis_gait else [(0.0, 0.0)] * len(samples)
    support_sign = 1.0 if _support_side(rig, initial_feet) == "L" else -1.0
    turn_lag = []
    lag = lag_v = 0.0
    for i in range(len(samples)):
        rate = _angle(samples[max(0, i-1)][1], samples[i][1])*fps
        lag, lag_v = spring_step(lag, lag_v, -rate*.035, 1/fps)
        turn_lag.append(math.degrees(lag))
    # Per-frame pelvis yaw (radians) and lateral sway (world vector) for the route root.
    pelvis_yaw = [0.0] * len(samples)
    sway = [Vector() for _ in samples]
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
            if pelvis_gait:
                # Weight transfer (film/mocap reference): the pelvis shifts ~3 cm over the
                # supporting foot at mid-stance, yaws ~5 degrees with the forward leg at heel
                # strike, and the shoulders counter-rotate ~6 degrees against it.
                stride = math.sin(math.pi * phase / half)       # +1: left thigh forward
                lean = math.sin(math.pi * phases[i]) * support_sign
                # Fade the yaw while the route itself turns fast, so pelvis sway never
                # pushes body yaw past the 100 deg/s heading limit.
                rate = abs(_angle(samples[max(0, i - 1)][1], samples[min(len(samples) - 1, i + 1)][1])) * fps / 2
                calm = max(0.0, 1.0 - rate / (TURN_RATE * .7))
                pelvis_yaw[i] = -math.radians(PELVIS_YAW) * stride * w * amp * calm
                left = Vector((math.cos(yaw), math.sin(yaw), 0.0))
                signed_rate = _angle(samples[max(0,i-1)][1],samples[min(len(samples)-1,i+1)][1])*fps/2
                turn_load = min(1.,abs(signed_rate)/math.radians(70))
                # Extra transfer only during the outside leg's support lobe.
                # The torso leans inward against the lateral acceleration.
                outside = -math.copysign(1.,signed_rate) if signed_rate else 0.
                loaded = max(0.,lean*outside)
                sway[i] = left * ((PELVIS_SWAY*lean+.018*outside*loaded*turn_load)*w)
                spine = list(rots.get("spine", (0, 0, 0)))
                spine[1] += (PELVIS_YAW + SHOULDER_COUNTER - 4.0) * stride * w * amp
                # Small C1 step accents affect upper-body phrasing, never landing
                # coordinates or timing. The same route always bakes the same keys.
                accent = (step_variation(phases[i]/2+gait.get("rhythm_seed",0)*17,7)
                          if gait.get("rhythm_seed",0) is not None else 0.)
                spine[2] += (.45 * accent + 2.0*outside*loaded*turn_load) * w
                for side in "LR":
                    arm = list(rots[f"upper_arm.{side}"])
                    arm[0] *= 1 + .025 * accent
                    rots[f"upper_arm.{side}"] = arm
                pitch, loading = inertia[i]
                rots["hips"] = (pitch*.28, 0, 0)
                spine[0] += pitch*.72
                up -= loading
                rots["spine"] = spine
            if ground is None and phases is not None and clip == "walk":
                # Velocity-driven shoulder lag, breath and relaxed distal follow.
                # The envelope and final hold are shared with the step planner.
                tail = 1-_smoothstep((i-active)/max(1, len(samples)-5-active))
                live = _smoothstep(i/half)*tail
                breath = .22*math.sin(2*math.pi*i/(fps*3.6))*live
                spine = list(rots.get("spine", (0, 0, 0)))
                spine[0] += breath
                spine[1] += turn_lag[i]*live
                rots["spine"] = spine
                head = list(rots.get("head", (0, 0, 0)))
                head[0] -= breath*.7
                head[1] -= turn_lag[i]*live*.25
                rots["head"] = head
                for side in "LR":
                    shoulder = list(rots.get("shoulder."+side, (0,0,0)))
                    shoulder[0] += breath*.5
                    rots["shoulder."+side] = shoulder
                    hand = list(rots.get("hand."+side, (0,0,0)))
                    hand[0] += 2*math.sin(math.pi*phase/half-.4)*w*amp
                    rots["hand."+side] = hand
            if weight and phases is not None and ground is None:
                # In-place steps: lean the trunk over the supporting foot mid-step and
                # let the pelvis settle ~1.2 cm as each foot lands (weight transfer).
                lean = math.sin(math.pi * phases[i]) * support_sign * w
                spine = list(rots.get("spine", (0, 0, 0)))
                left = Vector((math.cos(yaw), math.sin(yaw), 0))
                sway[i] = left * (.025 * weight * lean)
                spine[2] -= 3.5 * weight * lean      # Z+ leans to the character's right
                rots["spine"] = spine
                up -= .003 * weight * w * (.5 + .5 * math.cos(2 * math.pi * phases[i]))
            if ground is not None:
                a, b = max(0, i-half), min(len(samples)-1, i+half)
                delta = samples[b][0] - samples[a][0]
                slope = math.atan2(delta.z, max(math.hypot(delta.x, delta.y), 0.01))
                rots["spine"] = (max(-3.0, min(7.0, math.degrees(slope)*0.2)), 0, 0)
                rots["toe.L"] = rots["toe.R"] = (0, 0, 0)
                up = pos.z - rig.matrix_world.translation.z + up*0.2*w - 0.035*_smoothstep(i/half)
                root_heights.append(root_rest.z + up + sole_lift)
            # _drive retargets offsets from the proxy rest onto the target rest.
            # Rigify's torso control need not share the proxy pelvis' rest head.
            moved = pos + sway[i]
            offset = undo @ Vector((moved.x - root_rest.x, moved.y - root_rest.y, 0.0))
            anim._key_basic(basic, f, rots,
                            (offset.x, (up if ground else up*w) + sole_lift, -offset.y))
            bpy.context.view_layer.update()
            hp = basic.pose.bones["hips"]
            world = mw @ hp.matrix
            q = Quaternion((0, 0, 1), yaw - turn - rest_yaw + pelvis_yaw[i]) @ world.to_quaternion()
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
            correction = Quaternion((0, 0, 1), _angle(heading, samples[f - start][1] + pelvis_yaw[f - start]))
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
                pos = samples[f-start][0] + sway[f-start]
                loc = Vector((pos.x, pos.y, (mw @ hp.matrix).translation.z))
            anim._set_world_rot(rig, hp, correction @ q, loc)
            anim._key_rot(hp, f, previous)
            if ground is not None or _world_route:
                hp.keyframe_insert("location", frame=f, group=hips_name)
        bpy.context.view_layer.update()
    toe_roll, support_events = {}, []
    targets, contacts, footfalls = _footsteps(rig, samples, initial_feet, half, start, run=clip == "run",
                                   ground=ground, phases=phases, runs=runs,
                                   arrive=gait.get("arrive", False), roll=gait.get("roll", False),
                                   roll_scale=gait.get("roll_scale", 1.0), stance=gait.get("stance"),
                                   track_width=gait.get("track"), toe_targets=toe_roll,
                                   support_events=support_events, cruise=pelvis_gait,
                                   toe_out=math.radians(7) if phases is not None and ground is None and clip == "walk" else 0.0)
    if pelvis_gait:
        _stance_height(rig, start, targets, support_events, toe_roll, speed)
    lock = foot_lock(rig, start, end, floor=0.0, contacts=contacts, foot_targets=targets,
                     ground=ground, adjust_hips=not pelvis_gait)
    if pelvis_gait:
        for _ in range(3):
            _swing_ankles(rig, start, targets, support_events, toe_roll)
            _stance_height(rig, start, targets, support_events, toe_roll, speed)
            lock = foot_lock(rig, start, end, floor=0.0, contacts=contacts, foot_targets=targets,
                             adjust_hips=False)
    _articulate_toes(rig, start, targets, toe_roll)
    if phases is not None and ground is None and clip == 'walk':
        info['shoe_guard'] = _mesh_floor_guard(rig,start,targets,contacts,support_events,toe_roll)
    if phases is not None and ground is None and clip == "walk":
        _relax_fingers(rig, start, samples, phases, half)
    info["foot_lock"] = {"contacts": contacts, "max_ik_error_m": lock["max_ik_error_m"],
                         "hips_lowered_max_m": lock["hips_lowered_max_m"],
                         "sole_clearance_m": round(sole_lift, 5)}
    info["footfalls"] = [{"frame": f, "side": side, "character": rig.name} for f, side in footfalls]
    info["support_events"] = sorted(support_events, key=lambda e: (e["land"], e["side"]))
    if pelvis_gait:
        info["momentum"] = {"model": "critical_spring", "omega_rad_s": SPRING_OMEGA,
                            "lean_deg": [round(min(v[0] for v in inertia), 3),
                                         round(max(v[0] for v in inertia), 3)],
                            "brake_drop_m": round(max(v[1] for v in inertia), 4)}
    if ground is not None:
        info["foot_lock"].update({k: lock[k] for k in
            ("ground_heights", "max_penetration_m", "min_swing_clearance_m")})
        info["terrain"] = {"objects": [o.name for o in ground.objects],
                           "gait": "run/walk" if clip == "run" and any(
                               ground.gait(p, yaw)[0] for p, yaw in samples) else clip,
                           "bake_seconds": round(time.perf_counter()-began, 3)}
    if ground is None and phases is not None:
        info['weight_transfer'] = dict(model='support-paced kinematic transfer',
            route_xy_m=[list(p)[:2] for p,_ in samples],
            lateral_pelvis_m=[v.dot(Vector((math.cos(yaw),math.sin(yaw),0))) for v,(_,yaw) in zip(sway,samples)])
    info["_sway"] = sway
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


def _shoe_clearance(rig):
    """Fit the native MPFB shoe's neutral outsole, without changing mesh or weights.

    The analytical foot probes otherwise assume a barefoot Z=0 plane, whereas
    shoes03 extends ~26 mm below it. A small sole-flex margin covers skinning
    variation at the toe hinge. REST evaluation also works on a posed/chained rig.
    """
    kind = str(rig.get("c3d_rig_type", ""))
    if not (kind.startswith("mpfb_") or kind == "rigify"):
        return float(rig.get('c3d_sole_clearance_m', 0.0))
    shoes = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_render
             and o.get("c3d_garment_category") == "shoes"
             and any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers)]
    if not shoes:
        rig['c3d_sole_clearance_m'] = 0.0
        return 0.0
    saved = rig.data.pose_position
    try:
        rig.data.pose_position = "REST"
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        lowest = 0.0
        for shoe in shoes:
            ev = shoe.evaluated_get(depsgraph)
            mesh = ev.to_mesh()
            try:
                if mesh.vertices:
                    lowest = min(lowest, min((ev.matrix_world @ v.co).z - rig.matrix_world.translation.z
                                             for v in mesh.vertices))
            finally:
                ev.to_mesh_clear()
        lift = max(0.0, -lowest)
        if lift > .001:
            lift += .0055 * rig.matrix_world.to_scale().length / math.sqrt(3)
        rig['c3d_sole_clearance_m'] = lift
        return lift
    finally:
        rig.data.pose_position = saved
        bpy.context.view_layer.update()


def _bake(rig, start, samples, active, initial_feet, clip, speed, ground=None,
          phases=None, runs=None, _world_route=False, gait=None):
    """Generated FK rigs need bone evaluation, not repeated skin deformation."""
    began = time.perf_counter()
    gait = dict(gait or {}, sole_lift=_shoe_clearance(rig))
    gait["phase_offset"] = _phase_offset(rig, initial_feet)
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
    # All navigation baking uses joints/rest sole probes, never the skinned surface.
    # Defer skin evaluation on flat routes too (notably the per-frame toe pass).
    if kind in ("basic", "rigify") or kind.startswith("mpfb_"):
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


QUICK_TURN_S = 1.4                    # seconds for an in-place 180-degree turn_to
STOP_SECONDS = .45                    # cruise speed to standstill on flat walks
BRAKE_STEP_S = .40                    # ~.32 s swing plus ~.08 s double support when braking
PELVIS_YAW = 5.0                      # degrees, peaks at heel strike with the forward leg
PELVIS_SWAY = .03                     # metres toward the supporting foot at mid-stance
SHOULDER_COUNTER = 6.0                # degrees the shoulders turn against the pelvis
STANCE = .115                         # relaxed stop: ankle centres ~0.2 m apart at 1.75 m
TRACK = .055                          # ankle track; heel track is narrower with toe-out
TURN_STEP_S = .33                     # in-place turns take short, quick steps
GAZE_LIMIT = math.radians(60)         # anticipation never exceeds a comfortable head yaw
# (role, lead in half-steps, share of the heading change still to come).
# One step of head anticipation scales with local cadence, including braking/turns.
GAZE_CHAIN = (("chest", .50, .15), ("neck", .76, .30), ("head", 1.0, .45))


def _lead_gaze(rig, start, samples, fps, phases=None, half=None):
    """Turn head, then neck, then chest toward the heading the body reaches later.

    The body still follows the route; only the upper chain anticipates bends,
    corner turns and the final facing, then releases as the body catches up.
    """
    smap = anim.semantic_map(rig)
    chain = [(rig.pose.bones[smap[r]], lead, w) for r, lead, w in GAZE_CHAIN
             if smap.get(r) and smap[r] in rig.pose.bones]
    n = len(samples)
    phases = phases if phases is not None else [i / (half or .5*fps) for i in range(n)]
    lead_s = 0.0
    if not chain or n < 3:
        return {"lead_steps": 1.0, "lead_s": lead_s, "max_deg": 0.0}
    windows = [(bisect.bisect_left(phases, p-.2), bisect.bisect_right(phases, p+.2)) for p in phases]
    signals = []
    for bone, lead, share in chain:
        ahead = [min(n-1, bisect.bisect_left(phases, min(phases[-1], p+lead), lo=i))
                 for i, p in enumerate(phases)]
        lead_s = max(lead_s, max((a-i)/fps for i, a in enumerate(ahead)))
        raw = [max(-GAZE_LIMIT, min(GAZE_LIMIT, _angle(samples[i][1], samples[ahead[i]][1])))
               for i in range(n)]
        # Smooth twice with a short box so each joint eases in/out instead of snapping.
        for _ in range(2):
            raw = [sum(raw[a:b]) / max(1, b-a) for a, b in windows]
        signals.append([v * share * _smoothstep((n-4-i)/max(1, round(.15*fps)))
                        for i, v in enumerate(raw)])
    head_total = [sum(sig[i] for sig in signals) for i in range(n)]
    peak = max(abs(v) for v in head_total)
    if peak < math.radians(.5):
        return {"lead_steps": 1.0, "lead_s": round(lead_s, 3), "max_deg": 0.0}
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
    return {"lead_steps": 1.0, "lead_s": round(lead_s, 3), "max_deg": round(math.degrees(peak), 2)}


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


def _breath_settle(rig, begin, end, yaw):
    """One subtle chest expansion/release; all channels stop before the final four frames."""
    name = anim.semantic_map(rig).get("chest") or anim.semantic_map(rig).get("spine")
    if not name or end-3 <= begin:
        return
    bone = rig.pose.bones[name]
    axis = Vector((math.cos(yaw), math.sin(yaw), 0))
    previous = {}
    for frame in range(begin, end+1):
        bpy.context.scene.frame_set(frame)
        u = min(1.0, (frame-begin)/max(1,end-3-begin))
        angle = math.radians(.65)*math.sin(math.pi*u)**2
        q = (rig.matrix_world@bone.matrix).to_quaternion()
        anim._set_world_rot(rig,bone,Quaternion(axis,angle)@q)
        anim._key_rot(bone,frame,previous)
    bpy.context.view_layer.update()


@command("walk_path")
def walk_path(armature, points, clip="walk", start_frame=None, speed=1.0, face_end=None,
              avoid="auto", ignore=None, _world_route=False, _plant_at_arrival=False, rhythm_seed=0):
    """Walk/run through XY targets; static obstacle detours by default.

    avoid=False preserves the old route. auto/True plan only on intersection;
    blocked targets snap to free cells with warnings, unreachable paths raise.
    ignore names exclude objects and descendants, e.g. a sit_on approach chair.
    """
    ignored = validate_options(avoid, ignore)
    if clip not in ("walk", "run"):
        raise ValueError('clip must be "walk" or "run"')
    speed = _speed(speed)
    if rhythm_seed is not None and (isinstance(rhythm_seed, bool) or not isinstance(rhythm_seed,int)):
        raise ValueError('rhythm_seed must be an integer or None (symmetric)')
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
        # Flat walks brake within ~0.45 s (film/mocap reference) on two quick steps.
        braking = ground is None and clip == "walk"
        keys, distance = _route(pos, yaw, route, velocity, ground, fps, speed,
                                planner.curve_free if avoided else None,
                                brake=velocity / STOP_SECONDS if braking else None)
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
            samples, active, phases, _step = _arrival_samples(
                keys, fps, half, brake=max(2, round(BRAKE_STEP_S * fps / speed)) if braking else None, vary=braking, rhythm_seed=rhythm_seed)
        gait = {"half": half, "arrive": flat, "roll": flat and clip == "walk",
                "phase_offset": _phase_offset(rig, feet), "stance": STANCE * d["H"],
                "track": max(.10, TRACK * d["H"]) if flat else None, "pelvis": flat and clip == "walk",
                "rhythm_seed":rhythm_seed}
        result = _bake(rig, start, samples, active, feet, clip, speed, ground=ground,
                       phases=phases, runs=runs, _world_route=_world_route, gait=gait)
        # Clearance is reported for the actual root, including the pelvis weight shift.
        sway = result.pop("_sway", None) or [Vector()] * len(samples)
        rooted = [(p + d, yaw) for (p, yaw), d in zip(samples, sway)]
        navigation = (planner.report(route, rooted, avoided) if planner else
                      {"avoided": False, "detours": 0, "path_points": [list(p)[:2] for p in route],
                       "clearance_m": None, "warnings": []})
        navigation["planning_seconds"] = round(planning_seconds, 6)
        result["gaze_lead"] = _lead_gaze(rig, start, samples, fps, phases, half)
        footfalls = result["footfalls"]
        if flat and clip != "walk" and footfalls and footfalls[-1]["frame"] < result["frames"][1]:
            _settle_chest(rig, footfalls[-1]["frame"], result["frames"][1], samples[-1][1], fps)
        return {**result, "clip": clip, "distance_m": round(distance, 4),
                "rhythm": {"seed":rhythm_seed,"mode":("symmetric" if rhythm_seed is None else "correlated") if braking else "clip_default",
                           "duration_variation_max":.0182 if braking and rhythm_seed is not None else 0.},
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
        _turn(keys, heading, quick=ground is None)
        fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
        flat = ground is None
        gait = {"phase_offset": _phase_offset(rig, feet)}
        if flat:
            # Short quick steps with little leg/arm swing, a light heel roll, and no idle
            # tail: the last two steps gather as the rotation finishes.
            d = anim._dims(anim._rig_landmarks(rig, anim.semantic_map(rig)))
            # About one step per 60 degrees plus the closing step: 180 deg -> 4 steps.
            steps = max(2, round(abs(math.degrees(_angle(yaw, heading))) / 60) + 1)
            samples, active, phases, half = _arrival_samples(
                keys, fps, max(2, round(TURN_STEP_S * fps)), count=steps, last_weight=1.35, hold_s=.65,
                close_after=True)
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
        result.pop("_sway", None)
        result["gaze_lead"] = _lead_gaze(rig, start, samples, fps, phases, half)
        if flat and result["footfalls"]:
            _breath_settle(rig, result["footfalls"][-1]["frame"], result["frames"][1], heading)
        return {**result, "distance_m": 0.0, "turn_degrees": round(math.degrees(_angle(yaw, heading)), 3),
                **navigation}
    finally:
        bpy.context.scene.frame_set(saved_frame)
