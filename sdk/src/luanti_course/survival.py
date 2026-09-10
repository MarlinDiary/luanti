"""Explicit consumption of held food, without an automatic food procurement loop."""
import time
from .skills import Failure, close_form, face, wield_slot, count_items, use_keys
from .workstations import station_cleanup

@station_cleanup
def eat(ctx,item,count):
    item=ctx.book.resolve(item)
    groups=ctx.book.items.get(item,{}).get('groups') or {}
    if not groups.get('eatable',0):raise Failure('not_edible',{'item':item})
    close_form(ctx);state=ctx.read();initial=count_items(state,item,ctx.book)
    if initial<count:raise Failure('item_not_held',{'item':item,'needed':count,'held':initial})
    ctx.details.update(item=item,requested=count,consumed=0)
    for i in range(count):
        state=ctx.read();slot=state.inventory['main'].find(item)
        if slot is None:raise Failure('food_inventory_changed')
        ctx.details['food_slot']=wield_slot(ctx,slot)
        # Aim away from farm soil; only interactive/unknown faces need sneak-use.
        state=ctx.read()
        # Normal eating in a clear view needs no camera movement. Only retain
        # the air-use fallback when a pointed block could intercept right-click.
        pointed=getattr(state,'pointed_node',None)
        above=getattr(state,'raw',{}).get('pointed_above')
        # Known ordinary faces need no sneak; interactive faces still suppress callbacks. Eating
        # against a vertical wall needs no skyward camera reset. Keep air-use
        # for top faces/unknown geometry: edible seeds may plant on that face.
        avoid_face=pointed is not None
        if pointed is not None and above is not None and above[1]<=pointed[1] and ctx.book.items[item].get('type')=='craft':
            ctx.read(6)
            support=ctx.world.nodes.get((above[0],above[1]-1,above[2]))
            # A seed can also plant beside a wall when the adjacent cell sits
            # above farmland. Require observed non-soil before preserving aim.
            avoid_face=support is None or (support.groups or {}).get('soil',0)>0
        if avoid_face:
            face(ctx,(state.eye[0],state.eye[1]+6,state.eye[2]+.01))
        state=ctx.read();pointed=getattr(state,'pointed_node',None)
        if pointed is not None:ctx.read(6)
        keys=use_keys(ctx,pointed)
        before=count_items(state,item,ctx.book);end=min(ctx.deadline,time.monotonic()+6)
        pressed_at=time.monotonic()
        try:
            while time.monotonic()<end:
                # An air-use pressed during the server cooldown may be ignored.
                # Hold long enough for the normal eating animation, then re-arm
                # the button edge; renewing a held key alone never retries use.
                if time.monotonic()-pressed_at>=2.2:
                    ctx.stop_input();ctx.sleep(.12);pressed_at=time.monotonic()
                ctx.game._submit('input',keys=keys,duration_ms=400)
                ctx.sleep(.08);state=ctx.read()
                now=count_items(state,item,ctx.book)
                if now==before-1:
                    ctx.details['consumed']=i+1;ctx.log('food_consumed',item=item,count=i+1);break
                if now!=before:raise Failure('food_inventory_changed',{'observed_decrease':before-now})
            else:raise Failure('food_not_consumed',{'message':'Server did not consume the item; hunger may be full or eating disallowed.'})
        finally:ctx.stop_input()
        # Give the server its normal eating cooldown before requesting another item.
        if i+1<count:ctx.sleep(.2)
