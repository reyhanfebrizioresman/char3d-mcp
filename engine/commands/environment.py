"""Local, procedural sets and reusable furniture (meters, front = -Y).

Only tagged environment objects/data are owned here. Lighting rigs, characters and
cameras survive replacement; no downloaded geometry, textures or fonts are needed.
"""
import math
import json
import os
import random

import bpy
from mathutils import Vector

from .. import context
from . import command
from .camera import _subjects
from .lighting import make_material
from .util import scene_bounds, vec

COLLECTION = "char3d_env"
PRESETS = ("podcast_studio", "classroom", "office", "stage", "living_room", "news_desk",
           "city_street", "park", "cafe_terrace", "beach")
PROPS = ("chair", "desk", "table", "microphone", "laptop", "plant", "lamp", "screen",
         "bookshelf", "sofa", "whiteboard", "bench", "stool", "cup", "phone", "book",
         "handheld_microphone")
HANDHELD = ("cup", "phone", "book", "handheld_microphone")
THEMES = {
    "warm": {"wall": (0.32, 0.27, 0.22), "accent": (0.10, 0.40, 0.34),
             "fabric": (0.22, 0.29, 0.27)},
    "cool": {"wall": (0.10, 0.17, 0.25), "accent": (0.04, 0.55, 0.80),
             "fabric": (0.09, 0.17, 0.26)},
    "neutral": {"wall": (0.56, 0.58, 0.56), "accent": (0.28, 0.43, 0.50),
                "fabric": (0.24, 0.27, 0.30)},
}


def _positive_scale(scale):
    scale = float(scale)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be a finite positive number")
    return scale


def _vector(value, label):
    if len(value) != 3 or not all(math.isfinite(float(v)) for v in value):
        raise ValueError(f"{label} must contain three finite numbers")
    return Vector(value)


def _palette(theme, default="warm"):
    colors = dict(THEMES[default])
    if isinstance(theme, str):
        if theme not in THEMES:
            raise ValueError(f"color_theme must be one of {list(THEMES)} or RGB overrides")
        colors.update(THEMES[theme])
    elif theme is not None:
        if not isinstance(theme, dict) or set(theme) - set(colors):
            raise ValueError("color_theme overrides accept wall, accent, fabric RGB keys")
        for key, value in theme.items():
            rgb = _vector(value, key)
            if any(c < 0 or c > 1 for c in rgb):
                raise ValueError(f"{key} RGB must be in 0..1")
            colors[key] = tuple(rgb)
    return colors


def _screen_image(path):
    if not path:
        return None
    path = context.resolve(path, "imports")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    # Validate/load before replacing a set. Reuse existing user images without owning them.
    existing = set(bpy.data.images)
    image = bpy.data.images.load(path, check_existing=True)
    if image not in existing:
        image["c3d_environment"] = True
    return image


def _collection():
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(COLLECTION)
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)
    return coll


def _ground_height(default):
    """Stage surroundings sit below the presenter's unchanged foot plane."""
    stages = [o for o in bpy.context.scene.objects if o.get("c3d_env_stage")]
    return min([default] + [(o.matrix_world @ Vector((0, 0, -0.15))).z for o in stages])


def _sync_ground():
    for obj in bpy.context.scene.objects:
        if obj.get("c3d_role") == "ground":
            original = obj.get("c3d_env_ground_original_z", obj.location.z)
            height = _ground_height(original)
            if height != original:
                obj["c3d_env_ground_original_z"] = original
                obj.location.z = height


@command("clear_environment")
def clear_environment():
    """Remove owned sets/props and unused owned data, preserving all other scene objects."""
    from .holding import clear_grip
    from .outdoor import clear_sky, outdoor_root
    if outdoor_root() is not None:
        from .weather import set_weather
        set_weather("clear")
        clear_sky()
    removed = []
    for obj in bpy.context.scene.objects:
        if "c3d_env_ground_original_z" in obj:
            obj.location.z = obj["c3d_env_ground_original_z"]
            del obj["c3d_env_ground_original_z"]
    for obj in bpy.context.scene.objects:
        if obj.get("c3d_role") == "environment" and obj.get("c3d_hold_layer"):
            clear_grip(obj)
    for obj in list(bpy.data.objects):
        if obj.get("c3d_role") == "environment":
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    for pool in (bpy.data.meshes, bpy.data.lights, bpy.data.materials, bpy.data.images):
        for item in list(pool):
            if item.get("c3d_environment") and item.users == 0:
                pool.remove(item)
    coll = bpy.data.collections.get(COLLECTION)
    if coll is not None and not coll.objects and not coll.children:
        bpy.data.collections.remove(coll)
    return {"removed": removed, "count": len(removed), "collection": COLLECTION}


class _Builder:
    """Build in local meters under one transformable root; share a small material palette."""

    def __init__(self, name, location, scale, rotation=0, colors=None, image=None, seed=0):
        self.coll = _collection()
        self.objects = []
        self.materials = {}
        self.image = image
        self.rng = random.Random(seed)
        self.root = self._link(bpy.data.objects.new(f"Env_{name}", None))
        self.root.location = location
        self.root.scale = (scale,) * 3
        self.root.rotation_euler.z = math.radians(rotation)
        palette = {"wood": (0.31, 0.16, 0.07), "metal": (0.025, 0.035, 0.045),
                   "white": (0.82, 0.85, 0.83), "floor": (0.18, 0.19, 0.20),
                   "leaf": (0.08, 0.28, 0.10), "pot": (0.44, 0.22, 0.12),
                   "screen": (0.025, 0.09, 0.16), **(colors or THEMES["warm"])}
        for key, color in palette.items():
            self.materials[key] = self.material(key, color, metallic=0.5 if key == "metal" else 0)
        self.materials["glow"] = self.material("glow", palette["accent"], emission=2.5)
        self.materials["bulb"] = self.material("bulb", (1.0, 0.72, 0.40), emission=3)

    def _link(self, obj):
        for coll in list(obj.users_collection):
            coll.objects.unlink(obj)
        self.coll.objects.link(obj)
        obj["c3d_role"] = "environment"
        if obj.data is not None:
            obj.data["c3d_environment"] = True
        self.objects.append(obj)
        return obj

    def material(self, name, color, metallic=0, emission=0):
        mat = make_material(f"{self.root.name}_{name}", color, roughness=0.65,
                            metallic=metallic, emission_strength=emission)
        mat["c3d_environment"] = True
        return mat

    def _mesh(self, name, mat):
        obj = self._link(bpy.context.object)
        obj.name = f"{self.root.name}_{name}"
        obj.parent = self.root
        obj.data.materials.append(self.materials[mat] if isinstance(mat, str) else mat)
        return obj

    def box(self, name, loc, dims, mat="wood", bevel=0.015):
        bpy.ops.mesh.primitive_cube_add(size=1)
        obj = self._mesh(name, mat)
        # Bake dimensions in the mesh: bevels stay small and props need no apply-transform ops.
        for v in obj.data.vertices:
            v.co = Vector((v.co.x * dims[0], v.co.y * dims[1], v.co.z * dims[2]))
        obj.location = loc
        if bevel:
            mod = obj.modifiers.new("Soft edges", "BEVEL")
            mod.width = min(bevel, min(dims) * 0.2)
            mod.segments = 2
        return obj

    def cylinder(self, name, loc, radius, depth, mat="metal", radius_top=None):
        bpy.ops.mesh.primitive_cone_add(vertices=16, radius1=radius,
                                       radius2=radius if radius_top is None else radius_top,
                                       depth=depth)
        obj = self._mesh(name, mat)
        obj.location = loc
        return obj

    def rod(self, name, a, b, radius=0.018, mat="metal"):
        a, b = Vector(a), Vector(b)
        obj = self.cylinder(name, (a + b) / 2, radius, (b - a).length, mat)
        obj.rotation_euler = (b - a).to_track_quat("Z", "Y").to_euler()
        return obj

    def light(self, name, loc, target, energy=80, color=(1, 0.78, 0.53), kind="AREA", size=1):
        data = bpy.data.lights.new(f"{self.root.name}_{name}", kind)
        # Parent scaling changes distances/areas; squared power preserves illuminance.
        data.energy = energy * self.root.scale.x ** 2
        data.color = color
        if kind == "AREA":
            data.shape, data.size = "DISK", size
        else:
            data.shadow_soft_size = 0.08
            if kind == "SPOT":
                data.spot_size, data.spot_blend = math.radians(55), 0.55
        obj = self._link(bpy.data.objects.new(data.name, data))
        obj.parent = self.root
        obj.location = loc
        obj.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        return obj

    def display(self, name, loc, width=1.25, height=0.72, board=False):
        x, y, z = loc
        self.box(name + "_frame", loc, (width + 0.10, 0.08, height + 0.10), "metal")
        if self.image is None:
            self.box(name + "_face", (x, y - 0.047, z), (width, 0.012, height),
                     "white" if board else "screen", bevel=0)
            # Original geometric graphics, visible without an external image.
            for i in range(3):
                self.box(name + "_graphic", (x - width * 0.1, y - 0.057, z + height * (0.23 - i * 0.21)),
                         (width * (0.64 - i * 0.12), 0.008, height * 0.025),
                         "accent" if board else "glow", bevel=0)
        else:
            mat = self.material(name + "_image", (1, 1, 1))
            nodes, links = mat.node_tree.nodes, mat.node_tree.links
            tex = nodes.new("ShaderNodeTexImage")
            tex.image = self.image
            bsdf = nodes.get("Principled BSDF")
            links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
            bsdf.inputs["Emission Strength"].default_value = 0.2 if board else 0.8
            # Explicit UVs: left to right and upright as viewed from -Y.
            mesh = bpy.data.meshes.new(name + "_image")
            mesh.from_pydata([(-width/2, 0, -height/2), (width/2, 0, -height/2),
                              (width/2, 0, height/2), (-width/2, 0, height/2)], [], [(0, 1, 2, 3)])
            uv = mesh.uv_layers.new()
            for loop, coord in zip(uv.data, ((0, 0), (1, 0), (1, 1), (0, 1))):
                loop.uv = coord
            obj = self._link(bpy.data.objects.new(f"{self.root.name}_{name}_image", mesh))
            obj.parent = self.root
            obj.location = (x, y - 0.053, z)
            mesh.materials.append(mat)

    def prop(self, kind, loc=(0, 0, 0), rotation=0, scale=1):
        start = len(self.objects)
        x, y, z = loc
        if kind in ("desk", "table"):
            w, d, h = (2.25, 0.85, 1.02) if kind == "desk" else (1.25, 0.65, 0.43)
            self.box(kind + "_top", (0, 0, h - 0.045), (w, d, 0.09))
            for sx in (-1, 1):
                for sy in (-1, 1):
                    self.box(kind + "_leg", (sx * (w/2 - 0.12), sy * (d/2 - 0.10), (h - 0.09)/2),
                             (0.07, 0.07, h - 0.09), "metal")
        elif kind == "chair":
            self.box("chair_seat", (0, 0, 0.46), (0.51, 0.49, 0.11), "fabric", 0.05)
            self.box("chair_back", (0, 0.22, 0.79), (0.51, 0.10, 0.57), "fabric", 0.05)
            for sx in (-1, 1):
                for sy in (-1, 1):
                    self.rod("chair_leg", (sx*0.20, sy*0.19, 0.43), (sx*0.23, sy*0.23, 0.005), 0.025)
        elif kind in ("bench", "stool"):
            width = 1.50 if kind == "bench" else 0.42
            self.box(kind + "_seat", (0, 0, 0.455), (width, 0.42, 0.09), "wood")
            for sx in (-1, 1):
                for sy in (-1, 1):
                    self.rod(kind + "_leg", (sx*(width/2-0.06), sy*0.15, 0.42),
                             (sx*(width/2-0.04), sy*0.18, 0.01), 0.025)
        elif kind == "cup":
            # Grip origin is on the handle; an open rim and dark interior read at close range.
            # Leave room for curled fingers and the wrist above the handle.
            self.cylinder("cup_body", (0.095, 0, -0.030), 0.039, 0.095, "white", radius_top=0.045)
            self.cylinder("cup_inside", (0.095, 0, 0.018), 0.036, 0.002, "wood")
            bpy.ops.mesh.primitive_torus_add(major_segments=24, minor_segments=8,
                                           major_radius=0.026, minor_radius=0.006)
            handle = self._mesh("cup_handle", "white")
            handle.location = (0.026, 0, -0.012)
            handle.rotation_euler.x = math.pi/2
            handle.scale.x = 1.4
        elif kind == "phone":
            self.box("phone_body", (0, 0, 0.025), (0.012, 0.074, 0.15), "metal", 0.006)
            self.box("phone_glass", (0.007, 0, 0.025), (0.002, 0.064, 0.13), "screen", 0.002)
        elif kind == "book":
            self.box("book_pages", (0, 0, 0.04), (0.025, 0.14, 0.20), "white", 0.002)
            for sy in (-1, 1):
                self.box("book_cover", (sy*0.015, 0, 0.04), (0.005, 0.15, 0.21), "accent", 0.002)
            self.box("book_spine", (0, -0.073, 0.04), (0.034, 0.008, 0.21), "accent", 0.002)
        elif kind == "handheld_microphone":
            self.cylinder("handheld_mic_body", (0, 0, 0.025), 0.018, 0.18)
            self.cylinder("handheld_mic_grille", (0, 0, 0.14), 0.030, 0.065, "fabric")
        elif kind == "microphone":
            self.cylinder("mic_clamp", (0, 0, 0.02), 0.065, 0.04)
            self.rod("mic_arm_lower", (0, 0, 0.04), (0, 0.16, 0.40))
            self.rod("mic_arm_upper", (0, 0.16, 0.40), (0.28, 0.30, 0.53))
            self.rod("mic_body", (0.28, 0.30, 0.44), (0.28, 0.30, 0.61), 0.042)
            self.cylinder("mic_grille", (0.28, 0.30, 0.62), 0.045, 0.08, "fabric")
        elif kind == "laptop":
            self.box("laptop_base", (0, 0, 0.015), (0.38, 0.27, 0.03), "metal")
            self.display("laptop_screen", (0, 0.115, 0.15), 0.34, 0.22)
            self.box("laptop_keys", (0, -0.015, 0.033), (0.31, 0.15, 0.008), "fabric")
        elif kind == "plant":
            self.cylinder("plant_pot", (0, 0, 0.20), 0.18, 0.40, "pot", radius_top=0.23)
            for i in range(9):
                angle = i * 2.4
                tip = Vector((0.27*math.cos(angle), 0.27*math.sin(angle), 0.75 + (i % 3)*0.22))
                self.rod("plant_stem", (0, 0, 0.36), tip, 0.009, "leaf")
                bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1)
                leaf = self._mesh("plant_leaf", "leaf")
                leaf.location = tip
                leaf.scale = (0.09, 0.07, 0.25)
                leaf.rotation_euler = Vector((tip.x, tip.y, 0.25)).to_track_quat("Z", "Y").to_euler()
        elif kind == "lamp":
            self.cylinder("lamp_base", (0, 0, 0.025), 0.23, 0.05)
            self.rod("lamp_stem", (0, 0, 0.04), (0, 0, 1.52), 0.022)
            self.cylinder("lamp_shade", (0, 0, 1.52), 0.29, 0.32, "white", radius_top=0.17)
            self.cylinder("lamp_bulb", (0, 0, 1.35), 0.11, 0.02, "bulb")
            self.light("lamp_practical", (0, 0, 1.32), (0, -0.3, 0.2), 45, kind="POINT")
        elif kind == "screen":
            self.display("screen", (0, 0, 1.28))
            self.rod("screen_stand", (0, 0, 0.04), (0, 0, 1.10), 0.045)
            self.box("screen_base", (0, 0, 0.025), (0.55, 0.35, 0.05), "metal")
        elif kind == "whiteboard":
            self.display("whiteboard", (0, 0, 1.50), 1.9, 1.05, board=True)
            for sx in (-1, 1):
                self.rod("whiteboard_leg", (sx*0.78, 0.04, 0.04), (sx*0.78, 0.04, 1.48), 0.025)
                self.box("whiteboard_foot", (sx*0.78, 0, 0.035), (0.12, 0.58, 0.07), "metal")
            self.box("whiteboard_tray", (0, -0.10, 0.93), (1.95, 0.16, 0.035), "metal")
        elif kind == "bookshelf":
            self.box("shelf_back", (0, 0.17, 1.0), (1.0, 0.05, 2.0))
            for sx in (-1, 1):
                self.box("shelf_side", (sx*0.49, 0, 1.0), (0.05, 0.4, 2.0))
            for row in range(5):
                height = 0.06 + row * 0.47
                self.box("shelf_board", (0, 0, height), (1.0, 0.42, 0.045))
                if row < 4:
                    for i in range(6):
                        h = self.rng.uniform(0.22, 0.36)
                        self.box("shelf_book", (-0.36+i*0.13, -0.03, height+0.025+h/2),
                                 (0.08, 0.23, h), ("accent", "white", "fabric")[i % 3], 0.004)
        elif kind == "sofa":
            # A 46 cm cushion top lets adult shins reach the floor without a perched pose.
            self.box("sofa_base", (0, 0, 0.20), (2.25, 0.85, 0.28), "fabric", 0.08)
            self.box("sofa_back", (0, 0.36, 0.62), (2.25, 0.20, 0.70), "fabric", 0.07)
            for sx in (-1, 1):
                self.box("sofa_arm", (sx*1.08, 0, 0.47), (0.20, 0.86, 0.40), "fabric", 0.07)
                self.box("sofa_cushion", (sx*0.52, -0.04, 0.38), (0.95, 0.65, 0.16), "white", 0.06)
                for sy in (-1, 1):
                    self.box("sofa_foot", (sx*0.9, sy*0.30, 0.07), (0.09, 0.09, 0.14), "metal")
        parts = self.objects[start:]
        if kind in ("chair", "sofa", "bench", "stool"):
            anchor = parts[0]
            # Usable sitting centers are near the sofa's front so calves clear its deep base.
            centers = ([[-0.52, -0.15, 0.26], [0.52, -0.15, 0.26]] if kind == "sofa" else
                       [[-0.45, 0, 0.045], [0.45, 0, 0.045]] if kind == "bench" else
                       [[0, 0, 0.055 if kind == "chair" else 0.045]])
            anchor["c3d_seat_centers"] = json.dumps(centers)
            anchor["c3d_seat_surface_height"] = centers[0][2]
            anchor["c3d_seat_front"] = [0.0, -1.0, 0.0]
            anchor["c3d_seat_floor"] = -anchor.location.z
            if kind == "sofa":
                anchor["c3d_seat_armrests"] = json.dumps([[-1.0, -0.1, 0.47], [1.0, -0.1, 0.47]])
            for part in parts:
                part["c3d_seat_anchor"] = anchor.name
            if start == 1:  # standalone add_prop root (sets can contain several chairs)
                self.root["c3d_seat_anchor"] = anchor.name
        # Transform the whole prop, including its light directions, in the set's local space.
        angle = math.radians(rotation)
        for obj in self.objects[start:]:
            p = obj.location * scale
            obj.location = (x + p.x*math.cos(angle) - p.y*math.sin(angle),
                            y + p.x*math.sin(angle) + p.y*math.cos(angle), z + p.z)
            obj.rotation_euler.rotate_axis("Z", angle)
            obj.scale *= scale
            if obj.type == "LIGHT":
                obj.data.energy *= scale ** 2

    def room(self, stage=False):
        # No front/side wall or ceiling: camera and key lights have an unobstructed path.
        self.box("floor", (0, -0.5, -0.045 if not stage else -0.195),
                 (12, 11, 0.10), "floor", 0)
        self.box("back_wall", (0, 2.6, 2.1), (16, 0.14, 4.6 if stage else 4.4), "wall", 0)
        self.box("skirting", (0, 2.50, 0.10), (16, 0.06, 0.20), "metal")

    def result(self):
        bpy.context.view_layer.update()
        return {"collection": COLLECTION, "root": self.root.name,
                "objects": [o.name for o in self.objects],
                "lights": [o.name for o in self.objects if o.type == "LIGHT"],
                "screen_image": self.image.filepath if self.image else None}


def _build_set(b, preset, variant):
    b.room(stage=preset == "stage")
    if preset == "stage":
        b.root["c3d_env_stage"] = True
    side = -1 if variant % 2 else 1
    if preset == "podcast_studio":
        b.prop("desk", (0, -0.87, 0))
        for sx in (-1, 1):
            b.prop("chair", (sx*0.86, 0.50, 0), rotation=-sx*12)
            b.prop("microphone", (sx*0.80, -0.77, 1.02), rotation=-sx*25)
        for x in (-2.2, -1.35, 1.35, 2.2):
            b.box("acoustic_panel", (x, 2.43, 1.75), (0.66, 0.18, 1.55), "fabric", 0.04)
            for i in range(4):
                b.box("panel_rib", (x-0.23+i*0.15, 2.32, 1.75), (0.035, 0.035, 1.4), "metal")
        b.box("neon_sign_back", (0, 2.44, 2.15), (1.65, 0.12, 0.65), "metal")
        for z in (1.95, 2.35):
            b.box("neon_sign_strip", (0, 2.36, z), (1.40, 0.035, 0.025), "glow")
        b.box("neon_sign_wave", (0, 2.36, 2.15), (0.8, 0.035, 0.035), "glow")
        b.light("neon_practical", (0, 2.1, 2.15), (0, 0, 1.3), 65,
                color=tuple(b.materials["accent"].diffuse_color[:3]))
        b.prop("plant", (side*2.5, 1.2, 0), scale=1.25)
    elif preset == "classroom":
        b.prop("whiteboard", (0, 1.7, 0), scale=1.25)
        for sx in (-1, 1):
            for y in (-0.65, 1.05):
                b.prop("desk", (sx*2.20, y, 0), scale=0.66)
                b.prop("chair", (sx*2.20, y+0.65, 0), scale=0.9)
        b.prop("bookshelf", (-side*3.55, 2.2, 0))
        b.light("board_wash", (0, 1.0, 3.5), (0, 1.7, 1.4), 130, (0.85, 0.93, 1), size=2)
    elif preset == "office":
        b.prop("desk", (0, -0.90, 0))
        b.prop("chair", (0.85, 0.45, 0), rotation=-15)
        b.prop("screen", (-0.70, -0.86, 1.02), scale=0.40)
        b.prop("laptop", (0.65, -0.94, 1.02), rotation=12)
        b.prop("bookshelf", (-side*2.55, 2.2, 0), scale=1.15)
        # Opaque emissive sky avoids costly glass/refraction and external HDRIs.
        sky = b.material("sky", (0.29, 0.57, 0.82), emission=0.6)
        b.box("window_sky", (side*1.65, 2.49, 2.05), (2.1, 0.025, 2.0), sky)
        for x in (0.55, 1.65, 2.75):
            b.box("window_mullion", (side*x, 2.44, 2.05), (0.06, 0.08, 2.1), "white")
        for z in (1.02, 2.05, 3.08):
            b.box("window_frame", (side*1.65, 2.44, z), (2.25, 0.08, 0.06), "white")
        b.light("window_daylight", (side*1.65, 2.1, 2.6), (0, -0.5, 1.0), 180, (0.68, 0.84, 1), size=2)
        b.prop("plant", (side*2.8, 1.0, 0))
    elif preset == "stage":
        # Platform top is at the existing foot plane: the character is never moved.
        b.box("raised_platform", (0, 0.25, -0.08), (6.2, 3.9, 0.16), "metal")["char3d_walkable"] = True
        b.box("platform_edge", (0, -1.71, -0.075), (6.2, 0.02, 0.025), "glow")
        for sx in (-1, 1):
            for i in range(9):
                b.cylinder("curtain_fold", (sx*(2.05+i*0.23), 2.28, 1.85), 0.17, 3.7, "fabric")
            b.rod("spotlight_bar", (sx*2.5, 0.6, 3.4), (sx*2.5, 1.6, 3.4), 0.045)
            b.cylinder("spotlight_housing", (sx*2.5, 0.8, 3.35), 0.16, 0.25)
            b.light("stage_spot", (sx*2.5, 0.8, 3.2), (sx*0.4, -0.25, 0),
                    220, (1, 0.72, 0.43) if sx == side else (0.35, 0.65, 1), "SPOT")
        b.display("stage_screen", (0, 2.40, 2.0), 3.55, 1.9)
    elif preset == "living_room":
        b.prop("sofa", (0, 1.20, 0))
        b.prop("table", (-side*1.15, -0.75, 0))
        b.box("rug", (0, 0.15, 0.013), (4.5, 3.2, 0.016), "fabric", 0.01)
        b.prop("lamp", (side*1.75, 1.55, 0))
        b.prop("plant", (-side*2.2, 1.5, 0))
        for sx in (-1, 1):
            b.box("art_frame", (sx*0.85, 2.45, 2.10), (1.1, 0.08, 1.10), "metal")
            b.box("art_canvas", (sx*0.85, 2.40, 2.10), (0.96, 0.02, 0.96), "white")
            art = b.box("art_geometry", (sx*0.85, 2.38, 2.10), (0.50, 0.02, 0.50), "accent")
            art.rotation_euler.y = math.radians(30 + variant % 4 * 10)
    elif preset == "news_desk":
        b.box("anchor_desk_top", (0, -0.92, 1.07), (2.9, 1.0, 0.12), "metal", 0.04)
        b.box("anchor_desk_front", (0, -1.27, 0.55), (2.7, 0.16, 0.95), "wall", 0.04)
        for sx in (-1, 1):
            b.box("anchor_desk_side", (sx*1.23, -0.93, 0.53), (0.12, 0.65, 0.97), "metal")
        b.box("desk_light_strip", (0, -1.36, 0.85), (2.5, 0.025, 0.045), "glow")
        for x in (-2.6, 0, 2.6):
            b.display("news_screen", (x, 2.42, 1.95), 2.45, 1.65)
        b.box("screen_wall_strip", (0, 2.32, 0.7), (8.2, 0.03, 0.035), "glow")
        b.light("screen_wall_wash", (0, 2, 2.8), (0, 0, 1), 100, (0.3, 0.65, 1), size=3)


@command("set_environment")
def set_environment(preset, subject=None, scale=1.0, variant=0, color_theme=None,
                    screen_image=None):
    """Replace the set around subject feet, auto-sized to its height; never move the subject."""
    if preset not in PRESETS:
        raise ValueError(f"preset must be one of {list(PRESETS)}")
    scale = _positive_scale(scale)
    if isinstance(variant, bool) or not isinstance(variant, int) or variant < 0:
        raise ValueError("variant must be a nonnegative integer")
    colors = _palette(color_theme, "cool" if preset in ("news_desk", "stage", "podcast_studio") else "warm")
    targets = _subjects(subject)
    lo, hi = scene_bounds(targets) if targets else (None, None)
    origin = Vector((0, 0, 0)) if lo is None else Vector(((lo.x+hi.x)/2, (lo.y+hi.y)/2, lo.z))
    # A character's root is stable across asymmetric speaking/pointing poses.
    roots = [bpy.data.objects[n] for n in subject] if subject else [
        o for o in bpy.context.scene.objects if o.type == "ARMATURE" and o.visible_get()
        and not o.name.startswith("__")]
    if len(roots) == 1 and roots[0].type == "ARMATURE":
        origin.x, origin.y = roots[0].matrix_world.translation.xy
    unit = scale * (max(hi.z - lo.z, 0.1) / 1.75 if lo is not None else 1)
    image = _screen_image(screen_image)
    # Keep a loaded image alive while unused data from the previous set is collected.
    fake_user = image.use_fake_user if image else False
    if image:
        image.use_fake_user = True
    try:
        cleared = clear_environment()
        b = _Builder(preset, origin, unit, colors=colors, image=image, seed=variant)
        from .outdoor import PRESETS as OUTDOORS, build_outdoor
        if preset in OUTDOORS:
            from .lighting import _clear_c3d
            _clear_c3d("ground")
            build_outdoor(b, preset, variant)
        else:
            _build_set(b, preset, variant)
        bpy.context.view_layer.update()
        _sync_ground()
    finally:
        if image:
            image.use_fake_user = fake_user
    return {**b.result(), "preset": preset, "variant": variant, "scale": scale,
            "unit_scale": round(unit, 4), "standing_position": vec(origin),
            "replaced": cleared["count"], "color_theme": colors,
            "camera_direction": "-Y; central aisle open, desks in foreground"}


@command("add_prop")
def add_prop(kind, location=None, rotation_z=0, scale=1.0, screen_image=None):
    """Add one transformable furniture group; location is its floor/base center in world meters."""
    if kind not in PROPS:
        raise ValueError(f"kind must be one of {list(PROPS)}")
    scale = _positive_scale(scale)
    spawn = location is None and kind in HANDHELD
    location = _vector(location if location is not None else (0, 0, 0), "location")
    if not math.isfinite(float(rotation_z)):
        raise ValueError("rotation_z must be finite (degrees)")
    image = _screen_image(screen_image)
    b = _Builder(kind, location, scale, rotation=rotation_z, image=image)
    b.prop(kind)
    b.root["c3d_prop_kind"] = kind
    b.root["c3d_prop_spawn_at_hand"] = spawn
    if spawn:
        from .holding import _palm
        from .anim import semantic_map
        rigs = [o for o in bpy.context.scene.objects if o.type == "ARMATURE" and o.visible_get()
                and not o.name.startswith("__") and "hand.R" in semantic_map(o)]
        if rigs:
            rig = rigs[-1]
            bone, palm = _palm(rig, "R")
            bpy.context.view_layer.update()
            b.root.matrix_world = rig.matrix_world @ rig.pose.bones[bone].matrix @ palm
            b.root.scale = (scale,)*3
            location = b.root.matrix_world.translation.copy()
    return {**b.result(), "kind": kind, "location": vec(location),
            "rotation_z": rotation_z, "scale": scale}
