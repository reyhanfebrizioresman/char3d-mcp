"""Feature-specific integration sections shared by e2e_smoke and isolated runs."""
import json
import textwrap
from filmstyle_support import ROOT, snapshot_video


STATE = '''
    from engine.commands.talk import _fcurves
    def value(v):
        if isinstance(v,(str,int,float,bool)) or v is None:return v
        try:return list(v)
        except TypeError:return str(v)
    def graph(tree):
        if tree is None:return None
        return dict(nodes=[(n.name,n.bl_idname,[(s.name,value(s.default_value)) for s in n.inputs
                                              if hasattr(s,'default_value')]) for n in tree.nodes],
                    links=[(l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier)
                           for l in tree.links])
    def props(item):
        out={}
        for p in item.bl_rna.properties:
            if p.identifier=='rna_type' or p.is_readonly:continue
            v=getattr(item,p.identifier)
            if p.type in {'BOOLEAN','INT','FLOAT','STRING','ENUM'}:out[p.identifier]=value(v)
            elif p.type=='POINTER':out[p.identifier]=getattr(v,'name',None)
        return out
    sc=bpy.context.scene
    result=dict(render=props(sc.render),eevee=props(sc.eevee),
                cameras=[(o.name,props(o.data),props(o.data.dof)) for o in sc.objects if o.type=='CAMERA'],
                material_settings=[(m.name,props(m)) for m in bpy.data.materials],
                materials=[(m.name,graph(m.node_tree)) for m in bpy.data.materials],
                groups=[(g.name,graph(g)) for g in bpy.data.node_groups],
                objects=[(o.name,o.data.name if o.data else None,
                          [(s.link,s.material.name if s.material else None) for s in o.material_slots],
                          [(m.name,m.type) for m in o.modifiers]) for o in sc.objects],
                lights=[(o.name,o.data.name,o.data.energy,list(o.data.color),o.data.size if o.data.type=='AREA' else None)
                        for o in sc.objects if o.type=='LIGHT'],
                meshes=sorted(m.name for m in bpy.data.meshes),
                images=sorted(i.name for i in bpy.data.images),
                world=sc.world.name if sc.world else None,
                worlds=[(w.name,graph(w.node_tree)) for w in bpy.data.worlds],
                view=[sc.view_settings.view_transform,sc.view_settings.look,sc.view_settings.exposure,sc.view_settings.gamma],
                compositor=sc.compositing_node_group.name if sc.compositing_node_group else None)
'''


async def helpers(call, text_of):
    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[-1])
    async def python(code):
        return (await data('run_blender_python', code=textwrap.dedent(code)))['result']
    return data, python


async def animated(call, text_of):
    import av
    import numpy as np
    data, python = await helpers(call, text_of)
    await data('scene_info')
    await data('new_scene', frame_end=4)
    await data('add_primitive', kind='monkey', name='StyleTest', location=[0, 0, 1])
    await data('set_material', objects=['StyleTest'], color=[.65, .20, .08])
    await data('set_lighting', preset='studio', subject=['StyleTest'])
    await data('camera_shot', subject=['StyleTest'], shot='full', start_frame=1, end_frame=4)
    await python("bpy.context.scene.render.resolution_x=320\nbpy.context.scene.render.resolution_y=180")
    def pixels(path):
        with av.open(path) as source:return next(source.decode(video=0)).to_ndarray(format='rgb24')
    async def frame(engine='eevee'):
        return pixels((await data('render_preview', camera='scene', engine_name=engine, width=256, height=144))['path'])
    base = await frame()
    original = await python(STATE)
    draft = await frame('workbench')
    for alias in ('animated_film', 'film_animasi', 'animasi'):
        result = await data('render_style', style=alias)
        assert result['style'] == 'animated_film' and not result['outline']
        image = await frame()
        assert np.abs(image.astype(float)-base).mean() > 3, 'default style must visibly change procedural materials'
        assert await python(STATE) == original
        assert np.array_equal(await frame('workbench'), draft)
    await data('render_style', style='animated_film', strength=0)
    assert np.array_equal(await frame(), base)
    await data('render_style', style='none')
    assert np.array_equal(await frame(), base)
    for preset in ('golden_hour', 'night', 'misty_morning'):
        await data('cinematic_look', preset=preset)
        await data('render_style', style='none')
        look_base=await frame()
        await data('render_style', style='animated_film', strength=0)
        assert np.array_equal(await frame(),look_base),preset
        await data('render_style', style='animated_film')
        before = await python(STATE)
        await frame()
        assert await python(STATE) == before, preset
    await data('cinematic_look', clear=True)
    await data('render_style', style='animated_film', outline=True, strength=.65)
    before = await python(STATE)
    await python('''
        from unittest.mock import patch
        from engine.commands.render_style import applied_style
        try:
            with patch('engine.commands.render_style._compositor',side_effect=RuntimeError('failure fixture')):
                with applied_style(bpy.context.scene):pass
        except RuntimeError:pass
        else:raise AssertionError('failure not injected')
        result=True
    ''')
    assert await python(STATE) == before
    # Generic linked alpha/emission/roughness/normal/SSS graph, recursively nested.
    await python('''
        from engine.commands.render_style import applied_style,render_style
        sc=bpy.context.scene;obj=bpy.data.objects['StyleTest'];original=obj.material_slots[0].material
        group=bpy.data.node_groups.new('FutureSkin','ShaderNodeTree')
        group.interface.new_socket(name='Shader',in_out='OUTPUT',socket_type='NodeSocketShader')
        group.interface.new_socket(name='Color',in_out='INPUT',socket_type='NodeSocketColor')
        group.interface.new_socket(name='Opacity',in_out='INPUT',socket_type='NodeSocketFloat')
        bsdf=group.nodes.new('ShaderNodeBsdfPrincipled');out=group.nodes.new('NodeGroupOutput')
        group.links.new(bsdf.outputs[0],out.inputs[0])
        for name in ('Alpha','Roughness','Subsurface Weight','Emission Strength'):
            node=group.nodes.new('ShaderNodeValue');node.outputs[0].default_value=.4
            group.links.new(node.outputs[0],bsdf.inputs[name])
        color=group.nodes.new('ShaderNodeRGB');color.outputs[0].default_value=(.6,.2,.1,1)
        gi=group.nodes.new('NodeGroupInput')
        group.links.new(gi.outputs['Color'],bsdf.inputs['Base Color'])
        group.links.new(gi.outputs['Opacity'],bsdf.inputs['Alpha'])
        group.links.new(color.outputs[0],bsdf.inputs['Emission Color'])
        mat=bpy.data.materials.new('GenericSkin');mat.use_nodes=True
        nested=mat.node_tree.nodes.new('ShaderNodeGroup');nested.node_tree=group
        import numpy as np,hashlib
        image=bpy.data.images.new('FutureTexture',width=1024,height=1024)
        image.colorspace_settings.name='sRGB'
        pixels=np.tile(np.array([.6,.2,.1,1,.2,.1,.05,.4],dtype=np.float32),1024*1024//2)
        image.pixels.foreach_set(pixels)
        def image_state():
            pixels=np.empty(len(image.pixels),dtype=np.float32);image.pixels.foreach_get(pixels)
            return list(image.size),hashlib.sha256(pixels.tobytes()).hexdigest()
        image_before=image_state()
        texture=mat.node_tree.nodes.new('ShaderNodeTexImage');texture.image=image
        mat.node_tree.links.new(texture.outputs['Color'],nested.inputs['Color'])
        mat.node_tree.links.new(texture.outputs['Alpha'],nested.inputs['Opacity'])
        mat.node_tree.links.new(nested.outputs[0],mat.node_tree.nodes.get('Material Output').inputs['Surface'])
        obj.material_slots[0].material=mat
        for engine in ('BLENDER_EEVEE','CYCLES'):
            sc.render.engine=engine
            render_style('animated_film')
            with applied_style(sc):
                copy=obj.material_slots[0].material
                g=next(n.node_tree for n in copy.node_tree.nodes if n.type=='GROUP')
                assert g!=group
                b=next(n for n in g.nodes if n.type=='BSDF_PRINCIPLED')
                assert all(b.inputs[n].is_linked for n in ('Alpha','Subsurface Weight','Emission Color','Emission Strength'))
                assert any(n.type=='SHADERTORGB' for n in g.nodes)==(engine=='BLENDER_EEVEE')
                if engine=='BLENDER_EEVEE':assert any(n.type=='ADD_SHADER' for n in g.nodes)
                assert any(n.type=='TEX_IMAGE' and n.image!=image and max(n.image.size)==512 for n in copy.node_tree.nodes)
                assert sum(next(n.image for n in copy.node_tree.nodes if n.type=='TEX_IMAGE' and n.image!=image).pixels[:3])>.1, 'unsaved painted pixels lost'
                assert any(n.type=='TEX_IMAGE' and n.image==image for n in copy.node_tree.nodes)
                assert next(n for n in copy.node_tree.nodes if n.type=='TEX_IMAGE' and n.image==image).outputs['Alpha'].is_linked
                assert not any(n.outputs['Alpha'].is_linked for n in copy.node_tree.nodes if n.type=='TEX_IMAGE' and n.image!=image)
            assert obj.material_slots[0].material==mat
            assert image_state()==image_before,'original texture pixels/size changed'
            assert not any(o.name.startswith('__c3d_style_') for o in sc.objects)
        # Grayscale Color used as opacity through a group must never be blurred.
        mat.node_tree.links.new(texture.outputs['Color'],nested.inputs['Opacity'])
        sc.render.engine='BLENDER_EEVEE'
        with applied_style(sc):
            tree=obj.material_slots[0].material.node_tree
            assert not any(n.type=='TEX_IMAGE' and n.image!=image for n in tree.nodes)
            mask=next(n for n in tree.nodes if n.type=='TEX_IMAGE')
            opacity=next(n for n in tree.nodes if n.type=='GROUP').inputs['Opacity']
            assert opacity.links[0].from_node==mask
            assert opacity.links[0].from_socket.name=='Color'
        noise=mat.node_tree.nodes.new('ShaderNodeTexNoise')
        noise.inputs['Detail'].default_value=5
        mat.node_tree.links.new(noise.outputs['Fac'],nested.inputs['Opacity'])
        with applied_style(sc):
            tree=obj.material_slots[0].material.node_tree
            assert tree.nodes[noise.name].inputs['Detail'].default_value==5,'procedural opacity changed'
        obj.material_slots[0].material=original
        bpy.data.materials.remove(mat);bpy.data.node_groups.remove(group);bpy.data.images.remove(image)
        sc.render.engine='BLENDER_EEVEE'
        result=True
    ''')
    await data('render_style', style='animated_film')
    config = await python("result=bpy.context.scene['char3d_render_style']")
    saved = await data('save_project', path='filmstyle/style_e2e.blend')
    await data('render_style', style='none')
    await data('open_project', path=saved['path'])
    assert await python("result=bpy.context.scene['char3d_render_style']") == config
    assert (await data('render_options', quality='preview'))['render_style']['style'] == 'animated_film'
    assert (await data('render_options', quality='draft'))['style_cost_factor'] == 1
    # Real persisted render_video snapshots for preview/final/Cycles. One short
    # preview is encoded through the same worker entry point, serially.
    await python('''
        from engine.commands.video import render_video,JOBS
        import json,os
        from engine.commands.render_style import applied_style
        from engine.commands.cinematic import applied_look
        live=os.path.join(os.path.dirname(bpy.data.filepath),'style_live_snapshot.blend')
        bpy.ops.wm.save_as_mainfile(filepath=live,copy=True)
        for quality in ('preview','final','cycles'):
            result=render_video(path='snapshot_'+quality+'.mp4',quality=quality,width=128,height=72,
                                frame_start=1,frame_end=2,_defer=True)
            job=JOBS[result['job_id']]
            assert os.path.isfile(job['blend']) and 'render_movie.py' in ' '.join(job['render_cmd'])
            job['status']='done'
            bpy.ops.wm.open_mainfile(filepath=job['blend'])
            sc=bpy.context.scene
            assert json.loads(sc['char3d_render_style'])['style']=='animated_film'
            assert sc.render.engine=={'preview':'BLENDER_EEVEE','final':'BLENDER_EEVEE','cycles':'CYCLES'}[quality]
            if quality=='cycles':
                sc.cycles.samples=2
                sc.render.resolution_percentage=100
                sc.render.image_settings.media_type='IMAGE'
                sc.render.image_settings.file_format='PNG'
                sc.render.filepath=os.path.join(os.path.dirname(live),'animated_cycles.png')
                with applied_look(sc),applied_style(sc):bpy.ops.render.render(write_still=True)
            bpy.ops.wm.open_mainfile(filepath=live)
        result=True
    ''')
    movie = await snapshot_video(python, dict(path='filmstyle_animated_snapshot.mp4', quality='preview',
                                            width=256, height=144, frame_start=1, frame_end=2))
    assert movie['status'] == 'done' and movie['bytes'] > 1000
    with av.open(movie['path']) as video:assert len(list(video.decode(video=0))) == 2
    print('ANIMATED STYLE E2E OK: exact restore, aliases, failure, generic graphs, draft, save/open, video snapshots', flush=True)


async def life(call, text_of):
    data, python = await helpers(call, text_of)
    await data('scene_info')
    await data('new_scene', frame_end=192)
    for name, gender in (('Ana', 0), ('Budi', 1)):
        await data('create_realistic_human', name=name, gender=gender, age=28,
                   hair='short02', clothes=['female_casualsuit01' if gender == 0 else 'male_casualsuit01'])
        await python(f"from engine.commands.script_scene import _skeleton\nresult=_skeleton('animate',dict(armature={name+'_rig'!r},clip='idle',cycles=2))")
    await data('lip_sync', character='Ana_rig', text='Mama bawa peta. Wah, bagus sekali!', language='id')
    await data('lip_sync', character='Budi_rig', text='Mungkin bersama?', language='id', start_frame=115)
    await data('auto_expression', character='Ana_rig')
    await data('auto_expression', character='Budi_rig')
    await data('auto_blink', character='Ana_rig')
    await data('set_lighting', preset='soft', subject=['Ana_rig', 'Budi_rig'])
    await data('camera_shot', subject=['Ana_rig'], shot='close_up', start_frame=1, end_frame=96)
    await data('camera_shot', subject=['Budi_rig'], shot='close_up', start_frame=97, end_frame=192)
    # Real clothed/rigged material restoration, including live blush coordinates.
    material_state = await python(STATE)
    await python('''
        from engine.commands.render_style import applied_style,render_style,CONFIG_PROP
        sc=bpy.context.scene;engine=sc.render.engine;saved=sc.get(CONFIG_PROP)
        try:
            sc.render.engine='BLENDER_EEVEE';render_style('animated_film')
            with applied_style(sc):
                heads=[o for o in sc.objects if o.name.startswith('__c3d_style_cheeks')]
                assert len(heads)==2
                assert {o.parent.constraints[0].target.name for o in heads}=={'Ana_rig','Budi_rig'}
        finally:
            sc.render.engine=engine
            if saved is None:del sc[CONFIG_PROP]
            else:sc[CONFIG_PROP]=saved
        result=True
    ''')
    assert await python(STATE) == material_state
    curves = '''
        from engine.commands.talk import _fcurves
        from engine.commands.face import _basemesh,_face_meshes
        result={}
        for obj in bpy.context.scene.objects:
            if obj.type=='ARMATURE':
                ad=obj.animation_data
                result[obj.name]={fc.data_path+str(fc.array_index):[(list(k.co),k.interpolation) for k in fc.keyframe_points]
                                 for fc in _fcurves(ad.action if ad else None)}
            elif obj.type=='MESH' and obj.data.shape_keys:
                sk=obj.data.shape_keys;ad=sk.animation_data
                result[obj.name]={fc.data_path:[(list(k.co),k.interpolation) for k in fc.keyframe_points]
                                 for fc in _fcurves(ad.action if ad else None)
                                 if not fc.data_path.startswith('key_blocks["__c3d_life_')}
    '''
    before = await python(curves)
    first = await data('face_life', character='Ana_rig', seed=17, listen_to='Budi_rig')
    assert (first['blinks'] or first['authored_blinks']) and first['reactions'] and first['breathing']
    assert all(abs(b['frame']-f)>24 for b in first['blinks'] for f in first['authored_blinks'])
    assert await python(curves) == before
    owned = '''
        from engine.commands.talk import _fcurves
        result={o.name:{fc.data_path:[list(p.co) for p in fc.keyframe_points]
                for fc in _fcurves(o.data.shape_keys.animation_data.action)
                if fc.data_path.startswith('key_blocks["__c3d_life_')}
                for o in bpy.context.scene.objects if o.type=='MESH' and o.data.shape_keys and o.data.shape_keys.animation_data}
    '''
    performance = await python(owned)
    assert await data('face_life', character='Ana_rig', seed=17, listen_to='Budi_rig') == first
    assert await python(owned) == performance
    assert await python(curves) == before
    await python('''
        from engine.commands.face import _basemesh,_face_meshes
        from engine.commands.talk import _fcurves
        base=_basemesh('Ana_rig');sc=bpy.context.scene
        closure=[];jumps=[]
        sk=base.data.shape_keys
        previous=None
        for f in range(1,193):
            sc.frame_set(f);keys=sk.key_blocks
            if keys['p_b_m_21'].value>.2:
                assert abs(keys.get('__c3d_life_jawOpen').value)<1e-7
                assert all(abs(k.value)<1e-7 for k in keys if k.name.startswith('__c3d_life_mouth'))
                closure.append(f)
            state=[keys['__c3d_life_browOuterUpLeft'].value,keys['__c3d_life_eyeLookOutLeft'].value]
            if previous:jumps.append(max(abs(a-b) for a,b in zip(state,previous)))
            previous=state
        assert closure and max(jumps)<.2,(closure,max(jumps))
        result=dict(closure_frames=closure,max_nonblink_delta=max(jumps))
    ''')
    saved = await data('save_project', path='filmstyle/face_e2e.blend')
    await data('open_project', path=saved['path'])
    assert await python(owned) == performance
    await data('face_life', character='Ana_rig', intensity=0)
    assert await python(curves) == before
    assert await python('''
        from engine.commands.face import _basemesh
        result=True
        for f in range(1,193):
            bpy.context.scene.frame_set(f)
            assert all(abs(k.value)<1e-7 for k in _basemesh('Ana_rig').data.shape_keys.key_blocks
                       if k.name.startswith('__c3d_life_'))
    ''')
    await data('face_life', character='Ana_rig', seed=17, listen_to='Budi_rig')
    assert await python(owned) == performance
    await python('''
        from engine.commands.face import _basemesh
        from engine.commands.face_life import face_life
        base=_basemesh('Ana_rig');words=base['char3d_words']
        try:
            del base['char3d_words']
            report=face_life('Ana_rig',seed=17)
            assert report['rhythm']=='envelope' and report['accents'],report
            assert 'char3d_words' not in base,'invented a transcript'
        finally:
            base['char3d_words']=words
        result=report
    ''')
    assert await python(curves) == before
    # Hand-made, unrigged ARKit assets and driven visemes use evaluated values.
    await python('''
        from engine.commands.face import ARKIT,VISEMES
        from engine.commands.face_life import face_life
        mesh=bpy.data.meshes.new('DrivenFace');mesh.from_pydata([(0,0,0)],[],[])
        obj=bpy.data.objects.new('DrivenFace',mesh);bpy.context.scene.collection.objects.link(obj)
        obj.shape_key_add(name='Basis')
        for name in ARKIT+VISEMES+['pupilSmall','pupilDilate']:obj.shape_key_add(name=name).value=0
        keys=obj.data.shape_keys.key_blocks
        driver=keys['p_b_m_21'].driver_add('value')
        driver.driver.expression='0.8 if frame % 24 < 8 else 0.0'
        bpy.context.scene.frame_set(12,subframe=.5)
        report=face_life('DrivenFace',1,48,seed=9)
        assert bpy.context.scene.frame_current==12 and abs(bpy.context.scene.frame_subframe-.5)<1e-6
        assert report['pupil']=='pupilSmall'
        closures=[];pauses=[]
        for frame in range(1,49):
            bpy.context.scene.frame_set(frame)
            if keys['p_b_m_21'].value>.2:
                assert abs(keys['__c3d_life_jawOpen'].value)<1e-7
                closures.append(frame)
            else:
                pauses.append(keys['__c3d_life_jawOpen'].value)
        assert closures and pauses and max(pauses)>1e-4,(closures,pauses)
        assert len(obj.data.shape_keys.animation_data.drivers)==1
        bpy.data.objects.remove(obj,do_unlink=True);bpy.data.meshes.remove(mesh)
        result=True
    ''')
    await python('''
        from engine.commands.face import ARKIT,VISEMES
        from engine.commands.face_life import face_life
        action=bpy.data.actions.new('SharedLifeAction');objects=[]
        for name,value in (('SharedLifeA',.8),('SharedLifeB',0.)):
            mesh=bpy.data.meshes.new(name);mesh.from_pydata([(0,0,0)],[],[])
            obj=bpy.data.objects.new(name,mesh);bpy.context.scene.collection.objects.link(obj)
            obj.shape_key_add(name='Basis')
            for shape in ARKIT+VISEMES:obj.shape_key_add(name=shape).value=0
            sk=obj.data.shape_keys;ad=sk.animation_data_create();ad.action=action
            ad.action_slot=action.slots.new(id_type='KEY',name=name)
            key=sk.key_blocks['p_b_m_21'];key.value=value
            key.keyframe_insert('value',frame=1);key.keyframe_insert('value',frame=48)
            objects.append(obj)
        def curves(obj,owned):
            sk=obj.data.shape_keys
            bag=action.layers[0].strips[0].channelbag(sk.animation_data.action_slot)
            return {fc.data_path:[(list(k.co),k.interpolation) for k in fc.keyframe_points]
                    for fc in bag.fcurves if ('__c3d_life_' in fc.data_path)==owned}
        original=[curves(obj,False) for obj in objects]
        face_life(objects[0].name,1,48)
        owned_a=curves(objects[0],True);assert len(owned_a)>5
        face_life(objects[1].name,1,48)
        assert curves(objects[0],True)==owned_a,'another slot was overwritten'
        jaw_b=[]
        for frame in range(2,48):
            bpy.context.scene.frame_set(frame)
            a,b=[obj.data.shape_keys.key_blocks for obj in objects]
            assert a['p_b_m_21'].value>.79 and abs(a['__c3d_life_jawOpen'].value)<1e-7
            jaw_b.append(b['__c3d_life_jawOpen'].value)
        assert max(jaw_b)>1e-4,'read the closed mouth from the other slot'
        face_life(objects[1].name,1,48,intensity=0)
        assert curves(objects[0],True)==owned_a
        for frame in range(1,49):
            bpy.context.scene.frame_set(frame)
            assert all(abs(k.value)<1e-7 for k in objects[1].data.shape_keys.key_blocks
                       if k.name.startswith('__c3d_life_'))
        assert [curves(obj,False) for obj in objects]==original
        for obj in objects:
            mesh=obj.data;bpy.data.objects.remove(obj,do_unlink=True);bpy.data.meshes.remove(mesh)
        bpy.data.actions.remove(action)
        result=True
    ''')
    print('FACE LIFE E2E OK: deterministic replacement, zero/restore, saved morphs, viseme closures, body/arm/face curves untouched, smooth gaze, wordless rhythm, shared Action slots isolated', flush=True)


async def fresh_snapshot(call, text_of):
    """Restart between snapshot preparation and rendering: never two Blenders."""
    import av
    data, python = await helpers(call, text_of)
    await data('scene_info')
    await data('open_project', path='filmstyle/face_e2e.blend')
    await data('render_style', style='animated_film')
    description = await python('''
        import json,os
        from engine import context
        from engine.commands.video import render_video,JOBS
        config=bpy.context.scene['char3d_render_style']
        live=os.path.join(context.WORKSPACE,'projects','filmstyle','fresh_live.blend')
        bpy.ops.wm.save_as_mainfile(filepath=live,copy=True)
        report=render_video(path='filmstyle_fresh_snapshot.mp4',quality='preview',
                            width=256,height=144,frame_start=2,frame_end=3,subtitles=False,_defer=True)
        job=JOBS[report['job_id']]
        result=dict(pid=os.getpid(),config=config,live=live,blend=job['blend'],base=job['base'],
                    spec=os.path.join(job['subs_dir'],'handles.json'))
    ''')
    await call('engine_shutdown')
    await data('engine_status')
    await data('open_project', path=description['blend'])
    result = await python(f'''
        import os,glob,shutil,json
        from engine.render_movie import main
        from engine.commands.talk import _fcurves
        sc=bpy.context.scene
        assert os.getpid()!={description['pid']},'engine did not restart'
        assert sc['char3d_render_style']=={description['config']!r}
        count=sum(1 for obj in sc.objects if obj.type=='MESH' and obj.data.shape_keys
                  for key in obj.data.shape_keys.key_blocks if key.name.startswith('__c3d_life_'))
        assert count>20,count
        main({description['spec']!r})
        source=sorted(glob.glob(glob.escape({description['base']!r})+'*.mp4'))[-1]
        target={str(ROOT/'output/filmstyle/fresh_snapshot.mp4')!r}
        shutil.copyfile(source,target)
        result=dict(before_pid={description['pid']},render_pid=os.getpid(),morphs=count,path=target)
    ''')
    with av.open(result['path']) as video:
        frames=list(video.decode(video=0))
        assert len(frames)==2 and frames[0].to_ndarray(format='rgb24').std()>5
    await data('open_project', path=description['live'])
    (ROOT/'output/filmstyle/fresh_snapshot.json').write_text(json.dumps(result,indent=2))
    print('FRESH SNAPSHOT E2E OK: different PID, same JSON, native life morphs, textured preview MP4, one Blender',flush=True)


async def defaults(call, text_of):
    """Public build entry points enable life and persist normalized style names."""
    data, python=await helpers(call,text_of)
    await data('scene_info')
    await data('new_scene')
    built=await data('script_to_scene',script='GAYA: animasi\nANA: Mama bawa peta.\nBUDI: Mungkin bersama?',
                     voice=False,sound=False,subtitles=False)
    rigs=[c['rig'] for c in built['characters'].values()]
    assert set(built['face_life'])==set(rigs)
    assert all(r['intensity']==1 for r in built['face_life'].values())
    assert await python("import json\nresult=json.loads(bpy.context.scene['char3d_render_style'])['style']")=='animated_film'
    performed=await data('dialog',lines=[dict(speaker=rigs[0],text='Mama bawa peta.'),
                                         dict(speaker=rigs[1],text='Mungkin bersama?')])
    assert set(performed['face_life'])==set(rigs)
    assert all(r['intensity']==1 for r in performed['face_life'].values())
    film=await data('script_to_film',name='FilmstyleDefaults',voice=False,sound=False,subtitles=False,
        style='film_animasi',script=dict(characters=[dict(id='Ada',gender=0,hair='short02',
            clothes=['female_casualsuit01'])],scenes=[
                dict(name='Day',beats=[dict(say='Ada',text='Halo!')]),
                dict(name='Night',style='film',look='night',beats=[dict(say='Ada',text='Mungkin?')])]))
    assert film['built']
    for index in (1,2):
        await data('open_film_scene',name='FilmstyleDefaults',index=index)
        state=await python('''
            import json
            sc=bpy.context.scene
            result=dict(style=json.loads(sc['char3d_render_style'])['style'],
                life=[json.loads(o['char3d_face_life'])['intensity'] for o in sc.objects if 'char3d_face_life' in o])
        ''')
        assert state['style']=='animated_film' and state['life'] and all(k==1 for k in state['life']),state
    print('FILMSTYLE DEFAULTS E2E OK: script header, dialog defaults, film alias/override and saved scenes',flush=True)
