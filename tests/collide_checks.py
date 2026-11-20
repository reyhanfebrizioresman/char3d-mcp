"""Real MCP collision faults, invariants, visual evidence and CPU measurements."""
import json
import os
from pathlib import Path
import time
import shutil
import textwrap
import numpy as np


async def run(call, text_of):
    if os.environ.get('CHAR3D_PORT') != '9970':
        raise RuntimeError('Collision verification requires isolated port 9970')
    root = Path(__file__).resolve().parents[1]
    out = root/'output/collide'
    out.mkdir(parents=True, exist_ok=True)
    async def data(tool, **args):
        result = await call(tool, **args)
        return json.loads(text_of(result)[0])
    async def python(code):
        return (await data('run_blender_python', code=textwrap.dedent(code)))['result']
    resume=os.environ.get("CHAR3D_COLLIDE_RESUME", "")
    results=json.loads((out/"measurements.json").read_text()) if resume and (out/"measurements.json").exists() else {}
    images=json.loads((out/"images.json").read_text()) if resume and (out/"images.json").exists() else []
    async def still(label, rig, frame, engine='workbench', view='three_quarter', camera='auto'):
        res=await call('render_frames', frames=[frame], objects=[rig], view=view,
                       camera=camera, engine_name=engine, size=384 if engine=='workbench' else 448)
        item=json.loads(text_of(res)[0])
        target=out/(label+'.png')
        shutil.copy2(item['path'],target)
        images.append(dict(path=str(target),label=label,frame=frame))
        return str(target)
    def save():
        (out/'measurements.json').write_text(json.dumps(results,indent=2))
        (out/'images.json').write_text(json.dumps(images,indent=2))
    await data('scene_info')
    if not resume:
        await data('new_scene')
        await data('create_human', name='Fault', style='realistic')
        await data('auto_rig_humanoid', mesh='Fault')
        await data('set_timeline', frame_start=1, frame_end=48, fps=24)
        await data('apply_pose', armature='Fault_rig', pose='relaxed', frame=1, keyframe=True)
        await data('set_pose', armature='Fault_rig', bones={'forearm.R':[75,0,0]}, frame=1, keyframe=True)
        await data('set_pose', armature='Fault_rig', bones={'forearm.R':[25,0,0]}, frame=80, keyframe=True)
        await python("""
r=bpy.data.objects['Fault_rig'];ad=r.animation_data;action=ad.action
collections=([bag.fcurves for layer in action.layers for strip in layer.strips
              if (bag:=strip.channelbag(ad.action_slot)) is not None]
             if hasattr(action,'layers') else [action.fcurves])
for collection in collections:
    for fc in list(collection):
        if fc.data_path.startswith('pose.bones["upper_arm.R"].rotation_'):collection.remove(fc)
result=True
""")
        # Put a real triangle slab through the relaxed right hand by a measured 2 cm.
        hand = await python("bpy.context.scene.frame_set(1)\nr=bpy.data.objects['Fault_rig']\nresult=list((r.matrix_world@r.pose.bones['hand.R'].matrix).translation)")
        await data('add_primitive', kind='cube', name='FaultDesk', location=[hand[0],hand[1],hand[2]-.03])
        await data('transform_object', name='FaultDesk', scale=[.16,.16,.035])
        await data('scene_info')
        await still('slab_before','Fault_rig',12)
        before = await data('resolve_collisions', characters=['Fault_rig'], frame_start=1, frame_end=48,
                            parts=['arms'], report_only=True)
        await data('save_project',path='collide/slab_before.blend')
        outside_code="""
from engine.commands.talk import _data_curves
r=bpy.data.objects['Fault_rig']
result=[(fc.data_path,fc.array_index,[fc.evaluate(f) for f in (0,49,50,65,79,80,96)]) for fc in _data_curves(r)]
"""
        outside=await python(outside_code)
        outside_pose_code="""
r=bpy.data.objects['Fault_rig'];result=[]
for f in (0,49,50,65,79,80,96):
    bpy.context.scene.frame_set(f)
    result.append([list(row) for row in r.pose.bones['hand.R'].matrix])
"""
        outside_poses=await python(outside_pose_code)
        state_code = """
    import hashlib,json
    from engine.commands.anim import semantic_map
    from engine.commands.talk import _data_curves
    result={}
    for rig in [o for o in bpy.context.scene.objects if o.type=='ARMATURE' and not o.name.startswith('__')]:
        sm=semantic_map(rig)
        paths={rig.pose.bones[n].path_from_id(p) for k,n in sm.items() if k=='hips' or k.startswith(('thigh.','shin.','foot.','toe.')) for p in ('location','rotation_quaternion','rotation_euler')}
        curves=[(fc.data_path,fc.array_index,[(list(k.co),k.interpolation) for k in fc.keyframe_points]) for fc in _data_curves(rig) if fc.data_path in paths]
        face=[(o.name,[(fc.data_path,fc.array_index,[list(k.co) for k in fc.keyframe_points]) for fc in _data_curves(o.data.shape_keys)]) for o in rig.children_recursive if o.type=='MESH' and o.data.shape_keys]
        world=[]
        for f in (1,12,24,36,48):
            bpy.context.scene.frame_set(f)
            world.append([list(rig.matrix_world@rig.pose.bones[sm[k]].matrix.translation) for k in ('hips','foot.L','foot.R')])
        result[rig.name]=dict(body_curves=hashlib.sha256(json.dumps(curves).encode()).hexdigest(),face=hashlib.sha256(json.dumps(face).encode()).hexdigest(),world=world)
    """
        untouched = await python(state_code)
        fixed = await data('resolve_collisions', characters=['Fault_rig'], frame_start=1, frame_end=48, parts=['arms'])
        after_state = await python(state_code)
        assert untouched == after_state, (untouched,after_state)
        assert fixed['frames_corrected'] > 0, fixed
        assert fixed['max_penetration_after_m'] < before['max_penetration_before_m'], (before,fixed)
        after_outside=await python(outside_code)
        for a,b in zip(outside,after_outside):
            assert a[:2]==b[:2]
            np.testing.assert_allclose(a[2],b[2],atol=2e-6)
        np.testing.assert_allclose(outside_poses,await python(outside_pose_code),atol=2e-6)
        digest_code="""
import hashlib,json
from engine.commands.talk import _data_curves
r=bpy.data.objects['Fault_rig']
result=hashlib.sha256(json.dumps([(fc.data_path,fc.array_index,[(list(k.co),k.interpolation) for k in fc.keyframe_points]) for fc in _data_curves(r)]).encode()).hexdigest()
"""
        digest=await python(digest_code)
        await data('open_project',path='collide/slab_before.blend')
        repeated=await data('resolve_collisions',characters=['Fault_rig'],frame_start=1,frame_end=48,parts=['arms'])
        assert digest==await python(digest_code),'collision bake is not deterministic'
        assert {k:v for k,v in fixed.items() if k!='timings'}=={k:v for k,v in repeated.items() if k!='timings'}
        fixed['determinism']='identical baked curves and reports on restored input; sparse outside curves preserved'
        await still('slab_after','Fault_rig',12)
        results['slab'] = fixed
        save()
        print('COLLIDE slab', fixed['max_penetration_before_m'], '->', fixed['max_penetration_after_m'],
              'seconds', fixed['timings']['total'], flush=True)
        await data('new_scene', frame_end=144)
        await data('create_realistic_human',name='DeskActor',gender=0,age=28,hair=None,clothes=[],materials='mpfb')
        chair=(await data('add_prop',kind='chair'))['root']
        await data('sit_on',character='DeskActor_rig',seat=chair,start_frame=1,collisions=False)
        desk=(await data('add_prop',kind='desk',location=[0,-.58,0],scale=.80,rotation_z=180))['root']
        await data('add_prop',kind='laptop',location=[0,-.44,.83],rotation_z=180,scale=.8)
        await data('lip_sync',character='DeskActor_rig',text='Ini ide besar! Saya pikir kita semua bisa.',start_frame=24,language='id')
        await data('talk_gestures',character='DeskActor_rig',frame_start=24,frame_end=120,
                   style='energetic',collisions=False,cues=[{'frame':48,'gesture':'big'},{'frame':90,'gesture':'self'}])
        await data('set_lighting',preset='studio',subject=['DeskActor_rig'])
        await data('camera_shot',subject=['DeskActor_rig'],shot='medium',angle=40,start_frame=1,end_frame=144)
        await data('scene_info')
        await still('energetic_before','DeskActor_rig',55,camera='scene')
        await data('save_project',path='collide/energetic_before.blend')
        untouched=await python(state_code)
        results['energetic_desk']=await data('resolve_collisions',characters=['DeskActor_rig'],frame_start=24,frame_end=120,
                                              parts=['arms','props'])
        assert untouched==await python(state_code),'energetic pass changed root/feet/face keys'
        await still('energetic_after','DeskActor_rig',55,camera='scene')
        await data('save_project',path='collide/energetic.blend')
        save()
        print('COLLIDE energetic',results['energetic_desk']['max_penetration_before_m'],'->',
              results['energetic_desk']['max_penetration_after_m'],results['energetic_desk']['timings'],flush=True)
        # Exercise the actual safe review fix on a known geometric desk fault.
        await data('open_project',path='collide/energetic_before.blend')
        inspected=await data('review_scene',level='quick',fix=False,sheet=False)
        assert any(i['id'].startswith('penetration:') for i in inspected['issues']),inspected['issues']
        reviewed=await data('review_scene',level='quick',fix=True,sheet=False)
        repaired=[a for a in reviewed['fixed'] if a['tool']=='resolve_collisions' and a['status']=='applied']
        assert repaired and repaired[0]['result']['characters'],reviewed['fixed']
        (out/'review_collision.json').write_text(json.dumps(dict(before=inspected,after=reviewed),indent=2))
        print('COLLIDE REVIEW penetration check / safe fix OK',flush=True)
        await data('open_project',path='collide/energetic.blend')

    async def invariants(first,last):
        return await python(f'''
import hashlib,json
from engine.commands.anim import semantic_map
from engine.commands.talk import _data_curves
from engine.commands.script_scene import _bones_only
from engine.commands.collision import contacts_at
result={{}}
with _bones_only():
    for r in [o for o in bpy.context.scene.objects if o.type=='ARMATURE' and not o.name.startswith('__')]:
        sm=semantic_map(r)
        finger_names={{b.name for b in r.pose.bones if any(k in b.name.lower() for k in ('thumb','index','middle','ring','pinky'))}}
        keep={{r.pose.bones[n].path_from_id(p) for n in finger_names for p in ('location','rotation_quaternion','rotation_euler')}}
        rows=[(fc.data_path,fc.array_index,[(list(k.co),k.interpolation) for k in fc.keyframe_points]) for fc in _data_curves(r) if fc.data_path in keep or fc.data_path.startswith('pose.bones["'+sm['hips']+'"]') or not fc.data_path.startswith('pose.bones[')]
        face=[(o.name,[(fc.data_path,fc.array_index,[list(k.co) for k in fc.keyframe_points]) for fc in _data_curves(o.data.shape_keys)]) for o in r.children_recursive if o.type=='MESH' and o.data.shape_keys]
        samples={{}}
        for f in sorted(set(range({first},{last}+1,max(1,({last}-{first})//8)))|{{{last}}}):
            bpy.context.scene.frame_set(f)
            samples[str(f)]={{'anchors':[list(r.matrix_world@r.pose.bones[sm[k]].matrix.translation) for k in ('hips','foot.L','foot.R')],
                'wrists':[list((r.matrix_world@r.pose.bones[sm['hand.'+s]].matrix).to_quaternion()) for s in 'LR'],
                'contacts':[list((r.matrix_world@r.pose.bones[sm['hand.'+s]].matrix).translation) if contacts_at(r,s,f) else None for s in 'LR']}}
        result[r.name]=dict(keys=hashlib.sha256(json.dumps(rows).encode()).hexdigest(),face=hashlib.sha256(json.dumps(face).encode()).hexdigest(),samples=samples)
from engine.commands.seating import _body_samples,_contact_height
from engine.commands.collision import evaluated_skin
from mathutils import Vector
for r in [o for o in bpy.context.scene.objects if o.type=='ARMATURE' and o.get('c3d_seat_active')]:
    seat=json.loads(r['c3d_seated'])
    bpy.context.scene.frame_set({last})
    with evaluated_skin([r]):
        samples=_body_samples(r,semantic_map(r))
        result[r.name]['seat_height']=_contact_height(r,Vector(seat['center']),Vector(seat['front']),samples)
result['attachments']=[(o.name,o.get('c3d_hold_character'),o.get('c3d_hold_hand'),[(c.name,c.target.name if c.target else None) for c in o.constraints if c.name.startswith('char3d_hold')]) for o in bpy.context.scene.objects if o.get('c3d_hold_character')]
result['cameras']=[(o.name,[list(row) for row in o.matrix_world]) for o in bpy.context.scene.objects if o.type=='CAMERA']
''')
    def unchanged(a,b):
        assert a['attachments']==b['attachments'] and a['cameras']==b['cameras']
        for rig,entry in a.items():
            if rig in ('attachments','cameras'):continue
            assert entry['keys']==b[rig]['keys'] and entry['face']==b[rig]['face'],rig
            if 'seat_height' in entry:
                assert abs(entry['seat_height']-b[rig]['seat_height'])<.003,(rig,entry['seat_height'],b[rig]['seat_height'])
            for f,sample in entry['samples'].items():
                after=b[rig]['samples'][f]
                np.testing.assert_allclose(sample['anchors'],after['anchors'],atol=.0005,err_msg=rig)
                for q,z in zip(sample['wrists'],after['wrists']):
                    assert abs(np.dot(q,z))/(np.linalg.norm(q)*np.linalg.norm(z))>1.-2e-6,(rig,f,q,z)
                for p,z in zip(sample['contacts'],after['contacts']):
                    if p is not None:np.testing.assert_allclose(p,z,atol=.003,err_msg=rig+' contact')
    async def check(label,rigs,first,last,peak,parts=None):
        print('COLLIDE CHECK',label,flush=True)
        await data('scene_info')
        await data('set_lighting',preset='studio',subject=rigs)
        await data('camera_shot',subject=rigs,shot='medium_full' if len(rigs)>1 else 'medium',
                   angle=65 if len(rigs)>1 else 30,start_frame=first,end_frame=max(first+1,last),avoid_occlusion=False)
        if label in ('skirt_seat','sofa_armrests'):
            await data('camera_shot',subject=rigs,shot='full',angle=90,start_frame=first,
                       end_frame=max(first+1,last),avoid_occlusion=False,name='CollisionSeatSide')
        await still(label+'_before',rigs[0],peak,camera='scene')
        await data('save_project',path='collide/'+label+'_before.blend')
        original=await invariants(first,last)
        result=await data('resolve_collisions',characters=rigs,frame_start=first,frame_end=last,parts=parts or ['arms','props'])
        unchanged(original,await invariants(first,last))
        for rig,report in result['characters'].items():
            for stat in report['parts'].values():
                assert stat['max_penetration_after_m']<=max(.020001,stat['max_penetration_before_m']+.002001),(label,rig,stat)
                if stat['max_penetration_after_m']>.020001:
                    assert report['skipped'],(label,rig,stat)
        await still(label+'_after',rigs[0],peak,camera='scene')
        await data('save_project',path='collide/'+label+'.blend')
        result['invariants']='root/feet world, root/finger/face keys, protected wrists, wrist orientation, attachments and cameras passed'
        results[label]=result;save()
        print('COLLIDE',label,result['max_penetration_before_m'],'->',result['max_penetration_after_m'],
              'seconds',result['timings']['total'],flush=True)
        return result

    if resume not in ('interactions','cloth','bench'):
        for clip in ('arms_crossed','thinking','hand_on_heart','drink','type'):
            await data('new_scene',frame_end=80)
            await data('create_realistic_human',name='Action',gender=.7,hair=None,clothes=[],materials='mpfb')
            first,last=1,60
            if clip=='type':
                chair=(await data('add_prop',kind='chair'))['root']
                await data('sit_on',character='Action_rig',seat=chair,start_frame=1,collisions=False)
                await data('add_prop',kind='desk',location=[0,-.58,0],scale=.75,rotation_z=180)
                await data('add_prop',kind='laptop',location=[0,-.44,.78],scale=.8,rotation_z=180)
                first=24
            if clip=='drink':
                cup=(await data('add_prop',kind='cup'))['root']
                await data('hold_prop',character='Action_rig',prop=cup,start_frame=1)
            if clip=='hand_on_heart':
                await data('talk_gestures',character='Action_rig',frame_start=1,frame_end=60,collisions=False,
                           cues=[{'frame':24,'gesture':'love','hold_seconds':.6}])
            else:
                motion=await data('animate',armature='Action_rig',clip=clip,start_frame=first,
                                  cycles=1,speed=2,foot_lock=False,blend_frames=0,collisions=False)
                first,last=motion['frames']
            await check(clip,['Action_rig'],first,last,(first+last)//2)

    if resume not in ('cloth','bench'):
        for kind in ('handshake','hug'):
            await data('new_scene',frame_end=100)
            await data('create_realistic_human',name='Short',gender=0,height=.4,hair=None,clothes=[],materials='mpfb')
            await data('create_realistic_human',name='Tall',gender=1,height=.6,hair=None,clothes=[],materials='mpfb',location=[0,-.24 if kind=='hug' else -.8,0])
            await data('transform_object',name='Tall_rig',rotation_deg=[0,0,180])
            interaction=await data('interact',a='Short_rig',b='Tall_rig',kind=kind,start_frame=1,collisions=False,approach=kind!='hug')
            await check(kind,['Short_rig','Tall_rig'],interaction['frames']['reach'],interaction['frames']['end'],
                        interaction['frames']['contact']+3,parts=['arms','props','torso'])

    if resume != 'bench':
        await data('new_scene',frame_end=60)
        catalog=await data('mpfb_assets')
        assets=catalog['assets']['clothes']
        skirt=next((n for n in ('toigo_shift_dress','toigo_halter_dress_knee_length','frankyaye_mini_skirt_01','toigo_long_full_skirt') if n in assets),
                   next((n for n in assets if 'skirt' in n or 'dress' in n),None))
        assert skirt,'Collision verification requires an installed CC0 skirt/dress'
        await data('create_realistic_human',name='Skirt',gender=0,hair=None,clothes=[skirt],materials='mpfb')
        chair=(await data('add_prop',kind='chair'))['root']
        await data('sit_on',character='Skirt_rig',seat=chair,start_frame=1,collisions=False)
        await data('secondary_motion',character='Skirt_rig',parts=['clothes'],frame_start=1,frame_end=60,collisions=False)
        await check('skirt_seat',['Skirt_rig'],1,60,40,parts=['clothes'])

        await data('new_scene',frame_end=60)
        await data('create_realistic_human',name='Sofa',gender=1,hair=None,clothes=[],materials='mpfb')
        sofa=(await data('add_prop',kind='sofa'))['root']
        await data('sit_on',character='Sofa_rig',seat=sofa,start_frame=1,hands='armrests',collisions=False)
        await check('sofa_armrests',['Sofa_rig'],1,60,40,parts=['arms','legs'])

    if not os.environ.get('CHAR3D_COLLIDE_NO_BENCH'):
        if resume=='bench' and (root/'output/projects/collide/benchmark_before.blend').exists():
            await data('open_project',path='collide/benchmark_before.blend')
            cast=['Bench0_rig','Bench1_rig']
        else:
            await data('new_scene',frame_end=720)
            cast=[]
            for i,x in enumerate((-.55,.55)):
                name='Bench'+str(i)
                clothes=[('female' if i==0 else 'male')+'_casualsuit01','shoes01']
                await data('create_realistic_human',name=name,gender=i,hair=None,clothes=clothes,materials='mpfb',location=[x,0,0])
                chair=(await data('add_prop',kind='chair',location=[x,0,0]))['root']
                await data('sit_on',character=name+'_rig',seat=chair,start_frame=1,collisions=False)
                await data('lip_sync',character=name+'_rig',text=('Kita bisa membuat ini bersama. '*14),start_frame=24,language='id')
                await python("from engine.commands.script_scene import _bones_only\nfrom engine.commands.gesture import talk_gestures\nwith _bones_only():\n    result=talk_gestures("+repr(name+'_rig')+",frame_start=24,frame_end=720,style='energetic',collisions=False,seed="+str(15+i)+")")
                cast.append(name+'_rig')
            await data('add_prop',kind='desk',location=[0,-.58,0],scale=.8,rotation_z=180)
            await data('add_prop',kind='laptop',location=[0,-.44,.83],scale=.8,rotation_z=180)
        await data('save_project',path='collide/benchmark_before.blend')
        print('COLLIDE BENCH 30 seconds / 2 MPFB / 720 frames',flush=True)
        result=await data('resolve_collisions',characters=cast,frame_start=1,frame_end=720)
        result['benchmark_fixture']='720 frames at 24 fps; two clothed MPFB humans, seated energetic gestures, desk/laptop; no loose garment chains'
        results['benchmark_30s']=result;save()
        print('COLLIDE BENCH seconds',result['timings'],flush=True)
        assert result['timings']['total']<60,result['timings']
    print('COLLIDE E2E OK', flush=True)
    return results
