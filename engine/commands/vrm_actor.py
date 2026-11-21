"""VRM actor casting. Imported weights, skeletons and authored faces stay native."""
import json
import math
import os
import hashlib

import bpy
from mathutils import Matrix, Vector

from ..vrm import actor_path


def build_actor(char, name, dispatch, cache=None):
    path, relative = actor_path(char['vrm'])
    key = hashlib.sha256((str(path)+char['id']).encode()).hexdigest()
    cached = cache.get(key) if cache else None
    if cached:
        from .vrm import enable_addon
        enable_addon()
        with bpy.data.libraries.load(cached, link=False) as (source, target):
            target.collections = [source.collections[0]]
        collection = target.collections[0]
        bpy.context.scene.collection.children.link(collection)
        rig = next(o for o in collection.objects if o.type == 'ARMATURE')
        face = face_mesh(rig)
        return dict(rig=rig.name, mesh=face.name, realistic=True, source='vrm', vrm=relative,
                    vrm_meta=json.loads(rig['c3d_vrm_meta']), appearance={'vrm': relative},
                    actor_import='cached native actor', warnings=[])
    imported = dispatch('import_model', {'path': str(path)})
    entries = imported.get('vrm', [])
    if len(entries) != 1:
        raise ValueError('A VRM actor must contain exactly one humanoid armature')
    info = entries[0]
    rig = bpy.data.objects[info['armature']]
    old = rig.name
    rig.name = name + '_rig'
    for obj in rig.children_recursive:
        if obj.get('c3d_rig') == old:
            obj['c3d_rig'] = rig.name
    info['armature'] = rig.name
    mapping = json.loads(rig['c3d_bone_map'])
    required = ('head', 'hips', 'thigh.L', 'thigh.R', 'upper_arm.L', 'upper_arm.R')
    if any(k not in mapping for k in required):
        raise ValueError('VRM actor is missing required humanoid head/hips/limb assignments')
    # The add-on converts glTF Y-up into Blender. Derive any remaining rest
    # orientation from declared humanoid bones, never from hair/object bounds.
    bones = rig.data.bones
    left = (bones[mapping['thigh.L']].head_local-bones[mapping['thigh.R']].head_local).normalized()
    up = bones[mapping['head']].head_local-bones[mapping['hips']].head_local
    up = (up-left*up.dot(left)).normalized()
    basis = Matrix((left, -left.cross(up), up)).transposed()
    rig.matrix_world = (rig.matrix_world.to_3x3() @ basis).inverted().to_4x4() @ rig.matrix_world
    bpy.context.view_layer.update()
    meshes = [o for o in rig.children_recursive if o.type == 'MESH' and not o.hide_render]
    def bounds():
        return [o.matrix_world @ Vector(p) for o in meshes for p in o.bound_box]
    pts = bounds()
    height = max(p.z for p in pts)-min(p.z for p in pts)
    if not math.isfinite(height) or height < .01:
        raise ValueError('VRM actor has invalid height')
    notes = list(info.get('warnings', []))
    if not .8 <= height <= 2.5:
        factor = 1.7 / height
        rig.scale *= factor
        notes.append(f'VRM height {height:.3f} m outside .8..2.5 m; normalized to 1.7 m')
        bpy.context.view_layer.update()
        pts = bounds()
    rig.location.z -= min(p.z for p in pts)
    bpy.context.view_layer.update()
    rig['c3d_vrm_ground_local'] = list(rig.matrix_world.inverted() @ Vector((0,0,0)))
    face = face_mesh(rig)
    if face is None:
        raise ValueError('VRM actor has no visible facial mesh with authored morphs')
    rig['c3d_vrm_actor_path'] = relative
    rig['c3d_actor_id'] = char['id']
    if cache is not None:
        collection = bpy.data.collections.new('__c3d_vrm_actor')
        for obj in [rig, *rig.children_recursive]:collection.objects.link(obj)
        cachefile = os.path.join(cache['_directory'], key+'.blend')
        try:
            bpy.data.libraries.write(cachefile, {collection}, path_remap='ABSOLUTE', fake_user=True)
            cache[key] = cachefile
        finally:
            bpy.data.collections.remove(collection)
    return dict(rig=rig.name, mesh=face.name, realistic=True, source='vrm', vrm=relative,
                semantic_face_regions=info.get('semantic_face_regions', []),
                vrm_meta=json.loads(rig.get('c3d_vrm_meta', '{}')),
                appearance={'vrm': relative}, actor_import='VRM add-on', normalization=dict(height_m=max(p.z for p in bounds()),
                ground_z=min(p.z for p in bounds()), forward=[0, -1, 0]), warnings=notes)


def face_mesh(rig):
    """Authored morph inventory separates Face from hair, body and hidden helpers."""
    def score(obj):
        names = ' '.join(s.material.name.lower() for s in obj.material_slots if s.material)
        facial = sum(word in names for word in ('facemouth','eyeiris','facebrow','face_'))
        return facial, sum(n in obj.data.shape_keys.key_blocks for n in
                           ('eyeBlinkLeft','eyeBlinkRight','mouthSmileLeft','jawOpen'))
    return max((o for o in rig.children_recursive if o.type == 'MESH' and not o.hide_render
                and o.data.shape_keys and 'jawOpen' in o.data.shape_keys.key_blocks
                and ('hair' not in o.name.lower() or score(o)[0])), key=score,
               default=None)


def face_vertex_ids(obj):
    slots={i for i,s in enumerate(obj.material_slots) if s.material and
           any(word in s.material.name.lower() for word in ('face','eye','brow')) and
           'hair' not in s.material.name.lower()}
    if not slots:
        slots={i for i,s in enumerate(obj.material_slots) if s.material and
               'hair' not in s.material.name.lower() and s.material.get('c3d_toon_role')!='hair'}
    return {i for p in obj.data.polygons if p.material_index in slots for i in p.vertices}


def skin_slots(obj):
    """VRoid combines body and loose clothing in one skinned object."""
    return {i for i,s in enumerate(obj.material_slots) if s.material and
            ('skin' in s.material.name.lower() or s.material.get('c3d_material_role')=='skin')}


def cast_dialog(characters, lines, dispatch):
    from ..vrm import dialog_declarations
    declarations, warnings, _ = dialog_declarations(characters)
    actors = {}
    cast = []
    for entry in declarations or []:
        if not isinstance(entry, dict):
            cast.append(entry)
            continue
        name = entry['id'];index=1
        while name in bpy.data.objects or name+'_rig' in bpy.data.objects:
            name=entry['id']+'_'+str(index);index+=1
        actor=build_actor(entry,name,dispatch)
        warnings.extend(actor.pop('warnings'))
        actors[entry['id']]=actor;cast.append(actor['rig'])
        dispatch('apply_pose',dict(armature=actor['rig'],pose='relaxed'))
    mapping={k.casefold():v['rig'] for k,v in actors.items()}
    return cast, [dict(line,speaker=mapping.get(line['speaker'].casefold(),line['speaker'])) for line in lines], actors, warnings


def face_sites(rig):
    """VRoid features from face materials and declared eye/head assignments.

    All points are neutral coordinates in head-bone space. Hair, hidden meshes,
    and clothing are excluded even when they carry transferred facial morphs.
    Unknown material vocabularies retain the shared landmark fallback.
    """
    from ..vrm import addon_bones
    if not hasattr(rig.data, 'vrm_addon_extension'):
        from .vrm import enable_addon
        enable_addon()
    source = addon_bones(rig.data.vrm_addon_extension)
    mesh = face_mesh(rig)
    if mesh is None:
        return None
    features = {}
    for label, words in (('mouth', ('facemouth',)), ('eyes', ('eyeiris',)),
                         ('forehead', ('facebrow',)), ('skin', ('face_','face.'))):
        slots = {i for i, s in enumerate(mesh.material_slots) if s.material and
                 any(w in s.material.name.lower() for w in words)}
        ids = {i for p in mesh.data.polygons if p.material_index in slots for i in p.vertices}
        if not ids:
            continue
        pts = [rig.matrix_world.inverted() @ mesh.matrix_world @ mesh.data.vertices[i].co for i in ids]
        lo = Vector(tuple(min(p[i] for p in pts) for i in range(3)))
        hi = Vector(tuple(max(p[i] for p in pts) for i in range(3)))
        features[label] = (lo+hi)/2
        if label == 'skin':
            features['chin'] = Vector(((lo.x+hi.x)/2, features[label].y, lo.z))
            features['width'] = hi.x-lo.x
    if not all(k in features for k in ('mouth', 'eyes', 'forehead', 'chin')):
        return None
    eye_bones = [rig.data.bones[source[n]].head_local for n in ('leftEye', 'rightEye')
                 if source.get(n) and source[n] in rig.data.bones]
    if eye_bones:
        center = sum(eye_bones, Vector())/len(eye_bones)
        # Bone anchors establish eye height, mesh inserts establish the face plane.
        features['eyes'].z = center.z
    inv = rig.data.bones[source['head']].matrix_local.inverted()
    features['forehead'].z += .01
    for side, sign in (('L',1),('R',-1)):
        features['ear.'+side] = features['eyes']+Vector((sign*features['width']*.48,.05,-.01))
    points = {k: inv @ p for k, p in features.items() if k != 'width' and k != 'skin'}
    return points
