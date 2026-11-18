"""Lighting presets, world/background, ground plane and quick materials.

Lights are placed around the subject with the same angle convention as cameras
(azimuth 0 = in front of the subject, 90 = subject's left, 180 = behind).
"""
import math
from bisect import bisect_left, bisect_right

import bpy
from mathutils import Vector

from . import command
from .camera import _subjects
from .util import obj_or_raise, scene_bounds

# light: (type, azimuth, elevation, distance x height, power, rgb, size x height)
# power: W for AREA/SPOT/POINT, strength for SUN
PRESETS = {
    "studio": dict(
        desc="Classic 3-point: soft key, fill, rim. Neutral grey backdrop.",
        world=((0.05, 0.05, 0.055), 1.0),
        lights=[("AREA", 40, 35, 1.8, 550, (1, 0.97, 0.93), 0.9),
                ("AREA", -55, 15, 2.0, 180, (0.92, 0.95, 1), 1.4),
                ("AREA", 160, 40, 1.8, 420, (1, 1, 1), 0.5)]),
    "soft": dict(
        desc="Large soft sources, low contrast, beauty/commercial look.",
        world=((0.18, 0.18, 0.19), 1.0),
        lights=[("AREA", 25, 25, 1.8, 600, (1, 0.98, 0.95), 2.2),
                ("AREA", -40, 10, 1.8, 300, (0.95, 0.97, 1), 2.2)]),
    "dramatic": dict(
        desc="Hard side key and strong rim, deep shadows (film noir / thriller).",
        world=((0.004, 0.004, 0.006), 1.0),
        lights=[("SPOT", 75, 40, 2.2, 1600, (1, 0.93, 0.82), 0.06),
                ("AREA", -150, 30, 1.6, 500, (0.75, 0.85, 1), 0.3)]),
    "sunset": dict(
        desc="Low warm sun, cool sky fill, long shadows (golden hour).",
        world=((0.22, 0.28, 0.5), 0.8),
        lights=[("SUN", 70, 8, 0, 4.0, (1, 0.55, 0.28), 0.02)]),
    "noon": dict(
        desc="High white sun, blue sky, crisp daylight.",
        world=((0.45, 0.6, 0.9), 1.0),
        lights=[("SUN", 30, 65, 0, 5.0, (1, 0.97, 0.92), 0.01)]),
    "overcast": dict(
        desc="Flat bright sky light, soft shadows.",
        world=((0.75, 0.78, 0.82), 1.4),
        lights=[("SUN", 20, 60, 0, 0.6, (0.95, 0.97, 1), 0.3)]),
    "night": dict(
        desc="Cool moonlight, dark blue ambience, subtle rim.",
        world=((0.01, 0.015, 0.04), 1.0),
        lights=[("SUN", -40, 35, 0, 0.9, (0.55, 0.68, 1), 0.02),
                ("AREA", 170, 25, 1.6, 250, (0.5, 0.65, 1), 0.4)]),
    "neon": dict(
        desc="Cyberpunk: magenta and cyan side lights on a dark set.",
        world=((0.01, 0.005, 0.02), 1.0),
        lights=[("AREA", 75, 10, 1.4, 650, (1, 0.12, 0.75), 0.6),
                ("AREA", -75, 10, 1.4, 650, (0.1, 0.8, 1), 0.6),
                ("AREA", 180, 35, 1.6, 300, (0.6, 0.4, 1), 0.4)]),
    "silhouette": dict(
        desc="Bright backdrop, subject dark (sunset silhouette / music video).",
        world=((1.0, 0.55, 0.3), 2.5),
        lights=[("AREA", 180, 5, 2.0, 900, (1, 0.6, 0.35), 2.0)]),
    "horror": dict(
        desc="Under-lighting with sickly green tint, very dark surroundings.",
        world=((0.003, 0.005, 0.004), 1.0),
        lights=[("SPOT", 10, -40, 1.5, 900, (0.55, 1, 0.6), 0.15),
                ("AREA", 170, 20, 1.6, 200, (0.4, 0.5, 0.6), 0.3)]),
}


def _world(color, strength):
    sc = bpy.context.scene
    w = sc.world or bpy.data.worlds.new("World")
    sc.world = w
    w.color = color
    if hasattr(w, "use_nodes"):
        w.use_nodes = True
    bg = w.node_tree.nodes.get("Background") if w.node_tree else None
    if bg:
        bg.inputs["Color"].default_value = (*color, 1.0)
        bg.inputs["Strength"].default_value = strength
    return w


def _clear_c3d(role):
    for o in [o for o in bpy.data.objects if o.get("c3d_role") == role]:
        data = o.data
        action = o.animation_data.action if o.animation_data else None
        bpy.data.objects.remove(o, do_unlink=True)
        if action is not None and action.users == 0:
            bpy.data.actions.remove(action)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Light):
                bpy.data.lights.remove(data)
            elif isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)


def make_material(name, color=(0.8, 0.8, 0.8), roughness=0.5, metallic=0.0,
                  emission=None, emission_strength=0.0):
    mat = bpy.data.materials.new(name)
    rgba = (*color[:3], 1.0)
    mat.diffuse_color = rgba
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = float(roughness)
        bsdf.inputs["Metallic"].default_value = float(metallic)
        if emission is not None or emission_strength:
            ec = emission or color
            key = "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
            bsdf.inputs[key].default_value = (*ec[:3], 1.0)
            bsdf.inputs["Emission Strength"].default_value = float(emission_strength or 1.0)
    return mat


@command("list_lighting_presets")
def list_lighting_presets():
    return {k: v["desc"] for k, v in PRESETS.items()}


def _motion_bounds(targets):
    """Sample evaluated bounds, keeping the caller's frame (including subframe)."""
    sc = bpy.context.scene
    saved = sc.frame_current, sc.frame_subframe
    frames = sorted({*range(sc.frame_start, sc.frame_end + 1, 3), sc.frame_end})
    samples = []
    try:
        for frame in frames:
            sc.frame_set(frame)
            lo, hi = scene_bounds(targets)
            samples.append((frame, Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)),
                            hi.z - lo.z))
    finally:
        sc.frame_set(saved[0], subframe=saved[1])
    return samples


def _follow_rig(samples):
    """Centered half-second average: suppress gait bob without a trailing light rig.

    Z follows the feet/ground, rather than the bounds' center, so sitting does not
    lower the lights. A single fixed standing height controls power, size and aim.
    """
    from .talk import _fcurves

    sc = bpy.context.scene
    rig = bpy.data.objects.new("c3d_light_rig", None)
    rig["c3d_role"] = "light"
    sc.collection.objects.link(rig)
    frames = [s[0] for s in samples]
    sums = [Vector((0, 0, 0))]
    for _, position, _ in samples:
        sums.append(sums[-1] + position)
    radius = max(1.0, sc.render.fps / sc.render.fps_base * 0.25)
    for frame, _, _ in samples:
        a, b = bisect_left(frames, frame - radius), bisect_right(frames, frame + radius)
        rig.location = (sums[b] - sums[a]) / (b - a)
        rig.keyframe_insert("location", frame=frame)
    for curve in _fcurves(rig.animation_data.action):
        for key in curve.keyframe_points:
            key.interpolation = "LINEAR"
    sc.frame_set(sc.frame_current, subframe=sc.frame_subframe)
    return rig


@command("set_lighting")
def set_lighting(preset="studio", subject=None, strength=1.0, rotate=0.0, background=None,
                 ground=True, ground_color=(0.32, 0.32, 0.33), follow="auto"):
    """Replace preset lights; follow=True/False/'auto' bakes a smoothed subject path.

    Auto follows XY travel above 0.43 times standing height (~0.75 m for a human).
    Call after body animation and rerun after motion changes. SUNs remain static.
    Returns actual follow, travel_m and keys (location samples, not scalar keys).
    """
    from .environment import _sync_ground
    from .outdoor import outdoor_root, configure_sky

    if preset not in PRESETS:
        raise ValueError(f"preset must be one of {list(PRESETS)}")
    if not (isinstance(follow, bool) or follow == "auto"):
        raise ValueError("follow must be True, False or 'auto'")
    sc = bpy.context.scene
    p = PRESETS[preset]
    outdoors = outdoor_root() is not None
    lights = list(p["lights"])
    if outdoors:
        lights = [light for light in lights if light[0] != "SUN"]
        if not lights:
            lights = [("AREA", 30, 35, 1.8, 180, (1, .92, .83), 1.6),
                      ("AREA", -45, 25, 1.8, 90, (.72, .84, 1), 2.)]
            if preset == "night":
                lights = [(k, a, e, d, power*.32, c, s) for k, a, e, d, power, c, s in lights]
    targets = _subjects(subject)
    lo, hi = scene_bounds(targets) if targets else (Vector((-0.5, -0.5, 0)), Vector((0.5, 0.5, 1.8)))
    H = max(hi.z - lo.z, 0.1)
    call_height = H
    anchor = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    samples = _motion_bounds(targets) if targets else []
    travel = max(((pos.xy - anchor.xy).length for _, pos, _ in samples), default=0.0)
    standing_height = max([H] + [h for _, _, h in samples])
    motion = max(((pos - anchor).length for _, pos, _ in samples), default=0.0) > 1e-4
    following = bool(motion and (follow is True or (follow == "auto" and travel > 0.43 * standing_height))
                     and any(light[0] != "SUN" for light in lights))
    _clear_c3d("light")
    for obj in sc.objects:
        if obj.get('c3d_nature_night_fill'):
            obj.data.energy=obj['c3d_nature_night_fill'] if preset=='night' else 0
    rig = _follow_rig(samples) if following else None
    if following:
        H = standing_height
    center = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z + H * 0.55))
    scale = (H / 1.75) ** 2   # keep exposure similar for small/large subjects

    made = []
    for i, (kind, az, el, dist, power, rgb, size) in enumerate(lights):
        data = bpy.data.lights.new(f"c3d_{preset}_{i}", kind)
        data.color = rgb
        a, e = math.radians(az + rotate), math.radians(el)
        direction = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
        if kind == "SUN":
            data.energy = power * strength
            data.angle = math.radians(max(size * 57.3, 0.5))
            loc = center + direction * H * 3
        else:
            data.energy = power * strength * scale
            loc = center + direction * dist * H
            if kind == "AREA":
                data.shape = "DISK"
                data.size = size * H
            elif kind == "SPOT":
                data.spot_size = math.radians(45)
                data.spot_blend = 0.4
                data.shadow_soft_size = size * H
        obj = bpy.data.objects.new(data.name, data)
        obj["c3d_role"] = "light"
        sc.collection.objects.link(obj)
        obj.location = loc
        if rig is not None and kind != "SUN":
            obj.parent = rig
            obj.location = loc - anchor
        obj.rotation_euler = (center - loc).to_track_quat("-Z", "Y").to_euler()
        made.append(obj.name)

    color, wstrength = p["world"]
    if background is not None:
        color = tuple(background[:3])
    sky = configure_sky(preset, strength, rotate, background) if outdoors else None
    if not outdoors:
        _world(color, wstrength * (strength if preset in ("overcast", "silhouette") else 1.0))

    ground_name = None
    _clear_c3d("ground")
    if ground and not outdoors:
        bpy.ops.mesh.primitive_plane_add(size=max(400.0, call_height * 200))   # horizon far away
        g = bpy.context.view_layer.objects.active
        g.name = "c3d_ground"
        g["c3d_role"] = "ground"
        g.location.z = lo.z
        g.data.materials.append(make_material("c3d_ground_mat", ground_color, roughness=0.8))
        _sync_ground()
        ground_name = g.name
    if sc.render.engine == "BLENDER_WORKBENCH":
        sc.render.engine = "BLENDER_EEVEE"
    result = {"preset": preset, "lights": made, "ground": ground_name,
            "world_color": [round(c, 3) for c in color], "follow": following,
            "travel_m": round(travel, 4), "keys": len(samples) if following else 0}
    if outdoors:
        result["outdoor"] = sky
    return result


@command("set_material")
def set_material(objects, color=(0.8, 0.8, 0.8), roughness=0.5, metallic=0.0,
                 emission=None, emission_strength=0.0, name=None):
    """Give objects a single simple material (replaces their material slots)."""
    mat = make_material(name or f"mat_{objects[0]}", color, roughness, metallic, emission,
                        emission_strength)
    done = []
    for n in objects:
        o = obj_or_raise(n)
        if not hasattr(o.data, "materials"):
            continue
        o.data.materials.clear()
        o.data.materials.append(mat)
        done.append(o.name)
    return {"material": mat.name, "objects": done}
