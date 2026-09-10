#!/usr/bin/env python3
"""Attach-only terrain acceptance suite: resetting scenes does not restart GUI."""
import argparse,json,math,sys,time,traceback,inspect,random
from pathlib import Path
from test_session import Session
S='mcl_core:stone';A='air';W='mcl_core:water_source'
def fill(a,b,n):return dict(min=a,max=b,name=n)
def case(name,fills=(),nodes=(),target=(8,99.5,0),spawn=(0,99.51,0),options=None,**kw):
 kw['physics']={'speed_walk':1,**kw.get('physics',{})}
 return dict(id=name,fill=list(fills),nodes=list(nodes),spawn=spawn,target=target,options=options or {},**kw)
def cases():
 c={}
 def add(v):c[v['id']]=v
 pool=[fill((3,96,-4),(10,99,4),W),fill((3,95,-4),(10,95,4),S)]
 add(case('water_shore',pool,target=(13,99.5,0),options=dict(allow_swim=True)))
 add(case('surface_turn',pool,target=(9,100,3),spawn=(4,99.05,-2),options=dict(allow_swim=True)))
 add(case('dive',pool,target=(7,97.5,0),spawn=(4,99.05,0),options=dict(allow_swim=True,allow_dive=True)))
 wall=[fill((3,100,-32),(3,103,32),S),fill((3,100,0),(3,101,0),A)]
 add(case('door',wall,[(3,100,0,'mcl_doors:wooden_door_b_1',1),(3,101,0,'mcl_doors:wooden_door_t_1',1)]))
 add(case('locked_door_detour',[fill((3,100,-1),(3,102,1),S),fill((3,100,0),(3,101,0),A)],[(3,100,0,'mcl_doors:iron_door_b_1',1),(3,101,0,'mcl_doors:iron_door_t_1',1)]))
 add(case('gate',wall,[(3,100,0,'mcl_fences:fence_gate',1)]))
 for gap in (1,2):
  add(case('gap'+str(gap),[fill((3,95,-32),(2+gap,99,32),A),fill((3,94,-32),(2+gap,94,32),S)],options=dict(allow_jump_gaps=True)))
 add(case('gap2_standing',[fill((3,95,-32),(4,99,32),A),fill((3,94,-32),(4,94,32),S)],spawn=(2,99.51,0),options=dict(allow_jump_gaps=True)))
 add(case('bridge',[fill((3,95,-32),(5,99,32),A),fill((3,94,-32),(5,94,32),S)],inventory=['mcl_core:cobble 16'],options=dict(build_with='mcl_core:cobble')))
 add(case('build_steps',[fill((4,99,-2),(12,101,2),S)],target=(8,101.5,0),inventory=['mcl_core:cobble 12'],options=dict(build_with='mcl_core:cobble')))
 add(case('tunnel',[fill((3,100,-32),(3,103,32),S)],inventory=['mcl_tools:pick_iron'],options=dict(allow_dig=True)))
 add(case('drop2',[fill((3,99,-32),(32,99,32),A),fill((3,97,-32),(32,97,32),S)],target=(8,97.5,0),options=dict(max_drop=2)))
 for n,item in [('ice','mcl_core:ice'),('slime','mcl_core:slimeblock'),('honey','mcl_honey:honey_block'),('soul_sand','mcl_nether:soul_sand')]:
  add(case(n,[fill((-4,99,-4),(18,99,4),item)],target=(12,99.5,2)))
 add(case('slabs',[fill((3,100,-2),(6,100,2),'mcl_stairs:slab_stone')],target=(9,99.5,0)))
 add(case('steps',[fill((3,100,-2),(6,100,2),S)],target=(9,99.5,0)))
 add(case('dynamic_wall',target=(15,99.5,0),changes=[dict(at=.7,nodes=[(4,y,z,S) for y in (100,101) for z in range(-2,3)])]))
 add(case('flat',target=(14,99.5,0)))
 for rot in range(4):
  ramp=[fill((3,99,-2),(9,100,2),S)]
  nodes=[(3,100,z,'mcl_stairs:stair_stone_rough',rot) for z in range(-2,3)]
  add(case('stairs_'+str(rot),ramp,nodes,target=(8,100.5,0)))
 ladder=[(3,y,0,S) for y in range(100,105)]+[(2,y,0,'mcl_core:ladder',2) for y in range(100,105)]
 add(case('ladder_up',nodes=ladder,target=(2,103.5,0)))
 add(case('ladder_down',nodes=ladder,spawn=(2,103.51,0),target=(2,99.5,0)))
 add(case('low_tunnel',[fill((-2,102,-1),(12,102,1),S),fill((-2,100,-2),(12,102,-2),S),fill((-2,100,2),(12,102,2),S)],target=(10,99.5,0)))
 add(case('narrow_bridge',[fill((-2,95,-4),(15,99,4),A),fill((-2,94,-4),(15,94,4),S),fill((-2,99,0),(15,99,0),S)],target=(12,99.5,0)))
 for name,node in [('snow','mcl_core:snow'),('carpet','mcl_wool:white_carpet')]:
  add(case(name,[fill((2,100,-2),(8,100,2),node)],target=(10,99.5,0)))
 add(case('ice_corner',[fill((-4,99,-5),(18,99,5),'mcl_core:ice'),fill((5,100,-3),(5,102,2),S)],target=(13,99.5,0)))
 add(case('slow_physics',target=(10,99.5,0),physics=dict(speed_walk=.65,jump=.8,gravity=1.15)))
 add(case('water_shallow',[fill((3,99,-4),(10,99,4),W),fill((3,98,-4),(10,98,4),S)],target=(13,99.5,0),options=dict(allow_swim=True)))
 flow=[fill((3,96,-4),(10,99,4),'mcl_core:water_flowing'),fill((3,95,-4),(10,95,4),S),fill((3,99,-4),(10,99,-4),W)]
 for f in flow:
  if f['name']=='mcl_core:water_flowing':f['param2']=7
 add(case('flowing_water',flow,target=(13,99.5,0),options=dict(allow_swim=True)))
 add(case('air_recovery',pool,target=(7,97.5,0),spawn=(4,97.51,0),options=dict(allow_swim=True,allow_dive=True),wait_breath=6))
 add(case('dive_return',pool,target=(7,96.5,0),spawn=(4,99.05,0),options=dict(allow_swim=True,allow_dive=True),then=[(8,99.05,0),(13,99.5,0)]))
 add(case('lava_detour',[fill((3,99,-2),(7,99,2),'mcl_core:lava_source')],target=(11,99.5,0)))
 for seed in (13,42,91):
  rng=random.Random(seed);nodes=[]
  # A reproducible mixture of pits, raised blocks and partial-height surfaces.
  for x in range(3,15):
   for z in range(-5,6):
    pick=rng.randrange(8)
    if pick==0:nodes.extend([(x,99,z,A),(x,98,z,S)])
    elif pick==1:nodes.append((x,100,z,S))
    elif pick==2:nodes.append((x,100,z,'mcl_stairs:slab_stone'))
  add(case('mixed_seed_'+str(seed),nodes=nodes,target=(17,99.5,0)))
 return c

def metrics(rows,begin,end):
 rows=[r for r in rows if begin<=r['sequence']<=end]
 moving=[i for i,r in enumerate(rows) if math.hypot(r['velocity']['x'],r['velocity']['z'])>.25]
 active=rows[moving[0]:moving[-1]+1] if moving else rows
 turns=[];stops=0;stopped=False;length=0
 for a,b in zip(active,active[1:]):
  dt=b['time']-a['time'];speed=math.hypot(a['velocity']['x'],a['velocity']['z'])
  if speed<.25 and not stopped:stops+=1
  stopped=speed<.25
  length+=math.hypot(a['pos']['x']-b['pos']['x'],a['pos']['z']-b['pos']['z'])
  if dt>0:turns.append(abs((b['yaw']-a['yaw']+math.pi)%(2*math.pi)-math.pi)*180/math.pi/dt)
 shore=[r for r in active if 10.6<r['pos']['x']<12.5]
 return dict(samples=len(rows),stop_starts=stops,path_length=length,peak_yaw_deg_s=max(turns,default=0),min_hp=min((r['hp'] for r in rows),default=20),max_abs_vy=max((abs(r['velocity']['y']) for r in rows),default=0),shore_peak_y=max((r['pos']['y'] for r in shore),default=None),shore_jump_frames=sum(r['control']['jump'] for r in shore))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--session',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--cases',default=','.join(cases()));p.add_argument('--fps',type=int,default=60);p.add_argument('--baseline',action='store_true');a=p.parse_args()
 sys.path.insert(0,str(a.sdk.resolve()));from luanti_course import Game
 a.out.mkdir(parents=True,exist_ok=False);session=Session(a.session);results=[];failed=0
 with session.connect(Game) as game:
  original_observe=game.observe
  def observe(radius=0):
   s=original_observe(radius)
   with (a.out/'observations.jsonl').open('a') as f:f.write(json.dumps(dict(time=time.monotonic(),case=name,position=s.position,velocity=s.raw.get('velocity'),yaw=s.yaw,pitch=s.pitch,liquid=s.raw.get('in_liquid'),grounded=s.raw.get('touching_ground'),frame=s.frame))+'\n')
   return s
  game.observe=observe
  for name in a.cases.split(','):
   spec=cases()[name];spec['fps']=a.fps;gen=session.reset(game,spec);begin=session.state()['sequence'];start=time.monotonic()
   options=spec['options'];options={k:v for k,v in options.items() if k in inspect.signature(game.navigate_to).parameters}
   try:
    if spec.get('wait_breath'):
     end_wait=time.monotonic()+30
     with game.motion() as motion:
      while game.observe().raw['breath']>spec['wait_breath']:
       if time.monotonic()>end_wait:raise TimeoutError('breath fixture threshold')
       motion.steer(0,speed=0,swim_y=spec['spawn'][1]);time.sleep(.10)
     begin=session.state()['sequence']
    r=game.navigate_to(spec['target'],timeout=45,search_radius=20,**options)
    legs=[r.to_dict()]
    for target in spec.get('then',[]):
     if not r.ok:break
     r=game.navigate_to(target,timeout=45,search_radius=20,**options);legs.append(r.to_dict())
    end=session.state()['sequence'];state=game.observe(6)
    data=dict(case=name,generation=gen,pid=session.meta['pid'],spec=spec,result=r.to_dict(),legs=legs,position=state.position,physics=state.raw.get('physics'),metrics=metrics(session.rows(gen),begin,end))
    data['pass']=r.ok and data['metrics']['min_hp']==20
    if name=='water_shore':
     data['natural_shore_gate']=data['metrics']['shore_peak_y'] is not None and data['metrics']['shore_peak_y']<99.9 and data['metrics']['shore_jump_frames']==0
     data['pass']=data['pass'] and data['natural_shore_gate']
    game.screenshot()
   except Exception as e:
    game.stop();data=dict(case=name,pass_=False,error=repr(e),traceback=traceback.format_exc());data['pass']=False
   results.append(data);failed+=not data['pass'];(a.out/(name+'.json')).write_text(json.dumps(data,indent=2))
   print(json.dumps({k:data.get(k) for k in ('case','pass','error','position','metrics','natural_shore_gate')}),flush=True)
  session.park(game)
 (a.out/'results.json').write_text(json.dumps(dict(pid=session.meta['pid'],cases=results,failed=failed),indent=2))
 print('RESULT',len(results)-failed,'/',len(results),'PID',session.meta['pid'],flush=True)
 sys.exit(0 if a.baseline or not failed else 1)
