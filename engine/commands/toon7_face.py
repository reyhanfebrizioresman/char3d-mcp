"""Bounded native expression refinements for stylized MPFB faces only."""
import numpy as np
from ..toon import LID_PAIRS
from ..toon_refine import squint_field
from .toon import neutral_coords,coords,anatomy


def steady_scalp_hair(body,meshes):
    """Scalp cards follow the head bone, not the cheek/eyelid expression warp."""
    from .materials import _role
    from .face import ARKIT,VISEMES
    units=set(ARKIT+VISEMES)
    for obj in meshes:
        if _role(obj,body)!='hair' or not obj.data.shape_keys:continue
        for key in obj.data.shape_keys.key_blocks:
            if key.name in units or key.name.startswith('_c3d_'):
                key.data.foreach_set('co',coords(key.relative_key.data).astype(np.float32).ravel())
        obj.data.update()
        obj['c3d_toon_steady_scalp_hair']=True


def round_neck(body,meshes,style):
    if style not in ('cartoon','chibi') or body.get('c3d_toon_neck_version'):return
    from ..toon import smooth
    from ..toon_refine import round_chin_offset
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,meshes,p);h=top-chin;eye=np.mean(eyes,0)
    edges=np.array([e.vertices[:] for e in body.data.edges]);edges=edges[(edges<13380).all(1)]
    a=np.r_[edges[:,0],edges[:,1]];b=np.r_[edges[:,1],edges[:,0]];degree=np.maximum(1,np.bincount(a,minlength=len(p)))
    u=(p[:,2]-chin)/h
    w=smooth((u+.16)/.12)*(1-smooth((u-.13)/.15))
    w*=1-smooth((p[:,1]-eye[1]-.06*h)/(.18*h));w[13380:]=0
    y=p[:,1].copy()
    for _ in range(10):y+=(np.bincount(a,weights=y[b],minlength=len(p))/degree-y)*(.28*w)
    field=np.zeros_like(p);field[:,1]=np.clip(y-p[:,1],-.025*h,.025*h)
    # A fixed neutral-space offset is added to every target. Fitted parts use
    # the same surface field; no remeshing, bone edits or new skin weights.
    polygons=[list(f.vertices) for f in body.data.polygons if max(f.vertices)<13380]
    tree=BVHTree.FromPolygons([Vector(v) for v in p],polygons)
    for obj in meshes:
        matrix=np.array(body.matrix_world.inverted()@obj.matrix_world);inverse=np.linalg.inv(matrix)
        q=neutral_coords(obj)@matrix[:3,:3].T+matrix[:3,3];offset=round_chin_offset(q,h,chin,eye[1])
        if obj is body:offset+=field
        else:
            ids=np.flatnonzero((q[:,2]>chin-.17*h)&(q[:,2]<chin+.29*h)&(q[:,1]<eye[1]+.24*h))
            for i in ids:
                hit,_,index,distance=tree.find_nearest(Vector(q[i]))
                if hit is None or distance>.04*h:continue
                nearest=min(polygons[index],key=lambda k:float(np.sum((p[k]-hit)**2)))
                offset[i]+=field[nearest]
        local=offset@inverse[:3,:3].T
        for data in [obj.data.vertices]+([k.data for k in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else []):
            data.foreach_set('co',(coords(data)+local).astype(np.float32).ravel())
        obj.data.update()
    body['c3d_toon_neck_version']=1


def polish_squints(body,meshes):
    """Retarget the lower socket as a sliding lid rather than a rolling fold.

    Relative-delta corrective technique: owner-supplied MIT
    blender-agent-skills/blender-facial-shapekeys. No reference script runs.
    """
    if body.get('c3d_toon_socket_version') or not body.data.shape_keys:return
    p=neutral_coords(body);_,top,chin,_=anatomy(body,meshes,p);h=top-chin
    rims=[np.unique(np.array(pairs)[:,1]) for pairs in LID_PAIRS.values()]
    source=body.data.shape_keys.key_blocks
    from .face import ARKIT,VISEMES
    from .materials import _role
    names=[n for n in ARKIT+VISEMES if not n.startswith(('brow','eye')) or n.startswith(('eyeSquint','eyeWide'))]
    for name in names:
        if name not in source:continue
        source_delta=coords(source[name].data)-coords(source[name].relative_key.data)
        motion=[source_delta[indices] for indices in rims]
        for obj in meshes:
            if _role(obj,body)=='eyes':continue  # retain native cornea/iris and gaze geometry
            blocks=obj.data.shape_keys.key_blocks if obj.data.shape_keys else None
            if blocks is None or name not in blocks:continue
            matrix=np.array(body.matrix_world.inverted()@obj.matrix_world);inverse=np.linalg.inv(matrix)
            neutral=neutral_coords(obj);points=neutral@matrix[:3,:3].T+matrix[:3,3]
            relative=coords(blocks[name].relative_key.data);delta=(coords(blocks[name].data)-relative)@matrix[:3,:3].T
            limit=.025 if name.startswith('cheekSquint') else .035 if name.startswith('eyeSquint') else None
            corrected=squint_field(points,delta,h,[p[i] for i in rims],motion,limit=limit)
            blocks[name].data.foreach_set('co',(relative+corrected@inverse[:3,:3].T).astype(np.float32).ravel())
            obj.data.update()
    body['c3d_toon_socket_version']=1


def guard_blinks(body,meshes):
    """Cancel non-squint lid separation only while that eyelid blinks.

    Native per-unit combination correctives extend the existing squint guards.
    Mouth smiles and brow lifts otherwise leave a small opening at blink peak.
    The owner-supplied MIT facial-shapekeys reference motivates this technique.
    """
    import json
    from ..toon import smooth
    if not body.data.shape_keys:return
    p=neutral_coords(body);_,top,chin,_=anatomy(body,meshes,p);h=top-chin
    source=body.data.shape_keys.key_blocks;candidates=[]
    for key in list(source)[1:]:
        if key.name.startswith(('$','_','eyeBlink','eyeLook','eyeSquint','cheekSquint')):continue
        delta=coords(key.data)-coords(key.relative_key.data)
        for side,pairs in LID_PAIRS.items():
            if max(np.linalg.norm(delta[a]-delta[b]) for a,b in pairs)>2e-5:
                candidates.append((key.name,side,pairs))
    for obj in meshes:
        if not obj.data.shape_keys:continue
        blocks=obj.data.shape_keys.key_blocks
        matrix=np.array(body.matrix_world.inverted()@obj.matrix_world)
        q=neutral_coords(obj)@matrix[:3,:3].T+matrix[:3,3]
        for channel,side,pairs in candidates:
            suffix='Left' if side=='L' else 'Right';name='_c3d_lid_guard_'+channel+'_'+suffix
            blink='eyeBlink'+suffix
            if channel not in blocks or blink not in blocks or name in blocks:continue
            rim=p[np.asarray(pairs).ravel()]
            distance=np.sqrt(((q[:,None,[0,2]]-rim[None,:,[0,2]])**2).sum(2)).min(1)/h
            weight=1-smooth((distance-.020)/.12)
            # Separate eye supports keep global brow/cheek units from being
            # cancelled twice near the inner canthi; independent winks work.
            sign=1 if rim[:,0].mean()>0 else -1
            weight*=smooth(q[:,0]*sign/(.025*h))
            delta=coords(blocks[channel].data)-coords(blocks[channel].relative_key.data)
            key=obj.shape_key_add(name=name,from_mix=False);key.relative_key=blocks[0]
            key.data.foreach_set('co',(coords(blocks[0].data)-delta*weight[:,None]).astype(np.float32).ravel())
            driver=key.driver_add('value').driver;driver.type='SCRIPTED'
            driver.expression='min(1,max(0,b))*min(1,max(0,s))'
            for variable,unit in (('b',blink),('s',channel)):
                var=driver.variables.new();var.name=variable;var.type='SINGLE_PROP'
                var.targets[0].id_type='KEY';var.targets[0].id=obj.data.shape_keys
                var.targets[0].data_path='key_blocks['+json.dumps(unit)+'].value'
        obj.data.update()


def calibrate_closed_ink(body,meshes):
    """Keep blink-only lash ribbons on the visible skin, with bounded depth.

    Surface-ray QA technique informed by the owner's MIT asset-QA reference.
    Temporary subdivided surfaces are discarded; Basis and body rims stay put.
    """
    import json,bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    ink=[o for o in meshes if o.get('c3d_toon_lid_ink') and o.data.shape_keys]
    if not ink or not body.data.shape_keys:return
    p=neutral_coords(body);_,top,chin,_=anatomy(body,meshes,p);h=top-chin
    faces=[list(f.vertices) for f in body.data.polygons if max(f.vertices)<13380]
    source_creases=body.data.attributes.get('crease_edge')
    creases={tuple(sorted(e.vertices)):float(source_creases.data[e.index].value) for e in body.data.edges} if source_creases else {}
    for name,sign in (('eyeBlinkLeft',1),('eyeBlinkRight',-1)):
        source=body.data.shape_keys.key_blocks.get(name)
        if source is None:continue
        points=coords(source.data);mesh=bpy.data.meshes.new('__c3d_closed_ink_surface')
        mesh.from_pydata(points.tolist(),[],faces);mesh.update()
        attr=mesh.attributes.new('crease_edge','FLOAT','EDGE')
        attr.data.foreach_set('value',np.array([creases.get(tuple(sorted(e.vertices)),0.) for e in mesh.edges],np.float32))
        obj=bpy.data.objects.new(mesh.name,mesh);bpy.context.scene.collection.objects.link(obj);obj.hide_render=True
        obj.modifiers.new('Render surface','SUBSURF').levels=2
        try:
            evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());surface=evaluated.to_mesh()
            try:tree=BVHTree.FromPolygons([v.co.copy() for v in surface.vertices],[list(f.vertices) for f in surface.polygons])
            finally:evaluated.to_mesh_clear()
            front=float(points[:13380,1].min()-.1*h)
            for part in ink:
                key=part.data.shape_keys.key_blocks.get(name)
                if key is None:continue
                ids=np.asarray(json.loads(part['c3d_toon_sources']),int)
                offsets=np.asarray(json.loads(part['c3d_toon_offsets']))
                q=points[ids].mean(1)+offsets;original=q.copy()
                for i in np.flatnonzero(q[:,0]*sign>0):
                    hit,_,_,_=tree.ray_cast(Vector((q[i,0],front,q[i,2])),Vector((0,1,0)))
                    if hit is not None:q[i,1]-=np.clip(q[i,1]-hit.y+.0015*h,0,.008*h)
                key.data.foreach_set('co',q.astype(np.float32).ravel());part.data.update()
                part['c3d_toon_closed_ink_max_m']=max(float(part.get('c3d_toon_closed_ink_max_m',0)),float(abs(q-original).max()))
        finally:
            bpy.data.objects.remove(obj,do_unlink=True);bpy.data.meshes.remove(mesh)
