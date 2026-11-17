"""Import / export / save / open."""
import os
from contextlib import contextmanager

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
    for obj in bpy.context.scene.objects:
        if obj.get("c3d_hold_character") in names:
            obj.select_set(True)
            for child in obj.children_recursive:
                child.select_set(True)


@contextmanager
def _limited_weights(objects, maximum):
    """Swap in private mesh data for export; always restore the original weights/keys."""
    copies = []
    limited = 0
    try:
        for obj in objects:
            if maximum is None or obj.type != "MESH":
                continue
            rig = obj.find_armature()
            if rig is None:
                continue
            deform = {b.name for b in rig.data.bones if b.use_deform}
            original = obj.data
            temporary = original.copy()
            copies.append((obj, original, temporary))
            obj.data = temporary
            # Blender 5 stores group definitions on the mesh: fetch RNA after swapping.
            groups = {g.index: g for g in obj.vertex_groups if g.name in deform}
            for vertex in temporary.vertices:
                weights = sorted(((g.group, g.weight) for g in vertex.groups
                                  if g.group in groups and g.weight > 0),
                                 key=lambda pair: (-pair[1], pair[0]))
                if len(weights) > maximum:
                    limited += 1
                    for index, _weight in weights[maximum:]:
                        groups[index].remove([vertex.index])
                kept = weights[:maximum]
                total = sum(weight for _index, weight in kept)
                for index, weight in kept:
                    groups[index].add([vertex.index], weight / total, "REPLACE")
            temporary.update()
        if copies:
            bpy.context.view_layer.update()
        yield limited
    finally:
        for obj, original, temporary in reversed(copies):
            obj.data = original
            bpy.data.meshes.remove(temporary)
        if copies:
            bpy.context.view_layer.update()


@command("export_asset")
def export_asset(path, objects=None, max_influences=None):
    """Export an asset, optionally limiting deform weights on temporary mesh copies."""
    if max_influences is not None and (type(max_influences) is not int or max_influences < 1):
        raise ValueError("max_influences must be a positive integer or None")
    path = context.resolve(path, "exports")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    selected = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    try:
        if objects:
            _select_only(objects)
        exported = [o for o in bpy.context.scene.objects
                    if (not objects or o.select_get()) and o.visible_get()]
        from .holding import export_attachments
        with _limited_weights(exported, max_influences) as limited:
            with export_attachments(exported):
                _export(path, objects, max_influences)
        return {"path": path, "bytes": os.path.getsize(path),
                "max_influences": max_influences, "vertices_limited": limited}
    finally:
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        for obj in selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = active


def _export(path, objects, max_influences):
    ext = os.path.splitext(path)[1].lower()
    sel = bool(objects)
    if ext in (".glb", ".gltf"):
        weights = {"export_all_influences": True} if max_influences is not None else {}
        _op("export_scene.gltf")(
            filepath=path, export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE",
            use_selection=sel, use_visible=True, export_animations=True, export_skins=True,
            export_def_bones=True,  # Rigify: ship only the deform skeleton
            export_animation_mode="ACTIVE_ACTIONS",  # only what each exported rig plays
            **weights,
        )
    elif ext == ".fbx":
        _op("export_scene.fbx")(filepath=path, use_selection=sel, use_visible=True,
                                add_leaf_bones=False, bake_anim=True,
                                use_armature_deform_only=True)
    elif ext == ".obj":
        _op("wm.obj_export")(filepath=path, export_selected_objects=sel)
    elif ext == ".bvh":
        arms = [bpy.data.objects[n] for n in (objects or []) if bpy.data.objects[n].type == "ARMATURE"]
        arms = arms or [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
        if not arms:
            raise ValueError("BVH export needs an armature")
        rig = arms[0]
        for o in bpy.context.selected_objects:
            o.select_set(False)
        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)
        sc = bpy.context.scene
        _op("export_anim.bvh")(filepath=path, frame_start=sc.frame_start, frame_end=sc.frame_end)
    elif ext in (".usd", ".usdc", ".usda", ".usdz"):
        _op("wm.usd_export")(filepath=path, selected_objects_only=sel)
    else:
        raise ValueError("export format must be .glb, .gltf, .fbx, .obj, .bvh or .usd*")


def _external_files():
    """Images and sounds that live in files (not packed)."""
    for coll in (bpy.data.images, bpy.data.sounds):
        for item in coll:
            if item.filepath and getattr(item, "packed_file", None) is None:
                yield item


def _absolute_external_paths():
    """Files outside the workspace (MPFB textures, system assets) get absolute paths, so a
    saved .blend still finds them after it is copied or moved; workspace files stay relative
    so the whole workspace can move together."""
    ws = os.path.realpath(context.WORKSPACE)
    changed = 0
    for item in _external_files():
        if not item.filepath.startswith("//"):
            continue
        absp = os.path.normpath(bpy.path.abspath(item.filepath))
        if not os.path.realpath(absp).startswith(ws + os.sep):
            item.filepath = absp
            changed += 1
    return changed


def _repair_missing_files():
    """Re-find textures whose stored path broke (e.g. a .blend saved relative elsewhere):
    re-anchor paths inside Blender's extensions folder (MPFB assets) on this install."""
    roots = [bpy.utils.user_resource("EXTENSIONS")]
    try:
        roots.append(bpy.utils.system_resource("EXTENSIONS"))
    except (AttributeError, ValueError, TypeError):
        pass
    fixed, missing = 0, []
    for item in _external_files():
        absp = bpy.path.abspath(item.filepath)
        if os.path.exists(absp):
            continue
        norm = absp.replace("\\", "/")
        found = None
        if "/extensions/" in norm:
            tail = norm.split("/extensions/", 1)[1]
            parts = tail.split("/")
            for root in roots:
                if not root:
                    continue
                for k in range(len(parts)):             # tolerate .user/ or repo-name changes
                    cand = os.path.join(root, *parts[k:])
                    if os.path.exists(cand):
                        found = cand
                        break
                if found:
                    break
        if not found and "/imports/" in norm:        # workspace audio/textures
            cand = os.path.join(context.WORKSPACE, "imports", norm.split("/imports/", 1)[1])
            if os.path.exists(cand):
                found = cand
        if found:
            item.filepath = found
            if hasattr(item, "reload"):
                item.reload()
            fixed += 1
        else:
            missing.append(item.name)
    return fixed, missing


@command("save_project")
def save_project(path="scene.blend"):
    from .weather import refresh_weather
    refresh_weather()
    path = context.resolve(path, "projects")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _absolute_external_paths()
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return {"path": path}


@command("open_project")
def open_project(path):
    path = context.resolve(path, "projects")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    bpy.ops.wm.open_mainfile(filepath=path)
    fixed, missing = _repair_missing_files()
    out = {"path": path, "objects": [o.name for o in bpy.context.scene.objects]}
    if fixed:
        out["relinked_files"] = fixed
    if missing:
        out["missing_files"] = missing[:20]
    return out


@command("prepare_model")
def prepare_model(objects, name="Model", height=None, max_faces=None, rotate_z=0.0,
                  center=True, on_ground=True, merge_distance=0.0001):
    """Turn imported pieces into one clean mesh: unparent, join, apply transforms, weld,
    optional decimate, rotate about Z, scale to `height`, center on XY, stand on Z=0."""
    import math

    from mathutils import Matrix, Vector

    roots = [bpy.data.objects[n] for n in objects if n in bpy.data.objects]
    if not roots:
        raise ValueError(f"none of {objects} exist")
    family = set()
    for o in roots:
        family.add(o)
        family.update(o.children_recursive)
    meshes = [o for o in family if o.type == "MESH"]
    if not meshes:
        raise ValueError("no mesh among the given objects")
    for m in meshes:   # bake parent transforms into each mesh, then detach
        mw = m.matrix_world.copy()
        m.parent = None
        m.matrix_world = mw
    for m in meshes:   # imported rigs/armature modifiers would fight our own rig later
        for md in [md for md in m.modifiers if md.type == "ARMATURE"]:
            m.modifiers.remove(md)

    vl = bpy.context.view_layer
    if vl.objects.active and vl.objects.active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for m in meshes:
        m.select_set(True)
    vl.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = vl.objects.active
    obj.name = name
    obj.data.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in family:   # leftover empties / armatures from the file
        if o.name in bpy.data.objects and o is not obj and o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)

    me = obj.data
    if merge_distance:
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=float(merge_distance))
        bm.to_mesh(me)
        bm.free()
    faces = len(me.polygons)
    if max_faces and faces > int(max_faces):
        dec = obj.modifiers.new("Decimate", "DECIMATE")
        dec.ratio = max(0.01, int(max_faces) / faces)
        bpy.ops.object.modifier_apply(modifier=dec.name)
    if rotate_z:
        me.transform(Matrix.Rotation(math.radians(rotate_z), 4, "Z"))
    vs = [v.co for v in me.vertices]
    lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
    hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
    if height:
        s = float(height) / max(hi.z - lo.z, 1e-6)
        me.transform(Matrix.Scale(s, 4))
        lo, hi = lo * s, hi * s
    shift = Vector((-(lo.x + hi.x) / 2 if center else 0, -(lo.y + hi.y) / 2 if center else 0,
                    -lo.z if on_ground else 0))
    me.transform(Matrix.Translation(shift))
    obj.location = (0, 0, 0)
    for p in me.polygons:
        p.use_smooth = True
    me.update()
    bpy.context.view_layer.update()
    return {"name": obj.name, "faces": len(me.polygons), "vertices": len(me.vertices),
            "faces_before": faces, "dimensions": [round(d, 4) for d in obj.dimensions]}
