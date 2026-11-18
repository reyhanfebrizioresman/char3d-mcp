"""MCP e2e world section, usable in isolation through e2e_smoke --world-only."""
import json
from providers.director.world import ARCHETYPES


async def _world_checks(call,text_of):
    async def data(tool,**args):return json.loads(text_of(await call(tool,**args))[-1])
    async def py(code):return (await data('run_blender_python',code=code))['result']
    await call('scene_info');await call('new_scene',frame_end=96)
    await py("bpy.context.scene.render.threads_mode='FIXED'\nbpy.context.scene.render.threads=8\nresult=True")
    catalog=await data('world_schema');assert len(catalog['generators'])==38
    await call('add_primitive',kind='cube',name='UserKeep',location=[60,60,0])
    before=await py("result=sorted(o.name for o in bpy.context.scene.objects)")
    dry=await data('direct_world',idea='whale',generator='offline',seed=21)
    await call('compose_world',recipe=dry['recipe'],build=False)
    assert before==await py("result=sorted(o.name for o in bpy.context.scene.objects)")
    for i,idea in enumerate([words[0] for _,words in ARCHETYPES]+['phoenix over crystals','a quiet original dream']):
        draft=await data('direct_world',idea=idea,generator='offline',seed=i)
        built=await data('compose_world',recipe=draft['recipe'])
        assert built['built'] and built['cost']==draft['cost']
        await call('render_preview',engine_name='workbench',camera=built['hero_camera'],width=128,height=72)
        owned=set(built['objects'])
        assert await py("result='UserKeep' in bpy.data.objects")
        removed=await data('clear_world');assert set(removed['removed'])==owned
        assert before==await py("result=sorted(o.name for o in bpy.context.scene.objects)")
        assert await py("result=not any(x.get('c3d_world') and not x.users for pool in (bpy.data.meshes,bpy.data.materials,bpy.data.lights,bpy.data.actions,bpy.data.node_groups,bpy.data.worlds,bpy.data.cameras) for x in pool)")
    # Material overrides, native driver budgets, side-effect ownership and rollback.
    small={'version':1,'seed':7,'duration_s':3,'elements':[
        {'id':'gem','generator':'primitive','params':{'shape':'sphere'},'material':'jade',
         'animation':[{'kind':'bob','amplitude':.2}]},
        {'id':'seat','generator':'prop','params':{'kind':'bench'},
         'transform':{'location':[0,1,0]},'material_overrides':{'wood':'jade'}},
        {'id':'guardian','generator':'serpent','params':{'length':3,'radius':.2,'segments':24},
         'transform':{'location':[3,3,3]},'material':'jade','material_overrides':{'ivory_gold':'amber'}}],
        'palette':{'green':[.05,.4,.2]},'materials':{'jade':{'color':'green','roughness':.22,'emission':.3,'transparency':'glass'},
                     'amber':{'color':[.9,.45,.08],'roughness':.7}},
        'look':'night','weather':{'kind':'wind','intensity':.4,'seed':44},'stage':{'seats':['seat']}}
    await call('cinematic_look',preset='golden_hour')
    await call('set_weather',kind='wind',intensity=.4,seed=33,wind=[1,2,0])
    await call('compose_world',recipe=small)
    assert await py("result=any(m.node_tree and m.node_tree.nodes.get('Principled BSDF') and abs(m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value-.22)<.001 for m in bpy.data.materials if m.get('c3d_world'))")
    # Shared hero materials keep selective overrides; transparency is still correct
    # when replacing a world creates temporary Blender name suffixes.
    await call('compose_world',recipe=small)
    assert await py("mats=[m for m in bpy.data.materials if m.get('c3d_world') and 'world_amber' in m.name]\nresult=bool(mats) and all(abs(m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value-.7)<.001 and m.node_tree.nodes['Principled BSDF'].inputs['Alpha'].default_value==1 for m in mats)")
    names=await py("result=sorted(o.name for o in bpy.context.scene.objects)")
    await py(f"""from unittest.mock import patch
from engine.commands.world import compose_world
try:
 with patch('engine.commands.world._motion',side_effect=RuntimeError('intentional rollback')):
  compose_world({small!r})
except RuntimeError:pass
else:raise AssertionError('failure injection did not execute')
result=True
""")
    assert await py("result=sorted(o.name for o in bpy.context.scene.objects)")==names
    await call('set_weather',kind='wind',intensity=.4,seed=55,wind=[2,3,0])
    await call('cinematic_look',preset='blue_hour')
    await call('clear_world')
    assert await py("result=bpy.context.scene['c3d_weather_seed']==55 and list(bpy.context.scene['c3d_weather_wind'])==[2,3,0]")
    assert (await data('scene_info'))['cinematic_look']['preset']=='blue_hour'
    await call('set_weather',kind='clear');await call('cinematic_look',clear=True)
    # A world layered onto an existing outdoor set delegates and restores its sky.
    await call('set_environment',preset='park')
    state=await py("from engine.commands.outdoor import outdoor_root\nresult=[bpy.context.scene.world.name,outdoor_root()['c3d_outdoor_lighting']]")
    tiny={'version':1,'elements':[],'sky':{'preset':'night'}}
    await call('compose_world',recipe=tiny)
    assert await py("from engine.commands.outdoor import outdoor_root\nresult=outdoor_root()['c3d_outdoor_lighting']=='night'")
    await call('clear_world')
    assert await py("from engine.commands.outdoor import outdoor_root\nresult=[bpy.context.scene.world.name,outdoor_root()['c3d_outdoor_lighting']]")==state
    await call('clear_environment')
    recipe=dry['recipe'];built=await data('compose_world',recipe=recipe)
    sample='''import hashlib,json
sc=bpy.context.scene;values=[]
for frame in (1,17,55,17):
 sc.frame_set(frame);parts=[]
 for o in sc.objects:
  if o.get('c3d_world') and o.type=='MESH':
   e=o.evaluated_get(bpy.context.evaluated_depsgraph_get());m=e.to_mesh()
   parts.append([list(e.matrix_world@v.co) for v in list(m.vertices)[::max(1,len(m.vertices)//15)]])
   e.to_mesh_clear()
 values.append(hashlib.sha256(json.dumps(parts).encode()).hexdigest())
result=values
'''
    first=await py(sample);assert first[0]!=first[1]!=first[2] and first[1]==first[3],first
    saved=await data('save_world',name='e2e-world')
    assert saved['recipe']==recipe
    loaded=await data('load_world',name='e2e-world',build=False);assert loaded['recipe']==recipe
    await call('save_project',path='e2e_world.blend');await call('new_scene');await call('open_project',path='e2e_world.blend')
    assert await py(sample)==first,'saved world motion changed'
    await call('render_preview',camera=built['hero_camera'],engine_name='eevee',width=256,height=144)
    await call('clear_world');await call('load_world',name='e2e-world')
    assert await py(sample)==first,'rebuild not deterministic'
    await call('clear_world')
    # Raised stage and explicit saved-world header, including actual walking.
    recipe['stage']['location']=[0,0,.6]
    await call('save_world',name='e2e-stage',recipe=recipe)
    await call('new_scene')
    script='DUNIA: e2e-stage\nANA (perempuan, 28, rambut bob): Indah!\n[Ana jalan ke 1, 0]'
    plan=await data('script_to_scene',script=script,build=False,voice=False)
    assert plan['plan']['world']=='e2e-stage'
    built=await data('script_to_scene',script=script,voice=False,sound=False,subtitles=False)
    assert built['world']['stage']['location'][2]==.6
    assert await py("result=any(o.get('char3d_walkable') and o.get('c3d_world') for o in bpy.context.scene.objects)")
    rig=built['characters']['ANA']['rig']
    assert await py(f"bpy.context.scene.frame_set({built['frames'][1]})\nresult=bpy.data.objects[{rig!r}].matrix_world.translation.z>.5")
    await call('render_preview',engine_name='eevee',camera='scene',width=256,height=144)
    print('WORLD E2E OK: 12 offline builds, exact clear, save/load, seeking, saved motion, DUNIA and walkable stage',flush=True)
