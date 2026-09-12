import sys,unittest,math,threading
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Game,Traversal
from luanti_course.skills import ActionLock,follow_path
from luanti_course.navigation import World,Node
class Captured(Exception):pass
def pool():
 w=World();w.traversal=Traversal(allow_swim=True,allow_dive=True)
 for x in range(-3,10):
  for z in range(-3,10):
   for y in range(-4,5):w.nodes[x,y,z]=Node('water',False,liquid=True,drowning=1) if y<=0 else Node('air',False)
 return w

def first_steer(w,position,path,target):
 state=NS(position=position,eye=(position[0],position[1]+1.625,position[2]),yaw=-90,raw={'in_liquid':True,'velocity':(0,0,0)})
 calls=[]
 def submit(op,**kw):calls.append(kw);raise Captured()
 ctx=NS(world=w,read=lambda *a:state,game=NS(capabilities=('steer','swim_height'),_submit=submit),sleep=lambda t:None,recoveries={})
 try:follow_path(ctx,path,target)
 except Captured:pass
 return calls[0]
class NaturalnessTests(unittest.TestCase):
 def test_observation_reports_native_camera_rate_state(self):
  source=(Path(__file__).resolve().parents[2]/'engine/src/game_course.inc').read_text()
  self.assertIn('r["steering_yaw_velocity"] = m_course_steering.yaw_velocity',source)
  self.assertIn('r["steering_pitch_velocity"] = m_course_steering.pitch_velocity',source)
 def test_diagonal_open_water_does_not_alternate_grid_headings(self):
  path=[(0,1,0)]+[p for i in range(1,6) for p in ((i,1,i-1),(i,1,i))]
  command=first_steer(pool(),(0,.05,0),path,(5,.05,5))
  self.assertAlmostEqual(command['heading'],-45,places=3)
 def test_clear_ascending_swim_does_not_recenter_backwards(self):
  path=[(1,-2,0),(0,-2,0),(0,-1,0),(1,-1,0),(1,0,0),(1,1,0)]
  command=first_steer(pool(),(.65,-2.5,0),path,(1,.05,0))
  self.assertAlmostEqual(command['heading'],-90,places=3)
  self.assertAlmostEqual(command['swim_y'],.05,places=3)
 def test_short_press_native_lease_never_exceeds_requested_duration(self):
  clock=[0.];calls=[]
  class Cancel:
   def clear(self):pass
   def is_set(self):return False
   def wait(self,seconds):clock[0]+=seconds;return False
  game=Game.__new__(Game);game._motion=None;game._action_lock=ActionLock();game._skill_depth=0;game._cancel=Cancel();game._closed=False;game._epoch=1
  def submit(op,**kw):
   calls.append((op,kw))
   if op=='input':clock[0]+=.3 # Caller stalls after the accepted request.
  game._submit=submit;game.observe=lambda:NS(control='agent',control_epoch=1)
  with patch('luanti_course.client.time.monotonic',lambda:clock[0]):game.hold(['sneak','place'],.12)
  self.assertEqual(calls[-1][0],'stop')
  self.assertLessEqual(calls[0][1]['duration_ms'],120)
 def test_swim_shortcut_rejects_unknown_obstruction_and_lava(self):
  for obstacle in (None,Node('stone',True),Node('lava',False,liquid=True,damage=4)):
   w=pool()
   if obstacle is None:del w.nodes[2,1,2]
   else:w.nodes[2,1,2]=obstacle
   self.assertFalse(w.swim_corridor_clear((0,.05,0),(4,.05,4)))
 def test_swim_shortcut_requires_wet_support_along_whole_span(self):
  w=pool()
  for y in range(-4,1):w.nodes[2,y,0]=Node('air',False)
  self.assertFalse(w.swim_corridor_clear((0,.05,0),(4,.05,0)))
 def test_surface_policy_does_not_create_a_dive_shortcut(self):
  w=pool();w.traversal=Traversal(allow_swim=True)
  self.assertFalse(w.swim_corridor_clear((0,.05,0),(3,-2.5,0)))
 def test_surface_recovery_can_look_ahead_while_below_float_height(self):
  w=pool();w.traversal=Traversal(allow_swim=True)
  self.assertTrue(w.swim_corridor_clear((0,-.6,0),(3,.05,3)))
 def test_chosen_construction_station_is_used_before_moving_again(self):
  from luanti_course.construction import construction_station
  w=World();w.traversal=Traversal()
  for x in range(-5,10):
   for z in range(-5,10):
    for y in range(5):w.nodes[x,y,z]=Node('stone',True) if y==0 else Node('air',False,buildable=True)
  state=NS(position=(0,.5,0),eye=(0,2.125,0));calls=[]
  ctx=NS(last=state,world=w,within=lambda p:True,blocked=set(),log=lambda *a,**k:None)
  def move(c,p,**kw):
   calls.append(p);state.position=(p[0]-.08,p[1],p[2]-.17);state.eye=(state.position[0],p[1]+1.625,state.position[2])
  blocks=[('stone',(3,1,z)) for z in range(6)]
  with patch('luanti_course.construction.navigate',side_effect=move):
   construction_station(ctx,blocks);w.nodes[3,1,0]=Node('stone',True);construction_station(ctx,blocks[1:])
  self.assertEqual(len(calls),1)
 def test_mining_step_keeps_the_next_work_face_in_view(self):
  from luanti_course.excursions import mining_job
  state=NS(position=(0,99.5,0),eye=(0,101.125,0));calls=[]
  ctx=NS(game=NS(endpoint=Path('/fixture'),_mining_trip=None),world=NS(traversal=Traversal(),height=1.75,nodes={}),radius=20,details={},read=lambda *a:state,log=lambda *a,**k:None)
  with patch('luanti_course.excursions.close_form'),patch('luanti_course.excursions.trail_to'),patch('luanti_course.excursions.preflight_step',return_value=[]),patch('luanti_course.excursions.navigate',side_effect=lambda *args,**kw:calls.append(kw)):
   mining_job(ctx,'dig_down',1,heading=(1,0,0))
  self.assertAlmostEqual(calls[0]['look_direction'][0],-90)
  self.assertAlmostEqual(calls[0]['look_direction'][1],math.degrees(math.atan2(.125,1)))
 def test_upward_stair_jump_never_chases_the_passed_tread_backwards(self):
  state=NS(position=(.7,99.53,0),yaw=90,raw={'velocity':(-2,1,0),'touching_ground':False})
  w=NS(point=lambda p:(p[0],p[1]-.5,p[2]),surface_water=lambda p:False,swimmable=lambda p:False,ladder=lambda p:False,standable=lambda p:True,start=lambda p:(1,99,0),corridor_clear=lambda *a:False,physics={'step_height':.6,'walk_speed':4})
  calls=[]
  def submit(op,**kw):calls.append(kw);raise Captured()
  ctx=NS(world=w,read=lambda *a:state,game=NS(capabilities=('steer',),_submit=submit),recoveries={})
  try:follow_path(ctx,[(2,98,0),(1,99,0),(0,100,0)],(0,99.5,0))
  except Captured:pass
  self.assertAlmostEqual(calls[0]['heading'],90)
 def test_airborne_arrival_waits_without_turning_on_tiny_horizontal_error(self):
  state=NS(position=(-.03,1.3,0),yaw=90,raw={'velocity':(0,-1,0),'touching_ground':False})
  w=NS(point=lambda p:(p[0],p[1]-.5,p[2]),surface_water=lambda p:False,swimmable=lambda p:False,ladder=lambda p:False,standable=lambda p:True,start=lambda p:(0,1,0),corridor_clear=lambda *a:False,physics={'step_height':.6,'walk_speed':4})
  calls=[]
  def submit(op,**kw):calls.append(kw);raise Captured()
  ctx=NS(world=w,read=lambda *a:state,game=NS(capabilities=('steer',),_submit=submit),recoveries={})
  try:follow_path(ctx,[(0,1,0)],(0,.5,0))
  except Captured:pass
  self.assertEqual(calls[0]['speed'],0)
  self.assertEqual(calls[0]['heading'],90)
 def test_eating_with_clear_view_does_not_force_the_camera_up(self):
  from luanti_course.survival import eat
  remaining=[1];state=NS(eye=(0,2,0),pointed_node=None,inventory={'main':NS(find=lambda item:0)})
  ctx=NS(book=NS(resolve=lambda i:i,items={'apple':{'groups':{'eatable':4}}}),read=lambda:state,details={},deadline=1e20,game=NS(_submit=lambda *a,**k:remaining.__setitem__(0,0)),sleep=lambda t:None,stop_input=lambda:None,log=lambda *a,**k:None)
  with patch('luanti_course.survival.close_form'),patch('luanti_course.survival.wield_slot'),patch('luanti_course.survival.count_items',side_effect=lambda *a:remaining[0]),patch('luanti_course.survival.face') as face:
   eat.__wrapped__(ctx,'apple',1)
   face.assert_not_called()
  self.assertEqual(ctx.details['consumed'],1)
if __name__=='__main__':unittest.main()
