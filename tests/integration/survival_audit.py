#!/usr/bin/env python3
"""Real-engine local survival audit; no course-server credentials or fixture deployment."""
import argparse,json,sys,time,threading,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'sdk/src'))
from test_session import Session
p=argparse.ArgumentParser();p.add_argument('--session',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cases',default='all');p.add_argument('--sdk',type=Path);a=p.parse_args()
if a.sdk:
 if not (a.sdk/'luanti_course/__init__.py').is_file():raise SystemExit('Requested SDK directory is missing; no source fallback')
 sys.path.insert(0,str(a.sdk))
from luanti_course import Game,SurvivalConfig
import luanti_course
print('SDK',luanti_course.__version__,luanti_course.__file__,flush=True)
a.output.mkdir(parents=True,exist_ok=False);session=Session(a.session);results=[];samples=[];commands=[];current=''
def save():
 for name,value in [('results',results),('samples',samples),('commands',commands)]:
  (a.output/(name+'.json')).write_text(json.dumps(value,indent=2))
def wait_for(pred,timeout=5):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  v=pred()
  if v:return v
  time.sleep(.06)
 raise AssertionError('condition timeout')
def scene(g,name,**kw):
 session.reset(g,dict(id=name,**kw));time.sleep(.5)
 if kw.get('entities'):wait_for(lambda:g.observe().entities)
 if 'hunger' in kw:wait_for(lambda:g.observe().hunger==kw['hunger'])
def target(g):return next(e for e in g.observe().entities if not e.is_player)
def expect(r):
 assert r.ok,r.to_dict();return r.to_dict()
def dummy(x=0,z=2,**kw):return dict(name='persistent_fixture:target',position=[x,99.51,z],**kw)
with session.connect(Game) as g:
 raw=g._request
 def request(op,**kw):
  r=raw(op,**kw)
  if op=='observe':samples.append(dict(case=current,time=time.monotonic(),**{k:r.get(k) for k in ('position','eye','yaw','pitch','hp','breath','control','control_epoch','input_active','steering_active','velocity','in_liquid','entities','hud_statbars','hazards','focused','audio_enabled')}))
  else:commands.append(dict(case=current,time=time.monotonic(),op=op,args=kw,response=r))
  return r
 g._request=request
 def case(name,fn):
  global current
  if a.cases!='all' and name not in a.cases.split(','):return
  current=name;start=time.monotonic()
  try:
   detail=fn();row=dict(case=name,status='passed',detail=detail)
  except Exception as exc:row=dict(case=name,status='failed',error=str(exc),traceback=traceback.format_exc())
  row['elapsed']=time.monotonic()-start;results.append(row);save();print(json.dumps(row),flush=True)
 def observe_case():
  scene(g,'observe',hunger=8,entities=[dummy()],inventory=['mcl_core:apple 3'])
  s=g.observe();assert s.hunger==8;assert s.entities[0].name=='persistent_fixture:target';assert not s.raw['audio_enabled'];assert not s.raw['focused']
  return dict(hunger=s.hunger,entity=s.entities[0].ref)
 case('observation',observe_case)
 def kill():
  scene(g,'attack',entities=[dummy()],inventory=['mcl_tools:sword_diamond'])
  r=expect(g.attack_entity(target(g),timeout=12));assert r['details']['outcome']=='target_no_longer_observed';assert r['details']['attacks_submitted']>=3;return r
 case('attack_stationary',kill)
 def chase():
  scene(g,'chase',entities=[dummy(z=6)],inventory=['mcl_tools:sword_diamond'])
  return expect(g.attack_entity(target(g),timeout=18))
 case('chase_and_attack',chase)
 def stale():
  scene(g,'stale1',entities=[dummy()],inventory=['mcl_tools:sword_diamond']);old=target(g)
  scene(g,'stale2',entities=[dummy()],inventory=['mcl_tools:sword_diamond']);r=g.attack_entity(old,timeout=5)
  assert r.reason=='target_not_observed',r;assert r.details['attacks_submitted']==0;return r.to_dict()
 case('stale_target',stale)
 def moving_flee():
  scene(g,'moving_flee',entities=[dummy(z=1.5,chase=True,speed=2,damage=2)])
  s=g.observe();r=expect(g.flee_from(target(g),safe_distance=10,timeout=22));assert r['details']['nearest_distance']>=10
  return dict(result=r,hp_before=s.hp,hp_after=g.observe().hp)
 case('flee_moving_damage',moving_flee)
 def damaged_attack():
  scene(g,'damaged_attack',entities=[dummy(chase=True,damage=2)],inventory=['mcl_tools:sword_diamond'])
  r=expect(g.attack_entity(target(g),timeout=18));assert g.observe().hp>0;return r
 case('attack_under_damage',damaged_attack)
 def eating():
  scene(g,'eat',hunger=8,inventory=['mcl_mobitems:rotten_flesh','mcl_core:apple 5'])
  r=expect(g.eat_best_food());assert r['details']['item']=='mcl_core:apple';wait_for(lambda:g.observe().hunger>=12);return r
 case('eat_best_food',eating)
 def gear():
  scene(g,'gear',inventory=['mcl_tools:sword_wood','mcl_tools:sword_iron','mcl_armor:helmet_iron','mcl_armor:chestplate_iron'])
  r=expect(g.equip_best_gear());assert r['details']['weapon']=='mcl_tools:sword_iron';assert len(r['details']['armor_equipped'])==2;return r
 case('equip_best_gear',gear)
 def supervisor_eat():
  scene(g,'auto_eat',hunger=8,inventory=['mcl_core:apple 5'])
  with g.survival() as guard:
   wait_for(lambda:g.observe().hunger>=16,18);assert guard.wait_idle(5);events=guard.events()
  assert any(e['event']=='reaction_finished' and e['result']['status']=='success' for e in events);return events
 case('idle_auto_eat',supervisor_eat)
 def preemption():
  scene(g,'preempt',hunger=8,inventory=['mcl_core:apple 5'])
  with g.survival() as guard:
   r=g.navigate_to((20,99.5,0),timeout=20)
   assert r.status=='cancelled' and r.reason=='survival_interrupted',r
   wait_for(lambda:g.observe().hunger>=12,12);assert guard.wait_idle(6);events=guard.events()
  assert g.observe().position[0]<10
  return dict(task=r.to_dict(),events=events)
 case('interrupt_navigation',preemption)
 def paused():
  scene(g,'paused',hunger=8,inventory=['mcl_core:apple 5'])
  with g.survival() as guard:
   guard.pause();time.sleep(.5);assert g.observe().hunger==8
   guard.resume();wait_for(lambda:guard.busy);g.stop();time.sleep(.7)
   assert guard.paused;assert not g.observe().raw['input_active'];return guard.events()
 case('explicit_stop',paused)
 def zombie():
  scene(g,'zombie',night=True,entities=[dict(name='mobs_mc:zombie',position=[0,99.51,4])],inventory=['mcl_tools:sword_diamond','mcl_armor:helmet_diamond','mcl_armor:chestplate_diamond'])
  e=next(e for e in g.observe().entities if e.name=='mobs_mc:zombie');assert e.hostile
  return expect(g.attack_entity(e,timeout=25))
 case('real_zombie_combat',zombie)
 def skeleton():
  scene(g,'skeleton',night=True,entities=[dict(name='mobs_mc:skeleton',position=[0,99.51,5])])
  with g.survival(SurvivalConfig(threat_radius=9,safe_distance=13)) as guard:
   collected=[]
   def completed():
    collected.extend(guard.events());return any(e['event']=='reaction_finished' for e in collected)
   wait_for(completed,28)
   # A newly observed arrow may correctly preempt the longer flee action.
   # Keep draining until the explicit priority handoff itself completes.
   end=time.monotonic()+28
   while time.monotonic()<end:
    collected.extend(guard.events())
    finished=[e for e in collected if e['event']=='reaction_finished']
    if any(e['result']['status']=='success' for e in finished) and guard.wait_idle(.2):break
    time.sleep(.06)
   finished=[e for e in collected if e['event']=='reaction_finished']
   cancelled=[e for e in finished if e['result']['status']=='cancelled']
   assert all(e['result']['reason']=='survival_interrupted' and
              e['result']['details'].get('intervention',{}).get('action')=='avoid_projectile'
              for e in cancelled),finished
   assert any(e['result']['status']=='success' for e in finished),finished
  return collected
 case('real_skeleton_avoid',skeleton)
 def retreat():
  scene(g,'retreat',hp=4,night=True,entities=[dict(name='mobs_mc:zombie',position=[0,99.51,4])],inventory=['mcl_tools:sword_diamond'])
  r=expect(g.defend_self(timeout=25));assert r['details']['outcome']=='retreated';assert g.observe().hp>0;return r
 case('defend_low_health_retreat',retreat)
 def native_gate():
  scene(g,'native_gate',entities=[dummy(z=5)],inventory=['mcl_tools:sword_diamond'],fill=[dict(min=[-3,100,2],max=[3,102,2],name='mcl_core:stone')])
  e=target(g);seen=[]
  for args in (dict(target_id=e.id,instance=e.instance+1),dict(target_id=e.id,instance=e.instance)):
   try:g._submit('attack',**args)
   except Exception as exc:seen.append(getattr(exc,'code',str(exc)))
  assert seen==['stale_entity','entity_not_in_crosshair'],seen
  assert not g.observe().raw['input_active'];return seen
 case('native_target_guards',native_gate)
 def air():
  scene(g,'air',spawn=[0,98,0],breath=3,fill=[dict(min=[-4,96,-4],max=[4,100,4],name='mcl_core:water_source'),dict(min=[-4,95,-4],max=[4,95,4],name='mcl_core:stone')])
  return expect(g.recover_air(timeout=20))
 case('recover_air',air)
 def fire():
  scene(g,'fire',nodes=[[0,100,0,'mcl_fire:fire']],hp=20)
  assert g.observe().raw['hazards'];r=expect(g.escape_hazard(timeout=15))
  # Leaving the source does not extinguish the game's continuing fire effect.
  # Let it expire naturally before the next independent fixture/suite.
  time.sleep(12);return r
 case('escape_fire',fire)
 current='cleanup';session.park(g);g.screenshot();save()
failed=[r['case'] for r in results if r['status']!='passed'];print('FAILED',failed);sys.exit(bool(failed))
