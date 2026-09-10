"""Explicit, bounded construction jobs; observed support and real materials only."""
import math
from dataclasses import replace
from .navigation import cell,feet,distance
from .skills import Failure,navigate,place_block,dig_node,face,wield_slot,count_items,use_keys

def position(p):
    if len(p)!=3 or any(type(v) is not int or abs(v)>32700 for v in p):raise ValueError('expected three integer node coordinates')
    return tuple(p)

def validate_route(route):
    route=tuple(position(p) for p in route)
    if not 1<=len(route)<=128:raise ValueError('route must have 1..128 cells')
    if len(set(route))!=len(route):raise ValueError('excavation route must not revisit cells')
    for a,b in zip(route,route[1:]):
        if abs(a[0]-b[0])+abs(a[2]-b[2])!=1 or abs(a[1]-b[1])>1:raise ValueError('use adjacent horizontal or stair steps, not a blind vertical shaft')
    return route

def validate_blueprint(blocks):
    result=[];seen=set()
    for item,p in blocks:
        p=position(p)
        if not isinstance(item,str) or not item or p in seen:raise ValueError('invalid or duplicate blueprint block')
        result.append((item,p));seen.add(p)
    if not 1<=len(result)<=128:raise ValueError('blueprint must have 1..128 blocks')
    return tuple(result)

def safe_dig(ctx,p):
    state=ctx.read(6);n=ctx.world.nodes.get(p)
    if n is None:raise Failure('excavation_unobserved',{'position':p})
    if n.liquid or n.damage or n.drowning:raise Failure('excavation_hazard',{'position':p})
    if not n.walkable:return
    own=cell(state.position)
    if p==(own[0],own[1]-1,own[2]):raise Failure('would_remove_support')
    for dx,dy,dz in ((0,1,0),(1,0,0),(-1,0,0),(0,0,1),(0,0,-1)):
        other=ctx.world.nodes.get((p[0]+dx,p[1]+dy,p[2]+dz))
        if other is None or other.liquid or other.damage or other.drowning or (dy==1 and other.groups.get('falling_node',0)):
            raise Failure('unstable_excavation_boundary',{'position':p})
    if ctx.terrain_edits>=ctx.world.traversal.edit_budget:raise Failure('terrain_edit_budget')
    dig_node(ctx,p);ctx.terrain_edits+=1
    ctx.details.setdefault('terrain_changes',[]).append(dict(action='dig',position=p))

def excavate(ctx,route,return_to_start=True):
    route=validate_route(route);navigate(ctx,feet(route[0]));start=route[0]
    ctx.details['completed_cells']=[]
    for previous,p in zip(route,route[1:]):
        state=ctx.read(6)
        support=ctx.world.nodes.get((p[0],p[1]-1,p[2]))
        if not support or not support.harmless or not support.walkable or not support.full_cube or support.groups.get('falling_node',0):raise Failure('excavation_floor_unstable',{'position':p})
        # Descending needs the full swept headroom at the original height too.
        top=max(previous[1],p[1])+math.ceil(ctx.world.height)-1
        for y in range(top,p[1]-1,-1):safe_dig(ctx,(p[0],y,p[2]))
        navigate(ctx,feet(p));ctx.details['completed_cells'].append(p)
        # Verify an observed reverse route before proceeding deeper.
        back,_=ctx.world.path(ctx.world.start(ctx.read(6).position),lambda q:q==start,within=ctx.within)
        if back is None:raise Failure('return_route_missing')
    if return_to_start:
        navigate(ctx,feet(start));ctx.details['returned_to_start']=True
    ctx.details['excavated_steps']=len(route)-1

def construction_station(ctx,pending):
    """One observed stance can place a cluster; avoid walking once per block."""
    if len(pending)<3:return
    state=ctx.last;world=ctx.world;reserved={p for _,p in pending}
    faces={}
    for _,p in pending:
        n=world.nodes.get(p)
        if not n or not n.buildable:continue
        aims=[]
        for d in ((0,-1,0),(1,0,0),(-1,0,0),(0,0,1),(0,0,-1)):
            q=tuple(p[i]+d[i] for i in range(3));support=world.nodes.get(q)
            if support and support.full_cube and support.walkable and support.harmless:
                aims.append(tuple(q[i]-d[i]*.49 for i in range(3)))
        if aims:faces[p]=aims
    def coverage(eye):
        return sum(any(distance(eye,a)<3.4 and world.visible(eye,a) for a in aims) for aims in faces.values())
    current=coverage(state.eye)
    # Use the reachable work at a chosen station before optimizing another
    # stance. Re-ranking after every placement caused needless mid-row walks.
    if getattr(ctx,'construction_station_chosen',False) and current:return
    rank=[]
    eye_offset=state.eye[1]-state.position[1]
    for q in world.nodes:
        if q in reserved or (q[0],q[1]+1,q[2]) in reserved or not ctx.within(q) or not world.standable(q):continue
        foot=world.point(q)
        if distance(foot,state.position)>7:continue
        eye=(foot[0],foot[1]+eye_offset,foot[2]);n=coverage(eye)
        if n>=current+2:rank.append((-n,distance(foot,state.position),q))
    start=world.start(state.position)
    for neg,_,q in sorted(rank)[:12]:
        path,_=world.path(start,lambda t:t==q,blocked=ctx.blocked,within=ctx.within)
        if path is not None:
            ctx.construction_station_chosen=True
            ctx.log('construction_station',position=q,coverage=-neg)
            look=min(faces,key=lambda p:distance(p,q))
            navigate(ctx,world.point(q),look_at=look);return

def build(ctx,blocks):
    pending=list(validate_blueprint(blocks));done=[]
    xs=[p[0] for _,p in pending];zs=[p[2] for _,p in pending]
    axis=0 if max(xs)-min(xs)>max(zs)-min(zs) else 2
    initial=ctx.read().position;values=[p[axis] for _,p in pending]
    sign=1 if abs(initial[axis]-min(values))<=abs(initial[axis]-max(values)) else -1
    while pending:
        ctx.read(6);construction_station(ctx,pending);ctx.read(6);progress=False;errors=[]
        for item,p in sorted(pending,key=lambda b:(b[1][1],sign*b[1][axis],b[1][2-axis])):
            n=ctx.world.nodes.get(p)
            if n and n.name==ctx.book.resolve(item):
                done.append(p);pending.remove((item,p));progress=True;continue
            if ctx.terrain_edits>=ctx.world.traversal.edit_budget:raise Failure('terrain_edit_budget')
            try:place_block(ctx,item,p)
            except Failure as exc:
                if exc.reason not in ('no_placement_face','placement_face_not_in_crosshair','placement_intersects_player','no_path'):raise
                errors.append(dict(position=p,reason=exc.reason));continue
            ctx.terrain_edits+=1;done.append(p);pending.remove((item,p));progress=True
            ctx.details.update(completed_blocks=list(done),remaining_blocks=len(pending))
            break
        if not progress:raise Failure('blueprint_unreachable',{'completed_blocks':done,'remaining_blocks':pending,'obstacles':errors})
    ctx.details.update(completed_blocks=done,remaining_blocks=0)

def build_ladder(ctx,bottom,height,backing,material='mcl_core:ladder',backing_material=None):
    bottom=position(bottom)
    if type(height) is not int or not 1<=height<=32:raise ValueError('height must be 1..32')
    if tuple(backing) not in ((1,0,0),(-1,0,0),(0,0,1),(0,0,-1)):raise ValueError('backing is a horizontal wall direction')
    if not ctx.book.items.get(material,{}).get('groups',{}).get('ladder',0):raise Failure('not_ladder_material')
    navigate(ctx,feet(bottom));done=[]
    for i in range(height):
        p=(bottom[0],bottom[1]+i,bottom[2]);wall=tuple(p[j]+backing[j] for j in range(3))
        ctx.read(6);n=ctx.world.nodes.get(p);support=ctx.world.nodes.get(wall)
        if support and support.buildable and backing_material:
            if ctx.terrain_edits>=ctx.world.traversal.edit_budget:raise Failure('terrain_edit_budget')
            definition=ctx.game._request('inspect_item',name=backing_material)
            if not definition['walkable'] or not definition['full_cube'] or definition['liquid'] or definition['damage_per_second'] or definition['groups'].get('falling_node',0):raise Failure('building_material_not_full_cube')
            place_block(ctx,backing_material,wall);ctx.terrain_edits+=1;ctx.read(6);support=ctx.world.nodes.get(wall)
        if not support or not support.harmless or not support.full_cube or not support.walkable:raise Failure('ladder_backing_missing',{'position':wall})
        if not n or (not n.buildable and not n.climbable):raise Failure('ladder_target_occupied',{'position':p})
        if not n.climbable:
            if ctx.terrain_edits>=ctx.world.traversal.edit_budget:raise Failure('terrain_edit_budget')
            state=ctx.read();slot=state.inventory['main'].find(material)
            if slot is None:raise Failure('item_not_held',{'item':material})
            wield_slot(ctx,slot);aim=tuple(wall[j]-backing[j]*.49 for j in range(3));face(ctx,aim)
            ctx.wait(lambda s:s.pointed_node==wall,reason='ladder_wall_not_in_crosshair')
            before=count_items(ctx.read(),material,ctx.book);ctx.game.hold(use_keys(ctx,wall),.12)
            ctx.wait(lambda s:ctx.world.nodes.get(p) and ctx.world.nodes[p].climbable and count_items(s,material,ctx.book)==before-1,reason='ladder_placement_unconfirmed',radius=6)
            ctx.terrain_edits+=1
        done.append(p);ctx.details.update(ladder_blocks=done)
        # Ascend the built portion, placing the next reachable wall section.
        state=ctx.read()
        view_yaw=math.degrees(math.atan2(-backing[0],backing[2]))
        # Face the next attachment from the landing pose, not a nearby point
        # whose pitch crosses above/below the moving eye on every rung.
        view_pitch=math.degrees(math.atan2(state.eye[1]-state.position[1]-1.5,.51))
        navigate(ctx,feet(p),look_direction=(view_yaw,view_pitch))
    ctx.log('ladder_descent_start',position=bottom)
    navigate(ctx,feet(bottom),look_direction=(view_yaw,45));ctx.details['returned_to_bottom']=True
