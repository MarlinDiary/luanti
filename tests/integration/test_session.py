#!/usr/bin/env python3
"""Persistent visible test client. SDK/scenario iterations never restart the GUI."""
import argparse,hashlib,json,os,shutil,socket,subprocess,sys,time,signal,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def alive(pid):
 try:os.kill(pid,0);return True
 except ProcessLookupError:return False

def status(directory):
 meta=json.loads((directory/'session.json').read_text());meta['alive']=alive(meta['pid'])
 if meta['alive']:
  row=subprocess.check_output(['ps','-p',str(meta['pid']),'-o','stat=','-o','command='],text=True).strip()
  if meta['command'][0] not in row or meta['profile'] not in row:raise RuntimeError('PID no longer belongs to this isolated test session')
  meta['paused']=row.split()[0].startswith('T')
 return meta

def start(a):
 directory=a.session.resolve()
 if (directory/'session.json').exists():
  m=status(directory)
  if m['alive']:
   if m['client_sha256']!=digest(a.client):raise SystemExit('Native binary changed: explicitly stop and restart this session once.')
   print(json.dumps(m,indent=2));return
  raise SystemExit('Previous session ended; use a fresh session directory (never auto-restart).')
 directory.mkdir(parents=True,exist_ok=False);profile=directory/'profile';(profile/'games').mkdir(parents=True)
 (profile/'games/voxelibre').symlink_to(a.game.resolve(),target_is_directory=True)
 world=profile/'world';mod=world/'worldmods/persistent_fixture';mod.mkdir(parents=True)
 shutil.copy2(Path(__file__).with_name('session_world.lua'),mod/'init.lua')
 shutil.copy2(Path(__file__).with_name('survival_fixture.lua'),mod/'survival_fixture.lua')
 (mod/'mod.conf').write_text('name = persistent_fixture\noptional_depends = mcl_core,mcl_tools,mcl_doors,mcl_fences\n')
 (world/'world.mt').write_text('gameid = voxelibre\nbackend = sqlite3\nplayer_backend = sqlite3\nauth_backend = sqlite3\n')
 with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 conf=profile/'test.conf';conf.write_text(f'''video_driver = opengl
course_control = true
course_test_fixture = true
sound_volume = 0
sound_volume_unfocused = 0
server_announce = false
bind_address = 127.0.0.1
port = {port}
screen_w = 960
screen_h = 640
window_maximized = false
fullscreen = false
fps_max = 60
fps_max_unfocused = 60
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
screenshot_path = {directory}
''')
 cmd=[str(a.client.resolve()),'--config',str(conf),'--world',str(world),'--go','--logfile','']
 env=dict(os.environ,LUANTI_USER_PATH=str(profile),LUANTI_COURSE_TEST_SILENT='1',SDL_MAC_BACKGROUND_APP='1',SDL_WINDOW_NO_ACTIVATION_WHEN_SHOWN='1',COURSE_TEST_BACKGROUND='1',DYLD_INSERT_LIBRARIES=str(a.audit.resolve())+':'+str(a.focus_guard.resolve()),COURSE_CURSOR_AUDIT_LOG=str(directory/'cursor.txt'),COURSE_FOCUS_AUDIT_LOG=str(directory/'focus-guard.txt'))
 with (directory/'stdout.txt').open('w') as out,(directory/'stderr.txt').open('w') as err:
  process=subprocess.Popen(cmd,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
 meta=dict(pid=process.pid,started=time.time(),client_sha256=digest(a.client),command=cmd,profile=str(profile),world=str(world),config_sha256=digest(conf),start_count=1,environment_overrides={k:env[k] for k in ('LUANTI_COURSE_TEST_SILENT','SDL_MAC_BACKGROUND_APP','SDL_WINDOW_NO_ACTIVATION_WHEN_SHOWN','COURSE_TEST_BACKGROUND','DYLD_INSERT_LIBRARIES')})
 (directory/'session.json').write_text(json.dumps(meta,indent=2))
 end=time.monotonic()+90
 while time.monotonic()<end:
  if process.poll() is not None:raise SystemExit('Test client exited: '+str(process.returncode)+'; inspect '+str(directory/'stderr.txt'))
  try:
   if json.loads((world/'state.json').read_text())['scenario']=='ready':print(json.dumps(meta,indent=2));return
  except (FileNotFoundError,json.JSONDecodeError):pass
  time.sleep(.1)
 raise SystemExit('Fixture startup timed out; session left intact for diagnosis.')

def suspend(directory,paused):
 if not hasattr(signal,'SIGSTOP'):raise RuntimeError('Process suspension is POSIX-only; keep the Windows session idle instead.')
 m=status(directory)
 if not m['alive']:raise RuntimeError('Session ended; never auto-restart')
 os.kill(m['pid'],signal.SIGSTOP if paused else signal.SIGCONT)
 with (directory/'lifecycle.jsonl').open('a') as f:f.write(json.dumps(dict(time=time.time(),pid=m['pid'],event='pause' if paused else 'resume'))+'\n')
 return m['pid']

def validate_spec(spec):
 if not isinstance(spec,dict) or not isinstance(spec.get('id'),str) or re.fullmatch(r'[A-Za-z0-9_-]+',spec['id']) is None:raise ValueError('invalid fixture scenario ID')
 # Reject invalid fixture geometry before sending a chat command to Lua.
 # An assertion inside the server callback otherwise ends the test session.
 for fill in spec.get('fill',()):
  lo,hi=fill['min'],fill['max']
  if len(lo)!=3 or len(hi)!=3 or any(type(v) is not int for v in (*lo,*hi)):raise ValueError('fixture bounds must be integer triples')
  if any(lo[i]>hi[i] for i in range(3)) or lo[0]<-32 or hi[0]>32 or lo[2]<-32 or hi[2]>32 or lo[1]<88 or hi[1]>118:raise ValueError('fixture fill outside isolated world bounds')
 for n in spec.get('nodes',()):
  if len(n)<4 or any(type(v) is not int for v in n[:3]) or not (-32<=n[0]<=32 and 88<=n[1]<=118 and -32<=n[2]<=32):raise ValueError('fixture node outside isolated world bounds')

class Session:
 def __init__(self,directory):
  self.directory=Path(directory).resolve();self.meta=status(self.directory)
  if not self.meta['alive']:raise RuntimeError('Test client is not running; no automatic relaunch.')
  self.profile=Path(self.meta['profile']);self.world=Path(self.meta['world'])
 def state(self):return json.loads((self.world/'state.json').read_text())
 def connect(self,Game):
  if self.meta.get('paused'):suspend(self.directory,False)
  game=Game.connect(profile=self.profile)
  try:
   if game.observe().dead:
    game.respawn();end=time.monotonic()+8
    while game.observe().dead:
     if time.monotonic()>end:raise TimeoutError('Fixture respawn not confirmed')
     time.sleep(.05)
    time.sleep(.15)
   game.take_control();return game
  except BaseException:game.close();raise
 def park(self,game):
  self.reset(game,dict(id='idle',fps=10,trace=False,physics={'speed_walk':1}))
  game.stop()
 def reset(self,game,spec):
  validate_spec(spec)
  old=self.state()['generation'];request=dict(spec,id=spec['id']+'_'+str(time.time_ns()))
  game.stop()
  if game.observe().dead:
   game.respawn();time.sleep(.3);game.take_control()
  if game.observe().control!='agent' or game._epoch is None:game.take_control()
  game.close_inventory()
  tmp=self.world/'request.tmp';tmp.write_text(json.dumps(request));tmp.replace(self.world/'request.json')
  game.chat('/fixture reset');end=time.monotonic()+20;client_synced=False
  while time.monotonic()<end:
   try:
    failure=self.world/'reset-error.json'
    if failure.exists():
     error=json.loads(failure.read_text())
     if error.get('id')==request['id']:raise ValueError('fixture rejected scene: '+error['error'])
    state=self.state()
    if state['generation']>old and state['scenario']==request['id']:
     # Wait for position replication, not an arbitrary long sinking delay.
     spawn=spec.get('spawn',(0,99.51,0));snapshot=game.observe()
     client_synced=client_synced or sum((snapshot.position[i]-spawn[i])**2 for i in range(3))<.5
     # Remember the first replicated teleport. Water keeps moving vertically
     # while server/client packets arrive; requiring both to stay at spawn
     # height can wait forever and drown the idle test character.
     horizontal=sum((state['pos'][axis]-snapshot.position[i])**2 for i,axis in ((0,'x'),(2,'z')))
     if client_synced and state['sequence']>=8 and horizontal<.1:
      return state['generation']
   except (FileNotFoundError,json.JSONDecodeError):pass
   time.sleep(.03)
  raise TimeoutError('Fixture reset not replicated')
 def rows(self,generation):
  return [r for line in (self.world/'motion.jsonl').read_text().splitlines() if line.strip() for r in [json.loads(line)] if r['generation']==generation]

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('start','status','stop','park','pause','resume'));p.add_argument('--session',type=Path,required=True);p.add_argument('--client',type=Path);p.add_argument('--game',type=Path);p.add_argument('--audit',type=Path);p.add_argument('--focus-guard',type=Path);a=p.parse_args()
 if a.operation=='start':
  if not all((a.client,a.game,a.audit,a.focus_guard)):p.error('start requires client/game/audit/focus-guard')
  start(a)
 elif a.operation in ('pause','resume'):print(a.operation,'PID',suspend(a.session,a.operation=='pause'))
 elif a.operation=='status':print(json.dumps(status(a.session),indent=2))
 else:
  sys.path.insert(0,str(ROOT/'sdk/src'));from luanti_course import Game
  session=Session(a.session)
  with session.connect(Game) as game:
   if a.operation=='park':
    session.park(game);game.release_control();s=game.observe()
    print(json.dumps(dict(pid=session.meta['pid'],parked=True,control=s.control,input_active=s.raw.get('input_active'),focused=s.raw.get('focused'),audio_enabled=s.raw.get('audio_enabled'))))
   else:game.chat('/fixture finish')
  if a.operation=='stop':print('Explicit shutdown requested; no relaunch.')
