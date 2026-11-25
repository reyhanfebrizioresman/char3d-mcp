"""Rest-space rigid outsole projection for the existing footstep/IK planner.

One direct height projection per planned pose, with a constant flat anchor.
No mesh edits, pose fitting, iterative solver, or extra dependency-graph passes.
"""
import bpy
import json
import math
import numpy as np
from mathutils import Quaternion, Vector
from engine.commands import anim
from engine.shoe_contact import calibrate, vertices

_cache = None


def clearance(rig, targets, toe_roll):
    """Native lower-surface Z relative to the planned ankle, without evaluation."""
    if _cache is None or _cache[0] != rig.as_pointer():return {}
    _, frames, tables = _cache
    out = {}
    for s,(foot,toe) in frames.items():
        if not tables[s]:continue
        origin=foot.inverted() @ toe.translation
        relative=foot.to_quaternion().inverted() @ toe.to_quaternion()
        out[s]=[]
        for i,(_p,q) in enumerate(targets[s]):
            tq=toe_roll.get(s,{}).get(i,Quaternion()) @ q @ relative
            f=np.asarray(q.to_matrix())[2];t=np.asarray(tq.to_matrix())[2]
            tz=(q @ origin).z
            out[s].append(min(float((a[:,:3] @ f*w[:,0]+b[:,:3] @ t*w[:,1]+tz*w[:,1]).min())
                              for a,b,w in tables[s]))
    return out


def project(rig, start, targets, contacts, events, toe_roll):
    global _cache
    _cache = None
    shoes = [o for o in rig.children_recursive if o.get('c3d_garment_category') == 'shoes']
    if not shoes or not all(o.get('c3d_rigid_sole') for o in shoes):
        return None
    patches = calibrate(rig)
    sm = anim.semantic_map(rig)
    # Rigify FK controls share rest frames with DEF foot/toe.
    mw = rig.matrix_world
    frames = {s:[mw @ rig.data.bones[sm[k+'.'+s]].matrix_local for k in ('foot','toe')]
              for s in 'LR' if 'toe.'+s in sm}
    tables = {s:[] for s in frames}
    saved = rig.data.pose_position
    try:
        rig.data.pose_position = 'REST';bpy.context.view_layer.update()
        for name, sides in patches:
            ob = bpy.data.objects[name]
            xyz = vertices(ob)
            if len(xyz) != len(ob.data.vertices):continue
            for s, (foot, toe) in frames.items():
                # Restrict to the full-rigid band; collar/boot shaft never
                # contributes to the outsole. All IDs remain anatomical.
                fn,tn = sm['foot.'+s],sm['toe.'+s]
                if rig.get('c3d_rig_type') == 'rigify':
                    from engine.commands.mpfb import RIGIFY_DEF
                    fn,tn = RIGIFY_DEF['foot.'+s],RIGIFY_DEF['toe.'+s]
                groups = {g.index:g.name for g in ob.vertex_groups if g.name in rig.data.bones and rig.data.bones[g.name].use_deform}
                ids=[];weights=[]
                for i in sides[s]['all']:
                    w={groups[g.group]:g.weight for g in ob.data.vertices[i].groups if g.group in groups}
                    total=sum(w.values());f,t=w.get(fn,0.),w.get(tn,0.)
                    if total > .99 and total-f-t < 1e-6:
                        ids.append(i);weights.append((f/total,t/total))
                if not ids:continue
                points=np.column_stack((xyz[ids],np.ones(len(ids))))
                tables[s].append((points @ np.asarray(foot.inverted()).T,
                                  points @ np.asarray(toe.inverted()).T,
                                  np.asarray(weights)))
    finally:
        rig.data.pose_position=saved;bpy.context.view_layer.update()
    _cache = (rig.as_pointer(),frames,tables)
    corrections={}
    nominal={}
    for s, (foot,toe) in frames.items():
        if not tables[s]:continue
        origin=foot.inverted() @ toe.translation
        relative=foot.to_quaternion().inverted() @ toe.to_quaternion()
        neutral=anim._facing(rig,sm).inverted() @ Vector((0,-1,0))
        bias=float(json.loads(rig.get('c3d_sole_pitch_rad','{}')).get(s,0.))
        nominal[s]=[]
        lows=[]
        for i,(p,q) in enumerate(targets[s]):
            fw=q @ foot.to_quaternion().inverted() @ neutral
            nominal[s].append(-math.degrees(math.atan2(fw.z,math.hypot(fw.x,fw.y)))+math.degrees(bias))
            tq=toe_roll.get(s,{}).get(i,Quaternion()) @ q @ relative
            # Z rows suffice; native linear skinning is evaluated analytically.
            f=np.asarray(q.to_matrix())[2];t=np.asarray(tq.to_matrix())[2]
            tz=(p+q @ origin).z
            lows.append(min(float((a[:,:3] @ f*w[:,0]+b[:,:3] @ t*w[:,1]+p.z*w[:,0]+tz*w[:,1]).min())
                            for a,b,w in tables[s]))
        shift=[-.0016-z for z in lows]
        fixed=set()
        for a,b in contacts[s]:
            a,b=a-start,b-start
            dz=max(shift[a:b+1])
            for i in range(a,b+1):shift[i]=dz;fixed.add(i)
        for e in events:
            if e['side'] != s:continue
            a,b=e['lift']-start,e['land']-start
            for i in range(a+1,b):
                u=(i-a)/(b-a)
                from engine.commands.footlock import _smoothstep
                shift[i]=shift[a]*(1-_smoothstep(u/.3))+shift[b]*_smoothstep((u-.7)/.3)
        for i,dz in enumerate(shift):targets[s][i]=(targets[s][i][0]+Vector((0,0,dz)),targets[s][i][1])
        corrections[s]=shift
    return dict(method='native rigid outsole support projection; constant flat anchors; swing-only easing',
                corrections_m=corrections,nominal_roll_deg=nominal,contact_tolerance_m=.0016)
