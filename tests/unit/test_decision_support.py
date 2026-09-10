import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Game
class DecisionContracts(unittest.TestCase):
 def test_read_only_recipe_queries(self):
  for n in ('plan_craft','recipes_for'):self.assertTrue(callable(getattr(Game,n,None)),n)
 def test_landmarks(self):
  for n in ('remember_location','saved_locations','go_to_location','save_locations','load_locations','forget_location'):self.assertTrue(callable(getattr(Game,n,None)),n)
 def test_container_inspection(self):self.assertTrue(callable(getattr(Game,'inspect_container',None)))
 def test_honest_return_name(self):self.assertTrue(callable(getattr(Game,'return_to_entrance',None)))
 def test_explicit_checkpoint_upgrade(self):self.assertTrue(callable(getattr(Game,'upgrade_checkpoint',None)))

from types import SimpleNamespace
from luanti_course import RecipeBook,Item,InventoryList
from luanti_course.queries import plan_craft,recipes_for

def inventory(stock):return SimpleNamespace(raw={},inventory={'main':InventoryList(9,tuple(Item(n,c) for n,c in stock.items()))})
def book():return RecipeBook({'items':{'log':{'type':'node','drop':'log'},'plank':{}},'recipes':[{'output':'plank','count':4,'width':1,'items':['log']}]})

class QueryTests(unittest.TestCase):
 def test_ready_plan_is_read_only(self):
  state=inventory({'log':1});r=plan_craft(book(),'plank',4,state)
  self.assertTrue(r.materials_ready);self.assertEqual(r.missing,{})
  self.assertEqual(state.inventory['main'].count('log'),1);self.assertEqual(r.steps[0]['kind'],'craft')
 def test_missing_materials_are_a_proposal(self):
  r=plan_craft(book(),'plank',8,inventory({'log':1}))
  self.assertFalse(r.materials_ready);self.assertEqual(r.missing,{'log':1});self.assertTrue(r.missing_complete)
 def test_unavailable_recipe_not_empty_success(self):
  r=plan_craft(book(),'unknown',1,inventory({}))
  self.assertFalse(r.materials_ready);self.assertFalse(r.missing_complete);self.assertEqual(r.reason,'recipe_unavailable')
 def test_plan_count_means_additional(self):
  r=plan_craft(book(),'plank',4,inventory({'plank':100}))
  self.assertEqual(r.missing,{'log':1});self.assertFalse(r.materials_ready)
 def test_preview_and_form_are_not_materials(self):
  s=inventory({});s.inventory['craftpreview']=InventoryList(1,(Item('log',99),));s.inventory['form:0']=s.inventory['craftpreview']
  self.assertFalse(plan_craft(book(),'plank',4,s).materials_ready)
 def test_owned_crafting_grid_materials_count(self):
  s=inventory({});s.inventory['craft']=InventoryList(2,(Item('log',1),))
  self.assertTrue(plan_craft(book(),'plank',4,s).materials_ready)
 def test_recipe_data_detached(self):
  b=book();r=recipes_for(b,'plank');r['source']['x']=1
  self.assertNotIn('x',b.source)
 def test_plan_never_claims_fuel_checked(self):
  self.assertFalse(plan_craft(book(),'plank',4,inventory({'log':1})).requirements['fuel_and_furnace_checked'])
 def test_arguments(self):
  for n in (0,65,True,1.5):
   with self.assertRaises(ValueError):plan_craft(book(),'plank',n,inventory({}))
 def test_game_query_only_observes(self):
  calls=[];g=SimpleNamespace(recipe_book=book(),observe=lambda radius:(calls.append(('observe',radius)) or inventory({'log':1})))
  self.assertTrue(Game.plan_craft(g,'plank',4).materials_ready);self.assertEqual(calls,[('observe',0)])

class LocationTests(unittest.TestCase):
 def test_label_and_position_validation(self):
  from luanti_course.locations import label,position
  for v in ('','\n','x'*65):
   with self.assertRaises(ValueError):label(v)
  for p in ((0,float('nan'),0),(True,0,0),(0,0,32701)):
   with self.assertRaises(ValueError):position(p)
 def test_location_roundtrip_scoped(self):
  import tempfile
  from luanti_course.locations import save,load
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'places.json';save(p,'same',{'基地':(1,2,3)})
   self.assertEqual(load(p,'same'),{'基地':(1,2,3)})
   with self.assertRaises(ValueError):load(p,'other')
   before=p.read_bytes()
   with self.assertRaises(ValueError):save(p,'other',{})
   self.assertEqual(p.read_bytes(),before)
 def test_limit(self):
  from luanti_course.locations import validate
  with self.assertRaises(ValueError):validate(dict(schema=1,scope='x',locations={str(i):(0,0,0) for i in range(129)}),'x')
 def test_missing_location_does_not_move(self):
  g=SimpleNamespace(saved_locations=lambda:{})
  self.assertEqual(Game.go_to_location(g,'base').reason,'location_unknown')
 def test_failed_load_preserves_book(self):
  from unittest.mock import patch
  g=SimpleNamespace(endpoint=Path('/client'),_locations={'base':(0,0,0)})
  with patch('luanti_course.locations.load',side_effect=ValueError('bad')):
   with self.assertRaises(ValueError):Game.load_locations(g,'bad')
  self.assertEqual(g._locations,{'base':(0,0,0)})

class UpgradeTests(unittest.TestCase):
 def prepare(self,p):
  from luanti_course.persistence import Checkpoint
  x=Checkpoint(p,'client','collect',{'resource':'log','count':5,'recover':True},0);x.progress(2);return x
 def test_upgrade_keeps_original_and_progress(self):
  import tempfile,json
  from luanti_course.persistence import upgrade_checkpoint,Checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old';q=Path(d)/'new';self.prepare(p);before=p.read_bytes()
   result=upgrade_checkpoint(p,q,'client',2)
   self.assertEqual(p.read_bytes(),before);self.assertEqual(result['remaining'],3)
   data=json.loads(q.read_text());self.assertIs(data['request']['allow_tool_crafting'],False)
   cp=Checkpoint(q,'client','collect',data['request'],2);self.assertEqual(cp.remaining(2),3)
 def test_upgrade_failures_do_not_create_destination(self):
  import tempfile
  from luanti_course.persistence import upgrade_checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old';q=Path(d)/'new';self.prepare(p)
   for scope,current in [('wrong',2),('client',1)]:
    with self.assertRaises(ValueError):upgrade_checkpoint(p,q,scope,current)
    self.assertFalse(q.exists())
 def test_no_inplace_or_overwrite(self):
  import tempfile
  from luanti_course.persistence import upgrade_checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old';q=Path(d)/'new';self.prepare(p)
   with self.assertRaises(ValueError):upgrade_checkpoint(p,p,'client',2)
   q.write_text('later work')
   with self.assertRaises(ValueError):upgrade_checkpoint(p,q,'client',2)
   self.assertEqual(q.read_text(),'later work')
 def test_pending_furnace_is_preserved(self):
  import tempfile,json
  from luanti_course.persistence import upgrade_checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old';q=Path(d)/'new';cp=self.prepare(p);cp.data['station']={'position':[1,2,3],'item':'plank','input':'log','target':5};cp.save()
   upgrade_checkpoint(p,q,'client',2)
   self.assertEqual(json.loads(q.read_text())['station'],cp.data['station'])
 def test_completed_checkpoint_stays_complete(self):
  import tempfile
  from luanti_course.persistence import upgrade_checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old';q=Path(d)/'new';cp=self.prepare(p);cp.progress(5,complete=True)
   r=upgrade_checkpoint(p,q,'client',0);self.assertTrue(r['complete']);self.assertEqual(r['remaining'],0)

class InspectionTests(unittest.TestCase):
 def test_container_inspection_never_transfers(self):
  from unittest.mock import patch
  from luanti_course.workstations import inspect_container
  from collections import Counter
  row={'name':'main','location':'form:0','first_slot':0,'last_slot':26,'items':[{'name':'log','count':3,'wear':0,'stack_key':'k'}]+[{'name':'','count':0}]*26}
  state=SimpleNamespace(form={'id':5,'lists':[row]},frame=10)
  c=SimpleNamespace(details={},log=lambda *a,**k:None)
  with patch('luanti_course.workstations.open_station',return_value=state),patch('luanti_course.workstations.close_form'),patch('luanti_course.workstations.move_external') as move:
   inspect_container.__wrapped__(c,(1,2,3));move.assert_not_called()
  self.assertEqual(c.details['counts'],{'log':3});self.assertEqual(c.details['items_transferred'],0)
  c.details['lists'][0]['items'][0]['count']=99;self.assertEqual(row['items'][0]['count'],3)

class AdditionalBoundaries(unittest.TestCase):
 def test_upgrade_changed_source_observation_rejected(self):
  import tempfile
  from luanti_course.persistence import Checkpoint,upgrade_checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old';q=Path(d)/'new';Checkpoint(p,'client','collect',{'resource':'log','count':1},0)
   with self.assertRaises(ValueError):upgrade_checkpoint(p,q,'client',0,expected_sha256='0'*64)
   self.assertFalse(q.exists())
 def test_upgrade_source_lock_is_respected(self):
  import tempfile
  from luanti_course.persistence import Checkpoint,upgrade_checkpoint,checkpoint_lock
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old';q=Path(d)/'new';Checkpoint(p,'client','collect',{'resource':'log','count':1},0)
   with checkpoint_lock(p):
    with self.assertRaises(ValueError):upgrade_checkpoint(p,q,'client',0)
   self.assertFalse(q.exists())
 def test_new_checkpoint_not_treated_as_legacy(self):
  import tempfile
  from luanti_course.persistence import Checkpoint,upgrade_checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old';q=Path(d)/'new';Checkpoint(p,'client','collect',{'resource':'log','count':1,'allow_tool_crafting':False},0)
   with self.assertRaises(ValueError):upgrade_checkpoint(p,q,'client',0)
   self.assertFalse(q.exists())

class UpgradeFormatTests(unittest.TestCase):
 def test_malformed_checkpoint_rejected_before_observation(self):
  import tempfile,json
  g=SimpleNamespace(observe=lambda: self.fail('malformed file must not observe'))
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'bad'
   for data in ([],None,{'request':[]},{'operation':'collect','request':{'resource':'log','count':True}}, {'operation':'craft','request':{'item':'plank','count':0}}):
    p.write_text(json.dumps(data))
    with self.assertRaises(ValueError):Game.upgrade_checkpoint(g,p,Path(d)/'new')
    self.assertFalse((Path(d)/'new').exists())
 def test_upgrade_unicode_client_uses_utf8(self):
  import tempfile
  from luanti_course.persistence import Checkpoint,upgrade_checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old';q=Path(d)/'new';request={'resource':'log','count':2}
   Checkpoint(p,'学生客户端','collect',request,0)
   upgrade_checkpoint(p,q,'学生客户端',0)
   request['allow_tool_crafting']=False
   self.assertEqual(Checkpoint(q,'学生客户端','collect',request,0).remaining(0),2)
