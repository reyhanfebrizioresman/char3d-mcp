"""Fixed-ROI native-render measurements; numpy/PyAV, no extra dependencies."""
from collections import deque
from pathlib import Path
import colorsys
import json
from functools import lru_cache
import numpy as np
from toon_polish import read,save
from toon_round4b import board
from engine.toon_refine import projected_concavity


def components(mask):
    seen=np.zeros_like(mask,bool);result=[]
    height,width=mask.shape
    for y,x in zip(*np.nonzero(mask)):
        if seen[y,x]:continue
        queue=deque([(y,x)]);seen[y,x]=True;points=[]
        while queue:
            j,i=queue.popleft();points.append((j,i))
            for jj,ii in ((j-1,i),(j+1,i),(j,i-1),(j,i+1)):
                if 0<=jj<height and 0<=ii<width and mask[jj,ii] and not seen[jj,ii]:
                    seen[jj,ii]=True;queue.append((jj,ii))
        result.append(np.asarray(points))
    return result


def polygon_mask(shape,vertices):
    y,x=np.indices(shape);p=np.asarray(vertices);inside=np.zeros(shape,bool)
    for a,b in zip(p,np.roll(p,-1,axis=0)):
        if abs(b[1]-a[1])<1e-9:continue
        inside^=((a[1]>y)!=(b[1]>y))&(x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])
    return inside


@lru_cache(maxsize=64)
def native_camera(root_path,phase,name,angle):
    """Recover the native perspective projection; verify an independent point."""
    from engine.toon import LID_PAIRS
    root=Path(root_path)
    data=np.load(root/phase/f'{name}_mesh.npz');p=data['points'];h=float(data['head_height']);chin=float(data['chin'])
    origin=data['eyes'].mean(0);normalized=(p-origin)/h
    native=json.loads((root/'projections'/f'{phase}_{name}.json').read_text())[str(angle)]
    points=np.concatenate([normalized[np.asarray(pairs).ravel()] for pairs in LID_PAIRS.values()])
    points=np.c_[points,np.ones(len(points))];uv=np.concatenate(native['eye_rims'])
    system=[];values=[]
    for v,w in zip(points,uv):
        system.extend((np.r_[v,np.zeros(4),-w[0]*v[:3]],np.r_[np.zeros(4),v,-w[1]*v[:3]]));values.extend(w)
    solution,_,rank,_=np.linalg.lstsq(system,values,rcond=None)
    assert rank==11,(phase,name,angle,rank)
    projection=np.r_[solution,1.].reshape(3,4)
    projected=np.c_[normalized,np.ones(len(p))]@projection.T;projected=projected[:,:2]/projected[:,2,None]
    assert abs(projected[294]-native['nose']).max()<.001,(phase,name,angle)
    return projection,origin,h


@lru_cache(maxsize=64)
def native_projection(root_path,phase,name,angle):
    p=np.load(Path(root_path)/phase/f'{name}_mesh.npz')['points']
    projection,origin,h=native_camera(root_path,phase,name,angle)
    points=np.c_[(p-origin)/h,np.ones(len(p))]@projection.T
    return points[:,:2]/points[:,2,None]


@lru_cache(maxsize=64)
def skin_interior(root_path,phase,name,angle,shape):
    """Conservative physical-head silhouette, using the validated native camera.

    Retracting the muzzle moves its silhouette inside the old planar ROI at
    oblique views. Do not count that new skin/background edge as a cel shadow.
    Intersect projected physical mesh edges with each image row. Both builds'
    interiors are intersected below: the comparison uses one identical mask.
    """
    data=np.load(Path(root_path)/phase/f'{name}_mesh.npz');p=data['points'];h=float(data['head_height']);chin=float(data['chin'])
    projected=native_projection(root_path,phase,name,angle)
    edges=data['edges'];edges=edges[(edges<13380).all(1)]
    edges=edges[(p[edges,2]>chin-.10*h).all(1)]
    segments=projected[edges];height,width=shape;mask=np.zeros(shape,bool);xx=np.arange(width)
    for y in range(height):
        active=(segments[:,:,1].min(1)<=y)&(segments[:,:,1].max(1)>y)
        lines=segments[active]
        if not len(lines):continue
        fraction=(y-lines[:,0,1])/(lines[:,1,1]-lines[:,0,1])
        xs=lines[:,0,0]+fraction*(lines[:,1,0]-lines[:,0,0])
        mask[y]=(xx>=xs.min()+2)&(xx<=xs.max()-2)
    return mask


def face_mask(case,shape):
    """Fixed baseline cheek/nose mask minus both builds' projected eye sockets."""
    root=next(p for p in Path(case['path']).parents if (p/'before'/f"{case['name']}_mesh.npz").exists())
    return _face_mask(str(root),case['name'],case['angle'],shape,tuple(map(tuple,case['face_polygon'])))


@lru_cache(maxsize=64)
def _face_mask(root_path,name,angle,shape,face_polygon):
    from engine.toon import LID_PAIRS
    polygon=np.asarray(face_polygon,float);root=Path(root_path)
    with np.load(root/'before'/f'{name}_mesh.npz') as source:
        p=source['points'];h=float(source['head_height']);chin=float(source['chin']);eye=source['eyes'].mean(0)
        low=float(p[[520,540,521,538,7267,7282],2].mean()-chin)/h+.07
        high=float((eye[2]-chin)/h-.075)
    plane=np.array([[-.23,low],[.23,low],[.23,high],[-.23,high]])
    system=[];values=[]
    for (x,z),(u,v) in zip(plane,polygon):
        system.extend(([x,z,1,0,0,0,-u*x,-u*z],[0,0,0,x,z,1,-v*x,-v*z]));values.extend((u,v))
    transform=np.r_[np.linalg.solve(system,values),1.].reshape(3,3)
    # Cover cheeks down to the lower jaw, rather than only the narrow strip
    # below the eyes. Keep actual eye/mouth features out of the shadow metric.
    face=np.array([[-.26,.10],[.26,.10],[.26,high],[-.26,high]])
    face=np.c_[face,np.ones(len(face))]@transform.T
    broad=polygon_mask(shape,face[:,:2]/face[:,2,None])
    yy,xx=np.indices(shape);exclude=np.zeros(shape,bool)
    # This union is shared by before/after, so opening a sleepy eye cannot be
    # penalized as an extra cel shadow. Include the socket wall under the rim.
    for phase in ('before','after'):
        native=root/'projections'/f'{phase}_{name}.json'
        if native.exists():
            rims=json.loads(native.read_text())[str(angle)]['eye_rims']
            for projected in rims:
                uv=np.asarray(projected);lo=uv.min(0)-[3,3];hi=uv.max(0)+[3,8]
                exclude|=(xx>=lo[0])&(xx<=hi[0])&(yy>=lo[1])&(yy<=hi[1])
            with np.load(root/phase/f'{name}_mesh.npz') as data:
                p=data['points'];ids=[520,521,522,514,515,470,5362,469,419,417,416,498,499,3734,500,501,540,534,517,487,481,475,476,438,502,503,3705]
                mirrored=p[ids].copy();mirrored[:,0]*=-1
                ids+=np.argmin(((p[:13380,None,:]-mirrored[None,:,:])**2).sum(2),axis=0).tolist()
                uv=native_projection(str(root),phase,name,angle)[ids]
                lo=uv.min(0)-2;hi=uv.max(0)+2
                exclude|=(xx>=lo[0])&(xx<=hi[0])&(yy>=lo[1])&(yy<=hi[1])
        else:
            with np.load(root/phase/f'{name}_mesh.npz') as data:
                points=data['points']
                for pairs in LID_PAIRS.values():
                    rim=points[np.asarray(pairs).ravel()]
                    uv=np.c_[rim[:,0]/h,(rim[:,2]-chin)/h,np.ones(len(rim))]@transform.T
                    uv=uv[:,:2]/uv[:,2,None];lo=uv.min(0)-[3,3];hi=uv.max(0)+[3,8]
                    exclude|=(xx>=lo[0])&(xx<=hi[0])&(yy>=lo[1])&(yy<=hi[1])
    interior=np.ones(shape,bool)
    if all((root/'projections'/f'{phase}_{name}.json').exists() for phase in ('before','after')):
        for phase in ('before','after'):
            interior&=skin_interior(str(root),phase,name,angle,shape)
    return broad&~exclude&interior,broad


def patches(case,reference=None):
    pixels=read(Path(case['path']))/255;y=pixels@[.2126,.7152,.0722]
    mask,broad=face_mask(reference or case,y.shape)
    median=float(np.median(y[mask]));threshold=median*.88
    regions=components(mask&(y<threshold));sizes=[len(r) for r in regions]
    gradient=np.zeros_like(y)
    dx=abs(np.diff(y,axis=1))*(mask[:,1:]&mask[:,:-1]);dy=abs(np.diff(y,axis=0))*(mask[1:]&mask[:-1])
    gradient[:,1:]=np.maximum(gradient[:,1:],dx);gradient[:,:-1]=np.maximum(gradient[:,:-1],dx)
    gradient[1:]=np.maximum(gradient[1:],dy);gradient[:-1]=np.maximum(gradient[:-1],dy)
    def density(area):
        horizontal=area[:,1:]&area[:,:-1];vertical=area[1:]&area[:-1]
        edges=int(((abs(np.diff(y,axis=1))>.045)&horizontal).sum()+((abs(np.diff(y,axis=0))>.045)&vertical).sum())
        return edges/max(1,int(horizontal.sum()+vertical.sum()))
    return dict(patch_count=sum(s>=4 for s in sizes),hard_patch_count=sum(len(r)>=4 and bool((gradient[r[:,0],r[:,1]]>.045).any()) for r in regions),speck_count=sum(1<=s<=6 for s in sizes),
                edge_density=density(mask),raw_edge_density_including_features=density(broad),
                shadow_fraction=float((mask&(y<threshold)).sum()/max(1,mask.sum())),
                median_Yprime=median,roi_pixels=int(mask.sum()),feature_excluded_pixels=int((broad&~mask).sum()))


def aperture(state):
    pixels=read(Path(state['path']))/255;y=pixels@[.2126,.7152,.0722]
    x,z=np.rint(state['mouth_center_px']).astype(int);h=state['head_height_px']
    yy,xx=np.indices(y.shape);roi=(abs(xx-x)<.135*h)&(abs(yy-z)<.10*h)
    skin=(abs(xx-x)<.17*h)&(abs(yy-z)<.13*h)&~roi
    threshold=float(np.median(y[skin]))*.50
    regions=components(roi&(y<threshold));regions=[r for r in regions if np.min((r[:,1]-x)**2+(r[:,0]-z)**2)<(.03*h)**2]
    if not regions:return dict(dark_opening_area_head2=0.,dark_opening_width_head=0.,threshold_Yprime=threshold)
    r=max(regions,key=len)
    return dict(dark_opening_area_head2=float(len(r)/h**2),dark_opening_width_head=float((np.ptp(r[:,1])+1)/h),threshold_Yprime=threshold)


def check(root,enforce=True):
    root=Path(root);records={p:json.loads((root/p/'matrix.json').read_text())['cases'] for p in ('before','after')}
    key=lambda c:(c['name'],c['angle'],c['look'],c['style'])
    assert {key(c) for c in records['before']}=={key(c) for c in records['after']}
    assert len(records['after'])==72
    geometry=[]
    for name in [f'{t}_{g}' for t in ('light','medium','dark') for g in ('F','M')]:
        phases={p:np.load(root/p/f'{name}_mesh.npz') for p in records}
        for angle in (35,55):
            values={}
            for phase,data in phases.items():
                points=data['points'];eye=data['eyes'].mean(0);mouth_z=float(points[[520,540,521,538,7267,7282],2].mean())
                values[phase]=projected_concavity(points,float(data['head_height']),float(data['chin']),eye[1],eye[2],mouth_z,angle,edges=data['edges'])
            reduction=1-values['after']['max_deficit_head']/max(.0001,values['before']['max_deficit_head'])
            geometry.append(dict(name=name,angle=angle,reduction=reduction,**values))
    shading=[]
    for a in records['before']:
        b=next(c for c in records['after'] if key(c)==key(a))
        shading.append(dict(name=a['name'],angle=a['angle'],look=a['look'],style=a['style'],before=patches(a),after=patches(b,a)))
    if enforce:
        assert np.mean([r['reduction'] for r in geometry])>.30,geometry
        assert all(r['after']['max_deficit_head']<.045 for r in geometry),geometry
        for look in ('blue_hour','studio_film'):
            rows=[r for r in shading if r['look']==look and r['style']=='anime']
            old=np.mean([r['before']['edge_density'] for r in rows]);new=np.mean([r['after']['edge_density'] for r in rows])
            assert new<=old+.005,(look,old,new)
    projections=[root/'projections'/f'{phase}_{tone}_{sex}.json' for phase in ('before','after') for tone in ('light','medium','dark') for sex in ('F','M')]
    if enforce:assert all(p.exists() for p in projections),'Run articulation --all-characters --measure-only for both phases'
    result=dict(geometry=geometry,shading=shading,roi_projection='native validated camera replay' if all(p.exists() for p in projections) else 'provisional plane homography')
    (root/'metrics.json').write_text(json.dumps(result,indent=2))
    overlays=[]
    for angle in (0,55):
        for name in ('light_M','medium_F','dark_M'):
            a=next(c for c in records['before'] if key(c)==(name,angle,'blue_hour','anime'));mask,broad=face_mask(a,(256,256));line=[]
            for phase in ('before','after'):
                case=next(c for c in records[phase] if key(c)==key(a));pixels=read(Path(case['path'])).astype(float)
                pixels[mask]=pixels[mask]*.65+np.array([40,240,80])*.35
                pixels[broad&~mask]=pixels[broad&~mask]*.65+np.array([240,50,50])*.35
                path=root/f'roi_{phase}_{name}_{angle}.png';save(path,pixels.astype(np.uint8));line.append((phase+' '+name+(' front' if angle==0 else ' profile'),path))
            overlays.append(line)
    board(root/'roi_masks.png',overlays,cell=(256,256))
    for look in ('studio_film','blue_hour'):
        for style in ('anime','animated_film'):
            rows=[]
            for name in [f'{t}_{g}' for t in ('light','medium','dark') for g in ('F','M')]:
                rows.append([(f'{p} {name} '+{0:'front',35:'quarter',55:'profile'}[angle],next(c['path'] for c in records[p] if key(c)==(name,angle,look,style))) for angle in (0,35,55) for p in ('before','after')])
            board(root/f'{style}_{look}.png',rows,cell=(256,256))
    return result


def check_colour(root):
    import toon_round4b as colour
    root=Path(root);old=colour.OUT
    try:
        colour.OUT=root/'colour';result=colour.metrics()
    finally:colour.OUT=old
    identity=[]
    for tone in ('light','medium','dark'):
        before=read(root.parent/'toon_round4b/after'/f'{tone}_realistic.png')
        after=read(root/'colour/after'/f'{tone}_realistic.png')
        same=bool(np.array_equal(before,after));identity.append(dict(tone=tone,pixel_identical=same,rgb_byte_mae=float(abs(before.astype(float)-after.astype(float)).mean())))
        assert same,identity[-1]
    (root/'colour/realistic_identity.json').write_text(json.dumps(identity,indent=2))
    board(root/'colour.png',[[(tone+' '+style,root/'colour/after'/f'{tone}_{style}.png') for style in ('realistic','anime','animated_film')] for tone in ('light','medium','dark')])
    print('TOON ROUND6 FRESH COLOUR OK; REALISTIC PIXEL IDENTITY OK',flush=True)
    return result


def articulation_checks(root,enforce=True,boards=True):
    root=Path(root);rows=[];binding=[]
    for tone in ('light','medium','dark'):
        for sex in ('F','M'):
            name=f'{tone}_{sex}'
            data={p:json.loads((root/'articulation'/p/name/'metrics.json').read_text()) for p in ('before','after')}
            a,b=data['before']['binding'],data['after']['binding']
            same={key:a[key]==b[key] for key in ('vertices','faces','topology_sha256','weights_sha256','bones_sha256','landmarks')}
            same['native_shapes_retained']=set(a['shape_names'])<=set(b['shape_names'])
            binding.append(dict(name=name,**same,added_shapes=sorted(set(b['shape_names'])-set(a['shape_names']))))
            if enforce:assert all(same.values()),binding[-1]
            for old in data['before']['states']:
                new=next(s for s in data['after']['states'] if s['name']==old['name'])
                row=dict(character=name,pose=old['name'],before=old.copy(),after=new.copy())
                for phase,state in (('before',old),('after',new)):
                    if state.get('path'):row[phase].update(aperture(state))
                rows.append(row)
                if not enforce:continue
                if new['name'] in ('M','B','P'):
                    assert new['lip_gap_m']<.001 and new['lip_gap3d_m']<.001,new
                    assert new['full_rim_max_gap_m']<.001,new
                if new['name'] in ('blink','blink_squint'):assert new['lid_gap3d_m']<.0001,new
                if new['name'] in ('A','O'):assert new['lip_gap_head']>=(.135 if new['name']=='A' else .095),new
            neutral=next(r for r in data['after']['states'] if r['name']=='neutral')
            smile=next(r for r in data['after']['states'] if r['name']=='smile')
            if enforce:assert smile['corner_lift_head']-neutral['corner_lift_head']>.02,(name,neutral,smile)
    (root/'articulation.json').write_text(json.dumps(rows,indent=2));(root/'binding.json').write_text(json.dumps(binding,indent=2))
    if not boards:return rows
    for filename,names in [('expressions.png',('neutral','smile','A','O','M')),('eyes.png',('neutral','surprised','blink'))]:
        board(root/filename,[[(phase+' '+name,root/'articulation'/phase/'dark_M'/f'{name}.png') for name in names] for phase in ('before','after')])
    return rows


def eye_checks(root,enforce=True):
    from engine.toon import LID_PAIRS
    root=Path(root);rows=[]
    for tone in ('light','medium','dark'):
        for sex in ('F','M'):
            name=f'{tone}_{sex}';values={}
            for phase in ('before','after'):
                d=np.load(root/phase/f'{name}_mesh.npz');p=d['points'];h=float(d['head_height'])
                iris=d['iris_centers'] if 'iris_centers' in d else d['eyes'];eyes=[]
                for pairs in LID_PAIRS.values():
                    ids=np.array(pairs);low=p[ids[:,1],2].min();high=p[ids[:,0],2].max();cx=p[ids.ravel(),0].mean();center=min(iris,key=lambda q:abs(q[0]-cx))
                    eyes.append(dict(height_head=float((high-low)/h),iris_fraction=float((center[2]-low)/(high-low))))
                values[phase]=eyes
            rows.append(dict(name=name,**values))
            if enforce:
                assert all(.34<=v['iris_fraction']<=.66 for v in values['after']),rows[-1]
                if sex=='M':assert all(v['height_head']>=.125 for v in values['after']),rows[-1]
    (root/'eyes.json').write_text(json.dumps(rows,indent=2));return rows


def hair_checks(root,enforce=True):
    root=Path(root);references=json.loads((root/'hair/matrix.json').read_text())['cases']
    references.sort(key=lambda r:('light_F','medium_F','dark_M').index(r['name']))
    cases=json.loads((root/'after/matrix.json').read_text())['cases'];rows=[]
    def sample(case):
        p=read(Path(case['path']))/255;site=case['hair_site']
        if 'style' in case:
            data=np.load(root/'after'/f"{case['name']}_mesh.npz");h=float(data['head_height']);chin=float(data['chin']);eye=data['eyes'].mean(0)
            projection,origin,_=native_camera(str(root),'after',case['name'],35)
            q=np.r_[(np.array([.07*h,eye[1]+.10*h,chin+.94*h])-origin)/h,1.]@projection.T
            site=q[:2]/q[2]
        x,y=np.rint(site).astype(int);rgb=np.median(p[y-2:y+3,x-2:x+3],axis=(0,1))
        return dict(rgb=rgb.tolist(),hsv=list(colorsys.rgb_to_hsv(*rgb)),Yprime=float(rgb@[.2126,.7152,.0722]),roi=[int(x-2),int(y-2),int(x+3),int(y+3)])
    for ref in references:
        source=sample(ref);styled={}
        for style in ('anime','animated_film'):
            case=next(c for c in cases if (c['name'],c['angle'],c['look'],c['style'])==(ref['name'],35,'studio_film',style))
            value=sample(case);hue=abs(value['hsv'][0]-source['hsv'][0]);hue=min(hue,1-hue)
            saturation=value['hsv'][1]/max(.001,source['hsv'][1]);value.update(hue_error_turns=hue,saturation_ratio=saturation)
            styled[style]=value
        delta=abs(styled['anime']['Yprime']-styled['animated_film']['Yprime'])
        row=dict(name=ref['name'],hair=ref['hair'],reference=source,styles=styled,style_Yprime_difference=delta,
                 audited_asset=ref['hair'] in ('ponytail01','short02'),
                 pbr_colour_pass=all(v['hue_error_turns']<=.04 and v['saturation_ratio']>=.75 for v in styled.values()))
        # The owner audited ponytail01/short02 for this item. Keep the extra
        # replacement-bob/PBR comparison as an explicit diagnostic, including
        # its warm physical highlight mismatch; do not present it as passing.
        rows.append(row)
    (root/'hair/colour.json').write_text(json.dumps(rows,indent=2))
    before=json.loads((root/'before/matrix.json').read_text())['cases'];sheet=[]
    for ref in references:
        line=[(ref['name']+' PBR',ref['path'])]
        for phase,source in (('before',before),('after',cases)):
            line.extend([(phase+' '+style,next(c['path'] for c in source if (c['name'],c['angle'],c['look'],c['style'])==(ref['name'],35,'studio_film',style))) for style in ('anime','animated_film')])
        sheet.append(line)
    board(root/'hair.png',sheet,cell=(256,256))
    if enforce:
        for row in rows:
            assert row['style_Yprime_difference']<.08,row
            if row['audited_asset']:assert row['pbr_colour_pass'],row
            elif not row['pbr_colour_pass']:
                print('TOON ROUND6 HAIR LIMIT:',row['name'],'replacement bob/PBR highlight hue differs; see hair/colour.json',flush=True)
    return rows


def look_checks(root,enforce=True):
    root=Path(root);data={phase:json.loads((root/'looks'/phase/'matrix.json').read_text())['cases'] for phase in ('before','after')};rows=[]
    for a in data['before']:
        b=next(c for c in data['after'] if c['look']==a['look'])
        old,new=patches(a),patches(b,a);rows.append(dict(look=a['look'],before=old,after=new))
        if enforce:assert new['edge_density']<=old['edge_density']+.005,rows[-1]
    (root/'looks/metrics.json').write_text(json.dumps(rows,indent=2))
    board(root/'all_looks.png',[[(phase+' '+look,next(c['path'] for c in data[phase] if c['look']==look)) for look in [r['look'] for r in rows][i:i+2] for phase in ('before','after')] for i in range(0,len(rows),2)],cell=(256,256))
    return rows
