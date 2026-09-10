"""Read-only catalog/material planning. A plan is not a world execution promise."""
from collections import Counter
from dataclasses import asdict, dataclass, field
import copy
from .recipes import PlanningError, TABLE, batch_plan

@dataclass(frozen=True)
class CraftPlan:
    item: str
    count: int
    materials_ready: bool
    reason: str = ''
    missing: dict = field(default_factory=dict)
    missing_complete: bool = False
    steps: tuple = ()
    requirements: dict = field(default_factory=dict)
    source: dict = field(default_factory=dict)
    diagnostic: dict = field(default_factory=dict)

    def to_dict(self):return asdict(self)

def validate_item_count(item,count):
    if not isinstance(item,str) or not item:raise ValueError('item must be an item name')
    if type(count) is not int or not 1<=count<=64:raise ValueError('count must be 1..64 additional outputs')

def recipes_for(book,item):
    validate_item_count(item,1);item=book.resolve(item)
    return dict(item=item,recipes=[asdict(r) for r in book.recipes.get(item,())],
                cooking=copy.deepcopy(book.cooking.get(item,[])),source=copy.deepcopy(book.source))

def plan_craft(book,item,count,state):
    validate_item_count(item,count);item=book.resolve(item);stock=Counter()
    # Form inventories and craftpreview duplicate data or predict an output.
    # Armor/offhand are not free crafting materials either.
    for name,inventory in state.inventory.items():
        if name in ('main','craft','craftresult'):
            for stack in inventory.items:
                if stack.count:stock[book.resolve(stack.name)]+=stack.count
    nearby={n['name'] for n in state.raw.get('nodes',()) if n.get('name') and n.get('known',True)}
    table=TABLE in nearby;missing=Counter();steps=();reason='';diagnostic={};ready=False;complete=False
    try:
        steps=book.plan(item,count,stock,gather=False,nearby=nearby,has_table=table)
        ready=True;complete=True
    except PlanningError as exc:
        reason=exc.code;diagnostic=exc.detail
        try:
            # These collect steps describe a possible shopping list only.
            # No navigation, collection, crafting or extra scouting is issued.
            steps=book.plan(item,count,stock,gather=True,nearby=nearby,has_table=table)
            for step in steps:
                if step.kind=='collect':missing[step.item]+=step.count
            complete=True
        except PlanningError as proposed:
            diagnostic=dict(held_material_plan=diagnostic,procurement_plan=dict(reason=proposed.code,details=proposed.detail))
    steps=batch_plan(steps,book)
    requirements=dict(nearby_table_observed=table,table_placement_planned=any(s.kind=='workbench' for s in steps),
                      smelting_required=any(s.kind=='smelt' for s in steps),
                      execution_checks_pending=['reachability','tools','inventory_capacity','server_recipe'],
                      fuel_and_furnace_checked=False)
    return CraftPlan(item,count,ready,reason,dict(missing),complete,tuple(asdict(s) for s in steps),requirements,copy.deepcopy(book.source),diagnostic)
