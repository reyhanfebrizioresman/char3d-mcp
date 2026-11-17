"""Scene inspection and basic object manipulation."""
import math
import os

import bpy
from mathutils import Vector

from . import command
from .util import is_helper, obj_or_raise, scene_bounds, vec

PRIMITIVES = {
    "cube": lambda s: bpy.ops.mesh.primitive_cube_add(size=s),
    "sphere": lambda s: bpy.ops.mesh.primitive_uv_sphere_add(radius=s / 2),
    "ico_sphere": lambda s: bpy.ops.mesh.primitive_ico_sphere_add(radius=s / 2),
    "cylinder": lambda s: bpy.ops.mesh.primitive_cylinder_add(radius=s / 2, depth=s),
    "cone": lambda s: bpy.ops.mesh.primitive_cone_add(radius1=s / 2, depth=s),
    "plane": lambda s: bpy.ops.mesh.primitive_plane_add(size=s),
    "torus": lambda s: bpy.ops.mesh.primitive_torus_add(major_radius=s / 2, minor_radius=s / 8),
    "monkey": lambda s: bpy.ops.mesh.primitive_monkey_add(size=s),
}


@command("ping")
def ping():
    return {
        "blender": bpy.app.version_string,
        "file": bpy.data.filepath or None,
        "allow_python": os.environ.get("CHAR3D_ALLOW_PYTHON") == "1",
    }


def _describe(obj):
    info = {
        "name": obj.name,
        "type": obj.type,
        "parent": obj.parent.name if obj.parent else None,
        "location": vec(obj.location),
        "rotation_deg": [round(math.degrees(a), 2) for a in obj.rotation_euler],
        "scale": vec(obj.scale),
        "dimensions": vec(obj.dimensions),
        "visible": not obj.hide_render,
        "collections": [c.name for c in obj.users_collection],
    }
    if obj.type == "MESH":
        me = obj.data
        info["mesh"] = {
            "vertices": len(me.vertices),
            "faces": len(me.polygons),
            "materials": [m.name for m in me.materials if m],
            "vertex_groups": len(obj.vertex_groups),
            "shape_keys": len(me.shape_keys.key_blocks) if me.shape_keys else 0,
        }
        info["modifiers"] = [f"{m.type}:{m.name}" for m in obj.modifiers]
    elif obj.type == "ARMATURE":
        bones = obj.data.bones
        info["armature"] = {
            "bones": len(bones),
            "root_bones": [b.name for b in bones if b.parent is None][:10],
        }
    if obj.animation_data and obj.animation_data.action:
        act = obj.animation_data.action
        info["action"] = {"name": act.name, "frame_range": vec(act.frame_range, 1)}
    return info


@command("scene_info")
def scene_info():
    sc = bpy.context.scene
    lo, hi = scene_bounds()
    return {
        "scene": sc.name,
        "file": bpy.data.filepath or None,
        "frame_range": [sc.frame_start, sc.frame_end],
        "fps": sc.render.fps,
        "render": {
            "engine": sc.render.engine,
            "resolution": [sc.render.resolution_x, sc.render.resolution_y],
        },
        "active_camera": sc.camera.name if sc.camera else None,
        "bounds": {"min": vec(lo), "max": vec(hi)} if lo else None,
        "objects": [_describe(o) for o in sc.objects if not is_helper(o)],
        "hidden_helper_objects": sum(1 for o in sc.objects if is_helper(o)),
    }


@command("new_scene")
def new_scene(fps=24, frame_end=120):
    """Empty scene (no default cube/camera/light), metric units, Z-up, -Y forward."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.render.fps = fps
    sc.frame_start, sc.frame_end = 1, frame_end
    if not bpy.data.worlds:
        bpy.data.worlds.new("World")
    sc.world = bpy.data.worlds[0]
    return scene_info()


@command("add_primitive")
def add_primitive(kind="cube", name=None, location=(0, 0, 0), size=1.0):
    if kind not in PRIMITIVES:
        raise ValueError(f"kind must be one of {sorted(PRIMITIVES)}")
    PRIMITIVES[kind](size)
    obj = bpy.context.active_object
    obj.location = Vector(location)
    if name:
        obj.name = name
    return _describe(obj)


@command("transform_object")
def transform_object(name, location=None, rotation_deg=None, scale=None):
    obj = obj_or_raise(name)
    if location is not None:
        obj.location = Vector(location)
    if rotation_deg is not None:
        obj.rotation_euler = [math.radians(a) for a in rotation_deg]
    if scale is not None:
        obj.scale = Vector(scale if hasattr(scale, "__len__") else (scale,) * 3)
    # Refresh matrix_world now: later commands read world-space landmarks, and a
    # stale matrix made e.g. animate build its proxy unrotated (bent/akimbo arms).
    bpy.context.view_layer.update()
    return _describe(obj)


@command("delete_objects")
def delete_objects(names):
    removed = []
    for n in names:
        obj = bpy.data.objects.get(n)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed.append(n)
    return {"removed": removed, "missing": [n for n in names if n not in removed]}


@command("run_python")
def run_python(code):
    """Escape hatch. Only enabled when CHAR3D_ALLOW_PYTHON=1 is set."""
    if os.environ.get("CHAR3D_ALLOW_PYTHON") != "1":
        raise PermissionError("run_python is disabled. Start the engine with CHAR3D_ALLOW_PYTHON=1.")
    import contextlib
    import io as _io

    buf = _io.StringIO()
    ns = {"bpy": bpy, "Vector": Vector, "result": None}
    with contextlib.redirect_stdout(buf):
        exec(code, ns)  # noqa: S102 - deliberate, gated by env flag
    res = ns.get("result")
    try:
        import json

        json.dumps(res)
    except TypeError:
        res = repr(res)
    return {"stdout": buf.getvalue()[-8000:], "result": res}
