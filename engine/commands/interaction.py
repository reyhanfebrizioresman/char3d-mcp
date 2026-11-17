"""Paired contact performances, baked onto the existing humanoid FK controls."""
import math
from contextlib import contextmanager

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import command, anim
from .fingers import HandRig
from .footlock import _smoothstep
from .gaze import head_frame
from .holding import _palm, _prop, _constraint, transfer_prop
from .seating import _chain
from .talk import _rig_of, _fcurves
from .util import vec


KINDS = ("handshake", "hug", "high_five", "fist_bump", "handover", "pat_shoulder")
UP = Vector((0, 0, 1))


def _history(rigs, start):
    """Appending a key must not move an earlier Bezier key's automatic handles."""
    saved = []
    for rig in rigs:
        action = rig.animation_data.action if rig.animation_data else None
        for fc in _fcurves(action):
            keys = [(k.co.copy(), k.handle_left.copy(), k.handle_right.copy(), k.interpolation)
                    for k in fc.keyframe_points if k.co.x < start]
            guard, cut = start-1, None
            left = next((k for k in reversed(list(fc.keyframe_points)) if k.co.x < guard), None)
            right = next((k for k in fc.keyframe_points if k.co.x > guard), None)
            if (left and right and not any(k.co.x == guard for k in fc.keyframe_points)):
                value = fc.evaluate(guard)
                if left.interpolation == "BEZIER":
                    # Split the ORIGINAL cubic at the last preceding frame. Just
                    # inserting its sampled value changes a sparse Bezier segment.
                    p0, p1, p2, p3 = (tuple(p) for p in
                                     (left.co, left.handle_right, right.handle_left, right.co))

                    def lerp(a, b, t):
                        return tuple(x+(y-x)*t for x,y in zip(a,b))

                    lo, hi = 0., 1.
                    for _ in range(45):
                        t = (lo+hi)/2
                        a, b, c = lerp(p0,p1,t), lerp(p1,p2,t), lerp(p2,p3,t)
                        d, e = lerp(a,b,t), lerp(b,c,t)
                        point = lerp(d,e,t)
                        if point[0] < guard:
                            lo = t
                        else:
                            hi = t
                    cut = (guard, value, left.co.x, a, d, "BEZIER")
                elif left.interpolation in ("LINEAR", "CONSTANT"):
                    cut = (guard, value, left.co.x, None, None, left.interpolation)
            saved.append((fc, keys, cut))
    return saved


def _restore_history(saved, split=True):
    for fc, keys, cut in saved:
        by_frame = {k.co.x: k for k in fc.keyframe_points}
        for co, left, right, interpolation in keys:
            key = by_frame.get(co.x)
            if key is None:
                key = fc.keyframe_points.insert(co.x, co.y)
            key.co = co
            key.interpolation = interpolation
            if (key.handle_left-left).length > 1e-7 or (key.handle_right-right).length > 1e-7:
                key.handle_left_type = key.handle_right_type = "FREE"
                key.handle_left, key.handle_right = left, right
        if cut and split:
            guard, value, previous, outgoing, incoming, interpolation = cut
            key = fc.keyframe_points.insert(guard, value, options={"FAST"})
            key.interpolation = interpolation
            if outgoing is not None:
                previous = next(k for k in fc.keyframe_points if k.co.x == previous)
                old_left = next(left for co,left,_,_ in keys if co.x == previous.co.x)
                previous.handle_left_type = previous.handle_right_type = "FREE"
                previous.handle_left, previous.handle_right = old_left, outgoing
                key.handle_left_type = key.handle_right_type = "FREE"
                key.handle_left = incoming
        fc.update()


@contextmanager
def preserve_interactions(beats):
    """Keep scripted contacts over the later whole-scene speaking gesture pass."""
    saved = []
    for beat in beats:
        if beat.get("do") != "interact" or "result" not in beat:
            continue
        report = beat["result"]
        approach = report["frames"]["approach"]
        lo = approach[0] if approach else report["frames"]["reach"]
        hi = report["frames"]["end"]
        for name, bones in report["bones"].items():
            rig = bpy.data.objects[name]
            for fc in _fcurves(rig.animation_data.action):
                if any(fc.data_path.startswith(f'pose.bones["{n}"].rotation_') for n in bones):
                    saved.append((fc, lo, hi, [(k.co.x, k.co.y, k.interpolation)
                                 for k in fc.keyframe_points if lo <= k.co.x <= hi]))
    try:
        yield
    finally:
        for fc, lo, hi, keys in saved:
            for k in reversed(list(fc.keyframe_points)):
                if lo <= k.co.x <= hi:
                    fc.keyframe_points.remove(k, fast=True)
            for f, value, interpolation in keys:
                key = fc.keyframe_points.insert(f, value, options={"FAST"})
                key.interpolation = interpolation
            fc.update()


def _position(rig, key="hips"):
    return (rig.matrix_world @ rig.pose.bones[anim.semantic_map(rig)[key]].matrix).translation


def _height(rig, smap):
    mw = rig.matrix_world
    top = mw @ rig.data.bones[smap["head"]].tail_local
    floor = min((mw @ rig.data.bones[smap[f"foot.{s}"]].tail_local).z for s in "LR")
    return top.z - floor, floor


def _axes(a, b):
    delta = _position(b) - _position(a)
    delta.z = 0
    if delta.length < 1e-5:
        _, q = head_frame(a, "hips")
        delta = q @ Vector((0, -1, 0))
        delta.z = 0
    forward = delta.normalized()
    return forward, UP.cross(forward)


def _orientation(palm, normal, fingers):
    """Map measured palm normal and bone +Y (fingers) to two world axes.

    The prop frame's thumb axis has opposite handedness on left/right hands;
    aligning its Y directly would point one hand back toward its own wrist.
    """
    n = palm.to_3x3().col[0].normalized()
    along = Vector((0, 1, 0))
    along = (along - n * along.dot(n)).normalized()
    local = Matrix((n, along, n.cross(along))).transposed()
    normal = normal.normalized()
    fingers = (fingers-normal*fingers.dot(normal)).normalized()
    world = Matrix((normal, fingers, normal.cross(fingers))).transposed()
    return (world @ local.transposed()).to_quaternion()


def _chest(rig):
    return _position(rig, "chest").lerp(_position(rig, "neck"), 0.55)


def _targets(rigs, heights, floors, kind, side, f, contact, release, palms, grip_gap=0.09):
    a, b = rigs
    d, lateral = _axes(a, b)
    h = min(heights)
    center = (_chest(a) + _chest(b)) / 2
    fraction = {"handshake": 0.71, "high_five": 0.91, "fist_bump": 0.72,
                "handover": 0.72}.get(kind, 0.76)
    center.z = max(floors) + h * fraction
    if kind == "handshake" and contact <= f <= release:
        u = (f - contact) / max(1, release - contact)
        center.z += 0.025 * math.sin(6 * math.pi * u)
    if kind == "high_five" and f < contact:
        center.z += 0.10 * math.sin(math.pi * (f - (contact - 14)) / 14)
    out = [{}, {}]
    for i, rig in enumerate(rigs):
        sign = 1 if i == 0 else -1
        if kind == "hug":
            other = rigs[1-i]
            back = d * sign
            for s in "LR":
                # Opposite shoulders remain in separate height bands. Elbows route
                # outside the partner's chest, hands land on the upper back.
                across = lateral * (1 if s == "L" else -1) * sign
                target = _chest(other) + back * (heights[1-i] * 0.065 + 0.012)
                target += across * heights[1-i] * 0.085
                shoulder = _position(rig, f"upper_arm.{s}")
                target.z = (target.z + shoulder.z) / 2 + (0.025 if i == 0 else -0.025)
                out[i][s] = (target, _orientation(palms[i][s][1], -back, -across),
                              across * 1.5 - UP * 0.1)
        elif kind == "pat_shoulder":
            if i:
                continue
            shoulders = [_position(b, f"upper_arm.{s}") for s in "LR"]
            target = min(shoulders, key=lambda p: (p - _position(a)).length).copy()
            target.z += heights[1] * 0.035
            out[i][side] = (target, _orientation(palms[i][side][1], -UP, d),
                            d * -0.3 - UP * 0.5)
        else:
            target = center.copy()
            if kind == "high_five":
                # Palm normal faces the partner and fingers point vertically up.
                normal = d * sign
                fingers = UP
                if f > release:
                    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
                    follow = math.sin(math.pi * min(1, (f-release)/max(4, round(fps*.45))))
                    target += lateral * sign * 0.06 * follow - UP * 0.09 * follow
            elif kind == "fist_bump":
                normal, fingers = -UP, d * sign
            else:
                normal, fingers = -lateral * sign, d * sign
                if side == "L":
                    normal = -normal
                if kind == "handover":
                    # Match the live hold layer's upright prop frame, whose Y
                    # may point opposite the finger bones on a given skeleton.
                    palm_y = palms[i][side][1].to_3x3().col[1]
                    normal = -lateral * sign * (1 if palm_y.y >= 0 else -1)
                    # Two grip sites on opposite sides of the cup/book. The
                    # receiving live attachment preserves the prop's world frame.
                    target -= normal * (grip_gap / 2)
            bone, palm = palms[i][side]
            q = _orientation(palm, normal, fingers)
            if kind == "fist_bump":
                # The folded knuckles, rather than the middle of the palm, meet.
                local = palm.translation + Vector((0, 0.04, 0))
            else:
                local = palm.translation
            out[i][side] = (target, q, -UP * 0.8 - lateral * sign * 0.3, local)
    for i in range(2):
        for s, values in list(out[i].items()):
            if len(values) == 3:
                target, q, pole = values
                _, palm = palms[i][s]
                out[i][s] = (target, q, pole,
                              palm.translation)
    return out


def _approach(rigs, heights, kind, side, start):
    from .walk import walk_path, turn_to, _start, _anatomical_yaw
    sc = bpy.context.scene
    sc.frame_set(max(sc.frame_start, start-1))
    positions = [_position(r).copy() for r in rigs]
    d, _ = _axes(*rigs)
    scale = min(heights) / 1.7
    distance = {"hug": 0.30, "pat_shoulder": 0.53}.get(kind, 0.76) * scale
    common = None
    if kind == "pat_shoulder":
        _, q = head_frame(rigs[0], "hips")
        common = q @ Vector((0, -1, 0))
        common.z = 0
        common.normalize()
        d = q @ Vector((-1 if side == "R" else 1, 0, 0))
        d.z = 0
        d.normalize()
    destination = positions[0] + d * distance
    moved, ends = [], []
    for i, rig in enumerate(rigs):
        target = destination if i else positions[0]
        face = target + common if common is not None else (positions[0] if i else destination)
        _, pos, _, _ = _start(rig, start)
        yaw = _anatomical_yaw(rig)
        goal = math.atan2(face.x-pos.x, -(face.y-pos.y))
        angle = abs((goal-yaw+math.pi) % (2*math.pi)-math.pi)
        travel = (target.xy-pos.xy).length
        if i and kind not in ("hug", "pat_shoulder"):
            # Already closer than the comfortable distance (e.g. right after a hug):
            # backing away would need a full turn-walk-turn. Arm IK reaches anyway.
            cur = (pos.xy - positions[0].xy).length
            want = (target.xy - positions[0].xy).length
            if 0.25 * scale <= cur < want:
                travel = 0.0
        params = dict(armature=rig.name, start_frame=start, ignore=[rigs[1-i].name],
                      _world_route=True)
        if i and travel > 0.035:
            # The partner is ignored only for the final close step. A route that
            # would pass through the partner first walks around them to a point on
            # the destination side (partner treated as an obstacle).
            partner = positions[0].xy
            seg = target.xy - pos.xy
            u = max(0.0, min(1.0, (partner - pos.xy).dot(seg) / max(seg.length_squared, 1e-9)))
            gap = (pos.xy + seg * u - partner).length
            away = target.xy - partner
            first = None
            if (gap < 0.45 * scale / 0.94 and 0.15 < u < 0.85 and away.length > 1e-6
                    and (pos.xy - target.xy).length > 0.3):
                pre = partner + away.normalized() * 0.95
                first = walk_path(points=[list(pre)], armature=rig.name, start_frame=start,
                                  _world_route=True)
                params["start_frame"] = first["next_start_frame"]
            report = walk_path(points=[list(target.xy)], face_end=list(face.xy), **params)
            if first is not None:
                report = dict(report, frames=[first["frames"][0], report["frames"][1]],
                              distance_m=first["distance_m"] + report["distance_m"],
                              avoided=True)
        elif angle > math.radians(3):
            report = turn_to(target=list(face.xy), **params)
        else:
            ends.append(start-1)
            continue
        ends.append(report["frames"][1])
        moved.append({"character": rig.name, "distance_m": report["distance_m"],
                      "frames": report["frames"], "avoided": report.get("avoided", False)})
    ready = max(ends) + 1
    # A partner finishing first waits in its completed standing pose.
    for rig, end in zip(rigs, ends):
        if end >= ready-1:
            continue
        sc.frame_set(max(sc.frame_start, end))
        smap = anim.semantic_map(rig)
        for n in smap.values():
            anim._key_rot(rig.pose.bones[n], ready-1, {})
        rig.pose.bones[smap["hips"]].keyframe_insert("location", frame=ready-1)
    return ready, moved


def _penetration(rigs, heights):
    """Sample chest ellipsoids and arm capsules; not a mesh collision solver."""
    d, _ = _axes(*rigs)
    centers = [_chest(r) for r in rigs]
    depths = [h * 0.075 for h in heights]
    separation = abs((centers[1]-centers[0]).dot(d))
    worst = max(0.0, sum(depths) - separation)
    for i, rig in enumerate(rigs):
        other = 1-i
        _, q = head_frame(rigs[other], "hips")
        inv = q.inverted()
        radii = Vector((heights[other]*0.115, depths[other], heights[other]*0.12))
        for s in "LR":
            points = [_position(rig, f"{key}.{s}") for key in ("upper_arm", "forearm", "hand")]
            for a, b in zip(points, points[1:]):
                for j in range(9):
                    local = inv @ (a.lerp(b, j/8)-centers[other])
                    scaled = Vector(tuple(local[k]/radii[k] for k in range(3)))
                    # Conservative radial surface distance plus a 2.2 cm arm radius.
                    distance = (scaled.length-1) * min(radii)
                    worst = max(worst, 0.022-distance)
    return max(0.0, worst)


def _step_back(rigs, maps, heights, end, fps):
    """After a hug both partners take a short two-step shuffle back to talking
    distance instead of staying chest to chest. The pelvis eases back along the
    line between them; forced foot contacts let foot lock plant, swing and replant
    each foot in turn (left, then right)."""
    from .footlock import lock_feet
    sc = bpy.context.scene
    steps = max(12, round(fps * 0.75))
    sc.frame_set(end)
    centers = [_position(r).copy() for r in rigs]
    for i, (rig, smap) in enumerate(zip(rigs, maps)):
        away = centers[i] - centers[1-i]
        away.z = 0
        if away.length < 1e-6:
            continue
        away = away.normalized() * 0.2 * heights[i] / 1.7
        pb = rig.pose.bones[smap["hips"]]
        sc.frame_set(end)
        origin = (rig.matrix_world @ pb.matrix).translation.copy()
        for f in range(end, end + steps + 1):
            sc.frame_set(f)
            world = rig.matrix_world @ pb.matrix
            u = (f - end) / steps
            anim._set_world_rot(rig, pb, world.to_quaternion(), loc=origin + away * _smoothstep(u))
            pb.keyframe_insert("location", frame=f, group=pb.name)
        third = steps // 3
        last = end + steps + 4
        lock_feet(rig.name, frame_start=end - 2, frame_end=last,
                  contacts={"L": [[end - 2, end + 2], [end + third + 2, last]],
                            "R": [[end - 2, end + third + 2], [end + 2 * third + 3, last]]})
    return [end + 1, end + steps]


@command("interact")
def interact(a, b, kind, start_frame=None, prop=None, approach=True, hold_seconds=None,
             side="right"):
    """Bake a paired reach/contact/retract with shared world-space contact sites."""
    from .script_scene import _bones_only
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}")
    if side not in ("right", "left"):
        raise ValueError("side must be right or left")
    if not isinstance(approach, bool):
        raise ValueError("approach must be a bool")
    duration = {"handshake": 1.0, "hug": 1.0, "high_five": 0.12,
                "fist_bump": 0.25, "handover": 0.5, "pat_shoulder": 0.7}[kind]
    if hold_seconds is not None:
        if isinstance(hold_seconds, bool) or not isinstance(hold_seconds, (int, float)) or not math.isfinite(hold_seconds) or not 0 <= hold_seconds <= 30:
            raise ValueError("hold_seconds must be a finite number in 0..30")
        duration = hold_seconds
    rigs = [_rig_of(a), _rig_of(b)]
    if rigs[0] == rigs[1]:
        raise ValueError("interact needs two different characters")
    maps = [anim.semantic_map(r) for r in rigs]
    required = ["hips", "chest", "neck", "head"] + [f"{k}.{s}" for k in
                ("upper_arm", "forearm", "hand", "thigh", "foot") for s in "LR"]
    for rig, smap in zip(rigs, maps):
        missing = [k for k in required if k not in smap]
        if missing:
            raise ValueError(f"{rig.name}: missing humanoid bones {missing}")
    sc = bpy.context.scene
    start = start_frame
    if start is None:
        start = max([sc.frame_start-1] + [int(r.animation_data.action.frame_range[1])
                    for r in rigs if r.animation_data and r.animation_data.action]) + 1
    if type(start) is not int or start < sc.frame_start:
        raise ValueError("start_frame must be an integer at or after scene start")
    held = None
    if kind == "handover":
        if not prop:
            raise ValueError("handover needs prop held by a (use hold_prop first)")
        held = _prop(prop)
        if (_constraint(held) is None or held.get("c3d_hold_character") != rigs[0].name
                or held.get("c3d_hold_hand") != side
                or held.get("c3d_hold_start", start+1) > start
                or held.get("c3d_hold_release", start+1) <= start):
            raise ValueError("handover prop must be held by a in the selected hand at start_frame")
    s = "R" if side == "right" else "L"
    hands = [HandRig(r) for r in rigs]
    # Procedural props have authored grip origins. A cup starts at its handle:
    # the opposite surface is 9.5 cm + 4.5 cm away, rather than at its center.
    prop_kind = held.get("c3d_prop_kind", "") if held else ""
    grip_gap = {"cup": .14, "book": .04, "phone": .03,
                "handheld_microphone": .05}.get(prop_kind, .09)
    if held:
        grip_gap *= abs(held.matrix_world.to_scale().x)
    palms = [{ss: _palm(r, ss, hand) for ss in "LR"} for r, hand in zip(rigs, hands)]
    sizes = [_height(r, smap) for r, smap in zip(rigs, maps)]
    heights, floors = [v[0] for v in sizes], [v[1] for v in sizes]
    fps = sc.render.fps / sc.render.fps_base
    blend = max(4, round(fps * (2.0 if kind == "handover" else 0.45)))
    saved_frame = sc.frame_current
    history = _history(rigs, start)
    changed = approach
    moved = []
    try:
        with _bones_only():
            reach = start
            if approach:
                reach, moved = _approach(rigs, heights, kind, s, start)
            contact = reach + blend
            release = contact + max(1, round(duration * fps))
            end = release + blend
            names = []
            for i, smap in enumerate(maps):
                # Retain the other arm too: later scripted speaking postures must
                # not turn a single handshake into an unintended second contact.
                active_sides = "LR"
                names.append(list(dict.fromkeys([smap[k] for k in ("chest", "neck", "head")] +
                    [smap[f"{k}.{ss}"] for ss in active_sides for k in ("upper_arm", "forearm", "hand")] +
                    [n for ss in active_sides for ch in hands[i].fingers.get(ss, {}).values() for n in ch])))
            # Snapshot every untouched pose before writing any keys. This also makes
            # reach failures with approach=False leave both actions unchanged.
            base, planned = {}, {}
            for f in range(reach, end+1):
                sc.frame_set(f)
                base[f] = [{n: r.pose.bones[n].matrix_basis.copy() for n in names[i]}
                           for i, r in enumerate(rigs)]
                planned[f] = _targets(rigs, heights, floors, kind, s, f, contact, release, palms, grip_gap)
                if contact <= f <= release:
                    for i, targets in enumerate(planned[f]):
                        for ss, (target, q, pole, local) in targets.items():
                            rig, smap = rigs[i], maps[i]
                            sh, el, wrist = [_position(rig, f"{k}.{ss}") for k in ("upper_arm", "forearm", "hand")]
                            scale = (rig.matrix_world @ rig.pose.bones[smap[f"hand.{ss}"]].matrix).to_scale().x
                            distance = (target - q @ (local * scale) - sh).length
                            if distance > (el-sh).length + (wrist-el).length - 0.002:
                                raise ValueError(f"{rig.name} cannot reach {kind} contact ({distance:.3f} m, arm {(el-sh).length + (wrist-el).length:.3f} m, target {vec(target)}, shoulder {vec(sh)}); use approach=True or move the characters closer")
            previous = [{}, {}]
            changed = True
            errors, site_errors, penetrations, samples = [], [], [], []
            for f in range(reach, end+1):
                sc.frame_set(f)
                weight = _smoothstep((f-reach)/blend) * (1-_smoothstep((f-release)/blend))
                for i, rig in enumerate(rigs):
                    for n, m in base[f][i].items():
                        rig.pose.bones[n].matrix_basis = m
                bpy.context.view_layer.update()
                face_points = [head_frame(r)[0] for r in rigs]
                contacts = []
                for i, rig in enumerate(rigs):
                    smap = maps[i]
                    hp, facing = head_frame(rig)
                    toward = _position(rigs[1-i])-_position(rig)
                    left = UP.cross(toward).normalized()
                    if left.length < 1e-6:
                        left = facing @ Vector((1, 0, 0))
                    chest = rig.pose.bones[smap["chest"]]
                    world = rig.matrix_world @ chest.matrix
                    anim._set_world_rot(rig, chest, Quaternion(left, math.radians(2)*weight) @ world.to_quaternion())
                    bpy.context.view_layer.update()
                    # Anatomical frame avoids assuming any rig's bone-roll axes.
                    head = rig.pose.bones[smap["head"]]
                    hp, facing = head_frame(rig)
                    desired = (face_points[1-i]-hp).normalized()
                    forward = facing @ Vector((0, -1, 0))
                    if kind == "hug":
                        # Look past the partner's shoulder (each to their own right) so
                        # faces never press into the partner's head.
                        flat = Vector((desired.x, desired.y, 0))
                        flat = flat.normalized() if flat.length > 1e-6 else Vector((forward.x, forward.y, 0)).normalized()
                        flat = Quaternion(UP, math.radians(-32)) @ flat
                        desired = (flat + UP * math.tan(math.radians(-8))).normalized()
                    # Neck pitch stays natural (eyes cover larger height gaps).
                    # Swing as yaw about world up, then pitch about the turned side
                    # axis: a combined shortest-arc rotation would roll the head.
                    f_flat = Vector((forward.x, forward.y, 0))
                    d_flat = Vector((desired.x, desired.y, 0))
                    if f_flat.length > 1e-6 and d_flat.length > 1e-6:
                        f_flat.normalize()
                        d_flat.normalize()
                        limit = math.radians(70 if kind == "pat_shoulder" else 55)
                        yaw = math.atan2(f_flat.cross(d_flat).z, f_flat.dot(d_flat))
                        yaw = max(-limit, min(limit, yaw))
                        yaw_q = Quaternion(UP, yaw)
                        pitch = (math.atan2(desired.z, Vector((desired.x, desired.y)).length)
                                 - math.atan2(forward.z, Vector((forward.x, forward.y)).length))
                        pitch = max(math.radians(-30), min(math.radians(22), pitch))
                        axis = (yaw_q @ f_flat).cross(UP).normalized()
                        turn = Quaternion(axis, pitch) @ yaw_q
                    else:
                        turn = Quaternion()
                    q = Quaternion().slerp(turn, weight)
                    if kind == "hug":
                        q = Quaternion(forward, math.radians(14)*weight) @ q
                    head_q = (rig.matrix_world @ head.matrix).to_quaternion()
                    neck = rig.pose.bones[smap["neck"]]
                    neck_q = (rig.matrix_world @ neck.matrix).to_quaternion()
                    anim._set_world_rot(rig, neck, Quaternion().slerp(q, .25) @ neck_q)
                    bpy.context.view_layer.update()
                    anim._set_world_rot(rig, head, q @ head_q)
                    bpy.context.view_layer.update()
                    for ss, (target, q, pole, local) in planned[f][i].items():
                        hand = rig.pose.bones[smap[f"hand.{ss}"]]
                        original = rig.matrix_world @ hand.matrix
                        rot = original.to_quaternion().slerp(q, weight)
                        point = (original @ local).lerp(target, weight)
                        wrist = point - rot @ (local * original.to_scale().x)
                        chain = [smap[f"{k}.{ss}"] for k in ("upper_arm", "forearm", "hand")]
                        base_pole = (_position(rig, f"forearm.{ss}")-
                                     _position(rig, f"upper_arm.{ss}")).normalized()
                        pole = base_pole.lerp(pole.normalized(), weight)
                        _chain(rig, chain, wrist, pole, rot)
                        # A held cup's live upright layer may change wrist rotation.
                        # Solve the actual constrained palm, rather than an assumed
                        # unconstrained wrist frame, without disabling its grip.
                        if hand.constraints:
                            for _ in range(4):
                                current = rig.matrix_world @ hand.matrix
                                delta = point - current @ local
                                if delta.length < 0.0001:
                                    break
                                _chain(rig, chain, current.translation + delta, pole, rot)
                        shape = {"handshake": "grip", "high_five": "open", "hug": "relaxed",
                                 "fist_bump": "fist", "handover": "grip", "pat_shoulder": "palm"}[kind]
                        for n, fq in hands[i].rotations(ss, shape).items():
                            pb = rig.pose.bones[n]
                            _, bq, bs = base[f][i][n].decompose()
                            pb.matrix_basis = Matrix.LocRotScale(pb.location, bq.slerp(fq, weight), bs)
                        bpy.context.view_layer.update()
                        if contact <= f <= release:
                            actual = (rig.matrix_world @ hand.matrix) @ local
                            error = (actual-target).length
                            site_errors.append(error)
                            contacts.append(actual.copy())
                            samples.append({"frame": f, "character": rig.name, "side": ss,
                                            "target": vec(target), "actual": vec(actual)})
                    for n in names[i]:
                        anim._key_rot(rig.pose.bones[n], f, previous[i])
                if contact <= f <= release:
                    if kind in ("handshake", "high_five", "fist_bump"):
                        errors.append((contacts[0]-contacts[1]).length)
                    if kind == "hug":
                        penetrations.append(_penetration(rigs, heights))
            for rig, touched in zip(rigs, names):
                for fc in _fcurves(rig.animation_data.action):
                    if any(fc.data_path.startswith(f'pose.bones["{n}"].rotation_') for n in touched):
                        for key in fc.keyframe_points:
                            if reach <= key.co.x <= end:
                                key.interpolation = "LINEAR"
            step_back = None
            if kind == "hug":
                step_back = _step_back(rigs, maps, heights, end, fps)
                end = step_back[1]
            anim._extend_range(end)
        transfer = None
        if held:
            transfer = transfer_prop(rigs[0], rigs[1], held, side, contact)
        return {"a": rigs[0].name, "b": rigs[1].name, "kind": kind,
                "frames": {"approach": [start, reach-1] if reach > start else None,
                           "reach": reach, "contact": contact, "release": release, "end": end,
                           "step_back": step_back},
                "next_start_frame": end+1,
                "contact_error_m": round(max(errors or site_errors, default=0), 6),
                "max_site_error_m": round(max(site_errors, default=0), 6),
                "penetration_m": round(max(penetrations, default=0), 6) if kind == "hug" else None,
                "moved": moved, "contact_samples": samples, "transfer": transfer,
                "grip_gap_m": round(grip_gap, 5) if held else None,
                "bones": {r.name: n for r, n in zip(rigs, names)},
                "contact_measure": "grip/back/shoulder site error" if kind in ("handover", "hug", "pat_shoulder") else "shared palm/knuckle point error",
                "limits": "sampled chest/arm proxies; no mesh, cloth or dynamic collision solver"}
    finally:
        _restore_history(history, split=changed)
        sc.frame_set(saved_frame)
