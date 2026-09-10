#!/usr/bin/env python3
"""Core skill regression attached to the persistent local fixture (no GUI spawn)."""
import argparse,json,sys,time,threading
from pathlib import Path
from test_session import Session
p=argparse.ArgumentParser();p.add_argument('--session',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
sys.path.insert(0,str(a.sdk.resolve()));from luanti_course import Game,ActionError
session=Session(a.session);checks=[]
def check(name,condition,details=None):
 checks.append(dict(name=name,pass_=bool(condition),details=details));print(json.dumps(checks[-1]),flush=True);assert condition,name
with session.connect(Game) as game:
 session.reset(game,dict(id='core_skills',nodes=[(4,y,0,'mcl_core:tree') for y in range(100,104)]+[(6,100,0,'mcl_core:stone')]))
 r=game.find_resource('group:tree',search_radius=16,timeout=40);check('find_tree',r.ok,r.to_dict())
 r=game.craft('wooden_pickaxe',gather=True,search_radius=16,timeout=180);check('gather_and_craft_pickaxe',r.ok,r.to_dict())
 check('crafted_inventory',game.observe().inventory['main'].count('mcl_tools:pick_wood')>=1)
 r=game.equip('mcl_tools:pick_wood');check('equip_by_name',r.ok,r.to_dict())
 r=game.collect('mcl_core:cobble',1,search_radius=16,timeout=60);check('collect_with_tool',r.ok,r.to_dict())
 check('collected_inventory',game.observe().inventory['main'].count('mcl_core:cobble')>=1)
 session.reset(game,dict(id='place_inventory',inventory=['mcl_core:cobble 3','mcl_core:wood 10','mcl_core:wood 5','mcl_armor:helmet_iron']))
 r=game.organize_inventory();check('organize',r.ok,r.to_dict());check('conserved_wood',game.observe().inventory['main'].count('mcl_core:wood')==15)
 r=game.equip('mcl_armor:helmet_iron',destination='armor');check('armor',r.ok,r.to_dict())
 r=game.place_block('mcl_core:cobble',(2,100,0));check('place_block',r.ok,r.to_dict());check('placement_count',game.observe().inventory['main'].count('mcl_core:cobble')==2)
 r=game.craft('mcl_core:stick',count=16,gather=False,timeout=50);check('batch_crafting',r.ok,r.to_dict());check('batch_count',game.observe().inventory['main'].count('mcl_core:stick')==16)
 for name,kwargs in [('sand',dict(build_with='mcl_core:sand')),('slab',dict(build_with='mcl_stairs:slab_stone'))]:
  r=game.navigate_to((5,99.5,0),**kwargs);check('reject_unstable_build_'+name,not r.ok and r.reason=='building_material_not_full_cube',r.to_dict())
 session.reset(game,dict(id='cancellation'))
 results=[]
 t=threading.Thread(target=lambda:results.append(game.navigate_to((25,99.5,0),timeout=30)),daemon=True);t.start();time.sleep(.4);game.stop();t.join(10)
 check('cancel_joins',not t.is_alive());check('cancel_structured',results and results[0].status=='cancelled',results[0].to_dict() if results else None)
 time.sleep(.3);before=game.observe();time.sleep(.3);after=game.observe();check('cancel_stopped',sum((x-y)**2 for x,y in zip(before.position,after.position))<.01)
 # Explicit release must remove action ownership; observing remains available.
 game.release_control();check('release_is_read_only',game.observe().control!='agent')
 r=game.navigate_to((2,99.5,0));check('movement_requires_control',r.reason=='control_required',r.to_dict())
 session.park(game)
a.out.write_text(json.dumps(dict(pid=session.meta['pid'],checks=checks,passed=len(checks)),indent=2));print('ALL CORE CHECKS PASSED',len(checks))
