"""Offline invariants for the Round 6 geometry/alpha kernels."""
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine.toon_refine import profile_displacement,mouth_width_map,aperture_map,soften_cutout,projected_concavity,harmonic_correction,ellipsoid_mesh


def main():
    x,z=np.meshgrid(np.linspace(-.35,.35,81),np.linspace(0,.48,81))
    t=np.clip(z/.49,0,1)
    convex=-.068-.162*np.sqrt(t*(2-t))+.07*(x/.35)**2
    snout=convex-.055*np.exp(-((z-.20)/.05)**2)+.035*np.exp(-((z-.30)/.045)**2)
    p=np.c_[x.ravel(),snout.ravel(),z.ravel()]
    d=profile_displacement(p,p[:,1],1.,0.,-.08,-.23,.20)
    q=p+d
    assert np.isfinite(q).all() and abs(d).max()<=.12
    assert np.array_equal(p[:,[0,2]],q[:,[0,2]])
    epsilon=1e-6
    chin_line=np.array([[0,-.15,-epsilon],[0,-.15,0],[0,-.15,epsilon]])
    chin_delta=profile_displacement(chin_line,chin_line[:,1],1.,0.,-.08,-.23,.2)[:,1]
    slopes=np.diff(chin_delta)/epsilon
    assert abs(slopes[1]-slopes[0])<.001,slopes
    for angle in (35,55):
        old=projected_concavity(p,1.,0.,-.23,.49,.20,angle)['max_deficit_head']
        new=projected_concavity(q,1.,0.,-.23,.49,.20,angle)['max_deficit_head']
        assert new<old*.8,(angle,old,new)
    # Exterior and lining translate by the same amount in the full-weight zone.
    outer=np.array([[0,-.25,.2],[.05,-.24,.2]])
    inner=outer+[0,.02,0]
    a=profile_displacement(outer,outer[:,1],1.,0.,-.08,-.23,.2)
    b=profile_displacement(inner,outer[:,1],1.,0.,-.08,-.23,.2)
    assert np.allclose(a,b)
    # Widening is monotone and cannot turn a closed seam into crossed lips.
    line=np.c_[np.linspace(-.4,.4,1001),np.full(1001,-.2),np.full(1001,.2)]
    wide=mouth_width_map(line,1.,[0,-.2,.2],-.23)
    assert np.diff(wide[:,0]).min()>0
    duplicate=mouth_width_map([[0,-.2,.2],[0,-.2,.2]],1.,[0,-.2,.2],-.23)
    assert np.array_equal(duplicate[0],duplicate[1])
    # Narrow lids expand without folding Z or moving head endpoints; every
    # coincident closed-lid point receives exactly the same map.
    line=np.c_[np.full(1001,.16),np.full(1001,-.2),np.linspace(0,1,1001)]
    opened=aperture_map(line,1.,[(.16,.5,.25,.09)],-.23)
    assert np.diff(opened[:,2]).min()>0
    assert np.array_equal(opened[[0,-1]],line[[0,-1]])
    bounds=aperture_map([[.16,-.23,.455],[.16,-.23,.545]],1.,[(.16,.5,.25,.09)],-.23)
    assert abs(np.ptp(bounds[:,2])-.13)<1e-10
    alpha=np.zeros((64,64));alpha[20:,:]=1;alpha[19,::2]=1
    mask=soften_cutout(alpha)
    assert mask.min()>=0 and mask.max()<=1 and ((mask>0)&(mask<1)).any()
    assert np.max(abs(soften_cutout(np.ones((8,8)))-1))<1e-12
    assert not soften_cutout(np.zeros((8,8))).any()
    # Topology, rather than 3D distance, keeps coincident closed lips distinct.
    edges=np.array([[0,1],[1,2],[2,3],[3,4],[4,5],[5,0]])
    controls=np.array([1,4]);pinned=np.array([[0,.1],[0,-.1]])
    delta=harmonic_correction(edges,np.ones(6),controls,pinned)
    assert np.array_equal(delta[controls],pinned)
    assert np.isfinite(delta).all() and abs(delta).max()<=.1
    assert np.allclose(harmonic_correction(edges,np.ones(6),controls,pinned*2),delta*2)
    assert not harmonic_correction(edges,np.zeros(6),[],np.zeros((0,2))).any()
    vertices,faces=ellipsoid_mesh([1,2,3],[.5,.3,1.])
    points=np.asarray(vertices)
    for face in faces:
        triangle=points[list(face[:3])]
        normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0])
        assert np.linalg.norm(normal)>1e-10
        assert normal@(triangle.mean(0)-[1,2,3])>0
    # Continuous edge-plane sections do not invent a notch between sparse
    # vertex rows on a genuinely convex head proxy.
    edge_set={tuple(sorted((a,b))) for face in faces for a,b in zip(face,face[1:]+face[:1])}
    centered=(points-[1,2,3])/[1,1,2]+[0,0,.5]
    for angle in (35,55):
        contour=projected_concavity(centered,1.,0.,-.1,.6,.2,angle,edges=np.array(sorted(edge_set)))
        assert contour['max_deficit_head']<.002,contour
    print('TOON REFINE UNIT OK')

if __name__=='__main__':main()
