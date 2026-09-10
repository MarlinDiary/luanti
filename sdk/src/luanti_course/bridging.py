"""Continuous crouched backwards bridging via observed attachment faces."""
import math,time
from .skills import Failure,wield_slot,count_items
from .errors import CourseError

def bridge_axis(support,target,goal):
    delta=tuple(target[i]-support[i] for i in range(3))
    if delta[1] or abs(delta[0])+abs(delta[2])!=1:return None
    # This is a straight span, not an invented strategy for a turning route.
    cross=(goal[0]-support[0])*delta[2]-(goal[2]-support[2])*delta[0]
    along=(goal[0]-support[0])*delta[0]+(goal[2]-support[2])*delta[2]
    if abs(goal[1]-(support[1]+.5))>.15 or abs(cross)>.5 or along<1:return None
    return delta

def stream_bridge(ctx,actions,goal):
    if len(actions)!=1 or actions[0][0]!='build' or not {'independent_heading','steer_place'}.issubset(set(ctx.game.capabilities)):return False
    state=ctx.read(6);start=ctx.world.start(state.position)
    if start is None:return False
    support=(start[0],round(start[1]-1),start[2]);target=tuple(int(x) for x in actions[0][1]);direction=bridge_axis(support,target,goal)
    if direction is None:return False
    node=ctx.world.nodes.get(support)
    if not node or not node.full_cube or not node.harmless:return False
    item=ctx.world.traversal.build_with
    if not item:return False
    slot=state.inventory['main'].find(item)
    if slot is None:raise Failure('item_not_held',{'item':item})
    wield_slot(ctx,slot)
    travel=math.degrees(math.atan2(-direction[0],direction[2]));view=travel+180
    ctx.log('backward_bridge_start',direction=direction,position=support)
    completed=0;pending=None
    try:
        while completed<128:
            state=ctx.read(6);node=ctx.world.nodes.get(target)
            if node is None:raise Failure('bridge_target_unobserved')
            if node.walkable and node.full_cube and node.harmless:break
            if not node.buildable or not node.harmless:raise Failure('bridge_target_occupied')
            if not ctx.within(target):raise Failure('target_out_of_radius')
            if ctx.terrain_edits>=ctx.world.traversal.edit_budget:raise Failure('terrain_edit_budget')
            if (target[0]-goal[0])*direction[0]+(target[2]-goal[2])*direction[2]>.5:break
            for dy in (1,2):
                head=ctx.world.nodes.get((target[0],target[1]+dy,target[2]))
                if head is None or not head.harmless or head.walkable:raise Failure('bridge_headroom_blocked')
            state=ctx.read();count=count_items(state,item,ctx.book);revision=state.inventory_revision
            if not count:raise Failure('item_not_held',{'item':item})
            pending=(target,revision,count)
            stance=(support[0]+direction[0]*.80,support[1]+.5,support[2]+direction[2]*.80)
            deadline=min(ctx.deadline,time.monotonic()+7);clicked=False;released=False;sent=0
            while time.monotonic()<deadline:
                state=ctx.read(6);current=ctx.world.nodes.get(target)
                if current and current.name==item:
                    if state.inventory_revision>revision and count_items(state,item,ctx.book)==count-1:break
                if abs(state.position[1]-stance[1])>.18:raise Failure('bridge_stance_unstable')
                # Travel remains forward in world space while the camera faces
                # the attachment behind the player. Crouching guards the edge.
                pitch=min(89.0,math.degrees(math.atan2(state.eye[1]-support[1],.29)))
                speed=.55
                can_place=(state.pointed_node==support and tuple(state.raw.get('pointed_above',()))==target
                           and abs((state.yaw-view+180)%360-180)<1 and abs(state.pitch-pitch)<1)
                press=False
                if not clicked and can_place:
                    clicked=True;sent=time.monotonic();press=True
                elif clicked and not released:
                    if time.monotonic()-sent<.10:press=True
                    else:released=True
                ctx.game._submit('steer',heading=view,move_heading=travel,pitch=pitch,speed=speed,jump=False,sneak=True,place=press,duration_ms=300)
                ctx.sleep(.035)
            else:raise Failure('bridge_placement_unconfirmed',{'position':target})
            # Release right-click even when server confirmation arrived before
            # the timed pulse ended. Keep walking; the next block needs a new edge.
            ctx.game._submit('steer',heading=view,move_heading=travel,pitch=state.pitch,speed=.4,jump=False,sneak=True,place=False,duration_ms=300)
            ctx.sleep(.04)
            ctx.terrain_edits+=1;completed+=1
            ctx.details.setdefault('terrain_changes',[]).append(dict(action='build',position=target))
            ctx.log('bridge_support_confirmed',item=item,position=target)
            pending=None
            support=target;target=tuple(support[i]+direction[i] for i in range(3))
        ctx.log('backward_bridge_end',blocks=completed)
        ctx.details['backward_bridge_blocks']=ctx.details.get('backward_bridge_blocks',0)+completed
        return bool(completed)
    finally:
        ctx.stop_input()
        # A cancellation may arrive after the server placed a block but before
        # the normal acknowledgement loop records it. Reconcile read-only after
        # releasing input; never hide an already observed world/material change.
        if pending is not None and not ctx.game._closed:
            try:
                state=ctx.game.observe(6);ctx.world.update(state)
                p,revision,count=pending;n=ctx.world.nodes.get(p)
                if n and n.name==item and state.inventory_revision>revision and count_items(state,item,ctx.book)==count-1:
                    ctx.terrain_edits+=1
                    ctx.details.setdefault('terrain_changes',[]).append(dict(action='build',position=p))
                    ctx.details['backward_bridge_blocks']=completed+1
                    ctx.log('bridge_support_confirmed',item=item,position=p,after_stop=True)
            except (CourseError,ValueError):pass

def direct_bridge(ctx,goal):
    """Prefer an observed straight span over a sideways frontier detour."""
    if not ctx.world.traversal.build_with or not {'independent_heading','steer_place'}.issubset(set(ctx.game.capabilities)):return False
    state=ctx.last;start=ctx.world.start(state.position)
    if start is None:return False
    dx,dz=goal[0]-state.position[0],goal[2]-state.position[2]
    if abs(goal[1]-state.position[1])>.15:return False
    if abs(dz)<.35 and abs(dx)>1:direction=(1 if dx>0 else -1,0,0)
    elif abs(dx)<.35 and abs(dz)>1:direction=(0,0,1 if dz>0 else -1)
    else:return False
    path=[start]
    for i in range(1,min(7,int(max(abs(dx),abs(dz)))+1)):
        p=tuple(start[j]+direction[j]*i for j in range(3));floor=(p[0],p[1]-1,p[2]);n=ctx.world.nodes.get(floor)
        if not n or not n.harmless:return False
        for dy in (0,1):
            body=ctx.world.nodes.get((p[0],p[1]+dy,p[2]))
            if not body or body.walkable or not body.harmless:return False
        if n.buildable:
            from .skills import follow_path
            if len(path)>1:
                ok,_=follow_path(ctx,path,ctx.world.point(path[-1]),.24)
                if not ok:return False
            ctx.stop_input()
            return stream_bridge(ctx,[('build',floor)],goal)
        if not n.full_cube or not n.walkable:return False
        path.append(p)
    return False
