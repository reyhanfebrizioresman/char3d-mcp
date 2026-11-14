"""Preview rendering with an automatic framing camera.

Convention: characters face -Y (Blender "front" view), Z is up.
"""
import math
import os
import time

import bpy
from mathutils import Vector

from .. import context
from . import command
from .util import obj_or_raise, scene_bounds

VIEWS = {
    "front": (0, -1, 0),
    "back": (0, 1, 0),
    "left": (-1, 0, 0),
    "right": (1, 0, 0),
    "top": (0, -0.001, 1),
    "three_quarter": (0.65, -1, 0.35),
    "three_quarter_left": (-0.65, -1, 0.35),
}

ENGINES = {
    "workbench": "BLENDER_WORKBENCH",
    "eevee": "BLENDER_EEVEE",
    "cycles": "CYCLES",
}


def _setup_engine(sc, engine):
    sc.render.engine = ENGINES[engine]
    if engine == "workbench":
        sh = sc.display.shading
        sh.light = "STUDIO"
        sh.color_type = "MATERIAL"
        sh.show_cavity = True
        sh.cavity_type = "BOTH"
    elif engine == "cycles":
        sc.cycles.device = "CPU"
        sc.cycles.samples = 24
        sc.cycles.use_denoising = True
    elif engine == "eevee" and hasattr(sc, "eevee"):
        sc.eevee.taa_render_samples = 16


def _temp_lights(sc, center, radius):
    """Simple key/fill lights + gray world, only when the scene has no lights."""
    if any(o.type == "LIGHT" and not o.hide_render for o in sc.objects):
        return []
    made = []
    for name, energy, offset in (("key", 4.0, (1.5, -2.0, 2.5)), ("fill", 1.5, (-2.0, -1.0, 1.0))):
        data = bpy.data.lights.new(f"__c3d_{name}", "SUN")
        data.energy = energy
        obj = bpy.data.objects.new(f"__c3d_{name}", data)
        sc.collection.objects.link(obj)
        obj.location = center + Vector(offset) * radius
        obj.rotation_euler = (center - obj.location).to_track_quat("-Z", "Y").to_euler()
        made.append(obj)
    if sc.world is None:
        sc.world = bpy.data.worlds.new("World")
    return made


@command("render_preview")
def render_preview(view="three_quarter", width=512, height=512, engine="workbench",
                   frame=None, objects=None, filename=None, transparent=False):
    """Render a still from an auto-framed camera. Returns the PNG path."""
    if view not in VIEWS:
        raise ValueError(f"view must be one of {sorted(VIEWS)}")
    if engine not in ENGINES:
        raise ValueError(f"engine must be one of {sorted(ENGINES)}")
    sc = bpy.context.scene
    if frame is not None:
        sc.frame_set(int(frame))

    targets = [obj_or_raise(n) for n in objects] if objects else None
    lo, hi = scene_bounds(targets)
    if lo is None:
        raise RuntimeError("nothing to render: scene has no visible geometry")
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.01)

    # remember settings we touch
    saved = dict(engine=sc.render.engine, camera=sc.camera, rx=sc.render.resolution_x,
                 ry=sc.render.resolution_y, pct=sc.render.resolution_percentage,
                 fp=sc.render.filepath, transparent=sc.render.film_transparent,
                 fmt=sc.render.image_settings.file_format)

    cam_data = bpy.data.cameras.new("__c3d_preview_cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("__c3d_preview_cam", cam_data)
    sc.collection.objects.link(cam)
    # sensor_fit AUTO: the longer image side gets the full 36mm sensor
    half = math.atan(18.0 / cam_data.lens)
    short = math.atan(math.tan(half) * min(width, height) / max(width, height))
    fov = 2 * min(half, short)
    dist = radius / math.sin(fov / 2) * 1.08
    direction = Vector(VIEWS[view]).normalized()
    cam.location = center + direction * dist
    cam.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    cam_data.clip_start = max(dist - radius * 3, 0.01)
    cam_data.clip_end = dist + radius * 3
    lights = _temp_lights(sc, center, radius) if engine != "workbench" else []

    os.makedirs(os.path.join(context.WORKSPACE, "renders"), exist_ok=True)
    name = filename or f"preview_{view}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    out = context.resolve(name, "renders")
    used = engine
    try:
        sc.camera = cam
        sc.render.resolution_x, sc.render.resolution_y = int(width), int(height)
        sc.render.resolution_percentage = 100
        sc.render.film_transparent = bool(transparent)
        sc.render.image_settings.file_format = "PNG"
        sc.render.filepath = out
        try:
            _setup_engine(sc, engine)
            bpy.ops.render.render(write_still=True)
        except RuntimeError:
            # Workbench/Eevee need an OpenGL context; fall back to CPU Cycles.
            if engine == "cycles":
                raise
            used = "cycles"
            if not lights:
                lights = _temp_lights(sc, center, radius)
            _setup_engine(sc, "cycles")
            bpy.ops.render.render(write_still=True)
    finally:
        sc.render.engine = saved["engine"]
        sc.camera = saved["camera"]
        sc.render.resolution_x, sc.render.resolution_y = saved["rx"], saved["ry"]
        sc.render.resolution_percentage = saved["pct"]
        sc.render.filepath = saved["fp"]
        sc.render.film_transparent = saved["transparent"]
        sc.render.image_settings.file_format = saved["fmt"]
        for o in [cam, *lights]:
            data = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if isinstance(data, bpy.types.Camera):
                bpy.data.cameras.remove(data)
            else:
                bpy.data.lights.remove(data)
    return {"path": out, "view": view, "engine": used, "size": [width, height]}
