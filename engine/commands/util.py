"""Small helpers shared by commands."""
import bpy
from mathutils import Vector

RENDERABLE = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME"}


def vec(v, nd=4):
    return [round(float(x), nd) for x in v]


def is_helper(obj):
    """Rig widget shapes etc. that live in hidden collections (e.g. Rigify WGT-*)."""
    return obj.name.startswith("WGT-") or any(c.name.startswith("WGTS") for c in obj.users_collection)


def obj_or_raise(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        names = [o.name for o in bpy.context.scene.objects][:50]
        raise KeyError(f"object '{name}' not found. Objects in scene: {names}")
    return obj


def scene_bounds(objects=None):
    """World-space AABB of renderable objects (after modifiers/armature deform)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objs = objects or [o for o in bpy.context.scene.objects
                       if o.type in RENDERABLE and not o.hide_render and o.visible_get()
                       and not is_helper(o) and o.get("c3d_role") != "ground"]
    lo = hi = None
    for o in objs:
        ev = o.evaluated_get(depsgraph)
        for corner in ev.bound_box:
            p = ev.matrix_world @ Vector(corner)
            lo = p.copy() if lo is None else Vector(map(min, lo, p))
            hi = p.copy() if hi is None else Vector(map(max, hi, p))
    return lo, hi
