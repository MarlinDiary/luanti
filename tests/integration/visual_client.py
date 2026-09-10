#!/usr/bin/env python3
"""Visible, isolated live-engine acceptance checks. No course server is contacted."""
import argparse,json,os,shutil,socket,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'sdk/src'))
from luanti_course import Game,ActionError
p=argparse.ArgumentParser();p.add_argument('--client',type=Path,required=True);p.add_argument('--game',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--hold',type=int,default=0);p.add_argument('--cursor-audit',type=Path);a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=False);profile=a.out/'profile';profile.mkdir();(profile/'games').mkdir();(profile/'games/voxelibre').symlink_to(a.game.resolve(),target_is_directory=True)
world=profile/'world';mod=world/'worldmods/control_probe';mod.mkdir(parents=True)
for f in ['init.lua','mod.conf']:shutil.copy2(Path(__file__).parent/f,mod/f)
(world/'world.mt').write_text('gameid = voxelibre\nbackend = sqlite3\nplayer_backend = sqlite3\nauth_backend = sqlite3\nload_mod_control_probe = true\n')
with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
config=f'''video_driver = opengl
course_control = true
sound_volume = 0
sound_volume_unfocused = 0
enable_server = false
server_announce = false
bind_address = 127.0.0.1
port = {port}
screen_w = 1100
screen_h = 720
window_maximized = false
fullscreen = false
fps_max = 30
fps_max_unfocused = 20
gui_scaling = 0.7
hud_scaling = 0.7
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
conf=profile/'minetest.conf';conf.write_text(config)
command=[str(a.client.resolve()),'--config',str(conf.resolve()),'--world',str(world.resolve()),'--go','--logfile',str((a.out/'debug.txt').resolve())]
stdout=(a.out/'stdout.txt').open('w');stderr=(a.out/'stderr.txt').open('w')
env=dict(os.environ,LUANTI_COURSE_TEST_SILENT="1",LUANTI_USER_PATH=str(profile.resolve()))
if a.cursor_audit:env.update(DYLD_INSERT_LIBRARIES=str(a.cursor_audit.resolve()),COURSE_CURSOR_AUDIT_LOG=str((a.out/'cursor-audit.txt').resolve()))
proc=subprocess.Popen(command,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
record={'command':command,'environment_overrides':{'LUANTI_USER_PATH':str(profile.resolve())},'config':config,'checks':[],'transactions':[]};game=None

def check(name,condition,details=None):
    item={'name':name,'pass':bool(condition),'details':details};record['checks'].append(item);print(json.dumps(item),flush=True)
    if not condition:raise AssertionError(name)
def until(fn,timeout=10):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            value=fn()
            if value:return value
        except (FileNotFoundError,json.JSONDecodeError):pass
        if proc.poll() is not None:raise RuntimeError('Game exited: '+str(proc.returncode))
        time.sleep(.15)
    raise TimeoutError('Condition not observed')
def auth():return json.loads((world/'authoritative.json').read_text())
def count(s,name,listname='main'):return sum(i['count'] for i in s['inventory'][listname]['items'] if i['name']==name)
def req(op,**params):
    reply=game._request(op,**params);record['transactions'].append({'request':dict(op=op,**params),'response':reply});return reply
def reset(name):
    game.stop();game.close_inventory();game.chat('/probe reset '+name)
    until(lambda:auth()['scenario']==name);time.sleep(.8);game.look(0,0)
    return game.observe()
def move(fl,fs,tl,ts,n=1):game.move_items(fl,fs,tl,ts,n);time.sleep(.35)
try:
    until(lambda:auth()['scenario']=='ready',60);time.sleep(1)
    game=Game.connect(profile=profile)
    state=game.observe();check('read_only_connection_starts_observe',state.control=='observe')
    check('test_audio_device_disabled',state.raw['audio_enabled'] is False)
    check('watching_mouse_visible_and_human_gameplay_blocked',state.raw['cursor_visible'] and not state.raw['human_input_enabled'])
    check('session_file_is_private',os.name=='nt' or (game.endpoint.stat().st_mode & 0o777)==0o600)
    game.take_control();state=game.observe();check('explicit_take_control',state.control=='agent')
    check('agent_mouse_visible_and_human_input_blocked',state.raw['cursor_visible'] and not state.raw['human_input_enabled'])
    check('player_alive_with_damage_enabled',game.observe().hp>0 and not game.observe().dead)
    for name,op,args in [('input_duration_limit','input',{'keys':['forward'],'duration_ms':9999}),('invalid_slot','move_items',{'from_list':'main','from_slot':-1,'to_list':'craft','to_slot':0,'count':1})]:
        try:req(op,**args);rejected=False
        except ActionError:rejected=True
        check(name,rejected)
    start=reset('movement');after=game.move(seconds=.5);time.sleep(.5);server=until(lambda: (x:=auth())['position']['z']>.5 and x)
    check('normal_movement_server_confirmed',after.position[2]-start.position[2]>.5,{'before':start.position,'after':after.position,'server':server['position'],'focused':after.raw['focused']})
    t=game.observe();time.sleep(.5);u=game.observe();check('normal_stop',abs(t.position[2]-u.position[2])<.1)
    req('input',keys=['left'],duration_ms=300);time.sleep(1);t=game.observe();time.sleep(.5);u=game.observe();check('native_lease_expires',not u.raw['input_active'] and abs(t.position[0]-u.position[0])<.1)
    reset('dig');game.wield(4);game.look_at((0,102,3));time.sleep(.4)
    check('crosshair_target',game.observe().pointed_node==(0,102,3))
    game.dig(1.7);until(lambda:auth()['dig_node']=='air');check('dig_server_confirmed',True)
    game.look(0,0);game.move(seconds=.8);until(lambda:count(auth(),'mcl_core:dirt')>=1);check('dug_item_collected',True)
    state=game.observe(radius=2);check('bounded_node_observations',len(state.raw['nodes'])==125 and any(n['known'] for n in state.raw['nodes']))
    reset('craft2');game.open_inventory();time.sleep(.5)
    for i in range(4):move('main',0,'craft',i)
    revision=game.observe().inventory_revision;game.craft_grid();until(lambda:count(auth(),'mcl_crafting_table:crafting_table','craftresult')==1)
    check('craft_2x2_materials_and_result',count(auth(),'mcl_core:wood')==8 and count(auth(),'mcl_core:wood','craft')==0)
    check('server_inventory_revision_advances',game.observe().inventory_revision>revision)
    move('craftresult',0,'main',8);game.close_inventory();time.sleep(.4)
    reset('craft3');game.wield(4);game.look_at((2,100,3));time.sleep(.4);game.use()
    state=until(lambda:(s:=game.observe()).inventory['craft'].width==3 and s)
    check('real_workbench_opens_3x3',state.inventory['craft'].size==9)
    form=state.form;check('current_form_has_visible_inventory_lists',bool(form['id']) and bool(form['lists']))
    for i in [0,1,2]:move('main',0,'craft',i)
    for i in [4,7]:move('main',1,'craft',i)
    game.craft_grid();until(lambda:count(auth(),'mcl_tools:pick_wood','craftresult')==1)
    check('craft_3x3_materials_and_result',count(auth(),'mcl_core:wood')==9 and count(auth(),'mcl_core:stick')==2)
    move('craftresult',0,'main',8);game.close_inventory();until(lambda:game.observe().inventory['craft'].width==2);check('close_workbench_restores_2x2',True)
    try:game.move_items('main',0,'main',9,from_inventory=form['lists'][0]['location'],form_id=form['id']);rejected=False
    except ActionError:rejected=True
    check('stale_form_rejected',rejected)
    game.wield(8);until(lambda:auth()['wield_name']=='mcl_tools:pick_wood');check('equip_crafted_tool',True)
    move('main',2,'armor',1);until(lambda:auth()['armor_points']>0);check('armor_effect_callback',auth()['armor_points']==2)
    before=game.observe();time.sleep(2);after=game.observe();check('rendering_continues_during_script_wait',after.frame-before.frame>=10,{'frames':after.frame-before.frame,'focused':after.raw['focused']})
    game.screenshot();until(lambda:list(a.out.glob('*.png')));check('screenshot_created',True)
    # Human-readable screenshot inspection can happen while this process is held.
    if a.hold:print('VISUAL_INSPECTION_READY',flush=True);time.sleep(a.hold)
    old_epoch=game.observe().control_epoch;game.release_control();state=game.observe();check('release_returns_to_observe',state.control=='observe')
    try:req('input',keys=['forward'],duration_ms=100,control_epoch=old_epoch);rejected=False
    except ActionError:rejected=True
    check('old_control_epoch_rejected',rejected)
    game.close();time.sleep(.2);game=Game.connect(profile=profile,control=True);check('second_script_reconnects_same_game',game.observe().control=='agent')
    req('input',keys=['left'],duration_ms=3000)
    # Simulate a process disappearing without sending stop/release.
    game._socket.close();game._closed=True;time.sleep(.7);p1=auth()['position'];time.sleep(.5);p2=auth()['position']
    check('lost_controller_releases_input',abs(p2['x']-p1['x'])<.1,{'before':p1,'after':p2})
    game=Game.connect(profile=profile);check('disconnect_restores_observe_mode',game.observe().control=='observe')
    state=game.observe();check('disconnect_leaves_cursor_free_and_human_gameplay_blocked',state.raw['cursor_visible'] and not state.raw['human_input_enabled'])
    if a.cursor_audit:
        lines=(a.out/'cursor-audit.txt').read_text().splitlines()
        check('cursor_auditor_loaded', 'audit_loaded' in lines)
        check('no_actual_SDL_capture_or_warp_requests',not any(x in ('CAPTURE_REQUESTED','WARP_REQUESTED') for x in lines),{'capture_requests':lines.count('CAPTURE_REQUESTED'),'warp_requests':lines.count('WARP_REQUESTED')})
    game.take_control();game.chat('/probe finish');game.close();game=None
    proc.wait(timeout=10)
    check('clean_client_shutdown',proc.returncode==0,proc.returncode)
except BaseException as exc:
    record['error']=repr(exc);record['traceback']=traceback.format_exc();print(record['traceback'],flush=True)
finally:
    if game:
        try:game.close()
        except Exception:pass
    if proc.poll() is None:
        proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
    stdout.close();stderr.close();record['game_exit_status']=proc.returncode
    record['all_checks_passed']=not record.get('error') and all(c['pass'] for c in record['checks'])
    (a.out/'record.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'all_checks_passed':record['all_checks_passed'],'checks':len(record['checks']),'game_exit_status':proc.returncode,'record':str(a.out/'record.json')}),flush=True)
sys.exit(0 if record['all_checks_passed'] else 1)
