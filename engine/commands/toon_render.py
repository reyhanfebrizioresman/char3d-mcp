"""Temporary NPR normal field; original meshes, groups and modifiers restored."""
from contextlib import contextmanager
import numpy as np
import bpy
from .toon import neutral_coords,anatomy,LIP_PAIRS
from ..toon import smooth,LID_PAIRS


@contextmanager
def face_normal_proxies(scene):
    """Ellipsoid CUSTOM_NORMAL transfer, masked away from articulated rims.

    Technique credit: MIT blender-agent-skills/blender-stylized-npr, supplied by
    the owner. Native Data Transfer follows the head; no reference script runs.
    """
    owned=[]
    try:
        for body in list(scene.objects):
            if body.type!='MESH' or body.hide_render or body.get('c3d_source')!='mpfb' or body.get('c3d_style') not in ('anime','cartoon','chibi'):continue
            p=neutral_coords(body);_,top,chin,_=anatomy(body,[]);h=top-chin
            head=p[:13380][(p[:13380,2]>chin)&(p[:13380,2]<top)]
            lo,hi=head.min(0),head.max(0);center=(lo+hi)*.5;radii=(hi-lo)*.5
            center[2]=chin+.53*h;radii[2]=.56*h
            from ..toon_refine import ellipsoid_mesh
            vertices,faces=ellipsoid_mesh(center,radii)
            mesh=bpy.data.meshes.new('__c3d_face_normal_proxy');mesh.from_pydata(vertices,[],faces);mesh.update()
            proxy=bpy.data.objects.new(mesh.name,mesh);scene.collection.objects.link(proxy)
            proxy.matrix_world=body.matrix_world.copy();proxy.hide_render=True;proxy.display_type='WIRE'
            for face in mesh.polygons:face.use_smooth=True
            rig=body.find_armature()
            if rig:
                from .anim import semantic_map
                bone=semantic_map(rig).get('head')
                if bone:
                    proxy.parent=rig;proxy.matrix_world=body.matrix_world.copy()
                    group=proxy.vertex_groups.new(name=bone);group.add(list(range(len(vertices))),1.,'REPLACE')
                    proxy.modifiers.new('Head follow','ARMATURE').object=rig
            eye_y=float(p[[24,66,6808,6850],1].mean());u=(p[:,2]-chin)/h
            weight=smooth((u+.02)/.13)*(1-smooth((u-.84)/.15))
            weight*=1-smooth((p[:,1]-eye_y-.06*h)/(.20*h));weight[13380:]=0
            lining=set(body.get('c3d_toon_oral_lining_faces',[]))
            # Transfer the face envelope's normals only to its exterior. Oral
            # walls must keep their inward normals when a vowel opens the lips.
            lining_vertices={i for f in lining for i in body.data.polygons[f].vertices}
            exterior_vertices={i for f in body.data.polygons if f.index not in lining for i in f.vertices}
            if lining_vertices:
                weight[list(lining_vertices-exterior_vertices)]=0
            rim=sorted({i for pairs in LID_PAIRS.values() for pair in pairs for i in pair})
            distance=np.sqrt((((p[:,None,[0,2]]-p[np.asarray(rim)][None,:,[0,2]])/h)**2).sum(2)).min(1)
            weight*=smooth(distance/.006)
            lip=p[np.asarray([i for pair in LIP_PAIRS for i in pair])]
            lip_distance=np.sqrt((((p[:,None,[0,2]]-lip[None,:,[0,2]])/h)**2).sum(2)).min(1)
            weight*=smooth(lip_distance/.003)
            active_group=body.vertex_groups.active_index
            group=body.vertex_groups.new(name='__c3d_face_normal_weight')
            for i in np.flatnonzero(weight>.001):group.add([int(i)],float(weight[i]),'REPLACE')
            mod=body.modifiers.new('__c3d_face_normals','DATA_TRANSFER');mod.object=proxy
            owned.append((body,mod,group,proxy,mesh,active_group))
            mod.use_loop_data=True;mod.data_types_loops={'CUSTOM_NORMAL'};mod.loop_mapping='POLYINTERP_NEAREST'
            mod.mix_mode='MIX';mod.mix_factor=.85;mod.vertex_group=group.name
        yield
    finally:
        for body,mod,group,proxy,mesh,active_group in reversed(owned):
            body.modifiers.remove(mod);body.vertex_groups.remove(group)
            if body.vertex_groups:body.vertex_groups.active_index=active_group
            bpy.data.objects.remove(proxy,do_unlink=True);bpy.data.meshes.remove(mesh)


def key_light(scene):
    from .cinematic import _cast,_classify_lights,_light_role
    cast=_cast(scene);_classify_lights(scene,cast)
    candidates=[o for o in scene.objects if o.type=='LIGHT' and not o.hide_render and o.data.energy>0 and not o.get('c3d_material_catchlight_owner')]
    keys=[o for o in candidates if o.get('c3d_role')=='light' and _light_role(o,cast)=='key']
    return max(keys or candidates,key=lambda o:o.data.energy,default=None)


def key_bands(tree,bsdf,cfg):
    """One motivated key and a soft two-state threshold, independent of energy.

    N.L key shading technique: MIT blender-agent-skills/blender-stylized-npr.
    Native transform drivers follow animated lights in saved video snapshots.
    """
    nodes,links=tree.nodes,tree.links
    geometry=nodes.new('ShaderNodeNewGeometry');light=cfg.get('_toon_key')
    direction=nodes.new('ShaderNodeVectorMath');direction.operation='NORMALIZE'
    if light and light.data.type!='SUN':
        position=nodes.new('ShaderNodeCombineXYZ')
        for i,axis in enumerate('XYZ'):
            fc=position.inputs[i].driver_add('default_value');d=fc.driver;d.type='SCRIPTED';d.expression='v'
            v=d.variables.new();v.name='v';v.type='TRANSFORMS';v.targets[0].id=light;v.targets[0].transform_type='LOC_'+axis;v.targets[0].transform_space='WORLD_SPACE'
        subtract=nodes.new('ShaderNodeVectorMath');subtract.operation='SUBTRACT'
        links.new(position.outputs[0],subtract.inputs[0]);links.new(geometry.outputs['Position'],subtract.inputs[1]);links.new(subtract.outputs[0],direction.inputs[0])
    elif light:
        vector=nodes.new('ShaderNodeCombineXYZ')
        expressions=('cos(rx)*sin(ry)*cos(rz)+sin(rx)*sin(rz)',
                     'cos(rx)*sin(ry)*sin(rz)-sin(rx)*cos(rz)','cos(rx)*cos(ry)')
        for i,expression in enumerate(expressions):
            d=vector.inputs[i].driver_add('default_value').driver;d.type='SCRIPTED';d.expression=expression
            for name,axis in zip(('rx','ry','rz'),'XYZ'):
                v=d.variables.new();v.name=name;v.type='TRANSFORMS';v.targets[0].id=light;v.targets[0].transform_type='ROT_'+axis;v.targets[0].transform_space='WORLD_SPACE'
        links.new(vector.outputs[0],direction.inputs[0])
    else:direction.inputs[0].default_value=(.4,-.65,.65)
    dot=nodes.new('ShaderNodeVectorMath');dot.operation='DOT_PRODUCT'
    links.new(geometry.outputs['Normal'],dot.inputs[0]);links.new(direction.outputs[0],dot.inputs[1])
    light_value=dot.outputs['Value']
    if cfg.get('_toon_role')=='skin':
        # Enlarged HM08 sockets expose the reverse side of a thin lower-lid
        # fold during squints. Its transferred normal can be reversed again
        # by raster backface handling. Keep that side's normal field facing
        # the surface, while ordinary front-facing skin keeps its terminator.
        absolute=nodes.new('ShaderNodeMath');absolute.operation='ABSOLUTE'
        links.new(light_value,absolute.inputs[0])
        choose=nodes.new('ShaderNodeMixRGB')
        links.new(geometry.outputs['Backfacing'],choose.inputs[0])
        links.new(light_value,choose.inputs[1]);links.new(absolute.outputs[0],choose.inputs[2])
        light_value=choose.outputs[0]
    band=nodes.new('ShaderNodeMapRange');band.interpolation_type='SMOOTHSTEP';band.clamp=True
    links.new(light_value,band.inputs[0]);band.inputs['From Min'].default_value=.10;band.inputs['From Max'].default_value=.24
    band.inputs['To Min'].default_value=.72 if cfg.get('_toon_role')=='skin' else .64
    band.inputs['To Max'].default_value=1.05
    if cfg['style']=='animated_film' and cfg.get('_toon_role')=='skin':
        # A broad continuous form gradient, rather than scene-energy thresholds
        # and short-range self-shadowing of the enlarged socket/oral folds.
        # Fifteen percent native normal detail retains the nose/lip surfaces.
        band.inputs['From Min'].default_value=-.45;band.inputs['From Max'].default_value=.95
        band.inputs['To Min'].default_value=.60;band.inputs['To Max'].default_value=1.75
    scalar=band.outputs[0]
    if cfg.get('_toon_role')=='hair':
        half=nodes.new('ShaderNodeVectorMath');half.operation='ADD';links.new(direction.outputs[0],half.inputs[0]);links.new(geometry.outputs['Incoming'],half.inputs[1])
        norm=nodes.new('ShaderNodeVectorMath');norm.operation='NORMALIZE';links.new(half.outputs[0],norm.inputs[0])
        shine=nodes.new('ShaderNodeVectorMath');shine.operation='DOT_PRODUCT';links.new(norm.outputs[0],shine.inputs[0]);links.new(geometry.outputs['Normal'],shine.inputs[1])
        hard=nodes.new('ShaderNodeMapRange');hard.interpolation_type='SMOOTHSTEP';hard.clamp=True
        links.new(shine.outputs['Value'],hard.inputs[0]);hard.inputs['From Min'].default_value=.92;hard.inputs['From Max'].default_value=.96;hard.inputs['To Max'].default_value=.25
        add=nodes.new('ShaderNodeMath');add.operation='ADD';links.new(scalar,add.inputs[0]);links.new(hard.outputs[0],add.inputs[1]);scalar=add.outputs[0]
    pigment=nodes.new('ShaderNodeVectorMath');pigment.operation='SCALE'
    from .render_style import _input
    base=bsdf.inputs['Base Color']
    if base.is_linked:links.new(base.links[0].from_socket,pigment.inputs[0])
    else:pigment.inputs[0].default_value=tuple(base.default_value[:3])
    links.new(scalar,pigment.inputs['Scale'])
    emission=nodes.new('ShaderNodeEmission');links.new(pigment.outputs[0],emission.inputs['Color'])
    transparent=nodes.new('ShaderNodeBsdfTransparent');alpha=nodes.new('ShaderNodeMixShader')
    _input(tree,alpha.inputs[0],bsdf.inputs['Alpha']);links.new(transparent.outputs[0],alpha.inputs[1]);links.new(emission.outputs[0],alpha.inputs[2])
    if cfg['strength']==1:return alpha.outputs[0]
    blend=nodes.new('ShaderNodeMixShader');blend.inputs[0].default_value=cfg['strength']
    links.new(bsdf.outputs[0],blend.inputs[1]);links.new(alpha.outputs[0],blend.inputs[2])
    return blend.outputs[0]
