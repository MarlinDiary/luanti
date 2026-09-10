import sys,unittest,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course.combat import flee
from luanti_course.skills import Failure
from luanti_course.navigation import World,Node,Traversal,distance
from luanti_course import Entity

class FleeProgressTests(unittest.TestCase):
 def context(self):
  # A short known corridor offers 1.5 blocks of real improvement, not 3.
  w=World(Traversal(allow_interact=False));air=Node('air',False);stone=Node('stone',True)
  for x in range(-1,2):
   for z in range(-1,3):
    w.nodes[(x,0,z)]=stone
    for y in (1,2,3):w.nodes[(x,y,z)]=air
  e=Entity(1,1,'mobs_mc:zombie',(0,.5,-3),(0,2,-3),(0,0,0),pointable=True)
  states=[SimpleNamespace(position=(0,.5,0),raw={'entities_available':True,'entities':[]},entities=(e,))]
  c=SimpleNamespace(world=w,within=lambda p:True,read=lambda r=0:states[-1],stop_input=lambda:None,
   details={},log=lambda *a,**kw:None,sleep=lambda s:None)
  return c,states
 def test_partial_known_progress_is_not_route_failure(self):
  c,states=self.context();moves=[]
  def follow(ctx,path,target,*args,**kw):
   moves.append(path);states[-1]=SimpleNamespace(position=target,raw={'entities_available':True,'entities':[]},entities=())
   return True,None
  with patch('luanti_course.combat.close_form'),patch('luanti_course.combat.follow_path',follow):flee(c,safe_distance=12)
  self.assertTrue(moves);self.assertGreater(distance(c.world.point(moves[0][-1]),(0,.5,-3)),3.25)
 def test_unreachable_unknown_stays_blocked(self):
  c,states=self.context();c.world.nodes={}
  with patch('luanti_course.combat.close_form'),self.assertRaises(Failure) as e:flee(c,safe_distance=12)
  self.assertEqual(e.exception.reason,'escape_route_unavailable')
class ReactionCooldownTests(unittest.TestCase):
 def test_failed_escape_rechecks_without_three_second_freeze(self):
  from luanti_course.skills import SkillResult
  from luanti_course.supervisor import reaction_cooldown
  self.assertLessEqual(reaction_cooldown(SkillResult('flee_from','blocked','escape_route_unavailable')),.15)
 def test_non_emergency_failure_still_backs_off(self):
  from luanti_course.skills import SkillResult
  from luanti_course.supervisor import reaction_cooldown
  self.assertEqual(reaction_cooldown(SkillResult('eat_best_food','blocked','no_suitable_food')),3)
if __name__=='__main__':unittest.main()

class MovingAimRaceTests(unittest.TestCase):
 def context(self,errors):
  from unittest.mock import Mock
  from luanti_course import ActionError
  e=Entity(1,2,'mobs_mc:zombie',(0,.5,2),(0,1.5,2),(0,0,-1),pointable=True)
  state=SimpleNamespace(position=(0,.5,0),pointed_entity=e.ref,raw={'weapons':[{'slot':0,'usable':False,'interval':.6}],'wield':0})
  g=SimpleNamespace(capabilities={'attack'},_submit=Mock(side_effect=errors))
  c=SimpleNamespace(game=g,details={},log=Mock(),sleep=Mock(),stop_input=Mock())
  return c,e,state
 def test_moving_crosshair_reaims_without_counting_rejected_hit(self):
  from luanti_course import ActionError
  from luanti_course.combat import attack
  c,e,s=self.context([ActionError('entity_not_in_crosshair'),None])
  with patch('luanti_course.combat.current_target',return_value=(s,e)),patch('luanti_course.combat.close_form'),patch('luanti_course.combat.face'):
   attack(c,e,one_hit=True,auto_equip=False)
  self.assertEqual(c.game._submit.call_count,2);self.assertEqual(c.details['attacks_submitted'],1)
 def test_control_loss_is_not_retried(self):
  from luanti_course import ActionError
  from luanti_course.combat import attack
  c,e,s=self.context([ActionError('control_released')])
  with patch('luanti_course.combat.current_target',return_value=(s,e)),patch('luanti_course.combat.close_form'),patch('luanti_course.combat.face'),self.assertRaises(ActionError):
   attack(c,e,one_hit=True,auto_equip=False)
  self.assertEqual(c.game._submit.call_count,1)
 def test_stale_entity_is_not_retargeted(self):
  from luanti_course import ActionError
  from luanti_course.combat import attack
  c,e,s=self.context([ActionError('stale_entity')])
  with patch('luanti_course.combat.current_target',return_value=(s,e)),patch('luanti_course.combat.close_form'),patch('luanti_course.combat.face'),self.assertRaises(ActionError):
   attack(c,e,one_hit=True,auto_equip=False)
  self.assertEqual(c.game._submit.call_count,1)

class ChaseHorizonTests(unittest.TestCase):
 def test_visible_entity_outside_map_horizon_is_approached_in_stages(self):
  from luanti_course.combat import chase
  from unittest.mock import Mock
  w=World(Traversal(allow_interact=False));air=Node('air',False);stone=Node('stone',True)
  for x in range(-1,2):
   for z in range(-1,7):
    w.nodes[(x,0,z)]=stone
    for y in (1,2,3):w.nodes[(x,y,z)]=air
  state=SimpleNamespace(position=(0,.5,0));target=Entity(1,1,'mobs_mc:zombie',(0,.5,12),(0,1.5,12),(0,0,0),pointable=True)
  c=SimpleNamespace(world=w,within=lambda p:True,movement_look_target=None)
  with patch('luanti_course.combat.follow_path',return_value=(True,None)) as move:chase(c,state,target)
  self.assertTrue(move.called);self.assertLess(distance(move.call_args.args[2],target.position),12)
