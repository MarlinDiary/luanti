"""Completion must include any already-started survival handoff, not just stock."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import sys, unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'sdk/src'))
from luanti_course import RecipeBook
from luanti_course.skills import SkillResult
from test_survival import state
spec=importlib.util.spec_from_file_location('completion_example',ROOT/'examples/survival_collect.py')
example=importlib.util.module_from_spec(spec);spec.loader.exec_module(example)

def finished(status='success'):
    return dict(event='reaction_finished',decision={'action':'flee_from'},result={'status':status,'reason':'escape_route_unavailable' if status!='success' else '', 'details':{}})

class CompletionTests(unittest.TestCase):
    def execute(self, *, reaction='success', busy=True, lost_stock=False, close_error=False, dead_after=False):
        held=[0];events=[];calls=[];waits=[];stopped=[];dead=[False]
        guard=NS(busy=False,paused=False)
        def drain():
            batch=events[:];events.clear();return batch
        guard.events=drain
        def wait(timeout):
            waits.append(timeout);guard.busy=False
            if reaction=='timeout':return False
            events.append(finished(reaction))
            if lost_stock:held[0]=0
            if dead_after:dead[0]=True
            return True
        guard.wait_idle=wait
        class Scope:
            def __enter__(self):return guard
            def __exit__(self,*a):
                if close_error:events.append(dict(event='reaction_error',message='failed at shutdown'))
        def observe(*a):return state(dead=dead[0],inventory={'main':{'width':9,'items':[{'name':'mcl_core:tree','count':held[0]}]}})
        def collect(item,count,**kw):
            calls.append(count);held[0]+=count
            if len(calls)==1:
                guard.busy=busy
                if not busy:events.append(finished(reaction))
                return SkillResult('collect','cancelled','survival_interrupted',{'intervention':{'action':'flee_from'}})
            return SkillResult('collect','success')
        game=NS(recipe_book=RecipeBook.voxelibre(),exploration_memory=None,observe=observe,survival=lambda c:Scope(),collect=collect,stop=lambda:stopped.append(True))
        result=example.collect_with_survival(game,'mcl_core:tree',2,seconds=2)
        self.assertTrue(stopped)
        return result,calls,waits
    def test_target_reached_waits_for_successful_reaction(self):
        r,c,w=self.execute();self.assertEqual(r['status'],'complete');self.assertEqual(c,[2]);self.assertEqual(len(w),1)
    def test_target_reached_with_failed_reaction_is_not_complete(self):
        r,c,w=self.execute(reaction='blocked');self.assertEqual(r['status'],'needs_replan');self.assertEqual(len(w),1)
    def test_target_reached_with_pending_timeout_is_not_complete(self):
        r,c,w=self.execute(reaction='timeout');self.assertEqual(r['status'],'survival_timeout');self.assertEqual(len(w),1)
    def test_finished_reaction_failure_is_checked_before_completion(self):
        r,c,w=self.execute(reaction='blocked',busy=False);self.assertEqual(r['status'],'needs_replan');self.assertFalse(w)
    def test_stock_reobserved_after_reaction(self):
        r,c,w=self.execute(lost_stock=True);self.assertEqual(r['status'],'complete');self.assertEqual(c,[2,2])
    def test_death_during_reaction_stops_task(self):
        r,c,w=self.execute(dead_after=True);self.assertEqual(r['status'],'stopped');self.assertEqual(c,[2])
    def test_shutdown_reaction_error_is_not_silently_ignored(self):
        r,c,w=self.execute(busy=False,close_error=True);self.assertEqual(r['status'],'needs_replan')

if __name__=='__main__':unittest.main()
