#!/usr/bin/env python3
"""Verify respawn, idle parking, pause/resume and movement with one unchanged PID."""
import argparse,json,time,sys
from pathlib import Path
from test_session import Session,suspend,status
p=argparse.ArgumentParser();p.add_argument('--session',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
sys.path.insert(0,str(a.sdk.resolve()));from luanti_course import Game
session=Session(a.session);pid=session.meta['pid'];checks=[]
def check(name,ok,details=None):
 checks.append(dict(name=name,passed=bool(ok),details=details));print(json.dumps(checks[-1]),flush=True);assert ok,name
with session.connect(Game) as game:
 session.reset(game,dict(id='respawn_lifecycle',hp=0))
 check('modern_death_screen',game.observe().dead and game.observe().raw['menu_open'])
 game.respawn();end=time.monotonic()+5
 while game.observe().dead and time.monotonic()<end:time.sleep(.05)
 check('normal_respawn_confirmed',not game.observe().dead)
 time.sleep(.15);game.take_control();session.park(game)
 check('parked_alive_on_ground',game.observe().hp==20 and not game.observe().raw['in_liquid'])
suspend(a.session,True);time.sleep(.1);before=(session.world/'state.json').read_bytes();trace=(session.world/'motion.jsonl').stat().st_size;time.sleep(.5)
check('same_pid_suspended',status(a.session)['pid']==pid and status(a.session)['paused'])
check('world_frozen_without_exit',before==(session.world/'state.json').read_bytes() and trace==(session.world/'motion.jsonl').stat().st_size)
with Session(a.session).connect(Game) as game:
 check('same_pid_resumed',status(a.session)['pid']==pid and not status(a.session)['paused'])
 check('resume_did_not_focus',not game.observe().raw['focused'])
 session.reset(game,dict(id='after_resume'))
 r=game.navigate_to((4,99.5,0),timeout=20);check('movement_after_resume',r.ok,r.to_dict());session.park(game)
suspend(a.session,True)
check('left_parked_and_suspended',status(a.session)['paused'])
a.out.write_text(json.dumps(dict(pid=pid,checks=checks,passed=len(checks),final_status=status(a.session)),indent=2));print('ALL LIFECYCLE CHECKS PASSED',len(checks))
