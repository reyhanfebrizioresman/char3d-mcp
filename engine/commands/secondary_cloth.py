"""Geometry-derived garment rings for secondary_motion (no external physics state)."""
import math

import bpy
import numpy as np
from mathutils import Quaternion, Vector


def _segment_distances(points, a, b):
    a, b = np.asarray(a), np.asarray(b)
    d = b - a
    t = np.clip((points - a) @ d / max(float(d @ d), 1e-12), 0, 1)
    return np.linalg.norm(points - a - t[:, None] * d, axis=1), t


def leg_colliders(rig, smap):
    """Fit conservative capsules inside the actual rest body, excluding helpers."""
    from .secondary import _basis
    basis = _basis(rig, smap)
    body = next((o for o in rig.children_recursive if o.type == 'MESH'
                 and o.get('c3d_kind') == 'humanoid'), None)
    points = None
    if body:
        mode = rig.data.pose_position
        # Evaluate shape keys and the helper mask, but reveal body surfaces
        # hidden by a garment's delete mask. Posed or helper vertices misfit radii.
        masks = [(m, m.show_viewport) for m in body.modifiers
                 if m.type == 'MASK' and m.name.startswith('Delete.')]
        try:
            rig.data.pose_position = 'REST'
            for modifier, _ in masks:
                modifier.show_viewport = False
            bpy.context.view_layer.update()
            evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            try:
                co = np.empty(len(mesh.vertices) * 3)
                mesh.vertices.foreach_get('co', co)
                mat = np.asarray(basis.transposed().to_4x4() @
                                 rig.matrix_world.inverted() @ evaluated.matrix_world)
                points = co.reshape(-1, 3) @ mat[:3, :3].T + mat[:3, 3]
            finally:
                evaluated.to_mesh_clear()
        finally:
            rig.data.pose_position = mode
            for modifier, visible in masks:
                modifier.show_viewport = visible
            bpy.context.view_layer.update()
    specs = []
    for limb in ('thigh', 'shin'):
        for side in 'LR':
            semantic = f'{limb}.{side}'
            # Rigify control bones are not exporter-safe attachment/collider frames.
            name = next((n for n in (f'DEF-{limb}.{side}', smap.get(semantic))
                         if n in rig.data.bones and rig.data.bones[n].use_deform), smap[semantic])
            bone = rig.data.bones[name]
            a, b = basis.transposed() @ bone.head_local, basis.transposed() @ bone.tail_local
            radius = bone.length * (.23 if limb == 'thigh' else .14)
            if points is not None:
                dist, t = _segment_distances(points, a, b)
                other = rig.data.bones[smap[f'{limb}.{"R" if side == "L" else "L"}']]
                od, _ = _segment_distances(points, basis.transposed() @ other.head_local,
                                           basis.transposed() @ other.tail_local)
                use = (t > .2) & (t < .8) & (dist < od) & (dist < bone.length * .42)
                if use.sum() > 10:
                    radius = float(np.quantile(dist[use], .65)) * .94
            specs.append(dict(name=semantic, bone=name, a=list(bone.head_local),
                              b=list(bone.tail_local), radius=max(.01, radius), part='clothes'))
    return specs


def chains_for_garment(obj, rig, smap, colliders, index):
    from .secondary import _basis, _geometry
    basis = _basis(rig, smap)
    pts = _geometry(obj, rig, basis)
    hip = sum((basis.transposed() @ rig.data.bones[smap[f'thigh.{s}']].head_local
               for s in 'LR'), Vector()) / 2
    height = rig.data.bones[smap['head']].length * 7.5
    root_z = hip.z + height * .065
    if len(pts) and float(pts[:, 2].max()) < hip.z - height * .12:
        # Shoes, boots and socks sit entirely on the leg/foot: their toes clear the
        # leg capsules, but they must keep following the foot bones.
        return [], None, 'Footwear or lower-leg item: no waist attachment.'
    below = pts[:, 2] < hip.z - height * .045
    if below.sum() < 16:
        return [], None, 'No hem below the hips (tight shirt, accessory or short garment).'
    gap = np.full(len(pts), np.inf)
    for c in colliders:
        a, b = (basis.transposed() @ Vector(c[k]) for k in ('a', 'b'))
        dist, _ = _segment_distances(pts, a, b)
        gap = np.minimum(gap, dist - c['radius'])
    threshold = height * .026
    loose = below & (gap > threshold)
    # A few crotch/ankle outliers on trousers are insufficient evidence of a hem.
    if loose.sum() < 16 or loose.sum() / below.sum() < .22:
        return [], None, f'Tight fit: no broad loose hem beyond {threshold:.3f} m leg clearance.'
    end_z = float(np.quantile(pts[loose, 2], .02))
    if root_z - end_z < height * .13:
        return [], None, 'Loose region is too short for a garment chain.'
    # Keep only connected mesh components containing loose evidence. A combined
    # suit's shirt and trousers do not acquire weights from an unrelated skirt.
    adjacent = [[] for _ in pts]
    for edge in obj.data.edges:
        a, b = edge.vertices
        adjacent[a].append(b)
        adjacent[b].append(a)
    mask = np.zeros(len(pts), dtype=bool)
    allowed = pts[:, 2] < root_z
    todo = list(np.flatnonzero(loose))
    mask[todo] = True
    while todo:
        for j in adjacent[todo.pop()]:
            if allowed[j] and not mask[j]:
                mask[j] = True
                todo.append(j)
    angles = np.arctan2(pts[:, 1] - hip.y, pts[:, 0] - hip.x)
    parent = next((n for n in ('DEF-spine', smap['hips'])
                   if n in rig.data.bones and rig.data.bones[n].use_deform), smap['hips'])
    chains = []
    for k in range(12):
        angle = -math.pi + k * math.tau / 12
        da = np.abs(np.arctan2(np.sin(angles - angle), np.cos(angles - angle)))
        sector = pts[mask & (da < math.pi / 10)]
        if len(sector) < 6:
            continue  # Open coats need not have geometry around the whole ring.
        low = float(np.quantile(sector[:, 2], .02))
        if root_z - low < height * .13:
            continue
        nodes = []
        for z in np.linspace(root_z, low, 5):
            nearest = sector[np.argsort(abs(sector[:, 2] - z))[:max(3, len(sector) // 12)]]
            xy = np.median(nearest[:, :2], axis=0)
            nodes.append(list(basis @ Vector((float(xy[0]), float(xy[1]), float(z)))))
        chains.append(dict(bones=[f'cloth_{index + len(chains):02d}_{j:02d}' for j in range(4)],
                           points=nodes, parent=parent, mesh=obj.name, part='clothes',
                           radius=height * .004, center=list(np.mean(sector[:, :2], axis=0)),
                           root_z=root_z, end_z=low, angle=angle))
    if len(chains) < 3:
        return [], None, 'Insufficient angular coverage for a loose garment ring.'
    return chains, (pts, mask, basis), None


def constrain_ring(points, targets, chains):
    """Keep adjacent tips in angular order and limit excess separation.

    An open coat is not joined across its opening. Corrections are followed by
    length/capsule projection by the shared solver, so collision takes priority.
    """
    for mesh in {ch['mesh'] for ch in chains if ch.get('part') == 'clothes'}:
        ring = [i for i, ch in enumerate(chains) if ch['mesh'] == mesh]
        for a, b in zip(ring, ring[1:] + ring[:1]):
            if (chains[b]['angle'] - chains[a]['angle']) % math.tau > math.pi / 3:
                continue
            rest = targets[b][-1] - targets[a][-1]
            d = points[b][-1] - points[a][-1]
            if rest.length < 1e-8:
                continue
            axis = rest.normalized()
            signed = d.dot(axis)
            correction = axis * max(0., rest.length * .35 - signed)
            if d.length > rest.length * 1.35:
                correction -= d.normalized() * (d.length - rest.length * 1.35)
            points[a][-1] -= correction * .5
            points[b][-1] += correction * .5


def _outward(point, normal, colliders, radius):
    """Farthest ray/capsule hit keeps the leg inside the garment's radial shell.

    A two-sided point collision alone lets a fast thigh step through a skirt.
    Exact finite cylinder + endpoint sphere intersections also handle long shins.
    """
    shift = 0.
    for a, b, r in colliders:
        r += radius
        axis = b - a
        length = axis.length
        if length < 1e-8:
            continue
        axis /= length
        rel = point - a
        nd, rd = normal.dot(axis), rel.dot(axis)
        v, w = normal - nd * axis, rel - rd * axis
        aa, bb, cc = v.dot(v), v.dot(w), w.dot(w) - r * r
        disc = bb * bb - aa * cc
        if aa > 1e-9 and disc >= 0:
            t = (-bb + math.sqrt(disc)) / aa
            if 0 <= rd + t * nd <= length:
                shift = max(shift, t)
        for center in (a, b):
            delta = point - center
            proj = delta.dot(normal)
            disc = proj * proj - delta.length_squared + r * r
            if disc >= 0:
                shift = max(shift, -proj + math.sqrt(disc))
    return point + normal * max(0., shift)


def constrain_cloth(points, targets, lengths, colliders, radius, normal):
    """Shared inextensible spring projection plus one-sided garment enclosure."""
    from .secondary import _constrain
    for _ in range(3):
        points[0] = targets[0].copy()
        for j, length in enumerate(lengths):
            p = _outward(points[j + 1], normal, colliders, radius + .025)
            d = p - points[j]
            if d.length > 1e-9:
                points[j + 1] = points[j] + d.normalized() * length
        _constrain(points, targets, lengths, colliders, radius + .002)


def drape_targets(strands, cols, colliders, chains, mw, parents, rig):
    """An elastic, collision-safe drape is the equilibrium for tip-lag metrics."""
    from .secondary import _basis
    from .anim import semantic_map
    basis = _basis(rig, semantic_map(rig)) if any(c.get("part") == "clothes" for c in chains) else None
    own = [col for spec, col in zip(colliders, cols) if spec.get('part') == 'clothes']
    thighs = [col for spec, col in zip(colliders, cols)
              if spec.get('part') == 'clothes' and spec['name'].startswith('thigh')]
    normals = []
    for k, ch in enumerate(chains):
        if ch.get('part') != 'clothes':
            normals.append(None)
            continue
        attach = mw @ parents[ch['parent']] @ rig.data.bones[ch['parent']].matrix_local.inverted()
        # Polar direction in the character's anatomical frame, transformed by hips.
        normal = (attach.to_3x3() @ (basis @ Vector((math.cos(ch['angle']), math.sin(ch['angle']), 0)))).normalized()
        down = (attach.to_3x3() @ -basis.col[2]).normalized()
        directions = [(b - a).normalized() for a, b, _ in thighs]
        average = sum(directions, Vector()).normalized()
        direction = max(directions, key=lambda d: d.dot(normal))
        bend = down.rotation_difference(direction)
        # Follow the leg facing this sector so a stride stays enclosed. Horizontal
        # thighs lay the front/side over the lap while the back remains hanging.
        sitting = max(0., min(1., (1. - average.dot(down) - .20) / .65))
        front = (1. - math.sin(ch['angle'])) * .5
        q = Quaternion().slerp(bend, .85 * (1. - sitting) + sitting * front)
        root = strands[k][0]
        strands[k] = [root + q @ (p - root) for p in strands[k]]
        if sitting:
            normal = (normal + Vector((0, 0, sitting * front * 1.5))).normalized()
        lengths = [(b - a).length for a, b in zip(strands[k], strands[k][1:])]
        targets = [p.copy() for p in strands[k]]
        constrain_cloth(strands[k], targets, lengths, own,
                        ch['radius'] * max(mw.to_scale()), normal)
        normals.append(normal)
    return normals


def constrain_scene(points, targets, lengths, field, radius, iterations=3):
    """Project elastic chain samples against static BVHs and posed peer bodies.

    Segment lengths and the waist attachment remain fixed. Report remaining
    penetration when these constraints are incompatible with seat geometry.
    """
    import numpy as np
    for _ in range(iterations):
        for j, length in enumerate(lengths):
            a, b = points[j], points[j+1]
            samples = [np.array(a.lerp(b, t)) for t in (.35, .7, 1.)]
            hits = field.hits(samples, [radius]*3, ['0', '1', '2'])
            if hits:
                depth, normal, index, _, _ = hits[0]
                t = (.35, .7, 1.)[int(index)]
                b = b+Vector(normal)*min(depth/t, length*.35)
                direction = b-a
                if direction.length > 1e-9:
                    points[j+1] = a+direction.normalized()*length
    samples = [np.array(a.lerp(b, t)) for a,b in zip(points,points[1:]) for t in (.35,.7,1.)]
    hits = field.hits(samples, [radius]*len(samples), ['cloth']*len(samples))
    return max((h[4] for h in hits), default=0.)
