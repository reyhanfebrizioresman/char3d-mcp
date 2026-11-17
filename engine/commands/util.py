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


def _visible_part(o):
    return (o.type in RENDERABLE and not o.hide_render and o.visible_get()
            and not is_helper(o) and o.get("c3d_role") not in {"ground", "weather"})


def scene_bounds(objects=None):
    """World-space AABB of renderable objects (after modifiers/armature deform).
    An armature stands for the character it drives: its visible meshes (body, hair,
    clothes), or its deform bones when it has none - never its control bones, which on
    Rigify-style rigs (root, properties) reach far beyond the body."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objs, points = [], []
    if objects:
        for o in objects:
            if o.type != "ARMATURE":
                objs.append(o)
                continue
            parts = [c for c in o.children_recursive if _visible_part(c)]
            if parts:
                objs.extend(p for p in parts if p not in objs)
                continue
            mw = o.matrix_world
            bones = [pb for pb in o.pose.bones if pb.bone.use_deform] or list(o.pose.bones)
            for pb in bones:
                points += [mw @ pb.head, mw @ pb.tail]
    else:
        objs = [o for o in bpy.context.scene.objects if _visible_part(o)]
    for o in objs:
        ev = o.evaluated_get(depsgraph)
        points += [ev.matrix_world @ Vector(corner) for corner in ev.bound_box]
    if not points:
        return None, None
    lo, hi = points[0].copy(), points[0].copy()
    for p in points[1:]:
        lo = Vector(map(min, lo, p))
        hi = Vector(map(max, hi, p))
    return lo, hi
