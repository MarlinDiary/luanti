#!/usr/bin/env python3
"""Silent, isolated real-engine motion comparison. Never changes system volume."""
import argparse,json,math,os,shutil,socket,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--client',type=Path,required=True);p.add_argument('--game',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--audit',type=Path,required=True);p.add_argument('--strict',action='store_true');p.add_argument('--background-cap',type=int,default=60);p.add_argument('--cases',default='straight,nav_a,nav_b,steps');a=p.parse_args()
sys.path.insert(0,str(a.sdk.resolve()))
from luanti_course import Game
a.out.mkdir(parents=True,exist_ok=False);profile=a.out/'profile';(profile/'games').mkdir(parents=True);(profile/'games/voxelibre').symlink_to(a.game.resolve(),target_is_directory=True)
world=profile/'world';mod=world/'worldmods/skills_probe';mod.mkdir(parents=True);shutil.copy2(Path(__file__).with_name('skills_world.lua'),mod/'init.lua');(mod/'mod.conf').write_text('name = skills_probe\noptional_depends = mcl_core,mcl_tools,mcl_crafting_table\n')
(world/'world.mt').write_text('gameid = voxelibre\nbackend = sqlite3\nplayer_backend = sqlite3\nauth_backend = sqlite3\n')
with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
config=f'''video_driver = opengl
course_control = true
sound_volume = 0
sound_volume_unfocused = 0
server_announce = false
bind_address = 127.0.0.1
port = {port}
screen_w = 1100
screen_h = 720
window_maximized = false
fullscreen = false
fps_max = 60
fps_max_unfocused = {a.background_cap}
gui_scaling = .7
hud_scaling = .7
pause_on_lost_focus = false
camera_smoothing = 0
free_move = false
fast_move = false
noclip = false
continuous_forward = false
enable_client_modding = false
csm_restriction_flags = 0
enable_post_processing = false
mobs_spawn = false
mcl_doWeatherCycle = false
mg_name = singlenode
static_spawnpoint = 0,100,0
creative_mode = false
enable_damage = true
course_motion_trace = true
screenshot_path = {a.out.resolve()}
'''
conf=profile/'test.conf';conf.write_text(config)
command=[str(a.client.resolve()),'--config',str(conf.resolve()),'--world',str(world.resolve()),'--go','--logfile','']
overrides={'LUANTI_USER_PATH':str(profile.resolve()),'LUANTI_COURSE_TEST_SILENT':'1','DYLD_INSERT_LIBRARIES':str(a.audit.resolve()),'COURSE_CURSOR_AUDIT_LOG':str((a.out/'cursor.txt').resolve())}
out=(a.out/'stdout.txt').open('w');err=(a.out/'stderr.txt').open('w');proc=subprocess.Popen(command,env=dict(os.environ,**overrides),stdout=out,stderr=err,stdin=subprocess.DEVNULL,start_new_session=True)
record={'command':command,'environment_overrides':overrides,'config':config,'sdk':str(a.sdk.resolve()),'cases':[]};game=None

def auth():return json.loads((world/'state.json').read_text())
def wait(fn,timeout=90):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  if proc.poll() is not None:raise RuntimeError('Game exited '+str(proc.returncode))
  try:
   if fn():return
  except (FileNotFoundError,json.JSONDecodeError):pass
  time.sleep(.1)
 raise TimeoutError('condition timeout')
def motion(case):
 rows=[json.loads(l) for l in (world/'motion.jsonl').read_text().splitlines() if l.strip()]
 rows=[r for r in rows if r['scenario']==case]
 moving=[i for i,r in enumerate(rows) if math.hypot(r['velocity']['x'],r['velocity']['z'])>.3]
 if not moving:raise AssertionError('No movement')
 rows=rows[moving[0]:moving[-1]+1]
 pauses=0;paused=False;duration=rows[-1]['time']-rows[0]['time'];idle=0;distance=0;turns=[]
 for x,y in zip(rows,rows[1:]):
  dt=y['time']-x['time'];speed=math.hypot(x['velocity']['x'],x['velocity']['z'])
  idle+=dt if speed<.3 else 0
  if speed<.3 and not paused:pauses+=1
  paused=speed<.3
  distance+=math.hypot(y['pos']['x']-x['pos']['x'],y['pos']['z']-x['pos']['z'])
  if dt>0:turns.append(abs((y['yaw']-x['yaw']+math.pi)%(2*math.pi)-math.pi)*180/math.pi/dt)
 return dict(samples=len(rows),moving_duration=duration,path_length=distance,average_speed=distance/duration,idle_fraction=idle/duration,stop_starts=pauses,peak_yaw_deg_s=max(turns,default=0))
try:
 wait(lambda:auth()['scenario']=='ready');time.sleep(.5);game=Game.connect(profile=profile,control=True)
 first=game.observe();start=time.monotonic();time.sleep(1);last=game.observe()
 record['frame_pacing']={'focused_before':first.raw['focused'],'focused_after':last.raw['focused'],'fps':(last.frame-first.frame)/(time.monotonic()-start),'configured_background_cap':a.background_cap}
 if a.strict and a.background_cap==10 and not first.raw['focused'] and not last.raw['focused']:
  assert record['frame_pacing']['fps']>35,record['frame_pacing']
 for case in a.cases.split(','):
  game.stop();game.close_inventory();game.chat('/skills reset '+case);wait(lambda:auth()['scenario']==case,10);time.sleep(.8)
  target={'straight':(14,99.5,0),'nav_a':(6,99.5,-5),'nav_b':(-5,99.5,6),'steps':(5,100.5,0)}[case]
  r=game.navigate_to(target,timeout=90,search_radius=28);time.sleep(.4)
  data=dict(scenario=case,result=r.to_dict(),metrics=motion(case),server_position=auth()['pos']);record['cases'].append(data);print(json.dumps(data),flush=True)
  (a.out/(case+'.json')).write_text(json.dumps(data,indent=2));assert r.ok,(case,r.reason)
  error=math.dist(tuple(data['server_position'][k] for k in 'xyz'),target);assert error<.65,(case,error)
  if a.strict:
   m=data['metrics'];assert m['idle_fraction']<.08,(case,m)
   if case=='straight':assert m['stop_starts']==0 and m['average_speed']>3.0,m
  game.screenshot()
 if 'steer' in game.capabilities:
  for parameters in [dict(heading=0,speed=2,jump=False,duration_ms=100),dict(heading=0,speed=.1,jump=False,duration_ms=2000),dict(heading=0,pitch=100,speed=.1,jump=False,duration_ms=100)]:
   try:game._submit('steer',**parameters)
   except Exception as exc:
    from luanti_course import ActionError
    assert isinstance(exc,ActionError),exc
   else:raise AssertionError('invalid steering accepted')
  game._submit('steer',heading=game.observe().yaw,speed=.2,jump=False,duration_ms=100)
  time.sleep(.45);state=game.observe();record['steering_lease_released']=not state.raw['input_active'] and not state.raw['steering_active'];assert record['steering_lease_released']
 lines=(a.out/'cursor.txt').read_text().splitlines();assert 'audit_loaded' in lines and not any(x in ('WARP_REQUESTED','CAPTURE_REQUESTED') for x in lines)
 # Old-client baseline is force-silenced by the audio interposer; new clients
 # skip audio initialization entirely through the test-only environment switch.
 state=game.observe();record['audio_disabled']=state.raw.get('audio_enabled') is False or 'AUDIO_DEVICE_BLOCKED' in lines
 assert record['audio_disabled'],'No evidence of disabled audio device'
 record['cursor_log']=lines;game.chat('/skills finish');game.close();game=None;proc.wait(timeout=10);assert proc.returncode==0
 record['all_passed']=True
except BaseException as exc:
 record['all_passed']=False;record['error']=repr(exc);record['traceback']=traceback.format_exc();print(record['traceback'],flush=True)
finally:
 if game:game.close()
 if proc.poll() is None:
  proc.terminate()
  try:proc.wait(timeout=10)
  except subprocess.TimeoutExpired:proc.kill();proc.wait()
 out.close();err.close();record['exit_status']=proc.returncode;(a.out/'record.json').write_text(json.dumps(record,indent=2));print(json.dumps({'all_passed':record['all_passed'],'exit_status':proc.returncode}),flush=True)
sys.exit(0 if record['all_passed'] else 1)
