#!/usr/bin/env python3
"""Attach-only action quality comparisons; metrics are separate from success."""
import argparse,json,math,sys,time
from pathlib import Path
from test_session import Session
p=argparse.ArgumentParser();p.add_argument('--session',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--cases',default='bridge,return,tunnel,harvest,build');p.add_argument('--fps',type=int,default=60);a=p.parse_args()
sys.path.insert(0,str(a.sdk));from luanti_course import Game,Traversal
s=Session(a.session);a.out.mkdir(parents=True,exist_ok=False);results=[]
def fill(lo,hi,name):return dict(min=lo,max=hi,name=name)
def measure(name,action,g,generation):
 rows=[];requests=[];observe=g.observe;submit=g._submit
 def watched(radius=0):
  x=observe(radius);rows.append(dict(time=time.monotonic(),frame=x.frame,position=x.position,yaw=x.yaw,pitch=x.pitch,velocity=x.raw['velocity'],pointed=x.pointed_node,above=x.raw.get('pointed_above'),hp=x.hp,wet=x.raw['in_liquid'],input=x.raw['input_active']));return x
 def request(op,**kw):requests.append(dict(time=time.monotonic(),op=op,arguments=kw));return submit(op,**kw)
 g.observe=watched;g._submit=request;t=time.monotonic()
 try:r=action()
 finally:g.observe=observe;g._submit=submit
 elapsed=time.monotonic()-t;unique=[]
 for row in rows:
  if not unique or row['frame']!=unique[-1]['frame']:unique.append(row)
 yaw=sum(abs((v['yaw']-u['yaw']+180)%360-180) for u,v in zip(unique,unique[1:]));pitch=sum(abs(v['pitch']-u['pitch']) for u,v in zip(unique,unique[1:]))
 steps=[math.dist(u['position'],v['position']) for u,v in zip(unique,unique[1:])]
 stops=sum(x['op']=='stop' for x in requests);physical=s.rows(generation)
 result=dict(case=name,fps=a.fps,pid=s.meta['pid'],generation=generation,result=r.to_dict(),elapsed=elapsed,yaw_travel=yaw,pitch_travel=pitch,stop_commands=stops,path_length=sum(steps),samples=len(unique),min_hp=min(x['hp'] for x in unique))
 (a.out/(name+'.observations.json')).write_text(json.dumps(unique));(a.out/(name+'.requests.json')).write_text(json.dumps(requests));(a.out/(name+'.physical.json')).write_text(json.dumps(physical));results.append(result);(a.out/'partial.json').write_text(json.dumps(results,indent=2));print(json.dumps(result),flush=True)
 return r
with s.connect(Game) as g:
 try:
  for case in a.cases.split(','):
   try:
    g.traversal=None;g.exploration_memory=None;g.reset_mining_trip()
    if case=='bridge':
     gen=s.reset(g,dict(id=case,fps=a.fps,fill=[fill([3,94,-32],[10,99,32],'air'),fill([3,93,-32],[10,93,32],'mcl_core:stone')],inventory=['mcl_core:cobble 32']))
     r=measure(case,lambda:g.bridge_to((13,99.5,0),timeout=150),g,gen)
    elif case=='return':
     gen=s.reset(g,dict(id=case,fps=a.fps,fill=[fill([-10,88,-10],[20,99,10],'mcl_core:stone')],inventory=['mcl_tools:pick_iron']))
     prep=g.dig_down(8,timeout=180);assert prep.ok,prep.to_dict()
     r=measure(case,lambda:g.return_to_entrance(),g,gen)
    elif case=='tunnel':
     gen=s.reset(g,dict(id=case,fps=a.fps,fill=[fill([-10,88,-10],[20,99,10],'mcl_core:stone')],inventory=['mcl_tools:pick_iron']))
     prep=g.dig_down(3);assert prep.ok,prep.to_dict()
     r=measure(case,lambda:g.dig_tunnel(6,direction=(0,0,1),timeout=150),g,gen)
    elif case=='harvest':
     gen=s.reset(g,dict(id=case,fps=a.fps,nodes=[(3,100,z,'mcl_core:tree') for z in range(5)],inventory=['mcl_tools:axe_iron']))
     r=measure(case,lambda:g.collect('mcl_core:tree',5,timeout=90),g,gen)
    elif case=='build':
     gen=s.reset(g,dict(id=case,fps=a.fps,inventory=['mcl_core:cobble 16']))
     r=measure(case,lambda:g.build([('mcl_core:cobble',(3,100,z)) for z in range(6)],timeout=100),g,gen)
    else:raise ValueError(case)
   except Exception as exc:results.append(dict(case=case,error=repr(exc)));print(repr(exc),flush=True)
   finally:s.park(g);g.take_control()
 finally:s.park(g)
(a.out/'results.json').write_text(json.dumps(results,indent=2));assert all(x.get('result',{}).get('status')=='success' for x in results)
