import unittest,sys,threading
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Game,InventoryList,Item,Traversal,ActionError
from luanti_course.bridging import bridge_axis,stream_bridge
from luanti_course.navigation import Node
from luanti_course.skills import Failure,face

class BridgePolicyTests(unittest.TestCase):
 def test_straight_span_four_directions(self):
  for d in ((1,0,0),(-1,0,0),(0,0,1),(0,0,-1)):
   self.assertEqual(bridge_axis((0,99,0),(d[0],99,d[2]),(d[0]*8,99.5,d[2]*8)),d)
 def test_turn_height_and_reverse_are_not_invented_spans(self):
  for target,goal in [((1,99,1),(8,99.5,8)),((1,100,0),(8,100.5,0)),((1,99,0),(-8,99.5,0)),((1,99,0),(8,99.5,2))]:
   self.assertIsNone(bridge_axis((0,99,0),target,goal))
 def test_old_native_uses_existing_navigation(self):
  self.assertFalse(stream_bridge(NS(game=NS(capabilities=('steer',))),[('build',(1,99,0))],(4,99.5,0)))
 def test_multiple_actions_do_not_take_stream_shortcut(self):
  self.assertFalse(stream_bridge(NS(),[('build',(1,99,0)),('dig',(1,100,0))],(4,99.5,0)))
 def test_budget_stops_before_any_motion_or_placement(self):
  calls=[];state=NS(position=(0,99.5,0),inventory={'main':InventoryList(9,(Item('stone',4),))})
  world=NS(start=lambda p:(0,100,0),nodes={(0,99,0):Node('stone',True),(1,99,0):Node('air',False,buildable=True)},traversal=Traversal(build_with='stone',edit_budget=0))
  ctx=NS(game=NS(capabilities=('independent_heading','steer_place'),_submit=lambda *a,**k:calls.append((a,k))),read=lambda *a:state,world=world,log=lambda *a,**k:None,terrain_edits=0,within=lambda p:True,stop_input=lambda:calls.append('stop'))
  with patch('luanti_course.bridging.wield_slot'):
   with self.assertRaises(Failure) as r:stream_bridge(ctx,[('build',(1,99,0))],(4,99.5,0))
  self.assertEqual(r.exception.reason,'terrain_edit_budget');self.assertEqual(calls,['stop'])

class ActionCompositionTests(unittest.TestCase):
 def test_already_aimed_does_not_reissue_turn_or_stop(self):
  state=NS(eye=(0,2,0),yaw=0,pitch=0);ctx=NS(check=lambda:None,read=lambda:state,game=NS(_submit=lambda *a,**kw:self.fail('redundant steering')))
  self.assertIs(face(ctx,(0,2,1)),state)
 def test_long_return_uses_continuous_chunks_not_per_cell_navigation(self):
  from luanti_course.excursions import trail_to
  trail=[(x,100,0) for x in range(10)];state=NS(position=(9,99.5,0));calls=[]
  ctx=NS(read=lambda *a:state,world=NS(standable=lambda p:True,edge_plan=lambda p,q:()),details={},log=lambda *a,**kw:None)
  def follow(c,path,target,tolerance,**kw):calls.append((path,kw));state.position=target;return True,None
  with patch('luanti_course.skills.follow_path',side_effect=follow),patch('luanti_course.excursions.navigate',side_effect=AssertionError('per-cell stop')):
   trail_to(ctx,trail,0)
  self.assertEqual(len(calls),2);self.assertEqual(ctx.details['return_progress'],0);self.assertTrue(calls[0][1]['through']);self.assertFalse(calls[-1][1]['through'])
 def test_changed_trail_uses_normal_navigation_instead_of_blind_follow(self):
  from luanti_course.excursions import trail_to
  state=NS(position=(1,99.5,0));calls=[]
  ctx=NS(read=lambda *a:state,world=NS(standable=lambda p:False),details={},log=lambda *a,**kw:None)
  with patch('luanti_course.excursions.navigate',side_effect=lambda c,p:calls.append(p)):
   trail_to(ctx,[(0,100,0),(1,100,0)],0)
  self.assertEqual(calls,[(0,99.5,0)])

class StudentMotionTests(unittest.TestCase):
 def motion(self,caps):
  from luanti_course.motion import Motion
  calls=[];g=NS(capabilities=caps,_submit=lambda op,**kw:calls.append((op,kw)))
  m=Motion(g);m.check=lambda:None;return m,calls
 def test_look_back_while_moving_forward(self):
  m,calls=self.motion(('independent_heading','steer_place'));m.steer(90,move_heading=-90,sneak=True,place=True)
  self.assertEqual(calls[0][1]['heading'],90);self.assertEqual(calls[0][1]['move_heading'],-90);self.assertTrue(calls[0][1]['place'])
 def test_move_heading_needs_capability(self):
  m,calls=self.motion(())
  with self.assertRaises(ActionError):m.steer(0,move_heading=90)
  self.assertEqual(calls,[])
 def test_new_arguments_validate_before_submit(self):
  m,calls=self.motion(('independent_heading','steer_place'))
  for value in (True,float('nan'),float('inf'),36001):
   with self.assertRaises(ValueError):m.steer(0,move_heading=value)
  with self.assertRaises(ValueError):m.steer(0,place=1)
  self.assertEqual(calls,[])

class FixtureGuardTests(unittest.TestCase):
 def test_bad_scene_never_touches_game_or_world(self):
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'integration'))
  from test_session import Session
  for spec in ({'id':'bad','fill':[{'min':[0,82,0],'max':[1,100,1],'name':'stone'}]}, {'id':'bad','nodes':[(33,100,0,'stone')]}):
   with self.assertRaises(ValueError):Session.reset(NS(),None,spec)
 def test_valid_current_world_bounds(self):
  from test_session import validate_spec
  validate_spec({'id':'valid','fill':[{'min':[-32,88,-32],'max':[32,118,32],'name':'stone'}]})

class ConstructionFluencyTests(unittest.TestCase):
 def test_blueprint_sweep_does_not_reverse_with_moving_actor(self):
  from luanti_course.construction import build
  state=NS(position=(0,99.5,0));calls=[]
  ctx=NS(read=lambda *a:state,world=NS(nodes={},traversal=Traversal()),terrain_edits=0,details={},book=NS(resolve=lambda x:x))
  # A perturbed stance must not reverse the initially selected sweep direction.
  def place(c,item,p):calls.append(p);state.position=(20,99.5,20)
  with patch('luanti_course.construction.construction_station'),patch('luanti_course.construction.place_block',side_effect=place):
   build(ctx,[('stone',(3,100,z)) for z in (5,1,4,0,3,2)])
  self.assertEqual(calls,[(3,100,z) for z in range(6)])
  self.assertEqual(ctx.terrain_edits,6);self.assertEqual(ctx.details['remaining_blocks'],0)
 def test_already_built_blueprint_spends_no_material_or_motion(self):
  from luanti_course.construction import build
  target=(3,100,0);state=NS(position=(0,99.5,0));ctx=NS(read=lambda *a:state,world=NS(nodes={target:Node('stone',True)},traversal=Traversal()),terrain_edits=0,details={},book=NS(resolve=lambda x:x))
  with patch('luanti_course.construction.place_block',side_effect=AssertionError('duplicate placement')):
   build(ctx,[('stone',target)])
  self.assertEqual(ctx.terrain_edits,0);self.assertEqual(ctx.details['completed_blocks'],[target])

class FixtureNameTests(unittest.TestCase):
 def test_invalid_id_never_reaches_lua(self):
  from test_session import Session
  for name in ('spaces here','tuple_(1, 0, 0)','',None):
   with self.assertRaises(ValueError):Session.reset(NS(),None,{'id':name})

class BridgeCancellationEvidenceTests(unittest.TestCase):
 def test_cancel_after_server_placement_keeps_observed_world_change(self):
  # Model cancellation arriving just after replication, before the next ctx.read.
  from luanti_course.bridging import stream_bridge
  from luanti_course.skills import Failure
  support=(0,99,0);target=(1,99,0);reads=[0]
  air=Node('air',False,buildable=True)
  nodes={support:Node('stone',True),target:air,(1,100,0):air,(1,101,0):air}
  state=NS(position=(0,99.5,0),inventory={'main':InventoryList(9,(Item('stone',4),))},inventory_revision=1)
  confirmed=NS(position=(.8,99.5,0),inventory={'main':InventoryList(9,(Item('stone',3),))},inventory_revision=2)
  def read(*a):
   reads[0]+=1
   if reads[0]==4:
    nodes[target]=Node('stone',True)
    raise Failure('cancelled',status='cancelled')
   return state
  world=NS(start=lambda p:(0,100,0),nodes=nodes,traversal=Traversal(build_with='stone'),update=lambda s:None)
  ctx=NS(game=NS(capabilities=('independent_heading','steer_place'),observe=lambda *a:confirmed,_closed=False),read=read,world=world,book=NS(matches=lambda n,item:n==item),log=lambda *a,**k:None,terrain_edits=0,within=lambda p:True,stop_input=lambda:None,details={},deadline=1e20)
  with patch('luanti_course.bridging.wield_slot'):
   with self.assertRaises(Failure):stream_bridge(ctx,[('build',target)],(4,99.5,0))
  self.assertEqual(ctx.terrain_edits,1)
  self.assertEqual(ctx.details['terrain_changes'],[dict(action='build',position=target)])

class NativeVersionContractTests(unittest.TestCase):
 def test_endpoint_and_hello_match_release_metadata(self):
  import json,re
  root=Path(__file__).resolve().parents[2];version=json.loads((root/'engine/upstream.json').read_text())['course_version']
  for name in ('course_bridge.cpp','game_course.inc'):
   versions=re.findall(r'\["course_version"\]\s*=\s*"([^"]+)"',(root/'engine/src'/name).read_text())
   self.assertEqual(versions,[version])
