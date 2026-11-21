"""Native Round 7 fixtures; no reference scripts, network or shared ports."""
from pathlib import Path
import hashlib,json
from contextlib import contextmanager,nullcontext
import numpy as np
from toon_round6_fixture import CASES,write_json

STATES=[('neutral','neutral',{}),('smile','smile',{}),('big_smile','big_smile',{}),
        ('A','neutral',{'aa_02':1}),('O','neutral',{'ow_08':1}),('surprised','surprised',{}),
        ('laugh','laugh',{}),('M','neutral',{'p_b_m_21':1,'mouthClose':.1}),
        ('jaw55','neutral',{'jawOpen':.55}),('tongue','neutral',{'jawOpen':.55,'tongueOut':1}),('B','neutral',{'p_b_m_21':1,'mouthClose':.1}),
        ('P','neutral',{'p_b_m_21':1,'mouthClose':.1}),
        ('blink','neutral',{'eyeBlinkLeft':1,'eyeBlinkRight':1}),
        ('blink_squint','laugh',{'eyeBlinkLeft':1,'eyeBlinkRight':1}),
        ('blink_surprised','surprised',{'eyeBlinkLeft':1,'eyeBlinkRight':1}),
        ('wink_left','laugh',{'eyeBlinkLeft':1}),('wink_right','laugh',{'eyeBlinkRight':1})]


@contextmanager
def lit_stage(camera,samples=16):
    """Reuse the engine's temporary render overrides across fixed-look cells.

    This removes repeated material/proxy construction and shader compilation.
    Neutral angle batches have fixed morphs; expression batches use animated-
    film without outline shells, so their native morphs remain live throughout.
    """
    import bpy
    from engine.commands import render as rendering
    sc=bpy.context.scene;sc.camera=bpy.data.objects[camera]
    sc.render.resolution_x=sc.render.resolution_y=512
    rendering._setup_engine(sc,'eevee');sc.eevee.taa_render_samples=samples
    look,style=rendering.applied_look,rendering.applied_style
    with look(sc,camera=sc.camera),style(sc):
        rendering.applied_look=lambda *a,**k:nullcontext()
        rendering.applied_style=lambda *a,**k:nullcontext()
        try:yield
        finally:rendering.applied_look,rendering.applied_style=look,style


def signature():
    root=Path(__file__).resolve().parents[1]
    files=['engine/commands/toon.py','engine/commands/toon_refine.py','engine/commands/toon_render.py','engine/toon_refine.py','engine/commands/render_style.py','engine/commands/mpfb.py']
    files += [str(p.relative_to(root)) for p in (root/'engine/commands').glob('toon7*.py')]
    return hashlib.sha256(b''.join((root/p).read_bytes() for p in files)).hexdigest()


def dump(body,parts,path):
    from engine.commands.toon import neutral_coords,coords,anatomy
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,parts,p)
    keys=body.data.shape_keys.key_blocks
    polygons=[list(f.vertices) for f in body.data.polygons]
    np.savez_compressed(path,points=p,edges=np.array([e.vertices[:] for e in body.data.edges]),
        faces=np.array(polygons),material_indices=np.array([f.material_index for f in body.data.polygons]),
        keys=np.array([k.name for k in keys]),targets=np.array([coords(k.data) for k in keys]),
        head_height=top-chin,chin=chin,eyes=np.asarray(eyes),
        weights_digest=hashlib.sha256(json.dumps([[(g.group,g.weight) for g in v.groups] for v in body.data.vertices]).encode()).hexdigest())


def capture(root_path,phase,name,build_only=False,quick=False,resume=False):
    import bpy
    from toon_round4_fixture import setup
    from engine.commands.materials import _family
    from engine.commands.toon import neutral_coords,anatomy
    from engine.commands.camera import camera_shot
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render_style import render_style
    from engine.commands.render import render_preview
    from engine.commands.io import save_project
    root=Path(root_path);out=root/phase;out.mkdir(parents=True,exist_ok=True)
    case=next(c for c in CASES if c[0]==name);_,tone,gender,body_style,hair=case
    import shutil
    from engine.commands import render as build_render
    original_preview=build_render.render_preview;build_views=[]
    def record_preview(*a,**kwargs):
        result=original_preview(*a,**kwargs)
        folder=root/'workbench'/phase;folder.mkdir(parents=True,exist_ok=True)
        view=kwargs.get('view','preview');file=folder/f'{name}_{view}.png'
        shutil.copy2(result['path'],file);build_views.append(dict(view=view,path=str(file)))
        return result
    build_render.render_preview=record_preview
    try:built,_=setup(tone,body_style,hair,gender)
    finally:build_render.render_preview=original_preview
    write_json(out/f'{name}_build_views.json',dict(cases=build_views))
    rig,body,parts=_family('Review_rig')
    bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
    bounds_file=root/f'{name}_bounds.npy'
    if phase=='before':np.save(bounds_file,np.array([v.co[:] for v in bounds.data.vertices]))
    else:bounds.data.vertices.foreach_set('co',np.load(bounds_file).astype(np.float32).ravel())
    body['c3d_round7_source']='d92d70d' if phase=='before' else signature()
    dump(body,parts,out/f'{name}_mesh.npz')
    save_project(path=f'round7/{phase}_{name}.blend')
    if build_only:return dict(built=built,mesh=str(out/f'{name}_mesh.npz'))
    path=out/'matrix.json';records=json.loads(path.read_text())['cases'] if path.exists() else []
    source='d92d70d' if phase=='before' else signature()
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,parts,p);h=top-chin;eye=np.mean(eyes,0)
    from engine.commands import render as rendering
    old_setup=rendering._setup_engine
    def samples(*args,**kwargs):
        result=old_setup(*args,**kwargs);bpy.context.scene.eevee.taa_render_samples=16;return result
    rendering._setup_engine=samples
    try:
        for look in (('studio_film',) if quick else ('studio_film','blue_hour')):
            cinematic_look(preset=look,dof='off')
            for style in ('anime','animated_film'):
                render_style(style=style)
                cam=camera_shot(subject=[bounds.name],shot='full',angle=35 if quick else 0,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
                with lit_stage(cam):
                  for angle in ((35,) if quick else (0,35,55)):
                    cam=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
                    def pixel(point):
                        uv=world_to_camera_view(bpy.context.scene,bpy.data.objects[cam],body.matrix_world@Vector(point))
                        return [float(uv.x*512),float((1-uv.y)*512)]
                    key=(name,angle,look,style);file=out/f'{name}_{angle}_{style}_{look}.png'
                    previous=next((c for c in records if tuple(c[k] for k in ('name','angle','look','style'))==key),None)
                    valid=resume and previous and previous['signature']==source and __import__('toon_round7_geometry').valid_png(file)
                    if not valid:render_preview(camera=cam,engine='eevee',width=512,height=512,filename=str(file))
                    record=dict(name=name,tone=tone,gender=gender,body_style=body_style,hair=hair,actual_hair=built.get('hair'),angle=angle,look=look,style=style,path=str(file),signature=source,
                        head_height_m=h,head_top_px=pixel([0,eye[1],top]),chin_px=pixel([0,eye[1],chin]),
                        eyes_px=[pixel(v) for v in eyes],mouth_px=pixel((p[520]+p[540])*.5),build=built)
                    records=[c for c in records if tuple(c[k] for k in ('name','angle','look','style'))!=key];records.append(record)
                    write_json(path,dict(cases=records))
    finally:rendering._setup_engine=old_setup
    return dict(cases=len(records),source=source)


def probe(root_path,phase='before',names=None,masks_only=False):
    import bpy
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.camera import camera_shot
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render_style import render_style
    from engine.commands.face import _set,_face_meshes,set_expression
    from engine.commands.render import render_preview
    from engine.commands import render as rendering
    root=Path(root_path);out=root/'probe_current'/phase;out.mkdir(parents=True,exist_ok=True)
    for name in names or ['light_F']:
        open_project(path=f'round7/{phase}_{name}.blend');rig,body,parts=_family('Review_rig')
        if phase=='after':
            from engine.commands.toon import head_surface
            head_surface(body)
        bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
        cam=camera_shot(subject=[bounds.name],shot='full',angle=35,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
        cinematic_look(preset='studio_film',dof='off');render_style(style='animated_film')
        with lit_stage(cam):
            for pose in ('neutral','smile','laugh'):
                _set(_face_meshes(body),{k.name:0 for k in body.data.shape_keys.key_blocks[1:] if not k.name.startswith(('_','$'))})
                set_expression(character=rig.name,expression=pose)
                if not masks_only:render_preview(camera=cam,engine='eevee',width=512,height=512,filename=str(out/f'{name}_{pose}.png'))
                from toon_round7_geometry import socket_faces,visibility
                data=np.load(root/'before'/f'{name}_mesh.npz');base=data['points'];channels=data['keys'].tolist();posed=[]
                from engine.commands.face import EXPRESSIONS
                for expression in ('smile','big_smile','laugh'):
                    q=base.copy()
                    for channel,value in EXPRESSIONS[expression].items():
                        q+=(data['targets'][channels.index(channel)]-base)*value
                    posed.append(q)
                ids=socket_faces(base,data['faces'],posed,float(data['head_height']))
                write_json(root/f'{name}_socket_faces.json',dict(face_ids=ids))
                visibility(body,ids,cam,out/f'{name}_{pose}_mask.png')
        if name=='light_F' and not masks_only:
            set_expression(character=rig.name,expression='neutral');render_style(style='anime')
            cam=camera_shot(subject=[bounds.name],shot='full',angle=0,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
            render_preview(camera=cam,engine='eevee',width=512,height=512,filename=str(out/f'{name}_jaw_front.png'))
    return dict(path=str(out))


def expressions(root_path,phase='before',names=None):
    import bpy,shutil
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.toon import neutral_coords,coords,anatomy
    from engine.commands.camera import camera_shot
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render_style import render_style
    from engine.commands.face import _set,_face_meshes,set_expression
    from engine.commands import render as rendering
    from toon_round7_geometry import socket_faces,visibility,gaps,insert_depths
    root=Path(root_path);out=root/'expressions'/phase;out.mkdir(parents=True,exist_ok=True)
    old_setup=rendering._setup_engine
    def samples(*args,**kwargs):
        result=old_setup(*args,**kwargs);bpy.context.scene.eevee.taa_render_samples=8;return result
    rendering._setup_engine=samples
    try:
        for name in names or [c[0] for c in CASES]:
            open_project(path=f'round7/{phase}_{name}.blend');rig,body,parts=_family('Review_rig')
            if phase=='after' and (body.get('c3d_toon_mouth_version',0)<4 or body.get('c3d_round7_source')!=signature()):
                # Rebuild stale prototypes through the production constructor.
                previous=neutral_coords(body).copy()
                capture(root_path,phase,name,build_only=True)
                open_project(path=f'round7/{phase}_{name}.blend');rig,body,parts=_family('Review_rig')
                assert np.array_equal(previous,neutral_coords(body)),'A tongue-only revision changed neutral geometry'
            bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
            p=neutral_coords(body);_,top,chin,eyes=anatomy(body,parts,p);h=top-chin;keys=body.data.shape_keys.key_blocks
            poses={}
            for pose,expression,units in STATES:
                _set(_face_meshes(body),{k.name:0 for k in keys[1:] if not k.name.startswith(('$','_'))})
                set_expression(character=rig.name,expression=expression);_set(_face_meshes(body),units);bpy.context.view_layer.update()
                q=p.copy()
                for key in keys[1:]:q+=(coords(key.data)-coords(key.relative_key.data))*key.value
                poses[pose]=(q.copy(),{k.name:float(k.value) for k in keys[1:] if k.value and not k.name.startswith('$')})
            socket_file=root/f'{name}_socket_faces.json'
            if phase=='before':
                faces=np.array([list(f.vertices) for f in body.data.polygons]);ids=socket_faces(p,faces,[poses[v][0] for v in ('smile','big_smile','laugh')],h)
                write_json(socket_file,dict(face_ids=ids,physical_faces=int((faces<13380).all(1).sum())))
            else:ids=json.loads(socket_file.read_text())['face_ids']
            records=[]
            for angle in (0,35,55):
                cam=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
                cinematic_look(preset='studio_film',dof='off');render_style(style='animated_film')
                def pixel(point):
                    uv=world_to_camera_view(bpy.context.scene,bpy.data.objects[cam],body.matrix_world@Vector(point))
                    return [float(uv.x*512),float((1-uv.y)*512)]
                with lit_stage(cam,samples=8):
                    for pose,expression,units in STATES:
                        _set(_face_meshes(body),{k.name:0 for k in keys[1:] if not k.name.startswith(('$','_'))})
                        set_expression(character=rig.name,expression=expression);_set(_face_meshes(body),units);bpy.context.view_layer.update()
                        q,_=poses[pose];row=dict(name=name,pose=pose,angle=angle,phase=phase,**gaps(body,q,h),
                            mouth_px=pixel((q[520]+q[540])*.5),head_height_px=float(np.linalg.norm(np.array(pixel([0,eyes[0][1],top]))-pixel([0,eyes[0][1],chin]))),
                            lower_lids_px=[[pixel(q[i]) for i in dict.fromkeys(pair[1] for pair in pairs)] for pairs in __import__('engine.toon',fromlist=['LID_PAIRS']).LID_PAIRS.values()])
                        if phase=='after':
                            if pose in ('M','B','P'):assert row['full_rim_gap_m']<.001,row
                            if pose in ('blink','blink_squint','blink_surprised'):assert row['lid_gap_m']<.0001,row
                        from engine.commands.toon_refine import _lip_paths
                        upper,lower=_lip_paths(p)
                        # Sort each rim by X to make an aperture polygon; the source
                        # paths contain both mirrored halves and shared canthi.
                        up=sorted(set(upper),key=lambda i:q[i,0]);low=sorted(set(lower),key=lambda i:q[i,0],reverse=True)
                        row['mouth_rim_px']=[pixel(q[i]) for i in up+low]
                        if angle==35:
                            row['insert_depths']=insert_depths(body,parts,q)
                            if pose in ('blink','blink_squint','blink_surprised'):
                                from toon_round4_fixture import hair_visibility
                                row['closed_eye_visibility']=hair_visibility(cam)
                                if phase=='after':assert all(v['ideal']==0 for v in row['closed_eye_visibility'].values()),row
                        if pose in ('neutral','smile','big_smile','laugh'):
                            mask=root/'socket_masks'/phase/f'{name}_{angle}_{pose}.png';mask.parent.mkdir(parents=True,exist_ok=True)
                            visibility(body,ids,cam,mask);row['socket_mask']=str(mask)
                        beauty=(angle==35 and pose in ('neutral','smile','big_smile','A','O','surprised','laugh','M','jaw55','tongue','blink')) or pose in ('smile','big_smile','laugh','A','O') or (phase=='after' and pose=='blink')
                        if beauty:
                            file=out/f'{name}_{angle}_{pose}.png'
                            rendering.render_preview(camera=cam,engine='eevee',width=512,height=512,filename=str(file))
                            row['path']=str(file)
                        records.append(row);write_json(out/f'{name}.json',dict(cases=records))
            write_json(out/f'{name}.json',dict(cases=records,
                beauty_source='d92d70d' if phase=='before' else signature(),
                beauty_frames_refreshed=sum(bool(row.get('path')) for row in records),
                native_targets_sha256=hashlib.sha256(np.asarray([coords(k.data) for k in keys]).tobytes()).hexdigest()))
    finally:rendering._setup_engine=old_setup
    return dict(path=str(out))


def colour(root_path,phase='after',names=None):
    from toon_round4b_fixture import matrix
    result=matrix(str(Path(root_path)/'colour'),project_prefix='round7/colour')
    return result


def beauty_refresh(root_path,phase='after',names=None):
    """Refresh beauty pixels after a shader-only revision, retaining native QA.

    Verify all native target coordinates before reusing the stored projection,
    aperture and socket-ID measurements. No image transformation is performed.
    """
    import bpy
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.toon import coords
    from engine.commands.face import _set,_face_meshes,set_expression
    from engine.commands.camera import camera_shot
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render_style import render_style
    from engine.commands.render import render_preview
    root=Path(root_path)
    for name in names or [c[0] for c in CASES]:
        file=root/'expressions'/phase/f'{name}.json';record=json.loads(file.read_text())
        open_project(path=f'round7/{phase}_{name}.blend');rig,body,parts=_family('Review_rig')
        saved=np.load(root/phase/f'{name}_mesh.npz');keys=body.data.shape_keys.key_blocks
        assert saved['keys'].tolist()==[k.name for k in keys]
        assert np.array_equal(saved['targets'],np.asarray([coords(k.data) for k in keys]))
        digest=hashlib.sha256(saved['targets'].tobytes()).hexdigest()
        if 'native_targets_sha256' in record:
            assert record['native_targets_sha256']==digest,name
        else:
            # The original v4 capture predates this header. Its archived freeze
            # proves that only render_style changed for this one-time replay.
            original=json.loads((root/'source_freeze_rejected_warmth.json').read_text())
            source_root=Path(__file__).resolve().parents[1]
            for path,expected in original['files'].items():
                if path!='engine/commands/render_style.py':
                    assert hashlib.sha256((source_root/path).read_bytes()).hexdigest()==expected,path
        bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
        count=0
        for angle in (0,35,55):
            camera=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
            cinematic_look(preset='studio_film',dof='off');render_style(style='animated_film')
            with lit_stage(camera,samples=8):
                for row in record['cases']:
                    if row['angle']!=angle or not row.get('path'):continue
                    _,expression,units=next(s for s in STATES if s[0]==row['pose'])
                    _set(_face_meshes(body),{k.name:0 for k in keys[1:] if not k.name.startswith(('$','_'))})
                    set_expression(character=rig.name,expression=expression);_set(_face_meshes(body),units)
                    render_preview(camera=camera,engine='eevee',width=512,height=512,filename=row['path']);count+=1
        record.update(beauty_source=signature(),beauty_frames_refreshed=count,native_targets_sha256=digest)
        write_json(file,record)
    return dict(refreshed=True)


def projection(root_path,phase='after',names=None):
    import bpy
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.camera import camera_shot
    from engine.commands.toon import neutral_coords,anatomy
    root=Path(root_path);out=root/'projection'/phase;out.mkdir(parents=True,exist_ok=True)
    matrix=json.loads((root/phase/'matrix.json').read_text())['cases']
    for name in names or [c[0] for c in CASES]:
        open_project(path=f'round7/{phase}_{name}.blend');rig,body,parts=_family('Review_rig')
        p=neutral_coords(body);_,top,chin,eyes=anatomy(body,parts,p);h=top-chin;eye=np.mean(eyes,0)
        bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'));rows={}
        for angle in (0,35,55):
            cam=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
            def pixel(point):
                uv=world_to_camera_view(bpy.context.scene,bpy.data.objects[cam],body.matrix_world@Vector(point))
                return [float(uv.x*512),float((1-uv.y)*512)]
            reference=next(c for c in matrix if c['name']==name and c['angle']==angle)
            error=float(abs(np.asarray([pixel(v) for v in eyes])-reference['eyes_px']).max());assert error<.001,error
            candidate=np.flatnonzero((np.arange(len(p))<13380)&(abs(p[:,0])<.05*h)&(p[:,2]>chin-.01*h)&(p[:,2]<chin+.07*h))
            front_chin=candidate[np.argmin(p[candidate,1])]
            rows[str(angle)]=dict(camera_replay_error_px=error,chin_tip=pixel(p[791]),chin_surface=pixel(p[front_chin]),chin_surface_vertex=int(front_chin),
                cheeks=[pixel([sign*.18*h,eye[1]-.012*h,eye[2]-.14*h]) for sign in (-1,1)],
                crown=pixel([.07*h,eye[1]+.1*h,chin+.94*h]))
        write_json(out/f'{name}.json',rows)
    return dict(path=str(out))


def qa(root_path,phase='after',names=None):
    import bpy
    from engine.commands.io import open_project
    from engine.commands.materials import _family,_role
    from engine.commands.toon import neutral_coords,anatomy,coords
    from engine.commands.face import ARKIT,VISEMES
    root=Path(root_path);out=root/'qa'/phase;out.mkdir(parents=True,exist_ok=True);report=[]
    for name in names or [c[0] for c in CASES]:
        open_project(path=f'round7/{phase}_{name}.blend');rig,body,parts=_family('Review_rig')
        _,top,chin,_=anatomy(body,parts);head_height=top-chin
        if phase=='after':assert body.get('c3d_round7_source')==signature(),(name,'stale build')
        bones={b.name for b in rig.data.bones if b.use_deform}
        def bone_weights(obj):
            groups={g.index:g.name for g in obj.vertex_groups};weights=[]
            for vertex in obj.data.vertices:
                weights.append(sorted((groups[g.group],float(g.weight)) for g in vertex.groups if groups[g.group] in bones and g.weight>0))
            return weights
        def digest(value):return hashlib.sha256(json.dumps(value).encode()).hexdigest()
        row=dict(name=name,source=body.get('c3d_round7_source'),mouth_version=body.get('c3d_toon_mouth_version',0),weights_digest=digest(bone_weights(body)),
            bones_digest=digest([(b.name,[list(v) for v in b.matrix_local]) for b in rig.data.bones]),
            topology_digest=digest([list(f.vertices) for f in body.data.polygons]),landmarks=rig.get('c3d_landmarks'),meshes=[])
        for obj in parts:
            p=neutral_coords(obj);obj.data.calc_loop_triangles();triangles=np.array([list(t.vertices) for t in obj.data.loop_triangles])
            normals=np.cross(p[triangles[:,1]]-p[triangles[:,0]],p[triangles[:,2]]-p[triangles[:,0]]) if triangles.size else np.empty((0,3))
            areas=np.linalg.norm(normals,axis=1)*.5
            counts={};oriented={}
            for face in obj.data.polygons:
                ids=list(face.vertices)
                for i,j in zip(ids,ids[1:]+ids[:1]):
                    edge=tuple(sorted((i,j)));counts[edge]=counts.get(edge,0)+1
                    oriented[edge]=oriented.get(edge,0)+(1 if i<j else -1)
            weights=bone_weights(obj);sums=np.array([sum(v for _,v in group) for group in weights]);uv=obj.data.uv_layers.active
            record=dict(name=obj.name,vertices=len(p),triangles=len(triangles),visible=not obj.hide_render,
                finite=bool(np.isfinite(p).all()),degenerate_triangles=int((areas<1e-12).sum()),
                boundary_edges=sum(v==1 for v in counts.values()),nonmanifold_edges=sum(v>2 for v in counts.values()),
                inconsistent_winding_edges=sum(counts[e]==2 and v!=0 for e,v in oriented.items()),
                uv_layers=len(obj.data.uv_layers),unweighted=int((sums<.00001).sum()),
                max_influences=max(map(len,weights),default=0),weight_sum_error=float(abs(sums-1).max()),
                generated_mouth=obj.get('c3d_toon_mouth'),source=obj.get('c3d_source'),blink_ink_max_shift_m=obj.get('c3d_toon_closed_ink_max_m',0),warnings=[])
            record['front_normal_fraction']=float((normals[:,1]<0).mean()) if len(normals) else None
            record['duplicate_positions']=len(p)-len(np.unique(np.round(p,7),axis=0))
            used={i for face in obj.data.polygons for i in face.vertices}
            record['loose_vertices']=len(p)-len(used)
            record['scale']=list(obj.scale);record['negative_scale']=any(v<0 for v in obj.scale)
            record['missing_images']=[]
            for material in obj.data.materials:
                if not material or not material.node_tree:continue
                for node in material.node_tree.nodes:
                    image=getattr(node,'image',None)
                    if image and image.source=='FILE' and not image.packed_file and not Path(bpy.path.abspath(image.filepath)).is_file():
                        record['missing_images'].append(image.name)
            if uv:
                uv_tri=np.array([[uv.data[i].uv[:] for i in t.loops] for t in obj.data.loop_triangles])
                if len(uv_tri):
                    a,b=uv_tri[:,1]-uv_tri[:,0],uv_tri[:,2]-uv_tri[:,0]
                    record['zero_area_uv_triangles']=int((abs(a[:,0]*b[:,1]-a[:,1]*b[:,0])<1e-12).sum())
            if record['duplicate_positions']:record['warnings'].append('Coincident authored seams/cards retained; no destructive vertex merge.')

            if record['boundary_edges']:record['warnings'].append('Authored open cards/rims or shallow mouth disk; render asset, not a watertight print.')
            if record['max_influences']>4:record['warnings'].append('Native MPFB influences retained; GLB uses a temporary four-influence limit.')
            assert record['finite'],record
            assert 0<=record['blink_ink_max_shift_m']<=.008*head_height+1e-7,record
            if _role(obj,body)=='hair' and obj.data.shape_keys:
                units=set(ARKIT+VISEMES)
                record['facial_hair_delta_max_m']=max((float(np.linalg.norm(coords(k.data)-coords(k.relative_key.data),axis=1).max()) for k in obj.data.shape_keys.key_blocks if k.name in units or k.name.startswith('_c3d_')),default=0.)
                if phase=='after' and obj.get('c3d_toon_steady_scalp_hair'):assert record['facial_hair_delta_max_m']<1e-8,record
            if record['generated_mouth']:
                assert not record['degenerate_triangles'] and not record['nonmanifold_edges'] and not record['unweighted'] and record['uv_layers'],record
                assert not record['loose_vertices'] and not record['negative_scale'] and not record['missing_images'] and not record.get('zero_area_uv_triangles',0),record
                assert not record['inconsistent_winding_edges'],record
                assert record['front_normal_fraction']>.99,record
                if record['generated_mouth']=='cavity':
                    from toon_round7_geometry import mouth_backfaces
                    bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
                    record['backface_review']=mouth_backfaces(body,obj,bounds)
                    # A concave oral pocket is deliberately two-sided. A side
                    # visible through the lip opening is not reversed winding;
                    # retain the view diagnostic rather than reject a valid bowl.
                    record['double_sided']=all(not s.material.use_backface_culling for s in obj.material_slots if s.material)
                    assert record['double_sided'],record
                    if any(r['exposed_backward_triangles'] for r in record['backface_review']):
                        record['warnings'].append('Oblique view exposes a two-sided inner-pocket surface; winding remains consistent.')
            row['meshes'].append(record)
        if name=='light_F':
            bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
            wire_review(body,parts,bounds,out)
        report.append(row);write_json(out/f'{name}.json',row)
    return dict(cases=len(report))


def hair(root_path,phase='after',names=None):
    """Side/opposite-side/profile review of the actual Bima replacement."""
    import bpy
    from engine.commands.io import open_project
    from engine.commands.camera import camera_shot
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render import render_preview
    root=Path(root_path);out=root/'hair'/phase;out.mkdir(parents=True,exist_ok=True)
    open_project(path=f'round7/{phase}_dark_M.blend')
    bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
    rows=[]
    for style in ('anime','animated_film'):
        cinematic_look(preset='studio_film',dof='off');render_style(style=style)
        camera=camera_shot(subject=[bounds.name],shot='full',angle=0,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
        with lit_stage(camera):
            for angle in (0,35,-55,90):
                camera=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
                path=out/f'{style}_{angle}.png'
                if angle in (0,35):
                    import shutil
                    shutil.copy2(root/phase/f'dark_M_{angle}_{style}_studio_film.png',path)
                else:render_preview(camera=camera,engine='eevee',width=512,height=512,filename=str(path))
                from toon_round4_fixture import hair_visibility
                eyes=hair_visibility(camera)
                if angle!=90:assert all(v['blocked_by_hair']==0 for v in eyes.values()),(phase,angle,eyes)
                rows.append(dict(style=style,angle=angle,path=str(path),eyes=eyes))
    write_json(out/'matrix.json',dict(cases=rows));return dict(cases=len(rows))


def wire_review(body,parts,bounds,out):
    """Own control-cage review, following the MIT asset-QA reference technique."""
    import bpy
    from mathutils import Vector
    from engine.commands.camera import camera_shot
    from engine.commands.render import render_preview
    from engine.commands.toon import neutral_coords,anatomy
    p=neutral_coords(body);_,top,chin,_=anatomy(body,parts,p);h=top-chin
    curve=bpy.data.curves.new('__round7_control_cage','CURVE');curve.dimensions='3D'
    curve.resolution_u=1;curve.bevel_resolution=0;curve.bevel_depth=h*.0005
    for edge in body.data.edges:
        a,b=edge.vertices
        if max(a,b)>=13380 or min(p[a,2],p[b,2])<chin-.12*h:continue
        line=curve.splines.new('POLY');line.points.add(1)
        for point,index in zip(line.points,(a,b)):
            vertex=p[index]+np.asarray(body.data.vertices[index].normal)*h*.001
            point.co=(*vertex,1)
    wire=bpy.data.objects.new(curve.name,curve);bpy.context.collection.objects.link(wire);wire.matrix_world=body.matrix_world.copy()
    mat=bpy.data.materials.new('__round7_wire');mat.diffuse_color=(.003,.003,.003,1);curve.materials.append(mat)
    hidden=[(o,o.hide_render) for o in parts if o is not body]
    sub=[(m,m.show_render) for m in body.modifiers if m.type=='SUBSURF']
    colors=[(m,tuple(m.diffuse_color)) for m in body.data.materials if m]
    try:
        for obj,_ in hidden:obj.hide_render=True
        for mod,_ in sub:mod.show_render=False
        for m,_ in colors:m.diffuse_color=(.45,.45,.45,1)
        for angle in (0,35):
            cam=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
            render_preview(camera=cam,engine='workbench',width=512,height=512,filename=str(out/f'wire_{angle}.png'))
    finally:
        for obj,state in hidden:obj.hide_render=state
        for mod,state in sub:mod.show_render=state
        for material,color in colors:material.diffuse_color=color
        bpy.data.objects.remove(wire,do_unlink=True);bpy.data.curves.remove(curve);bpy.data.materials.remove(mat)


def articulation(root_path,phase='after',names=None):
    import bpy
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.toon import neutral_coords,coords,anatomy
    from engine.commands.face import _set,_face_meshes,set_expression
    from toon_round7_geometry import gaps,insert_depths
    root=Path(root_path);out=root/'articulation'/phase;out.mkdir(parents=True,exist_ok=True)
    for name in names or [c[0] for c in CASES]:
        open_project(path=f'round7/{phase}_{name}.blend');rig,body,parts=_family('Review_rig')
        p=neutral_coords(body);_,top,chin,_=anatomy(body,parts,p);keys=body.data.shape_keys.key_blocks;rows=[]
        for pose,expression,units in STATES:
            _set(_face_meshes(body),{k.name:0 for k in keys[1:] if not k.name.startswith(('$','_'))})
            set_expression(character=rig.name,expression=expression);_set(_face_meshes(body),units);bpy.context.view_layer.update()
            q=p.copy()
            for key in keys[1:]:q+=(coords(key.data)-coords(key.relative_key.data))*key.value
            row=dict(pose=pose,**gaps(body,q,top-chin),insert_depths=insert_depths(body,parts,q));rows.append(row)
        write_json(out/f'{name}.json',dict(cases=rows))
    return dict(path=str(out))


def look_rows(root_path,phase='after',names=None):
    """Strong squint and open vowel in every requested render/lighting pairing."""
    import bpy
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.face import _set,_face_meshes,set_expression
    from engine.commands.camera import camera_shot
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    from engine.commands import render as rendering
    root=Path(root_path);out=root/'look_rows'/phase;out.mkdir(parents=True,exist_ok=True)
    original=rendering._setup_engine
    def setup(*a,**k):
        result=original(*a,**k);bpy.context.scene.eevee.taa_render_samples=8;return result
    rendering._setup_engine=setup
    try:
        for name in names or [c[0] for c in CASES]:
            open_project(path=f'round7/{phase}_{name}.blend');rig,body,parts=_family('Review_rig')
            bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
            camera=camera_shot(subject=[bounds.name],shot='full',angle=35,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera'];rows=[]
            templates=json.loads((root/'expressions'/phase/f'{name}.json').read_text())['cases']
            for style in ('anime','animated_film'):
                for look in ('studio_film','blue_hour'):
                    cinematic_look(preset=look,dof='off');render_style(style=style)
                    for pose,expression,units in [('big_smile','big_smile',{}),('A','neutral',{'aa_02':1})]:
                        _set(_face_meshes(body),{k.name:0 for k in body.data.shape_keys.key_blocks[1:] if not k.name.startswith(('$','_'))})
                        set_expression(character=rig.name,expression=expression);_set(_face_meshes(body),units)
                        # Anime's evaluated outline shell must be rebuilt for
                        # each pose; retaining a neutral shell would clip vowels.
                        file=out/f'{name}_{style}_{look}_{pose}.png'
                        template=next(c for c in templates if (c['pose'],c['angle'])==(pose,35))
                        from engine.commands.toon import neutral_coords,coords
                        from bpy_extras.object_utils import world_to_camera_view
                        from mathutils import Vector
                        keys=body.data.shape_keys.key_blocks;q=neutral_coords(body)
                        for key in keys[1:]:q+=(coords(key.data)-coords(key.relative_key.data))*key.value
                        uv=world_to_camera_view(bpy.context.scene,bpy.data.objects[camera],body.matrix_world@Vector((q[520]+q[540])*.5))
                        error=float(abs(np.array([uv.x*512,(1-uv.y)*512])-template['mouth_px']).max())
                        assert error<.001,(phase,name,style,look,error)
                        reused=None
                        if style=='animated_film' and look=='studio_film':
                            # Identical pose, fixed bounds/lens, engine and eight
                            # samples; retain provenance instead of re-rendering.
                            import shutil
                            from toon_round7_geometry import valid_png
                            assert valid_png(template['path']),template
                            shutil.copy2(template['path'],file);reused=template['path']
                        else:
                            rendering.render_preview(camera=camera,engine='eevee',width=512,height=512,filename=str(file))
                        rows.append(dict(template,style=style,look=look,path=str(file),camera_replay_error_px=error,reused_from=reused))
                        write_json(out/f'{name}.json',dict(cases=rows))
    finally:rendering._setup_engine=original
    return dict(path=str(out))


def chibi(root_path,phase='after',names=None):
    import bpy
    from toon_round4_fixture import setup
    from engine.commands.materials import _family
    from engine.commands.camera import camera_shot
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render import render_preview
    from engine.commands.io import save_project
    root=Path(root_path);out=root/'chibi'/phase;out.mkdir(parents=True,exist_ok=True)
    build,_=setup('light','chibi','ponytail01',0);rig,body,parts=_family('Review_rig')
    bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
    boundfile=root/'chibi_bounds.npy'
    if phase=='before':np.save(boundfile,np.array([v.co[:] for v in bounds.data.vertices]))
    else:bounds.data.vertices.foreach_set('co',np.load(boundfile).astype(np.float32).ravel())
    dump(body,parts,out/'mesh.npz');save_project(path=f'round7/{phase}_chibi.blend');rows=[]
    cinematic_look(preset='studio_film',dof='off')
    for style in ('anime','animated_film'):
        render_style(style=style)
        cam=camera_shot(subject=[bounds.name],shot='full',angle=0,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
        with lit_stage(cam):
            for angle in (0,35,55):
                cam=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
                file=out/f'{style}_{angle}.png';render_preview(camera=cam,engine='eevee',width=512,height=512,filename=str(file))
                rows.append(dict(style=style,angle=angle,path=str(file)));write_json(out/'matrix.json',dict(build=build,cases=rows))
    return dict(path=str(out))


def hair_ref(root_path,phase='after',names=None):
    """Fresh PBR references for the requested short02 and ponytail pigments."""
    import bpy
    from toon_round4_fixture import setup
    from engine.commands.materials import _family
    from engine.commands.toon import neutral_coords,anatomy
    from engine.commands.camera import camera_shot
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render import render_preview
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    root=Path(root_path);out=root/'hair_reference';out.mkdir(parents=True,exist_ok=True);rows=[]
    for name,tone,gender,hair in [('light_F','light',0,'ponytail01'),('dark_M','dark',1,'short02')]:
        build,_=setup(tone,'realistic',hair,gender);rig,body,parts=_family('Review_rig')
        bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
        camera=camera_shot(subject=[bounds.name],shot='full',angle=35,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
        cinematic_look(preset='studio_film',dof='off');render_style(style='none')
        file=out/f'{name}.png';render_preview(camera=camera,engine='eevee',width=512,height=512,filename=str(file))
        p=neutral_coords(body);_,top,chin,eyes=anatomy(body,parts,p);eye=np.mean(eyes,0);h=top-chin
        uv=world_to_camera_view(bpy.context.scene,bpy.data.objects[camera],body.matrix_world@Vector((.07*h,eye[1]+.10*h,chin+.94*h)))
        rows.append(dict(name=name,hair=hair,path=str(file),crown=[float(uv.x*512),float((1-uv.y)*512)],build=build))
        write_json(out/'matrix.json',dict(cases=rows))
    return dict(cases=len(rows))
