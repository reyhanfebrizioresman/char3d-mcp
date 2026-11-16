"""Original walkable geometry and a per-bake world-space ground BVH (meters, Z up)."""
import math

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import command

COLLECTION = "char3d_terrain"


def sole_footprint(sole, rotation):
    """Sample sole length and both edges; width scales with the skeletal foot length."""
    direction = rotation @ (sole[-1] - sole[0])
    side = Vector((-direction.y, direction.x, 0)).normalized() * direction.length * 0.2
    side = rotation.inverted() @ side
    centerline = [sole[0].lerp(sole[-1], i/6) for i in range(7)]
    return [p + side*w for p in centerline for w in (-1, 0, 1)]


def _positive(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return float(value)


@command("add_terrain")
def add_terrain(kind, location=(0, 0, 0), rotation_z=0, width=1.2, length=None,
                height=None, steps=None, name=None):
    """Base/entrance at location; extends along local -Y, rising toward its far end."""
    if kind not in ("stairs", "ramp", "platform", "step"):
        raise ValueError("kind must be stairs, ramp, platform or step")
    if not isinstance(location, (list, tuple)) or len(location) != 3 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in location):
        raise ValueError("location must contain three finite coordinates")
    if isinstance(rotation_z, bool) or not isinstance(rotation_z, (int, float)) or not math.isfinite(rotation_z):
        raise ValueError("rotation_z must be finite")
    width = _positive(width, "width")
    if steps is not None and (isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 200):
        raise ValueError("steps must be an integer in 1..200")
    if kind != "stairs" and steps is not None:
        raise ValueError("steps is only used for stairs")
    count = 1
    if kind == "stairs":
        count = steps if steps is not None else (max(1, round(_positive(height, "height") / 0.17))
                                                if height is not None else 5)
        if count > 200:
            raise ValueError("inferred steps exceeds 200; specify steps or reduce height")
    height = _positive(height if height is not None else count * 0.17, "height")
    length = _positive(length if length is not None else
                       (count * 0.28 if kind == "stairs" else 2.0 if kind == "ramp" else
                        1.2 if kind == "platform" else 0.28), "length")
    verts, faces = [], []

    def block(y0, y1, top0, top1):
        k = len(verts)
        verts.extend([(-width/2, y0, 0), (width/2, y0, 0), (width/2, y1, 0), (-width/2, y1, 0),
                      (-width/2, y0, top0), (width/2, y0, top0),
                      (width/2, y1, top1), (-width/2, y1, top1)])
        faces.extend(tuple(k+i for i in f) for f in
                     [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
                      (3, 2, 6, 7), (0, 3, 7, 4), (1, 5, 6, 2)])

    if kind == "stairs":
        for i in range(count):
            block(-i*length/count, -(i+1)*length/count, (i+1)*height/count, (i+1)*height/count)
    else:
        block(0, -length, 0 if kind == "ramp" else height, height)
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(COLLECTION)
        bpy.context.scene.collection.children.link(coll)
    mesh = bpy.data.meshes.new(name or f"Terrain_{kind}")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name or f"Terrain_{kind}", mesh)
    coll.objects.link(obj)
    obj.location = location
    obj.rotation_euler.z = math.radians(rotation_z)
    obj["char3d_walkable"] = True
    obj["char3d_terrain_kind"] = kind
    obj["char3d_tread"] = length/count if kind == "stairs" else 0.0
    obj["char3d_rise"] = height/count
    from .lighting import make_material
    material = make_material("Terrain_stone", (0.25, 0.34, 0.39), roughness=0.85)
    material["char3d_terrain"] = True
    obj.data.materials.append(material)
    obj.color = (0.25, 0.34, 0.39, 1)
    bpy.context.view_layer.update()
    return {"object": obj.name, "kind": kind, "location": list(location), "width": width,
            "length": length, "height": height, "steps": count if kind == "stairs" else None,
            "rise_m": height/count, "tread_m": length/count if kind == "stairs" else None,
            "walkable": True}


@command("clear_terrain")
def clear_terrain():
    coll = bpy.data.collections.get(COLLECTION)
    removed = []
    if coll:
        for obj in list(coll.objects):
            removed.append(obj.name)
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        bpy.data.collections.remove(coll)
    for mat in list(bpy.data.materials):
        if mat.get("char3d_terrain") and mat.users == 0:
            bpy.data.materials.remove(mat)
    return {"removed": removed}


class GroundQuery:
    """Snapshot evaluated walkable meshes once per call. Cache ray hits by world XY.

    The base plane remains a fallback. Only upward surfaces above it are walkable;
    untagged scenery/characters are deliberately excluded, including lighting ground.
    """
    def __init__(self, floor=0.0, enabled=True):
        self.floor = float(floor)
        self.objects = [o for o in bpy.context.scene.objects
                        if enabled and o.type == "MESH" and o.get("char3d_walkable")
                        and not o.hide_render]
        verts, faces, treads = [], [], []
        deps = bpy.context.evaluated_depsgraph_get()
        for obj in self.objects:
            evaluated = obj.evaluated_get(deps)
            mesh = evaluated.to_mesh()
            try:
                base = len(verts)
                verts.extend(evaluated.matrix_world @ v.co for v in mesh.vertices)
                faces.extend(tuple(base+i for i in p.vertices) for p in mesh.polygons)
                treads.extend([float(obj.get("char3d_tread", 0))] * len(mesh.polygons))
            finally:
                evaluated.to_mesh_clear()
        self.bvh = BVHTree.FromPolygons(verts, faces, all_triangles=False) if faces else None
        self.top = max([self.floor] + [v.z for v in verts]) + 1.0
        self.cache = {}
        self.treads = treads
        self.tread_cache = {}

    def sample(self, x, y):
        key = (round(x, 6), round(y, 6))
        if key not in self.cache:
            hit = self.bvh.ray_cast(Vector((x, y, self.top)), Vector((0, 0, -1))) if self.bvh else (None,)*4
            p, normal = hit[:2]
            walkable = p is not None and p.z > self.floor and normal.z > 0.1
            self.cache[key] = ((p.z, normal) if walkable
                               else (self.floor, Vector((0, 0, 1))))
            self.tread_cache[key] = self.treads[hit[2]] if walkable else 0.0
        return self.cache[key]

    def gait(self, point, heading):
        """Local tread and slope, including the sole's approach to a stair edge."""
        forward = Vector((math.sin(heading), -math.cos(heading), 0))
        tread, slope = 0.0, 0.0
        probes = []
        for offset in (-0.18, 0.0, 0.18):
            p = point + forward * offset
            height, normal = self.sample(p.x, p.y)
            probes.append((height, normal))
            local = self.tread_cache[(round(p.x, 6), round(p.y, 6))]
            if local:
                tread = min(tread or local, local)
            slope = max(slope, abs(normal.dot(forward)) / max(normal.z, 0.1))
        # User-tagged meshes need no procedural metadata: a height discontinuity
        # between horizontal surfaces is a step, while a continuous ramp is not.
        for (a, na), (b, nb) in zip(probes, probes[1:]):
            if na.z > 0.995 and nb.z > 0.995 and abs(a-b) > 0.025:
                tread = tread or 0.28
        return tread, slope

    def fit(self, ankle, rotation, sole):
        """Pitch a sole onto the local plane. Return pose and its footprint height error."""
        center = ankle + rotation @ (sum(sole, Vector()) / len(sole))
        height, normal = self.sample(center.x, center.y)
        q = Vector((0, 0, 1)).rotation_difference(normal) @ rotation
        points = [ankle + q @ p for p in sole_footprint(sole, rotation)]
        dz = [self.sample(p.x, p.y)[0] - p.z for p in points]
        p = ankle + Vector((0, 0, max(dz)))
        return p, q, max(dz) - min(dz), height


def smooth_heights(values, radius):
    """Symmetric triangular filter; prefix sums avoid a quadratic baking window."""
    def box(items):
        prefix = [0.0]
        for v in items:
            prefix.append(prefix[-1] + v)
        return [(prefix[min(len(items), i+radius+1)] - prefix[max(0, i-radius)]) /
                (min(len(items), i+radius+1) - max(0, i-radius)) for i in range(len(items))]
    return box(box(values))
