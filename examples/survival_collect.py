"""Reference student loop: collect, handle survival, observe, explicitly replan.

This is an example policy, not automatic SDK replay. It never respawns, grants
items, changes server rules, or silently continues after a failed reaction.
"""
import argparse,json,time
from luanti_course import Game,SurvivalConfig,ExplorationMemory

def reaction_failed(event):
    if event['event'] in ('reaction_error','action_not_yielding','control_lost'):
        return True
    if event['event']!='reaction_finished':return False
    result=event['result']
    if result['status']=='success':return False
    # A documented priority handoff is not a failed survival action. The
    # supervisor stays busy across that handoff; any failed successor still
    # appears separately and stops this example. Manual cancellation does not
    # carry this reason and intervention, and remains a stopping condition.
    intervention=result.get('details',{}).get('intervention') or {}
    return not (result['status']=='cancelled' and result['reason']=='survival_interrupted'
                and intervention.get('action') in ('recover_air','escape_hazard','flee_from','defend_self','eat_best_food'))

def collect_with_survival(game,item,count=3,*,seconds=90,enemies='avoid',max_interruptions=3):
    if type(count) is not int or count<1:raise ValueError('count must be positive')
    if not 0<seconds<=600:raise ValueError('seconds must be 0..600')
    if type(max_interruptions) is not int or not 0<=max_interruptions<=20:raise ValueError('invalid interruption budget')
    if game.exploration_memory is None:game.exploration_memory=ExplorationMemory()
    item=game.recipe_book.resolve(item);baseline=game.observe().inventory['main'].count(item)
    report={'item':item,'requested_additional':count,'baseline':baseline,'steps':[]};end=time.monotonic()+seconds;interruptions=0
    with game.survival(SurvivalConfig(enemies=enemies)) as guard:
        while time.monotonic()<end:
            s=game.observe()
            if s.dead or s.control!='agent' or guard.paused:report['status']='stopped';break
            # Stock may have reached the target while a reaction interrupted
            # collect. Finish that handoff and inspect its outcome first.
            if guard.busy:
                if not guard.wait_idle(min(30,max(.1,end-time.monotonic()))):
                    game.stop();report['status']='survival_timeout';break
            events=guard.events();report['steps'].extend({'survival_event':e} for e in events)
            if any(reaction_failed(e) for e in events):
                game.stop();report['status']='needs_replan';break
            fresh=game.observe()
            if fresh.dead or fresh.control!='agent' or guard.paused:report['status']='stopped';break
            if guard.busy:continue  # A new reaction began while observing.
            remaining=count-max(0,fresh.inventory['main'].count(item)-baseline)
            if remaining<=0:report['status']='complete';break
            result=game.collect(item,remaining,timeout=max(.1,min(40,end-time.monotonic())))
            report['steps'].append({'remaining_requested':remaining,'result':result.to_dict()})
            if result.ok:continue
            if result.reason!='survival_interrupted':report['status']='needs_replan';break
            interruptions+=1
            if interruptions>max_interruptions:report['status']='interruption_budget';break
            # The next iteration consumes reaction results, re-observes stock,
            # and requests only the remaining amount. No unconditional replay.
        else:report['status']='deadline'
    # close() joins the worker; include late results/errors emitted on exit.
    tail=guard.events();report['steps'].extend({'survival_event':e} for e in tail)
    if report.get('status')=='complete' and any(reaction_failed(e) for e in tail):
        report['status']='needs_replan'
    game.stop();final=game.observe()
    report['gained']=max(0,final.inventory['main'].count(item)-baseline)
    if report.get('status')=='complete':
        if final.dead or final.control!='agent' or guard.paused:report['status']='stopped'
        elif report['gained']<count:report['status']='needs_replan'
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--item',default='mcl_core:tree');p.add_argument('--count',type=int,default=3)
    p.add_argument('--seconds',type=float,default=90);p.add_argument('--enemies',choices=('avoid','defend','off'),default='avoid');a=p.parse_args()
    with Game.connect() as game,game.control():
        print(json.dumps(collect_with_survival(game,a.item,a.count,seconds=a.seconds,enemies=a.enemies),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
