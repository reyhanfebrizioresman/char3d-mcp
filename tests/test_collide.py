"""Collision geometry, bounded IK and temporal contracts, without Blender."""
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.collision import (segment_pair, capsule_distance, closest_segment,
    ellipsoid_distance, surface_distance, two_bone, smooth_corrections, bounded_correction, split_bezier)


class CollisionTests(unittest.TestCase):
    def test_capsule_crossing_parallel_endpoints_and_degenerate(self):
        for args, expected in (
            (([0,0,0], [1,0,0], .1, [.5,-1,0], [.5,1,0], .2), -.3),
            (([0,0,0], [1,0,0], .1, [0,1,0], [1,1,0], .2), .7),
            (([0,0,0], [1,0,0], .1, [2,1,0], [2,2,0], .2), 2**.5-.3),
            (([0,0,0], [0,0,0], .1, [1,0,0], [1,0,0], .2), .7)):
            distance, normal = capsule_distance(*args)
            self.assertAlmostEqual(distance, expected)
            self.assertAlmostEqual(np.linalg.norm(normal), 1.)
        np.testing.assert_allclose(closest_segment([[.5,1,0], [2,0,0]], [0,0,0], [1,0,0]), [[.5,0,0],[1,0,0]])
        rng = np.random.default_rng(71)
        for _ in range(30):
            a,b,c,d = rng.normal(size=(4,3))
            p,q = segment_pair(a,b,c,d)
            brute = np.linalg.norm((a+(b-a)*np.linspace(0,1,151)[:,None])[:,None,:]-
                     (c+(d-c)*np.linspace(0,1,151)[:,None])[None,:,:], axis=2).min()
            self.assertLessEqual(np.linalg.norm(p-q), brute+1e-8)

    def test_ellipsoid_inside_outside_principal_plane_center_and_rotation(self):
        d,n = ellipsoid_distance([[0,0,0], [0,.5,0], [0,2,0], [1,0,0]], [0,0,0], [1,1,1])
        np.testing.assert_allclose(d, [-1,-.5,1,0], atol=1e-7)
        d,n = ellipsoid_distance([[3,0,0], [0,0,0], [0,.5,0]], [0,0,0], [2,1,.5])
        np.testing.assert_allclose(d[:2], [1,-.5], atol=1e-7)
        self.assertLess(d[2], 0)
        np.testing.assert_allclose(np.linalg.norm(n, axis=1), 1., atol=1e-8)
        rot=np.array([[0,-1,0],[1,0,0],[0,0,1]])
        rotated,_ = ellipsoid_distance([[0,3,0]], [0,0,0], [2,1,.5], rot)
        self.assertAlmostEqual(rotated[0], 1., places=6)

    def test_bvh_signed_surface_contract(self):
        distance,normal=surface_distance([0,0,-.03],[0,0,0],[0,0,1],inside=True)
        self.assertAlmostEqual(distance,-.03)
        np.testing.assert_allclose(normal,[0,0,1])
        # Open surfaces must have finite two-sided thickness, no infinite inside.
        self.assertAlmostEqual(surface_distance([0,0,-2],[0,0,0],[0,0,1])[0],2)

    def test_ik_pushout_lengths_and_degenerate_pole(self):
        for target in ([.3,-.3,.1],[.3,-.4,.1],[0,0,0],[0,-5,0]):
            elbow,wrist=two_bone([0,0,0], target, .3,.25,[0,0,-1])
            self.assertAlmostEqual(np.linalg.norm(elbow),.3,places=7)
            self.assertAlmostEqual(np.linalg.norm(wrist-elbow),.25,places=7)
            self.assertTrue(np.isfinite(elbow).all())
        # Actual constrained world wrist orientation is checked by collide_checks
        # on Blender basic/MPFB contact performances, rather than a mock matrix.

    def test_smoothing_anticipates_contact_without_pops_or_lag(self):
        raw=np.zeros((80,3));raw[25:45,2]=.08
        smooth=smooth_corrections(raw,24)
        self.assertTrue(np.all(smooth[25:45,2]>=.08))
        self.assertTrue(smooth[24,2]>0 and smooth[45,2]>0)
        self.assertLess(np.abs(np.diff(smooth[:,2])).max(),.025)
        onset=int(np.flatnonzero(smooth[:,2]>1e-6)[0])
        self.assertLess(abs(smooth[onset,2]-smooth[onset-1,2]),.002)
        np.testing.assert_array_equal(smooth,smooth_corrections(raw,24))
        np.testing.assert_array_equal(raw[0], [0,0,0])

    def test_intended_contacts_and_large_conflicts_skip(self):
        correction,reason=bounded_correction([0,.04,0], .1,locked=True)
        self.assertIn('protected',reason);self.assertFalse(correction.any())
        correction,reason=bounded_correction([0,.4,0], .1)
        self.assertIn('limit',reason);self.assertFalse(correction.any())
        self.assertIsNone(bounded_correction([0,.04,0], .1)[1])
        locked=np.zeros(20,bool);locked[8:13]=True
        raw=np.ones((20,3))*.01
        np.testing.assert_array_equal(smooth_corrections(raw,24,locked)[locked],np.zeros((5,3)))

    def test_sparse_curve_split_preserves_authored_halves(self):
        p=np.array([[1,0],[35,2],[70,-1],[100,.5]],dtype=float)
        a,c,d,e,q=split_bezier(p,42.)
        self.assertAlmostEqual(q[0],42.,places=10)
        def cubic(points,t):
            p0,p1,p2,p3=points
            return (1-t)**3*p0+3*(1-t)**2*t*p1+3*(1-t)*t*t*p2+t**3*p3
        lo,hi=0.,1.
        for _ in range(50):
            t=(lo+hi)/2
            if cubic(p,t)[0]<42.:lo=t
            else:hi=t
        for u in np.linspace(0,1,17):
            np.testing.assert_allclose(cubic([p[0],a,d,q],u),cubic(p,hi*u),atol=1e-10)
            np.testing.assert_allclose(cubic([q,e,c,p[3]],u),cubic(p,hi+(1-hi)*u),atol=1e-10)


if __name__ == '__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(CollisionTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print('COLLIDE UNIT OK')
