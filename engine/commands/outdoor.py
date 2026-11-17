"""Original low-poly outdoor sets and a saved, procedural gradient sky."""
import math

import bpy
from mathutils import Vector

PRESETS = ("city_street", "park", "cafe_terrace", "beach")
DAYLIGHT = {
    # elevation, sun energy, sun RGB, horizon RGB, zenith RGB, world strength
    "noon": (65, 3.0, (1, .96, .85), (.62, .79, .89), (.12, .39, .72), .65),
    "sunset": (8, 2.0, (1, .42, .16), (.95, .40, .19), (.17, .23, .47), .4),
    "overcast": (55, .35, (.85, .91, 1), (.62, .68, .72), (.35, .43, .52), .7),
    "night": (25, .12, (.42, .56, 1), (.035, .055, .12), (.004, .009, .03), .18),
}


def outdoor_root():
    return next((o for o in bpy.context.scene.objects if o.get("c3d_outdoor")), None)


def clear_sky():
    sc = bpy.context.scene
    root = outdoor_root()
    if root is not None and "c3d_outdoor_shadow_pool" in root:
        sc.eevee.shadow_pool_size = root["c3d_outdoor_shadow_pool"]
        sc.eevee.shadow_resolution_scale = root["c3d_outdoor_shadow_resolution"]
    if "c3d_outdoor_previous_world" in sc:
        owned = sc.world
        sc.world = (sc.get("c3d_outdoor_previous_world_id") or
                    bpy.data.worlds.get(sc["c3d_outdoor_previous_world"]))
        del sc["c3d_outdoor_previous_world"]
        if "c3d_outdoor_previous_world_id" in sc:
            del sc["c3d_outdoor_previous_world_id"]
        if owned and owned.get("c3d_environment") and not owned.users:
            bpy.data.worlds.remove(owned)


def configure_sky(preset="noon", strength=1, rotate=0, background=None):
    """World Normal -> ramp works in CPU Eevee without an HDRI or sky LUT."""
    root = outdoor_root()
    if root is None:
        return None
    sc = bpy.context.scene
    if "c3d_outdoor_shadow_pool" not in root:
        root["c3d_outdoor_shadow_pool"] = sc.eevee.shadow_pool_size
        root["c3d_outdoor_shadow_resolution"] = sc.eevee.shadow_resolution_scale
    # Bound the software renderer's shadow atlas for large outdoor backdrops.
    sc.eevee.shadow_pool_size = "128"
    sc.eevee.shadow_resolution_scale = .5
    if "c3d_outdoor_previous_world" not in sc:
        sc["c3d_outdoor_previous_world"] = sc.world.name if sc.world else ""
        if sc.world:
            # An ID reference keeps the original world alive across save/open.
            sc["c3d_outdoor_previous_world_id"] = sc.world
        w = bpy.data.worlds.new("c3d_outdoor_world")
        w["c3d_environment"] = True
        sc.world = w
        w.use_nodes = True
        nodes, links = w.node_tree.nodes, w.node_tree.links
        coord = nodes.new("ShaderNodeTexCoord")
        separate = nodes.new("ShaderNodeSeparateXYZ")
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.name = "OutdoorSky"
        ramp.color_ramp.elements[0].position = 0
        ramp.color_ramp.elements[1].position = .8
        links.new(coord.outputs["Normal"], separate.inputs[0])
        links.new(separate.outputs["Z"], ramp.inputs[0])
        links.new(ramp.outputs[0], nodes.get("Background").inputs["Color"])
    key = preset if preset in DAYLIGHT else "noon"
    elevation, energy, rgb, horizon, zenith, ambient = DAYLIGHT[key]
    root["c3d_outdoor_lighting"] = key
    root["c3d_outdoor_strength"] = strength
    root["c3d_outdoor_rotate"] = rotate
    if background is not None:
        root["c3d_outdoor_background"] = list(background[:3])
    elif "c3d_outdoor_background" in root:
        del root["c3d_outdoor_background"]
    return update_sky()


def update_sky():
    root = outdoor_root()
    if root is None:
        return None
    sc = bpy.context.scene
    key = root.get("c3d_outdoor_lighting", "noon")
    elevation, energy, rgb, horizon, zenith, ambient = DAYLIGHT[key]
    strength = root.get("c3d_outdoor_strength", 1.0)
    kind, intensity = sc.get("c3d_weather_kind", "clear"), sc.get("c3d_weather_intensity", 0.)
    cloud = intensity if kind in ("rain", "snow", "fog") else 0
    dim = 1 - cloud * (.65 if kind == "rain" else .35)
    override = root.get("c3d_outdoor_background")
    ramp = sc.world.node_tree.nodes.get("OutdoorSky")
    for element, color in zip(ramp.color_ramp.elements, (horizon, zenith)):
        c = Vector(override if override is not None else color)
        grey = sum(c)/3
        c = c.lerp(Vector((grey, grey, grey)), cloud * .7) * dim
        element.color = (*c, 1)
    sc.world.node_tree.nodes.get("Background").inputs["Strength"].default_value = ambient * strength
    sun = next(o for o in sc.objects if o.get("c3d_outdoor_sun"))
    sun.data.energy = energy * strength * dim
    sun.data.color = rgb
    sun.data.angle = math.radians(.8 + 15*cloud + (18 if key == "overcast" else 0))
    az, el = math.radians(40 + root.get("c3d_outdoor_rotate", 0)), math.radians(elevation)
    direction = Vector((math.sin(az)*math.cos(el), -math.cos(az)*math.cos(el), math.sin(el)))
    sun.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    sun["c3d_sun_elevation"] = elevation
    return {"preset": key, "sun": sun.name, "elevation": elevation,
            "energy": round(sun.data.energy, 4), "sky": "gradient"}


def _ground(b, name, loc, dims, mat):
    o = b.box(name, loc, dims, mat, bevel=0)
    o["char3d_walkable"] = True
    o["c3d_weather_ground"] = True
    return o


def _crown(b, name, loc, scale, mat="leaf"):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1)
    o = b._mesh(name, mat)
    o.location, o.scale = loc, scale
    return o


def _tree(b, x, y, size=1, palm=False):
    h = (4.1 if palm else 2.8)*size
    b.rod("palm_trunk" if palm else "tree_trunk", (x, y, 0), (x+.15*size, y, h), .12*size, "wood")
    if palm:
        for i in range(7):
            a = i*math.tau/7
            # Broad folded leaf ribbons, rather than expensive hair/alpha cards.
            verts = [(x+.15*size, y, h),
                     (x+math.cos(a)*.9*size, y+math.sin(a)*.9*size, h+.3*size),
                     (x+math.cos(a)*1.8*size, y+math.sin(a)*1.8*size, h-.55*size),
                     (x+math.cos(a)*.8*size-math.sin(a)*.35*size,
                      y+math.sin(a)*.8*size+math.cos(a)*.35*size, h+.05*size)]
            mesh = bpy.data.meshes.new("PalmLeaf")
            mesh.from_pydata(verts, [], [(0, 1, 3), (1, 2, 3)])
            o = b._link(bpy.data.objects.new(b.root.name+"_palm_leaf", mesh))
            o.parent = b.root
            mesh.materials.append(b.materials["leaf"])
    else:
        for dx, dy, dz, r in ((0, 0, 0, 1.05), (-.5, 0, -.35, .8), (.45, .2, -.25, .85)):
            _crown(b, "tree_crown", (x+dx*size, y+dy*size, h+dz*size),
                   (r*size, r*.85*size, r*1.15*size), "leaf" if dx == 0 else "leaf_light")


def _lamp(b, x, y):
    b.cylinder("street_lamp_base", (x, y, .12), .16, .24)
    b.rod("street_lamp_post", (x, y, .15), (x, y, 3.15), .045)
    b.cylinder("street_lamp_glass", (x, y, 3.15), .16, .30, "bulb")
    b.cylinder("street_lamp_cap", (x, y, 3.36), .27, .14, radius_top=.08)
    b.light("street_lamp_practical", (x, y, 3.1), (x, y, 0), 65, kind="POINT")


def _bench(b, x, y):
    start = len(b.objects)
    b.prop("bench", (x, y, 0))
    anchor = b.objects[start]
    for z in (.69, .88):
        b.box("bench_back_slats", (x, y+.20, z), (1.5, .065, .12))
    for dx in (-.63, .63):
        b.rod("bench_back_support", (x+dx, y+.17, .2), (x+dx, y+.20, .98), .025)
    for part in b.objects[start:]:
        part["c3d_seat_anchor"] = anchor.name
    return anchor


def _umbrella(b, x, y, radius=1.45):
    b.cylinder("umbrella_base", (x, y, .06), .30, .12)
    b.rod("umbrella_pole", (x, y, .08), (x, y, 2.65), .035)
    for i in range(12):
        a, c = i*math.tau/12, (i+1)*math.tau/12
        verts = [(x, y, 2.65), (x+radius*math.cos(a), y+radius*math.sin(a), 2.27),
                 (x+radius*math.cos(c), y+radius*math.sin(c), 2.27)]
        mesh = bpy.data.meshes.new("UmbrellaPanel")
        mesh.from_pydata(verts, [], [(0, 1, 2)])
        o = b._link(bpy.data.objects.new(b.root.name+"_umbrella_panel", mesh))
        o.parent = b.root
        mesh.materials.append(b.materials["accent" if i % 2 else "white"])


def _facade(b, x, y, width=6, height=7):
    b.box("building_facade", (x, y, height/2), (width, 2, height), "wall", 0)
    b.box("building_cornice", (x, y-1.04, height-.15), (width+.15, .18, .22), "white")
    for dx in range(max(1, int(width/1.6))):
        for row in range(max(1, int((height-1)/2))):
            xx, zz = x-width/2+.8+dx*1.6, 1.4+row*2
            b.box("window_frame", (xx, y-1.03, zz), (.96, .06, 1.3), "white", 0)
            b.box("window_glass", (xx, y-1.07, zz), (.82, .02, 1.16), "glass", 0)
            b.box("window_mullion", (xx, y-1.09, zz), (.035, .02, 1.16), "white", 0)


def build_outdoor(b, preset, variant):
    b.root["c3d_outdoor"] = preset
    side = -1 if variant % 2 else 1
    for name, color in {"grass": (.19, .34, .12), "path": (.56, .50, .39),
                        "sand": (.73, .58, .36), "sea": (.035, .36, .43),
                        "glass": (.12, .28, .34), "leaf_light": (.24, .43, .13),
                        "road": (.075, .09, .105)}.items():
        b.materials[name] = b.material(name, color)
    if preset == "city_street":
        _ground(b, "sidewalk", (0, 42, -.1), (220, 90, .2), "path")
        _ground(b, "road", (0, -53, -.06), (220, 100, .12), "road")
        _ground(b, "curb", (0, -3, -.03), (220, .20, .16), "white")
        for x in range(-36, 37, 4):
            b.box("road_dash", (x, -6, .004), (1.8, .10, .005), "white", 0)
        for x in range(-24, 25, 6):
            _facade(b, x, 7.2, height=b.rng.uniform(6.5, 10))
        _bench(b, -side*2.5, 1.3)
        _lamp(b, side*3, 1.7)
        b.cylinder("trash_bin", (-side*3.8, 1.4, .42), .23, .84)
        b.cylinder("trash_bin_lid", (-side*3.8, 1.4, .86), .26, .07, "accent")
        b.box("parked_car_body", (side*4.8, -4.25, .48), (3.6, 1.55, .60), "accent", .12)
        b.box("parked_car_cabin", (side*4.8, -4.25, 1.03), (1.9, 1.35, .65), "glass", .12)
        for dx in (-1.1, 1.1):
            for dy in (-.75, .75):
                wheel = b.cylinder("car_wheel", (side*4.8+dx, -4.25+dy, .3), .30, .14)
                wheel.rotation_euler.x = math.pi/2
        for dx in (-1.76, 1.76):
            b.box("car_lights", (side*4.8+dx, -4.25, .65), (.03, .95, .14), "bulb")
    elif preset == "park":
        _ground(b, "grass", (0, 0, -.08), (220, 220, .14), "grass")
        _ground(b, "park_path", (0, 0, -.025), (3, 220, .05), "path")
        _ground(b, "cross_path", (0, 3, -.025), (220, 2, .05), "path")
        bench = _bench(b, -side*2.6, 1.2)
        bench.data.materials[0] = b.materials["accent"]
        _lamp(b, side*2.6, 2.1)
        for x, y in ((-4.5, 4.6), (4.7, 5), (-6.5, 0), (6, 0), (-3.8, 9), (4, 11)):
            _tree(b, x, y, b.rng.uniform(.85, 1.2))
        for x in (-3, 3):
            for y in (5.2, 7):
                _crown(b, "bush", (x, y, .45), (.7, .55, .55))
        for y in (18, 32, 55):
            for x in range(-44, 45, 7):
                _tree(b, x+b.rng.uniform(-1, 1), y, b.rng.uniform(1, 1.8))
    elif preset == "cafe_terrace":
        _ground(b, "terrace", (0, 0, -.06), (220, 220, .12), "path")
        # Large pavers in the acting area only.
        for x in range(-7, 8):
            b.box("paving_joint", (x, 0, .001), (.014, 14, .002), "floor", 0)
        for y in range(-7, 8):
            b.box("paving_joint", (0, y, .001), (14, .014, .002), "floor", 0)
        _facade(b, 0, 6, width=26, height=8)
        for x in (-3, 0, 3):
            b.box("shop_window", (x, 4.96, 1.5), (2.65, .05, 2.7), "glass")
            b.box("shop_window_frame", (x-1.4, 4.9, 1.5), (.1, .1, 3), "white")
        for x in range(-10, 11):
            awning = b.box("striped_awning", (x*.5, 4.15, 3.25), (.5, 1.8, .08),
                           "accent" if x % 2 else "white", 0)
            awning.rotation_euler.x = math.radians(12)
        for x in (-2.7, 2.7):
            b.cylinder("cafe_table", (x, 1.65, .75), .53, .08, "wood")
            b.cylinder("cafe_table_pedestal", (x, 1.65, .36), .07, .72)
            b.cylinder("cafe_table_base", (x, 1.65, .04), .20, .08)
            b.prop("chair", (x-.95, 1.65, 0), rotation=90)
            b.prop("chair", (x+.95, 1.65, 0), rotation=-90)
        _umbrella(b, side*2.7, 2.3)
        for x in (-5, 5):
            b.box("planter", (x, 2.8, .35), (1.4, .65, .7), "pot")
            for dx in (-.4, .2):
                _crown(b, "planter_bush", (x+dx, 2.8, .85), (.48, .4, .55))
        for x in (-19, 19):
            _facade(b, x, 18, width=12, height=10)
    else:
        _ground(b, "sand", (0, -49, -.09), (400, 110, .18), "sand")
        # Gentle original waves in one mesh, no displacement/subdivision at render time.
        verts, faces = [], []
        for j in range(49):
            y = 6+j*6
            for i in range(49):
                x = -200+i*400/48
                verts.append((x, y, -.09+.035*math.sin(x*.6+y*1.6)))
                if i and j:
                    k = j*49+i
                    faces.append((k-50, k-49, k, k-1))
        mesh = bpy.data.meshes.new("SeaWaves")
        mesh.from_pydata(verts, [], faces)
        o = b._link(bpy.data.objects.new(b.root.name+"_sea_waves", mesh))
        o.parent = b.root
        mesh.materials.append(b.materials["sea"])
        bsdf = b.materials["sea"].node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Roughness"].default_value = .24
        noise = b.materials["sea"].node_tree.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 5
        bump = b.materials["sea"].node_tree.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = .22
        bump.inputs["Distance"].default_value = .08
        links = b.materials["sea"].node_tree.links
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        for x, y in ((-4, 3.5), (4.3, 4), (-7, 6), (8, 5)):
            _tree(b, x, y, palm=True)
        start = len(b.objects)
        b.prop("chair", (-side*2.7, 1.3, 0))
        # Folding canvas deck chair with a level sitting pad for the seat IK contract.
        seat = next(o for o in reversed(b.objects) if "c3d_seat_centers" in o)
        seat["c3d_seat_kind"] = "deck_chair"
        for part in b.objects[start:]:
            if "chair_back" in part.name:
                part.rotation_euler.x = math.radians(-15)
                part.location.y += .07
            if "chair_leg" in part.name:
                part.data.materials[0] = b.materials["wood"]
        for dx in (-.27, .27):
            leg = b.rod("deck_chair_cross_leg", (-side*2.7+dx, 1.55, .01),
                        (-side*2.7+dx, 1.05, .50), .025, "wood")
            leg["c3d_seat_anchor"] = seat.name
        _umbrella(b, -side*3.8, 2.1)
        for x, y in ((-2, 4.8), (2, 5.4), (5, 2.5)):
            _crown(b, "beach_rock", (x, y, .14), (.3, .23, .2), "path")
    data = bpy.data.lights.new("OutdoorSun", "SUN")
    sun = b._link(bpy.data.objects.new("OutdoorSun", data))
    sun["c3d_outdoor_sun"] = True
    # A SUN is directional and deliberately not parented to the scalable set root.
    configure_sky()
