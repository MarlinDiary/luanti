import json,sys,unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'sdk/src'))
sys.path.insert(0,str(ROOT/'tests/unit'))
from luanti_course import SkillResult
from luanti_course.agent import Agent, SkillCall, PlannerError, observation_for_planner
from test_survival import state,entity


class AgentTests(unittest.TestCase):
    def game(self):
        calls=[]
        g=NS(observe=lambda radius=0:state(entities=(entity(pointable=True),)),
             navigate_to=lambda position,**kw:calls.append(('navigate_to',position)) or SkillResult('navigate_to','success'),
             collect=lambda resource,count=1,**kw:calls.append(('collect',resource,count)) or SkillResult('collect','blocked','resource_not_observed'))
        return g,calls

    def test_observe_replan_loop_and_finish(self):
        game,calls=self.game();prompts=[]
        choices=iter([{'name':'navigate_to','args':{'position':[1,2,3]}},
                      {'name':'finish','args':{'summary':'done'}}])
        def planner(request):prompts.append(request);return next(choices)
        result=Agent(game,planner,max_steps=3).run('reach a visible point')
        self.assertEqual(result.status,'complete');self.assertEqual(calls,[('navigate_to',[1,2,3])])
        self.assertEqual(len(prompts),2);self.assertEqual(prompts[1]['last_result']['status'],'success')

    def test_planner_cannot_call_private_or_unlisted_method(self):
        game,_=self.game()
        with self.assertRaises(PlannerError):Agent(game,lambda r:{'name':'_submit','args':{}},max_steps=1).run('x')

    def test_entity_reference_resolves_only_current_observation(self):
        game,_=self.game()
        call=SkillCall.from_value({'name':'attack_entity','args':{'target':[2,10]}})
        target=call.resolve_entities(game.observe())['target']
        self.assertEqual(target.ref,(2,10))

    def test_summary_is_bounded_and_json_serializable(self):
        value=observation_for_planner(state())
        self.assertLess(len(json.dumps(value)),20000)

if __name__=='__main__':unittest.main()
