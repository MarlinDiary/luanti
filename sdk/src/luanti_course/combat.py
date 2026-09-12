"""Bounded normal-player survival skills; no hidden map data or resource grants."""
import math
import time
from dataclasses import replace
from .entities import target_ref, hostiles
from .errors import ActionError
from .navigation import distance, cell, Traversal
from .skills import Failure, face, follow_path, wield_slot, equip, close_form, regain_air, route_runout

BANNED_FOOD = frozenset(('mcl_mobitems:rotten_flesh','mcl_mobitems:spider_eye',
    'mcl_farming:potato_item_poison','mcl_fishing:pufferfish_raw','mcl_mobitems:chicken','mcl_sus_stew:stew'))

def incoming_projectiles(state, horizon=1.25, clearance=1.15):
    """Visible projectiles whose measured trajectory intersects the player.

    This is a short reaction horizon, not future-world prediction. Stationary,
    receding and unfamiliar entities are ignored.
    """
    body=(state.position[0],state.position[1]+.9,state.position[2]);rows=[]
    for e in state.entities:
        if not e.projectile:continue
        v=e.velocity;speed2=sum(x*x for x in v)
        if speed2<.25:continue
        rel=tuple(e.position[i]-body[i] for i in range(3))
        t=-sum(rel[i]*v[i] for i in range(3))/speed2
        if not 0<t<=horizon:continue
        miss=math.sqrt(sum((rel[i]+v[i]*t)**2 for i in range(3)))
        if miss<=clearance:rows.append((t,miss,e))
    return tuple(x[2] for x in sorted(rows,key=lambda x:(x[0],x[1])))

def explosive_threats(state, radius=6):
    """Conservative visible-creeper proximity guard; no hidden fuse state."""
    return tuple(sorted((e for e in state.entities if e.explosive and distance(e.position,state.position)<=radius),
                        key=lambda e:distance(e.position,state.position)))

def count_ammo(state, book):
    return sum(i.count for i in state.inventory['main'].items
               if (book.items.get(i.name,{}).get('groups') or {}).get('ammo_bow',0)>0)

def _find_group_slot(state, book, group):
    return next((n for n,i in enumerate(state.inventory['main'].items) if i.count and
        (book.items.get(i.name,{}).get('groups') or {}).get(group,0)>0),None)

def ranged_attack(ctx, target, shots=1, charge=.65):
    """Fire an existing bow at one currently observed non-player target."""
    ref=target_ref(target);state=ctx.read();require_entities(state)
    bow=_find_group_slot(state,ctx.book,'bow')
    if bow is None:raise Failure('bow_not_held')
    if count_ammo(state,ctx.book)<shots:raise Failure('bow_ammo_not_held',{'needed':shots})
    ctx.details.update(target=list(ref),shots_requested=shots,shots_fired=0)
    for n in range(shots):
        state,current=current_target(ctx,ref)
        if current is None:raise Failure('target_not_observed')
        bow=_find_group_slot(state,ctx.book,'bow')
        if bow is None:raise Failure('bow_not_held')
        before=count_ammo(state,ctx.book);wield_slot(ctx,bow)
        # Lead only by a bounded fraction of the measured velocity; the server
        # remains authoritative and ammo consumption confirms an actual shot.
        d=distance(state.eye,current.aim);lead=min(.75,d/20)
        face(ctx,tuple(current.aim[i]+current.velocity[i]*lead for i in range(3)))
        try:
            end=time.monotonic()+charge
            while time.monotonic()<end:
                ctx.game._submit('input',keys=['place'],duration_ms=250)
                ctx.sleep(min(.08,end-time.monotonic()));ctx.read()
        finally:ctx.stop_input()
        ctx.sleep(.1)
        ctx.wait(lambda s:count_ammo(s,ctx.book)==before-1,timeout=2,reason='ranged_shot_unconfirmed')
        ctx.details['shots_fired']=n+1;ctx.log('ranged_shot',target=list(ref),charge=charge)

def _shield_slot(state, book):
    return _find_group_slot(state,book,'shield')

def block_with_shield(ctx, threat, duration=1.2):
    """Face a visible threat and hold an existing shield for a bounded time."""
    ref=threat.ref;state=ctx.read();slot=_shield_slot(state,ctx.book)
    if slot is None:raise Failure('shield_not_held')
    if 'hud_images' not in ctx.game.capabilities:raise Failure('shield_confirmation_unavailable')
    old=state.raw.get('wield');wield_slot(ctx,slot);face(ctx,threat.aim)
    end=min(ctx.deadline,time.monotonic()+duration);confirmed=False
    try:
        while time.monotonic()<end:
            ctx.game._submit('input',keys=['place'],duration_ms=300)
            ctx.sleep(.06);state=ctx.read()
            confirmed=confirmed or any(isinstance(x,str) and x.startswith('mcl_shield_hud.png')
                                       for x in state.raw.get('hud_images',()))
        if not confirmed:raise Failure('shield_block_unconfirmed')
        ctx.details.update(target=list(ref),blocked_for=duration,outcome='shielded')
        ctx.log('shield_block',target=list(ref),duration=duration)
    finally:
        ctx.stop_input()
        # The server-side shield globalstep clears blocking asynchronously.
        # Do not return a skill while the player is still slowed/interact-locked.
        ctx.wait(lambda s:not any(isinstance(x,str) and x.startswith('mcl_shield_hud.png')
                                  for x in s.raw.get('hud_images',())),
                 timeout=1,reason='shield_release_unconfirmed')
        if type(old) is int and old!=slot:
            fresh=ctx.read();items=fresh.inventory['main'].items
            if 0<=old<len(items) and items[old].count:wield_slot(ctx,old)

def evade_projectile(ctx, projectile, distance_to_move=3):
    """Take one smooth observed lateral leg away from an incoming trajectory."""
    state=ctx.read(6);v=projectile.velocity
    horizontal=math.hypot(v[0],v[2])
    if horizontal<.1:raise Failure('projectile_trajectory_unusable')
    candidates=[]
    for side in (-1,1):
        p=(state.position[0]+side*v[2]/horizontal*distance_to_move,state.position[1],
           state.position[2]-side*v[0]/horizontal*distance_to_move)
        goal=ctx.world.start(p)
        if goal is None:continue
        path,_=ctx.world.path(ctx.world.start(state.position),lambda q:q==goal,
                              lambda q:distance(ctx.world.point(q),p),within=ctx.within,max_nodes=1500)
        if path:candidates.append((len(path),path,p))
    if not candidates:raise Failure('projectile_evasion_route_unavailable')
    _,path,p=min(candidates,key=lambda x:x[0])
    ok,_=follow_path(ctx,path,p,through=True,cruise=True)
    if not ok:raise Failure('projectile_evasion_blocked')
    ctx.details.update(target=list(projectile.ref),outcome='evaded')

def extinguish_fire(ctx):
    """Enter already-observed water and confirm the visible flame overlay ends."""
    state=ctx.read(6)
    if not state.burning:ctx.details['outcome']='not_burning';return
    start=ctx.world.start(state.position)
    wet=lambda p:ctx.world.wading(p) or ctx.world.surface_water(p) or ctx.world.swimmable(p)
    path,_=ctx.world.path(start,wet,
                          lambda p:distance(ctx.world.point(p),state.position),within=ctx.within,max_nodes=2500)
    if not path:raise Failure('extinguishing_water_not_observed')
    ok,_=follow_path(ctx,path,ctx.world.point(path[-1]))
    if not ok:raise Failure('extinguishing_route_blocked')
    ctx.wait(lambda s:not s.burning,timeout=3,reason='burning_persists')
    ctx.details['outcome']='extinguished'

def food_choice(state, book, banned=BANNED_FOOD):
    # Catalog groups are a game adapter, not proof that the live server will eat.
    candidates=[]
    for item in state.inventory['main'].items:
        groups=book.items.get(item.name,{}).get('groups') or {}
        value=groups.get('eatable',0)
        if item.count and value>0 and item.name not in banned and not groups.get('poison',0):
            candidates.append((-value,item.name))
    return min(candidates)[1] if candidates else None

def eat_best(ctx, banned=BANNED_FOOD):
    from .survival import eat
    state=ctx.read()
    if state.hunger is None:raise Failure('hunger_unavailable')
    if state.hunger>=20:ctx.details['outcome']='already_full';return
    name=food_choice(state,ctx.book,banned)
    if not name:raise Failure('no_suitable_food')
    ctx.details['hunger_before']=state.hunger
    eat(ctx,name,1)
    # Only a normally completed meal restores the previous held item. This
    # fresh read checks cancellation, control epoch and emergency priority;
    # cleanup after an interrupted meal never delays the next reaction.
    after=ctx.read();ctx.details['hunger_after']=after.hunger
    old_slot=state.raw.get('wield');items=state.inventory['main'].items
    if type(old_slot) is not int or not 0<=old_slot<len(items):
        ctx.details['wield_restore']='previous_wield_unavailable';return
    if after.raw.get('wield')!=ctx.details.get('food_slot'):
        ctx.details['wield_restore']='wield_changed';return
    old=items[old_slot];current=after.inventory['main'].items
    if old.name==name:
        ctx.details['wield_restore']='unchanged';return
    if not old.count:
        slot=old_slot if old_slot<len(current) and not current[old_slot].count else None
    else:
        # Wielding food may relocate a full-hotbar tool. Follow exact stack
        # identity (including metadata), not just a slot or a similar name.
        key=(old.name,old.wear,old.stack_key)
        matches=[i for i,x in enumerate(current) if x.count and old.stack_key and
                 (x.name,x.wear,x.stack_key)==key]
        slot=old_slot if old_slot in matches else next(iter(matches),None)
    if slot is None:
        ctx.details['wield_restore']='previous_item_unavailable';return
    restored=wield_slot(ctx,slot)
    ctx.details.update(wield_restore='restored',restored_wield=restored)
    ctx.log('wield_restored',item=old.name,slot=restored)

def equip_best(ctx, armor=True, weapon=True):
    state=ctx.read();chosen=[]
    if armor:
        for slot,group in enumerate(('armor_head','armor_torso','armor_legs','armor_feet'),1):
            worn=state.inventory.get('armor')
            if worn is None or slot>=worn.size:continue
            old=worn.items[slot]
            score=lambda i:(ctx.book.items.get(i.name,{}).get('groups') or {}).get('mcl_armor_points',0)
            choices=[i for i in state.inventory['main'].items if i.count and
                     (ctx.book.items.get(i.name,{}).get('groups') or {}).get(group,0)>0]
            best=max(choices,key=lambda i:(score(i),-i.wear),default=None)
            if best and score(best)>score(old):
                equip(ctx,best.name,'armor');chosen.append(best.name);state=ctx.read()
    if weapon:
        rows=[r for r in state.raw.get('weapons',()) if not r.get('usable') and r.get('damage_groups',{}).get('fleshy',0)>0]
        if not rows:raise Failure('weapon_stats_unavailable')
        best=max(rows,key=lambda r:(r['damage_groups'].get('fleshy',0),-r['interval']))
        wield_slot(ctx,best['slot']);ctx.details['weapon']=best['name'] or 'hand'
    ctx.details['armor_equipped']=chosen

def require_entities(state):
    if not state.raw.get('entities_available') or 'entities' not in state.raw:raise Failure('entities_unavailable')
    if state.raw.get('entities_truncated'):raise Failure('entity_observation_truncated')

def current_target(ctx, ref):
    state=ctx.read(6);require_entities(state)
    return state,next((e for e in state.entities if e.ref==ref),None)

def weapon_interval(state):
    row=next((r for r in state.raw.get('weapons',()) if r['slot']==state.raw.get('wield')),None)
    if row is None or row.get('usable'):raise Failure('weapon_stats_unavailable')
    return max(.3,min(5,float(row['interval'])))

def chase(ctx, state, target, reach=2.8):
    start=ctx.world.start(state.position)
    # Entities are replicated farther than the permitted local node cube.
    # Advance through known geometry in short stages; require a clear target
    # ray only for the final approach, not through still-unobserved terrain.
    stage_reach=max(reach,distance(state.position,target.position)-3)
    goal=lambda p: distance(ctx.world.point(p),target.position)<stage_reach and (stage_reach>reach or ctx.world.visible(
        (ctx.world.point(p)[0],ctx.world.point(p)[1]+1.5,ctx.world.point(p)[2]),target.aim))
    path,_=ctx.world.path(start,goal,lambda p:max(0,distance(ctx.world.point(p),target.position)-stage_reach),
                          within=ctx.within,max_nodes=2500)
    if not path:raise Failure('entity_route_unavailable',{'target':target.ref})
    deadline=time.monotonic()+.45
    ctx.movement_look_target=target.aim
    try:
        ok,_=follow_path(ctx,path,ctx.world.point(path[-1]),partial=True,
                        until=lambda s:time.monotonic()>=deadline or distance(s.position,target.position)<reach)
        if not ok:raise Failure('entity_route_blocked')
    finally:ctx.movement_look_target=None

def attack(ctx, target, max_attacks=30, one_hit=False, auto_equip=True, *, defense_radius=None):
    ref=target_ref(target)
    if 'attack' not in ctx.game.capabilities:raise Failure('targeted_attack_unavailable')
    close_form(ctx)
    if auto_equip:equip_best(ctx)
    attacks=0;last_attack=-math.inf;missing_since=None
    ctx.details.update(target=list(ref),target_name=target.name,attacks_submitted=0,killed=None)
    while True:
        state,target=current_target(ctx,ref)
        if defense_radius is not None:
            target=next((e for e in hostiles(state,defense_radius) if e.pointable),None)
            if target is not None and target.ref!=ref:
                ctx.log('defense_retarget',previous=list(ref),target=list(target.ref))
                ref=target.ref
                ctx.details.update(target=list(ref),target_name=target.name)
            # Keep the weapon cooldown and total attack budget across targets.
        if target is None or (not target.pointable and attacks>0):
            if attacks==0 and defense_radius is None:raise Failure('target_not_observed')
            if missing_since is None:missing_since=time.monotonic();ctx.stop_input()
            if time.monotonic()-missing_since>=.6:
                ctx.details['outcome']=('no_attackable_threat' if defense_radius is not None else
                    'target_no_longer_observed' if target is None else 'target_no_longer_attackable');return
            ctx.sleep(.08);continue
        missing_since=None
        if target.is_player or not target.pointable:raise Failure('target_no_longer_attackable')
        if attacks>=max_attacks:raise Failure('attack_limit')
        if distance(state.position,target.position)>2.8:
            chase(ctx,state,target);continue
        # Smooth aim, then recheck native raycast + the generation immediately.
        face(ctx,target.aim)
        state,target=current_target(ctx,ref)
        if target is None:continue
        if defense_radius is not None:
            nearest=next((e for e in hostiles(state,defense_radius) if e.pointable),None)
            if nearest is None or nearest.ref!=ref:continue
        if state.pointed_entity!=ref:
            chase(ctx,state,target,reach=2.2);ctx.sleep(.08);continue
        interval=weapon_interval(state)
        if time.monotonic()-last_attack>=interval:
            try:ctx.game._submit('attack',target_id=ref[0],instance=ref[1])
            except ActionError as exc:
                if exc.code!='entity_not_in_crosshair':raise
                # A moving mob can leave the ray between observe and submit.
                # The native side rejected this input; observe and aim again,
                # without counting a hit or relaxing any native target guard.
                ctx.log('attack_reaim',reason=exc.code);ctx.sleep(.05);continue
            attacks+=1;last_attack=time.monotonic()
            ctx.details['attacks_submitted']=attacks;ctx.log('attack_submitted',target=list(ref),interval=interval)
            if one_hit:
                ctx.sleep(.12);ctx.details['outcome']='attack_submitted';return
        ctx.sleep(.08)

def segment_clearance(a, b, threats):
    """Closest approach along a straight leg, not merely at its endpoints."""
    delta=tuple(y-x for x,y in zip(a,b));length=sum(v*v for v in delta)
    def separation(e):
        t=max(0,min(1,sum((e.position[i]-a[i])*delta[i] for i in range(3))/length)) if length else 0
        return distance(tuple(a[i]+t*delta[i] for i in range(3)),e.position)
    return min((separation(e) for e in threats),default=math.inf)

def retreat_segment_allowed(a, b, threats, clearance):
    """Keep the band, or move out without getting closer if a pursuer entered it."""
    for e in threats:
        current=distance(a,e.position)
        required=min(clearance,current)
        if segment_clearance(a,b,(e,))<required-1e-6:return False
        if current<clearance and distance(b,e.position)<=current+1e-6:return False
    return True

def escape_ray(ctx, state, threats, clearance, accept):
    """A known flat diagonal can fit between threats when grid edges cannot."""
    origin=state.position;start=ctx.world.start(origin);choices=[];seen=set()
    for i in range(16):
        angle=i*math.pi/8
        end=ctx.world.start((origin[0]+3*math.sin(angle),origin[1],origin[2]+3*math.cos(angle)))
        if end is None or end in seen or not ctx.within(end):continue
        seen.add(end);point=ctx.world.point(end)
        if abs(point[1]-origin[1])>.12 or not accept(end):continue
        score=min(distance(point,e.position) for e in threats)
        choices.append((score,end,point))
    for _,end,point in sorted(choices,reverse=True):
        if retreat_segment_allowed(origin,point,threats,clearance) and ctx.world.corridor_clear(origin,point):
            return [start,end]
    return None

def flee(ctx, threats=(), safe_distance=12, settle_time=1.0):
    refs={e.ref for e in threats};initial=None;quiet=None;safe_since=None;replans=0;retreat_started=False
    lateral=None;lateral_until=0;explored=[]
    committed=None;commit_until=0;recent_goals=[];blocked_legs=0
    close_form(ctx)
    while True:
        state=ctx.read(6);require_entities(state)
        # Selecting one pursuer must not hide another observed hostile.
        active=tuple(e for e in state.entities if e.ref in refs or e.hostile)
        if not active:
            safe_since=None
            if quiet is None:quiet=time.monotonic();ctx.stop_input()
            if time.monotonic()-quiet>=settle_time:
                ctx.details.update(outcome='no_threat_observed',clear_observed_for=time.monotonic()-quiet);return
            ctx.sleep(.08);continue
        quiet=None
        safety=lambda p:min(distance(p,e.position) for e in active)
        nearest=safety(state.position)
        if initial is None:initial=nearest;ctx.details['initial_distance']=initial
        ctx.details.update(nearest_distance=nearest,threats=[list(e.ref) for e in active],replans=replans)
        closing=max((sum(e.velocity[i]*(state.position[i]-e.position[i]) for i in range(3))/
                     max(.01,distance(state.position,e.position)) for e in active),default=0)
        margin=max(1,min(4,max(0,closing))*(settle_time+.25))
        buffered=safe_distance+(margin if retreat_started and closing>.1 else 0)
        if nearest>=safe_distance and (safe_since is not None or nearest>=buffered):
            if safe_since is None:safe_since=time.monotonic();ctx.stop_input()
            if time.monotonic()-safe_since>=settle_time:
                ctx.details.update(outcome='distance_reached',clear_observed_for=time.monotonic()-safe_since);return
            ctx.sleep(.08);continue
        safe_since=None;retreat_started=True
        start=ctx.world.start(state.position)
        # Incremental horizons expose new terrain without guessing unseen ground.
        # Like Mindcraft's distance+1 goal, leave a buffer before yielding.
        # Scale that buffer to the observed pursuer speed for the confirmation
        # window; never fabricate future entity positions or unseen terrain.
        # Plan beyond the acceptance boundary: the pursuer moves during a
        # half-second leg, and the follower slows near its lattice endpoint.
        # Acceptance at the endpoint itself creates endless chasing of a
        # moving threshold. Keep a distinct geometric goal and success test.
        target_distance=min(safe_distance+margin+max(.5,max(0,closing)*.6),nearest+3)
        # Do not cut through another observed melee threat on the way out.
        # A partial, genuinely safer route is useful even when the current
        # observation horizon cannot offer the whole 3-block improvement.
        clearance=min(nearest,3)-.15
        within=lambda p:ctx.within(p) and safety(ctx.world.point(p))>=clearance
        path=None;seen={}
        # Keep a short chosen leg instead of selecting the opposite side of
        # moving pursuers on every .5 s refresh. Geometry and live threat bands
        # still gate every steer; this is a target lease, not a longer input lease.
        if committed is not None and lateral is None:
            if distance(state.position,ctx.world.point(committed))<.25 or time.monotonic()>=commit_until:
                committed=None
            else:
                point=ctx.world.point(committed)
                if ctx.world.corridor_clear(state.position,point) and retreat_segment_allowed(state.position,point,active,clearance):path=[start,committed]
                else:path,_=ctx.world.path(start,lambda p:p==committed,
                    lambda p:distance(ctx.world.point(p),point),within=within,max_nodes=3000)
                if path is None:committed=None
        # Commit to a bounded lateral observation point across short replans.
        # Otherwise the previous local maximum wins again and causes a U-turn.
        if lateral is not None:
            if distance(state.position,ctx.world.point(lateral))<.5 or time.monotonic()>=lateral_until:
                ctx.log('escape_frontier_finished',target=ctx.world.point(lateral))
                lateral=None
            else:
                path,_=ctx.world.path(start,lambda p:p==lateral,
                    lambda p:distance(ctx.world.point(p),ctx.world.point(lateral)),within=within,max_nodes=3000)
                if path is None:lateral=None
        if path is None:
            fresh_goal=lambda p:all(distance(ctx.world.point(p),q)>1.5 for q in recent_goals)
            goal=lambda p:fresh_goal(p) and safety(ctx.world.point(p))>=target_distance
            path=escape_ray(ctx,state,active,clearance,goal)
            if path is None:
                path,seen=ctx.world.path(start,goal,
                    lambda p:max(0,target_distance-safety(ctx.world.point(p))),within=within,max_nodes=3000)
            if path is None:
                path=escape_ray(ctx,state,active,clearance,lambda p:fresh_goal(p) and safety(ctx.world.point(p))>nearest+.08)
        if not path:
            # The rounded start cell can still be ahead of the actual player.
            # Keep its final centimetres when a short leg is nearly complete.
            candidates=[p for p in seen if distance(ctx.world.point(p),state.position)>.08
                        and safety(ctx.world.point(p))>nearest+.08 and fresh_goal(p)]
            if candidates:
                goal=max(candidates,key=lambda p:safety(ctx.world.point(p))-.05*seen[p])
                path,_=ctx.world.path(start,lambda p:p==goal,
                    lambda p:distance(ctx.world.point(p),ctx.world.point(goal)),within=within,max_nodes=3000)
                if path:ctx.log('partial_escape_progress',nearest_distance=nearest,target_distance=safety(ctx.world.point(goal)))
        if not path and len(explored)<4:
            # A distance plateau is not proof of a dead end. Explore a nearby
            # *observed and reachable* edge, retaining the same clearance along
            # every followed segment. Never invent terrain beyond that edge.
            candidates=[p for p,cost in seen.items() if ctx.world.frontier(p) and cost<=18
                and 2<distance(ctx.world.point(p),state.position)<=12
                and safety(ctx.world.point(p))>=max(clearance,nearest-3)
                and all(distance(ctx.world.point(p),q)>2 for q in explored) and fresh_goal(p)]
            if candidates:
                lateral=max(candidates,key=lambda p:safety(ctx.world.point(p))-.02*seen[p])
                path,_=ctx.world.path(start,lambda p:p==lateral,
                    lambda p:distance(ctx.world.point(p),ctx.world.point(lateral)),within=within,max_nodes=3000)
                if path:
                    explored.append(ctx.world.point(lateral));lateral_until=time.monotonic()+6
                    ctx.log('escape_frontier',target=ctx.world.point(lateral),attempt=len(explored),nearest_distance=nearest)
                    ctx.details['frontiers_attempted']=len(explored)
        if not path:raise Failure('escape_route_unavailable',{'nearest_distance':nearest})
        if lateral is None and committed is None:
            committed=path[-1];commit_until=time.monotonic()+1.5
            recent_goals.append(ctx.world.point(committed));recent_goals=recent_goals[-12:]
            ctx.log('escape_leg',target=ctx.world.point(committed))
        replans+=1;end=time.monotonic()+.5
        positions={e.ref:e.position for e in active}
        def reconsider(s):
            fresh=tuple(e for e in s.entities if e.ref in refs or e.hostile)
            if {e.ref for e in fresh}!=set(positions):
                ctx.stop_input();return True
            # Refresh the live segment guard before the next steer, not only
            # when a pursuer has moved an arbitrary .75 blocks.
            live[0]=fresh
            return time.monotonic()>=end
        prior=getattr(ctx,'movement_segment_allowed',None)
        live=[active]
        ctx.movement_segment_allowed=lambda a,b:retreat_segment_allowed(a,b,live[0],clearance) and (prior is None or prior(a,b))
        try:
            # A one-block escape is real progress: generic partial following
            # returns two blocks early, before it has issued any movement.
            target=ctx.world.point(path[-1]);cruise=route_runout(ctx,state.position,target)
            ok,_=follow_path(ctx,path,target,tolerance=.4 if cruise else .08,through=True,until=reconsider,cruise=cruise)
            last=getattr(ctx,'last',None)
            if cruise and last is not None and distance(last.position,target)<.4:committed=None
        finally:
            if prior is None:del ctx.movement_segment_allowed
            else:ctx.movement_segment_allowed=prior
        if not ok:
            # A live pursuer can invalidate a formerly safe leg between scans.
            # Stop first, discard that target, then plan from fresh observations;
            # a bounded failure is preferable to retrying one segment forever.
            ctx.stop_input();committed=None;lateral=None;blocked_legs+=1
            ctx.log('escape_replan',blocked_legs=blocked_legs)
            if blocked_legs>=3:raise Failure('escape_route_blocked')
        else:blocked_legs=0

def defend(ctx, radius=8, safe_distance=12, min_hp=6, settle_time=1.0):
    state=ctx.read(6);require_entities(state);enemies=hostiles(state,radius)
    if not enemies:ctx.details['outcome']='no_threat_observed';return
    enemies=tuple(e for e in enemies if e.pointable)
    if not enemies:ctx.details['outcome']='no_attackable_threat';return
    ctx.min_hp=min_hp
    try:attack(ctx,enemies[0],defense_radius=radius)
    except Failure as exc:
        if exc.reason not in ('health_floor','damage_budget_exceeded',
                              'entity_route_unavailable','entity_route_blocked'):
            raise
        ctx.log('retreat',reason=exc.reason,hp=ctx.last.hp)
        ctx.min_hp=1;ctx.damage_budget=100;ctx.damage_taken=0
        flee(ctx,enemies,safe_distance,settle_time)
        ctx.details['outcome']=('retreated_unreachable'
                                if exc.reason.startswith('entity_route_')
                                else 'retreated')


def escape_hazard(ctx):
    state=ctx.read(6)
    hazards=state.raw.get('hazards',())
    if not hazards:ctx.details['outcome']='no_contact_hazard_observed';return
    start_cell=cell(state.position)
    ctx.escape_cells={tuple(h['position']) for h in hazards}
    # Include only already occupied footprint cells, never a new pool of lava.
    for p,n in ctx.world.nodes.items():
        if n.damage and abs(p[0]-state.position[0])<.8 and abs(p[2]-state.position[2])<.8 and abs(p[1]-state.position[1])<2:
            ctx.escape_cells.add(p)
    original={p:ctx.world.nodes[p] for p in ctx.escape_cells if p in ctx.world.nodes}
    try:
        state=ctx.read(6);start=ctx.world.start(state.position)
        def clear(p):
            return all(distance(ctx.world.point(p),q)>2.5 for q in ctx.escape_cells) and not ctx.world.swimmable(p)
        path,_=ctx.world.path(start,clear,within=ctx.within,max_nodes=2500)
        if not path:raise Failure('hazard_escape_route_unavailable')
        ctx.log('leave_contact_hazard',hazards=hazards)
        ok,_=follow_path(ctx,path,ctx.world.point(path[-1]))
        if not ok:raise Failure('hazard_escape_route_blocked')
        if ctx.read().raw.get('hazards'):raise Failure('hazard_contact_persists')
        ctx.details['outcome']='left_contact_hazard'
    finally:
        ctx.escape_cells=set();ctx.world.nodes.update(original)
