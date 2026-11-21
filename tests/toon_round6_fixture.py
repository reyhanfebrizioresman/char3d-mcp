"""Round 6 owned MPFB portraits. Called through MCP on port 9971 only."""
from pathlib import Path
import json
import numpy as np

CASES=[(f'{tone}_{sex}',tone,gender,'cartoon' if tone=='light' and gender==0 else 'anime','bob01' if gender==0 and tone=='medium' else 'ponytail01' if gender==0 else 'short02') for tone in ('light','medium','dark') for sex,gender in (('F',0),('M',1))]


def write_json(path,value):
    temporary=path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value,indent=2));temporary.replace(path)


def source_signature():
    import hashlib
    root=Path(__file__).resolve().parents[1]
    paths=('engine/commands/toon.py','engine/commands/toon_refine.py','engine/commands/toon_render.py','engine/toon_refine.py','engine/commands/render_style.py','tests/toon_round6_fixture.py')
    return hashlib.sha256(b''.join((root/p).read_bytes() for p in paths)).hexdigest()


def _capture(root_path,phase='before',names=None,quick=False,skip_keys=()):
    import bpy
    from toon_round4_fixture import setup
    from engine.commands.materials import _family
    from engine.commands.camera import camera_shot
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render_style import render_style
    from engine.commands.render import render_preview
    from engine.commands.io import save_project
    out=Path(root_path)/phase;out.mkdir(parents=True,exist_ok=True)
    report_path=out/'matrix.json';report=json.loads(report_path.read_text()) if report_path.exists() else dict(cases=[])
    for name,tone,gender,body_style,hair in CASES:
        if names and name not in names:continue
        built,camera=setup(tone,body_style,hair,gender)
        rig,body,parts=_family('Review_rig')
        bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
        # Use fixed baseline bounds so camera/light changes cannot improve a score.
        bounds_path=Path(root_path)/f'{name}_bounds.npy'
        if phase=='before':np.save(bounds_path,np.array([v.co[:] for v in bounds.data.vertices]))
        else:bounds.data.vertices.foreach_set('co',np.load(bounds_path).astype(np.float32).ravel())
        from engine.commands.toon import neutral_coords,anatomy
        p=neutral_coords(body);_,top,chin,eyes=anatomy(body,parts,p);h=top-chin
        iris=json.loads(body.get('c3d_toon_iris_centers','null')) or eyes
        np.savez(out/f'{name}_mesh.npz',points=p,edges=np.array([e.vertices[:] for e in body.data.edges]),head_height=h,chin=chin,eyes=np.array(eyes),iris_centers=np.array(iris))
        if phase=='after':
            from engine.commands.toon_render import face_normal_proxies
            state=(set(bpy.data.objects.keys()),set(bpy.data.meshes.keys()),[g.name for g in body.vertex_groups],[m.name for m in body.modifiers])
            try:
                with face_normal_proxies(bpy.context.scene):
                    assert any(m.name=='__c3d_face_normals' for m in body.modifiers)
                    raise RuntimeError('intentional Round 6 restoration probe')
            except RuntimeError as error:
                assert str(error)=='intentional Round 6 restoration probe'
            assert state==(set(bpy.data.objects.keys()),set(bpy.data.meshes.keys()),[g.name for g in body.vertex_groups],[m.name for m in body.modifiers])
        for angle in ((35,) if quick else (0,35,55)):
            shot=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)
            camera=shot['camera']
            for look in (('studio_film',) if quick else ('studio_film','blue_hour')):
                cinematic_look(preset=look,dof='off')
                for style in ('anime','animated_film'):
                    render_style(style=style)
                    path=out/f'{name}_{angle}_{style}_{look}.png'
                    if [name,angle,look,style] not in skip_keys:
                        render_preview(camera=camera,engine='eevee',width=256,height=256,filename=str(path))
                    assert not any(o.name.startswith('__c3d_face_normal_proxy') for o in bpy.context.scene.objects)
                    from bpy_extras.object_utils import world_to_camera_view
                    from mathutils import Vector
                    cam=bpy.data.objects[camera];sc=bpy.context.scene
                    sites=[(0,float(np.mean(eyes,0)[1]),chin+.34*h),(.18*h,float(np.mean(eyes,0)[1])-.012*h,float(np.mean(eyes,0)[2])-.14*h)]
                    uv=[[float(q.x*256),float((1-q.y)*256)] for q in [world_to_camera_view(sc,cam,body.matrix_world@Vector(s)) for s in sites]]
                    eye=np.mean(eyes,0);mouth_z=float(p[np.asarray([[520,540],[521,538],[7267,7282]]).ravel(),2].mean())
                    face_corners=[(x,eye[1],z) for x,z in ((-.23*h,mouth_z+.07*h),(.23*h,mouth_z+.07*h),(.23*h,eye[2]-.075*h),(-.23*h,eye[2]-.075*h))]
                    face_polygon=[]
                    for point in face_corners:
                        v=world_to_camera_view(sc,cam,body.matrix_world@Vector(point));face_polygon.append([float(v.x*256),float((1-v.y)*256)])
                    hair_site=world_to_camera_view(sc,cam,body.matrix_world@Vector((.07*h,eye[1]+.10*h,eye[2]+.31*h)))
                    hair_metrics=[dict(object=o.name,vertices=o.get('c3d_toon_root_vertices',0),max_delta_m=o.get('c3d_toon_root_max_delta_m',0),roughness_before=o.get('c3d_toon_root_roughness_before'),roughness_after=o.get('c3d_toon_root_roughness_after')) for o in parts if 'c3d_toon_root_vertices' in o]
                    record=dict(name=name,tone=tone,gender=gender,body_style=body_style,hair=hair,angle=angle,look=look,style=style,path=str(path),sites=uv,face_polygon=face_polygon,hair_site=[float(hair_site.x*256),float((1-hair_site.y)*256)],build=built,hair_metrics=hair_metrics,source_signature='c7720c9' if phase=='before' else source_signature())
                    key=lambda c:(c['name'],c['angle'],c['look'],c['style'])
                    report['cases']=[c for c in report['cases'] if key(c)!=key(record)];report['cases'].append(record)
                    write_json(report_path,report)
        save_project(path=f'round6/{phase}_{name}.blend')
    return dict(cases=len(report['cases']))


def diagnostic(root_path,labels=None):
    import bpy
    from contextlib import nullcontext
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.camera import camera_shot
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render_style import render_style
    from engine.commands.render import render_preview
    import engine.commands.toon_render as normal
    from engine.commands.toon import coords
    out=Path(root_path)/'diagnostic';out.mkdir(parents=True,exist_ok=True)
    open_project(path='round6/after_light_F.blend');rig,body,parts=_family('Review_rig')
    bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
    cam=camera_shot(subject=[bounds.name],shot='full',angle=35,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
    report={}
    report['mouth']={o.name:dict(ymin=float(coords(o.data.vertices)[:,1].min()),ymax=float(coords(o.data.vertices)[:,1].max())) for o in parts if any(w in o.name.lower() for w in ('teeth','tongue'))}
    for label,hide,proxy,style,look in [('normal',False,True,'animated_film','studio_film'),('no_mouth_parts',True,True,'animated_film','studio_film'),('no_proxy',False,False,'animated_film','studio_film'),('no_physical',False,True,'animated_film','studio_film'),('blue_proxy_key',False,True,'anime','blue_hour')]:
        if labels and label not in labels:continue
        for o in parts:
            if any(w in o.name.lower() for w in ('teeth','tongue')):o.hide_render=hide
        old=normal.face_normal_proxies
        import engine.commands.render_style as shaders
        old_shader=shaders._animated_shader
        if label=='no_physical':
            def shader(tree,bsdf,cfg,name,engine):
                output=old_shader(tree,bsdf,cfg,name,engine)
                if cfg.get('_toon_role')=='skin':output.node.inputs[0].default_value=1.
                return output
            shaders._animated_shader=shader
        if not proxy:normal.face_normal_proxies=lambda scene:nullcontext()
        try:
            cinematic_look(preset=look,dof='off');render_style(style=style)
            path=out/f'{label}.png';render_preview(camera=cam,engine='eevee',width=384,height=384,filename=str(path));report[label]=str(path)
        finally:normal.face_normal_proxies=old;shaders._animated_shader=old_shader
    (out/'probe.json').write_text(json.dumps(report,indent=2));return report


def sampled(function,*args,**kwargs):
    import bpy
    from engine.commands import render as rendering
    original_setup=rendering._setup_engine
    def setup_engine(*args,**kwargs):
        result=original_setup(*args,**kwargs);bpy.context.scene.eevee.taa_render_samples=8;return result
    rendering._setup_engine=setup_engine
    try:return function(*args,**kwargs)
    finally:rendering._setup_engine=original_setup


def capture(*args,**kwargs):
    return sampled(_capture,*args,**kwargs)


def articulation(root_path,phase='after',name='dark_M',render=True,labels=None):
    """Native relative-target gaps plus visible mouth bounding box, all poses."""
    import bpy
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.toon import coords,neutral_coords,anatomy,LIP_PAIRS,face_metrics
    from engine.commands.face import _set,_face_meshes,set_expression
    from engine.toon import LID_PAIRS
    from engine.commands.camera import camera_shot
    from engine.commands.render import render_preview
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    out=Path(root_path)/'articulation'/phase/name;out.mkdir(parents=True,exist_ok=True)
    open_project(path=f'round6/{phase}_{name}.blend');rig,body,parts=_family('Review_rig')
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,parts,p);h=top-chin
    keys=body.data.shape_keys.key_blocks
    bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
    camera=camera_shot(subject=[bounds.name],shot='full',angle=35,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
    cinematic_look(preset='studio_film',dof='off');render_style(style='animated_film')
    states=[('neutral','neutral',{}),('smile','smile',{}),('A','neutral',{'aa_02':1}),('O','neutral',{'ow_08':1}),
            ('M','neutral',{'p_b_m_21':1,'mouthClose':.1}),('B','neutral',{'p_b_m_21':1,'mouthClose':.1}),
            ('P','neutral',{'p_b_m_21':1,'mouthClose':.1}),('surprised','surprised',{}),
            ('blink','neutral',{'eyeBlinkLeft':1,'eyeBlinkRight':1}),
            ('A_smile','smile',{'aa_02':1}),('blink_squint','neutral',{'eyeBlinkLeft':1,'eyeBlinkRight':1,'eyeSquintLeft':.3,'eyeSquintRight':.3})]
    signature='c7720c9' if phase=='before' else source_signature()
    previous=json.loads((out/'metrics.json').read_text()) if (out/'metrics.json').exists() else {}
    reusable={s['name'] for s in previous.get('states',[]) if s.get('path')} if previous.get('source_signature')==signature else set()
    report=dict(name=name,phase=phase,source_signature=signature,head_height_m=h,measurements=face_metrics(body,parts),states=[])
    import hashlib
    def digest(value):return hashlib.sha256(value).hexdigest()
    report['binding']=dict(vertices=len(body.data.vertices),faces=len(body.data.polygons),shape_names=[k.name for k in keys],
        topology_sha256=digest(json.dumps([list(f.vertices) for f in body.data.polygons]).encode()),
        weights_sha256=digest(json.dumps([[(g.group,g.weight) for g in v.groups] for v in body.data.vertices]).encode()),
        bones_sha256=digest(json.dumps([(b.name,[list(row) for row in b.matrix_local]) for b in rig.data.bones]).encode()),
        landmarks=rig.get('c3d_landmarks'))
    from engine.commands.toon_refine import _lip_paths
    upper,lower=_lip_paths(p)
    corner_left=min(upper,key=lambda i:p[i,0]);corner_right=max(upper,key=lambda i:p[i,0])
    # Lid aperture and iris center are neutral-space measurements, independent of lighting.
    iris=json.loads(body.get('c3d_toon_iris_centers','null')) or eyes
    report['eyes']=[]
    for pairs in LID_PAIRS.values():
        ids=np.array(pairs);lo=p[ids[:,1],2].min();hi=p[ids[:,0],2].max();cx=float(p[ids.ravel(),0].mean())
        center=min(iris,key=lambda v:abs(v[0]-cx))
        report['eyes'].append(dict(height_head=float((hi-lo)/h),iris_height_in_opening=float((center[2]-lo)/(hi-lo))))
    for name,expression,units in states:
        _set(_face_meshes(body),{key.name:0. for key in keys[1:] if not key.name.startswith('$')})
        set_expression(character=rig.name,expression=expression);_set(_face_meshes(body),units)
        bpy.context.view_layer.update()
        q=coords(keys[0].data)
        for key in keys[1:]:q+=(coords(key.data)-coords(key.relative_key.data))*key.value
        gap=max(abs(float(q[a,2]-q[b,2])) for a,b in LIP_PAIRS)
        from bpy_extras.object_utils import world_to_camera_view
        from mathutils import Vector
        def pixel(point):
            v=world_to_camera_view(bpy.context.scene,bpy.data.objects[camera],body.matrix_world@Vector(point))
            return [float(v.x*384),float((1-v.y)*384)]
        center=(q[520]+q[540])*.5
        head_pixels=float(np.linalg.norm(np.array(pixel(center+[0,0,h]))-pixel(center)))
        def rim_at_x(indices,axis,xs):
            values=q[np.array(indices)];order=np.argsort(values[:,0]);return np.interp(xs,values[order,0],values[order,axis])
        xs=np.linspace(max(q[upper,0].min(),q[lower,0].min()),min(q[upper,0].max(),q[lower,0].max()),31)
        seam=np.stack([rim_at_x(upper,axis,xs)-rim_at_x(lower,axis,xs) for axis in (1,2)],axis=1)
        row=dict(name=name,lip_gap_m=gap,lip_gap_head=gap/h,lip_gap3d_m=max(float(np.linalg.norm(q[a]-q[b])) for a,b in LIP_PAIRS),full_rim_max_gap_m=float(np.linalg.norm(seam,axis=1).max()),
                 corner_lift_head=float((q[[corner_left,corner_right],2].mean()-center[2])/h),
                 mouth_center_px=pixel(center),head_height_px=head_pixels,
                 lid_gap3d_m=max(float(np.linalg.norm(q[a]-q[b])) for pairs in LID_PAIRS.values() for a,b in pairs))
        path=out/f'{name}.png'
        if render and name not in ('B','P','blink_squint') and (not labels or name in labels):
            valid=name in reusable and path.exists() and path.read_bytes().endswith(b'IEND\xaeB`\x82')
            if not valid:render_preview(camera=camera,engine='eevee',width=384,height=384,filename=str(path))
            row['path']=str(path)
        elif name in reusable and path.exists():row['path']=str(path)
        report['states'].append(row);write_json(out/'metrics.json',report)
    return dict(states=len(report['states']),path=str(out/'metrics.json'))


def colour(root_path):
    from toon_round4b_fixture import matrix
    return matrix(str(Path(root_path)/'colour'),project_prefix='round6/colour')


def mouth_diagnostic(root_path):
    import bpy
    from engine.commands.io import open_project
    from engine.commands.materials import _family,_role
    from engine.commands.toon import coords,LIP_PAIRS
    from engine.commands.face import _set,_face_meshes,set_expression
    from engine.commands.render_style import render_style
    from engine.commands.render import render_preview
    from engine.commands.cinematic import cinematic_look
    from engine.commands.camera import camera_shot
    out=Path(root_path)/'diagnostic_mouth';out.mkdir(parents=True,exist_ok=True)
    open_project(path='round6/after_dark_M.blend');rig,body,parts=_family('Review_rig')
    keys=body.data.shape_keys.key_blocks
    bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
    cam=camera_shot(subject=[bounds.name],shot='full',angle=35,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
    cinematic_look(preset='studio_film',dof='off');result={}
    for pose in ('smile','A'):
        _set(_face_meshes(body),{key.name:0 for key in keys[1:] if not key.name.startswith('$')})
        set_expression(character=rig.name,expression='smile' if pose=='smile' else 'neutral')
        if pose=='A':_set(_face_meshes(body),{'aa_02':1})
        q=coords(keys[0].data)
        for key in keys[1:]:q+=(coords(key.data)-coords(key.relative_key.data))*key.value
        np.savez(out/f'{pose}.npz',points=q,base=coords(keys[0].data),edges=np.array([e.vertices[:] for e in body.data.edges]))
        result[pose]={str(i):q[i].tolist() for i in (294,455,492,520,540,521,538,7267,7282)}
        for label in ('no_outline','no_ink' if pose=='smile' else 'no_interior'):
            for obj in parts:
                if (obj.get('c3d_toon_lid_ink') and label=='no_ink') or (_role(obj,body)=='mouth' and label=='no_interior'):obj.hide_render=True
            render_style(style='animated_film',outline=False)
            render_preview(camera=cam,engine='eevee',width=384,height=384,filename=str(out/f'{pose}_{label}.png'))
    (out/'probe.json').write_text(json.dumps(result,indent=2));return result


def ray_probe(root_path):
    """Identify actual surfaces at suspect pixels; no material/scene assumptions."""
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from engine.commands.io import open_project
    from engine.commands.materials import _family,_role
    from engine.commands.face import _set,_face_meshes,set_expression
    from engine.commands.camera import camera_shot
    from engine.commands.toon import coords
    open_project(path='round6/after_dark_M.blend');rig,body,parts=_family('Review_rig')
    bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
    camera=camera_shot(subject=[bounds.name],shot='full',angle=35,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
    cam=bpy.data.objects[camera];sc=bpy.context.scene;sc.render.resolution_x=sc.render.resolution_y=384
    for mod in body.modifiers:
        if mod.type=='SUBSURF':mod.levels=mod.render_levels
    report={'parts':[dict(name=o.name,hidden=o.hide_render,part=o.get('c3d_material_part'),materials=[dict(name=s.material.name,role=s.material.get('c3d_toon_role'),alpha=s.material.node_tree.nodes.get('Principled BSDF').inputs['Alpha'].default_value if s.material.node_tree.nodes.get('Principled BSDF') else None) for s in o.material_slots if s.material]) for o in parts]}
    for pose,pixels in [('smile',[(190,244),(195,241),(187,247),(185,252)]),('A',[(150,288),(154,291),(153,300)])]:
        keys=body.data.shape_keys.key_blocks
        _set(_face_meshes(body),{k.name:0 for k in keys[1:] if not k.name.startswith('$')})
        set_expression(character=rig.name,expression='smile' if pose=='smile' else 'neutral')
        if pose=='A':_set(_face_meshes(body),{'aa_02':1})
        bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get()
        trees=[]
        for obj in parts:
            if obj.hide_render:continue
            evaluated=obj.evaluated_get(dg);me=evaluated.to_mesh()
            world=[obj.matrix_world@v.co for v in me.vertices]
            tree=BVHTree.FromPolygons(world,[f.vertices[:] for f in me.polygons])
            trees.append((obj,tree,me,evaluated))
        rows=[];frame=cam.data.view_frame(scene=sc);origin=cam.matrix_world.translation
        for x,y in pixels:
            local=Vector((min(v.x for v in frame)+x/384*(max(v.x for v in frame)-min(v.x for v in frame)),min(v.y for v in frame)+(1-y/384)*(max(v.y for v in frame)-min(v.y for v in frame)),frame[0].z))
            direction=(cam.matrix_world.to_3x3()@local).normalized();hits=[]
            for obj,tree,me,_ in trees:
                hit=tree.ray_cast(origin,direction)
                if hit[0] is not None:
                    face=me.polygons[hit[2]]
                    hits.append(dict(object=obj.name,role=_role(obj,body),distance=hit[3],position=list(hit[0]),normal=list(hit[1]),face=hit[2],material=face.material_index))
            rows.append(dict(pixel=[x,y],hits=sorted(hits,key=lambda a:a['distance'])[:3]))
        for obj,tree,me,evaluated in trees:evaluated.to_mesh_clear()
        report[pose]=rows
    path=Path(root_path)/'diagnostic_mouth/rays.json';path.write_text(json.dumps(report,indent=2));return report


def all_looks(root_path,phase='after'):
    import bpy
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.camera import camera_shot
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render_style import render_style
    from engine.commands.render import render_preview
    from engine.cinematic import PRESETS
    root=Path(root_path);out=root/'looks'/phase;out.mkdir(parents=True,exist_ok=True)
    open_project(path=f'round6/{phase}_dark_M.blend');rig,body,parts=_family('Review_rig')
    bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
    camera=camera_shot(subject=[bounds.name],shot='full',angle=0,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
    source=json.loads((root/phase/'matrix.json').read_text())['cases']
    reference=next(c for c in source if (c['name'],c['angle'],c['look'],c['style'])==('dark_M',0,'studio_film','anime'))
    report=[]
    for look in ('studio',*PRESETS):
        existing=next((c for c in source if (c['name'],c['angle'],c['look'],c['style'])==('dark_M',0,look,'anime')),None)
        if existing:report.append(existing);continue
        cinematic_look(clear=True) if look=='studio' else cinematic_look(preset=look,dof='off')
        render_style(style='anime');path=out/f'{look}.png'
        render_preview(camera=camera,engine='eevee',width=256,height=256,filename=str(path))
        report.append({**reference,'look':look,'path':str(path)})
        (out/'matrix.json').write_text(json.dumps(dict(cases=report),indent=2))
    (out/'matrix.json').write_text(json.dumps(dict(cases=report),indent=2));return dict(cases=len(report))


def hair_reference(root_path):
    """Original albedo/PBR reference for the three audited catalog hairstyles."""
    import bpy
    from toon_round4_fixture import setup
    from engine.commands.materials import _family
    from engine.commands.camera import camera_shot
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render_style import render_style
    from engine.commands.render import render_preview
    from engine.commands.toon import neutral_coords,anatomy
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    out=Path(root_path)/'hair';out.mkdir(parents=True,exist_ok=True);report=[]
    for name,tone,gender,_,hair in [c for c in CASES if c[0] in ('light_F','medium_F','dark_M')]:
        setup(tone,'realistic',hair,gender);rig,body,parts=_family('Review_rig')
        bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
        camera=camera_shot(subject=[bounds.name],shot='full',angle=35,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
        cinematic_look(preset='studio_film',dof='off');render_style(style='none')
        path=out/f'{name}_realistic.png';render_preview(camera=camera,engine='eevee',width=256,height=256,filename=str(path))
        p=neutral_coords(body);_,top,chin,eyes=anatomy(body,parts,p);eye=np.mean(eyes,0);h=top-chin
        site=world_to_camera_view(bpy.context.scene,bpy.data.objects[camera],body.matrix_world@Vector((.07*h,eye[1]+.10*h,eye[2]+.31*h)))
        report.append(dict(name=name,hair=hair,path=str(path),hair_site=[float(site.x*256),float((1-site.y)*256)]))
        (out/'matrix.json').write_text(json.dumps(dict(cases=report),indent=2))
    return dict(cases=len(report))


def shade_probe(root_path):
    import bpy
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.face import set_expression
    from engine.commands.render_style import render_style
    from engine.commands.render import render_preview
    from engine.commands.camera import camera_shot
    from engine.commands.cinematic import cinematic_look
    open_project(path='round6/after_dark_M.blend');rig,body,parts=_family('Review_rig')
    bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
    camera=camera_shot(subject=[bounds.name],shot='full',angle=35,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
    set_expression(character=rig.name,expression='smile');cinematic_look(preset='studio_film',dof='off');render_style(style='animated_film')
    path=Path(root_path)/'diagnostic_mouth/backface_fixed.png'
    render_preview(camera=camera,engine='eevee',width=384,height=384,filename=str(path))
    return dict(path=str(path))
