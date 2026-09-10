#!/usr/bin/env python3
"""Extended skills against the existing visible process. Never launches a GUI."""
import argparse,json,sys,time,threading
from pathlib import Path
from test_session import Session
p=argparse.ArgumentParser();p.add_argument('--session',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--cases',default='container,smelt,iron_tool,checkpoint,bridge_collect,excavate,build,ladder,memory');a=p.parse_args()
sys.path.insert(0,str(a.sdk.resolve()));from luanti_course import Game,Traversal,ExplorationMemory
s=Session(a.session);a.out.mkdir(parents=True,exist_ok=False);checks=[]
def check(name,test,details=None):
 row=dict(name=name,passed=bool(test),details=details);checks.append(row);(a.out/'partial.json').write_text(json.dumps(checks,indent=2));print(json.dumps(row),flush=True)
 if not test:raise AssertionError(name)
def result(name,r):check(name,r.ok,r.to_dict());return r
with s.connect(Game) as g:
 try:
  for case in a.cases.split(','):
   g.exploration_memory=None;g.traversal=None
   try:
    if case=='container':
     s.reset(g,dict(id=case,nodes=[(3,100,0,'mcl_chests:chest_small')],inventory=['mcl_core:cobble 12']))
     result('deposit',g.deposit((3,100,0),'mcl_core:cobble',7));check('deposited_balance',g.observe().inventory['main'].count('mcl_core:cobble')==5)
     result('withdraw',g.withdraw((3,100,0),'mcl_core:cobble',4));check('withdrawn_balance',g.observe().inventory['main'].count('mcl_core:cobble')==9)
     result('restock',g.restock((3,100,0),'mcl_core:cobble',11));check('restock_balance',g.observe().inventory['main'].count('mcl_core:cobble')==11)
     result('restock_noop',g.restock((3,100,0),'mcl_core:cobble',11))
    elif case=='smelt':
     s.reset(g,dict(id=case,nodes=[(3,100,0,'mcl_furnaces:furnace')],inventory=['mcl_raw_ores:raw_iron 2','mcl_core:coal_lump']))
     result('smelt_iron',g.smelt('mcl_core:iron_ingot',2,furnace=(3,100,0),timeout=80));check('smelt_balance',g.observe().inventory['main'].count('mcl_core:iron_ingot')==2)
    elif case=='iron_tool':
     s.reset(g,dict(id=case,nodes=[(3,100,0,'mcl_furnaces:furnace'),(-3,100,0,'mcl_crafting_table:crafting_table')],inventory=['mcl_raw_ores:raw_iron 3','mcl_core:coal_lump','mcl_core:stick 2']))
     result('craft_iron_pickaxe',g.craft('mcl_tools:pick_iron',gather=False,timeout=120));check('iron_tool_inventory',g.observe().inventory['main'].count('mcl_tools:pick_iron')==1)
    elif case=='checkpoint':
     s.reset(g,dict(id=case,nodes=[(3,100,0,'mcl_furnaces:furnace')],inventory=['mcl_raw_ores:raw_iron 2','mcl_core:coal_lump']))
     path=a.out/'smelt.checkpoint.json';out=[]
     t=threading.Thread(target=lambda:out.append(g.smelt('mcl_core:iron_ingot',2,furnace=(3,100,0),checkpoint=path,timeout=80)),daemon=True);t.start()
     end=time.monotonic()+25
     while time.monotonic()<end and not g.observe().inventory['main'].count('mcl_core:iron_ingot'):time.sleep(.1)
     g.stop();t.join(8);check('checkpoint_cancel',not t.is_alive() and out and not out[0].ok,out[0].to_dict() if out else None)
     g.take_control();result('checkpoint_resume',g.resume(path,timeout=80));check('checkpoint_no_duplicate',g.observe().inventory['main'].count('mcl_core:iron_ingot')==2)
     result('checkpoint_repeat_noop',g.resume(path,timeout=20));check('checkpoint_repeat_balance',g.observe().inventory['main'].count('mcl_core:iron_ingot')==2)
    elif case=='bridge_collect':
     s.reset(g,dict(id=case,fill=[dict(min=[4,99,-32],max=[6,99,32],name='air')],nodes=[(10,100,0,'mcl_core:tree')],inventory=['mcl_core:cobble 16']))
     result('collect_across_bridge',g.collect('mcl_core:tree',1,traversal=Traversal(build_with='mcl_core:cobble'),search_radius=18,timeout=120));check('bridge_material_consumed',g.observe().inventory['main'].count('mcl_core:cobble')<16)
    elif case=='excavate':
     s.reset(g,dict(id=case,fill=[dict(min=[1,94,-3],max=[6,101,3],name='mcl_core:stone')],inventory=['mcl_tools:pick_iron']))
     result('staircase_down_and_return',g.excavate([(0,100,0),(1,99,0),(2,98,0),(3,97,0)],timeout=150));check('returned',abs(g.observe().position[0])<.5 and abs(g.observe().position[1]-99.5)<.2)
    elif case=='build':
     s.reset(g,dict(id=case,inventory=['mcl_core:cobble 8']))
     blocks=[('mcl_core:cobble',(2,y,z)) for y in (100,101) for z in (0,1)]
     result('blueprint',g.build(list(reversed(blocks)),timeout=90));check('build_balance',g.observe().inventory['main'].count('mcl_core:cobble')==4)
     result('blueprint_repeat_noop',g.build(blocks,timeout=20));check('build_no_duplicate',g.observe().inventory['main'].count('mcl_core:cobble')==4)
    elif case=='ladder':
     s.reset(g,dict(id=case,fill=[dict(min=[1,100,3],max=[1,105,3],name='mcl_core:stone')],inventory=['mcl_core:ladder 6']))
     result('build_and_climb_ladder',g.build_ladder((0,100,3),5,timeout=100));check('ladder_balance',g.observe().inventory['main'].count('mcl_core:ladder')==1)
    elif case=='ladder_wall':
     s.reset(g,dict(id=case,inventory=['mcl_core:ladder 5','mcl_core:cobble 5']))
     result('ladder_and_backing',g.build_ladder((0,100,3),5,backing_material='mcl_core:cobble',timeout=100));check('backing_inventory',g.observe().inventory['main'].count('mcl_core:cobble')==0)
    elif case=='craft_gather_iron':
     s.reset(g,dict(id=case,nodes=[(3,100,0,'mcl_core:stone_with_iron'),(3,100,1,'mcl_core:stone_with_iron'),(3,100,2,'mcl_core:stone_with_iron'),(-3,100,0,'mcl_crafting_table:crafting_table')],inventory=['mcl_tools:pick_stone','mcl_core:coal_lump','mcl_core:stick 2','mcl_core:cobble 8']))
     result('mine_smelt_craft_iron',g.craft('mcl_tools:pick_iron',gather=True,timeout=150));check('gather_iron_inventory',g.observe().inventory['main'].count('mcl_tools:pick_iron')==1)
    elif case=='craft_checkpoint':
     s.reset(g,dict(id=case,nodes=[(3,100,0,'mcl_furnaces:furnace'),(-3,100,0,'mcl_crafting_table:crafting_table')],inventory=['mcl_raw_ores:raw_iron 3','mcl_core:coal_lump','mcl_core:stick 2']))
     path=a.out/'craft.checkpoint.json';out=[]
     t=threading.Thread(target=lambda:out.append(g.craft('mcl_tools:pick_iron',gather=False,checkpoint=path,timeout=100)),daemon=True);t.start()
     end=time.monotonic()+25
     while time.monotonic()<end and not g.observe().inventory['main'].count('mcl_core:iron_ingot'):time.sleep(.1)
     g.stop();t.join(8);check('craft_checkpoint_cancel',not t.is_alive() and out and out[0].status=='cancelled',out[0].to_dict() if out else None)
     g.take_control();result('craft_inflight_resume',g.resume(path,timeout=120));check('craft_checkpoint_inventory',g.observe().inventory['main'].count('mcl_tools:pick_iron')==1)
    elif case=='collect_checkpoint':
     s.reset(g,dict(id=case,nodes=[(3,100,z,'mcl_core:tree') for z in range(7)]))
     path=a.out/'collect.checkpoint.json';out=[]
     t=threading.Thread(target=lambda:out.append(g.collect('mcl_core:tree',7,checkpoint=path,timeout=80)),daemon=True);t.start()
     end=time.monotonic()+25
     while time.monotonic()<end and not g.observe().inventory['main'].count('mcl_core:tree'):time.sleep(.05)
     g.stop();t.join(8);check('collect_checkpoint_cancel',not t.is_alive() and out and out[0].status=='cancelled',out[0].to_dict() if out else None)
     # A new Python connection, same visible character and same checkpoint file.
     g.close();g=s.connect(Game)
     result('collect_reconnect_resume',g.resume(path,timeout=80));check('collect_checkpoint_inventory',g.observe().inventory['main'].count('mcl_core:tree')==7)
    elif case=='swim_collect':
     s.reset(g,dict(id=case,spawn=(2,99.51,0),fill=[dict(min=[3,96,-32],max=[6,99,32],name='mcl_core:water_source'),dict(min=[3,95,-32],max=[6,95,32],name='mcl_core:stone')],nodes=[(8,100,0,'mcl_core:tree')]))
     result('collect_across_water',g.collect('mcl_core:tree',1,traversal=Traversal(allow_swim=True),search_radius=16,timeout=90))
    elif case=='dig_collect':
     s.reset(g,dict(id=case,fill=[dict(min=[3,100,-32],max=[3,103,32],name='mcl_core:stone')],nodes=[(6,100,0,'mcl_core:tree')],inventory=['mcl_tools:pick_iron']))
     result('collect_through_wall',g.collect('mcl_core:tree',1,traversal=Traversal(allow_dig=True),search_radius=16,timeout=80))
    elif case=='hazards':
     s.reset(g,dict(id=case,fill=[dict(min=[1,98,-2],max=[3,101,2],name='mcl_core:stone')],nodes=[(1,102,0,'mcl_core:sand')],inventory=['mcl_tools:pick_iron']))
     r=g.excavate([(0,100,0),(1,99,0)],timeout=20);check('sand_roof_stops',r.reason=='unstable_excavation_boundary',r.to_dict());check('hazard_no_damage',g.observe().hp==20)
     s.reset(g,dict(id=case+'_fuel',nodes=[(3,100,0,'mcl_furnaces:furnace')],inventory=['mcl_raw_ores:raw_iron']))
     r=g.smelt('mcl_core:iron_ingot',furnace=(3,100,0),timeout=20);check('missing_fuel_stops',r.reason=='fuel_unavailable',r.to_dict());check('missing_fuel_keeps_input',g.observe().inventory['main'].count('mcl_raw_ores:raw_iron')==1)
     s.reset(g,dict(id=case+'_material'))
     r=g.build([('mcl_core:cobble',(2,100,0))],timeout=20);check('missing_build_material',r.reason=='item_not_held',r.to_dict())
     s.reset(g,dict(id=case+'_empty',nodes=[(3,100,0,'mcl_chests:chest_small')]))
     r=g.withdraw((3,100,0),'mcl_core:wood',1);check('empty_chest_stops',r.reason=='container_item_missing',r.to_dict())
    elif case=='policy_override':
     s.reset(g,dict(id=case,fill=[dict(min=[3,100,-32],max=[3,103,32],name='mcl_core:stone')],inventory=['mcl_tools:pick_iron','mcl_core:cobble 16']))
     g.traversal=Traversal(allow_dig=True,build_with='mcl_core:cobble')
     r=g.navigate_to((5,99.5,0),allow_dig=False,build_with=None,search_radius=8,timeout=25)
     check('explicit_edit_disable',not r.ok and not r.details.get('terrain_changes'),r.to_dict())
     check('disabled_material_unchanged',g.observe().inventory['main'].count('mcl_core:cobble')==16)
     s.reset(g,dict(id=case+'_enabled',fill=[dict(min=[3,100,-32],max=[3,103,32],name='mcl_core:stone')],inventory=['mcl_tools:pick_iron','mcl_core:cobble 16']))
     result('inherited_edit_enable',g.navigate_to((5,99.5,0),search_radius=8,timeout=35))
    elif case=='memory':
     s.reset(g,dict(id=case));g.exploration_memory=ExplorationMemory()
     result('segmented_route',g.navigate_route([(20,99.5,0),(20,99.5,20),(-20,99.5,20),(-20,99.5,-20),(0,99.5,0)],timeout=150))
     check('memory_retained',len(g.exploration_memory.nodes)>2000,len(g.exploration_memory.nodes))
     result('memory_reuse',g.navigate_to((15,99.5,0),timeout=30))
     check('memory_scope',g.exploration_memory.scope==str(g.endpoint.resolve()))
   except Exception as e:
    checks.append(dict(name=case+'_exception',passed=False,error=repr(e)));print(json.dumps(checks[-1]),flush=True)
   finally:
    g.exploration_memory=None;s.park(g);g.take_control()
 finally:s.park(g)
(a.out/'results.json').write_text(json.dumps(dict(pid=s.meta['pid'],checks=checks),indent=2))
assert all(x['passed'] for x in checks),'some extended checks failed'
print('PASS',len(checks),'checks, PID',s.meta['pid'])
