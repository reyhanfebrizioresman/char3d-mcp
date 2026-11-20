"""Realistic humans through MPFB (MakeHuman for Blender, CC0 assets).

MPFB must be installed as a Blender extension (repo "user_default") and the MakeHuman
system asset pack extracted into its user data folder (see README "MPFB").
Characters are built from an MPFB preset dict via MPFB's own deserializer, rigged with an
MPFB rig that ships hand-made skin weights, then tagged so char3d's pose/animation/
mocap tools drive it through the usual proxy retarget.
"""
import json
import os
import random
import re

import addon_utils
import bpy

from . import command
from .scene import _describe

MODULE = "bl_ext.user_default.mpfb"
RIGS = ("game_engine", "default", "default_no_toes", "mixamo", "cmu_mb", "rigify")
# landmarks for Rigify rigs come from the deform skeleton
RIGIFY_DEF = {"hips": "DEF-spine", "spine": "DEF-spine.001", "chest": "DEF-spine.003",
              "neck": "DEF-spine.004", "head": "DEF-spine.006"}
for _s in "LR":
    RIGIFY_DEF.update({f"shoulder.{_s}": f"DEF-shoulder.{_s}", f"upper_arm.{_s}": f"DEF-upper_arm.{_s}",
                       f"forearm.{_s}": f"DEF-forearm.{_s}", f"hand.{_s}": f"DEF-hand.{_s}",
                       f"thigh.{_s}": f"DEF-thigh.{_s}", f"shin.{_s}": f"DEF-shin.{_s}",
                       f"foot.{_s}": f"DEF-foot.{_s}", f"toe.{_s}": f"DEF-toe.{_s}"})
BODYPARTS = ("eyes", "eyebrows", "eyelashes", "hair", "teeth", "tongue")
OUTFITS = ("casual", "formal", "sport", "summer", "winter")


def _services():
    if not any(m.__name__ == MODULE for m in addon_utils.modules()):
        raise RuntimeError("MPFB is not installed in this Blender (README: 'MPFB').")
    addon_utils.enable(MODULE, default_set=True)
    from bl_ext.user_default.mpfb.services import AssetService, HumanService, LocationService
    return AssetService, HumanService, LocationService


def _data_dir():
    _a, _h, loc = _services()
    return loc.get_user_data()


def _catalog():
    """{kind: {asset_name: absolute_file}}, including optional pack directories."""
    root = _data_dir()
    out = {}
    kinds = set(("skins",) + BODYPARTS + ("clothes", "proxymeshes", "beards", "moustaches"))
    kinds.update(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    for kind in sorted(kinds):
        d = os.path.join(root, kind)
        if not os.path.isdir(d):
            out[kind] = {}
            continue
        ext = ".mhmat" if kind == "skins" else ".mhclo"
        items = {}
        for sub, dirs, filenames in os.walk(d):
            dirs.sort()
            files = sorted(f for f in filenames if f.endswith(ext))
            if files:
                name = os.path.basename(sub)
                pick = f"{name}{ext}" if f"{name}{ext}" in files else files[0]
                items[name] = os.path.join(sub, pick)
        if items or kind in ("skins",) + BODYPARTS + ("clothes", "proxymeshes", "beards", "moustaches"):
            out[kind] = items
    # Pack versions can put facial hair under clothes, beards or moustaches. Load all
    # through MPFB's clothing path, preserving fitting, delete masks and rig weights.
    out["clothes"].update(out["beards"])
    out["clothes"].update(out["moustaches"])
    for name, path in out["clothes"].items():
        category = _clothing_metadata(name, path)["category"]
        if category in ("beard", "moustache"):
            out["beards"][name] = path
        if category == "moustache":
            out["moustaches"][name] = path
    return out


def _words(text):
    return set(re.findall(r"[a-z]+", text.lower()))


def _clothing_metadata(name, path):
    """Read only the mhclo header; geometry and weights can be very large."""
    meta = {"name": name, "tags": [], "z_depth": None}
    with open(path, encoding="utf-8", errors="replace") as stream:
        for line in stream:
            key, _, value = line.strip().partition(" ")
            if key in ("verts", "weights", "delete_verts"):
                break
            if key in ("tag", "tags"):
                meta["tags"].append(value.strip())
            elif key == "name":
                meta["name"] = value.strip()
            elif key == "z_depth":
                try:
                    meta["z_depth"] = int(value)
                except ValueError:
                    pass
    rules = (
        ("moustache", ("moustache", "mustache")),
        ("beard", ("beard",)),
        ("glasses", ("glasses", "optical", "spectacles")),
        ("hat", ("hat", "cap", "fedora", "bag_on_head")),
        ("shoes", ("shoe", "boot", "flat", "sneaker", "sandal", "t_bar", "heel")),
        ("dress", ("dress", "tunic", "kimono", "robe")),
        ("suit", ("suit", "overall")),
        ("bottom", ("pant", "jean", "shorts", "trouser", "skirt", "legging")),
        ("top", ("shirt", "top", "sweater", "turtleneck", "jacket", "coat", "blouse")),
        ("underwear", ("underwear", "bra", "brief", "panties")),
        ("socks", ("sock", "stocking",)),
    )
    meta["category"] = "accessory"
    # Prefer the asset/display name: a skirt in skirts01 is incorrectly tagged dress.
    for text in (name + " " + meta["name"], " ".join(meta["tags"])):
        normalized = text.lower().replace("-", "_")
        category = next((cat for cat, hints in rules if any(h in normalized for h in hints)), None)
        if category:
            meta["category"] = category
            break
    words = _words(name + " " + meta["name"] + " " + " ".join(meta["tags"]))
    meta["gender"] = ("unisex" if "unisex" in words or {"male", "female"} <= words else
                      "female" if words & {"female", "fem", "heroine"} else
                      "male" if "male" in words else "unisex")
    return meta


def _outfit_clothes(metadata, outfit, gender, seed):
    """Choose from sorted installed candidates without changing global random state."""
    rng = random.Random(seed)
    sex = "male" if gender >= 0.5 else "female"
    eligible = {n: m for n, m in metadata.items() if m["gender"] in (sex, "unisex")}
    preferred = {
        "casual": {"top": ("t-shirt", "polo", "casual"), "bottom": ("jeans", "cargo"),
                   "shoes": ("cloth", "sneaker", "flat" if sex == "female" else "shoes")},
        "formal": {"suit": ("formal", "elegant"), "shoes": ("ankle", "flat"),
                   "top": ("shirt", "blouse"), "bottom": ("wool", "pants")},
        "sport": {"suit": ("sport",), "top": ("t-shirt", "polo", "sport"),
                  "bottom": ("shorts", "sport"), "shoes": ("sneaker", "cloth", "shoes03")},
        "summer": {"top": ("t-shirt", "polo", "tank") if sex == "male" else ("camisole", "tank", "halter"),
                   "bottom": ("shorts",) if sex == "male" else ("mini", "skirt", "shorts"),
                   "dress": ("halter", "camisole"), "shoes": ("sandal", "flat" if sex == "female" else "cloth")},
        "winter": {"top": ("sweater", "coat"), "bottom": ("wool", "pants"),
                   "shoes": ("boot",), "hat": ("cap",)},
    }[outfit]

    def choose(category):
        pool = sorted(n for n, m in eligible.items() if m["category"] == category)
        if not pool:
            return None
        scores = {n: 10 * sum(h in (n + " " + " ".join(eligible[n]["tags"])).lower()
                              for h in preferred.get(category, ())) + (eligible[n]["gender"] == sex)
                  for n in pool}
        best = max(scores.values())
        return rng.choice([n for n in pool if scores[n] == best])

    selected = []
    full = choose("suit") if outfit in ("formal", "sport") else None
    if outfit == "sport" and full and "sport" not in full.lower():
        full = None
    if not full and sex == "female" and outfit in ("formal", "summer"):
        full = choose("dress")
    if full:
        selected.append(full)
    else:
        selected.extend(filter(None, (choose("top"), choose("bottom"))))
        if len(selected) < 2:
            full = choose("dress") or choose("suit")
            if full:
                selected = [full]
    selected.extend(filter(None, (choose("shoes"), choose("hat") if outfit == "winter" else None)))
    categories = {metadata[n]["category"] for n in selected}
    missing = []
    if not categories & {"dress", "suit"}:
        missing.extend(c for c in ("top", "bottom") if c not in categories)
    missing.extend(c for c in ("shoes", "hat") if c not in categories and
                   (c == "shoes" or outfit == "winter"))
    warnings = [f"Outfit '{outfit}': no compatible installed {c}; install optional MPFB packs."
                for c in missing]
    return selected, warnings


def _outfit_warnings(clothes, metadata):
    occupied = {}
    warnings = []
    for name in clothes:
        category = metadata[name]["category"]
        slots = {"suit": ("top", "bottom"), "dress": ("top", "bottom")}.get(category, (category,))
        for slot in slots:
            if slot == "accessory":
                continue
            if slot in occupied:
                warnings.append(f"Clothing conflict ({slot}): '{occupied[slot]}' and '{name}' may overlap.")
            occupied[slot] = name
    return warnings


def _age_value(years):
    """MakeHuman age macro: 0 -> 1 y, 0.1875 -> 11 y, 0.5 -> 25 y, 1 -> 90 y."""
    y = max(1.0, min(90.0, float(years)))
    if y <= 11:
        return (y - 1) / 10 * 0.1875
    if y <= 25:
        return 0.1875 + (y - 11) / 14 * 0.3125
    return 0.5 + (y - 25) / 65 * 0.5


def _auto_skin(skins, gender, years, race):
    sex = "male" if gender >= 0.5 else "female"
    age = "young" if years < 35 else ("middleage" if years < 60 else "old")
    eth = max(race, key=race.get)
    for cand in (f"{age}_{eth}_{sex}", f"young_{eth}_{sex}", f"young_caucasian_{sex}"):
        if cand in skins:
            return cand
    return next(iter(skins), None)


def _pick(catalog, kind, name):
    if not name:
        return None
    key = str(name).lower().replace(" ", "_").replace("-", "_")
    for k in catalog[kind]:
        if k.lower().replace("-", "_") == key:
            return catalog[kind][k]
    raise ValueError(f"unknown {kind} '{name}'. Available: {sorted(catalog[kind])}")


def _repair_part_weights(parts, basemesh, rig):
    """Fill interpolation gaps only; keep all authored nonzero deform weights intact.

    Some proxies reference helper vertices without weights on a particular skeleton
    (e.g. faydaen_hair_1 on Mixamo). Copy the closest weighted vertex on the same
    fitted part, falling back to the body only for a completely unweighted part.
    """
    from mathutils.kdtree import KDTree
    body_deform = {b.name for b in rig.data.bones if b.use_deform}
    deform = body_deform

    def weighted(obj):
        groups = {g.index: g.name for g in obj.vertex_groups if g.name in deform}
        return [(v, [(groups[g.group], g.weight) for g in v.groups
                      if g.group in groups and g.weight > 1e-4]) for v in obj.data.vertices]

    repaired = {}
    for obj in parts:
        deform = body_deform | {b.name for m in obj.modifiers if m.type == "ARMATURE" and m.object
                                for b in m.object.data.bones if b.use_deform}
        vertices = weighted(obj)
        missing = [v for v, weights in vertices if not weights]
        if not missing:
            continue
        donors = [(obj.matrix_world @ v.co, weights) for v, weights in vertices if weights]
        if not donors:
            donors = [(basemesh.matrix_world @ v.co, weights) for v, weights in weighted(basemesh) if weights]
        if not donors:
            raise RuntimeError(f"No deform weights available for MPFB part '{obj.name}'")
        tree = KDTree(len(donors))
        for i, (point, _weights) in enumerate(donors):
            tree.insert(point, i)
        tree.balance()
        for vertex in missing:
            _point, index, _distance = tree.find(obj.matrix_world @ vertex.co)
            weights = donors[index][1]
            total = sum(w for _n, w in weights)
            for bone, weight in weights:
                group = obj.vertex_groups.get(bone)
                if group is None:
                    group = obj.vertex_groups.new(name=bone)
                group.add([vertex.index], weight / total, "REPLACE")
        repaired[obj.name] = len(missing)
    return repaired


@command("mpfb_assets")
def mpfb_assets():
    cat = _catalog()
    metadata = {n: _clothing_metadata(n, p) for n, p in sorted(cat["clothes"].items())}
    categories = {}
    for name, meta in metadata.items():
        categories.setdefault(meta["category"], []).append(name)
    packs = {}
    pack_dir = os.path.join(_data_dir(), "packs")
    if os.path.isdir(pack_dir):
        for filename in sorted(os.listdir(pack_dir)):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(pack_dir, filename), encoding="utf-8") as stream:
                entries = json.load(stream)
            installed = {}
            for name, entry in entries.items():
                kind = entry.get("type", "").lower()
                kind = {"skin": "skins"}.get(kind, kind)
                # hair01 labels its entries "clothes" although the ZIP installs
                # them under hair/. Trust the extracted catalog over manifest type.
                if name not in cat.get(kind, {}):
                    kind = next((k for k, assets in cat.items() if name in assets), None)
                if name in cat.get(kind, {}):
                    installed.setdefault(kind, []).append(name)
            packs[filename[:-5]] = {k: sorted(v) for k, v in installed.items()}
    return {"installed": True, "data_dir": _data_dir(), "rigs": list(RIGS),
            "assets": {k: sorted(v) for k, v in cat.items()},
            "clothing_categories": categories, "clothing_metadata": metadata,
            "outfits": list(OUTFITS), "packs": packs}


@command("create_realistic_human")
def create_realistic_human(name="Person", gender=0.5, age=25, muscle=0.5, weight=0.5,
                           height=0.5, proportions=0.5, race=None, skin="auto",
                           hair=None, eyebrows="eyebrow001", eyelashes="eyelashes01",
                           eyes="high-poly", clothes=None, rig="game_engine",
                           subdiv=0, location=(0, 0, 0), face=True, beard=None,
                           outfit=None, seed=0, materials="enhanced", style="realistic"):
    """Build a realistic human with MPFB. gender 0=female..1=male; age in years;
    muscle/weight/height/proportions 0..1 (0.5 = average); race weights dict."""
    from ..materials import options
    from ..toon import style_name
    style = style_name(style)
    options(materials)
    AssetService, HumanService, _loc = _services()
    if rig == "rigify":
        addon_utils.enable("rigify", default_set=True)   # MPFB checks this before adding the metarig
    if rig not in RIGS + ("none",):
        raise ValueError(f"rig must be one of {list(RIGS) + ['none']}")
    cat = _catalog()
    if outfit is not None and outfit not in OUTFITS:
        raise ValueError(f"outfit must be one of {list(OUTFITS)} or None")
    if not cat["skins"]:
        raise RuntimeError("MakeHuman system assets are not installed (README: 'MPFB').")
    race = race or {"caucasian": 1 / 3, "african": 1 / 3, "asian": 1 / 3}
    tot = sum(race.values()) or 1.0
    race = {k: float(race.get(k, 0)) / tot for k in ("african", "asian", "caucasian")}
    skin_name = _auto_skin(cat["skins"], gender, age, race) if skin == "auto" else skin
    metadata = {n: _clothing_metadata(n, p) for n, p in cat["clothes"].items()}
    warnings = []
    chosen = list(clothes) if clothes is not None else []
    if clothes is None and outfit is not None:
        chosen, warnings = _outfit_clothes(metadata, outfit, gender, seed)
    clothing_paths = [_pick(cat, "clothes", c) for c in chosen]
    if beard:
        clothing_paths.append(_pick(cat, "beards", beard))
    canonical = {path: n for n, path in cat["clothes"].items()}
    resolved = [canonical[p] for p in clothing_paths]
    warnings.extend(_outfit_warnings(resolved, metadata))

    info = {
        "phenotype": {"gender": float(gender), "age": _age_value(age), "muscle": float(muscle),
                      "weight": float(weight), "height": float(height),
                      "proportions": float(proportions), "cupsize": 0.5, "firmness": 0.5,
                      "race": race},
        "rig": "" if rig == "none" else ("rigify.human" if rig == "rigify" else rig),
        "skin_mhmat": _pick(cat, "skins", skin_name) if skin_name else "",
        "skin_material_type": "ENHANCED_SSS" if skin_name else "NONE",
        "skin_material_settings": {},
        "eyes_material_type": "MAKESKIN", "eyes_material_settings": {},
        "clothes": list(dict.fromkeys(clothing_paths)),
        "proxy": "", "targets": [], "makeup": [], "expressions": [],
        "color_adjustments": {}, "alternative_materials": {},
    }
    for part, value in (("eyes", eyes), ("eyebrows", eyebrows), ("eyelashes", eyelashes),
                        ("hair", hair), ("teeth", "teeth_base" if face else None),
                        ("tongue", "tongue01" if face else None)):
        info[part] = _pick(cat, part, value) if value else ""

    settings = HumanService.get_default_deserialization_settings()
    settings.update({"subdiv_levels": int(subdiv), "load_clothes": True,
                     "material_instances": "NEVER"})
    vl = bpy.context.view_layer
    if vl.objects.active and vl.objects.active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    before = set(bpy.data.objects)
    basemesh = HumanService.deserialize_from_dict(info, settings)
    if style != "realistic":
        # Freeze the chosen phenotype before loading facial animation targets.
        # MPFB's live macro keys otherwise add their original unscaled deltas.
        from bl_ext.user_default.mpfb.services.targetservice import TargetService
        TargetService.bake_targets(basemesh)
    if rig == "rigify":
        if style != "realistic":
            from .toon import prefit_rigify
            prefit_rigify(basemesh,style,face)
        basemesh = _generate_rigify(basemesh, name)
    from .util import is_helper
    new = [o for o in bpy.data.objects
           if o not in before and o.name in bpy.data.objects and not is_helper(o)]

    root = basemesh.parent if basemesh.parent and basemesh.parent.type == "ARMATURE" else basemesh
    root.location = tuple(location)
    old_prefix = basemesh.name + "."
    for o in new:   # MPFB names parts "<basemesh>.<asset>": make them "<name>.<asset>"
        if o is not basemesh and o.name.startswith(old_prefix):
            o.name = f"{name}.{o.name[len(old_prefix):]}"
    basemesh.name = name
    basemesh["c3d_kind"] = "humanoid"
    basemesh["c3d_source"] = "mpfb"
    basemesh["c3d_age"] = float(age)
    basemesh["c3d_skin"] = skin_name or ""
    basemesh['c3d_asset_provenance'] = json.dumps(dict(assets=list(filter(None,
        [skin_name, hair, beard, eyes, eyebrows, eyelashes, 'teeth_base' if face else None,
         'tongue01' if face else None, *chosen]))))
    provenance = json.loads(basemesh['c3d_asset_provenance'])
    pack_names = {}
    pack_dir = os.path.join(_data_dir(), 'packs')
    if os.path.isdir(pack_dir):
        for filename in sorted(os.listdir(pack_dir)):
            if filename.endswith('.json'):
                with open(os.path.join(pack_dir, filename), encoding='utf-8') as stream:
                    for asset in json.load(stream):
                        pack_names[asset] = filename[:-5]
    provenance['records'] = [dict(name=asset, pack=pack_names.get(asset, 'system'),
        path=next((assets[asset] for assets in cat.values() if asset in assets), None))
        for asset in provenance['assets']]
    basemesh['c3d_asset_provenance'] = json.dumps(provenance)
    # Persist asset categories: names alone cannot identify every pack hair proxy.
    for obj in new:
        if obj.type != "MESH" or obj is basemesh:
            continue
        part = obj.name.removeprefix(name + '.')
        obj["c3d_material_part"] = ("hair " + part) if hair and part == hair else part
        if part in metadata:
            obj["c3d_garment_category"] = metadata[part]["category"]
            obj["c3d_garment_tags"] = " ".join(metadata[part]["tags"])
    repaired = {}
    if root.type == "ARMATURE":
        repaired = _repair_part_weights([o for o in new if o.type == "MESH" and o is not basemesh],
                                        basemesh, root)
    result = _describe(basemesh)
    if root.type == "ARMATURE":
        root.name = f"{name}_rig"
        root.data.name = f"{name}_rig"
        bpy.context.view_layer.update()
        from .anim import _rig_landmarks, heuristic_map, semantic_map
        if rig == "rigify":
            root["c3d_rig_type"] = "rigify"          # use char3d's Rigify control mapping
            for pb in root.pose.bones:               # FK limbs so poses/clips rotate directly
                if "IK_FK" in pb.keys():
                    pb["IK_FK"] = 1.0
            lm = _rig_landmarks(root, RIGIFY_DEF)
            smap = semantic_map(root)
        else:
            root["c3d_rig_type"] = f"mpfb_{rig}"
            smap = heuristic_map(root)
            lm = _rig_landmarks(root, smap)
        root["c3d_landmarks"] = json.dumps({k: list(v) for k, v in lm.items()})
        basemesh["c3d_rig"] = root.name
        result["armature"] = root.name
        result["mapped_bones"] = len(smap)
    if face:
        from .face import _ensure_face
        result["face_rig"] = "shape keys (ARKit 52 + visemes 22)" if _ensure_face(basemesh) \
            or basemesh.data.shape_keys else None
    if style != "realistic":
        from .toon import stylize
        result["stylized"] = stylize(basemesh, [o for o in new if o.type == "MESH"],
                                     root if root.type == "ARMATURE" else None, style)
        result.update(_describe(basemesh))
    from .util import scene_bounds
    lo, hi = scene_bounds([o for o in new if o.type == "MESH"])
    result.update({
        "skin": skin_name, "hair": hair, "clothes": chosen, "rig": rig,
        "beard": beard, "outfit": outfit, "seed": seed, "warnings": warnings,
        "weights_repaired": repaired,
        "height_m": round(hi.z - lo.z, 3) if lo else None,
        "parts": sorted(o.name for o in new if o.type == "MESH" and o is not basemesh),
    })
    if style != "realistic":
        result["materials"] = result["stylized"]["materials"]
        result["recommended_render_style"] = "anime"
    elif materials == "enhanced":
        from .materials import upgrade_materials
        result["materials"] = upgrade_materials(root.name)
    else:
        result["materials"] = {"quality": "mpfb", "materials_cost_factor": 1.}
    result["mesh"]["materials"] = [slot.material.name for slot in basemesh.material_slots if slot.material]
    return result


def _generate_rigify(basemesh, name):
    """Turn the MPFB Rigify metarig into a full control rig (face rig included)."""
    from bl_ext.user_default.mpfb.services import RigService, SystemService
    addon_utils.enable("rigify", default_set=True)
    meta = basemesh.parent
    if meta is None or not SystemService.check_for_rigify():
        raise RuntimeError("Rigify metarig missing or Rigify add-on unavailable")
    vl = bpy.context.view_layer
    for o in bpy.context.selected_objects:
        o.select_set(False)
    vl.objects.active = meta
    meta.select_set(True)
    rig = RigService.generate_rigify_rig(meta, name=f"{name}_rig", meta_rig_action="delete")
    if rig is None:
        raise RuntimeError("Rigify rejected the MPFB metarig")
    return basemesh
