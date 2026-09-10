#!/usr/bin/env python3
"""Attach-only backward span, direction, budget and cancellation acceptance."""
import argparse,json,sys,time,threading,math
from pathlib import Path
from test_session import Session
p=argparse.ArgumentParser();p.add_argument('--session',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
sys.path.insert(0,str(a.sdk));from luanti_course import Game,Traversal
s=Session(a.session);a.out.mkdir(parents=True,exist_ok=False);checks=[]
def check(name,ok,**data):
 checks.append(dict(name=name,passed=bool(ok),**data));(a.out/'partial.json').write_text(json.dumps(checks,indent=2));print(json.dumps(checks[-1]),flush=True)
 if not ok:raise AssertionError(name)
def spec(name,d,fps=60,stock=20,length=8):
 lo=[-32,94,-32];hi=[32,99,32];axis=0 if d[0] else 2;sign=d[axis]
 lo[axis],hi[axis]=(3,length+2) if sign==1 else (-length-2,-3)
 return dict(id=name,fps=fps,fill=[dict(min=lo,max=hi,name='air')],inventory=['mcl_core:cobble '+str(stock)]),tuple((length+5)*v if i!=1 else 99.5 for i,v in enumerate(d))
with s.connect(Game) as g:
 try:
  for fps in (30,60):
   for d in ((1,0,0),(-1,0,0),(0,0,1),(0,0,-1)):
    name='span_%s_%s'%(fps,('_'.join(map(str,d))));scene,target=spec(name,d,fps);gen=s.reset(g,scene);rows=[];observe=g.observe
    def watch(radius=0):
     v=observe(radius);rows.append(dict(frame=v.frame,yaw=v.yaw,pitch=v.pitch,hp=v.hp,position=v.position,stock=v.inventory['main'].count('mcl_core:cobble')));return v
    g.observe=watch
    try:r=g.bridge_to(target,timeout=100)
    finally:g.observe=observe
    state=g.observe();span=[x for x in rows if 13<=x['stock']<=19];turn=sum(abs((y['yaw']-x['yaw']+180)%360-180) for x,y in zip(span,span[1:]));pitch=max((x['pitch'] for x in span),default=0)-min((x['pitch'] for x in span),default=0)
    (a.out/(name+'.json')).write_text(json.dumps(dict(result=r.to_dict(),observations=rows)))
    check(name,r.ok and r.details.get('backward_bridge_blocks')==8 and state.inventory['main'].count('mcl_core:cobble')==12 and state.hp==20 and math.dist(state.position,target)<.6 and turn<2 and pitch<2 and not state.raw['input_active'],turn_inside_span=turn,pitch_range_inside_span=pitch,result=r.to_dict())
    time.sleep(.4);check(name+'_released',g.observe().inventory['main'].count('mcl_core:cobble')==12 and not g.observe().raw['input_active'])
  for name,stock,budget,want in [('budget',20,3,'terrain_edit_budget'),('materials',2,30,'item_not_held')]:
   scene,target=spec(name,(1,0,0),stock=stock);s.reset(g,scene);r=g.bridge_to(target,traversal=Traversal(edit_budget=budget),timeout=90);state=g.observe();spent=stock-state.inventory['main'].count('mcl_core:cobble')
   check(name,r.reason==want and spent==min(stock,budget) and len(r.details.get('terrain_changes',[]))==spent and not state.raw['input_active'] and state.hp==20,result=r.to_dict(),spent=spent)
  scene,target=spec('cancel',(1,0,0));s.reset(g,scene);out=[]
  t=threading.Thread(target=lambda:out.append(g.bridge_to(target,timeout=90)),daemon=True);t.start();end=time.monotonic()+25
  while time.monotonic()<end and g.observe().inventory['main'].count('mcl_core:cobble')>18:time.sleep(.05)
  begin=time.monotonic();g.stop();t.join(6);state=g.observe();check('cancel',not t.is_alive() and out and out[0].status=='cancelled' and state.hp==20 and not state.raw['input_active'],latency=time.monotonic()-begin,result=out[0].to_dict() if out else None)
  spent=20-state.inventory['main'].count('mcl_core:cobble');check('cancel_keeps_placed_blocks',len(out[0].details.get('terrain_changes',[]))==spent,spent=spent,recorded=len(out[0].details.get('terrain_changes',[])))
  stock=state.inventory['main'].count('mcl_core:cobble');time.sleep(.5);check('cancel_no_extra_placement',g.observe().inventory['main'].count('mcl_core:cobble')==stock and not g.observe().raw['input_active'])
 finally:s.park(g)
(a.out/'results.json').write_text(json.dumps(dict(pid=s.meta['pid'],checks=checks),indent=2));print('PASS',len(checks))
