"""Standard-library-only SDK. Normal client rendering never waits for the agent."""
import contextlib
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import uuid
from .errors import ActionCancelled, ActionError, ActionTimeout, ConnectionError, ProtocolError
from .state import Snapshot, Submission
from .skills import ActionLock

_UNSET = object()
MAX_REPLY = 512 * 1024
KEYS = frozenset(('forward','backward','left','right','jump','aux1','sneak','dig','place'))

def profile_path():
    value=os.environ.get('LUANTI_USER_PATH') or os.environ.get('MINETEST_USER_PATH')
    if value:return Path(value).expanduser()
    if sys.platform=='darwin':return Path.home()/'Library/Application Support/LuantiCourse'
    if os.name=='nt':return Path(os.environ['APPDATA'])/'LuantiCourse'
    return Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'luanti-course'

def find_binary(explicit=None):
    if explicit:
        p=Path(explicit).expanduser()
        if p.suffix=='.app':p=p/'Contents/MacOS/luanti'
        if p.is_file():return p
        raise ConnectionError('Client executable does not exist: '+str(p))
    candidates=[]
    if os.environ.get('LUANTI_COURSE_CLIENT'):candidates.append(Path(os.environ['LUANTI_COURSE_CLIENT']))
    if sys.platform=='darwin':
        candidates.extend([Path('/Applications/Luanti Course.app/Contents/MacOS/luanti'),Path.home()/'Applications/Luanti Course.app/Contents/MacOS/luanti'])
    elif os.name=='nt':
        for var in ['LOCALAPPDATA','ProgramFiles']:
            if os.environ.get(var):candidates.append(Path(os.environ[var])/'Luanti Course/bin/luanti.exe')
    # Repository developers may use the locally built distribution.
    candidates.extend([Path.cwd()/'dist/Luanti Course.app/Contents/MacOS/luanti',Path.cwd()/'dist/Luanti Course/bin/luanti.exe'])
    for candidate in candidates:
        if candidate.is_file():return candidate
    raise ConnectionError('Install Luanti Course first, or pass client=PATH. The ordinary Luanti client has no Course API.')

class Game:
    def __init__(self,sock,endpoint,timeout=5.0):
        self._socket=sock;self._socket.settimeout(timeout)
        if sock.family in (socket.AF_INET,socket.AF_INET6):sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.endpoint=endpoint;self._buffer=b'';self._counter=0;self._epoch=None
        self._lock=threading.RLock();self._action_lock=ActionLock();self._skill_depth=0;self._recipe_book=None;self._cancel=threading.Event()
        self._observation_source=uuid.uuid4().hex
        self._closed=False;self.timeout=timeout;self._motion=None;self._survival=None
        self.traversal=None;self.exploration_memory=None;self._mining_trip=None;self._locations={}

    @classmethod
    def connect(cls, *, profile=None, endpoint=None, timeout=5.0, control=False):
        """Attach to the same running visible player. Does not relaunch the game."""
        if timeout<=0:raise ValueError('timeout must be positive')
        directory=Path(profile) if profile else profile_path()
        if endpoint:
            files=[Path(endpoint)]
        else:
            files=sorted(directory.glob('course-control-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        connected=[]
        for file in files:
            sock=None
            try:
                info=json.loads(file.read_text())
                if info.get('host')!='127.0.0.1' or info.get('protocol')!=1:continue
                port=info['port'];token=info['token']
                if isinstance(port,bool) or not isinstance(port,int) or not 1<=port<=65535:continue
                if not isinstance(token,str) or len(token)!=64:continue
                sock=socket.create_connection(('127.0.0.1',port),timeout=min(timeout,1.5))
                game=cls(sock,file,timeout);game._send({'protocol':1,'token':token})
                hello=game._read()
                if hello.get('status')!='connected':raise ProtocolError('Unexpected handshake')
                connected.append(game)
            except (OSError,ValueError,KeyError,ConnectionError,ProtocolError):
                if sock:sock.close()
        if len(connected)>1:
            for game in connected:game.close()
            raise ConnectionError('Several Course clients are running. Pass endpoint=PATH to choose one.')
        if not connected:raise ConnectionError('No available Course client. Open Luanti Course and join a world first; close other controller scripts if it is busy.')
        game=connected[0]
        try:
            hello=game._request('hello')
            if hello.get('protocol')!=1:raise ProtocolError('Unsupported Course protocol')
            game.capabilities=tuple(hello['capabilities'])
            if control:game.take_control()
            return game
        except BaseException:
            game.close();raise

    @classmethod
    def launch(cls, *, client=None, profile=None, world=None, timeout=90.0, control=False):
        """Launch the visible client, then attach after the user joins a world.

        Login stays in the game's UI. Passwords are not put on the command line.
        """
        binary=find_binary(client);directory=Path(profile) if profile else profile_path()
        directory.mkdir(parents=True,exist_ok=True)
        env=dict(os.environ,LUANTI_USER_PATH=str(directory))
        command=[str(binary)]
        if world:command.extend(['--world',str(Path(world).resolve()),'--go'])
        subprocess.Popen(command,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:return cls.connect(profile=directory,control=control)
            except ConnectionError:time.sleep(.3)
        raise ConnectionError('Client opened, but no world became ready. Join a server/world, then use Game.connect().')

    def _send(self,value):
        data=(json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode('utf8')
        if len(data)>8192:raise ValueError('Request exceeds the 8192-byte limit')
        self._socket.sendall(data)
    def _read(self):
        end=time.monotonic()+self.timeout
        while b'\n' not in self._buffer:
            if time.monotonic()>=end:raise ConnectionError('Client response timed out; the action outcome is unknown.')
            chunk=self._socket.recv(65536)
            if not chunk:raise ConnectionError('Controller connection closed; held input is released by the client.')
            self._buffer+=chunk
            if len(self._buffer)>MAX_REPLY:raise ProtocolError('Client response too large')
        line,self._buffer=self._buffer.split(b'\n',1)
        try:value=json.loads(line)
        except (ValueError,UnicodeError) as exc:raise ProtocolError('Invalid client response') from exc
        if not isinstance(value,dict):raise ProtocolError('Expected an object response')
        return value
    def _request(self,op,**args):
        with self._lock:
            guard=getattr(self,'_survival',None)
            if guard and op not in ('observe','hello','inspect_node','inspect_item','screenshot','stop','release'):
                if guard.interrupted():raise ActionCancelled('survival_interrupted')
            if op not in ('observe','hello','inspect_node','inspect_item','screenshot','stop','release') and self._action_lock.other_owner():
                raise ActionError('another_action_running')
            if self._closed:raise ConnectionError('Game connection is closed')
            self._counter+=1;message=dict(id=self._counter,op=op,**args)
            if self._epoch is not None:message.setdefault('control_epoch',self._epoch)
            try:
                self._send(message);reply=self._read()
                if reply.get('id')!=self._counter:raise ProtocolError('Unexpected response id')
            except (OSError,ConnectionError,ProtocolError) as exc:
                self._closed=True;self._socket.close();self._cancel.set()
                if isinstance(exc,(ConnectionError,ProtocolError)):raise
                raise ConnectionError('Connection interrupted; action outcome is unknown. Reconnect explicitly.') from exc
            if reply.get('status')=='error':
                if reply.get('error') in ('control_released','stale_control_epoch','manual_control_active'):self._epoch=None;self._cancel.set()
                raise ActionError(reply.get('error','unknown_error'),reply)
            return reply
    def _submit(self,op,**args):
        reply=self._request(op,**args);return Submission(reply['id'],reply['frame'],op)
    def observe(self,radius=0):
        if isinstance(radius,bool) or not isinstance(radius,int) or not 0<=radius<=6:raise ValueError('radius must be an integer from 0 to 6')
        raw=self._request('observe',radius=radius)
        raw['observation_source']=self._observation_source
        return Snapshot.from_dict(raw)
    def take_control(self):
        state=self.observe();reply=self._request('acquire',control_epoch=state.control_epoch)
        self._epoch=reply['control_epoch'];self._cancel.clear();return self
    def release_control(self):
        if self._survival:self._survival.pause()
        self._cancel.set()
        try:return self._submit('release')
        finally:self._epoch=None
    @contextlib.contextmanager
    def control(self):
        self.take_control()
        try:yield self
        finally:
            if not self._closed:self.release_control()
    def stop(self):
        if self._survival and not self._survival.is_worker():self._survival.pause()
        self._cancel.set();return self._submit('stop')
    def hold(self,keys,seconds=1.0):
        """Bounded, cancellable input. Native leases also expire if this process dies."""
        keys=tuple(keys)
        if not keys or len(keys)>9 or any(k not in KEYS for k in keys):raise ValueError('Unknown or empty controls')
        if isinstance(seconds,bool) or not math.isfinite(seconds) or not 0<seconds<=60:raise ValueError('seconds must be in (0, 60]')
        if self._motion is not None:
            if self._action_lock.other_owner():raise ActionError('another_action_running')
            return self._motion.hold(keys,seconds)
        if not self._action_lock.acquire(blocking=False):raise ActionError('another_action_running')
        if not self._skill_depth:self._cancel.clear()
        end=time.monotonic()+seconds
        try:
            while time.monotonic()<end:
                if self._cancel.is_set():raise ActionCancelled('Action cancelled')
                duration=min(.15,end-time.monotonic())
                # A short tap must expire natively even if the next observe or
                # stop is delayed. A fixed 400 ms lease could repeat PLACE.
                lease=min(.4,max(.001,end-time.monotonic()))
                self._submit('input',keys=list(keys),duration_ms=max(1,math.ceil(lease*1000)))
                deadline=min(end,time.monotonic()+duration)
                while time.monotonic()<deadline:
                    if self._cancel.wait(min(.1,max(0,deadline-time.monotonic()))):raise ActionCancelled('Action cancelled')
                    state=self.observe()
                    if state.control!='agent' or state.control_epoch!=self._epoch:raise ActionError('control_released')
            return self.observe()
        finally:
            try:
                if not self._closed:self._submit('stop')
            finally:self._action_lock.release()
    def move(self,direction='forward',seconds=1.0,*,jump=False,sneak=False):
        if direction not in ('forward','backward','left','right'):raise ValueError('Unknown movement direction')
        return self.hold([direction]+(['jump'] if jump else [])+(['sneak'] if sneak else []),seconds)
    def motion(self):
        """Explicit continuous control for short Python loops; exit always stops."""
        from .motion import Motion
        return Motion(self)
    def look(self,yaw,pitch=0,*,instant=False,timeout=2):
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (yaw,pitch)):raise ValueError('Orientation must be finite numbers')
        if abs(yaw)>36000 or abs(pitch)>89.9:raise ValueError('Orientation outside supported range')
        if not isinstance(instant,bool):raise ValueError('instant must be boolean')
        if instant:return self._submit('look',yaw=yaw,pitch=pitch)
        from .motion import turn
        return turn(self,yaw,pitch,timeout)
    def look_at(self,position,*,instant=False,timeout=2):
        if len(position)!=3 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in position):raise ValueError('position must contain finite x, y, z')
        eye=self.observe().eye;dx,dy,dz=[position[i]-eye[i] for i in range(3)]
        return self.look(math.degrees(math.atan2(-dx,dz)),max(-89.9,min(89.9,math.degrees(math.atan2(-dy,math.hypot(dx,dz))))),instant=instant,timeout=timeout)
    def dig(self,seconds=1.0):return self.hold(['dig'],seconds)
    def use(self,seconds=.1):return self.hold(['place'],seconds)
    def wield(self,slot):return self._submit('wield',slot=slot)
    def open_inventory(self):return self._submit('inventory_open')
    def close_inventory(self):return self._submit('inventory_close')
    def move_items(self,from_list,from_slot,to_list,to_slot,count=1,*,from_inventory='player',to_inventory='player',form_id=None):
        args=dict(from_list=from_list,from_slot=from_slot,to_list=to_list,to_slot=to_slot,count=count,from_inventory=from_inventory,to_inventory=to_inventory)
        if form_id is not None:args['form_id']=form_id
        return self._submit('move_items',**args)
    def craft_grid(self,count=1):
        """Submit the current real 2x2 / 3x3 grid. No hidden recipe or material grants."""
        return self._submit('craft',count=count)
    def drop(self,slot,count=1,*,list_name='main'):
        return self._submit('drop',from_inventory='player',from_list=list_name,from_slot=slot,count=count)
    def chat(self,text):return self._submit('chat',text=text)
    def screenshot(self):return self._submit('screenshot')
    def respawn(self):return self._submit('respawn')
    def wait_for(self,predicate,timeout=5.0,interval=.1):
        """Wait for an observed condition; it is not a per-action server acknowledgement."""
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            state=self.observe()
            if predicate(state):return state
            time.sleep(interval)
        raise ActionTimeout('Condition not observed before timeout; inspect the game before retrying an action.')
    @property
    def recipe_book(self):
        from .recipes import RecipeBook
        if self._recipe_book is None:self._recipe_book=RecipeBook.voxelibre()
        return self._recipe_book
    @recipe_book.setter
    def recipe_book(self, book):
        self._recipe_book=book
    def navigate_to(self, position, *, tolerance=.45, timeout=90, search_radius=64, allow_swim=None, allow_climb=None, allow_jump_gaps=None, allow_dive=None, allow_interact=None, allow_dig=None, build_with=_UNSET, max_drop=None, max_gap=None, edit_budget=None, traversal=None):
        """Navigate observed geometry; water/diving/gaps require explicit opt-in.

        Doors use ordinary right-click interactions. Mining and construction
        are opt-in and consume normal tools/materials. max_drop defaults to one
        block; gap jumps are bounded by observed movement physics. Unknown or
        hazardous terrain stays blocked. Native movement never teleports.
        Diving is bounded by observations, timeout and the breath guard.
        """
        from .skills import run, navigate, positive
        if len(position)!=3 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or abs(x)>32700 for x in position):raise ValueError('position must contain three finite world coordinates')
        positive(tolerance,'tolerance',2)
        from .navigation import Traversal
        from dataclasses import replace
        base=traversal if traversal is not None else self.traversal or Traversal()
        if not isinstance(base,Traversal):raise ValueError('traversal must be Traversal')
        overrides={name:value for name,value in dict(allow_swim=allow_swim,allow_climb=allow_climb,allow_jump_gaps=allow_jump_gaps,allow_dive=allow_dive,allow_interact=allow_interact,allow_dig=allow_dig,max_drop=max_drop,max_gap=max_gap,edit_budget=edit_budget).items() if value is not None}
        if build_with is not _UNSET:overrides['build_with']=build_with
        policy=replace(base,**overrides)
        def go(c):
            c.world.traversal=policy
            if policy.build_with:
                from .skills import Failure
                if 'inspect_item' not in self.capabilities:raise Failure('building_geometry_unavailable')
                d=self._request('inspect_item',name=policy.build_with)
                if not d['full_cube'] or not d['walkable'] or d['liquid'] or d['damage_per_second'] or d['groups'].get('falling_node',0):
                    raise Failure('building_material_not_full_cube',{'item':policy.build_with})
            if policy.allow_dive and 'swim_height' not in self.capabilities:
                from .skills import Failure
                raise Failure('swim_control_unavailable',{'message':'Use Course client 0.5 or newer.'})
            return navigate(c,position,tolerance)
        return run(self,'navigate_to',go,timeout=timeout,search_radius=search_radius,traversal=policy)
    def find_resource(self, resource, *, search_radius=32, timeout=90, traversal=None):
        """Search reachable observed terrain, exploring within a bounded radius."""
        from .skills import run, find_resource
        if not isinstance(resource,str) or not resource:raise ValueError('resource must be a node/item ID or group selector')
        def find(c):
            p=find_resource(c,resource);c.details.update(position=p,node=c.world.nodes[p].name)
        return run(self,'find_resource',find,timeout=timeout,search_radius=search_radius,traversal=traversal)
    def collect(self, resource, count=1, *, search_radius=32, timeout=180, recover=True, traversal=None, checkpoint=None, allow_tool_crafting=False):
        """Collect count additional items; success requires inventory confirmation."""
        from .skills import run, collect
        if not isinstance(resource,str) or not resource:raise ValueError('resource must be a node/item ID or group selector')
        if isinstance(count,bool) or not isinstance(count,int) or not 1<=count<=256:raise ValueError('count must be an integer from 1 to 256')
        if not isinstance(recover,bool):raise ValueError('recover must be boolean')
        if not isinstance(allow_tool_crafting,bool):raise ValueError('allow_tool_crafting must be boolean')
        def execute(c):
            c.recover=recover;c.allow_tool_crafting=allow_tool_crafting
            from .persistence import quantity_task
            quantity_task(c,'collect',resource,count,checkpoint,self._task_request(c,resource=resource,count=count,search_radius=search_radius,recover=recover,allow_tool_crafting=allow_tool_crafting),lambda n:collect(c,resource,n))
        return run(self,'collect',execute,timeout=timeout,search_radius=search_radius,traversal=traversal)
    def craft(self, item, count=1, *, gather=False, search_radius=32, timeout=300, recover=True, traversal=None, checkpoint=None, allow_tool_crafting=False):
        """Produce count additional outputs, resolving materials and a real workbench."""
        from .skills import run, craft
        if not isinstance(item,str) or not item:raise ValueError('item must be an item ID')
        if isinstance(count,bool) or not isinstance(count,int) or not 1<=count<=64:raise ValueError('count must be an integer from 1 to 64')
        if not isinstance(gather,bool):raise ValueError('gather must be a boolean')
        if not isinstance(recover,bool):raise ValueError('recover must be boolean')
        if not isinstance(allow_tool_crafting,bool):raise ValueError('allow_tool_crafting must be boolean')
        def execute(c):
            c.recover=recover;c.allow_tool_crafting=allow_tool_crafting
            from .persistence import quantity_task
            quantity_task(c,'craft',item,count,checkpoint,self._task_request(c,item=item,count=count,gather=gather,search_radius=search_radius,recover=recover,allow_tool_crafting=allow_tool_crafting),lambda n:craft(c,item,n,gather))
        return run(self,'craft',execute,timeout=timeout,search_radius=search_radius,traversal=traversal)
    def organize_inventory(self, *, timeout=30):
        """Merge identical stacks, preserving metadata and every item."""
        from .skills import run, organize_inventory
        return run(self,'organize_inventory',organize_inventory,timeout=timeout)
    def equip(self, item, *, destination='hand', timeout=30):
        """Select a named held item, or move it into a compatible armor/offhand slot."""
        from .skills import run, equip
        if not isinstance(item,str) or not item:raise ValueError('item must be an item ID')
        if destination not in ('hand','armor','offhand'):raise ValueError('destination must be hand, armor or offhand')
        return run(self,'equip',lambda c:equip(c,item,destination),timeout=timeout)
    def place_block(self, item, position, *, timeout=45, search_radius=16, traversal=None):
        """Place one held node at integer node coordinates, then confirm the world."""
        from .skills import run, place_block
        if not isinstance(item,str) or not item:raise ValueError('item must be an item ID')
        if len(position)!=3 or any(isinstance(v,bool) or not isinstance(v,int) or abs(v)>32700 for v in position):raise ValueError('position must contain three integer node coordinates')
        return run(self,'place_block',lambda c:place_block(c,item,tuple(position)),timeout=timeout,search_radius=search_radius,traversal=traversal)
    @staticmethod
    def _task_request(ctx,**kwargs):
        from dataclasses import asdict
        return dict(kwargs,traversal=asdict(ctx.world.traversal))

    def resume(self, checkpoint, *, timeout=300):
        """Explicitly resume the same client-bound quantity goal after observing."""
        path=Path(checkpoint).expanduser().resolve()
        if path.stat().st_size>256000:raise ValueError('checkpoint too large')
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('scope')!=str(self.endpoint.resolve()):raise ValueError('checkpoint belongs to a different client')
        op=data.get('operation')
        if op not in ('collect','craft','smelt','dig_down','dig_tunnel'):raise ValueError('unsupported checkpoint operation')
        from .navigation import Traversal
        args=dict(data['request']);args['traversal']=Traversal(**args['traversal'])
        return getattr(self,op)(**args,checkpoint=path,timeout=timeout)

    def smelt(self,item,count=1,*,furnace=None,fuel=None,gather=False,timeout=300,search_radius=32,traversal=None,checkpoint=None):
        from .skills import run
        from .workstations import smelt
        from .persistence import quantity_task
        if type(count) is not int or not 1<=count<=64:raise ValueError('count must be 1..64')
        if not isinstance(item,str) or not item:raise ValueError('item must be a name')
        if not isinstance(gather,bool):raise ValueError('gather must be boolean')
        if fuel is not None and (not isinstance(fuel,str) or not fuel):raise ValueError('fuel must be an item name')
        if furnace is not None:
            from .construction import position
            furnace=position(furnace)
        def execute(c):
            request=self._task_request(c,item=item,count=count,furnace=furnace,fuel=fuel,gather=gather,search_radius=search_radius)
            quantity_task(c,'smelt',item,count,checkpoint,request,lambda n:smelt(c,item,n,gather=gather,furnace=furnace,fuel=fuel))
        return run(self,'smelt',execute,timeout=timeout,search_radius=search_radius,traversal=traversal)

    def deposit(self,position,item,count=1,*,timeout=60,search_radius=64,traversal=None):
        return self._transfer(position,item,count,'deposit',timeout,search_radius,traversal)

    def withdraw(self,position,item,count=1,*,timeout=60,search_radius=64,traversal=None):
        return self._transfer(position,item,count,'withdraw',timeout,search_radius,traversal)

    def restock(self,position,item,target_count,*,timeout=60,search_radius=64,traversal=None):
        """Withdraw only the deficit to a desired inventory total."""
        from .construction import position as node_position
        from .workstations import transfer
        from .skills import run,count_items
        position=node_position(position)
        if not isinstance(item,str) or not item:raise ValueError('item must be a name')
        if type(target_count) is not int or not 0<=target_count<=4096:raise ValueError('target_count must be 0..4096')
        def execute(c):
            missing=max(0,target_count-count_items(c.read(),item,c.book))
            if missing:transfer(c,position,item,missing,'withdraw')
            c.details.update(item=item,target_count=target_count,withdrawn=missing)
        return run(self,'restock',execute,timeout=timeout,search_radius=search_radius,traversal=traversal)

    def _transfer(self,p,item,count,direction,timeout,search_radius,traversal):
        from .construction import position
        from .workstations import transfer
        from .skills import run
        p=position(p)
        if not isinstance(item,str) or not item:raise ValueError('item must be a name')
        if type(count) is not int or not 1<=count<=4096:raise ValueError('count must be 1..4096')
        return run(self,direction,lambda c:transfer(c,p,item,count,direction),timeout=timeout,search_radius=search_radius,traversal=traversal)

    def excavate(self,route,*,return_to_start=True,timeout=600,search_radius=128,traversal=None):
        from .construction import excavate,validate_route
        from .skills import run
        route=validate_route(route)
        if not isinstance(return_to_start,bool):raise ValueError('return_to_start must be boolean')
        return run(self,'excavate',lambda c:excavate(c,route,return_to_start),timeout=timeout,search_radius=search_radius,traversal=traversal)

    def build(self,blocks,*,timeout=600,search_radius=128,traversal=None):
        from .construction import build,validate_blueprint
        from .skills import run
        blocks=validate_blueprint(blocks)
        return run(self,'build',lambda c:build(c,blocks),timeout=timeout,search_radius=search_radius,traversal=traversal)

    def build_ladder(self,bottom,height,*,backing=(1,0,0),material='mcl_core:ladder',backing_material=None,timeout=300,search_radius=64,traversal=None):
        from .construction import build_ladder,position
        from .skills import run
        bottom=position(bottom)
        if type(height) is not int or not 1<=height<=32:raise ValueError('height must be 1..32')
        if tuple(backing) not in ((1,0,0),(-1,0,0),(0,0,1),(0,0,-1)):raise ValueError('backing must point horizontally to the wall')
        if not isinstance(material,str) or not material:raise ValueError('material must be an item name')
        if backing_material is not None and (not isinstance(backing_material,str) or not backing_material):raise ValueError('backing_material must be an item name')
        return run(self,'build_ladder',lambda c:build_ladder(c,bottom,height,backing,material,backing_material),timeout=timeout,search_radius=search_radius,traversal=traversal)

    def navigate_route(self,waypoints,*,timeout=900,search_radius=4096,traversal=None):
        """Pass intermediate waypoints continuously; stop at the final destination."""
        from .skills import run,navigate
        points=tuple(tuple(p) for p in waypoints)
        if not 1<=len(points)<=256 or any(len(p)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>32700 for v in p) for p in points):raise ValueError('expected 1..256 finite world positions')
        def execute(c):
            for i,p in enumerate(points):
                navigate(c,p,through=i<len(points)-1);c.details.update(completed_waypoints=i+1,total_waypoints=len(points))
        return run(self,'navigate_route',execute,timeout=timeout,search_radius=search_radius,traversal=traversal)

    def dig_down(self, depth, *, direction=None, timeout=600, search_radius=128, traversal=None, checkpoint=None):
        """Generate a bounded descending stairway and stay at its end."""
        from .excursions import mining_job, validate_distance, direction as heading
        from .skills import run
        validate_distance(depth, 'depth');direction=heading(direction)
        return run(self,'dig_down',lambda c:mining_job(c,'dig_down',depth,direction,checkpoint),timeout=timeout,search_radius=search_radius,traversal=traversal)

    def dig_tunnel(self, length, *, direction=(1,0,0), timeout=600, search_radius=128, traversal=None, checkpoint=None):
        """Excavate a horizontal corridor without planning what resource to seek."""
        from .excursions import mining_job, validate_distance, direction as heading
        from .skills import run
        validate_distance(length, 'length');direction=heading(direction)
        if direction is None:raise ValueError('tunnel direction is required')
        return run(self,'dig_tunnel',lambda c:mining_job(c,'dig_tunnel',length,direction,checkpoint),timeout=timeout,search_radius=search_radius,traversal=traversal)

    def go_to_surface(self, surface=None, *, timeout=600, search_radius=4096, traversal=None, checkpoint=None):
        """Return to the remembered mining entrance, or an explicit surface point.

        A cave entrance is not proof of outdoor sky. Provide a known surface
        position when the excursion began underground. No height is guessed.
        """
        from .excursions import go_to_surface
        from .skills import run
        if surface is not None:
            surface=tuple(surface)
            if len(surface)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>32700 for v in surface):raise ValueError('expected a finite surface position')
        return run(self,'go_to_surface',lambda c:go_to_surface(c,surface,checkpoint),timeout=timeout,search_radius=search_radius,traversal=traversal)

    def reset_mining_trip(self):
        """Explicitly start a separate excursion; never erases checkpoint files."""
        if self._action_lock.locked():raise ActionError('another_action_running')
        self._mining_trip=None

    def bridge_to(self, position, *, material='mcl_core:cobble', max_blocks=32, timeout=180, search_radius=64, traversal=None):
        """Reach a destination using held scaffold material, within an edit budget.

        This does not prescribe a decorative bridge shape; use build for blueprints.
        """
        from dataclasses import replace
        from .navigation import Traversal
        from .skills import run,navigate
        position=tuple(position)
        if len(position)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>32700 for v in position):raise ValueError('expected a finite destination')
        if not isinstance(material,str) or not material:raise ValueError('material must be an item name')
        if type(max_blocks) is not int or not 1<=max_blocks<=128:raise ValueError('max_blocks must be 1..128')
        base=traversal if traversal is not None else self.traversal or Traversal()
        if not isinstance(base,Traversal):raise ValueError('traversal must be Traversal')
        policy=replace(base,build_with=material,allow_dig=False,edit_budget=min(base.edit_budget,max_blocks))
        return run(self,'bridge_to',lambda c:navigate(c,position),timeout=timeout,search_radius=search_radius,traversal=policy)

    def eat(self, item, count=1, *, timeout=60):
        """Eat a specified held food; server inventory consumption confirms success."""
        from .survival import eat
        from .skills import run
        if not isinstance(item,str) or not item:raise ValueError('item must be a food name')
        if type(count) is not int or not 1<=count<=16:raise ValueError('count must be 1..16')
        return run(self,'eat',lambda c:eat(c,item,count),timeout=timeout)

    def survival(self, config=None):
        """Explicit fast survival context. Requires control(); never acquires it."""
        from .supervisor import Survival
        return Survival(self,config)

    def attack_entity(self, target, *, one_hit=False, auto_equip=True, timeout=45, max_attacks=30, min_hp=6, damage_budget=10):
        from .combat import attack
        from .entities import target_ref
        from .skills import run, positive
        target_ref(target)
        if target.source!=self._observation_source:raise ValueError('target belongs to another Game connection; observe again')
        if type(one_hit) is not bool or type(auto_equip) is not bool:raise ValueError('flags must be bool')
        if type(max_attacks) is not int or not 1<=max_attacks<=100:raise ValueError('max_attacks must be 1..100')
        positive(min_hp,'min_hp',20);positive(damage_budget,'damage_budget',100)
        return run(self,'attack_entity',lambda c:attack(c,target,max_attacks,one_hit,auto_equip),timeout=timeout,
                   damage_budget=damage_budget,min_hp=min_hp)

    def flee_from(self, target=None, *, safe_distance=12, timeout=30, search_radius=64, traversal=None, settle_time=1.0):
        from .combat import flee
        from .entities import Entity
        from .skills import run,positive
        from .navigation import Traversal
        if target is not None and not isinstance(target,Entity):raise ValueError('target must be an Entity')
        if target is not None and target.is_player:raise ValueError('player targets are excluded')
        if target is not None and target.source!=self._observation_source:raise ValueError('target belongs to another Game connection; observe again')
        positive(safe_distance,'safe_distance',15);positive(settle_time,'settle_time',5)
        base=traversal or self.traversal or Traversal(allow_swim=True)
        return run(self,'flee_from',lambda c:flee(c,() if target is None else (target,),safe_distance,settle_time),
                   timeout=timeout,search_radius=search_radius,traversal=base,damage_budget=100)

    def defend_self(self, *, radius=8, safe_distance=12, timeout=45, min_hp=6, damage_budget=10, settle_time=1.0):
        from .combat import defend
        from .skills import run,positive
        positive(radius,'radius',16);positive(safe_distance,'safe_distance',15);positive(settle_time,'settle_time',5)
        positive(min_hp,'min_hp',20);positive(damage_budget,'damage_budget',100)
        return run(self,'defend_self',lambda c:defend(c,radius,safe_distance,min_hp,settle_time),timeout=timeout,damage_budget=damage_budget,min_hp=1)

    def attack_ranged(self, target, *, shots=1, charge=.65, timeout=20, min_hp=4, damage_budget=8):
        """Fire existing bow ammunition at an observed non-player entity."""
        from .combat import ranged_attack
        from .entities import target_ref
        from .skills import run,positive
        target_ref(target)
        if target.source!=self._observation_source:raise ValueError('target belongs to another Game connection; observe again')
        if type(shots) is not int or not 1<=shots<=16:raise ValueError('shots must be 1..16')
        positive(charge,'charge',2);positive(min_hp,'min_hp',20);positive(damage_budget,'damage_budget',100)
        return run(self,'attack_ranged',lambda c:ranged_attack(c,target,shots,charge),timeout=timeout,
                   damage_budget=damage_budget,min_hp=min_hp)

    @staticmethod
    def _observed_target(ctx, ref):
        from .skills import Failure
        state=ctx.read();target=next((e for e in state.entities if e.ref==tuple(ref)),None)
        if target is None:raise Failure('target_not_observed')
        return target

    def block_with_shield(self, target, *, duration=1.2, timeout=8, damage_budget=20):
        from .combat import block_with_shield
        from .entities import target_ref
        from .skills import run,positive
        target_ref(target)
        if target.source!=self._observation_source:raise ValueError('target belongs to another Game connection; observe again')
        positive(duration,'duration',5);positive(damage_budget,'damage_budget',100)
        return run(self,'block_with_shield',lambda c:block_with_shield(c,self._observed_target(c,target.ref),duration),
                   timeout=timeout,damage_budget=damage_budget)

    def avoid_projectile(self, target, *, timeout=12, search_radius=24):
        """Shield if available; otherwise take one observed lateral dodge."""
        from .combat import block_with_shield,evade_projectile,_shield_slot
        from .skills import run,Failure
        if hasattr(target,'source') and target.source!=self._observation_source:raise ValueError('target belongs to another Game connection; observe again')
        ref=tuple(target.ref if hasattr(target,'ref') else target)
        if len(ref)!=2 or any(type(x) is not int for x in ref):raise ValueError('target must be an Entity or (id, instance)')
        def execute(c):
            projectile=self._observed_target(c,ref)
            if not projectile.projectile:raise Failure('target_not_projectile')
            if _shield_slot(c.last,c.book) is not None:block_with_shield(c,projectile,.8)
            else:evade_projectile(c,projectile)
        from .navigation import Traversal
        return run(self,'avoid_projectile',execute,timeout=timeout,search_radius=search_radius,
                   traversal=Traversal(allow_swim=True),damage_budget=100)

    def survive_blast(self, target, *, safe_distance=14, timeout=20, search_radius=48):
        """Shield against a nearby visible creeper, or smoothly retreat."""
        from .combat import block_with_shield,flee,_shield_slot
        from .skills import run,positive,Failure
        positive(safe_distance,'safe_distance',15)
        if hasattr(target,'source') and target.source!=self._observation_source:raise ValueError('target belongs to another Game connection; observe again')
        ref=tuple(target.ref if hasattr(target,'ref') else target)
        if len(ref)!=2 or any(type(x) is not int for x in ref):raise ValueError('target must be an Entity or (id, instance)')
        def execute(c):
            threat=self._observed_target(c,ref)
            if not threat.explosive:raise Failure('target_not_explosive')
            if _shield_slot(c.last,c.book) is not None:block_with_shield(c,threat,1.8)
            else:flee(c,(threat,),safe_distance,.8)
        from .navigation import Traversal
        return run(self,'survive_blast',execute,timeout=timeout,search_radius=search_radius,
                   traversal=Traversal(allow_swim=True),damage_budget=100)

    def eat_best_food(self, *, timeout=12, banned_food=None):
        from .combat import eat_best,BANNED_FOOD
        from .skills import run
        banned=BANNED_FOOD if banned_food is None else frozenset(banned_food)
        return run(self,'eat_best_food',lambda c:eat_best(c,banned),timeout=timeout)

    def equip_best_gear(self, *, armor=True, weapon=True, timeout=30):
        from .combat import equip_best
        from .skills import run
        if type(armor) is not bool or type(weapon) is not bool:raise ValueError('flags must be bool')
        return run(self,'equip_best_gear',lambda c:equip_best(c,armor,weapon),timeout=timeout)

    def escape_hazard(self, *, timeout=20):
        from .navigation import Traversal
        from .combat import escape_hazard
        from .skills import run
        return run(self,'escape_hazard',escape_hazard,timeout=timeout,
                   traversal=Traversal(allow_swim=True),damage_budget=100)

    def extinguish_fire(self, *, timeout=20, search_radius=32):
        """Reach observed water and confirm the visible burning overlay clears."""
        from .navigation import Traversal
        from .combat import extinguish_fire
        from .skills import run
        return run(self,'extinguish_fire',extinguish_fire,timeout=timeout,search_radius=search_radius,
                   traversal=Traversal(allow_swim=True),damage_budget=100)

    def recover_air(self, *, timeout=20):
        from .navigation import Traversal
        from .skills import run,regain_air
        # An explicit action permits resurfacing, not arbitrary future diving.
        return run(self,'recover_air',lambda c:regain_air(c),timeout=timeout,
                   traversal=Traversal(allow_swim=True,allow_dive=True),damage_budget=100)

    def recipes_for(self, item):
        """Read versioned grid/cooking recipes without interacting with the world."""
        from .queries import recipes_for
        return recipes_for(self.recipe_book,item)

    def plan_craft(self, item, count=1, *, radius=0):
        """Read-only material plan; readiness does not promise tools/fuel/reachability."""
        from .queries import plan_craft,validate_item_count
        validate_item_count(item,count)
        return plan_craft(self.recipe_book,item,count,self.observe(radius))

    def remember_location(self, name):
        """Remember the currently observed feet position, without moving."""
        from .locations import label,position,MAX_LOCATIONS
        label(name)
        with self._lock:
            if name not in self._locations and len(self._locations)>=MAX_LOCATIONS:raise ValueError('location limit reached')
            p=position(self.observe().position);self._locations[name]=p;return p

    def saved_locations(self):
        with self._lock:return dict(self._locations)

    def forget_location(self, name):
        from .locations import label
        label(name)
        with self._lock:return self._locations.pop(name,None) is not None

    def save_locations(self, path):
        from .locations import save
        return save(path,str(self.endpoint.resolve()),self.saved_locations())

    def load_locations(self, path):
        """Replace the in-memory book only after a complete, same-client validation."""
        from .locations import load
        values=load(path,str(self.endpoint.resolve()))
        with self._lock:self._locations=values
        return self.saved_locations()

    def go_to_location(self, name, **navigation_options):
        """Navigate to a saved feet position using the normal navigation options."""
        from .locations import label
        from .skills import SkillResult
        label(name);positions=self.saved_locations()
        if name not in positions:return SkillResult('go_to_location','blocked','location_unknown',{'name':name})
        from dataclasses import replace
        result=self.navigate_to(positions[name],**navigation_options)
        return replace(result,operation='go_to_location',details=dict(result.details,location=name))

    def inspect_container(self, position, *, timeout=60, search_radius=64, traversal=None):
        """Approach/open a supported chest and report contents without transferring."""
        from .construction import position as node_position
        from .workstations import inspect_container
        from .skills import run
        p=node_position(position)
        return run(self,'inspect_container',lambda c:inspect_container(c,p),timeout=timeout,search_radius=search_radius,traversal=traversal)

    def return_to_entrance(self, *, timeout=600, search_radius=4096, traversal=None, checkpoint=None):
        """Return to the mining entrance, which may itself be inside a cave."""
        from .excursions import go_to_surface
        from .skills import run
        return run(self,'return_to_entrance',lambda c:go_to_surface(c,None,checkpoint),timeout=timeout,search_radius=search_radius,traversal=traversal)

    def upgrade_checkpoint(self, source, destination, *, allow_tool_crafting=False):
        """Explicitly create an upgraded copy of a 0.7 collect/craft ledger."""
        from .persistence import upgrade_checkpoint,owned_count,legacy_request
        if type(allow_tool_crafting) is not bool:raise ValueError('allow_tool_crafting must be boolean')
        source=Path(source).expanduser().resolve()
        if source.stat().st_size>65536:raise ValueError('checkpoint too large')
        import hashlib
        raw=source.read_bytes();expected=hashlib.sha256(raw).hexdigest()
        _,_,item=legacy_request(json.loads(raw))
        if not self._action_lock.acquire(blocking=False):raise ActionError('another_action_running')
        try:
            current=owned_count(self.observe(),item,self.recipe_book)
            return upgrade_checkpoint(source,destination,str(self.endpoint.resolve()),current,allow_tool_crafting=allow_tool_crafting,expected_sha256=expected)
        finally:self._action_lock.release()

    def close(self):
        if self._survival:self._survival.close()
        with self._lock:
            if self._closed:return
            try:
                if self._epoch is not None:self.release_control()
            except (ConnectionError, ProtocolError, ActionError):
                # Best-effort cleanup: a closing game may remove the transport
                # before answering release. Explicit actions still raise errors.
                pass
            finally:
                self._closed=True;self._cancel.set();self._socket.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
