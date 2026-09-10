#!/usr/bin/env python3
"""Course 0.9 survival and reference-agent audit on one persistent client."""
import argparse,json,sys,time,traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--session',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
sys.path.insert(0,str(a.sdk));sys.path.insert(0,str(ROOT/'tests/integration'))
from luanti_course import Agent,Game,SkillResult,SurvivalConfig,__version__
from luanti_course.combat import incoming_projectiles
from test_session import Session

a.output.mkdir(parents=True,exist_ok=False);session=Session(a.session);rows=[]
def wait(fn,timeout=12):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=fn()
        if value:return value
        time.sleep(.04)
    raise AssertionError('condition timeout')
def case(name,fn):
    start=time.monotonic()
    try:rows.append({'case':name,'status':'passed','detail':fn(),'elapsed':time.monotonic()-start})
    except Exception as exc:rows.append({'case':name,'status':'failed','error':str(exc),'traceback':traceback.format_exc(),'elapsed':time.monotonic()-start})
    (a.output/'results.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows[-1]),flush=True)

with session.connect(Game) as g:
    def burning_water():
        session.reset(g,dict(id='burning_water',nodes=[[0,100,0,'mcl_fire:fire']],
            fill=[dict(min=[3,100,-1],max=[5,100,1],name='mcl_core:water_source'),
                  dict(min=[3,99,-1],max=[5,99,1],name='mcl_core:stone')]))
        wait(lambda:g.observe().burning,6)
        with g.survival(SurvivalConfig(enemies='off',auto_eat=False,action_timeout=18,poll_interval=.08)) as guard:
            events=[]
            def finished():
                events.extend(guard.events())
                return any(e['event']=='reaction_finished' and e['decision']['action']=='extinguish_fire' for e in events)
            wait(finished,25);assert guard.wait_idle(3)
        state=g.observe();assert not state.burning and not state.raw['hazards'],events
        actions=[e['decision']['action'] for e in events if e['event']=='reaction_finished']
        assert actions[:2]==['escape_hazard','extinguish_fire'],actions
        return {'actions':actions,'position':state.position,'hp':state.hp}
    case('continuous_burning',burning_water)

    def shield_block():
        session.reset(g,dict(id='shield_block',inventory=['mcl_shields:shield'],
            entities=[dict(name='persistent_fixture:target',position=[0,99.51,4],damage=2)]))
        threat=wait(lambda:next(iter(g.observe().entities),None))
        result=g.block_with_shield(threat,duration=.8,timeout=8,damage_budget=10)
        assert result.ok,result.to_dict();assert result.details['outcome']=='shielded'
        assert not any(x.startswith('mcl_shield_hud.png') for x in g.observe().raw['hud_images'])
        return result.to_dict()
    case('shield_block',shield_block)

    def bow_shot():
        session.reset(g,dict(id='bow_shot',inventory=['mcl_bows:bow','mcl_bows:arrow 3'],
            entities=[dict(name='persistent_fixture:target',position=[0,99.51,8])]))
        target=wait(lambda:next(iter(g.observe().entities),None));before=g.observe().inventory['main'].count('mcl_bows:arrow')
        result=g.attack_ranged(target,shots=1,timeout=10)
        after=g.observe().inventory['main'].count('mcl_bows:arrow')
        assert result.ok and after==before-1,(result.to_dict(),before,after)
        return {'result':result.to_dict(),'ammo_before':before,'ammo_after':after}
    case('ranged_attack',bow_shot)

    def creeper_guard():
        session.reset(g,dict(id='creeper_guard',night=True,inventory=['mcl_shields:shield'],
            entities=[dict(name='mobs_mc:stalker',position=[0,99.51,5])]))
        threat=wait(lambda:next((e for e in g.observe().entities if e.explosive),None))
        result=g.survive_blast(threat,safe_distance=12,timeout=10)
        assert result.ok,result.to_dict();return result.to_dict()
    case('explosive_guard',creeper_guard)

    def projectile_observation():
        session.reset(g,dict(id='projectile',night=True,inventory=['mcl_shields:shield'],
            entities=[dict(name='mobs_mc:skeleton',position=[0,99.51,9])]))
        observed=[]
        def incoming():
            s=g.observe();observed.extend(e for e in s.entities if e.projectile)
            return incoming_projectiles(s)
        threats=wait(incoming,18);result=g.avoid_projectile(threats[0],timeout=8)
        assert result.ok,result.to_dict();return {'observed_names':sorted({e.name for e in observed}),'result':result.to_dict()}
    case('projectile_avoidance',projectile_observation)

    def reference_agent():
        session.reset(g,dict(id='reference_agent',nodes=[[5,100,0,'mcl_core:tree'],[5,101,0,'mcl_core:tree']]))
        choices=iter(({'name':'collect','args':{'resource':'mcl_core:tree','count':1,'timeout':45}},
                      {'name':'finish','args':{'summary':'one observed tree collected'}}))
        result=Agent(g,lambda request:next(choices),max_steps=3).run('collect one visible tree')
        assert result.ok and result.steps[0]['result']['status']=='success',result.to_dict()
        return result.to_dict()
    case('reference_agent_loop',reference_agent)

    session.park(g);g.release_control();final=g.observe()
    (a.output/'final.json').write_text(json.dumps({'sdk':__version__,'pid':session.meta['pid'],'control':final.control,
        'input_active':final.raw['input_active'],'focused':final.raw['focused'],'audio_enabled':final.raw['audio_enabled']},indent=2)+'\n')

raise SystemExit(any(r['status']!='passed' for r in rows))
