#!/usr/bin/env python3
"""Held-item restoration against an existing isolated native test session."""
import argparse,json,sys,time,traceback
from collections import Counter
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--session',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
assert (a.sdk/'luanti_course/__init__.py').is_file();sys.path.insert(0,str(a.sdk))
from luanti_course import Game,__version__
from test_session import Session
session=Session(a.session);a.output.mkdir(parents=True,exist_ok=False)
rows=[];samples=[];commands=[];current='setup'
def save():
 for n,v in [('results',rows),('samples',samples),('commands',commands)]: (a.output/(n+'.json')).write_text(json.dumps(v,indent=2))
def stock(s):return Counter({k:sum(i.count for i in s.inventory['main'].items if i.stack_key==k) for k in {i.stack_key for i in s.inventory['main'].items if i.count}})
def identity(s):
 i=s.inventory['main'].items[s.raw['wield']];return (i.name,i.wear,i.stack_key)
def until(fn,seconds=10):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  s=g.observe()
  if fn(s):return s
  time.sleep(.05)
 raise AssertionError('native state confirmation timeout')
with session.connect(Game) as g:
 raw=g._request
 def request(op,**kw):
  r=raw(op,**kw)
  if op=='observe':samples.append(dict(case=current,time=time.monotonic(),**{k:r.get(k) for k in ('position','hp','dead','control','input_active','steering_active','wield','hunger','focused','audio_enabled')}))
  else:commands.append(dict(case=current,time=time.monotonic(),op=op,args=kw,response=r))
  return r
 g._request=request
 try:
  for current in ('held_tool','full_hotbar','empty_hand','supervisor_eating'):
   detail={};start=time.monotonic()
   try:
    inv=['mcl_tools:sword_wood','mcl_core:apple 5'];slot=0
    if current=='full_hotbar':inv=['mcl_core:dirt 2']*8+['mcl_tools:sword_wood','mcl_core:apple 5'];slot=8
    if current=='empty_hand':inv=['','mcl_core:apple 5']
    session.reset(g,dict(id=current,hunger=8,inventory=inv));until(lambda s:s.hunger==8)
    g.wield(slot);before=until(lambda s:s.raw['wield']==slot);before_stock=stock(before)
    if current=='supervisor_eating':
     with g.survival() as guard:
      until(lambda s:s.hunger>=16,20);assert guard.wait_idle(10);events=guard.events()
     finished=[e for e in events if e['event']=='reaction_finished'];assert finished and all(e['result']['status']=='success' for e in finished),events
     detail['events']=events
    else:
     r=g.eat_best_food(timeout=15);detail['result']=r.to_dict();assert r.ok and r.details['wield_restore']=='restored',detail
    after=g.observe();after_stock=stock(after);consumed=before_stock['mcl_core:apple']-after_stock['mcl_core:apple']
    assert consumed>=1 and (current=='supervisor_eating' or consumed==1)
    expected=before_stock.copy();expected['mcl_core:apple']-=consumed
    assert after_stock==+expected,(before_stock,after_stock)
    assert identity(before)==identity(after),(identity(before),identity(after))
    assert after.hunger>before.hunger and not after.dead
    detail.update(before_wield=before.raw['wield'],after_wield=after.raw['wield'],identity=identity(after),consumed=consumed,before_hunger=before.hunger,after_hunger=after.hunger)
    rows.append(dict(case=current,status='passed',detail=detail,elapsed=time.monotonic()-start))
   except Exception as exc:rows.append(dict(case=current,status='failed',detail=detail,error=str(exc),traceback=traceback.format_exc(),elapsed=time.monotonic()-start))
   save();print(json.dumps(rows[-1]),flush=True)
 finally:
  current='cleanup';session.park(g);g.release_control();final=g.observe()
  (a.output/'final.json').write_text(json.dumps(dict(sdk=__version__,sdk_path=str(a.sdk),pid=session.meta['pid'],state=final.raw),indent=2));save()
assert samples and all(s['focused'] is False and s['audio_enabled'] is False for s in samples)
sys.exit(any(r['status']!='passed' for r in rows))
