#!/usr/bin/env python3
"""Preplanned, bounded normal-player audit; owns and closes its native client.

No fixture commands, stdin command loop, automatic respawn, or server changes.
Credentials enter an anonymous pipe via getpass, not arguments/config/logs.
"""
import argparse,getpass,json,math,os,subprocess,sys,threading,time
from pathlib import Path

class OwnedClientWatchdog:
    """Independent of the SDK socket/action lock; never accepts an arbitrary PID."""
    def __init__(self,child,seconds=60,join_seconds=45,stale_seconds=4,min_hp=12,focus_log=None):
        self.child=child;self.end=time.monotonic()+seconds;self.join_end=time.monotonic()+join_seconds
        self.stale_seconds=stale_seconds;self.min_hp=min_hp;self.last=None;self.reason=None
        self.focus_log=Path(focus_log) if focus_log else None;self.focus_offset=0
        self.done=threading.Event();self.lock=threading.Lock();self.thread=threading.Thread(target=self._loop,daemon=True)
    def start(self):self.thread.start();return self
    def sample(self,state):
        with self.lock:
            self.last=time.monotonic()
            if state.get('dead'):self.reason=self.reason or 'player_dead'
            elif state.get('hp',20)<self.min_hp:self.reason=self.reason or 'health_floor'
            elif state.get('control')=='manual':self.reason=self.reason or 'manual_takeover'
            elif state.get('audio_enabled') is True:self.reason=self.reason or 'unexpected_audio'
    def _scan_focus(self):
        if not self.focus_log or not self.focus_log.exists():return
        with self.focus_log.open() as f:
            f.seek(self.focus_offset)
            for line in f:
                try:row=json.loads(line)
                except (ValueError,TypeError):continue
                if row.get('pid')==self.child.pid:self.reason=self.reason or 'unexpected_frontmost'
            self.focus_offset=f.tell()
    def _loop(self):
        while not self.done.wait(.05):
            now=time.monotonic()
            with self.lock:
                self._scan_focus()
                if now>=self.end:self.reason=self.reason or 'session_deadline'
                if self.last is None and now>=self.join_end:self.reason=self.reason or 'join_timeout'
                if self.last is not None and now-self.last>=self.stale_seconds:self.reason=self.reason or 'observation_stalled'
                reason=self.reason
            if reason:self.terminate();return
            if self.child.poll() is not None:return
    def terminate(self):
        if self.child.poll() is None:
            self.child.terminate()
            try:self.child.wait(timeout=2)
            except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=2)
    def close(self):
        self.done.set()
        if self.thread.ident:self.thread.join(timeout=5)
        with self.lock:self._scan_focus()
        self.terminate()

def validate_plan(plan):
    allowed={'observe','equip_best_gear','flee_from','eat_best_food','recover_air','escape_hazard','collect'}
    if not isinstance(plan,list) or not 1<=len(plan)<=10:raise ValueError('plan requires 1..10 steps')
    for step in plan:
        if not isinstance(step,dict) or step.get('action') not in allowed:raise ValueError('unsupported plan action')
        keys={'action','timeout'}|({'item','count'} if step['action']=='collect' else {'safe_distance'} if step['action']=='flee_from' else set())
        if set(step)-keys:raise ValueError('unexpected plan fields')
        timeout=step.get('timeout',12)
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not .1<=timeout<=20:raise ValueError('step timeout must be .1..20')
        if step['action']=='collect':
            if not isinstance(step.get('item'),str) or not step['item']:raise ValueError('collect needs item')
            if type(step.get('count',1)) is not int or not 1<=step.get('count',1)<=4:raise ValueError('collect count must be 1..4')
        if step['action']=='flee_from':
            d=step.get('safe_distance',14)
            if type(d) not in (int,float) or not math.isfinite(d) or not 1<=d<=15:raise ValueError('invalid safety distance')
    return plan

def execute_plan(game,plan,record,remaining):
    """First failure ends the run; no waiting for interactive follow-up prompts."""
    for step in plan:
        if remaining()<=0:return 'session_deadline'
        s=game.observe(6)
        if s.dead or s.control!='agent':return 'control_lost'
        op=step['action'];kw={k:v for k,v in step.items() if k!='action'}
        if op=='observe':result={'position':s.position,'hp':s.hp,'dead':s.dead}
        else:
            kw['timeout']=min(kw.get('timeout',12),remaining())
            if kw['timeout']<=0:return 'session_deadline'
            if op=='collect':kw['resource']=kw.pop('item')
            r=getattr(game,op)(**kw);result=r.to_dict()
        record({'step':step,'result':result})
        if op!='observe' and not r.ok:return 'step_failed'
    return 'complete'

def launch_environment(profile,output):
    env=dict(os.environ,LUANTI_USER_PATH=str(profile.resolve()),
        LUANTI_COURSE_TEST_SILENT='1',SDL_MAC_BACKGROUND_APP='1',
        SDL_WINDOW_NO_ACTIVATION_WHEN_SHOWN='1',COURSE_TEST_BACKGROUND='1')
    if sys.platform=='darwin':
        # macOS can strip DYLD_* before the system Python starts. Carry paths
        # through a non-DYLD setting and construct the child env here instead.
        libraries=env.pop('COURSE_TEST_DYLD_LIBRARIES','')
        paths=libraries.split(':')
        if len(paths)!=2 or not all(Path(x).is_absolute() and Path(x).is_file() for x in paths):
            raise ValueError('macOS audit requires two existing background instrumentation libraries')
        env.update(DYLD_INSERT_LIBRARIES=libraries,COURSE_CURSOR_AUDIT_LOG=str((output/'cursor.txt').resolve()),COURSE_FOCUS_AUDIT_LOG=str((output/'focus.txt').resolve()))
    return env

def validate_background_bundle(client):
    if sys.platform!='darwin':return
    import plistlib
    info=client.resolve().parents[1]/'Info.plist'
    if not info.is_file() or plistlib.loads(info.read_bytes()).get('LSUIElement') is not True:
        raise ValueError('macOS remote audit needs an isolated LSUIElement test app; keep the student app unchanged')

def validate_focus_watcher():
    if sys.platform!='darwin':return None
    path=Path(os.environ.get('COURSE_TEST_FOCUS_WATCH',''))
    if not path.is_absolute() or not path.is_file() or not os.access(path,os.X_OK):
        raise ValueError('macOS remote audit requires an executable frontmost-app watcher')
    return path

class ExclusiveRemoteAudit:
    """One owned remote test client per user; OS releases the lock on exit."""
    def __init__(self):self.file=None
    def __enter__(self):
        import tempfile
        self.file=open(Path(tempfile.gettempdir())/'luanti-course-remote-audit.lock','a+b')
        try:
            if os.name=='nt':
                import msvcrt
                self.file.seek(0);self.file.write(b'0');self.file.flush();self.file.seek(0)
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();self.file=None
            raise RuntimeError('another remote audit owns the test session')
        return self
    def __exit__(self,*args):
        if self.file:self.file.close();self.file=None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('client','profile','sdk','output','plan'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--address',required=True);p.add_argument('--port',type=int,default=30000);p.add_argument('--name',required=True)
    p.add_argument('--seconds',type=float,default=60);p.add_argument('--min-hp',type=int,default=12)
    a=p.parse_args();plan=validate_plan(json.loads(a.plan.read_text()))
    if not math.isfinite(a.seconds) or not 1<=a.seconds<=120:p.error('seconds must be 1..120')
    if not 1<=a.min_hp<=20:p.error('min-hp must be 1..20')
    if not a.client.is_file() or not (a.profile/'minetest.conf').is_file() or not (a.sdk/'luanti_course/__init__.py').is_file():p.error('client, profile or SDK missing')
    # Environment is configured explicitly by the test operator. Never launch
    # an audible or cursor-capturing test due to missing test environment.
    if os.environ.get('LUANTI_COURSE_TEST_SILENT')!='1':p.error('muted test environment required')
    validate_background_bundle(a.client);focus_watcher=validate_focus_watcher()
    a.output.mkdir(parents=True,exist_ok=False);sys.path.insert(0,str(a.sdk))
    from luanti_course import Game
    import luanti_course
    result={'status':'not_started','steps':[],'plan':plan,'sdk':luanti_course.__version__,'world_reset':False,'automatic_respawn':False}
    def save(): (a.output/'results.json').write_text(json.dumps(result,indent=2))
    def record(row):result['steps'].append(row);save()
    password=getpass.getpass('Course password (hidden): ');read_fd,write_fd=os.pipe()
    try:os.write(write_fd,password.encode()+b'\n')
    finally:os.close(write_fd);del password
    child=None;watch=None;game=None;focus_process=None
    try:
        env=launch_environment(a.profile,a.output)
        focus_log=a.output/'frontmost.jsonl'
        if focus_watcher:
            focus_process=subprocess.Popen([str(focus_watcher),str(focus_log),str(a.seconds+10)],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        command=[str(a.client.resolve()),'--config',str((a.profile/'minetest.conf').resolve()),'--address',a.address,'--port',str(a.port),'--name',a.name,'--password-file',f'/dev/fd/{read_fd}','--go','--logfile','']
        with (a.output/'native-stdout.txt').open('w') as out,(a.output/'native-stderr.txt').open('w') as err:
            child=subprocess.Popen(command,env=env,pass_fds=(read_fd,),stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
        os.close(read_fd);read_fd=None
        watch=OwnedClientWatchdog(child,a.seconds,min_hp=a.min_hp,focus_log=focus_log if focus_watcher else None).start()
        # Start deadline protection immediately after spawn, before connection.
        while child.poll() is None and not watch.reason:
            try:
                endpoint=a.profile/('course-control-'+str(child.pid)+'.json')
                if json.loads(endpoint.read_text()).get('pid')!=child.pid:raise RuntimeError('endpoint owner mismatch')
                game=Game.connect(endpoint=endpoint,control=False,timeout=4);break
            except Exception:time.sleep(.1)
        if game is None:raise RuntimeError(watch.reason or 'client_exit_before_connection')
        raw=game._request
        def request(op,**kw):
            if op in ('chat','respawn'):raise AssertionError('No server commands or automatic respawn')
            reply=raw(op,**kw)
            if op=='observe':
                watch.sample(reply)
                # Preserve complete geometry for failure replay, unlike v0.18.
                with (a.output/'observations.jsonl').open('a') as f:f.write(json.dumps(reply)+'\n')
                if watch.reason:raise RuntimeError(watch.reason)
            return reply
        game._request=request
        s=game.observe(6)
        if s.dead or s.raw.get('menu_open') or s.control=='manual':raise RuntimeError('initial_state_requires_human_attention')
        game.take_control()
        result['status']=execute_plan(game,plan,record,lambda:watch.end-time.monotonic())
    except Exception as exc:result.update(status='aborted',error=type(exc).__name__+': '+str(exc))
    finally:
        if read_fd is not None:os.close(read_fd)
        # Close the owned native client first: stopping inputs alone leaves a
        # connected character exposed. This also bounds hung socket cleanup.
        if watch:watch.close();result['watchdog_reason']=watch.reason
        if focus_process and focus_process.poll() is None:
            focus_process.terminate()
            try:focus_process.wait(timeout=2)
            except subprocess.TimeoutExpired:focus_process.kill();focus_process.wait(timeout=2)
        if game:
            try:game.close()
            except Exception as exc:result['cleanup_error']=type(exc).__name__
        result['native_exit_status']=None if child is None else child.poll()
        result['client_closed']=child is None or child.poll() is not None
        if result.get('watchdog_reason'):result['status']='aborted'
        save()
    print(json.dumps({'status':result['status'],'client_closed':result['client_closed'],'watchdog_reason':result.get('watchdog_reason')}))
    return 0 if result['status']=='complete' else 1

if __name__=='__main__':
    with ExclusiveRemoteAudit():sys.exit(main())
