#!/usr/bin/env python3
"""Run the student survival loop against a persistent, isolated native world."""
import argparse,importlib.util,json,sys,time,traceback
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--session',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--fps',type=int,choices=(30,60),default=60);p.add_argument('--turns',type=int,choices=(0,1,2,3),default=0)
p.add_argument('--cases',default='hunger_chain,zombie_chain,air_chain,fire_replan');a=p.parse_args()
assert (a.sdk/'luanti_course/__init__.py').is_file();sys.path.insert(0,str(a.sdk))
from luanti_course import Game,Traversal,__version__
from test_session import Session
spec=importlib.util.spec_from_file_location('student_example',Path(__file__).resolve().parents[2]/'examples/survival_collect.py')
example=importlib.util.module_from_spec(spec);spec.loader.exec_module(example)
session=Session(a.session);a.output.mkdir(parents=True,exist_ok=False)
rows=[];samples=[];commands=[];current='setup'
def save():
 for name,value in [('results',rows),('samples',samples),('commands',commands)]:
  (a.output/(name+'.json')).write_text(json.dumps(value,indent=2))
with session.connect(Game) as game:
 raw=game._request
 def request(op,**kw):
  result=raw(op,**kw)
  if op=='observe':
   sample=dict(case=current,time=time.monotonic(),**{k:result.get(k) for k in ('position','hp','breath','hunger','dead','control','input_active','steering_active','velocity','yaw','pitch','entities','hazards','focused','audio_enabled','in_liquid','touching_ground','swim_height_active')});samples.append(sample)
   if sample['focused'] is True or sample['audio_enabled'] is True:raise AssertionError('unexpected focus or audio')
  else:commands.append(dict(case=current,time=time.monotonic(),op=op,args=kw))
  return result
 game._request=request
 try:
  for current in a.cases.split(','):
   detail={};start=time.monotonic()
   try:
    spec=dict(id=current,fps=60,nodes=[[x,100,5,'mcl_core:tree'] for x in (-1,0,1)])
    expected={'hunger_chain':'eat_best_food','zombie_chain':'defend_self','air_chain':'recover_air','fire_replan':'escape_hazard'}[current]
    if current=='hunger_chain':spec.update(hunger=8,inventory=['mcl_core:apple 5'])
    if current=='zombie_chain':spec.update(night=True,entities=[dict(name='mobs_mc:zombie',position=[0,99.51,4])],inventory=['mcl_tools:sword_diamond','mcl_armor:helmet_diamond','mcl_armor:chestplate_diamond','mcl_armor:leggings_diamond','mcl_armor:boots_diamond'])
    if current=='air_chain':spec.update(spawn=[0,98,0],breath=3,fill=[dict(min=[-3,96,-3],max=[3,100,3],name='mcl_core:water_source'),dict(min=[-3,95,-3],max=[3,95,3],name='mcl_core:stone')],nodes=[[x,100,6,'mcl_core:tree'] for x in (-1,0,1)])
    if current=='fire_replan':spec['nodes'].append([0,100,0,'mcl_fire:fire'])
    spec['fps']=a.fps
    def rotate(p):
     x,y,z=p
     for _ in range(a.turns):x,z=-z,x
     return [x,y,z]
    if 'spawn' in spec:spec['spawn']=rotate(spec['spawn'])
    spec['nodes']=[rotate(n[:3])+n[3:] for n in spec.get('nodes',())]
    for f in spec.get('fill',()):
     ends=[rotate(f['min']),rotate(f['max'])]
     f['min']=[min(v[i] for v in ends) for i in range(3)]
     f['max']=[max(v[i] for v in ends) for i in range(3)]
    detail['fixture']=spec
    session.reset(game,spec)
    # Swimming is an explicit student traversal choice, not a default override
    # secretly carried out by the survival reaction.
    game.traversal=Traversal(allow_swim=current=='air_chain')
    before=game.observe();detail['before']=dict(position=before.position,hp=before.hp,breath=before.raw.get('breath'),hunger=before.hunger)
    report=example.collect_with_survival(game,'mcl_core:tree',3,seconds=100,enemies='defend' if current=='zombie_chain' else 'off',max_interruptions=8)
    detail['collection']=report
    if current=='fire_replan':
     assert report['status']=='needs_replan',report
     # Continuing fire is now a first-class reaction. If the most recently
     # observed water is no longer valid, it must return a bounded blocked
     # result and hand planning back instead of masking the failed extinguish.
     finished=[x['survival_event'] for x in report['steps'] if
               x.get('survival_event',{}).get('event')=='reaction_finished']
     assert any(e['decision']['action']=='extinguish_fire' and
                e['result']['status']=='blocked' and
                e['result']['reason'] in ('burning_persists','extinguishing_water_not_observed')
                for e in finished),report
    else:assert report['status']=='complete' and report['gained']>=3,report
    events=[s['survival_event'] for s in report['steps'] if 'survival_event' in s]
    assert any(e['event']=='reaction_finished' and e['decision']['action']==expected and e['result']['status']=='success' for e in events),events
    detail['task_interrupted']=any(s.get('result',{}).get('reason')=='survival_interrupted' for s in report['steps'])
    # An already-known hazard is allowed to run before the task starts; that
    # is not evidence of mid-action preemption. Record the distinction.
    if current=='fire_replan':
     # The explicit planner waits after the bounded extinguish attempt. No
     # healing grant, automatic SDK retry, or hidden damage-tolerance change.
     # Each observation must remain alive and idle.
     until=time.monotonic()+12;recovery=[]
     while time.monotonic()<until:
      state=game.observe();assert not state.dead and not state.raw.get('input_active')
      recovery.append(dict(time=time.monotonic(),hp=state.hp));time.sleep(.1)
     detail['natural_fire_expiry']=recovery
     # Natural healing is not continuing damage; reject health decreases, not increases.
     assert all(b['hp']>=a['hp'] for a,b in zip(recovery[-20:],recovery[-19:])),'damage still ongoing'
     remaining=3-game.observe().inventory['main'].count('mcl_core:tree')
     resumed=example.collect_with_survival(game,'mcl_core:tree',remaining,seconds=70,enemies='off')
     detail['explicit_replan']=resumed
     assert resumed['status']=='complete' and game.observe().inventory['main'].count('mcl_core:tree')>=3,resumed
    crafting=game.craft('wooden_pickaxe',timeout=50);detail['craft']=crafting.to_dict();assert crafting.ok,detail
    final=game.observe();assert not final.dead and final.inventory['main'].count('mcl_tools:pick_wood')>=1
    assert not final.raw.get('input_active') and not final.raw.get('steering_active')
    rows.append(dict(case=current,status='passed',elapsed=time.monotonic()-start,detail=detail,final_hp=game.observe().hp))
   except Exception as exc:rows.append(dict(case=current,status='failed',elapsed=time.monotonic()-start,detail=detail,error=str(exc),traceback=traceback.format_exc()))
   save();print(json.dumps(rows[-1]),flush=True)
 finally:
  current='cleanup';session.park(game);game.release_control()
  if 'fire_replan' in a.cases.split(','):
   # Resetting terrain/HP does not clear VoxeLibre's persistent burning timer.
   # Let it expire on the parked dry floor before another suite can start.
   end=time.monotonic()+12
   while time.monotonic()<end:
    assert not game.observe().dead;time.sleep(.1)
  final=game.observe();save()
  (a.output/'final.json').write_text(json.dumps(dict(sdk=__version__,sdk_path=str(a.sdk),pid=session.meta['pid'],state=final.raw),indent=2))
assert samples and all(s['focused'] is False and s['audio_enabled'] is False for s in samples)
sys.exit(any(r['status']!='passed' for r in rows))
