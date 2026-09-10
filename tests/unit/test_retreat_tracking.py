import sys,unittest,math
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Entity
from luanti_course.combat import flee
from luanti_course.navigation import World,Node,Traversal,distance
from luanti_course.skills import follow_path

class Captured(Exception):pass

def separation(a,b,q):
 delta=tuple(y-x for x,y in zip(a,b));length=sum(x*x for x in delta)
 t=max(0,min(1,sum((q[i]-a[i])*delta[i] for i in range(3))/length)) if length else 0
 return distance(tuple(a[i]+t*delta[i] for i in range(3)),q)

def ground():
 w=World(Traversal(allow_interact=False))
 for x in range(-8,9):
  for z in range(-8,9):
   for y in range(-2,4):w.nodes[x,y,z]=Node('stone',True) if y<=0 else Node('air',False)
 return w

def mob(i,p):return Entity(i,i,'mobs_mc:zombie',p,p,(0,0,0),pointable=True)

class RetreatTrackingTests(unittest.TestCase):
 def test_short_escape_actually_starts_moving(self):
  w=ground();w.nodes={p:n for p,n in w.nodes.items() if p[0]==0 and -4<=p[2]<=1}
  e=mob(1,(0,.5,-3));s=NS(position=(0,.5,0),yaw=0,raw={'entities_available':True,'entities':[]},entities=(e,));reads=[0];calls=[]
  def read(*a):
   reads[0]+=1
   if reads[0]>20:raise AssertionError('replanning without any movement')
   return s
  def submit(op,**kw):calls.append((op,kw));raise Captured()
  ctx=NS(world=w,read=read,game=NS(capabilities=(),_submit=submit),within=lambda p:True,details={},log=lambda *a,**k:None,stop_input=lambda:None,recoveries={})
  with patch('luanti_course.combat.close_form'),patch('luanti_course.skills.time.monotonic',return_value=100),self.assertRaises(Captured):flee(ctx,(e,),3.8)
  self.assertEqual(calls[0][0],'steer');self.assertGreater(calls[0][1]['speed'],0)
 def test_explicit_target_does_not_hide_other_hostiles(self):
  selected=mob(1,(0,.5,-14));nearby=mob(2,(0,.5,3));s=NS(position=(0,.5,0),raw={'entities_available':True,'entities':[]},entities=(selected,nearby))
  ctx=NS(world=ground(),read=lambda *a:s,within=lambda p:True,details={},log=lambda *a,**k:None,stop_input=lambda:None)
  with patch('luanti_course.combat.close_form'),patch('luanti_course.combat.follow_path',side_effect=Captured),self.assertRaises(Captured):flee(ctx,(selected,),12)
  self.assertIn(list(nearby.ref),ctx.details['threats'])
 def steering(self,wet=False):
  w=ground();y=.5
  if wet:
   w.traversal=Traversal(allow_swim=True)
   for p,n in list(w.nodes.items()):
    if p[1]<=0:w.nodes[p]=Node('water',False,liquid=True,drowning=1)
   y=.05
  state=NS(position=(0,y,0),yaw=0,raw={'in_liquid':wet,'velocity':(0,0,0),'touching_ground':not wet})
  path=[(0,1,0),(1,1,0),(2,1,0),(3,1,0),(3,1,1),(3,1,2),(3,1,3),(3,1,4),(2,1,4),(1,1,4),(0,1,4)]
  calls=[];obstacle=(0,y,2)
  def submit(op,**kw):calls.append(kw);raise Captured()
  ctx=NS(world=w,read=lambda *a:state,game=NS(capabilities=(),_submit=submit),recoveries={},stop_input=lambda:None)
  allowed=lambda a,b:separation(a,b,obstacle)>=1.8
  ctx.movement_segment_allowed=allowed
  with self.assertRaises(Captured):follow_path(ctx,path,(0,y,4))
  theta=math.radians(calls[0]['heading']);direction=(-math.sin(theta),0,math.cos(theta))
  endpoint=tuple(state.position[i]+direction[i]*4 for i in range(3))
  self.assertGreaterEqual(separation(state.position,endpoint,obstacle),1.8)
 def test_flat_smoothing_keeps_threat_detour(self):self.steering()
 def test_water_smoothing_keeps_threat_detour(self):self.steering(True)
 def test_invalid_segment_stops_before_submitting_input(self):
  state=NS(position=(0,.5,0),yaw=0,raw={});calls=[]
  ctx=NS(world=ground(),read=lambda *a:state,game=NS(_submit=lambda *a,**k:self.fail('input sent through disallowed segment')),stop_input=lambda:calls.append('stop'))
  ctx.movement_segment_allowed=lambda a,b:False
  ok,_=follow_path(ctx,[(0,1,0),(1,1,0)],(1,.5,0))
  self.assertFalse(ok);self.assertEqual(calls,['stop'])

 def test_new_threat_interrupts_old_escape_leg(self):
  old=mob(1,(0,.5,-3));new=mob(2,(1,.5,0));s=NS(position=(0,.5,0),raw={'entities_available':True,'entities':[]},entities=(old,));stops=[]
  ctx=NS(world=ground(),read=lambda *a:s,within=lambda p:True,details={},log=lambda *a,**k:None,stop_input=lambda:stops.append(True))
  def follow(c,path,target,**kw):
   fresh=NS(entities=(old,new));self.assertTrue(kw['until'](fresh));self.assertEqual(stops,[True]);raise Captured()
  with patch('luanti_course.combat.close_form'),patch('luanti_course.combat.follow_path',follow),self.assertRaises(Captured):flee(ctx,(old,),12)
  self.assertFalse(hasattr(ctx,'movement_segment_allowed'))
 def test_segment_distance_includes_middle_and_zero_length(self):
  from luanti_course.combat import segment_clearance
  e=mob(1,(0,.5,2))
  self.assertEqual(segment_clearance((0,.5,0),(0,.5,4),(e,)),0)
  self.assertEqual(segment_clearance((0,.5,0),(0,.5,0),(e,)),2)
  self.assertEqual(segment_clearance((0,.5,0),(0,.5,0),()),math.inf)
 def test_corner_advance_keeps_constraint_after_first_shortcut(self):
  w=ground();states=iter([NS(position=(0,.5,0),yaw=0,raw={}),NS(position=(1.84,.5,1.61),yaw=-30,raw={})]);calls=[]
  def submit(op,**kw):
   calls.append(kw)
   if len(calls)==2:raise Captured()
  c=NS(world=w,read=lambda *a:next(states),game=NS(capabilities=(),_submit=submit),recoveries={},sleep=lambda t:None,stop_input=lambda:None)
  c.movement_segment_allowed=lambda a,b:separation(a,b,(0,.5,2))>=1.8
  path=[(0,1,0),(1,1,0),(2,1,0),(3,1,0),(3,1,1),(3,1,2),(3,1,3),(3,1,4),(2,1,4),(1,1,4),(0,1,4)]
  with self.assertRaises(Captured):follow_path(c,path,(0,.5,4))

if __name__=='__main__':unittest.main()
