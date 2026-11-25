"""Evaluated native outsole patches; the raised arch is never a contact gate."""
import bpy
import numpy as np
from mathutils import Vector
from engine.commands import anim


def vertices(ob):
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    try:
        xyz = np.empty(len(me.vertices)*3, dtype=np.float64)
        me.vertices.foreach_get('co', xyz)
        mat = np.asarray(ev.matrix_world)
        return xyz.reshape(-1,3) @ mat[:3,:3].T + mat[:3,3]
    finally:
        ev.to_mesh_clear()


def calibrate(rig):
    """Freeze native vertex IDs from evaluated REST, per shoe and anatomical side.

    Each 5 mm sole cell contributes only its lowest 1 mm band. This samples
    actual outsole surfaces rather than including the upper or a raised arch.
    """
    shoes = [o for o in bpy.context.scene.objects if o.type == 'MESH' and not o.hide_render
             and o.get('c3d_garment_category') == 'shoes'
             and any(m.type == 'ARMATURE' and m.object == rig for m in o.modifiers)]
    sm = anim.semantic_map(rig)
    saved = rig.data.pose_position
    hidden = [o for o in shoes if o.hide_viewport]
    try:
        for o in hidden: o.hide_viewport = False
        rig.data.pose_position = 'REST'
        bpy.context.view_layer.update()
        feet = np.array([(rig.matrix_world @ rig.data.bones[sm['foot.'+s]].matrix_local).translation for s in 'LR'])
        forward = rig.matrix_world.to_quaternion() @ Vector((0,-1,0))
        patches = []
        for ob in shoes:
            xyz = vertices(ob)
            ids = np.argmin(((xyz[:,None,:]-feet[None,:,:])**2).sum(axis=2),axis=1)
            sides = {}
            for si, side in enumerate('LR'):
                selected = np.flatnonzero(ids == si)
                if not len(selected):
                    sides[side] = dict(regions={},all=[])
                    continue
                foot_bone = rig.data.bones[sm['foot.'+side]]
                toe_bone = rig.data.bones.get(sm.get('toe.'+side,''))
                ankle = rig.matrix_world @ foot_bone.head_local
                ball = rig.matrix_world @ (toe_bone.head_local if toe_bone else foot_bone.tail_local)
                tip = rig.matrix_world @ (toe_bone.tail_local if toe_bone else foot_bone.tail_local)
                axis = tip-ankle; axis.z = 0
                axis = axis.normalized() if axis.length>1e-8 else forward
                longitudinal = xyz[selected] @ np.array(axis)
                lo, hi = longitudinal.min(), longitudinal.max()
                span = max(hi-lo,1e-6)
                ankle_at,ball_at = ankle.dot(axis),ball.dot(axis)
                # Patch boundaries follow each rig's fitted ankle and ball
                # joints, not fixed fractions of a shoe's ornamental extent.
                heel_end = min(ankle_at+.18*(ball_at-ankle_at),ball_at-.15*span)
                ball_begin = max(heel_end,ball_at-.10*span)
                toe_begin = min(hi,ball_at+.10*span)
                # Lower envelope per small XY cell, so the toe/heel edge
                # that becomes lowest during roll is not discarded merely
                # because it sits above the neutral patch minimum.
                grid = np.floor(xyz[selected,:2]/.005).astype(int)
                cells = {}
                for local,cell in enumerate(map(tuple,grid)):
                    cells.setdefault(cell,[]).append(local)
                shell = []
                for local_ids in cells.values():
                    local_ids = np.asarray(local_ids)
                    ids_cell = selected[local_ids]
                    z = xyz[ids_cell,2]
                    shell.extend(local_ids[z<=z.min()+.001].tolist())
                shell = np.asarray(shell,dtype=int)
                bins = {}
                for name, a,b in [('heel',lo-1e-8,heel_end),('arch',heel_end,ball_begin),
                                  ('ball',ball_begin,toe_begin),('toe',toe_begin,hi+1e-8)]:
                    local = shell[(longitudinal[shell]>=a)&(longitudinal[shell]<b)]
                    if len(local): bins[name] = selected[local].tolist()
                sides[side] = dict(regions=bins, all=selected.tolist(),
                    longitudinal_limits_m=[float(v) for v in (lo,heel_end,ball_begin,toe_begin,hi)],
                    ankle_ball_m=[float(ankle_at),float(ball_at)])
            patches.append((ob.name,sides))
        return patches
    finally:
        rig.data.pose_position = saved
        for o in hidden: o.hide_viewport = True
        bpy.context.view_layer.update()


def measure(patches, xyzs=None):
    out = {s: {} for s in 'LR'}
    for name, sides in patches:
        xyz = xyzs[name] if xyzs is not None else vertices(bpy.data.objects[name])
        for side, data in sides.items():
            if not data['all']: continue
            values = {'mesh':float(xyz[data['all'],2].min())}
            values.update({region:float(xyz[ids,2].min()) for region,ids in data['regions'].items()})
            for region,z in values.items():
                out[side][region] = min(out[side].get(region,float('inf')),z)
    return out


def touching_points(patches, xyzs, side, active, tolerance=.002, previous=()):
    """Native material points actually in the active floor-contact band.

    A vertex episode ends when it leaves the floor band or its region stops
    supporting. A raised heel-strike vertex is not a flat-stance drift probe.
    """
    result={}
    for name,sides in patches:
        for area in active:
            ids=sides[side]['regions'].get(area,[])
            if not ids:continue
            low=float(xyzs[name][ids,2].min())
            for idx in ids:
                p=xyzs[name][idx]
                key=f'{area}:{name}:{idx}'
                band=.00075 if key in previous else .00025
                if abs(float(p[2]))<=tolerance and float(p[2])<=low+band:
                    result[key]=(area,name,idx,p)
    return result
