"""Isolated integration checks through the normal engine RPC on port 9997.

No second Blender, no downloads. Use after nature_visuals.py has released the port.
"""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))
from nature_visuals import connect,py,setup


def _nature_checks(call):
    class Client:
        def call(self,command,**params): return call(command,**params)
    c=Client()
    original=c.call
    def traced(command,**params):
        print('CHECK',command,params.get('preset',params.get('kind','')),flush=True)
        return original(command,**params)
    c.call=traced
    c.call('scene_info');c.call('new_scene',frame_end=72);setup(c)
    catalog=c.call('nature_catalog')
    assert len(catalog['generators'])==29,catalog
    for kind,params in [('tree',dict(kind='blossom',height=3)),
                        ('grass_field',dict(area=[3,3],density=8)),
                        ('lake',dict(shape=[4,3])),('birds_flock',dict(count=2)),
                        ('river',dict(points=[[-5,-8,-.12],[0,0,-.12],[4,8,-.12]],banks=True)),
                        ('ferns',dict(count=2)),
                        ('falling_petals',dict(count=10))]:
        r=c.call('add_nature',kind=kind,location=[6,5,0],seed=19,params=params)
        assert r['vertices']>0 and r['parts'],r
    c.call('set_weather',kind='wind',intensity=.8,wind=[2,.7,0])
    sample='''import hashlib,json
sc=bpy.context.scene
results=[]
for frame in (1,12,48,12):
    sc.frame_set(frame)
    dg=bpy.context.evaluated_depsgraph_get()
    items=[]
    for o in sc.objects:
        if o.type=='MESH' and o.get('c3d_nature'):
            e=o.evaluated_get(dg);m=e.to_mesh()
            items.append((o.name,list(e.matrix_world.translation),
                [list(v.co) for v in list(m.vertices)[::max(1,len(m.vertices)//12)]]))
            e.to_mesh_clear()
    results.append(hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest())
result=results
'''
    before=py(c,sample)
    assert before[0]!=before[1]!=before[2] and before[1]==before[3],before
    changes=py(c,'''import hashlib,json
sc=bpy.context.scene
frames=[]
for frame in (7,29):
    sc.frame_set(frame);parts={}
    for o in sc.objects:
        if o.get('c3d_nature_kind'):
            e=o.evaluated_get(bpy.context.evaluated_depsgraph_get());m=e.to_mesh()
            value=[list(e.matrix_world@v.co) for v in list(m.vertices)[::max(1,len(m.vertices)//20)]]
            e.to_mesh_clear()
            parts.setdefault(o['c3d_nature_kind'],[]).append(value)
    frames.append({k:hashlib.sha256(json.dumps(v).encode()).hexdigest() for k,v in parts.items()})
result={k:frames[0][k]!=frames[1][k] for k in frames[0]}
''')
    assert all(changes.values()),changes
    flow_probe='''sc=bpy.context.scene
mat=next(m for m in bpy.data.materials if m.node_tree and m.node_tree.nodes.get('River flow'))
result=[]
for frame in (1,29):
    sc.frame_set(frame)
    result.append(list(mat.node_tree.nodes['River flow'].inputs[1].default_value))
'''
    flow_before=py(c,flow_probe)
    assert flow_before[0]!=flow_before[1],('river normals must flow',flow_before)
    diameter=py(c,'''sc=bpy.context.scene
maximum=0.
for frame in (1,48,120,240,480):
    sc.frame_set(frame)
    for o in sc.objects:
        if o.get('c3d_nature_kind') not in ('falling_petals','falling_leaves'): continue
        e=o.evaluated_get(bpy.context.evaluated_depsgraph_get());m=e.to_mesh()
        for i in range(0,len(m.vertices),18):
            vs=[v.co.copy() for v in m.vertices[i:i+18]]
            maximum=max(maximum,max((a-b).length for a in vs for b in vs))
        e.to_mesh_clear()
result=maximum
''')
    assert diameter<.2,('particle stretched across wrap boundary',diameter)
    c.call('camera_shot',subject=r['parts'],shot='wide',start_frame=1,end_frame=72,
           avoid_occlusion=False)
    # Render actual saved analytic deformation before and after reopening.
    c.call('render_preview',engine='workbench',camera='scene',width=320,height=180,
           filename='nature_state_before.png',frame=12)
    path=c.call('save_project',path='nature_state.blend')['path']
    c.call('new_scene');c.call('open_project',path=path)
    assert py(c,sample)==before,'saved analytic motion changed'
    assert py(c,flow_probe)==flow_before,'saved river texture clock changed'
    c.call('render_preview',engine='workbench',camera='scene',width=320,height=180,
           filename='nature_state_after.png',frame=12)
    c.call('clear_nature')
    assert py(c,"result=not any(o.get('c3d_nature_root') for o in bpy.context.scene.objects)")
    assert py(c,"result=not any(x.get('c3d_nature') and x.users==0 for pool in (bpy.data.meshes,bpy.data.materials,bpy.data.actions,bpy.data.node_groups) for x in pool)")
    c.call('clear_environment')
    assert py(c,"result=not any(n.get('c3d_nature') and not n.users for n in bpy.data.node_groups)")
    assert py(c,"result=not any(k.startswith('c3d_nature_') for k in bpy.context.scene.keys())")
    print('NATURE STATE OK: saved motion, random seeking, clear ownership',flush=True)

    c.call('new_scene',frame_end=24);setup(c)
    digest='''import hashlib,json
items=[]
for o in sorted(bpy.context.scene.objects,key=lambda o:o.name):
    if o.type=='MESH':
        vs=o.data.vertices
        items.append((o.name,len(vs),len(o.data.polygons),[list(vs[i].co) for i in (0,len(vs)//2,len(vs)-1)]))
result=hashlib.sha256(json.dumps(items).encode()).hexdigest()
'''
    for preset in ('forest','mountain_lake','village','blossom_garden','riverside','rice_terraces','park','beach'):
        original_ray=py(c,"result=bpy.context.scene.eevee.use_raytracing")
        original_method=py(c,"result=bpy.context.scene.eevee.ray_tracing_method")
        env=c.call('set_environment',preset=preset,variant=7,density=.2)
        assert py(c,"result=bpy.context.scene.eevee.use_raytracing")==(
            original_ray or preset in ('mountain_lake','blossom_garden','riverside','rice_terraces'))
        assert len(env['objects'])==len(set(env['objects']))
        assert py(c,"result=any(o.get('char3d_walkable') for o in bpy.context.scene.objects)")
        ground=py(c,'''from mathutils import Vector
from mathutils.bvhtree import BVHTree
dg=bpy.context.evaluated_depsgraph_get();heights=[]
for o in bpy.context.scene.objects:
    if o.type!='MESH' or not o.get('char3d_walkable'): continue
    e=o.evaluated_get(dg);m=e.to_mesh()
    tree=BVHTree.FromPolygons([e.matrix_world@v.co for v in m.vertices],[list(p.vertices) for p in m.polygons])
    p,n,index,distance=tree.ray_cast(Vector((0,0,2)),Vector((0,0,-1)))
    if p is not None and n.z>.5: heights.append(p.z)
    e.to_mesh_clear()
result=max(heights) if heights else None
''')
        assert ground is not None and abs(ground)<.02,('acting floor moved',preset,ground)
        assert py(c,"from mathutils import Vector\nfrom engine.commands.outdoor import outdoor_root\nresult=all(abs((o.matrix_world@Vector((0,0,o['c3d_seat_floor']))).z-outdoor_root().matrix_world.translation.z)<.002 for o in bpy.context.scene.objects if o.get('c3d_seat_kind')=='stone')"),preset
        first=py(c,digest)
        cleared=c.call('clear_environment')
        assert py(c,"result=bpy.context.scene.eevee.use_raytracing")==original_ray,'reflection setting leaked'
        assert py(c,"result=bpy.context.scene.eevee.ray_tracing_method")==original_method,'reflection method leaked'
        assert set(cleared['removed'])==set(env['objects']),(preset,cleared,env)
        assert not c.call('scene_info')['objects'],preset
        assert c.call('clear_environment')['count']==0
        if preset=='forest':
            c.call('set_environment',preset=preset,variant=7,density=.2)
            assert py(c,digest)==first,'native seeded geometry changed'
            c.call('clear_environment')
    print('NATURE PRESETS OK: eight build/clear cycles, requested preset aliases, native determinism',flush=True)

    c.call('new_scene',frame_end=120);setup(c)
    c.call('create_realistic_human',name='Walker',gender=0,hair='ponytail01',
           clothes=['female_casualsuit01','shoes01'])
    c.call('set_environment',preset='park',subject=['Walker_rig'],variant=2,density=.4)
    c.call('add_nature',kind='grass_field',params=dict(area=[5,5],density=15))
    obstacle=c.call('add_nature',kind='bush',location=[0,-1.8,0],params=dict(height=1.0))
    route=c.call('walk_path',armature='Walker_rig',points=[[0,-3.5]],start_frame=1)
    assert route['avoided'] and route['clearance_m']>.2,route
    assert py(c,"result=all(o.get('c3d_nature_solid') is False for o in bpy.context.scene.objects if o.get('c3d_nature_kind')=='grass_field')")
    c.call('set_weather',kind='rain',intensity=.25,wind=[1.2,.4,0],seed=19)
    secondary=c.call('secondary_motion',character='Walker_rig',frame_start=1,frame_end=40)
    assert secondary['chains']>0,secondary
    c.call('set_lighting',preset='overcast',subject=['Walker_rig'])
    shot=c.call('camera_shot',subject=['Walker_rig'],shot='medium',start_frame=1,end_frame=40)
    assert shot['occlusion']['after']<=.05,shot
    near=c.call('add_nature',kind='grass_field',location=[0,-3,0],params=dict(area=[2,2],density=10))
    far=c.call('add_nature',kind='grass_field',location=[100,100,0],params=dict(area=[2,2],density=10))
    fixed=c.call('add_nature',kind='grass_field',location=[100,100,0],camera_aware=False,
                 params=dict(area=[2,2],density=10))
    assert near['vertices']>far['vertices'] and fixed['vertices']==near['vertices'],(near,far,fixed)
    c.call('render_preview',engine='eevee',camera='scene',frame=24,width=512,height=288,
           filename='nature_navigation.png')
    c.call('clear_animation',armature='Walker_rig')
    # Existing bench metadata and a generated flat rock both support sit_on.
    seat=py(c,"result=next(o.name for o in bpy.context.scene.objects if 'c3d_seat_centers' in o and 'bench' in o.name)")
    seated=c.call('sit_on',character='Walker_rig',seat=seat,start_frame=1)
    assert seated.get('contact_error_m',0)<.04,seated
    c.call('render_preview',engine='workbench',camera='scene',frame=30,width=320,height=180,
           filename='nature_seat.png')
    c.call('cinematic_look',preset='misty_morning')
    options=c.call('render_options',quality='preview')
    assert options['nature_cost_factor']>1 and options['look_cost_factor']>1,options
    assert c.call('render_options',quality='draft')['nature_cost_factor']==1
    stone=c.call('add_nature',kind='rocks',location=[3,-2,0],params=dict(count=1,area=[.1,.1],height=.7))
    c.call('clear_animation',armature='Walker_rig')
    rockseat=c.call('sit_on',character='Walker_rig',seat=stone['parts'][0],start_frame=1)
    assert abs(rockseat['contact_error_m'])<.03,rockseat
    leg_penetration=py(c,f'''from mathutils.bvhtree import BVHTree
sc=bpy.context.scene;sc.frame_set(30);dg=bpy.context.evaluated_depsgraph_get()
rock=bpy.data.objects[{stone['parts'][0]!r}].evaluated_get(dg);m=rock.to_mesh()
tree=BVHTree.FromPolygons([rock.matrix_world@v.co for v in m.vertices],[list(p.vertices) for p in m.polygons])
rock.to_mesh_clear();maximum=0.
for o in bpy.data.objects['Walker_rig'].children_recursive:
    if o.type!='MESH' or o.hide_render: continue
    e=o.evaluated_get(dg);m=e.to_mesh()
    for v in m.vertices:
        p=e.matrix_world@v.co
        if .03<p.z<{rockseat['seat_surface_z']!r}-.03:
            near,normal,index,distance=tree.find_nearest(p)
            if near is not None: maximum=max(maximum,-normal.dot(p-near))
    e.to_mesh_clear()
result=maximum
''')
    assert leg_penetration<.015,('seated legs intersect the stone',leg_penetration)
    c.call('camera_shot',subject=['Walker_rig'],shot='full',name='RockSeat',
           start_frame=30,end_frame=48,angle=60)
    c.call('render_preview',engine='workbench',camera='scene',frame=30,width=512,height=288,
           filename='nature_rock_seat.png')
    log=c.call('add_nature',kind='fallen_log',location=[-3,-2,0],rotation_z=25,seed=9)
    c.call('clear_animation',armature='Walker_rig')
    logseat=c.call('sit_on',character='Walker_rig',seat=log['root'],seat_index=1,start_frame=1)
    assert abs(logseat['contact_error_m'])<.03 and abs(logseat['floor'])<.002,logseat
    c.call('camera_shot',subject=['Walker_rig'],shot='full',name='LogSeat',start_frame=30,end_frame=48,angle=60)
    c.call('render_preview',engine='workbench',camera='scene',frame=30,width=512,height=288,filename='nature_log_seat.png')
    c.call('save_project',path='nature_integration.blend')
    sampletree=c.call('add_nature',kind='tree',location=[8,0,0],camera_aware=False,
                      params=dict(kind='blossom',height=4),seed=19)
    exported=c.call('export_asset',path='nature_tree.glb',objects=[sampletree['root']])
    assert exported['bytes']>1000,exported
    (ROOT/'output/nature_integration.json').write_text(json.dumps(dict(
        route=route,secondary=secondary,seat=seated,rockseat=rockseat,rock_leg_penetration=leg_penetration,
        logseat=logseat,camera=shot,options=options,export=exported),indent=2))
    print('NATURE INTEGRATION OK: obstacle detour, thin grass, seat, camera, hair wind, costs, GLB',flush=True)

    c.call('new_scene',frame_end=96)
    c.call('create_human',name='BridgeWalker',height=1.75)
    c.call('auto_rig_humanoid',mesh='BridgeWalker')
    c.call('transform_object',name='BridgeWalker_rig',location=[0,3.5,0])
    bridge=c.call('add_nature',kind='wooden_bridge')
    walk=c.call('walk_path',armature='BridgeWalker_rig',points=[[0,-3.5]],start_frame=1)
    assert walk['terrain']['objects'] and walk['foot_lock']['max_penetration_m']<.015,walk
    assert not walk['avoided'],('walk must cross the deck, not detour around it',walk)
    assert max(v['height_m'] for side in walk['foot_lock']['ground_heights'].values() for v in side)>.15,walk
    mid=sum(walk['frames'])//2
    c.call('camera_shot',subject=['BridgeWalker_rig'],shot='full',angle=75,name='BridgeWalk',
           start_frame=mid,end_frame=mid+1)
    c.call('render_preview',engine='workbench',camera='scene',frame=sum(walk['frames'])//2,
           width=512,height=288,filename='nature_bridge_walk.png')
    for kind,location in [('fence',[-5,5,0]),('lantern',[-3,3,0]),('gazebo',[4,5,0]),
                          ('village_house',[0,11,0]),('fireflies',[0,2,0])]:
        c.call('add_nature',kind=kind,location=location,seed=19)
    c.call('set_lighting',preset='night',subject=['BridgeWalker_rig'])
    c.call('camera_shot',subject=['BridgeWalker_rig'],shot='extreme_wide',start_frame=1,end_frame=48,
           name='PropsGallery',angle=25,elevation=15)
    c.call('render_preview',engine='eevee',camera='scene',frame=12,width=512,height=288,
           filename='nature_props.png')
    c.call('save_project',path='nature_props.blend')
    (ROOT/'output/nature_bridge.json').write_text(json.dumps(walk,indent=2))
    print('NATURE PROPS OK: bridge walking, 6 reusable dressing/life generators, practical lights',flush=True)
    _nature_hut_checks(c)


def _nature_hut_checks(c):
    """Walk from the acting plane to the raised gubuk, then inspect the log seat."""

    c.call('new_scene',frame_end=360)
    c.call('create_human',name='FieldWalker',height=1.75)
    c.call('auto_rig_humanoid',mesh='FieldWalker')
    c.call('set_environment',preset='rice_terraces',variant=14,density=.2,subject=[])
    approach=c.call('walk_path',armature='FieldWalker_rig',
                    points=[[.3,5],[.4,7.6],[2.7,7.6],[4.4,7.3]],start_frame=1)
    assert approach['terrain']['objects'] and approach['foot_lock']['max_penetration_m']<.015,approach
    hutseat=py(c,"result=next(o.name for o in bpy.context.scene.objects if o.get('c3d_nature_landmark')=='hut_seat' and 'c3d_seat_centers' in o)")
    seated=c.call('sit_on',character='FieldWalker_rig',seat=hutseat,seat_index=0)
    assert abs(seated['contact_error_m'])<.03 and seated['floor']>1,seated
    final_frame=seated['frames'][-1]
    c.call('set_timeline',frame_end=final_frame+1)
    c.call('set_lighting',preset='overcast',subject=['FieldWalker_rig'])
    c.call('camera_shot',subject=['FieldWalker_rig'],shot='full',angle=30,elevation=10,
           start_frame=final_frame,end_frame=final_frame+1,name='HutSeat')
    c.call('render_preview',engine='workbench',camera='scene',frame=final_frame,width=512,height=288,
           filename='nature_review/hut_seat.png')
    c.call('save_project',path='nature_hut_access.blend')
    (ROOT/'output/nature_hut_access.json').write_text(json.dumps(dict(route=approach,seat=seated),indent=2))
    print('NATURE HUT OK: raised-path approach, crop clearance, log seat and grounded feet',flush=True)


if __name__=='__main__':
    c=connect()
    try: _nature_checks(c.call)
    finally: c.stop()
