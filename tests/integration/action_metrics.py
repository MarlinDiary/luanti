#!/usr/bin/env python3
"""Real visible client tests, isolated local server, no original profiles touched."""
import argparse,json,os,shutil,socket,subprocess,sys,time,traceback,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,sys.argv[sys.argv.index('--sdk')+1])
import luanti_course
from luanti_course import Game
p=argparse.ArgumentParser();p.add_argument('--client',type=Path,required=True);p.add_argument('--game',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--audit',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);p.add_argument('--cases',default='nav_a,nav_b,steps,oak,spruce,stone,wall,cancel');a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=False);profile=a.out/'profile';(profile/'games').mkdir(parents=True);(profile/'games/voxelibre').symlink_to(a.game.resolve(),target_is_directory=True)
world=profile/'world';mod=world/'worldmods/skills_probe';mod.mkdir(parents=True);shutil.copy2(Path(__file__).with_name('skills_world.lua'),mod/'init.lua');(mod/'mod.conf').write_text('name = skills_probe\noptional_depends = mcl_core, mcl_tools, mcl_crafting_table\n')
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
fps_max = 30
fps_max_unfocused = 30
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
screenshot_path = {a.out.resolve()}
'''
conf=profile/'test.conf';conf.write_text(config)
command=[str(a.client.resolve()),'--config',str(conf.resolve()),'--world',str(world.resolve()),'--go','--logfile','']
env=dict(os.environ,LUANTI_COURSE_TEST_SILENT="1",LUANTI_USER_PATH=str(profile.resolve()),DYLD_INSERT_LIBRARIES=str(a.audit.resolve()),COURSE_CURSOR_AUDIT_LOG=str((a.out/'cursor.txt').resolve()))
out=(a.out/'stdout.txt').open('w');err=(a.out/'stderr.txt').open('w');proc=subprocess.Popen(command,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
record={'command':command,'config':config,'sdk_path':luanti_course.__file__,'sdk_version':luanti_course.__version__,'cases':[]};game=None

def authoritative():return json.loads((world/'state.json').read_text())
def wait(fn,timeout=10):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if proc.poll() is not None:raise RuntimeError('Client exited '+str(proc.returncode))
        try:
            v=fn()
            if v:return v
        except (FileNotFoundError,json.JSONDecodeError):pass
        time.sleep(.1)
    raise TimeoutError('Test condition not observed')
def check(name,condition,details=None):
    value=dict(name=name,pass_=bool(condition),details=details);record['cases'].append(value);print(json.dumps(value),flush=True)
    (a.out/'record.partial.json').write_text(json.dumps(record,indent=2))
    if not condition:raise AssertionError(name)
def reset(name):
    game.stop();game.close_inventory();game.chat('/skills reset '+name);wait(lambda:authoritative()['scenario']==name);time.sleep(.8)
    if name not in ('mismatch','batch','replan','collect_batch','tool_recovery','organize','full','equip_place'):check(name+'_starts_empty',not any(authoritative()['counts'].values()))
def result(name,r,expected='success'):
    (a.out/(name+'.json')).write_text(json.dumps(r.to_dict(),indent=2))
    check(name,r.status==expected,dict(status=r.status,reason=r.reason,details=r.details,elapsed=r.elapsed))
try:
    wait(lambda:authoritative()['scenario']=='ready',90);time.sleep(.5)
    game=Game.connect(profile=profile,control=True)
    check('full_radius_reply_with_geometry',bool(game.observe(6).raw['node_defs']))
    check('test_audio_device_disabled',game.observe().raw['audio_enabled'] is False)
    for case in a.cases.split(','):
        reset(case)
        requests=[];original=game._request
        def request(op,**kw):requests.append((op,kw));return original(op,**kw)
        game._request=request
        started=time.monotonic()
        try:
            if case=='batch':r=game.craft('mcl_core:stick',count=16,gather=False,timeout=60)
            elif case=='collect_batch':r=game.collect('mcl_core:cobble',count=3,timeout=90)
            else:raise ValueError(case)
        finally:game._request=original
        result(case,r)
        metrics=dict(scenario=case,elapsed=time.monotonic()-started,requests={op:sum(x==op for x,_ in requests) for op,_ in requests},trace=r.to_dict()['trace'])
        (a.out/(case+'-metrics.json')).write_text(json.dumps(metrics,indent=2));print(json.dumps(metrics),flush=True)
    lines=(a.out/'cursor.txt').read_text().splitlines();check('no_cursor_capture_or_warp','audit_loaded' in lines and not any(x in ('CAPTURE_REQUESTED','WARP_REQUESTED') for x in lines),lines)
    game.chat('/skills finish');game.close();game=None;proc.wait(timeout=10)
    check('clean_client_shutdown',proc.returncode==0,proc.returncode)
    record['all_passed']=True
except BaseException as e:
    record['all_passed']=False;record['error']=repr(e);record['traceback']=traceback.format_exc();print(record['traceback'],flush=True)
finally:
    if game:game.close()
    if proc.poll() is None:
        proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
    out.close();err.close();record['exit_status']=proc.returncode;(a.out/'record.json').write_text(json.dumps(record,indent=2));print(json.dumps({'all_passed':record['all_passed'],'exit_status':proc.returncode,'record':str(a.out/'record.json')}),flush=True)
sys.exit(0 if record['all_passed'] else 1)
