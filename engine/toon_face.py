"""Rest-depth fairing for the compressed HM08 midface (numpy only).

The eye/mouth proportion maps can put the nasal bridge in front of the tip and
leave the upper lip behind the cheek plane. A broad cheek-supported surface
removes that inherited fold while retaining a small rounded tip and soft lips.
Only Y changes. One neutral offset is shared by all relative morphs.
"""
import numpy as np
from .toon import smooth


def midface_offset(points, head_height, eye_y, eye_z, lip_ids, lid_ids, surface_y=None):
    p=np.asarray(points,dtype=float);h=float(head_height)
    mouth=p[np.asarray(lip_ids)].mean(0)
    x=p[:,0]/h;z=(p[:,2]-mouth[2])/h;y=p[:,1]/h
    front=(p[:,1]<eye_y+.035*h)&(np.arange(len(p))<13380)
    # Cheeks support the facial plane; exclude compressed nose, nasolabial folds
    # and the oral cavity. Keep only the anterior envelope in each X/Z bin.
    samples=front&(abs(x)>.19)&(abs(x)<.32)&(z>-.11)&(z<(eye_z-mouth[2])/h+.12)
    ids=np.flatnonzero(samples)
    if len(ids)<20:return np.zeros_like(p)
    bins=np.floor(np.c_[x[ids],z[ids]]/.025).astype(int)
    _,inverse=np.unique(bins,axis=0,return_inverse=True)
    minimum=np.full(inverse.max()+1,np.inf);np.minimum.at(minimum,inverse,y[ids])
    ids=ids[y[ids]<minimum[inverse]+.008]
    def design(xx,zz):return np.c_[np.ones_like(xx),xx*xx,zz,zz*zz]
    a=design(x[ids],z[ids]);v=y[ids]
    # Robust fit prevents a mouth-interior/helper vertex from skewing the plane.
    weights=np.ones(len(ids))
    for _ in range(4):
        coefficients=np.linalg.lstsq(a*weights[:,None],v*weights,rcond=None)[0]
        error=abs(a@coefficients-v);weights=1/np.maximum(1,error/.012)
    target=design(x,z)@coefficients
    # The lip rolls share a gently sloping support. Extrapolating the cheek's
    # jawward slope through the tiny mouth would recess the lower lip again.
    oral=np.exp(-.5*(x/.14)**4-.5*(z/.070)**4)
    target+=((design(x,z*.30)@coefficients)-target)*oral
    tip_z=(p[294,2]-mouth[2])/h if len(p)>294 else .12
    tip_z=float(np.clip(tip_z,.07,.17))
    # A rounded button, shallow bridge and two soft lip rolls. These are depth
    # details, not dark painted marks; native lip X/Z outlines remain intact.
    target-=.030*np.exp(-.5*(x/.043)**2-.5*((z-tip_z)/.030)**2)
    target-=.004*np.exp(-.5*(x/.042)**2-.5*((z-tip_z-.075)/.080)**2)
    lip=(np.exp(-.5*((z-.018)/.014)**2)+.85*np.exp(-.5*((z+.026)/.017)**2))
    target-=.010*lip*np.exp(-.5*(x/.11)**4)
    # Cheek extrapolation alone leaves the bridge too far ahead of the inner
    # canthi. Anchor its upper part to their depth, with only shallow convexity;
    # this avoids replacing the old ridge with a pocket beside each eye.
    eye_height=(eye_z-mouth[2])/h
    inner=max(.015,float(np.min(abs(p[np.asarray(lid_ids),0]))/h))
    bridge=smooth((z-eye_height+.085)/.065)*(1-smooth((z-eye_height-.10)/.09))
    width=inner+.14*smooth((z-eye_height)/.08)
    bridge*=1-smooth((abs(x)-width)/(.40*width))
    shallow=eye_y/h-.008*(1-np.minimum(abs(x)/inner,1)**2)
    target+=(shallow-target)*bridge
    weight=(1-smooth((abs(x)-.12)/.16))*smooth((z+.22)/.14)
    weight*=1-smooth((z-(eye_z-mouth[2])/h-.025)/.12)
    weight*=1-smooth((p[:,1]-eye_y-.025*h)/(.050*h))
    weight[13380:]=0
    # Exact eye-rim preservation with a continuous spatial transition. The lip
    # rims deliberately participate: pinning them was retaining a sunken mouth.
    rim=p[np.asarray(lid_ids)]
    distance=np.sqrt((((p[:,None,[0,2]]-rim[None,:,[0,2]])/h)**2).sum(2)).min(1)
    weight*=smooth(distance/.035)
    weight[np.asarray(lid_ids)]=0
    delta=np.zeros_like(p)
    # Translate hidden linings by the exterior's displacement. Projecting each
    # depth layer onto the same plane would pull the oral cavity through skin.
    exterior=y if surface_y is None else np.asarray(surface_y)/h
    delta[:,1]=np.clip((target-exterior)*h,-.09*h,.09*h)*weight*(.94-.16*oral)
    return delta


def midface_motion_gain(points,head_height,lip_ids,lid_ids):
    """Contract oversized native depth articulation, preserving screen contours.

    A common neutral-space scalar keeps morph combinations linear. Opening,
    corner lift and eye rims retain their native X/Z motion; the tiny stylized
    mouth needs much less forward/back travel than its realistic source.
    """
    p=np.asarray(points);h=float(head_height);mouth=p[np.asarray(lip_ids)].mean(0)
    x=abs(p[:,0])/h;z=(p[:,2]-mouth[2])/h
    weight=(1-smooth((x-.14)/.16))*smooth((z+.32)/.16)*(1-smooth((z-.08)/.14))
    weight*=1-smooth((p[:,1]-mouth[1]-.10*h)/(.12*h))
    weight[13380:]=0;weight[np.asarray(lid_ids)]=0
    return 1-.88*weight
