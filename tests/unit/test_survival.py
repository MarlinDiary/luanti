import sys,unittest,threading,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Game,Entity,Snapshot,RecipeBook,SurvivalConfig,ActionError
from luanti_course.entities import hunger_from_hud,hostiles,target_ref
from luanti_course.combat import food_choice,attack,defend,BANNED_FOOD
from luanti_course.supervisor import decide,Survival
from luanti_course.skills import Context,Failure,ActionLock,run,SkillResult
from test_sdk import snapshot

def entity(name='mobs_mc:skeleton',id=2,instance=10,**kw):
 return Entity(id,instance,name,(0,1,2),(0,2,2),(0,0,0),**kw)
def state(hunger=10,entities=(),**kw):
 raw=snapshot(control='agent',entities_available=True,entities_truncated=False,entities=[dict(id=e.id,instance=e.instance,name=e.name,position=e.position,aim=e.aim,velocity=e.velocity,is_player=e.is_player,pointable=e.pointable,immortal=e.engine_immortal) for e in entities],hud_statbars=[dict(texture='hbhunger_icon.png',background='hbhunger_bgicon.png',number=hunger,max=20)],**kw)
 return Snapshot.from_dict(raw)

class ObservationTests(unittest.TestCase):
 def test_hunger_known(self):self.assertEqual(state().hunger,10)
 def test_hunger_missing_unknown(self):self.assertIsNone(hunger_from_hud({}))
 def test_hunger_custom_scale_unknown(self):
  r=state().raw;r['hud_statbars'][0]['max']=40;self.assertIsNone(hunger_from_hud(r))
 def test_hunger_ambiguous_unknown(self):
  r=state().raw;r['hud_statbars']*=2;self.assertIsNone(hunger_from_hud(r))
 def test_hunger_zero_is_not_missing(self):self.assertEqual(state(hunger=0).hunger,0)
 def test_hunger_malformed_unknown(self):self.assertIsNone(state(hunger=True).hunger)
 def test_hunger_hidden_texture_unknown(self):
  r=state().raw;r['hud_statbars'][0]['texture']='';self.assertIsNone(hunger_from_hud(r))
 def test_native_name_and_identity(self):self.assertEqual(state(entities=(entity(),)).entities[0].ref,(2,10))
 def test_player_never_hostile(self):self.assertFalse(entity(is_player=True).hostile)
 def test_unknown_mod_is_unknown(self):self.assertFalse(entity(name='custom:skeleton').hostile)
 def test_neutral_is_not_hostile(self):self.assertFalse(entity(name='mobs_mc:cow').hostile)
 def test_stale_instance_is_distinct(self):self.assertNotEqual(entity().ref,entity(instance=11).ref)
 def test_target_requires_snapshot_object(self):
  with self.assertRaises(ValueError):target_ref(2)
 def test_pvp_rejected(self):
  with self.assertRaises(ValueError):target_ref(entity(is_player=True,pointable=True))
 def test_script_health_mobs_are_attackable(self):
  self.assertEqual(target_ref(entity(engine_immortal=True,pointable=True)),(2,10))

class PolicyTests(unittest.TestCase):
 def setUp(self):self.config=SurvivalConfig();self.book=RecipeBook.voxelibre()
 def test_default_is_avoid_not_competing_attack(self):
  self.assertEqual(decide(state(entities=(entity(),)),self.config,self.book)['action'],'flee_from')
 def test_explicit_defense(self):
  self.assertEqual(decide(state(entities=(entity(),)),SurvivalConfig(enemies='defend'),self.book)['action'],'defend_self')
 def test_critical_hp_overrides_defend(self):
  self.assertEqual(decide(state(hp=4,entities=(entity(),)),SurvivalConfig(enemies='defend'),self.book)['reason'],'critical_health')
 def test_air_priority(self):
  self.assertEqual(decide(state(breath=3,entities=(entity(),)),self.config,self.book)['action'],'recover_air')
 def test_contact_hazard(self):
  self.assertEqual(decide(state(hazards=[{'name':'fire'}]),self.config,self.book)['action'],'escape_hazard')
 def test_manual_is_untouched(self):
  s=state(entities=(entity(),));s.raw['control']='manual';s=Snapshot.from_dict(s.raw)
  self.assertIsNone(decide(s,self.config,self.book))
 def test_death_no_auto_respawn(self):self.assertIsNone(decide(state(dead=True),self.config,self.book))
 def test_modes_disabled(self):self.assertIsNone(decide(state(entities=(entity(),)),SurvivalConfig(enemies='off',self_preservation=False,auto_eat=False),self.book))
 def test_distance_hysteresis(self):
  with self.assertRaises(ValueError):SurvivalConfig(threat_radius=14,safe_distance=12)
 def test_invalid_configuration(self):
  for args in ({'auto_eat':1},{'poll_interval':float('nan')},{'poll_interval':.001},{'enemies':'attack_everything'}):
   with self.assertRaises(ValueError):SurvivalConfig(**args)
 def test_no_food_no_fabrication(self):self.assertIsNone(food_choice(state(),self.book))
 def test_excludes_unsafe_food(self):
  s=state(inventory={'main':{'width':9,'items':[{'name':n,'count':1} for n in BANNED_FOOD]}})
  self.assertIsNone(food_choice(s,self.book))
 def test_choose_held_food(self):
  s=state(inventory={'main':{'width':9,'items':[{'name':'mcl_core:apple','count':2}]}})
  self.assertEqual(food_choice(s,self.book),'mcl_core:apple');self.assertEqual(decide(s,self.config,self.book)['action'],'eat_best_food')

class HealthTests(unittest.TestCase):
 def ctx(self):
  g=SimpleNamespace(_epoch=1,_cancel=threading.Event(),observe=lambda r=0:state(),_survival=None)
  return Context(g,5,32,RecipeBook.voxelibre())
 def test_normal_damage_still_interrupts(self):
  c=self.ctx();c.read();c.game.observe=lambda r=0:state(hp=18)
  with self.assertRaises(Failure) as x:c.read()
  self.assertEqual(x.exception.reason,'player_damaged')
 def test_bounded_damage_continues(self):
  c=self.ctx();c.damage_budget=8;c.read();c.game.observe=lambda r=0:state(hp=18);self.assertEqual(c.read().hp,18)
  self.assertEqual(c.damage_taken,2)
 def test_budget_is_cumulative(self):
  c=self.ctx();c.damage_budget=3;c.read();c.game.observe=lambda r=0:state(hp=18);c.read();c.game.observe=lambda r=0:state(hp=16)
  with self.assertRaises(Failure) as x:c.read()
  self.assertEqual(x.exception.reason,'damage_budget_exceeded')
 def test_floor_applies_at_start(self):
  c=self.ctx();c.min_hp=6;c.game.observe=lambda r=0:state(hp=5)
  with self.assertRaises(Failure) as x:c.read()
  self.assertEqual(x.exception.reason,'health_floor')
 def test_cancel_always_wins(self):
  c=self.ctx();c.damage_budget=100;c.game._cancel.set()
  with self.assertRaises(Failure) as x:c.read()
  self.assertEqual(x.exception.status,'cancelled')
 def test_epoch_always_wins(self):
  c=self.ctx();c.damage_budget=100;c.game.observe=lambda r=0:state(control_epoch=2)
  with self.assertRaises(Failure) as x:c.read()
  self.assertEqual(x.exception.reason,'control_released')
 def test_death_always_wins(self):
  c=self.ctx();c.damage_budget=100;c.game.observe=lambda r=0:state(dead=True)
  with self.assertRaises(Failure) as x:c.read()
  self.assertEqual(x.exception.reason,'player_dead')
 def test_pending_intervention_is_reported(self):
  c=self.ctx();c.game._survival=SimpleNamespace(interrupted=lambda:True,pending={'action':'flee_from'})
  with self.assertRaises(Failure) as x:c.check()
  self.assertEqual(x.exception.reason,'survival_interrupted')

class SupervisorTests(unittest.TestCase):
 def game(self):
  g=SimpleNamespace(_survival=None,_epoch=1,_cancel=threading.Event(),_action_lock=ActionLock(),_closed=False,timeout=.3,
   capabilities={'living_entities','hud_statbars','hud_images','weapon_stats','attack'},recipe_book=RecipeBook.voxelibre(),_motion=None,
   _skill_depth=0,traversal=None,exploration_memory=None,endpoint=Path('/test'))
  g.observe=lambda r=0:state(entities=(entity(pointable=True),));g._submit=lambda *a,**k:None
  g.flee_from=lambda **kw:SkillResult('flee_from','success');return g
 def wait(self,pred):
  end=time.monotonic()+2
  while not pred():
   if time.monotonic()>end:self.fail('thread did not complete')
   time.sleep(.01)
 def test_observer_not_auto_acquired(self):
  g=self.game();g._epoch=None
  with self.assertRaises(ActionError):Survival(g).__enter__()
 def test_old_client_explicit_error(self):
  g=self.game();g.capabilities=set()
  with self.assertRaises(ActionError):Survival(g).__enter__()
 def test_worker_waits_for_normal_action_to_unwind(self):
  g=self.game();called=[];g.flee_from=lambda **kw:called.append(threading.get_ident()) or SkillResult('flee_from','success')
  g._action_lock.acquire()
  with Survival(g,SurvivalConfig(poll_interval=.05)) as guard:
   self.wait(lambda:guard.pending is not None);self.assertEqual(called,[])
   g._action_lock.release();self.wait(lambda:len(called)==1);self.assertTrue(guard.wait_idle(1))
   events=guard.events();self.assertEqual(events[-1]['event'],'reaction_finished');self.assertTrue(events[-1]['replan_required'])
  self.assertIsNone(g._survival)
 def test_manual_stop_pauses_without_reacquire(self):
  g=self.game()
  with Survival(g,SurvivalConfig(poll_interval=.05)) as guard:
   guard.pause();time.sleep(.12);self.assertTrue(guard.paused);self.assertFalse(guard.busy)
 def test_control_epoch_change_pauses(self):
  g=self.game()
  with Survival(g,SurvivalConfig(poll_interval=.05)) as guard:
   g.observe=lambda r=0:state(control_epoch=2)
   self.wait(lambda:guard.paused);self.assertEqual(guard.events()[-1]['event'],'control_lost')
 def test_reaction_connection_failure_is_recorded(self):
  from luanti_course import ConnectionError
  g=self.game()
  with Survival(g,SurvivalConfig(poll_interval=.05)) as guard:
   g.flee_from=lambda **kw:(_ for _ in ()).throw(ConnectionError('disconnected'))
   self.wait(lambda:guard.paused);self.assertEqual(guard.events()[-1]['event'],'reaction_error')
 def test_no_blind_replay(self):
  g=self.game();g._action_lock.acquire();called=[]
  with Survival(g,SurvivalConfig(poll_interval=.05)) as guard:
   self.wait(lambda:guard.pending is not None)
   result=run(g,'craft',lambda c:called.append('mutate'),timeout=1)
   self.assertEqual(result.reason,'survival_interrupted');self.assertFalse(called)
   g._action_lock.release();self.wait(lambda:not guard.busy)

if __name__=='__main__':unittest.main()

class CombatCompletionTests(unittest.TestCase):
 def test_script_managed_death_animation_stops_attacking(self):
  old=entity(pointable=True,engine_immortal=True);dying=entity(pointable=False,engine_immortal=True)
  s=state(entities=(old,),weapons=[dict(slot=0,name='sword',interval=.625,usable=False)],wield=0,pointed_entity={'id':2,'instance':10})
  c=SimpleNamespace(game=SimpleNamespace(capabilities={'attack'},_submit=lambda *a,**kw:c.submitted.append((a,kw))),details={},submitted=[],
    sleep=lambda t:None,stop_input=lambda:None,log=lambda *a,**kw:None)
  calls=[0];clock=[0]
  def observed(ctx,ref):calls[0]+=1;return s,old if calls[0]<=2 else dying
  def tick():clock[0]+=.2;return clock[0]
  with patch('luanti_course.combat.current_target',observed),patch('luanti_course.combat.close_form'),patch('luanti_course.combat.face'),patch('luanti_course.combat.time.monotonic',tick):
   attack(c,old,auto_equip=False)
  self.assertEqual(len(c.submitted),1);self.assertIsNone(c.details['killed']);self.assertEqual(c.details['outcome'],'target_no_longer_attackable')
 def test_socket_level_interruption_retains_reason(self):
  from luanti_course import ActionCancelled
  g=SimpleNamespace(_motion=None,_epoch=1,_cancel=threading.Event(),_action_lock=ActionLock(),_skill_depth=0,
    recipe_book=RecipeBook.voxelibre(),traversal=None,_closed=False,_submit=lambda *a:None)
  with patch('luanti_course.skills.Context.read',lambda *a:None):
   r=run(g,'test',lambda c:(_ for _ in ()).throw(ActionCancelled('survival_interrupted')),timeout=1)
  self.assertEqual(r.status,'cancelled');self.assertEqual(r.reason,'survival_interrupted')
 def test_entity_reference_bound_to_connection(self):
  g=Game.__new__(Game);g._observation_source='new-connection'
  with self.assertRaisesRegex(ValueError,'another Game connection'):g.attack_entity(entity(pointable=True))
  with self.assertRaisesRegex(ValueError,'another Game connection'):g.flee_from(entity())

class SurvivalBusyTests(unittest.TestCase):
 def test_new_skill_during_reaction_returns_replan_not_uncaught_error(self):
  g=SimpleNamespace(_motion=None,_action_lock=SimpleNamespace(acquire=lambda **kw:False),
    _survival=SimpleNamespace(busy=True,pending={'action':'eat_best_food'}))
  r=run(g,'collect',lambda c:self.fail('must not execute'),timeout=1)
  self.assertEqual(r.reason,'survival_interrupted');self.assertFalse(r.details['started'])

class DefenseEdgeTests(unittest.TestCase):
 def test_dying_hostile_does_not_crash_self_defense(self):
  s=state(entities=(entity(pointable=False),));c=SimpleNamespace(read=lambda r=0:s,details={})
  with patch('luanti_course.combat.attack') as attack_mock:defend(c)
  attack_mock.assert_not_called();self.assertEqual(c.details['outcome'],'no_attackable_threat')
