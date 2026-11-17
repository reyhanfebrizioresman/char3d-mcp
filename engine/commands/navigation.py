"""Static XY navigation snapshots. No scene mutation or animation baking here."""
import heapq
import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.geometry import convex_hull_2d

from . import anim
from .util import is_helper, obj_or_raise

ESCAPE_DISTANCE = 0.6  # m a start inside the clearance margin may step out
CELL = 0.05
CLEARANCE = 0.05


def validate_options(avoid, ignore):
    if avoid is not True and avoid is not False and avoid != "auto":
        raise ValueError('avoid must be "auto", True or False')
    if ignore is None:
        return set()
    if not isinstance(ignore, (list, tuple)) or any(not isinstance(n, str) for n in ignore):
        raise ValueError("ignore must be a list of object names (including descendants)")
    return {obj_or_raise(n) for n in ignore}


def _excluded(obj, rig, ignored, frame):
    node = obj
    while node:
        if node == rig or node in ignored:
            return True
        if (node.get("c3d_hold_character") == rig.name and
                node.get("c3d_hold_start", frame) <= frame <= node.get("c3d_hold_release", math.inf)):
            return True
        node = node.parent
    return any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers)


def body_radius(rig):
    """Shoulder/hip centers plus soft tissue; scale with the evaluated skeleton."""
    smap = anim.semantic_map(rig)
    mw = rig.matrix_world
    widths = [(mw @ rig.pose.bones[smap[f"{b}.L"]].head -
               mw @ rig.pose.bones[smap[f"{b}.R"]].head).length for b in ("upper_arm", "thigh")]
    height = (mw @ rig.data.bones[smap["head"]].tail_local).z - min(
        (mw @ rig.data.bones[smap[f"foot.{s}"]].head_local).z for s in "LR")
    return max(max(widths)/2 + abs(height)*0.035, abs(height)*0.14, 0.05)


def _distance(points, polygon):
    """Euclidean XY distance to a closed convex footprint (zero inside)."""
    points = np.asarray(points, dtype=float)
    if math.prod(points.shape[:-1])*len(polygon) <= 500000:
        # Most prop slices are tiny. Broadcast their edges in one operation
        # rather than allocating several numpy arrays per edge per prop.
        edge = np.roll(polygon, -1, axis=0)-polygon
        dx = points[..., None, 0]-polygon[:, 0]
        dy = points[..., None, 1]-polygon[:, 1]
        ex, ey = edge.T
        t = np.clip((dx*ex+dy*ey)/np.maximum(ex*ex+ey*ey, 1e-20), 0, 1)
        best = np.min((dx-t*ex)**2+(dy-t*ey)**2, axis=-1)
        inside = np.all(ex*dy-ey*dx >= -1e-9, axis=-1) if len(polygon) > 2 else False
        return np.where(inside, 0, np.sqrt(best))
    best = np.full(points.shape[:-1], np.inf)
    inside = np.ones(points.shape[:-1], dtype=bool) if len(polygon) > 2 else np.zeros(points.shape[:-1], bool)
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        edge = b-a
        delta = points-a
        t = np.clip(np.sum(delta*edge, axis=-1)/max(float(edge@edge), 1e-20), 0, 1)
        best = np.minimum(best, np.sum((delta-t[..., None]*edge)**2, axis=-1))
        inside &= edge[0]*delta[..., 1]-edge[1]*delta[..., 0] >= -1e-9
    return np.where(inside, 0, np.sqrt(best))


def footprints(rig, ignored, ground, frame):
    """Conservative convex slice per mesh, retaining separate furniture parts.

    Clip edges as well as vertices: a wall crossing the height slice can have all
    its vertices outside it. Evaluated meshes include deformation and modifiers.
    """
    out = []
    deps = bpy.context.evaluated_depsgraph_get()
    for obj in bpy.context.scene.objects:
        if (obj.type != "MESH" or obj.hide_render or not obj.visible_get() or is_helper(obj)
                or obj.get("char3d_walkable") or obj.get("c3d_role") in {"ground", "weather"}
                or obj.name == "c3d_ground" or _excluded(obj, rig, ignored, frame)):
            continue
        ev = obj.evaluated_get(deps)
        bounds = [ev.matrix_world @ Vector(c) for c in ev.bound_box]
        floors = [ground.sample(v.x, v.y)[0] for v in bounds] if ground.objects else [ground.floor]
        low, high = min(floors)+0.05, max(floors)+1.7
        if max(v.z for v in bounds) < low or min(v.z for v in bounds) > high:
            continue
        mesh = ev.to_mesh()
        try:
            coords = np.empty(len(mesh.vertices)*3)
            mesh.vertices.foreach_get("co", coords)
            coords = coords.reshape(-1, 3)
            mw = np.asarray(ev.matrix_world)
            coords = coords @ mw[:3, :3].T + mw[:3, 3]
            sliced = [coords[(coords[:, 2] >= low) & (coords[:, 2] <= high), :2]]
            indices = np.empty(len(mesh.edges)*2, dtype=np.int32)
            mesh.edges.foreach_get("vertices", indices)
            edges = coords[indices.reshape(-1, 2)]
            for z in (low, high):
                mask = (edges[:, 0, 2] < z) != (edges[:, 1, 2] < z)
                a, b = edges[mask, 0], edges[mask, 1]
                t = (z-a[:, 2])/(b[:, 2]-a[:, 2])
                sliced.append((a+(b-a)*t[:, None])[:, :2])
            xy = np.unique(np.concatenate(sliced), axis=0)
            if len(xy):
                hull = xy[convex_hull_2d([Vector(p) for p in xy])]
                # mathutils hull winding is not guaranteed; distances expect CCW.
                area = sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(hull, np.roll(hull, -1, axis=0)))
                out.append((obj.name, hull if area >= 0 else hull[::-1]))
        finally:
            ev.to_mesh_clear()
    return out


class Planner:
    def __init__(self, rig, route, ground, ignored, frame):
        self.radius = body_radius(rig)
        self.margin = self.radius + CLEARANCE
        self.raw = footprints(rig, ignored, ground, frame)
        self.edges = []
        self.warnings = []
        self.detours = 0
        self.empty = not self.raw and not ground.objects
        if self.empty:
            return
        xy = np.array([[p.x, p.y] for p in route])
        # Bound work independently of huge background meshes. Search up to ten
        # meters beyond the requested route; this covers ordinary furnished rooms.
        padding = min(10.0, max(3.0, float(np.linalg.norm(np.ptp(xy, axis=0)))*0.5))
        self.origin = np.floor((xy.min(axis=0)-padding)/CELL)*CELL
        end = xy.max(axis=0)+padding
        self.shape = tuple(int(v) for v in (np.ceil((end-self.origin)/CELL).astype(int)+1)[::-1])
        if math.prod(self.shape) > 1000000:
            raise ValueError("obstacle search exceeds one million cells; split the route or use avoid=False")
        self.blocked = np.zeros(self.shape, dtype=bool)
        # Half a cell diagonal makes rasterization/LOS conservative at boundaries.
        inflate = self.margin + CELL*math.sqrt(2)/2
        for _name, poly in self.raw:
            lo = np.maximum(0, np.floor((poly.min(axis=0)-inflate-self.origin)/CELL).astype(int))
            hi = np.minimum(np.array(self.shape[::-1])-1,
                            np.ceil((poly.max(axis=0)+inflate-self.origin)/CELL).astype(int))
            if np.any(hi < lo):
                continue
            yy, xx = np.mgrid[lo[1]:hi[1]+1, lo[0]:hi[0]+1]
            points = np.stack((xx, yy), axis=-1)*CELL+self.origin
            mask = _distance(points, poly) <= inflate
            if ground.objects:
                # Retain only the local ankle-to-head slice (bounds are conservative).
                obj = bpy.data.objects[_name].evaluated_get(bpy.context.evaluated_depsgraph_get())
                zs = [(obj.matrix_world @ Vector(c)).z for c in obj.bound_box]
                heights = np.array([ground.sample(*p)[0] for p in points.reshape(-1, 2)]).reshape(xx.shape)
                mask &= (max(zs) >= heights+0.05) & (min(zs) <= heights+1.7)
            self.blocked[lo[1]:hi[1]+1, lo[0]:hi[0]+1] |= mask
        if ground.objects:
            # Only abrupt height differences block passage; tops and normal stair
            # risers remain walkable. Inflate cliff edges so the whole body stays in.
            yy, xx = np.indices(self.shape)
            heights = np.array([ground.sample(x*CELL+self.origin[0], y*CELL+self.origin[1])[0]
                                for y, x in zip(yy.flat, xx.flat)]).reshape(self.shape)
            edge = np.zeros(self.shape, bool)
            for axis in (0, 1):
                jump = abs(np.diff(heights, axis=axis)) > 0.25+1e-6
                a, b = [slice(None)]*2, [slice(None)]*2
                a[axis], b[axis] = slice(None, -1), slice(1, None)
                edge[tuple(a)] |= jump
                edge[tuple(b)] |= jump
            ey, ex = np.nonzero(edge)
            self.edges = np.stack((ex, ey), axis=-1)*CELL+self.origin
            n = math.ceil(inflate/CELL)
            for dy in range(-n, n+1):
                for dx in range(-n, n+1):
                    if math.hypot(dx, dy)*CELL > inflate:
                        continue
                    x, y = ex+dx, ey+dy
                    valid = (x >= 0) & (x < self.shape[1]) & (y >= 0) & (y < self.shape[0])
                    self.blocked[y[valid], x[valid]] = True

    def cell(self, point):
        # Python ints matter here: numpy scalar arithmetic in every A* neighbor
        # and heap comparison otherwise dominates a room-sized search.
        return tuple(int(v) for v in np.rint((np.array(point[:2])-self.origin)/CELL))

    def point(self, cell):
        return Vector((*map(float, np.array(cell)*CELL+self.origin), 0))

    def free(self, cell):
        x, y = cell
        return 0 <= x < self.shape[1] and 0 <= y < self.shape[0] and not self.blocked[y, x]

    def line_free(self, a, b):
        a, b = np.array(a[:2]), np.array(b[:2])
        n = max(1, math.ceil(float(np.linalg.norm(b-a))/(CELL*0.4)))
        cells = np.rint((np.linspace(a, b, n+1)-self.origin)/CELL).astype(int)
        x, y = cells.T
        if np.any(x < 0) or np.any(x >= self.shape[1]) or np.any(y < 0) or np.any(y >= self.shape[0]):
            return False
        return not self.blocked[y, x].any()

    def curve_free(self, points):
        return all(self.line_free(a, b) for a, b in zip(points, points[1:]))

    def _astar(self, start, goal):
        # A blocked border and flat Python storage keep the neighbor loop small;
        # numpy scalars/dict tuples are disproportionately expensive here.
        width = self.shape[1]+2
        blocked = np.pad(self.blocked, 1, constant_values=True).ravel().tobytes()
        first = (start[1]+1)*width+start[0]+1
        last = (goal[1]+1)*width+goal[0]+1
        costs, parents = [math.inf]*len(blocked), [-1]*len(blocked)
        closed = bytearray(len(blocked))
        root2 = math.sqrt(2)

        def heuristic(index):
            y, x = divmod(index, width)
            dx, dy = abs(x-goal[0]-1), abs(y-goal[1]-1)
            return max(dx, dy)+(root2-1)*min(dx, dy)

        h = heuristic(first)
        opened = [(h, h, 0.0, first)]
        costs[first] = 0.0
        neighbors = [(dy*width+dx, root2 if dx and dy else 1.0, dx, dy*width)
                     for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                                    (1, 1), (1, -1), (-1, 1), (-1, -1))]
        while opened:
            _f, _h, cost, p = heapq.heappop(opened)
            if closed[p] or cost > costs[p]+1e-9:
                continue
            if p == last:
                path = []
                while p != -1:
                    y, x = divmod(p, width)
                    path.append((x-1, y-1))
                    p = parents[p]
                return list(reversed(path))
            closed[p] = 1
            for offset, step, sx, sy in neighbors:
                q = p+offset
                if blocked[q] or closed[q] or (sx and sy and (blocked[p+sx] or blocked[p+sy])):
                    continue
                g = cost+step
                if g < costs[q]-1e-9:
                    costs[q], parents[q] = g, p
                    h = heuristic(q)
                    # Prefer progress on equal f-scores without changing A*'s
                    # admissible octile heuristic or optimality.
                    heapq.heappush(opened, (g+h, h, g, q))
        raise ValueError("no obstacle-free path to target within the navigation grid; change targets/ignore or use avoid=False")

    def _nearest_free(self, target):
        y, x = np.nonzero(~self.blocked)
        if not len(x):
            raise ValueError("no obstacle-free cells in navigation grid")
        delta = np.stack((x, y), axis=-1)*CELL+self.origin-np.array(target[:2])
        i = int(np.argmin(np.sum(delta*delta, axis=-1)))
        return (int(x[i]), int(y[i]))

    def plan(self, route, curves, escape=True):
        # Test the existing curved route too: a rounded free polyline can bow into
        # furniture. Do not replace any points on a clear route.
        if self.empty:
            return route
        straight_free = all(self.line_free(a, b) for a, b in zip(route, route[1:]))
        curved_free = straight_free and (len(route) == 1 or all(
            self.curve_free([p for p, _ in c]) for c in curves(route)))
        out = [route[0]]
        if not self.free(self.cell(route[0])):
            # Characters often stand within the clearance margin of a desk or chair
            # (e.g. staged behind a desk). Step straight out to the nearest free cell
            # first, but only over a short distance; a deeply buried start is an error.
            exit_point = self.point(self._nearest_free(route[0]))
            if not escape or len(route) < 2 or (exit_point - route[0]).length > ESCAPE_DISTANCE:
                raise ValueError("walking character starts inside an inflated obstacle; move it or ignore the object")
            self.warnings.append(f"start {list(route[0])[:2]} is within the clearance margin; "
                                 f"stepping out to {[round(v, 3) for v in list(exit_point)[:2]]} first")
            out.append(exit_point)
            self.detours += 1
            curved_free = False
        if curved_free:
            return route
        for target in route[1:]:
            goal = self.cell(target)
            if not self.free(goal):
                goal = self._nearest_free(target)
                replacement = self.point(goal)
                self.warnings.append(f"target {list(target)[:2]} is blocked; moved to {list(replacement)[:2]}")
                target = replacement
            if self.line_free(out[-1], target):
                out.append(target)
                continue
            cells = self._astar(self.cell(out[-1]), goal)
            # Remove grid runs before LOS simplification (hundreds of redundant
            # collinear tests otherwise cost more than the search itself).
            corners = [cells[0]] + [b for a, b, c in zip(cells, cells[1:], cells[2:])
                if (b[0]-a[0], b[1]-a[1]) != (c[0]-b[0], c[1]-b[1])] + [cells[-1]]
            path = [out[-1]] + [self.point(c) for c in corners] + [target]
            i = 0
            while i < len(path)-1:
                j = len(path)-1
                while j > i+1 and not self.line_free(path[i], path[j]):
                    j -= 1
                out.append(path[j])
                i = j
            self.detours += 1
        # A curve-only collision also counts as a detour (walk uses safe curves).
        self.detours = max(1, self.detours)
        return [p for i, p in enumerate(out) if i == 0 or (p-out[i-1]).length > 1e-5]

    def report(self, route, samples, avoided):
        xy = np.array([[p.x, p.y] for p, _yaw in samples])
        distances = [float(_distance(xy, poly).min()) for _name, poly in self.raw]
        if len(self.edges):
            distances.extend(float(np.linalg.norm(xy-p, axis=-1).min()) for p in self.edges)
        return {"avoided": avoided, "detours": self.detours,
                "path_points": [list(p)[:2] for p in route],
                "body_radius_m": round(self.radius, 5),
                "clearance_m": round(min(distances), 5) if distances else None,
                "warnings": self.warnings}
