import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk/src"))
from luanti_course import InventoryList, Item, SkillResult

SPEC = importlib.util.spec_from_file_location(
    "student_first_project", ROOT / "examples/student_first_project.py"
)
student = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(student)


class FakeGame:
    def __init__(self, *, dead=False, control="observe", fail_collect=False,
                 collect_failure=None, breath=10, burning=False, hunger=20):
        self.dead = dead
        self.control = control
        self.fail_collect = fail_collect
        self.collect_failure = collect_failure
        self.breath = breath
        self.burning = burning
        self.hunger = hunger
        self.logs = 0
        self.picks = 0
        self.calls = []

    def _state(self):
        items = tuple(
            Item(name, count)
            for name, count in (
                ("mcl_core:tree", self.logs),
                ("mcl_tools:pick_wood", self.picks),
            )
            if count
        )
        return SimpleNamespace(
            dead=self.dead,
            hp=0 if self.dead else 20,
            control=self.control,
            position=(1.0, 2.0, 3.0),
            hunger=self.hunger,
            burning=self.burning,
            raw={"breath": self.breath, "in_liquid": False},
            inventory={"main": InventoryList(9, items)},
        )

    def observe(self, radius=0):
        self.calls.append(("observe", {"radius": radius}))
        return self._state()

    def respawn(self):
        self.calls.append(("respawn", {}))
        self.dead = False

    def wait_for(self, predicate, timeout=5.0, interval=.1):
        self.calls.append(("wait_for", {"timeout": timeout}))
        state = self._state()
        if not predicate(state):
            raise AssertionError("fixture did not meet predicate")
        return state

    def take_control(self):
        self.calls.append(("take_control", {}))
        self.control = "agent"

    def stop(self):
        self.calls.append(("stop", {}))

    def release_control(self):
        self.calls.append(("release_control", {}))
        self.control = "observe"

    def remember_location(self, name):
        self.calls.append(("remember_location", {"name": name}))
        return (1.0, 2.0, 3.0)

    def plan_craft(self, item, count=1, radius=0):
        self.calls.append(("plan_craft", {"item": item, "count": count, "radius": radius}))
        return SimpleNamespace(
            materials_ready=self.logs >= 3,
            reason="" if self.logs >= 3 else "missing_materials",
            missing={} if self.logs >= 3 else {"mcl_core:tree": 3 - self.logs},
            missing_complete=True,
            to_dict=lambda: {
                "materials_ready": self.logs >= 3,
                "missing": {} if self.logs >= 3 else {"mcl_core:tree": 3 - self.logs},
            },
        )

    def collect(self, resource, count=1, **kwargs):
        self.calls.append(("collect", {"resource": resource, "count": count, **kwargs}))
        if self.collect_failure:
            if self.collect_failure == "player_dead":
                self.dead = True
            return SkillResult("collect", "blocked", self.collect_failure)
        if self.fail_collect:
            return SkillResult("collect", "blocked", "resource_not_found")
        self.logs += count
        return SkillResult("collect", "success", details={"collected": count})

    def craft(self, item, count=1, **kwargs):
        self.calls.append(("craft", {"item": item, "count": count, **kwargs}))
        self.picks += count
        return SkillResult("craft", "success", details={"crafted": count})

    def go_to_location(self, name, **kwargs):
        self.calls.append(("go_to_location", {"name": name, **kwargs}))
        return SkillResult("go_to_location", "success")

    def recover_air(self, **kwargs):
        self.calls.append(("recover_air", kwargs))
        self.breath = 10
        return SkillResult("recover_air", "success")

    def extinguish_fire(self, **kwargs):
        self.calls.append(("extinguish_fire", kwargs))
        self.burning = False
        return SkillResult("extinguish_fire", "success")

    def eat_best_food(self, **kwargs):
        self.calls.append(("eat_best_food", kwargs))
        self.hunger = 20
        return SkillResult("eat_best_food", "success")


class StudentStrategyTests(unittest.TestCase):
    def execute(self, game, **kwargs):
        events = []
        report = student.run_strategy(game, emit=events.append, **kwargs)
        return report, events

    def test_student_chooses_bounded_steps_without_teacher_flags(self):
        game = FakeGame()
        report, events = self.execute(game)
        actions = [name for name, _ in game.calls if name in ("collect", "craft", "go_to_location")]
        self.assertEqual(actions, ["collect", "craft", "go_to_location"])
        self.assertEqual(report["status"], "complete")
        collect = next(args for name, args in game.calls if name == "collect")
        craft = next(args for name, args in game.calls if name == "craft")
        self.assertEqual(collect["resource"], "mcl_core:tree")
        self.assertNotIn("allow_tool_crafting", collect)
        self.assertIs(craft["gather"], False)
        self.assertIs(craft["allow_tool_crafting"], False)
        self.assertTrue(any(e["event"] == "decision" for e in events))

    def test_death_is_observed_then_explicitly_respawned_once(self):
        game = FakeGame(dead=True)
        report, events = self.execute(game, max_respawns=1)
        self.assertEqual([name for name, _ in game.calls].count("respawn"), 1)
        self.assertEqual(report["respawns"], 1)
        self.assertEqual(report["status"], "complete")
        self.assertTrue(any(e.get("action") == "respawn" for e in events))

    def test_blocked_skill_returns_to_student_instead_of_replaying(self):
        game = FakeGame(fail_collect=True)
        report, _ = self.execute(game)
        self.assertEqual(report["status"], "needs_replan")
        self.assertEqual(report["reason"], "resource_not_found")
        self.assertEqual([name for name, _ in game.calls].count("collect"), 1)
        self.assertNotIn("craft", [name for name, _ in game.calls])

    def test_manual_takeover_stops_without_reacquiring(self):
        game = FakeGame(control="manual")
        report, _ = self.execute(game)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["reason"], "manual_takeover")
        self.assertNotIn("take_control", [name for name, _ in game.calls])

    def test_death_during_task_respawns_but_does_not_replay(self):
        game = FakeGame(collect_failure="player_dead")
        report, _ = self.execute(game)
        self.assertEqual(report["status"], "needs_replan")
        self.assertEqual(report["reason"], "death_changed_task_state")
        self.assertEqual([name for name, _ in game.calls].count("respawn"), 1)
        self.assertEqual([name for name, _ in game.calls].count("collect"), 1)

    def test_emergency_decisions_precede_the_course_task(self):
        for field, action in (
            ({"breath": 3}, "recover_air"),
            ({"burning": True}, "extinguish_fire"),
            ({"hunger": 4}, "eat_best_food"),
        ):
            with self.subTest(action=action):
                game = FakeGame(**field)
                report, _ = self.execute(game)
                high_level = [name for name, _ in game.calls if name in (
                    "recover_air", "extinguish_fire", "eat_best_food",
                    "collect", "craft", "go_to_location",
                )]
                self.assertEqual(high_level[0], action)
                self.assertEqual(report["status"], "complete")


if __name__ == "__main__":
    unittest.main()
