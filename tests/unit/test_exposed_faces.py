import sys, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course.navigation import World,Node
from luanti_course.skills import approach_and_face,dig_node

def tunnel():
 w=World()
 for x in range(-3,4):
  for y in range(5):
   for z in range(-3,4):w.nodes[x,y,z]=Node('stone',True)
 for y in (1,2):
  for z in range(-3,4):w.nodes[0,y,z]=Node('air',False)
 return w

class ExposedFaceTests(unittest.TestCase):
 def test_side_ore_in_two_high_tunnel_is_reachable(self):
  w=tunnel();eye=(0,2.125,0);target=(1,1,0)
  self.assertFalse(w.visible(eye,target));self.assertTrue(w.approach((0,1,0),target))
  self.assertEqual(w.interaction_point(eye,target),(.51,1,0))
 def test_lower_exposed_edge_after_neighbor_ore_is_removed(self):
  w=tunnel();w.nodes[1,1,0]=Node('air',False)
  # Next block around a tunnel corner is exposed through the first ore hole,
  # but the overhanging roof still hides every face centre.
  w.nodes[0,1,1]=Node('stone',True);w.nodes[0,2,1]=Node('stone',True)
  self.assertIsNotNone(w.interaction_point((0,2.125,0),(1,1,1)))
 def test_centre_aim_is_preserved_when_visible(self):
  w=tunnel();self.assertEqual(w.interaction_point((0,2.125,0),(1,2,0)),(1,2,0))
 def test_hidden_ore_does_not_allow_through_wall_ray(self):
  w=tunnel();self.assertIsNone(w.interaction_point((0,2.125,0),(2,1,0)))
  self.assertFalse(w.approach((0,1,0),(2,1,0)))
 def test_no_extended_reach(self):
  w=tunnel();self.assertFalse(w.approach((0,1,-3),(1,1,1)))
 def test_unknown_ray_is_not_air(self):
  w=tunnel();del w.nodes[0,1,0]
  self.assertIsNone(w.interaction_point((0,2.125,0),(1,1,0)))
 def test_partial_geometry_does_not_invent_full_cube_face(self):
  w=tunnel();w.nodes[1,1,0]=Node('slab',True,full_cube=False)
  self.assertIsNone(w.interaction_point((0,2.125,0),(1,1,0)))
 def test_approach_aims_using_actual_eye(self):
  w=tunnel();state=NS(eye=(0,2.1,.13),position=(0,.5,.13),pointed_node=(1,1,0))
  ctx=NS(world=w,read=lambda *args:state,wait=lambda test,**kw:state if test(state) else None)
  aim=w.interaction_point(state.eye,(1,1,0))
  with patch('luanti_course.skills.navigate'),patch('luanti_course.skills.face') as face:
   approach_and_face(ctx,(1,1,0));face.assert_called_once_with(ctx,aim)
 def test_dig_does_not_retarget_occluded_centre_after_tool_change(self):
  w=tunnel();w.nodes[1,1,0]=Node('air',False)
  state=NS(position=(0,.5,0),pointed_node=(1,1,0))
  ctx=NS(world=w,read=lambda *args:state,wait=lambda test,**kw:state,log=lambda *a,**k:None,stop_input=lambda:None)
  with patch('luanti_course.skills.approach_and_face'),patch('luanti_course.skills.choose_tool',return_value=('stone',.1)),patch('luanti_course.skills.face',side_effect=AssertionError('should retain confirmed aim')):
   dig_node(ctx,(1,1,0))
if __name__=='__main__':unittest.main()
