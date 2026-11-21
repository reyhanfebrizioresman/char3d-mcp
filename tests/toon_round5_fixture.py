"""Owned synthetic faces, through MCP only; no optional assets or network."""
from pathlib import Path
import json
import numpy as np


def surface(body, parts, camera, path):
    import bpy
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    from engine.commands.toon import neutral_coords,anatomy
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,parts,p);h=top-chin
    eye=np.mean(eyes,0);mouth=p[[520,540,7267,7282]].mean(0)
    # Sidewall below the nose, excluding nostril/lip edges and cheek silhouette.
    front=p[:,1]<eye[1]+.015*h
    groove=front&(abs(p[:,0])>.035*h)&(abs(p[:,0])<.18*h)&(p[:,2]>mouth[2]+.025*h)&(p[:,2]<eye[2]-.065*h)
    cheek=front&(abs(p[:,0])>.22*h)&(abs(p[:,0])<.31*h)&(p[:,2]>mouth[2]+.025*h)&(p[:,2]<eye[2]-.065*h)
    nose=front&(abs(p[:,0])<.07*h)&(p[:,2]>mouth[2]+.06*h)&(p[:,2]<eye[2]-.03*h)
    bridge=front&(abs(p[:,0])<.04*h)&(p[:,2]>p[294,2]+.045*h)&(p[:,2]<eye[2]+.08*h)
    for region in (groove,cheek,nose,bridge):region[13380:]=False
    # Exclude masked MPFB helper surfaces sharing the projected face area.
    attr=body.data.attributes.new('__round5_index','INT','POINT')
    attr.data.foreach_set('value',np.arange(len(p),dtype=np.int32))
    try:
        bpy.context.view_layer.update()
        ev=body.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh()
        indices=np.array([v.value for v in me.attributes[attr.name].data],int)
        normals=np.zeros_like(p);normals[indices]=np.array([v.normal[:] for v in me.vertices])
        triangles=[list(f.vertices) for f in me.polygons]
        vertices=[v.co.copy() for v in me.vertices]
        visible=np.zeros(len(p),bool);visible[indices]=True
        ev.to_mesh_clear()
    finally:body.data.attributes.remove(attr)
    for region in (groove,cheek,nose,bridge):region&=visible
    from mathutils.bvhtree import BVHTree
    tree=BVHTree.FromPolygons(vertices,triangles)
    # Projected diagnostics use the exterior surface seen by this camera, not
    # the folded nostril lining or the back of the closed oral cavity.
    origin=body.matrix_world.inverted()@bpy.data.objects[camera].matrix_world.translation
    camera_visible=np.zeros(len(p),bool)
    for i in np.flatnonzero(groove|cheek|nose|bridge):
        ray=Vector(p[i])-origin;distance=ray.length
        hit=tree.ray_cast(origin,ray.normalized(),distance+h*.003)
        camera_visible[i]=hit[0] is not None and abs(hit[3]-distance)<h*.003
    for region in (groove,cheek,nose,bridge):region&=camera_visible
    occlusion=np.full(len(p),np.nan)
    for region in (groove,cheek,nose,bridge):
        ids=np.flatnonzero(region);ids=ids[::max(1,len(ids)//64)]
        for i in ids:
            normal=Vector(normals[i]).normalized();tangent=normal.orthogonal().normalized();bitangent=normal.cross(tangent)
            hits=0
            for j in range(24):
                theta=j*2.399963229728653;radius=np.sqrt((j+.5)/24)
                direction=(normal*np.sqrt(1-radius*radius)+tangent*(radius*np.cos(theta))+bitangent*(radius*np.sin(theta)))
                origin=Vector(p[i])+normal*(h*.0005)
                hit=tree.ray_cast(origin,direction,h*.08);hits+=int(hit[0] is not None)
            occlusion[i]=hits/24
    edges=np.array([e.vertices[:] for e in body.data.edges]);edges=edges[(edges<13380).all(1)&visible[edges].all(1)]
    a,b=np.r_[edges[:,0],edges[:,1]],np.r_[edges[:,1],edges[:,0]]
    degree=np.maximum(1,np.bincount(a,minlength=len(p)))
    mean=np.zeros_like(p);np.add.at(mean,a,p[b]);mean/=degree[:,None]
    concavity=np.sum((mean-p)*normals,axis=1)/h
    angle=np.arccos(np.clip(np.sum(normals[a]*normals[b],axis=1),-1,1))
    deviation=np.bincount(a,weights=angle,minlength=len(p))/degree
    cam=bpy.data.objects[camera];sc=bpy.context.scene
    uv=np.array([[q.x*512,(1-q.y)*512] for q in (world_to_camera_view(sc,cam,body.matrix_world@Vector(v)) for v in p)])
    np.savez(path,points=p,normals=normals,edges=edges,groove=groove,cheek=cheek,nose=nose,bridge=bridge,pixels=uv,concavity=concavity,normal_deviation=deviation,head_height=h,occlusion=occlusion,visible=visible)
    return {name:dict(vertices=int(mask.sum()),local_AO_fraction=float(np.nanmean(occlusion[mask])),normal_deviation_deg=float(np.degrees(deviation[mask]).mean()),concave_depth_mean_head=float(np.maximum(0,concavity[mask]).mean()),concave_depth_p90_head=float(np.percentile(np.maximum(0,concavity[mask]),90))) for name,mask in (('groove',groove),('cheek',cheek),('nose',nose),('bridge',bridge))}


def run(root_path,phase='before',tones=('light','medium','dark'),genders=(0,1),pilot=False,angles=None):
    import bpy
    from toon_round4_fixture import setup,portrait_bounds
    from engine.commands.materials import _family
    from engine.commands.camera import camera_shot
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render_style import render_style
    from engine.commands.render import render_preview
    from engine.commands.io import save_project,open_project
    out=Path(root_path)/phase;out.mkdir(parents=True,exist_ok=True)
    report_path=out/'matrix.json';report=json.loads(report_path.read_text()) if report_path.exists() else dict(cases=[])
    for tone in tones:
        for gender in genders:
            tag=f'{tone}_{"F" if gender==0 else "M"}'
            if phase=='before':
                # Reproduce ab28f51's geometry after this correction is merged.
                from engine.commands import toon
                original=toon.soften_midface;motion=toon.soften_face_motion
                toon.soften_midface=toon.soften_face_motion=lambda body:None
                try:built,camera=setup(tone,style='anime',hair='short02',gender=gender)
                finally:toon.soften_midface=original;toon.soften_face_motion=motion
                cinematic_look(preset='studio_film',dof='off');render_style(style='animated_film')
                save_project(path=f'round5/{tag}.blend')
            else:
                open_project(path=f'round5/{tag}.blend');built={}
                rig,body,parts=_family('Review_rig');correct(body,parts)
            rig,body,parts=_family('Review_rig')
            bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
            for angle in (angles if angles is not None else (25,) if pilot else (0,25)):
                view='front' if angle==0 else 'three_quarter'
                shot=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)
                camera=shot['camera'];path=out/f'{tag}_{view}.png';npz=out/f'{tag}_{view}.npz'
                measured=surface(body,parts,camera,npz)
                render_preview(camera=camera,engine='eevee',width=512,height=512,filename=str(path))
                record=dict(tone=tone,gender=gender,view=view,path=str(path),surface=str(npz),geometry=measured,build=built,
                            correction=dict(rest=body.get('c3d_toon_midface_version'),motion=body.get('c3d_toon_motion_version')))
                report['cases']=[c for c in report['cases'] if (c['tone'],c['gender'],c['view'])!=(tone,gender,view)]
                report['cases'].append(record);report_path.write_text(json.dumps(report,indent=2))
    return report


def ablation(root_path):
    """Remove only individual temporary AF shader contributions on one saved mesh."""
    import bpy
    from engine.commands.io import open_project
    from engine.commands.render import render_preview
    from engine.commands import render_style as styles
    out=Path(root_path)/'diagnosis';out.mkdir(parents=True,exist_ok=True)
    open_project(path='round5/dark_F.blend');original=styles._animated_shader
    results=[]
    for case in ('default','no_AO','no_form','no_AO_form','normal','AO'):
        def shader(tree,bsdf,cfg,name,engine):
            result=original(tree,bsdf,cfg,name,engine)
            if cfg.get('_toon_skin'):
                for node in list(tree.nodes):
                    if node.type=='MIX_RGB' and node.blend_type=='MULTIPLY':
                        fac=node.inputs[0].default_value
                        if ('AO' in case and case!='AO' and abs(fac-.10)<1e-5) or ('form' in case and abs(fac-.20)<1e-5):node.inputs[0].default_value=0
                if case in ('normal','AO'):
                    for node in list(tree.nodes):
                        if node.type=='OUTPUT_AOV':tree.nodes.remove(node)
                    emission=tree.nodes.new('ShaderNodeEmission')
                    if case=='AO':
                        ao=next(n for n in tree.nodes if n.type=='AMBIENT_OCCLUSION');tree.links.new(ao.outputs['AO'],emission.inputs['Color'])
                    else:
                        geom=tree.nodes.new('ShaderNodeNewGeometry');normal=tree.nodes.new('ShaderNodeVectorMath');normal.operation='MULTIPLY_ADD'
                        tree.links.new(geom.outputs['Normal'],normal.inputs[0]);normal.inputs[1].default_value=(.5,.5,.5);normal.inputs[2].default_value=(.5,.5,.5)
                        tree.links.new(normal.outputs[0],emission.inputs['Color'])
                    return emission.outputs[0]
            return result
        styles._animated_shader=shader
        try:
            path=out/f'{case}.png';render_preview(camera='Shot1',engine='eevee',width=512,height=512,filename=str(path));results.append(str(path))
        finally:styles._animated_shader=original
    return results


def articulation(root_path,only=None):
    import bpy
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.toon import soften_midface,coords,LIP_PAIRS,face_metrics
    from engine.commands.face import _set,_face_meshes,set_expression
    from engine.toon import LID_PAIRS
    from engine.commands.render import render_preview
    out=Path(root_path)/'articulation';out.mkdir(parents=True,exist_ok=True)
    open_project(path='round5/dark_F.blend');rig,body,parts=_family('Review_rig')
    keys=body.data.shape_keys.key_blocks;basis=coords(keys[0].data)
    deltas={key.name:coords(key.data)-coords(key.relative_key.data) for key in keys[1:]}
    correct(body,parts)
    error=max(float(abs((coords(key.data)-coords(key.relative_key.data)-deltas[key.name])[:,[0,2]]).max()) for key in keys[1:] if key.name not in ('mouthSmileLeft','mouthSmileRight'))
    eye_error=max(float(abs(coords(key.data)-coords(key.relative_key.data)-deltas[key.name]).max()) for key in keys[1:] if key.name.startswith(('eye','brow')))
    report=dict(relative_morph_XZ_error_m=error,eye_brow_delta_error_m=eye_error,measurements=face_metrics(body,parts),states=[])
    assert error<.000001,error
    assert eye_error<.000001,eye_error
    for name,expression,units in (('neutral','neutral',{}),('smile','smile',{}),('A','neutral',{'aa_02':1}),('O','neutral',{'ow_08':1}),('M','neutral',{'p_b_m_21':1,'mouthClose':.1}),('B','neutral',{'p_b_m_21':1,'mouthClose':.1}),('P','neutral',{'p_b_m_21':1,'mouthClose':.1}),('blink','neutral',{'eyeBlinkLeft':1,'eyeBlinkRight':1})):
        _set(_face_meshes(body),{key.name:0 for key in keys[1:] if not key.name.startswith('$')})
        set_expression(character=rig.name,expression=expression);_set(_face_meshes(body),units)
        q=coords(keys[0].data)
        for key in keys[1:]:q+=(coords(key.data)-coords(key.relative_key.data))*key.value
        lip=max(abs(float(q[a,2]-q[b,2])) for a,b in LIP_PAIRS)
        record=dict(name=name,lip_gap_m=lip,
                    lip_gap3d_m=max(float(np.linalg.norm(q[a]-q[b])) for a,b in LIP_PAIRS))
        if name in ('A','O'):assert lip>.001,record
        if name in ('M','B','P'):assert lip<.001 and record['lip_gap3d_m']<.001,record
        if name=='blink':
            gap=max(float(np.linalg.norm(q[a]-q[b])) for pairs in LID_PAIRS.values() for a,b in pairs)
            record['lid_gap3d_m']=gap;assert gap<.0001,record
        path=out/f'{"M" if name in ("B","P") else name}.png'
        if name not in ('B','P') and (only is None or name==only):render_preview(camera='Shot1',engine='eevee',width=512,height=512,filename=str(path))
        assert path.exists(),path
        np.savez(out/f'{name}.npz',points=q)
        record['path']=str(path);report['states'].append(record)
        (out/'metrics.json').write_text(json.dumps(report,indent=2))
    return report


def refresh_geometry(root_path):
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.camera import camera_shot
    out=Path(root_path)/'before';path=out/'matrix.json';report=json.loads(path.read_text())
    for tone in ('light','medium','dark'):
        for gender in (0,1):
            tag=f'{tone}_{"F" if gender==0 else "M"}';open_project(path=f'round5/{tag}.blend')
            import bpy
            rig,body,parts=_family('Review_rig');bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
            for angle in (0,25):
                view='front' if angle==0 else 'three_quarter'
                shot=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)
                case=next(c for c in report['cases'] if (c['tone'],c['gender'],c['view'])==(tone,gender,view))
                case['geometry']=surface(body,parts,shot['camera'],case['surface'])
    path.write_text(json.dumps(report,indent=2));return report


def correct(body,parts):
    """Replay on ab28 snapshots, shifting already-fitted interiors without shrink."""
    from engine.commands.toon import soften_midface,soften_face_motion,coords,LIP_PAIRS
    from engine.commands.materials import _role
    keys=body.data.shape_keys.key_blocks;lips=[i for pair in LIP_PAIRS for i in pair]
    old={key.name:float(coords(key.data)[lips,1].max()) for key in keys}
    soften_midface(body);soften_face_motion(body)
    shifts={key.name:float(coords(key.data)[lips,1].max())-old[key.name] for key in keys}
    for obj in parts:
        if _role(obj,body)!='mouth':continue
        m=np.array(body.matrix_world.inverted()@obj.matrix_world);inv=np.linalg.inv(m)
        blocks=[(obj.data.vertices,keys[0].name)]+([(k.data,k.name) for k in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else [])
        for data,name in blocks:
            q=coords(data)@m[:3,:3].T+m[:3,3];q[:,1]+=shifts.get(name,shifts[keys[0].name])
            data.foreach_set('co',(q@inv[:3,:3].T+inv[:3,3]).astype(np.float32).ravel())
    from engine.commands.toon import sync_ink
    sync_ink(body,parts)


def style_identity(root_path):
    import hashlib
    from engine.commands.io import open_project
    from engine.commands.materials import _family
    from engine.commands.toon import neutral_coords
    from engine.commands.render_style import render_style
    from engine.commands.render import render_preview
    out=Path(root_path)/'diagnosis';out.mkdir(parents=True,exist_ok=True)
    open_project(path='round5/dark_F.blend');rig,body,parts=_family('Review_rig')
    before=neutral_coords(body).copy();digest=lambda:hashlib.sha256(neutral_coords(body).tobytes()).hexdigest()
    old=digest();render_style(style='anime')
    path=out/'anime.png';render_preview(camera='Shot1',engine='eevee',width=512,height=512,filename=str(path))
    assert np.array_equal(before,neutral_coords(body))
    result=dict(anime_mesh_sha256=digest(),animated_film_mesh_sha256=old,geometry_identical=True,path=str(path))
    (out/'style_identity.json').write_text(json.dumps(result,indent=2));return result
