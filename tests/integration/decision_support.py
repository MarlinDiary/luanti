#!/usr/bin/env python3
"""Decision-support APIs on the existing isolated visible client. Never launches."""
import argparse,json,sys,time,threading
from pathlib import Path
from test_session import Session
p=argparse.ArgumentParser();p.add_argument('--session',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--cases',default='queries,locations,container,migration,collect_upgrade,furnace_upgrade,return');a=p.parse_args()
sys.path.insert(0,str(a.sdk.resolve()))
from luanti_course import Game,Traversal
from luanti_course.persistence import Checkpoint
from dataclasses import asdict
s=Session(a.session);a.out.mkdir(parents=True,exist_ok=False);checks=[]
def check(name,passed,details=None):
 row=dict(name=name,passed=bool(passed),details=details);checks.append(row);(a.out/'partial.json').write_text(json.dumps(checks,indent=2));print(json.dumps(row),flush=True)
 if not passed:raise AssertionError(name)
def result(name,r):check(name,r.ok,r.to_dict());return r
with s.connect(Game) as g:
 try:
  for case in a.cases.split(','):
   try:
    g.traversal=None;g.exploration_memory=None;g.reset_mining_trip()
    if case=='queries':
     s.reset(g,dict(id=case,inventory=['mcl_core:tree 3']));g.release_control();before=g.observe();plan=g.plan_craft('wooden_pickaxe')
     check('read_only_plan_ready',plan.materials_ready and not plan.missing,plan.to_dict())
     check('plan_contains_intermediates',any(x['item']=='mcl_core:stick' for x in plan.steps))
     after=g.observe();check('query_never_acquires_or_moves',after.control=='observe' and after.position==before.position and not after.raw['input_active'])
     check('query_preserves_inventory',after.inventory==before.inventory)
     check('recipe_catalog_query',bool(g.recipes_for('wooden_pickaxe')['recipes']))
     g.take_control();s.reset(g,dict(id=case+'_missing'));g.release_control();r=g.plan_craft('wooden_pickaxe')
     check('missing_materials_explicit',not r.materials_ready and r.missing_complete and bool(r.missing),r.to_dict())
     check('missing_plan_did_not_collect',not any(x.count for x in g.observe().inventory['main'].items))
     g.take_control()
    elif case=='locations':
     s.reset(g,dict(id=case));g.release_control();entry=g.remember_location('基地');path=a.out/'places.json';g.save_locations(path)
     check('remember_is_observe_only',g.observe().control=='observe' and not g.observe().raw['input_active'])
     returned=g.saved_locations();returned.clear();check('landmark_copy_detached','基地' in g.saved_locations())
     g.take_control();result('travel_away',g.navigate_to((5,99.5,2)))
     g.close();g=s.connect(Game);check('load_after_reconnect',g.load_locations(path)['基地']==entry)
     result('return_named_place',g.go_to_location('基地'));check('returned_to_named_coordinates',sum(abs(x-y) for x,y in zip(g.observe().position,entry))<.6)
     before=g.observe().position;r=g.go_to_location('missing');check('unknown_place_no_motion',r.reason=='location_unknown' and g.observe().position==before)
     check('forget_explicit',g.forget_location('基地') and not g.saved_locations())
    elif case=='container':
     s.reset(g,dict(id=case,nodes=[(3,100,0,'mcl_chests:chest_small')],inventory=['mcl_core:cobble 9']))
     result('prepare_container',g.deposit((3,100,0),'mcl_core:cobble',5));before=g.observe().inventory
     r=result('inspect_container',g.inspect_container((3,100,0)))
     check('container_exact_contents',r.details['counts']=={'mcl_core:cobble':5} and r.details['items_transferred']==0,r.to_dict())
     check('inspect_preserves_inventory',g.observe().inventory==before)
     check('inspect_closes_owned_ui',not g.observe().raw['menu_open'])
     result('take_after_inspection',g.withdraw((3,100,0),'mcl_core:cobble',5));check('container_total_conserved',g.observe().inventory['main'].count('mcl_core:cobble')==9)
     r=g.inspect_container((0,99,0));check('unsupported_container_clear_error',r.reason=='station_type_unsupported',r.to_dict())
    elif case=='migration':
     s.reset(g,dict(id=case,inventory=['mcl_core:wood 4','mcl_core:tree']))
     old=a.out/'old-craft.json';new=a.out/'new-craft.json';request=dict(item='mcl_core:wood',count=8,gather=False,search_radius=32,recover=True,traversal=asdict(Traversal()))
     cp=Checkpoint(old,str(g.endpoint.resolve()),'craft',request,0);cp.progress(4);saved=old.read_bytes()
     g.release_control();r=g.upgrade_checkpoint(old,new);check('upgrade_no_control_required',g.observe().control=='observe' and r['remaining']==4,r)
     check('upgrade_preserves_old_file',old.read_bytes()==saved)
     check('upgrade_default_no_tool_autonomy',json.loads(new.read_text())['request']['allow_tool_crafting'] is False)
     g.take_control();result('resume_upgraded_quantity',g.resume(new));check('upgrade_no_double_production',g.observe().inventory['main'].count('mcl_core:wood')==8)
     result('upgraded_completed_noop',g.resume(new));check('repeat_preserves_completed_count',g.observe().inventory['main'].count('mcl_core:wood')==8)
     try:g.upgrade_checkpoint(old,new)
     except ValueError:check('upgrade_no_overwrite',True)
     else:check('upgrade_no_overwrite',False)
    elif case=='collect_upgrade':
     s.reset(g,dict(id=case,nodes=[(3,100,z,'mcl_core:tree') for z in range(3)],inventory=['mcl_core:tree 2']))
     old=a.out/'old-collect.json';new=a.out/'new-collect.json';request=dict(resource='mcl_core:tree',count=5,search_radius=32,recover=True,traversal=asdict(Traversal()))
     cp=Checkpoint(old,str(g.endpoint.resolve()),'collect',request,0);cp.progress(2);saved=old.read_bytes()
     r=g.upgrade_checkpoint(old,new);check('collect_upgrade_remaining',r['remaining']==3 and old.read_bytes()==saved,r)
     result('collect_upgraded_resume',g.resume(new));check('collect_upgrade_exact_total',g.observe().inventory['main'].count('mcl_core:tree')==5)
     result('collect_upgraded_noop',g.resume(new));check('collect_upgraded_no_extra',g.observe().inventory['main'].count('mcl_core:tree')==5)
    elif case=='furnace_upgrade':
     s.reset(g,dict(id=case,nodes=[(3,100,0,'mcl_furnaces:furnace'),(-3,100,0,'mcl_crafting_table:crafting_table')],inventory=['mcl_raw_ores:raw_iron 3','mcl_core:coal_lump','mcl_core:stick 2']))
     path=a.out/'current-furnace-task.json';out=[]
     t=threading.Thread(target=lambda:out.append(g.craft('mcl_tools:pick_iron',checkpoint=path,timeout=100)),daemon=True);t.start()
     end=time.monotonic()+25
     while time.monotonic()<end and not g.observe().inventory['main'].count('mcl_core:iron_ingot'):time.sleep(.1)
     g.stop();t.join(8);check('upgrade_inflight_cancel',not t.is_alive() and out and out[0].status=='cancelled',out[0].to_dict() if out else None)
     data=json.loads(path.read_text());check('upgrade_has_pending_furnace',bool(data['station']),data)
     # Legacy 0.7 schema: same ledger/station, missing only the new tool policy.
     del data['request']['allow_tool_crafting'];old=a.out/'old-furnace-craft.json';new=a.out/'new-furnace-craft.json';old.write_text(json.dumps(data));saved=old.read_bytes()
     r=g.upgrade_checkpoint(old,new);check('upgrade_preserves_pending_station',r['station']==data['station'] and old.read_bytes()==saved,r)
     g.take_control();result('upgrade_inflight_resume',g.resume(new,timeout=120));check('upgrade_inflight_one_pick',g.observe().inventory['main'].count('mcl_tools:pick_iron')==1)
     result('upgrade_inflight_completed_noop',g.resume(new));check('upgrade_inflight_no_duplicate',g.observe().inventory['main'].count('mcl_tools:pick_iron')==1)
    elif case=='return':
     s.reset(g,dict(id=case,fill=[dict(min=[-8,88,-8],max=[8,99,8],name='mcl_core:stone')],inventory=['mcl_tools:pick_iron']))
     result('down_for_explicit_return',g.dig_down(2));r=result('explicit_entrance_return',g.return_to_entrance())
     check('entrance_name_and_destination',r.operation=='return_to_entrance' and r.details['destination_kind']=='remembered_mining_entrance' and abs(g.observe().position[1]-99.5)<.2)
   except Exception as exc:checks.append(dict(name=case+'_exception',passed=False,error=repr(exc)));print(json.dumps(checks[-1]),flush=True)
   finally:s.park(g);g.take_control()
 finally:s.park(g)
(a.out/'results.json').write_text(json.dumps(dict(pid=s.meta['pid'],checks=checks),indent=2));assert all(c['passed'] for c in checks)
print('PASS',len(checks),'checks PID',s.meta['pid'])
