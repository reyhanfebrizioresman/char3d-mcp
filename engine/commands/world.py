"""Declarative world realization. All authored input passes pure preflight first."""
import copy
import json
import math
import random
from pathlib import Path

import bpy
from mathutils import Vector

from . import command
from .environment import _Builder, THEMES
from .. import context
from ..world.schema import validate_recipe, world_schema as schema, primitive

TAG='c3d_world'
RECIPE='c3d_world_recipe'


class Builder(_Builder):
    def __init__(self,name,collection,parent=None,seed=0):
        self.coll=collection;self.objects=[];self.materials={};self.image=None;self.rng=random.Random(seed)
        self.root=self._link(bpy.data.objects.new('World_'+name,None));self.root.parent=parent
        colors={'wood':(.25,.13,.055),'metal':(.025,.035,.045),'white':(.82,.85,.83),
            'floor':(.18,.19,.20),'leaf':(.08,.28,.10),'pot':(.44,.22,.12),'screen':(.025,.09,.16),**THEMES['warm']}
        for key,color in colors.items():self.materials[key]=self.material(key,color,metallic=.5 if key=='metal' else 0)
        self.materials['glow']=self.material('glow',colors['accent'],emission=2.5)
        self.materials['bulb']=self.material('bulb',(1,.72,.4),emission=3)

    def _link(self,obj):
        super()._link(obj);obj[TAG]=True
        if obj.data:obj.data[TAG]=True
        return obj

    def material(self,*args,**kwargs):
        m=super().material(*args,**kwargs);m[TAG]=True;return m


def _cleanup():
    # Mesh removal releases shape keys; node modifiers release groups before mats.
    for pool in (bpy.data.meshes,bpy.data.curves,bpy.data.cameras,bpy.data.lights,
                 bpy.data.shape_keys,bpy.data.actions,bpy.data.node_groups,bpy.data.materials,bpy.data.worlds):
        for item in list(pool):
            if item.get(TAG) and not item.users:pool.remove(item)


def _remove(collection):
    names=[]
    if collection:
        for obj in list(collection.all_objects):
            if obj.get(TAG):names.append(obj.name);bpy.data.objects.remove(obj,do_unlink=True)
        if not collection.objects and not collection.children:bpy.data.collections.remove(collection)
    _cleanup();return names


def _outdoor_config(root):
    cfg={'preset':root.get('c3d_outdoor_lighting','noon'),
        'strength':root.get('c3d_outdoor_strength',1.),'rotate':root.get('c3d_outdoor_rotate',0.)}
    if root.get('c3d_outdoor_background') is not None:cfg['background']=list(root['c3d_outdoor_background'])
    return cfg


def _weather_state(sc):
    return {'kind':sc.get('c3d_weather_kind','clear'),'intensity':sc.get('c3d_weather_intensity',0),
        'seed':sc.get('c3d_weather_seed',0),'wind':list(sc.get('c3d_weather_wind',(0,0,0)))}


def _wind_state(sc):
    return {key:sc[key] for key in ('c3d_nature_wind_x','c3d_nature_wind_y') if key in sc}


def _restore_wind(sc,state):
    for key in ('c3d_nature_wind_x','c3d_nature_wind_y'):
        if key in state:sc[key]=state[key]
        elif key in sc:del sc[key]


def _collection():
    return next((c for c in bpy.data.collections if c.get('c3d_world_active')),None)


def _apply_hero_motion(obj,spec):
    from ..nature.blender import _shape,_driver
    kind=spec.get('kind','');amp=spec.get('amplitude',.2)
    rate=spec.get('speed',1);phase=spec.get('phase',0)
    if 'seed' in spec:phase+=random.Random(spec['seed']).random()*math.tau
    if kind=='hero_swim':
        length=spec['length']
        _shape(obj,'Swim A',lambda p:(amp*math.sin(p.y/length*math.tau),0,amp*.3*math.cos(p.y/length*math.tau)),
               f'sin(frame*base/fps*{1.7*rate}+{phase})')
        _shape(obj,'Swim B',lambda p:(amp*math.cos(p.y/length*math.tau),0,amp*.3*math.sin(p.y/length*math.tau)),
               f'cos(frame*base/fps*{1.7*rate}+{phase})')
    elif kind=='hero_flap':
        _shape(obj,'Wingbeat',lambda p:(0,0,abs(p.x)*amp),f'sin(frame*base/fps*{2.3*rate}+{phase})')
    elif kind=='hero_banner':
        h=spec['height']
        _shape(obj,'Cloth wave',lambda p:(0,amp*math.sin(p.x*3+p.z*2)*max(0,1-p.z/h),0),
               'sin(frame*base/fps*2.8)')
        _shape(obj,'Cloth wave B',lambda p:(0,amp*math.cos(p.x*3+p.z*2)*max(0,1-p.z/h),0),
               'cos(frame*base/fps*2.8)')
    elif kind=='hero_lantern':
        phase=(spec['seed']*.618%1)*math.tau
        for axis,a in enumerate((amp*.4,amp*.3,amp)):
            _driver(obj,'location',f'{a}*sin(frame*base/fps*.7+{phase+axis})'+(f'+frame*base/fps*{spec.get("rise",0)}' if axis==2 else ''),index=axis)
        for mat in obj.data.materials:
            node=mat.node_tree.nodes.get('Principled BSDF')
            if node and node.inputs['Emission Strength'].default_value:
                value=node.inputs['Emission Strength'].default_value
                _driver(node.inputs['Emission Strength'],'default_value',f'{value}*(.92+.08*sin(frame*base/fps*4+{phase}))')


def _motion(root,spec,duration):
    """Bake only whitelisted analytic transforms; never evaluate authored expressions."""
    from .talk import _fcurves
    kind=spec['kind'];speed=spec.get('speed',1);amplitude=spec.get('amplitude',.4)
    phase=spec.get('phase',0)+random.Random(spec.get('seed',0)).random()*math.tau
    fps=bpy.context.scene.render.fps/bpy.context.scene.render.fps_base
    base=root.location.copy();rotation=root.rotation_euler.copy();axis='xyz'.index(spec.get('axis','z'))
    for step in range(math.ceil(duration*12)+1):
        t=min(duration,step/12);frame=1+t*fps;u=t*speed+phase;p=base.copy();rot=rotation.copy()
        if kind=='orbit':
            r=spec.get('radius',5);p+=Vector((r*math.cos(u*.25),r*math.sin(u*.25),amplitude*math.sin(u*.5)))
            rot.z+=t*speed*.25
        elif kind=='follow_path':
            points=spec['path'];v=min(1,t*speed/max(duration,.01))*(len(points)-1);i=min(len(points)-2,int(v))
            p+=Vector(points[i]).lerp(Vector(points[i+1]),v-i)
            delta=Vector(points[i+1])-Vector(points[i]);rot.z+=math.atan2(delta.x,-delta.y)
        elif kind in ('bob','rise','drift'):
            p+=Vector((amplitude*.3*math.sin(u*.5),amplitude*.2*math.cos(u*.4),amplitude*math.sin(u)))
            if kind=='rise':p.z+=t*speed*.22
            if kind=='drift':p.x+=t*speed*.25
        elif kind=='spin':rot[axis]+=t*speed*.5
        elif kind=='sway':rot[axis]+=.1*amplitude*math.sin(u)
        root.location=p;root.rotation_euler=rot
        root.keyframe_insert('location',frame=frame);root.keyframe_insert('rotation_euler',frame=frame)
    for fc in _fcurves(root.animation_data.action):
        for key in fc.keyframe_points:key.interpolation='LINEAR'
    root.animation_data.action[TAG]=True


def _surface(asset,element,recipe):
    keys={};seen=set()
    for part in asset.parts:
        for mat in part.materials:
            if id(mat) in seen:continue
            seen.add(id(mat))
            key=element.get('material_overrides',{}).get(mat.name,element.get('material'))
            if key:
                keys[id(mat)]=key
                cfg=recipe['materials'][key]
                color=cfg.get('color')
                if isinstance(color,str):color=recipe['palette'][color]
                if color is not None:mat.color=tuple(color)
                for attr in ('roughness','metallic','emission'):
                    if attr in cfg:setattr(mat,attr,cfg[attr])
                mat.name='world_'+key
    return keys


def _tag_new(before):
    for pool in (bpy.data.objects,bpy.data.meshes,bpy.data.materials,bpy.data.lights,bpy.data.cameras,
                 bpy.data.shape_keys,bpy.data.actions,bpy.data.node_groups):
        for item in pool:
            if item.as_pointer() not in before:item[TAG]=True


def _pointers():
    return {item.as_pointer() for pool in (bpy.data.objects,bpy.data.meshes,bpy.data.materials,bpy.data.lights,
        bpy.data.cameras,bpy.data.shape_keys,bpy.data.actions,bpy.data.node_groups) for item in pool}


def _atmosphere(recipe):
    from .cinematic import cinematic_look
    from .weather import set_weather
    if 'weather' in recipe:set_weather(**recipe['weather'])
    if 'look' in recipe:
        look=recipe['look'];cinematic_look(**({'preset':look} if isinstance(look,str) else look))


def _camera(builder,recipe):
    sc=bpy.context.scene
    hint=recipe.get('camera_hints',{}).get('hero',{'location':[20,-32,14],'target':[0,8,5],'lens':40})
    data=bpy.data.cameras.new('WorldHero');data.lens=hint.get('lens',40)
    camera=builder._link(bpy.data.objects.new('WorldHero',data));camera.parent=builder.root
    camera.location=hint['location'];camera.rotation_euler=(Vector(hint['target'])-camera.location).to_track_quat('-Z','Y').to_euler()
    sc.camera=camera
    path=recipe.get('camera_hints',{}).get('establishing_path')
    if path:
        for i,p in enumerate(path):
            f=1+round(i/(len(path)-1)*(recipe['duration_s']*sc.render.fps-1))
            camera.location=p;camera.rotation_euler=(Vector(hint['target'])-camera.location).to_track_quat('-Z','Y').to_euler()
            camera.keyframe_insert('location',frame=f);camera.keyframe_insert('rotation_euler',frame=f)
        camera.animation_data.action[TAG]=True
    return camera


@command('world_schema')
def world_schema():return schema()


@command('compose_world')
def compose_world(recipe,build=True):
    if type(build) is not bool:raise ValueError('build must be boolean')
    report=validate_recipe(recipe,assets=build)
    if not build:return {**report,'built':False}
    r=report['recipe'];prepared=report.pop('_assets');sc=bpy.context.scene
    from .outdoor import outdoor_root
    previous=_collection();previous_camera=sc.camera;before=_pointers();initial_wind=_wind_state(sc)
    external=outdoor_root()
    if external and external.get(TAG):external=None
    external_before=_outdoor_config(external) if external else None
    collection=bpy.data.collections.new('char3d_world_build');sc.collection.children.link(collection);collection[TAG]=True
    elements={};oldframe=sc.frame_current
    try:
        b=Builder('Root',collection,seed=r['seed']);b.root['c3d_world_root']=True
        for i,(e,asset,poses) in enumerate(prepared):
            group=b._link(bpy.data.objects.new('World_'+e['id'],None));group.parent=b.root
            tr=e['transform'];group.location=tr['location'];group.rotation_euler=[math.radians(v) for v in tr['rotation_deg']];group.scale=tr['scale']
            elements[e['id']]=group.name
            for j,pose in enumerate(poses):
                part=Builder(e['id']+f'_{j}',collection,parent=group,seed=(r['seed']+i*101+j)%2147483648)
                part.root.location=pose.get('location',[0,0,0]);part.root.rotation_euler=[math.radians(v) for v in pose.get('rotation_deg',[0,0,0])];part.root.scale=pose.get('scale',[1,1,1])
                material_keys={}
                if asset:
                    from ..nature.blender import realize
                    a=copy.deepcopy(asset);asset_keys=_surface(a,e,r);names=realize(part,a)
                    for mesh,name in zip([p for p in a.parts if p.faces],[n for n in names if bpy.data.objects[n].type=='MESH']):
                        obj=bpy.data.objects[name];_apply_hero_motion(obj,mesh.motion)
                        for source,actual in zip(mesh.materials,obj.data.materials):
                            if id(source) in asset_keys:material_keys[actual.as_pointer()]=asset_keys[id(source)]
                else:
                    part.prop(e['params']['kind'],(0,0,0))
                # Material presets work identically for nature, heroes and props.
                for o in part.objects:
                    if o.type != 'MESH': continue
                    for mat in o.data.materials:
                        key = material_keys.get(mat.as_pointer()) if asset else e.get('material')
                        if not asset:
                            source=next((name for name,value in part.materials.items() if value==mat),None)
                            key=e.get('material_overrides',{}).get(source,e.get('material'))
                        cfg = r.get('materials', {}).get(key, {})
                        if not cfg: continue
                        node = mat.node_tree.nodes.get('Principled BSDF')
                        if not node: continue
                        if not asset:
                            color = cfg.get('color')
                            if isinstance(color, str): color = r['palette'][color]
                            if color is not None:
                                node.inputs['Base Color'].default_value = (*color, 1)
                                node.inputs['Emission Color'].default_value = (*color, 1)
                            for source, target in [('roughness', 'Roughness'), ('metallic', 'Metallic'), ('emission', 'Emission Strength')]:
                                if source in cfg: node.inputs[target].default_value = cfg[source]
                        if cfg.get('transparency', 'opaque') != 'opaque':
                            node.inputs['Alpha'].default_value = .55 if cfg['transparency'] == 'glass' else .25
                            mat.surface_render_method = 'DITHERED'
                for spec in e.get('animation',[]):
                    if spec['kind'] in ('flap','swim'):
                        for o in part.objects:
                            if o.type=='MESH':_apply_hero_motion(o,{**spec,'kind':'hero_'+spec['kind'],'amplitude':spec.get('amplitude',.4),'length':10})
                    elif spec['kind']=='flicker':
                        from ..nature.blender import _driver
                        flicker_phase=spec.get('phase',0)+random.Random(spec.get('seed',r['seed']+i*101+j)).random()*math.tau
                        for mat in part.materials.values():
                            node=mat.node_tree.nodes.get('Principled BSDF')
                            if node:
                                value=node.inputs['Emission Strength'].default_value
                                _driver(node.inputs['Emission Strength'],'default_value',f'{value}*(.8+.2*sin(frame*base/fps*{spec.get("speed",1)*4}+{flicker_phase}))')
                    else:
                        # Separate parent per preset keeps multiple motions additive.
                        moving=b._link(bpy.data.objects.new('WorldMotion_'+e['id'],None));moving.parent=part.root.parent
                        part.root.parent=moving;_motion(moving,spec,r['duration_s'])
        s=r['stage'];loc=s['location']
        if s['floor']:
            a=primitive(size=[*s['area'],.16],color=s.get('color',[.20,.18,.14]),walkable=True)
            a.parts[0].materials[0].surface=s.get('surface','stone')
            from ..nature.blender import realize
            realize(b,a,location=[loc[0],loc[1],loc[2]-.08])
        for cfg in r.get('lights',[]):
            lamp=b.light('practical_lamp',cfg['location'],cfg.get('target',[0,0,0]),cfg.get('energy',100),cfg.get('color',[1,.65,.3]),kind=cfg['kind'].upper(),size=cfg.get('size',1))
            if lamp.data.type=='SPOT':lamp.data.spot_size=math.radians(cfg.get('angle',55))
        if external is None:
            sun=b.light('sun',[8,-12,18],[0,0,0],2,[1,.8,.6],kind='SUN')
            sun['c3d_outdoor_sun']=True
        camera=_camera(b,r)
        _tag_new(before)
    except BaseException:
        _tag_new(before);_remove(collection);_restore_wind(sc,initial_wind);sc.camera=previous_camera;sc.frame_set(oldframe);raise
    # Geometry succeeds before the active world is replaced. Its restoration state
    # is carried forward so clear restores the scene before the FIRST composition.
    restore=json.loads(previous.get('restore','{}')) if previous else {
        'look':sc.get('char3d_cinematic_look'),'weather':_weather_state(sc),'nature_wind':initial_wind,
        'outdoor':external_before,'outdoor_root':external.name if external else None,
        'camera':previous_camera.name if previous_camera else '',
        'frames':[sc.frame_start,sc.frame_end],
        'grounds':{o.name:o.hide_render for o in sc.objects if o.get('c3d_role')=='ground'}}
    if previous:
        if external and json.dumps(external_before)!=previous.get('applied_outdoor'):
            restore['outdoor']=external_before;restore['outdoor_root']=external.name
        if sc.get('char3d_cinematic_look','') != previous.get('applied_look',''):
            restore['look'] = sc.get('char3d_cinematic_look')
        if json.dumps(_weather_state(sc)) != previous.get('applied_weather'):
            restore['weather'] = _weather_state(sc);restore['nature_wind'] = initial_wind
    world_before=previous.get('previous_world') if previous else sc.world
    if previous:
        if any(o.get('c3d_outdoor') for o in previous.all_objects):
            from .outdoor import clear_sky
            clear_sky()
        _remove(previous)
    collection.name='char3d_world';collection['c3d_world_active']=True
    collection['restore']=json.dumps(restore)
    if world_before:collection['previous_world']=world_before
    # Reuse the established sky/weather integration, but only when this world owns
    # the outdoor sky. Existing outdoor sets remain independently removable.
    if not any(o.get('c3d_outdoor') for o in sc.objects):
        b.root['c3d_outdoor']='world'
        from .outdoor import configure_sky
        configure_sky(**r.get('sky',{}))
        sc.world[TAG]=True
    elif external:
        from .outdoor import configure_sky
        if 'sky' in r:configure_sky(**r['sky'])
        elif restore.get('outdoor'):configure_sky(**restore['outdoor'])
        collection['applied_outdoor']=json.dumps(_outdoor_config(external))
    for name in restore.get('grounds', {}):
        ground = bpy.data.objects.get(name)
        if ground: ground.hide_render = True
    if 'look' not in r:
        if restore.get('look'): sc['char3d_cinematic_look'] = restore['look']
        elif 'char3d_cinematic_look' in sc: del sc['char3d_cinematic_look']
    if 'weather' not in r and previous:
        from .weather import set_weather
        from ..nature.blender import sync_wind
        set_weather(**restore.get('weather',{'kind':'clear'}));sync_wind()
    _atmosphere(r)
    sc[RECIPE]=json.dumps(r,sort_keys=True)
    collection['applied_look']=sc.get('char3d_cinematic_look','')
    collection['applied_weather']=json.dumps(_weather_state(sc))
    sc.frame_start=1;sc.frame_end=round(r['duration_s']*sc.render.fps);sc.frame_set(1)
    collection['applied_frames']=json.dumps([sc.frame_start,sc.frame_end])
    _cleanup()
    return {**report,'built':True,'root':b.root.name,'elements':elements,'hero_camera':camera.name,
            'stage':s,'objects':[o.name for o in collection.all_objects]}


@command('clear_world')
def clear_world():
    sc=bpy.context.scene;c=_collection()
    if not c:return {'removed':[],'count':0}
    restore=json.loads(c.get('restore','{}'))
    if sc.get('char3d_cinematic_look','')==c.get('applied_look',''):
        if restore.get('look'):sc['char3d_cinematic_look']=restore['look']
        elif 'char3d_cinematic_look' in sc:del sc['char3d_cinematic_look']
    weather=_weather_state(sc)
    if json.dumps(weather)==c.get('applied_weather'):
        from .weather import set_weather
        set_weather(**restore.get('weather',{'kind':'clear'}))
        _restore_wind(sc,restore.get('nature_wind',{}))
    external=bpy.data.objects.get(restore.get('outdoor_root') or '')
    if external and json.dumps(_outdoor_config(external))==c.get('applied_outdoor') and restore.get('outdoor'):
        from .outdoor import configure_sky
        configure_sky(**restore['outdoor'])
    if any(o.get('c3d_outdoor') for o in c.all_objects):
        from .outdoor import clear_sky
        clear_sky()
    if sc.camera and sc.camera.get(TAG):sc.camera=bpy.data.objects.get(restore.get('camera',''))
    for name, hidden in restore.get('grounds', {}).items():
        ground = bpy.data.objects.get(name)
        if ground and ground.hide_render: ground.hide_render = hidden
    if json.dumps([sc.frame_start,sc.frame_end])==c.get('applied_frames'):
        sc.frame_start,sc.frame_end=restore.get('frames',[1,250])
    names=_remove(c)
    if RECIPE in sc:del sc[RECIPE]
    return {'removed':names,'count':len(names)}


def _path(name):
    import re
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}(?:\.json)?',name):raise ValueError('world name: 1..80 letters/digits/_/-; no paths')
    workspace=Path(context.WORKSPACE).resolve();folder=workspace/'worlds'
    if folder.is_symlink():raise ValueError('worlds directory must stay inside workspace')
    root=folder.resolve()
    if not root.is_relative_to(workspace):raise ValueError('worlds directory must stay inside workspace')
    root.mkdir(exist_ok=True)
    p=root/(name if name.endswith('.json') else name+'.json')
    if p.is_symlink() or p.resolve().parent!=root:raise ValueError('world path must stay inside workspace/worlds')
    return p


@command('save_world')
def save_world(name,recipe=None):
    if recipe is None:
        value=bpy.context.scene.get(RECIPE)
        if not value:raise ValueError('compose a world or supply recipe first')
        recipe=json.loads(value)
    report=validate_recipe(recipe);p=_path(name);temp=p.with_suffix('.json.tmp')
    if temp.is_symlink():raise ValueError('unsafe temporary path')
    temp.write_text(json.dumps(report['recipe'],indent=2)+'\n');temp.replace(p)
    return {'name':p.stem,'path':str(p),**report}


@command('load_world')
def load_world(name,build=True):
    p=_path(name)
    if p.stat().st_size>262144:raise ValueError('world file exceeds 256 KiB')
    return {'name':p.stem,'path':str(p),**compose_world(json.loads(p.read_text()),build=build)}
