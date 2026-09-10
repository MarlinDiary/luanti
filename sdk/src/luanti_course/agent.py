"""Small provider-neutral reference loop; students still own the planner.

The SDK exposes deterministic skills.  This module demonstrates the same
observe -> choose one typed skill -> execute -> observe/replan boundary used by
Minecraft agents, without embedding a diamond route or a model dependency.
"""
from dataclasses import dataclass,asdict
import json,shlex,subprocess

from .skills import SkillResult


class PlannerError(ValueError):pass


class CommandPlanner:
    """Adapter for any model CLI that reads one JSON request from stdin."""
    def __init__(self,command,*,timeout=90):
        self.command=tuple(shlex.split(command) if isinstance(command,str) else command)
        if not self.command:raise ValueError('planner command is empty')
        if not 1<=timeout<=600:raise ValueError('planner timeout must be 1..600 seconds')
        self.timeout=timeout
    def __call__(self,request):
        try:r=subprocess.run(self.command,input=json.dumps(request)+'\n',text=True,capture_output=True,timeout=self.timeout)
        except (OSError,subprocess.TimeoutExpired) as exc:raise PlannerError('planner command failed: '+str(exc)) from exc
        if r.returncode:raise PlannerError('planner command exited '+str(r.returncode)+': '+r.stderr[-1000:])
        return r.stdout


ALLOWED_SKILLS=frozenset({
    'navigate_to','navigate_route','collect','craft','smelt','place_block',
    'organize_inventory','equip','equip_best_gear','eat','eat_best_food',
    'attack_entity','attack_ranged','flee_from','defend_self','block_with_shield',
    'avoid_projectile','survive_blast',
    'dig_down','dig_tunnel','go_to_surface','bridge_to','build_ladder',
    'deposit','withdraw','restock','extinguish_fire',
})
ENTITY_ARGUMENT_SKILLS=frozenset(('attack_entity','attack_ranged','flee_from','block_with_shield','avoid_projectile','survive_blast'))


@dataclass(frozen=True)
class SkillCall:
    name:str
    args:dict

    @classmethod
    def from_value(cls,value):
        if isinstance(value,str):
            try:value=json.loads(value)
            except json.JSONDecodeError as exc:raise PlannerError('planner response is not JSON') from exc
        if not isinstance(value,dict) or set(value)-{'name','args'} or not isinstance(value.get('name'),str):
            raise PlannerError('planner must return {"name": ..., "args": {...}}')
        args=value.get('args',{})
        if not isinstance(args,dict):raise PlannerError('skill args must be an object')
        if value['name']!='finish' and value['name'] not in ALLOWED_SKILLS:raise PlannerError('skill is not in the reference allowlist')
        if value['name']=='finish' and set(args)-{'summary'}:raise PlannerError('finish accepts only summary')
        return cls(value['name'],args)

    def resolve_entities(self,state):
        args=dict(self.args)
        if self.name not in ENTITY_ARGUMENT_SKILLS or 'target' not in args:return args
        ref=args['target']
        if not isinstance(ref,(list,tuple)) or len(ref)!=2 or any(type(x) is not int for x in ref):
            raise PlannerError('target must be a current [id, instance] pair')
        target=next((e for e in state.entities if e.ref==tuple(ref)),None)
        if target is None:raise PlannerError('target is stale or not currently observed')
        args['target']=target;return args


def observation_for_planner(state):
    """Bounded, JSON-safe public observation rather than the entire raw frame."""
    inventory=[]
    for name,listing in sorted(state.inventory.items()):
        inventory.append({'list':name,'items':[{'slot':n,'name':i.name,'count':i.count,'wear':i.wear}
            for n,i in enumerate(listing.items) if i.count][:128]})
    return {
        'position':list(state.position),'hp':state.hp,'dead':state.dead,
        'breath':state.raw.get('breath'),'hunger':state.hunger,'burning':state.burning,
        'in_liquid':state.raw.get('in_liquid'),'inventory':inventory,
        'entities':[{'ref':list(e.ref),'name':e.name,'position':list(e.position),
                     'velocity':list(e.velocity),'hostile':e.hostile,'projectile':e.projectile,
                     'explosive':e.explosive,'attackable':e.pointable and not e.is_player}
                    for e in state.entities[:128]],
    }


@dataclass(frozen=True)
class AgentResult:
    status:str
    summary:str
    steps:tuple
    @property
    def ok(self):return self.status=='complete'
    def to_dict(self):return asdict(self)


class Agent:
    """Reference executor around any callable planner(request)->typed call."""
    def __init__(self,game,planner,*,max_steps=24,observation_radius=0):
        if not callable(planner):raise ValueError('planner must be callable')
        if type(max_steps) is not int or not 1<=max_steps<=128:raise ValueError('max_steps must be 1..128')
        if type(observation_radius) is not int or not 0<=observation_radius<=6:raise ValueError('observation_radius must be 0..6')
        self.game,self.planner,self.max_steps,self.radius=game,planner,max_steps,observation_radius

    def run(self,objective):
        if not isinstance(objective,str) or not objective.strip():raise ValueError('objective must be text')
        if len(objective)>16000:raise ValueError('objective exceeds 16000 characters')
        rows=[];last=None
        for index in range(self.max_steps):
            state=self.game.observe(self.radius)
            request={'objective':objective,'step':index+1,'max_steps':self.max_steps,
                     'observation':observation_for_planner(state),
                     'last_result':last.to_dict() if isinstance(last,SkillResult) else last,
                     'allowed_skills':sorted(ALLOWED_SKILLS),'response_schema':{'name':'skill or finish','args':{}}}
            call=SkillCall.from_value(self.planner(request))
            if call.name=='finish':
                summary=call.args.get('summary','')
                if not isinstance(summary,str):raise PlannerError('finish summary must be text')
                return AgentResult('complete',summary,tuple(rows))
            args=call.resolve_entities(state)
            method=getattr(self.game,call.name,None)
            if method is None or not callable(method):raise PlannerError('installed SDK does not implement requested skill')
            result=method(**args)
            if not isinstance(result,SkillResult):raise PlannerError('skill did not return SkillResult')
            row={'call':asdict(call),'result':result.to_dict()};rows.append(row);last=result
        return AgentResult('step_limit','planner did not finish within max_steps',tuple(rows))
