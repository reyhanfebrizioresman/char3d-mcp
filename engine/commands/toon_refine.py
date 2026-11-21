"""Native surface/morph refinements. Bone transforms and weights stay authored."""
import json
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from ..toon import LID_PAIRS
from ..toon_refine import profile_displacement,mouth_width_map,aperture_map,harmonic_correction
from .toon import coords,neutral_coords,anatomy,LIP_PAIRS,transform_family
from .materials import _role


def lip_pigment(body, points, head_height):
    """A narrow, native-UV lip seam; it follows every facial target naturally.

    HM08's inner upper/lower lip paths meet at the authored mouth corner.
    Distance is measured in 3D so the oral lining cannot tint nearby nose skin.
    """
    p=np.asarray(points);upper,lower=_lip_paths(p);ids=set(upper+lower)
    rim=p[sorted(ids)]
    distance=np.sqrt(((p[:,None,:]-rim[None,:,:])**2).sum(2)).min(1)
    return np.exp(-.5*(distance/(.006*head_height))**2)


def mouth_lining(body):
    """Retain a dark cavity instead of painting hidden oral walls skin colour.

    The original physical faces keep their vertices, weights and morphs. A
    material boundary is portable to glTF and cannot protrude like an insert.
    """
    import bpy
    p=neutral_coords(body);_,top,chin,_=anatomy(body,[]);h=top-chin
    mouth=p[np.asarray(LIP_PAIRS).ravel()].mean(0)
    faces=[list(f.vertices) for f in body.data.polygons if max(f.vertices)<13380]
    tree=BVHTree.FromPolygons([Vector(v) for v in p],faces)
    front=float(p[:13380,1].min()-.1*h);lining=[]
    for face in body.data.polygons:
        if max(face.vertices)>=13380:continue
        q=p[list(face.vertices)].mean(0)
        if abs(q[0]-mouth[0])>.12*h or abs(q[2]-mouth[2])>.075*h or q[1]>mouth[1]+.20*h:continue
        hit=tree.ray_cast(Vector((q[0],front,q[2])),Vector((0,1,0)))
        if hit[0] is not None and q[1]-hit[0].y>.018*h:lining.append(face.index)
    if not lining:return
    mat=bpy.data.materials.new('c3d_toon.oral_lining');mat.use_nodes=True
    mat['c3d_toon_role']='mouth';mat.diffuse_color=(.018,.006,.009,1)
    bsdf=mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value=mat.diffuse_color;bsdf.inputs['Roughness'].default_value=1.
    body.data.materials.append(mat);index=len(body.material_slots)-1
    for i in lining:body.data.polygons[i].material_index=index
    body['c3d_toon_oral_lining_faces']=lining


def refine_rest(body,meshes,rig=None):
    if body.get('c3d_toon_refined_rest'):return
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,meshes,p);h=top-chin;eye=np.mean(eyes,0)
    mouth=p[[i for pair in LIP_PAIRS for i in pair]].mean(0)
    faces=[list(f.vertices) for f in body.data.polygons if max(f.vertices)<13380]
    tree=BVHTree.FromPolygons([Vector(v) for v in p],faces)
    front=float(p[:13380,1].min()-.1*h)
    # All fitted parts receive the same spatial displacement. Mouth lining,
    # beard and hair card depths remain relative to the original exterior.
    for obj in meshes:
        m=np.array(body.matrix_world.inverted()@obj.matrix_world);inv=np.linalg.inv(m)
        base=neutral_coords(obj);q=base@m[:3,:3].T+m[:3,3];surface=q[:,1].copy()
        selected=(q[:,2]>chin-.04*h)&(q[:,2]<chin+.48*h)&(abs(q[:,0])<.42*h)&(q[:,1]<eye[1]+.20*h)
        for i in np.flatnonzero(selected):
            hit=tree.ray_cast(Vector((q[i,0],front,q[i,2])),Vector((0,1,0)))
            if hit[0] is not None:surface[i]=min(q[i,1],hit[0].y) if obj is body else hit[0].y
        offset=profile_displacement(q,surface,h,chin,float(p[791,1]),float(eye[1]),float(mouth[2]))
        local=offset@inv[:3,:3].T
        for data in [obj.data.vertices]+([k.data for k in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else []):
            data.foreach_set('co',(coords(data)+local).astype(np.float32).ravel())
        obj.data.update()
    transform_family(body,meshes,lambda q:mouth_width_map(q,h,mouth,eye[1]),refit=False)
    p=neutral_coords(body);apertures=[];iris=[]
    for side,pairs in LID_PAIRS.items():
        r=np.array(pairs);low=float(p[r[:,1],2].min());high=float(p[r[:,0],2].max())
        cx=float((p[r.ravel(),0].min()+p[r.ravel(),0].max())*.5);cz=(low+high)*.5
        apertures.append((cx,cz,float(np.ptp(p[r.ravel(),0])),high-low))
        center=min(eyes,key=lambda c:abs(c[0]-cx))
        position=(float(center[2])-low)/max(.0001,high-low)
        iris.append([float(center[0]),float(center[1]),cz if high-low<.105*h or not .35<=position<=.65 else float(center[2])])
    affected=[o for o in meshes if _role(o,body)!='eyes']
    transform_family(body,affected,lambda q:aperture_map(q,h,apertures,float(eye[1])),refit=False)
    body['c3d_toon_iris_centers']=json.dumps(iris)
    body['c3d_toon_refined_rest']=1


def _lip_paths(points):
    # The first shared vertex (501) is the oral canthus. Continuing through
    # 426/423 would paint/deform the outer cheek as a second mouth corner.
    upper=[520,521,522,514,515,470,5362,469,419,417,416,498,499,3734,500,501]
    lower=[540,534,517,487,481,475,476,438,502,503,3705,501]
    def mirror(path):
        reflected=points[path].copy();reflected[:,0]*=-1
        return [int(np.argmin(((points[:13380]-v)**2).sum(1))) for v in reflected]
    return [upper+mirror(upper),lower+mirror(lower)]


def _motion_followers(body,meshes,p,mouth,h,eye_y):
    """Barycentric rest bindings carry mouth corrections to nearby proxies."""
    body.data.calc_loop_triangles()
    triangles=np.array([t.vertices[:] for t in body.data.loop_triangles if max(t.vertices)<13380])
    tree=BVHTree.FromPolygons([Vector(v) for v in p],triangles.tolist(),all_triangles=True)
    followers=[]
    for obj in meshes:
        if obj is body or not obj.data.shape_keys or _role(obj,body)=='mouth':continue
        m=np.array(body.matrix_world.inverted()@obj.matrix_world);inv=np.linalg.inv(m)
        q=neutral_coords(obj)@m[:3,:3].T+m[:3,3]
        candidates=(abs(q[:,0]-mouth[0])<.34*h)&(q[:,2]>mouth[2]-.44*h)&(q[:,2]<mouth[2]+.22*h)&(q[:,1]<eye_y+.27*h)
        indices=[];sources=[];weights=[]
        for i in np.flatnonzero(candidates):
            hit,_,index,distance=tree.find_nearest(Vector(q[i]))
            if hit is None or distance>.08*h:continue
            ids=triangles[index];vertices=p[ids]
            w=np.linalg.lstsq(np.vstack((vertices.T,np.ones(3))),np.r_[hit,1.],rcond=None)[0]
            w=np.maximum(0,w);w/=w.sum()
            indices.append(i);sources.append(ids);weights.append(w)
        if indices:followers.append((obj,np.array(indices),np.array(sources),np.array(weights),inv[:3,:3]))
    return followers


def refine_motion(body,meshes):
    """Pin native mouth rims to round vowel/curved smile targets, then fair deltas.

    Topological diffusion carries the correction through each lip separately;
    a spatial RBF would confuse the coincident upper/lower rims of a closed mouth.
    Relative-key deltas and topology stay native (MIT facial-shapekeys reference).
    """
    if body.get('c3d_toon_refined_motion') or not body.data.shape_keys:return
    from ..toon import smooth
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,meshes,p);h=top-chin;eye=np.mean(eyes,0)
    mouth=p[np.asarray(LIP_PAIRS).ravel()].mean(0);keys=body.data.shape_keys.key_blocks
    upper,lower=_lip_paths(p);controls=np.array(sorted(set(upper+lower)))
    half=max(abs(p[controls,0]-mouth[0]));edges=np.array([e.vertices[:] for e in body.data.edges])
    x=abs(p[:,0]-mouth[0])/h;z=(p[:,2]-mouth[2])/h
    mask=(1-smooth((x-.20)/.12))*smooth((z+.42)/.18)*(1-smooth((z-.08)/.12))
    mask*=1-smooth((p[:,1]-eye[1]-.08*h)/(.18*h));mask[13380:]=0
    followers=_motion_followers(body,meshes,p,mouth,h,eye[1])
    vowels_a={'aa_02','aa_ah_ax_01','ao_03','aw_09','ay_11','jawOpen'}
    vowels_o={'ow_08','oy_10','w_uw_07'}
    for key in keys:
        if key.name not in vowels_a|vowels_o|{'mouthSmileLeft','mouthSmileRight'}:continue
        q=coords(key.data);goals=q.copy()
        for indices,sign in ((upper,1),(lower,-1)):
            ids=np.array(indices);t=np.clip((p[ids,0]-mouth[0])/half,-1,1)
            if key.name in vowels_a|vowels_o:
                is_a=key.name in vowels_a
                width=(.24 if is_a else .16)*h
                height=(.14 if is_a else .10)*h
                center=mouth[2]-(.052 if is_a else .015)*h
                goals[ids,0]=mouth[0]+t*width*.5
                goals[ids,2]=center+sign*height*.5*np.sqrt(np.maximum(0,1-t*t))
            else:
                side=smooth((t*(1 if key.name.endswith('Left') else -1)+.05)/.15)
                goals[ids,0]=p[ids,0]+.06*(p[ids,0]-mouth[0])*side
                goals[ids,2]=p[ids,2]+.045*h*t*t*side
        pinned=goals[controls][:,[0,2]]-q[controls][:,[0,2]]
        correction=harmonic_correction(edges,mask,controls,pinned)
        q[:,[0,2]]+=correction
        key.data.foreach_set('co',q.astype(np.float32).ravel())
        for obj,indices,sources,weights,inverse in followers:
            proxy_key=obj.data.shape_keys.key_blocks.get(key.name)
            if proxy_key is None:continue
            offset=np.zeros((len(indices),3));offset[:,[0,2]]=(correction[sources]*weights[:,:,None]).sum(1)
            values=coords(proxy_key.data);values[indices]+=offset@inverse.T
            proxy_key.data.foreach_set('co',values.astype(np.float32).ravel())
    for obj,*_ in followers:obj.data.update()
    body.data.update();body['c3d_toon_refined_motion']=2


def refine_hair_roots(body,meshes):
    """Smooth only close, frontal card boundaries; keep authored clump volume.

    Soft root/density boundary technique: MIT blender-agent-skills/
    blender-hair-grooming. No curves/groom scripts or new assets are required.
    """
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,meshes,p);h=top-chin;eye=np.mean(eyes,0)
    tree=BVHTree.FromPolygons([Vector(v) for v in p],[list(f.vertices) for f in body.data.polygons if max(f.vertices)<13380])
    for obj in meshes:
        if _role(obj,body)!='hair':continue
        m=np.array(body.matrix_world.inverted()@obj.matrix_world);inv=np.linalg.inv(m)
        original=coords(obj.data.shape_keys.key_blocks[0].data if obj.data.shape_keys else obj.data.vertices)
        q=original@m[:3,:3].T+m[:3,3]
        counts={}
        for f in obj.data.polygons:
            ids=list(f.vertices)
            for i,j in zip(ids,ids[1:]+ids[:1]):
                edge=tuple(sorted((i,j)));counts[edge]=counts.get(edge,0)+1
        edges=np.array([e for e,n in counts.items() if n==1],int)
        if not len(edges):continue
        a,b=np.r_[edges[:,0],edges[:,1]],np.r_[edges[:,1],edges[:,0]]
        degree=np.bincount(a,minlength=len(q));weight=np.zeros(len(q))
        for i in np.flatnonzero(degree):
            if not (eye[2]+.10*h<q[i,2]<eye[2]+.44*h and q[i,1]<eye[1]+.08*h):continue
            hit=tree.find_nearest(Vector(q[i]))
            if hit[0] is not None and hit[3]<.045*h:weight[i]=1.
        smooth_q=q.copy()
        for _ in range(4):
            sums=np.zeros_like(q);np.add.at(sums,a,smooth_q[b]);mean=sums/np.maximum(1,degree[:,None])
            smooth_q+=(mean-smooth_q)*(.40*weight[:,None])
        delta=(smooth_q-q)@inv[:3,:3].T
        selected=weight>0
        obj['c3d_toon_root_vertices']=int(selected.sum())
        obj['c3d_toon_root_max_delta_m']=float(np.linalg.norm(smooth_q-q,axis=1).max())
        if selected.any():
            def roughness(points):
                sums=np.zeros_like(points);np.add.at(sums,a,points[b])
                mean=sums/np.maximum(1,degree[:,None])
                return float(np.linalg.norm(points[selected]-mean[selected],axis=1).mean()/h)
            obj['c3d_toon_root_roughness_before']=roughness(q)
            obj['c3d_toon_root_roughness_after']=roughness(smooth_q)
        for data in [obj.data.vertices]+([k.data for k in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else []):data.foreach_set('co',(coords(data)+delta).astype(np.float32).ravel())
        obj.data.update()


def close_full_rim(body,meshes):
    """Close the actual oral contour as well as the legacy central M/B/P probes."""
    keys=body.data.shape_keys.key_blocks if body.data.shape_keys else None
    if keys is None or 'p_b_m_21' not in keys or 'mouthClose' not in keys:return
    from ..toon import smooth
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,meshes,p);h=top-chin;eye=np.mean(eyes,0)
    mouth=p[np.asarray(LIP_PAIRS).ravel()].mean(0);upper,lower=_lip_paths(p)
    target=coords(keys['p_b_m_21'].data)
    mix=target+.1*(coords(keys['mouthClose'].data)-coords(keys['mouthClose'].relative_key.data))
    goals=mix.copy()
    corners=[min(upper,key=lambda i:mix[i,0]),520,max(upper,key=lambda i:mix[i,0])]
    values=mix[corners];contour=np.array(sorted(set(upper+lower)))
    # Both differently sampled rim polylines share the same piecewise-linear
    # contact curve. Fitting only the lower rim to every upper vertex can leave
    # small gaps between their unequal vertex rows.
    for axis in (1,2):goals[contour,axis]=np.interp(mix[contour,0],values[:,0],values[:,axis])
    for a,b in LIP_PAIRS:goals[b,1:]=goals[a,1:]
    controls=np.array(sorted(set(upper+lower+[i for pair in LIP_PAIRS for i in pair])))
    x=abs(p[:,0]-mouth[0])/h;z=(p[:,2]-mouth[2])/h
    mask=(1-smooth((x-.20)/.12))*smooth((z+.42)/.18)*(1-smooth((z-.08)/.12))
    mask*=1-smooth((p[:,1]-eye[1]-.08*h)/(.18*h));mask[13380:]=0
    field=harmonic_correction(np.array([e.vertices[:] for e in body.data.edges]),mask,controls,goals[controls]-mix[controls])
    keys['p_b_m_21'].data.foreach_set('co',(target+field).astype(np.float32).ravel())
    for obj,indices,sources,weights,inverse in _motion_followers(body,meshes,p,mouth,h,eye[1]):
        key=obj.data.shape_keys.key_blocks.get('p_b_m_21')
        if key is None:continue
        q=coords(key.data);q[indices]+=(field[sources]*weights[:,:,None]).sum(1)@inverse.T
        key.data.foreach_set('co',q.astype(np.float32).ravel());obj.data.update()
    body.data.update()


def blink_correctives(body,meshes):
    """Native combination correctives keep closed lids closed during squints.

    Relative deltas and simple native drivers implement the jaw/lid combination
    principle in the owner's MIT blender-facial-shapekeys reference. They save
    in .blend; glTF animations sample the driven morph weights.
    """
    p=neutral_coords(body);_,top,chin,_=anatomy(body,meshes,p);h=top-chin
    from ..toon import smooth
    for obj in meshes:
        if not obj.data.shape_keys:continue
        blocks=obj.data.shape_keys.key_blocks
        m=np.array(body.matrix_world.inverted()@obj.matrix_world)
        q=neutral_coords(obj)@m[:3,:3].T+m[:3,3]
        for side,pairs in LID_PAIRS.items():
            suffix='Left' if side=='L' else 'Right';blink='eyeBlink'+suffix
            if blink not in blocks:continue
            rim=p[np.asarray(pairs).ravel()]
            distance=np.sqrt(((q[:,None,[0,2]]-rim[None,:,[0,2]])**2).sum(2)).min(1)/h
            weight=1-smooth((distance-.020)/.12)
            for source in ('eyeSquint'+suffix,'cheekSquint'+suffix):
                if source not in blocks:continue
                name='_c3d_closed_'+source
                if name in blocks:continue
                key=obj.shape_key_add(name=name,from_mix=False);key.relative_key=blocks[0]
                delta=coords(blocks[source].data)-coords(blocks[source].relative_key.data)
                key.data.foreach_set('co',(coords(blocks[0].data)-delta*weight[:,None]).astype(np.float32).ravel())
                driver=key.driver_add('value').driver;driver.type='SCRIPTED'
                driver.expression='min(1,max(0,b))*min(1,max(0,s))'
                for variable,channel in (('b',blink),('s',source)):
                    var=driver.variables.new();var.name=variable;var.type='SINGLE_PROP'
                    var.targets[0].id_type='KEY';var.targets[0].id=obj.data.shape_keys
                    var.targets[0].data_path='key_blocks['+json.dumps(channel)+'].value'
        obj.data.update()
