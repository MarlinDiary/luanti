import sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'sdk/src'))
from luanti_course import SurvivalConfig
from luanti_course.supervisor import Survival
from luanti_course.skills import Context,Failure
import test_survival as helpers
from test_survival import state

class SurvivalEntryTests(unittest.TestCase):
    def guard(self,s,config=None):
        g=helpers.SupervisorTests().game();g.observe=lambda r=0:s
        return g,Survival(g,config)
    def test_known_air_hazard_is_pending_before_first_worker_poll(self):
        g,guard=self.guard(state(breath=3))
        with patch.object(guard,'_loop',lambda:None):
            with guard:self.assertEqual((guard.pending or {}).get('action'),'recover_air');self.assertTrue(guard.busy)
    def test_known_fire_is_pending_before_first_worker_poll(self):
        g,guard=self.guard(state(hazards=[{'name':'fire'}]))
        with patch.object(guard,'_loop',lambda:None):
            with guard:self.assertEqual((guard.pending or {}).get('action'),'escape_hazard')
    def test_disabled_preservation_does_not_seed_reaction(self):
        g,guard=self.guard(state(breath=3),SurvivalConfig(self_preservation=False))
        with patch.object(guard,'_loop',lambda:None):
            with guard:self.assertIsNone(guard.pending)
    def test_fresh_air_hazard_yields_before_generic_skill_failure(self):
        g,guard=self.guard(state(breath=3));guard._epoch=1;g._survival=guard
        c=Context(g,1,6,g.recipe_book)
        with self.assertRaises(Failure) as exc:c.read()
        self.assertEqual(exc.exception.reason,'survival_interrupted')
        self.assertEqual(exc.exception.details['intervention']['action'],'recover_air')
    def test_fresh_fire_observation_requests_worker_without_acting(self):
        g,guard=self.guard(state());guard._epoch=1
        with patch.object(g,'_submit') as send:
            guard.on_observation(state(hazards=[{'name':'fire'}]))
            self.assertEqual((guard.pending or {}).get('action'),'escape_hazard');send.assert_not_called()
    def test_paused_guard_does_not_request_emergency(self):
        g,guard=self.guard(state());guard._epoch=1;guard._paused=True
        guard.on_observation(state(breath=3));self.assertIsNone(guard.pending)
    def test_other_control_epoch_never_requests_emergency(self):
        g,guard=self.guard(state());guard._epoch=1
        guard.on_observation(state(breath=3,control_epoch=2));self.assertIsNone(guard.pending)
    def test_disabled_preservation_keeps_low_breath_result(self):
        g,guard=self.guard(state(breath=3),SurvivalConfig(self_preservation=False));guard._epoch=1;g._survival=guard
        with self.assertRaises(Failure) as exc:Context(g,1,6,g.recipe_book).read()
        self.assertEqual(exc.exception.reason,'low_breath')

if __name__=='__main__':unittest.main()
