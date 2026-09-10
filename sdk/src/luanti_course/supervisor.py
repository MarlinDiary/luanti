"""Opt-in Mindcraft-style fast reactions below the student's planner.

One socket, one action owner. A reaction asks the current action to unwind first;
it never races a movement writer or blindly replays a partly completed task.
"""
from collections import deque
from dataclasses import dataclass, asdict
import threading
import time
from .entities import hostiles
from .combat import food_choice, BANNED_FOOD, incoming_projectiles, explosive_threats
from .errors import ActionError, CourseError

@dataclass(frozen=True)
class SurvivalConfig:
    auto_eat: bool = True
    self_preservation: bool = True
    enemies: str = 'avoid'  # avoid | defend | off; one policy, not competing loops
    eat_at: int = 14
    critical_hp: int = 6
    threat_radius: float = 12
    safe_distance: float = 14
    poll_interval: float = .15
    action_timeout: float = 25
    banned_food: tuple = tuple(sorted(BANNED_FOOD))
    settle_time: float = 1.0  # continuously clear observations before yielding

    def __post_init__(self):
        from .skills import positive
        if type(self.auto_eat) is not bool or type(self.self_preservation) is not bool:raise ValueError('mode flags must be bool')
        if self.enemies not in ('avoid','defend','off'):raise ValueError('enemies must be avoid, defend, or off')
        for name,limit in (('eat_at',19),('critical_hp',19),('threat_radius',15),('safe_distance',15),('poll_interval',1),('action_timeout',120),('settle_time',5)):
            positive(getattr(self,name),name,limit)
        if self.safe_distance<=self.threat_radius:raise ValueError('safe_distance must exceed threat_radius for hysteresis')
        if self.poll_interval<.05:raise ValueError('poll_interval must be at least .05')
        if not all(isinstance(x,str) for x in self.banned_food):raise ValueError('banned_food must contain item names')

def decide(state, config, book):
    if state.dead or state.control!='agent' or state.raw.get('paused'):return None
    if config.self_preservation and state.raw.get('breath',11)<5:return dict(action='recover_air',reason='low_breath')
    if config.self_preservation and state.raw.get('hazards'):return dict(action='escape_hazard',reason='contact_hazard')
    if config.self_preservation and state.burning:return dict(action='extinguish_fire',reason='burning')
    if config.self_preservation and state.raw.get('entities_available'):
        projectiles=incoming_projectiles(state)
        if projectiles:return dict(action='avoid_projectile',reason='incoming_projectile',target=list(projectiles[0].ref))
        explosives=explosive_threats(state,min(6,config.threat_radius))
        if explosives:return dict(action='survive_blast',reason='explosive_proximity',target=list(explosives[0].ref))
    enemies=hostiles(state,config.threat_radius) if state.raw.get('entities_available') else ()
    if enemies:
        if config.self_preservation and state.hp<=config.critical_hp:
            return dict(action='flee_from',reason='critical_health',target=list(enemies[0].ref))
        if config.enemies!='off':
            action='flee_from' if config.enemies=='avoid' else 'defend_self'
            return dict(action=action,reason='nearby_hostile',target=list(enemies[0].ref))
    if config.auto_eat and state.hunger is not None and (state.hunger<=config.eat_at or (state.hp<20 and state.hunger<18)):
        if food_choice(state,book,config.banned_food):return dict(action='eat_best_food',reason='hunger')
    return None

def reaction_cooldown(result):
    # A trapped player must not wait three seconds before reconsidering a
    # moving threat. Requests remain bounded and return replan_required.
    if not result.ok and result.operation in ('flee_from','recover_air','escape_hazard','extinguish_fire','avoid_projectile','survive_blast'):
        return .15
    return 1 if result.ok else 3

class Survival:
    def __init__(self, game, config=None):
        self.game=game;self.config=config or SurvivalConfig()
        if not isinstance(self.config,SurvivalConfig):raise ValueError('config must be SurvivalConfig')
        self._stop=threading.Event();self._thread=None;self._pending=None;self._paused=False
        self._events=deque(maxlen=256);self._event_lock=threading.Lock();self._busy=False
        self._epoch=None;self._sequence=0
        self._active_choice=None;self._preempted=False

    @property
    def pending(self):return dict(self._pending) if self._pending else None
    @property
    def paused(self):return self._paused
    @property
    def busy(self):return self._busy or self._pending is not None
    def is_worker(self):return threading.current_thread() is self._thread
    def interrupted(self):
        if self.is_worker():return self._stop.is_set() or self._paused or self._preempted
        return self._pending is not None

    def on_observation(self, state):
        """Cooperative priority check on the action owner's fresh snapshot.

        No second socket or input writer: Context unwinds the current skill,
        then the worker re-observes before dispatching the higher priority one.
        """
        if self._paused or self._stop.is_set() or (self._epoch is not None and state.control_epoch!=self._epoch):
            return
        if not self.is_worker():
            # Urgent hazards discovered by the action owner's fresh read must
            # yield before Context reports a generic low-breath/path failure.
            # Only request a handoff here; the sole worker still owns actions
            # and rechecks the live state after acquiring the action lock.
            choice=decide(state,self.config,self.game.recipe_book)
            if choice and choice['action'] in ('recover_air','escape_hazard','extinguish_fire','avoid_projectile','survive_blast'):
                self._pending=choice
            return
        if not self._busy or not self._active_choice or self._preempted:
            return
        choice=decide(state,self.config,self.game.recipe_book)
        priorities={'recover_air':0,'escape_hazard':1,'extinguish_fire':2,'avoid_projectile':3,
                    'survive_blast':4,'flee_from':5,'defend_self':6,'eat_best_food':7}
        active=self._active_choice['action']
        # A committed retreat is already evasive movement. Cancelling it for
        # every short-lived arrow makes the worker stop, reacquire a projectile
        # that has usually disappeared, and then restart the same retreat. Keep
        # the smooth escape leg; still let air, contact fire and burning take it
        # over. A stationary/attacking action remains preemptible by an arrow.
        if active=='flee_from' and choice and choice['action']=='avoid_projectile':
            return
        if choice and priorities[choice['action']]<priorities[active]:
            self._pending=choice;self._preempted=True
            self._event('reaction_preempted',previous=self._active_choice,decision=choice,hp=state.hp,breath=state.raw.get('breath'))

    def _event(self, kind, **details):
        with self._event_lock:
            self._sequence+=1
            self._events.append(dict(sequence=self._sequence,time=time.monotonic(),event=kind,**details))
    def events(self):
        """Drain up to 256 recent events; sequence numbers expose any overflow."""
        with self._event_lock:
            result=list(self._events);self._events.clear();return result

    def __enter__(self):
        g=self.game
        if g._survival is not None or self._thread is not None:raise ActionError('survival_scope_active')
        required={'living_entities','hud_statbars','hud_images','weapon_stats','attack'}
        if not required.issubset(g.capabilities):raise ActionError('survival_requires_course_0_9')
        s=g.observe()
        if g._epoch is None or s.control!='agent' or s.control_epoch!=g._epoch:raise ActionError('control_required')
        self._epoch=g._epoch;g._survival=self
        # Advertise already-observed work immediately, not after the first
        # polling interval. No input is written from the caller's thread.
        self._pending=decide(s,self.config,g.recipe_book)
        self._thread=threading.Thread(target=self._loop,name='Luanti survival',daemon=True);self._thread.start()
        return self

    def pause(self):
        self._paused=True
        if self._busy or self._pending:
            self.game._cancel.set()
            if not self.game._closed:self.game._submit('stop')
        self._event('paused')

    def resume(self):
        s=self.game.observe()
        if self._stop.is_set() or self.game._epoch is None or s.control!='agent' or s.control_epoch!=self.game._epoch:
            raise ActionError('control_required')
        self._epoch=self.game._epoch;self._paused=False;self._event('resumed')

    def wait_idle(self, timeout=30):
        end=time.monotonic()+timeout
        while self.busy:
            if time.monotonic()>=end:return False
            time.sleep(.05)
        return True

    def _execute(self, choice):
        g=self.game;action=choice['action'];timeout=self.config.action_timeout
        if action=='flee_from':return g.flee_from(safe_distance=self.config.safe_distance,settle_time=self.config.settle_time,timeout=timeout)
        if action=='defend_self':return g.defend_self(radius=self.config.threat_radius,safe_distance=self.config.safe_distance,timeout=timeout,min_hp=self.config.critical_hp,settle_time=self.config.settle_time)
        if action=='escape_hazard':return g.escape_hazard(timeout=timeout)
        if action=='extinguish_fire':return g.extinguish_fire(timeout=timeout)
        if action=='avoid_projectile':return g.avoid_projectile(tuple(choice['target']),timeout=timeout)
        if action=='survive_blast':return g.survive_blast(tuple(choice['target']),safe_distance=self.config.safe_distance,timeout=timeout)
        if action=='recover_air':return g.recover_air(timeout=timeout)
        if action=='eat_best_food':return g.eat_best_food(timeout=timeout,banned_food=self.config.banned_food)
        raise ValueError('unknown reaction')

    def _loop(self):
        g=self.game;cooldown=0;last_choice=None
        try:
            while not self._stop.wait(self.config.poll_interval):
                if self._paused:self._pending=None;continue
                s=g.observe()
                if s.control!='agent' or s.control_epoch!=self._epoch or g._epoch!=self._epoch or s.dead:
                    self._paused=True;self._pending=None;self._event('control_lost',dead=s.dead);continue
                choice=decide(s,self.config,g.recipe_book)
                if choice is None:self._pending=None;continue
                if time.monotonic()<cooldown and choice==last_choice:continue
                self._pending=choice;self._event('interrupt_requested',decision=choice)
                # Existing skills and low-level motions check this pending flag.
                # Native leases expire even if user code never yields its lock.
                end=time.monotonic()+2
                acquired=False
                while not self._stop.is_set() and not self._paused:
                    if g._action_lock.acquire(False):acquired=True;break
                    if time.monotonic()>=end:
                        g._cancel.set();g._submit('stop');self._paused=True
                        self._event('action_not_yielding');break
                    self._stop.wait(.02)
                if not acquired:self._pending=None;continue
                try:
                    if self._paused or self._stop.is_set():continue
                    self._busy=True
                    # Re-evaluate after the previous action's cleanup and any damage.
                    fresh=g.observe()
                    if fresh.control_epoch!=self._epoch or fresh.control!='agent':continue
                    choice=decide(fresh,self.config,g.recipe_book)
                    if choice is None:continue
                    self._pending=choice
                    self._active_choice=choice;self._preempted=False
                    result=self._execute(choice)
                    self._event('reaction_finished',decision=choice,result=result.to_dict(),replan_required=True)
                    last_choice=choice;cooldown=0 if self._preempted else time.monotonic()+reaction_cooldown(result)
                finally:
                    handoff=self._preempted and not self._paused and not self._stop.is_set()
                    self._active_choice=None;self._preempted=False
                    # A cancelled reaction is not an idle slot for normal
                    # work. Keep its successor pending until the next fresh
                    # decision dispatches it or determines it is unnecessary.
                    if not handoff:self._pending=None
                    self._busy=False;g._action_lock.release()
        except Exception as exc:
            self._paused=True;self._event('reaction_error',message=str(exc))
        finally:
            self._pending=None;self._busy=False

    def close(self):
        self._stop.set()
        if self._busy or self._pending:
            self.game._cancel.set()
            if not self.game._closed:self.game._submit('stop')
        if self._thread and not self.is_worker():self._thread.join(self.game.timeout+3)
        if self._thread and self._thread.is_alive() and not self.is_worker():raise ActionError('survival_shutdown_pending')
        if self.game._survival is self:self.game._survival=None
    def __exit__(self,*args):self.close()
