#!/usr/bin/env python3
"""Attach-only mixed-terrain, end-to-end, fault-recovery and active soak audit.

All terrain/supply injection occurs once per scenario via the local fixture.
No skill failure is silently retried. Checkpoints resume only at explicit steps.
"""
import argparse, hashlib, json, math, os, statistics, subprocess, sys, threading, time, traceback
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'engine/upstream.json').exists())
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--sdk',type=Path,required=True);p.add_argument('--session',type=Path,required=True)
p.add_argument('--out',type=Path,required=True);p.add_argument('--only',default='mixed,production,recovery,mining_resume,dynamic,seeds,soak')
p.add_argument('--soak-seconds',type=float,default=600);a=p.parse_args()
sys.path[:0]=[str(a.sdk.resolve()),str(ROOT/'tests/integration')]
from luanti_course import Game, Traversal, ExplorationMemory, __version__
from luanti_course.skills import Context
from test_session import Session
from terrain_suite import cases,fill
S='mcl_core:stone';C='mcl_core:cobble';T='mcl_core:tree';IRON='mcl_raw_ores:raw_iron';INGOT='mcl_core:iron_ingot';IP='mcl_tools:pick_iron';CHEST='mcl_chests:chest_small';FURNACE='mcl_furnaces:furnace';TABLE='mcl_crafting_table:crafting_table'
a.out.mkdir(parents=True,exist_ok=False)
session=Session(a.session);results=[];g=None;connection_lock=threading.RLock()
class Observer:
 def observe(self,radius=0):
  with connection_lock:return g.observe(radius)
 def close(self):pass
observer=Observer()
def write(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str));tmp.replace(path)
def snapshot(s):
 return dict(t=time.monotonic(),frame=s.frame,position=s.position,eye=s.eye,yaw=s.yaw,pitch=s.pitch,
             inventory={name:inv.count(name) for name in sorted({i.name for i in s.inventory['main'].items if i.count}) for inv in [s.inventory['main']]},
             **{k:s.raw.get(k) for k in ('hp','breath','velocity','in_liquid','touching_ground','input_active','steering_active','control','audio_enabled','human_input_enabled','menu_open','focused')})
def delta(u,v):return (v-u+180)%360-180
def rss(pid):
 return int(subprocess.check_output(['ps','-p',str(pid),'-o','rss='],text=True).strip())
def connect():
 global g
 g=session.connect(Game)
 if active is not None:active.instrument(g)
 return g
active=None
class Audit:
 def __init__(self,name,spec,expect):
  self.name=name;self.path=a.out/name;self.path.mkdir();self.expect=expect
  self.actions=[];self.checks=[];self.events=[];self.requests=[];self.rows=[];self.errors=[];self.current=None;self.done=threading.Event()
  g.traversal=None;g.exploration_memory=None;g.reset_mining_trip()
  spec=dict(spec,id='complex_'+name,fps=60,physics={'speed_walk':1,**spec.get('physics',{})})
  self.spec=spec;write(self.path/'fixture.json',spec)
  self.motion=session.world/'motion.jsonl';self.offset=self.motion.stat().st_size
  setup=[]
  for attempt in range(3):
   self.generation=session.reset(g,spec);s1=observer.observe();time.sleep(.18);s2=observer.observe()
   setup.append(dict(attempt=attempt+1,generation=self.generation,first=snapshot(s1),second=snapshot(s2)))
   if s1.hp==s2.hp==spec.get('hp',20) and s2.raw['breath']==spec.get('breath',10):break
  else:raise RuntimeError('fixture precondition failed before skill')
  write(self.path/'setup.json',setup)
  self.initial=snapshot(s2);self.native_rss=[dict(t=time.monotonic(),rss_kib=rss(session.meta['pid']))]
  self.log_orig=Context.log
  def log(ctx,event,**kw):
   self.events.append(dict(t=time.monotonic(),step=self.current,event=event,**kw));return self.log_orig(ctx,event,**kw)
  Context.log=log;self.instrument(g)
  self.stream=(self.path/'samples.jsonl').open('w')
  self.thread=threading.Thread(target=self.monitor,daemon=True);self.thread.start()
 def instrument(self,game):
  original=getattr(game,"_complex_original_submit",game._submit)
  game._complex_original_submit=original
  def submit(op,**kwargs):
   row=dict(t=time.monotonic(),step=self.current,op=op,args=kwargs)
   try:return original(op,**kwargs)
   finally:row['end']=time.monotonic();self.requests.append(row)
  game._submit=submit
 def monitor(self):
  while not self.done.is_set():
   t=time.monotonic()
   try:
    row=snapshot(observer.observe());row['step']=self.current;self.rows.append(row);self.stream.write(json.dumps(row)+'\n')
    if row['control']!='agent':raise RuntimeError('control released; stop audit')
   except Exception as exc:self.errors.append(repr(exc));break
   self.done.wait(max(0,.04-(time.monotonic()-t)))
 def check(self,name,ok,observed=None,expected=True):
  row=dict(name=name,pass_=bool(ok),observed=observed,expected=expected);self.checks.append(row);write(self.path/'checks.json',self.checks)
  if not ok:raise AssertionError(json.dumps(row,ensure_ascii=False))
 def count(self,item):return observer.observe().inventory['main'].count(item)
 def step(self,label,method=None,*args,expect='success',reason=None,fn=None,standing=False,**kwargs):
  if self.errors:raise RuntimeError(str(self.errors))
  self.current=label;before=snapshot(observer.observe());record=dict(label=label,method=method,args=args,kwargs=kwargs,begin=time.monotonic(),before=before);self.actions.append(record)
  try:
   r=fn() if fn else getattr(g,method)(*args,**kwargs)
   record.update(end=time.monotonic(),result=r.to_dict() if hasattr(r,'to_dict') else dict(status='success',value=r))
   ended=snapshot(observer.observe());time.sleep(.3);settled=snapshot(observer.observe());record.update(after=ended,settled=settled)
   self.check(label+'.outcome',record['result']['status']==expect,record['result'],expect)
   if reason:self.check(label+'.reason',record['result'].get('reason')==reason,record['result'].get('reason'),reason)
   self.check(label+'.released_inputs',not settled['input_active'] and not settled['steering_active'],[settled['input_active'],settled['steering_active']],[False,False])
   self.check(label+'.closed_menu',not settled['menu_open'],settled['menu_open'],False)
   for axis in ('yaw','pitch'):
    diff=abs(delta(ended[axis],settled[axis]));self.check(label+'.settled_'+axis,diff<=1,diff,'<=1 degree')
   if not ended['in_liquid']:
    drift=math.dist(ended['position'],settled['position']);self.check(label+'.settled_feet',drift<=.22,drift,'<=0.22 block')
   if standing:
    span=[x for x in self.rows if record['begin']<=x['t']<=settled['t']]
    heights=[x['eye'][1]-x['position'][1] for x in span]
    spread=max(heights)-min(heights) if heights else math.inf
    self.check(label+'.no_extra_crouch',spread<=.04,spread,'<=0.04 block')
   return r
  except Exception as exc:
   record.setdefault('end',time.monotonic());record['error']=repr(exc);raise
  finally:write(self.path/'actions.json',self.actions);self.current=None
 def cancel(self,method,args,kwargs,predicate,limit=40):
  out=[];errors=[]
  def worker():
   try:out.append(getattr(g,method)(*args,**kwargs))
   except Exception as exc:errors.append(repr(exc))
  thread=threading.Thread(target=worker,daemon=True);thread.start();end=time.monotonic()+limit
  while time.monotonic()<end and thread.is_alive():
   if predicate():break
   time.sleep(.025)
  else:
   g.stop();thread.join(5);raise RuntimeError('cancel trigger not reached: '+str(errors))
  self.events.append(dict(t=time.monotonic(),step=self.current,event='explicit_test_stop'))
  g.stop();thread.join(5)
  if thread.is_alive() or not out:raise RuntimeError('cancel did not join '+str(errors))
  return out[0]
 def reconnect(self):
  global g
  with connection_lock:g.close();connect()
  self.events.append(dict(t=time.monotonic(),event='python_reconnect_same_native_pid',pid=session.meta['pid']))
 def finish(self,error=None):
  if error:self.errors.append(error)
  if g and observer.observe().control=='agent':g.stop()
  time.sleep(.35);self.done.set();self.thread.join(5);self.stream.close();Context.log=self.log_orig
  write(self.path/'events.json',self.events);write(self.path/'commands.json',self.requests);write(self.path/'actions.json',self.actions)
  write(self.path/'final-observation.json',observer.observe(6).raw)
  physical=[]
  with self.motion.open() as f:
   f.seek(self.offset)
   for line in f:
    if line.strip():
     row=json.loads(line)
     if row['generation']==self.generation:physical.append(row)
  write(self.path/'server.json',physical)
  rows=self.rows;unique={r['frame']:r for r in reversed(rows)};rows=sorted(unique.values(),key=lambda x:x['t'])
  gaps=[y['t']-x['t'] for x,y in zip(rows,rows[1:])]
  def gate(name,ok,observed,expected):self.checks.append(dict(name=name,pass_=bool(ok),observed=observed,expected=expected))
  gate('no_damage',bool(rows) and min(x['hp'] for x in rows)==20,min((x['hp'] for x in rows),default=None),20)
  gate('silent_and_no_human_input',bool(rows) and all(not x['audio_enabled'] and not x['human_input_enabled'] for x in rows),None,True)
  p95=sorted(gaps)[int(len(gaps)*.95)] if gaps else math.inf
  gate('valid_sampling',p95<=.18,p95,'p95 <=0.18 second')
  # Bridge work yaw/posture is constant; entrance and exit turns are separate.
  start=None
  for e in self.events:
   if e['event']=='backward_bridge_start':start=None
   if e['event']=='bridge_support_confirmed' and start is None:start=e['t']
   if e['event']=='backward_bridge_end' and start is not None:
    span=[x for x in rows if start<=x['t']<=e['t']]
    if span:
     angles=[delta(span[0]['yaw'],x['yaw']) for x in span];heights=[x['eye'][1]-x['position'][1] for x in span]
     gate('bridge_work_yaw',max(angles)-min(angles)<=2,max(angles)-min(angles),'<=2 degrees')
     gate('bridge_continuous_posture',max(heights)-min(heights)<=.04,max(heights)-min(heights),'<=0.04 block')
    start=None
  self.native_rss.append(dict(t=time.monotonic(),rss_kib=rss(session.meta['pid'])))
  write(self.path/'rss.json',self.native_rss);write(self.path/'checks.json',self.checks)
  result=dict(id=self.name,expect=self.expect,generation=self.generation,pass_=not self.errors and all(c['pass_'] for c in self.checks),errors=self.errors,
              steps=len(self.actions),checks=len(self.checks),failures=[c for c in self.checks if not c['pass_']],duration=time.monotonic()-self.initial['t'],samples=len(rows),sampling_p95=p95,
              path_length=sum(math.dist(x['position'],y['position']) for x,y in zip(rows,rows[1:])),rss=self.native_rss)
  write(self.path/'result.json',result);results.append(result);write(a.out/'results.json',dict(pid=session.meta['pid'],sdk=__version__,cases=results,complete=False));print(json.dumps(result,ensure_ascii=False),flush=True)

def mixed(t):
 g.exploration_memory=ExplorationMemory()
 t.step('door_and_slabs','navigate_to',(-11,99.5,0),timeout=90,search_radius=64)
 t.step('low_clearance','navigate_to',(-5,99.5,0),timeout=60)
 t.step('cross_water','navigate_to',(3,99.5,0),allow_swim=True,timeout=90)
 before=t.count(C);t.step('bridge_river_gap','bridge_to',(12,99.5,0),timeout=120)
 t.check('bridge_spends_material',t.count(C)<before,[before,t.count(C)])
 t.step('collect_beyond_obstacle','collect',T,3,timeout=120)
 t.step('store_harvest','deposit',(22,100,0),T,3,timeout=60)
 t.check('wood_moved_to_chest',t.count(T)==0,t.count(T),0)
 blueprint=[(C,(20,100,z)) for z in (3,4,5)]+[(C,(20,101,4))]
 b=t.count(C);t.step('remote_build','build',blueprint,timeout=120,standing=True)
 t.check('blueprint_cost',t.count(C)==b-4,[b,t.count(C)],'four blocks')
 t.step('remote_build_idempotent','build',blueprint,timeout=40,standing=True)
 t.check('blueprint_no_duplicate',t.count(C)==b-4,t.count(C),b-4)
 t.step('return_over_finished_bridge','navigate_to',(3,99.5,0),timeout=90)
 t.step('return_through_water_tunnel_door','navigate_route',[(-5,99.5,0),(-11,99.5,0),(-24,99.5,0)],traversal=Traversal(allow_swim=True),timeout=150)
 t.check('home_reached',math.dist(g.observe().position,(-24,99.5,0))<.5,g.observe().position)

def ore_sidewall(t):
 t.step('collect_sidewall_ore','collect',IRON,3,timeout=60,search_radius=6,standing=True)
 t.check('all_three_ores_in_inventory',t.count(IRON)==3,t.count(IRON),3)
 st=g.observe(6)
 remaining=[n for n in st.raw['nodes'] if n['position'] in ([1,96,0],[1,96,1],[1,96,2]) and n['name']!='air']
 t.check('three_ore_cells_removed',not remaining,remaining,[])

def production(t):
 t.step('harvest_four_logs','collect',T,4,timeout=120)
 t.step('craft_wood_pick','craft','wooden_pickaxe',timeout=90)
 t.step('equip_wood_pick','equip','mcl_tools:pick_wood')
 t.step('mine_surface_cobble','collect',C,12,timeout=180)
 t.step('craft_stone_pick','craft','mcl_tools:pick_stone',timeout=90)
 t.step('equip_stone_pick','equip','mcl_tools:pick_stone')
 t.step('return_to_mine_entrance','navigate_to',(0,99.5,0),timeout=60)
 down=t.path/'down.json';tunnel=t.path/'tunnel.json'
 t.step('staircase_down_four','dig_down',4,direction=(1,0,0),checkpoint=down,timeout=180)
 t.step('tunnel_four','dig_tunnel',4,direction=(0,0,1),checkpoint=tunnel,timeout=180)
 t.step('mine_visible_iron_vein','collect',IRON,3,timeout=120,search_radius=12)
 t.check('raw_iron_confirmed',t.count(IRON)==3,t.count(IRON),3)
 t.step('return_to_known_entrance','return_to_entrance',checkpoint=tunnel,timeout=120)
 t.check('back_at_entrance',math.dist(g.observe().position,(0,99.5,0))<.6,g.observe().position)
 cp=t.path/'iron-pick.json'
 t.step('start_iron_pick_then_cancel',expect='cancelled',fn=lambda:t.cancel('craft',('mcl_tools:pick_iron',),dict(checkpoint=cp,timeout=150),lambda:t.count(INGOT)>=1))
 t.reconnect()
 t.step('resume_iron_pick','resume',cp,timeout=150)
 t.check('one_iron_pick',t.count(IP)==1,t.count(IP),1)
 t.step('completed_craft_noop','resume',cp,timeout=30)
 t.check('still_one_iron_pick',t.count(IP)==1,t.count(IP),1)
 t.step('equip_new_pick','equip',IP)
 t.step('store_spare_stone','deposit',(-3,100,2),C,4,timeout=60)
 t.step('organize_after_full_trip','organize_inventory',standing=True)

def recovery(t):
 t.step('fuel_missing_is_structured','smelt',INGOT,1,furnace=(-3,100,0),timeout=30,expect='blocked',reason='fuel_unavailable')
 t.check('missing_fuel_keeps_ore',t.count(IRON)==1,t.count(IRON),1)
 t.step('fetch_coal','withdraw',(-3,100,2),'mcl_core:coal_lump',1,timeout=45,expect='blocked',reason='container_item_missing')
 # Materials already held by the actor, not spawned mid-flow. A deposit/withdraw
 # round trip exercises the explicit resource-replenishment choice.
 t.step('store_construction_reserve','deposit',(-3,100,2),C,7)
 b=t.count(C)
 t.step('bridge_budget_stop','bridge_to',(9,99.5,0),max_blocks=1,timeout=60,expect='blocked',reason='terrain_edit_budget')
 t.check('at_most_one_support_consumed',0<=b-t.count(C)<=1,[b,t.count(C)],'0..1')
 t.step('retrieve_reserve','withdraw',(-3,100,2),C,7,timeout=60)
 t.step('finish_bridge_explicitly','bridge_to',(9,99.5,0),timeout=120)
 t.step('come_back','navigate_to',(0,99.5,0),timeout=60)
 b=t.count(C)
 # Ordinary held-material craft fails without chopping trees or manufacturing tools.
 t.step('missing_diamond_not_automated','craft','mcl_tools:pick_diamond',timeout=30,expect='blocked')
 t.check('failure_keeps_cobble',t.count(C)==b,t.count(C),b)
 t.step('continue_after_failure','navigate_to',(-5,99.5,-4),timeout=45)

def mining_resume(t):
 cp=t.path/'mining.json'
 def partial():
  try:return json.loads(cp.read_text()).get('completed_steps',0)>=2
  except (FileNotFoundError,json.JSONDecodeError):return False
 t.step('cancel_partial_mine',expect='cancelled',fn=lambda:t.cancel('dig_down',(6,),dict(direction=(1,0,0),checkpoint=cp,timeout=180),partial))
 data=json.loads(cp.read_text());t.check('partial_trail_persisted',2<=data['completed_steps']<6,data['completed_steps'],'2..5')
 t.reconnect()
 t.step('return_before_resuming','return_to_entrance',checkpoint=cp,timeout=100)
 t.step('resume_down_six','resume',cp,timeout=180)
 t.check('depth_six',abs(g.observe().position[1]-93.5)<.2,g.observe().position)
 t.step('already_complete_does_not_dig','resume',cp,timeout=30)
 t.step('home_again','return_to_entrance',checkpoint=cp,timeout=100)

def dynamic(t):
 g.exploration_memory=ExplorationMemory()
 # A timed fixture edit arrives after movement starts. It is an obstacle to
 # observe/replan around, never a command to bypass ordinary movement rules.
 t.step('new_wall_during_approach','navigate_to',(22,99.5,0),timeout=120,search_radius=48)
 st=g.observe(6);wall=[n for n in st.raw['nodes'] if n['position']==[5,100,0]]
 # The wall is beyond observation radius at the far end; verify near it on return.
 t.step('revisit_changed_area','navigate_to',(0,99.5,0),timeout=120,search_radius=48)
 st=g.observe(6);wall=[n for n in st.raw['nodes'] if n['position']==[5,100,0]]
 t.check('wall_really_existed',bool(wall) and wall[0]['name']==S,wall,S)
 t.check('no_accidental_terrain_edits',not any(e['event'] in ('dig_confirmed','placement_confirmed') for e in t.events),None,True)

def seeds(t):
 for i in range(3):
  t.step('mixed_cross_'+str(i),'navigate_to',(20 if i%2==0 else -4,99.5,0),timeout=100,search_radius=48)

def soak(t):
 g.exploration_memory=ExplorationMemory(ttl=600,max_nodes=45000)
 plan=[(C,(-22,100,5)),(C,(-22,100,6)),(C,(-22,101,5))]
 t.step('prepare_marker','build',plan,timeout=90,standing=True)
 materials=t.count(C);start=time.monotonic();loops=0;stats=[]
 while time.monotonic()-start<a.soak_seconds or loops<3:
  loops+=1
  if loops>40:raise RuntimeError('active soak failed to reach requested duration within 40 laps')
  t.step('lap_%02d_route'%loops,'navigate_route',[(20,99.5,0),(18,99.5,18),(-18,99.5,18),(-20,99.5,0)],timeout=180,search_radius=64)
  t.step('lap_%02d_no_duplicate_build'%loops,'build',plan,timeout=30,standing=True)
  t.step('lap_%02d_inventory'%loops,'organize_inventory',standing=True)
  t.check('lap_%02d_material_conserved'%loops,t.count(C)==materials,t.count(C),materials)
  t.check('lap_%02d_memory_bounded'%loops,len(g.exploration_memory.nodes)<=45000,len(g.exploration_memory.nodes),'<=45000')
  stat=dict(lap=loops,elapsed=time.monotonic()-start,native_rss_kib=rss(session.meta['pid']),python_rss_kib=rss(os.getpid()),memory_nodes=len(g.exploration_memory.nodes));stats.append(stat);write(t.path/'soak-progress.json',stats)
  print(json.dumps(dict(soak=stat)),flush=True)
  if loops%3==0:
   memory=g.exploration_memory;t.reconnect();g.exploration_memory=memory
 t.check('active_soak_duration',time.monotonic()-start>=a.soak_seconds,time.monotonic()-start,a.soak_seconds)
 # Cache warm-up is excluded; a moderate allocator/cache bound is an acceptance
 # limit, not a proof that arbitrary-duration native/Python runs cannot leak.
 warm=stats[min(2,len(stats)-1)]['native_rss_kib'];growth=stats[-1]['native_rss_kib']-warm
 t.check('native_rss_after_warmup',growth<=128*1024,growth,'<=128 MiB growth')

specs={
 'ore_sidewall':dict(spawn=(0,95.51,0),fill=[fill((-8,88,-8),(8,100,8),S),fill((0,96,-3),(0,97,3),'air')],nodes=[(1,96,z,'mcl_core:stone_with_iron') for z in (0,1,2)],inventory=[IP]),
 'mixed':dict(spawn=(-24,99.51,0),fill=[fill((-18,100,-32),(-18,103,32),S),fill((-18,100,0),(-18,101,0),'air'),fill((-14,100,-2),(-12,100,2),'mcl_stairs:slab_stone'),fill((-10,102,-1),(-7,102,1),S),fill((-10,100,-2),(-7,102,-2),S),fill((-10,100,2),(-7,102,2),S),fill((-4,96,-4),(1,99,4),'mcl_core:water_source'),fill((-4,95,-4),(1,95,4),S),fill((6,94,-32),(8,99,32),'air'),fill((6,93,-32),(8,93,32),S),fill((14,100,-1),(14,102,1),S)],nodes=[(-18,100,0,'mcl_doors:wooden_door_b_1',1),(-18,101,0,'mcl_doors:wooden_door_t_1',1),(22,100,0,CHEST)]+[(18,100,z,T) for z in (0,1,2)],inventory=[C+' 24','mcl_tools:axe_iron']),
 'production':dict(fill=[fill((-12,88,-12),(24,99,12),S)],nodes=[(-3,100,0,TABLE),(-3,100,-2,FURNACE),(-3,100,2,CHEST)]+[(-6,y,0,T) for y in range(100,104)]+[(x,100,z,S) for x in range(4,8) for z in range(-4,-1)]+[(5,96,z,'mcl_core:stone_with_iron') for z in (3,4,5)],inventory=['mcl_core:coal_lump 2']),
 'recovery':dict(fill=[fill((3,94,-32),(5,99,32),'air'),fill((3,93,-32),(5,93,32),S)],nodes=[(-3,100,0,FURNACE),(-3,100,2,CHEST)],inventory=[IRON,C+' 8']),
 'mining_resume':dict(fill=[fill((-10,88,-10),(20,99,10),S)],inventory=[IP]),
 'dynamic':dict(changes=[dict(at=.65,nodes=[(5,y,z,S) for y in (100,101,102) for z in range(-3,4)])]),
 'soak':dict(spawn=(-20,99.51,0),nodes=cases()['mixed_seed_42']['nodes'],inventory=[C+' 16'])}
expectations={
 'ore_sidewall':'两格高窄隧道中的脚边侧壁矿：中心被上方石块遮挡，露出的侧面仍应可瞄准；采集3个生铁，不拆其他石头、不下蹲、不扩大挖掘策略。',
 'mixed':'同一世界穿门、半砖、低顶、水体、倒退搭桥、绕障采集、入库、造物和返程；物品守恒、无伤、桥中方向和视点稳定。',
 'production':'同一库存从原木和木镐逐级制作石镐，下矿挖隧道采铁后原路返回；熔炼合成中取消，重连恢复只产出一把铁镐。工作站和煤在初始夹具提供。',
 'recovery':'缺燃料/空箱/预算不足/缺钻石均明确停止；保留材料和已建地形，补取自存材料后显式继续，后续动作仍可用。',
 'mining_resume':'开矿两层后取消；新 Python 连接先返程再续挖，六层只挖一次，最后回到入口。',
 'dynamic':'行走中新增墙面；重新观察、绕行和返程，无穿墙、无自动破坏地形。',
 'seeds':'固定随机种子的坑洼、全砖和半砖混合地形连续往返三程。',
 'soak':'至少十分钟主动执行混合地形长路线、幂等建造和背包整理；同一世界无重置，定期 Python 重连，检查物品、停止状态和缓存/内存上限。'}
write(a.out/'manifest.json',dict(sdk=__version__,sdk_path=str(a.sdk.resolve()),pid=session.meta['pid'],only=a.only,soak_seconds=a.soak_seconds,expectations=expectations,specs=specs))
try:
 connect()
 for name in a.only.split(','):
  todo=[('seed_'+str(n),dict(nodes=cases()['mixed_seed_'+str(n)]['nodes']),seeds,expectations['seeds']) for n in (13,42,91)] if name=='seeds' else [(name,specs[name],globals()[name],expectations[name])]
  for ident,spec,fn,expect in todo:
   if observer.observe().control!='agent':raise RuntimeError('control released; not reacquiring')
   active=Audit(ident,spec,expect);error=None
   try:fn(active)
   except Exception:error=traceback.format_exc()
   finally:active.finish(error);active=None

finally:
 if g:
  if observer.observe().control=='agent':session.park(g);g.release_control()
  write(a.out/'final-client.json',dict(session=session.meta,state=observer.observe().raw));g.close()
 observer.close()
complete=dict(pid=session.meta['pid'],sdk=__version__,cases=results,complete=True,passed=sum(x['pass_'] for x in results),total=len(results))
write(a.out/'results.json',complete);print('RESULT',complete['passed'],'/',complete['total'],flush=True)
sys.exit(0 if all(x['pass_'] for x in results) else 1)
