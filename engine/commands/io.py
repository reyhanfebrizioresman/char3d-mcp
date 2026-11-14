"""Import / export / save / open."""
import os

import bpy

from .. import context
from . import command


def _op(*candidates):
    """Return the first operator that exists (names change between Blender versions)."""
    for path in candidates:
        mod, name = path.split(".")
        group = getattr(bpy.ops, mod)
        if hasattr(group, name):
            return getattr(group, name)
    raise RuntimeError(f"none of these operators exist in this Blender: {candidates}")


IMPORTERS = {
    ".glb": lambda p: _op("import_scene.gltf")(filepath=p),
    ".gltf": lambda p: _op("import_scene.gltf")(filepath=p),
    ".fbx": lambda p: _op("import_scene.fbx", "wm.fbx_import")(filepath=p),
    ".obj": lambda p: _op("wm.obj_import", "import_scene.obj")(filepath=p),
    ".stl": lambda p: _op("wm.stl_import", "import_mesh.stl")(filepath=p),
    ".ply": lambda p: _op("wm.ply_import", "import_mesh.ply")(filepath=p),
    ".usd": lambda p: _op("wm.usd_import")(filepath=p),
    ".usdz": lambda p: _op("wm.usd_import")(filepath=p),
    ".usdc": lambda p: _op("wm.usd_import")(filepath=p),
    ".bvh": lambda p: _op("import_anim.bvh")(filepath=p),
}


@command("import_model")
def import_model(path):
    path = context.resolve(path, "imports")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMPORTERS:
        raise ValueError(f"unsupported format {ext}. Supported: {sorted(IMPORTERS)}")
    before = set(bpy.data.objects)
    IMPORTERS[ext](path)
    new = [o for o in bpy.data.objects if o not in before]
    return {
        "path": path,
        "imported": [{"name": o.name, "type": o.type,
                      "parent": o.parent.name if o.parent else None} for o in new],
    }


def _select_only(names):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for n in names:
        obj = bpy.data.objects[n]
        obj.select_set(True)
        for child in obj.children_recursive:
            child.select_set(True)


@command("export_asset")
def export_asset(path, objects=None):
    """Export to .glb/.gltf/.fbx/.obj/.usd. `objects` limits the export (children included)."""
    path = context.resolve(path, "exports")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    sel = bool(objects)
    if sel:
        _select_only(objects)
    if ext in (".glb", ".gltf"):
        _op("export_scene.gltf")(
            filepath=path, export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE",
            use_selection=sel, use_visible=True, export_animations=True, export_skins=True,
            export_def_bones=True,  # Rigify: ship only the deform skeleton
        )
    elif ext == ".fbx":
        _op("export_scene.fbx")(filepath=path, use_selection=sel, use_visible=True,
                                add_leaf_bones=False, bake_anim=True,
                                use_armature_deform_only=True)
    elif ext == ".obj":
        _op("wm.obj_export")(filepath=path, export_selected_objects=sel)
    elif ext in (".usd", ".usdc", ".usda", ".usdz"):
        _op("wm.usd_export")(filepath=path, selected_objects_only=sel)
    else:
        raise ValueError("export format must be .glb, .gltf, .fbx, .obj or .usd*")
    return {"path": path, "bytes": os.path.getsize(path)}


@command("save_project")
def save_project(path="scene.blend"):
    path = context.resolve(path, "projects")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return {"path": path}


@command("open_project")
def open_project(path):
    path = context.resolve(path, "projects")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    bpy.ops.wm.open_mainfile(filepath=path)
    return {"path": path, "objects": [o.name for o in bpy.context.scene.objects]}
