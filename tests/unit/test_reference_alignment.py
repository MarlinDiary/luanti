"""Regression contracts from the pinned Mindcraft behavior comparison."""
import sys, threading, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Entity, RecipeBook, SurvivalConfig
from luanti_course.skills import Context, Failure
from luanti_course.supervisor import Survival
from luanti_course.combat import defend, flee
from test_survival import state, entity
from test_retreat_tracking import ground

class ReferenceAlignmentTests(unittest.TestCase):
 def context(self, observed):
  g=NS(_epoch=1,_cancel=threading.Event(),observe=lambda r=0:observed,recipe_book=RecipeBook.voxelibre())
  guard=Survival(g);g._survival=guard;guard._thread=threading.current_thread();guard._busy=True
  guard._active_choice={'action':'eat_best_food','reason':'hunger'};guard._pending=guard._active_choice
  return Context(g,5,32,g.recipe_book),guard
 def test_threat_preempts_running_food_reaction(self):
  c,guard=self.context(state(entities=(entity(pointable=True),)))
  with self.assertRaises(Failure) as e:c.read()
  self.assertEqual(e.exception.reason,'survival_interrupted')
  self.assertEqual(guard.pending['action'],'flee_from')
 def test_fire_preempts_running_flee(self):
  c,guard=self.context(state(hazards=[{'name':'fire'}]))
  guard._active_choice={'action':'flee_from','reason':'nearby_hostile'}
  with self.assertRaises(Failure) as e:c.read()
  self.assertEqual(e.exception.reason,'survival_interrupted')
  self.assertEqual(guard.pending['action'],'escape_hazard')
 def test_air_preemption_is_not_just_low_breath_failure(self):
  c,guard=self.context(state(breath=3))
  guard._active_choice={'action':'defend_self','reason':'nearby_hostile'}
  with self.assertRaises(Failure) as e:c.read()
  self.assertEqual(e.exception.reason,'survival_interrupted')
  self.assertEqual(guard.pending['action'],'recover_air')
 def test_equal_priority_does_not_restart_same_reaction(self):
  c,guard=self.context(state(entities=(entity(pointable=True),)))
  guard._active_choice={'action':'flee_from','reason':'nearby_hostile'}
  self.assertEqual(c.read().hp,20);self.assertFalse(guard.interrupted())
 def test_incoming_arrow_does_not_churn_a_committed_retreat(self):
  arrow=Entity(20,30,'mcl_bows:arrow_entity',(0,1,5),(0,1,5),(0,0,-8),pointable=False)
  c,guard=self.context(state(entities=(entity(pointable=True),arrow)))
  guard._active_choice={'action':'flee_from','reason':'nearby_hostile'}
  self.assertEqual(c.read().hp,20)
  self.assertFalse(guard.interrupted())
  self.assertFalse(guard.events())
 def test_incoming_arrow_still_preempts_stationary_reaction(self):
  arrow=Entity(20,30,'mcl_bows:arrow_entity',(0,1,5),(0,1,5),(0,0,-8),pointable=False)
  c,guard=self.context(state(entities=(entity(pointable=True),arrow)))
  with self.assertRaises(Failure):c.read()
  self.assertEqual(guard.pending['action'],'avoid_projectile')
 def test_lower_priority_does_not_interrupt_air(self):
  c,guard=self.context(state(entities=(entity(pointable=True),)))
  guard._active_choice={'action':'recover_air','reason':'low_breath'}
  c.read();self.assertFalse(guard.interrupted())
 def test_lost_control_precedes_reaction_selection(self):
  c,guard=self.context(state(control_epoch=2,entities=(entity(pointable=True),)))
  with self.assertRaises(Failure) as e:c.read()
  self.assertEqual(e.exception.reason,'control_released')
  self.assertEqual(guard.pending['action'],'eat_best_food')
 def test_defense_retargets_and_keeps_attack_cooldown(self):
  a=entity(id=1,instance=1,pointable=True)
  b=entity(id=2,instance=2,pointable=True)
  hits=[];now=[0.];current=[a]
  def snap():
   e=current[0]
   return state(entities=(() if e is None else (e,)),weapons=[dict(slot=0,name='sword',interval=.625,usable=False)],wield=0,
     pointed_entity={} if e is None else {'id':e.id,'instance':e.instance})
  def submit(op,**kw):
   hits.append((kw['target_id'],now[0]));current[0]=b if len(hits)==1 else None
  def read(*args):
   if now[0]>4:raise AssertionError('defense did not terminate')
   return snap()
  c=NS(read=read,details={},game=NS(capabilities={'attack'},_submit=submit),stop_input=lambda:None,
    sleep=lambda t:now.__setitem__(0,now[0]+t),log=lambda *a,**k:None)
  with patch('luanti_course.combat.current_target',lambda ctx,ref:(snap(),current[0] if current[0] and current[0].ref==ref else None)),patch('luanti_course.combat.close_form'),patch('luanti_course.combat.equip_best'),patch('luanti_course.combat.face'),patch('luanti_course.combat.time.monotonic',lambda:now[0]):
   defend(c)
  self.assertEqual([i for i,t in hits],[1,2])
  self.assertGreaterEqual(hits[1][1]-hits[0][1],.625)
  self.assertEqual(c.details['attacks_submitted'],2)
  self.assertIsNone(c.details['killed'])
 def flee_case(self, approaching=False):
  now=[0.];moves=[];e=Entity(1,1,'mobs_mc:zombie',(0,.5,-14),(0,2,-14),(0,0,0),pointable=True)
  def read(*args):
   pos=(0,.5,-13) if approaching and now[0]>=.2 else e.position
   mob=Entity(e.id,e.instance,e.name,pos,pos,e.velocity,pointable=True)
   return NS(position=(0,.5,0),raw={'entities_available':True,'entities':[]},entities=(mob,))
  def follow(*a,**kw):moves.append(True);raise Failure('test_movement_requested')
  c=NS(read=read,world=ground(),details={},within=lambda p:True,stop_input=lambda:None,
    sleep=lambda t:now.__setitem__(0,now[0]+t),log=lambda *a,**k:None)
  with patch('luanti_course.combat.close_form'),patch('luanti_course.combat.follow_path',follow),patch('luanti_course.combat.time.monotonic',lambda:now[0]):
   if approaching:
    with self.assertRaises(Failure) as x:flee(c,(e,),14)
    self.assertEqual(x.exception.reason,'test_movement_requested');self.assertTrue(moves)
   else:
    flee(c,(e,),14);self.assertGreaterEqual(now[0],1.)
    self.assertEqual(c.details['outcome'],'distance_reached')
 def test_flee_threshold_must_remain_clear(self):self.flee_case()
 def test_reapproaching_pursuer_resumes_retreat(self):self.flee_case(True)

 def test_preempted_reaction_keeps_damage_trace(self):
  c,guard=self.context(state(hp=17,entities=(entity(pointable=True),)))
  c.hp=20
  with self.assertRaises(Failure):c.read()
  self.assertEqual(c.damage_taken,3)
  self.assertEqual(c.trace[-1]['event'],'damage_observed')
  self.assertEqual(guard.events()[-1]['hp'],17)
 def test_death_precedes_reaction_selection(self):
  c,guard=self.context(state(dead=True,entities=(entity(pointable=True),)))
  with self.assertRaises(Failure) as e:c.read()
  self.assertEqual(e.exception.reason,'player_dead')
  self.assertEqual(guard.pending['action'],'eat_best_food')
 def test_one_preemption_event_per_reaction(self):
  c,guard=self.context(state(entities=(entity(pointable=True),)))
  for _ in range(3):
   with self.assertRaises(Failure):c.read()
  self.assertEqual(len(guard.events()),1)
 def test_external_observer_does_not_preempt_worker(self):
  c,guard=self.context(state(entities=(entity(pointable=True),)))
  guard._thread=object()
  guard.on_observation(c.game.observe())
  self.assertEqual(guard.pending['action'],'eat_best_food');self.assertFalse(guard.events())
 def test_critical_health_preempts_defense(self):
  c,guard=self.context(state(hp=4,entities=(entity(pointable=True),)))
  guard.config=SurvivalConfig(enemies='defend')
  guard._active_choice={'action':'defend_self','reason':'nearby_hostile'}
  with self.assertRaises(Failure):c.read()
  self.assertEqual(guard.pending['reason'],'critical_health')
 def test_settle_configuration_is_bounded(self):
  for v in (0,-1,True,float('nan'),6):
   with self.assertRaises(ValueError):SurvivalConfig(settle_time=v)
 def test_truncated_entity_observation_is_not_clearance(self):
  c=NS(read=lambda r=0:NS(raw={'entities_available':True,'entities':[],'entities_truncated':True}),details={})
  with patch('luanti_course.combat.close_form'),self.assertRaises(Failure) as e:flee(c)
  self.assertEqual(e.exception.reason,'entity_observation_truncated')
 def test_explicit_attack_keeps_selected_target(self):
  from luanti_course.combat import attack
  a=entity(id=1,instance=1,pointable=True);b=entity(id=2,instance=2,pointable=True)
  s=state(entities=(b,a),pointed_entity={'id':1,'instance':1},weapons=[dict(slot=0,name='sword',interval=.625,usable=False)],wield=0)
  hits=[];c=NS(game=NS(capabilities={'attack'},_submit=lambda op,**kw:hits.append(kw['target_id'])),details={},sleep=lambda t:None,log=lambda *a,**k:None)
  with patch('luanti_course.combat.current_target',return_value=(s,a)),patch('luanti_course.combat.close_form'),patch('luanti_course.combat.face'):
   attack(c,a,one_hit=True,auto_equip=False)
  self.assertEqual(hits,[1])

if __name__=='__main__':unittest.main()
