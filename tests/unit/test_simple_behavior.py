import sys,unittest,math
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course.skills import follow_path
from luanti_course.navigation import World,Node
class Captured(Exception):pass
def ground():
 w=World()
 for x in range(-8,9):
  for z in range(-8,9):
   for y in range(-1,4):w.nodes[x,y,z]=Node('stone',True) if y<=0 else Node('air',False)
 return w

def heading(w,path,target):
 state=NS(position=(0,.5,0),yaw=0,raw={'in_liquid':False,'velocity':(0,0,0),'touching_ground':True})
 calls=[]
 def submit(op,**kw):calls.append(kw);raise Captured()
 ctx=NS(world=w,read=lambda *a:state,game=NS(capabilities=('steer',),_submit=submit),recoveries={})
 try:follow_path(ctx,path,target)
 except Captured:pass
 return calls[0]['heading']
class SimpleBehavior(unittest.TestCase):
 def test_flat_diagonal_looks_at_visible_destination_not_lattice_corner(self):
  for sx,sz in ((1,1),(-1,1),(1,-1),(-1,-1)):
   path=[(0,1,0)]+[p for i in range(1,6) for p in ((i*sx,1,(i-1)*sz),(i*sx,1,i*sz))]
   self.assertAlmostEqual(heading(ground(),path,(5*sx,.5,5*sz)),math.degrees(math.atan2(-sx,sz)),places=4)
 def test_flat_shortcut_never_cuts_a_wall_or_missing_floor(self):
  for p,node in [((2,1,2),Node('stone',True)),((2,0,2),Node('air',False)),((2,1,2),None),((2,1,2),Node('lava',False,liquid=True,damage=4))]:
   w=ground()
   if node is None:del w.nodes[p]
   else:w.nodes[p]=node
   self.assertFalse(w.corridor_clear((0,.5,0),(5,.5,5)))
 def test_flat_shortcut_keeps_full_player_width(self):
  w=ground();w.nodes[2,1,3]=Node('stone',True)
  self.assertFalse(w.corridor_clear((0,.5,.45),(5,.5,5.45)))

class SettlingBehavior(unittest.TestCase):
 def test_intermediate_drop_does_not_turn_back_on_centimetre_error(self):
  w=NS(point=lambda p:(p[0],p[1]-.5,p[2]),surface_water=lambda p:False,swimmable=lambda p:False,ladder=lambda p:False,standable=lambda p:True,start=lambda p:(3,99,0),corridor_clear=lambda *a:False,physics={'step_height':.6,'walk_speed':4})
  state=NS(position=(3.07,98.25,0),yaw=-90,raw={'velocity':(.5,-7,0),'touching_ground':False})
  calls=[]
  def submit(op,**kw):calls.append(kw);raise Captured()
  ctx=NS(world=w,read=lambda *a:state,game=NS(capabilities=('steer',),_submit=submit),recoveries={})
  try:follow_path(ctx,[(2,100,0),(3,98,0),(4,98,0)],(4,97.5,0))
  except Captured:pass
  self.assertEqual(calls[0]['heading'],-90);self.assertEqual(calls[0]['speed'],0)
 def test_gap_runup_backs_away_while_watching_landing(self):
  from collections import Counter
  w=NS(point=lambda p:(p[0],p[1]-.5,p[2]),surface_water=lambda p:False,swimmable=lambda p:False,ladder=lambda p:False,standable=lambda p:True,start=lambda p:(round(p[0]),100,0),corridor_clear=lambda a,b:abs(a[0]-b[0])<2,physics={'step_height':.6,'walk_speed':4})
  state=NS(position=(2,99.5,0),eye=(2,101.125,0),yaw=0,raw={'velocity':(0,0,0),'touching_ground':True})
  calls=[]
  def submit(op,**kw):calls.append(kw);raise Captured()
  ctx=NS(world=w,read=lambda *a:state,game=NS(capabilities=('steer','independent_heading'),_submit=submit),recoveries=Counter(),log=lambda *a,**k:None)
  try:follow_path(ctx,[(2,100,0),(5,100,0)],(5,99.5,0))
  except Captured:pass
  self.assertEqual(calls[0]['heading'],-90);self.assertEqual(calls[0]['move_heading'],90)
 def test_ice_arrival_is_not_success_while_still_sliding(self):
  w=ground();w.nodes[0,0,0]=Node('ice',True,groups={'slippery':3});w.physics['ground_acceleration']=30
  state=NS(position=(0,.5,0),eye=(0,2.125,0),yaw=-90,raw={'velocity':(1.5,0,0),'touching_ground':True})
  calls=[]
  def submit(op,**kw):calls.append(kw);raise Captured()
  ctx=NS(world=w,read=lambda *a:state,game=NS(capabilities=('steer',),_submit=submit),recoveries={})
  try:follow_path(ctx,[(0,1,0)],(.2,.5,0))
  except Captured:pass
  self.assertEqual(len(calls),1);self.assertEqual(calls[0]['speed'],0);self.assertEqual(calls[0]['heading'],-90)
 def test_wall_eating_keeps_aim_but_adjacent_soil_retains_air_use(self):
  from unittest.mock import patch
  from luanti_course.survival import eat
  for soil,expected in ((0,False),(2,True),(None,True)):
   remaining=[1];state=NS(eye=(0,2,0),pointed_node=(0,1,2),raw={'pointed_above':[0,1,1]},inventory={'main':NS(find=lambda i:0)})
   nodes={} if soil is None else {(0,0,1):Node('floor',True,groups={'soil':soil})}
   ctx=NS(book=NS(resolve=lambda i:i,items={'apple':{'type':'craft','groups':{'eatable':4}}}),world=NS(nodes=nodes),read=lambda *a:state,details={},deadline=1e20,game=NS(_submit=lambda *a,**k:remaining.__setitem__(0,0)),sleep=lambda t:None,stop_input=lambda:None,log=lambda *a,**k:None)
   with patch('luanti_course.survival.close_form'),patch('luanti_course.survival.wield_slot'),patch('luanti_course.survival.count_items',side_effect=lambda *a:remaining[0]),patch('luanti_course.survival.face') as face:
    eat.__wrapped__(ctx,'apple',1)
    self.assertEqual(face.called,expected)

class StairPrecision(unittest.TestCase):
 def test_rotated_centre_edge_roundoff_keeps_stair_top_support(self):
  for box in ((-.5,0,-.5,.5,.5,-6.123e-17),(-.5,0,-.5,-6.123e-17,.5,.5)):
   w=ground();w.nodes[3,1,0]=Node('stair',True,full_cube=False,boxes=((-.5,-.5,-.5,.5,0,.5),box))
   self.assertIn(2.,w.support_heights(3,0,1))
   self.assertTrue(w.standable((3,2.,0)))
 def test_tolerance_does_not_cover_a_real_gap(self):
  w=ground();w.nodes[3,1,0]=Node('offset',True,full_cube=False,boxes=((-.5,0,-.5,-.01,.5,.5),))
  self.assertNotIn(2.,w.support_heights(3,0,1))

class ObservedRayBehavior(unittest.TestCase):
 def context(self,w):
  from collections import Counter
  state=NS(position=(0,.5,0),raw={'velocity':(0,0,0)})
  return NS(world=w,read=lambda *a:state,game=NS(capabilities=('steer',)),radius=20,within=lambda p:True,blocked=set(),log=lambda *a,**k:None,stop_input=lambda:None,recoveries=Counter())
 def test_distant_goal_preserves_bearing_without_inventing_terrain(self):
  from luanti_course.skills import _navigate
  from unittest.mock import patch
  w=ground();ctx=self.context(w);captured=[]
  def follow(*args,**kwargs):captured.append(args);raise Captured()
  with patch.object(w,'path',side_effect=AssertionError('unneeded lattice frontier')),patch('luanti_course.skills.follow_path',side_effect=follow):
   with self.assertRaises(Captured):_navigate(ctx,(12,.625,2))
  endpoint=captured[0][2];self.assertAlmostEqual(endpoint[0]/endpoint[2],6);self.assertEqual(endpoint[1],.5);self.assertTrue(captured[0][4])
 def test_unknown_or_obstructed_ray_falls_back_to_graph(self):
  from luanti_course.skills import _navigate
  from unittest.mock import patch
  for obstacle in (None,Node('wall',True),Node('lava',False,liquid=True,damage=4)):
   w=ground()
   if obstacle is None:del w.nodes[2,1,0]
   else:w.nodes[2,1,0]=obstacle
   with patch.object(w,'path',side_effect=Captured()):
    with self.assertRaises(Captured):_navigate(self.context(w),(12,.5,0))
 def test_new_obstacle_invalidates_previously_clear_shortcut(self):
  w=ground();calls=[];reads=[0]
  state=NS(position=(0,.5,0),yaw=-45,raw={'in_liquid':False,'velocity':(1,0,1),'touching_ground':True})
  def read(*a):
   reads[0]+=1
   if reads[0]>1:w.nodes[2,1,2]=Node('wall',True)
   return state
  ctx=NS(world=w,read=read,game=NS(capabilities=('steer',),_submit=lambda op,**kw:calls.append(kw)),recoveries={},sleep=lambda t:None)
  path=[(0,1,0)]+[p for i in range(1,6) for p in ((i,1,i-1),(i,1,i))]
  ok,edge=follow_path(ctx,path,(5,.5,5))
  self.assertFalse(ok);self.assertEqual(len(calls),1);self.assertIsNotNone(edge)

if __name__=='__main__':unittest.main()
