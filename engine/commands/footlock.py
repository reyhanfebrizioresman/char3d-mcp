"""Foot locking: keep planted feet still on the ground (no sliding, no floor penetration).

A post-process that works on any humanoid rig and any animation already keyed on it
(procedural clips, retargeted mocap):

1. Sample the original motion: for each foot a few sole points (heel, ball, toe tip)
   in world space, plus hip/knee/ankle positions.
2. Contact = the lowest sole point is near the floor AND moving slowly. Short gaps are
   filled, blips dropped.
3. Inside a contact the foot *rolls without slipping*: each frame the current pivot
   (lowest sole point) keeps its world position, so heel-strike -> flat -> toe-off still
   reads naturally; the lowest point is also snapped onto the floor. The lock is anchored
   at the slowest frame of the contact.
4. The correction (new ankle - original ankle) eases in before and out after each contact.
5. Each leg is re-solved with an analytic 2-bone IK keeping the original knee direction;
   the foot keeps its original world rotation. When a target is out of reach the hips
   are lowered just enough (smoothed) instead of letting the foot slide.
"""
import math

import bpy
from mathutils import Matrix, Vector

from . import command


def _smoothstep(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def _rotate_bone(rig, pb, cur_vec, new_vec):
    """Rotate pose bone about its head so world direction cur_vec turns into new_vec."""
    mw = rig.matrix_world
    world = mw @ pb.matrix
    if cur_vec.length < 1e-9 or new_vec.length < 1e-9:
        return
    q = cur_vec.rotation_difference(new_vec) @ world.to_quaternion()
    pb.matrix = mw.inverted() @ Matrix.LocRotScale(world.translation, q, world.to_scale())


def _set_world_rot(rig, pb, q):
    mw = rig.matrix_world
    world = mw @ pb.matrix
    pb.matrix = mw.inverted() @ Matrix.LocRotScale(world.translation, q, world.to_scale())


def _ik_knee(H, A, l1, l2, pole):
    """Knee position for hip H -> ankle A (target clamped to reach)."""
    d_vec = A - H
    d = max(min(d_vec.length, (l1 + l2) * 0.9995), abs(l1 - l2) + 1e-4)
    u = d_vec.normalized()
    cos_a = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
    perp = pole - u * pole.dot(u)
    if perp.length < 1e-8:
        fallback = Vector((1, 0, 0)) if abs(u.x) < .8 else Vector((0, 1, 0))
        perp = fallback-u*fallback.dot(u)
    perp.normalize()
    return H + l1 * (u * cos_a + perp * math.sqrt(max(0.0, 1 - cos_a * cos_a)))


def _legs(rig):
    from .anim import semantic_map
    smap = semantic_map(rig)
    legs = {}
    for s in "LR":
        names = [smap.get(f"{b}.{s}") for b in ("thigh", "shin", "foot")]
        if all(names):
            legs[s] = {"thigh": names[0], "shin": names[1], "foot": names[2],
                       "toe": smap.get(f"toe.{s}")}
    return legs, smap


def _sole_points(rig, leg, floor):
    """Heel, ball and toe-tip sole points in the foot bone's rest space."""
    mw = rig.matrix_world
    B = rig.data.bones
    foot = B[leg["foot"]]
    ankle = mw @ foot.head_local
    if leg["toe"] and leg["toe"] in B:
        ball = mw @ B[leg["toe"]].head_local
        tip = mw @ B[leg["toe"]].tail_local
    else:
        ball = mw @ foot.tail_local
        tip = ball + (ball - ankle) * 0.4
    fwd = tip - ankle
    fwd.z = 0.0
    length = max(fwd.length, 1e-3)
    fwd.normalize()
    heel = ankle - fwd * (0.25 * length)
    pts = [Vector((p.x, p.y, floor)) for p in (heel, ball, tip)]
    inv = (mw @ foot.matrix_local).inverted()
    return [inv @ p for p in pts]


def _intervals(mask, fill=2, min_len=3):
    n = len(mask)
    m = list(mask)
    i = 0
    while i < n:   # fill short gaps between contacts
        if not m[i]:
            j = i
            while j < n and not m[j]:
                j += 1
            if 0 < i and j < n and j - i <= fill:
                for k in range(i, j):
                    m[k] = True
            i = j
        else:
            i += 1
    out, start = [], None
    for i, on in enumerate(m + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start >= min_len:
                out.append((start, i - 1))
            start = None
    return out


def _detect_contacts(pts, body_vel, fps, floor, height_tolerance, ground=None,
                     speed_tolerance=None):
    """Shared rolling-sole contact detector for foot IK and procedural Foley.

    Returns inclusive sample-index intervals, sole speeds in meters/frame, and pivots.
    """
    n = len(pts)
    v_min = (0.3 if speed_tolerance is None else float(speed_tolerance)) / fps
    low = [min(range(3), key=lambda k: pts[i][k].z -
               (ground.sample(pts[i][k].x, pts[i][k].y)[0] if ground else floor))
           for i in range(n)]
    speed, mask = [], []
    for i in range(n):
        a, b = max(0, i - 1), min(n - 1, i + 1)
        k = low[i]
        d = (pts[b][k] - pts[a][k]) / max(1, b - a)
        vel = Vector((d.x, d.y, 0.0))
        speed.append(vel.length)
        V = body_vel[i]
        vb = V.length
        if vb > 1e-4:
            u = V / vb
            along = vel.dot(u)
            side = (vel - u * along).length
            slow = along < 0.5 * vb + v_min and side < 0.5 * vb + 2 * v_min
        else:
            slow = speed[-1] < v_min
        p = pts[i][k]
        height = p.z - (ground.sample(p.x, p.y)[0] if ground else floor)
        mask.append(height < height_tolerance and (speed[-1] < v_min or slow))
    return _intervals(mask), speed, low


def foot_lock(rig, frame_start, frame_end, floor=None, height_tolerance=None,
              speed_tolerance=None, blend_frames=None, adjust_hips=True, key=True,
              contacts=None, foot_targets=None, terrain=True, ground=None):
    """contacts: optional {"L": [[first, last], ...], "R": [...]} absolute frames where each
    foot is planted (skips detection). speed_tolerance: m/s a planted foot may drift.
    Internal foot_targets: per-side world (ankle, quaternion) samples from a step planner;
    these replace rolling corrections, sharing the same reach adjustment and IK solve."""
    from .anim import _key_rot
    sc = bpy.context.scene
    fps = sc.render.fps
    legs, smap = _legs(rig)
    if not legs:
        raise ValueError(f"{rig.name}: no recognisable thigh/shin/foot bones")
    hips_name = smap.get("hips")
    mw = rig.matrix_world
    floor = float(mw.translation.z if floor is None else floor)
    if ground is None and terrain:
        from .terrain import GroundQuery
        query = GroundQuery(floor)
        ground = query if query.objects else None
    f0, f1 = int(frame_start), int(frame_end)
    frames = list(range(f0, f1 + 1))
    n = len(frames)
    B = rig.data.bones
    leg_len = {}
    for s, leg in legs.items():
        hh = mw @ B[leg["thigh"]].head_local
        kk = mw @ B[leg["shin"]].head_local
        aa = mw @ B[leg["foot"]].head_local
        leg_len[s] = ((kk - hh).length, (aa - kk).length)
    total = sum(leg_len[next(iter(leg_len))])
    h_tol = 0.045 * total if height_tolerance is None else float(height_tolerance)
    blend = max(1, int(round(0.25 * fps))) if blend_frames is None else max(1, int(blend_frames))
    sole = {s: _sole_points(rig, leg, floor) for s, leg in legs.items()}
    fwd_axis = (mw.to_3x3() @ Vector((0, -1, 0))).normalized()

    # ---- pass 1: sample the original motion
    keep = [leg[k] for leg in legs.values() for k in ("thigh", "shin", "foot")]
    if hips_name:
        keep_all = keep + [hips_name]
    else:
        keep_all = keep
    orig = {}       # frame -> {bone: matrix_basis}
    S = {s: {"H": [], "K": [], "A": [], "R": [], "pts": []} for s in legs}
    hips_world = []
    for f in frames:
        sc.frame_set(f)
        orig[f] = {b: rig.pose.bones[b].matrix_basis.copy() for b in keep_all}
        hips_world.append((mw @ rig.pose.bones[hips_name].matrix).translation.copy()
                          if hips_name else Vector())
        for s, leg in legs.items():
            P = rig.pose.bones
            fw = mw @ P[leg["foot"]].matrix
            S[s]["H"].append((mw @ P[leg["thigh"]].matrix).translation.copy())
            S[s]["K"].append((mw @ P[leg["shin"]].matrix).translation.copy())
            S[s]["A"].append(fw.translation.copy())
            S[s]["R"].append(fw.to_3x3().normalized())
            S[s]["pts"].append([fw @ p for p in sole[s]])

    # body (hips) horizontal velocity per frame, lightly smoothed
    v_min = (0.3 if speed_tolerance is None else float(speed_tolerance)) / fps
    raw = []
    for i in range(n):
        a, b = max(0, i - 1), min(n - 1, i + 1)
        d = (hips_world[b] - hips_world[a]) / max(1, b - a)
        raw.append(Vector((d.x, d.y, 0.0)))
    win = max(1, int(round(0.2 * fps)))
    body_vel = []
    for i in range(n):
        seg = raw[max(0, i - win):i + win + 1]
        body_vel.append(sum(seg, Vector()) / len(seg))

    # ---- contacts, rolling lock, eased correction
    report = {}
    corr = {}
    for s in legs:
        if foot_targets is not None:
            targets = foot_targets[s]
            corr[s] = [p - a for (p, _q), a in zip(targets, S[s]["A"])]
            S[s]["R"] = [q.to_matrix() for _p, q in targets]
            report[s] = {"contacts": contacts[s], "slide_removed_m": 0.0}
            continue
        pts = S[s]["pts"]
        detected, speed, low = _detect_contacts(pts, body_vel, fps, floor, h_tol, ground, speed_tolerance)
        if contacts is not None:
            ivs = []
            for a, b in contacts.get(s, []):
                a, b = max(int(a), f0) - f0, min(int(b), f1) - f0
                if b >= a:
                    ivs.append((a, b))
        else:
            ivs = detected
        A, R = S[s]["A"], S[s]["R"]
        c = [Vector((0.0, 0.0, 0.0)) for _ in range(n)]
        lsole = sole[s]
        for a, b in ivs:
            # anchor: where the foot already is at a clip boundary (continuity with the
            # previous/next animation), else the slowest frame of the contact
            if a == 0:
                m = 0
            elif b == n - 1:
                m = n - 1
            else:
                m = min(range(a, b + 1), key=lambda i: speed[i])
            if ground is not None:
                # Flatten the original sole before aligning it to the new surface.
                rest = (mw @ B[legs[s]["foot"]].matrix_local).to_quaternion()
                normal = R[m] @ (rest.inverted() @ Vector((0, 0, 1)))
                flat = normal.rotation_difference(Vector((0, 0, 1))) @ R[m].to_quaternion()
                target, q, _error, _height = ground.fit(A[m], flat, lsole)
                for i in range(a, b+1):
                    c[i] = target - A[i]
                    R[i] = q.to_matrix()
                continue
            N = {m: A[m].copy()}
            for i in range(m + 1, b + 1):          # roll forward without slipping
                p = lsole[low[i - 1]]
                step = R[i - 1] @ p - R[i] @ p
                N[i] = N[i - 1] + Vector((step.x, step.y, 0.0))
                N[i].z = A[i].z
            for i in range(m - 1, a - 1, -1):      # ... and backward
                p = lsole[low[i + 1]]
                step = R[i + 1] @ p - R[i] @ p
                N[i] = N[i + 1] + Vector((step.x, step.y, 0.0))
                N[i].z = A[i].z
            for i in range(a, b + 1):
                cc = N[i] - A[i]
                cc.z = floor - pts[i][low[i]].z      # lowest sole point onto the floor
                c[i] = cc
        # ease the correction in/out around each contact
        for j, (a, b) in enumerate(ivs):
            nxt = ivs[j + 1][0] if j + 1 < len(ivs) else None
            if nxt is not None and nxt - b - 1 <= 2 * blend:
                for i in range(b + 1, nxt):
                    c[i] = c[b].lerp(c[nxt], _smoothstep((i - b) / (nxt - b)))
                continue
            for i in range(b + 1, min(n, b + 1 + blend)):
                c[i] = c[b] * (1 - _smoothstep((i - b) / (blend + 1)))
            if nxt is not None:
                for i in range(max(b + 1 + blend, nxt - blend), nxt):
                    c[i] = c[nxt] * _smoothstep((i - (nxt - blend - 1)) / (blend + 1))
        if ivs and ivs[0][0] > 0:
            a = ivs[0][0]
            for i in range(max(0, a - blend), a):
                c[i] = c[a] * _smoothstep((i - (a - blend - 1)) / (blend + 1))
        # outside contacts never let the foot dip into the floor, and a fast-moving
        # (swinging) foot keeps a little clearance instead of scraping along it
        inside = set(i for a, b in ivs for i in range(a, b + 1))
        clearance = 0.022 * total
        for i in range(n):
            if i not in inside:
                if ground is None:
                    lowest = min(p.z for p in pts[i])
                else:
                    corrected = [S[s]["A"][i] + c[i] + R[i] @ p for p in lsole]
                    lowest = min(p.z - ground.sample(p.x, p.y)[0] for p in corrected) + floor - c[i].z
                w = _smoothstep((speed[i] - v_min) / (3 * v_min))   # moving over the ground
                c[i] = Vector((c[i].x, c[i].y, max(c[i].z, floor + clearance * w - lowest)))
        corr[s] = c
        slide = 0.0
        for a, b in ivs:
            for i in range(a, b):
                k = low[i]
                d = pts[i + 1][k] - pts[i][k]
                slide += math.hypot(d.x, d.y)
        report[s] = {"contacts": [[frames[a], frames[b]] for a, b in ivs],
                     "slide_removed_m": round(slide, 3)}

    # ---- hips drop where a target is out of reach (smoothed)
    drop = [0.0] * n
    if adjust_hips and hips_name:
        for i in range(n):
            need = 0.0
            for s in legs:
                H = S[s]["H"][i]
                T = S[s]["A"][i] + corr[s][i]
                reach = sum(leg_len[s]) * 0.995
                d = T - H
                if d.length > reach:
                    # lower H by x so |d + x z| = reach (d.z < 0: ankle below hip)
                    bq = 2 * d.z
                    cq = d.length_squared - reach * reach
                    disc = bq * bq - 4 * cq
                    x = (-bq - math.sqrt(disc)) / 2 if disc >= 0 else -d.z
                    need = max(need, x)
            drop[i] = need
        w = max(1, blend // 2)
        grown = [max(drop[max(0, i - w):i + w + 1]) for i in range(n)]
        drop = [sum(grown[max(0, i - w):i + w + 1]) / len(grown[max(0, i - w):i + w + 1])
                for i in range(n)]

    # ---- pass 2: solve and key
    prev = {}
    worst = 0.0
    penetration = 0.0
    swing_clearance = None
    ground_heights = {s: [] for s in legs}
    planted = {s: {f for a, b in report[s]["contacts"] for f in range(a, b+1)} for s in legs}
    for i, f in enumerate(frames):
        sc.frame_set(f)
        P = rig.pose.bones
        for b in keep_all:
            P[b].matrix_basis = orig[f][b]
        bpy.context.view_layer.update()
        if drop[i] > 1e-5:
            hb = P[hips_name]
            world = mw @ hb.matrix
            world.translation = world.translation - Vector((0, 0, drop[i]))
            hb.matrix = mw.inverted() @ world
            bpy.context.view_layer.update()
        # Solve each hierarchy level for both legs before evaluating. Updating after
        # each individual bone also evaluates every skinned mesh (and Rigify driver).
        # The two leg chains are independent, so they share those expensive updates.
        for s, leg in legs.items():
            pt, ps, pf = P[leg["thigh"]], P[leg["shin"]], P[leg["foot"]]
            l1, l2 = leg_len[s]
            H = (mw @ pt.matrix).translation
            K = (mw @ ps.matrix).translation
            A = (mw @ pf.matrix).translation
            T = S[s]["A"][i] + corr[s][i]
            pole = K - (H + A) / 2
            u = (T - H).normalized()
            if (pole - u * pole.dot(u)).length < 1e-4:
                pole = fwd_axis
            K2 = _ik_knee(H, T, l1, l2, pole)
            _rotate_bone(rig, pt, K - H, K2 - H)
        bpy.context.view_layer.update()
        for s, leg in legs.items():
            ps, pf = P[leg["shin"]], P[leg["foot"]]
            T = S[s]["A"][i] + corr[s][i]
            K_now = (mw @ ps.matrix).translation
            A_now = (mw @ pf.matrix).translation
            _rotate_bone(rig, ps, A_now - K_now, T - K_now)
        bpy.context.view_layer.update()
        for s, leg in legs.items():
            pf = P[leg["foot"]]
            _set_world_rot(rig, pf, S[s]["R"][i].to_quaternion())
        bpy.context.view_layer.update()
        for s, leg in legs.items():
            pf = P[leg["foot"]]
            T = S[s]["A"][i] + corr[s][i]
            worst = max(worst, ((mw @ pf.matrix).translation - T).length)
            if ground is not None:
                fw = mw @ pf.matrix
                pts = [fw @ p for p in sole[s]]
                gaps = [p.z - ground.sample(p.x, p.y)[0] for p in pts]
                penetration = max(penetration, -min(gaps))
                # Liftoff/touchdown transitions approach zero clearance continuously;
                # measure the airborne interior, excluding the two adjacent frames.
                if all(f+j not in planted[s] for j in (-2, -1, 0, 1, 2)):
                    swing_clearance = min(gaps) if swing_clearance is None else min(swing_clearance, min(gaps))
                for a, _b in report[s]["contacts"]:
                    if f == a:
                        ground_heights[s].append({"frames": [a, _b],
                            "height_m": round(ground.sample(pts[1].x, pts[1].y)[0], 5)})
        if key:
            for b in keep:
                _key_rot(P[b], f, prev)
            if hips_name and max(drop) > 1e-5:
                P[hips_name].keyframe_insert("location", frame=f, group=hips_name)
    bpy.context.view_layer.update()
    metrics = ({"ground_heights": ground_heights, "max_penetration_m": round(max(0, penetration), 5),
                "min_swing_clearance_m": round(swing_clearance, 5) if swing_clearance is not None else None}
               if ground is not None else {})
    return {"armature": rig.name, "frames": [f0, f1], "feet": report, **metrics,
            "hips_lowered_max_m": round(max(drop), 3), "max_ik_error_m": round(worst, 4),
            "floor": round(floor, 3)}


@command("lock_feet")
def lock_feet(armature, frame_start=None, frame_end=None, floor=None, height_tolerance=None,
              speed_tolerance=None, blend_frames=None, adjust_hips=True, contacts=None, terrain=True):
    """Remove foot sliding from the animation on a rig (rolling foot lock + leg IK)."""
    from .talk import _rig_of
    rig = _rig_of(armature)
    sc = bpy.context.scene
    act = rig.animation_data.action if rig.animation_data else None
    if act is None:
        raise ValueError(f"{rig.name} has no animation to fix")
    fs = int(frame_start if frame_start is not None else max(sc.frame_start, act.frame_range[0]))
    fe = int(frame_end if frame_end is not None else act.frame_range[1])
    return foot_lock(rig, fs, fe, floor=floor, height_tolerance=height_tolerance,
                     speed_tolerance=speed_tolerance, blend_frames=blend_frames,
                     adjust_hips=adjust_hips, contacts=contacts, terrain=terrain)
