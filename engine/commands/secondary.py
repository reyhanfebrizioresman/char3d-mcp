"""Deterministic, baked hair springs. Only owned deform bones/curves are modified.

The solver operates on cached world-space attachment/collider samples, without
evaluating Blender inside its substeps. Authored rest curves are elastic targets;
capsules are conservative rest-fitted body proxies, not triangle-mesh collisions.
"""
import json
import math
import time

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from . import command
from .anim import _key_rot, semantic_map
from .talk import _fcurves, _rig_of

_STATE = "char3d_secondary"
_HAIR = ("hair", "ponytail", "braid", "long01", "bob01", "bob02", "afro", "short")


def _asset_name(obj, rig):
    prefix = rig.name.removesuffix('_rig') + '.'
    return obj.name.removeprefix(prefix).lower()


def _deform_head(rig, smap):
    # Rigify controls are not deformation parents (and are stripped by exporters).
    return next((n for n in ("DEF-spine.006", "DEF-head", smap.get("head"))
                 if n and n in rig.data.bones and rig.data.bones[n].use_deform),
                smap.get("head"))


def _basis(rig, smap):
    b = rig.data.bones
    left = (b[smap['thigh.L']].head_local - b[smap['thigh.R']].head_local).normalized()
    up = b[smap['head']].tail_local - b[smap['hips']].head_local
    up = (up - left * up.dot(left)).normalized()
    return Matrix((left, up.cross(left), up)).transposed()


def _geometry(obj, rig, basis):
    mat = basis.transposed().to_4x4() @ rig.matrix_world.inverted() @ obj.matrix_world
    return np.array([mat @ v.co for v in obj.data.vertices], dtype=float)


def _chains(obj, rig, smap, parent, index):
    basis = _basis(rig, smap)
    pts = _geometry(obj, rig, basis)
    eligible = np.ones(len(pts), dtype=bool)
    if not any(h in _asset_name(obj, rig) for h in _HAIR):
        hints = {g.index for g in obj.vertex_groups if any(h in g.name.lower() for h in _HAIR)}
        eligible = np.array([any(g.group in hints and g.weight > 0 for g in v.groups)
                             for v in obj.data.vertices])
    if not np.any(eligible):
        return [], None
    head = basis.transposed() @ rig.data.bones[smap['head']].head_local
    h = rig.data.bones[smap['head']].length
    root_z = head.z + h * 0.28
    low = float(np.quantile(pts[eligible, 2], 0.01))
    if root_z - low < h * 0.45:
        return [], None
    active = (pts[:, 2] < root_z) & eligible
    single = any(n in _asset_name(obj, rig) for n in ('ponytail', 'braid'))
    if single:
        # Exclude fringe/scalp in front of the attachment when tracing the tail.
        active &= pts[:, 1] > head.y + h * 0.4
    loose = pts[active]
    if len(loose) < 12:
        return [], None
    if single:
        centers = np.mean(loose[:, :2], axis=0)[None, :]
    else:
        angles = np.arctan2(loose[:, 0] - head.x, loose[:, 1] - head.y)
        # Deterministic angular seeds followed by a few 2D Lloyd iterations.
        ordered = loose[np.argsort(angles), :2]
        count = min(5, max(1, len(loose) // 24))
        centers = ordered[np.linspace(0, len(ordered) - 1, count).astype(int)].copy()
        for _ in range(8):
            labels = np.argmin(((loose[:, None, :2] - centers) ** 2).sum(axis=2), axis=1)
            centers = np.array([loose[labels == k, :2].mean(axis=0)
                                if np.any(labels == k) else c for k, c in enumerate(centers)])
    labels = np.argmin(((loose[:, None, :2] - centers) ** 2).sum(axis=2), axis=1)
    chains = []
    for k, center in enumerate(centers):
        strand = loose[labels == k]
        if len(strand) < 8:
            continue
        end_z = float(np.quantile(strand[:, 2], 0.01))
        if root_z - end_z < h * 0.4:
            continue
        nodes = []
        for z in np.linspace(root_z, end_z, 5):
            nearby = strand[np.argsort(abs(strand[:, 2] - z))[:max(8, len(strand) // 10)]]
            xy = np.median(nearby[:, :2], axis=0)
            nodes.append(basis @ Vector((float(xy[0]), float(xy[1]), float(z))))
        radial = np.linalg.norm(strand[:, :2] - center, axis=1)
        radius = min(h * 0.16, max(h * 0.035, float(np.quantile(radial, 0.65)) * 0.5))
        chains.append(dict(bones=[f'hair_{index + len(chains):02d}_{j:02d}' for j in range(4)],
                           points=[list(p) for p in nodes], radius=radius, parent=parent,
                           mesh=obj.name, center=center.tolist(), root_z=root_z,
                           end_z=end_z))
    return chains, (pts, active, basis)


def _install(rig, chains, geometry):
    for ch in chains:
        for name in ch['bones']:
            if name in rig.data.bones:
                raise ValueError(f'{name} already exists and is not owned by secondary_motion')
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    hidden = rig.hide_get()
    try:
        rig.hide_set(False)
        for o in selected:
            o.select_set(False)
        rig.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='EDIT')
        for ch in chains:
            parent = rig.data.edit_bones[ch['parent']]
            for j, name in enumerate(ch['bones']):
                bone = rig.data.edit_bones.new(name)
                bone.head, bone.tail = ch['points'][j:j + 2]
                bone.parent = parent
                bone.use_connect = j > 0
                bone.use_deform = True
                parent = bone
        bpy.ops.object.mode_set(mode='OBJECT')
        coll = rig.data.collections.get('Secondary motion') or rig.data.collections.new('Secondary motion')
        coll.is_visible = False
        for ch in chains:
            for name in ch['bones']:
                bone = rig.data.bones[name]
                coll.assign(bone)
                for other in list(bone.collections):
                    if other != coll:
                        other.unassign(bone)
                rig.pose.bones[name].rotation_mode = 'QUATERNION'
        # At bind pose every new bone has an identity skin matrix. Reweight only
        # the loose region; scalp weights and all non-bone groups remain intact.
        deform = {b.name for b in rig.data.bones if b.use_deform}
        for obj, mesh_chains, (pts, mask, _basis_matrix) in geometry:
            groups = {n: obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n)
                      for ch in mesh_chains for n in ch['bones']}
            centers = np.array([ch['center'] for ch in mesh_chains])
            head = obj.vertex_groups.get(mesh_chains[0]['parent'])
            head = head if head is not None else obj.vertex_groups.new(name=mesh_chains[0]['parent'])
            old = {g.index: g for g in obj.vertex_groups if g.name in deform and g.name not in groups}
            for i in np.flatnonzero(mask):
                i = int(i)
                distances = np.linalg.norm(centers - pts[i, :2], axis=1)
                near = np.argsort(distances)[:2]
                weights = 1 / np.maximum(distances[near], 0.005) ** 4
                weights /= weights.sum()
                result = {}
                for k, w in zip(near, weights):
                    ch = mesh_chains[k]
                    t = float(np.clip((ch['root_z'] - pts[i, 2]) /
                                      (ch['root_z'] - ch['end_z']) * 4, 0, 4))
                    # Blend head -> first bone over the first quarter of the lock,
                    # then between adjacent bones, never above the attachment.
                    a = min(3, int(t))
                    u = min(1.0, t - a)
                    names = [ch['parent'], *ch['bones']]
                    for n, value in ((names[a], 1 - u), (names[a + 1], u)):
                        result[n] = result.get(n, 0.0) + float(w) * value
                for g in list(obj.data.vertices[i].groups):
                    if g.group in old:
                        old[g.group].remove([i])
                for n, value in result.items():
                    if value > 0:
                        (head if n == head.name else groups[n]).add([i], value, 'REPLACE')
    finally:
        if rig.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        rig.select_set(False)
        for o in selected:
            o.select_set(True)
        bpy.context.view_layer.objects.active = active
        rig.hide_set(hidden)


def _closest(p, a, b):
    d = b - a
    return a + d * max(0.0, min(1.0, (p - a).dot(d) / max(d.length_squared, 1e-12)))


def _colliders(rig, smap, parent, chains):
    b = rig.data.bones
    basis = _basis(rig, smap)
    up, back = basis.col[2], basis.col[1]
    head = b[parent]
    h = b[smap['head']].length
    neck = b[smap['neck']]
    shoulders = [b[smap[f'upper_arm.{s}']].head_local for s in 'LR']
    specs = [dict(name='head', bone=parent, a=list(head.head_local.lerp(head.tail_local, .48)),
                  b=list(head.head_local.lerp(head.tail_local, .68)), radius=h * .46),
             dict(name='neck', bone=smap['neck'], a=list(neck.head_local),
                  b=list(neck.tail_local), radius=h * .29),
             dict(name='shoulders', bone=smap['chest'],
                  a=list(shoulders[0] - back * h * .18),
                  b=list(shoulders[1] - back * h * .18), radius=h * .36),
             dict(name='upper_back', bone=smap['chest'],
                  a=list(neck.head_local - up * h * 2.0 - back * h * .5),
                  b=list(neck.head_local - up * h * .5 - back * h * .5), radius=h * .75)]
    for c in specs:
        # Fit inside the authored hair's envelope: no pop at bind pose, including
        # assets already close to the shoulders. Radius is in armature rest units.
        a, bb = Vector(c['a']), Vector(c['b'])
        gap = min((p - _closest(p, a, bb)).length - ch['radius']
                  for ch in chains for p in _strand_samples(ch))
        c['radius'] = max(0.001, min(c['radius'], gap - .002))
    return specs


def _strand_samples(ch):
    points = [Vector(p) for p in ch['points']]
    return [a.lerp(b, s) for a, b in zip(points, points[1:]) for s in (.25, .5, .75, 1.)]


def _clear_keys(rig, names, f0, f1, neutral=False):
    act = rig.animation_data.action if rig.animation_data else None
    paths = {rig.pose.bones[n].path_from_id('rotation_quaternion') for n in names}
    for fc in _fcurves(act):
        if fc.data_path not in paths:
            continue
        for index in range(len(fc.keyframe_points) - 1, -1, -1):
            k = fc.keyframe_points[index]
            if f0 <= k.co.x <= f1:
                fc.keyframe_points.remove(k, fast=True)
        fc.update()
        if neutral and len(fc.keyframe_points):
            value = 1.0 if fc.array_index == 0 else 0.0
            for f in (f0, f1):
                fc.keyframe_points.insert(f, value).interpolation = 'LINEAR'
    for n in names:
        rig.pose.bones[n].rotation_quaternion = Quaternion()


def _sample(rig, chains, colliders, f0, f1):
    sc = bpy.context.scene
    rest_inv = {n: rig.data.bones[n].matrix_local.inverted()
                for n in {ch['parent'] for ch in chains} | {c['bone'] for c in colliders}}
    samples = []
    for f in range(f0 - 1, f1 + 2):
        sc.frame_set(f)
        mw = rig.matrix_world.copy()
        transforms = {n: mw @ rig.pose.bones[n].matrix @ inv for n, inv in rest_inv.items()}
        strands = [[transforms[ch['parent']] @ Vector(p) for p in ch['points']] for ch in chains]
        cols = [(transforms[c['bone']] @ Vector(c['a']), transforms[c['bone']] @ Vector(c['b']),
                 c['radius'] * max(transforms[c['bone']].to_scale())) for c in colliders]
        samples.append((strands, cols, mw, {ch['parent']: rig.pose.bones[ch['parent']].matrix.copy()
                                          for ch in chains}))
    return samples


def _constrain(points, targets, lengths, colliders, radius):
    points[0] = targets[0].copy()
    for j, length in enumerate(lengths):
        a = points[j]
        d = points[j + 1] - a
        if d.length < 1e-9:
            d = targets[j + 1] - targets[j]
        p = a + d.normalized() * length
        for _ in range(6):
            for ca, cb, cr in colliders:
                for s in (.25, .5, .75, 1.):
                    q = a.lerp(p, s)
                    nearest = _closest(q, ca, cb)
                    normal = q - nearest
                    limit = cr + radius
                    if normal.length < limit:
                        if normal.length < 1e-9:
                            normal = Vector((0, 1, 0))
                        p += normal.normalized() * (limit - (q - nearest).length) / s
                        p = a + (p - a).normalized() * length
        points[j + 1] = p


def _bake(rig, chains, colliders, samples, f0, f1, stiffness, damping, gravity, wind):
    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    dt = 1 / fps
    steps = max(4, math.ceil(dt * 120))
    step = dt / steps
    omega = 7 + 16 * stiffness
    drag = 2 * (.35 + damping) * omega
    # Reduced effective gravity preserves the authored groom; this is an elastic
    # style control, not a mass/material-accurate hair simulation.
    force = Vector(wind) + Vector((0, 0, -0.981 * gravity))
    offsets = [[Vector() for _ in ch['points']] for ch in chains]
    velocities = [[Vector() for _ in ch['points']] for ch in chains]
    prev = {}
    motion, final, clearance = 0.0, 0.0, float('inf')
    for i, f in enumerate(range(f0, f1 + 1), 1):
        targets, cols, mw, parents = samples[i]
        inverse = mw.inverted()
        for k, ch in enumerate(chains):
            rest = targets[k]
            before, after = samples[i - 1][0][k], samples[i + 1][0][k]
            acceleration = [(a - 2 * b + c) / (dt * dt) for a, b, c in zip(before, rest, after)]
            # Mild air resistance gives sustained travel a trailing groom, even
            # when root velocity is constant. It vanishes as the body stops.
            air = [(a - b) * ((1.5 + 3 * (1 - stiffness)) / (2 * dt))
                   for a, b in zip(after, before)]
            lengths = [(b - a).length for a, b in zip(rest, rest[1:])]
            radius = ch['radius'] * max(mw.to_scale())
            for _ in range(steps):
                old = [v.copy() for v in offsets[k]]
                for j in range(1, len(rest)):
                    velocities[k][j] += (force - acceleration[j] - air[j] - omega * omega * offsets[k][j]
                                          - drag * velocities[k][j]) * step
                    offsets[k][j] += velocities[k][j] * step
                points = [p + d for p, d in zip(rest, offsets[k])]
                _constrain(points, rest, lengths, cols, radius)
                for j in range(1, len(rest)):
                    offsets[k][j] = points[j] - rest[j]
                    velocities[k][j] = (offsets[k][j] - old[j]) / step
            displacement = offsets[k][-1].length
            motion = max(motion, displacement)
            if f == f1:
                final = max(final, displacement)
            for a, b in zip(points, points[1:]):
                for s in (.25, .5, .75, 1.):
                    p = a.lerp(b, s)
                    for ca, cb, cr in cols:
                        clearance = min(clearance, (p - _closest(p, ca, cb)).length - cr - radius)
            parent_matrix = parents[ch['parent']]
            for j, name in enumerate(ch['bones']):
                bone = rig.data.bones[name]
                # Recover the posed rest orientation from the attachment, then
                # swing it to the constrained direction without introducing twist.
                attach = mw @ parents[ch['parent']] @ rig.data.bones[ch['parent']].matrix_local.inverted()
                rest_matrix = attach @ bone.matrix_local
                q = (rest[j + 1] - rest[j]).rotation_difference(points[j + 1] - points[j])
                desired = inverse @ Matrix.LocRotScale(points[j], q @ rest_matrix.to_quaternion(),
                                                       rest_matrix.to_scale())
                local = bone.convert_local_to_pose(desired, bone.matrix_local,
                                                    parent_matrix=parent_matrix,
                                                    parent_matrix_local=bone.parent.matrix_local,
                                                    invert=True)
                pb = rig.pose.bones[name]
                pb.rotation_quaternion = local.to_quaternion()
                _key_rot(pb, f, prev)
                parent_matrix = desired
    return dict(max_tip_offset_m=round(motion, 6), final_tip_offset_m=round(final, 6),
                min_collider_clearance_m=round(clearance, 6))


@command('secondary_motion')
def secondary_motion(character, parts=('hair',), frame_start=None, frame_end=None,
                     stiffness=0.5, damping=0.5, gravity=1.0, wind=None, clear=False):
    """Bake elastic hair chains after body/face motion; export as ordinary skin bones."""
    started = time.perf_counter()
    if isinstance(parts, str) or not parts or any(p not in ('hair', 'clothes') for p in parts):
        raise ValueError('parts must contain hair and/or clothes')
    for n, v in (('stiffness', stiffness), ('damping', damping), ('gravity', gravity)):
        if not math.isfinite(v) or v < 0 or (n != 'gravity' and v > 1):
            raise ValueError(f'{n} must be finite and ' + ('>= 0' if n == 'gravity' else 'in 0..1'))
    wind = (0, 0, 0) if wind is None else wind
    if len(wind) != 3 or not all(math.isfinite(v) for v in wind):
        raise ValueError('wind must be a finite world-space XYZ acceleration vector')
    rig = _rig_of(character)
    sc = bpy.context.scene
    f0 = sc.frame_start if frame_start is None else int(frame_start)
    f1 = sc.frame_end if frame_end is None else int(frame_end)
    if f0 < 0 or f1 < f0 or f1 - f0 > 23999:
        raise ValueError('expected 0 <= frame_start <= frame_end and at most 24000 frames')
    state = json.loads(rig.get(_STATE, '{"meshes": {}, "chains": [], "colliders": []}'))
    skipped = []
    if 'clothes' in parts:
        skipped.append(dict(part='clothes', reason='Loose clothes/cloth simulation is not supported; hair only.'))
    saved = sc.frame_current
    try:
        if 'hair' in parts and not clear:
            smap = semantic_map(rig)
            if not all(n in smap for n in ('head', 'neck', 'chest', 'hips', 'thigh.L', 'thigh.R',
                                           'upper_arm.L', 'upper_arm.R')):
                raise ValueError(f'{rig.name}: cannot identify humanoid head/torso bones')
            parent = _deform_head(rig, smap)
            candidates = sorted((o for o in sc.objects if o.type == 'MESH' and o.find_armature() == rig
                                 and not o.get('c3d_source') and o.get('c3d_kind') != 'humanoid' and
                                 any(h in _asset_name(o, rig) or any(h in g.name.lower() for g in o.vertex_groups)
                                     for h in _HAIR)), key=lambda o: o.name)
            fresh, geometry = [], []
            for obj in candidates:
                if obj.name in state['meshes']:
                    if len(obj.data.vertices) != state['meshes'][obj.name]:
                        raise ValueError(f'{obj.name}: topology changed after secondary chain setup')
                    continue
                if any(h in _asset_name(obj, rig) for h in ('short', 'afro')):
                    skipped.append(dict(object=obj.name, reason='Short/scalp hair has no loose tail.'))
                    continue
                chains, data = _chains(obj, rig, smap, parent, len(state['chains']) + len(fresh))
                if not chains:
                    skipped.append(dict(object=obj.name, reason='No sufficiently long loose hair region.'))
                    continue
                fresh.extend(chains)
                geometry.append((obj, chains, data))
            if fresh:
                _install(rig, fresh, geometry)
                state['chains'].extend(fresh)
                state['meshes'].update({obj.name: len(obj.data.vertices) for obj, _, _ in geometry})
                state['colliders'] = _colliders(rig, smap, parent, state['chains'])
                rig[_STATE] = json.dumps(state)
            if not candidates:
                skipped.append(dict(part='hair', reason='No skinned mesh with a hair name/group hint.'))
        chains = state['chains'] if 'hair' in parts else []
        names = [n for ch in chains for n in ch['bones']]
        _clear_keys(rig, names, f0, f1, neutral=clear)
        measured = {}
        if names and not clear:
            samples = _sample(rig, chains, state['colliders'], f0, f1)
            measured = _bake(rig, chains, state['colliders'], samples, f0, f1,
                             stiffness, damping, gravity, wind)
            for fc in _fcurves(rig.animation_data.action):
                if any(fc.data_path == rig.pose.bones[n].path_from_id('rotation_quaternion') for n in names):
                    for key in fc.keyframe_points:
                        if f0 <= key.co.x <= f1:
                            key.interpolation = 'LINEAR'
        return dict(character=rig.name, frames=[f0, f1], chains=len(chains), bones=names,
                    meshes=sorted(state['meshes']) if chains else [], cleared=bool(clear),
                    skipped=skipped, **measured, bake_seconds=round(time.perf_counter() - started, 4))
    finally:
        sc.frame_set(saved)
        bpy.context.view_layer.update()
