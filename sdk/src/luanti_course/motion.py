"""Smooth turns and explicit continuous input scopes with native dead-man leases."""
import math
import time
from .errors import ActionError, ActionCancelled, ActionTimeout


def seconds(value, maximum=60):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<=maximum:
        raise ValueError('seconds must be a finite positive number <= '+str(maximum))
    return value


class Motion:
    """Keep input continuous across short calls; always stop on context exit.

    No background thread replays actions. A stalled student loop stops within
    400 ms (or the explicitly requested lease), even while this scope is open.
    """
    def __init__(self, game):
        self.game=game;self.active=False;self.epoch=None

    def __enter__(self):
        g=self.game
        if self.active or getattr(g,'_motion',None) is not None:raise ActionError('motion_scope_active')
        if not g._action_lock.acquire(False):raise ActionError('another_action_running')
        try:
            s=g.observe()
            if g._epoch is None or s.control!='agent' or s.control_epoch!=g._epoch:raise ActionError('control_released')
            self.epoch=g._epoch;g._cancel.clear();self.active=True;g._motion=self
            return self
        except BaseException:
            g._action_lock.release();raise

    def check(self):
        if not self.active:raise ActionError('motion_scope_closed')
        if self.game._cancel.is_set():raise ActionCancelled('Action cancelled')
        state=self.game.observe()
        if state.control!='agent' or state.control_epoch!=self.epoch or state.dead:raise ActionError('control_released')
        return state

    def hold(self, keys, duration):
        from .client import KEYS
        keys=tuple(keys)
        if not keys or len(keys)>9 or any(k not in KEYS for k in keys):raise ValueError('Unknown or empty controls')
        seconds(duration);end=time.monotonic()+duration
        while True:
            self.check()
            self.game._submit('input',keys=list(keys),duration_ms=400)
            remaining=end-time.monotonic()
            if remaining<=0:break
            if self.game._cancel.wait(min(.15,remaining)):raise ActionCancelled('Action cancelled')
        return self.check()

    def move(self, direction='forward', seconds=1, *, jump=False, sneak=False):
        self.check()
        return self.game.move(direction,seconds,jump=jump,sneak=sneak)

    def steer(self, heading, speed=1, *, pitch=0, jump=False, sneak=False, lease=.4, swim_y=None, move_heading=None, place=False):
        """Non-blocking update for a student feedback loop; angles in degrees."""
        seconds(lease,1)
        for name,v,limit in [('heading',heading,36000),('pitch',pitch,89.9),('speed',speed,1)]:
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>limit or (name=='speed' and v<0):raise ValueError('invalid '+name)
        if not isinstance(jump,bool) or not isinstance(sneak,bool):raise ValueError('jump/sneak must be boolean')
        extra={}
        if swim_y is not None:
            if isinstance(swim_y,bool) or not isinstance(swim_y,(int,float)) or not math.isfinite(swim_y) or abs(swim_y)>32760:raise ValueError('invalid swim_y')
            if jump or sneak:raise ValueError('swim_y selects vertical controls; omit jump/sneak')
            if 'swim_height' not in self.game.capabilities:raise ActionError('swim_control_unavailable')
            extra['swim_y']=swim_y
        if move_heading is not None:
            if isinstance(move_heading,bool) or not isinstance(move_heading,(int,float)) or not math.isfinite(move_heading) or abs(move_heading)>36000:raise ValueError('invalid move_heading')
            if 'independent_heading' not in self.game.capabilities:raise ActionError('independent_heading_unavailable')
            extra['move_heading']=move_heading
        if type(place) is not bool:raise ValueError('place must be boolean')
        if place:
            if 'steer_place' not in self.game.capabilities:raise ActionError('steer_place_unavailable')
            extra['place']=True
        self.check()
        return self.game._submit('steer',heading=heading,pitch=pitch,speed=speed,jump=jump,sneak=sneak,duration_ms=max(1,math.ceil(lease*1000)),**extra)

    def __exit__(self,*args):
        try:
            if not self.game._closed:self.game._submit('stop')
        finally:
            self.active=False;self.game._motion=None;self.game._action_lock.release()


def turn(game,yaw,pitch,timeout):
    seconds(timeout,10)
    if 'steer' not in getattr(game,'capabilities',()):raise ActionError('smooth_steering_unavailable')
    if getattr(game,'_motion',None) is not None:raise ActionError('use_motion_steer_for_continuous_turns')
    if not game._action_lock.acquire(False):raise ActionError('another_action_running')
    try:
        if not game._skill_depth:game._cancel.clear()
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if game._cancel.is_set():raise ActionCancelled('Action cancelled')
            state=game.observe()
            if game._epoch is None or state.control!='agent' or state.control_epoch!=game._epoch or state.dead:raise ActionError('control_released')
            submission=game._submit('steer',heading=yaw,pitch=pitch,speed=0,jump=False,duration_ms=400)
            if abs((state.yaw-yaw+180)%360-180)<.5 and abs(state.pitch-pitch)<.5:return submission
            if game._cancel.wait(.04):raise ActionCancelled('Action cancelled')
        raise ActionTimeout('Smooth turn did not reach the requested orientation')
    finally:
        try:
            if not game._closed:game._submit('stop')
        finally:game._action_lock.release()
