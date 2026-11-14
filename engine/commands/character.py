"""Procedural humanoid characters (skin-modifier body built from joint landmarks).

The mesh stores its landmarks in obj["c3d_landmarks"], so auto_rig_humanoid can place
bones exactly where the body was built.
"""
import json

import bpy
from mathutils import Vector

from . import command
from .landmarks import STYLES, human_landmarks
from .scene import _describe

# (landmark, neighbour) edges of the skin skeleton
EDGES = [
    ("hips", "waist"), ("waist", "chest"), ("chest", "upper_chest"),
    ("upper_chest", "neck_base"), ("neck_base", "neck"), ("neck", "chin"),
    ("chin", "head_center"), ("head_center", "head_top"),
]
for s in ("L", "R"):
    EDGES += [
        ("upper_chest", f"clavicle.{s}"), (f"clavicle.{s}", f"shoulder.{s}"),
        (f"shoulder.{s}", f"elbow.{s}"), (f"elbow.{s}", f"wrist.{s}"),
        (f"wrist.{s}", f"hand_tip.{s}"),
        ("hips", f"hip.{s}"), (f"hip.{s}", f"knee.{s}"), (f"knee.{s}", f"ankle.{s}"),
        (f"ankle.{s}", f"ball.{s}"), (f"ball.{s}", f"toe_tip.{s}"), (f"ankle.{s}", f"heel.{s}"),
    ]


def _radii(H, h, gender, build):
    """Skin radius (side-to-side, front-to-back) per landmark."""
    b = build
    fem = gender == "female"
    r = {
        "hips": ((0.095 if fem else 0.085) * H * b, 0.065 * H * b),
        "waist": ((0.068 if fem else 0.074) * H * b, 0.052 * H * b),
        "chest": (0.088 * H * b, (0.072 if fem else 0.064) * H * b),
        "upper_chest": ((0.080 if fem else 0.090) * H * b, 0.058 * H * b),
        "neck_base": (0.034 * H * b, 0.034 * H * b),
        "neck": (0.029 * H * b, 0.029 * H * b),
        "chin": (0.30 * h, 0.30 * h),
        "head_center": (0.40 * h, 0.42 * h),
        "head_top": (0.16 * h, 0.16 * h),
    }
    side = {
        "clavicle": (0.045 * H * b, 0.045 * H * b),
        "shoulder": (0.040 * H * b, 0.040 * H * b),
        "elbow": (0.029 * H * b, 0.029 * H * b),
        "wrist": (0.020 * H * b, 0.020 * H * b),
        "hand_tip": (0.016 * H * b, 0.016 * H * b),
        "hip": (0.062 * H * b, 0.062 * H * b),
        "knee": (0.040 * H * b, 0.040 * H * b),
        "ankle": (0.026 * H * b, 0.026 * H * b),
        "ball": (0.028 * H * b, 0.020 * H * b),
        "toe_tip": (0.020 * H * b, 0.014 * H * b),
        "heel": (0.024 * H * b, 0.022 * H * b),
    }
    for k, v in side.items():
        r[f"{k}.L"] = r[f"{k}.R"] = v
    # subdivision shrinks the skin hull ~25%; stylized proportions get chunkier limbs
    k = 1.35 * (1.0 + max(0.0, 7.5 - H / h) * 0.06)
    head = {"chin", "head_center", "head_top"}
    return {n: v if n in head else (v[0] * k, v[1] * k) for n, v in r.items()}


def _material(name, color):
    mat = bpy.data.materials.new(name)
    rgba = (*color[:3], 1.0)
    mat.diffuse_color = rgba            # workbench / viewport
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = 0.6
    return mat


def _apply_modifiers(obj):
    with bpy.context.temp_override(object=obj, active_object=obj,
                                   selected_objects=[obj], selected_editable_objects=[obj]):
        for m in list(obj.modifiers):
            bpy.ops.object.modifier_apply(modifier=m.name)


@command("create_human")
def create_human(name="Human", height=1.75, style="stylized", heads=None, gender="neutral",
                 build=1.0, arm_angle=35.0, skin_color=(0.80, 0.62, 0.50), smooth=2,
                 location=(0, 0, 0)):
    """Build a stylized humanoid body mesh standing on Z=0, facing -Y, in A-pose."""
    if style not in STYLES and heads is None:
        raise ValueError(f"style must be one of {sorted(STYLES)} (or pass heads=)")
    heads = float(heads or STYLES[style])
    H = float(height)
    lm = human_landmarks(H, heads, gender, arm_angle, build)
    radii = _radii(H, H / heads, gender, build)

    keys = list(lm)
    index = {k: i for i, k in enumerate(keys)}
    me = bpy.data.meshes.new(name)
    me.from_pydata([lm[k] for k in keys], [(index[a], index[b]) for a, b in EDGES], [])
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)

    skin = obj.modifiers.new("Skin", "SKIN")
    skin.use_smooth_shade = True
    skin.branch_smoothing = 0.4
    if not me.skin_vertices:
        me.skin_vertices.new()
    data = me.skin_vertices[0].data
    for k, i in index.items():
        data[i].radius = radii[k]
        data[i].use_root = k == "hips"
    if smooth:
        sub = obj.modifiers.new("Smooth", "SUBSURF")
        sub.levels = sub.render_levels = int(smooth)
    _apply_modifiers(obj)

    # stand on the ground: shift geometry so the lowest point is Z=0
    dz = -min(v.co.z for v in me.vertices)
    for v in me.vertices:
        v.co.z += dz
    lm = {k: (v[0], v[1], v[2] + dz) for k, v in lm.items()}
    for p in me.polygons:
        p.use_smooth = True

    me.materials.append(_material(f"{name}_skin", skin_color))
    obj.location = Vector(location)
    lm = {k: (v[0] + location[0], v[1] + location[1], v[2] + location[2]) for k, v in lm.items()}
    obj["c3d_landmarks"] = json.dumps(lm)
    obj["c3d_kind"] = "humanoid"
    info = _describe(obj)
    info["landmarks"] = {k: [round(c, 4) for c in v] for k, v in lm.items()}
    return info
