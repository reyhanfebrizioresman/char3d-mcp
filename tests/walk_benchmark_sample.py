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
from engine.shoe_contact import calibrate as shoe_patches, measure as shoe_measure, vertices as shoe_vertices, touching_points
from engine.body_mass import estimate as body_com


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

    patches = shoe_patches(rig)
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
        com = body_com(rig, sm)
        row['com_m'] = list(com)
        route = nav.get('weight_transfer', {}).get('route_xy_m', [])
        origin = Vector((*route[f-nav['frames'][0]],0)) if route else mats['hips'].translation
        row['pelvis_lateral_m'] = (mats['hips'].translation-origin).dot(lateral)
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
        supports = [s for s in 'LR' if row['feet'][s]['support'] != 'swing']
        row['support_feet'] = supports
        row['com_relative_support_m'] = {s:list(com-Vector(row['feet'][s]['ankle_m'])) for s in supports}
        row['support_segment_xy_m'] = [row['feet'][s]['ankle_m'][:2] for s in supports]
        # Approximate finite support area from sole landmarks, not an ankle
        # line. Width is an engineering footprint approximation, not measured COP.
        area = []
        for s in supports:
            p = row['feet'][s]
            a,b = Vector(p['heel_m']),Vector(p['toe_m'])
            direction = b-a; direction.z=0; direction.normalize()
            across = Vector((-direction.y,direction.x,0))*.045*rig.matrix_world.to_scale().x
            if p['foot_roll_deg'] < -1: b = a+direction*.025
            elif p['foot_roll_deg'] > 1: a = b-direction*.06
            area.extend([list((v+offset))[:2] for v in (a,b) for offset in (across,-across)])
        row['support_area_xy_m'] = area
        row['com_relative_support_area_center_m'] = ([com[k]-sum(p[k] for p in area)/len(area) for k in (0,1)] if area else None)
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
    # Preserve anatomical vertex identity through crossing feet. Nearest posed
    # ankle classification can accidentally measure the opposite support shoe.
    shoes = [o for o in hidden if o.get('c3d_garment_category') == 'shoes']
    for o in shoes: o.hide_viewport = False
    mesh_penetration = mesh_flat_gap = 0.
    probes={s:{} for s in 'LR'}
    for row in rows if shoes else []:
        sc.frame_set(row['frame'])
        xyzs={name:shoe_vertices(bpy.data.objects[name]) for name,_ in patches}
        regions = shoe_measure(patches,xyzs)
        for side in 'LR':
            p = row['feet'][side]
            roll=nav.get('shoe_guard',{}).get('nominal_roll_deg',{}).get(side,[r['feet'][side]['foot_roll_deg'] for r in rows])[row['frame']-nav['frames'][0]]
            active=() if p['support']=='swing' else ('heel',) if roll < -1 else ('ball','toe') if roll > 1 else ('heel','ball')
            touching=touching_points(patches,xyzs,side,active,previous=probes[side])
            probes[side]=touching
            points={k:v[3].tolist() for k,v in touching.items()}
            identities={k:[v[1],v[2]] for k,v in touching.items()}
            p['contact_mesh_points_m']=points;p['contact_mesh_vertex_ids']=identities
            p['active_contact_regions']=list(active)
            p['contact_regions_m'] = regions[side]
            p['arch_clearance_m'] = regions[side].get('arch')
            if not regions[side]: continue
            p['mesh_low_m'] = regions[side]['mesh']
            mesh_penetration = max(mesh_penetration,-p['mesh_low_m'])
            if p['support']=='flat': mesh_flat_gap=max(mesh_flat_gap,abs(p['mesh_low_m']))
    for o in hidden:
        o.hide_viewport = False
    return dict(rows=rows, hold_m=hold_m, hold_rad=hold_rad,
                mesh_penetration_m=mesh_penetration, mesh_flat_gap_m=mesh_flat_gap,
                shoe_objects=[o.name for o in shoes], contact_point_sampling=dict(floor_band_m=.002,entry_patch_band_m=.00025,exit_patch_band_m=.00075,native_vertex_episodes=True), outsole_patches=patches, com_model='de Leva 1996 male fractions; approximate joint endpoints; kinematic estimate',
                dimensions_m=list(rig.dimensions), bones=len(rig.data.bones))
