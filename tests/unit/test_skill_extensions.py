import inspect,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Game,RecipeBook

class ExtensionTests(unittest.TestCase):
 def test_policy_is_composable(self):
  for method in ('find_resource','collect','craft','place_block','smelt','deposit','withdraw','excavate','build','build_ladder','navigate_route'):
   self.assertIn('traversal',inspect.signature(getattr(Game,method)).parameters,method)
 def test_checkpoint_apis(self):
  for method in ('collect','craft','smelt'):
   self.assertIn('checkpoint',inspect.signature(getattr(Game,method)).parameters)
  self.assertTrue(callable(Game.resume))
 def test_cooking_dependency_plan(self):
  b=RecipeBook({'items':{'raw':{},'ingot':{},'tool':{},'coal':{}},'recipes':[{'output':'tool','count':1,'width':1,'items':['ingot','ingot']}],'cooking':[{'input':'raw','output':'ingot','count':1,'time':10}],'fuels':{'coal':80}})
  p=b.plan('tool',1,{'raw':2,'coal':1},gather=False)
  self.assertEqual([s.kind for s in p],['smelt','smelt','craft'])
 def test_fuel_minimum_and_no_wasteful_tools(self):
  from luanti_course.workstations import select_fuel
  self.assertEqual(select_fuel({'coal':80,'wood':15},{'coal':1,'wood':2},20),('wood',2))
  self.assertEqual(select_fuel({'coal':80},{'coal':1},80),('coal',1))
  with self.assertRaises(ValueError):select_fuel({'coal':80},{'coal':1},81)
 def test_checkpoint_reconciles_and_binds(self):
  from luanti_course.persistence import Checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'task.json';a=Checkpoint(p,'world','collect',{'resource':'wood','count':5},10);a.progress(12)
   b=Checkpoint(p,'world','collect',{'resource':'wood','count':5},13)
   self.assertEqual(b.remaining(13),2)
   with self.assertRaises(ValueError):Checkpoint(p,'other','collect',{'resource':'wood','count':5},13)
   with self.assertRaises(ValueError):Checkpoint(p,'world','collect',{'resource':'wood','count':6},13)
   with self.assertRaises(ValueError):b.remaining(11)
 def test_checkpoint_does_not_replay_completed(self):
  from luanti_course.persistence import Checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'task';a=Checkpoint(p,'world','craft',{'item':'stick','count':4},0);a.progress(4,complete=True)
   self.assertEqual(Checkpoint(p,'world','craft',{'item':'stick','count':4},0).remaining(0),0)
 def test_excavation_rejects_vertical_shaft(self):
  from luanti_course.construction import validate_route
  with self.assertRaises(ValueError):validate_route([(0,100,0),(0,99,0)])
  self.assertEqual(len(validate_route([(0,100,0),(1,99,0),(2,98,0)])),3)
 def test_blueprint_validation(self):
  from luanti_course.construction import validate_blueprint
  with self.assertRaises(ValueError):validate_blueprint([('stone',(0,100,0)),('wood',(0,100,0))])
  self.assertEqual(len(validate_blueprint([('stone',(0,100,0))])),1)
 def test_memory_scope_and_expiry(self):
  from luanti_course.persistence import ExplorationMemory
  from luanti_course.navigation import World,Node
  from collections import Counter
  m=ExplorationMemory(ttl=.01);w=World();w.nodes[(0,1,0)]=Node('air',False)
  m.store('one',w,Counter({(0,1,0):1}));new,visited=m.load('one');self.assertEqual(len(new.nodes),1)
  self.assertFalse(m.load('two')[0].nodes)
  time.sleep(.02);self.assertFalse(m.load('one')[0].nodes)

 def test_policy_reaches_real_skill_context(self):
  from types import SimpleNamespace
  import threading
  from luanti_course import Traversal
  from luanti_course.skills import run,ActionLock
  g=SimpleNamespace(_motion=None,_action_lock=ActionLock(),_epoch=1,_cancel=threading.Event(),_skill_depth=0,traversal=Traversal(allow_swim=True),recipe_book=RecipeBook({'items':{},'recipes':[]}))
  seen=[]
  with patch('luanti_course.skills.Context.read',lambda c,radius=0:None),patch('luanti_course.skills.Context.stop_input'):
   r=run(g,'test',lambda c:seen.append(c.world.traversal.allow_swim),timeout=1)
  self.assertTrue(r.ok);self.assertEqual(seen,[True])
 def test_cooking_plan_batches(self):
  from luanti_course.recipes import batch_plan
  b=RecipeBook({'items':{'raw':{},'ingot':{},'tool':{}},'recipes':[{'output':'tool','count':1,'width':1,'items':['ingot','ingot']}],'cooking':[{'input':'raw','output':'ingot','count':1,'time':10}]})
  p=batch_plan(b.plan('tool',1,{'raw':2},gather=False),b)
  self.assertEqual([(s.kind,s.count) for s in p],[('smelt',2),('craft',1)])
 def test_no_cooking_recipe_is_an_explicit_error(self):
  from luanti_course.recipes import PlanningError
  b=RecipeBook({'items':{'x':{}},'recipes':[]})
  with self.assertRaises(PlanningError):b.plan('x',1,{})
 def test_storage_form_does_not_select_player_inventory(self):
  from types import SimpleNamespace
  from luanti_course.workstations import storage_lists
  from luanti_course.skills import Failure
  player={'name':'main','items':[{}]*36,'first_slot':9,'last_slot':35}
  with self.assertRaises(Failure):storage_lists(SimpleNamespace(form={'lists':[player]}))
  box={'name':'main','items':[{}]*27,'first_slot':0,'last_slot':26}
  self.assertEqual(storage_lists(SimpleNamespace(form={'lists':[player,box]})),[box])
 def test_route_rejects_nonfinite_and_diagonal(self):
  from luanti_course.construction import validate_route
  for route in [[(0,float('nan'),0)],[(0,100,0),(1,100,1)],[(0,100,0),(3,100,0)]]:
   with self.assertRaises(ValueError):validate_route(route)
 def test_memory_is_detached(self):
  from luanti_course.persistence import ExplorationMemory
  from luanti_course.navigation import World,Node
  from collections import Counter
  m=ExplorationMemory();w=World();w.nodes[(0,0,0)]=Node('air',False);m.store('a',w,Counter())
  copy,_=m.load('a');copy.nodes.clear();self.assertEqual(len(m.load('a')[0].nodes),1)
 def test_excavation_hazard_never_digs(self):
  from luanti_course.construction import safe_dig
  from luanti_course.navigation import Node,World
  from luanti_course.skills import Failure
  from types import SimpleNamespace
  w=World();p=(1,1,0);w.nodes[p]=Node('stone',True);w.nodes[(1,2,0)]=Node('sand',True,groups={'falling_node':1})
  c=SimpleNamespace(read=lambda n:SimpleNamespace(position=(0,.5,0)),world=w)
  with patch('luanti_course.construction.dig_node') as dig:
   with self.assertRaises(Failure):safe_dig(c,p)
   dig.assert_not_called()

 def test_long_frontier_navigation(self):
  from types import SimpleNamespace
  from luanti_course.navigation import World,Node
  from luanti_course.skills import navigate
  class C:
   def __init__(self):
    self.position=(0,.5,0);self.origin=self.position;self.radius=256;self.world=World();self.blocked=set();self.calls=0;self.game=SimpleNamespace(capabilities=('steer',));self.last=None
   def read(self,radius=0):
    self.calls+=1
    x=round(self.position[0])
    for i in range(max(-6,x-6),min(206,x+6)+1):
     for z in range(-2,3):
      for y in range(4):self.world.nodes[(i,y,z)]=Node('stone',True) if y==0 else Node('air',False)
    self.last=SimpleNamespace(position=self.position);return self.last
   def within(self,p):return abs(p[0])<=256 and abs(p[2])<=2
   def log(self,*a,**k):pass
   def stop_input(self):pass
   def sleep(self,s):pass
  c=C()
  def move(c,path,target,*args,**kwargs):c.position=target;c.last=SimpleNamespace(position=target);return True,None
  with patch('luanti_course.skills.follow_path',move):navigate(c,(200,.5,0))
  self.assertLess(abs(c.position[0]-200),.5);self.assertGreater(c.calls,20);self.assertLess(c.calls,200)
 def test_checkpoint_detects_tampered_target(self):
  from luanti_course.persistence import Checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'c';Checkpoint(p,'w','collect',{'count':1},0);x=json.loads(p.read_text());x['target']=1000;p.write_text(json.dumps(x))
   with self.assertRaises(ValueError):Checkpoint(p,'w','collect',{'count':1},0)

 def test_checkpoint_lock_is_exclusive_and_released(self):
  from luanti_course.persistence import checkpoint_lock
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'checkpoint'
   with checkpoint_lock(p):
    with self.assertRaises(ValueError):
     with checkpoint_lock(p):pass
   with checkpoint_lock(p):pass
 def test_geometry_cache_does_not_survive_map_changes(self):
  from luanti_course.navigation import World,Node
  w=World()
  for x in range(-1,4):
   for y in range(4):
    for z in range(-1,2):w.nodes[(x,y,z)]=Node('s',True) if y==0 else Node('air',False)
  self.assertIsNotNone(w.path((0,1,0),lambda p:p==(2,1,0))[0])
  for z in range(-1,2):
   for y in range(1,4):w.nodes[(1,y,z)]=Node('s',True)
  self.assertIsNone(w.path((0,1,0),lambda p:p==(2,1,0))[0])
 def test_planning_checks_cancellation(self):
  from luanti_course.navigation import World,Node
  from luanti_course.skills import Failure
  w=World()
  for x in range(8):
   for z in range(8):
    for y in range(3):w.nodes[(x,y,z)]=Node('s',True) if y==0 else Node('air',False)
  def stop():raise Failure('cancelled',status='cancelled')
  w.planning_check=stop
  with self.assertRaises(Failure):w.path((0,1,0),lambda p:False)

 def test_direct_smelting_beats_packing_nine_ores(self):
  b=RecipeBook.voxelibre();p=b.plan('mcl_tools:pick_iron',1,{'mcl_core:stick':2},gather=True,nearby=['mcl_core:stone_with_iron'],has_table=True)
  self.assertEqual(sum(s.count for s in p if s.kind=='collect' and s.item=='mcl_raw_ores:raw_iron'),3)
 def test_interaction_does_not_stop_on_water_surface(self):
  from luanti_course.navigation import Node,World,Traversal
  w=World(Traversal(allow_swim=True))
  for x in range(-1,7):
   for z in range(-1,2):
    for y in range(4):w.nodes[(x,y,z)]=Node('stone',True) if y==0 else Node('air',False)
  w.nodes[(1,0,0)]=Node('water',False,liquid=True);w.nodes[(3,1,0)]=Node('wood',True)
  self.assertFalse(w.approach((1,1,0),(3,1,0)))
  self.assertTrue(w.approach((2,1,0),(3,1,0)))

 def test_explicit_navigation_disables_inherited_edits(self):
  from types import SimpleNamespace
  from luanti_course import Traversal
  g=SimpleNamespace(traversal=Traversal(allow_swim=True,allow_dig=True,build_with='stone'))
  with patch('luanti_course.skills.run') as run:
   Game.navigate_to(g,(1,1,1),allow_dig=False,build_with=None)
   policy=run.call_args.kwargs['traversal']
  self.assertTrue(policy.allow_swim);self.assertFalse(policy.allow_dig);self.assertIsNone(policy.build_with)
 def test_explicit_navigation_can_enable_inherited_option(self):
  from types import SimpleNamespace
  from luanti_course import Traversal
  g=SimpleNamespace(traversal=Traversal())
  with patch('luanti_course.skills.run') as run:
   Game.navigate_to(g,(1,1,1),allow_swim=True)
   self.assertTrue(run.call_args.kwargs['traversal'].allow_swim)

 def test_initial_low_air_reaches_recovery(self):
  from types import SimpleNamespace
  import threading
  from luanti_course import Traversal
  from luanti_course.skills import run,ActionLock,Failure
  g=SimpleNamespace(_motion=None,_action_lock=ActionLock(),_epoch=1,_cancel=threading.Event(),_skill_depth=0,traversal=Traversal(allow_swim=True,allow_dive=True),capabilities=('swim_height',),recipe_book=RecipeBook({'items':{},'recipes':[]}))
  events=[]
  def read(c,radius=0):
   if not c.resurfacing:raise Failure('low_breath',{'breath':6})
   return SimpleNamespace(raw={'breath':6})
  with patch('luanti_course.skills.Context.read',read),patch('luanti_course.skills.Context.stop_input'),patch('luanti_course.skills.regain_air',lambda c:events.append('air')):
   r=run(g,'navigate_to',lambda c:events.append('task'),timeout=1)
  self.assertTrue(r.ok,r.to_dict());self.assertEqual(events,['air','task'])
