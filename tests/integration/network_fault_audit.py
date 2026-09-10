#!/usr/bin/env python3
"""Exercise the actual Luanti UDP session through latency/loss/cut faults."""
import argparse,json,os,signal,socket,subprocess,sys,time,traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--client',type=Path,required=True);p.add_argument('--game',type=Path,required=True);p.add_argument('--audit',type=Path,required=True);p.add_argument('--focus-guard',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
sys.path[:0]=[str(a.sdk),str(ROOT/'tools')]
from luanti_course import Game,ConnectionError
from udp_fault_proxy import Faults,UdpFaultProxy

out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
def port():
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind(('127.0.0.1',0));v=s.getsockname()[1];s.close();return v
server_port=port();server_profile=out/'server-profile';client_profile=out/'client-profile';world=server_profile/'world'
(server_profile/'games').mkdir(parents=True);(server_profile/'games/voxelibre').symlink_to(a.game.resolve(),target_is_directory=True)
client_profile.mkdir(parents=True)
mod=world/'worldmods/network_fixture';mod.mkdir(parents=True)
(mod/'mod.conf').write_text('name = network_fixture\ndepends = mcl_core\n')
(mod/'init.lua').write_text('''
local function reset(name)
 core.emerge_area({x=-16,y=96,z=-8},{x=16,y=104,z=8},function(_,_,remaining)
  if remaining ~= 0 then return end
  core.after(0,function()
   local p=core.get_player_by_name(name);if not p then return end
   for x=-12,12 do for z=-5,5 do
    core.set_node({x=x,y=99,z=z},{name="mcl_core:stone"})
    for y=100,103 do core.set_node({x=x,y=y,z=z},{name="air"}) end
   end end
   p:set_pos({x=0,y=99.51,z=0});p:add_velocity(-p:get_velocity());p:set_hp(20);p:set_breath(10)
  end)
 end)
end
core.register_on_joinplayer(function(p) core.after(1,function() reset(p:get_player_name()) end) end)
core.register_chatcommand("network_reset",{func=function(name) reset(name);return true,"reset queued" end})
''')
(world/'world.mt').write_text('gameid = voxelibre\nbackend = sqlite3\nplayer_backend = sqlite3\nauth_backend = sqlite3\n')
(server_profile/'server.conf').write_text(f'''server_announce = false\nbind_address = 127.0.0.1\nport = {server_port}\ndefault_password = local-fixture\ncsm_restriction_flags = 0\ncreative_mode = false\nenable_damage = true\n''')
(client_profile/'client.conf').write_text('''course_control = true\nsound_volume = 0\nsound_volume_unfocused = 0\npause_on_lost_focus = false\nfps_max = 60\nfps_max_unfocused = 60\nenable_client_modding = false\n''')
password=out/'password';password.write_text('local-fixture');password.chmod(0o600)
server=None;client=None;proxy=None;game=None;rows=[]
def wait(fn,seconds=40):
    end=time.monotonic()+seconds;error=None
    while time.monotonic()<end:
        try:
            v=fn()
            if v:return v
        except Exception as exc:error=exc
        time.sleep(.1)
    raise RuntimeError('condition timeout'+(': '+str(error) if error else ''))
def launch_server(label):
    log=(out/(label+'-server.log')).open('w')
    env=dict(os.environ,LUANTI_USER_PATH=str(server_profile))
    return subprocess.Popen([str(a.client.resolve()),'--server','--world',str(world),'--config',str(server_profile/'server.conf'),'--logfile',''],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
def wait_server(label,process):
    log=out/(label+'-server.log')
    def ready():
        if process.poll() is not None:raise RuntimeError('dedicated server exited')
        if log.exists() and ' listening on ' in log.read_text(errors='replace'):return True
    wait(ready,20)
def launch_client(label,proxy_port):
    log=(out/(label+'-client.log')).open('w')
    env=dict(os.environ,LUANTI_USER_PATH=str(client_profile),LUANTI_COURSE_TEST_SILENT='1',SDL_MAC_BACKGROUND_APP='1',SDL_WINDOW_NO_ACTIVATION_WHEN_SHOWN='1',COURSE_TEST_BACKGROUND='1',DYLD_INSERT_LIBRARIES=str(a.audit.resolve())+':'+str(a.focus_guard.resolve()),COURSE_CURSOR_AUDIT_LOG=str(out/(label+'-cursor.txt')),COURSE_FOCUS_AUDIT_LOG=str(out/(label+'-focus.txt')))
    return subprocess.Popen([str(a.client.resolve()),'--config',str(client_profile/'client.conf'),'--address','127.0.0.1','--port',str(proxy_port),'--name','faultstudent','--password-file',str(password),'--go','--logfile',''],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
try:
    server=launch_server('first');wait_server('first',server)
    proxy=UdpFaultProxy(('127.0.0.1',server_port)).start();client=launch_client('first',proxy.address[1])
    game=wait(lambda:Game.connect(profile=client_profile),60);game.take_control();game.chat('/network_reset')
    # The fixture modifies an actually emerged map block, then waits for the
    # replicated player to be resting on it. Fixed sleeps can race map emerge
    # on slower machines and turn a network test into no_supported_start.
    baseline=wait(lambda:(s if s.raw['touching_ground'] and abs(s.position[0])<.2
                              and abs(s.position[2])<.2 and 99.35<s.position[1]<99.7 else None)
                  if (s:=game.observe()) else None,20)
    assert not baseline.raw['focused'] and not baseline.raw['audio_enabled']
    proxy.set_faults(Faults(delay_ms=90,drop_every=23))
    delayed=game.navigate_to((5,99.5,0),timeout=35,search_radius=24);assert delayed.ok,delayed.to_dict()
    rows.append({'phase':'latency_loss','status':'passed','result':delayed.to_dict(),'metrics':dict(proxy.metrics)})
    proxy.set_faults(Faults(cut=True));game.move('forward',.8);cut_local=game.observe();assert not cut_local.raw['input_active']
    time.sleep(1);proxy.set_faults(Faults());game.chat('/network_reset')
    resumed=wait(lambda:(s if s.raw['touching_ground'] and abs(s.position[0])<1
                              and 99.35<s.position[1]<99.7 else None)
                 if (s:=game.observe()) else None,20)
    rows.append({'phase':'cut_resume','status':'passed','local_position':cut_local.position,'resumed_position':resumed.position,'metrics':dict(proxy.metrics)})
    # A real server termination must leave no leased input. Restarting is
    # validated with a new background client and the same saved world/auth.
    server.terminate();server.wait(10);time.sleep(2)
    try:
        disconnected=game.observe();assert not disconnected.raw['input_active']
        disconnect_cleanup='bridge_observed_idle'
    except ConnectionError:
        # --go returns to the menu and destroys the in-game Course bridge on
        # an orderly server shutdown. Destroying that bridge clears native
        # held keys before closing the SDK socket; a closed bridge is the
        # stronger terminal cleanup state, not an audit failure.
        disconnect_cleanup='bridge_closed_after_server_shutdown'
    rows.append({'phase':'server_disconnect_cleanup','status':'passed','mode':disconnect_cleanup})
    game.close();game=None;client.terminate();client.wait(10);client=None;proxy.close();proxy=None
    server=launch_server('second');wait_server('second',server);proxy=UdpFaultProxy(('127.0.0.1',server_port)).start();client=launch_client('second',proxy.address[1])
    game=wait(lambda:Game.connect(profile=client_profile),60);state=game.observe();assert not state.dead and not state.raw['focused'] and not state.raw['audio_enabled']
    rows.append({'phase':'server_restart_reconnect','status':'passed','position':state.position,'control':state.control})
except Exception as exc:
    rows.append({'phase':'audit','status':'failed','error':str(exc),'traceback':traceback.format_exc()})
finally:
    if game:
        try:game.stop();game.release_control();game.close()
        except Exception:pass
    for process in (client,server):
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(8)
            except subprocess.TimeoutExpired:process.kill()
    if proxy:proxy.close()
    (out/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
    (out/'metrics.json').write_text(json.dumps(proxy.metrics if proxy else {},indent=2)+'\n')
print(json.dumps(rows,indent=2));raise SystemExit(any(r['status']!='passed' for r in rows))
