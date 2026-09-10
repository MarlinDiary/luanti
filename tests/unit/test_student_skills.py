import inspect,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Game

class StudentContracts(unittest.TestCase):
 def test_crafting_does_not_procure_by_default(self):
  self.assertIs(inspect.signature(Game.craft).parameters['gather'].default,False)
 def test_tool_upgrade_is_explicit(self):
  for method in ('collect','craft'):
   self.assertIs(inspect.signature(getattr(Game,method)).parameters['allow_tool_crafting'].default,False)
 def test_complete_jobs_have_simple_entries(self):
  for method in ('dig_down','dig_tunnel','go_to_surface','bridge_to','eat'):
   self.assertTrue(callable(getattr(Game,method,None)),method)
 def test_down_stays_at_destination(self):
  self.assertNotIn('route',inspect.signature(Game.dig_down).parameters)
 def test_mining_checkpoint_is_supported(self):
  for method in ('dig_down','dig_tunnel','go_to_surface'):
   self.assertIn('checkpoint',inspect.signature(getattr(Game,method)).parameters)

class JobUnitTests(unittest.TestCase):
 def test_direction_validation(self):
  from luanti_course.excursions import direction
  self.assertIsNone(direction(None));self.assertEqual(direction([0,0,-1]),(0,0,-1))
  for x in [(1,1,0),(1,0,1),(True,0,0),(1.,0,0),'east']:
   with self.assertRaises(ValueError):direction(x)
 def test_distance_validation(self):
  from luanti_course.excursions import validate_distance
  for n in [0,65,True,2.1]:
   with self.assertRaises(ValueError):validate_distance(n)
 def test_no_automatic_tool_crafting(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  from luanti_course.skills import choose_tool,Failure
  c=SimpleNamespace(check=lambda:None,recover=True,allow_tool_crafting=False,game=SimpleNamespace(_request=lambda *a,**k:dict(name='stone',groups={},tools=[])))
  with patch('luanti_course.skills.craft') as craft:
   with self.assertRaises(Failure) as e:choose_tool(c,(0,0,0))
   self.assertEqual(e.exception.reason,'suitable_tool_required');craft.assert_not_called()
 def test_return_trail_validation(self):
  from luanti_course.excursions import validate_trip
  good=dict(schema=2,scope='client',entry=[0,100,0],trail=[[0,100,0],[1,99,0],[1,99,1]])
  self.assertIs(validate_trip(good,'client'),good)
  for changes in [dict(scope='other'),dict(trail=[]),dict(entry=[1,100,0]),dict(trail=[[0,100,0],[0,99,0]]),dict(trail=[[0,100,0],[2,100,0]])]:
   with self.assertRaises(ValueError):validate_trip(dict(good,**changes),'client')
 def test_checkpoint_atomic_roundtrip(self):
  import tempfile
  from luanti_course.excursions import save_checkpoint,read_checkpoint
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'trip.json';x=dict(schema=2,scope='client',entry=[0,100,0],trail=[[0,100,0]])
   save_checkpoint(p,x);self.assertEqual(read_checkpoint(p,'client'),x)
   self.assertEqual([n.name for n in Path(d).iterdir()],['trip.json'])
 def test_no_edit_before_unsafe_step(self):
  from luanti_course.excursions import preflight_step
  from luanti_course.navigation import World,Node
  from luanti_course.skills import Failure
  from types import SimpleNamespace
  from unittest.mock import patch
  w=World();c=SimpleNamespace(world=w,within=lambda p:True,terrain_edits=0)
  for x in range(-1,4):
   for y in range(96,104):
    for z in range(-1,2):w.nodes[(x,y,z)]=Node('stone',True)
  w.nodes[(2,99,0)]=Node('water',False,liquid=True)
  with patch('luanti_course.excursions.choose_tool') as tool:
   with self.assertRaises(Failure) as e:preflight_step(c,(0,100,0),(1,99,0))
   self.assertEqual(e.exception.reason,'unstable_excavation_boundary');tool.assert_not_called()
 def test_bridge_preserves_budget_and_disables_dig(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  from luanti_course import Traversal
  g=SimpleNamespace(traversal=Traversal(allow_dig=True,edit_budget=8))
  with patch('luanti_course.skills.run') as run:
   Game.bridge_to(g,(8,99.5,0),max_blocks=12)
   t=run.call_args.kwargs['traversal'];self.assertEqual(t.edit_budget,8);self.assertFalse(t.allow_dig);self.assertEqual(t.build_with,'mcl_core:cobble')
 def test_non_food_does_not_issue_input(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  from luanti_course.survival import eat
  from luanti_course import RecipeBook,ConnectionError
  from luanti_course.skills import Failure
  c=SimpleNamespace(book=RecipeBook({'items':{'stone':{'groups':{}}},'recipes':[]}),game=SimpleNamespace(observe=lambda:None))
  # Bypass the station cleanup wrapper to isolate food eligibility.
  with self.assertRaises(Failure) as e:eat.__wrapped__(c,'stone',1)
  self.assertEqual(e.exception.reason,'not_edible')
 def test_held_wood_recipe_contains_no_collection(self):
  from luanti_course import RecipeBook
  plan=RecipeBook.voxelibre().plan('wooden_pickaxe',1,{'mcl_core:tree':3},gather=False)
  self.assertTrue(plan);self.assertFalse(any(x.kind=='collect' for x in plan))
 def test_missing_raw_material_is_reported(self):
  from luanti_course import RecipeBook
  from luanti_course.recipes import PlanningError
  with self.assertRaises(PlanningError):RecipeBook.voxelibre().plan('mcl_tools:pick_iron',1,{},gather=False)
 def test_food_public_input_validation(self):
  for item,n in [('',1),('apple',0),('apple',True),('apple',17)]:
   with self.assertRaises(ValueError):Game.eat(None,item,n)

class FoodInputTests(unittest.TestCase):
 def test_cooldown_ignored_press_is_rearmed(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  from luanti_course.survival import eat
  # Simulate an ignored initial button edge during the server's cooldown.
  clock=[0.];held=[False];pressed=[None];remaining=[1];stops=[]
  def submit(*a,**k):
   if not held[0]:pressed[0]=clock[0];held[0]=True
  def stop():held[0]=False;stops.append(clock[0])
  def read():
   if held[0] and pressed[0]>=2 and clock[0]-pressed[0]>=1.6:remaining[0]=0
   return SimpleNamespace(eye=(0,0,0),inventory={'main':SimpleNamespace(find=lambda i:0)})
  c=SimpleNamespace(book=SimpleNamespace(resolve=lambda i:i,items={'apple':{'groups':{'eatable':4}}}),read=read,deadline=60,details={},game=SimpleNamespace(_submit=submit),sleep=lambda t:clock.__setitem__(0,clock[0]+t),stop_input=stop,log=lambda *a,**k:None)
  with patch('luanti_course.survival.time.monotonic',lambda:clock[0]),patch('luanti_course.survival.close_form'),patch('luanti_course.survival.face'),patch('luanti_course.survival.wield_slot'),patch('luanti_course.survival.count_items',lambda *a:remaining[0]):
   eat.__wrapped__(c,'apple',1)
  self.assertEqual(c.details['consumed'],1);self.assertFalse(held[0]);self.assertGreaterEqual(len(stops),2)
 def test_food_releases_input_on_cancel(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  from luanti_course.survival import eat
  from luanti_course.skills import Failure
  def cancel(t):raise Failure('cancelled',status='cancelled')
  stopped=[]
  state=SimpleNamespace(eye=(0,0,0),inventory={'main':SimpleNamespace(find=lambda i:0)})
  c=SimpleNamespace(book=SimpleNamespace(resolve=lambda i:i,items={'apple':{'groups':{'eatable':4}}}),read=lambda:state,deadline=float('inf'),details={},game=SimpleNamespace(_submit=lambda *a,**k:None),sleep=cancel,stop_input=lambda:stopped.append(True))
  with patch('luanti_course.survival.close_form'),patch('luanti_course.survival.face'),patch('luanti_course.survival.wield_slot'),patch('luanti_course.survival.count_items',return_value=1):
   with self.assertRaises(Failure) as e:eat.__wrapped__(c,'apple',1)
  self.assertEqual(e.exception.status,'cancelled');self.assertTrue(stopped)
