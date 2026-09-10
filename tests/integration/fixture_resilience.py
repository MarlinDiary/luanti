#!/usr/bin/env python3
import argparse,json,sys,time,os
from pathlib import Path
from test_session import Session
p=argparse.ArgumentParser();p.add_argument('--session',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();sys.path.insert(0,str(a.sdk));from luanti_course import Game
s=Session(a.session);a.out.mkdir(parents=True,exist_ok=False);checks=[]
with s.connect(Game) as g:
 try:
  s.reset(g,{'id':'guard_baseline','inventory':['mcl_core:cobble 7']});gen=s.state()['generation']
  for bad in ({'id':'bad name'}, {'id':'unknown_node','fill':[{'min':[0,99,0],'max':[1,99,1],'name':'fixture:missing_node'}]}, {'id':'bad_bounds','fill':[{'min':[0,82,0],'max':[1,99,1],'name':'mcl_core:stone'}]}):
   # Deliberately bypass the Python preflight to test the Lua error boundary.
   (s.world/'request.json').write_text(json.dumps(bad));g.chat('/fixture reset');end=time.monotonic()+4
   while time.monotonic()<end:
    f=s.world/'reset-error.json'
    if f.exists() and json.loads(f.read_text()).get('id')==bad['id']:break
    time.sleep(.05)
   else:raise AssertionError('missing fixture error')
   os.kill(s.meta['pid'],0);state=g.observe();assert s.state()['generation']==gen and state.inventory['main'].count('mcl_core:cobble')==7 and state.hp==20
   checks.append(dict(name=bad['id'],passed=True,error=json.loads(f.read_text()),pid=s.meta['pid'],scene_preserved=True))
  nextgen=s.reset(g,{'id':'guard_recovered'});assert nextgen>gen;checks.append(dict(name='valid_reset_after_errors',passed=True,pid=s.meta['pid']))
 finally:s.park(g)
(a.out/'results.json').write_text(json.dumps(dict(pid=s.meta['pid'],checks=checks),indent=2));print(json.dumps(checks))
