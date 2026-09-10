"""Visible VoxeLibre workstation adapters; all moves use the current formspec."""
import math
import time
from functools import wraps
from .errors import CourseError
from collections import Counter
from .skills import Failure,close_form,navigate,face,approach_and_face,main_space,count_items,craft,collect,place_block
from .navigation import distance,cell
FURNACE='mcl_furnaces:furnace'

def station_cleanup(fn):
    @wraps(fn)
    def call(ctx,*args,**kwargs):
        try:return fn(ctx,*args,**kwargs)
        finally:
            # Cancellation does not leave our station UI blocking the next task.
            # Never close a menu after a human has taken control.
            try:
                state=ctx.game.observe()
                if state.control=='agent' and state.control_epoch==ctx.epoch and state.raw['menu_open']:
                    ctx.game.close_inventory()
            except CourseError:pass
    return call

def select_fuel(fuels,stock,seconds,preferred=None):
    candidates=[]
    for name,burn in fuels.items():
        if preferred and name!=preferred:continue
        if burn<=0:continue
        needed=math.ceil(seconds/burn)
        if 0<needed<=stock.get(name,0):candidates.append((needed*burn-seconds,needed,name))
    if not candidates:raise ValueError('insufficient suitable fuel')
    waste,needed,name=min(candidates);return name,needed

def stack_counts(items):
    c=Counter()
    for i in items:
        if i['count']:c[i['name']]+=i['count']
    return c

def forms(state,name):return [x for x in state.form['lists'] if x['name']==name]
def storage_lists(state):
    # Pinned VoxeLibre single/double chest adapter: each node list has 27 slots.
    # Player inventory is 36 slots, including its two displayed slices.
    lists=[x for x in forms(state,'main') if len(x['items'])==27 and x['first_slot']==0 and x['last_slot']==26]
    if not lists:raise Failure('container_form_unrecognized')
    return lists

def station_list(state,name):
    rows=forms(state,name)
    if len(rows)!=1 or len(rows[0]['items'])!=1:raise Failure('station_form_unrecognized',{'list':name})
    return rows[0]

def move_external(ctx,src,source,dst,dest,amount):
    """A bounded transfer with source and destination confirmation, never blind retry."""
    before=ctx.read();form_id=before.form['id']
    def readslot(s,ref,slot):
        if ref=='player':
            i=s.inventory['main'].items[slot];return dict(name=i.name,count=i.count,stack_key=i.stack_key)
        rows=[r for r in s.form['lists'] if r['location']==ref[0] and r['name']==ref[1]]
        if not rows:raise Failure('station_form_changed')
        return rows[0]['items'][slot]
    a,b=readslot(before,src,source),readslot(before,dst,dest)
    if a['count']<amount or (b['count'] and (a['name']!=b['name'] or a.get('stack_key')!=b.get('stack_key'))):raise Failure('inventory_changed')
    sl='main' if src=='player' else src[1];dl='main' if dst=='player' else dst[1]
    ctx.game.move_items(sl,source,dl,dest,amount,from_inventory='player' if src=='player' else src[0],to_inventory='player' if dst=='player' else dst[0],form_id=form_id)
    def confirmed(s):
        x,y=readslot(s,src,source),readslot(s,dst,dest)
        # Fuel may start burning immediately, but player decrement and same fuel
        # or an empty consumed slot still require the furnace active observation.
        consumed_fuel=dst!='player' and dst[1]=='fuel' and y['count']==0 and ctx.station_active(s)
        return x['count']==a['count']-amount and ((y['name']==a['name'] and y['count']==b['count']+amount) or consumed_fuel)
    ctx.wait(confirmed,reason='station_transfer_unconfirmed',radius=6)
    ctx.log('station_transfer',item=a['name'],count=amount,source=src,destination=dst)

def open_station(ctx,position,kind):
    close_form(ctx);navigate(ctx,position,approach=True);state=ctx.read(6);node=ctx.world.nodes.get(tuple(position))
    if node is None:raise Failure('station_unobserved')
    valid=node.name in (FURNACE,FURNACE+'_active') if kind=='furnace' else node.name in tuple('mcl_chests:'+n for n in ('chest_small','chest_left','chest_right','trapped_chest_small','trapped_chest_left','trapped_chest_right'))
    if not valid:raise Failure('station_type_unsupported',{'node':node.name,'kind':kind})
    approach_and_face(ctx,position,'station_not_in_crosshair')
    ctx.game.use(.12);state=ctx.wait(lambda s:s.raw['menu_open'] and bool(s.form['lists']),reason='station_open_unconfirmed')
    if kind=='furnace':
        for n in ('src','fuel','dst'):station_list(state,n)
    else:storage_lists(state)
    ctx.station_active=lambda s:ctx.world.nodes.get(tuple(position)) is not None and ctx.world.nodes[tuple(position)].name==FURNACE+'_active'
    return state

@station_cleanup
def transfer(ctx,position,item,count,direction):
    item=ctx.book.resolve(item);open_station(ctx,position,'chest');initial=count_items(ctx.read(),item,ctx.book);moved=0
    try:
        while moved<count:
            state=ctx.read();rows=storage_lists(state);choices=[]
            if direction=='deposit':
                sources=[(i,n) for n,i in enumerate(state.inventory['main'].items) if ctx.book.matches(i.name,item) and i.count]
                if not sources:raise Failure('item_not_held',{'transferred':moved})
                obj,source=sources[0]
                for row in rows:
                    for j,b in enumerate(row['items']):
                        if not b['count'] or (b['name']==obj.name and b.get('stack_key')==obj.stack_key):
                            room=ctx.book.items.get(obj.name,{}).get('stack_max',1)-b['count']
                            if room>0:choices.append((row,j,min(room,obj.count,count-moved,99)))
                if not choices:raise Failure('container_full',{'transferred':moved})
                row,dest,amount=choices[0];move_external(ctx,'player',source,(row['location'],'main'),dest,amount)
            else:
                for row in rows:
                    for j,obj in enumerate(row['items']):
                        if obj['count'] and ctx.book.matches(obj['name'],item):choices.append((row,j,obj))
                if not choices:raise Failure('container_item_missing',{'transferred':moved})
                row,source,obj=choices[0];amount=min(count-moved,obj['count'],99)
                dest=main_space(ctx,obj['name'],amount,obj.get('stack_key',''));move_external(ctx,(row['location'],'main'),source,'player',dest,amount)
            moved+=amount;ctx.details.update(item=item,transferred=moved,requested=count,container=position)
        expected=initial+count*(1 if direction=='withdraw' else -1)
        if count_items(ctx.read(),item,ctx.book)!=expected:raise Failure('container_balance_changed')
    finally:close_form(ctx)

def furnace_site(ctx,gather,preferred):
    if preferred is not None:return tuple(preferred)
    cp=getattr(ctx,'checkpoint',None)
    if cp and cp.data.get('station'):return tuple(cp.data['station']['position'])
    state=ctx.read(6)
    known=sorted((p for p,n in ctx.world.nodes.items() if n.name in (FURNACE,FURNACE+'_active')),key=lambda p:distance(p,state.position))
    if known:return known[0]
    if state.inventory['main'].count(FURNACE)==0:
        if not gather:raise Failure('furnace_required')
        craft(ctx,FURNACE,1,True);state=ctx.read(6)
    origin=cell(state.position)
    sites=sorted((p for p,n in ctx.world.nodes.items() if n.buildable and p[1]==origin[1] and 1.5<=distance(p,origin)<=3 and ctx.world.standable(p)),key=lambda p:distance(p,origin))
    for p in sites:
        try:place_block(ctx,FURNACE,p);return p
        except Failure as exc:
            if exc.reason not in ('no_placement_face','placement_face_not_in_crosshair'):raise
    raise Failure('furnace_placement_site_missing')

@station_cleanup
def smelt(ctx,item,count,*,gather=False,furnace=None,fuel=None):
    item=ctx.book.resolve(item);options=ctx.book.cooking.get(item,())
    if not options:raise Failure('cooking_recipe_unavailable',{'item':item})
    cp=getattr(ctx,'checkpoint',None)
    pending=cp.data.get('station') if cp else None
    if pending and pending['item']==item:options=[r for r in options if r['input']==pending['input']]
    state=ctx.read(6);start=count_items(state,item,ctx.book);known={n.name for n in ctx.world.nodes.values()};recipe=min(options,key=lambda r:(-state.inventory['main'].count(r['input']),not bool(ctx.book.resources(r['input']) & known),not bool(ctx.book.resources(r['input'])),r['input']))
    raw=recipe['input'];batches=math.ceil(count/recipe['count'])
    if batches>64:raise Failure('smelting_batch_limit')
    position=furnace_site(ctx,gather,furnace);cp=getattr(ctx,'checkpoint',None)
    oldstation=cp.data.get('station') if cp else None
    state=open_station(ctx,position,'furnace');source=station_list(state,'src')['items'][0];output=station_list(state,'dst')['items'][0]
    if source['count'] or output['count']:
        if not oldstation or oldstation['position']!=list(position) or oldstation['item']!=item:raise Failure('furnace_busy')
        if source['count'] and source['name']!=raw or output['count'] and output['name']!=item:raise Failure('furnace_contents_changed')
        if source['count']*recipe['count']+output['count']>batches*recipe['count']:raise Failure('furnace_contents_changed')
    inflight=source['count']+math.ceil(output['count']/recipe['count']);needed=max(0,batches-inflight)
    close_form(ctx)
    if ctx.read().inventory['main'].count(raw)<needed:
        if not gather:raise Failure('smelting_input_missing',{'item':raw,'needed':needed})
        collect(ctx,raw,needed-ctx.read().inventory['main'].count(raw))
    state=ctx.read();stock=Counter()
    for x in state.inventory['main'].items:stock[x.name]+=x.count
    fuels={n:t for n,t in ctx.book.fuels.items() if n in ('mcl_core:coal_lump','mcl_core:charcoal_lump','mcl_core:coalblock') or ctx.book.items.get(n,{}).get('groups',{}).get('wood',0) or ctx.book.items.get(n,{}).get('groups',{}).get('tree',0)}
    if fuel:
        fuel=ctx.book.resolve(fuel);fuels={fuel:ctx.book.fuels.get(fuel,0)}
    # Do not choose input ingredients as fuel without an explicit selection.
    if not fuel:fuels.pop(raw,None)
    state=open_station(ctx,position,'furnace');held_fuel=station_list(state,'fuel')['items'][0]
    credit=held_fuel['count']*ctx.book.fuels.get(held_fuel['name'],0)
    seconds=max(0,recipe['time']*(batches-math.floor(output['count']/recipe['count']))-credit)
    selected=None
    if seconds:
        try:selected=select_fuel(fuels,stock,seconds,fuel)
        except ValueError:
            if ctx.station_active(ctx.read(6)):
                selected=None
            elif gather:
                close_form(ctx)
                material=fuel or 'mcl_core:tree';burn=ctx.book.fuels.get(material,0)
                if not burn:raise Failure('fuel_unavailable')
                collect(ctx,material,max(1,math.ceil(seconds/burn)-stock[material]));state=open_station(ctx,position,'furnace')
                selected=(material,math.ceil(seconds/burn))
            else:raise Failure('fuel_unavailable')
    if cp:
        cp.data['station']=dict(position=list(position),item=item,input=raw,target=start+count);cp.save()
    # Load recipe input before fuel, then confirm both inventories.
    remaining=needed
    while remaining:
        state=ctx.read();row=station_list(state,'src');slot=state.inventory['main'].find(raw)
        if slot is None:raise Failure('smelting_input_changed')
        amount=min(remaining,state.inventory['main'].items[slot].count)
        move_external(ctx,'player',slot,(row['location'],'src'),0,amount);remaining-=amount
    if selected:
        name,remaining=selected
        while remaining:
            state=ctx.read();row=station_list(state,'fuel')
            if row['items'][0]['count'] and row['items'][0]['name']!=name:
                state=ctx.wait(lambda s:not station_list(s,'fuel')['items'][0]['count'] or station_list(s,'dst')['items'][0]['count']>=count,timeout=min(240,recipe['time']*batches+10),reason='fuel_slot_busy',radius=6)
                if station_list(state,'dst')['items'][0]['count']>=count:break
                row=station_list(state,'fuel')
            slot=state.inventory['main'].find(name)
            if slot is None:raise Failure('fuel_unavailable')
            amount=min(remaining,state.inventory['main'].items[slot].count)
            move_external(ctx,'player',slot,(row['location'],'fuel'),0,amount);remaining-=amount
    try:
        last_progress=time.monotonic();last_amount=0
        while count_items(ctx.read(),item,ctx.book)-start<count:
            state=ctx.read(6);row=station_list(state,'dst');out=row['items'][0]
            if out['count'] and out['name']!=item:raise Failure('cooking_output_mismatch')
            if out['count']:
                amount=min(out['count'],count-(count_items(state,item,ctx.book)-start));dest=main_space(ctx,item,amount,out.get('stack_key',''))
                move_external(ctx,(row['location'],'dst'),0,'player',dest,amount)
                last_progress=time.monotonic();last_amount+=amount
                if cp and cp.data['operation']=='smelt':
                    from .persistence import owned_count
                    cp.progress(owned_count(ctx.read(),item,ctx.book))
            elif time.monotonic()-last_progress>max(20,recipe['time']*2+5):
                raise Failure('cooking_stalled',{'station':position,'input_retained':True})
            else:ctx.sleep(.15)
        ctx.details.update(item=item,produced=count_items(ctx.read(),item,ctx.book)-start,furnace=position)
        ctx.log('smelting_confirmed',item=item,count=count,station=position)
        if cp:cp.data['station']=None;cp.save()
    finally:close_form(ctx)

@station_cleanup
def inspect_container(ctx,position):
    """Open a supported chest normally, copy its shown contents, transfer nothing."""
    state=open_station(ctx,position,'chest');rows=storage_lists(state)
    contents=[];counts=Counter();seen=set()
    for row in rows:
        identity=(row['location'],row['name'])
        if identity in seen:continue
        seen.add(identity)
        items=[dict(x) for x in row['items']]
        counts.update(stack_counts(items))
        contents.append(dict(location=row['location'],name=row['name'],items=items))
    ctx.details.update(container=position,counts=dict(counts),lists=contents,
                       form_id=state.form['id'],frame=state.frame,items_transferred=0)
    ctx.log('container_inspected',position=position,lists=len(contents))
    close_form(ctx)
