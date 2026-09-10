#!/usr/bin/env python3
"""Pinned-reference behavior regressions in the existing isolated native world."""
import argparse,json,sys,time,traceback
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--session',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cases',default='defense_retarget,priority_retreat,settled_flee');a=p.parse_args()
assert (a.sdk/'luanti_course/__init__.py').is_file();sys.path.insert(0,str(a.sdk))
from luanti_course import Game,SurvivalConfig,__version__
from test_session import Session
session=Session(a.session);a.output.mkdir(parents=True,exist_ok=False)
rows=[];samples=[];commands=[];current='setup'
def save():
 for n,v in [('results',rows),('samples',samples),('commands',commands)]: (a.output/(n+'.json')).write_text(json.dumps(v,indent=2))
with session.connect(Game) as g:
 raw=g._request
 def request(op,**kw):
  r=raw(op,**kw)
  if op=='observe':samples.append(dict(case=current,time=time.monotonic(),**{k:r.get(k) for k in ('position','hp','dead','control','input_active','steering_active','entities','focused','audio_enabled')}))
  else:commands.append(dict(case=current,time=time.monotonic(),op=op,args=kw,response=r))
  return r
 g._request=request
 try:
  for current in a.cases.split(','):
   start=time.monotonic();detail={}
   try:
    if current=='defense_retarget':
     session.reset(g,dict(id=current,night=True,entities=[dict(name='mobs_mc:zombie',position=[0,99.51,3]),dict(name='mobs_mc:zombie',position=[3,99.51,5])],inventory=['mcl_tools:sword_diamond','mcl_armor:helmet_diamond','mcl_armor:chestplate_diamond','mcl_armor:leggings_diamond','mcl_armor:boots_diamond']))
     time.sleep(.3);r=g.defend_self(radius=12,timeout=45,damage_budget=18);detail=r.to_dict()
     target_ids={c['args']['target_id'] for c in commands if c['case']==current and c['op']=='attack'}
     detail['distinct_attacked_targets']=sorted(target_ids)
     assert r.ok and len(target_ids)>=2 and r.details['outcome']=='no_attackable_threat',detail
    elif current=='priority_retreat':
     session.reset(g,dict(id=current,night=True,entities=[dict(name='mobs_mc:zombie',position=[0,99.51,4.5])],inventory=['mcl_tools:sword_wood']))
     events=[];config=SurvivalConfig(enemies='defend',critical_hp=19,threat_radius=8,safe_distance=13,action_timeout=30,poll_interval=.05)
     with g.survival(config) as guard:
      end=time.monotonic()+40
      while time.monotonic()<end:
       events.extend(guard.events())
       if any(e['event']=='reaction_finished' and e['decision']['action']=='flee_from' for e in events):break
       if guard.paused:break
       time.sleep(.05)
     events.extend(guard.events());detail=events
     assert any(e['event']=='reaction_preempted' and e['previous']['action']=='defend_self' and e['decision']['action']=='flee_from' for e in events),events
     assert any(e['event']=='reaction_finished' and e['decision']['action']=='flee_from' and e['result']['status']=='success' for e in events),events
    elif current=='settled_flee':
     session.reset(g,dict(id=current,entities=[dict(name='persistent_fixture:target',position=[0,99.51,1.5],chase=True,speed=2,damage=2)]))
     time.sleep(.2);target=next(e for e in g.observe().entities if e.name=='persistent_fixture:target')
     r=g.flee_from(target,safe_distance=10,timeout=30);detail=r.to_dict()
     assert r.ok and r.details.get('clear_observed_for',0)>=1,detail
    else:raise ValueError(current)
    final=g.observe();assert not final.dead
    rows.append(dict(case=current,status='passed',detail=detail,final_hp=final.hp,elapsed=time.monotonic()-start))
   except Exception as exc:
    rows.append(dict(case=current,status='failed',detail=detail,error=str(exc),traceback=traceback.format_exc(),elapsed=time.monotonic()-start))
   save();print(json.dumps(rows[-1]),flush=True)
 finally:
  current='cleanup';session.park(g);g.release_control();final=g.observe()
  (a.output/'final.json').write_text(json.dumps(dict(sdk=__version__,sdk_path=str(a.sdk),pid=session.meta['pid'],state=final.raw),indent=2));save()
assert samples and all(not s['focused'] and not s['audio_enabled'] for s in samples)
sys.exit(any(r['status']!='passed' for r in rows))
