#!/usr/bin/env python3
"""Real visible client tests, isolated local server, no original profiles touched."""
import argparse,json,os,shutil,socket,subprocess,sys,time,traceback,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if '--installed-sdk' not in sys.argv:sys.path.insert(0,str(ROOT/'sdk/src'))
import luanti_course
from luanti_course import Game
p=argparse.ArgumentParser();p.add_argument('--client',type=Path,required=True);p.add_argument('--game',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--audit',type=Path,required=True);p.add_argument('--fps',type=int,default=60);p.add_argument('--installed-sdk',action='store_true');p.add_argument('--cases',default='nav_a,nav_b,steps,oak,spruce,stone,wall,cancel');a=p.parse_args()
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
fps_max = {a.fps}
fps_max_unfocused = {a.fps}
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
    if name not in ('mismatch','batch','replan','collect_batch','tool_recovery','organize','full','equip_place','metadata_output'):check(name+'_starts_empty',not any(authoritative()['counts'].values()))
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
        trace_start=len((world/'motion.jsonl').read_text().splitlines())
        record.setdefault('motion_starts',{})[case]=trace_start
        if case in ('nav_a','nav_b','steps'):
            goal={'nav_a':(6,99.5,-5),'nav_b':(-5,99.5,6),'steps':(5,100.5,0)}[case]
            r=game.navigate_to(goal,timeout=90,search_radius=25);result(case,r)
            pos=authoritative()['pos'];check(case+'_server_position',sum((pos[k]-goal[i])**2 for i,k in enumerate('xyz'))<1,{'pos':pos,'goal':goal})
        elif case in ('oak','spruce','far'):
            if case=='oak':
                r=game.find_resource('group:tree',search_radius=18,timeout=30);result('find_tree',r)
                expected=[(-4,y,-3) for y in range(100,103)]+[(5,y,4) for y in range(100,103)]+[(-6,y,6) for y in range(100,103)]
                check('found_coordinates_are_resource_not_player',tuple(r.details['position']) in expected and tuple(r.details['position'])!=tuple(r.details['player_position']))
                check('find_does_not_dig',not any(authoritative()['counts'].values()))
            r=game.craft('wooden_pickaxe',timeout=240,search_radius=18);result(case,r)
            wait(lambda:authoritative()['counts'].get('mcl_tools:pick_wood',0)>=1)
            check(case+'_server_pickaxe_confirmed',True,authoritative())
            game.screenshot()
            if case=='oak':
                r=game.craft('wooden_pickaxe',gather=False,timeout=40);result('additional_pickaxe_existing_materials',r)
                wait(lambda:authoritative()['counts'].get('mcl_tools:pick_wood',0)==2)
                check('additional_count_server_confirmed',True)
                r=game.collect('mcl_core:cobble',count=3,search_radius=18,timeout=90);result('collect_cobble_with_new_pickaxe',r)
                wait(lambda:authoritative()['counts'].get('mcl_core:cobble',0)>=3)
                check('cobble_server_inventory_confirmed',True,authoritative()['counts'])

        elif case=='batch':
            requests=[];original=game._request
            def request(op,**kw):
                requests.append((op,kw));return original(op,**kw)
            game._request=request
            try:r=game.craft('mcl_core:stick',count=16,gather=False,timeout=40)
            finally:game._request=original
            result('batch_craft',r)
            check('batch_one_craft_submission',sum(op=='craft' for op,_ in requests)==1,requests)
            check('batch_four_recipe_repetitions',next(k['count'] for op,k in requests if op=='craft')==4)
            check('batch_inventory_increment',game.observe().inventory['main'].count('mcl_core:stick')==16)
        elif case=='metadata_output':
            original_item=game.observe().inventory['main'].items[1]
            result(case,game.craft('mcl_core:stick',count=16,gather=False,timeout=30))
            state=game.observe()
            check('labeled_output_stack_preserved',state.inventory['main'].count('mcl_core:stick')==17 and any(i==original_item for i in state.inventory['main'].items))
        elif case=='replan':
            r=game.craft('crafting_table',gather=False,timeout=60);result(case,r)
            check('changed_materials_replanned',any(e['event']=='craft_replan' for e in r.trace),r.trace)
            check('replan_did_not_duplicate_output',game.observe().inventory['main'].count('mcl_crafting_table:crafting_table')==1)
        elif case=='collect_batch':
            r=game.collect('mcl_core:cobble',count=3,timeout=40);result(case,r)
            check('multiple_blocks_before_pickup',any(e['event']=='harvest_batch' and e['nodes']>=2 for e in r.trace),r.trace)
            check('actual_drop_tracking_used',any(e['event']=='pickup_track' and isinstance(e['entity'],int) for e in r.trace))
        elif case=='pickup_shift':
            wait(lambda:len(game.observe().item_entities)>0)
            r=game.collect('mcl_core:tree',count=3,timeout=30);result(case,r)
            check('pick_existing_drop_without_dig',not any(e['event']=='node_changed' for e in r.trace))
        elif case=='tool_recovery':
            r=game.collect('mcl_core:cobble',count=1,timeout=70);result(case,r)
            check('automatically_crafted_tool',any(e['event']=='recover_tool' for e in r.trace))
            check('real_cobble_after_tool_recovery',game.observe().inventory['main'].count('mcl_core:cobble')>=1)
        elif case=='organize':
            before=game.observe();special=[i for i in before.inventory['main'].items if 'Keep my label' in i.stack_key]
            r=game.organize_inventory(timeout=60);result(case,r)
            state=game.observe()
            check('organize_frees_slots',sum(not i.count for i in state.inventory['main'].items)>=30)
            check('organize_preserves_count',state.inventory['main'].count('mcl_core:wood')==36)
            check('organize_preserves_metadata',len(special)==1 and any(i==special[0] for i in state.inventory['main'].items))
        elif case=='full':
            r=game.craft('mcl_core:stick',count=4,gather=False,timeout=70);result(case,r,'blocked')
            check('full_never_discards',r.reason=='inventory_full' and sum(x.count('mcl_core:wood') for k,x in game.observe().inventory.items() if k in ('main','craft'))==36*64)
        elif case=='equip_place':
            result('equip_named_tool',game.equip('wooden_pickaxe'))
            check('named_tool_in_hand',game.observe().inventory['main'].items[game.observe().raw['wield']].name=='mcl_tools:pick_wood')
            result('equip_armor',game.equip('mcl_armor:helmet_iron',destination='armor'))
            result('replace_armor_preserves_old',game.equip('mcl_armor:helmet_gold',destination='armor'))
            check('old_armor_not_discarded',game.observe().inventory['main'].count('mcl_armor:helmet_iron')==1)
            result('equip_offhand',game.equip('mcl_core:cobble',destination='offhand'))
            result('place_named_block',game.place_block('mcl_core:cobble',(2,100,0)))
            check('placed_count_confirmed',game.observe().inventory['main'].count('mcl_core:cobble')==1)
            game.screenshot()
            result('occupied_placement_rejected',game.place_block('mcl_core:cobble',(2,100,0)),'blocked')
        elif case in ('gap','ladder','swim'):
            goal={'gap':(5,99.5,0),'ladder':(2,103.5,0),'swim':(10,99.5,0)}[case]
            flags={'gap':{'allow_jump_gaps':True},'ladder':{},'swim':{'allow_swim':True}}[case]
            r=game.navigate_to(goal,search_radius=15,timeout=45,**flags);result(case,r)
            state=game.observe();check(case+'_arrival_and_no_damage',sum((state.position[i]-goal[i])**2 for i in range(3))<.8 and state.hp==20,dict(position=state.position,hp=state.hp))
            if case=='swim':
                rows=[json.loads(l) for l in (world/'motion.jsonl').read_text().splitlines()[trace_start:]]
                ys=[v['pos']['y'] for v in rows if v['scenario']=='swim' and 3.5<=v['pos']['x']<=6.5]
                check('swim_no_replans',not any(e['event']=='replan' for e in r.trace),r.trace)
                # Interior-only steady-state gate; bank entry/exit use arrival/damage gates.
                check('swim_no_large_bobbing',bool(ys) and max(ys)-min(ys)<.20,dict(min_y=min(ys,default=None),max_y=max(ys,default=None),samples=len(ys)))
                xs=[v['pos']['x'] for v in rows if v['scenario']=='swim' and 3.5<=v['pos']['x']<=6.5]
                check('swim_no_horizontal_reversal',all(b>=a-.04 for a,b in zip(xs,xs[1:])))
                middle=[v for v in rows if v['scenario']=='swim' and 3.5<=v['pos']['x']<=6.5]
                peak=max(abs(v['velocity']['y']) for v in middle)
                check('swim_no_vertical_spikes',peak<1.2,dict(peak_vertical_speed=peak))
                check('swim_no_mid_stop',all((v['velocity']['x']**2+v['velocity']['z']**2)**.5>.3 for v in middle))
            if case=='ladder':result('ladder_down',game.navigate_to((2,99.5,0),timeout=30))
        elif case in ('slabs','stairs','stairs_rotated','snow'):
            expected={'slabs':100.0,'stairs':100.5,'stairs_rotated':100.5,'snow':99.625}[case]
            goal=(6,expected,0)
            result(case,game.navigate_to(goal,search_radius=15,timeout=45))
            check(case+'_on_actual_surface',abs(game.observe().position[1]-expected)<.15,game.observe().position)
            result(case+'_down',game.navigate_to((0,99.5,0),search_radius=15,timeout=45))
            check(case+'_no_damage',game.observe().hp==20)
        elif case=='low_ceiling':
            result(case,game.navigate_to((5,99.5,0),search_radius=8,timeout=20),'blocked')
            check('low_ceiling_no_damage',game.observe().hp==20)
        elif case in ('swim_deep','swim_turn'):
            goal=(16,99.5,0)
            r=game.navigate_to(goal,allow_swim=True,search_radius=25,timeout=90);result(case,r)
            check(case+'_no_damage',game.observe().hp==20)
            check(case+'_no_replans',not any(e['event']=='replan' for e in r.trace),r.trace)
            rows=[json.loads(l) for l in (world/'motion.jsonl').read_text().splitlines()[trace_start:]]
            pool=[v for v in rows if v['scenario']==case and 3.5<=v['pos']['x']<=12 and (case!='swim_turn' or v['pos']['z']>2.6)]
            ys=[v['pos']['y'] for v in pool]
            check(case+'_steady_height',bool(ys) and max(ys)-min(ys)<.20,dict(min_y=min(ys,default=None),max_y=max(ys,default=None),samples=len(ys)))
            check(case+'_no_vertical_spikes',bool(pool) and max(abs(v['velocity']['y']) for v in pool)<1.2)
        elif case=='dive':
            result('dive_down',game.navigate_to((4,97.5,0),allow_swim=True,allow_dive=True,timeout=12,search_radius=10))
            check('dive_reached_depth',abs(game.observe().position[1]-97.5)<.5)
            game.screenshot()
            result('dive_sideways',game.navigate_to((6,97.5,1),allow_swim=True,allow_dive=True,timeout=12,search_radius=10))
            result('dive_resurface',game.navigate_to((6,99.5,1),allow_swim=True,allow_dive=True,timeout=12,search_radius=10))
            check('dive_round_trip_healthy',game.observe().hp==20 and game.observe().raw['breath']>=5)
            with game.motion() as motion:
                motion.steer(0,speed=0,swim_y=99.05,lease=.1)
                time.sleep(.3)
                state=game.observe()
                check('swim_lease_expires',not state.raw['steering_active'] and not state.raw['swim_height_active'] and not state.raw['input_active'])
            check('swim_scope_exit_releases',not game.observe().raw['input_active'])
        elif case=='motion':
            game.look(90);check('smooth_look_arrived',abs((game.observe().yaw-90+180)%360-180)<.6)
            requests=[];original=game._request
            def request(op,**kw):requests.append((op,kw));return original(op,**kw)
            game._request=request
            try:
                with game.motion() as motion:
                    for _ in range(10):motion.move(seconds=.1)
                    check('no_stop_between_short_moves',not any(op=='stop' for op,_ in requests))
            finally:game._request=original
            check('motion_exit_releases',not game.observe().raw['input_active'])
            rows=[json.loads(l) for l in (world/'motion.jsonl').read_text().splitlines()[trace_start:]]
            speeds=[(v['velocity']['x']**2+v['velocity']['z']**2)**.5 for v in rows if v['scenario']=='motion']
            moving=[i for i,v in enumerate(speeds) if v>.3]
            check('short_loop_no_physical_stop',bool(moving) and all(v>.3 for v in speeds[moving[0]:moving[-1]+1]),dict(samples=len(speeds)))
            with game.motion() as motion:
                motion.steer(90,speed=.3,lease=.1);time.sleep(.3)
                check('stalled_loop_lease_expires',not game.observe().raw['steering_active'])
            try:
                with game.motion() as motion:motion.steer(0);raise ValueError('student loop')
            except ValueError:pass
            check('student_exception_releases',not game.observe().raw['input_active'])
        elif case=='geometry':
            from luanti_course.navigation import World
            state=game.observe(6);w=World();w.update(state)
            check('slab_geometry_not_full_cube',not state.raw['node_defs']['mcl_stairs:slab_stone']['full_cube'])
            check('slab_and_lava_not_walkable_support',not w.standable((2,101,0)) and not w.standable((3,101,0)))
        elif case=='missing':
            r=game.craft('wooden_pickaxe',gather=False,timeout=15);result(case,r,'blocked');check('missing_materials_explicit',r.reason=='missing_materials')
        elif case=='mismatch':
            r=game.craft('mcl_core:stick',gather=False,timeout=20);result(case,r,'blocked');check('server_preview_authoritative',r.reason=='recipe_preview_mismatch')
            check('mismatch_materials_preserved_in_grid',game.observe().inventory['craft'].count('mcl_core:wood')==2)
        elif case=='deadline':
            r=game.navigate_to((12,99.5,0),timeout=.1);result(case,r,'timeout');check('deadline_releases_input',not game.observe().raw['input_active'])
        elif case=='stone':
            r=game.collect('mcl_core:cobble',timeout=25,search_radius=8);result(case,r,'blocked');check('tool_requirement',r.reason=='suitable_tool_required')
        elif case=='wall':
            r=game.navigate_to((6,99.5,0),timeout=20,search_radius=8);result(case,r,'blocked');check('unreachable_bounded',r.reason=='no_path')
        elif case=='cancel':
            timer=threading.Timer(.8,game.stop);timer.start()
            try:r=game.find_resource('mcl_core:diamond',timeout=40,search_radius=12)
            finally:timer.cancel();timer.join()
            result(case,r,'cancelled');check('cancel_releases_input',not game.observe().raw['input_active'])
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
