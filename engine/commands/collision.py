"""Bounded, contact-aware collision repair for baked FK performances.

Body envelopes are measured once on evaluated rest skin and follow posed bones.
Furniture uses evaluated world-space triangle BVHs. Only limb rotation channels
are baked; no root, feet, face, finger, attachment or camera channels are edited.
Unrepairable conflicts remain explicit in the report rather than moving a contact.
"""
from contextlib import contextmanager
from functools import wraps
import json
import math
import time

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import command
from . import anim
from .talk import _rig_of, _data_curves
from .util import is_helper
from ..collision import (closest_segment, ellipsoid_distance, unit, two_bone,
                         smooth_corrections, bounded_correction, surface_distance, split_bezier)

CONTACTS = 'c3d_collision_contacts'
_DEFER = 0


def deferred(fn):
    """Orchestrators run one final pass, instead of one pass per nested tool."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        global _DEFER
        _DEFER += 1
        try:
            return fn(*args, **kwargs)
        finally:
            _DEFER -= 1
    return wrapped


def automatic(enabled, characters, first, last, outer=False, **kwargs):
    if enabled and (_DEFER == 0 or outer and _DEFER == 1):
        return resolve_collisions(characters, first, last, **kwargs)
    return {'enabled': bool(enabled), 'deferred': bool(_DEFER)}


def record_contact(rig, side, first, last, kind, other=None, part=None):
    """Save contact intervals as native JSON; reruns replace the same authored beat.

    A protected wrist can still change its elbow pole. It cannot be translated
    away from a handshake, temple, heart, keyboard, armrest or cup/lip target.
    """
    if last<first:return
    records = json.loads(rig.get(CONTACTS, '[]'))
    record = dict(side=side, frames=[int(first), int(last)], kind=kind,
                  other=other or rig.name, part=part)
    records = [r for r in records if not (r['side'] == side and r['kind'] == kind
               and r['frames'][0] == int(first))]
    records.append(record)
    rig[CONTACTS] = json.dumps(sorted(records, key=lambda r: (r['frames'][0], r['side'], r['kind'])))


def contacts_at(rig, side, frame):
    return [r for r in json.loads(rig.get(CONTACTS, '[]'))
            if r['side'] == side and r['frames'][0] <= frame <= r['frames'][1]]


def forget_contacts(rig,first,last,prefix=None):
    records=[]
    for record in json.loads(rig.get(CONTACTS,'[]')):
        a,b=record['frames']
        if (prefix and not record['kind'].startswith(prefix)) or b<first or a>last:
            records.append(record)
        else:
            if a<first:records.append(dict(record,frames=[a,first-1]))
            if b>last:records.append(dict(record,frames=[last+1,b]))
    if CONTACTS in rig:
        rig[CONTACTS]=json.dumps(records)


def _window_snapshot(rigs, first, last):
    """Keep sparse authored Bezier animation outside the repaired interval exact."""
    saved=[];defaults={};known=set()
    for rig in rigs:
        future=bpy.context.scene.frame_end>last or bool(rig.animation_data and rig.animation_data.action and rig.animation_data.action.frame_range[1]>last)
        for fc in _data_curves(rig):
            if not fc.data_path.startswith('pose.bones['):
                continue
            known.add((rig.name,fc.data_path,fc.array_index))
            keys=[(k.co.copy(),k.handle_left.copy(),k.handle_right.copy(),k.interpolation)
                  for k in fc.keyframe_points]
            signature=[(tuple(k.co),k.interpolation) for k in fc.keyframe_points if first<=k.co.x<=last]
            guards=[]
            for frame,lower in ((first-1,True),(last+1,False)):
                if not lower and not future:
                    continue
                left=next((k for k in reversed(keys) if k[0].x<frame),None)
                right=next((k for k in keys if k[0].x>frame),None)
                split=None
                if left and right and not any(k[0].x==frame for k in keys) and left[3]=='BEZIER':
                    split=split_bezier((left[0],left[2],right[1],right[0]),frame)
                guards.append((frame,lower,fc.evaluate(frame),left,right,split))
            saved.append((fc,keys,signature,guards))
    from .script_scene import _bones_only
    with _bones_only():
        for frame in (first-1,last+1):
            bpy.context.scene.frame_set(frame)
            for rig in rigs:
                names=set(anim.semantic_map(rig).values())
                names.update(n for ch in json.loads(rig.get('char3d_secondary','{}')).get('chains',[])
                             for n in ch['bones'] if n in rig.pose.bones)
                for name in names:
                    pb=rig.pose.bones[name]
                    for prop in ('location','rotation_euler','rotation_quaternion','rotation_axis_angle'):
                        path=pb.path_from_id(prop)
                        for index,value in enumerate(getattr(pb,prop)):
                            key=(rig.name,path,index)
                            if key not in known:defaults[(*key,frame)]=float(value)
    return saved,defaults,known,rigs


def _restore_window(window,first,last):
    saved,defaults,known,rigs=window
    for fc,keys,signature,guards in saved:
        current=[(tuple(k.co),k.interpolation) for k in fc.keyframe_points if first<=k.co.x<=last]
        if current==signature:
            continue
        by_frame={k.co.x:k for k in fc.keyframe_points}
        for co,left,right,interpolation in keys:
            if first<=co.x<=last:
                continue
            key=by_frame.get(co.x)
            if key is None:key=fc.keyframe_points.insert(co.x,co.y,options={'FAST'})
            key.co=co;key.interpolation=interpolation
            key.handle_left_type=key.handle_right_type='FREE'
            key.handle_left,key.handle_right=left,right
        for frame,lower,value,left,right,split in guards:
            key=fc.keyframe_points.insert(frame,value,options={'FAST'})
            key.handle_left_type=key.handle_right_type='FREE'
            key.interpolation='LINEAR' if lower else left[3] if left else 'CONSTANT'
            if split is not None:
                a,c,d,e,point=split
                if lower:
                    original=next(k for k in fc.keyframe_points if k.co.x==left[0].x)
                    original.handle_right=a;key.handle_left=d
                else:
                    original=next(k for k in fc.keyframe_points if k.co.x==right[0].x)
                    original.handle_left=c;key.handle_right=e
        fc.update()
    for rig in rigs:
        future=bpy.context.scene.frame_end>last or bool(rig.animation_data and rig.animation_data.action and
                                                      rig.animation_data.action.frame_range[1]>last)
        owned={rig.pose.bones[n].path_from_id('rotation_quaternion')
               for ch in json.loads(rig.get('char3d_secondary','{}')).get('chains',[])
               for n in ch['bones'] if n in rig.pose.bones}
        for fc in _data_curves(rig):
            key=(rig.name,fc.data_path,fc.array_index)
            if key not in known and (*key,first-1) not in defaults and fc.data_path in owned:
                # Newly installed elastic bones have an identity pose outside
                # this requested range; they had no channels to snapshot.
                for frame in (first-1,last+1):
                    defaults[(*key,frame)]=1. if fc.array_index==0 else 0.
            if key in known or (*key,first-1) not in defaults:continue
            for frame in (first-1,last+1):
                if frame==last+1 and not future:continue
                fc.keyframe_points.insert(frame,defaults[(*key,frame)]).interpolation='LINEAR'
            fc.update()


def _reject_body_bake(window,rig,basis):
    """Restore authored physical channels when a combined repair makes things worse.

    Reject the whole physical interval for this character, rather than putting a
    one-frame discontinuity in a filtered performance. Face/fingers/root stay on
    their original curves throughout.
    """
    saved,defaults,known,_=window
    smap=anim.semantic_map(rig)
    names={n for k,n in smap.items() if k in ('chest',) or k.split('.')[0] in
           ('upper_arm','forearm','hand','thigh','shin','foot')}
    paths={rig.pose.bones[n].path_from_id(p) for n in names for p in
           ('location','rotation_euler','rotation_quaternion','rotation_axis_angle')}
    curves=_data_curves(rig)
    original={(fc.data_path,fc.array_index):keys for fc,keys,_,_ in saved if fc in curves}
    for fc in curves:
        if fc.data_path not in paths:continue
        keys=original.get((fc.data_path,fc.array_index))
        if keys is not None:
            fc.keyframe_points.clear()
            for co,left,right,interpolation in keys:
                key=fc.keyframe_points.insert(co.x,co.y,options={'FAST'})
                key.interpolation=interpolation
                key.handle_left_type=key.handle_right_type='FREE'
                key.handle_left,key.handle_right=left,right
        else:
            values=[(frame,value) for (owner,path,index,frame),value in defaults.items()
                    if owner==rig.name and path==fc.data_path and index==fc.array_index]
            if values:
                fc.keyframe_points.clear()
                for frame,value in sorted(values):
                    fc.keyframe_points.insert(frame,value,options={'FAST'}).interpolation='LINEAR'
        fc.update()
    for name in names:
        rig.pose.bones[name].matrix_basis=basis[name]
    bpy.context.view_layer.update()


@contextmanager
def evaluated_skin(rigs):
    """Expose skin during fitting even inside an orchestrator's bones-only scope."""
    hidden = [(o, o.hide_viewport) for o in bpy.context.scene.objects
              if o.type == 'MESH' and o.find_armature() in rigs]
    try:
        for obj, _ in hidden:
            obj.hide_viewport = False
        bpy.context.view_layer.update()
        yield
    finally:
        for obj, state in hidden:
            obj.hide_viewport = state
        bpy.context.view_layer.update()


def _points(obj, space=None):
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    try:
        co = np.empty(len(mesh.vertices)*3)
        mesh.vertices.foreach_get('co', co)
        m = np.asarray((space or Matrix.Identity(4)) @ ev.matrix_world)
        return co.reshape(-1, 3) @ m[:3, :3].T+m[:3, 3]
    finally:
        ev.to_mesh_clear()


class Body:
    """Anatomical rest envelopes fitted to evaluated skin, never to a size table."""
    def __init__(self, rig):
        self.rig = rig
        self.map = anim.semantic_map(rig)
        required = ('hips', 'chest', 'neck', 'head', *[f'{b}.{s}' for s in 'LR'
                    for b in ('upper_arm', 'forearm', 'hand', 'thigh', 'shin', 'foot')])
        if not all(n in self.map for n in required):
            raise ValueError(f'{rig.name}: missing humanoid chains for collision pass')
        scale = np.abs(np.array(rig.matrix_world.to_scale()))
        if scale.min() < 1e-8 or scale.max()/scale.min() > 1.01:
            raise ValueError(f'{rig.name}: collision pass requires uniform rig scale')
        self.rest = {k: rig.data.bones[n].matrix_local.copy() for k, n in self.map.items()}
        self.inverse = {k: m.inverted() for k, m in self.rest.items()}
        body = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.find_armature() == rig
                and o.get('c3d_kind') == 'humanoid']
        if not body:
            candidates = [o for o in bpy.context.scene.objects if o.type == 'MESH'
                          and o.find_armature() == rig and not o.hide_render]
            body = sorted(candidates, key=lambda o: -len(o.data.vertices))[:1]
        if not body:
            raise ValueError(f'{rig.name}: no skinned body mesh to fit')
        mode = rig.data.pose_position
        masks = [(m, m.show_viewport) for o in body for m in o.modifiers
                 if m.type == 'MASK' and m.name.startswith('Delete.')]
        try:
            rig.data.pose_position = 'REST'
            for modifier, _ in masks:
                modifier.show_viewport = False
            with evaluated_skin([rig]):
                points = np.concatenate([_points(o, rig.matrix_world.inverted()) for o in body])
        finally:
            rig.data.pose_position = mode
            for modifier, state in masks:
                modifier.show_viewport = state
            bpy.context.view_layer.update()
        if not len(points):
            raise ValueError(f'{rig.name}: evaluated body is empty')
        # Anatomical axes handle basic, MPFB, Mixamo and Rigify bone rolls.
        B = rig.data.bones
        head = lambda k: np.array(B[self.map[k]].head_local)
        left = unit(head('thigh.L')-head('thigh.R'))
        up = unit(head('head')-head('hips'))
        up = unit(up-left*float(up@left))
        basis = np.column_stack((left, np.cross(up, left), up))
        p = points @ basis
        self.height = float(np.ptp(p[:, 2]))*scale[0]
        self.specs = []
        hip, neck = head('hips') @ basis, head('neck') @ basis
        shoulder = np.linalg.norm(head('upper_arm.L')-head('upper_arm.R'))
        def ellipsoid(name, bone, mask):
            pts = p[mask]
            if len(pts) < 8:
                return
            lo, hi = np.quantile(pts, [.015, .985], axis=0)
            center = (lo+hi)/2
            radius = np.maximum((hi-lo)/2, self.height/scale[0]*.006)
            self.specs.append(dict(name=name, bone=bone, center=basis@center,
                                   radii=radius, axes=basis, shape='ellipsoid'))
        torso = (np.abs(p[:, 0]-hip[0]) < shoulder*.47)
        span = neck[2]-hip[2]
        for name, bone, low, high in (('pelvis', 'hips', -.22, .23),
                                       ('abdomen', 'spine' if 'spine' in self.map else 'chest', .12, .63),
                                       ('chest', 'chest', .43, .96)):
            ellipsoid(name, bone, torso & (p[:, 2] > hip[2]+span*low)
                      & (p[:, 2] < hip[2]+span*high))
        ellipsoid('head', 'head', p[:, 2] > neck[2]+span*.06)
        segments = {}
        for kind in ('upper_arm', 'forearm', 'hand', 'thigh', 'shin', 'foot', 'neck'):
            for side in ('',) if kind == 'neck' else ('L', 'R'):
                key = kind+('.'+side if side else '')
                a = head(key)
                b = np.array(B[self.map[key]].tail_local)
                # Semantic control tails sometimes do not coincide with next joints.
                nxt = {'upper_arm': 'forearm', 'forearm': 'hand', 'thigh': 'shin', 'shin': 'foot'}.get(kind)
                if nxt:
                    b = head(nxt+'.'+side)
                segments[key] = (a, b)
        distances = np.column_stack([np.linalg.norm(points-closest_segment(points, a, b), axis=1)
                                     for a, b in segments.values()])
        nearest = np.argmin(distances, axis=1)
        for i, (key, (a, b)) in enumerate(segments.items()):
            d = b-a
            t = (points-a)@d/max(float(d@d), 1e-12)
            use = (nearest == i) & (t > .18) & (t < .82)
            # Exclude torso vertices competing with proximal arm/neck segments.
            if key.startswith(('upper_arm', 'forearm', 'hand')):
                use &= np.abs(p[:, 0]-hip[0]) > shoulder*.36
            radius = float(np.quantile(distances[use, i], .78)) if use.sum() >= 6 else float(np.linalg.norm(d))*.12
            radius = max(self.height/scale[0]*.004, min(radius, np.linalg.norm(d)*.45))
            if key.startswith('hand'):
                a, b = a+d*.22, a+d*.80
            self.specs.append(dict(name=key, bone=key, a=a, b=b, radius=radius, shape='capsule'))
        self.spec_by_name = {s['name']: s for s in self.specs}

    def world(self, matrices):
        result = []
        for spec in self.specs:
            transform = matrices[spec['bone']] @ np.asarray(self.inverse[spec['bone']])
            linear, offset = transform[:3, :3], transform[:3, 3]
            scale = float(np.linalg.norm(linear[:, 0]))
            col = dict(name=spec['name'], owner=self.rig.name, shape=spec['shape'])
            if spec['shape'] == 'capsule':
                col.update(a=linear@spec['a']+offset, b=linear@spec['b']+offset,
                           radius=spec['radius']*scale)
            else:
                col.update(center=linear@spec['center']+offset, radii=spec['radii']*scale,
                           axes=linear@spec['axes']/scale)
            result.append(col)
        return result


class Surface:
    """One evaluated visible mesh, world-space BVH, two-sided open surfaces."""
    def __init__(self, obj):
        self.name = obj.name
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = ev.to_mesh()
        try:
            vertices = [ev.matrix_world@v.co for v in mesh.vertices]
            polygons = [list(p.vertices) for p in mesh.polygons]
            self.tree = BVHTree.FromPolygons(vertices, polygons)
            pts = np.asarray(vertices)
            self.lo, self.hi = pts.min(axis=0), pts.max(axis=0)
            dims = self.hi-self.lo
            self.support_top = dims[2] < min(dims[0], dims[1])*.5
            edges = {}
            for poly in polygons:
                for a, b in zip(poly, poly[1:]+poly[:1]):
                    k = tuple(sorted((a, b)))
                    edges[k] = edges.get(k, 0)+1
            self.closed = bool(edges) and all(v == 2 for v in edges.values())
        finally:
            ev.to_mesh_clear()

    def distance(self, point, radius=0., prefer_top=False):
        if (point[0]<self.lo[0]-radius or point[0]>self.hi[0]+radius or
            point[1]<self.lo[1]-radius or point[1]>self.hi[1]+radius or
            point[2]<self.lo[2]-radius or point[2]>self.hi[2]+radius):
            return math.inf, np.array((0., 0., 1.))
        if (prefer_top and self.support_top and self.lo[0]<=point[0]<=self.hi[0] and
            self.lo[1]<=point[1]<=self.hi[1]):
            return float(point[2]-self.hi[2]), np.array((0., 0., 1.))
        near, normal, _, distance = self.tree.find_nearest(Vector(point))
        if near is None:
            return math.inf, np.array((0., 0., 1.))
        inside = False
        if (self.closed and self.lo[0]<=point[0]<=self.hi[0] and
            self.lo[1]<=point[1]<=self.hi[1] and self.lo[2]<=point[2]<=self.hi[2]):
            # Parity is independent of authored winding. A fixed non-axis ray
            # avoids nearly all shared-edge coincidences on procedural furniture.
            direction = Vector((.371, .529, .763)).normalized()
            origin, count = Vector(point), 0
            for _ in range(64):
                hit = self.tree.ray_cast(origin, direction)
                if hit[0] is None:
                    break
                count += 1
                origin = hit[0]+direction*1e-5
            inside = bool(count % 2)
        return surface_distance(point, near, normal, inside)


def surfaces(rigs):
    from .occlusion import _ancestors, _render_collections, _rig
    collections = set(_render_collections(bpy.context.scene.collection))
    result = []
    for obj in sorted(bpy.context.scene.objects, key=lambda o: o.name):
        if (obj.type != 'MESH' or obj.hide_render or not obj.visible_get() or is_helper(obj)
                or _rig(obj) is not None or obj.get('c3d_weather') or obj.get('c3d_nature_occludes') is False
                or not any(c in collections for c in obj.users_collection)):
            continue
        chain = list(_ancestors(obj))
        if any(o.hide_render or o.get('c3d_hold_character') or o.get('c3d_hold_helper') for o in chain):
            continue
        if obj.data.polygons:
            result.append(Surface(obj))
    return result


class Field:
    def __init__(self, proxies, geometry, owner, side, clearance, contacts=()):
        self.owner = owner
        self.proxies = [c for c in proxies if not (c['owner'] == owner and
                        (c.get('attached_side') == side or c['name'].endswith('.'+side) and
                         c['name'].split('.')[0] in ('upper_arm', 'forearm', 'hand')))]
        self.geometry, self.clearance, self.contacts = geometry, clearance, contacts
        self.bounds=[]
        for col in self.proxies:
            if col['shape']=='capsule':
                low,high=np.minimum(col['a'],col['b'])-col['radius'],np.maximum(col['a'],col['b'])+col['radius']
            else:
                extent=np.abs(col['axes'])@col['radii']
                low,high=col['center']-extent,col['center']+extent
            self.bounds.append((col,low,high))
        self.proxy_low=np.array([row[1] for row in self.bounds]).reshape(-1,3)
        self.proxy_high=np.array([row[2] for row in self.bounds]).reshape(-1,3)
        self.static_low=np.array([s.lo for s in geometry]).reshape(-1,3)
        self.static_high=np.array([s.hi for s in geometry]).reshape(-1,3)

    def hits(self, points, radii, labels, exact=False):
        points, radii = np.asarray(points), np.asarray(radii)
        hits = []
        low=points-radii[:,None]-self.clearance
        high=points+radii[:,None]+self.clearance
        mask=np.all((high[:,None,:]>=self.proxy_low[None,:,:]) &
                    (low[:,None,:]<=self.proxy_high[None,:,:]),axis=2)
        for index in np.flatnonzero(mask.any(axis=0)):
            col=self.bounds[index][0]
            ids = np.flatnonzero(mask[:,index])
            if col['owner'] == self.owner and col['name'] in ('chest','abdomen','neck'):
                # Shoulder/armpit skin joins the upper arm to the torso. Overlap
                # of these adjacent fitted envelopes is not interpenetration.
                ids = np.array([i for i in ids if not str(labels[i]).startswith('upper_arm.')],dtype=int)
            if not len(ids):
                continue
            query, sizes = points[ids], radii[ids]
            if col['shape'] == 'capsule':
                delta = query-closest_segment(query, col['a'], col['b'])
                lengths = np.linalg.norm(delta, axis=1)
                gaps = lengths-col['radius']-sizes
                normals = delta/np.maximum(lengths[:, None], 1e-12)
                normals[lengths < 1e-10] = (1., 0., 0.)
            else:
                if exact:
                    distance, normals = ellipsoid_distance(query, col['center'], col['radii'], col['axes'])
                else:
                    # Implicit/gradient distance is cheap near the surface. Final
                    # statistics use the closest-point ellipsoid distance above.
                    p = (query-col['center'])@col['axes']
                    k0 = np.linalg.norm(p/col['radii'], axis=1)
                    k1 = np.linalg.norm(p/(col['radii']**2), axis=1)
                    distance = k0*(k0-1)/np.maximum(k1, 1e-10)
                    distance[k0 < 1e-8] = -min(col['radii'])
                    n = p/(col['radii']**2)
                    normals = n/np.maximum(np.linalg.norm(n, axis=1)[:, None], 1e-10)@col['axes'].T
                gaps = distance-sizes
            margin = self.clearance
            if any(r['other'] == col['owner'] and (r['part'] is None or r['part'] == col['name'])
                   for r in self.contacts):
                margin = 0.
            for i in np.flatnonzero(gaps < margin):
                hits.append((float(margin-gaps[i]), normals[i], labels[ids[i]], col['owner']+':'+col['name'], float(max(0., -gaps[i]))))
        mask=np.all((high[:,None,:]>=self.static_low[None,:,:]) &
                    (low[:,None,:]<=self.static_high[None,:,:]),axis=2)
        for i,j in zip(*np.nonzero(mask)):
            surface=self.geometry[j]
            point,radius,label=points[i],radii[i],labels[i]
            distance, normal = surface.distance(point, radius+self.clearance, prefer_top=not exact)
            if distance-radius < self.clearance:
                hits.append((self.clearance+radius-distance, normal, label, surface.name,
                             max(0., radius-distance)))
        return sorted(hits, key=lambda h: (-h[0], h[2], h[3]))


def _arm_points(body, cols, side, shoulder, elbow, wrist, original_wrist, props=()):
    by_name = {c['name']: c for c in cols if c['owner'] == body.rig.name}
    points, radii, labels = [], [], []
    for kind, a, b, fractions in (('upper_arm', shoulder, elbow, (.6, .85)),
                                 ('forearm', elbow, wrist, (.12, .4, .7, .95))):
        radius = by_name[kind+'.'+side]['radius']
        for t in fractions:
            points.append(a+(b-a)*t); radii.append(radius); labels.append(kind+'.'+side)
    hand = by_name['hand.'+side]
    delta = wrist-original_wrist
    for t in (0., .5, 1.):
        points.append(hand['a']+(hand['b']-hand['a'])*t+delta)
        radii.append(hand['radius']); labels.append('hand.'+side)
    for name, pts in props:
        for p in pts:
            points.append(p+delta); radii.append(.002); labels.append('prop:'+name)
    return np.array(points), np.array(radii), labels


def _elbow_ceiling(body, shoulder, elbow):
    return max(float(elbow[2]),float(shoulder[2])+min(.05,body.height*.03))


def _plan_arm(body, cols, side, matrices, field, maximum, iterations, props=(), locked=False, include_arms=True, hint=None):
    S, E, W = [matrices[k+'.'+side][:3, 3].copy() for k in ('upper_arm', 'forearm', 'hand')]
    upper, lower = float(np.linalg.norm(E-S)), float(np.linalg.norm(W-E))
    ceiling=_elbow_ceiling(body,S,E)
    original_pole = E-(S+W)/2
    base_pole = original_pole.copy()
    if np.linalg.norm(base_pole) < 1e-6:
        base_pole = np.array((1. if side == 'L' else -1., 0., -.5))
    def query(points,radii,labels,exact):
        if not include_arms:
            ids=[i for i,label in enumerate(labels) if label.startswith('prop:')]
            if not ids:
                return []
            points,radii,labels=points[ids],radii[ids],[labels[i] for i in ids]
        return field.hits(points,radii,labels,exact)
    def evaluate(target, pole, exact=False):
        elbow, wrist = two_bone(S, target, upper, lower, pole)
        points, radii, labels = _arm_points(body, cols, side, S, elbow, wrist, W, props)
        return query(points, radii, labels, exact), elbow, wrist
    # The original elbow is authoritative: do not introduce numerical IK drift
    # into an untouched/straight arm just to measure it.
    points, radii, labels = _arm_points(body, cols, side, S, E, W, W, props)
    initial = query(points, radii, labels, True)
    if not iterations or not initial or initial[0][0] <= .001:
        return np.zeros(3), original_pole, initial, None
    if hint is not None:
        delta,offset=hint['delta'],hint['offset']
        candidate_pole=original_pole+offset
        if np.linalg.norm(delta)<=maximum and (not locked or np.linalg.norm(delta)<1e-8):
            cached,joint,endpoint=evaluate(W+delta,candidate_pole,True)
            stable=(hint.get('reason') and hint.get('age',0)<6 and
                    max(np.linalg.norm(a-b) for a,b in zip((S,E,W),hint['source']))<.003 and
                    initial[0][2:4]==hint['signature'][2:4] and abs(initial[0][0]-hint['signature'][0])<.002 and
                    float(initial[0][1]@hint['signature'][1])>.995)
            if (stable and np.linalg.norm(endpoint-(W+delta))<.001 and np.linalg.norm(joint-E)<=maximum and joint[2]<=ceiling and
                (not cached or cached[0][0]<=initial[0][0]+.001)):
                hint['_reused']=True;hint['age']=hint.get('age',0)+1
                return delta.copy(),candidate_pole,initial,hint['reason']
            if (np.linalg.norm(endpoint-(W+delta))<.001 and np.linalg.norm(joint-E)<=maximum and joint[2]<=ceiling and
                (not cached or cached[0][0]<.006) and
                (not cached or cached[0][0]<initial[0][0])):
                return delta.copy(),candidate_pole,initial,None
    target, pole = W.copy(), base_pole.copy()
    best = (initial[0][0], target.copy(), pole.copy())
    skipped = None
    for _ in range(iterations):
        hits, elbow, wrist = evaluate(target, pole)
        if not hits or hits[0][0] < .001:
            break
        depth, normal, label, _, _ = hits[0]
        if not label.startswith(('hand.', 'prop:')):
            # First try an outward/up elbow around the unchanged wrist. This is
            # especially useful for crossed arms and protected contact targets.
            out = np.array((1. if side == 'L' else -1., 0., .35))
            candidate_poles = [pole+normal*max(.08, depth*2), pole+out*.15, pole+out*.3]
            choices = []
            for candidate in candidate_poles:
                candidate_hits, candidate_elbow, _ = evaluate(target, candidate)
                if np.linalg.norm(candidate_elbow-E) <= maximum and candidate_elbow[2]<=ceiling:
                    choices.append((candidate_hits, candidate))
            if not choices:
                choices = [(hits, pole)]
            choice = min(choices, key=lambda c: c[0][0][0] if c[0] else 0.)
            error = choice[0][0][0] if choice[0] else 0.
            if error < hits[0][0]-.0005:
                pole = choice[1]
                if error < best[0]:
                    best = (error, target.copy(), pole.copy())
                continue
        if locked:
            skipped = 'intended contact target is protected'
            break
        delta = normal*min(depth*(1. if label.startswith(('hand.', 'prop:')) else 1.6)+.001, maximum)
        proposed = target+delta
        _, reason = bounded_correction(proposed-W, maximum)
        if reason:
            skipped = reason
            break
        if np.linalg.norm(proposed-S) >= (upper+lower)*.998:
            proposed=S+unit(proposed-S)*(upper+lower)*.997
        # A small wrist push can swing a nearly straight elbow a long way.
        # Backtrack the step before filtering, instead of dropping one baked
        # frame later and creating a discontinuity.
        for _ in range(5):
            joint,_=two_bone(S,proposed,upper,lower,pole)
            if np.linalg.norm(joint-E)<=maximum and joint[2]<=ceiling:break
            proposed=(target+proposed)*.5
            skipped='elbow displacement limit reached'
        if np.linalg.norm(proposed-target)<1e-5:
            break
        target = proposed
        candidates, joint, _ = evaluate(target, pole)
        error = candidates[0][0] if candidates else 0.
        if error < best[0] and np.linalg.norm(joint-E)<=maximum and joint[2]<=ceiling:
            best = (error, target.copy(), pole.copy())
    hits, joint, _ = evaluate(target, pole, True)
    if np.linalg.norm(joint-E)>maximum or joint[2]>ceiling or hits and hits[0][0] > best[0]+.002:
        target, pole = best[1:]
    if initial and best[0] >= initial[0][0]-.001:
        return np.zeros(3), original_pole, initial, skipped or 'no bounded IK solution improves the conflict'
    return target-W, pole, initial, skipped


def _prop_samples(frame, rigs, roots=None):
    """Read the active historical attachment, not just the prop's latest owner."""
    result = {}
    for obj in bpy.context.scene.objects:
        if not obj.get('c3d_hold_character'):
            continue
        con = next((c for c in reversed(list(obj.constraints)) if c.name.startswith('char3d_hold')
                    and c.influence > .5 and c.target and c.target.parent in rigs), None)
        if con is None:
            continue
        rig = con.target.parent
        smap = anim.semantic_map(rig)
        side = next((s for s in 'LR' if smap.get('hand.'+s) == con.target.parent_bone), None)
        if side is None:
            continue
        if roots is not None:
            ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            roots[obj.name]=(rig.name,np.array(ev.matrix_world.translation))
        points = []
        for part in [obj, *obj.children_recursive]:
            if part.type == 'MESH' and not part.hide_render:
                p = _points(part)
                if len(p):
                    points.extend(p[np.linspace(0, len(p)-1, min(24, len(p))).astype(int)])
        if points:
            result.setdefault((rig.name, side), []).append((obj.name, np.array(points)))
    return result


def _prop_colliders(samples):
    cols=[]
    for (owner,side), props in samples.items():
        for name,points in props:
            low,high=points.min(axis=0),points.max(axis=0)
            cols.append(dict(owner=owner,name='held:'+name,shape='ellipsoid',attached_side=side,
                             center=(low+high)/2,radii=np.maximum((high-low)/2,.003),axes=np.eye(3)))
    return cols


def _statistics(hits, stats, stage, frame):
    for _, _, part, collider, penetration in hits:
        st = stats.setdefault(part, dict(count_before=0, count_after=0,
                max_penetration_before_m=0., max_penetration_after_m=0., colliders=set()))
        st['count_'+stage] += 1
        k = 'max_penetration_'+stage+'_m'
        st[k] = max(st[k], penetration)
        st['colliders'].add(collider)


def _batch_chains(tasks):
    """The shared two-bone solve, with one evaluation per hierarchy level.

    All arm/leg chains are independent below chest/hips, so updating the whole
    dependency graph for each individual bone wastes most of the bake time.
    """
    from .footlock import _ik_knee,_rotate_bone
    for task in tasks:
        rig,names,target,pole,rotation=task
        a,b,c=[rig.pose.bones[n] for n in names]
        mw=rig.matrix_world
        S,E,W=[(mw@pb.matrix).translation for pb in (a,b,c)]
        joint=_ik_knee(S,target,(E-S).length,(W-E).length,pole)
        _rotate_bone(rig,a,E-S,joint-S)
    if tasks:bpy.context.view_layer.update()
    for rig,names,target,pole,rotation in tasks:
        a,b,c=[rig.pose.bones[n] for n in names]
        mw=rig.matrix_world
        E,W=[(mw@pb.matrix).translation for pb in (b,c)]
        _rotate_bone(rig,b,W-E,target-E)
    if tasks:bpy.context.view_layer.update()
    for rig,names,target,pole,rotation in tasks:
        anim._set_world_rot(rig,rig.pose.bones[names[-1]],rotation)
    if tasks:bpy.context.view_layer.update()


def _garment_meshes(rig):
    state = json.loads(rig.get('char3d_secondary','{}'))
    owned = {c['mesh'] for c in state.get('chains',[]) if c.get('part') == 'clothes'}
    return [o for o in rig.children_recursive if o.type == 'MESH' and not o.hide_render
            and o.get('c3d_kind') != 'humanoid' and not o.get('c3d_source') and
            (o.name in owned or any(k in (o.get('c3d_garment_category','')+' '+o.name).lower()
                                    for k in ('skirt','dress','coat')))]


def _measure_garments(rigs, bodies, frames, geometry, reports, stage, clearance, skip=None):
    sc = bpy.context.scene
    meshes = {r.name:_garment_meshes(r) for r in rigs}
    if not any(meshes.values()):
        return
    with evaluated_skin(rigs):
        for f in frames:
            sc.frame_set(f)
            cols = [c for body in bodies for c in body.world({
                k:np.array(body.rig.matrix_world@body.rig.pose.bones[n].matrix) for k,n in body.map.items()})]
            for rig in rigs:
                peers = [c for c in cols if c['owner'] != rig.name]
                field = Field(peers,geometry,rig.name,'',clearance)
                for obj in meshes[rig.name]:
                    points = _points(obj)
                    if not len(points):
                        continue
                    # Fixed evaluated vertex indices, not a new random sample.
                    points = points[np.linspace(0,len(points)-1,min(128,len(points))).astype(int)]
                    hits = field.hits(points,[0.]*len(points),['garment:'+obj.name]*len(points),True)
                    _statistics(hits,reports[rig.name]['parts'],stage,f)
                    if skip and hits and hits[0][4]>clearance+.01:
                        skip(rig,'garment:'+obj.name,f,'sampled garment surface remains inside scene/peer; elastic-chain limit',max(h[4] for h in hits))


def _leg_points(col, hip, knee, ankle):
    points, radii, labels = [], [], []
    for kind, a, b in (('thigh', hip, knee), ('shin', knee, ankle)):
        c = col[kind]
        for t in (.35, .65, .9):
            points.append(a+(b-a)*t); radii.append(c['radius']); labels.append(c['name'])
    return points, radii, labels


def _plan_leg(body, cols, side, matrices, geometry, clearance):
    hip, knee, ankle = [matrices[k+'.'+side][:3, 3] for k in ('thigh', 'shin', 'foot')]
    pole = knee-(hip+ankle)/2
    col = {c['name'].split('.')[0]: c for c in cols if c['owner'] == body.rig.name
           and c['name'] in ('thigh.'+side, 'shin.'+side)}
    field = Field([], geometry, body.rig.name, side, clearance)
    initial = field.hits(*_leg_points(col, hip, knee, ankle),exact=True)
    if not initial:
        return pole, initial, None
    best = (initial[0][0] if initial else 0., pole.copy())
    # The nearest triangle normal also permits lowering a knee away from a
    # desk underside; an upward-only pole search cannot repair that contact.
    directions=(initial[0][1],(1. if side == 'L' else -1., 0., .5),(0.,0.,1.))
    for direction in directions:
        for amount in (.015, .03, .06, .12):
            candidate = pole+np.array(direction)*body.height*amount
            joint, target = two_bone(hip, ankle, np.linalg.norm(knee-hip), np.linalg.norm(ankle-knee), candidate)
            if np.linalg.norm(joint-knee) > body.height*.08:
                continue
            hits = field.hits(*_leg_points(col, hip, joint, target))
            error = hits[0][0] if hits else 0.
            if error < best[0]-.001:
                best = (error, candidate)
    reason = 'leg conflict exceeds knee-pole limit; planted foot and seat preserved' if best[0] > clearance+.01 else None
    return best[1], initial, reason


def _torso_hits(cols, owner, clearance):
    own = [c for c in cols if c['owner'] == owner and c['name'] in ('chest','abdomen','pelvis')]
    other = [c for c in cols if c['owner'] != owner and c['name'] in ('chest','abdomen','pelvis')]
    directions = [np.array((x,y,z), dtype=float) for x in (-1,0,1) for y in (-1,0,1)
                  for z in (-1,0,1) if x or y or z]
    result = []
    for col in own:
        points = [col['center']+col['axes']@(unit(v)*col['radii']) for v in directions]
        points.append(col['center'])
        result.extend(Field(other, [], owner, '', clearance).hits(points, [0.]*len(points),
                                                                  [col['name']]*len(points), True))
    return sorted(result, key=lambda h: -h[0])


def _repair_torsos(bodies, rigs, frames, clearance, reports, skip):
    """Small chest-only offsets; keep hips, ankles and all wrist contact sites.

    A pelvis conflict cannot be repaired without changing root/seat motion and
    stays a reported restaging problem. Chest translations are capped at 3 cm.
    """
    from .script_scene import _bones_only
    from .seating import _chain
    sc = bpy.context.scene
    snapshots, corrections = {}, {r.name: [] for r in rigs}
    failed=set()
    with _bones_only():
        for f in frames:
            sc.frame_set(f)
            matrices = {b.rig.name: {k: np.array(b.rig.matrix_world@b.rig.pose.bones[n].matrix)
                        for k,n in b.map.items()} for b in bodies}
            cols = [c for b in bodies for c in b.world(matrices[b.rig.name])]
            snapshots[f] = {}
            for body in bodies:
                rig = body.rig
                if rig not in rigs:
                    continue
                names = [body.map['chest'], *[body.map[k+'.'+s] for s in 'LR'
                          for k in ('upper_arm','forearm','hand')]]
                snapshots[f][rig.name] = (matrices[rig.name], {n:rig.pose.bones[n].matrix_basis.copy() for n in names})
                hits = [h for h in _torso_hits(cols, rig.name, clearance) if h[2] == 'chest']
                delta = np.zeros(3)
                if hits:
                    depth, normal = hits[0][:2]
                    normal = unit((normal[0],normal[1],0.))
                    peer = hits[0][3].split(':')[0]
                    share = .5 if peer in corrections else 1.
                    needed = normal*(depth+.001)*share
                    if np.linalg.norm(needed) <= min(.03, body.height*.02):
                        delta = needed
                    elif hits[0][4] > clearance+.01:
                        skip(rig, 'chest', f, 'chest offset exceeds 3 cm limit; root/seat preserved', hits[0][4])
                corrections[rig.name].append(delta)
        previous = {r.name:{} for r in rigs}
        for body in bodies:
            rig = body.rig
            if rig not in rigs:
                continue
            raw = np.array(corrections[rig.name])
            if np.max(np.linalg.norm(raw,axis=1)) < 1e-8:
                continue
            edges=np.zeros(len(frames),dtype=bool)
            if frames[0]>sc.frame_start:edges[0]=True
            if frames[-1]<sc.frame_end:edges[-1]=True
            filtered = smooth_corrections(raw,sc.render.fps/sc.render.fps_base,edges)
            for i,f in enumerate(frames):
                sc.frame_set(f)
                mats,base = snapshots[f][rig.name]
                for n,m in base.items():
                    rig.pose.bones[n].matrix_basis = m
                bpy.context.view_layer.update()
                chest = rig.pose.bones[body.map['chest']]
                world = Matrix(mats['chest'].tolist())
                error = 0.
                if np.linalg.norm(filtered[i])>1e-8:
                    anim._set_world_rot(rig,chest,world.to_quaternion(),world.translation+Vector(filtered[i]))
                    bpy.context.view_layer.update()
                    for side in 'LR':
                        names = [body.map[k+'.'+side] for k in ('upper_arm','forearm','hand')]
                        wrist = Matrix(mats['hand.'+side].tolist())
                        s,e,w = [mats[k+'.'+side][:3,3] for k in ('upper_arm','forearm','hand')]
                        error = max(error,_chain(rig,names,wrist.translation,Vector(e-(s+w)/2),wrist.to_quaternion()))
                        actual=(rig.matrix_world@rig.pose.bones[names[-1]].matrix).to_quaternion().normalized()
                        if abs(actual.dot(wrist.to_quaternion().normalized()))<1.-2e-6:error=max(error,.004)
                if error > .003:
                    for n,m in base.items():
                        rig.pose.bones[n].matrix_basis = m
                    failed.add(rig.name)
                    skip(rig,'chest',f,'chest offset cannot preserve wrist position/orientation',target_error=error)
                elif np.linalg.norm(filtered[i]) > 1e-7:
                    reports[rig.name]['corrected_frames'].add(f)
                    reports[rig.name]['_part_frames'].setdefault('chest',set()).add(f)
                chest.keyframe_insert('location',frame=f,group=chest.name)
                for side in 'LR':
                    for k in ('upper_arm','forearm','hand'):
                        anim._key_rot(rig.pose.bones[body.map[k+'.'+side]],f,previous[rig.name])
            paths={rig.pose.bones[body.map['chest']].path_from_id('location')}
            paths.update(rig.pose.bones[body.map[k+'.'+s]].path_from_id(p) for s in 'LR'
                         for k in ('upper_arm','forearm','hand') for p in ('rotation_quaternion','rotation_euler','rotation_axis_angle'))
            for fc in _data_curves(rig):
                if fc.data_path in paths:
                    for key in fc.keyframe_points:
                        if frames[0]<=key.co.x<=frames[-1]:
                            key.interpolation='LINEAR'
    return failed


def _seat_contact_samples(rigs, first, last):
    from .seating import _body_samples, _contact_height

    scene = bpy.context.scene
    samples = {}
    with evaluated_skin(rigs):
        for rig in rigs:
            if not rig.get('c3d_seat_active') or not rig.get('c3d_seated'):
                continue
            seat = json.loads(rig['c3d_seated'])
            events = json.loads(rig.get('c3d_seat_events', '[]'))
            settled = max((event['end'] for event in events if event['kind'] == 'sit'
                           and event['seat'] == seat['seat']), default=first)
            if settled > last:
                continue
            center, front = Vector(seat['center']), Vector(seat['front'])
            scene.frame_set(max(first, settled))
            body = _body_samples(rig, anim.semantic_map(rig))
            contacts = {}
            for frame in sorted({max(first, settled), last}):
                scene.frame_set(frame)
                try:
                    contacts[frame] = _contact_height(rig, center, front, body)
                except ValueError:
                    # Older or edited scenes can retain seating metadata after
                    # deleting the mesh contact surface or moving the character.
                    continue
            if contacts:
                samples[rig.name] = (center, front, body, contacts)
    return samples


@command('resolve_collisions')
def resolve_collisions(characters=None, frame_start=None, frame_end=None, parts='all',
                       clearance=.01, max_iterations=8, report_only=False, _sample_step=1):
    """Measure/repair baked arms/props; constrained legs, torsos and garments are reported.

    Corrections beyond 8% of measured standing height are skipped. Protected
    wrist contacts may only receive elbow pole changes. report_only never keys,
    installs bones, changes metadata or saves a project.
    """
    started = time.perf_counter()
    cpu_started = time.process_time()
    sc = bpy.context.scene
    f0 = sc.frame_start if frame_start is None else frame_start
    f1 = sc.frame_end if frame_end is None else frame_end
    if type(f0) is not int or type(f1) is not int or f0 < 0 or f1 < f0 or f1-f0 > 23999:
        raise ValueError('expected integer 0 <= frame_start <= frame_end, at most 24000 frames')
    if isinstance(clearance, bool) or not math.isfinite(clearance) or not 0 <= clearance <= .1:
        raise ValueError('clearance must be finite in 0..0.1 meters')
    if type(max_iterations) is not int or not 1 <= max_iterations <= 32:
        raise ValueError('max_iterations must be an integer in 1..32')
    if type(report_only) is not bool:
        raise ValueError('report_only must be a bool')
    selected = {'arms', 'props', 'legs', 'torso', 'clothes'} if parts == 'all' else set([parts] if isinstance(parts, str) else parts)
    if not selected or not selected <= {'arms', 'props', 'legs', 'torso', 'clothes'}:
        raise ValueError('parts must be all, arms, props, legs, torso, clothes or a list of these')
    if characters is not None and (not isinstance(characters, (list, tuple)) or not characters):
        raise ValueError('characters must be a nonempty list of rig/body names or None')
    rigs = sorted(set(_rig_of(c) for c in characters), key=lambda r: r.name) if characters else sorted(
        (o for o in sc.objects if o.type == 'ARMATURE' and not o.hide_render and not o.name.startswith('__')), key=lambda r: r.name)
    saved = (sc.frame_current, sc.frame_subframe)
    reports = {r.name: dict(parts={}, corrected_frames=set(), skipped=[], _part_frames={}) for r in rigs}
    if type(_sample_step) is not int or _sample_step < 1 or (_sample_step != 1 and not report_only):
        raise ValueError('sampling is available only for read-only scene review')
    frames = sorted({f0, f1, *range(f0, f1+1, _sample_step)})
    timing = {}
    try:
        sc.frame_set(f0)
        bodies = [Body(r) for r in rigs]
        # Other visible characters are colliders even when only one is selected.
        others = [o for o in sc.objects if o.type == 'ARMATURE' and o not in rigs
                  and not o.hide_render and not o.name.startswith('__')]
        for other in sorted(others, key=lambda r: r.name):
            try:
                bodies.append(Body(other))
            except ValueError:
                pass
        geometry = surfaces(rigs)
        all_rigs = [b.rig for b in bodies]
        window = [] if report_only else _window_snapshot(rigs,f0,f1)
        seat_samples = (_seat_contact_samples(rigs, f0, f1)
                        if not report_only and selected & {'arms', 'legs', 'torso'} else {})
        timing['fit'] = time.perf_counter()-started
        from .script_scene import _bones_only
        samples, bases, prop_samples, prop_roots = {}, {}, {}, {}
        t = time.perf_counter()
        with _bones_only():
            for f in frames:
                sc.frame_set(f)
                samples[f] = {b.rig.name: {k: np.array(b.rig.matrix_world@b.rig.pose.bones[n].matrix)
                                          for k, n in b.map.items()} for b in bodies}
                bases[f] = {r.name: {n: r.pose.bones[n].matrix_basis.copy() for n in anim.semantic_map(r).values()}
                            for r in rigs}
                prop_roots[f]={}
                prop_samples[f] = _prop_samples(f, all_rigs,prop_roots[f])
        timing['sample'] = time.perf_counter()-t
        t = time.perf_counter()
        plans, leg_plans, hints, blocked = {}, {}, {}, set()
        def skip(rig, side, f, reason, penetration=0., target_error=0.):
            reports[rig.name]['skipped'].append(dict(part=side, frame=f, reason=reason,
                                                   penetration_m=round(penetration, 6), target_error_m=round(target_error,6)))
        if 'clothes' in selected:
            _measure_garments(rigs,bodies,frames,geometry,reports,'before',clearance)
        for f in frames:
            cols = [c for b in bodies for c in b.world(samples[f][b.rig.name])]+_prop_colliders(prop_samples[f])
            for body in bodies:
                rig = body.rig
                if rig not in rigs:
                    continue
                stats = reports[rig.name]['parts']
                matrices = samples[f][rig.name]
                for side in 'LR' if selected & {'arms', 'props'} else '':
                    contacts = contacts_at(rig, side, f)
                    field = Field(cols, geometry, rig.name, side, clearance, contacts)
                    props = prop_samples[f].get((rig.name, side), []) if 'props' in selected else []
                    delta, pole, hits, reason = _plan_arm(body, cols, side, matrices, field,
                         body.height*.08, max_iterations if not report_only else 0, props, bool(contacts),
                         'arms' in selected,hints.get((rig.name,side)))
                    s,e,w=[matrices[k+'.'+side][:3,3] for k in ('upper_arm','forearm','hand')]
                    joint,_=two_bone(s,w+delta,np.linalg.norm(e-s),np.linalg.norm(w-e),pole)
                    if np.linalg.norm(joint-e)>body.height*.08 or np.linalg.norm(delta)>body.height*.08:
                        delta,pole=np.zeros(3),e-(s+w)/2
                        reason='planned correction exceeds wrist/elbow displacement limit'
                    if reason and np.linalg.norm(delta)<1e-7 and np.linalg.norm(pole-(e-(s+w)/2))<1e-7:
                        blocked.add((rig.name,side,f))
                    previous_hint=hints.get((rig.name,side))
                    if not previous_hint or not previous_hint.pop('_reused',False):
                        hints[(rig.name,side)]=dict(delta=delta,offset=pole-(e-(s+w)/2),source=(s.copy(),e.copy(),w.copy()),
                                                   reason=reason,signature=hits[0] if hits else None,age=0)
                    if 'arms' not in selected:
                        hits = [h for h in hits if h[2].startswith('prop:')]
                    _statistics(hits, stats, 'before', f)
                    plans[(rig.name, side, f)] = (delta, pole, bool(contacts))
                    if reason and hits:
                        skip(rig, 'arm.'+side, f, reason, max(h[4] for h in hits))
                if 'legs' in selected:
                    for side in 'LR':
                        pole, hits, reason = _plan_leg(body, cols, side, matrices, geometry, clearance)
                        leg_plans[(rig.name, side, f)] = pole
                        _statistics(hits, stats, 'before', f)
                        if reason and hits:
                            skip(rig, 'leg.'+side, f, reason, max(h[4] for h in hits))
                if 'torso' in selected:
                    hits = _torso_hits(cols, rig.name, clearance)
                    _statistics(hits, stats, 'before', f)
                    for hit in hits:
                        if hit[2] in ('pelvis','abdomen') and hit[4]>clearance+.01:
                            skip(rig, hit[2], f, 'pelvis/seat/root anchor preserved; restage deep body overlap', hit[4])
        timing['plan'] = time.perf_counter()-t
        t = time.perf_counter()
        failed_rigs=set()
        if not report_only:
            # Smooth target and elbow corrections before any keys are written.
            edges=np.zeros(len(frames),dtype=bool)
            if f0>sc.frame_start:edges[0]=True
            if f1<sc.frame_end:edges[-1]=True
            for body in bodies:
                if body.rig not in rigs:
                    continue
                for side in 'LR' if selected & {'arms', 'props'} else '':
                    rows = [plans[(body.rig.name, side, f)] for f in frames]
                    excluded=edges|np.array([(body.rig.name,side,f) in blocked for f in frames])
                    delta = smooth_corrections([r[0] for r in rows], sc.render.fps/sc.render.fps_base,
                                               np.array([r[2] for r in rows])|excluded)
                    base_poles = []
                    for f in frames:
                        mats = samples[f][body.rig.name]
                        s, e, w = [mats[k+'.'+side][:3, 3] for k in ('upper_arm', 'forearm', 'hand')]
                        base_poles.append(e-(s+w)/2)
                    poles = np.array([r[1] for r in rows])
                    offset = smooth_corrections(poles-np.array(base_poles), sc.render.fps/sc.render.fps_base,excluded)
                    # Filtering changes both wrist and pole, and their combined
                    # IK can move an elbow farther than either raw plan did.
                    # Scale the entire continuous layer together, rather than
                    # clipping individual frames and introducing a velocity jump.
                    amount=1.
                    for _ in range(14):
                        valid=True
                        for i,f in enumerate(frames):
                            mats=samples[f][body.rig.name]
                            s,e,w=[mats[k+'.'+side][:3,3] for k in ('upper_arm','forearm','hand')]
                            target=w+delta[i]*amount
                            joint,endpoint=two_bone(s,target,np.linalg.norm(e-s),np.linalg.norm(w-e),
                                                    base_poles[i]+offset[i]*amount)
                            if (np.linalg.norm(delta[i]*amount)>body.height*.08 or
                                np.linalg.norm(joint-e)>body.height*.08 or
                                joint[2]>_elbow_ceiling(body,s,e)+.0005 or
                                np.linalg.norm(endpoint-target)>.0025):
                                valid=False;break
                        if valid:break
                        amount*=.75
                    if not valid:amount=0.
                    for i, f in enumerate(frames):
                        plans[(body.rig.name, side, f)] = (delta[i]*amount, base_poles[i]+offset[i]*amount, rows[i][2])
            active = {(b.rig.name, side) for b in bodies if b.rig in rigs
                      for side in 'LR' if selected & {'arms', 'props'}
                      if any(np.linalg.norm(plans[(b.rig.name, side, f)][0]) > 1e-7 or
                          np.linalg.norm(plans[(b.rig.name, side, f)][1] -
                          (samples[f][b.rig.name]['forearm.'+side][:3, 3]-
                           (samples[f][b.rig.name]['upper_arm.'+side][:3, 3]+
                            samples[f][b.rig.name]['hand.'+side][:3, 3])/2)) > 1e-7 for f in frames)}
            active_legs = set()
            if 'legs' in selected:
                for b in bodies:
                    if b.rig not in rigs:
                        continue
                    for side in 'LR':
                        base = np.array([samples[f][b.rig.name]['shin.'+side][:3, 3] -
                            (samples[f][b.rig.name]['thigh.'+side][:3, 3]+samples[f][b.rig.name]['foot.'+side][:3, 3])/2 for f in frames])
                        offset = np.array([leg_plans[(b.rig.name, side, f)] for f in frames])-base
                        if np.max(np.linalg.norm(offset, axis=1)) > 1e-7:
                            active_legs.add((b.rig.name, side))
                            offset = smooth_corrections(offset, sc.render.fps/sc.render.fps_base,edges)
                            for i, f in enumerate(frames):
                                leg_plans[(b.rig.name, side, f)] = base[i]+offset[i]
            previous = {r.name: {} for r in rigs}
            with _bones_only():
                for f in frames:
                    sc.frame_set(f)
                    rows=[]
                    for body in bodies:
                        rig=body.rig
                        if rig not in rigs:continue
                        mats=samples[f][rig.name]
                        for side in 'LR':
                            for kind,enabled in (('arm',(rig.name,side) in active),('leg',(rig.name,side) in active_legs)):
                                if not enabled:continue
                                semantics=('upper_arm','forearm','hand') if kind=='arm' else ('thigh','shin','foot')
                                names=[body.map[k+'.'+side] for k in semantics]
                                S,E,W=[mats[k+'.'+side][:3,3] for k in semantics]
                                original=E-(S+W)/2
                                if kind=='arm':delta,pole,locked=plans[(rig.name,side,f)]
                                else:delta,pole,locked=np.zeros(3),leg_plans[(rig.name,side,f)],True
                                changed=np.linalg.norm(delta)>1e-7 or np.linalg.norm(pole-original)>1e-7
                                if np.linalg.norm(delta)>body.height*.08:
                                    skip(rig,kind+'.'+side,f,'filtered correction exceeds displacement limit')
                                    failed_rigs.add(rig.name)
                                    changed=False
                                for n in names:rig.pose.bones[n].matrix_basis=bases[f][rig.name][n]
                                end=Matrix(mats[semantics[-1]+'.'+side].tolist())
                                task=(rig,names,Vector(W+delta),Vector(pole),end.to_quaternion())
                                rows.append((body,kind,side,names,task,changed,E))
                    if rows:bpy.context.view_layer.update()
                    _batch_chains([row[4] for row in rows if row[5]])
                    failed=False
                    for body,kind,side,names,task,changed,original_elbow in rows:
                        rig=body.rig
                        if changed:
                            actual=rig.matrix_world@rig.pose.bones[names[-1]].matrix
                            elbow=(rig.matrix_world@rig.pose.bones[names[1]].matrix).translation
                            error=(actual.translation-task[2]).length
                            orientation=abs(actual.to_quaternion().normalized().dot(task[4].normalized()))
                            excessive=(elbow-Vector(original_elbow)).length>body.height*.08+.001
                            if kind=='arm':excessive |= elbow.z>_elbow_ceiling(body,samples[f][rig.name]['upper_arm.'+side][:3,3],original_elbow)+.001
                            if error>.003 or orientation<1.-2e-6 or excessive:
                                for n in names:rig.pose.bones[n].matrix_basis=bases[f][rig.name][n]
                                skip(rig,kind+'.'+side,f,'evaluated IK/constraint or elbow limit cannot preserve the target',target_error=error)
                                failed_rigs.add(rig.name)
                                changed=False;failed=True
                        for n in names:anim._key_rot(rig.pose.bones[n],f,previous[rig.name])
                        if changed:
                            reports[rig.name]['corrected_frames'].add(f)
                            for part in (('upper_arm','forearm','hand') if kind=='arm' else ('thigh','shin')):
                                reports[rig.name]['_part_frames'].setdefault(part+'.'+side,set()).add(f)
                            if kind=='arm' and 'props' in selected:
                                for name,_ in prop_samples[f].get((rig.name,side),[]):
                                    reports[rig.name]['_part_frames'].setdefault('prop:'+name,set()).add(f)
                    if failed:bpy.context.view_layer.update()
            for rig in rigs:
                paths = {rig.pose.bones[anim.semantic_map(rig)[k+'.'+s]].path_from_id(p)
                         for k in ('upper_arm', 'forearm', 'hand', 'thigh', 'shin', 'foot') for s in 'LR'
                         if (rig.name, s) in (active if k in ('upper_arm', 'forearm', 'hand') else active_legs)
                         for p in ('rotation_quaternion', 'rotation_euler', 'rotation_axis_angle')}
                for fc in _data_curves(rig):
                    if fc.data_path in paths:
                        for key in fc.keyframe_points:
                            if f0 <= key.co.x <= f1:
                                key.interpolation = 'LINEAR'
        if 'torso' in selected and not report_only:
            failed_rigs.update(_repair_torsos(bodies, rigs, frames, clearance, reports, skip))
        if seat_samples:
            from .seating import _contact_height
            with evaluated_skin(rigs):
                for rig in rigs:
                    if rig.name not in seat_samples:
                        continue
                    center, front, body, contacts = seat_samples[rig.name]
                    for frame, before in contacts.items():
                        sc.frame_set(frame)
                        try:
                            error = abs(_contact_height(rig, center, front, body) - before)
                        except ValueError:
                            error = math.inf
                        if error > .003:
                            failed_rigs.add(rig.name)
                            skip(rig, 'seat', frame, 'body correction moved the seat contact',
                                 target_error=error if math.isfinite(error) else 0.)
        timing['bake'] = time.perf_counter()-t
        t = time.perf_counter()
        # Re-measure evaluated bones after keying, including all newly moved peer
        # arms. Never report a predicted target as an observed improvement.
        measured_roots={}
        def measure_baked():
            measured_roots.clear()
            for report in reports.values():
                for stat in report['parts'].values():
                    stat['count_after']=0
                    stat['max_penetration_after_m']=0.
            with _bones_only():
                for f in frames:
                    sc.frame_set(f)
                    mats = {b.rig.name: {k: np.array(b.rig.matrix_world@b.rig.pose.bones[n].matrix)
                                        for k, n in b.map.items()} for b in bodies}
                    measured_roots[f]={}
                    props = _prop_samples(f, all_rigs,measured_roots[f])
                    cols = [c for b in bodies for c in b.world(mats[b.rig.name])]+_prop_colliders(props)
                    for body in bodies:
                        rig = body.rig
                        if rig not in rigs:
                            continue
                        stats = reports[rig.name]['parts']
                        for side in 'LR' if selected & {'arms', 'props'} else '':
                            S, E, W = [mats[rig.name][k+'.'+side][:3, 3] for k in ('upper_arm', 'forearm', 'hand')]
                            pts, radii, labels = _arm_points(body, cols, side, S, E, W, W,
                                                             props.get((rig.name, side), []) if 'props' in selected else [])
                            hits = Field(cols, geometry, rig.name, side, clearance, contacts_at(rig, side, f)).hits(pts, radii, labels, True)
                            if 'arms' not in selected:
                                hits = [h for h in hits if h[2].startswith('prop:')]
                            _statistics(hits, stats, 'after', f)
                            if hits and hits[0][4] > clearance+.01 and not report_only:
                                skip(rig, 'arm.'+side, f, 'residual proxy/BVH conflict after bounded solve', max(h[4] for h in hits))
                        if 'legs' in selected:
                            for side in 'LR':
                                hip, knee, ankle = [mats[rig.name][k+'.'+side][:3, 3] for k in ('thigh', 'shin', 'foot')]
                                col = {c['name'].split('.')[0]: c for c in cols if c['owner'] == rig.name
                                       and c['name'] in ('thigh.'+side, 'shin.'+side)}
                                hits = Field([], geometry, rig.name, side, clearance).hits(*_leg_points(col, hip, knee, ankle),exact=True)
                                _statistics(hits, stats, 'after', f)
                                if hits and hits[0][4] > clearance+.01 and not report_only:
                                    skip(rig, 'leg.'+side, f, 'residual seat/BVH conflict; ankle and seat anchors preserved', max(h[4] for h in hits))
                        if 'torso' in selected:
                            hits = _torso_hits(cols, rig.name, clearance)
                            _statistics(hits, stats, 'after', f)
                            if hits and hits[0][4]>clearance+.01 and not report_only:
                                skip(rig, hits[0][2], f, 'residual torso conflict after bounded chest offset; root/feet preserved', max(h[4] for h in hits))
        def prop_continuity():
            offenders=set();metrics={}
            fps=sc.render.fps/sc.render.fps_base
            for a,b in zip(frames,frames[1:]):
                for name in sorted(prop_roots[a].keys() & prop_roots[b].keys()):
                    if name not in measured_roots[a] or name not in measured_roots[b]:continue
                    before=float(np.linalg.norm(prop_roots[b][name][1]-prop_roots[a][name][1]))
                    after=float(np.linalg.norm(measured_roots[b][name][1]-measured_roots[a][name][1]))
                    metric=metrics.setdefault(name,dict(max_step_before_m=0.,max_step_after_m=0.))
                    metric['max_step_before_m']=max(metric['max_step_before_m'],before)
                    metric['max_step_after_m']=max(metric['max_step_after_m'],after)
                    # Keep authored fast travel; a deliberate slow handover must
                    # not gain a one-frame jump from a clearance correction.
                    limit=max(before+.0001,.02*24/fps*(b-a))
                    if after>limit+1e-6:
                        offenders.update((prop_roots[a][name][0],prop_roots[b][name][0]))
            return offenders,metrics
        measure_baked()
        rejected=set()
        if not report_only:
            for _ in range(2):
                discontinuous,_=prop_continuity()
                worse=[rig for rig in rigs if rig.name not in rejected and (rig.name in discontinuous or rig.name in failed_rigs or any(
                    stat['max_penetration_after_m']>max(clearance+.01,stat['max_penetration_before_m']+.002)
                    for stat in reports[rig.name]['parts'].values()))]
                if not worse:break
                for rig in worse:
                    _reject_body_bake(window,rig,bases[f0][rig.name])
                    rejected.add(rig.name)
                    reports[rig.name]['corrected_frames'].clear()
                    reports[rig.name]['_part_frames'].clear()
                    for f in frames:
                        skip(rig,'body',f,('held prop step exceeds continuity limit' if rig.name in discontinuous else
                             'IK/constraint rejection requires a continuous original performance' if rig.name in failed_rigs else
                             'combined correction would increase penetration')+'; original physical performance restored')
                measure_baked()
        timing['measure'] = time.perf_counter()-t
        garments = []
        if 'clothes' in selected:
            t = time.perf_counter()
            if not report_only:
                from .secondary import secondary_motion
                for rig in rigs:
                    meshes = [obj.name for obj in _garment_meshes(rig)]
                    if not meshes:
                        continue
                    with _bones_only():
                        state=json.loads(rig.get('char3d_secondary', '{}'))
                        settings = state.get('settings_by_part',{}).get('clothes',state.get('settings', {}))
                        garment = secondary_motion(rig.name, parts=meshes, frame_start=f0, frame_end=f1,
                                                     **dict(settings, collisions=True))
                        garments.append(garment)
                        if garment['bones']:
                            reports[rig.name]['corrected_frames'].update(frames)
                            for name in garment['meshes']:
                                reports[rig.name]['_part_frames'].setdefault('garment:'+name,set()).update(frames)
            _measure_garments(rigs,bodies,frames,geometry,reports,'after',clearance,skip if not report_only else None)
            timing['garments'] = time.perf_counter()-t
        if window:
            _restore_window(window,f0,f1)
        for report in reports.values():
            part_frames=report.pop('_part_frames')
            for part in part_frames:
                report['parts'].setdefault(part,dict(count_before=0,count_after=0,
                    max_penetration_before_m=0.,max_penetration_after_m=0.,colliders=set()))
            for part, stat in report['parts'].items():
                stat['frames_corrected']=sorted(part_frames.get(part,set()))
                stat['corrected_count']=len(stat['frames_corrected'])
                stat['colliders'] = sorted(stat['colliders'])
                for key in ('max_penetration_before_m', 'max_penetration_after_m'):
                    stat[key] = round(stat[key], 6)
            report['corrected_frames'] = sorted(report['corrected_frames'])
            grouped = {}
            for conflict in report['skipped']:
                key = (conflict['part'], conflict['reason'])
                group = grouped.setdefault(key, dict(part=conflict['part'], reason=conflict['reason'],
                                                       frames=set(), max_penetration_m=0., max_target_error_m=0.))
                group['frames'].add(conflict['frame'])
                group['max_penetration_m'] = max(group['max_penetration_m'], conflict['penetration_m'])
                group['max_target_error_m'] = max(group['max_target_error_m'],conflict.get('target_error_m',0.))
            report['skipped'] = [dict(g, frames=sorted(g['frames']), count=len(g['frames']))
                                 for g in grouped.values()]
            report['skipped_large_conflicts'] = sum(g['count'] for g in report['skipped']
                                                   if 'limit' in g['reason'] or 'exceeds' in g['reason'])
        timing['total'] = time.perf_counter()-started
        timing['cpu_total'] = time.process_time()-cpu_started
        _,prop_motion=prop_continuity()
        return dict(characters=reports, frames=[f0, f1], clearance_m=clearance, report_only=report_only,
                    frames_corrected=sum(len(r['corrected_frames']) for r in reports.values()),
                    max_penetration_before_m=max((s['max_penetration_before_m'] for r in reports.values() for s in r['parts'].values()), default=0.),
                    max_penetration_after_m=max((s['max_penetration_after_m'] for r in reports.values() for s in r['parts'].values()), default=0.),
                    static_colliders=[s.name for s in geometry], garments=garments,prop_motion=prop_motion,
                    timings={k: round(v, 4) for k, v in timing.items()},
                    limits=['Measured skin-fitted proxies; static evaluated scene BVHs; sampled prop vertices.',
                            'No finger-level, continuous swept-mesh or full cloth/self collision simulation.',
                            'Protected contacts, root/feet/seat and large conflicts may require restaging.'])
    finally:
        sc.frame_set(saved[0], subframe=saved[1])
        bpy.context.view_layer.update()
