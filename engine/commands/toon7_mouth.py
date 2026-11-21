"""Original, native skinned mouth pocket, tooth band and tongue for MPFB toons."""
import numpy as np
import bpy
from .toon import neutral_coords,coords,anatomy
from .toon_refine import _lip_paths


from ..toon_refine import disk_grid,mouth_points


def _material(part):
    from .toon import image
    # Value changes vertically; the cavity is a dark warm pigment, never black.
    # Reserve a small value floor for the cinematic contrast curve: a merely
    # nonzero albedo still graded to black in half of the open-mouth pixels.
    palette={'cavity':((.130,.085,.090),(.065,.045,.055)),
             'teeth_band':((.58,.51,.40),(.70,.65,.54)),
             'tongue':((.160,.065,.065),(.230,.085,.085))}
    bottom,top=map(np.asarray,palette[part]);v=np.linspace(0,1,64)[:,None,None]
    rgba=np.ones((64,64,4),np.float32);rgba[:,:,:3]=bottom[None,None,:]*(1-v)+top[None,None,:]*v
    texture=image('c3d_toon.mouth_'+part,rgba)
    mat=bpy.data.materials.new('c3d_toon.teeth_'+part);mat.use_nodes=True
    mat['c3d_toon_role']='mouth';mat['c3d_toon_mouth']=part
    mat.diffuse_color=tuple((bottom+top)*.5)+(1.,)
    bsdf=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=texture
    mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
    mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Emission Color'])
    bsdf.inputs['Emission Strength'].default_value=.25
    bsdf.inputs['Roughness'].default_value=.85;bsdf.inputs['Specular IOR Level'].default_value=.05
    return mat


def styled_shader(tree,bsdf,strength=1.):
    """Keep the shallow mouth's authored value gradient under both NPR styles."""
    from .render_style import _input
    emission=tree.nodes.new('ShaderNodeEmission')
    _input(tree,emission.inputs['Color'],bsdf.inputs['Base Color'])
    if strength==1:return emission.outputs[0]
    mix=tree.nodes.new('ShaderNodeMixShader');mix.inputs[0].default_value=strength
    tree.links.new(bsdf.outputs[0],mix.inputs[1]);tree.links.new(emission.outputs[0],mix.inputs[2])
    return mix.outputs[0]


def build_mouth(body,meshes):
    if body.get('c3d_toon_mouth_version') or not body.data.shape_keys:return
    from .materials import _role
    p=neutral_coords(body);_,top,chin,_=anatomy(body,meshes,p);h=top-chin
    upper,lower=_lip_paths(p);params,faces=disk_grid()
    # Hide the detailed dental assets in Blender and portable material export.
    # Native geometry/weights/targets remain available; only stylized builds use
    # these simplified inserts. No change to the body's Basis topology.
    for obj in list(meshes):
        if _role(obj,body)!='mouth' or obj.get('c3d_toon_mouth'):continue
        obj.hide_render=True;obj.hide_viewport=True;obj['c3d_toon_hidden_mouth']=True
        for slot in obj.material_slots:
            if not slot.material:continue
            mat=slot.material.copy();slot.link='OBJECT';slot.material=mat
            mat.diffuse_color=(*mat.diffuse_color[:3],0.);mat.surface_render_method='DITHERED'
            if mat.node_tree:
                for node in mat.node_tree.nodes:
                    if node.type=='BSDF_PRINCIPLED':
                        for link in list(node.inputs['Alpha'].links):mat.node_tree.links.remove(link)
                        node.inputs['Alpha'].default_value=0.
    keys=body.data.shape_keys.key_blocks;rig=body.find_armature()
    for part in ('cavity','teeth_band','tongue'):
        base=mouth_points(p,upper,lower,params,h,part)
        mesh=bpy.data.meshes.new(body.name+'.mouth_'+part);mesh.from_pydata(base.tolist(),[],faces);mesh.update()
        obj=bpy.data.objects.new(mesh.name,mesh);bpy.context.collection.objects.link(obj)
        obj.parent=body.parent;obj.matrix_world=body.matrix_world.copy()
        obj['c3d_source']='toon_helper';obj['c3d_material_part']='teeth_'+part
        obj['c3d_toon_mouth']=part
        uv=mesh.uv_layers.new(name='c3d_toon_mouth')
        for loop in mesh.loops:uv.data[loop.index].uv=(params[loop.vertex_index]+1)*.5
        for key in keys:
            target=obj.shape_key_add(name=key.name,from_mix=False)
            points=mouth_points(coords(key.data),upper,lower,params,h,part,extension=float(part=='tongue' and key.name=='tongueOut'))
            target.data.foreach_set('co',points.astype(np.float32).ravel())
            target.value=key.value
        for key in keys:
            obj.data.shape_keys.key_blocks[key.name].relative_key=obj.data.shape_keys.key_blocks[key.relative_key.name]
        for group in body.vertex_groups:obj.vertex_groups.new(name=group.name)
        # Transfer native lip weights (rather than a new skeleton or controls).
        for i,point in enumerate(base):
            source=min(upper if part=='teeth_band' else lower if part=='tongue' else upper+lower,
                       key=lambda k:float(np.sum((p[k,[0,2]]-point[[0,2]])**2)))
            for group in body.data.vertices[source].groups:
                obj.vertex_groups[group.group].add([i],group.weight,'REPLACE')
        if rig:obj.modifiers.new('Native skin','ARMATURE').object=rig
        for face in mesh.polygons:face.use_smooth=True
        mesh.materials.append(_material(part));meshes.append(obj)
    body['c3d_toon_mouth_version']=4
