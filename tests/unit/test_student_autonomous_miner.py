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
                         ("collect", miner.LOG, 3))

    def test_three_logs_are_enough_to_start_the_tool_ladder(self):
        _, action = self.action(snapshot(("mcl_core:tree", 3, 0)))
        self.assertEqual((action.kind, action.item),
                         ("craft", miner.WOOD_PICK))

    def test_crafted_handle_stock_is_not_mistaken_for_missing_raw_logs(self):
        policy = miner.MinerPolicy()
        policy.runtime.phase = "mine"
        state = snapshot(
            (miner.WOOD_PICK, 1, 0),
            ("mcl_core:wood", 3, 0),
            ("mcl_core:stick", 2, 0),
            (miner.COBBLE, 3, 0),
            y=11.5,
        )
        action = policy.choose(state, BOOK)
        self.assertEqual((action.kind, action.item),
                         ("craft", miner.STONE_PICK))

    def test_missing_crafting_material_underground_returns_for_resupply(self):
        policy = miner.MinerPolicy()
        policy.runtime.phase = "mine"
        state = snapshot(
            (miner.STONE_PICK, 1, 0),
            (miner.COBBLE, 16, 0),
            (miner.COAL, 4, 0),
            (miner.RAW_IRON, 3, 0),
            y=-48,
        )
        craft = policy.choose(state, BOOK)
        self.assertEqual((craft.kind, craft.item), ("craft", miner.IRON_PICK))
        policy.on_result(
            craft,
            SkillResult("craft", "blocked", "missing_materials"),
            state,
        )
        retreat = policy.choose(state, BOOK)
        self.assertEqual((retreat.kind, retreat.reason),
                         ("return", "crafting_materials_unavailable_underground"))
        policy.on_result(retreat, SkillResult("return_to_entrance", "success"), state)
        self.assertEqual(policy.runtime.cycles, 0)

    def test_failed_cobble_pickup_exposes_fresh_stone_instead_of_repeating(self):
        policy = miner.MinerPolicy()
        state = snapshot((miner.STONE_PICK, 1, 0), (miner.COBBLE, 12, 0), y=10.5)
        collect = policy.choose(state, BOOK)
        self.assertEqual(collect.item, miner.COBBLE)
        policy.on_result(collect, SkillResult("collect", "blocked", "pickup_unconfirmed"), state)
        next_action = policy.choose(state, BOOK)
        self.assertEqual((next_action.kind, next_action.reason),
                         ("dig_down", "expose_reachable_stone"))
        self.assertLessEqual(next_action.count, 3)

    def test_surface_resupply_is_requested_only_after_observed_shortage(self):
        policy = miner.MinerPolicy()
        state = snapshot(
            (miner.STONE_PICK, 1, 0),
            (miner.COBBLE, 16, 0),
            (miner.COAL, 4, 0),
            (miner.RAW_IRON, 3, 0),
        )
        craft = policy.choose(state, BOOK)
        self.assertEqual((craft.kind, craft.item), ("craft", miner.IRON_PICK))
        policy.on_result(
            craft,
            SkillResult("craft", "blocked", "missing_materials"),
            state,
        )
        collect = policy.choose(state, BOOK)
        self.assertEqual((collect.kind, collect.item, collect.count),
                         ("collect", miner.LOG, 3))

    def test_tool_progression_is_wood_then_stone_then_iron(self):
        cases = (
            (snapshot(("mcl_core:tree", 8, 0)),
             ("craft", miner.WOOD_PICK)),
            (snapshot(("mcl_core:tree", 8, 0), (miner.WOOD_PICK, 1, 0)),
             ("dig_down", None)),
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

    def test_existing_pick_does_not_top_up_a_noncritical_wood_reserve(self):
        state = snapshot(
            ("mcl_core:tree", 7, 0),
            (miner.STONE_PICK, 1, 0),
            (miner.COBBLE, 16, 0),
            y=9.5,
        )
        _, action = self.action(state)
        self.assertEqual((action.kind, action.item), ("collect", miner.COAL))

    def test_wood_pick_mines_for_cobble_instead_of_waiting_for_exposed_stone(self):
        state = snapshot(
            ("mcl_core:tree", 8, 0),
            (miner.WOOD_PICK, 1, 0),
            y=15.5,
        )
        _, action = self.action(state)
        self.assertEqual(action.kind, "dig_down")
        self.assertEqual(action.reason, "mine_stone_for_pick")
        self.assertEqual(action.count, 3)

    def test_missing_underground_workbench_returns_before_replacing_pick(self):
        policy = miner.MinerPolicy()
        policy.runtime.phase = "mine"
        state = snapshot(
            ("mcl_core:tree", 3, 0),
            (miner.WOOD_PICK, 1, 0),
            (miner.COBBLE, 16, 0),
            y=-29.5,
        )
        craft = policy.choose(state, BOOK)
        self.assertEqual((craft.kind, craft.item), ("craft", miner.STONE_PICK))
        policy.on_result(
            craft,
            SkillResult("craft", "blocked", "no_workbench_placement_site"),
            state,
        )
        retreat = policy.choose(state, BOOK)
        self.assertEqual((retreat.kind, retreat.reason),
                         ("return", "workbench_unavailable_underground"))
        policy.on_result(retreat, SkillResult("return_to_entrance", "success"), state)
        self.assertEqual(policy.runtime.phase, "surface")
        self.assertEqual(policy.runtime.cycles, 0)

    def test_cramped_home_opens_a_short_level_workbench_alcove(self):
        policy = miner.MinerPolicy()
        state = snapshot((miner.WOOD_PICK, 1, 0), (miner.COBBLE, 16, 0), y=10.5)
        craft = policy.choose(state, BOOK)
        policy.on_result(craft, SkillResult("craft", "blocked", "no_workbench_placement_site"), state)
        alcove = policy.choose(state, BOOK)
        self.assertEqual((alcove.kind, alcove.reason, alcove.count),
                         ("dig_tunnel", "prepare_workbench_alcove", 2))
        self.assertIn(alcove.direction, ((1,0,0),(0,0,1),(-1,0,0),(0,0,-1)))
        policy.on_result(alcove, SkillResult("dig_tunnel", "blocked", "mining_route_blocked"), state)
        alternative = policy.choose(state, BOOK)
        self.assertNotEqual(alternative.direction, alcove.direction)
        self.assertEqual(alternative.reason, "prepare_workbench_alcove")
        alcove = alternative
        policy.on_result(alcove, SkillResult("dig_tunnel", "success"), state)
        self.assertEqual(policy.runtime.branches, 0)
        self.assertEqual(policy.runtime.cycles, 0)
        next_action = policy.choose(state, BOOK)
        self.assertEqual((next_action.kind, next_action.item), ("craft", miner.STONE_PICK))

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
        # Re-observe exposed coal/iron and wear before spending the whole pick
        # descending dozens of steps toward the diamond layer.
        self.assertEqual((descent.kind, descent.count), ("dig_down", 8))

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

    def test_successful_excavation_resets_stale_resource_search_failures(self):
        policy = miner.MinerPolicy()
        for y in (16, 8, 0, -8):
            state = snapshot((miner.STONE_PICK, 1, 0), (miner.COBBLE, 16, 0), y=y)
            search = policy.choose(state, BOOK)
            self.assertEqual(search.item, miner.COAL)
            policy.on_result(search, SkillResult("collect", "blocked", "resource_not_found"), state)
            descent = policy.choose(state, BOOK)
            self.assertEqual(descent.kind, "dig_down")
            policy.on_result(descent, SkillResult("dig_down", "success"), state)
        self.assertEqual(policy.runtime.branches, 0)
        self.assertEqual(policy.failures[("collect", miner.COAL, None)], 0)

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

    def test_bootstrap_damage_triggers_immediate_retreat_before_retry(self):
        policy = miner.MinerPolicy()
        healthy = snapshot(hp=20)
        collect = policy.choose(healthy, BOOK)
        damaged = snapshot(hp=16)
        policy.on_result(
            collect,
            SkillResult("collect", "blocked", "player_damaged"),
            damaged,
        )
        retreat = policy.choose(damaged, BOOK)
        self.assertEqual((retreat.kind, retreat.reason),
                         ("flee_from", "damaged_during_bootstrap"))

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

    def reset_mining_trip(self):
        self.calls.append(("reset_mining_trip", (), {}))


class FailedActionRecoveryTests(unittest.TestCase):
    def test_disconnected_mining_trail_starts_a_fresh_excursion(self):
        game = RecordingGame()
        result = SkillResult(
            "dig_down", "blocked", "mining_trip_disconnected"
        )
        self.assertEqual(
            miner.recover_failed_action(game, result),
            "mining_trip_reset",
        )
        self.assertEqual(game.calls, [("reset_mining_trip", (), {})])


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
    def test_bootstrap_avoids_unwinnable_combat_then_enables_defense(self):
        self.assertEqual(miner.enemy_policy(snapshot()), "off")
        self.assertEqual(
            miner.enemy_policy(snapshot((miner.WOOD_PICK, 1, 0))), "off"
        )
        self.assertEqual(
            miner.enemy_policy(snapshot((miner.STONE_PICK, 1, 0))), "defend"
        )

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


class SurvivalEventTests(unittest.TestCase):
    def test_bounded_reaction_timeout_requests_replan_instead_of_stopping(self):
        event = {
            "event": "reaction_finished",
            "result": {
                "operation": "flee_from",
                "status": "timeout",
                "reason": "deadline_exceeded",
                "details": {},
            },
        }
        self.assertFalse(miner.reaction_failed(event))

    def test_survival_worker_error_remains_fatal(self):
        self.assertTrue(miner.reaction_failed({
            "event": "reaction_error",
            "message": "worker stopped",
        }))

    def test_action_yield_timeout_is_recoverable_supervisor_feedback(self):
        self.assertFalse(miner.reaction_failed({
            "event": "action_not_yielding",
        }))


if __name__ == "__main__":
    unittest.main()
