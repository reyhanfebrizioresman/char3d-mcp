"""Isolated material lifecycle/export/snapshot checks using the real MCP tools."""
import asyncio
import json
from pathlib import Path
import struct
import textwrap


SNAPSHOT = '''
import hashlib,json
def nodes(tree):
    return dict(nodes=[(n.name,n.bl_idname,[(s.identifier,list(s.default_value) if hasattr(s.default_value,'__len__') and not isinstance(s.default_value,str) else s.default_value)
        for s in n.inputs if hasattr(s,'default_value')],n.image.name if n.type=='TEX_IMAGE' and n.image else None,
        nodes(n.node_tree) if n.type=='GROUP' and n.node_tree else None) for n in tree.nodes],
        links=[(l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier) for l in tree.links])
result=dict(materials={m.name:nodes(m.node_tree) for m in bpy.data.materials if m.node_tree},
    groups=sorted(g.name for g in bpy.data.node_groups),
    meshes={o.name:dict(slots=[(s.link,s.material.name if s.material else None) for s in o.material_slots],
        attributes=[(a.name,a.domain,a.data_type) for a in o.data.attributes],
        geometry=hashlib.sha256(str([(tuple(v.co),[(g.group,g.weight) for g in v.groups]) for v in o.data.vertices]).encode()).hexdigest())
        for o in bpy.context.scene.objects if o.type=='MESH'},
    view=(bpy.context.scene.view_settings.view_transform,bpy.context.scene.view_settings.look,bpy.context.scene.view_settings.exposure))
'''


async def run(call, text_of):
    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[-1])

    async def python(code):
        return (await data('run_blender_python', code=textwrap.dedent(code)))['result']

    await call('new_scene', frame_end=4)
    baseline = await data('create_realistic_human', name='MaterialTest', gender=0, age=24,
                          race={'caucasian':1},
                          hair='ponytail01', clothes=['female_casualsuit01','shoes01'], materials='mpfb')
    assert baseline['materials']['quality'] == 'mpfb'
    # Exercise both link modes and the otherwise invisible OBJECT override under DATA.
    await python('''
        body=bpy.data.objects['MaterialTest']
        slot=body.material_slots[0]
        slot.link='OBJECT'
        slot.material=bpy.data.objects['MaterialTest.high-poly'].material_slots[0].material
        slot.link='DATA'
        garment=bpy.data.objects['MaterialTest.female_casualsuit01']
        original=garment.material_slots[0].material
        garment.material_slots[0].link='OBJECT'
        garment.material_slots[0].material=original
        result=True
    ''')
    before = await python(SNAPSHOT)
    original = await python("result=bpy.data.objects['MaterialTest'].material_slots[0].material.name")
    upgraded = await data('upgrade_materials', character='MaterialTest_rig')
    assert {m['role'] for m in upgraded['materials']} >= {'skin','eyes','hair','brows','clothes'}
    assert 0 < upgraded['skin_profile']['radius'][2] < upgraded['skin_profile']['radius'][0]
    assert upgraded['materials_cost_factor'] == 1.15
    assert upgraded['catchlight']['eye_linked'] and not upgraded['catchlight']['shadows']
    assert await python('''
        lights=[o for o in bpy.context.scene.objects if o.get('c3d_material_catchlight_owner')]
        result=len(lights)==1 and lights[0].data.diffuse_factor==0 and lights[0].data.volume_factor==0 and {o.name for o in lights[0].light_linking.receiver_collection.objects}=={'MaterialTest.high-poly'}
    '''), 'catchlight must affect only the eye mesh'
    reference = (.6795425948454239,.4286905225680053,.2831487684477432)
    assert max(abs(a-b) for a,b in zip(upgraded['sampled_skin_rgb'],reference)) < 1e-6
    scene = await data('scene_info')
    assert next(o for o in scene['objects'] if o['name']=='MaterialTest')['mesh']['materials'][0].startswith('c3d_enhanced.')
    assert await python(f"result=bpy.data.materials[{original!r}].name") == original
    assert await python('''
        body=bpy.data.objects['MaterialTest']
        original=body['c3d_material_original_0']
        enhanced=body.material_slots[0].material
        def mixes(mat):
            return [n.inputs['colorMixInStrength'].default_value for n in mat.node_tree.nodes
                    if n.type=='GROUP' and 'colorMixInStrength' in n.inputs]
        result=abs(mixes(original)[0]-.05)<1e-6 and mixes(enhanced)==[0.]
    '''), 'default global tint stacked with local blood perfusion'
    await call('set_lighting', preset='studio', subject=['MaterialTest_rig'])
    await call('camera_shot', subject=['MaterialTest_rig'], shot='close_up', start_frame=1, end_frame=4)
    preview = await data('render_preview', camera='scene', engine_name='eevee', width=256, height=256)
    assert Path(preview['path']).is_file()
    once = await python(SNAPSHOT)
    await call('upgrade_materials', character='MaterialTest')
    assert await python(SNAPSHOT) == once, 'upgrade is not idempotent'
    await call('save_project', path='materials_checks.blend')
    await call('open_project', path='materials_checks.blend')
    assert await python(SNAPSHOT) == once, 'save/open changed material graphs'
    assert await python('''
        lights=[o for o in bpy.context.scene.objects if o.get('c3d_material_catchlight_owner')]
        result=len(lights)==1 and lights[0].parent_type=='BONE' and lights[0].parent.name=='MaterialTest_rig' and {o.name for o in lights[0].light_linking.receiver_collection.objects}=={'MaterialTest.high-poly'}
    '''), 'lighting/save/open lost native eye-linked catchlight'
    for quality in ('preview','cycles','draft'):
        opts = await data('render_options', quality=quality)
        assert opts['materials_cost_factor'] == (1 if quality == 'draft' else 1.15)
    await call('render_style', style='clay')
    assert (await data('render_options', quality='preview'))['materials_cost_factor'] == 1
    await call('render_style', style='film')
    await call('cinematic_look', preset='golden_hour')
    product = await python('''
        from engine.commands.video import _effects_cost
        from engine.commands.materials import scene_cost_factor
        from engine.commands.render_style import cost_factor
        from engine.commands.cinematic import cost_factor as look
        sc=bpy.context.scene
        result=(_effects_cost(sc,'BLENDER_EEVEE'),cost_factor(sc,'BLENDER_EEVEE')*look(sc,'BLENDER_EEVEE')*scene_cost_factor(sc,'BLENDER_EEVEE'))
    ''')
    assert abs(product[0]-product[1]) < 1e-10
    assert await python('''
        from engine.commands.cinematic import applied_look
        from engine.commands.materials import _trees
        mat=bpy.data.objects['MaterialTest'].material_slots[0].material
        socket=next(t.nodes['c3d skin reflectance'].inputs[2] for t in _trees(mat.node_tree) if t.nodes.get('c3d skin reflectance'))
        before=tuple(socket.default_value)
        try:
            with applied_look(bpy.context.scene):
                assert socket.default_value[0]>before[0], 'dim cinematic key stacked full portrait correction'
                raise RuntimeError('look failure')
        except RuntimeError as error:
            assert str(error)=='look failure'
        result=tuple(socket.default_value)==before
    '''), 'look correction leaked into saved scene'
    await call('render_style', style='none')
    await call('cinematic_look', clear=True)
    enhanced_state = await python(SNAPSHOT)
    export = await data('export_asset', path='materials_checks.glb', objects=['MaterialTest_rig'], max_influences=4)
    assert export['material_fallback']['materials']
    assert await python(SNAPSHOT) == enhanced_state, 'export changed material graphs or weights'
    raw = Path(export['path']).read_bytes()
    gltf = json.loads(raw[20:20+struct.unpack_from('<I',raw,12)[0]])
    fallback = [m for m in gltf['materials'] if m['name'].startswith('c3d_export.')]
    assert 'KHR_lights_punctual' not in gltf.get('extensionsUsed',[]), 'eye-only light leaked into portable asset'
    assert fallback and all('baseColorTexture' in m['pbrMetallicRoughness'] for m in fallback)
    assert any('normalTexture' in m for m in fallback)
    if not any(a[2] in ('FLOAT_COLOR','BYTE_COLOR') for mesh in before['meshes'].values() for a in mesh['attributes']):
        assert not any(k.startswith('COLOR_') for m in gltf['meshes'] for p in m['primitives'] for k in p['attributes']), 'internal material masks leaked as vertex colors'
    assert any(m['pbrMetallicRoughness'].get('baseColorFactor',[1,1,1,1])[0] < .95 for m in fallback)
    assert all(m['pbrMetallicRoughness']['roughnessFactor'] > 0 for m in fallback)
    await python('''
        from unittest.mock import patch
        from engine.commands.io import export_asset
        with patch('engine.commands.io._export',side_effect=RuntimeError('material export failure')):
            try: export_asset('materials_failed.glb',objects=['MaterialTest_rig'])
            except RuntimeError: pass
            else: raise AssertionError('expected export failure')
        result=True
    ''')
    assert await python(SNAPSHOT) == enhanced_state, 'failed export leaked temporary shaders'
    # Prepare through the real video snapshot path, then stop the editor before
    # its generated worker runs: this suite never owns two live Blenders.
    worker = await python('''
        from engine.commands.video import render_video,JOBS
        r=render_video(path='materials_snapshot.mp4',quality='preview',width=512,height=512,
                       frame_start=1,frame_end=4,_defer=True,subtitles=False)
        j=JOBS[r['job_id']]
        result=dict(command=j['render_cmd'],blend=j['blend'],base=j['base'],path=j['path'])
    ''')
    await call('open_project', path=worker['blend'])
    assert await python(SNAPSHOT) == enhanced_state
    await call('engine_shutdown')
    log = Path(worker['blend']).with_suffix('.serial.log')
    with log.open('wb') as output:
        process = await asyncio.create_subprocess_exec(*worker['command'], stdout=output, stderr=asyncio.subprocess.STDOUT)
        assert await process.wait() == 0, log.read_text()[-3000:]
    movies = sorted(Path(worker['base']).parent.glob(Path(worker['base']).name+'*.mp4'))
    assert movies
    movies[-1].replace(worker['path'])
    import av
    with av.open(worker['path']) as movie:
        frames = list(movie.decode(video=0))
    assert len(frames) == 4 and frames[0].width == 256
    await call('engine_status')
    await call('open_project', path='materials_checks.blend')
    await call('upgrade_materials', character='MaterialTest_rig', quality='mpfb')
    restored = await python(SNAPSHOT)
    # Lighting adds one ground material; compare all original shaders and geometry.
    assert all(restored['materials'][name] == tree for name,tree in before['materials'].items())
    assert all(restored['meshes'][name] == state for name,state in before['meshes'].items())
    assert not any(n.startswith('c3d_material.') for n in restored['groups'])
    assert not any(n.startswith('c3d_enhanced.') for n in restored['materials'])
    assert restored['view'] == before['view']
    assert await python("result=not any(o.get('c3d_material_catchlight_owner') for o in bpy.data.objects) and not any(c.get('c3d_material_catchlight_owner') for c in bpy.data.collections)"), 'catchlight resources survived restore'
    assert await python('''
        s=bpy.data.objects['MaterialTest'].material_slots[0]
        s.link='OBJECT'
        result=s.material == bpy.data.objects['MaterialTest.high-poly'].material_slots[0].material
        s.link='DATA'
    '''), 'inactive OBJECT override was not restored'
    await python('''
        mat=bpy.data.objects['MaterialTest'].material_slots[0].material
        n=next(n for n in mat.node_tree.nodes if n.type=='GROUP' and 'colorMixInStrength' in n.inputs)
        n.inputs['colorMixInStrength'].default_value=.14
        result=True
    ''')
    await call('upgrade_materials', character='MaterialTest_rig')
    assert await python('''
        mat=bpy.data.objects['MaterialTest'].material_slots[0].material
        n=next(n for n in mat.node_tree.nodes if n.type=='GROUP' and 'colorMixInStrength' in n.inputs)
        result=abs(n.inputs['colorMixInStrength'].default_value-.14)<1e-6
    '''), 'custom skin mix was reset'
    await call('upgrade_materials', character='MaterialTest_rig', quality='mpfb')
    await python('''
        mat=bpy.data.objects['MaterialTest'].material_slots[0].material
        n=next(n for n in mat.node_tree.nodes if n.type=='GROUP' and 'colorMixInStrength' in n.inputs)
        n.inputs['colorMixInStrength'].default_value=.05
        result=True
    ''')
    assert await python(SNAPSHOT) == restored
    await python('''
        from unittest.mock import patch
        from engine.commands.materials import upgrade_materials
        with patch('engine.commands.materials._skin',side_effect=RuntimeError('shader failure')):
            try: upgrade_materials('MaterialTest_rig')
            except RuntimeError: pass
            else: raise AssertionError('expected shader failure')
        result=True
    ''')
    assert await python(SNAPSHOT) == restored
    await call('upgrade_materials', character='MaterialTest_rig', skin_tone='dark', skin_detail=0, hair_detail=0)
    await call('upgrade_materials', character='MaterialTest_rig', quality='mpfb')
    assert await python(SNAPSHOT) == restored
    await call('new_scene')
    default = await data('create_realistic_human', name='DefaultMaterials', face=False)
    assert default['materials']['quality'] == 'enhanced'
    unrigged = await data('create_realistic_human', name='UnriggedMaterials', rig='none', face=False)
    assert unrigged['materials']['quality'] == 'enhanced'
    assert {m['role'] for m in unrigged['materials']['materials']} >= {'skin','eyes','brows'}
    mixed = await data('upgrade_materials', character=default['armature'], quality='mpfb')
    assert mixed['materials_cost_factor'] == 1.075
    restored = await data('upgrade_materials', character='UnriggedMaterials', quality='mpfb')
    assert restored['materials_cost_factor'] == 1.
    print('MATERIALS E2E OK | default + idempotent upgrade + exact restore + save/open + serial video snapshot + textured glTF + failure cleanup', flush=True)


async def realistic(call, text_of, pack_checks, check_weights):
    """Core existing realistic-human/export invariants, runnable without other sections."""
    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[-1])
    await call('new_scene')
    await pack_checks(call)
    for rig in ('game_engine','rigify'):
        await call('new_scene', frame_end=24)
        human = await data('create_realistic_human', name='MaterialRig', gender=0, hair='ponytail01',
                           clothes=['female_casualsuit01','shoes01'], rig=rig)
        assert human['face_rig']
        assert (await data('validate_rig', mesh='MaterialRig'))['ok']
        await call('animate', armature=human['armature'], clip='wave')
        await call('set_expression', character=human['armature'], expression='smile', strength=.4)
        await call('lip_sync', character=human['armature'], text='Halo semuanya', start_frame=1)
        await call('auto_blink', character=human['armature'], frame_start=1, frame_end=100)
        result = await data('export_asset', path=f'materials_{rig}_4.glb', objects=[human['armature']], max_influences=4)
        assert result['vertices_limited'] > 0
        assert check_weights(result['path'], 4) > 0
        views = await call('render_views', objects=[human['armature']], size=160, frame=9)
        assert sum(c.type == 'image' for c in views.content) == 4
    print('MPFB REALISTIC + EXPORT E2E OK | installed packs + game_engine/Rigify + face/wave + GLB normalized weights <= 4', flush=True)
