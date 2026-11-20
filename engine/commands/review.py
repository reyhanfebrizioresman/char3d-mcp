"""Scene/film review adapters. All checks inspect the current evaluated scene."""
import json
import math
import os
from pathlib import Path
import subprocess
import time
import uuid
import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from . import command, dispatch
from .. import context
from ..review import issue, call, score, rhythm, camera_checks, subtitle_checks, audio_metrics, sound_checks, report_text, safe_fixes, articulation_present, camera_followups


def read(owner, key, default=None):
    try: return json.loads(owner.get(key,'null')) or default
    except (TypeError,ValueError): return default


def _external(mode, spec, directory):
    if mode in ('sheet', 'stack'):
        from .review_sheet import sheet
        return sheet(spec, stack=mode=='stack')
    source=Path(directory)/(mode+'_input.json'); target=Path(directory)/(mode+'_result.json')
    source.write_text(json.dumps(spec),encoding='utf-8')
    python=os.environ.get('CHAR3D_REVIEW_PYTHON') or str(Path(__file__).resolve().parents[2]/'.venv/bin/python')
    done=subprocess.run([python,'-m','engine.review_media',mode,str(source),str(target)],
                        cwd=str(Path(__file__).resolve().parents[2]),capture_output=True,text=True,timeout=600)
    if done.returncode:
        raise RuntimeError('Review helper failed: '+done.stderr[-1500:])
    return json.loads(target.read_text())


def _mix(sc):
    import aud
    from .audio import _sound_strips, _volume_curve
    fps=sc.render.fps/sc.render.fps_base
    n=max(1,round((sc.frame_end-sc.frame_start+1)/fps*48000))
    stems={k:np.zeros((n,2),np.float32) for k in ('voice','music','ambience','sfx')}
    entries=[]; errors=[]; cache={}
    for strip in _sound_strips(sc):
        if strip.mute or not strip.sound: continue
        a=max(sc.frame_start,float(strip.frame_final_start)); b=min(sc.frame_end+1,float(strip.frame_final_end))
        if b<=a: continue
        path=bpy.path.abspath(strip.sound.filepath)
        try:
            if path not in cache:
                cache[path]=np.asarray(aud.Sound(path).rechannel(2).resample(48000).data(),dtype=np.float32)
            data=cache[path]
            if data.ndim==1: data=np.repeat(data[:,None],2,axis=1)
            start=round((a-sc.frame_start)/fps*48000)
            # frame_start is the untrimmed source origin; final_start includes strip offsets.
            offset=round((a-float(strip.frame_start))/fps*48000)+round(float(getattr(strip,'sound_offset',0))*48000)
            count=min(round((b-a)/fps*48000), n-start, len(data)-max(0,offset))
            if count<=0: continue
            curve=_volume_curve(strip)
            grid=np.arange(math.floor(a),math.ceil(b)+1,dtype=float)
            gain=np.array([curve.evaluate(f) if curve else strip.volume for f in grid])
            smooth=np.interp(a+np.arange(count)/48000*fps,grid,gain)
            kind='ambience' if strip.get('char3d_sfx_kind')=='ambience' else strip.get('char3d_audio_kind','voice')
            if kind not in stems: kind='sfx'
            stems[kind][start:start+count] += data[max(0,offset):max(0,offset)+count]*smooth[:,None]
            entries.append(dict(name=strip.name,kind=kind,start=a,end=b,path=path,
                speaker=strip.get('char3d_speaker'),gain_frames=grid.tolist(),gains=gain.tolist(),
                base_volume=float(strip.get('char3d_volume',strip.volume)),sfx_kind=strip.get('char3d_sfx_kind'),
                character=strip.get('char3d_sfx_character')))
        except (RuntimeError,ValueError,OSError) as exc:
            errors.append(dict(strip=strip.name,error=str(exc)))
    mix=sum(stems.values())
    return mix, stems, entries, errors


def _shots(sc, level):
    from .camera import _subjects, SHOTS
    from .occlusion import VisibilityProbe, _landmarks
    from .util import scene_bounds
    from .gaze import head_frame
    items=[]
    rigs=[o for o in sc.objects if o.type=='ARMATURE' and not o.hide_render and not o.name.startswith('__')]
    raw_shots=dispatch('list_shots',{})['shots']
    for raw in raw_shots:
        if not raw['camera']: continue
        cam=bpy.data.objects[raw['camera']]; meta=dict(cam.get('c3d_shot',{})); args=read(cam,'c3d_shot_args',{})
        a=max(sc.frame_start,raw['frames'][0]); b=min(sc.frame_end,raw['frames'][1])
        if b<a: continue
        size=meta.get('shot_size',meta.get('shot','medium')); names=list(meta.get('subject') or [])
        if size not in SHOTS:size='medium'
        allowed={'subject','shot','move','start_frame','end_frame','angle','elevation','intensity','ease','lens','handheld','roll','depth_of_field','f_stop','name','action_line','face_coverage','coverage_turns','angle_limits','foreground'}
        args={k:v for k,v in args.items() if k in allowed}
        missing=[n for n in names if n not in bpy.data.objects]
        names=[n for n in names if n in bpy.data.objects]
        subjects=_subjects(names) if names or not missing else []
        lo,hi=scene_bounds(subjects) if subjects else (None,None)
        H=max(.1,hi.z-lo.z) if lo is not None else 1.75
        probe=VisibilityProbe(subjects,size,H,foreground=cam.get('c3d_foreground'))
        samples=[]; angles=[]; side=0
        for f in sorted({a,(a+b)//2,b} if level!='quick' else {(a+b)//2}):
            sc.frame_set(f)
            pos=cam.matrix_world.translation
            groups=probe.points()
            for face,eyes,body in groups:
                if not eyes: continue
                def project(p):
                    q=world_to_camera_view(sc,cam,p)
                    return Vector((q.x,1-q.y,q.z))
                marks=[project(p) for p in _landmarks((face,eyes,body))]
                fp=[project(p) for p in face]; bp=[project(p) for p in body[:8]]
                samples.append(dict(frame=f,eye_y=round(marks[0].y,4),
                    head_chest_height=round(abs(marks[1].y-marks[2].y),4),
                    body_height=round(max(p.y for p in bp)-min(p.y for p in bp),4),
                    face_box=[min(p.x for p in fp),min(p.y for p in fp),max(p.x for p in fp),max(p.y for p in fp)],
                    face_edge=any(p.z<=0 or not .015<p.x<.985 or not .015<p.y<.985 for p in fp)))
            target=sum((head_frame(bpy.data.objects[n])[0] if bpy.data.objects[n].type=='ARMATURE' else bpy.data.objects[n].matrix_world.translation for n in names),Vector())/max(1,len(names))
            angles.append(math.degrees(math.atan2((pos-target).x,-(pos-target).y)))
            if len(rigs)>=2:
                p,q=[head_frame(r)[0] for r in rigs[:2]]
                side=(q-p).cross(pos-p).z
            # Recompute visibility from current geometry and camera, even after hand edits.
            if groups:
                rot=cam.matrix_world.to_euler(); aim=pos+cam.matrix_world.to_quaternion()@Vector((0,0,-1))
                probe.capture(f,pos,aim,rot,cam.data.lens)
        measured=probe.measure() if probe.samples else {}
        repair=[]
        if args and names and not missing and b>a:
            # Legacy native shots did not save their coverage flags. Add a live
            # line constraint so re-fitting cannot silently change dialog sides.
            line=args.get('action_line') or [r.name for r in rigs[:2]]
            # A camera reused by return-to-coverage markers must keep its other
            # intervals. Give this repair its own local camera in that case.
            repair_name=cam.name+f'_Review{a}' if sum(s['camera']==cam.name for s in raw_shots)>1 else cam.name
            repair=[call('camera_shot',**dict(args,name=repair_name,subject=names,shot='over_shoulder' if cam.get('c3d_foreground') else size,start_frame=a,end_frame=b,
                         action_line=line if len(line)>1 else None,require_composition=True,avoid_occlusion='auto'))]
        items.append(dict(name=raw['marker'],camera=cam.name,frames=[a,b],subject=names,
                          size=size,move=meta.get('move','static'),samples=samples,missing_subjects=missing,
                          deliberate=bool(cam.get('c3d_deliberate_cut',False)),
                          angle=angles[0] if angles else 0,angle_end=angles[-1] if angles else 0,
                          action_side=side,occlusion=measured.get('face',0),face_angle=measured.get('face_angle',0),repair=repair,
                          distinct_moves=meta.get('move','static'),
                          foreground_samples=measured.get('foreground',[]),foreground_shoulder=cam.get('c3d_ots_shoulder')))
    return items


def _performance(sc,shots,level):
    from .script_scene import _bones_only
    from .semantic import load_words
    from .talk import _data_curves
    from .anim import semantic_map
    from .gaze import head_frame
    from .footlock import _legs, _sole_points
    from .terrain import GroundQuery
    issues=[]; words=[]; states={}; contacts=[]; prop_errors={}; fps=sc.render.fps/sc.render.fps_base
    rigs=[o for o in sc.objects if o.type=='ARMATURE' and not o.hide_render and not o.name.startswith('__')]
    for rig in rigs:
        from .camera import _subjects
        meshes=[o for o in _subjects([rig.name]) if o.type=='MESH']
        base=next((m for m in meshes if load_words(m)),next((m for m in meshes if m.get('c3d_source')=='mpfb' or m.data.shape_keys and 'eyeBlinkLeft' in m.data.shape_keys.key_blocks),None))
        own=load_words(base) if base else []
        words.extend(own)
        states[rig.name]=dict(rig=rig,meshes=meshes,base=base,words=own,samples=[],feet={'L':[],'R':[]},visible_s=0)
    step=max(1,round(fps*(.5 if level=='quick' else .1 if level=='full' else .2)))
    with _bones_only():
        ground=GroundQuery()
        soles={r.name: {s:_sole_points(r,leg,r.matrix_world.translation.z) for s,leg in _legs(r)[0].items()} for r in rigs}
        frames=list(range(sc.frame_start,sc.frame_end+1,step))
        for f in frames:
            sc.frame_set(f)
            camera=next((s['camera'] for s in reversed(shots) if s['frames'][0]<=f),sc.camera.name if sc.camera else None)
            cam=bpy.data.objects.get(camera) if camera else None
            for rig in rigs:
                state=states[rig.name]; smap=semantic_map(rig); pos=head_frame(rig)[0]
                q=world_to_camera_view(sc,cam,pos) if cam else Vector((.5,.5,1))
                on=q.z>0 and -.05<q.x<1.05 and -.05<q.y<1.05
                if on: state['visible_s']+=step/fps
                points=[rig.matrix_world@rig.pose.bones[smap[n]].matrix.translation for n in ('head','chest','hand.L','hand.R') if n in smap]
                state['samples'].append((f,on,np.array([list(p) for p in points]).ravel()))
                for side,leg in _legs(rig)[0].items():
                    fw=rig.matrix_world@rig.pose.bones[leg['foot']].matrix
                    pts=[fw@p for p in soles[rig.name][side]]
                    low=min(pts,key=lambda p:p.z-ground.sample(p.x,p.y)[0])
                    state['feet'][side].append((f,list(low),low.z-ground.sample(low.x,low.y)[0]))
            from .holding import _palm
            for prop in sc.objects:
                holder=bpy.data.objects.get(prop.get('c3d_hold_character',''))
                if holder is None or not prop.get('c3d_hold_start',1)<=f<prop.get('c3d_hold_release',math.inf): continue
                bone,palm=_palm(holder,'L' if prop.get('c3d_hold_hand')=='left' else 'R')
                expected=(holder.matrix_world@holder.pose.bones[bone].matrix@palm).translation
                attachment=next((c for c in reversed(list(prop.constraints)) if c.name.startswith('char3d_hold') and c.influence>.5 and c.target),None)
                if attachment is not None:
                    expected=attachment.target.matrix_world.translation
                error=(prop.matrix_world.translation-expected).length
                if error>prop_errors.get(prop.name,{}).get('error',0):
                    prop_errors[prop.name]=dict(error=error,frame=f,character=holder.name)
            # Torso capsules give conservative body intersections, excluding arms/hands.
            for i,a in enumerate(rigs):
                for b in rigs[i+1:]:
                    am,bm=semantic_map(a),semantic_map(b)
                    if not all('hips' in m and 'chest' in m for m in (am,bm)): continue
                    aa=[a.matrix_world@a.pose.bones[am[n]].matrix.translation for n in ('hips','chest')]
                    bb=[b.matrix_world@b.pose.bones[bm[n]].matrix.translation for n in ('hips','chest')]
                    # Closest points of two finite segments via a bounded alternating projection.
                    p,q=aa[0],bb[0]
                    for _ in range(4):
                        d=aa[1]-aa[0]; p=aa[0]+d*min(1,max(0,(q-aa[0]).dot(d)/max(d.length_squared,1e-9)))
                        d=bb[1]-bb[0]; q=bb[0]+d*min(1,max(0,(p-bb[0]).dot(d)/max(d.length_squared,1e-9)))
                    penetration=.12*((aa[1]-aa[0]).length+(bb[1]-bb[0]).length)-(p-q).length
                    if penetration>.03 and not any(x['id'].startswith('body_overlap:'+a.name+':'+b.name) for x in issues):
                        issues.append(issue('body_overlap:'+a.name+':'+b.name,'performance','warn','Torso capsule proxies intersect.',dict(penetration_m=round(penetration,4)),frame=f))
    for name,state in states.items():
        base=state['base']; own=state['words']; visible_s=state['visible_s']
        curves=_data_curves(base.data.shape_keys) if base and base.data.shape_keys else []
        blink=[fc for fc in curves if 'eyeBlink' in fc.data_path]
        blinks=max((fc.evaluate(f) for fc in blink for f in range(sc.frame_start,sc.frame_end+1,max(1,round(fps/12)))),default=0)
        if visible_s>2 and base and base.data.shape_keys and blinks<.35:
            issues.append(issue('missing_blink','performance','warn','The visible face has no blink in this range.',dict(visible_s=round(visible_s,2),peak_closure=round(blinks,3)),
                fix=[call('auto_blink',character=name,frame_start=sc.frame_start,frame_end=sc.frame_end)],auto=True,character=name))
        from .face import VISEMES
        mouth=[fc for fc in curves if any(unit in fc.data_path for unit in [v for v in VISEMES if v!='sil_00']+['jawOpen','mouthClose','mouthFunnel','mouthPucker','mouthUpperUp','mouthLowerDown'])]
        state['mouth_curves']=mouth
        for w,a,b in own:
            if base and base.data.shape_keys and not articulation_present(mouth,a,b,fps):
                issues.append(issue('lip_coverage','performance','warn','A stored speech word has no sampled mouth articulation.',dict(word=w),character=name,frame=round(a)))
                break
        emotional=read(base,'char3d_emotions',[]) if base else []
        if not emotional and own:
            from ..emotion import sentences,classify
            emotional=[dict(emotion=classify(sentence)[0]) for sentence in sentences(own)]
        expression=[fc for fc in curves if any(t in fc.data_path for t in ('brow','mouthSmile','mouthFrown'))]
        delta=max((max(fc.evaluate(f) for f in frames)-min(fc.evaluate(f) for f in frames) for fc in expression),default=0)
        if any(e.get('emotion') not in ('neutral','thinking') for e in emotional) and len(own)>2 and visible_s>2 and delta<.02:
            issues.append(issue('flat_expression','performance','warn','Emotional lines have almost no changing brow or mouth-corner animation.',dict(expression_range=delta),character=name))
        window=max(2,math.ceil(4*fps/step)+1)
        for i in range(0,len(state['samples'])-window+1):
            part=state['samples'][i:i+window]
            if not all(v[1] for v in part) or not part[0][2].size: continue
            a,b=part[0][0],part[-1][0]
            spoken_frames=sum(max(0,min(b,wb)-max(a,wa)) for o,s in states.items() if o!=name for _,wa,wb in s['words'])
            other_talking=spoken_frames>=.75*(b-a)
            movement=max(float(np.max(abs(v[2]-part[0][2]))) for v in part)
            if other_talking and movement<.003:
                issues.append(issue('frozen_listener','performance','warn','A visible listener stays almost motionless for four seconds.',dict(max_motion_m=round(movement,5),seconds=(b-a)/fps),character=name,frame=a));break
        for side,points in state['feet'].items():
            pen=max((-p[2] for p in points),default=0)
            slide=max((np.linalg.norm(np.array(q[1][:2])-p[1][:2])/((q[0]-p[0])/fps)
                       for p,q in zip(points,points[1:]) if abs(p[2])<.025 and abs(q[2])<.025),default=0)
            if pen>.025 or slide>.35:
                issues.append(issue('feet_'+side,'performance','warn','Sampled supporting sole moves or penetrates the ground.',dict(max_penetration_m=round(pen,4),max_support_speed_m_s=round(float(slide),4),sample_step=step),
                    fix=[call('lock_feet',armature=name)],character=name))
    for prop,measurement in prop_errors.items():
        if measurement['error']>.04:
            issues.append(issue('prop_contact:'+prop,'performance','warn','Held prop grip is separated from its palm target.',
                dict(contact_error_m=round(measurement['error'],4)),frame=measurement['frame'],character=measurement['character']))
    # Contacts are recomputed with the shared detector, keeping all body/face keys intact.
    from .sfx import detect_motion
    with _bones_only():
        for rig in rigs:
            try:
                steps,seats=detect_motion(rig,sc.frame_start,sc.frame_end)
                contacts += [dict(e,kind='footsteps',character=rig.name) for e in steps]
                contacts += [dict(e,character=rig.name) for e in seats]
            except ValueError: pass
    return issues,sorted(words,key=lambda w:w[1]),contacts,states


def _scene_once(level,sheet,engine,size,frames,asr):
    from .subtitles import get_config, scene_words, chunk_words, _resolved_style
    from .graphics import get_config as graphics
    started=time.perf_counter();sc=bpy.context.scene; fps=sc.render.fps/sc.render.fps_base
    directory=context.resolve('review_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6],'renders')
    os.makedirs(directory)
    t=time.perf_counter();shots=_shots(sc,level); camera_s=time.perf_counter()-t
    t=time.perf_counter();issues,words,contacts,states=_performance(sc,shots,level); performance_s=time.perf_counter()-t
    if not shots:
        issues.append(issue('missing_camera','camera','error','No shot camera is available for review.'))
    duration=(sc.frame_end-sc.frame_start+1)/fps
    issues+=rhythm(shots,fps,words,duration)+camera_checks(shots,duration)
    t=time.perf_counter();mix,stems,entries,errors=_mix(sc)
    metrics=audio_metrics(mix);issues+=sound_checks(metrics)
    for error in errors:
        issues.append(issue('unreadable_sound','sound','error','A referenced sound could not be decoded.',error))
    voice=[s for s in entries if s['kind']=='voice'];music=[s for s in entries if s['kind']=='music']
    for name,state in states.items():
        for word,a,b in state['words']:
            if not any(s['start']<b and s['end']>a and max(s['gains'],default=0)>.0001 and s.get('speaker') in (None,name) for s in voice):
                issues.append(issue('silent_lips','sound','error','Lip-sync words have no corresponding voice audio.',dict(word=word),character=name,frame=round(a)));break
    for s in voice:
        if s.get('speaker') and not any(s['start']<b and s['end']>a for w,a,b in words) and not articulation_present(states.get(s['speaker'],{}).get('mouth_curves',[]),s['start'],s['end'],fps):
            issues.append(issue('voice_without_lips','performance','warn','A character voice strip has neither timed words nor changing mouth articulation.',dict(strip=s['name']),character=s['speaker'],frame=round(s['start'])))
    duck=[]
    for s in music:
        if s['base_volume']<=0: continue
        samples=[v/s['base_volume'] for f,v in zip(s['gain_frames'],s['gains']) if any(a<=f<=b for _,a,b in words)]
        if samples: duck.extend(samples)
    if duck:
        attenuation=20*math.log10(max(1e-9,float(np.percentile(duck,75))))
        if attenuation>-6:
            issues.append(issue('music_ducking','sound','warn','Music is not sufficiently lowered under speech.',dict(measured_duck_db=round(attenuation,3),minimum_db=-6),fix=[call('duck_music')],auto=True))
    # Measured voice/music energy catches a loud source even when a duck envelope exists.
    active=np.zeros(len(mix),bool)
    for _,a,b in words:
        active[max(0,round((a-sc.frame_start)/fps*48000)):min(len(mix),round((b-sc.frame_start)/fps*48000))]=True
    if active.any() and np.any(stems['voice'][active]):
        def rms(x): return math.sqrt(float(np.mean(x.astype(float)**2))+1e-20)
        ratio=20*math.log10(rms(stems['music'][active])/rms(stems['voice'][active]))
        if ratio>-6:
            issues.append(issue('music_masks_speech','sound','warn','Measured music energy approaches or exceeds the voice.',dict(music_vs_voice_db=round(ratio,3)),fix=[call('duck_music',amount_db=-18)],auto=True))
    if not any(s['kind']=='ambience' for s in entries):
        issues.append(issue('missing_ambience','sound','warn','No location ambience bed is present.',fix=[call('auto_sfx',kinds=['ambience'])],auto=True))
    missing=[e for e in contacts if not any(s['sfx_kind']==e['kind'] and s.get('character')==e['character'] and abs(s['start']-e['frame'])<=max(2,.1*fps) for s in entries)]
    if missing:
        issues.append(issue('missing_foley','sound','warn','Detected contacts lack matching Foley.',dict(missing_contacts=missing),fix=[call('auto_sfx',characters=sorted({e['character'] for e in missing}),kinds=sorted({e['kind'] for e in missing}))],auto=True))
    duration=(sc.frame_end-sc.frame_start+1)/fps
    silences=read(sc,'char3d_director_silences',[])
    if duration>20:
        emotions=[e for state in states.values() for e in (read(state['base'],'char3d_emotions',[]) if state['base'] else [])
                  if e.get('emotion') not in ('neutral','thinking') and e['frames'][0]>sc.frame_start+.2*duration*fps]
        peak=max(emotions,key=lambda e:e.get('strength',0),default=None)
        turn=peak['frames'][0] if peak else sc.frame_start+duration*.65*fps
        bed=stems['music']+stems['ambience'];hop=4800
        quiet=[];run=0
        for at in range(0,len(bed)-hop,hop):
            f=sc.frame_start+at/48000*fps
            silent=np.sqrt(np.mean(bed[at:at+hop]**2)) < 10**(-45/20)
            speaking=any(a<=f<=b for _,a,b in words)
            run=run+1 if silent and not speaking else 0
            if run>=4: quiet.append(f)
        if not any(turn-3*fps<=f<turn for f in quiet):
            issues.append(issue('no_quiet_turn','sound','warn' if peak else 'info',
                'No sustained near-silence precedes the estimated emotional turn.',
                dict(turn_frame=turn,bed_threshold_dbfs=-45,minimum_quiet_s=.4,inferred_turn=bool(peak))))
    audio_s=time.perf_counter()-t
    cfg=get_config(sc); chunks=[]
    if cfg:
        st=_resolved_style(cfg);chunks=chunk_words(scene_words(sc,cfg),fps,st)
        repair=[call('add_subtitles',**{k:v for k,v in dict(cfg,max_words=14,min_hold=1.8,hold=.6,max_cps=17).items() if k not in ('enabled','words')})]
        # Preserve explicit timed words without changing their source timing.
        if cfg.get('words'):
            repair=[]
        issues+=subtitle_checks(chunks,fps,sc.frame_start,sc.frame_end,repair)
        center=1-{'bottom':.12,'lower_third':.27,'center':.5,'top':.86}[st['position']]
        half=st['size']*st['lines']*.7
        for shot in shots:
            for sample in shot['samples']:
                if any(c['start']<=sample['frame']<c['end'] for c in chunks):
                    box=sample['face_box']
                    if box[0]<.93 and box[2]>.07 and box[1]<center+half and box[3]>center-half:
                        issues.append(issue('caption_face','readability','warn','Caption band overlaps a projected face box.',dict(face_box=box,caption_box=[.07,center-half,.93,center+half]),shot=shot['name'],frame=sample['frame']));break
    for g in graphics(sc):
        if g['type']=='title' and g['duration_s']<3:
            from .graphics import title_timing
            a,b,_=title_timing(sc,g)
            safe=a+round(3*fps)-1<=sc.frame_end
            args={k:v for k,v in dict(g,duration_s=3).items() if k!='type'}
            issues.append(issue('title_hold','readability','warn','The title is held for less than three seconds.',dict(seconds=g['duration_s']),fix=[call('add_title',**args)],auto=safe,frame=a))
    t=time.perf_counter();contact_sheet=None;strips=[];observations=[]
    if sheet and (sc.camera or shots):
        chosen=set(frames or range(sc.frame_start,sc.frame_end+1,max(1,round(fps*(2 if level=='quick' else 1.5)))))
        chosen|={(s['frames'][0]+s['frames'][1])//2 for s in shots}
        actions=[];plan=read(sc,'char3d_script_plan',{})
        for i,beat in enumerate(plan.get('beats',[])):
            if beat.get('do') not in ('walk','sit','interact','hold','stand'): continue
            center=(beat['frames'][0]+beat['frames'][1])//2
            if beat.get('do')=='interact':
                contact=beat.get('result',{}).get('frames',{}).get('contact')
                if isinstance(contact,list): center=contact[0]
            seq=sorted({max(sc.frame_start,min(sc.frame_end,center+round(d*fps))) for d in (-.4,-.2,0,.2,.4)})
            actions.append((f"{beat['do']}_{i}",seq));chosen.update(seq)
        extra=[]
        for event in contacts:
            if event.get('kind') in ('sit','stand'):
                if not any(b.get('do')==event['kind'] and b.get('frames',[0,0])[0]<=event['frame']<=b.get('frames',[0,0])[1] for b in plan.get('beats',[])):
                    extra.append((event['kind']+'_'+event['character'],event['frame']))
        for prop in sc.objects:
            if prop.get('c3d_hold_start') is not None and sc.frame_start<=prop['c3d_hold_start']<=sc.frame_end:
                if not any(b.get('do') in ('hold','interact') and b.get('frames',[0,0])[0]<=prop['c3d_hold_start']<=b.get('frames',[0,0])[1] for b in plan.get('beats',[])):
                    extra.append(('hold_'+prop.name,prop['c3d_hold_start']))
        for character in sorted({e['character'] for e in contacts if e.get('kind')=='footsteps'}):
            if not any(b.get('do')=='walk' for b in plan.get('beats',[])):
                steps=[e['frame'] for e in contacts if e.get('kind')=='footsteps' and e['character']==character]
                if len(steps)>1:extra.append(('walk_'+character,steps[len(steps)//2]))
        for label,center in extra:
            seq=sorted({max(sc.frame_start,min(sc.frame_end,center+round(d*fps))) for d in (-.4,-.2,0,.2,.4)})
            actions.append((label,seq));chosen.update(seq)
        chosen=sorted(f for f in chosen if sc.frame_start<=f<=sc.frame_end)
        try:
            rendered=dispatch('render_frames',dict(frames=chosen,camera='scene',engine=engine,size=size,prefix=directory+'/sample'))['frames']
        except (RuntimeError,ValueError,OSError) as exc:
            issues.append(issue('preview_failed','readability','error','The preview pass failed; inspect the render inputs.',dict(error=str(exc))))
            rendered=[]
        items=[]
        for item in rendered:
            f=item['frame']; shot=next((s for s in reversed(shots) if s['frames'][0]<=f),{})
            sample=next((p for p in shot.get('samples',[]) if p['frame']==f),None)
            items.append(dict(path=item['path'],frame=f,face_box=sample['face_box'] if sample else None,label=f"{(f-sc.frame_start)/fps:.2f}s {shot.get('name','camera')} {shot.get('size','')}"))
        aspect=sc.render.resolution_y/sc.render.resolution_x
        if items:
            result=_external('sheet',dict(items=items,path=directory+'/contact_sheet.png',size=size,aspect=aspect),directory)
            contact_sheet=result['path'];observations=result['observations']
        for label,seq in actions:
            if not items:continue
            import re
            filename=re.sub(r'[^A-Za-z0-9_.-]+','_',label)[:80]
            result=_external('sheet',dict(items=[i for i in items if i['frame'] in seq],path=directory+'/'+filename+'.png',size=min(size,256),aspect=aspect,columns=5),directory)
            strips.append(dict(action=label,frames=seq,path=result['path']))
        for sample in observations:
            if sample.get('contrast') is not None and sample['contrast']<.035:
                # Workbench renders untextured grey; its contrast is only a provisional hint.
                severity='info' if engine=='workbench' else 'warn'
                issues.append(issue('low_contrast','readability',severity,'Subject and surrounding background have similar sampled luminance.',dict(luminance_difference=sample['contrast'],engine=engine),frame=sample['frame']))
            if sample['dark_fraction']>.85 or sample['blown_fraction']>.5:
                issues.append(issue('exposure','readability','warn','Sampled image is predominantly dark or near-white.',sample,frame=sample['frame']))
        for prev,cur in zip(observations,observations[1:]):
            delta=float(np.linalg.norm(np.array(prev['color'])-cur['color']))
            if delta>.4:
                issues.append(issue('color_jump','continuity','warn','Sampled mean colour changes abruptly; inspect the cut.',dict(rgb_distance=round(delta,4),previous_frame=prev['frame'],engine=engine),frame=cur['frame']))
    visual_s=time.perf_counter()-t
    total,scores=score(issues)
    report=dict(kind='scene',score=total,scores=scores,issues=issues,contact_sheet=contact_sheet,strips=strips,
                report_md=directory+'/review.md',audio=metrics,camera=dict(shot_count=len(shots),distinct_sizes=len({s['size'] for s in shots}),distinct_moves=len({s['move'] for s in shots})),shots=shots,frames=[sc.frame_start,sc.frame_end],
                duration_s=duration,observations=observations,limits=[
                'Scores are heuristics, not story or artistic judgements; suggestions need review.',
                'Face/torso/sole/contact measurements use sampled proxies, not mesh collision simulation.',
                'Workbench luminance is a shape-preview proxy; use Eevee or the final MP4 for exposure.',
                'Volume automation and source trims are mixed offline; sequencer effects/spatial audio are not modelled.',
                'ASR is disabled unless requested; external/custom rigs may lack words or face controls.'],
                timings=dict(camera=round(camera_s,4),performance=round(performance_s,4),audio=round(audio_s,4),visuals=round(visual_s,4),total=round(time.perf_counter()-started,4)))
    if asr:
        from ..review_media import audio_segments
        report['asr_segments']=audio_segments(mix,read(sc,'char3d_script_lines',[]),directory,fps,sc.frame_start)
    Path(report['report_md']).write_text(report_text(report),encoding='utf-8')
    Path(directory+'/review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


@command('review_scene')
def review_scene(level='standard',fix=False,sheet=True,engine='workbench',size=384,asr=False,frames=None):
    if level not in ('quick','standard','full'): raise ValueError('level must be quick/standard/full')
    if engine not in ('workbench','eevee','cycles'): raise ValueError('unknown review engine')
    if type(size) is not int or not 64<=size<=512: raise ValueError('review size must be 64..512')
    sc=bpy.context.scene;saved=(sc.frame_current,sc.frame_subframe);saved_camera=sc.camera.name if sc.camera else None;started=time.perf_counter()
    shading=sc.display.shading
    saved_display={k:getattr(shading,k) for k in ('light','color_type','show_cavity','cavity_type')}
    saved_samples=sc.eevee.taa_render_samples if hasattr(sc,'eevee') else None
    try:
        before=_scene_once(level,sheet,engine,size,frames,asr)
        if not fix: return before
        applied=[]
        for action in safe_fixes(before['issues']):
            try:
                dispatch(action['tool'],action['args']);applied.append(dict(action,status='applied'))
            except (ValueError,RuntimeError,TypeError,KeyError,OSError) as exc:
                applied.append(dict(action,status='failed',reason=str(exc)))
        after=_scene_once(level,sheet,engine,size,frames,asr)
        after['issues']=camera_followups(after['shots'],after['issues'],applied)
        after.update(before=dict(score=before['score'],scores=before['scores'],issues=before['issues'],
                                 contact_sheet=before['contact_sheet'],report_md=before['report_md']),
                     fixed=applied,remaining=after['issues'],fix_rounds=1)
        after['timings']['total_with_fix']=round(time.perf_counter()-started,4)
        Path(after['report_md']).write_text(report_text(after),encoding='utf-8')
        Path(after['report_md']).with_suffix('.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
        return after
    finally:
        sc.frame_set(saved[0],subframe=saved[1])
        sc.camera=bpy.data.objects.get(saved_camera) if saved_camera else None
        for key,value in saved_display.items():setattr(shading,key,value)
        if saved_samples is not None:sc.eevee.taa_render_samples=saved_samples


@command('review_video')
def review_video(path,asr=False):
    output=context.resolve(path,'renders');directory=context.resolve('video_review_'+uuid.uuid4().hex[:8],'renders')
    os.makedirs(directory)
    sidecar=Path(output).with_suffix('.review_lines.json')
    lines=json.loads(sidecar.read_text()) if asr and sidecar.is_file() else None
    return _external('video',dict(path=output,lines=lines),directory)


@command('review_film')
def review_film(name=None,level='standard',fix=False,sheet=True,engine='workbench',size=384,asr=False,frames=None):
    from .film import _read,_snapshot_editor,_restore_editor
    film,manifest=_read(name);origin=_snapshot_editor();reports=[];issues=[];appearances=[];started=time.perf_counter()
    try:
        for scene in film['scenes']:
            dispatch('open_project',dict(path=scene['project']))
            current={}
            for ident,character in scene.get('characters',{}).items():
                body=bpy.data.objects.get(character.get('mesh',''));rig=bpy.data.objects.get(character.get('rig',''))
                if body and rig:
                    parts=[o for o in rig.children_recursive if o.type=='MESH' and not o.hide_render]
                    current[ident]=dict(skin=body.get('c3d_skin'),
                        hair=sorted(o.get('c3d_material_part','') for o in parts if o.get('c3d_material_part','').startswith('hair ')),
                        clothes=sorted(o.get('c3d_material_part',o.name) for o in parts if o.get('c3d_garment_category')))
            appearances.append(current)
            report=review_scene(level,fix,sheet,engine,size,asr,frames)
            report.update(index=scene['index'],name=scene['name'])
            reports.append(report)
            issues += [dict(i,scene=scene['index'],id=f"scene{scene['index']}:{i['id']}") for i in report['issues']]
            if fix: dispatch('save_project',dict(path=scene['project']))
        for index,(a,b) in enumerate(zip(film['scenes'],film['scenes'][1:])):
            for ident in set(appearances[index]) & set(appearances[index+1]):
                before=appearances[index][ident];after=appearances[index+1][ident]
                different={k:[before.get(k),after.get(k)] for k in ('hair','clothes','skin') if before.get(k)!=after.get(k)}
                if different:
                    issues.append(issue('appearance','continuity','info','Character appearance differs across scenes; verify the intended costume change.',different,scene=b['index'],character=ident))
        for s in film['scenes']:
            if s.get('card') and s['card']['duration_s']<3:
                issues.append(issue('film_card','continuity','warn','Scene card is shorter than three seconds.',dict(seconds=s['card']['duration_s']),scene=s['index']))
        from ..film_plan import layout
        import copy
        try: layout(copy.deepcopy(film['scenes']),film['fps'])
        except ValueError as exc: issues.append(issue('film_transition','continuity','error',str(exc)))
        directory=os.path.join(os.path.dirname(manifest),'review_'+uuid.uuid4().hex[:8]);os.makedirs(directory)
        combined=None
        if sheet:
            items=[dict(path=r['contact_sheet'],frame=r['index'],label=f"Scene {r['index']}: {r['name']}") for r in reports if r['contact_sheet']]
            if items:
                combined=_external('stack',dict(items=items,path=directory+'/contact_sheet.png',size=1024),directory)['path']
        total,scores=score(issues)
        report=dict(kind='film',name=film['name'],score=total,scores=scores,issues=issues,scenes=reports,
                    contact_sheet=combined,strips=[s for r in reports for s in r['strips']],report_md=directory+'/review.md',
                    timings=dict(total=round(time.perf_counter()-started,4)),limits=['Saved scenes only; editor restored after review.',
                    'Cross-scene wardrobe changes are reported for human intent review.'])
        if fix: report.update(fix_rounds=1,fixed=[dict(f,scene=r['index']) for r in reports for f in r.get('fixed',[])],remaining=issues)
        Path(report['report_md']).write_text(report_text(report),encoding='utf-8')
        Path(directory+'/review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        return report
    finally: _restore_editor(origin)
