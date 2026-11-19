"""Conservative segment/AABB rejection before expensive mesh ray casts."""
import numpy as np


def intersects(origin, targets, low, high):
    origin=np.asarray(origin,dtype=float);targets=np.asarray(targets,dtype=float)
    low,high=np.asarray(low,dtype=float)-1e-6,np.asarray(high,dtype=float)+1e-6
    delta=targets-origin
    parallel=abs(delta)<1e-12
    outside=np.any(parallel & ((origin<low) | (origin>high)),axis=1)
    safe=np.where(parallel,1.,delta)
    a,b=(low-origin)/safe,(high-origin)/safe
    enter=np.max(np.where(parallel,-np.inf,np.minimum(a,b)),axis=1)
    leave=np.min(np.where(parallel,np.inf,np.maximum(a,b)),axis=1)
    return ~outside & (np.maximum(0,enter)<=np.minimum(1,leave))
