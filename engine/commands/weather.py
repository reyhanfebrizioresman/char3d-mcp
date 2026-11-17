"""Camera-area weather: saved geometry-node particles, bounded fog and material state."""
import json
import math

import bpy
from mathutils import Vector

from . import command
from .lighting import make_material

KINDS = ("clear", "rain", "snow", "fog", "wind")


def _bounds():
    """Union near-camera frusta across every shot; no whole-world particle system."""
    sc = bpy.context.scene
    cameras = [o for o in sc.objects if o.type == "CAMERA" and not o.name.startswith("__")]
    root = next((o for o in sc.objects if o.get("c3d_outdoor")), None)
    floor = root.matrix_world.translation.z if root else 0.
    points = []
    saved = sc.frame_current, sc.frame_subframe
    try:
        for camera in cameras:
            frames = {sc.frame_start, sc.frame_end}
            # Sample animated cameras, including travel and cuts with different cameras.
            if camera.animation_data:
                frames.update(range(sc.frame_start, sc.frame_end+1, max(1, (sc.frame_end-sc.frame_start)//24)))
            for frame in sorted(frames):
                sc.frame_set(frame)
                mw = camera.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world
                corners = camera.data.view_frame(scene=sc)
                points.append(mw.translation.copy())
                for depth in (3, 12, 24):
                    points.extend(mw @ (v*(depth/abs(v.z))) for v in corners)
    finally:
        sc.frame_set(saved[0], subframe=saved[1])
    if not points:
        center = root.matrix_world.translation if root else Vector((0, 0, 0))
        points = [center+Vector((-8, -8, 0)), center+Vector((8, 8, 0))]
    low = Vector((min(p.x for p in points)-1, min(p.y for p in points)-1, floor+.08))
    high = Vector((max(p.x for p in points)+1, max(p.y for p in points)+1,
                   max(floor+7, max(p.z for p in points)+2)))
    return low, high


def refresh_weather():
    """Called before still/video rendering, after camera edits, and before saving."""
    sc = bpy.context.scene
    if sc.get("c3d_weather_kind", "clear") not in ("rain", "snow", "fog"):
        return
    low, high = _bounds()
    for obj in sc.objects:
        if not obj.get("c3d_weather"):
            continue
        if obj.get("c3d_weather_fog"):
            obj.location = (low+high)/2
            obj.scale = (high-low)/2
        for mod in obj.modifiers:
            if mod.type == "NODES" and mod.node_group:
                nodes = mod.node_group.nodes
                nodes["WeatherPositions"].inputs["Min"].default_value = low
                nodes["WeatherPositions"].inputs["Max"].default_value = high
                nodes["WeatherWrap"].inputs[1].default_value = high
                nodes["WeatherWrap"].inputs[2].default_value = low
        obj["c3d_weather_bounds"] = json.dumps([list(low), list(high)])
    bpy.context.view_layer.update()


def _clear():
    sc = bpy.context.scene
    removed = []
    for obj in list(bpy.data.objects):
        if obj.get("c3d_weather"):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    for pool in (bpy.data.meshes, bpy.data.node_groups, bpy.data.materials):
        for item in list(pool):
            if item.get("c3d_weather") and not item.users:
                pool.remove(item)
    for name, roughness in json.loads(sc.get("c3d_weather_materials", "[]")):
        mat = bpy.data.materials.get(name)
        if mat and mat.node_tree:
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Roughness"].default_value = roughness
    for key in list(sc.keys()):
        if key.startswith("c3d_weather_"):
            del sc[key]
    for coll in list(bpy.data.collections):
        if (coll.get("c3d_weather") or coll.name == "char3d_weather") and not coll.objects and not coll.children:
            bpy.data.collections.remove(coll)
    return removed


def _particles(coll, kind, intensity, wind, seed, low, high):
    """One modifier and shared low-poly instances. Scene Time is evaluated in saved blends."""
    count = round((350+1850*intensity) if kind == "rain" else (200+1000*intensity))
    mesh = bpy.data.meshes.new("WeatherPoints")
    obj = bpy.data.objects.new("Weather_"+kind, mesh)
    coll.objects.link(obj)
    mesh["c3d_weather"] = obj["c3d_weather"] = True
    obj["c3d_role"] = "weather"
    obj["c3d_particle_count"] = count
    group = bpy.data.node_groups.new("WeatherMotion", "GeometryNodeTree")
    group["c3d_weather"] = True
    group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = group.nodes, group.links

    def node(kind, name=None):
        n = nodes.new(kind)
        if name:
            n.name = name
        return n

    line = node("GeometryNodeMeshLine")
    line.inputs["Count"].default_value = count
    random = node("FunctionNodeRandomValue", "WeatherPositions")
    random.data_type = "FLOAT_VECTOR"
    random.inputs["Min"].default_value = low
    random.inputs["Max"].default_value = high
    random.inputs["Seed"].default_value = seed
    time = node("GeometryNodeInputSceneTime")
    velocity = Vector(wind) * .7
    velocity.z -= 7.5 if kind == "rain" else .65
    travel = node("ShaderNodeVectorMath")
    travel.operation = "SCALE"
    travel.inputs[0].default_value = velocity
    links.new(time.outputs["Seconds"], travel.inputs["Scale"])
    add = node("ShaderNodeVectorMath")
    add.operation = "ADD"
    links.new(random.outputs["Value"], add.inputs[0])
    links.new(travel.outputs[0], add.inputs[1])
    wrap = node("ShaderNodeVectorMath", "WeatherWrap")
    wrap.operation = "WRAP"
    wrap.inputs[1].default_value, wrap.inputs[2].default_value = high, low
    links.new(add.outputs[0], wrap.inputs[0])
    setpos = node("GeometryNodeSetPosition")
    links.new(line.outputs["Mesh"], setpos.inputs["Geometry"])
    links.new(wrap.outputs[0], setpos.inputs["Position"])
    ico = node("GeometryNodeMeshIcoSphere")
    ico.inputs["Radius"].default_value = 1
    ico.inputs["Subdivisions"].default_value = 1
    material = make_material("Weather_"+kind, (.60, .75, .87) if kind == "rain" else (.94, .97, 1),
                             roughness=.3, emission_strength=.35 if kind == "rain" else .15)
    material["c3d_weather"] = True
    mat = node("GeometryNodeSetMaterial")
    mat.inputs["Material"].default_value = material
    links.new(ico.outputs["Mesh"], mat.inputs["Geometry"])
    instances = node("GeometryNodeInstanceOnPoints")
    links.new(setpos.outputs[0], instances.inputs["Points"])
    links.new(mat.outputs[0], instances.inputs["Instance"])
    instances.inputs["Scale"].default_value = (.006, .006, .13) if kind == "rain" else (.028, .028, .018)
    instances.inputs["Rotation"].default_value = velocity.to_track_quat("Z", "Y").to_euler()
    # One small evaluated mesh avoids thousands of software-renderer draw objects.
    realize = node("GeometryNodeRealizeInstances")
    links.new(instances.outputs[0], realize.inputs["Geometry"])
    out = node("NodeGroupOutput")
    links.new(realize.outputs[0], out.inputs["Geometry"])
    obj.modifiers.new("Saved weather motion", "NODES").node_group = group
    return obj, count


@command("set_weather")
def set_weather(kind="clear", intensity=.5, wind=None, seed=0):
    """Replace weather. Wind is world XYZ acceleration (m/s²), reused by secondary_motion.

    Rain/snow use deterministic looping geometry nodes over the union of shot-camera
    near frusta (24 m depth); fog uses a bounded, low-density scattering volume whose
    attenuation increases with distance. Reapply after changing intensity/seed/wind;
    camera coverage refreshes on render/save. Clear restores ground roughness and sky.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if isinstance(intensity, bool) or not isinstance(intensity, (float, int)) or not math.isfinite(intensity) or not 0 <= intensity <= 1:
        raise ValueError("intensity must be finite in 0..1")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2147483647:
        raise ValueError("seed must be an integer in 0..2147483647")
    if wind is None:
        wind = (2.5*intensity, .7*intensity, 0) if kind == "wind" else (.45*intensity, 0, 0)
    if (not isinstance(wind, (list, tuple)) or len(wind) != 3 or
            any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or abs(v) > 100 for v in wind)):
        raise ValueError("wind must contain three finite world XYZ values in -100..100")
    removed = _clear()
    sc = bpy.context.scene
    objects, count = [], 0
    if kind != "clear" and intensity > 0:
        sc["c3d_weather_kind"] = kind
        sc["c3d_weather_intensity"] = intensity
        sc["c3d_weather_wind"] = list(wind)
        sc["c3d_weather_seed"] = seed
        coll = bpy.data.collections.new("char3d_weather")
        coll["c3d_weather"] = True
        sc.collection.children.link(coll)
        low, high = _bounds()
        if kind in ("rain", "snow"):
            obj, count = _particles(coll, kind, intensity, wind, seed, low, high)
            objects.append(obj.name)
        if kind == "fog":
            bpy.ops.mesh.primitive_cube_add(size=2)
            obj = bpy.context.object
            for c in list(obj.users_collection):
                c.objects.unlink(obj)
            coll.objects.link(obj)
            obj.name = "Weather_fog"
            obj["c3d_weather"] = obj["c3d_weather_fog"] = obj.data["c3d_weather"] = True
            obj["c3d_role"] = "weather"
            obj.display_type = "WIRE"
            mat = bpy.data.materials.new("Weather_fog")
            mat.use_nodes = True
            mat["c3d_weather"] = True
            nodes, links = mat.node_tree.nodes, mat.node_tree.links
            nodes.remove(nodes.get("Principled BSDF"))
            volume = nodes.new("ShaderNodeVolumeScatter")
            volume.inputs["Color"].default_value = (.72, .79, .84, 1)
            volume.inputs["Density"].default_value = .008 + .025*intensity
            volume.inputs["Anisotropy"].default_value = .15
            links.new(volume.outputs[0], nodes.get("Material Output").inputs["Volume"])
            obj.data.materials.append(mat)
            objects.append(obj.name)
        if kind == "rain":
            materials = {mat for o in sc.objects if o.get("c3d_weather_ground") for mat in o.data.materials}
            saved = []
            for mat in materials:
                bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
                if bsdf:
                    value = bsdf.inputs["Roughness"].default_value
                    saved.append([mat.name, value])
                    bsdf.inputs["Roughness"].default_value = value*(1-intensity)+.13*intensity
            sc["c3d_weather_materials"] = json.dumps(saved)
        refresh_weather()
    from .outdoor import update_sky
    sky = update_sky()
    return {"kind": kind, "intensity": intensity, "wind": list(wind) if kind != "clear" else [0, 0, 0],
            "seed": seed, "objects": objects, "particle_count": count, "removed": removed, "sky": sky,
            "coverage": "shot camera frusta, near 24 m; refreshed on render/save",
            "animation": "saved geometry nodes; deterministic at any frame"}
