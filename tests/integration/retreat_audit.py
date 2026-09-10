#!/usr/bin/env python3
"""Isolated native-client retreat regressions. Never use on a course server."""
import argparse,json,sys,time,traceback
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--session',type=Path,required=True);p.add_argument('--cases',default='short_corridor,blocked_alcove,threat_detour,two_pursuers');a=p.parse_args()
ROOT=Path(__file__).resolve().parents[2]
assert (a.sdk/'luanti_course/__init__.py').is_file();sys.path.insert(0,str(a.sdk));sys.path.insert(0,str(ROOT/'tests/integration'))
from test_session import Session
from luanti_course import Game
import luanti_course
session=Session(a.session);a.output.mkdir(exist_ok=False)
rows=[];samples=[];commands=[];current='setup'
def save():
 for name,value in [('results',rows),('samples',samples),('commands',commands)]: (a.output/(name+'.json')).write_text(json.dumps(value,indent=2))
with session.connect(Game) as g:
 raw=g._request
 def request(op,**kw):
  r=raw(op,**kw)
  if op=='observe':samples.append(dict(case=current,t=time.monotonic(),**{k:r.get(k) for k in ('position','hp','dead','yaw','velocity','control','input_active','steering_active','entities','focused','audio_enabled')}))
  else:commands.append(dict(case=current,t=time.monotonic(),op=op,args=kw,response=r))
  return r
 g._request=request
 try:
  for name in a.cases.split(','):
   current=name
   if name in ('short_corridor','blocked_alcove'):
    spec=dict(id=name,entities=[dict(name='persistent_fixture:target',position=[0,99.51,-3])],fill=[
     dict(min=[-1,100,-6],max=[-1,102,2],name='mcl_core:stone'),
     dict(min=[1,100,-6],max=[1,102,2],name='mcl_core:stone'),
     dict(min=[-1,100,2],max=[1,102,2],name='mcl_core:stone')])
   elif name=='two_pursuers':
    spec=dict(id=name,night=True,entities=[dict(name='mobs_mc:zombie',position=[-3,99.51,3]),dict(name='mobs_mc:skeleton',position=[3,99.51,4])])
   elif name=='threat_detour':
    spec=dict(id=name,entities=[dict(name='persistent_fixture:target',position=[0,99.51,2])])
   else:raise ValueError(name)
   session.reset(g,spec);time.sleep(.25)
   before=g.observe();target=next(e for e in before.entities if not e.is_player)
   sample_start=len(samples)
   if name=='threat_detour':
    from luanti_course.skills import run,follow_path,Failure
    from luanti_course.combat import segment_clearance
    path=[(0,100,0),(1,100,0),(2,100,0),(3,100,0),(3,100,1),(3,100,2),(3,100,3),(3,100,4),(2,100,4),(1,100,4),(0,100,4)]
    def action(c):
     c.read(6);c.movement_segment_allowed=lambda a,b:segment_clearance(a,b,(target,))>=1.8
     ok,_=follow_path(c,path,(0,99.5,4))
     if not ok:raise Failure('detour_blocked')
    r=run(g,'threat_detour',action,timeout=12)
   else:r=g.flee_from(None if name=='two_pursuers' else target,safe_distance=13 if name=='two_pursuers' else 12 if name=='blocked_alcove' else 3.8,timeout=18 if name=='two_pursuers' else 6)
   after=g.observe();row=dict(case=name,passed=r.ok,result=r.to_dict(),before=before.position,after=after.position,hp=after.hp)
   if name=='blocked_alcove':row['passed']=r.reason=='escape_route_unavailable' and after.position[2]>.7 and r.elapsed<3
   if name=='threat_detour':
    from luanti_course.navigation import distance
    d=min(distance(x['position'],target.position) for x in samples[sample_start:] if x['case']==name)
    row['minimum_sampled_clearance']=d;row['passed']=r.ok and d>=1.65
   row['passed']=row['passed'] and not after.dead
   rows.append(row);save();print(json.dumps(row),flush=True)
 finally:
  current='cleanup';session.park(g);g.release_control();s=g.observe();(a.output/'final.json').write_text(json.dumps(s.raw));save()
print('SDK',luanti_course.__version__,luanti_course.__file__)
sys.exit(any(not r['passed'] for r in rows))
