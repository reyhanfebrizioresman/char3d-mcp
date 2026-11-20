"""Shot-local visibility probes. No scene mutations; evaluated BVHs are cached per shot."""
import math
import time

import bpy
import numpy as np
from mathutils import Euler, Vector
from mathutils.bvhtree import BVHTree

from .anim import semantic_map
from .gaze import head_frame, face_angle
from .util import is_helper, scene_bounds
from ..ray_bounds import intersects


def sample_frames(start, end, fps):
    # Sample static cameras too: the subject/occluders can still move.
    return sorted({start, (start + end) // 2, end,
                   *range(start, end + 1, max(1, round(fps / 2)))})


def _ancestors(obj):
    while obj:
        yield obj
        obj = obj.parent


def _rig(obj):
    return next((o for o in _ancestors(obj) if o.type == "ARMATURE"), None) or next(
        (m.object for m in obj.modifiers if m.type == "ARMATURE" and m.object), None)


def _prop(obj):
    return any(o.get('c3d_prop_kind') or o.get('c3d_hold_character') for o in _ancestors(obj))


def _render_collections(collection):
    if not collection.hide_render:
        yield collection
        for child in collection.children:
            yield from _render_collections(child)


def _points(parts, rig, height, depsgraph):
    """Face grid, explicit eyes, head/chest and body bounds in evaluated world space.

    Head offsets use the rest-to-pose transform, so seated/turned/nodding faces are
    sampled on the head rather than at a fraction of the crouched body's bounds.
    Unrigged subjects use the top of their bounds as a conservative fallback.
    """
    lo, hi = scene_bounds(parts)
    if lo is None:
        return [], [], []
    center = (lo + hi) / 2
    body = [Vector((x, y, z)) for x in (lo.x, hi.x)
            for y in (lo.y, hi.y) for z in (lo.z, hi.z)] + [center]
    smap = semantic_map(rig) if rig else {}
    if "head" in smap:
        ev = rig.evaluated_get(depsgraph)
        pb = ev.pose.bones[smap["head"]]
        rest = rig.data.bones[smap["head"]]
        deform = ev.matrix_world @ pb.matrix @ rest.matrix_local.inverted()
        h = max(0.10, min(height * 0.17, rest.length * rig.matrix_world.to_scale().x))
        scale = max(abs(rig.matrix_world.to_scale().x), 1e-6)
        def point(x, z):
            return deform @ (rest.head_local + Vector((x, -h * 0.40, z)) / scale)
        face = [point(x * h, z * h) for z in (0.18, 0.45, 0.72) for x in (-0.25, 0, 0.25)]
        eyes = [point(x * h, 0.65 * h) for x in (-0.18, 0.18)]
        body += [ev.matrix_world @ pb.tail]
        if "chest" in smap:
            body += [ev.matrix_world @ ev.pose.bones[smap["chest"]].tail]
    else:
        h = (hi.z - lo.z) * 0.13
        face = [Vector((center.x + x * h, lo.y, hi.z - z * h))
                for z in (0.25, 0.6, 0.95) for x in (-0.25, 0, 0.25)]
        eyes = [Vector((center.x + x * h, lo.y, hi.z - 0.4 * h)) for x in (-0.18, 0.18)]
    return face + eyes, eyes, body


class _Mesh:
    def __init__(self, obj, depsgraph, height):
        self.name = obj.name
        self.scenery = _rig(obj) is None or _prop(obj)
        ev = obj.evaluated_get(depsgraph)
        self.tree = BVHTree.FromObject(obj, depsgraph, deform=True, cage=False)
        self.inverse = ev.matrix_world.inverted_safe()
        corners = [Vector(c) for c in ev.bound_box]
        self.lo = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
        self.hi = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
        dims = ev.dimensions
        self.wall = (any(s in obj.name.lower() for s in ("wall", "backdrop")) or
                     (dims.z > height and max(dims.x, dims.y) > height and
                      min(dims.x, dims.y) < 0.3))

    def hit(self, origin, target):
        a, b = self.inverse @ origin, self.inverse @ target
        d = b - a
        length = d.length
        return length > 1e-5 and self.tree.ray_cast(a, d / length, max(0, length - 0.005))[0] is not None

    def hits(self, origin, targets):
        """Reject local AABB misses in bulk; possible hits still use the exact BVH."""
        inverse=np.asarray(self.inverse,dtype=float)
        local=targets@inverse[:3,:3].T+inverse[:3,3]
        mask=intersects(self.inverse@origin,local,self.lo,self.hi)
        result=np.zeros(len(targets),dtype=bool)
        for i in np.flatnonzero(mask):
            result[i]=self.hit(origin,Vector(targets[i]))
        return result

    def inside(self, point):
        p = self.inverse @ point
        if any(p[i] < self.lo[i] - 0.01 or p[i] > self.hi[i] + 0.01 for i in range(3)):
            return False
        nearest = self.tree.find_nearest(p)
        if nearest[0] is not None and nearest[3] < 0.025:
            return True  # leave room for the near clip plane
        # Odd crossings in BOTH directions: closed volumes, independent of normals.
        # An open plane/backdrop must not classify its entire half-space as solid.
        direction = Vector((0.371, 0.529, 0.763)).normalized()
        for sign in (1, -1):
            origin, count = p.copy(), 0
            for _ in range(64):
                hit = self.tree.ray_cast(origin, direction * sign)
                if hit[0] is None:
                    break
                count += 1
                origin = hit[0] + direction * (sign * 1e-4)
            if count % 2 == 0:
                return False
        return True


# All screen coordinates are normalized (0..1), measured from the top-left.
def _project(position, rotation, lens, points, sensor):
    inverse = rotation.to_matrix().transposed()
    return [Vector((0.5 + lens / sensor[0] * q.x / max(1e-6, -q.z),
                    0.5 - lens / sensor[1] * q.y / max(1e-6, -q.z), -q.z))
            for p in points for q in [inverse @ (p - position)]]


def _landmarks(group):
    face, eyes, body = group
    if not eyes:
        return []
    eye = sum(eyes, Vector()) / len(eyes)
    # Rigged bounds finish with posed head-top/chest landmarks. The fallback is
    # deliberately based on bounds, for non-humanoid props and imported meshes.
    top = body[-2] if len(body) > 9 else max(body, key=lambda p: p.z)
    chest = body[-1] if len(body) > 9 else eye + Vector((0, 0, -(top.z-eye.z)*4))
    return [eye, top, chest]


def framing_targets(pos, rot, mm, groups, sensor, shot):
    targets = [_project(pos, rot, mm, _landmarks(g), sensor) for g in groups]
    # Bounds-based framing of a seated body can put its eyes against the top edge.
    # Define the unobstructed design once, retaining its scale and relative
    # head/chest positions, but place the eye line in the upper third.
    if len(targets) == 1 and shot in {"close_up", "medium_close", "medium"}:
        eye = targets[0][0].y
        if not 0.25 <= eye <= 0.45:
            for p in targets[0]:
                p.y += 1/3 - eye
    return targets


def fit_frame(pos, rot, mm, groups, sensor, targets):
    """Fit yaw, pitch and focal length to original eye/head/chest projections.

    A tiny finite-difference least-squares solve keeps the original roll/shake.
    No camera datablock is mutated, so scoring and baking use the exact same fit.
    """
    points = [p for g in groups for p in _landmarks(g)]
    goal = np.array([[p.x, p.y] for group in targets for p in group])
    if not points:
        return rot.copy(), mm
    weight = np.ones_like(goal)
    weight[::3] = 4  # keep the eye line/looking room while fitting subject scale
    def evaluate(x):
        rotation = (rot.to_quaternion() @ Euler((x[0], x[1], 0)).to_quaternion()).to_euler()
        lens = max(8.0, min(300.0, mm * math.exp(float(x[2]))))
        screen = np.array([[p.x, p.y] for p in _project(pos, rotation, lens, points, sensor)])
        return ((screen-goal)*weight).ravel(), rotation, lens
    x = np.zeros(3)
    for _ in range(7):
        residual, rotation, lens = evaluate(x)
        if np.max(np.abs(residual)) < 1e-4:
            break
        jacobian = np.column_stack([(evaluate(x + np.eye(3)[i]*0.001)[0]-residual)/0.001
                                    for i in range(3)])
        delta = np.linalg.lstsq(jacobian, -residual, rcond=None)[0]
        x += np.clip(delta, -0.25, 0.25)
    _, rotation, lens = evaluate(x)
    return rotation, lens


def frame_coverage(pos, rot, lens, sensor, meshes, groups):
    """24x14 camera rays, stopping at the nearest subject's eye-depth plane."""
    forward = rot.to_matrix() @ Vector((0, 0, -1))
    depth = min((p-pos).dot(forward) for g in groups for p in _landmarks(g)[:1])
    if depth <= 0:
        return 1.0
    basis = rot.to_matrix()
    targets=[]
    for y in range(14):
        for x in range(24):
            direction=Vector((((x+0.5)/24-0.5)*sensor[0]/lens,
                              (0.5-(y+0.5)/14)*sensor[1]/lens,-1))
            targets.append(pos+basis@direction*depth)
    targets=np.asarray(targets)
    covered=np.zeros(len(targets),dtype=bool)
    for mesh in meshes:
        remaining=np.flatnonzero(~covered)
        if not len(remaining):break
        covered[remaining]=mesh.hits(pos,targets[remaining])
    return float(np.mean(covered))


def foreground_coverage(pos, rot, lens, sensor, meshes, groups):
    """64x36 partner silhouette, stopping at the subject eye plane.

    Width is the span of occupied columns, clipped to the frame; area is the
    occupied pixel fraction. Mesh rays include head, hair, neck and shoulders.
    """
    forward = rot.to_matrix() @ Vector((0, 0, -1))
    depth = min((p-pos).dot(forward) for g in groups for p in _landmarks(g)[:1])
    if depth <= 0 or not meshes:
        return dict(width=0., area=0., side='none')
    basis = rot.to_matrix()
    points = np.asarray([pos+basis@Vector((((x+.5)/64-.5)*sensor[0]/lens,
                         (.5-(y+.5)/36)*sensor[1]/lens,-1))*depth
                         for y in range(36) for x in range(64)])
    mask = np.zeros(len(points), dtype=bool)
    for mesh in meshes:
        remaining = np.flatnonzero(~mask)
        if len(remaining):
            mask[remaining] |= mesh.hits(pos, points[remaining])
    mask = mask.reshape(36,64)
    columns = np.flatnonzero(mask.any(axis=0))
    width = (columns[-1]-columns[0]+1)/64 if len(columns) else 0.
    return dict(width=float(width), area=float(mask.mean()),
                side=('left' if float(np.mean(columns)) < 32 else 'right') if len(columns) else 'none')


class VisibilityProbe:
    def __init__(self, targets, shot, height, angle_limits=None, action_line=None, face_limit=75.0, foreground=None):
        self.shot, self.height = shot, height
        self.angle_limits = angle_limits
        self.action_line = action_line
        self.face_limit = face_limit
        self.foreground = foreground
        self.groups = {}
        self.rigs = {_rig(o) for o in targets} - {None}
        ignored = set(targets) | self.rigs
        for obj in list(ignored):
            ignored.update(o for o in obj.children_recursive if not _prop(o))
        for obj in bpy.context.scene.objects:
            if _rig(obj) in self.rigs and not _prop(obj):
                ignored.add(obj)
        for obj in targets:
            r = _rig(obj)
            self.groups.setdefault(r or obj, []).append(obj)
        self.ignored = ignored
        self.cache, self.samples = {}, []
        self.faces = {}
        self.foreground_faces = {}
        self.seconds = 0.0
        aspect = bpy.context.scene.render.resolution_y / bpy.context.scene.render.resolution_x
        self.sensor = (36 * max(1, aspect), 36 * min(1, aspect))
        from .face_geometry import FaceGeometry
        self.geometry = {r:FaceGeometry(r,height) for r in self.rigs}

    def points(self):
        dg = bpy.context.evaluated_depsgraph_get()
        groups = [_points(parts, root if root.type == "ARMATURE" else None, self.height, dg)
                  for root, parts in self.groups.items()]
        for (root, _), group in zip(self.groups.items(), groups):
            geometry = self.geometry.get(root)
            marks = geometry.points() if geometry else None
            if marks:
                group[0][:] = marks['face']
                group[1][:] = marks['eyes']
                if len(group[2])>9:
                    group[2][-2] = marks['crown']
        return groups

    def capture(self, frame, position, aim, rotation=None, lens=50):
        started = time.perf_counter()
        dg = bpy.context.evaluated_depsgraph_get()
        collections = set(_render_collections(bpy.context.scene.collection))
        meshes, solids = [], []
        for obj in bpy.context.scene.objects:
            if (obj.type != "MESH" or obj in self.ignored or is_helper(obj) or obj.get("c3d_weather")
                    or obj.get("c3d_nature_occludes") is False):
                continue
            chain = list(_ancestors(obj))
            if (obj.hide_render or
                    any(o.hide_render for o in chain) or
                    not any(c in collections for c in obj.users_collection)):
                continue
            ignored_sight = obj.get("c3d_role") == "ground"
            dynamic = (any(o.animation_data or o.constraints for o in chain) or
                       any(m.type not in {"BEVEL", "SUBSURF", "WEIGHTED_NORMAL", "SOLIDIFY",
                                          "TRIANGULATE", "MIRROR"} for m in obj.modifiers) or
                       bool(obj.data.shape_keys))
            mesh = self.cache.get(obj)
            if mesh is None or dynamic:
                mesh = _Mesh(obj, dg, self.height)
                if not dynamic:
                    self.cache[obj] = mesh
            if mesh.tree is not None:
                mesh.foreground = bool(self.foreground and _rig(obj) and _rig(obj).name == self.foreground)
                solids.append(mesh)
                if not ignored_sight:
                    meshes.append(mesh)
        groups = self.points()
        self.faces[frame] = [head_frame(root) if root.type == "ARMATURE" else None
                             for root in self.groups]
        if self.foreground:
            self.foreground_faces[frame] = head_frame(bpy.data.objects[self.foreground])
        rotation = rotation or (aim-position).to_track_quat("-Z", "Y").to_euler()
        targets = framing_targets(position, rotation, lens, groups, self.sensor, self.shot)
        line = []
        for name in (self.action_line or [])[:2]:
            rig = bpy.data.objects[name]
            ev = rig.evaluated_get(dg)
            head = semantic_map(rig).get("head")
            line.append(head_frame(rig)[0] if head else ev.matrix_world.translation.copy())
        self.samples.append((frame, position.copy(), aim.copy(), meshes, groups, line, rotation.copy(), lens, targets, solids))
        self.seconds += time.perf_counter() - started

    def measure(self, adjustment=None):
        worst, body_worst, eye_blocked, safe = 0.0, 0.0, False, True
        coverage, composed, screens, sizes = 0.0, True, [], []
        angle = 0.0
        foreground = []
        scenery, blockers = 0., set()
        for frame, pos, aim, meshes, groups, line, rot, mm, targets, solids in self.samples:
            original = pos
            if adjustment is not None:
                pos, aim = adjusted(pos, aim, self.height, adjustment)
                rot, mm = fit_frame(pos, rot, mm, groups, self.sensor, targets)
                az = math.degrees(math.atan2((pos - aim).x, -(pos - aim).y))
                if self.angle_limits and not self.angle_limits[0] <= az <= self.angle_limits[1]:
                    safe = False
                if len(line) == 2:
                    axis = line[1] - line[0]
                    if axis.cross(original - line[0]).z * axis.cross(pos - line[0]).z < 0:
                        safe = False
                if any(m.wall and (m.hit(aim, pos) or m.hit(original, pos)) for m in meshes):
                    safe = False
                for _, _, body in groups:
                    if body and all(min(p[i] for p in body) - 0.025 <= pos[i] <=
                                    max(p[i] for p in body) + 0.025 for i in range(3)):
                        safe = False
            inside = any(m.inside(pos) for m in solids)
            safe &= not inside
            if self.foreground:
                value = foreground_coverage(pos, rot, mm, self.sensor,
                    [m for m in meshes if m.foreground], groups)
                value.update(frame=frame,head_angle=face_angle(*self.foreground_faces[frame],pos))
                foreground.append(value)
            for face in self.faces[frame]:
                if face is not None:
                    angle = max(angle, face_angle(*face, pos))
            for group, target in zip(groups, targets):
                face, eyes, body = group
                blocked = lambda p: inside or any(m.hit(pos, p) for m in meshes)
                frac = sum(blocked(p) for p in face) / max(1, len(face))
                covered = np.zeros(len(face),dtype=bool)
                for mesh in meshes:
                    if mesh.scenery:
                        hits = mesh.hits(pos,np.asarray(face))
                        if hits.any():
                            blockers.add(mesh.name)
                            covered |= hits
                scenery = max(scenery,float(covered.mean()) if len(covered) else 0.)
                worst = max(worst, frac)
                eye_blocked |= any(blocked(p) for p in eyes)
                points = body if self.shot in {"full", "wide", "extreme_wide", "medium_full"} else body[-2:]
                body_worst = max(body_worst, sum(blocked(p) for p in points) / max(1, len(points)))
                screen = _project(pos, rot, mm, _landmarks(group), self.sensor)
                face_screen = _project(pos, rot, mm, face, self.sensor)
                if not screen:
                    continue
                scale = abs(screen[2].y-screen[1].y) / max(1e-5, abs(target[2].y-target[1].y))
                composed &= (all(0.01 <= p.x <= 0.99 and 0.01 <= p.y <= 0.99 and p.z > 0
                                 for p in face_screen) and
                             abs(screen[0].x-target[0].x) <= 0.04 and
                             abs(screen[0].y-target[0].y) <= 0.04 and
                             abs(screen[1].y-target[1].y) <= 0.04 and
                             0.85 <= scale <= 1.15)
                if len(groups) == 1 and self.shot in {"close_up", "medium_close", "medium"}:
                    composed &= 0.25 <= screen[0].y <= 0.45
                screens.append([round(screen[0].x, 4), round(screen[0].y, 4)])
                sizes.append(round(scale, 4))
            # Avoid spending grid rays on candidates that already fail visibility,
            # composition or collision checks. The original always gets a report.
            if adjustment is None or (safe and composed and worst <= 0.05 and angle <= self.face_limit):
                # Intended OTS foreground is exempt only from the area budget.
                # It still blocks face/eye rays and remains a camera collision solid.
                coverage = max(coverage, frame_coverage(pos, rot, mm, self.sensor,
                    [m for m in meshes if not m.foreground], groups))
            else:
                return dict(face=worst, eyes=eye_blocked, body=body_worst, safe=safe,
                            coverage=1.0, composed=False, screens=screens, sizes=sizes, face_angle=angle,
                            foreground=foreground,scenery_face=scenery,blockers=sorted(blockers))
        return dict(face=worst, eyes=eye_blocked, body=body_worst, safe=safe,
                    coverage=coverage, composed=composed, screens=screens, sizes=sizes, face_angle=angle,
                    foreground=foreground,scenery_face=scenery,blockers=sorted(blockers))

    def accepts(self, value):
        limit = 0.25 if self.shot in {"extreme_close_up", "close_up", "medium_close", "medium"} else 0.35
        return (value['safe'] and value['face'] <= 0.05 and not value.get('scenery_face') and value['face_angle'] <= self.face_limit and value['composed'] and
                not (self.shot in {"close_up", "extreme_close_up"} and value['eyes']) and
                all(.18 <= f['width'] <= .37 and f['head_angle'] >= 115 for f in value.get('foreground', [])) and
                value['coverage'] <= limit)

    def resolve(self, enabled, elevation, require_composition=False):
        started = time.perf_counter()
        before = self.measure()
        limit = 0.25 if self.shot in {"extreme_close_up", "close_up", "medium_close", "medium"} else 0.35
        # Preserve the exact keys of an unobstructed design, including intentional
        # pans/tilts and close crops. Composition constraints apply to corrections.
        blocked = (before['face'] > 0.05 or before.get('scenery_face',0)>0 or before['face_angle'] > self.face_limit or before['coverage'] > limit or
                   (self.shot in {"close_up", "extreme_close_up"} and before['eyes']) or
                   (require_composition and not self.accepts(before)))
        chosen, after = None, before
        if enabled and blocked:
            for candidate in _candidates(elevation):
                value = self.measure(candidate)
                if self.accepts(value):
                    chosen, after = candidate, value
                    break
            if chosen is None and before['face_angle'] > self.face_limit:
                for az in (60, -60, 90, -90, 120, -120, 150, -150, 180):
                    candidate = {"angle": az}
                    value = self.measure(candidate)
                    if self.accepts(value):
                        chosen, after = candidate, value
                        break
        report = {"before": round(before['face'], 4), "after": round(after['face'], 4),
                  "adjusted": [] if chosen is None else [
                      f"{key}={value:g}" for key, value in chosen.items()],
                  "body_before": round(before['body'], 4), "body_after": round(after['body'], 4),
                  "frame_coverage_before": round(before['coverage'], 4),
                  "frame_coverage_after": round(after['coverage'], 4),
                  "face_angle_before": round(before['face_angle'], 2),
                  "face_angle": round(after['face_angle'], 2),
                  "face_screen": after['screens'], "subject_scale": after['sizes'],
                  "shot_size": self.shot, "sample_frames": [s[0] for s in self.samples]}
        report.update(scenery_face_before=before.get('scenery_face',0),scenery_face_after=after.get('scenery_face',0),
                      blockers_before=before.get('blockers',[]),blockers_after=after.get('blockers',[]))
        if self.foreground:
            report['foreground'] = after['foreground']
        if enabled and blocked and chosen is None:
            report["warning"] = "No safe camera adjustment preserves composition; original camera retained."
        self.seconds += time.perf_counter() - started
        report["seconds"] = round(self.seconds, 4)
        return chosen, report


def _candidates(elevation):
    # Smallest physical change first within each preferred class. A pedestal
    # translates vertically (not around the low bounds-based focus of a seat).
    for up in (0.06, 0.12, 0.2, 0.3, 0.45, 0.6, 0.8):
        yield {"pedestal": up}
    lift = max(0, 20-float(elevation))
    angular = [{"angle": az, "pedestal": up} for az in (10, -10, 20, -20, 30, -30)
               for up in (0, 0.12, 0.3)]
    yield from sorted(angular, key=lambda c: abs(c['angle'])/30+c['pedestal'])
    # Include positions in front of the blocker, rather than only tiny dollies.
    closer = [{"distance": d, "pedestal": up} for d in (0.85, 0.7, 0.55, 0.4, 0.3, 0.2)
              for up in (0, 0.15, 0.3)]
    yield from sorted(closer, key=lambda c: 1-c['distance']+c['pedestal'])
    if lift:
        yield {"elevation": lift}


def adjusted(pos, aim, height, adjustment):
    delta = pos - aim
    distance = delta.length * adjustment.get("distance", 1)
    az = math.atan2(delta.x, -delta.y) + math.radians(adjustment.get("angle", 0))
    el = math.atan2(delta.z, math.hypot(delta.x, delta.y)) + math.radians(adjustment.get("elevation", 0))
    aim = aim + Vector((0, 0, height * adjustment.get("vertical", 0)))
    pos = aim + Vector((math.sin(az)*math.cos(el), -math.cos(az)*math.cos(el), math.sin(el))) * distance
    pos.z += height * adjustment.get("pedestal", 0)
    return pos, aim
