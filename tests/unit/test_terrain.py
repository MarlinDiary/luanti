import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course.navigation import Node,Traversal
from test_skills import world

class TerrainTests(unittest.TestCase):
 def test_slab_actual_height(self):
  w=world();w.nodes[(1,1,0)]=Node('slab',True,full_cube=False,boxes=((-0.5,-0.5,-0.5,0.5,0,0.5),))
  self.assertTrue(w.standable((1,1.5,0)))
  self.assertFalse(w.standable((1,2,0)))
  self.assertIn((1,1.5,0),dict(w.neighbors((0,1,0))))
  self.assertEqual(w.start((1,1.001,0)),(1,1.5,0))
 def test_rotated_stair_and_low_ceiling(self):
  for boxes in (((-.5,-.5,-.5,.5,0,.5),(0,0,-.5,.5,.5,.5)),((-.5,-.5,-.5,.5,0,.5),(-.5,0,0,.5,.5,.5))):
   w=world();w.nodes[(1,1,0)]=Node('stair',True,full_cube=False,boxes=boxes)
   self.assertTrue(w.standable((1,2,0)))
   w.nodes[(1,3,0)]=Node('ceiling',True)
   self.assertFalse(w.standable((1,2,0)))
 def test_fence_body_collision_and_unknown_geometry(self):
  w=world();w.nodes[(1,0,0)]=Node('fence',True,full_cube=False,boxes=((-0.12,-.5,-.12,.12,1,.12),))
  self.assertFalse(w.standable((1,1,0)))
  w.nodes[(1,1,0)]=Node('custom',True,full_cube=False)
  self.assertFalse(w.standable((1,2,0)))
 def test_no_cutting_through_partial_wall(self):
  w=world();w.nodes[(1,1,0)]=Node('wall',True,full_cube=False,boxes=((-0.1,-.5,-.5,.1,.5,.5),))
  self.assertFalse(w.corridor_clear((0,.5,0),(3,.5,0)))
 def test_height_sampling_preserves_unknown_and_hazards(self):
  w=world();w.nodes[(1,1,0)]=Node('slab',True,full_cube=False,boxes=((-0.5,-0.5,-0.5,0.5,0,0.5),))
  del w.nodes[(1,2,0)]
  self.assertFalse(w.standable((1,1.5,0)))
  w.nodes[(1,2,0)]=Node('fire',False,damage=4)
  self.assertFalse(w.standable((1,1.5,0)))

 def test_underwater_opt_in_and_vertical_path(self):
  w=world()
  for y in (1,2,3):w.nodes[(0,y,0)]=Node('water',False,liquid=True,drowning=1)
  w.nodes[(0,4,0)]=Node('air',False);w.nodes[(0,5,0)]=Node('air',False)
  self.assertFalse(w.standable((0,2,0)))
  w.traversal=Traversal(allow_swim=True,allow_dive=True)
  self.assertTrue(w.standable((0,2,0)))
  self.assertIn((0,3,0),dict(w.neighbors((0,2,0))))
  path,_=w.path((0,2,0),lambda p:p==(0,4,0));self.assertIsNotNone(path)
  w.nodes[(0,3,0)]=Node('lava',False,liquid=True,damage=4)
  self.assertFalse(w.standable((0,2,0)))
 def test_dive_requires_swim(self):
  with self.assertRaises(ValueError):Traversal(allow_dive=True)
 def test_fractional_frontier_not_always_unknown(self):
  w=world();self.assertFalse(w.frontier((0,1.5,0)))
 def test_motion_swim_lease_and_validation(self):
  from test_polish import PolishTests
  from luanti_course.motion import Motion
  g,state,events=PolishTests().motion_game();g.capabilities=('steer','swim_height')
  with Motion(g) as motion:
   motion.steer(90,swim_y=2.5)
   self.assertEqual(events[-1][1]['swim_y'],2.5)
   for value in (True,float('nan'),float('inf'),40000):
    with self.assertRaises(ValueError):motion.steer(0,swim_y=value)
   with self.assertRaises(ValueError):motion.steer(0,jump=True,swim_y=2)
  self.assertEqual(events[-1][0],'stop')

 def test_water_goal_crossing_at_speed_is_not_arrival(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  from luanti_course.skills import navigate
  w=world();w.traversal=Traversal(allow_swim=True,allow_dive=True)
  for y in (1,2):w.nodes[(0,y,0)]=Node('water',False,liquid=True,drowning=1)
  state=SimpleNamespace(position=(0,.5,0),raw={'velocity':(0,-4,0)})
  ctx=SimpleNamespace(world=w,last=state,read=lambda r=0:state,game=SimpleNamespace(capabilities=('steer','swim_height')),blocked=set(),within=lambda p:True,log=lambda *a,**k:None,stop_input=lambda:None)
  def follow(*args):state.raw['velocity']=(0,0,0);return True,None
  with patch('luanti_course.skills.follow_path',side_effect=follow) as mock:
   navigate(ctx,(0,.5,0));self.assertEqual(mock.call_count,1)

if __name__=='__main__':unittest.main()
