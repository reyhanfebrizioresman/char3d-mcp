"""Native optical socket visibility and topology/articulation review."""
from pathlib import Path
import json,struct,zlib
import numpy as np


def valid_png(path):
    """Validate native evidence without importing the host-only MCP package."""
    try:
        data=Path(path).read_bytes()
        if data[:8]!=b'\x89PNG\r\n\x1a\n':return False
        offset=8;size=None
        while offset<len(data):
            count=struct.unpack('>I',data[offset:offset+4])[0]
            kind=data[offset+4:offset+8];chunk=data[offset+4:offset+8+count]
            if zlib.crc32(chunk)&0xffffffff!=struct.unpack('>I',data[offset+8+count:offset+12+count])[0]:return False
            if kind==b'IHDR':size=struct.unpack('>II',chunk[4:12])
            offset+=12+count
            if kind==b'IEND':return offset==len(data) and size==(512,512)
    except (OSError,ValueError,struct.error):pass
    return False


def mouth_backfaces(body,part,bounds):
    """Review a closed pocket's folded rim against the actual render surface.

    A concave, two-sided oral lining need not face every review camera. Keep
    this visibility diagnostic separate from the mesh's winding/fold checks.
    """
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from engine.commands.camera import camera_shot
    from engine.commands.toon import coords,neutral_coords,anatomy
    _,top,chin,_=anatomy(body,[body,part]);h=top-chin
    modifiers=[(m,m.levels) for m in body.modifiers if m.type=='SUBSURF']
    try:
        for m,_ in modifiers:m.levels=m.render_levels
        bpy.context.view_layer.update()
        evaluated=body.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
        try:skin=BVHTree.FromPolygons([v.co.copy() for v in mesh.vertices],[list(f.vertices) for f in mesh.polygons])
        finally:evaluated.to_mesh_clear()
    finally:
        for m,levels in modifiers:m.levels=levels
    matrix=np.asarray(body.matrix_world.inverted()@part.matrix_world)
    p=neutral_coords(part)@matrix[:3,:3].T+matrix[:3,3]
    part.data.calc_loop_triangles();tri=np.asarray([list(t.vertices) for t in part.data.loop_triangles])
    cavity=BVHTree.FromPolygons([Vector(v) for v in p],tri.tolist(),all_triangles=True)
    normal=np.cross(p[tri[:,1]]-p[tri[:,0]],p[tri[:,2]]-p[tri[:,0]])
    centers=p[tri].mean(1);rows=[]
    for angle in (0,35,55):
        camera=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
        eye=body.matrix_world.inverted()@bpy.data.objects[camera].matrix_world.translation
        backward=np.flatnonzero((normal*(np.asarray(eye)-centers)).sum(1)<0);visible=[]
        for index in backward:
            for bary in ((1/3,1/3,1/3),(.6,.2,.2),(.2,.6,.2),(.2,.2,.6)):
                target=Vector(np.asarray(bary)@p[tri[index]]);direction=target-eye;distance=direction.length;direction.normalize()
                a=skin.ray_cast(eye,direction,distance+1e-5);b=cavity.ray_cast(eye,direction,distance+1e-5)
                hidden=any(hit[0] is not None and hit[3]<distance-.0001*h for hit in (a,b))
                if not hidden:visible.append(int(index));break
        rows.append(dict(angle=angle,backward_triangles=len(backward),exposed_backward_triangles=visible))
    return rows


def socket_faces(points,faces,posed,h):
    """Label the physical lower socket's inward wall from baseline poses.

    The label is fixed before correction and reused afterwards; changing its
    normal direction cannot make it disappear from the visibility measurement.
    """
    from engine.toon import LID_PAIRS
    p=points;physical=(faces<13380).all(1);keep=np.zeros(len(faces),bool)
    for pairs in LID_PAIRS.values():
        rim=p[np.unique(np.asarray(pairs)[:,1])];order=np.argsort(rim[:,0]);rim=rim[order]
        center=p[faces].mean(1)
        z=np.interp(center[:,0],rim[:,0],rim[:,2]);y=np.interp(center[:,0],rim[:,0],rim[:,1])
        local=physical&(center[:,0]>rim[:,0].min()-.015*h)&(center[:,0]<rim[:,0].max()+.015*h)
        local&=(center[:,2]>z-.14*h)&(center[:,2]<z+.025*h)&(center[:,1]<y+.10*h)&(center[:,1]>y-.06*h)
        reverse=np.zeros(len(faces),bool)
        for q in [p,*posed]:
            normal=np.cross(q[faces[:,1]]-q[faces[:,0]],q[faces[:,2]]-q[faces[:,0]])
            reverse|=normal[:,1]>1e-12
        keep|=local&reverse
    return np.flatnonzero(keep).tolist()


def visibility(body,face_ids,camera,path):
    """Render subdivided wall coverage white, other skin grey, other parts black.

    Uses the same meshes, camera, shape weights and masks as the beauty render.
    Material ownership and face assignments are restored on every exit path.
    """
    import bpy
    from engine.commands import render as rendering
    sc=bpy.context.scene
    colors=[(m,tuple(m.diffuse_color)) for m in bpy.data.materials]
    indices=np.empty(len(body.data.polygons),np.int32);body.data.polygons.foreach_get('material_index',indices)
    mat=bpy.data.materials.new('__round7_socket_id');mat.diffuse_color=(1,1,1,1)
    slot=len(body.data.materials);body.data.materials.append(mat)
    values=np.zeros(len(indices),np.int32);values[face_ids]=slot
    old_setup=rendering._setup_engine;old_world=tuple(sc.world.color)
    view={name:getattr(sc.view_settings,name) for name in ('view_transform','look','exposure','gamma')}
    saved={name:getattr(sc.display.shading,name) for name in ('light','color_type','show_shadows','show_cavity','show_specular_highlight','background_type')}
    def setup(scene,engine):
        old_setup(scene,engine);s=scene.display.shading
        s.light='FLAT';s.color_type='MATERIAL';s.show_shadows=False;s.show_cavity=False
        s.show_specular_highlight=False;s.background_type='WORLD'
    try:
        sc.view_settings.view_transform='Standard';sc.view_settings.look='None';sc.view_settings.exposure=0;sc.view_settings.gamma=1
        for original,_ in colors:original.diffuse_color=(0,0,0,1)
        body.material_slots[0].material.diffuse_color=(.03,.03,.03,1)
        sc.world.color=(0,0,0);body.data.polygons.foreach_set('material_index',values)
        rendering._setup_engine=setup
        rendering.render_preview(camera=camera,engine='workbench',width=512,height=512,filename=str(path))
    finally:
        rendering._setup_engine=old_setup;body.data.polygons.foreach_set('material_index',indices)
        body.data.materials.pop(index=slot);bpy.data.materials.remove(mat)
        for original,color in colors:original.diffuse_color=color
        sc.world.color=old_world
        for name,value in saved.items():setattr(sc.display.shading,name,value)
        for name,value in view.items():setattr(sc.view_settings,name,value)


def gaps(body,points,h):
    from engine.toon import LID_PAIRS
    from engine.commands.toon import LIP_PAIRS
    from engine.commands.toon import neutral_coords
    from engine.commands.toon_refine import _lip_paths
    upper,lower=_lip_paths(neutral_coords(body));q=points
    left=max(q[upper,0].min(),q[lower,0].min());right=min(q[upper,0].max(),q[lower,0].max())
    xx=np.linspace(left,right,61)
    def curve(indices,axis):
        v=q[indices];order=np.argsort(v[:,0]);return np.interp(xx,v[order,0],v[order,axis])
    delta=np.stack([curve(upper,axis)-curve(lower,axis) for axis in (1,2)],axis=1)
    return dict(lip_gap_m=max(abs(float(q[a,2]-q[b,2])) for a,b in LIP_PAIRS),
                full_rim_gap_m=float(np.linalg.norm(delta,axis=1).max()),
                lid_gap_m=max(float(np.linalg.norm(q[a]-q[b])) for pairs in LID_PAIRS.values() for a,b in pairs),
                lid_gaps_by_side_m={side:max(float(np.linalg.norm(q[a]-q[b])) for a,b in pairs) for side,pairs in LID_PAIRS.items()},
                head_height_m=h)


def insert_depths(body,parts,points):
    from engine.commands.toon import coords,neutral_coords
    from engine.commands.toon_refine import _lip_paths
    from engine.commands.materials import _role
    upper,lower=_lip_paths(neutral_coords(body));q=points;report=[]
    def front(indices,x):
        p=q[indices];order=np.argsort(p[:,0]);return np.interp(x,p[order,0],p[order,1])
    for obj in parts:
        if obj.hide_render or _role(obj,body)!='mouth' or not obj.data.shape_keys:continue
        keys=obj.data.shape_keys.key_blocks;p=coords(keys[0].data)
        for key in keys[1:]:p+=(coords(key.data)-coords(key.relative_key.data))*key.value
        matrix=np.asarray(body.matrix_world.inverted()@obj.matrix_world)
        p=p@matrix[:3,:3].T+matrix[:3,3]
        plane=np.minimum(front(upper,p[:,0]),front(lower,p[:,0]))
        report.append(dict(object=obj.name,part=obj.get('c3d_toon_mouth','legacy'),min_lip_plane_depth_m=float((p[:,1]-plane).min())))
    return report
