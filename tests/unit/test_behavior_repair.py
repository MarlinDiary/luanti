import sys, unittest, math
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Game, Entity
from luanti_course.navigation import World,Node,Traversal,distance
from luanti_course.skills import Failure,follow_path
from luanti_course.combat import flee

class Captured(Exception):pass

def plateau():
    # All known points are closer to one of two pursuers than the start;
    # a lateral edge of observations remains reachable without approaching melee.
    w=World(Traversal(allow_interact=False))
    for x in range(-6,7):
        for z in range(-2,3):
            w.nodes[x,0,z]=Node('stone',True)
            for y in (1,2,3):w.nodes[x,y,z]=Node('air',False)
    enemies=tuple(Entity(i,i,'mobs_mc:zombie',(0,.5,z),(0,2,z),(0,0,0),pointable=True) for i,z in [(1,-9),(2,9)])
    # Block the more distant sideways cells: force a detour whose destination
    # does not improve distance by .08 (mirrors the captured course failure).
    for x in (-6,6):
        for z in range(-2,3):w.nodes[x,1,z]=Node('stone',True)
    return w,enemies

class RouteTests(unittest.TestCase):
    def test_intermediate_only_handoffs(self):
        c=NS(details={});calls=[]
        def run(g,op,fn,**kw):return fn(c)
        with patch('luanti_course.skills.run',run),patch('luanti_course.skills.navigate',side_effect=lambda c,p,**kw:calls.append(kw)):
            Game.navigate_route(NS(),[(0,.5,4),(0,.5,8),(0,.5,12)])
        self.assertEqual([x.get('through',False) for x in calls],[True,True,False]);self.assertEqual(c.details['completed_waypoints'],3)
    def test_cruise_does_not_brake_at_intermediate_waypoint(self):
        w,_=plateau();commands=[]
        for x in range(-1,2):
            for z in (3,4):
                w.nodes[x,0,z]=Node('stone',True)
                for y in (1,2,3):w.nodes[x,y,z]=Node('air',False)
        s=NS(position=(0,.5,.2),yaw=0,raw={'velocity':(0,0,4),'touching_ground':True})
        def submit(op,**kw):commands.append(kw);raise Captured()
        c=NS(world=w,within=lambda p:True,read=lambda *a:s,game=NS(_submit=submit,capabilities=()),recoveries={},stop_input=Mock())
        with self.assertRaises(Captured):follow_path(c,[(0,1,0),(0,1,1)],(0,.5,1),.45,through=True,cruise=True)
        self.assertEqual(commands[0]['speed'],1);self.assertLessEqual(commands[0]['duration_ms'],400)

if __name__=='__main__':unittest.main()

class LateralEscapeTests(unittest.TestCase):
    def context(self):
        import json,gzip
        with gzip.open(Path(__file__).with_name('fixtures')/'retreat_plateau.json.gz','rt') as f:v=json.load(f)
        w=World(Traversal(allow_swim=True));w.nodes={tuple(p):Node(**dict(n,boxes=None if n['boxes'] is None else tuple(tuple(b) for b in n['boxes']))) for p,n in v['nodes']};w.physics=v['physics'];w.radius=v['radius'];w.height=v['height']
        enemies=tuple(Entity(**e) for e in v['entities']);s=NS(position=tuple(v['position']),raw={'entities_available':True,'entities':[]},entities=enemies)
        return NS(world=w,read=lambda *a:s,within=lambda p:True,details={},log=Mock(),stop_input=Mock()),s
    def test_captured_plateau_uses_known_lateral_frontier(self):
        from luanti_course.combat import segment_clearance
        c,s=self.context();near=min(distance(s.position,e.position) for e in s.entities)
        def follow(ctx,path,target,**kw):
            self.assertTrue(c.world.frontier(path[-1]));self.assertLessEqual(min(distance(target,e.position) for e in s.entities),near+.08)
            self.assertGreaterEqual(min(segment_clearance(a,b,s.entities) for a,b in zip([s.position]+[c.world.point(p) for p in path],[c.world.point(p) for p in path])),2.85)
            raise Captured()
        with patch('luanti_course.combat.close_form'),patch('luanti_course.combat.follow_path',follow),self.assertRaises(Captured):flee(c,safe_distance=15)
        self.assertEqual(c.details['frontiers_attempted'],1)
    def test_lateral_goal_sticks_across_replans(self):
        c,s=self.context();goals=[]
        def follow(ctx,path,target,**kw):
            goals.append(target)
            if len(goals)==3:raise Captured()
            # One path step, then the .5 s follower refresh. Do not turn back
            # toward the old maximum even though that is now a safer endpoint.
            s.position=ctx.world.point(path[min(1,len(path)-1)])
            return True,None
        with patch('luanti_course.combat.close_form'),patch('luanti_course.combat.follow_path',follow),self.assertRaises(Captured):flee(c,safe_distance=15)
        self.assertEqual(len(set(goals)),1)
    def test_lateral_path_keeps_outer_segment_constraint(self):
        c,s=self.context();prior=lambda a,b:False;c.movement_segment_allowed=prior
        def follow(ctx,path,target,**kw):
            self.assertFalse(ctx.movement_segment_allowed(s.position,target));raise Captured()
        with patch('luanti_course.combat.close_form'),patch('luanti_course.combat.follow_path',follow),self.assertRaises(Captured):flee(c,safe_distance=15)
        self.assertIs(c.movement_segment_allowed,prior)
    def test_changed_pursuer_refreshes_guard_without_stop_pulse(self):
        c,s=self.context();c.world,_=plateau();s.position=(0,.5,0);e=Entity(1,1,'mobs_mc:zombie',(0,.5,-3),(0,2,-3),(0,0,1),pointable=True);s.entities=(e,)
        def follow(ctx,path,target,**kw):
            close=Entity(1,1,'mobs_mc:zombie',(0,.5,.5),(0,2,.5),(0,0,1),pointable=True)
            self.assertFalse(kw['until'](NS(entities=(close,))))
            self.assertFalse(ctx.movement_segment_allowed(s.position,target));c.stop_input.assert_not_called();raise Captured()
        with patch('luanti_course.combat.close_form'),patch('luanti_course.combat.follow_path',follow),self.assertRaises(Captured):flee(c,safe_distance=12)

class RetreatBandTests(unittest.TestCase):
 def test_pursuer_inside_band_permits_only_departure(self):
  from luanti_course.combat import retreat_segment_allowed
  e=Entity(1,1,'mobs_mc:zombie',(0,.5,-2),(0,2,-2),(0,0,2),pointable=True)
  self.assertTrue(retreat_segment_allowed((0,.5,0),(0,.5,3),(e,),2.85))
  self.assertFalse(retreat_segment_allowed((0,.5,0),(0,.5,-1),(e,),2.85))
  other=Entity(2,2,'mobs_mc:zombie',(0,.5,4),(0,2,4),(0,0,0),pointable=True)
  self.assertFalse(retreat_segment_allowed((0,.5,0),(0,.5,3),(e,other),2.85))
 def test_motion_keeps_full_segment_not_just_endpoint(self):
  from luanti_course.combat import retreat_segment_allowed
  e=Entity(1,1,'mobs_mc:zombie',(0,.5,3),(0,2,3),(0,0,0),pointable=True)
  self.assertFalse(retreat_segment_allowed((0,.5,0),(0,.5,7),(e,),2.85))

class RouteHandoffGuardTests(unittest.TestCase):
 def context(self,open_runout):
  from collections import Counter
  w,_=plateau()
  if open_runout:
   for z in range(-2,3):w.nodes[6,1,z]=Node('air',False)
  s=NS(position=(0,.5,0),raw={},yaw=0)
  c=NS(game=NS(capabilities=('steer',)),world=w,read=lambda *a:s,last=s,radius=64,within=lambda p:True,blocked=set(),log=Mock(),stop_input=Mock(),sleep=Mock(),recoveries=Counter())
  return c
 def test_unknown_or_obstructed_runout_keeps_braking(self):
  from luanti_course.skills import navigate
  c=self.context(False)
  with patch('luanti_course.bridging.direct_bridge',return_value=False),patch('luanti_course.skills.follow_path',return_value=(True,None)) as follow:
   navigate(c,(4,.5,0),through=True)
  self.assertNotIn('cruise',follow.call_args.kwargs);c.stop_input.assert_called_once()
 def test_known_supported_runout_allows_cruise(self):
  from luanti_course.skills import navigate
  c=self.context(True)
  with patch('luanti_course.bridging.direct_bridge',return_value=False),patch('luanti_course.skills.follow_path',return_value=(True,None)) as follow:
   navigate(c,(3,.5,0),through=True)
  self.assertTrue(follow.call_args.kwargs['cruise']);c.stop_input.assert_not_called()
 def test_failed_handoff_stops_before_propagating(self):
  from luanti_course.skills import navigate
  c=self.context(True)
  with patch('luanti_course.bridging.direct_bridge',return_value=False),patch('luanti_course.skills.follow_path',side_effect=Failure('cancelled',status='cancelled')),self.assertRaises(Failure):navigate(c,(3,.5,0),through=True)
  c.stop_input.assert_called_once()

class LiveRunoutTests(unittest.TestCase):
 def test_new_obstacle_at_runout_stops_before_handoff_return(self):
  w,_=plateau();w.nodes[5,1,0]=Node('stone',True)
  c=NS(world=w,within=lambda p:True,read=lambda *a:NS(position=(3.7,.5,0),raw={},yaw=-90),stop_input=Mock(),game=NS(_submit=Mock()))
  ok,_=follow_path(c,[(0,1,0),(4,1,0)],(4,.5,0),tolerance=.45,through=True,cruise=True)
  self.assertTrue(ok);c.stop_input.assert_called_once();c.game._submit.assert_not_called()

class EscapeLegTests(unittest.TestCase):
 def test_changing_pursuers_does_not_reselect_half_finished_leg(self):
  w,_=plateau();e=Entity(1,1,'mobs_mc:zombie',(0,.5,-3),(0,2,-3),(0,0,1),pointable=True)
  s=NS(position=(0,.5,0),raw={'entities_available':True,'entities':[]},entities=(e,));goals=[]
  c=NS(world=w,read=lambda *a:s,within=lambda p:True,details={},log=Mock(),stop_input=Mock())
  def follow(ctx,path,target,**kw):
   goals.append(target)
   if len(goals)==2:raise Captured()
   s.position=tuple((a+b*.1)/1.1 for a,b in zip(s.position,target))
   shifted=Entity(1,1,'mobs_mc:zombie',(-1,.5,-2),(-1,2,-2),(1,0,1),pointable=True);s.entities=(shifted,)
   return True,None
  with patch('luanti_course.combat.close_form'),patch('luanti_course.combat.follow_path',follow),self.assertRaises(Captured):flee(c,safe_distance=12)
  self.assertEqual(goals[0],goals[1])

class EscapeHistoryTests(unittest.TestCase):
 def test_expired_leg_does_not_reselect_same_local_maximum(self):
  w,_=plateau();e=Entity(1,1,'mobs_mc:zombie',(0,.5,-3),(0,2,-3),(0,0,0),pointable=True)
  s=NS(position=(0,.5,0),raw={'entities_available':True,'entities':[]},entities=(e,));goals=[];clock=[100.0]
  c=NS(world=w,read=lambda *a:s,within=lambda p:True,details={},log=Mock(),stop_input=Mock())
  def follow(ctx,path,target,**kw):
   goals.append(target)
   if len(goals)==2:raise Captured()
   clock[0]+=2;return True,None
  with patch('luanti_course.combat.close_form'),patch('luanti_course.combat.time.monotonic',side_effect=lambda:clock[0]),patch('luanti_course.combat.follow_path',follow),self.assertRaises(Captured):flee(c,safe_distance=12)
  self.assertGreater(distance(goals[0],goals[1]),1.5)

class DiagonalEscapeTests(unittest.TestCase):
 def context(self):
  from luanti_course.combat import retreat_segment_allowed
  w=World(Traversal(allow_interact=False))
  for x in range(-8,9):
   for z in range(-8,9):
    w.nodes[x,0,z]=Node('stone',True)
    for y in (1,2,3):w.nodes[x,y,z]=Node('air',False)
  es=tuple(Entity(i,i,'mobs_mc:zombie',p,p,(0,0,0),pointable=True) for i,p in [(1,(-5,.5,1)),(2,(-1,.5,5))])
  return NS(world=w,within=lambda p:True),NS(position=(-3,.5,3)),es
 def test_observed_diagonal_crosses_safe_gap_between_threats(self):
  from luanti_course.combat import escape_ray,segment_clearance
  c,s,es=self.context();safety=lambda p:min(distance(p,e.position) for e in es)
  path,_=c.world.path(c.world.start(s.position),lambda p:safety(c.world.point(p))>=4,within=lambda p:safety(c.world.point(p))>=2.7)
  self.assertIsNone(path)
  ray=escape_ray(c,s,es,2.7,lambda p:safety(c.world.point(p))>=4)
  self.assertIsNotNone(ray);self.assertGreaterEqual(segment_clearance(s.position,c.world.point(ray[-1]),es),2.7)
 def test_diagonal_does_not_invent_unobserved_support(self):
  from luanti_course.combat import escape_ray
  c,s,es=self.context();c.world.nodes={}
  self.assertIsNone(escape_ray(c,s,es,2.7,lambda p:True))

class EscapeReplanTests(unittest.TestCase):
 def test_invalidated_live_leg_stops_then_replans(self):
  w,_=plateau();e=Entity(1,1,'mobs_mc:zombie',(0,.5,-3),(0,2,-3),(0,0,0),pointable=True)
  s=NS(position=(0,.5,0),raw={'entities_available':True,'entities':[]},entities=(e,));calls=[]
  c=NS(world=w,read=lambda *a:s,within=lambda p:True,details={},log=Mock(),stop_input=Mock())
  def follow(ctx,path,target,**kw):
   calls.append(target)
   if len(calls)==1:return False,None
   c.stop_input.assert_called();raise Captured()
  with patch('luanti_course.combat.close_form'),patch('luanti_course.combat.follow_path',follow),self.assertRaises(Captured):flee(c,safe_distance=12)
  self.assertEqual(len(calls),2)
