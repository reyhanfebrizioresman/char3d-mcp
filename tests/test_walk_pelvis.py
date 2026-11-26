"""Regression checks distinguishing trajectory smoothness from baseline offsets."""
import unittest
from walk_round14_metrics import compare_pelvis

def rows(values):return [dict(frame=i,pelvis_m=[0,0,z]) for i,z in enumerate(values)]
class PelvisTests(unittest.TestCase):
 def test_constant_lowering_preserves_smoothness(self):
  a=[1,1.002,1.001,1.003];r=compare_pelvis(rows(a),rows([z-.011 for z in a]))
  self.assertEqual(r['failures'],[]);self.assertAlmostEqual(r['mean_delta_m'],-.011)
 def test_high_frequency_change_fails_both_bounds(self):
  r=compare_pelvis(rows([1,1.001,1.002,1.003]),rows([1,1.001,1.02,1.003]))
  self.assertEqual(set(r['failures']),{'step_max_m','second_difference_max_m'})
 def test_ten_percent_boundary(self):
  self.assertEqual(compare_pelvis(rows([0,.01,0]),rows([0,.011,0]))['failures'],[])
  self.assertTrue(compare_pelvis(rows([0,.01,0]),rows([0,.01101,0]))['failures'])
 def test_frame_mismatch_rejected(self):
  with self.assertRaises(AssertionError):compare_pelvis(rows([0,1]),rows([0]))
if __name__=='__main__':unittest.main()
