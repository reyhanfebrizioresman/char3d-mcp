"""Our original CC0 MPFB avatar -> installed VRM add-on's documented native data."""
import json
import re
from pathlib import Path
import addon_utils
import bpy
from engine import context
from engine.commands.anim import semantic_map
from engine.commands.fingers import find_fingers
from engine.vrm import BONES


def export_original(armature,version):
    for module in addon_utils.modules():
        if module.__name__.endswith('.vrm'):addon_utils.enable(module.__name__,default_set=True)
    rig=bpy.data.objects[armature]
    bpy.context.view_layer.objects.active=rig
    for obj in bpy.context.selected_objects:obj.select_set(False)
    rig.select_set(True)
    meshes=[m for m in rig.children_recursive if m.type=='MESH' and not m.hide_render and m.name in bpy.context.view_layer.objects]
    for obj in meshes:obj.select_set(True)
    # Resolve MPFB masks once, on every morph, instead of asking the legacy
    # exporter to evaluate helper/costume masks separately on each target.
    from engine.commands.toon import coords
    import numpy as np
    source_body=next(o for o in meshes if o.get('c3d_kind')=='humanoid')
    source_keys=source_body.data.shape_keys.key_blocks
    indices=[520,540,521,538,7267,7282]
    neutral=coords(source_keys[0].data)
    smile=neutral.copy()
    for name in ('mouthSmileLeft','mouthSmileRight'):
        key=source_keys[name];smile+=.7*(coords(key.data)-coords(key.relative_key.data))
    source_reference=dict(neutral_lips=neutral[indices].tolist(),smile_lips=smile[indices].tolist(),
        relative_keys={k.name:k.relative_key.name for k in source_keys if k.name in ('mouthSmileLeft','mouthSmileRight','aa_02')})
    for obj in meshes:
        masks=[m for m in obj.modifiers if m.type=='MASK']
        if not masks:continue
        attr=obj.data.attributes.new('__fixture_index','INT','POINT')
        attr.data.foreach_set('value',np.arange(len(obj.data.vertices),dtype=np.int32))
        states=[(m,m.show_viewport) for m in obj.modifiers]
        for m,_ in states:m.show_viewport=m.type=='MASK'
        bpy.context.view_layer.update()
        ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh()
        source=np.array([v.value for v in mesh.attributes['__fixture_index'].data])
        keep={int(source[i]) for face in mesh.polygons for i in face.vertices};ev.to_mesh_clear()
        for m,show in states:m.show_viewport=show
        blocks=list(obj.data.shape_keys.key_blocks) if obj.data.shape_keys else []
        ids=sorted(keep);expected=[coords(k.data)[ids] for k in blocks]
        for item in bpy.context.selected_objects:item.select_set(False)
        obj.select_set(True);bpy.context.view_layer.objects.active=obj;obj.active_shape_key_index=0
        bpy.ops.object.mode_set(mode='EDIT')
        import bmesh
        bm=bmesh.from_edit_mesh(obj.data)
        for v in bm.verts:v.select=v.index not in keep
        bmesh.update_edit_mesh(obj.data);bpy.ops.mesh.delete(type='VERT');bpy.ops.object.mode_set(mode='OBJECT')
        for key,want in zip(blocks,expected):assert np.max(abs(coords(key.data)-want))<1e-6,key.name
        for m in masks:obj.modifiers.remove(m)
        obj.data.attributes.remove(obj.data.attributes['__fixture_index'])
    # VRM 0.x requires recognised MToon material data; plain Blender PBR graphs
    # otherwise export as white. Preserve the original pigment/cutout/iris atlas.
    seen=set()
    from engine.commands.materials import _image
    for obj in meshes:
        uv=obj.data.uv_layers.get('c3d_toon_iris')
        if uv:obj.data.uv_layers.active=uv;uv.active_render=True
        for slot in obj.material_slots:
            mat=slot.material
            if not mat or mat in seen:continue
            seen.add(mat)
            diffuse=_image(mat)
            opacity=mat.get('c3d_toon_cutout') or _image(mat,'opacity')
            pigment=list(mat.get('c3d_toon_flat_color',mat.diffuse_color[:3]))
            bsdf=mat.node_tree.nodes.get('Principled BSDF') if mat.node_tree else None
            alpha=bsdf.inputs['Alpha'].default_value if bsdf and not bsdf.inputs['Alpha'].is_linked else 1.
            double_sided=not mat.use_backface_culling
            mtoon=mat.vrm_addon_extension.mtoon1
            # The conversion operator builds nodes but does not enable export.
            mtoon.enabled=True
            mtoon.double_sided=double_sided
            mtoon.pbr_metallic_roughness.base_color_factor=(*( (1.,1.,1.) if diffuse and not opacity else pigment),alpha)
            if diffuse or opacity:mtoon.pbr_metallic_roughness.base_color_texture.index.source=diffuse or opacity
            if opacity or alpha<1:mtoon.alpha_mode='MASK';mtoon.alpha_cutoff=.5
            assert mtoon.enabled,mat.name
    # The legacy exporter reads mesh slots; material OBJECT overrides need to
    # become fixture-local DATA links before exporting this disposable scene.
    for obj in meshes:
        materials=[slot.material for slot in obj.material_slots]
        for i,material in enumerate(materials):
            obj.data.materials[i]=material;obj.material_slots[i].link='DATA'
    ext=rig.data.vrm_addon_extension
    ext.spec_version='1.0' if version==1 else '0.0'
    mapping={vrm:semantic_map(rig)[target] for vrm,target in BONES.items() if target in semantic_map(rig)}
    for side,hand in find_fingers(rig).items():
        prefix='left' if side=='L' else 'right'
        for finger,chain in hand.items():
            finger='little' if finger=='pinky' else finger
            parts=('Metacarpal','Proximal','Distal') if version==1 and finger=='thumb' else ('Proximal','Intermediate','Distal')
            for part,name in zip(parts,chain):mapping[prefix+finger.capitalize()+part]=name
    if version==1:
        human=ext.vrm1.humanoid.human_bones
        for key,name in mapping.items():getattr(human,re.sub(r'(?<!^)([A-Z])',r'_\1',key).lower()).node.bone_name=name
        meta=ext.vrm1.meta;meta.vrm_name='char3d original synthetic toon';meta.version='1'
        meta.authors.add().value='char3d original CC0 MPFB fixture'
        meta.avatar_permission='everyone';meta.other_license_url='https://creativecommons.org/publicdomain/zero/1.0/'
    else:
        ext.vrm0.humanoid.human_bones.clear()
        for key,name in mapping.items():
            bone=ext.vrm0.humanoid.human_bones.add();bone.bone=key;bone.node.bone_name=name
        meta=ext.vrm0.meta;meta.title='char3d original synthetic toon';meta.version='1'
        meta.author='char3d original CC0 MPFB fixture';meta.license_name='CC0'
    expressions={
        'aa':['aa_02'],'ih':['y_iy_ih_ix_06'],'ou':['w_uw_07'],'ee':['ey_eh_uh_04'],'oh':['ow_08'],
        'blinkLeft':['eyeBlinkLeft'],'blinkRight':['eyeBlinkRight'],
        'happy':['mouthSmileLeft','mouthSmileRight'],
        'angry':['browDownLeft','browDownRight'],'sad':['mouthFrownLeft','mouthFrownRight'],
        'relaxed':['mouthDimpleLeft','mouthDimpleRight'],
        'surprised':['eyeWideLeft','eyeWideRight','browOuterUpLeft','browOuterUpRight'],
        'lookLeft':['eyeLookOutLeft','eyeLookInRight'],'lookRight':['eyeLookInLeft','eyeLookOutRight'],
        'lookUp':['eyeLookUpLeft','eyeLookUpRight'],'lookDown':['eyeLookDownLeft','eyeLookDownRight'],
    }
    required={channel for channels in expressions.values() for channel in channels}
    old_names={}
    for obj in meshes:
        if not obj.data.shape_keys:continue
        for key in reversed(list(obj.data.shape_keys.key_blocks)[1:]):
            if key.name not in required:obj.shape_key_remove(key)
        old_names[obj.name]=set(obj.data.shape_keys.key_blocks.keys())
        for key in list(obj.data.shape_keys.key_blocks)[1:]:key.name='Original_'+key.name
    for name,channels in expressions.items():
        if version==1:
            group=getattr(ext.vrm1.expressions.preset,re.sub(r'(?<!^)([A-Z])',r'_\1',name).lower())
            binds=group.morph_target_binds
        else:
            aliases=dict(aa='a',ih='i',ou='u',ee='e',oh='o',happy='joy',sad='sorrow',relaxed='fun',
                         blinkLeft='blink_l',blinkRight='blink_r',lookLeft='lookleft',lookRight='lookright',lookUp='lookup',lookDown='lookdown')
            group=ext.vrm0.blend_shape_master.blend_shape_groups.add();group.name=name
            group.preset_name=aliases.get(name,name) if name!='surprised' else 'unknown';binds=group.binds
        for obj in meshes:
            for channel in channels:
                if channel not in old_names.get(obj.name,set()):continue
                bind=binds.add()
                node=bind.node if version==1 else bind.mesh
                node.mesh_object_name=obj.name;bind.index='Original_'+channel;bind.weight=1.
    path=Path(context.WORKSPACE)/'imports'/('round3_original_vrm'+str(version)+'.vrm')
    for obj in [rig,*meshes]:obj.select_set(True)
    bpy.context.view_layer.objects.active=rig
    result=bpy.ops.export_scene.vrm('EXEC_DEFAULT',filepath=str(path),use_addon_preferences=False,
        armature_object_name=rig.name,export_only_selections=False,export_invisibles=False,
        export_all_influences=True,export_gltf_animations=False,ignore_warning=True)
    assert 'FINISHED' in result and path.is_file(),str(result)
    import struct
    with path.open('rb') as stream:
        header=stream.read(20);length=struct.unpack_from('<I',header,12)[0];document=json.loads(stream.read(length))
    assert document.get('meshes') and document.get('skins'),'VRM export omitted skinned meshes'
    assert len(document.get('images',[]))>=3,'VRM export omitted skin/iris/cutout textures'
    return dict(meshes=len(document['meshes']),images=len(document['images']),source_reference=source_reference,path=str(path),bytes=path.stat().st_size,humanoid=mapping,expression_presets=list(expressions),
                original_asset=True,licence='CC0 MPFB assets and original procedural styling',version=version)
