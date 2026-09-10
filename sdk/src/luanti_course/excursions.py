"""Bounded mining jobs and a remembered return trail, not an ore-search planner."""
from contextlib import nullcontext
from dataclasses import asdict, replace
from pathlib import Path
import copy
import json
import math
import os
from .construction import position, safe_dig
from .navigation import cell, feet, distance
from .persistence import checkpoint_lock
from .skills import Failure, navigate, close_form, choose_tool

DIRECTIONS=((1,0,0),(0,0,1),(-1,0,0),(0,0,-1))

def direction(value):
    if value is None:return None
    if not isinstance(value,(list,tuple)) or tuple(value) not in DIRECTIONS or any(type(x) is not int for x in value):
        raise ValueError('direction must be one horizontal unit vector')
    return tuple(value)

def validate_distance(value,name='distance'):
    if type(value) is not int or not 1<=value<=64:raise ValueError(name+' must be 1..64 blocks')
    return value

def validate_trip(data,scope):
    if not isinstance(data,dict) or data.get('schema')!=2 or data.get('scope')!=scope:raise ValueError('mining trip client changed')
    trail=data.get('trail')
    if not isinstance(trail,list) or not 1<=len(trail)<=4096:raise ValueError('invalid return trail')
    trail=[position(p) for p in trail]
    for a,b in zip(trail,trail[1:]):
        if abs(a[0]-b[0])+abs(a[2]-b[2])!=1 or abs(a[1]-b[1])>1:raise ValueError('invalid return trail edge')
    if position(data.get('entry',()))!=trail[0]:raise ValueError('invalid mining entrance')
    return data

def read_checkpoint(path,scope):
    if path.stat().st_size>256000:raise ValueError('mining checkpoint too large')
    return validate_trip(json.loads(path.read_text()),scope)

def save_checkpoint(path,data):
    if path is None:return
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    with tmp.open('w') as f:
        json.dump(data,f,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def trail_to(ctx,trail,index):
    """Follow observed trail chunks continuously; only true obstacles replan."""
    from .skills import follow_path
    state=ctx.read(6)
    cursor=min(range(len(trail)),key=lambda i:distance(feet(trail[i]),state.position))
    if distance(feet(trail[cursor]),state.position)>8:raise Failure('return_trail_not_nearby')
    if distance(feet(trail[cursor]),state.position)>.5:navigate(ctx,feet(trail[cursor]))
    step=1 if cursor<index else -1
    while cursor!=index:
        ctx.read(6);path=[trail[cursor]];end=cursor
        for j in range(cursor+step,index+step,step):
            if not ctx.world.standable(trail[j]) or ctx.world.edge_plan(path[-1],trail[j])!=():break
            path.append(trail[j]);end=j
            if len(path)>=7:break
        if len(path)<2:
            end=cursor+step;navigate(ctx,feet(trail[end]))
        else:
            ok,_=follow_path(ctx,path,feet(path[-1]),.28,through=end!=index)
            if not ok:navigate(ctx,feet(path[-1]))
        cursor=end;ctx.details['return_progress']=cursor
        ctx.log('return_trail_chunk',cells=len(path),progress=cursor)


def preflight_step(ctx,previous,target):
    if not ctx.within(target):raise Failure('target_out_of_radius')
    support=ctx.world.nodes.get((target[0],target[1]-1,target[2]))
    if not support or not support.harmless or not support.walkable or not support.full_cube or support.groups.get('falling_node',0):
        raise Failure('excavation_floor_unstable',{'position':target})
    top=max(previous[1],target[1])+math.ceil(ctx.world.height)-1
    blocks=[]
    for y in range(top,target[1]-1,-1):
        p=(target[0],y,target[2]);n=ctx.world.nodes.get(p)
        if n is None:raise Failure('excavation_unobserved',{'position':p})
        if n.liquid or n.damage or n.drowning:raise Failure('excavation_hazard',{'position':p})
        if not n.walkable:continue
        for dx,dy,dz in ((0,1,0),(1,0,0),(-1,0,0),(0,0,1),(0,0,-1)):
            other=ctx.world.nodes.get((p[0]+dx,p[1]+dy,p[2]+dz))
            if other is None or not other.harmless or (dy==1 and other.groups.get('falling_node',0)):
                raise Failure('unstable_excavation_boundary',{'position':p})
        blocks.append(p)
    if ctx.terrain_edits+len(blocks)>ctx.world.traversal.edit_budget:raise Failure('terrain_edit_budget')
    # Check every required tool before making a partial opening.
    for p in blocks:choose_tool(ctx,p)
    return blocks

def mining_job(ctx,operation,steps,heading=None,checkpoint=None):
    path=Path(checkpoint).expanduser().resolve() if checkpoint is not None else None
    scope=str(ctx.game.endpoint.resolve())
    request=dict(depth=steps) if operation=='dig_down' else dict(length=steps)
    request.update(direction=list(heading) if heading is not None else None,traversal=asdict(ctx.world.traversal),search_radius=ctx.radius)
    guard=checkpoint_lock(path) if path is not None else nullcontext()
    try:
        with guard:
            close_form(ctx);state=ctx.read(6)
            if path is not None and path.exists():
                data=read_checkpoint(path,scope)
                if data.get('operation')!=operation or data.get('request')!=request:raise ValueError('mining checkpoint request changed')
                done=data.get('completed_steps')
                if type(done) is not int or not 0<=done<=steps or type(data.get('complete')) is not bool:raise ValueError('invalid mining progress')
                if data['complete'] and done!=steps:raise ValueError('invalid completed mining job')
            else:
                previous=getattr(ctx.game,'_mining_trip',None)
                here=cell(state.position)
                if previous is not None:
                    validate_trip(previous,scope)
                    trail=[tuple(p) for p in previous['trail']]
                    matches=[i for i,p in enumerate(trail) if p==here]
                    if not matches:raise Failure('mining_trip_disconnected',{'message':'Return to the trail, or call reset_mining_trip() to start a separate excursion.'})
                    trail=trail[:matches[-1]+1]
                else:trail=[here]
                data=dict(schema=2,scope=scope,operation=operation,request=request,entry=trail[0],trail=trail,completed_steps=0,complete=False)
            ctx.details.update(completed_steps=data['completed_steps'],requested_steps=steps,entry=feet(data['entry']),checkpoint=str(path) if path else None)
            ctx.game._mining_trip=copy.deepcopy(data)
            save_checkpoint(path,data)
            if data['complete']:
                ctx.details['already_complete']=True;return
            # Return navigation never silently spends more terrain-edit budget.
            old=ctx.world.traversal
            ctx.world.traversal=replace(old,allow_dig=False,build_with=None)
            try:trail_to(ctx,[tuple(p) for p in data['trail']],len(data['trail'])-1)
            finally:ctx.world.traversal=old
            try:
                while data['completed_steps']<steps:
                    if len(data['trail'])>=4096:raise Failure('return_trail_limit')
                    state=ctx.read(6);previous=tuple(data['trail'][-1])
                    choices=[heading] if heading is not None else list(DIRECTIONS)
                    if heading is None:
                        last=tuple(data['trail'][-2]) if len(data['trail'])>1 else None
                        if last:
                            forward=(previous[0]-last[0],0,previous[2]-last[2])
                            choices.sort(key=lambda d:d!=forward)
                    failures=[];selected=None
                    for d in choices:
                        target=(previous[0]+d[0],previous[1]-(operation=='dig_down'),previous[2]+d[2])
                        if target in [tuple(p) for p in data['trail']]:continue
                        try:blocks=preflight_step(ctx,previous,target)
                        except Failure as exc:
                            if exc.status in ('cancelled','timeout') or exc.reason in ('player_damaged','player_dead','control_released','low_breath','terrain_edit_budget','suitable_tool_required'):raise
                            failures.append(dict(direction=d,reason=exc.reason,details=exc.details));continue
                        selected=(target,blocks);break
                    if selected is None:raise Failure('mining_route_blocked',{'obstacles':failures})
                    target,blocks=selected
                    for p in blocks:safe_dig(ctx,p)
                    # Anticipate the next *observed* working face from the
                    # landing pose. Tracking a near point from the falling
                    # eye made pitch dip, rise, then stop halfway through a turn.
                    top=target[1]+math.ceil(ctx.world.height)-1
                    next_y=target[1]-(operation=='dig_down')
                    gaze=(target[0]+d[0],top,target[2]+d[2])
                    for y in range(top,next_y-1,-1):
                        p=(gaze[0],y,gaze[2]);node=ctx.world.nodes.get(p)
                        if node and node.walkable:gaze=p;break
                    eye_y=target[1]-.5+(state.eye[1]-state.position[1])
                    view=(math.degrees(math.atan2(-d[0],d[2])),math.degrees(math.atan2(eye_y-gaze[1],1)))
                    navigate(ctx,feet(target),look_direction=view)
                    data['trail'].append(list(target));data['completed_steps']+=1
                    ctx.details.update(completed_steps=data['completed_steps'],destination=feet(target))
                    ctx.log('mining_step',position=target,completed=data['completed_steps'])
                    save_checkpoint(path,data);ctx.game._mining_trip=copy.deepcopy(data)
                data['complete']=True
            finally:
                save_checkpoint(path,data);ctx.game._mining_trip=copy.deepcopy(data)
    except (ValueError,OSError) as exc:
        raise Failure('checkpoint_conflict',{'message':str(exc)})

def go_to_surface(ctx,surface=None,checkpoint=None):
    path=Path(checkpoint).expanduser().resolve() if checkpoint is not None else None
    scope=str(ctx.game.endpoint.resolve())
    try:
        with checkpoint_lock(path) if path else nullcontext():
            data=read_checkpoint(path,scope) if path else getattr(ctx.game,'_mining_trip',None)
            if surface is not None:
                navigate(ctx,surface);ctx.details.update(destination=surface,destination_kind='specified_surface')
                ctx.game._mining_trip=None
                return
            if data is None:raise Failure('surface_unknown',{'message':'Pass a known surface position, or use a mining return trail/checkpoint.'})
            validate_trip(data,scope);close_form(ctx)
            trail=[tuple(p) for p in data['trail']]
            trail_to(ctx,trail,0)
            ctx.game._mining_trip=copy.deepcopy(data)
            ctx.details.update(destination=feet(trail[0]),destination_kind='remembered_mining_entrance',returned=True)
            ctx.log('returned_to_entrance',position=trail[0])
    except (ValueError,OSError) as exc:raise Failure('checkpoint_conflict',{'message':str(exc)})
