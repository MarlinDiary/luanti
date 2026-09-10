#!/usr/bin/env python3
"""Attach-only native motion and lateral-escape regression. Local fixtures only."""
import argparse,json,time,math,sys,threading,traceback
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--session',type=Path,required=True);p.add_argument('--cases',default='straight,route,pursuer,route_bend,route_edge,route_cancel,plateau,shifting_pursuers');a=p.parse_args()
sys.path.insert(0,str(a.sdk))
from luanti_course import Game,Traversal,__version__
from luanti_course.skills import run
from luanti_course.combat import flee
from test_session import Session
session=Session(a.session);a.output.mkdir(parents=True,exist_ok=False)
rows=[];samples=[];commands=[];case='setup'
def save():
 for n,v in [('results',rows),('samples',samples),('commands',commands)]: (a.output/(n+'.json')).write_text(json.dumps(v))
with session.connect(Game) as g:
 raw=g._request
 def req(op,**kw):
  t=time.monotonic();r=raw(op,**kw)
  if op=='observe':samples.append(dict(case=case,t=t,**{k:r.get(k) for k in ('position','velocity','yaw','hp','focused','audio_enabled','steering_active','input_active','dead','control','entities')}))
  else:commands.append(dict(case=case,t=t,op=op,args=kw))
  return r
 g._request=req
 try:
  for case in a.cases.split(','):
   timer=None
   try:
    spec=dict(id='motion_'+case);points=[]
    if case=='pursuer':spec.update(entities=[dict(name='persistent_fixture:target',position=[0,99.51,-4],chase=True,speed=2,damage=0)])
    if case=='route_bend':points=[(0,99.5,8),(8,99.5,8),(8,99.5,16)]
    if case=='route_edge':
     points=[(4,99.5,0),(4,99.5,4)];spec['fill']=[dict(min=[5,94,-2],max=[8,99,6],name='air')]
    if case in ('plateau','shifting_pursuers'):spec.update(entities=[dict(name='persistent_fixture:target',position=[x,99.51,z],chase=case=='shifting_pursuers',speed=2,damage=0) for x,z in [(8,0),(-8,0),(0,8),(0,-8)]])
    session.reset(g,spec);time.sleep(.25);s=g.observe(6);t=time.monotonic()
    if case=='straight':r=g.navigate_to((0,99.5,24),timeout=20)
    elif case=='route':r=g.navigate_route([(0,99.5,z) for z in (4,8,12,16,20,24)],timeout=25)
    elif case=='pursuer':r=g.flee_from(s.entities[0],safe_distance=13,timeout=20)
    elif case in ('route_bend','route_edge'):r=g.navigate_route(points,timeout=25)
    elif case=='route_cancel':
     timer=threading.Timer(1.25,g.stop);timer.start()
     r=g.navigate_route([(0,99.5,z) for z in (4,8,12,16,20,24)],timeout=25)
     timer.join()
    elif case in ('plateau','shifting_pursuers'):r=run(g,'flee_from',lambda c:flee(c,s.entities,safe_distance=12),timeout=30,traversal=Traversal(allow_swim=True),damage_budget=0)
    else:raise ValueError(case)
    end=time.monotonic();trace=[x for x in samples if x['case']==case and t<=x['t']<=end]
    middle=[x for x in trace if 2<x['position'][2]<22]
    gaps=[b['t']-a['t'] for a,b in zip(trace,trace[1:])];slow=[x for x in middle if math.hypot(x['velocity'][0],x['velocity'][2])<.5]
    time.sleep(.25);after=g.observe()
    row=dict(case=case,result=r.to_dict(),elapsed=end-t,samples=len(trace),middle_slow=len(slow),max_sample_gap=max(gaps,default=0),stops=sum(x['op']=='stop' and x['case']==case and t<=x['t']<=end for x in commands),passed=r.ok)
    assert r.status=='cancelled' if case=='route_cancel' else r.ok,r.to_dict()
    if case in ('straight','route'):assert len(slow)==0,row
    if case=='route':assert r.details['completed_waypoints']==6
    if case=='route_cancel':assert r.details.get('completed_waypoints',0)>=1
    if points:
     for point in points:assert min(math.dist(point,x['position']) for x in trace)<.65,(point,row)
    if case=='route_edge':assert min(x['position'][1] for x in trace)>99.4
    if case=='plateau':assert any(x['event']=='escape_frontier' for x in r.trace),r.to_dict()
    assert math.hypot(*[after.raw['velocity'][i] for i in (0,2)])<.25,after.raw['velocity']
    assert not after.raw['input_active'] and not after.raw['steering_active'] and not after.dead
    row['passed']=True;rows.append(row)
   except Exception as exc:rows.append(dict(case=case,passed=False,error=str(exc),traceback=traceback.format_exc()))
   finally:
    if timer:timer.cancel();timer.join()
   save();print(json.dumps(rows[-1]),flush=True)
 finally:
  case='cleanup';session.park(g);g.release_control();final=g.observe();(a.output/'final.json').write_text(json.dumps(dict(sdk=__version__,pid=session.meta['pid'],state=final.raw)));save()
assert samples and all(x['focused'] is False and x['audio_enabled'] is False for x in samples)
sys.exit(any(not r['passed'] for r in rows))
