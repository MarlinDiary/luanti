"""Versioned recipe data and a bounded dependency planner (no LLM required)."""
from collections import Counter, defaultdict
from dataclasses import dataclass
import copy
from functools import lru_cache
import json
from pathlib import Path

TABLE = 'mcl_crafting_table:crafting_table'
FRIENDLY = {'wooden_pickaxe':'mcl_tools:pick_wood', '木镐':'mcl_tools:pick_wood',
            'crafting_table':TABLE, '工作台':TABLE, 'stick':'mcl_core:stick', '木棍':'mcl_core:stick'}

class PlanningError(ValueError):
    def __init__(self, code, detail):
        self.code,self.detail = code,detail
        super().__init__(str(detail))

@dataclass(frozen=True)
class Recipe:
    output: str
    count: int
    width: int
    items: tuple
    replacements: tuple = ()

    @property
    def grid(self):
        if self.width == 0:
            return 2 if len(self.items) <= 4 else 3
        return 3 if self.width > 2 or (len(self.items)+self.width-1)//self.width > 2 else 2

@dataclass(frozen=True)
class PlanStep:
    kind: str
    item: str
    count: int = 1
    recipe: Recipe = None
    ingredients: tuple = ()

class RecipeBook:
    def __init__(self, data):
        self.source = data.get('source', {})
        self.items = data['items']
        self.aliases = data.get('aliases') or {}
        self.hand = data.get('hand_diggroups') or {}
        self.cooking = defaultdict(list)
        self.fuels = data.get('fuels',{})
        for r in data.get('cooking',()):
            if r.get('input') and r.get('output') and r.get('time',0)>0 and r.get('count',0)>0:self.cooking[r['output']].append(r)
        self.recipes = defaultdict(list)
        self.drops = defaultdict(list)
        self._groups = {}
        for raw in data['recipes']:
            r = Recipe(raw['output'],raw['count'],raw['width'],tuple(raw['items']),tuple(tuple(x) for x in raw.get('replacements') or ()))
            if not r.output or r.count < 1 or not 0 <= r.width <= 3 or not 1 <= len(r.items) <= 9:
                continue
            self.recipes[r.output].append(r)
        for name, item in self.items.items():
            drop = item.get('drop','')
            if drop:
                self.drops[drop.split()[0]].append(name)

    @classmethod
    def voxelibre(cls):
        return cls(json.loads((Path(__file__).parent/'data/voxelibre.json').read_text()))

    def resolve(self, name):
        name = FRIENDLY.get(name,name)
        seen = set()
        while name in self.aliases and name not in seen:
            seen.add(name)
            name = self.aliases[name]
        return name

    def matches(self, name, token):
        name,token = self.resolve(name),self.resolve(token)
        if token.startswith('group:'):
            groups = self.items.get(name,{}).get('groups') or {}
            return all(groups.get(g,0)>0 for g in token[6:].split(','))
        return name == token

    def candidates(self, token):
        token = self.resolve(token)
        if not token.startswith('group:'):
            return [token]
        if token not in self._groups:
            self._groups[token] = tuple(sorted(n for n in self.items if self.matches(n,token)))
        return self._groups[token]

    def resources(self, token):
        return set(n for item in self.candidates(token) for n in self.drops.get(item,())
                   if self.items.get(n,{}).get('type')=='node')

    def procurement_nodes(self, item):
        """All bounded recipe-alternative resource nodes, for pre-planning scouting."""
        nodes=set();seen=set()
        def visit(token,depth):
            if depth>10:return
            for name in self.candidates(token):
                if name in seen or len(seen)>=512:continue
                seen.add(name)
                nodes.update(self.resources(name))
                for cooked in self.cooking.get(name,()):visit(cooked['input'],depth+1)
                for recipe in self.recipes.get(name,())[:24]:
                    if recipe.grid==3 and name!=TABLE:visit(TABLE,depth+1)
                    for ingredient in set(recipe.items)-{''}:visit(ingredient,depth+1)
        visit(self.resolve(item),0)
        return nodes

    def harvestable(self, node, tool, live_groups=None):
        groups = live_groups or self.items.get(node,{}).get('groups') or {}
        if groups.get('dig_immediate',0)>=2 or groups.get('dig_immediate_piston',0)>=1:
            return True
        rules = self.items.get(tool,{}).get('diggroups') or {}
        return any(groups.get(g,0)>0 and groups[g]<=v.get('level',0)
                   for source in (rules,self.hand) for g,v in source.items())

    def plan(self, item, count, inventory, *, gather=True, nearby=(), has_table=False, max_steps=128):
        """Plan count additional outputs; consume/reserve materials in a copy.

        Alternative/group choice prefers held materials and observed resources.
        Cycles, missing non-harvestable inputs and excessive plans fail explicitly.
        """
        item = self.resolve(item)
        if item not in self.recipes and item not in self.cooking:
            raise PlanningError('recipe_unavailable', {'item':item,'source':self.source})
        seen_nodes = set(nearby)
        budget = [0]
        @dataclass
        class State:
            stock: Counter
            steps: list
            table: bool
        initial = State(Counter(inventory),[],has_table)

        @lru_cache(maxsize=10000)
        def affinity(name, visiting=frozenset(), depth=0):
            if name in visiting or depth>5:
                return 1000
            if initial.stock[name]>0:
                return 0
            if self.resources(name)&seen_nodes:
                return 1
            best = 20 if self.resources(name) else 1000
            for r in self.recipes.get(name,())[:16]:
                cost = 2
                for t in set(r.items)-{''}:
                    cs = self.candidates(t)
                    cost += min((affinity(c,visiting|{name},depth+1) for c in cs[:12]),default=1000)
                best = min(best,cost)
            return best

        def ensure(token, needed, state, visiting):
            budget[0]+=1
            if budget[0]>2500 or len(state.steps)>max_steps:
                raise PlanningError('plan_limit',{'item':token})
            candidates = self.candidates(token)
            candidates = sorted(candidates,key=lambda n:(-min(needed,state.stock[n]),affinity(n),n))
            errors=[]
            for name in candidates[:12]:
                trial=copy.deepcopy(state)
                try:
                    exact(name,needed,trial,visiting)
                    state.stock,state.steps,state.table=trial.stock,trial.steps,trial.table
                    return name
                except PlanningError as exc:
                    errors.append({'candidate':name,'code':exc.code,'detail':exc.detail})
            raise PlanningError('missing_materials',{'ingredient':token,'count':needed,'candidates':errors[:4]})

        def exact(name, needed, state, visiting):
            if state.stock[name]>=needed:
                return
            if name in visiting or len(visiting)>12:
                raise PlanningError('recipe_cycle',{'item':name})
            amount=needed-state.stock[name]
            if gather and name!=item and self.resources(name)&seen_nodes:
                state.steps.append(PlanStep('collect',name,amount));state.stock[name]+=amount;return
            options=list(self.recipes.get(name,()))
            # Prefer short recipes and held ingredients; avoid unpack/repack cycles.
            def score(r):
                tokens=[t for t in r.items if t]
                held=sum(any(state.stock[x]>0 for x in self.candidates(t)) for t in tokens)
                return (-held,sum(min((affinity(x) for x in self.candidates(t)),default=1000) for t in set(tokens)),len(tokens),r.grid)
            options.sort(key=score)
            failure=None
            direct_grid=any(all(sum(state.stock[n] for n in self.candidates(token))>=qty for token,qty in Counter(t for t in r.items if t).items()) for r in options)
            if not direct_grid:
                for cooked in self.cooking.get(name,()):
                    trial=copy.deepcopy(state)
                    try:
                        batches=(amount+cooked['count']-1)//cooked['count']
                        selected=ensure(cooked['input'],batches,trial,visiting|{name})
                        trial.stock[selected]-=batches;trial.stock[name]+=batches*cooked['count']
                        trial.steps.append(PlanStep('smelt',name,batches*cooked['count']))
                        state.stock,state.steps,state.table=trial.stock,trial.steps,trial.table
                        return
                    except PlanningError as exc:failure=exc
            for r in options[:16]:
                trial=copy.deepcopy(state)
                try:
                    if r.grid==3 and not trial.table:
                        exact(TABLE,1,trial,visiting|{name})
                        trial.stock[TABLE]-=1
                        trial.steps.append(PlanStep('workbench',TABLE))
                        trial.table=True
                    crafts=(amount+r.count-1)//r.count
                    for _ in range(crafts):
                        concrete=[]
                        for token in r.items:
                            if not token:
                                concrete.append('');continue
                            selected=ensure(token,1,trial,visiting|{name})
                            trial.stock[selected]-=1
                            concrete.append(selected)
                        trial.stock[name]+=r.count
                        trial.steps.append(PlanStep('craft',name,r.count,r,tuple(concrete)))
                        # Replacement items are returned by the real grid. Do not
                        # assume callback-dependent returns as planning credit.
                        if len(trial.steps)>max_steps:
                            raise PlanningError('plan_limit',{'item':name})
                    state.stock,state.steps,state.table=trial.stock,trial.steps,trial.table
                    return
                except PlanningError as exc:
                    failure=exc
            for cooked in self.cooking.get(name,()):
                trial=copy.deepcopy(state)
                try:
                    batches=(amount+cooked['count']-1)//cooked['count']
                    selected=ensure(cooked['input'],batches,trial,visiting|{name})
                    trial.stock[selected]-=batches;trial.stock[name]+=batches*cooked['count']
                    trial.steps.append(PlanStep('smelt',name,batches*cooked['count']))
                    state.stock,state.steps,state.table=trial.stock,trial.steps,trial.table
                    return
                except PlanningError as exc:failure=exc
            if gather and name!=item and self.resources(name):
                state.steps.append(PlanStep('collect',name,amount))
                state.stock[name]+=amount
                return
            if failure:
                raise failure
            raise PlanningError('missing_materials',{'item':name,'count':amount,'gather':gather})

        exact(item,initial.stock[item]+count,initial,frozenset())
        return tuple(initial.steps)


def batch_plan(steps, book):
    """Coalesce adjacent equal actions without reordering dependencies."""
    out=[]
    for step in steps:
        if out:
            prev=out[-1]
            same=step.kind==prev.kind and step.item==prev.item
            if same and step.kind in ('collect','smelt') and prev.count+step.count<=(64 if step.kind=='smelt' else 256):
                out[-1]=PlanStep(step.kind,step.item,prev.count+step.count);continue
            if same and step.kind=='craft' and step.recipe==prev.recipe and step.ingredients==prev.ingredients and not step.recipe.replacements:
                crafts=(prev.count+step.count)//step.recipe.count
                limit=min([64,book.items.get(step.item,{}).get('stack_max',1)//step.recipe.count]+[book.items.get(i,{}).get('stack_max',1) for i in step.ingredients if i])
                if crafts<=limit:
                    out[-1]=PlanStep('craft',step.item,prev.count+step.count,step.recipe,step.ingredients);continue
        out.append(step)
    return tuple(out)
