"""Contact and hand performance for the original procedural motion scores.

Body scores travel through anim._drive; contacts are solved on the final skeleton,
using the same world-space limb solver, palm frames and live grips as seating and
interactions. No new rig, attachment system or downloaded motion assets.
"""
from contextlib import contextmanager
import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from ..motion_library import BASES, FLOOR, MOTIONS, ease, phrase, score
from . import anim
from .fingers import HandRig, SHAPES, blend_shapes
from .gaze import head_frame
from .holding import _palm
from .seating import _chain
from .talk import _fcurves


def held_props(rig, frame):
    return [o for o in bpy.context.scene.objects if o.get("c3d_hold_character") == rig.name
            and o.get("c3d_hold_start", frame+1) <= frame
            and o.get("c3d_hold_release", frame+1) > frame]


def held_prop(rig, kind, frame):
    return next((o for o in held_props(rig, frame) if o.get("c3d_prop_kind") == kind), None)


def _fk_ready(rig):
    if rig.get("c3d_rig_type") == "rigify":
        for bone in rig.pose.bones:
            if "IK_FK" in bone:
                bone["IK_FK"] = 1.0
        # Procedural scores drive FK controls; refresh the selected mode before
        # sampling or solving the limbs on a freshly created rig.
        rig.update_tag(refresh={"OBJECT"})
        bpy.context.view_layer.update()


def validate(rig, name, frame, phase):
    if phase not in ("full", "down", "hold", "up") or (phase != "full" and name != "kneel"):
        raise ValueError("phase is full, or down/hold/up for kneel")
    if MOTIONS[name]["required_seat"] and not (rig.get("c3d_seated") and rig.get("c3d_seat_active", True)):
        raise ValueError("type needs a seated character; call sit_on first")
    for kind in MOTIONS[name]["required_props"]:
        if held_prop(rig, kind, frame) is None:
            raise ValueError(f"{name} needs a held {kind}; call hold_prop first")
    _fk_ready(rig)


def prepare_typing(rig):
    """Script convenience: furnish an empty typing beat with the existing props."""
    from .environment import add_prop
    smap = anim.semantic_map(rig)
    hip = (rig.matrix_world @ rig.pose.bones[smap["hips"]].matrix).translation
    nearby = [o for o in bpy.context.scene.objects if o.get("c3d_prop_kind") in ("laptop", "desk")
              and (o.matrix_world.translation.xy-hip.xy).length < 1.1]
    if any(o.get("c3d_prop_kind") == "laptop" for o in nearby):
        return []
    height, floor = _landmarks(rig, smap)
    scale = height/1.7
    _, q = head_frame(rig, "hips")
    front = q @ Vector((0, -1, 0))
    front.z = 0
    front.normalize()
    yaw = math.degrees(math.atan2(front.x, -front.y))+180
    created = []
    desk = next((o for o in nearby if o.get("c3d_prop_kind") == "desk"), None)
    if desk is None:
        p = hip+front*.60*scale
        p.z = floor
        made = add_prop("desk", location=list(p), rotation_z=yaw, scale=.75*scale)
        desk = bpy.data.objects[made["root"]]
        created.append(desk.name)
    p = hip+front*.43*scale
    p.z = (desk.matrix_world @ Vector((0, 0, 1.02))).z+.008*scale
    created.append(add_prop("laptop", location=list(p), rotation_z=yaw, scale=scale)["root"])
    return created


def seated_samples(rig, name, start, end):
    if name in FLOOR or MOTIONS[name]["category"] in ("dance", "fight"):
        return None
    if not (rig.get("c3d_seated") and rig.get("c3d_seat_active", True)):
        return None
    smap = anim.semantic_map(rig)
    names = [n for b, n in smap.items() if b == "hips" or b.split(".")[0] in ("thigh", "shin", "foot", "toe")]
    poses = {}
    for f in range(start, end+1):
        bpy.context.scene.frame_set(f)
        poses[f] = {n: rig.pose.bones[n].matrix_basis.copy() for n in names}
    return poses


def _linear(rig, start, end):
    for fc in _fcurves(rig.animation_data.action):
        if fc.data_path.startswith('pose.bones['):
            for k in fc.keyframe_points:
                if start <= k.co.x <= end:
                    k.interpolation = "LINEAR"


@contextmanager
def _visible_skin(rig):
    hidden = [o for o in rig.children_recursive if o.type == "MESH" and o.hide_viewport and not o.hide_render]
    try:
        for obj in hidden:
            obj.hide_viewport = False
        bpy.context.view_layer.update()
        yield
    finally:
        for obj in hidden:
            obj.hide_viewport = True
        bpy.context.view_layer.update()


def _floor_low(rig):
    """Evaluated skin/clothing surface, including contact padding from real meshes."""
    import numpy as np
    lows = []
    with _visible_skin(rig):
        deps = bpy.context.evaluated_depsgraph_get()
        for obj in rig.children_recursive:
            if obj.type != "MESH" or obj.hide_render or obj.get("c3d_role") == "environment":
                continue
            ev = obj.evaluated_get(deps)
            mesh = ev.to_mesh()
            try:
                if not mesh.vertices:
                    continue
                co = np.empty(len(mesh.vertices)*3)
                mesh.vertices.foreach_get("co", co)
                m = np.asarray(ev.matrix_world)
                lows.append(float((co.reshape(-1, 3) @ m[2, :3] + m[2, 3]).min()))
            finally:
                ev.to_mesh_clear()
    return min(lows) if lows else rig.matrix_world.translation.z


def _hand_states(name, t):
    """Targets relative to neck, in height units, +X left / -Y front / +Z up.

    A None target keeps the authored arm. Hand placement runs after retarget so
    bent MPFB rest elbows and Rigify bone rolls cannot change the contact point.
    """
    p = 2*math.pi*t
    s = math.sin(p)
    loop = MOTIONS[name]["loops"]
    w = 1. if loop else phrase(t, .27, .72)
    out = {}
    def hand(side, target, shape="relaxed", palm=None, weight=None):
        out[side] = (target, shape, palm, w if weight is None else weight)
    if name == "confident":
        for side, sign in (("L", 1), ("R", -1)):
            hand(side, (sign*.11, .012, -.25), "beat", (0, 0, -1))
    elif name in ("shy", "nervous", "arms_crossed"):
        high = name == "arms_crossed"
        for side, sign in (("L", 1), ("R", -1)):
            hand(side, (-sign*(.085 if high else .025), -.105-(.006*s if name == "nervous" else 0),
                        (-.14 if high else -.26) + (.024 if side == "L" else 0)), "beat" if high else "relaxed", (0, 1, 0))
    elif name == "cry":
        for side, sign in (("L", 1), ("R", -1)):
            hand(side, (sign*.043, -.075, .035), dict(SHAPES["palm"], spread=0), (0, 1, 0))
    elif name in ("facepalm", "thinking", "cover_mouth", "eat"):
        target = {"facepalm": (-.01, -.078, .085), "thinking": (-.022, -.072, -.025),
                  "cover_mouth": (-.006, -.082, .012), "eat": (-.015, -.085, .005)}[name]
        shape = "fist" if name == "thinking" else "beat" if name == "eat" else dict(SHAPES["palm"], spread=0)
        hand("R", target, shape, (0, 1, 0))
    elif name == "shrug":
        for side, sign in (("L", 1), ("R", -1)):
            hand(side, (sign*.19, -.125, -.13), "open", (0, 0, 1))
    elif name in ("startle", "surprised", "block"):
        if name in ("startle", "surprised"):
            from ..motion_library import track
            w = track(t, [(0, 0), (.13, 1), (.32, .7), (.65, .3), (1, 0)])
        for side, sign in (("L", 1), ("R", -1)):
            hand(side, (sign*.11, -.15, -.02), "fist" if name == "block" else "open", (0, -1, 0), w)
    elif name == "clap":
        gap = .009+.065*(.5+.5*math.cos(3*p))
        for side, sign in (("L", 1), ("R", -1)):
            hand(side, (sign*gap, -.19, -.13), dict(SHAPES["palm"], spread=1), (-sign, 0, 0), ease(t/.12)*(1-ease((t-.9)/.1)))
    elif name in ("point", "disagree", "beckon"):
        hand("R", (-.12+(.035*s if name == "disagree" else 0), -.28 if name == "point" else -.21,
                    -.07 if name != "beckon" else -.12),
             "point" if name == "point" else "palm", (0, 0, 1) if name == "beckon" else (0, 0, -1) if name == "point" else (0, -1, 0))
    elif name == "stretch":
        for side, sign in (("L", 1), ("R", -1)):
            hand(side, (sign*.15, -.01, .21), "open", (0, 0, 1))
    elif name == "read_book":
        hand("R", (-.075, -.20, -.11), "beat", (1, 0, 0))
        hand("L", (.045, -.20, -.11), "palm", (0, 0, 1))
    elif name == "type":
        for side, sign in (("L", 1), ("R", -1)):
            hand(side, (sign*.075, -.22, -.14+.002*math.sin(8*p+sign)), "relaxed", (0, 0, -1))
    elif name == "dance_traditional":
        for side, sign in (("L", 1), ("R", -1)):
            hand(side, (sign*(.18+.04*math.cos(p)), -.10-.04*sign*s, -.08+.075*sign*s),
                 "palm", (sign*.7, -.7, .3))
    elif name == "pick_up":
        hand("R", (-.09, -.24, -.5), "grip", (0, 0, -1))
    return out


def _landmarks(rig, smap):
    mw = rig.matrix_world
    floor = mw.translation.z
    height = (mw @ rig.data.bones[smap["head"]].tail_local).z-floor
    return max(.3, height*1.04), floor


def face_sites(rig, smap, height):
    """Anatomical contact points in head-bone space, calibrated on neutral assets.

    MPFB's head bone center sits above the eyes. Teeth/lashes/brows provide actual
    lip, eye and forehead heights; a mannequin uses its authored head proportions.
    Rest mesh coordinates avoid dependence on the current pose or facial keys.
    """
    head_bone = rig.data.bones[smap["head"]]
    rest = rig.matrix_world @ head_bone.matrix_local
    left = (rig.matrix_world.to_3x3() @ (rig.data.bones[smap["thigh.L"]].head_local-
                                       rig.data.bones[smap["thigh.R"]].head_local)).normalized()
    up = rig.matrix_world.to_3x3() @ (head_bone.tail_local-rig.data.bones[smap["hips"]].head_local)
    up = (up-left*left.dot(up)).normalized()
    back = -left.cross(up).normalized()
    q = Matrix((left, back, up)).transposed().to_quaternion()
    origin = rig.matrix_world @ ((head_bone.head_local+head_bone.tail_local)/2)
    mpfb = any(o.get("c3d_source") == "mpfb" for o in rig.children_recursive)
    sites = {"mouth": Vector((0, -.066 if mpfb else -.052, -.060 if mpfb else -.025))*height,
             "eyes": Vector((0, -.060, -.022 if mpfb else .015))*height,
             "forehead": Vector((0, -.060, .002 if mpfb else .04))*height}
    for obj in rig.children_recursive:
        if obj.type != "MESH":
            continue
        name = obj.name.lower()
        kind = "mouth" if "teeth" in name else "eyes" if "eyelash" in name else "forehead" if "eyebrow" in name else None
        if kind is None:
            continue
        points = [q.inverted() @ (obj.matrix_world @ v.co-origin) for v in obj.data.vertices]
        if not points:
            continue
        low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        center = (low+high)/2
        center.x = 0
        center.y = low.y-(.008 if kind == "mouth" else .004)*height
        center.z += (.005 if kind == "mouth" else .018 if kind == "forehead" else 0)*height
        sites[kind] = center
    sites["chin"] = sites["mouth"]+Vector((0, .008, -.025))*height
    for side, sign in (("L", 1), ("R", -1)):
        sites["ear."+side] = sites["eyes"]+Vector((sign*.052, .050, -.008))*height
    inv = rest.inverted()
    return {key: inv @ (origin+q @ point) for key, point in sites.items()}


def _dance_feet(rig, start, end, period, height):
    from .footlock import foot_lock, _intervals
    sc = bpy.context.scene
    smap = anim.semantic_map(rig)
    sc.frame_set(start)
    _, q = head_frame(rig, "hips")
    left = q @ Vector((1, 0, 0))
    rest_left = rig.matrix_world.to_3x3() @ (rig.data.bones[smap["thigh.L"]].head_local-
                                          rig.data.bones[smap["thigh.R"]].head_local)
    turn = Quaternion((0, 0, 1), math.atan2(left.y, left.x)-math.atan2(rest_left.y, rest_left.x))
    targets, contacts = {}, {}
    for side, sign in (("L", 1), ("R", -1)):
        pb = rig.pose.bones[smap[f"foot.{side}"]]
        # Rest orientation keeps both soles level, independently of the hip sway.
        m = rig.matrix_world @ pb.matrix
        pos = m.translation.copy()
        rest_q = turn @ (rig.matrix_world @ pb.bone.matrix_local).to_quaternion()
        # The first score frame already flexes the knees. Snap the sole to ground.
        from .footlock import _sole_points, _legs
        legs, _ = _legs(rig)
        sole = _sole_points(rig, legs[side], rig.matrix_world.translation.z)
        pos.z = rig.matrix_world.translation.z-min((rest_q @ (p*rig.matrix_world.to_scale().x)).z for p in sole)
        track, mask = [], []
        for f in range(start, end+1):
            beat = ((f-start)/period*4) % 4
            if side == "R":
                beat = (beat-1) % 4
            if beat < 1:
                offset, lift = ease(beat), math.sin(math.pi*beat)**2
            elif beat < 2:
                offset, lift = 1., 0.
            elif beat < 3:
                offset, lift = 1-ease(beat-2), math.sin(math.pi*(beat-2))**2
            else:
                offset, lift = 0., 0.
            target = pos+left*(sign*.027*height*offset)+Vector((0, 0, .018*height*lift))
            track.append((target, rest_q.copy()))
            mask.append(lift < .001)
        targets[side] = track
        contacts[side] = [[start+a, start+b] for a, b in _intervals(mask, fill=0, min_len=1)]
    report = foot_lock(rig, start, end, contacts=contacts, foot_targets=targets, terrain=False)
    return {"contacts": contacts, "max_ik_error_m": report["max_ik_error_m"],
            "hips_lowered_max_m": report["hips_lowered_max_m"]}


def finish(rig, name, start, end, period, amplitude, lower=None, lock=True, keyed=True, pose_time=None):
    """Post-retarget hands, floor skin contact and final contact reports."""
    sc = bpy.context.scene
    smap = anim.semantic_map(rig)
    height, floor = _landmarks(rig, smap)
    sites = face_sites(rig, smap, height)
    hands = HandRig(rig)
    palms = {s: _palm(rig, s, hands) for s in "LR"}
    props = {k: held_prop(rig, k, start) for k in MOTIONS[name]["required_props"]}
    touched = set()
    previous, errors, floor_errors = {}, [], []
    planted_xy = None
    report = {}
    if lock and not lower:
        if MOTIONS[name]["category"] == "dance":
            report["foot_lock"] = _dance_feet(rig, start, end, period, height)
        elif name not in FLOOR:
            contacts = {s: [[start, end]] for s in "LR"}
            if name == "kick":
                contacts["R"] = [[start, start+round(period*.12)], [start+round(period*.9), end]]
            report["foot_lock"] = anim._lock(rig, start, end, contacts)
    # Sample once before writing: never read back an earlier frame's new keys.
    samples = {}
    all_names = set(smap.values()) | set(hands.bones)
    for f in range(start, end+1):
        if keyed:
            sc.frame_set(f)
        samples[f] = {n: rig.pose.bones[n].matrix_basis.copy() for n in all_names}
    for f in range(start, end+1):
        if keyed:
            sc.frame_set(f)
        for n, m in samples[f].items():
            rig.pose.bones[n].matrix_basis = m
        if lower:
            for n, m in lower[f].items():
                rig.pose.bones[n].matrix_basis = m
                touched.add(n)
        bpy.context.view_layer.update()
        t = (f-start)/period if pose_time is None else pose_time
        t = t % 1 if MOTIONS[name]["loops"] else min(1., t)
        if name in ("kneel", "pick_up"):
            # Retargeted hip/leg lengths differ slightly from the proxy. Keep
            # the authored ankle positions in XY on the actual final skeleton.
            feet = [(rig.matrix_world @ rig.pose.bones[smap[f"foot.{s}"]].matrix).translation.copy()
                    for s in "LR"]
            if planted_xy is None:
                planted_xy = feet
            correction = sum((a-b for a, b in zip(planted_xy, feet)), Vector())/2
            correction.z = 0
            hp = rig.pose.bones[smap["hips"]]
            m = rig.matrix_world @ hp.matrix
            anim._set_world_rot(rig, hp, m.to_quaternion(), m.translation+correction)
            bpy.context.view_layer.update()
            touched.add(hp.name)
            # A hip translation cannot remove symmetric sideways changes in
            # stance width. Resolve each final leg without changing foot pitch.
            for side, anchor in zip("LR", planted_xy):
                names = [smap[f"{b}.{side}"] for b in ("thigh", "shin", "foot")]
                h, k, a = [(rig.matrix_world @ rig.pose.bones[n].matrix).translation for n in names]
                goal = Vector((anchor.x, anchor.y, a.z))
                pole = k-(h+a)/2
                if pole.length < 1e-5:
                    pole = head_frame(rig, "hips")[1] @ Vector((0, -1, 0))
                q = (rig.matrix_world @ rig.pose.bones[names[-1]].matrix).to_quaternion()
                _chain(rig, names, goal, pole, q)
                touched.update(names)
        if name in FLOOR:
            # Grounding uses visible evaluated skin, so knees/buttocks/back touch
            # the real floor on different body builds and through rig scaling.
            low = _floor_low(rig)
            hp = rig.pose.bones[smap["hips"]]
            m = rig.matrix_world @ hp.matrix
            m.translation.z += floor-low
            anim._set_world_rot(rig, hp, m.to_quaternion(), m.translation)
            bpy.context.view_layer.update()
            touched.add(hp.name)
            if f in (start, (start+end)//2, end):
                floor_errors.append(abs(_floor_low(rig)-floor))
        neck = (rig.matrix_world @ rig.pose.bones[smap["neck"]].matrix).translation
        _, body_q = head_frame(rig, "chest")
        head, face_q = head_frame(rig)
        head_matrix = rig.matrix_world @ rig.pose.bones[smap["head"]].matrix
        mouth = head_matrix @ sites["mouth"]
        states = _hand_states(name, t)
        if name in ("lie_down", "get_up", "sit_floor", "fall_down"):
            q = 1-t if name == "get_up" else t
            for side in "LR":
                states[side] = (None, "palm", (0, 0, -1), ease((q-.2)/.28)*(1-ease((q-.78)/.22)))
        # Required props choose whichever hand actually holds them.
        for kind, obj in props.items():
            side = "L" if obj["c3d_hold_hand"] == "left" else "R"
            if name == "drink":
                states.pop("R", None)
                states[side] = (None, "fist", None, phrase(t, .3, .65))
            elif name == "phone_call":
                states[side] = (None, "beat", None, 1.)
            elif name == "read_book" and side == "L":
                states = {"L": ((.075, -.20, -.11), "beat", (-1, 0, 0), 1.),
                          "R": ((-.045, -.20, -.11), "palm", (0, 0, 1), 1.)}
        book_side = ("L" if props["book"]["c3d_hold_hand"] == "left" else "R") if name == "read_book" else None
        sides = (book_side, "R" if book_side == "L" else "L") if book_side else "LR"
        for side in sides:
            shape = "fist" if name in ("angry", "punch", "kick", "block", "dodge", "hit_react") else "relaxed"
            target, palm_dir, weight = None, None, 1.
            if side in states:
                xyz, shape, palm_dir, weight = states[side]
                target = neck+body_q @ (Vector(xyz)*height) if xyz else None
                if name in ("lie_down", "get_up", "sit_floor", "fall_down"):
                    hip = (rig.matrix_world @ rig.pose.bones[smap["hips"]].matrix).translation
                    _, root_q = head_frame(rig, "hips")
                    target = hip+root_q @ Vector(((.14 if side == "L" else -.14)*height, .10*height, 0))
                    target.z = floor+.035*height
                elif name == "pick_up":
                    hip = (rig.matrix_world @ rig.pose.bones[smap["hips"]].matrix).translation
                    _, root_q = head_frame(rig, "hips")
                    target = hip+root_q @ Vector((-.09*height, -.21*height, 0))
                    target.z = floor+.045*height
                    shape = blend_shapes("open", "grip", ease((t-.42)/.13))
                if name in ("facepalm", "thinking", "cover_mouth", "eat") and side == "R":
                    site = "forehead" if name == "facepalm" else "chin" if name == "thinking" else "mouth"
                    target = head_matrix @ sites[site]
                    target += face_q @ Vector((-.008*height, -.008*height, 0))
                elif name == "cry":
                    target = head_matrix @ sites["eyes"]
                    target += face_q @ Vector(((.027 if side == "L" else -.027)*height, -.009*height, -.005*height))
                elif name in ("block", "startle", "surprised"):
                    target = head_matrix @ sites["eyes" if name == "block" else "mouth"]
                    target += face_q @ Vector(((1 if side == "L" else -1)*(.075 if name == "block" else .10)*height,
                                                -.035*height, 0 if name == "block" else .02*height))
            if name == "excited":
                shape = "open"
            if name == "beckon" and side == "R":
                shape = blend_shapes("open", "beat", .5+.5*math.sin(8*math.pi*t))
            if name == "type":
                shape = dict(SHAPES["relaxed"])
                for j, finger in enumerate(("index", "middle", "ring", "pinky")):
                    tap = (.5+.5*math.sin(2*math.pi*(4*t+j*.21+(0 if side == "L" else .43))))**4
                    shape[finger] = (8+9*tap, 14+17*tap, 8+12*tap)
                # Use a nearby authored keyboard/table plane when available.
                candidates = [o for o in sc.objects if o.get("c3d_prop_kind") in ("laptop", "desk")]
                if candidates:
                    desk = min(candidates, key=lambda o: (o.matrix_world.translation-neck).length)
                    local = ((.10 if side == "L" else -.10), -.035, .065) if desk.get("c3d_prop_kind") == "laptop" else ((.13 if side == "L" else -.13), -.15, 1.045)
                    # A keyboard facing the character is usually turned 180°.
                    # Keep the anatomical left/right hands on their own halves.
                    left = body_q @ Vector((1, 0, 0))
                    if desk.matrix_world.to_3x3().col[0].dot(left) < 0:
                        local = (-local[0], local[1], local[2])
                    p = desk.matrix_world @ Vector(local)
                    if (p-neck).length < .5*height:
                        target = p
            bone, palm = palms[side]
            pb = rig.pose.bones[bone]
            if name == "read_book" and side != book_side:
                ev = props["book"].evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world
                target = ev @ Vector((0, .045, -.065))
                palm_dir = (0, 0, 1)
            if name in ("drink", "phone_call"):
                kind = "cup" if name == "drink" else "phone"
                obj = props[kind]
                held_side = "L" if obj["c3d_hold_hand"] == "left" else "R"
                if side == held_side:
                    bpy.context.view_layer.update()
                    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world
                    if kind == "cup":
                        # Cup rim nearest the face; the existing grip keeps it upright.
                        contact = ev @ Vector((.095, -.035, .019))
                        goal = mouth
                    else:
                        contact = ev @ Vector((0, 0, .078))
                        goal = head_matrix @ sites["ear."+side]
                    wrist = (rig.matrix_world @ pb.matrix).translation
                    target = wrist+(goal-contact)
                    if kind == "phone":
                        # Upright phone plane beside the ear, rather than across the face.
                        palm_dir = (-1 if side == "L" else 1, 0, 0)
            if target is not None and weight > 1e-5:
                wrist = (rig.matrix_world @ pb.matrix).translation
                palm_goal = None
                if name not in ("drink", "phone_call"):
                    palm_now = (rig.matrix_world @ pb.matrix) @ palm.translation
                    palm_goal = palm_now.lerp(target, weight*min(amplitude, 1.))
                    target -= (rig.matrix_world @ pb.matrix).to_3x3() @ palm.translation
                goal = wrist.lerp(target, weight*min(amplitude, 1.))
                pole = body_q @ Vector((.5 if side == "L" else -.5, .15, -.8))
                if name in ("drink", "phone_call"):
                    # A high wrist close to the head needs an anterior, low
                    # elbow pole; an outward pole lifts the elbow behind the ear.
                    pole = body_q @ Vector((.12 if side == "L" else -.12, -.55, -1.2))
                _chain(rig, [smap[f"{b}.{side}"] for b in ("upper_arm", "forearm", "hand")], goal, pole)
                if name == "read_book" and side == book_side:
                    normal = (head-target).normalized()
                    up = Vector((0, 0, 1))
                    z_axis = (up-normal*normal.dot(up)).normalized()
                    y_axis = z_axis.cross(normal).normalized()
                    prop_q = Matrix((normal, y_axis, z_axis)).transposed().to_quaternion()
                    current_q = (rig.matrix_world @ pb.matrix).to_quaternion()
                    anim._set_world_rot(rig, pb, current_q.slerp(prop_q @ palm.to_quaternion().inverted(), weight))
                    bpy.context.view_layer.update()
                if palm_dir and hands.palm_local(side, bone) is not None and name != "drink":
                    from .gesture import _orient_palm
                    direction = (body_q @ Vector(palm_dir)).normalized()
                    if name in ("facepalm", "thinking", "cover_mouth", "eat", "cry"):
                        direction = face_q @ Vector((0, 1, 0))
                    _orient_palm(rig, rig.pose.bones[smap[f"forearm.{side}"]], pb,
                                 hands.palm_local(side, bone), direction, weight, forearm_share=.65)
                    axis = None
                    if name in ("point", "type", "shrug", "beckon"):
                        axis = body_q @ Vector((0, -1, 0))
                    elif name in ("facepalm", "thinking", "cry", "clap"):
                        axis = (face_q if name != "clap" else body_q) @ Vector((0, 0, 1))
                    elif name in ("cover_mouth", "eat"):
                        axis = face_q @ Vector((1, 0, 0))
                    elif name == "arms_crossed":
                        axis = body_q @ Vector((-1 if side == "L" else 1, 0, .1))
                    if axis is not None:
                        from .interaction import _orientation
                        current = (rig.matrix_world @ pb.matrix).to_quaternion()
                        desired = _orientation(palm, direction, axis)
                        anim._set_world_rot(rig, pb, current.slerp(desired, weight))
                        bpy.context.view_layer.update()
                if palm_goal is not None:
                    # Palm orientation may translate the wrist on bent-rest rigs.
                    # Preserve the final hand rotation while restoring palm contact.
                    wrist_q = (rig.matrix_world @ pb.matrix).to_quaternion()
                    for _ in range(2):
                        m = rig.matrix_world @ pb.matrix
                        corrected = m.translation+(palm_goal-(m @ palm.translation))
                        _chain(rig, [smap[f"{b}.{side}"] for b in ("upper_arm", "forearm", "hand")], corrected, pole, wrist_q)
                if name in ("drink", "phone_call") and side == held_side:
                    # Wrist rotation changes the live prop's offset from the wrist.
                    # Re-evaluate that attachment after solving/orienting the hand.
                    wrist_q = (rig.matrix_world @ pb.matrix).to_quaternion()
                    if name == "phone_call":
                        screen = Quaternion((0, 0, 1), math.pi if side == "L" else 0)
                        wrist_q = wrist_q.slerp(body_q @ screen @ palm.to_quaternion().inverted(), weight)
                    for _ in range(3):
                        bpy.context.view_layer.update()
                        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world
                        local_contact = Vector((.095, -.035, .019) if name == "drink" else (0, 0, .078))
                        actual = ev @ local_contact
                        wrist = (rig.matrix_world @ pb.matrix).translation
                        desired_contact = mouth if name == "drink" else head_matrix @ sites["ear."+side]
                        corrected = wrist+(desired_contact-actual)*weight
                        _chain(rig, [smap[f"{b}.{side}"] for b in ("upper_arm", "forearm", "hand")], corrected, pole, wrist_q)
                touched.update(smap[f"{b}.{side}"] for b in ("upper_arm", "forearm", "hand"))
            if side in hands.fingers:
                # Absolute shape from rest: retained hold constraints still win on held fingers.
                qshape = blend_shapes("relaxed", shape, min(1., weight*amplitude))
                for n, q in hands.rotations(side, qshape).items():
                    rig.pose.bones[n].matrix_basis = Matrix.Translation(rig.pose.bones[n].location) @ q.to_matrix().to_4x4()
                    touched.add(n)
        if name in FLOOR:
            # Bracing can move the originally lowest hand away from the floor.
            # Ground the completed pose, including those final arm/finger changes.
            low = _floor_low(rig)
            hp = rig.pose.bones[smap["hips"]]
            m = rig.matrix_world @ hp.matrix
            m.translation.z += floor-low
            anim._set_world_rot(rig, hp, m.to_quaternion(), m.translation)
            bpy.context.view_layer.update()
        if keyed:
            for n in touched:
                anim._key_rot(rig.pose.bones[n], f, previous)
                if n == smap["hips"]:
                    rig.pose.bones[n].keyframe_insert("location", frame=f, group=n)
        bpy.context.view_layer.update()
        if name in ("drink", "phone_call") and .35 <= t <= .6:
            obj = props["cup" if name == "drink" else "phone"]
            ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world
            point = ev @ Vector((.095, -.035, .019) if name == "drink" else (0, 0, .078))
            side = "L" if obj["c3d_hold_hand"] == "left" else "R"
            goal = mouth if name == "drink" else head_matrix @ sites["ear."+side]
            errors.append((point-goal).length)
    if keyed:
        _linear(rig, start, end)
    report.update(hand_bones=len(touched), seated_lower_body_preserved=bool(lower))
    if errors:
        report["contact_error_m"] = round(max(errors), 5)
        report["contact_site"] = "cup_rim_to_mouth" if name == "drink" else "phone_to_ear"
    if floor_errors:
        report["floor_contact_error_m"] = round(max(floor_errors), 6)
    if keyed:
        sc.frame_set(start)
    return report


@contextmanager
def preserve_motion(beats):
    """Explicit physical directions keep their authored arms/head over dialog layers."""
    saved = []
    for beat in beats:
        if beat.get("do") != "gesture" or beat.get("name") not in MOTIONS or "result" not in beat:
            continue
        reports = [beat["result"]]
        if beat["result"].get("reaction"):
            reports.append(beat["result"]["reaction"])
        for r in reports:
            rig = bpy.data.objects[r["armature"]]
            lo, hi = r["frames"]
            for fc in _fcurves(rig.animation_data.action):
                if fc.data_path.startswith('pose.bones['):
                    saved.append((fc, lo, hi, [(k.co.x, k.co.y, k.interpolation) for k in fc.keyframe_points if lo <= k.co.x <= hi]))
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


EMOTION_BODY = {"sad": "sad", "anger": "angry", "angry": "angry", "furious": "angry",
                "fear": "nervous", "nervous": "nervous", "joy": "happy", "smile": "happy",
                "happy": "happy", "big_smile": "excited", "surprise": "surprised", "surprised": "surprised",
                "thinking": "bored", "sleepy": "tired", "tired": "tired"}
EMOTION_BODY.update({name: name for name in BASES})


def layer_body(rig, emotion, start, end, intensity=.65):
    """Add only torso/head/shoulder rotations; retain routes, seated hips and arms.

    Samples the base before keying. Uses a canonical proxy for offset rotations,
    then adds those offsets to the final bone basis, preserving authored leg/root
    and all keys outside this line. Talk performance runs after this layer.
    """
    name = EMOTION_BODY.get(emotion)
    if not name or end <= start:
        return None
    _fk_ready(rig)
    smap = anim.semantic_map(rig)
    sc = bpy.context.scene
    bones = [b for b in ("spine", "chest", "neck", "head", "shoulder.L", "shoulder.R") if b in smap]
    base = {}
    for f in range(start, end+1):
        sc.frame_set(f)
        base[f] = {b: rig.pose.bones[smap[b]].matrix_basis.copy() for b in bones}
    # Canonical world Euler offsets, conjugated by the anatomical body heading.
    previous = {}
    for f in range(start, end+1):
        sc.frame_set(f)
        for b in bones:
            rig.pose.bones[smap[b]].matrix_basis = base[f][b]
        bpy.context.view_layer.update()
        _, facing = head_frame(rig, "hips")
        spec, _ = score(name, (f-start)/max(1, end-start))
        fps = sc.render.fps/sc.render.fps_base
        env = ease((f-start)/max(1, .33*fps))*ease((end-f)/max(1, .42*fps))*intensity
        for b in bones:
            v = spec.get(b, (0, 0, 0))
            # Basic X bends forward, basic Y twists; canonical up is world Z.
            q = (Quaternion((0, 0, 1), math.radians(v[1]*env)) @
                 Quaternion((1, 0, 0), math.radians(v[0]*env)) @
                 Quaternion((0, 1, 0), math.radians(v[2]*env)))
            pb = rig.pose.bones[smap[b]]
            current = (rig.matrix_world @ pb.matrix).to_quaternion()
            anim._set_world_rot(rig, pb, facing @ q @ facing.inverted() @ current)
            bpy.context.view_layer.update()
            anim._key_rot(pb, f, previous)
    return {"character": rig.name, "clip": name, "frames": [start, end], "intensity": intensity}


def dialog_body(turns, characters, language="auto", expression_results=None):
    """Explicit emotions win; otherwise use the same sentence classifier as faces."""
    from .emotion import classify
    report = []
    segmented = []
    for turn in turns:
        events = (expression_results or {}).get(turn["speaker"], {}).get("sentences", [])
        if turn.get("emotion") or not events:
            segmented.append(turn)
            continue
        matched = False
        for event in events:
            a, b = event["frames"]
            lo, hi = max(turn["start"], round(a)), min(turn["end"], round(b))
            if hi > lo:
                segmented.append(dict(turn, start=lo, end=hi, emotion=event["emotion"]))
                matched = True
        if not matched:
            segmented.append(turn)
    for turn in segmented:
        emotion = turn.get("body_emotion") or turn.get("emotion")
        if not emotion:
            emotion, _, _ = classify([(w, 0, 1) for w in (turn.get("text") or "").split()], language or "auto")
        rig = anim._target(turn["speaker"])
        r = layer_body(rig, emotion, turn["start"], turn["end"])
        if r:
            report.append(r)
        if emotion in ("sad", "surprise", "surprised"):
            for other in characters:
                if other != rig.name:
                    r = layer_body(anim._target(other), emotion, turn["start"], turn["end"], .22)
                    if r:
                        report.append(r)
    return report


def script_faces(character, ident, beats):
    """Give explicit emotional directions a face through their whole physical beat.

    These beats are sequential, outside speech. Emotion units are isolated from
    visemes/blinks/gaze; laugh/startle may open the jaw only inside that action.
    Sample both boundaries first so neighbouring actions never inherit new keys.
    """
    from .face import _basemesh, _face_meshes, _emotion_values, _set, EMOTION_UNITS
    expressions = {"sad": "sad", "cry": "sad", "angry": "angry", "nervous": "fear",
                   "happy": "smile", "excited": "big_smile", "tired": "sleepy",
                   "confident": "smirk", "shy": "pout", "bored": "neutral",
                   "laugh": "laugh", "startle": "surprised", "surprised": "surprised",
                   "thinking": "thinking", "facepalm": "thinking", "sigh": "sad"}
    mesh = _basemesh(character)
    meshes = _face_meshes(mesh)
    sc = bpy.context.scene
    jobs = []
    for beat in beats:
        name = beat.get("name")
        if beat.get("who") != ident or beat.get("do") != "gesture" or name not in expressions:
            continue
        lo, hi = beat["frames"]
        jaw = name in ("laugh", "startle", "surprised")
        names = EMOTION_UNITS+(["jawOpen"] if jaw else [])
        boundaries = []
        for f in (lo, hi):
            sc.frame_set(f)
            keys = mesh.data.shape_keys.key_blocks
            boundaries.append({n: keys[n].value for n in names if n in keys})
        values = _emotion_values(expressions[name], .6)
        if jaw:
            values["jawOpen"] = .30 if name == "laugh" else .22
        jobs.append((lo, hi, boundaries, values))
    fps = sc.render.fps/sc.render.fps_base
    for lo, hi, (entry, exit_), values in jobs:
        ramp = max(1, min(round(.20*fps), (hi-lo)//3))
        _set(meshes, entry, lo)
        _set(meshes, values, lo+ramp)
        _set(meshes, values, max(lo+ramp, hi-ramp))
        _set(meshes, exit_, hi)
