#!/usr/bin/env python3
"""Expected-v-observed simple behavior contracts; attach, never launch a client."""
import argparse,json,math,sys,time,threading,traceback,statistics,hashlib
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'engine/upstream.json').exists())
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--only');p.add_argument('--list',action='store_true');p.add_argument('--capture',action='store_true');p.add_argument('--repeat',type=int,default=1);p.add_argument('--session',type=Path,default=ROOT/'build/evidence/fluency-v0.10/session-release');a=p.parse_args()
sys.path[:0]=[str(a.sdk),str(ROOT/'tests/integration')]
from luanti_course import Game
from luanti_course.skills import Context
from luanti_course.navigation import World
from test_session import Session
from terrain_suite import cases,fill
S='mcl_core:stone';C='mcl_core:cobble';T='mcl_core:tree';IP='mcl_tools:pick_iron'
scenes=[]
def call(name,*args,**kw):return dict(method=name,args=args,kwargs=kw)
def add(id,spec,actions,expect,**gates):
 scenes.append(dict(id=id,spec=dict(spec,id='simple_'+id,fps=60,physics={'speed_walk':1,**spec.get('physics',{})}),actions=actions,expect=expect,gates=gates))
def nav(id,target,spec=None,**options):
 add(id,spec or {},[call('navigate_to',target,timeout=45,search_radius=20,**options)],
     '先转向目标；平地走直线，不追格点左右摇头；中段不无故停顿；接近目标减速一次，停稳后不再旋转或走动。',straight=True,target=target,max_excess_yaw=8,max_lateral=.22,max_idle=.35,max_detour=1.07)
for id,target in [('east',(6,99.5,0)),('west',(-6,99.5,0)),('north',(0,99.5,6)),('south',(0,99.5,-6)),('diag_ne',(5,99.5,5)),('diag_nw',(-5,99.5,5)),('diag_se',(5,99.5,-5)),('diag_sw',(-5,99.5,-5)),('shallow_ne',(6,99.5,3)),('steep_ne',(3,99.5,6)),('fractional',(5.3,99.5,3.7)),('long_diagonal',(12,99.5,12)),('short_stop',(.8,99.5,.4))]:nav(id,target)
terrain=cases()
for id in ('steps','slabs','stairs_0','stairs_1','stairs_2','stairs_3','drop2','gap1','gap2','gap2_standing','low_tunnel','narrow_bridge','snow','carpet','ladder_up','ladder_down','door','gate','ice','slime','honey','soul_sand','slow_physics','water_shore','surface_turn','dive','water_shallow','flowing_water'):
 sp=terrain[id];navkeys={'water_shore','surface_turn','dive','water_shallow','flowing_water'}
 expect=('保留水体自然起伏；目标方向稳定，不追水中格点；到高度后不持续过冲反复纠正；上岸不多跳。' if id in navkeys else
         '连续通过简单地形；必要时只在台阶/沟边跳跃，不回头追已经越过的落脚点；抵达后停止。')
 if id in ('door','gate'):expect='走近、瞄准开门一次、通过；允许交互确认停顿，不反复开关门、不多余重新定位。'
 if id.startswith('ladder'):expect='对齐梯子后持续上下，保持方向，不为厘米级水平误差旋转；落地停止。'
 gates=dict(target=sp['target'],no_loop=True,max_excess_yaw=25)
 if id=='surface_turn':gates=dict(target=(9,99.05,3),straight=True,max_excess_yaw=8,max_lateral=.3,max_idle=.45,max_detour=1.1,water=True)
 if id in ('ice','slime','honey','soul_sand'):gates=dict(target=sp['target'],straight=True,max_excess_yaw=12,max_lateral=.3,max_idle=.4,max_detour=1.1)
 if id=='water_shore':gates['shore']=True
 if id in ('door','gate'):gates=dict(target=sp['target'],door=True)
 add(id,sp,[call('navigate_to',sp['target'],timeout=50,search_radius=20,**sp['options'])],expect,**gates)
add('obstacle',{'fill':[fill((3,100,-1),(3,102,1),S)]},[call('navigate_to',(8,99.5,0),timeout=45)],'绕单一障碍：提前连续转弯，净空时回到目标方向，不碰墙后反复左右试探。',target=(8,99.5,0),no_loop=True,max_excess_yaw=210)
add('bridge8',{'fill':[fill((3,94,-32),(10,99,32),'air'),fill((3,93,-32),(10,93,32),S)],'inventory':[C+' 32']},[call('bridge_to',(13,99.5,0),timeout=150)],'进入施工方向后倒退连续搭桥；中段视角稳定，逐块落地确认；仅入口/出口各转身一次。',bridge=True)
solid={'fill':[fill((-10,88,-10),(20,99,10),S)],'inventory':[IP]}
add('dig_down',solid,[call('dig_down',4,timeout=100)],'逐层先挖净再下行；移动时看向下一工作面，不每层抬头归零；材料/安全确认的停顿有明确原因。',mining=True)
add('return',solid,[call('dig_down',4,timeout=100),call('return_to_entrance',timeout=80)],'返程转身一次，上行持续前进，不回头找越过的踏步。',last_action_only=True,no_loop=True,max_excess_yaw=15)
add('tunnel',solid,[call('dig_down',2,timeout=60),call('dig_tunnel',4,direction=(0,0,1),timeout=100)],'保持施工方向，瞄准实际头部/脚部方块后挖掘；每段挖通才向前，不穿插无目的转身。',last_action_only=True,mining=True)
add('harvest',{'nodes':[(3,100,z,T) for z in range(5)],'inventory':['mcl_tools:axe_iron']},[call('collect',T,5,timeout=90)],'同一工作区先采集可达资源，再收取掉落物；每个转向对应目标/掉落物，不反复无效挥动。',work=True)
add('single_dig',{'nodes':[(3,100,0,S)],'inventory':[IP]},[call('collect',C,1,timeout=45)],'接近、选工具、对准一次、持续挖到确认、释放按键。',work=True)
add('place',{'inventory':[C+' 8']},[call('place_block',C,(2,100,0))],'原地可达则不换位；对准支撑面，短按放一块，不连放。',static=True,max_yaw=110)
add('build_row',{'inventory':[C+' 16']},[call('build',[(C,(3,100,z)) for z in range(6)],timeout=100)],'一个工作站位的可达方块先完成；视线按实际支撑面变化，不每块重新选择站位。',work=True)
add('blueprint',{'inventory':[C+' 8']},[call('build',[(C,(2,y,z)) for y in (100,101) for z in (0,1)],timeout=80)],'先支撑后上层，稳定站位，无多放、漏放和不必要往返。',work=True)
add('ladder_build',{'inventory':['mcl_core:ladder 5',C+' 5']},[call('build_ladder',(0,100,3),5,backing_material=C,timeout=120)],'逐层完成背板/梯子，攀爬时稳定面对墙，不跟踪贴脸点导致抬头低头抽动。',work=True)
add('craft',{'inventory':[T+' 3']},[call('craft','wooden_pickaxe',timeout=90)],'现有材料合成依赖链；背包操作不伴随走动/转头，工作台放置交互另有明确阶段。',work=True)
add('craft_batch',{'inventory':['mcl_core:wood 10']},[call('craft','mcl_core:stick',count=16,gather=False)],'批量背包合成，角色保持静止与原视角。',static=True,max_yaw=1,max_pitch=1)
add('equip',{'inventory':[IP,'mcl_armor:helmet_iron']},[call('equip',IP),call('equip','mcl_armor:helmet_iron',destination='armor')],'只换持物/盔甲，不挪动、不转头。',static=True,max_yaw=1,max_pitch=1)
add('organize',{'inventory':[C+' 3','mcl_core:wood 10','mcl_core:wood 5']},[call('organize_inventory')],'仅整理背包，不走动和转头。',static=True,max_yaw=1,max_pitch=1)
add('chest',{'nodes':[(3,100,0,'mcl_chests:chest_small')],'inventory':[C+' 12']},[call('deposit',(3,100,0),C,7),call('withdraw',(3,100,0),C,4),call('restock',(3,100,0),C,11)],'接近并对准箱子；后续同箱操作不重复换位，等待材料确认时保持静止。',work=True)
add('smelt',{'nodes':[(3,100,0,'mcl_furnaces:furnace')],'inventory':['mcl_raw_ores:raw_iron 2','mcl_core:coal_lump']},[call('smelt','mcl_core:iron_ingot',2,furnace=(3,100,0),timeout=100)],'一次靠近熔炉，放入原料燃料后稳定等待，不将熔炼等待视作犹豫。',work=True)
for id,nodes in [('eat',[]),('eat_wall',[(0,100,2,S),(0,101,2,S)]),('eat_roof',[(0,102,0,S)])]:
 add(id,{'nodes':nodes,'inventory':['mcl_core:apple 3']},[call('eat','mcl_core:apple',2,timeout=30)],'进食保持站位；空视野不抬头。对着普通墙也尽量原朝向使用食物，交互物体拦截才避让。',food=True,static=True,max_yaw=1,max_pitch=5)

pool=[fill((3,96,-4),(10,99,4),'mcl_core:water_source'),fill((3,95,-4),(10,95,4),S)]
add('surface_stable',{'fill':pool,'spawn':(4,99.05,-2)},[call('navigate_to',(9,99.05,3),allow_swim=True,timeout=35)],'从稳定水面开始斜游：保持连续目标方向，允许自然水体起伏，不反复出入水或追格点摇头。',prepare_float=True,water=True,straight=True,target=(9,99.05,3),max_excess_yaw=8,max_lateral=.3,max_idle=.45,max_detour=1.1)
add('water_vertical_down',{'fill':pool,'spawn':(5,99.05,0)},[call('navigate_to',(5,97.5,0),allow_swim=True,allow_dive=True,timeout=35)],'原地明确下潜：保留水平朝向，垂直减速接近目标，不为厘米级误差转圈。',prepare_float=True,water=True,static=True,max_yaw=2,max_pitch=2)
add('food_soil_guard',{'nodes':[(0,101,2,S),(0,100,1,'mcl_farming:soil')],'inventory':['mcl_farming:carrot_item 3']},[call('eat','mcl_farming:carrot_item',1,timeout=30)],'可种植食物对着相邻耕地时避免种下：保留必要的避让瞄准，确实进食而非误种植。',food=True,static=True,max_yaw=1,max_pitch=100,soil_guard=True)

for id,yaw,pitch in [('look_left',90,0),('look_right',-90,0),('look_behind',180,0),('look_up',0,-45),('look_down',0,45)]:
 add(id,{},[call('look',yaw,pitch)],'原地单次平滑转向；不额外往返、不带动脚步；转到后停止。',static=True,max_yaw=abs(yaw)+1,max_pitch=abs(pitch)+1,no_loop=True,max_excess_yaw=2)
add('cancel_walk',{},[call('_cancel_walk')],'移动中取消：立即释放输入，短暂正常惯性后停稳；不自动重启路线。',expected_status='cancelled',cancel=True)
add('cancel_dig',{'nodes':[(3,100,0,S)],'inventory':[IP]},[call('_cancel_dig')],'挖掘中取消：释放挖掘键，不重复发起采集；保留真实的局部进度。',expected_status='cancelled',cancel=True)


# Station top-face placement must bypass right-click without opening the form.
for id,node in [('place_furnace','mcl_furnaces:furnace'),('place_table','mcl_crafting_table:crafting_table')]:
 add(id,{'nodes':[(2,100,0,node)],'inventory':[C+' 3']},[call('place_block',C,(2,101,0))],
     '在交互方块顶面放置：保留必要潜行，仅放一块，不打开工作站。',static=True,max_yaw=110,stance='one_crouch',no_menu=True)
add('eat_furnace',{'nodes':[(0,101,2,'mcl_furnaces:furnace')],'inventory':['mcl_core:apple 3']},
    [call('eat','mcl_core:apple',1,timeout=30)],'对着熔炉进食：只在绕过交互时潜行，不开炉子、不误放置。',food=True,static=True,max_yaw=1,max_pitch=5,stance='one_crouch',no_menu=True)
for sc in scenes:
 if 'stance' not in sc['gates']:
  sc['gates']['stance']=('continuous_bridge' if sc['id']=='bridge8' else 'one_crouch' if sc['id']=='ladder_down' else 'ladder_job' if sc['id']=='ladder_build' else
       'water' if sc['spec'].get('options',{}).get('allow_swim') or sc['gates'].get('water') or sc['id'] in ('water_shore','surface_turn','dive','water_shallow','flowing_water') else 'standing')

manifest=[{k:v for k,v in s.items()} for s in scenes]
if a.list:print(json.dumps(manifest,ensure_ascii=False,indent=2));sys.exit()
a.out.mkdir(parents=True,exist_ok=False);(a.out/'contracts.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
if a.only:scenes=[s for s in scenes if s['id'] in a.only.split(',')]
session=Session(a.session);results=[]
def write(name,v):(a.out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str))
def delta(a,b):return (b-a+180)%360-180
def sample(s):
 return dict(t=time.monotonic(),frame=s.frame,position=s.position,eye=s.eye,yaw=s.yaw,pitch=s.pitch,**{k:s.raw.get(k) for k in ('velocity','in_liquid','touching_ground','input_active','steering_active','control','audio_enabled','human_input_enabled','breath','hp')})
def metrics(rows,sc,actions,events):
 active=[r for r in rows if actions[0]['begin']<=r['t']<=actions[-1]['end']]
 if sc['gates'].get('last_action_only'):active=[r for r in active if r['t']>=actions[-1]['begin']]
 if not active:raise RuntimeError('no client samples')
 yaw=[active[0]['yaw']]
 for r in active[1:]:yaw.append(yaw[-1]+delta(yaw[-1],r['yaw']))
 travel=sum(abs(b-a) for a,b in zip(yaw,yaw[1:]));pitch=sum(abs(b['pitch']-a['pitch']) for a,b in zip(active,active[1:]))
 steps=[math.dist(a['position'],b['position']) for a,b in zip(active,active[1:])]
 gaps=[b['t']-a['t'] for a,b in zip(active,active[1:])]
 m=dict(samples=len(active),duration=active[-1]['t']-active[0]['t'],yaw_travel=travel,yaw_excess=travel-abs(delta(yaw[0],yaw[-1])),pitch_travel=pitch,path_length=sum(steps),max_sample_gap=max(gaps,default=0),p95_sample_gap=sorted(gaps)[int(len(gaps)*.95)] if gaps else 0,min_hp=min(r['hp'] for r in active),reversals=[],idle_spans=[])
 # Significant changes in turn direction: ignore sub-degree replication noise.
 anchor=yaw[0];extreme=anchor;direction=0
 for r,v in zip(active,yaw):
  if direction==0 and abs(v-anchor)>4:direction=1 if v>anchor else -1;extreme=v
  elif direction and (v-extreme)*direction>0:extreme=v
  elif direction and (extreme-v)*direction>4:
   m['reversals'].append(dict(t=r['t'],yaw=v,excursion=abs(extreme-v)));direction=-direction;extreme=v
 expected=[]
 def gate(name,value,limit,ok):expected.append(dict(check=name,observed=value,limit=limit,pass_=bool(ok)))
 gates=sc['gates'];wanted=gates.get('expected_status','success');gate('skill_outcome',[x['result'].get('status') for x in actions],wanted,all(x['result'].get('status')==wanted for x in actions))
 gate('no_damage',m['min_hp'],20,m['min_hp']==20)
 # Instrumentation validity is its own outcome, never mislabel missing frames as smoothness.
 gate('sampling_p95_seconds',m['p95_sample_gap'],.12,m['p95_sample_gap']<=.12)
 if gates.get('straight') or gates.get('no_loop'):
  gate('unnecessary_yaw_travel_degrees',m['yaw_excess'],gates['max_excess_yaw'],m['yaw_excess']<=gates['max_excess_yaw'])
 if gates.get('straight'):
  start=active[0]['position'];target=gates['target'];dx=target[0]-start[0];dz=target[2]-start[2];length=math.hypot(dx,dz)
  lateral=[abs((r['position'][0]-start[0])*dz-(r['position'][2]-start[2])*dx)/max(length,.01) for r in active]
  m['max_lateral']=max(lateral);m['path_ratio']=sum(math.hypot(b['position'][0]-a['position'][0],b['position'][2]-a['position'][2]) for a,b in zip(active,active[1:]))/max(math.hypot(active[-1]['position'][0]-start[0],active[-1]['position'][2]-start[2]),.01)
  gate('lateral_deviation_blocks',m['max_lateral'],gates['max_lateral'],m['max_lateral']<=gates['max_lateral'])
  gate('path_detour_ratio',m['path_ratio'],gates['max_detour'],m['path_ratio']<=gates['max_detour'])
  idle=None
  for r in active:
   moving=math.hypot(r['velocity'][0],r['velocity'][2])>.25
   interior=math.hypot(r['position'][0]-start[0],r['position'][2]-start[2])>.7 and math.hypot(r['position'][0]-target[0],r['position'][2]-target[2])>1.0
   if not moving and interior:
    if idle is None:idle=r['t']
   elif idle is not None:m['idle_spans'].append([idle,r['t']]);idle=None
  if idle is not None:m['idle_spans'].append([idle,active[-1]['t']])
  idlemax=max((b-a for a,b in m['idle_spans']),default=0);gate('unexplained_middle_idle_seconds',idlemax,gates['max_idle'],idlemax<=gates['max_idle'])
 if gates.get('static'):
  spread=max(math.hypot(r['position'][0]-active[0]['position'][0],r['position'][2]-active[0]['position'][2]) for r in active)
  gate('unnecessary_translation',spread,.05,spread<=.05)
  gate('yaw_for_static_action',travel,gates.get('max_yaw',360),travel<=gates.get('max_yaw',360))
  if 'max_pitch' in gates:gate('pitch_for_static_action',pitch,gates['max_pitch'],pitch<=gates['max_pitch'])
 if gates.get('bridge'):
  begun=next((e['t'] for e in events if e['event']=='bridge_support_confirmed'),math.inf)
  ended=next((e['t'] for e in events if e['event']=='backward_bridge_end'),-math.inf)
  span=[r for r in active if begun<=r['t']<=ended];angles=[delta(span[0]['yaw'],r['yaw']) for r in span] if span else []
  wobble=max(angles,default=999)-min(angles,default=0);gate('bridge_working_yaw_range',wobble,2,wobble<=2)

 # Track eye relative to feet: a crouch pulse can shake the camera with zero
 # player translation and zero yaw/pitch change. Include the post-action tail.
 camera=[r for r in rows if r['t']>=actions[0]['begin']]
 heights=[r['eye'][1]-r['position'][1] for r in camera]
 m['eye_height_range']=max(heights)-min(heights)
 m['eye_height_transitions']=sum(abs(x-y)>.07 for x,y in zip(heights,heights[1:]))
 stance=gates['stance']
 if stance=='standing':
  gate('no_unneeded_crouch_camera',m['eye_height_range'],.04,m['eye_height_range']<=.04)
 elif stance=='one_crouch':
  gate('no_repeated_crouch_cycles',m['eye_height_transitions'],2,m['eye_height_transitions']<=2)
 elif stance=='ladder_job':
  descent=next((e['t'] for e in events if e['event']=='ladder_descent_start'),math.inf)
  before=[r['eye'][1]-r['position'][1] for r in camera if r['t']<descent]
  spread=max(before)-min(before) if before else 999
  gate('ladder_construction_no_crouch_pulses',spread,.04,spread<=.04)
  after=[r['eye'][1]-r['position'][1] for r in camera if r['t']>=descent]
  changes=sum(abs(x-y)>.07 for x,y in zip(after,after[1:]))
  gate('ladder_descent_single_crouch',changes,2,changes<=2)
 elif stance=='continuous_bridge':
  eye=[r['eye'][1]-r['position'][1] for r in span]
  spread=max(eye)-min(eye) if eye else 999
  gate('bridge_continuous_crouched_camera',spread,.04,spread<=.04)
 if sc['id'] in ('surface_stable','water_vertical_down'):
  transitions=sum(a['in_liquid']!=b['in_liquid'] for a,b in zip(active,active[1:]));gate('no_liquid_boundary_chatter',transitions,0,transitions==0)
 if gates.get('shore'):
  span=[r for r in active if 10.6<r['position'][0]<12.5];peak=max((r['position'][1] for r in span),default=999);gate('shore_no_extra_jump_height',peak,99.9,peak<99.9)
 return m,expected
with session.connect(Game) as g:
 try:
  for rep in range(a.repeat):
   for sc in scenes:
    name=sc['id']+(f'_{rep+1}' if a.repeat>1 else '');rows=[];requests=[];actions=[];events=[];plans=[];geometry=[];done=threading.Event();errors=[]
    if g.observe().control!='agent':raise RuntimeError('Control released: stop suite without reacquiring')
    g.traversal=None;g.exploration_memory=None;g.reset_mining_trip()
    motion_file=session.world/'motion.jsonl';motion_offset=motion_file.stat().st_size if motion_file.exists() else 0
    setup=[]
    for setup_attempt in range(3):
     generation=session.reset(g,sc['spec'])
     first=g.observe();time.sleep(.18);ready=g.observe()
     setup.append(dict(attempt=setup_attempt+1,generation=generation,initial_hp=first.hp,ready_hp=ready.hp,ready_breath=ready.raw['breath'],ready_position=ready.position))
     if first.hp==ready.hp==sc['spec'].get('hp',20) and ready.raw['breath']==sc['spec'].get('breath',10):break
    else:
     write(name+'.setup.json',setup)
     raise RuntimeError('Fixture precondition failed before any skill was started: '+name)
    write(name+'.setup.json',setup)
    if sc['gates'].get('prepare_float'):
     with g.motion() as motion:
      end=time.monotonic()+4
      while time.monotonic()<end:
       state=g.observe();motion.steer(0,speed=0,swim_y=sc['spec']['spawn'][1]);time.sleep(.05)
       if abs(state.position[1]-sc['spec']['spawn'][1])<.05 and abs(state.raw['velocity'][1])<.15:break
    if sc['gates'].get('food'):
     g.chat('/grantme hunger');time.sleep(.1);g.chat('/sethunger singleplayer 8');time.sleep(.25)
    submit=g._submit;observe=g.observe;log=Context.log;plan=World.path
    def logged(ctx,event,**kw):events.append(dict(t=time.monotonic(),event=event,**kw));return log(ctx,event,**kw)
    def planned(world,*args,**kw):
     begin=time.monotonic();result=plan(world,*args,**kw);plans.append(dict(begin=begin,end=time.monotonic(),path=result[0]));return result
    Context.log=logged;World.path=planned
    def watched(radius=0):
     snapshot=observe(radius);rows.append(sample(snapshot));
     if radius and not geometry:geometry.append(snapshot.raw)
     return snapshot
    def request(op,**kw):
     t=time.monotonic();result=submit(op,**kw);requests.append(dict(t=t,end=time.monotonic(),op=op,args=kw));return result
    g.observe=watched;g._submit=request
    def monitor():
     while not done.is_set():
      t=time.monotonic()
      try:
       snap=g.observe()
       if snap.control!='agent':errors.append('control released');g.stop();done.set();break
      except Exception as e:errors.append(repr(e));break
      done.wait(max(0,.03-(time.monotonic()-t)))
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    try:
     for ac in sc['actions']:
      if errors:raise RuntimeError(str(errors))
      record=dict(ac,begin=time.monotonic());actions.append(record)
      if ac['method'].startswith('_cancel_'):
       value=[]
       def operation():value.append(g.navigate_to((20,99.5,0),timeout=30) if ac['method']=='_cancel_walk' else g.collect(C,1,timeout=30))
       worker=threading.Thread(target=operation,daemon=True);worker.start();deadline=time.monotonic()+10
       while time.monotonic()<deadline:
        state=g.observe()
        started=(state.position[0]>.8 if ac['method']=='_cancel_walk' else any(q['op']=='input' and 'dig' in q['args'].get('keys',[]) for q in requests))
        if started:break
        if not worker.is_alive():raise RuntimeError('action ended before cancellation')
        time.sleep(.015)
       else:raise RuntimeError('cancellation precondition timeout')
       g.stop();worker.join(4)
       if worker.is_alive() or not value:raise RuntimeError('cancel did not terminate action')
       r=value[0]
      else:r=getattr(g,ac['method'])(*ac['args'],**ac['kwargs'])
      record.update(end=time.monotonic(),result=r.to_dict() if hasattr(r,'to_dict') else dict(status='success',value=r))
      if hasattr(r,'ok') and not r.ok:break
     final=g.observe();time.sleep(.4);settled=g.observe()
     if a.capture:g.screenshot()
    except Exception as e:errors.append(repr(e));g.stop()
    finally:
     done.set();thread.join(5);g.observe=observe;g._submit=submit;Context.log=log;World.path=plan
    ordered=sorted(rows,key=lambda r:(r['frame'],r['t']));unique={r['frame']:r for r in reversed(ordered)};rows=sorted(unique.values(),key=lambda r:r['t'])
    write(name+'.geometry.json',geometry);write(name+'.events.json',events);write(name+'.plans.json',plans);write(name+'.samples.json',rows);write(name+'.commands.json',requests);write(name+'.actions.json',actions);
    with motion_file.open() as motion_stream:
     motion_stream.seek(motion_offset);physical=[r for line in motion_stream if line.strip() for r in [json.loads(line)] if r['generation']==generation]
    write(name+'.server.json',physical)
    try:
     m,checks=metrics(rows,sc,actions,events)
     sneak_onsets=sum(bool(r['control'].get('sneak')) and (i==0 or not physical[i-1]['control'].get('sneak')) for i,r in enumerate(physical))
     m['sneak_onsets']=sneak_onsets
     if sc['gates']['stance']=='standing':checks.append(dict(check='no_unneeded_sneak_input',observed=sneak_onsets,limit=0,pass_=sneak_onsets==0))
     if sc['gates'].get('no_menu'):checks.append(dict(check='no_unintended_form',observed=final.raw['menu_open'],limit=False,pass_=not final.raw['menu_open']))
     jump_onsets=sum(bool(r['control'].get('jump')) and (i==0 or not physical[i-1]['control'].get('jump')) for i,r in enumerate(physical))
     m['jump_onsets']=jump_onsets
     one_jump={'steps','stairs_0','stairs_1','stairs_2','stairs_3','gap1','gap2','gap2_standing','ladder_up'}
     no_jump={'slabs','drop2','low_tunnel','narrow_bridge','snow','carpet','ladder_down','door','gate','ice','slime','honey','soul_sand','slow_physics'}
     if sc['id'] in one_jump or sc['id'] in no_jump or sc['id'].startswith(('diag_','look_')):
      limit=2 if sc['id']=='ladder_up' else int(sc['id'] in one_jump);checks.append(dict(check='no_repeated_or_unneeded_jump',observed=jump_onsets,limit=limit,pass_=jump_onsets<=limit))
     if sc['id'] in ('ladder_up','ladder_down'):
      direction=1 if sc['id']=='ladder_up' else -1
      movement=[r for r in rows if actions[0]['begin']<=r['t']<=actions[-1]['end']]
      reverse=sum(max(0,(u['position'][1]-v['position'][1])*direction) for u,v in zip(movement,movement[1:]))
      checks.append(dict(check='ladder_reverse_vertical_motion',observed=reverse,limit=.15,pass_=reverse<=.15))
     holds=[];held=None
     for req in requests:
      if req['op']=='input' and any(k in req['args'].get('keys',[]) for k in ('dig','place')):
       if held is None:held=req
      elif req['op'] in ('stop','steer','look','release') and held is not None:
       samples=[r for r in rows if held['end']+.05<=r['t']<=req['t']]
       if len(samples)>2:
        angles=[delta(samples[0]['yaw'],r['yaw']) for r in samples]
        holds.append(dict(start=held['t'],end=req['t'],keys=held['args']['keys'],yaw_range=max(angles)-min(angles),pitch_range=max(r['pitch'] for r in samples)-min(r['pitch'] for r in samples),horizontal_drift=max(math.hypot(r['position'][0]-samples[0]['position'][0],r['position'][2]-samples[0]['position'][2]) for r in samples)))
       held=None
     if sc['id'] in ('place','build_row','blueprint','ladder_build','craft'):
      bad=[q for q in requests if q['op']=='input' and 'place' in q['args'].get('keys',[]) and 'sneak' in q['args'].get('keys',[])]
      checks.append(dict(check='ordinary_placement_never_crouches',observed=len(bad),limit=0,pass_=not bad))
     m['interaction_holds']=holds
     if holds:
      for field,limit in [('yaw_range',3),('pitch_range',3),('horizontal_drift',.12)]:
       value=max(h[field] for h in holds);checks.append(dict(check='stable_interaction_'+field,observed=value,limit=limit,pass_=value<=limit))
     if sc['id']=='build_row':
      arrivals=[e['position'] for e in events if e['event']=='arrived']
      redundant=sum(math.dist(u,v)<.05 for u,v in zip(arrivals,arrivals[1:]))
      checks.append(dict(check='no_repeated_same_work_stance',observed=redundant,limit=0,pass_=redundant==0))
     if sc['id'] in ('build_row','harvest','blueprint','chest','smelt'):
      navs=sum(e['event']=='follow_path' for e in events)
      # Real drops scatter randomly. Each observed pickup destination is a
      # legitimate leg; each confirmed harvest batch may also need an approach.
      # Require reasons, not a fixed count tied to one RNG draw.
      limit={'build_row':2,'harvest':max(1,sum(e['event']=='harvest_batch' for e in events))+sum(e['event']=='pickup_track' for e in events),'blueprint':0,'chest':1,'smelt':1}[sc['id']]
      checks.append(dict(check='bounded_work_repositioning',observed=navs,limit=limit,pass_=navs<=limit))
     if sc['gates'].get('soil_guard'):
      snap=g.observe(6);node=next((n for n in snap.raw['nodes'] if n['position']==[0,101,1]),None)
      clear=node is not None and node['name']=='air';checks.append(dict(check='food_not_planted',observed=node['name'] if node else None,limit='air',pass_=clear))
     if sc['gates'].get('cancel'):
      quiet=not settled.raw['input_active'] and not settled.raw['steering_active'];checks.append(dict(check='cancel_quiescence',observed=quiet,limit=True,pass_=quiet))
     for field in ('yaw','pitch'):
      drift=abs(delta(getattr(final,field),getattr(settled,field)))
      checks.append(dict(check='post_completion_'+field+'_drift',observed=drift,limit=1,pass_=drift<=1))
     if not sc['gates'].get('water') and not final.raw.get('in_liquid'):
      drift=math.dist(final.position,settled.position);checks.append(dict(check='post_completion_drift',observed=drift,limit=.22,pass_=drift<=.22))
     result=dict(id=name,expect=sc['expect'],gates=sc['gates'],generation=generation,metrics=m,checks=checks,errors=errors,pass_=not errors and all(c['pass_'] for c in checks))
    except Exception as e:result=dict(id=name,errors=errors+[repr(e)],pass_=False)
    results.append(result);write(name+'.result.json',result);write('results.json',dict(pid=session.meta['pid'],cases=results))
    print(json.dumps(dict(id=name,pass_=result['pass_'],fail=[c for c in result.get('checks',[]) if not c['pass_']],errors=result.get('errors'),metrics={k:v for k,v in result.get('metrics',{}).items() if k in ('yaw_excess','max_lateral','p95_sample_gap')})),flush=True)
    if sc['gates'].get('food'):g.chat('/sethunger singleplayer 20');g.chat('/revokeme hunger')
    if errors and any('control released' in e for e in errors):raise RuntimeError('User control change: suite stopped')
 finally:
  if g.observe().control=='agent':session.park(g)
write('summary.json',dict(pid=session.meta['pid'],total=len(results),passed=sum(r['pass_'] for r in results),failed=[r['id'] for r in results if not r['pass_']]))
sys.exit(0 if all(r['pass_'] for r in results) else 1)
