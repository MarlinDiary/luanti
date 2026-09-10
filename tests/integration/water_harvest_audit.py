#!/usr/bin/env python3
"""Attach-only regression for shallow harvest, support reposition and ascent."""
import argparse,json,sys,time,traceback
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--session',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--cases',default='underfoot,shallow_source,shallow_flow,submerged_bank,submerged_same_cell');a=p.parse_args()
valid={'underfoot','shallow_source','shallow_flow','submerged_bank','submerged_same_cell'}
chosen=a.cases.split(',')
if not chosen or any(case not in valid for case in chosen):p.error('unknown case')
sys.path.insert(0,str(a.sdk));from luanti_course import Game,Traversal,__version__
from test_session import Session
session=Session(a.session);a.output.mkdir(parents=True,exist_ok=False)
rows=[];samples=[];commands=[];case='setup'
with session.connect(Game) as game:
 raw=game._request
 def request(op,**kw):
  r=raw(op,**kw);t=time.monotonic()
  if op=='observe':
   samples.append(dict(case=case,t=t,**{k:r.get(k) for k in ('position','velocity','in_liquid','touching_ground','yaw','hp','breath','focused','audio_enabled','input_active','steering_active','item_entities')}))
   assert r['focused'] is False and r['audio_enabled'] is False
  else:commands.append(dict(case=case,t=t,op=op,args=kw))
  return r
 game._request=request
 try:
  for case in chosen:
   detail={};t=time.monotonic()
   try:
    spec=dict(id='harvest_'+case,fps=60,nodes=[[0,100,0,'mcl_core:tree']])
    if case=='underfoot':spec['spawn']=[0,100.51,0]
    elif case.startswith('shallow'):
     # Five visible nodes for a request of three: the game may merge or lose a
     # floating drop, and the SDK must keep partial inventory progress and use
     # another resource instead of assuming every removed block was collected.
     spec.update(nodes=[[x,100,4,'mcl_core:tree'] for x in (-2,-1,0,1,2)],fill=[dict(min=[-4,100,-4],max=[4,100,6],name='mcl_core:water_source' if case=='shallow_source' else 'mcl_core:water_flowing',param2=7)])
    else:
     spec.update(spawn=[0,96,0],nodes=[],fill=[dict(min=[-3,96,-3],max=[3,100,3],name='mcl_core:water_source'),dict(min=[-3,95,-3],max=[3,95,3],name='mcl_core:stone')])
    session.reset(game,spec);game.traversal=Traversal(allow_swim=True);before=game.observe();start=time.monotonic()
    if case.startswith('submerged'):
     r=game.navigate_to((-.45,100.05,-.45) if case=='submerged_same_cell' else (0,99.5,5),timeout=25)
    else:r=game.collect('mcl_core:tree',1 if case=='underfoot' else 3,timeout=45)
    detail['result']=r.to_dict();detail['inventory_count']=game.observe().inventory['main'].count('mcl_core:tree');assert r.ok,r.to_dict()
    after=game.observe();assert not after.dead and after.hp==before.hp
    if not case.startswith('submerged'):
     gained=after.inventory['main'].count('mcl_core:tree')-before.inventory['main'].count('mcl_core:tree');detail['gained']=gained
     assert gained>=(1 if case=='underfoot' else 3)
     assert not any(e.get('reason')=='would_remove_support' for e in r.trace),r.trace
    else:
     trace=[s for s in samples if s['case']==case and s['t']>=start]
     # Below the bank's floor, the actor must recover vertically in the pool,
     # not walk into its submerged collision wall or a neighboring shaft.
     deep=[s for s in trace if s['position'][1]<99.3]
     assert deep and max((s['position'][0]**2+s['position'][2]**2)**.5 for s in deep)<.4,deep
     detail['deep_max_horizontal']=max((s['position'][0]**2+s['position'][2]**2)**.5 for s in deep)
     if case=='submerged_same_cell':
      error=((after.position[0]+.45)**2+(after.position[2]+.45)**2)**.5
      detail['horizontal_error']=error;assert error<.3,error
    assert not after.raw['input_active'] and not after.raw['steering_active']
    rows.append(dict(case=case,status='passed',elapsed=time.monotonic()-t,detail=detail))
   except Exception as exc:rows.append(dict(case=case,status='failed',elapsed=time.monotonic()-t,detail=detail,error=str(exc),traceback=traceback.format_exc()))
   (a.output/'results.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows[-1]),flush=True)
 finally:
  case='cleanup';session.park(game);game.release_control();s=game.observe()
  (a.output/'final.json').write_text(json.dumps(dict(pid=session.meta['pid'],sdk=__version__,state=s.raw),indent=2))
  for name,value in [('samples',samples),('commands',commands)]: (a.output/(name+'.json')).write_text(json.dumps(value,indent=2))
sys.exit(any(r['status']!='passed' for r in rows))
