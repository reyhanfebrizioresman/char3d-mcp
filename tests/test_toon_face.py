"""Deterministic depth fairing contracts, without Blender or rendered fixtures."""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine.toon_face import midface_offset,midface_motion_gain


def main():
    x,z=np.meshgrid(np.linspace(-.35,.35,81),np.linspace(-.20,.48,89))
    base=-.12+.20*x*x+.12*z*z
    bridge=-.07*np.exp(-.5*(x/.018)**2-.5*((z-.21)/.08)**2)
    valley=.04*np.exp(-.5*((abs(x)-.075)/.017)**2-.5*((z-.11)/.09)**2)
    p=np.c_[x.ravel(),(base+bridge+valley).ravel(),z.ravel()]
    p[294]=[0,-.15,.12]
    lip=[int(np.argmin((x.ravel()-v)**2+z.ravel()**2)) for v in (-.02,0,.02)]
    lid=[int(np.argmin((x.ravel()-v)**2+(z.ravel()-.27)**2)) for v in (-.20,-.10,.10,.20)]
    offset=midface_offset(p,1.,-.10,.27,lip,lid)
    assert np.isfinite(offset).all() and abs(offset).max()<=.09
    assert np.array_equal(offset[:,[0,2]],np.zeros((len(p),2)))
    assert np.array_equal(offset[lid],np.zeros((len(lid),3)))
    q=p+offset
    # A compressed narrow bridge is rounded without deleting the tip.
    ridge=(abs(p[:,0])<.012)&(p[:,2]>.18)&(p[:,2]<.25)
    assert (q[ridge,1]-p[ridge,1]).mean()>.025
    assert q[294,1]<-.14
    source=(base+bridge+valley)
    fitted=q[:,1].reshape(x.shape)
    mask=(abs(x[:,1:-1])<.16)&(z[:,1:-1]>.04)&(z[:,1:-1]<.23)
    before=np.abs(np.diff(source,2,axis=1))[mask].mean()
    after=np.abs(np.diff(fitted,2,axis=1))[mask].mean()
    assert after<before*.5,(before,after)
    # Fixed rest offsets preserve arbitrary relative articulation exactly.
    articulation=np.random.default_rng(9).normal(0,.002,p.shape)
    assert np.allclose((p+articulation+offset)-q,articulation,atol=1e-14)
    # Scale and vertical translation equivariance, including the compact falloff.
    shifted=p*2+[0,0,3]
    twice=midface_offset(shifted,2.,-.20,.54+3,lip,lid)
    assert np.allclose(twice,offset*2,atol=1e-12)
    # An oral lining behind the exterior must retain its depth, rather than
    # being projected onto the skin and appearing as a protruding lip block.
    parent=np.flatnonzero((abs(p[:,0])<.08)&(abs(p[:,2])<.08))[:40]
    lining=p[parent]+[0,.03,0]
    layered=np.r_[p,lining];surface_y=np.r_[p[:,1],p[parent,1]]
    moved=layered+midface_offset(layered,1.,0.,.27,lip,lid,surface_y)
    assert np.allclose(moved[len(p):,1]-moved[parent,1],.03,atol=1e-12)
    gain=midface_motion_gain(p,1.,lip,lid)
    assert gain.min()>=.12-1e-12 and gain.max()<=1
    assert np.array_equal(gain[lid],np.ones(len(lid)))
    assert gain[np.argmin(abs(p[:,0])+abs(p[:,2]))]<.13
    transform=lambda d:d*np.c_[np.ones(len(p)),gain,np.ones(len(p))]
    a,b=np.random.default_rng(4).normal(size=(2,*p.shape))
    assert np.allclose(transform(a+b),transform(a)+transform(b))
    assert np.array_equal(transform(a)[:,[0,2]],a[:,[0,2]])
    assert np.allclose(midface_motion_gain(shifted,2.,lip,lid),gain)
    print('TOON FACE UNIT OK')

if __name__=='__main__':main()
