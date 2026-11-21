"""Temporary Eevee MToon rendering, independent of MPFB Principled bands.

Use the add-on's linear, converted VRM0/1 material parameters. A single key
direction avoids energy-dependent muddy patches and repeated colour conversion.
Original MToon graphs remain available for VRM/glTF export and saved projects.
"""
from contextlib import contextmanager
import math
import bpy
from mathutils import Matrix, Vector


def is_mtoon(material):
    ext = getattr(material, 'vrm_addon_extension', None)
    return bool(ext and ext.mtoon1.enabled and not ext.mtoon1.is_outline_material)


def head_field(rig, style, helpers):
    """Smooth face normals in a head-following frame, never mesh edits.

    Anime flattens depth/height variation, keeping a horizontal cheek gradient
    without exposing chin/nose triangles. Film retains an ellipsoid gradient.
    Technique: owner's MIT blender-agent-skills NPR ellipsoid-normal reference.
    """
    from .vrm_actor import face_mesh
    from .anim import semantic_map
    from .secondary import _basis
    obj=face_mesh(rig)
    if obj is None:return None
    slots={i for i,s in enumerate(obj.material_slots) if s.material and
           'face_' in s.material.name.lower() and 'skin' in s.material.name.lower()}
    ids={i for p in obj.data.polygons if p.material_index in slots for i in p.vertices}
    if not ids:return None
    mapping=semantic_map(rig)
    basis=(rig.matrix_world.to_3x3() @ _basis(rig,mapping)).normalized()
    points=[basis.transposed() @ (obj.matrix_world @ obj.data.vertices[i].co) for i in ids]
    lo=Vector(tuple(min(p[i] for p in points) for i in range(3)))
    hi=Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center=(lo+hi)/2;radii=(hi-lo)/2
    radii.z=(hi.z-lo.z)*(4. if style=='anime' else .65)
    radii=Vector(tuple(max(.01,v) for v in radii))
    anchor=bpy.data.objects.new('__c3d_vrm_head_anchor',None)
    bpy.context.scene.collection.objects.link(anchor);helpers.append(anchor)
    follow=anchor.constraints.new('COPY_TRANSFORMS');follow.target=rig;follow.subtarget=mapping['head']
    field=bpy.data.objects.new('__c3d_vrm_face_normals',None)
    bpy.context.scene.collection.objects.link(field);helpers.append(field)
    field.parent=anchor
    world=basis.to_4x4();world.translation=basis @ center
    rest=rig.matrix_world @ rig.data.bones[mapping['head']].matrix_local
    field.matrix_basis=rest.inverted() @ world
    field['radii']=list(radii)
    field['flat_anime']=style=='anime'
    bpy.context.view_layer.update()
    return field


def material(original, style, key, owned, field=None):
    gltf = original.vrm_addon_extension.mtoon1
    toon = gltf.extensions.vrmc_materials_mtoon
    mat = bpy.data.materials.new('__c3d_vrm_'+original.name)
    owned.append(mat)
    mat['c3d_vrm_material'] = True
    mat.use_nodes = True
    mat.use_backface_culling = not gltf.double_sided
    mat.surface_render_method = 'DITHERED'
    nt = mat.node_tree; nodes = nt.nodes; links = nt.links
    nodes.clear()
    def node(kind):return nodes.new('ShaderNode'+kind)
    def math_node(op, a, b):
        n=node('Math');n.operation=op
        for sock,v in zip(n.inputs,(a,b)):
            if hasattr(v,'node'):links.new(v,sock)
            else:sock.default_value=v
        return n.outputs[0]
    def color(info, factor, vector=None):
        rgba=tuple(factor[:3])+(factor[3] if len(factor)>3 else 1.,)
        source=getattr(getattr(info,'index',None),'source',None) if info else None
        if source:
            tex=node('TexImage');tex.image=source
            uv=node('UVMap');uv.uv_map='UVMap'
            # The imported UV layer may retain its authored name.
            uv.uv_map=''
            transform=info.extensions.khr_texture_transform
            mapping=node('Mapping');mapping.vector_type='POINT'
            mapping.inputs['Location'].default_value=(*transform.offset,0)
            mapping.inputs['Scale'].default_value=(*transform.scale,1)
            mapping.inputs['Rotation'].default_value=(0,0,getattr(transform,'rotation',0.))
            links.new(vector or uv.outputs[0],mapping.inputs[0]);links.new(mapping.outputs[0],tex.inputs['Vector'])
            mix=node('MixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1.
            links.new(tex.outputs['Color'],mix.inputs[1]);mix.inputs[2].default_value=rgba
            alpha=math_node('MULTIPLY',tex.outputs['Alpha'],rgba[3])
            return mix.outputs[0],alpha
        rgb=node('RGB');rgb.outputs[0].default_value=rgba
        return rgb.outputs[0],rgba[3]
    lit,alpha=color(gltf.pbr_metallic_roughness.base_color_texture,gltf.pbr_metallic_roughness.base_color_factor)
    shade_info = toon.shade_multiply_texture
    if not shade_info.index.source:shade_info=gltf.pbr_metallic_roughness.base_color_texture
    shade,_=color(shade_info,toon.shade_color_factor)
    geo=node('NewGeometry')
    normal=geo.outputs['Normal']
    if field:
        coordinates=node('TexCoord');coordinates.object=field
        gradient=node('VectorMath');gradient.operation='MULTIPLY_ADD' if field.get('flat_anime') else 'MULTIPLY'
        links.new(coordinates.outputs['Object'],gradient.inputs[0])
        if field.get('flat_anime'):
            # A full +/-45 degree horizontal spread put the cel terminator
            # down the nose whenever the key sat beside the face. Anime faces
            # read as one flat plane: a narrow spread lights or shades the face
            # almost as a whole, keeping only a soft edge-band transition.
            # Measured on Kabar f94/f110/f140/f177: .2 removes the nose split.
            gradient.inputs[1].default_value=(.2/field['radii'][0],0,0)
            gradient.inputs[2].default_value=(0,-1,0)
        else:gradient.inputs[1].default_value=tuple(1/(r*r) for r in field['radii'])
        normalize=node('VectorMath');normalize.operation='NORMALIZE';links.new(gradient.outputs[0],normalize.inputs[0])
        rotate=node('VectorRotate');rotate.rotation_type='EULER_XYZ'
        links.new(normalize.outputs[0],rotate.inputs['Vector'])
        for i,axis in enumerate('XYZ'):
            driver=rotate.inputs['Rotation'].driver_add('default_value',i).driver;driver.expression='v'
            var=driver.variables.new();var.name='v';var.type='TRANSFORMS'
            var.targets[0].id=field;var.targets[0].transform_type='ROT_'+axis;var.targets[0].transform_space='WORLD_SPACE'
        normal=rotate.outputs[0]
    direction=node('VectorMath');direction.operation='NORMALIZE'
    if key and key.data.type!='SUN':
        xyz=node('CombineXYZ')
        for i,axis in enumerate('XYZ'):
            driver=xyz.inputs[i].driver_add('default_value').driver;driver.expression='v'
            var=driver.variables.new();var.name='v';var.type='TRANSFORMS'
            var.targets[0].id=key;var.targets[0].transform_type='LOC_'+axis;var.targets[0].transform_space='WORLD_SPACE'
        sub=node('VectorMath');sub.operation='SUBTRACT'
        links.new(xyz.outputs[0],sub.inputs[0]);links.new(geo.outputs['Position'],sub.inputs[1]);links.new(sub.outputs[0],direction.inputs[0])
    elif key:
        direction.inputs[0].default_value=tuple(key.matrix_world.to_3x3().col[2])
    else:direction.inputs[0].default_value=(.4,-.65,.65)
    dot=node('VectorMath');dot.operation='DOT_PRODUCT'
    links.new(normal,dot.inputs[0]);links.new(direction.outputs[0],dot.inputs[1])
    shift=toon.shading_shift_factor
    shifted=dot.outputs['Value']
    if toon.shading_shift_texture.index.source:
        texture,_=color(toon.shading_shift_texture,(1,1,1))
        shifted=math_node('ADD',shifted,math_node('MULTIPLY',texture,getattr(toon.shading_shift_texture,'scale',1.)))
    width=max(.015,(1-toon.shading_toony_factor)*.5)
    if style=='anime':width=min(.035,width)
    elif style=='animated_film':width=max(.28,width)
    ramp=node('MapRange');ramp.interpolation_type='SMOOTHSTEP';ramp.clamp=True
    links.new(shifted,ramp.inputs[0])
    ramp.inputs['From Min'].default_value=-shift-width
    ramp.inputs['From Max'].default_value=-shift+width
    hair='hair' in original.name.lower()
    if hair:
        # Near-black authored shade textures merge every clump into one mass.
        # Inspected on Kabar studio_film/blue_hour: a 30% shade lift and 1.25x
        # value keep black/purple hair readable; a fresnel rim greyed it.
        toward=node('MixRGB');toward.inputs[0].default_value=.3
        links.new(shade,toward.inputs[1]);links.new(lit,toward.inputs[2]);shade=toward.outputs[0]
    mix=node('MixRGB');links.new(ramp.outputs[0],mix.inputs[0]);links.new(shade,mix.inputs[1]);links.new(lit,mix.inputs[2])
    pigment=mix.outputs[0]
    if hair:
        lift=node('VectorMath');lift.operation='SCALE';links.new(pigment,lift.inputs[0]);lift.inputs['Scale'].default_value=1.25
        pigment=lift.outputs[0]
    # Rim uses the authored Fresnel colour/power and its multiply texture.
    fresnel=node('LayerWeight')
    if field:links.new(normal,fresnel.inputs['Normal'])
    rim=math_node('POWER',math_node('SUBTRACT',1.,fresnel.outputs['Facing']),max(.01,toon.parametric_rim_fresnel_power_factor))
    rim=math_node('MAXIMUM',math_node('ADD',rim,toon.parametric_rim_lift_factor),0.)
    rim_color,_=color(toon.rim_multiply_texture,toon.parametric_rim_color_factor)
    rim_light=node('MixRGB');rim_light.inputs[0].default_value=toon.rim_lighting_mix_factor
    rim_light.inputs[1].default_value=(1,1,1,1)
    rim_light.inputs[2].default_value=(*(key.data.color if key else (1,1,1)),1)
    rim_tint=node('MixRGB');rim_tint.blend_type='MULTIPLY';rim_tint.inputs[0].default_value=1.
    links.new(rim_color,rim_tint.inputs[1]);links.new(rim_light.outputs[0],rim_tint.inputs[2]);rim_color=rim_tint.outputs[0]
    rim_mix=node('MixRGB');rim_mix.blend_type='ADD';links.new(rim,rim_mix.inputs[0]);links.new(pigment,rim_mix.inputs[1]);links.new(rim_color,rim_mix.inputs[2]);pigment=rim_mix.outputs[0]
    emission,_=color(gltf.emissive_texture,gltf.emissive_factor)
    emissive_strength=gltf.extensions.khr_materials_emissive_strength.emissive_strength
    if emissive_strength!=1:
        scale=node('VectorMath');scale.operation='SCALE';links.new(emission,scale.inputs[0]);scale.inputs['Scale'].default_value=emissive_strength
        emission=scale.outputs[0]
    add=node('MixRGB');add.blend_type='ADD';add.inputs[0].default_value=1.
    links.new(pigment,add.inputs[1]);links.new(emission,add.inputs[2]);pigment=add.outputs[0]
    if toon.matcap_texture.index.source:
        camera_normal=node('VectorTransform');camera_normal.vector_type='NORMAL';camera_normal.convert_from='WORLD';camera_normal.convert_to='CAMERA'
        links.new(geo.outputs['Normal'],camera_normal.inputs[0])
        scale=node('VectorMath');scale.operation='MULTIPLY_ADD';links.new(camera_normal.outputs[0],scale.inputs[0]);scale.inputs[1].default_value=(.5,.5,0);scale.inputs[2].default_value=(.5,.5,0)
        cap,_=color(toon.matcap_texture,toon.matcap_factor,scale.outputs[0])
        add=node('MixRGB');add.blend_type='ADD';add.inputs[0].default_value=1.
        links.new(pigment,add.inputs[1]);links.new(cap,add.inputs[2]);pigment=add.outputs[0]
    emit=node('Emission');links.new(pigment,emit.inputs['Color'])
    output=node('OutputMaterial')
    if gltf.alpha_mode=='OPAQUE':links.new(emit.outputs[0],output.inputs['Surface'])
    else:
        if gltf.alpha_mode=='MASK':alpha=math_node('GREATER_THAN',alpha,gltf.alpha_cutoff)
        trans=node('BsdfTransparent');blend=node('MixShader')
        if hasattr(alpha,'node'):links.new(alpha,blend.inputs[0])
        else:blend.inputs[0].default_value=alpha
        links.new(trans.outputs[0],blend.inputs[1]);links.new(emit.outputs[0],blend.inputs[2]);links.new(blend.outputs[0],output.inputs['Surface'])
    return mat


@contextmanager
def applied(scene, config):
    if config and not config.get('strength',1.):config=None
    if any(o.type=='ARMATURE' and o.get('c3d_rig_type')=='vrm' for o in scene.objects):
        from .vrm import enable_addon
        if not hasattr(bpy.types.Armature, 'vrm_addon_extension'):
            enable_addon()
    if scene.render.engine=='BLENDER_WORKBENCH' or not any(o.type=='MESH' and not o.hide_render
            and any(s.material and is_mtoon(s.material) for s in o.material_slots) for o in scene.objects):
        yield
        return
    from .toon_render import key_light
    style=(config or {}).get('style','none')
    key=key_light(scene)
    slots=[];materials=[];modifiers=[];inputs=[];cache={};fields={};helpers=[]
    try:
        for obj in list(scene.objects):
            if obj.type!='MESH' or obj.hide_render or not any(is_mtoon(s.material) for s in obj.material_slots if s.material):continue
            assigned={}
            for slot in obj.material_slots:
                orig=slot.material
                if not orig or not is_mtoon(orig):continue
                field=None
                if style in ('anime','animated_film') and 'face_' in orig.name.lower() and 'skin' in orig.name.lower():
                    rig=obj.find_armature()
                    if rig:
                        if rig not in fields:fields[rig]=head_field(rig,style,helpers)
                        field=fields[rig]
                cache_key=orig,field
                if cache_key not in cache:
                    cache[cache_key]=material(orig,style,key,materials,field)
                assigned[orig]=cache[cache_key]
                link=slot.link;slot.link='OBJECT';slots.append((slot,link,slot.material));slot.material=cache[cache_key]
            for modifier in obj.modifiers:
                if modifier.name.startswith('MToon Outline'):
                    modifiers.append((modifier,modifier.show_render))
                    modifier.show_render=(config or {}).get('outline',style!='animated_film')
                    sockets={s.name:getattr(modifier.properties.inputs,s.identifier) for s in modifier.node_group.interface.items_tree
                             if s.item_type=='SOCKET' and s.in_out=='INPUT'}
                    source=sockets.get('Material')
                    if source and source.value in assigned:
                        inputs.append((source,source.value));source.value=assigned[source.value]
                    width=sockets.get('Outline Width Factor')
                    mode=sockets.get('Outline Width Mode')
                    if width and mode and width.value>0 and scene.camera:
                        # Clamp world-space extrusion to 1.25 output pixels at
                        # the subject depth. Screen-space authored modes already
                        # compensate perspective; scale their fractional width.
                        old=width.value;inputs.append((width,old))
                        pixels=max(scene.render.resolution_x,scene.render.resolution_y)*scene.render.resolution_percentage/100
                        if mode.value==1:
                            depth=abs((scene.camera.matrix_world.inverted() @ obj.matrix_world.translation).z)
                            limit=2*depth*math.tan(scene.camera.data.angle/2)*1.25/max(1,pixels)
                            width.value=min(old,limit)
                        else:width.value=min(old,1.25/max(1,pixels))
        yield
    finally:
        for socket,value in reversed(inputs):socket.value=value
        for modifier,shown in modifiers:modifier.show_render=shown
        for slot,link,orig in reversed(slots):slot.material=orig;slot.link=link
        for mat in materials:bpy.data.materials.remove(mat)
        for obj in reversed(helpers):bpy.data.objects.remove(obj,do_unlink=True)
