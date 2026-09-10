import sys,threading,time,unittest,importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'sdk/src'))
from luanti_course import RecipeBook,SurvivalConfig
from luanti_course.skills import Failure,SkillResult
from luanti_course.combat import eat_best
from luanti_course.supervisor import Survival
from test_survival import state,entity
import test_survival as helpers
spec=importlib.util.spec_from_file_location('survival_collect_example',ROOT/'examples/survival_collect.py');example=importlib.util.module_from_spec(spec);spec.loader.exec_module(example)

def reaction(action,status='success',reason='',intervention=None):
 return dict(event='reaction_finished',decision={'action':action},result={'status':status,'reason':reason,'details':{} if intervention is None else {'intervention':{'action':intervention}}})

class ExampleFinishingTests(unittest.TestCase):
 def execute(self,events,paused=False):
  held=[0];calls=[]
  guard=NS(busy=False,paused=paused,wait_idle=lambda t:True)
  class Scope:
   def __enter__(self):return guard
   def __exit__(self,*a):pass
  batch=[events,[]];guard.events=lambda:batch.pop(0) if batch else []
  def observe(*a):return state(inventory={'main':{'width':9,'items':[{'name':'mcl_core:tree','count':held[0]}]}})
  def collect(item,count,**kw):calls.append(count);held[0]+=count;return SkillResult('collect','success')
  game=NS(recipe_book=RecipeBook.voxelibre(),exploration_memory=None,observe=observe,survival=lambda c:Scope(),collect=collect,stop=lambda:None)
  return example.collect_with_survival(game,'mcl_core:tree',2,seconds=1),calls
 def test_successful_priority_handoff_is_not_failure(self):
  result,calls=self.execute([reaction('defend_self','cancelled','survival_interrupted','flee_from'),reaction('flee_from')])
  self.assertEqual(result['status'],'complete');self.assertEqual(calls,[2])
 def test_failed_successor_still_requires_replanning(self):
  result,calls=self.execute([reaction('defend_self','cancelled','survival_interrupted','flee_from'),reaction('flee_from','blocked','escape_route_unavailable')])
  self.assertEqual(result['status'],'needs_replan');self.assertFalse(calls)
 def test_manual_cancellation_is_not_normal_handoff(self):
  result,calls=self.execute([reaction('defend_self','cancelled','cancelled')]);self.assertEqual(result['status'],'needs_replan');self.assertFalse(calls)
 def test_unexplained_cancel_is_not_ignored(self):
  result,calls=self.execute([reaction('defend_self','cancelled','survival_interrupted')]);self.assertEqual(result['status'],'needs_replan');self.assertFalse(calls)
 def test_paused_guard_does_not_resume_collection(self):
  result,calls=self.execute([],True);self.assertEqual(result['status'],'stopped');self.assertFalse(calls)

class EatingRestoreTests(unittest.TestCase):
 def context(self):
  items=[{'name':'mcl_tools:sword_wood','count':1,'wear':20,'stack_key':'sword identity'},{'name':'mcl_core:apple','count':3,'stack_key':'apple'}]
  current=[state(wield=0,hotbar_size=9,inventory={'main':{'width':9,'items':items}})];restores=[]
  def eat(c,name,count):
   current[0]=state(hunger=14,wield=1,hotbar_size=9,inventory={'main':{'width':9,'items':[items[0],dict(items[1],count=2)]}})
   c.details.update(consumed=1,food_slot=1)
  c=NS(read=lambda *a:current[0],book=RecipeBook.voxelibre(),details={},log=lambda *a,**k:None)
  return c,current,restores,eat
 def test_success_restores_previous_tool(self):
  c,current,restores,eat=self.context()
  with patch('luanti_course.survival.eat',eat),patch('luanti_course.combat.wield_slot',lambda c,slot:restores.append(slot) or slot):eat_best(c)
  self.assertEqual(restores,[0]);self.assertEqual(c.details.get('wield_restore'),'restored')
 def test_same_named_different_metadata_is_not_substituted(self):
  c,current,restores,eat=self.context()
  def changed(c,n,k):
   eat(c,n,k);raw=current[0].raw;raw['inventory']['main']['items'][0]['stack_key']='other sword';current[0]=type(current[0]).from_dict(raw)
  with patch('luanti_course.survival.eat',changed),patch('luanti_course.combat.wield_slot',lambda *a:restores.append(a)):eat_best(c)
  self.assertFalse(restores);self.assertEqual(c.details.get('wield_restore'),'previous_item_unavailable')
 def test_inventory_relocation_follows_stack_identity(self):
  c,current,restores,eat=self.context()
  def moved(c,n,k):
   eat(c,n,k);raw=current[0].raw;items=raw['inventory']['main']['items'];items.append(items[0]);items[0]={'name':'other','count':1,'stack_key':'other'};current[0]=type(current[0]).from_dict(raw)
  with patch('luanti_course.survival.eat',moved),patch('luanti_course.combat.wield_slot',lambda c,slot:restores.append(slot) or slot):eat_best(c)
  self.assertEqual(restores,[2])
 def test_emergency_interrupt_never_restores_tool(self):
  c,current,restores,eat=self.context()
  with patch('luanti_course.survival.eat',side_effect=Failure('survival_interrupted',status='cancelled')),patch('luanti_course.combat.wield_slot',lambda *a:restores.append(a)),self.assertRaises(Failure):eat_best(c)
  self.assertFalse(restores)
 def test_changed_wield_does_not_get_overwritten(self):
  c,current,restores,eat=self.context()
  def changed(c,n,k):
   eat(c,n,k);raw=current[0].raw;raw['wield']=0;current[0]=type(current[0]).from_dict(raw)
  with patch('luanti_course.survival.eat',changed),patch('luanti_course.combat.wield_slot',lambda *a:restores.append(a)):eat_best(c)
  self.assertFalse(restores);self.assertEqual(c.details.get('wield_restore'),'wield_changed')

 def test_post_meal_cancellation_skips_restore(self):
  c,current,restores,eat=self.context()
  def interrupted(c,n,k):
   eat(c,n,k)
   def read(*a):raise Failure('control_lost',status='cancelled')
   c.read=read
  with patch('luanti_course.survival.eat',interrupted),patch('luanti_course.combat.wield_slot',lambda *a:restores.append(a)),self.assertRaises(Failure):eat_best(c)
  self.assertFalse(restores);self.assertEqual(c.details['consumed'],1)
 def test_already_full_does_not_eat_or_change_wield(self):
  c,current,restores,eat=self.context();current[0]=state(hunger=20)
  with patch('luanti_course.survival.eat') as action,patch('luanti_course.combat.wield_slot') as wield:eat_best(c)
  action.assert_not_called();wield.assert_not_called();self.assertEqual(c.details['outcome'],'already_full')

class HandoffBusyTests(unittest.TestCase):
 def test_higher_priority_handoff_has_no_false_idle_gap(self):
  g=helpers.SupervisorTests().game();phase=['food'];finished=threading.Event();release=threading.Event()
  def observe(r=0):
   return state(inventory={'main':{'width':9,'items':[{'name':'mcl_core:apple','count':3}]}},entities=() if phase[0]=='food' else (entity(pointable=True),))
  g.observe=observe
  guard=Survival(g,SurvivalConfig(poll_interval=.2))
  event=guard._event
  def emit(kind,**kw):
   event(kind,**kw)
   if kind=='reaction_finished':finished.set()
  guard._event=emit
  def execute(choice):
   if choice['action']=='eat_best_food':
    phase[0]='enemy';guard.on_observation(observe());return SkillResult('eat_best_food','cancelled','survival_interrupted',{'intervention':guard.pending})
   release.wait(.5);return SkillResult('flee_from','success')
  guard._execute=execute
  try:
   with guard:
    self.assertTrue(finished.wait(1));time.sleep(.02)
    self.assertFalse(guard.wait_idle(.05),'unfinished handoff was exposed as idle')
  finally:release.set()

if __name__=='__main__':unittest.main()
