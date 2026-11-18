"""Blender realization of pure recipes; no operators, handlers, caches or downloads.

One object per semantic part. Opaque folded foliage avoids alpha overdraw. Native
shape drivers and geometry nodes survive save/open and background rendering.
"""
import json
import math
import re

import bpy
from mathutils import Vector

from .core import Material


def _material(builder, spec):
    key = 'nature_' + json.dumps(spec.__dict__, sort_keys=True)
    if key in builder.materials:
        return builder.materials[key]
    mat = builder.material(spec.name, spec.color, spec.metallic, spec.emission)
    builder.materials[key] = mat
    mat['c3d_nature'] = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get('Principled BSDF')
    bsdf.inputs['Roughness'].default_value = spec.roughness
    if spec.surface:
        mat['char3d_surface'] = spec.surface
    if spec.shader:
        _authored_shader(nodes,links,bsdf,spec)
    elif spec.surface == 'water':
        bsdf.inputs['Coat Weight'].default_value = .35
        # Opaque water is deliberate: CPU Eevee reflections without screen-space
        # refraction, layered transparent planes, simulation or render subdivision.
        noise = nodes.new('ShaderNodeTexNoise');noise.noise_dimensions='4D'
        noise.inputs['Scale'].default_value = 2.6
        noise.inputs['Detail'].default_value = 2
        coord=nodes.new('ShaderNodeTexCoord')
        links.new(coord.outputs['Object'],noise.inputs['Vector'])
        _driver(noise.inputs['W'], 'default_value', 'frame*base/fps*.12')
        fine = nodes.new('ShaderNodeTexNoise');fine.inputs['Scale'].default_value=37
        links.new(coord.outputs['Object'],fine.inputs['Vector'])
        coarse = nodes.new('ShaderNodeBump');coarse.inputs['Strength'].default_value=.24
        coarse.inputs['Distance'].default_value=.055
        bump = nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.14
        bump.inputs['Distance'].default_value=.008
        links.new(noise.outputs['Fac'],coarse.inputs['Height'])
        links.new(coarse.outputs['Normal'],bump.inputs['Normal'])
        links.new(fine.outputs['Fac'],bump.inputs['Height'])
        links.new(bump.outputs['Normal'],bsdf.inputs['Normal'])
        if spec.name=='sea_water':
            xyz=nodes.new('ShaderNodeSeparateXYZ');links.new(coord.outputs['Object'],xyz.inputs[0])
            depth=nodes.new('ShaderNodeMapRange')
            depth.inputs['From Min'].default_value=0;depth.inputs['From Max'].default_value=38
            links.new(xyz.outputs['Y'],depth.inputs[0])
            ramp=nodes.new('ShaderNodeValToRGB')
            ramp.color_ramp.elements[0].color=(.025,.34,.30,1)
            ramp.color_ramp.elements[1].color=(.018,.14,.23,1)
            links.new(depth.outputs[0],ramp.inputs[0]);links.new(ramp.outputs[0],bsdf.inputs['Base Color'])
    elif spec.name.startswith(('leaf','bush','rice','grass','blossom')):
        bsdf.inputs['Roughness'].default_value=.72
        bsdf.inputs['Subsurface Weight'].default_value=.035
    elif spec.surface in ('grass','earth','gravel','sand','stone') or spec.name == 'bark':
        noise=nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=18 if spec.name=='bark' else 7
        coord=nodes.new('ShaderNodeTexCoord');links.new(coord.outputs['Object'],noise.inputs['Vector'])
        noise.inputs['Detail'].default_value=2
        ramp=nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color=(*[v*.7 for v in spec.color],1)
        ramp.color_ramp.elements[1].color=(*[min(1,v*1.2) for v in spec.color],1)
        links.new(noise.outputs['Fac'],ramp.inputs[0]);links.new(ramp.outputs[0],bsdf.inputs['Base Color'])
        bump=nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.18
        bump.inputs['Distance'].default_value=.025
        links.new(noise.outputs['Fac'],bump.inputs['Height']);links.new(bump.outputs[0],bsdf.inputs['Normal'])
    return mat


def _authored_shader(nodes,links,bsdf,spec):
    """Fixed internal profiles. Recipe data can never supply nodes or expressions."""
    coord=nodes.new('ShaderNodeTexCoord')
    noise=nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=3.8
    noise.inputs['Detail'].default_value=3
    links.new(coord.outputs['Object'],noise.inputs['Vector'])
    ramp=nodes.new('ShaderNodeValToRGB')
    lo,hi=.65,1.15
    if spec.shader=='cloud':
        geometry=nodes.new('ShaderNodeNewGeometry');xyz=nodes.new('ShaderNodeSeparateXYZ')
        links.new(geometry.outputs['Normal'],xyz.inputs[0])
        height=nodes.new('ShaderNodeMapRange');height.inputs['From Min'].default_value=-1
        links.new(xyz.outputs['Z'],height.inputs[0]);links.new(height.outputs[0],ramp.inputs[0])
        ramp.color_ramp.elements[0].color=(spec.color[0]*.38,spec.color[1]*.47,spec.color[2]*.65,1)
        ramp.color_ramp.elements[1].color=(*spec.color,1)
        bsdf.inputs['Subsurface Weight'].default_value=.22
        bsdf.inputs['Subsurface Radius'].default_value=(2,1.4,.9)
    elif spec.shader=='mist':
        ramp.color_ramp.elements[0].color=(*spec.color,1)
        ramp.color_ramp.elements[1].color=(*spec.color,1)
        # Thin mist geometry, with a soft Fresnel edge and noise holes; no volume.
        layer=nodes.new('ShaderNodeLayerWeight');fade=nodes.new('ShaderNodeMath');fade.operation='SUBTRACT'
        fade.inputs[0].default_value=1;links.new(layer.outputs['Facing'],fade.inputs[1])
        alpha=nodes.new('ShaderNodeMath');alpha.operation='MULTIPLY'
        links.new(fade.outputs[0],alpha.inputs[0]);alpha.inputs[1].default_value=.17
        links.new(alpha.outputs[0],bsdf.inputs['Alpha'])
        bsdf.inputs['Emission Color'].default_value=(*spec.color,1)
        bsdf.inputs['Emission Strength'].default_value=.12
    else:
        field=noise.outputs['Fac']
        if spec.shader=='scales':
            mapping=nodes.new('ShaderNodeVectorMath');mapping.operation='MULTIPLY'
            links.new(coord.outputs['UV'],mapping.inputs[0]);mapping.inputs[1].default_value=(90,24,1)
            vor=nodes.new('ShaderNodeTexVoronoi');vor.feature='DISTANCE_TO_EDGE'
            links.new(mapping.outputs[0],vor.inputs['Vector']);field=vor.outputs['Distance']
            ramp.color_ramp.elements[0].position=.018;ramp.color_ramp.elements[1].position=.12
            lo=.42;hi=1.22
        elif spec.shader=='belly':
            wave=nodes.new('ShaderNodeTexWave');wave.bands_direction='Y'
            wave.inputs['Scale'].default_value=4;wave.inputs['Distortion'].default_value=.35
            links.new(coord.outputs['Object'],wave.inputs['Vector']);field=wave.outputs['Color'];lo=.85;hi=1.08
        elif spec.shader=='strata':
            wave=nodes.new('ShaderNodeTexWave');wave.bands_direction='Z'
            wave.inputs['Scale'].default_value=3;wave.inputs['Distortion'].default_value=7
            wave.inputs['Detail Scale'].default_value=.6
            links.new(coord.outputs['Object'],wave.inputs['Vector']);field=wave.outputs['Color'];lo=.78;hi=1.15
        elif spec.shader=='mountain':
            geo=nodes.new('ShaderNodeNewGeometry');xyz=nodes.new('ShaderNodeSeparateXYZ')
            links.new(geo.outputs['Normal'],xyz.inputs[0]);field=xyz.outputs['Z'];lo=.55;hi=1.25
        ramp.color_ramp.elements[0].color=(*[v*lo for v in spec.color],1)
        ramp.color_ramp.elements[1].color=(*[min(1,v*hi) for v in spec.color],1)
        links.new(field,ramp.inputs[0])
    links.new(ramp.outputs['Color'],bsdf.inputs['Base Color'])
    bump=nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.13
    bump.inputs['Distance'].default_value=.015 if spec.shader in ('scales','skin','belly') else .06
    links.new(noise.outputs['Fac'],bump.inputs['Height']);links.new(bump.outputs[0],bsdf.inputs['Normal'])


def _driver(owner, prop, expression, wind=False,index=None):
    curve=owner.driver_add(prop) if index is None else owner.driver_add(prop,index)
    d=curve.driver;d.type='SCRIPTED';d.expression=expression
    for name,path in [('fps','render.fps'),('base','render.fps_base')]+(
            [('wx','["c3d_nature_wind_x"]'),('wy','["c3d_nature_wind_y"]')] if wind else []):
        v=d.variables.new();v.name=name;v.type='SINGLE_PROP'
        v.targets[0].id_type='SCENE';v.targets[0].id=bpy.context.scene
        v.targets[0].data_path=path
    return curve


def sync_wind(wind=None):
    """Weather and hair/cloth read the same saved world acceleration vector."""
    sc=bpy.context.scene
    wind=wind if wind is not None else sc.get('c3d_weather_wind',(.45,.12,0))
    for axis,value in zip('xy',wind): sc['c3d_nature_wind_'+axis]=float(value)
    sc.update_tag()


def _shape(obj,name,offset,expression,wind=False):
    if not obj.data.shape_keys: obj.shape_key_add(name='Basis')
    key=obj.shape_key_add(name=name)
    for p,target in zip(obj.data.vertices,key.data): target.co=p.co+Vector(offset(p.co))
    key.slider_min=-10;key.slider_max=10
    curve=_driver(key,'value',expression,wind)
    if wind: _local_wind(curve,obj)
    obj.data.shape_keys['c3d_nature']=True


def _local_wind(curve,obj):
    """World wind stays aligned across randomly rotated trees and moved roots."""
    d=curve.driver
    v=d.variables.new();v.name='az';v.type='TRANSFORMS'
    v.targets[0].id=obj;v.targets[0].transform_type='ROT_Z';v.targets[0].transform_space='WORLD_SPACE'
    values=dict(wx='(wx*cos(az)+wy*sin(az))',wy='(-wx*sin(az)+wy*cos(az))')
    d.expression=re.sub(r'\b(wx|wy)\b',lambda m:values[m[0]],d.expression)


def _motion(obj,spec):
    kind=spec['kind'];seed=spec.get('seed',0)
    phase=(seed*.618033989 % 1)*math.tau
    if kind=='sway':
        _sway_nodes(obj,spec)
    elif kind in ('water','waterfall'):
        amp=spec['amplitude']
        _shape(obj,'Wave A',lambda p:(0,0,amp*math.sin(p.x*.71+p.y*1.17)), 'sin(frame*base/fps*1.1)')
        _shape(obj,'Wave B',lambda p:(0,0,amp*math.cos(p.x*.71+p.y*1.17)), 'cos(frame*base/fps*1.1)')
    elif kind in ('petals','fall'):
        _falling(obj,spec)
    elif kind=='fireflies':
        _shape(obj,'Drift A',lambda p:(.16*math.sin(p.x+p.y),.12*math.cos(p.y),.12*math.sin(p.x)),
               'sin(frame*base/fps*.8)')
        _shape(obj,'Drift B',lambda p:(.16*math.cos(p.x+p.y),.12*math.sin(p.y),.12*math.cos(p.x)),
               'cos(frame*base/fps*.8)')
    elif kind in ('bird','butterfly'):
        xs=[v.co.x for v in obj.data.vertices];mid=(min(xs)+max(xs))/2
        _shape(obj,'Wingbeat',lambda p:(0,0,abs(p.x-mid)*1.4),
               f'sin(frame*base/fps*{12 if kind=="bird" else 27}+{spec.get("phase",0)})')
        if kind=='bird':
            path=spec['path']
            if len(path)==2:
                a,b=path
                center=(Vector(a)+Vector(b))/2;delta=(Vector(b)-Vector(a))/2
                # A closed ellipse through both specified points, no offscreen reset.
                path=[list(center+delta*math.cos(i*math.tau/24)+Vector((0,4*math.sin(i*math.tau/24),
                    .6*math.sin(i*math.tau/24)))) for i in range(24)]
            _flight(obj,path,spec.get('phase',0))
        else:
            for axis,amp in enumerate((.4,.3,.18)):
                _driver(obj,'location',f'{amp}*sin(frame*base/fps*{24/(9+axis*3)}+{phase})',index=axis)
    obj['c3d_nature_motion']=json.dumps(spec)


def _sway_nodes(obj,spec):
    """One saved field graph; bounded native wind, seeded gusts and rooted tips."""
    if any(m.type=='NODES' and m.node_group and m.node_group.get('c3d_nature_sway') for m in obj.modifiers): return
    phase=(spec.get('seed',0)*.618033989%1)*math.tau
    low=spec.get('base',min(v.co.z for v in obj.data.vertices))
    weights=[min(1.3,max(0,(v.co.z-low)/spec['height']))**1.8*spec['amplitude'] for v in obj.data.vertices]
    attribute=obj.data.attributes.get('c3d_sway_weight') or obj.data.attributes.new('c3d_sway_weight','FLOAT','POINT')
    attribute.data.foreach_set('value',weights)
    group=bpy.data.node_groups.new(obj.name+'_Sway','GeometryNodeTree')
    group['c3d_nature']=group['c3d_nature_sway']=True
    group.interface.new_socket(name='Geometry',in_out='INPUT',socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
    nodes,links=group.nodes,group.links
    inp=nodes.new('NodeGroupInput');out=nodes.new('NodeGroupOutput')
    time=nodes.new('GeometryNodeInputSceneTime')
    attr=nodes.new('GeometryNodeInputNamedAttribute');attr.data_type='FLOAT'
    attr.inputs['Name'].default_value='c3d_sway_weight'
    def calc(operation,a,b=None):
        n=nodes.new('ShaderNodeMath');n.operation=operation
        for i,value in enumerate((a,b)):
            if value is None: continue
            if isinstance(value,(float,int)): n.inputs[i].default_value=value
            else: links.new(value,n.inputs[i])
        return n.outputs[0]
    vector=nodes.new('ShaderNodeCombineXYZ')
    for axis,name,f1,f2 in (('X','wx',1.7,3.1),('Y','wy',1.4,2.7)):
        wind=nodes.new('ShaderNodeValue')
        curve=_driver(wind.outputs[0],'default_value',f'min(3,max(-3,{name}))',True)
        _local_wind(curve,obj)
        a=calc('SINE',calc('ADD',calc('MULTIPLY',time.outputs['Seconds'],f1),phase))
        b=calc('SINE',calc('ADD',calc('MULTIPLY',time.outputs['Seconds'],f2),phase))
        gust=calc('ADD',calc('ADD',.55,calc('MULTIPLY',a,.35)),calc('MULTIPLY',b,.10))
        offset=calc('MULTIPLY',calc('MULTIPLY',gust,wind.outputs[0]),attr.outputs['Attribute'])
        links.new(offset,vector.inputs[axis])
    deform=nodes.new('GeometryNodeSetPosition')
    links.new(inp.outputs[0],deform.inputs['Geometry']);links.new(vector.outputs[0],deform.inputs['Offset'])
    links.new(deform.outputs[0],out.inputs[0])
    obj.modifiers.new('Saved Scene Time wind','NODES').node_group=group
    obj['c3d_nature_motion_backend']='geometry_nodes'


def upgrade_saved_sway():
    """Upgrade only the kit's old three-key sway; preserve custom morphs.

    Used by the evidence harness to compare/benchmark saved milestone scenes.
    Current generators create the same analytic field directly as geometry nodes.
    """
    changed=[]
    for obj in bpy.context.scene.objects:
        if obj.type!='MESH' or not obj.get('c3d_nature_motion'): continue
        spec=json.loads(obj['c3d_nature_motion'])
        if spec['kind']!='sway' or obj.get('c3d_nature_motion_backend')=='geometry_nodes': continue
        keys=obj.data.shape_keys
        if keys and set(keys.key_blocks.keys())-{'Basis','Breeze X','Breeze Y'}:
            raise ValueError(f'{obj.name}: custom shape keys retained; upgrade manually')
        if keys: obj.shape_key_clear()
        _sway_nodes(obj,spec);changed.append(obj.name)
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    return changed


def _flight(obj,path,phase):
    # Cyclic Catmull-Rom positions and tangential heading, with linear baked keys.
    from ..commands.talk import _fcurves
    ps=[Vector(p) for p in path]
    length=sum((b-a).length for a,b in zip(ps,ps[1:]+ps[:1]))
    sc=bpy.context.scene;fps=sc.render.fps/sc.render.fps_base
    period=max(24,round(length/4*fps));period += period%2
    previous=None
    for f in range(0,period+1,2):
        u=(f/period+phase/math.tau)%1*len(ps);i=int(u);t=u-i
        a,b,c,d=[ps[(i+j)%len(ps)] for j in (-1,0,1,2)]
        pos=.5*((2*b)+(-a+c)*t+(2*a-5*b+4*c-d)*t*t+(-a+3*b-3*c+d)*t*t*t)
        tangent=.5*((-a+c)+2*(2*a-5*b+4*c-d)*t+3*(-a+3*b-3*c+d)*t*t)
        yaw=math.atan2(tangent.x,-tangent.y)
        if previous is not None: yaw=previous+(yaw-previous+math.pi)%math.tau-math.pi
        previous=yaw
        obj.location=pos;obj.rotation_euler.z=yaw
        obj.keyframe_insert('location',frame=f);obj.keyframe_insert('rotation_euler',frame=f)
    for fc in _fcurves(obj.animation_data.action):
        for key in fc.keyframe_points: key.interpolation='LINEAR'
        mod=fc.modifiers.new('CYCLES')
        if fc.data_path=='rotation_euler': mod.mode_before=mod.mode_after='REPEAT_OFFSET'
    obj.animation_data.action['c3d_nature']=True


def _falling(obj,spec):
    if 'c3d_particle_pivot' not in obj.data.attributes:
        # Legacy kit leaves have six disconnected triangles (18 vertices).
        vs=obj.data.vertices
        if len(vs)%18: raise ValueError('falling mesh has custom topology; supply particle pivots')
        pivots=[]
        for i in range(0,len(vs),18):
            p=sum((v.co for v in vs[i:i+18]),Vector())/18
            pivots.extend([p]*18)
        _pivots(obj.data,pivots)
    group=bpy.data.node_groups.new(obj.name+'_drift','GeometryNodeTree');group['c3d_nature']=True
    group['c3d_nature_particle_version']=2
    group.interface.new_socket(name='Geometry',in_out='INPUT',socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
    nodes,links=group.nodes,group.links
    inp=nodes.new('NodeGroupInput');out=nodes.new('NodeGroupOutput')
    pos=nodes.new('GeometryNodeInputPosition');time=nodes.new('GeometryNodeInputSceneTime')
    pivot=nodes.new('GeometryNodeInputNamedAttribute');pivot.data_type='FLOAT_VECTOR'
    pivot.inputs['Name'].default_value='c3d_particle_pivot'
    scale=nodes.new('ShaderNodeVectorMath');scale.operation='SCALE'
    velocity=nodes.new('ShaderNodeCombineXYZ');velocity.inputs['Z'].default_value=-.42
    for axis,expression in (('X','wx*.12'),('Y','wy*.12')):
        curve=_driver(velocity.inputs[axis],'default_value',expression,True)
        _local_wind(curve,obj)
    links.new(velocity.outputs[0],scale.inputs[0])
    links.new(time.outputs['Seconds'],scale.inputs['Scale'])
    add=nodes.new('ShaderNodeVectorMath');add.operation='ADD'
    links.new(pivot.outputs['Attribute'],add.inputs[0]);links.new(scale.outputs[0],add.inputs[1])
    wrap=nodes.new('ShaderNodeVectorMath');wrap.operation='WRAP'
    coords=[v.co for v in obj.data.vertices]
    # Reset beyond the ground/top of the composition, never around the face plane.
    wrap.inputs[1].default_value=(max(p.x for p in coords)+.4,max(p.y for p in coords)+.4,max(p.z for p in coords)+1)
    wrap.inputs[2].default_value=(min(p.x for p in coords)-.4,min(p.y for p in coords)-.4,-.12)
    links.new(add.outputs[0],wrap.inputs[0])
    # Wrap whole particles, never individual vertices. Scale to zero at both
    # boundaries so a looping birth/death cannot stretch or pop across the view.
    xyz=nodes.new('ShaderNodeSeparateXYZ');links.new(wrap.outputs[0],xyz.inputs[0])
    fades=[]
    for a,b,u,v in ((-.12,.18,0,1),(max(p.z for p in coords)+.5,max(p.z for p in coords)+1,1,0)):
        fade=nodes.new('ShaderNodeMapRange');fade.clamp=True
        fade.inputs['From Min'].default_value=a;fade.inputs['From Max'].default_value=b
        fade.inputs['To Min'].default_value=u;fade.inputs['To Max'].default_value=v
        links.new(xyz.outputs['Z'],fade.inputs[0]);fades.append(fade.outputs[0])
    gain=nodes.new('ShaderNodeMath');gain.operation='MULTIPLY'
    links.new(fades[0],gain.inputs[0]);links.new(fades[1],gain.inputs[1])
    local=nodes.new('ShaderNodeVectorMath');local.operation='SUBTRACT'
    links.new(pos.outputs[0],local.inputs[0]);links.new(pivot.outputs['Attribute'],local.inputs[1])
    resize=nodes.new('ShaderNodeVectorMath');resize.operation='SCALE'
    links.new(local.outputs[0],resize.inputs[0]);links.new(gain.outputs[0],resize.inputs['Scale'])
    final=nodes.new('ShaderNodeVectorMath');final.operation='ADD'
    links.new(wrap.outputs[0],final.inputs[0]);links.new(resize.outputs[0],final.inputs[1])
    setpos=nodes.new('GeometryNodeSetPosition')
    links.new(inp.outputs[0],setpos.inputs['Geometry'])
    links.new(final.outputs[0],setpos.inputs['Position'])
    links.new(setpos.outputs[0],out.inputs[0])
    obj.modifiers.new('Saved petal drift','NODES').node_group=group


def _pivots(mesh,values):
    attribute=mesh.attributes.get('c3d_particle_pivot') or mesh.attributes.new('c3d_particle_pivot','FLOAT_VECTOR','POINT')
    attribute.data.foreach_set('vector',[component for p in values for component in p])


def upgrade_saved_motion():
    changed=upgrade_saved_sway()
    for obj in bpy.context.scene.objects:
        if obj.type!='MESH' or not obj.get('c3d_nature_motion'): continue
        spec=json.loads(obj['c3d_nature_motion'])
        if spec['kind'] not in ('fall','petals'): continue
        mods=[m for m in obj.modifiers if m.type=='NODES' and m.node_group and m.node_group.get('c3d_nature')]
        if any(m.node_group.get('c3d_nature_particle_version')==2 for m in mods): continue
        for mod in mods:
            data=mod.node_group;obj.modifiers.remove(mod)
            if not data.users: bpy.data.node_groups.remove(data)
        _falling(obj,spec);changed.append(obj.name)
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    return changed


def realize(builder,asset,location=(0,0,0),rotation=0.,scale=1.):
    """Create all parts under builder.root; returns their actual Blender names."""
    out=[]
    sync_wind()
    for part in asset.parts:
        if not part.faces: continue
        data=bpy.data.meshes.new('Nature_'+part.name)
        data.from_pydata(part.vertices,[],part.faces);data.update()
        if part.uvs:
            uv=data.uv_layers.new(name='AuthoredUV')
            for loop in data.loops:uv.data[loop.index].uv=part.uvs[loop.vertex_index]
        if part.pivots: _pivots(data,part.pivots)
        obj=builder._link(bpy.data.objects.new(builder.root.name+'_'+part.name,data))
        obj.parent=builder.root
        obj['c3d_nature']=True
        obj['c3d_nature_kind']=asset.kind
        obj['c3d_nature_solid']=part.solid
        obj['c3d_nature_occludes']=part.occludes
        if part.walkable: obj['char3d_walkable']=True;obj['c3d_weather_ground']=True
        for spec in part.materials: data.materials.append(_material(builder,spec))
        for p,index in zip(data.polygons,part.indices): p.material_index=index;p.use_smooth=part.smooth
        obj.color=(*part.materials[0].color,1)
        if part.materials[0].surface: obj['char3d_surface']=part.materials[0].surface
        if part.seat:
            obj['c3d_seat_centers']=json.dumps(part.seat['centers'])
            obj['c3d_seat_surface_height']=part.seat['centers'][0][2]
            obj['c3d_seat_front']=part.seat['front'];obj['c3d_seat_floor']=part.seat['floor']
            obj['c3d_seat_kind']='stone'
            if builder.root.get('c3d_nature_root'): builder.root['c3d_seat_anchor']=obj.name
        if part.motion: _motion(obj,part.motion)
        # Motion lives in local coordinates and object transforms place the asset.
        if part.motion.get('kind') in ('bird','butterfly'):
            # A transform parent keeps its flight keys local to the requested anchor.
            anchor=builder._link(bpy.data.objects.new(obj.name+'_flight',None))
            anchor.parent=builder.root;anchor.location=location
            anchor.rotation_euler.z=math.radians(rotation);anchor.scale=(scale,)*3
            anchor['c3d_nature']=True;obj.parent=anchor
        else:
            obj.location=location;obj.rotation_euler.z=math.radians(rotation);obj.scale=(scale,)*3
        out.append(obj.name)
    for spec in asset.metadata.get('lights',[]):
        p=Vector(spec['location'])*scale
        angle=math.radians(rotation)
        q=Vector((p.x*math.cos(angle)-p.y*math.sin(angle),p.x*math.sin(angle)+p.y*math.cos(angle),p.z))+Vector(location)
        light=builder.light(spec['name'],q,q-Vector((0,0,1)),spec['energy']*scale**2,
                            tuple(spec['color']),kind='POINT')
        light['c3d_nature']=True
        out.append(light.name)
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    return out


def cleanup():
    for pool in (bpy.data.node_groups,bpy.data.actions,bpy.data.shape_keys):
        for item in list(pool):
            if item.get('c3d_nature') and not item.users: pool.remove(item)
    if not any(o.get('c3d_nature') for o in bpy.context.scene.objects):
        for axis in 'xy':
            key='c3d_nature_wind_'+axis
            if key in bpy.context.scene: del bpy.context.scene[key]


def install_night_fill(root,builder=None):
    """A zero-energy daytime lamp bounce, enabled by night lighting/look contexts.

    Faces stay readable under back-facing practical lamps. This is a soft film
    fill, deliberately excluded from volumetric shafts and owned by the set.
    """
    existing=next((o for o in root.children if o.get('c3d_nature_night_fill')),None)
    if existing is not None: return existing
    data=bpy.data.lights.new(root.name+'_night_fill','AREA')
    data.energy=0;data.color=(1,.77,.52);data.shape='DISK';data.size=3
    data.volume_factor=0;data['c3d_environment']=True
    obj=bpy.data.objects.new(data.name,data)
    if builder is not None: builder._link(obj)
    else: root.users_collection[0].objects.link(obj)
    obj.parent=root;obj.location=(0,-3.3,2.2)
    obj.rotation_euler=(Vector((0,0,1.4))-obj.location).to_track_quat('-Z','Y').to_euler()
    obj['c3d_role']='environment';obj['c3d_nature']=True
    obj['c3d_nature_night_fill']=150*abs(root.scale.x)**2
    return obj
