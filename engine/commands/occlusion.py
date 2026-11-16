"""Shot-local visibility probes. No scene mutations; evaluated BVHs are cached per shot."""
import math
import time

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .anim import semantic_map
from .util import is_helper, scene_bounds


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


class VisibilityProbe:
    def __init__(self, targets, shot, height, angle_limits=None, action_line=None):
        self.shot, self.height = shot, height
        self.angle_limits = angle_limits
        self.action_line = action_line
        self.groups = {}
        self.rigs = {_rig(o) for o in targets} - {None}
        ignored = set(targets) | self.rigs
        for obj in list(ignored):
            ignored.update(obj.children_recursive)
        for obj in bpy.context.scene.objects:
            if _rig(obj) in self.rigs:
                ignored.add(obj)
        for obj in targets:
            r = _rig(obj)
            self.groups.setdefault(r or obj, []).append(obj)
        self.ignored = ignored
        self.cache, self.samples = {}, []
        self.seconds = 0.0

    def capture(self, frame, position, aim):
        started = time.perf_counter()
        dg = bpy.context.evaluated_depsgraph_get()
        collections = set(_render_collections(bpy.context.scene.collection))
        meshes = []
        for obj in bpy.context.scene.objects:
            if obj.type != "MESH" or obj in self.ignored or is_helper(obj):
                continue
            chain = list(_ancestors(obj))
            if (obj.get("c3d_role") == "ground" or obj.hide_render or not obj.visible_get() or
                    any(o.hide_render for o in chain) or
                    not any(c in collections for c in obj.users_collection)):
                continue
            held = next((o for o in chain if o.get("c3d_hold_character")), None)
            if (held and held.get("c3d_hold_character") in {r.name for r in self.rigs} and
                    held.get("c3d_hold_start", 0) <= frame <= held.get("c3d_hold_release", math.inf)):
                continue
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
                meshes.append(mesh)
        groups = [_points(parts, root if root.type == "ARMATURE" else None, self.height, dg)
                  for root, parts in self.groups.items()]
        line = []
        for name in (self.action_line or [])[:2]:
            rig = bpy.data.objects[name]
            ev = rig.evaluated_get(dg)
            hips = semantic_map(rig).get("hips")
            line.append(ev.matrix_world @ ev.pose.bones[hips].head if hips else ev.matrix_world.translation.copy())
        self.samples.append((frame, position.copy(), aim.copy(), meshes, groups, line))
        self.seconds += time.perf_counter() - started

    def measure(self, adjustment=None):
        worst, body_worst, eye_blocked, safe = 0.0, 0.0, False, True
        for _, pos, aim, meshes, groups, line in self.samples:
            original = pos
            if adjustment:
                pos, aim = adjusted(pos, aim, self.height, adjustment)
                az = math.degrees(math.atan2((pos - aim).x, -(pos - aim).y))
                if self.angle_limits and not self.angle_limits[0] <= az <= self.angle_limits[1]:
                    safe = False
                if len(line) == 2:
                    axis = line[1] - line[0]
                    if axis.cross(original - line[0]).z * axis.cross(pos - line[0]).z < 0:
                        safe = False
                if any(m.wall and (m.hit(aim, pos) or m.hit(original, pos))
                       for m in meshes):
                    safe = False
                # The subject is excluded from sight rays, but the camera must
                # remain outside its geometry too. Bounds are conservative here.
                for _, _, body in groups:
                    if body and all(min(p[i] for p in body) - 0.025 <= pos[i] <=
                                    max(p[i] for p in body) + 0.025 for i in range(3)):
                        safe = False
            inside = any(m.inside(pos) for m in meshes)
            safe &= not inside
            for face, eyes, body in groups:
                blocked = lambda p: inside or any(m.hit(pos, p) for m in meshes)
                frac = sum(blocked(p) for p in face) / max(1, len(face))
                worst = max(worst, frac)
                eye_blocked |= any(blocked(p) for p in eyes)
                points = body if self.shot in {"full", "wide", "extreme_wide", "medium_full"} else body[-2:]
                body_worst = max(body_worst, sum(blocked(p) for p in points) / max(1, len(points)))
        return worst, eye_blocked, body_worst, safe

    def resolve(self, enabled, elevation):
        started = time.perf_counter()
        before = self.measure()
        close = self.shot in {"close_up", "extreme_close_up"}
        wide = self.shot in {"full", "wide", "extreme_wide", "medium_full"}
        blocked = before[0] > 0.15 or (close and before[1]) or (wide and before[2] > 0.4)
        chosen, after = None, before
        if enabled and blocked:
            for candidate in _candidates(elevation):
                value = self.measure(candidate)
                if value[3] and value[0] <= 0.05 and not (close and value[1]) and (not wide or value[2] <= 0.4):
                    chosen, after = candidate, value
                    break
        report = {"before": round(before[0], 4), "after": round(after[0], 4),
                  "adjusted": [] if chosen is None else [
                      f"{key}={value:g}" for key, value in chosen.items() if value != (1 if key == "distance" else 0)],
                  "body_before": round(before[2], 4), "body_after": round(after[2], 4),
                  "sample_frames": [s[0] for s in self.samples]}
        if enabled and blocked and chosen is None:
            report["warning"] = "No safe camera adjustment clears the subject; original camera retained."
        self.seconds += time.perf_counter() - started
        report["seconds"] = round(self.seconds, 4)
        return chosen, report


def _candidates(elevation):
    lift = max(0, 20 - float(elevation))
    for el in (5, 10, 15, 20):
        if el <= lift:
            yield {"elevation": el}
    for az in (10, -10, 20, -20, 30, -30):
        yield {"angle": az}
        if lift:
            yield {"angle": az, "elevation": lift}
    for distance in (0.85, 0.7):
        yield {"distance": distance, "elevation": lift}
    for up in (0.04, 0.08):
        yield {"vertical": up, "elevation": lift}


def adjusted(pos, aim, height, adjustment):
    delta = pos - aim
    distance = delta.length * adjustment.get("distance", 1)
    az = math.atan2(delta.x, -delta.y) + math.radians(adjustment.get("angle", 0))
    el = math.atan2(delta.z, math.hypot(delta.x, delta.y)) + math.radians(adjustment.get("elevation", 0))
    aim = aim + Vector((0, 0, height * adjustment.get("vertical", 0)))
    pos = aim + Vector((math.sin(az)*math.cos(el), -math.cos(az)*math.cos(el), math.sin(el))) * distance
    return pos, aim
