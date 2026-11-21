"""Local, topology-preserving refinement of MPFB toon surfaces and articulation."""
import numpy as np
from .toon import smooth,monotone


def squint_field(points,delta,head_height,rims,rim_deltas,limit=.025):
    """Slide a lower socket with its rim, without rolling its inner wall out.

    The same spatial rule is used on the body and fitted facial proxies. The
    neutral surface is untouched; these are relative expression deltas.
    """
    p=np.asarray(points);d=np.asarray(delta).copy();h=float(head_height)
    for rim,motion in zip(rims,rim_deltas):
        order=np.argsort(rim[:,0]);line=rim[order];move=motion[order]
        z=np.interp(p[:,0],line[:,0],line[:,2]);y=np.interp(p[:,0],line[:,0],line[:,1])
        outside=np.maximum(line[:,0].min()-p[:,0],p[:,0]-line[:,0].max())/h
        w=1-smooth(outside/.070)
        height=(p[:,2]-z)/h
        w*=smooth((height+.20)/.10)*(1-smooth((height-.055)/.050))
        w*=1-smooth((p[:,1]-y-.090*h)/(.09*h))
        target=np.zeros_like(d)
        target[:,0]=np.interp(p[:,0],line[:,0],move[:,0])
        target[:,2]=np.interp(p[:,0],line[:,0],move[:,2])
        if limit is None:target[:,1]=np.interp(p[:,0],line[:,0],move[:,1])
        else:target[:,2]=np.clip(target[:,2],0,limit*h)
        d+=(target-d)*w[:,None]
    return d


def round_chin_offset(points,h,chin,eye_y):
    """Bounded U-shaped lower contour, preserving the scalp/chin endpoints."""
    p=np.asarray(points);u=(p[:,2]-chin)/h;x=p[:,0]/h
    target=chin+.22*h*(1-np.sqrt(np.maximum(0,1-np.clip(abs(x)/.35,0,1)**2)))
    w=smooth(u/.025)*(1-smooth((u-.10)/.16))
    w*=1-smooth((abs(x)-.27)/.10)
    w*=1-smooth((p[:,1]-eye_y-.08*h)/(.18*h))
    result=np.zeros_like(p,dtype=float)
    result[:,2]=np.clip(target-p[:,2],-.035*h,.015*h)*w*.45
    return result


def profile_displacement(points,surface_y,head_height,chin,chin_y,eye_y,mouth_z):
    """A convex lower-face support, translating deeper layers with its surface."""
    p=np.asarray(points);h=float(head_height);u=(p[:,2]-chin)/h;x=p[:,0]/h
    # Put the circular arc's root below the active neck/chin falloff. Its
    # derivative is then finite over the entire visible support, with the
    # original chin depth retained instead of a new projecting chin point.
    t=np.clip((u+.055)/.545,0,1)
    arc0=np.sqrt((.055/.545)*(2-.055/.545))
    arc=(np.sqrt(np.maximum(0,t*(2-t)))-arc0)/(1-arc0)
    lower=chin_y+.012*h
    depth=max(.13*h,lower-eye_y)
    target=lower-depth*arc+.070*h*(x/.35)**2
    weight=smooth((u+.035)/.075)*(1-smooth((u-.24)/.23))
    weight*=1-smooth((abs(x)-.26)/.15)
    weight*=1-smooth((p[:,1]-eye_y-.08*h)/(.12*h))
    delta=np.zeros_like(p,dtype=float)
    delta[:,1]=np.clip(target-np.asarray(surface_y),-.22*h,.16*h)*weight*.95
    return delta


def mouth_width_map(points,head_height,mouth,eye_y):
    p=np.asarray(points,dtype=float).copy();h=float(head_height);c=np.asarray(mouth)
    w=np.exp(-.5*((p[:,0]-c[0])/(.16*h))**4-.5*((p[:,2]-c[2])/(.065*h))**4)
    w*=1-smooth((p[:,1]-eye_y-.07*h)/(.12*h))
    p[:,0]+=(p[:,0]-c[0])*.60*w
    return p


def aperture_map(points,head_height,apertures,eye_y):
    """Monotone lid expansion, shared by every relative target/proxy point."""
    p=np.asarray(points,dtype=float).copy();h=float(head_height)
    total=np.zeros(len(p));displacement=np.zeros(len(p))
    for cx,cz,width,height in apertures:
        if height>=.105*h:continue
        gap=.130*h
        z=(p[:,2]-cz)/h;half=height/(2*h)
        moved=monotone(z,[-.24,-half,0,half,.24],[-.24,-gap/(2*h),0,gap/(2*h),.24],endpoint_slopes=(1.,1.))
        weight=np.exp(-((p[:,0]-cx)/(width*.68))**6)
        weight*=1-smooth((p[:,1]-eye_y-.025*h)/(.10*h))
        displacement+=(moved-z)*h*weight;total+=weight
    p[:,2]+=displacement/np.maximum(1,total)
    return p


def soften_cutout(alpha):
    """Close tiny card-mask notches, then retain a narrow fractional edge.

    Soft density-mask technique: MIT blender-agent-skills/blender-hair-grooming.
    The small closing/filter operates in texture space, preserving native UVs.
    """
    a=np.asarray(alpha,float)
    def neighborhood(v,op):
        p=np.pad(v,1,mode='edge');stack=np.stack([p[y:y+len(v),x:x+v.shape[1]] for y in range(3) for x in range(3)])
        return op(stack,axis=0)
    binary=(a>.32).astype(float)
    closed=neighborhood(neighborhood(binary,np.max),np.min)
    median=neighborhood(closed,np.median)
    p=np.pad(median,1,mode='edge');result=np.zeros_like(median)
    kernel=np.array([1,2,1])/4
    for y in range(3):
        for x in range(3):result+=p[y:y+len(a),x:x+a.shape[1]]*kernel[y]*kernel[x]
    return np.clip((result-.12)/.76,0,1)


def projected_concavity(points,head_height,chin,eye_y,eye_z,mouth_z,angle,edges=None):
    """Upper-hull deficit of the front cheek/chin contour, nose excluded."""
    p=np.asarray(points);h=float(head_height);u=(p[:,2]-chin)/h
    select=(u>=-.01)&(u<.45)
    select[13380:]=False
    select&=~((abs(p[:,0])<.075*h)&(p[:,2]>mouth_z+.065*h))
    a=np.radians(angle);front=p[:,0]*np.cos(a)-p[:,1]*np.sin(a)
    z=np.linspace(.015,min(.42,(eye_z-chin)/h-.07),40)
    valid=[];contour=[]
    if edges is not None:
        edges=np.asarray(edges,int);edges=edges[(edges<13380).all(1)]
        start,end=p[edges[:,0]],p[edges[:,1]]
        dz=end[:,2]-start[:,2]
    for height in z:
        if edges is None:
            ids=select&(abs(u-height)<.017)
            values=front[ids]
        else:
            level=chin+height*h
            crossed=(start[:,2]-level)*(end[:,2]-level)<=0
            crossed&=abs(dz)>1e-10
            t=(level-start[crossed,2])/dz[crossed]
            section=start[crossed]+t[:,None]*(end[crossed]-start[crossed])
            use=~((abs(section[:,0])<.075*h)&(section[:,2]>mouth_z+.065*h))
            values=section[use,0]*np.cos(a)-section[use,1]*np.sin(a)
        if len(values):valid.append(height);contour.append(float(values.max()/h))
    z=np.asarray(valid);q=np.asarray(contour);hull=[]
    for i in range(len(z)):
        while len(hull)>1:
            j,k=hull[-2:]
            cross=(z[k]-z[j])*(q[i]-q[k])-(q[k]-q[j])*(z[i]-z[k])
            if cross<0:break
            hull.pop()
        hull.append(i)
    envelope=np.interp(z,z[hull],q[hull]);gap=np.maximum(0,envelope-q)
    return dict(max_deficit_head=float(gap.max()),mean_deficit_head=float(gap.mean()),z=z.tolist(),contour=q.tolist(),envelope=envelope.tolist())


def harmonic_correction(edges,mask,controls,pinned,iterations=100):
    """Diffuse a delta on native connectivity, preserving distinct closed lips."""
    edges=np.asarray(edges,int);mask=np.asarray(mask,float);controls=np.asarray(controls,int)
    a=np.r_[edges[:,0],edges[:,1]];b=np.r_[edges[:,1],edges[:,0]]
    degree=np.maximum(1,np.bincount(a,minlength=len(mask)))
    correction=np.zeros((len(mask),np.asarray(pinned).shape[1]));correction[controls]=pinned
    for _ in range(iterations):
        average=np.stack([np.bincount(a,weights=correction[b,axis],minlength=len(mask))/degree for axis in range(correction.shape[1])],axis=1)
        correction=(.35*correction+.65*average)*mask[:,None]
        correction[controls]=pinned
    return correction


def ellipsoid_mesh(center,radii,rows=24,columns=40):
    """Outward, non-degenerate head proxy with unique poles."""
    center=np.asarray(center);radii=np.asarray(radii)
    vertices=[(center+radii*[0,0,1]).tolist()];faces=[]
    for j in range(1,rows):
        phi=np.pi*j/rows
        for i in range(columns):
            angle=2*np.pi*i/columns
            vertices.append((center+radii*[np.sin(phi)*np.cos(angle),np.sin(phi)*np.sin(angle),np.cos(phi)]).tolist())
    bottom=len(vertices);vertices.append((center-radii*[0,0,1]).tolist())
    for i in range(columns):
        n=(i+1)%columns;faces.append((0,1+i,1+n))
    for j in range(rows-2):
        for i in range(columns):
            n=(i+1)%columns;a=1+j*columns;b=a+columns
            faces.append((a+i,b+i,b+n,a+n))
    last=1+(rows-2)*columns
    for i in range(columns):faces.append((last+i,bottom,last+(i+1)%columns))
    return vertices,faces


def disk_grid(segments=32,rings=4):
    """Column-aligned disk: curved, narrow lip bands cannot fold radially.

    Each triangle has two points at the same X. Its projected winding therefore
    depends on the positive band thickness, not on lip-curve chord curvature.
    """
    rows=2*rings+1;uv=[[-1.,0.]];faces=[]
    for x in np.linspace(-1,1,segments+1)[1:-1]:
        for v in np.linspace(-1,1,rows):uv.append([x,v*np.sqrt(1-x*x)])
    last=len(uv);uv.append([1.,0.])
    for j in range(rows-1):faces.append((0,1+j,2+j))
    for column in range(segments-2):
        a=1+column*rows;b=a+rows
        for j in range(rows-1):faces.append((a+j,b+j,b+j+1,a+j+1))
    a=1+(segments-2)*rows
    for j in range(rows-1):faces.append((a+j,last,a+j+1))
    return np.asarray(uv),faces


def mouth_points(points,upper,lower,params,h,part,extension=0.):
    """Fit each authored relative target; no frame handler or alpha switching."""
    q=np.asarray(points);u=q[upper];l=q[lower]
    def curve(values,x):
        order=np.argsort(values[:,0]);p=values[order]
        return np.stack([np.interp(x,p[:,0],p[:,axis]) for axis in range(3)],axis=1)
    left=max(u[:,0].min(),l[:,0].min());right=min(u[:,0].max(),l[:,0].max())
    center=(left+right)*.5;half=(right-left)*.5
    t=params[:,0];v=params[:,1];radius=np.sqrt(t*t+v*v)
    if part=='cavity':
        x=center+t*half*1.04
        hi=curve(u,x);lo=curve(l,x)
        normalized=v/np.sqrt(np.maximum(1e-8,1-t*t))
        normalized=np.clip(normalized,-1,1)
        result=lo+(hi-lo)*((normalized+1)*.5)[:,None]
        result[:,0]=x
        # Native closed-lip contours can cross locally at the canthi. Keep a
        # positive hidden lining thickness instead of inverting its corners.
        low=np.minimum(lo[:,2],hi[:,2])-.004*h;high=np.maximum(lo[:,2],hi[:,2])+.004*h
        result[:,2]=low+(high-low)*((normalized+1)*.5)
        result[:,1]+=(.010+.050*(1-radius*radius))*h
    elif part=='teeth_band':
        # A single softly curved ivory band. Fixed physical thickness avoids
        # enlarging individual teeth with the A/O opening; closed lips hide it.
        x=center+t*half*.70;hi=curve(u,x)
        result=hi.copy();result[:,2]+=(-.018+.010*v)*h
        result[:,1]+=(.028-.002*(1-radius*radius))*h
    else:
        x=center+t*half*.55;lo=curve(l,x)
        result=lo.copy();result[:,2]+=(.010+.010*v)*h
        result[:,1]+=(.035+.004*(1-radius*radius))*h
        if extension:
            # A tongue unit moves the low tip forward/up within the opening;
            # lip-rim-only bindings would silently turn tongueOut into a no-op.
            tip=(1-t*t)*(.5+.5*v)*float(extension)
            result[:,1]-=.016*h*tip;result[:,2]+=.018*h*tip
    return result
