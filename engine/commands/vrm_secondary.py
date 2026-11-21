"""Bake authored VRM spring chains with char3d's deterministic elastic solver.

No new bones, weights or topology. Native VRM collider empties have already been
converted into Blender space by the add-on; snapshot those in the rest pose.
"""
import json
import bpy
from mathutils import Vector

STATE = 'c3d_vrm_springs'


def snapshot(rig):
    ext = rig.data.vrm_addon_extension
    meshes = [o for o in rig.children_recursive if o.type == 'MESH' and not o.hide_render]
    chains, colliders, skipped = [], [], []
    groups = []
    if str(ext.spec_version).startswith('1'):
        for spring in ext.spring_bone1.springs:
            groups.append((spring.vrm_name, [[j.node.bone_name for j in spring.joints]], [],
                           spring.joints[0].hit_radius if spring.joints else .005))
    else:
        secondary = ext.vrm0.secondary_animation
        for group in secondary.bone_groups:
            refs = {g.collider_group_uuid for g in group.collider_groups}
            cols = [g for g in secondary.collider_groups if g.uuid in refs]
            groups.append((group.comment, [[b.bone_name] for b in group.bones], cols, group.hit_radius))
    for label, paths, cols, radius in groups:
        for initial in paths:
            names = [n for n in initial if n in rig.data.bones]
            if not names:
                continue
            while len(names) == 1 or not str(ext.spec_version).startswith('1'):
                children = list(rig.data.bones[names[-1]].children)
                if len(children) != 1 or children[0].name.endswith('_end'):
                    break
                names.append(children[0].name)
            hint = (label+' '+' '.join(names)).lower()
            head = json.loads(rig['c3d_bone_map'])['head']
            ancestor = rig.data.bones[names[0]].parent
            parents = {b.name for b in rig.data.bones[names[0]].parent_recursive}
            part = 'hair' if head in parents or 'hair' in hint else 'clothes'
            if part == 'clothes' and not any(s in hint for s in ('skirt', 'sleeve', 'cloth', 'coat')):
                skipped.append(dict(group=label, reason='Only hair and loose clothing springs are baked'))
                continue
            if ancestor is None:
                continue
            def weighted(obj):
                groups={obj.vertex_groups[n].index for n in names if n in obj.vertex_groups}
                return bool(groups) and any(any(g.group in groups and g.weight>1e-6 for g in v.groups)
                                            for v in obj.data.vertices)
            affected = [o for o in meshes if weighted(o)]
            if not affected:
                skipped.append(dict(group=label, bones=names, reason='No skinned mesh uses this spring'))
                continue
            nodes = [list(rig.data.bones[n].head_local) for n in names]
            nodes.append(list(rig.data.bones[names[-1]].tail_local))
            if any((Vector(b)-Vector(a)).length < 1e-6 for a,b in zip(nodes,nodes[1:])):
                skipped.append(dict(group=label, bones=names, reason='Degenerate spring segment'))
                continue
            key = 'vrm_'+part
            chains.append(dict(bones=names, points=nodes, parent=ancestor.name, radius=float(radius),
                               part=key, public_part=part, native=True, mesh=affected[0].name,
                               group=label, affected_meshes=[o.name for o in affected]))
            for group in cols:
                bone = group.node.bone_name
                if bone not in rig.data.bones:
                    continue
                for collider in group.colliders:
                    obj = collider.bpy_object
                    if obj:
                        point = rig.matrix_world.inverted() @ obj.matrix_world.translation
                        spec = dict(name=obj.name, bone=bone, a=list(point), b=list(point),
                                    radius=obj.empty_display_size*max(obj.matrix_world.to_scale())/
                                    max(rig.matrix_world.to_scale()), part=key)
                        if spec not in colliders:
                            colliders.append(spec)
    # VRM1 colliders have sphere/capsule display objects with native bone parents.
    if str(ext.spec_version).startswith('1'):
        for collider in ext.spring_bone1.colliders:
            obj = collider.bpy_object
            bone = collider.node.bone_name
            if obj and bone in rig.data.bones:
                a = rig.matrix_world.inverted() @ obj.matrix_world.translation
                b = rig.matrix_world.inverted() @ obj.children[0].matrix_world.translation if obj.children else a
                for part in {c['part'] for c in chains}:
                    colliders.append(dict(name=obj.name, bone=bone, a=list(a), b=list(b),
                                          radius=obj.empty_display_size, part=part))
    rig[STATE] = json.dumps(dict(chains=chains, colliders=colliders, skipped=skipped))
    return len(chains)


def bake(rig, parts, f0, f1, stiffness, damping, gravity, wind, clear, collisions=True):
    from .secondary import _sample, _bake, _clear_keys
    from .talk import _data_curves
    state = json.loads(rig.get(STATE, '{}'))
    chains = [c for c in state.get('chains', []) if c['public_part'] in parts or c['mesh'] in parts]
    names = sorted({n for c in chains for n in c['bones']})
    saved = bpy.context.scene.frame_current
    try:
        _clear_keys(rig, names, f0, f1, neutral=clear)
        measured = {}
        if chains and not clear:
            bodies,geometry=[],[]
            if collisions and any(c['public_part']=='clothes' for c in chains):
                from .collision import Body,surfaces
                # Native sleeve joints can lie on the arm axis. Their authored
                # collider groups control self contact; peer bodies and scene
                # BVHs supplement those without ejecting a cuff from its arm.
                bodies=[Body(o) for o in bpy.context.scene.objects if o.type=='ARMATURE' and o!=rig and not o.hide_render]
                geometry=surfaces([rig])
            samples = _sample(rig, chains, state['colliders'], f0, f1,bodies,geometry)
            measured = _bake(rig, chains, state['colliders'], samples, f0, f1,
                             stiffness, damping, gravity, wind)
            paths = {rig.pose.bones[n].path_from_id('rotation_quaternion') for n in names}
            for fc in _data_curves(rig):
                if fc.data_path in paths:
                    for k in fc.keyframe_points:
                        if f0 <= k.co.x <= f1:
                            k.interpolation = 'LINEAR'
        return dict(character=rig.name, frames=[f0,f1], chains=len(chains), bones=names,
                    meshes=sorted({c['mesh'] for c in chains}), native_vrm=True,
                    chain_details=[{k:c[k] for k in ('bones','group','public_part','affected_meshes')} for c in chains],
                    collider_count=len(state.get('colliders', [])), cleared=clear,
                    collisions=collisions,
                    skipped=state.get('skipped', []), **measured)
    finally:
        bpy.context.scene.frame_set(saved)
