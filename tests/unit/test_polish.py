import inspect,math,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Game,RecipeBook,Item,InventoryList,ActionError,ActionCancelled
from luanti_course.navigation import World,Node,Traversal
from luanti_course.recipes import batch_plan,PlanStep,Recipe
from luanti_course.skills import ActionLock,Failure,organize_inventory,run,place_block
from luanti_course.motion import Motion,turn
from test_skills import world

class PolishTests(unittest.TestCase):
 def test_api(self):
  for name in ('motion','equip','place_block','organize_inventory'):self.assertTrue(callable(getattr(Game,name,None)))
  self.assertIn('instant',inspect.signature(Game.look).parameters)
  self.assertIn('recover',inspect.signature(Game.collect).parameters)
 def test_batch_adjacent_outputs(self):
  book=RecipeBook.voxelibre();plan=book.plan('mcl_core:stick',16,{'mcl_core:wood':8},gather=False)
  batched=batch_plan(plan,book)
  self.assertEqual(len(batched),1);self.assertEqual(batched[0].count,16)
 def test_batch_limits_and_order(self):
  book=RecipeBook.voxelibre();plan=book.plan('wooden_pickaxe',2,{'mcl_core:wood':6,'mcl_core:stick':4},gather=False,has_table=True)
  self.assertEqual(len(batch_plan(plan,book)),2) # tools stack max=1
  r=Recipe('a',1,1,('b',),(('b','c'),));a=PlanStep('craft','a',1,r,('b',))
  self.assertEqual(len(batch_plan((a,a),book)),2) # replacements are not batched
 def test_policy_validation(self):
  for v in (1,None,'yes'):
   with self.assertRaises(ValueError):Traversal(allow_swim=v)
 def test_surface_water_only(self):
  w=world();w.nodes[(1,0,0)]=Node('water',False,liquid=True,drowning=1)
  self.assertFalse(w.standable((1,1,0)))
  w.traversal=Traversal(allow_swim=True);self.assertTrue(w.standable((1,1,0)))
  w.nodes[(1,1,0)]=Node('water',False,liquid=True,drowning=1)
  self.assertFalse(w.standable((1,1,0))) # no diving
  w.nodes[(1,1,0)]=Node('air',False);w.nodes[(1,0,0)]=Node('lava',False,liquid=True,damage=4)
  self.assertFalse(w.standable((1,1,0)))
 def test_ladder_vertical_edges(self):
  w=world();ladder=Node('ladder',False,climbable=True)
  for y in (1,2,3):w.nodes[(0,y,0)]=ladder
  w.nodes[(0,4,0)]=Node('air',False)
  w.nodes[(0,2,0)]=Node('wall_ladder',True,climbable=True,full_cube=False)
  self.assertIn((0,2,0),dict(w.neighbors((0,1,0))))
  p,_=w.path((0,1,0),lambda p:p==(0,3,0));self.assertIsNotNone(p)
  w.traversal=Traversal(allow_climb=False);self.assertFalse(w.standable((0,2,0)))
 def test_single_gap_and_headroom(self):
  w=world();w.traversal=Traversal(allow_jump_gaps=True)
  w.nodes[(1,0,0)]=Node('air',False);w.nodes[(1,-1,0)]=Node('air',False)
  self.assertIn((2,1,0),dict(w.neighbors((0,1,0))))
  w.nodes[(1,3,0)]=Node('stone',True)
  self.assertNotIn((2,1,0),dict(w.neighbors((0,1,0))))
 def test_gap_unknown_below_blocked(self):
  w=world();w.traversal=Traversal(allow_jump_gaps=True);w.nodes[(1,0,0)]=Node('air',False)
  self.assertNotIn((2,1,0),dict(w.neighbors((0,1,0))))
 def motion_game(self):
  events=[];g=SimpleNamespace(_action_lock=ActionLock(),_epoch=1,_closed=False,_cancel=threading.Event(),_motion=None,_skill_depth=0,capabilities=('steer',))
  state=SimpleNamespace(control='agent',control_epoch=1,dead=False,yaw=0,pitch=0)
  g.observe=lambda:state
  def submit(op,**kwargs):events.append((op,kwargs));return SimpleNamespace(operation=op)
  g._submit=submit
  return g,state,events
 def test_scope_never_stops_between_segments(self):
  g,_,events=self.motion_game()
  with Motion(g) as m:
   m.hold(['forward'],.01);m.hold(['forward'],.01)
   self.assertFalse(any(op=='stop' for op,_ in events))
  self.assertEqual(events[-1][0],'stop');self.assertFalse(g._action_lock.locked())
  self.assertTrue(all(p['duration_ms']==400 for op,p in events if op=='input'))
 def test_scope_exception_stops_and_closes(self):
  g,_,events=self.motion_game()
  with self.assertRaises(RuntimeError):
   with Motion(g) as m:m.steer(20);raise RuntimeError('student loop error')
  self.assertEqual(events[-1][0],'stop')
  with self.assertRaises(ActionError):m.steer(0)
 def test_scope_cancel_and_owner_release(self):
  g,state,events=self.motion_game()
  with Motion(g) as m:
   g._cancel.set()
   with self.assertRaises(ActionCancelled):m.hold(['forward'],1)
   g._cancel.clear();state.control_epoch=2
   with self.assertRaises(ActionError):m.steer(0)
 def test_scope_rejects_nested_and_skills(self):
  g,_,_=self.motion_game()
  with Motion(g):
   with self.assertRaises(ActionError):
    with Motion(g):pass
   with self.assertRaises(ActionError):run(g,'collect',lambda c:None,timeout=1)
 def test_smooth_turn_bound_cancel_and_no_snap(self):
  g,state,events=self.motion_game()
  def observe():
   state.yaw+=min(25,90-state.yaw);return state
  g.observe=observe
  turn(g,90,0,1)
  self.assertEqual(events[-1][0],'stop');self.assertTrue(all(o in ('steer','stop') for o,_ in events))
  self.assertGreater(sum(o=='steer' for o,_ in events),1)
 def test_turn_wraparound(self):
  g,s,e=self.motion_game();s.yaw=359.9
  turn(g,0,0,1);self.assertEqual(len(e),2)
 def test_organize_preserves_metadata(self):
  items=[Item('a',2,0,'A'),Item('a',3,0,'A'),Item('a',1,0,'CUSTOM')]
  state=SimpleNamespace(inventory={'main':InventoryList(3,tuple(items))},raw={'wield':0})
  ctx=SimpleNamespace(read=lambda:state,book=SimpleNamespace(items={'a':{'stack_max':64}}),log=lambda *a,**k:None,operation='organize_inventory',details={})
  def move(c,fl,fs,tl,ts,n):
   a,b=items[fs],items[ts];items[fs]=Item(a.name if a.count>n else '',a.count-n,a.wear,a.stack_key if a.count>n else '');items[ts]=Item(b.name,b.count+n,b.wear,b.stack_key)
   state.inventory['main']=InventoryList(3,tuple(items))
  with patch('luanti_course.skills.move_confirmed',move):self.assertEqual(organize_inventory(ctx),1)
  self.assertEqual(items[0].count,5);self.assertEqual(items[2].stack_key,'CUSTOM');self.assertEqual(items[2].count,1)
 def test_output_does_not_merge_into_labeled_stack(self):
  from luanti_course.skills import main_space
  state=SimpleNamespace(inventory={'main':InventoryList(2,(Item('a',1,0,'CUSTOM'),Item('',0)))})
  ctx=SimpleNamespace(read=lambda:state,book=SimpleNamespace(items={'a':{'stack_max':64}}))
  self.assertEqual(main_space(ctx,'a',1,'PLAIN'),1)
 def test_cancelled_low_level_action_is_cancelled_result(self):
  from test_skills import SkillContractTests
  fake=SkillContractTests().fake_game()
  def action(c):raise ActionCancelled('test')
  r=run(fake,'test',action,timeout=1)
  self.assertEqual(r.status,'cancelled');self.assertEqual(r.reason,'cancelled')
 def test_organize_old_schema_never_guesses_metadata(self):
  state=SimpleNamespace(inventory={'main':InventoryList(2,(Item('a',1),Item('a',1)))})
  ctx=SimpleNamespace(read=lambda:state,book=SimpleNamespace(items={'a':{'stack_max':64}}),log=lambda *a,**k:None,operation='test')
  self.assertEqual(organize_inventory(ctx),0)

if __name__=='__main__':unittest.main()
