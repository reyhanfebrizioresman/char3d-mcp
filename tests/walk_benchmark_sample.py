"""Executed inside the owned char3d engine by walk_benchmark.py (no rendering).

Signed sagittal angles use the anatomical forward transported by each bone's
rest-to-pose rotation. The ankle is measured relative to the shin, subtracting
its rest angle; MTP is relative to the foot. Yaw/roll are projected out.
"""
import math
import bpy
from mathutils import Vector, Quaternion
from engine.commands import anim, walk
from engine.commands.footlock import _legs, _sole_points


def signed(a, b, axis):
    a = a - axis * a.dot(axis)
    b = b - axis * b.dot(axis)
    return math.degrees(math.atan2(axis.dot(a.cross(b)), a.dot(b)))


def calibrate():
    """Known independent movements and yaw invariance, before measuring rigs."""
    results = []
    for yaw in (0, .7, -1.4):
        # Signed anatomical FPA must distinguish toe-in from toe-out after
        # arbitrary route rotation, independently of rest-relative bone yaw.
        for side, sign in (('L', 1), ('R', -1)):
            for expected in (-7, 0, 7):
                axis = Quaternion((0,0,1), yaw+sign*math.radians(expected)) @ Vector((0,-1,0))
                actual = math.degrees(walk._angle(yaw, math.atan2(axis.x, -axis.y))) * sign
                assert abs(actual-expected) < .001, (side, actual, expected)
        q = Quaternion((0,0,1),yaw)
        neutral, down = q @ Vector((0,-1,0)), Vector((0,0,-1))
        axis = neutral.cross(Vector((0,0,1)))
        for roll, shin_pitch, toe_relative, expected in (
                (30,-30,0,(30,0,0)), (30,0,0,(30,30,0)), (0,0,45,(0,0,45))):
            fw = Quaternion(axis,math.radians(-roll)) @ neutral
            shin = Quaternion(axis,math.radians(shin_pitch)) @ down
            tw = Quaternion(axis,math.radians(toe_relative)) @ fw
            value = (-math.degrees(math.asin(fw.z)),
                     signed(down,neutral,axis)-signed(shin,fw,axis), signed(fw,tw,axis))
            assert all(abs(a-b)<.001 for a,b in zip(value,expected)), (value,expected)
            results.append(dict(yaw_rad=yaw, measured=value, expected=expected))
    return results


def sample(rig_name, nav):
    rig = bpy.data.objects[rig_name]
    sc = bpy.context.scene
    mw = rig.matrix_world.copy()
    sm = anim.semantic_map(rig)
    legs, _ = _legs(rig)
    rest = {k: mw @ rig.data.bones[v].matrix_local for k, v in sm.items()}
    sole = {s: _sole_points(rig, legs[s], 0) for s in 'LR'}
    neutral = walk._terrain_forward(rig, sm)
    neutral.z = 0
    neutral.normalize()
    up = Vector((0, 0, 1))

    # Bone telemetry must not evaluate every garment/face modifier each frame.
    hidden = [o for o in sc.objects if o.type == 'MESH' and not o.hide_viewport
              and any(m.type == 'ARMATURE' and m.object == rig for m in o.modifiers)]
    for o in hidden:
        o.hide_viewport = True
    rows = []
    last_yaw = None
    last_knee = {}
    fps = sc.render.fps / sc.render.fps_base
    for f in range(nav['frames'][0], nav['frames'][1] + 1):
        sc.frame_set(f)
        mats = {k: mw @ rig.pose.bones[v].matrix for k, v in sm.items()}
        body_yaw = walk._anatomical_yaw(rig)
        planned = getattr(walk, '_benchmark_headings', [])
        yaw = planned[f-nav['frames'][0]] if len(planned) == nav['frames'][1]-nav['frames'][0]+1 else body_yaw
        forward = Vector((math.sin(yaw), -math.cos(yaw), 0))
        lateral = forward.cross(up)
        row = dict(frame=f, pelvis_m=list(mats['hips'].translation), pelvis_yaw_deg=math.degrees(body_yaw),
                   yaw_deg=math.degrees(yaw), yaw_rate_deg_s=0 if last_yaw is None else
                   math.degrees(walk._angle(last_yaw, yaw)) * fps, feet={})
        last_yaw = yaw
        for s in 'LR':
            fk, sk, tk = 'foot.'+s, 'shin.'+s, 'toe.'+s
            foot, shin = mats[fk], mats[sk]
            fw = foot.to_quaternion() @ rest[fk].to_quaternion().inverted() @ neutral
            axis = Vector((fw.x, fw.y, 0)).normalized().cross(up)
            rest_shin = rest[fk].translation-rest[sk].translation
            shin_vector = foot.translation-shin.translation
            ankle = signed(rest_shin, neutral, neutral.cross(up))-signed(shin_vector, fw, axis)
            points = [foot @ p for p in sole[s]]
            mtp = None
            if tk in mats:
                tw = mats[tk].to_quaternion() @ rest[tk].to_quaternion().inverted() @ neutral
                mtp = signed(fw, tw, axis)
                points[1:] = [mats[tk] @ (rest[tk].inverted() @ (rest[fk] @ p)) for p in sole[s][1:]]
            knee = math.degrees((shin.translation-mats['thigh.'+s].translation).angle(shin_vector))
            flat = any(a <= f <= b for a, b in nav['foot_lock']['contacts'][s])
            airborne = any(e['side'] == s and e['lift'] < f < e['land'] for e in nav['support_events'])
            interval_swing = any(e['side'] == s and e['lift'] < f-.5 < e['land'] for e in nav['support_events'])
            # Keep the historical rest-relative yaw for comparison, but measure
            # anatomical progression from the actual heel-to-toe floor axis.
            # Facing -Y, the character's left is +X: positive yaw is outward L.
            fpa = math.degrees(walk._angle(yaw, math.atan2(fw.x, -fw.y)))
            toe_axis = points[-1]-points[0]
            anatomical_fpa = math.degrees(walk._angle(yaw, math.atan2(toe_axis.x, -toe_axis.y)))
            row['feet'][s] = dict(knee_deg=knee,
                knee_delta_deg=abs(knee-last_knee.get(s, knee)),
                foot_roll_deg=-math.degrees(math.atan2(fw.z, math.hypot(fw.x, fw.y))),
                ankle_plantarflexion_deg=ankle, mtp_extension_deg=mtp,
                legacy_progression_deg=fpa * (-1 if s == 'L' else 1),
                progression_outward_deg=anatomical_fpa * (1 if s == 'L' else -1),
                foot_rotation_wxyz=list(foot.to_quaternion()),
                ankle_m=list(foot.translation), heel_m=list(points[0]), toe_m=list(points[-1]),
                sole_gap_m=min(p.z for p in points), interval_support=not interval_swing,
                support='swing' if airborne else 'flat' if flat else 'rolling')
            last_knee[s] = knee
        rows.append(row)
    hold_m = hold_rad = 0.
    for bone in rig.pose.bones:
        sc.frame_set(nav['frames'][1])
        anchor = (mw @ bone.matrix).copy()
        for f in range(nav['frames'][1]-3, nav['frames'][1]+1):
            sc.frame_set(f)
            mat = mw @ bone.matrix
            hold_m = max(hold_m, (mat.translation-anchor.translation).length)
            q = anchor.to_quaternion().rotation_difference(mat.to_quaternion()).angle
            hold_rad = max(hold_rad, min(q, 2*math.pi-q))
    # Evaluate only footwear for the visible outsole contract; keep expensive
    # body/face modifiers hidden. Native buffers avoid Python vertex loops.
    import numpy as np
    shoes = [o for o in hidden if o.get('c3d_garment_category') == 'shoes']
    for o in shoes:
        o.hide_viewport = False
    mesh_penetration = mesh_flat_gap = 0.
    for row in rows if shoes else []:
        sc.frame_set(row['frame'])
        dg = bpy.context.evaluated_depsgraph_get()
        ankles = np.array([row['feet'][s]['ankle_m'] for s in 'LR'])
        for shoe in shoes:
            ev = shoe.evaluated_get(dg)
            me = ev.to_mesh()
            try:
                points = np.empty(len(me.vertices)*3, dtype=np.float32)
                me.vertices.foreach_get('co',points)
                points = points.reshape(-1,3)
                mat = np.array(ev.matrix_world)
                points = points @ mat[:3,:3].T + mat[:3,3]
                if not len(points): continue
                mesh_penetration = max(mesh_penetration, -float(points[:,2].min()))
                side_ids = np.argmin(((points[:,None,:]-ankles[None,:,:])**2).sum(axis=2),axis=1)
                for si,s in enumerate('LR'):
                    chosen = points[side_ids == si,2]
                    if len(chosen) and row['feet'][s]['support'] == 'flat':
                        mesh_flat_gap = max(mesh_flat_gap,abs(float(chosen.min())))
            finally:
                ev.to_mesh_clear()
    for o in hidden:
        o.hide_viewport = False
    return dict(rows=rows, hold_m=hold_m, hold_rad=hold_rad,
                mesh_penetration_m=mesh_penetration, mesh_flat_gap_m=mesh_flat_gap,
                shoe_objects=[o.name for o in shoes],
                dimensions_m=list(rig.dimensions), bones=len(rig.data.bones))
