import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk/src"))

from luanti_course import InventoryList, Item, RecipeBook, SkillResult

SPEC = importlib.util.spec_from_file_location(
    "student_autonomous_miner", ROOT / "examples/student_autonomous_miner.py"
)
miner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = miner
SPEC.loader.exec_module(miner)


BOOK = RecipeBook.voxelibre()


def snapshot(*items, y=20.0, hp=20, dead=False, control="agent", breath=10,
             hunger=20, burning=False, hazards=(), revision=1, slots=36):
    stacks = [Item(name, count, wear) for name, count, wear in items]
    stacks.extend(Item("", 0) for _ in range(max(0, slots - len(stacks))))
    return SimpleNamespace(
        position=(0.0, y, 0.0),
        hp=hp,
        dead=dead,
        control=control,
        hunger=hunger,
        burning=burning,
        inventory_revision=revision,
        inventory={"main": InventoryList(9, tuple(stacks))},
        raw={"breath": breath, "hazards": list(hazards)},
    )


class PolicyTests(unittest.TestCase):
    def action(self, state, policy=None):
        policy = policy or miner.MinerPolicy()
        return policy, policy.choose(state, BOOK)

    def test_empty_inventory_starts_with_explicit_wood_collection(self):
        _, action = self.action(snapshot())
        self.assertEqual((action.kind, action.item, action.count),
                         ("collect", miner.LOG, 8))

    def test_tool_progression_is_wood_then_stone_then_iron(self):
        cases = (
            (snapshot(("mcl_core:tree", 8, 0)),
             ("craft", miner.WOOD_PICK)),
            (snapshot(("mcl_core:tree", 8, 0), (miner.WOOD_PICK, 1, 0)),
             ("collect", miner.COBBLE)),
            (snapshot(("mcl_core:tree", 8, 0), (miner.STONE_PICK, 1, 0),
                      (miner.COBBLE, 16, 0), (miner.COAL, 4, 0),
                      (miner.RAW_IRON, 3, 0)),
             ("craft", miner.IRON_PICK)),
        )
        for state, expected in cases:
            with self.subTest(expected=expected):
                _, action = self.action(state)
                self.assertEqual((action.kind, action.item), expected)

    def test_nearly_broken_tool_is_replaced_before_mining(self):
        state = snapshot(
            ("mcl_core:tree", 8, 0),
            (miner.STONE_PICK, 1, 0),
            (miner.IRON_PICK, 1, 60_000),
            (miner.COBBLE, 16, 0),
            (miner.COAL, 4, 0),
            (miner.RAW_IRON, 3, 0),
        )
        _, action = self.action(state)
        self.assertEqual((action.kind, action.item), ("craft", miner.IRON_PICK))

    def test_iron_pick_seeks_diamond_and_diamonds_upgrade_the_pick(self):
        base = (
            ("mcl_core:tree", 8, 0),
            (miner.IRON_PICK, 1, 0),
            (miner.COBBLE, 16, 0),
            (miner.COAL, 4, 0),
        )
        _, action = self.action(snapshot(*base, y=-48))
        self.assertEqual((action.kind, action.item), ("collect", miner.DIAMOND))
        _, action = self.action(snapshot(*base, (miner.DIAMOND, 3, 0), y=-48))
        self.assertEqual((action.kind, action.item), ("craft", miner.DIAMOND_PICK))

    def test_failed_search_descends_then_rotates_branch_tunnels(self):
        policy = miner.MinerPolicy()
        state = snapshot(
            ("mcl_core:tree", 8, 0), (miner.IRON_PICK, 1, 0),
            (miner.COBBLE, 16, 0), (miner.COAL, 4, 0), y=20,
        )
        search = policy.choose(state, BOOK)
        policy.on_result(search, SkillResult("collect", "blocked", "resource_not_found"))
        descent = policy.choose(state, BOOK)
        self.assertEqual((descent.kind, descent.count), ("dig_down", 64))

        deep = snapshot(
            ("mcl_core:tree", 8, 0), (miner.IRON_PICK, 1, 0),
            (miner.COBBLE, 16, 0), (miner.COAL, 4, 0), y=-48,
        )
        tunnel = policy.choose(deep, BOOK)
        self.assertEqual((tunnel.kind, tunnel.direction),
                         ("dig_tunnel", (1, 0, 0)))
        policy.on_result(tunnel, SkillResult("dig_tunnel", "success"))
        retry = policy.choose(deep, BOOK)
        self.assertEqual((retry.kind, retry.item), ("collect", miner.DIAMOND))
        policy.on_result(retry, SkillResult("collect", "blocked", "resource_not_found"))
        connector = policy.choose(deep, BOOK)
        self.assertEqual(
            (connector.kind, connector.direction, connector.count),
            ("dig_tunnel", (0, 0, 1), 3),
        )

    def test_branch_budget_returns_via_recorded_entrance(self):
        config = miner.MinerConfig(branches_per_trip=1)
        policy = miner.MinerPolicy(config)
        policy.runtime.phase = "mine"
        policy.runtime.excavation_needed = True
        policy.runtime.branches = 1
        state = snapshot(
            ("mcl_core:tree", 8, 0), (miner.IRON_PICK, 1, 0),
            (miner.COBBLE, 16, 0), (miner.COAL, 4, 0), y=-48,
        )
        self.assertEqual(policy.choose(state, BOOK).kind, "return")

    def test_emergencies_precede_inventory_and_mining(self):
        cases = (
            (dict(breath=3), "recover_air"),
            (dict(hazards=("lava",)), "escape_hazard"),
            (dict(burning=True), "extinguish_fire"),
            (dict(hunger=4), "eat_best_food"),
        )
        for changes, expected in cases:
            with self.subTest(expected=expected):
                _, action = self.action(snapshot(**changes))
                self.assertEqual(action.kind, expected)

    def test_inventory_pressure_organizes_once_then_returns_from_mine(self):
        filled = tuple((f"test:item_{i}", 1, 0) for i in range(34))
        policy = miner.MinerPolicy()
        policy.runtime.phase = "mine"
        state = snapshot(*filled, slots=36, revision=7)
        first = policy.choose(state, BOOK)
        self.assertEqual(first.kind, "organize_inventory")
        policy.on_result(first, SkillResult("organize_inventory", "success"), state)
        self.assertEqual(policy.choose(state, BOOK).kind, "return")

    def test_full_surface_inventory_discards_only_after_organizing(self):
        filled = tuple((f"test:item_{i}", 1, 0) for i in range(35))
        policy = miner.MinerPolicy()
        state = snapshot(*filled, slots=36, revision=7)
        organize = policy.choose(state, BOOK)
        policy.on_result(organize, SkillResult("organize_inventory", "success"), state)
        self.assertEqual(policy.choose(state, BOOK).kind, "drop_surplus")

    def test_missing_food_is_not_retried_until_state_changes(self):
        policy = miner.MinerPolicy()
        hungry = snapshot(hunger=4, revision=9)
        action = policy.choose(hungry, BOOK)
        policy.on_result(
            action, SkillResult("eat_best_food", "blocked", "suitable_food_missing"),
            hungry,
        )
        self.assertNotEqual(policy.choose(hungry, BOOK).kind, "eat_best_food")
        changed = snapshot(hunger=4, revision=10)
        self.assertEqual(policy.choose(changed, BOOK).kind, "eat_best_food")


class RecordingGame:
    def __init__(self):
        self.calls = []

    def collect(self, *args, **kwargs):
        self.calls.append(("collect", args, kwargs))
        return SkillResult("collect", "success")

    def craft(self, *args, **kwargs):
        self.calls.append(("craft", args, kwargs))
        return SkillResult("craft", "success")

    def dig_down(self, *args, **kwargs):
        self.calls.append(("dig_down", args, kwargs))
        return SkillResult("dig_down", "success")

    def dig_tunnel(self, *args, **kwargs):
        self.calls.append(("dig_tunnel", args, kwargs))
        return SkillResult("dig_tunnel", "success")


class DropGame:
    def __init__(self, items):
        self.items = list(items)
        self.recipe_book = BOOK
        self.revision = 1

    def observe(self):
        stacks = [Item(name, count, wear) for name, count, wear in self.items]
        stacks.extend(Item("", 0) for _ in range(36 - len(stacks)))
        return SimpleNamespace(
            inventory={"main": InventoryList(9, tuple(stacks))},
            inventory_revision=self.revision,
        )

    def drop(self, slot, count):
        name, old_count, wear = self.items[slot]
        self.items[slot] = (name, old_count - count, wear)
        self.revision += 1

    def wait_for(self, predicate, timeout=5):
        state = self.observe()
        if not predicate(state):
            raise AssertionError("drop was not reflected")
        return state


class ExecutorTests(unittest.TestCase):
    def test_collection_does_not_hide_tool_crafting(self):
        game = RecordingGame()
        miner.execute(game, miner.Action("collect", "test", miner.DIAMOND, 2),
                      miner.MinerConfig())
        _, args, kwargs = game.calls[-1]
        self.assertEqual(args, (miner.DIAMOND, 2))
        self.assertIs(kwargs["allow_tool_crafting"], False)

    def test_crafting_does_not_hide_procurement(self):
        game = RecordingGame()
        miner.execute(game, miner.Action("craft", "test", miner.IRON_PICK),
                      miner.MinerConfig())
        _, args, kwargs = game.calls[-1]
        self.assertEqual(args, (miner.IRON_PICK, 1))
        self.assertIs(kwargs["gather"], False)
        self.assertIs(kwargs["allow_tool_crafting"], False)

    def test_tunnel_uses_one_long_skill_not_per_block_steps(self):
        game = RecordingGame()
        action = miner.Action("dig_tunnel", "test", count=12, direction=(0, 0, 1))
        miner.execute(game, action, miner.MinerConfig())
        name, args, kwargs = game.calls[-1]
        self.assertEqual((name, args), ("dig_tunnel", (12,)))
        self.assertEqual(kwargs["direction"], (0, 0, 1))

    def test_surplus_drop_protects_diamond_tools_and_food(self):
        game = DropGame([
            (miner.DIAMOND, 5, 0),
            (miner.DIAMOND_PICK, 1, 0),
            ("mcl_mobitems:cooked_beef", 4, 0),
            ("mcl_core:tree", 8, 0),
            ("mcl_core:dirt", 64, 0),
        ])
        result = miner.drop_surplus(game, miner.MinerConfig())
        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.details["item"], "mcl_core:dirt")
        self.assertEqual(game.items[0][1], 5)
        self.assertEqual(game.items[1][1], 1)
        self.assertEqual(game.items[2][1], 4)
        self.assertEqual(game.items[3][1], 8)


class LoopGame:
    def __init__(self, *, dead=False):
        self.control = "observe"
        self.dead = dead
        self.diamonds = 0
        self.exploration_memory = None
        self.recipe_book = BOOK
        self.calls = []

    def observe(self):
        return snapshot(
            ("mcl_core:tree", 8, 0),
            (miner.DIAMOND_PICK, 1, 0),
            *((miner.DIAMOND, self.diamonds, 0),) if self.diamonds else (),
            y=-48,
            dead=self.dead,
            control=self.control,
            revision=self.diamonds + 1,
        )

    def take_control(self):
        self.calls.append("take_control")
        self.control = "agent"

    def respawn(self):
        self.calls.append("respawn")
        self.dead = False

    def wait_for(self, predicate, timeout=5):
        state = self.observe()
        if not predicate(state):
            raise AssertionError("fixture did not reach the expected state")
        return state

    def remember_location(self, name):
        self.calls.append(("remember_location", name))
        return (0.0, -48.0, 0.0)

    def collect(self, item, count, **kwargs):
        self.calls.append(("collect", item, count, kwargs))
        self.diamonds += count
        return SkillResult("collect", "success", details={"collected": count})

    def stop(self):
        self.calls.append("stop")

    def release_control(self):
        self.calls.append("release_control")
        self.control = "observe"


class LoopTests(unittest.TestCase):
    def test_initial_death_respawns_before_control_acquisition(self):
        game = LoopGame(dead=True)
        events = []
        report = miner.run_strategy(
            game,
            config=miner.MinerConfig(max_actions=1),
            emit=events.append,
            sleep=lambda _: None,
            survival=False,
        )
        self.assertEqual(report["status"], "bounded_complete")
        self.assertEqual(report["respawns"], 1)
        self.assertLess(game.calls.index("respawn"), game.calls.index("take_control"))
        self.assertTrue(any(
            event.get("event") == "respawn" and
            event.get("reason") == "initial_player_dead"
            for event in events
        ))

    def test_bounded_mode_exercises_same_default_loop_and_releases_control(self):
        game = LoopGame()
        events = []
        report = miner.run_strategy(
            game,
            config=miner.MinerConfig(max_actions=1),
            emit=events.append,
            sleep=lambda _: None,
            survival=False,
        )
        self.assertEqual(report["status"], "bounded_complete")
        self.assertEqual(report["successful_actions"], 1)
        self.assertEqual(game.diamonds, 1)
        self.assertEqual(game.control, "observe")
        self.assertTrue(any(event["event"] == "decision" for event in events))


class ConfigTests(unittest.TestCase):
    def test_optional_bounds_leave_default_infinite(self):
        config = miner.MinerConfig()
        self.assertIsNone(config.max_actions)
        self.assertIsNone(config.max_cycles)

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            miner.MinerConfig(max_actions=0)
        with self.assertRaises(ValueError):
            miner.MinerConfig(tunnel_length=65)
        with self.assertRaises(ValueError):
            miner.MinerConfig(branch_spacing=9)


if __name__ == "__main__":
    unittest.main()
