"""Observed, cancellable skills built exclusively on ordinary Course actions."""
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
import math
import threading
import time
from .errors import ActionError, ActionCancelled, CourseError
from .navigation import World, cell, feet, distance
from .recipes import RecipeBook, PlanningError, TABLE


@dataclass(frozen=True)
class SkillResult:
    operation: str
    status: str
    reason: str = ''
    details: dict = field(default_factory=dict)
    trace: tuple = ()
    elapsed: float = 0.0

    @property
    def ok(self):
        return self.status == 'success'

    def to_dict(self):
        return asdict(self)


class Failure(Exception):
    def __init__(self, reason, details=None, status='blocked'):
        self.reason,self.details,self.status = reason,details or {},status


class ActionLock:
    """Reentrant for composed skills, non-blocking across competing scripts."""
    def __init__(self):
        self._lock = threading.RLock()
        self.owner = None
        self.depth = 0

    def acquire(self, blocking=True):
        if not self._lock.acquire(blocking=blocking):
            return False
        self.owner = threading.get_ident()
        self.depth += 1
        return True

    def release(self):
        self.depth -= 1
        if not self.depth:
            self.owner = None
        self._lock.release()

    def locked(self):
        return self.owner is not None

    def other_owner(self):
        return self.owner is not None and self.owner != threading.get_ident()


def positive(value, name, maximum):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f'{name} must be in (0, {maximum}]')
    return value


def count_items(state, token, book):
    return sum(i.count for i in state.inventory['main'].items if book.matches(i.name,token))


class Context:
    def __init__(self, game, timeout, search_radius, book):
        self.game,self.book = game,book
        self.started = time.monotonic()
        self.deadline = self.started+timeout
        self.radius = search_radius
        self.world = World()
        self.origin = None
        self.epoch = game._epoch
        self.trace = []
        self.details = {}
        self.calls = 0
        self.hp = None
        self.min_hp = 1
        self.damage_budget = 0
        self.damage_taken = 0
        self.last = None
        self.blocked = set()
        self.visited = Counter()
        self.table = None
        self.recover = True
        self.allow_tool_crafting = False
        self.tool_recovery = set()
        self.ignored_drops = set()
        self.recoveries = Counter()
        self.terrain_edits = 0
        self.resurfacing = False

    def check(self):
        guard=getattr(self.game,'_survival',None)
        if guard and guard.interrupted():
            raise Failure('survival_interrupted',{'intervention':guard.pending},status='cancelled')
        if self.game._cancel.is_set():
            raise Failure('cancelled',status='cancelled')
        if time.monotonic() >= self.deadline:
            raise Failure('deadline_exceeded',status='timeout')
        if self.calls >= 5000:
            raise Failure('step_limit')

    def log(self, event, **detail):
        if len(self.trace)<1000:
            self.trace.append(dict(event=event, **detail))

    def read(self, radius=0):
        self.check()
        s = self.game.observe(radius)
        self.calls += 1
        self.last = s
        if s.control!='agent' or s.control_epoch!=self.epoch:
            raise Failure('control_released',status='cancelled')
        if s.dead:
            raise Failure('player_dead')
        previous_hp=self.hp
        lost=max(0,previous_hp-s.hp) if previous_hp is not None else 0
        self.hp=s.hp
        if lost:
            self.damage_taken+=lost
            self.log('damage_observed',hp=s.hp,lost=lost,total=self.damage_taken)
        guard=getattr(self.game,'_survival',None)
        if guard and hasattr(guard,'on_observation'):
            guard.on_observation(s)
            self.check()
        if not self.resurfacing and getattr(s,'raw',{}).get('breath',11)<(7 if self.world.traversal.allow_dive else 5):
            raise Failure('low_breath',{'breath':s.raw['breath']})
        if lost and self.damage_taken>self.damage_budget:
            raise Failure('player_damaged' if self.damage_budget==0 else 'damage_budget_exceeded',
                          {'hp':s.hp,'previous_hp':previous_hp,'damage_taken':self.damage_taken})
        if s.hp < self.min_hp:raise Failure('health_floor',{'hp':s.hp,'minimum':self.min_hp})
        if self.origin is None:
            self.origin=s.position
        if radius:
            try:
                self.world.update(s)
                # Only the cells occupied at escape start may be exited through.
                # New hazardous cells remain blocked; observations stay unchanged.
                for pos in getattr(self,'escape_cells',()):
                    node=self.world.nodes.get(pos)
                    if node:self.world.nodes[pos]=replace(node,damage=0,drowning=0)
            except ValueError as exc:
                raise Failure('node_geometry_unavailable',{'message':str(exc)})
        return s

    def sleep(self, seconds):
        self.check()
        if self.game._cancel.wait(min(seconds,max(0,self.deadline-time.monotonic()))):
            raise Failure('cancelled',status='cancelled')
        self.check()

    def wait(self, predicate, timeout=4, reason='confirmation_timeout', radius=0):
        end = min(self.deadline,time.monotonic()+timeout)
        while time.monotonic()<end:
            s=self.read(radius)
            if predicate(s):
                return s
            self.sleep(.08)
        self.check()
        raise Failure(reason)

    def within(self, p):
        return distance(feet(p),self.origin)<=self.radius

    def stop_input(self):
        if not self.game._closed:
            self.game._submit('stop')

    def pulse(self, keys, seconds):
        self.check()
        self.game._submit('input',keys=list(keys),duration_ms=max(1,math.ceil(seconds*1000)))
        end=time.monotonic()+seconds
        try:
            while time.monotonic()<end:
                self.sleep(min(.08,end-time.monotonic()))
                self.read()
        finally:
            self.stop_input()
        self.sleep(.08)
        return self.read(6)


def run(game, operation, fn, *, timeout, search_radius=32, book=None, traversal=None, damage_budget=0, min_hp=1):
    if getattr(game,'_motion',None) is not None:raise ActionError('finish_motion_scope_before_skill')
    positive(timeout,'timeout',1800)
    positive(search_radius,'search_radius',4096)
    if not game._action_lock.acquire(blocking=False):
        guard=getattr(game,'_survival',None)
        if guard and guard.busy:
            return SkillResult(operation,'cancelled','survival_interrupted',
                               {'intervention':guard.pending,'started':False})
        raise ActionError('another_action_running')
    ctx=None
    try:
        if game._epoch is None:
            return SkillResult(operation,'blocked','control_required',{'message':'Use game.control() or take_control() first.'})
        game._cancel.clear()
        game._skill_depth+=1
        ctx=Context(game,timeout,search_radius,book or game.recipe_book)
        ctx.operation=operation
        ctx.damage_budget=damage_budget;ctx.min_hp=min_hp
        memory=getattr(game,'exploration_memory',None)
        if memory is not None:
            ctx.world,ctx.visited=memory.load(str(game.endpoint.resolve()))
        ctx.world.planning_check=ctx.check
        policy=traversal if traversal is not None else getattr(game,'traversal',None)
        if policy is not None:
            from .navigation import Traversal
            if not isinstance(policy,Traversal):raise ValueError('traversal must be Traversal')
            ctx.world.traversal=policy
        status,reason='success',''
        try:
            # The first snapshot must reach the bounded recovery dispatcher.
            # Only the breath check is deferred; control/death/damage still apply.
            ctx.resurfacing=ctx.world.traversal.allow_dive
            try:initial=ctx.read()
            finally:ctx.resurfacing=False
            policy=ctx.world.traversal
            if policy.build_with:
                d=game._request('inspect_item',name=policy.build_with)
                if not d['full_cube'] or not d['walkable'] or d['liquid'] or d['damage_per_second'] or d['groups'].get('falling_node',0):raise Failure('building_material_not_full_cube')
            if policy.allow_dive and 'swim_height' not in getattr(game,'capabilities',()):raise Failure('swim_control_unavailable')
            if policy.allow_dive and getattr(initial,'raw',{}).get('breath',10)<7:regain_air(ctx)
            fn(ctx)
        except Failure as exc:
            status,reason=exc.status,exc.reason
            ctx.details.update(exc.details)
        except PlanningError as exc:
            status,reason='blocked',exc.code
            ctx.details.update(plan_error=exc.detail)
        except (CourseError,ActionCancelled) as exc:
            status='cancelled' if isinstance(exc,ActionCancelled) or getattr(exc,'code','') in ('control_released','stale_control_epoch','manual_control_active') else 'blocked'
            reason=('survival_interrupted' if str(exc)=='survival_interrupted' else 'cancelled') if isinstance(exc,ActionCancelled) else getattr(exc,'code','connection_error')
            if reason=='survival_interrupted':ctx.details['intervention']=getattr(game,'_survival',None).pending if getattr(game,'_survival',None) else None
            ctx.details.update(message=str(exc))
        player_position=ctx.last.position if ctx.last else None
        ctx.details.update(observations=ctx.calls,player_position=player_position)
        ctx.details.setdefault('position',player_position)
        return SkillResult(operation,status,reason,dict(ctx.details),tuple(ctx.trace),round(time.monotonic()-ctx.started,3))
    except Failure as exc:
        return SkillResult(operation,exc.status,exc.reason,exc.details)
    finally:
        if ctx:
            memory=getattr(game,'exploration_memory',None)
            if memory is not None:memory.store(str(game.endpoint.resolve()),ctx.world,ctx.visited)
            try:ctx.stop_input()
            except CourseError:pass
        game._skill_depth=max(0,game._skill_depth-1)
        game._action_lock.release()


def face(ctx, point):
    ctx.check()
    state=ctx.read()
    dx,dy,dz=[point[i]-state.eye[i] for i in range(3)]
    yaw=math.degrees(math.atan2(-dx,dz))
    pitch=max(-89.9,min(89.9,math.degrees(math.atan2(-dy,math.hypot(dx,dz)))))
    if abs((state.yaw-yaw+180)%360-180)<.5 and abs(state.pitch-pitch)<.5:return state
    end=min(ctx.deadline,time.monotonic()+1.7)
    try:
        while time.monotonic()<end:
            state=ctx.read()
            if abs((state.yaw-yaw+180)%360-180)<.5 and abs(state.pitch-pitch)<.5:
                return state
            # Native steer leases are intentionally capped at one second.
            # Renew the same target while its velocity-aware easing finishes;
            # this retains angular velocity and never restarts the turn.
            ctx.game._submit('steer',heading=yaw,pitch=pitch,speed=0,jump=False,duration_ms=1000)
            ctx.sleep(.04)
        raise Failure('aim_unconfirmed')
    finally:
        ctx.stop_input()


def approach_and_face(ctx,target,reason='target_not_in_crosshair',for_dig=False):
    target=tuple(target)
    if not hasattr(ctx,'interaction_stances'):ctx.interaction_stances={}
    rejected=ctx.interaction_stances.setdefault(target,set())
    for _ in range(8):
        navigate(ctx,target,approach=True,for_dig=for_dig)
        state=ctx.read(6);aim=ctx.world.interaction_point(state.eye,target)
        if aim is not None:face(ctx,aim)
        try:return ctx.wait(lambda s:s.pointed_node==target,timeout=.4,reason=reason)
        except Failure as exc:
            if exc.reason!=reason:raise
            stance=ctx.world.start(ctx.read(6).position)
            if stance is None:raise
            rejected.add(stance);ctx.log('interaction_reposition',target=target,blocked_stance=stance)
    raise Failure(reason,{'target':target})


def route_runout(ctx, origin, target):
    """Observed flat stopping room for a short leased waypoint handoff."""
    dx,dz=target[0]-origin[0],target[2]-origin[2];length=math.hypot(dx,dz)
    if length<=.01 or abs(origin[1]-target[1])>=.12:return False
    runway=max(1.0,ctx.world.physics['walk_speed']*.4+.3)
    extension=(target[0]+dx/length*runway,target[1],target[2]+dz/length*runway)
    return (ctx.within(cell(extension)) and ctx.world.corridor_clear(origin,target)
            and ctx.world.corridor_clear(target,extension)
            and getattr(ctx,'movement_segment_allowed',lambda a,b:True)(origin,extension))


def follow_path(ctx, path, target, tolerance=.28, partial=False, until=None, through=False, cruise=False):
    """Continuous look-ahead path tracking with native per-frame camera easing.

    A* cells describe topology, not places at which the player must stop. Hold a
    renewable analog movement lease while advancing through those cells.
    """
    points=[ctx.world.point(p) for p in path]
    segment_allowed=getattr(ctx,'movement_segment_allowed',lambda a,b:True)
    points[-1]=tuple(target)
    if ctx.world.surface_water(path[-1]):
        points[-1]=(target[0],ctx.world.point(path[-1])[1],target[2])
    index=1 if len(points)>1 else 0
    last_scan=0.0
    shortcut_index=None
    surface_departure=False
    first_observation=True
    last_progress=time.monotonic()
    progress_index=index
    best_distance=math.inf
    tick=.05
    while True:
        began=time.monotonic()
        radius=6 if began-last_scan>=.20 else 0
        state=ctx.read(radius)
        if radius:last_scan=began
        if until is not None and until(state):return True,None
        pos=state.position
        if first_observation:
            first_observation=False
            surface_departure=(ctx.world.surface_water(path[0]) and state.raw.get('in_liquid',False)
                               and pos[1]<points[0][1]-.55)
            if surface_departure:
                # A one-cell route still has a precise horizontal destination.
                # Add a vertical departure point rather than overwriting it.
                if len(points)==1:
                    path=[path[0],path[0]];points.insert(0,points[0])
                points[0]=(pos[0],points[0][1],pos[2]);index=progress_index=0
        if surface_departure and abs(pos[1]-points[0][1])<.2:
            surface_departure=False
        # Advancing through a waypoint does not release the input lease.
        while not surface_departure and index<len(points)-1:
            point,previous=points[index],points[max(0,index-1)]
            dx,dz=point[0]-previous[0],point[2]-previous[2]
            passed=(pos[0]-point[0])*dx+(pos[2]-point[2])*dz>=0
            # A rounded corner can enter the outgoing leg without ever crossing
            # the incoming endpoint plane. Recognize that forward projection.
            following=points[index+1]
            ox,oz=following[0]-point[0],following[2]-point[2]
            length=math.hypot(ox,oz)
            along=((pos[0]-point[0])*ox+(pos[2]-point[2])*oz)/max(length,.001)
            lateral=abs((pos[0]-point[0])*oz-(pos[2]-point[2])*ox)/max(length,.001)
            rounded=abs(following[1]-point[1])<.12 and along>0 and lateral<.65
            # During an upward stair jump the body can already be beyond a
            # tread and above its height band. Do not steer backwards/downward
            # merely to touch that obsolete waypoint's centre.
            rising_passed=(passed and point[1]>previous[1] and following[1]>=point[1]
                           and point[1]-.1<=pos[1]<=following[1]+1.5)
            if (rising_passed or (abs(pos[1]-point[1])<.55 and (math.hypot(pos[0]-point[0],pos[2]-point[2])<.40 or passed or rounded))) and segment_allowed(pos,following):
                index+=1
            else:break
        remaining=distance(pos,points[-1])
        velocity=state.raw.get('velocity',(0,0,0))
        horizontal_speed=math.hypot(velocity[0],velocity[2])
        floor=ctx.world.nodes.get(cell((pos[0],pos[1]-.05,pos[2]))) if hasattr(ctx.world,'nodes') else None
        slippery=(floor.groups or {}).get('slippery',0) if floor else 0
        arrival_braking=(index==len(points)-1 and not partial and not through and remaining<=tolerance and slippery>0)
        if partial and radius and remaining<2.0:
            return True,None
        if (index==len(points)-1 and remaining<=tolerance and (not arrival_braking or horizontal_speed<.25)
                and (not (ctx.world.surface_water(path[index]) or ctx.world.swimmable(path[index]))
                     or abs(state.raw.get('velocity',(0,0,0))[1])<.4)):
            if cruise and not route_runout(ctx,pos,points[-1]):ctx.stop_input()
            return True,None
        current=ctx.world.start(pos)
        if current is None:
            # The support cell may briefly be below the player during a jump.
            if time.monotonic()-last_progress>1.3:return False,(path[max(0,index-1)],path[index])
        waypoint=points[index]
        if not ctx.world.standable(path[index]):
            return False,(current or path[max(0,index-1)],path[index])
        # Choose a farther point only if the entire swept footprint is known,
        # supported and clear. This joins straight cells and rounds open bends.
        aim=waypoint
        flat_pos=(pos[0],ctx.world.point(current)[1],pos[2]) if current else pos
        if (not state.raw.get('in_liquid',False) and not ctx.world.surface_water(path[index])
                and not ctx.world.swimmable(path[index])
                and abs(pos[1]-flat_pos[1])<.15 and abs(waypoint[1]-flat_pos[1])<.12):
            if shortcut_index==index and not ctx.world.corridor_clear(flat_pos,waypoint):
                return False,(current or path[max(0,index-1)],path[index])
            # Pull the taut string through a bounded, observed flat run.
            # A short moving lattice target alternates between x/z corners even
            # in an empty room. Prefer its farthest visible endpoint instead.
            end=index
            for j in range(index,len(points)):
                if abs(points[j][1]-flat_pos[1])>.12:break
                if math.hypot(points[j][0]-pos[0],points[j][2]-pos[2])>8:break
                end=j
            for j in range(end,index-1,-1):
                candidate=points[j]
                offset=.45 if ctx.world.surface_water(path[index]) else 0
                origin=(flat_pos[0],flat_pos[1]+offset,flat_pos[2])
                endpoint=(candidate[0],candidate[1]+offset,candidate[2])
                if ctx.world.corridor_clear(origin,endpoint) and segment_allowed(pos,candidate):
                    aim=waypoint=candidate
                    if j>index:index=j;shortcut_index=j
                    break
        # String-pull only through fully observed water. Chasing successive
        # lattice corners made open diagonal swims weave and vertical ascents
        # turn back towards obsolete cell centres.
        if state.raw.get('in_liquid',False) and not surface_departure:
            for j in range(len(points)-1,index-1,-1):
                if not all(ctx.world.surface_water(p) or ctx.world.swimmable(p) for p in path[index:j+1]):continue
                if ctx.world.swim_corridor_clear(pos,points[j]) and segment_allowed(pos,points[j]):
                    aim=waypoint=points[j];index=j
                    break
        # Geometric string-pulling must preserve the caller's transient
        # constraints too (for example observed mobs), on every actual leg.
        if not segment_allowed(pos,aim):
            ctx.stop_input()
            return False,(current or path[max(0,index-1)],path[index])
        dx,dz=aim[0]-pos[0],aim[2]-pos[2]
        horizontal=math.hypot(dx,dz)
        heading=math.degrees(math.atan2(-dx,dz)) if horizontal>.05 else getattr(state,'yaw',0)
        departure=points[max(0,index-1)]
        gap=math.hypot(waypoint[0]-departure[0],waypoint[2]-departure[2])>1.5 and not ctx.world.corridor_clear(departure,waypoint)
        if gap and math.hypot(waypoint[0]-departure[0],waypoint[2]-departure[2])>2.5:
            velocity=state.raw.get('velocity',(0,0,0));actual=math.hypot(velocity[0],velocity[2])
            leg=math.hypot(waypoint[0]-departure[0],waypoint[2]-departure[2])
            ux,uz=(waypoint[0]-departure[0])/leg,(waypoint[2]-departure[2])/leg
            along=(pos[0]-departure[0])*ux+(pos[2]-departure[2])*uz
            key=('runup',path[max(0,index-1)],path[index])
            if abs(along)<.3 and actual<ctx.world.physics['walk_speed']*.65 and not ctx.recoveries[key]:
                back=(departure[0]-ux,departure[1],departure[2]-uz);back_node=ctx.world.start(back)
                if back_node and ctx.world.corridor_clear(back,departure):
                    ctx.recoveries[key]+=1;ctx.log('jump_runup',position=back)
                    # Back up while watching the landing, rather than turning
                    # away from the gap and whipping around for the run-up.
                    prior_direction=getattr(ctx,'movement_look_direction',None)
                    ctx.movement_look_direction=(math.degrees(math.atan2(-ux,uz)),0)
                    try:ok,_=follow_path(ctx,[path[max(0,index-1)],back_node],back,.18)
                    finally:ctx.movement_look_direction=prior_direction
                    if not ok:raise Failure('jump_runup_blocked')
                    return False,None # Replan from the runway; no edge is blocked.
                raise Failure('jump_runup_unavailable')
        climbing=ctx.world.ladder(path[index]) or state.raw.get('climbing',False)
        swimming=ctx.world.surface_water(path[index]) or ctx.world.swimmable(path[index]) or state.raw.get('in_liquid',False)
        wet=state.raw.get('in_liquid',False)
        # Ground steps use actual server step height. On shore, retain the
        # swim controller until grounded instead of carrying a held jump out
        # of the water and launching another full-height land jump.
        step=ctx.world.physics.get('step_height',.6)
        jump=(waypoint[1]-pos[1]>(.12 if climbing else step+.02) or (gap and horizontal>.65))
        if gap:
            leg=math.hypot(waypoint[0]-departure[0],waypoint[2]-departure[2])
            along=((pos[0]-departure[0])*(waypoint[0]-departure[0])+(pos[2]-departure[2])*(waypoint[2]-departure[2]))/leg
            if leg>2.5 and along<-.05:jump=False
        if wet:jump=False
        if ctx.world.surface_water(path[index]):
            vy=state.raw.get('velocity',(0,0,0))[1]
            # Brake ascent before crossing the engine's liquid/air hysteresis.
            jump=state.raw.get('in_liquid',False) and pos[1]+vy*.18<waypoint[1]-.25
        sneak=climbing and waypoint[1]-pos[1]<-.12
        # Slow smoothly near a final stop or a tight corner; do not pulse keys.
        speed=1.0 if cruise and index==len(points)-1 and route_runout(ctx,pos,waypoint) else min(1.0,max(.16,horizontal/1.25))
        if jump:speed=max(.6,speed)
        if climbing or ctx.world.swimmable(path[index]):speed=min(.6,horizontal*1.8)
        if swimming:speed=min(.8,speed,horizontal*1.8)
        if not partial and not through and remaining<1.1:speed=min(speed,max(.14,remaining/1.1))
        if slippery and not partial and not through and index==len(points)-1:
            # Releasing keys on ice halves the native acceleration again.
            # Brake for the observed surface and server physics before arrival,
            # not after declaring success while the character is still sliding.
            deceleration=ctx.world.physics.get('ground_acceleration',3)/(slippery*2+1)
            budget=max(0,remaining-.15-horizontal_speed*.10)
            speed=min(speed,math.sqrt(2*max(.01,deceleration)*budget)/max(.1,ctx.world.physics['walk_speed']))
            if arrival_braking:speed=0;heading=getattr(state,'yaw',heading)

        velocity=state.raw.get('velocity',(0,0,0))
        actual=math.hypot(velocity[0],velocity[2])
        if actual>.3 and horizontal>.01:
            alignment=(velocity[0]*dx+velocity[2]*dz)/(actual*horizontal)
            speed*=max(.4,(alignment+1)/2)
        # Pure ascent/descent needs no heading correction for a few centimetres
        # of horizontal error. Otherwise near-zero vectors spin the camera
        # through arbitrary headings while waiting for vertical arrival.
        settling_at_goal=(index==len(points)-1 and not partial and not state.raw.get('touching_ground',True)
                          and abs(waypoint[1]-pos[1])<1.5)
        landing_on_segment=(not state.raw.get('touching_ground',True) and waypoint[1]<pos[1]-.1)
        if (swimming or climbing or settling_at_goal or landing_on_segment) and horizontal<.18:
            speed=0.0;heading=getattr(state,'yaw',heading)
        steering=dict(heading=heading,speed=speed,jump=jump,duration_ms=400)
        look_at=getattr(ctx,'movement_look_target',None)
        if look_at is not None and 'independent_heading' in getattr(ctx.game,'capabilities',()):
            lx,ly,lz=(look_at[i]-state.eye[i] for i in range(3))
            steering.update(move_heading=heading,heading=math.degrees(math.atan2(-lx,lz)),
                            pitch=max(-89.9,min(89.9,math.degrees(math.atan2(-ly,math.hypot(lx,lz))))))
        direction=getattr(ctx,'movement_look_direction',None)
        if direction is not None and 'independent_heading' in getattr(ctx.game,'capabilities',()):
            steering.update(move_heading=heading,heading=direction[0],pitch=direction[1])
        if (ctx.world.surface_water(path[index]) or ctx.world.swimmable(path[index]) or wet) and 'swim_height' in getattr(ctx.game,'capabilities',()):
            steering['swim_y']=waypoint[1]+(.08 if wet and not (ctx.world.surface_water(path[index]) or ctx.world.swimmable(path[index])) else 0)
            steering['jump']=False
        if wet and 'swim_y' in steering and not surface_departure:
            # Start lifting before the player's collision box reaches the bank,
            # while staying below the water surface until the shore step.
            for j in range(index,min(len(path),index+3)):
                if not (ctx.world.surface_water(path[j]) or ctx.world.swimmable(path[j])):
                    bank=points[j]
                    if .15<bank[1]-pos[1]<.8 and math.hypot(bank[0]-pos[0],bank[2]-pos[2])<2.0:
                        steering['swim_y']=bank[1]-.04
                        if index<len(path)-1:steering['speed']=max(.6,steering['speed'])
                    break
        if sneak:steering['sneak']=True
        ctx.game._submit('steer',**steering)
        to_waypoint=distance(pos,waypoint)
        if index>progress_index or to_waypoint<best_distance-.10:
            last_progress=time.monotonic();progress_index=index;best_distance=to_waypoint
        elif time.monotonic()-last_progress>1.4:
            return False,(current or path[max(0,index-1)],path[index])
        ctx.sleep(max(0,tick-(time.monotonic()-began)))


def regain_air(ctx):
    """Follow an observed route to air before the normal breath guard expires."""
    ctx.resurfacing=True
    try:
        state=ctx.read(6)
        # Already in observed dry, collision-free space: recover in place rather
        # than looking for a water surface. Full breath alone is insufficient:
        # a newly submerged player can still have a full breath meter.
        if ctx.world.body_clear(state.position):
            ctx.stop_input()
            initial_breath=state.raw.get('breath',0)
            end=min(ctx.deadline,time.monotonic()+8)
            while True:
                if state.raw.get('breath',0)>=9:
                    outcome='already_breathing' if initial_breath>=9 else 'breath_recovered'
                    ctx.details['outcome']=outcome
                    ctx.log(outcome,breath=state.raw['breath']);return
                if time.monotonic()>=end:raise Failure('breath_recovery_unconfirmed')
                ctx.sleep(.10);state=ctx.read(6)
                if not ctx.world.body_clear(state.position):break
        start=ctx.world.start(state.position)
        path,_=ctx.world.path(start,ctx.world.surface_water,blocked=ctx.blocked,within=ctx.within,max_nodes=5000)
        if not path:raise Failure('air_route_unavailable',{'breath':state.raw.get('breath')})
        target=ctx.world.point(path[-1]);ctx.log('resurface',target=target,breath=state.raw.get('breath'))
        ok,_=follow_path(ctx,path,target,.28)
        if not ok:raise Failure('air_route_blocked')
        end=min(ctx.deadline,time.monotonic()+8)
        while time.monotonic()<end:
            state=ctx.read()
            if state.raw.get('breath',0)>=9:
                ctx.log('breath_recovered',breath=state.raw['breath']);return
            ctx.game._submit('steer',heading=state.yaw,speed=0,jump=False,swim_y=target[1],duration_ms=400)
            ctx.sleep(.10)
        raise Failure('breath_recovery_unconfirmed')
    finally:
        ctx.resurfacing=False;ctx.stop_input()


def navigate(ctx, target, tolerance=.45, approach=False, until=None, look_at=None, look_direction=None, through=False, for_dig=False):
    previous=getattr(ctx,'movement_look_target',None)
    previous_direction=getattr(ctx,'movement_look_direction',None)
    ctx.movement_look_direction=look_direction
    ctx.movement_look_target=tuple(target) if approach else look_at
    try:
        for attempt in range(3):
            try:return _navigate(ctx,target,tolerance,approach,until,through,for_dig)
            except Failure as exc:
                if exc.reason!='low_breath' or not ctx.world.traversal.allow_dive or attempt==2:raise
                regain_air(ctx)
    finally:
        ctx.movement_look_target=previous
        ctx.movement_look_direction=previous_direction


def _navigate(ctx, target, tolerance=.45, approach=False, until=None, through=False, for_dig=False):
    if 'steer' not in getattr(ctx.game,'capabilities',()):
        raise Failure('smooth_steering_unavailable',{'message':'Use Course client 0.3 or newer.'})
    target=tuple(target)
    attempts=Counter()
    exploration_goal=None
    try:
        for _ in range(min(2048,max(120,int(getattr(ctx,"radius",64)*2)))):
            s=ctx.read(6)
            if until is not None and until(s):return s
            start=ctx.world.start(s.position)
            if start is None:
                ctx.sleep(.15)
                s=ctx.read(6);start=ctx.world.start(s.position)
                if start is None:raise Failure('no_supported_start',{'position':s.position})
            goal_node=ctx.world.start(target)
            rejected=getattr(ctx,'interaction_stances',{}).get(target,set())
            approach_goal=ctx.world.harvest_approach if for_dig else ctx.world.approach
            goal=(lambda p:p not in rejected and approach_goal(p,target)) if approach else (lambda p:p==goal_node)
            actual_target=target
            if not approach and goal_node is not None and not ctx.world.swimmable(goal_node):
                supported_target=ctx.world.point(goal_node)
                if abs(supported_target[1]-target[1])<=.2:
                    actual_target=(target[0],supported_target[1],target[2])
            if not approach and ctx.world.surface_water(goal_node or cell(target)):
                water_goal=goal_node
                if water_goal:actual_target=(target[0],ctx.world.point(water_goal)[1],target[2])
            if ((approach and goal(start)) or (not approach and distance(s.position,actual_target)<=tolerance)) and (
                    not (ctx.world.surface_water(start) or ctx.world.swimmable(start))
                    or abs(getattr(s,'raw',{}).get('velocity',(0,0,0))[1])<.4):
                ctx.log('arrived',position=s.position,target=target)
                return s
            from .bridging import direct_bridge
            if not approach and direct_bridge(ctx,actual_target):
                exploration_goal=None
                continue
            # If the goal is still beyond observations, advance through a useful
            # frontier instead of exhaustively proving that unknown space has no path.
            planning_goal=goal
            if goal_node is None and not approach:
                planning_goal=lambda p:goal(p) or (ctx.world.frontier(p) and attempts[p]<2 and distance(feet(p),target)<distance(s.position,target)-2)
            # An unseen distant goal must not make the planner choose an
            # arbitrary cardinal frontier in an otherwise open field. Advance
            # along the requested bearing only through a fully observed,
            # supported flat ray; keep the normal graph fallback at obstacles.
            ray=None
            if not approach and goal_node is None and abs(s.position[1]-target[1])<=.2:
                length=math.hypot(target[0]-s.position[0],target[2]-s.position[2])
                if length>5:
                    endpoint=(s.position[0]+(target[0]-s.position[0])*5/length,s.position[1],s.position[2]+(target[2]-s.position[2])*5/length)
                    node=ctx.world.start(endpoint)
                    if (node is not None and ctx.within(node)
                            and not ctx.world.surface_water(start) and not ctx.world.swimmable(start)
                            and not ctx.world.surface_water(node) and not ctx.world.swimmable(node)
                            and ctx.world.corridor_clear(s.position,endpoint)):
                        ray=([start,node],endpoint)
            if ray:path,reachable=ray[0],{}
            else:path,reachable=ctx.world.path(start,planning_goal,lambda p:max(0,distance(feet(p),target)-(3 if approach else 0)),blocked=ctx.blocked,within=ctx.within)
            partial=path is None or not goal(path[-1])
            if path is None:
                frontiers=[p for p in reachable if ctx.world.frontier(p) and p!=start and attempts[p]<2]
                if not frontiers:
                    if ctx.blocked and getattr(ctx,'recover',False) and ctx.recoveries['navigation']<2:
                        ctx.stop_input();ctx.sleep(.4);ctx.blocked.clear();ctx.recoveries['navigation']+=1
                        ctx.log('retry_transient_obstacle',attempt=ctx.recoveries['navigation']);continue
                    raise Failure('no_path',{'target':target,'position':s.position})
                if exploration_goal not in frontiers or exploration_goal==start:
                    if exploration_goal==start:attempts[exploration_goal]+=1
                    exploration_goal=min(frontiers,key=lambda p:distance(feet(p),target)+attempts[p]*6+.1*reachable[p])
                path,_=ctx.world.path(start,lambda p:p==exploration_goal,blocked=ctx.blocked,within=ctx.within)
            pending=next(((i,tuple(ctx.world.edge_actions.get((a,b),())))
                          for i,(a,b) in enumerate(zip(path,path[1:]))
                          if any(k!='jump' for k,_ in ctx.world.edge_actions.get((a,b),()))),None)
            if pending:
                i,actions=pending
                if i:
                    ok,edge=follow_path(ctx,path[:i+1],ctx.world.point(path[i]),.24)
                    if not ok:
                        ctx.stop_input()
                        if edge:ctx.blocked.add(edge)
                        continue
                ctx.stop_input()
                from .bridging import stream_bridge
                if stream_bridge(ctx,actions,actual_target):
                    exploration_goal=None
                    continue
                try:terrain_actions(ctx,actions)
                except Failure as exc:
                    if exc.reason not in ('interaction_unconfirmed','interaction_not_in_crosshair','unstable_mining_roof','placement_unconfirmed','no_placement_face','placement_face_not_in_crosshair'):
                        raise
                    # A locked/non-interactive door is an obstacle, not a reason
                    # to toggle it forever. Prefer another observed route.
                    for kind,pos in actions:
                        ctx.world.unusable.add(pos)
                        if kind=='interact':
                            for dy in (-1,1):
                                other=(pos[0],pos[1]+dy,pos[2]);n=ctx.world.nodes.get(other)
                                if n and ctx.world.interactive(n):ctx.world.unusable.add(other)
                    ctx.blocked.add((path[i],path[i+1]))
                    ctx.details.setdefault('terrain_blocked',[]).append(dict(reason=exc.reason,actions=actions))
                    ctx.log('terrain_replan',reason=exc.reason)
                exploration_goal=None
                continue
            destination=ray[1] if ray else (ctx.world.point(path[-1]) if partial or approach else actual_target)
            ctx.log('follow_path',cells=len(path),destination=destination,partial=partial)
            args=(ctx,path,destination,tolerance if through else min(.28,tolerance),partial)
            options={}
            if until is not None:options['until']=until
            # Recheck run-out during following too: an obstacle may appear
            # after planning, or the final approach may come from another side.
            handoff=through and not partial and route_runout(ctx,s.position,destination)
            if handoff:options.update(through=True,cruise=True)
            ok,edge=follow_path(*args,**options)
            if not ok:
                ctx.stop_input();exploration_goal=None
                if edge:ctx.blocked.add(edge)
                ctx.log('replan',blocked_edge=edge)
                # A blocked sub-cell endpoint has no graph edge to reroute:
                # A* immediately returns the same one-cell path again. Report
                # the failed stance so pickup can try another landing instead
                # of consuming its entire deadline against the same wall.
                if edge and edge[0]==edge[1]:
                    raise Failure('movement_blocked',{'target':target,'blocked_edge':edge})
                if len(ctx.blocked)>40:raise Failure('movement_blocked')
            elif not partial:
                if through:
                    if not handoff:ctx.stop_input()
                    ctx.log('passed_waypoint',position=ctx.last.position,target=target)
                    return ctx.last
                if ctx.world.surface_water(path[-1]) or ctx.world.swimmable(path[-1]):
                    # In water, releasing input then 'settling' means sinking.
                    # Confirm arrival while the height controller is still active.
                    ctx.log('arrived',position=ctx.last.position,target=target)
                    return ctx.last
                ctx.stop_input();ctx.sleep(.12)
            # Frontiers extend the plan while the input remains leased. Normal
            # passage through a cell or a path refresh is not a stop condition.
        raise Failure('navigation_limit')
    except BaseException:
        if through:ctx.stop_input()
        raise
    finally:
        # Only an internal route handoff retains the short native lease.
        # The enclosing run() still stops on every public return or failure.
        if not through:ctx.stop_input()


def place_scaffold(ctx,item,target):
    """Place an adjacent bridge support via normal crouch/aim/right-click.

    Standing at a voxel centre hides a bridge's vertical attachment face.
    Crouch to a measured 0.58-block overhang while the player box still has
    substantial support, then click the observed face. Never step into air.
    """
    state=ctx.read(6);start=ctx.world.start(state.position)
    if start is None:raise Failure('no_supported_start')
    support=(start[0],round(start[1]-1),start[2]);node=ctx.world.nodes.get(support)
    delta=tuple(target[i]-support[i] for i in range(3))
    if not node or not node.full_cube or not node.harmless or delta[1] or abs(delta[0])+abs(delta[2])!=1:
        return place_block(ctx,item,target)
    slot=state.inventory['main'].find(item)
    if slot is None:raise Failure('item_not_held',{'item':item})
    wield_slot(ctx,slot)
    stance=(support[0]+delta[0]*.58,support[1]+.5,support[2]+delta[2]*.58)
    end=min(ctx.deadline,time.monotonic()+5)
    try:
        while time.monotonic()<end:
            state=ctx.read();dx,dz=stance[0]-state.position[0],stance[2]-state.position[2]
            if math.hypot(dx,dz)<.025:break
            if abs(state.position[1]-stance[1])>.12:raise Failure('bridge_stance_unstable')
            ctx.game._submit('steer',heading=math.degrees(math.atan2(-dx,dz)),speed=min(.4,max(.06,math.hypot(dx,dz)*1.5)),jump=False,sneak=True,duration_ms=300)
            ctx.sleep(.04)
        else:raise Failure('bridge_stance_unconfirmed')
        ctx.stop_input();ctx.sleep(.08)
        if distance(ctx.read().position,stance)>.08:raise Failure('bridge_stance_unconfirmed')
        aim=(support[0]+delta[0]*.499,support[1],support[2]+delta[2]*.499)
        face(ctx,aim)
        if ctx.read().pointed_node!=support:raise Failure('placement_face_not_in_crosshair')
        before=ctx.read();count=count_items(before,item,ctx.book)
        ctx.game.hold(['sneak','place'],.12)
        ctx.wait(lambda s:ctx.world.nodes.get(target) and ctx.world.nodes[target].name==item,timeout=3,reason='placement_unconfirmed',radius=6)
        ctx.wait(lambda s:s.inventory_revision>before.inventory_revision and count_items(s,item,ctx.book)==count-1,reason='placement_inventory_unconfirmed')
        ctx.log('bridge_support_confirmed',item=item,position=target)
    finally:ctx.stop_input()


def terrain_actions(ctx, actions):
    """Perform one planned edge's edits, then let navigate observe and replan.

    No virtual block is inserted into the observed map. Server confirmation is
    required for every edit, and nested approach navigation cannot edit terrain.
    """
    policy=ctx.world.traversal
    if ctx.terrain_edits+len(actions)>policy.edit_budget:
        raise Failure('terrain_edit_budget',{'used':ctx.terrain_edits,'limit':policy.edit_budget})
    previous=dict(ctx.details)
    ctx.world.traversal=replace(policy,allow_interact=False,allow_dig=False,build_with=None)
    changes=ctx.details.setdefault('terrain_changes',[])
    try:
        for kind,pos in actions:
            ctx.read(6);node=ctx.world.nodes.get(pos)
            if node is None:raise Failure('terrain_target_unobserved',{'position':pos})
            if kind=='interact':
                if not ctx.world.interactive(node):continue
                # Aim at the real thin collision box, not the empty cell centre.
                before=(node.name,node.collision_boxes)
                aims=[tuple(pos[i]+(box[i]+box[i+3])/2 for i in range(3)) for box in node.collision_boxes]
                hit=False
                for aim in aims:
                    face(ctx,aim)
                    if ctx.read().pointed_node==pos:hit=True;break
                if not hit:raise Failure('interaction_not_in_crosshair',{'position':pos})
                ctx.game.use(.08)
                ctx.wait(lambda s:ctx.world.nodes.get(pos) and
                         (ctx.world.nodes[pos].name,ctx.world.nodes[pos].collision_boxes)!=before,
                         timeout=2,reason='interaction_unconfirmed',radius=6)
            elif kind=='dig':
                if not policy.allow_dig:raise Failure('mining_not_enabled')
                # Reject falling material or fluids directly above the opening.
                above=ctx.world.nodes.get((pos[0],pos[1]+1,pos[2]))
                if above is None or not above.harmless or above.groups.get('falling_node',0):
                    raise Failure('unstable_mining_roof',{'position':pos})
                dig_node(ctx,pos)
            elif kind=='build':
                if not policy.build_with:raise Failure('building_not_enabled')
                place_scaffold(ctx,policy.build_with,pos)
                observed=ctx.world.nodes.get(pos)
                if not observed or not observed.full_cube or not observed.harmless:
                    raise Failure('building_material_not_full_cube',{'item':policy.build_with})
            else:raise Failure('unknown_terrain_action')
            ctx.terrain_edits+=1
            changes.append(dict(action=kind,position=pos))
            ctx.log('terrain_confirmed',action=kind,position=pos)
            if kind=='interact':return # A door's other half may have changed too; reobserve/replan.
    finally:
        ctx.world.traversal=policy
        ctx.details.clear();ctx.details.update(previous,terrain_changes=changes)
        ctx.stop_input()


def find_resource(ctx, resource, excluded=frozenset(), for_dig=False, nodes=None):
    names=set(nodes) if nodes is not None else ctx.book.resources(resource)
    # A node with a callback-dependent drop can still be searched by exact name.
    names.update(n for n in ctx.book.candidates(resource) if ctx.book.items.get(n,{}).get('type')=='node')
    if not names:
        raise Failure('resource_unknown',{'resource':resource})
    for _ in range(100):
        s=ctx.read(6)
        start=ctx.world.start(s.position)
        def harvest_site(p):
            if not for_dig or p[1]>=cell(s.position)[1]:return True
            # A surface harvest must not create a blind shaft. A current
            # support resource is eligible only from a different safe stance.
            below=ctx.world.nodes.get((p[0],p[1]-1,p[2]))
            return below is not None and below.walkable and below.full_cube and below.harmless
        targets=sorted((p for p,n in ctx.world.nodes.items() if n.name in names and p not in excluded and ctx.within(p) and harvest_site(p)),key=lambda p:distance(p,s.position))
        for target in targets:
            path,_=ctx.world.path(start,lambda p:(ctx.world.harvest_approach if for_dig else ctx.world.approach)(p,target),
                                  lambda p:max(0,distance(p,target)-3),blocked=ctx.blocked,within=ctx.within)
            if path is not None:
                ctx.log('resource_found',node=ctx.world.nodes[target].name,position=target)
                return target
        frontier_path,_=ctx.world.path(start,lambda p:p!=start and ctx.world.frontier(p) and ctx.visited[p]<2,blocked=ctx.blocked,within=ctx.within)
        if not frontier_path:
            raise Failure('resource_not_found',{'resource':resource,'search_radius':ctx.radius,'visible_but_unreachable':len(targets)})
        destination=frontier_path[-1]
        ctx.visited[destination]+=1
        ctx.log('explore',destination=destination)
        try:
            navigate(ctx,feet(destination))
        except Failure as exc:
            if exc.reason not in ('no_path','movement_blocked','navigation_limit'):
                raise
    raise Failure('search_limit',{'resource':resource})


def move_confirmed(ctx, fl, fs, tl, ts, amount):
    before=ctx.read()
    a,b=before.inventory[fl].items[fs],before.inventory[tl].items[ts]
    if a.count<amount or not a.name or (b.count and (b.name!=a.name or (a.stack_key and b.stack_key and a.stack_key!=b.stack_key))):
        raise Failure('inventory_changed')
    ctx.game.move_items(fl,fs,tl,ts,amount)
    return ctx.wait(lambda s:s.inventory_revision>before.inventory_revision
                    and s.inventory[fl].items[fs].count==a.count-amount
                    and s.inventory[tl].items[ts].name==a.name
                    and s.inventory[tl].items[ts].count==b.count+amount,
                    reason='inventory_move_unconfirmed')


def main_space(ctx, name, amount, stack_key=None):
    main=ctx.read().inventory['main']
    maximum=ctx.book.items.get(name,{}).get('stack_max',99)
    for i,item in enumerate(main.items):
        if item.name==name and item.count+amount<=maximum and (stack_key is None or item.stack_key==stack_key):
            return i
    for i,item in enumerate(main.items):
        if not item.count and amount<=maximum:
            return i
    if getattr(ctx,'recover',False) and not getattr(ctx,'organizing',False):
        if organize_inventory(ctx):return main_space(ctx,name,amount,stack_key)
    raise Failure('inventory_full',{'item':name,'count':amount,'message':'Identical stacks consolidated; no items discarded. Free a slot or use a storage policy.'})


def wield_slot(ctx, slot):
    if slot is None:raise Failure('item_not_held')
    s=ctx.read();size=s.raw['hotbar_size']
    if slot>=size:
        hot=next((i for i,x in enumerate(s.inventory['main'].items[:size]) if not x.count),None)
        if hot is None:
            spare=s.inventory['main'].empty_slot()
            if spare is None:
                raise Failure('no_hotbar_space')
            hot=size-1
            move_confirmed(ctx,'main',hot,'main',spare,s.inventory['main'].items[hot].count)
        s=ctx.read()
        move_confirmed(ctx,'main',slot,'main',hot,s.inventory['main'].items[slot].count)
        slot=hot
    if ctx.read().raw['wield']==slot:return slot
    ctx.game.wield(slot)
    ctx.wait(lambda s:s.raw['wield']==slot,reason='wield_unconfirmed')
    return slot


def choose_tool(ctx, target):
    ctx.check()
    raw=ctx.game._request('inspect_node',x=target[0],y=target[1],z=target[2])
    choices=[t for t in raw['tools'] if t['diggable'] and ctx.book.harvestable(raw['name'],t['name'],raw['groups'])]
    if not choices:
        if getattr(ctx,'allow_tool_crafting',False) and getattr(ctx,'recover',False) and raw['name'] not in ctx.tool_recovery and ctx.recoveries['tool:'+raw['name']]<4:
            ctx.tool_recovery.add(raw['name'])
            state=ctx.read(6);stock=Counter()
            for item in state.inventory['main'].items:stock[item.name]+=item.count
            known=[n.name for n in ctx.world.nodes.values()]
            candidates=[]
            for name,definition in ctx.book.items.items():
                if not definition.get('diggroups') or not ctx.book.harvestable(raw['name'],name,raw['groups']):continue
                try:
                    plan=ctx.book.plan(name,1,stock,gather=False,nearby=known,has_table=TABLE in known)
                except PlanningError:
                    if not (ctx.book.procurement_nodes(name)&set(known)):continue
                    try:plan=ctx.book.plan(name,1,stock,nearby=known,has_table=TABLE in known)
                    except PlanningError:continue
                held=['']+[i.name for i in state.inventory['main'].items if i.count]
                # Do not bootstrap a pickaxe by mining ore that requires that pickaxe.
                if any(not any(node in known and any(ctx.book.harvestable(node,t) for t in held)
                               for node in ctx.book.resources(step.item)) for step in plan if step.kind=='collect'):
                    continue
                candidates.append((sum(x.count for x in plan)+len(plan)*2,name))
            if candidates:
                tool=min(candidates)[1];ctx.log('recover_tool',item=tool,node=raw['name'])
                saved=dict(ctx.details);ctx.recoveries['tool:'+raw['name']]+=1
                try:
                    craft(ctx,tool,1,True)
                    close_form(ctx);navigate(ctx,target,approach=True)
                    return choose_tool(ctx,target)
                finally:
                    ctx.details=saved;ctx.tool_recovery.discard(raw['name'])
        raise Failure('suitable_tool_required',{'node':raw['name']})
    choice=min(choices,key=lambda t:(t['time'],bool(t['name']),t['slot']))
    wield_slot(ctx,choice['slot'])
    ctx.log('tool_selected',name=choice['name'] or 'hand',expected_seconds=choice['time'])
    return raw['name'],choice['time']


def dig_node(ctx, target):
    approach_and_face(ctx,target,for_dig=True)
    name,seconds=choose_tool(ctx,target)
    s=ctx.read(6);p=cell(s.position)
    if target==(p[0],p[1]-1,p[2]):
        raise Failure('would_remove_support')
    # Keep the confirmed exposed-face aim; re-aiming at the node centre can
    # point into an occluding roof after approach_and_face just succeeded.
    ctx.wait(lambda s:s.pointed_node==target,timeout=2,reason='target_not_in_crosshair')
    started=time.monotonic()
    try:
        while time.monotonic()-started<max(4,min(35,seconds*2+3)):
            s=ctx.read(6)
            node=ctx.world.nodes.get(target)
            if node is not None and node.name!=name:
                ctx.log('node_changed',position=target,before=name,after=node.name)
                return
            if s.pointed_node!=target:
                raise Failure('dig_target_changed')
            # Renew before expiration without releasing DIG between renewals.
            ctx.game._submit('input',keys=['dig'],duration_ms=900)
            ctx.sleep(.25)
        raise Failure('dig_unconfirmed',{'node':name,'position':target})
    finally:
        ctx.stop_input()


def drop_candidates(ctx, state, resource):
    return sorted((o for o in state.raw.get('item_entities',())
                   if o['id'] not in ctx.ignored_drops and ctx.book.matches(o['item'].split()[0],resource) and ctx.within(cell(o['position']))),
                  key=lambda o:distance(o['position'],state.position))


def pickup(ctx, resource, desired, fallback=()):
    """Track current replicated item positions; only inventory grants success."""
    def landing(p,pos):
        base=feet(p)
        return (max(p[0]-.4,min(p[0]+.4,pos[0])),base[1],
                max(p[2]-.4,min(p[2]+.4,pos[2])))
    tried=Counter()
    for _ in range(8):
        state=ctx.read(6)
        if count_items(state,resource,ctx.book)>=desired:return
        objects=drop_candidates(ctx,state,resource)
        locations=[(o['id'],o['position']) for o in objects]
        if not locations:locations=[('node:'+str(p),p) for p in fallback]
        moved=False
        for ident,pos in locations:
            # A current entity may move and deserves a few fresh approaches;
            # a removed-node fallback is only a one-off local check.
            if tried[ident]>=(3 if isinstance(ident,int) else 1):continue
            tried[ident]+=1
            ground=sorted((p for p in ctx.world.nodes if ctx.world.standable(p)
                           and math.hypot(p[0]-pos[0],p[2]-pos[2])<=1.6
                           and abs(feet(p)[1]-pos[1])<=3),
                          # VoxeLibre tests collection .8 above the feet. Rank
                          # that point, not the feet themselves; otherwise a
                          # floating item makes shallow water choose an
                          # unnecessary one-block ascent to the water surface.
                          key=lambda p:distance((landing(p,pos)[0],landing(p,pos)[1]+.8,
                                                 landing(p,pos)[2]),pos)*3+
                                       distance(landing(p,pos),state.position))
            for p in ground[:6]:
                path,_=ctx.world.path(ctx.world.start(state.position),lambda q:q==p,blocked=ctx.blocked,within=ctx.within)
                if path is None:continue
                # Item entities often rest away from the integer cell centre,
                # especially on water. A generic .45 arrival radius can stop
                # just outside the game's pickup radius and then lose a bobbing
                # or merged entity. Stay inside the already validated stand
                # cell, but finish close to the entity's replicated x/z.
                destination=landing(p,pos)
                ctx.log('pickup_track',entity=ident,position=pos,destination=destination)
                # Pickup replication can outlive its inventory update for a
                # few frames. Stop following a vanished entity's old airborne
                # position; disappearance itself never grants collection.
                def refresh(s):
                    if count_items(s,resource,ctx.book)>=desired:return True
                    if not isinstance(ident,int) or any(o['id']==ident for o in s.raw.get('item_entities',())):
                        return False
                    # Entity merges can replace the id with a short replication
                    # gap. Finish a nearby (at most three blocks) safe approach
                    # even if another id flashes into view; the next outer
                    # observation will retarget it. A vanished distant object
                    # still ends the leg, so stale data never causes a long
                    # cross-map chase.
                    remaining=distance(s.position,destination)
                    return remaining<=.35 or remaining>3
                # VoxeLibre's collection sphere is radius .2 around a point
                # .8 above the feet. The typical floating-item height already
                # consumes most of that radius vertically, so .18 horizontal
                # arrival is not sufficient.
                # A replicated entity has a precise position and needs the
                # tight collection radius. A removed-node fallback is only an
                # approximate last-known location; forcing its centre to .05
                # can trap navigate in an internal replan loop after the drop
                # has already moved or merged.
                tolerance=.05 if isinstance(ident,int) else .45
                try:navigate(ctx,destination,tolerance=tolerance,until=refresh)
                except Failure as exc:
                    if exc.reason not in ('no_path','movement_blocked','no_supported_start'):raise
                    continue
                moved=True;break
            if moved:break
        try:
            # VoxeLibre can hide/merge the visual item before the authoritative
            # inventory update arrives, especially while it floats toward a
            # player in water. Stay at the confirmed approach point for one
            # short server round-trip window; inventory remains the only proof.
            ctx.wait(lambda s:count_items(s,resource,ctx.book)>=desired,timeout=1.25,reason='pickup_unconfirmed')
            return
        except Failure as exc:
            if exc.reason!='pickup_unconfirmed':raise
        if not moved:break
    last=getattr(ctx,'last',None)
    seen=count_items(last,resource,ctx.book) if last is not None else None
    raise Failure('pickup_unconfirmed',{'requested_inventory_count':desired,'observed_inventory_count':seen})


def keep_partial_pickup(ctx, before, got, count, current, error):
    """Record confirmed batch progress and tell collect whether to continue."""
    if error.reason!='pickup_unconfirmed' or current<=before+got or not getattr(ctx,'recover',False):
        return False
    ctx.log('pickup_partial',confirmed=current-before,remaining=max(0,count-(current-before)))
    if ctx.operation=='collect':ctx.details['collected']=current-before
    return True


def collect(ctx, resource, count):
    before=count_items(ctx.read(),resource,ctx.book)
    excluded=set();failures=Counter()
    while True:
        state=ctx.read(6)
        got=count_items(state,resource,ctx.book)-before
        progress=dict(resource=resource,collected=max(0,got),requested=count)
        if ctx.operation=='collect':ctx.details.update(progress)
        else:ctx.details['last_collection']=progress
        if got>=count:return
        # Existing drops cost less than breaking another block.
        if drop_candidates(ctx,state,resource):
            try:pickup(ctx,resource,before+min(count,got+1))
            except Failure as exc:
                if exc.reason!='pickup_unconfirmed':raise
                ctx.ignored_drops.update(o['id'] for o in drop_candidates(ctx,ctx.read(),resource))
            else:continue
        target=find_resource(ctx,resource,excluded,for_dig=True)
        state=ctx.read(6);start=ctx.world.start(state.position)
        names=ctx.book.resources(resource)
        names.update(n for n in ctx.book.candidates(resource) if ctx.book.items.get(n,{}).get('type')=='node')
        cluster=[p for p,n in ctx.world.nodes.items() if n.name in names and p not in excluded
                 and distance(p,target)<=3]
        if start is not None and count-got>1 and len(cluster)>1:
            choices=[]
            for stand in ctx.world.nodes:
                # Filter the small reach envelope before expensive collision
                # queries. Never stand on any block planned for this batch.
                if distance(stand,target)>3 or not ctx.within(stand):continue
                if not ctx.world.standable(stand) or not ctx.world.harvest_approach(stand,target):continue
                if any(ctx.world.supported_by(ctx.world.point(stand),p) for p in cluster):continue
                coverage=sum(ctx.world.harvest_approach(stand,p) for p in cluster)
                if coverage>=2:choices.append((-min(count-got,coverage),distance(stand,start),stand))
            # Ranking all candidates with separate full A* searches left the
            # player idle long enough to sink. Prefer a nearby high-coverage
            # reachable station; batch optimization is optional, not a gate.
            for neg_coverage,_,stand in sorted(choices)[:12]:
                path,_=ctx.world.path(start,lambda q:q==stand,lambda q:distance(q,stand),blocked=ctx.blocked,within=ctx.within)
                if path is None:continue
                ctx.log('harvest_station',position=stand,coverage=-neg_coverage)
                navigate(ctx,ctx.world.point(stand))
                break
        batch=[]
        for _ in range(min(4,count-got)):
            node_name=ctx.world.nodes[target].name
            drop=(ctx.book.items.get(node_name,{}).get('drop') or node_name).split()[0]
            main_space(ctx,drop,1)
            try:dig_node(ctx,target)
            except Failure as exc:
                if exc.reason in ('no_path','target_not_in_crosshair','dig_unconfirmed','dig_target_changed','would_remove_support'):
                    failures[target]+=1
                    if failures[target]>=2 or not ctx.recover:excluded.add(target)
                    ctx.log('resource_retry',position=target,reason=exc.reason,attempt=failures[target])
                    if len(excluded)>8:raise
                    break
                raise
            batch.append(target);excluded.add(target)
            state=ctx.read(6)
            if count_items(state,resource,ctx.book)-before>=count:
                if ctx.operation=='collect':ctx.details.update(collected=count_items(state,resource,ctx.book)-before)
                ctx.log('harvest_batch',nodes=len(batch))
                return
            # Harvest reachable neighbors without a pickup trip between each.
            names=ctx.book.resources(resource)
            names.update(n for n in ctx.book.candidates(resource) if ctx.book.items.get(n,{}).get('type')=='node')
            current=ctx.world.start(state.position)
            choices=[q for q,n in ctx.world.nodes.items() if n.name in names and q not in excluded
                     and current and ctx.world.harvest_approach(current,q) and q[1]>=cell(state.position)[1]
                     and ctx.within(q)]
            if not choices:break
            target=min(choices,key=lambda q:distance(q,target)+.2*distance(q,state.eye))
        if batch:
            ctx.log('harvest_batch',nodes=len(batch))
            # A removed node is not counted. Missing/random drops are reported.
            desired=before+min(count,got+len(batch))
            try:pickup(ctx,resource,desired,batch)
            except Failure as exc:
                current=count_items(ctx.read(),resource,ctx.book)
                # Drops are normal game objects and can be lost or merged.
                # Keep any confirmed inventory progress and, when recovery is
                # enabled, acquire only the remaining request from another
                # observed node. Never count a removed block as an item.
                if keep_partial_pickup(ctx,before,got,count,current,exc):
                    continue
                ctx.details['nodes_removed_without_confirmed_pickup']=batch
                raise
            ctx.log('pickup_confirmed',resource=resource,count=count_items(ctx.read(),resource,ctx.book)-before)


def clear_grid(ctx):
    for name in ('craftresult','craft'):
        state=ctx.read()
        if name not in state.inventory:continue
        for slot in range(state.inventory[name].size):
            item=ctx.read().inventory[name].items[slot]
            if item.count:
                dest=main_space(ctx,item.name,item.count,item.stack_key)
                move_confirmed(ctx,name,slot,'main',dest,item.count)


def close_form(ctx):
    if ctx.read().raw['menu_open']:
        ctx.game.close_inventory()
        ctx.wait(lambda s:not s.raw['menu_open'],reason='form_close_unconfirmed')


def workbench(ctx):
    close_form(ctx)
    state=ctx.read(6)
    nearby=sorted((p for p,n in ctx.world.nodes.items() if n.name==TABLE),key=lambda p:distance(p,state.position))
    start=ctx.world.start(state.position)
    reachable=[]
    for table in nearby:
        path,_=ctx.world.path(start,lambda p:ctx.world.approach(p,table),blocked=ctx.blocked,within=ctx.within)
        if path is not None:reachable.append((len(path),table))
    if reachable:
        ctx.table=min(reachable)[1]
    else:
        slot=state.inventory['main'].find(TABLE)
        if slot is None:
            raise Failure('workbench_required')
        start=ctx.world.start(state.position)
        sites=[p for p in ctx.world.nodes if ctx.world.standable(p) and p[1]==start[1]
               and 1.5<=distance(p,start)<=2.5]
        if not sites:
            raise Failure('no_workbench_placement_site')
        for site in sorted(sites,key=lambda p:distance(p,start)):
            support=(site[0],site[1]-1,site[2])
            if not ctx.world.visible(state.eye,support):continue
            wield_slot(ctx,slot)
            face(ctx,(support[0],support[1]+.49,support[2]))
            if ctx.read().pointed_node!=support:continue
            ctx.pulse(['place'],.12)
            ctx.read(6)
            if ctx.world.nodes.get(site) and ctx.world.nodes[site].name==TABLE:
                ctx.table=site
                ctx.log('workbench_placed',position=site)
                break
        else:
            raise Failure('workbench_placement_unconfirmed')
    approach_and_face(ctx,ctx.table,'workbench_not_in_crosshair')
    # Right-click uses the normal node interaction and its actual server formspec.
    ctx.game.use(.12)
    ctx.wait(lambda s:s.raw['menu_open'] and s.inventory['craft'].width==3,reason='workbench_open_unconfirmed')


def execute_recipe(ctx, step):
    r=step.recipe;crafts=step.count//r.count
    state=ctx.read()
    # A 3x3 session can execute 2x2 recipes too; keep a usable station open.
    if not (state.raw['menu_open'] and state.inventory['craft'].width>=r.grid):
        if r.grid==3:workbench(ctx)
        else:
            close_form(ctx);ctx.game.open_inventory()
            ctx.wait(lambda s:s.raw['menu_open'],reason='inventory_open_unconfirmed')
    clear_grid(ctx)
    width=ctx.read().inventory['craft'].width
    for index,name in enumerate(step.ingredients):
        if not name:continue
        source_width=r.width or (2 if len(r.items)<=4 else 3)
        slot=(index//source_width)*width+index%source_width
        remaining=crafts
        while remaining:
            state=ctx.read();source=state.inventory['main'].find(name)
            if source is None:raise Failure('planned_material_missing',{'item':name})
            amount=min(remaining,state.inventory['main'].items[source].count)
            move_confirmed(ctx,'main',source,'craft',slot,amount);remaining-=amount
    ctx.wait(lambda s:s.inventory.get('craftpreview') and s.inventory['craftpreview'].items[0].name==r.output
             and s.inventory['craftpreview'].items[0].count==r.count,
             timeout=3,reason='recipe_preview_mismatch')
    # Reserve output room before consuming inputs; a failure leaves the grid intact.
    dest=main_space(ctx,r.output,step.count,ctx.read().inventory['craftpreview'].items[0].stack_key)
    before=ctx.read();ctx.game.craft_grid(crafts)
    crafted=ctx.wait(lambda s:s.inventory_revision>before.inventory_revision
             and s.inventory['craftresult'].items[0].name==r.output
             and s.inventory['craftresult'].items[0].count==step.count,
             reason='craft_unconfirmed')
    dest=main_space(ctx,r.output,step.count,crafted.inventory['craftresult'].items[0].stack_key)
    move_confirmed(ctx,'craftresult',0,'main',dest,step.count)
    ctx.log('craft_confirmed',item=r.output,count=step.count,batch=crafts)


def craft(ctx, item, count, gather):
    from .recipes import batch_plan
    item=ctx.book.resolve(item)
    initial=count_items(ctx.read(),item,ctx.book)
    for attempt in range(4):
        # Observe again after every recovery; never replay the original item count.
        state=ctx.read()
        if any(i.count for name in ('craft','craftresult') if name in state.inventory for i in state.inventory[name].items):
            if not state.raw['menu_open']:
                ctx.game.open_inventory();ctx.wait(lambda s:s.raw['menu_open'])
            clear_grid(ctx)
        state=ctx.read(6);produced=count_items(state,item,ctx.book)-initial
        if produced>=count:
            ctx.details.update(item=item,produced=produced,requested=count);return
        stock=Counter()
        for stack in state.inventory['main'].items:stock[stack.name]+=stack.count
        known=[n.name for n in ctx.world.nodes.values()]
        def plan_now():
            usable=any(ctx.world.path(ctx.world.start(state.position),lambda p:ctx.world.approach(p,t),blocked=ctx.blocked,within=ctx.within)[0] is not None
                       for t,n in ctx.world.nodes.items() if n.name==TABLE)
            return ctx.book.plan(item,count-produced,stock,gather=gather,nearby=known,has_table=usable)
        plan=plan_now()
        missing_nodes=set(n for step in plan if step.kind=='collect' for n in ctx.book.resources(step.item))
        if gather and missing_nodes and not (missing_nodes & set(known)):
            alternatives=ctx.book.procurement_nodes(item)
            if alternatives:
                find_resource(ctx,'recipe_materials',nodes=alternatives)
                known=[n.name for n in ctx.world.nodes.values()];plan=plan_now()
        plan=batch_plan(plan,ctx.book)
        ctx.details.update(item=item,requested=count,plan_steps=len(plan),recipe_source=ctx.book.source)
        try:
            for step in plan:
                ctx.check();ctx.log('plan_step',kind=step.kind,item=step.item,count=step.count)
                if step.kind=='collect':close_form(ctx);collect(ctx,step.item,step.count)
                elif step.kind=='workbench':workbench(ctx)
                elif step.kind=='smelt':
                    from .workstations import smelt
                    close_form(ctx);smelt(ctx,step.item,step.count,gather=gather)
                else:execute_recipe(ctx,step)
            close_form(ctx)
            final=count_items(ctx.read(),item,ctx.book)
            ctx.details.update(item=item,produced=final-initial,requested=count)
            if final-initial<count:raise Failure('target_item_not_confirmed')
            return
        except Failure as exc:
            # Do not retry unknown outcomes, server preview rejection or cancellation.
            if not ctx.recover or attempt>=3 or exc.reason not in ('planned_material_missing','inventory_changed','workbench_open_unconfirmed','workbench_not_in_crosshair','workbench_required'):
                raise
            ctx.log('craft_replan',reason=exc.reason,attempt=attempt+1)
    raise Failure('recovery_limit')


def organize_inventory(ctx):
    """Only merge server-identical stacks; never discard/sort unique items."""
    if getattr(ctx,'organizing',False):return 0
    ctx.organizing=True
    moved=0
    try:
        initial=ctx.read()
        def totals(state):
            c=Counter()
            for item in state.inventory['main'].items:
                if item.count:c[(item.name,item.wear,item.stack_key)]+=item.count
            return c
        baseline=totals(initial)
        groups={}
        for i in initial.inventory['main'].items:
            if i.count and i.stack_key:groups.setdefault(i.stack_key,[]).append(i)
        useful={key for key,items in groups.items()
                if math.ceil(sum(i.count for i in items)/max(1,ctx.book.items.get(items[0].name,{}).get('stack_max',1)))<len(items)}
        size=initial.inventory['main'].size
        for dest in range(size):
            a=ctx.read().inventory['main'].items[dest]
            if not a.count or a.stack_key not in useful:continue
            maximum=ctx.book.items.get(a.name,{}).get('stack_max',1)
            for source in range(dest+1,size):
                state=ctx.read();a=state.inventory['main'].items[dest];b=state.inventory['main'].items[source]
                if a.count>=maximum:break
                if b.count and a.stack_key==b.stack_key:
                    amount=min(b.count,maximum-a.count,99)
                    move_confirmed(ctx,'main',source,'main',dest,amount);moved+=1
                    if state.raw.get('wield')==source and amount==b.count:ctx.game.wield(dest)
        final=ctx.read()
        if totals(final)!=baseline:raise Failure('inventory_changed_during_organization')
        ctx.log('inventory_organized',moves=moved,freed_slots=sum(not i.count for i in final.inventory['main'].items)-sum(not i.count for i in initial.inventory['main'].items))
        if ctx.operation=='organize_inventory':ctx.details.update(moves=moved,empty_slots=sum(not i.count for i in final.inventory['main'].items))
        return moved
    finally:ctx.organizing=False


def equip(ctx, item, destination='hand'):
    item=ctx.book.resolve(item);state=ctx.read()
    if destination=='hand':
        candidates=[(i.wear,n) for n,i in enumerate(state.inventory['main'].items) if i.count and ctx.book.matches(i.name,item)]
        if not candidates:raise Failure('item_not_held',{'item':item})
        slot=wield_slot(ctx,min(candidates)[1])
        ctx.details.update(item=ctx.read().inventory['main'].items[slot].name,slot=slot,destination=destination)
        return
    groups=ctx.book.items.get(item,{}).get('groups') or {}
    if destination=='armor':
        slot=next((index for index,g in enumerate(('armor_head','armor_torso','armor_legs','armor_feet'),1) if groups.get(g,0)>0),None)
        if slot is None:raise Failure('not_armor',{'item':item})
    else:slot=0
    items=state.inventory.get(destination)
    if items is None or slot>=items.size:raise Failure('equipment_slot_unavailable')
    if items.items[slot].name==item:
        ctx.details.update(item=item,slot=slot,destination=destination);return
    source=state.inventory['main'].find(item)
    if source is None:raise Failure('item_not_held',{'item':item})
    old=items.items[slot]
    if old.count:
        dest=main_space(ctx,old.name,old.count,old.stack_key)
        move_confirmed(ctx,destination,slot,'main',dest,old.count)
    # All equipment callbacks, including binding curses, remain server-authoritative.
    source=ctx.read().inventory['main'].find(item)
    if source is None:raise Failure('item_not_held',{'item':item})
    move_confirmed(ctx,'main',source,destination,slot,1)
    ctx.details.update(item=item,slot=slot,destination=destination)


def use_keys(ctx, support):
    """Suppress known/unknown node interactions only when necessary.

    The pinned game catalog records callbacks, not guesses from node names.
    A catalog miss or changed live groups retains conservative sneak-use.
    This is an interaction decision; bridge edge protection stays explicit.
    """
    if support is None:return ['place']
    node=ctx.world.nodes.get(tuple(support))
    definition=ctx.book.items.get(node.name,{}) if node else {}
    ordinary=(node is not None and definition.get('on_rightclick') is False
              and definition.get('on_receive_fields') is False and not node.groups.get('container',0)
              and dict(node.groups or {})==dict(definition.get('groups') or {}))
    return ['place'] if ordinary else ['sneak','place']


def place_block(ctx,item,target):
    item=ctx.book.resolve(item)
    if ctx.book.items.get(item,{}).get('type')!='node':raise Failure('not_placeable_node',{'item':item})
    close_form(ctx);state=ctx.read(6)
    if not ctx.within(target):raise Failure('target_out_of_radius')
    existing=ctx.world.nodes.get(target)
    if existing is None:
        navigate(ctx,target,approach=True);state=ctx.read(6);existing=ctx.world.nodes.get(target)
        if existing is None:raise Failure('placement_target_unobserved')
    if not existing.buildable:raise Failure('placement_target_occupied',{'node':existing.name})
    start=ctx.world.start(state.position)
    if target in (cell(state.position),(cell(state.position)[0],cell(state.position)[1]+1,cell(state.position)[2])):
        raise Failure('placement_intersects_player')
    slot=state.inventory['main'].find(item)
    if slot is None:raise Failure('item_not_held',{'item':item})
    supports=[];deferred=[]
    for delta in ((0,-1,0),(1,0,0),(-1,0,0),(0,0,1),(0,0,-1),(0,1,0)):
        support=tuple(target[i]+delta[i] for i in range(3))
        node=ctx.world.nodes.get(support)
        if node and node.walkable and node.full_cube and node.harmless:
            aim=tuple(support[i]-delta[i]*.49 for i in range(3))
            # Stand off the exact placement cell, with a direct ray to its face.
            def usable(q,aim=aim):
                eye=(q[0],q[1]+1.125,q[2])
                return q!=target and (q[0],q[1]+1,q[2])!=target and distance(eye,aim)<3.5 and ctx.world.visible(eye,aim)
            # Use the actual current stance if it already exposes the face.
            # Rounding to a different voxel centre caused needless per-block walks.
            overlap=(abs(state.position[0]-target[0])<.5+ctx.world.radius and abs(state.position[2]-target[2])<.5+ctx.world.radius
                     and state.position[1]<target[1]+.5 and state.position[1]+ctx.world.height>target[1]-.5)
            if not overlap and distance(state.eye,aim)<3.5 and ctx.world.visible(state.eye,aim):
                supports.append((0,support,aim,None))
            else:
                path,_=ctx.world.path(start,usable,blocked=ctx.blocked,within=ctx.within)
                if path is not None:
                    if path[-1]==start:
                        # This face works only at an ideal cell centre, not our
                        # actual eye. Prefer an already valid alternative face;
                        # do not aim at it after a no-op "arrival".
                        deferred.append((support,aim,usable))
                    else:supports.append((len(path),support,aim,path[-1]))
    if not supports:
        # A single-face target must remain reachable: search a genuinely new
        # stance rather than dropping it merely because its first plan was empty.
        for support,aim,usable in deferred:
            path,_=ctx.world.path(start,lambda q:q!=start and usable(q),blocked=ctx.blocked,within=ctx.within)
            if path is not None:supports.append((len(path),support,aim,path[-1]))
    if not supports:raise Failure('no_placement_face')
    for _,support,aim,stand in sorted(supports):
        if stand is not None:navigate(ctx,feet(stand),look_at=aim)
        wield_slot(ctx,ctx.read().inventory['main'].find(item));face(ctx,aim)
        if ctx.read().pointed_node!=support:continue
        before_state=ctx.read();before=count_items(before_state,item,ctx.book)
        ctx.game.hold(use_keys(ctx,support),.12)
        state=ctx.wait(lambda s:ctx.world.nodes.get(target) and ctx.world.nodes[target].name==item,
                       timeout=3,reason='placement_unconfirmed',radius=6)
        ctx.wait(lambda s:s.inventory_revision>before_state.inventory_revision and count_items(s,item,ctx.book)==before-1,reason='placement_inventory_unconfirmed')
        ctx.details.update(item=item,position=target,placed=1);ctx.log('placement_confirmed',item=item,position=target)
        return
    raise Failure('placement_face_not_in_crosshair')
