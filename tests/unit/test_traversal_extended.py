import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course.navigation import Node,Traversal,World
from test_skills import world,AIR,STONE
from types import SimpleNamespace

class ExtendedTerrainTests(unittest.TestCase):
 def test_new_policy_validation(self):
  for k,values in {'max_drop':(-1,4,float('nan'),True),'max_gap':(0,4,True,1.5),'edit_budget':(-1,129,True),'build_with':('',4),'allow_dig':(1,),'allow_interact':(0,)}.items():
   for v in values:
    with self.subTest(k=k,v=v),self.assertRaises(ValueError):Traversal(**{k:v})
 def test_drop_is_explicit_and_bounded(self):
  w=world();w.nodes[(1,0,0)]=AIR;w.nodes[(1,-1,0)]=AIR;w.nodes[(1,-2,0)]=STONE
  self.assertNotIn((1,-1,0),dict(w.neighbors((0,1,0))))
  w.traversal=Traversal(max_drop=2);self.assertIn((1,-1,0),dict(w.neighbors((0,1,0))))
 def test_door_proposes_normal_interaction(self):
  w=world();w.nodes[(1,1,0)]=Node('door',True,full_cube=False,boxes=((-0.1,-.5,-.5,.1,.5,.5),),groups={'door':1})
  self.assertIn((1,1,0),dict(w.neighbors((0,1,0))))
  self.assertEqual(w.edge_actions[((0,1,0),(1,1,0))],(('interact',(1,1,0)),))
  w.traversal=Traversal(allow_interact=False);self.assertNotIn((1,1,0),dict(w.neighbors((0,1,0))))
 def test_gate_groups_not_name_guess(self):
  w=world();w.nodes[(1,1,0)]=Node('custom:gate',True,full_cube=False,boxes=((-0.1,-.5,-.5,.1,1,.5),),groups={'fence_gate':1})
  self.assertIn((1,1,0),dict(w.neighbors((0,1,0))))
 def test_dig_requires_opt_in(self):
  w=world();w.nodes[(1,1,0)]=STONE;w.nodes[(1,2,0)]=STONE
  self.assertNotIn((1,1,0),dict(w.neighbors((0,1,0))))
  w.traversal=Traversal(allow_dig=True);self.assertIn((1,1,0),dict(w.neighbors((0,1,0))))
  self.assertEqual({k for k,_ in w.edge_actions[((0,1,0),(1,1,0))]},{'dig'})
 def test_never_mine_falling_block(self):
  w=world();w.traversal=Traversal(allow_dig=True);w.nodes[(1,1,0)]=Node('sand',True,groups={'falling_node':1});w.nodes[(1,2,0)]=STONE
  self.assertIsNone(w.editable((0,1,0),(1,1,0)))
 def test_bridge_plan_never_invents_observed_block(self):
  w=world();w.nodes[(1,0,0)]=Node('air',False,buildable=True);w.traversal=Traversal(build_with='stone')
  self.assertEqual(w.editable((0,1,0),(1,1,0)),(('build',(1,0,0)),))
  self.assertEqual(w.nodes[(1,0,0)].name,'air')
 def test_bridge_does_not_fill_lava(self):
  w=world();w.nodes[(1,0,0)]=Node('lava',False,liquid=True,damage=4,buildable=True);w.traversal=Traversal(build_with='stone')
  self.assertIsNone(w.editable((0,1,0),(1,1,0)))
 def test_bridge_does_not_fill_unknown(self):
  w=world();del w.nodes[(1,0,0)];w.traversal=Traversal(build_with='stone');self.assertIsNone(w.editable((0,1,0),(1,1,0)))
 def test_two_gap_jump_uses_server_physics(self):
  w=world();w.traversal=Traversal(allow_jump_gaps=True)
  for x in (1,2):w.nodes[(x,0,0)]=AIR;w.nodes[(x,-1,0)]=AIR
  self.assertIn((3,1,0),dict(w.neighbors((0,1,0))))
  w.physics['jump_speed']=2;self.assertNotIn((3,1,0),dict(w.neighbors((0,1,0))))
 def test_jump_envelope_does_not_skip_middle_obstacle(self):
  w=world();w.nodes[(1,1,0)]=Node('short_wall',True,full_cube=False,boxes=((-0.1,-.5,-.5,.1,.5,.5),))
  self.assertFalse(w.sweep((0,1,0),(2,1,0),jump=True))
 def test_thin_support_does_not_allow_corner_cut(self):
  w=world();w.nodes[(1,0,0)]=Node('post',True,full_cube=False,boxes=((-0.1,-.5,-.1,.1,.5,.1),))
  self.assertTrue(w.supported((1,.5,0)))
  self.assertFalse(w.supported((1,.5,.3)))
  self.assertFalse(w.corridor_clear((0,.5,0),(2,.5,0)))
 def test_body_box_is_actual_size(self):
  w=world();w.height=2.8;w.nodes[(1,3,0)]=STONE;self.assertFalse(w.standable((1,1,0)))
 def test_world_update_clears_edit_plan(self):
  w=World();w.edge_actions[(1,2)]=('dig',)
  w.update(SimpleNamespace(raw={'nodes':[],'node_defs':{'air':{}},'physics':{'walk_speed':2,'collision_box':(-.3,0,-.3,.3,1.75,.3)}},position=(0,0,0)))
  self.assertEqual(w.edge_actions,{})
  self.assertEqual(w.physics['walk_speed'],2);self.assertAlmostEqual(w.height,1.75)
 def test_edit_budget_before_mutation(self):
  from luanti_course.skills import terrain_actions,Failure
  w=World(Traversal(allow_dig=True,edit_budget=0))
  ctx=SimpleNamespace(world=w,terrain_edits=0)
  with self.assertRaises(Failure) as e:terrain_actions(ctx,(('dig',(1,1,1)),))
  self.assertEqual(e.exception.reason,'terrain_edit_budget')

 def test_open_door_gets_asymmetric_clearance(self):
  w=world();w.radius=.332
  for y in (1,2):w.nodes[(1,y,0)]=Node('door_open',True,full_cube=False,boxes=((-0.5,-.5,-.5,.5,.5,-.3125),),groups={'door':1})
  self.assertTrue(w.standable((1,1,0)))
  self.assertGreater(w.point((1,1,0))[2],0)
  self.assertEqual(w.edge_plan((0,1,0),(1,1,0)),())
 def test_failed_door_not_retried_from_another_side(self):
  w=world();w.nodes[(1,1,0)]=Node('locked',True,full_cube=False,boxes=((-0.1,-.5,-.5,.1,.5,.5),),groups={'door':1})
  w.unusable.add((1,1,0));self.assertNotIn((1,1,0),dict(w.neighbors((0,1,0))))
 def test_resurface_retries_only_low_breath(self):
  from unittest.mock import patch
  from luanti_course.skills import navigate,Failure
  ctx=SimpleNamespace(world=World(Traversal(allow_swim=True,allow_dive=True)))
  with patch('luanti_course.skills._navigate',side_effect=[Failure('low_breath'),42]),patch('luanti_course.skills.regain_air') as recover:
   self.assertEqual(navigate(ctx,(0,1,0)),42);recover.assert_called_once()
  with patch('luanti_course.skills._navigate',side_effect=Failure('player_damaged')),patch('luanti_course.skills.regain_air') as recover:
   with self.assertRaises(Failure):navigate(ctx,(0,1,0))
   recover.assert_not_called()
 def test_resurface_retry_is_bounded(self):
  from unittest.mock import patch
  from luanti_course.skills import navigate,Failure
  ctx=SimpleNamespace(world=World(Traversal(allow_swim=True,allow_dive=True)))
  with patch('luanti_course.skills._navigate',side_effect=Failure('low_breath')),patch('luanti_course.skills.regain_air') as recover:
   with self.assertRaises(Failure):navigate(ctx,(0,1,0))
   self.assertEqual(recover.call_count,2)

 def test_surface_start_after_passive_sinking(self):
  w=world();w.traversal=Traversal(allow_swim=True)
  for x in range(-1,2):
   for z in range(-1,2):
    for y in (1,2,3):w.nodes[(x,y,z)]=Node('water',False,liquid=True,drowning=1)
    for y in (4,5,6):w.nodes[(x,y,z)]=AIR
  self.assertEqual(w.start((0,1.5,0)),(0,4,0))
  self.assertFalse(w.standable((0,2,0))) # no new diving permission
  w.nodes[(0,3,0)]=STONE
  self.assertIsNone(w.start((0,1.5,0))) # never ascend through a ceiling

 def test_vertical_swim_does_not_spin_for_centimetres_of_error(self):
  from luanti_course.skills import follow_path
  w=world();w.traversal=Traversal(allow_swim=True,allow_dive=True)
  for x in range(-2,3):
   for z in range(-2,3):
    for y in (1,2,3):w.nodes[(x,y,z)]=Node('water',False,liquid=True,drowning=1)
    for y in (4,5,6):w.nodes[(x,y,z)]=AIR
  state=SimpleNamespace(position=(.06,1.5,.04),yaw=33,raw={'velocity':(0,1,0),'in_liquid':True})
  sent=[]
  class Captured(Exception):pass
  def submit(op,**kw):sent.append(kw);raise Captured()
  game=SimpleNamespace(capabilities=('steer','swim_height'),_submit=submit)
  ctx=SimpleNamespace(world=w,game=game,read=lambda radius=0:state)
  with self.assertRaises(Captured):follow_path(ctx,[(0,2,0),(0,3,0)],(0,2.5,0))
  self.assertEqual(sent[0]['heading'],33);self.assertEqual(sent[0]['speed'],0)

if __name__=='__main__':unittest.main()
