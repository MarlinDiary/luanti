#!/usr/bin/env python3
"""Student-facing boundaries and complete jobs, on the existing visible client."""
import argparse,json,sys,time,threading
from pathlib import Path
from test_session import Session
p=argparse.ArgumentParser();p.add_argument('--session',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--cases',default='defaults,held_craft,advanced_tool,down,tunnel,checkpoint,bridge,food,food_under_roof,hazards');a=p.parse_args()
sys.path.insert(0,str(a.sdk.resolve()))
from luanti_course import Game,Traversal
s=Session(a.session);a.out.mkdir(parents=True,exist_ok=False);checks=[]
def check(name,test,details=None):
 row=dict(name=name,passed=bool(test),details=details);checks.append(row);(a.out/'partial.json').write_text(json.dumps(checks,indent=2));print(json.dumps(row),flush=True)
 if not test:raise AssertionError(name)
def result(name,r):check(name,r.ok,r.to_dict());return r
def bedrock(**kw):return dict(fill=[dict(min=[-15,88,-15],max=[15,99,15],name='mcl_core:stone')],inventory=['mcl_tools:pick_iron'],**kw)
with s.connect(Game) as g:
 try:
  for case in a.cases.split(','):
   try:
    g.reset_mining_trip();g.traversal=None;g.exploration_memory=None
    if case=='defaults':
     s.reset(g,dict(id=case,nodes=[(3,100,0,'mcl_core:tree')]))
     r=g.craft('wooden_pickaxe',timeout=25);check('missing_materials_no_procurement',not r.ok and not r.trace,r.to_dict());check('tree_not_harvested',g.observe(6).inventory['main'].count('mcl_core:tree')==0)
     s.reset(g,dict(id=case+'_tool',nodes=[(3,100,0,'mcl_core:stone'),(-3,100,0,'mcl_crafting_table:crafting_table')],inventory=['mcl_core:wood 8','mcl_core:stick 8']))
     r=g.collect('mcl_core:cobble',timeout=30);check('missing_tool_no_upgrade',r.reason=='suitable_tool_required' and not any(t['event']=='recover_tool' for t in r.trace),r.to_dict());check('wood_not_spent',g.observe().inventory['main'].count('mcl_core:wood')==8)
    elif case=='held_craft':
     s.reset(g,dict(id=case,inventory=['mcl_core:tree 3']))
     result('craft_held_intermediates',g.craft('wooden_pickaxe',timeout=70));check('held_pickaxe_inventory',g.observe().inventory['main'].count('mcl_tools:pick_wood')==1)
    elif case=='advanced_tool':
     s.reset(g,dict(id=case,nodes=[(3,100,0,'mcl_core:stone'),(-3,100,0,'mcl_crafting_table:crafting_table')],inventory=['mcl_core:wood 8','mcl_core:stick 8']))
     r=result('explicit_tool_crafting',g.collect('mcl_core:cobble',allow_tool_crafting=True,timeout=60));check('tool_upgrade_was_explicit',any(t['event']=='recover_tool' for t in r.trace),r.to_dict())
    elif case=='down':
     s.reset(g,bedrock(id=case));r=result('automatic_staircase',g.dig_down(4,timeout=150));check('stays_at_depth',abs(g.observe().position[1]-95.5)<.2 and r.details['completed_steps']==4)
     result('return_to_entrance',g.go_to_surface(timeout=80));check('returned_position',sum(abs(x-y) for x,y in zip(g.observe().position,(0,99.5,0)))<.6)
    elif case=='tunnel':
     s.reset(g,bedrock(id=case));result('down_before_tunnel',g.dig_down(3,timeout=100));start=g.observe().position
     result('horizontal_tunnel',g.dig_tunnel(4,direction=(0,0,1),timeout=150));check('tunnel_endpoint',abs(g.observe().position[1]-96.5)<.2 and g.observe().position[2]>3.7)
     result('tunnel_then_surface',g.go_to_surface(timeout=100));check('whole_excursion_return',abs(g.observe().position[1]-99.5)<.2 and abs(g.observe().position[0])<.4)
    elif case=='checkpoint':
     s.reset(g,bedrock(id=case));path=a.out/'mining.json';out=[]
     t=threading.Thread(target=lambda:out.append(g.dig_down(5,checkpoint=path,timeout=180)),daemon=True);t.start();end=time.monotonic()+35
     while time.monotonic()<end:
      try:
       if json.loads(path.read_text()).get('completed_steps',0)>=1:break
      except (FileNotFoundError,json.JSONDecodeError):pass
      time.sleep(.05)
     g.stop();t.join(10);check('mining_cancel',not t.is_alive() and out and out[0].status=='cancelled',out[0].to_dict() if out else None)
     g.close();g=s.connect(Game);result('return_after_reconnect',g.go_to_surface(checkpoint=path,timeout=80))
     result('resume_after_return',g.resume(path,timeout=180));check('resumed_depth',abs(g.observe().position[1]-94.5)<.2)
     r=result('completed_resume_noop',g.resume(path,timeout=20));check('no_duplicate_descent',r.details.get('already_complete') and abs(g.observe().position[1]-94.5)<.2)
     result('completed_trip_surface',g.go_to_surface(checkpoint=path,timeout=100))
    elif case=='bridge':
     s.reset(g,dict(id=case,fill=[dict(min=[3,95,-32],max=[5,99,32],name='air'),dict(min=[3,94,-32],max=[5,94,32],name='mcl_core:stone')],inventory=['mcl_core:cobble 12']))
     r=result('complete_bridge_job',g.bridge_to((8,99.5,0),timeout=90));check('bridge_material_balance',g.observe().inventory['main'].count('mcl_core:cobble')<12 and bool(r.details.get('terrain_changes')))
    elif case=='food':
     s.reset(g,dict(id=case,inventory=['mcl_core:apple 3']));g.chat('/grantme hunger');time.sleep(.2);g.chat('/sethunger singleplayer 8');time.sleep(.5)
     result('eat_held_food',g.eat('mcl_core:apple',2,timeout=25));check('food_consumed_balance',g.observe().inventory['main'].count('mcl_core:apple')==1)
     g.chat('/sethunger singleplayer 20');time.sleep(.3);r=g.eat('mcl_core:apple',timeout=10);check('full_hunger_bounded',r.reason=='food_not_consumed',r.to_dict());check('full_hunger_keeps_food',g.observe().inventory['main'].count('mcl_core:apple')==1)
    elif case=='food_under_roof':
     s.reset(g,dict(id=case,fill=[dict(min=[-2,102,-2],max=[2,102,2],name='mcl_core:stone')],inventory=['mcl_core:apple 2']))
     g.chat('/grantme hunger');time.sleep(.2);g.chat('/sethunger singleplayer 8');time.sleep(.5)
     result('eat_under_roof',g.eat('mcl_core:apple',timeout=15));check('roof_food_balance',g.observe().inventory['main'].count('mcl_core:apple')==1)
     g.chat('/sethunger singleplayer 20');time.sleep(.2);out=[]
     t=threading.Thread(target=lambda:out.append(g.eat('mcl_core:apple',timeout=15)),daemon=True);t.start();time.sleep(.5);g.stop();t.join(8)
     check('food_cancelled',not t.is_alive() and out and out[0].status=='cancelled',out[0].to_dict() if out else None)
     check('food_cancel_stops_input',not g.observe().raw['input_active'])
    elif case=='hazards':
     s.reset(g,dict(id=case,fill=[dict(min=[-15,88,-15],max=[15,99,15],name='mcl_core:stone')],nodes=[(2,99,0,'mcl_core:water_source')],inventory=['mcl_tools:pick_iron']))
     r=g.dig_down(1,direction=(1,0,0),timeout=30);check('water_boundary_stops',r.reason=='mining_route_blocked',r.to_dict());check('water_no_damage',g.observe().hp==20)
     s.reset(g,bedrock(id=case+'_budget'));g.reset_mining_trip();r=g.dig_down(3,traversal=Traversal(edit_budget=1),timeout=45);check('shared_edit_budget',r.reason=='terrain_edit_budget' and r.details['completed_steps']==1,r.to_dict());result('budget_stop_can_return',g.go_to_surface(timeout=40))
     g.reset_mining_trip();r=g.go_to_surface(timeout=10);check('unknown_surface_reported',r.reason=='surface_unknown',r.to_dict())
   except Exception as exc:
    checks.append(dict(name=case+'_exception',passed=False,error=repr(exc)));print(json.dumps(checks[-1]),flush=True)
   finally:s.park(g);g.take_control()
 finally:
  g.chat('/revoke singleplayer hunger');s.park(g)
(a.out/'results.json').write_text(json.dumps(dict(pid=s.meta['pid'],checks=checks),indent=2));assert all(c['passed'] for c in checks)
print('PASS',len(checks),'checks PID',s.meta['pid'])
