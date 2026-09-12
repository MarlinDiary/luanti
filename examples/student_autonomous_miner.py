#!/usr/bin/env python3
"""A long-running student policy for the visible Luanti Course client.

This file deliberately lives above the SDK.  The SDK performs bounded skills;
this policy observes their real results, maintains tools, descends, branch-mines
for iron and diamonds, returns for another trip, and keeps replanning until a
human takes over or the optional action/cycle limit is reached.

Run the course client, enter a world, then use::

    python examples/student_autonomous_miner.py

F8 transfers control to the human and ends the policy.  For a bounded demo use
``--max-actions`` or ``--max-cycles``.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
import math
import time
from typing import Callable, Optional

from luanti_course import (
    CourseError,
    ExplorationMemory,
    Game,
    SkillResult,
    SurvivalConfig,
    Traversal,
)


LOG = "group:tree"
COBBLE = "mcl_core:cobble"
COAL = "mcl_core:coal_lump"
RAW_IRON = "mcl_raw_ores:raw_iron"
IRON = "mcl_core:iron_ingot"
DIAMOND = "mcl_core:diamond"

WOOD_PICK = "mcl_tools:pick_wood"
STONE_PICK = "mcl_tools:pick_stone"
IRON_PICK = "mcl_tools:pick_iron"
DIAMOND_PICK = "mcl_tools:pick_diamond"
PICKS = (WOOD_PICK, STONE_PICK, IRON_PICK, DIAMOND_PICK)

# Serpentine branch mine: long east/west lanes separated by a short connector.
# A four-equal-side rotation would eventually trace the same square again.
TUNNEL_PATTERN = ((1, 0, 0), (0, 0, 1), (-1, 0, 0), (0, 0, 1))


@dataclass(frozen=True)
class MinerConfig:
    """Student-editable strategy choices, rather than hidden SDK policy."""

    target_y: int = -48
    logs_at_surface: int = 8
    cobble_reserve: int = 16
    coal_reserve: int = 4
    raw_iron_target: int = 3
    diamonds_per_trip: int = 3
    tunnel_length: int = 12
    branch_spacing: int = 3
    branches_per_trip: int = 8
    search_radius: int = 24
    action_timeout: float = 180
    replace_tool_at_wear: int = 52_000
    max_retries: int = 3
    max_actions: Optional[int] = None
    max_cycles: Optional[int] = None

    def __post_init__(self):
        if not -256 <= self.target_y <= 256:
            raise ValueError("target_y must be in [-256, 256]")
        for name in (
            "logs_at_surface", "cobble_reserve", "coal_reserve",
            "raw_iron_target", "diamonds_per_trip", "tunnel_length",
            "branch_spacing",
            "branches_per_trip", "search_radius", "max_retries",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.tunnel_length > 64:
            raise ValueError("tunnel_length must be at most 64")
        if self.branch_spacing > 8:
            raise ValueError("branch_spacing must be at most 8")
        if not 1 <= self.search_radius <= 128:
            raise ValueError("search_radius must be in [1, 128]")
        if not 1 <= self.action_timeout <= 3600:
            raise ValueError("action_timeout must be in [1, 3600]")
        if not 1 <= self.replace_tool_at_wear <= 65_534:
            raise ValueError("replace_tool_at_wear must be in [1, 65534]")
        for name in ("max_actions", "max_cycles"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{name} must be a positive integer or None")


@dataclass(frozen=True)
class Action:
    kind: str
    reason: str
    item: Optional[str] = None
    count: int = 1
    direction: Optional[tuple[int, int, int]] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Runtime:
    phase: str = "surface"
    desired_resource: str = RAW_IRON
    excavation_needed: bool = False
    branches: int = 0
    direction_index: int = 0
    cycles: int = 0
    successful_actions: int = 0
    respawns: int = 0
    diamonds_at_trip_start: int = 0
    organized_revision: Optional[int] = None
    discard_attempt_revision: Optional[int] = None
    hunger_attempt: Optional[tuple] = None


def emit_json(event):
    print(json.dumps(event, ensure_ascii=False, default=str), flush=True)


def inventory_count(state, book, token):
    """Count concrete or group-matching items in the ordinary main inventory."""
    return sum(
        item.count for item in state.inventory["main"].items
        if item.count and book.matches(item.name, token)
    )


def healthy_tool(state, name, replace_at):
    """Treat a nearly exhausted tool as unavailable before it breaks mid-skill."""
    return any(
        item.name == name and item.count and item.wear < replace_at
        for item in state.inventory["main"].items
    )


def best_pick_rank(state, replace_at):
    return max(
        (rank for rank, name in enumerate(PICKS, start=1)
         if healthy_tool(state, name, replace_at)),
        default=0,
    )


def occupied_slots(state):
    main = state.inventory["main"]
    return sum(bool(item.count) for item in main.items), main.size


class MinerPolicy:
    """Pure decision state plus feedback from completed SDK skills."""

    def __init__(self, config=MinerConfig()):
        self.config = config
        self.runtime = Runtime()
        self.failures = Counter()

    def _resource_or_excavate(self, state, resource):
        r = self.runtime
        c = self.config
        r.desired_resource = resource
        if not r.excavation_needed:
            return Action("collect", "seek_required_resource", resource, 1)
        if state.position[1] > c.target_y + 0.5:
            depth = min(64, max(1, math.ceil(state.position[1] - c.target_y)))
            return Action("dig_down", "reach_mining_depth", count=depth)
        if r.branches >= c.branches_per_trip:
            return Action("return", "branch_budget_reached")
        direction = TUNNEL_PATTERN[r.direction_index % len(TUNNEL_PATTERN)]
        length = c.tunnel_length if direction[0] else c.branch_spacing
        return Action(
            "dig_tunnel", "expose_new_ore",
            count=length,
            direction=direction,
        )

    def choose(self, state, book):
        c, r = self.config, self.runtime

        # These urgent choices are also monitored during long actions by the
        # Survival supervisor. Repeating them here covers the interval between
        # two skills and keeps the policy independently understandable.
        if state.raw.get("breath") is not None and state.raw["breath"] < 5:
            return Action("recover_air", "low_breath")
        if state.raw.get("hazards"):
            return Action("escape_hazard", "contact_hazard")
        if state.burning:
            return Action("extinguish_fire", "burning")
        hunger_key = (state.hunger, state.inventory_revision)
        if state.hunger is not None and state.hunger <= 8 and r.hunger_attempt != hunger_key:
            return Action("eat_best_food", "critical_hunger")

        used, size = occupied_slots(state)
        if size and used >= size - 2 and r.organized_revision != state.inventory_revision:
            return Action("organize_inventory", "inventory_nearly_full")
        if size and used >= size - 1 and r.phase == "mine":
            return Action("return", "inventory_full_after_organizing")
        if size and used >= size - 1 and r.phase == "surface" and \
                r.discard_attempt_revision != state.inventory_revision:
            return Action("drop_surplus", "make_inventory_space")

        logs = inventory_count(state, book, LOG)
        cobble = inventory_count(state, book, COBBLE)
        coal = inventory_count(state, book, COAL)
        raw_iron = inventory_count(state, book, RAW_IRON)
        iron = inventory_count(state, book, IRON)
        diamonds = inventory_count(state, book, DIAMOND)
        rank = best_pick_rank(state, c.replace_tool_at_wear)

        # Do not get stranded underground without wood for sticks, a table, or
        # an emergency replacement. Return via the recorded trail first.
        if logs < 3 and r.phase == "mine" and rank < 4:
            return Action("return", "wood_reserve_exhausted")
        if logs < c.logs_at_surface and r.phase == "surface":
            return Action("collect", "replenish_wood", LOG, c.logs_at_surface - logs)

        # Explicit tool ladder. The collect skill never receives the teacher
        # shortcut allow_tool_crafting=True; replacement remains policy logic.
        if rank == 0:
            return Action("craft", "replace_or_bootstrap_pick", WOOD_PICK)
        if rank == 1:
            if cobble < 3:
                return Action("collect", "stone_pick_material", COBBLE, 3 - cobble)
            return Action("craft", "upgrade_to_stone_pick", STONE_PICK)

        # Preserve enough stone for a furnace and a spare stone pick before
        # committing to iron. Existing workstations simply make this cheaper.
        if rank < 3:
            if cobble < c.cobble_reserve:
                return Action("collect", "furnace_and_spare_stone", COBBLE,
                              c.cobble_reserve - cobble)
            if coal < 1:
                return self._resource_or_excavate(state, COAL)
            if raw_iron + iron < c.raw_iron_target:
                return self._resource_or_excavate(state, RAW_IRON)
            return Action("craft", "smelt_and_upgrade_to_iron", IRON_PICK)

        # Once three diamonds exist, invest them in a durable replacement. A
        # worn iron pick is not sent after another diamond vein.
        if rank < 4 and diamonds >= 3:
            return Action("craft", "upgrade_to_diamond_pick", DIAMOND_PICK)

        gained = max(0, diamonds - r.diamonds_at_trip_start)
        if r.phase == "mine" and gained >= c.diamonds_per_trip:
            return Action("return", "diamond_batch_complete")

        return self._resource_or_excavate(state, DIAMOND)

    def on_result(self, action, result, state=None):
        """Update only from an observed SDK result; never assume an action worked."""
        r, c = self.runtime, self.config
        key = (action.kind, action.item, action.direction)
        if result.ok:
            self.failures.pop(key, None)
            r.successful_actions += 1
            if action.kind == "dig_down":
                r.phase = "mine"
                r.excavation_needed = False
            elif action.kind == "dig_tunnel":
                r.phase = "mine"
                if action.direction and action.direction[0]:
                    r.branches += 1
                r.direction_index += 1
                r.excavation_needed = False
            elif action.kind == "collect":
                r.excavation_needed = False
            elif action.kind == "return":
                r.phase = "surface"
                r.branches = 0
                r.cycles += 1
                r.excavation_needed = False
            elif action.kind == "organize_inventory" and state is not None:
                r.organized_revision = state.inventory_revision
            elif action.kind == "drop_surplus" and state is not None:
                r.discard_attempt_revision = state.inventory_revision
            elif action.kind == "eat_best_food" and state is not None:
                r.hunger_attempt = (state.hunger, state.inventory_revision)
            return

        self.failures[key] += 1
        reason = result.reason
        if action.kind == "organize_inventory" and state is not None:
            r.organized_revision = state.inventory_revision
        if action.kind == "drop_surplus" and state is not None:
            r.discard_attempt_revision = state.inventory_revision
        if action.kind == "eat_best_food" and state is not None:
            # No suitable food is a real observation, not a reason to hammer
            # the same action forever. A changed hunger value or inventory
            # revision makes the choice eligible again.
            r.hunger_attempt = (state.hunger, state.inventory_revision)
        if action.kind == "collect" and reason in {
            "resource_not_found", "target_out_of_radius", "path_not_found",
            "resource_unreachable", "deadline_exceeded",
        }:
            r.desired_resource = action.item or r.desired_resource
            r.excavation_needed = True
        elif action.kind in {"dig_down", "dig_tunnel"} and reason in {
            "mining_route_blocked", "excavation_hazard",
            "unstable_excavation_boundary", "excavation_floor_unstable",
            "terrain_edit_budget", "deadline_exceeded",
        }:
            r.phase = "mine"
            if action.kind == "dig_tunnel" and action.direction and action.direction[0]:
                r.branches += 1
            if action.kind == "dig_tunnel":
                r.direction_index += 1
            r.excavation_needed = True
        elif reason == "suitable_tool_required":
            # The next observation will see the broken/missing tool and enter
            # the explicit replacement ladder.
            r.excavation_needed = action.kind == "collect"

        if self.failures[key] >= c.max_retries and r.phase == "mine":
            r.branches = c.branches_per_trip


def reaction_failed(event):
    if event.get("event") in {"reaction_error", "action_not_yielding", "control_lost"}:
        return True
    if event.get("event") != "reaction_finished":
        return False
    result = event["result"]
    if result["status"] == "success":
        return False
    intervention = result.get("details", {}).get("intervention") or {}
    return not (
        result["status"] == "cancelled"
        and result["reason"] == "survival_interrupted"
        and intervention.get("action") in {
            "recover_air", "escape_hazard", "extinguish_fire",
            "avoid_projectile", "survive_blast", "flee_from",
            "defend_self", "eat_best_food",
        }
    )


def _protected_item(name, book):
    if name in {*PICKS, LOG, COBBLE, COAL, RAW_IRON, IRON, DIAMOND}:
        return True
    data = book.items.get(book.resolve(name), {})
    groups = data.get("groups") or {}
    return data.get("type") == "tool" or any(
        groups.get(group, 0) > 0
        for group in (
            "food", "armor", "combat_armor", "weapon", "sword",
            "tree", "wood", "material_wood",
        )
    )


def drop_surplus(game, config):
    """Free one entire slot and confirm the real inventory change.

    This is intentionally a visible policy choice. It prefers bulk tunnel
    spoil, then other non-tool/non-food clutter, and never claims success from
    the low-level submission alone.
    """
    started = time.monotonic()
    state = game.observe()
    main = state.inventory["main"]
    preferred = {
        "mcl_core:dirt", "mcl_core:gravel", "mcl_core:stone",
        "mcl_deepslate:deepslate", "mcl_deepslate:deepslate_cobbled",
    }
    choices = []
    for slot, item in enumerate(main.items):
        if not item.count or _protected_item(item.name, game.recipe_book):
            continue
        choices.append((item.name not in preferred, -item.count, slot, item))
    # Cobble is protected as a reserve, but a full extra stack is safe to shed.
    cobble_total = inventory_count(state, game.recipe_book, COBBLE)
    for slot, item in enumerate(main.items):
        if item.name == COBBLE and cobble_total - item.count >= config.cobble_reserve:
            choices.append((False, -item.count, slot, item))
    if not choices:
        return SkillResult(
            "drop_surplus", "blocked", "no_discardable_stack",
            {"occupied": occupied_slots(state)[0]}, elapsed=round(time.monotonic() - started, 3),
        )
    _, _, slot, item = min(choices)
    before = sum(x.count for x in main.items if x.name == item.name)
    game.drop(slot, item.count)
    try:
        final = game.wait_for(
            lambda current: sum(
                x.count for x in current.inventory["main"].items
                if x.name == item.name
            ) <= before - item.count,
            timeout=min(8, config.action_timeout),
        )
    except CourseError as error:
        return SkillResult(
            "drop_surplus", "blocked", "drop_unconfirmed",
            {"item": item.name, "count": item.count, "message": str(error)},
            elapsed=round(time.monotonic() - started, 3),
        )
    return SkillResult(
        "drop_surplus", "success",
        details={
            "item": item.name,
            "count": item.count,
            "slot": slot,
            "inventory_revision": final.inventory_revision,
        },
        elapsed=round(time.monotonic() - started, 3),
    )


def execute(game, action, config):
    common = dict(
        timeout=config.action_timeout,
        search_radius=config.search_radius,
    )
    traversal = Traversal(
        allow_swim=True,
        allow_climb=True,
        allow_interact=True,
        edit_budget=128,
    )
    if action.kind == "collect":
        return game.collect(
            action.item, action.count, traversal=traversal,
            allow_tool_crafting=False, **common,
        )
    if action.kind == "craft":
        return game.craft(
            action.item, action.count, gather=False,
            allow_tool_crafting=False, traversal=traversal, **common,
        )
    if action.kind == "dig_down":
        return game.dig_down(
            action.count, traversal=traversal,
            timeout=config.action_timeout, search_radius=128,
        )
    if action.kind == "dig_tunnel":
        return game.dig_tunnel(
            action.count, direction=action.direction, traversal=traversal,
            timeout=config.action_timeout, search_radius=128,
        )
    if action.kind == "return":
        return game.return_to_entrance(
            traversal=traversal, timeout=config.action_timeout,
        )
    if action.kind == "organize_inventory":
        return game.organize_inventory(timeout=min(30, config.action_timeout))
    if action.kind == "drop_surplus":
        return drop_surplus(game, config)
    if action.kind == "recover_air":
        return game.recover_air(timeout=min(30, config.action_timeout))
    if action.kind == "escape_hazard":
        return game.escape_hazard(timeout=min(30, config.action_timeout))
    if action.kind == "extinguish_fire":
        return game.extinguish_fire(timeout=min(30, config.action_timeout))
    if action.kind == "eat_best_food":
        return game.eat_best_food(timeout=min(20, config.action_timeout))
    raise ValueError(f"unsupported policy action: {action.kind}")


def run_strategy(
    game,
    *,
    config=MinerConfig(),
    emit: Callable[[dict], None] = emit_json,
    sleep: Callable[[float], None] = time.sleep,
    survival=True,
):
    """Run until manual takeover, an explicit bound, or connection failure."""
    policy = MinerPolicy(config)
    report = {
        "objective": "continuous tool progression and branch mining for diamonds",
        "status": "running",
        "reason": "",
        "actions": [],
        "cycles": 0,
        "respawns": 0,
    }
    guard = None

    def record(event, **details):
        row = {"event": event, **details}
        if event in {"decision", "result", "survival", "respawn"}:
            report["actions"].append(row)
        emit(row)

    try:
        initial = game.observe()
        if initial.control == "manual":
            report.update(status="stopped", reason="manual_takeover")
            return report
        # The death form is intentionally a menu, so the client rejects
        # acquire until respawn. Recover before taking control rather than
        # making a long-running policy require a manual click after restart.
        if initial.dead:
            record("respawn", reason="initial_player_dead")
            game.respawn()
            initial = game.wait_for(
                lambda current: not current.dead and not current.raw.get("menu_open"),
                timeout=10,
            )
            policy.runtime.respawns += 1
        if initial.control != "agent":
            game.take_control()
        if game.exploration_memory is None:
            game.exploration_memory = ExplorationMemory(ttl=300)
        home = game.remember_location("student_miner_home")
        policy.runtime.diamonds_at_trip_start = inventory_count(
            initial, game.recipe_book, DIAMOND
        )
        record("memory", name="student_miner_home", position=list(home))

        if survival:
            guard = game.survival(SurvivalConfig(enemies="avoid"))
            guard.__enter__()

        while True:
            state = game.observe()
            record(
                "observation",
                phase=policy.runtime.phase,
                position=list(state.position),
                hp=state.hp,
                dead=state.dead,
                hunger=state.hunger,
                breath=state.raw.get("breath"),
                control=state.control,
                cycles=policy.runtime.cycles,
                successful_actions=policy.runtime.successful_actions,
            )

            if state.control == "manual":
                report.update(status="stopped", reason="manual_takeover")
                break
            if state.dead:
                record("respawn", reason="player_dead")
                if guard:
                    guard.pause()
                game.respawn()
                game.wait_for(lambda current: not current.dead, timeout=10)
                policy.runtime.respawns += 1
                game.take_control()
                game.reset_mining_trip()
                policy.runtime.phase = "surface"
                policy.runtime.branches = 0
                policy.runtime.excavation_needed = False
                if guard:
                    for event in guard.events():
                        record("survival", detail=event)
                    guard.resume()
                continue
            if state.control != "agent":
                report.update(status="stopped", reason="control_released")
                break

            if guard:
                if guard.busy:
                    if not guard.wait_idle(timeout=45):
                        report.update(status="stopped", reason="survival_timeout")
                        break
                    continue
                events = guard.events()
                for event in events:
                    record("survival", detail=event)
                if any(reaction_failed(event) for event in events):
                    report.update(status="stopped", reason="survival_reaction_failed")
                    break

            if config.max_actions is not None and \
                    policy.runtime.successful_actions >= config.max_actions:
                report.update(status="bounded_complete", reason="max_actions_reached")
                break
            if config.max_cycles is not None and policy.runtime.cycles >= config.max_cycles:
                report.update(status="bounded_complete", reason="max_cycles_reached")
                break

            action = policy.choose(state, game.recipe_book)
            record("decision", action=action.to_dict())
            result = execute(game, action, config)
            record("result", action=action.to_dict(), result=result.to_dict())

            fresh = game.observe()
            policy.on_result(action, result, fresh)
            if action.kind == "return" and result.ok:
                # The mining skill returned to its real recorded entrance. A
                # separate named navigation makes multi-stage trips explicit.
                home_result = game.go_to_location(
                    "student_miner_home",
                    timeout=config.action_timeout,
                    search_radius=max(64, config.search_radius),
                )
                record(
                    "result",
                    action=Action("go_home", "trip_complete").to_dict(),
                    result=home_result.to_dict(),
                )
                if home_result.ok:
                    game.reset_mining_trip()
                    policy.runtime.diamonds_at_trip_start = inventory_count(
                        game.observe(), game.recipe_book, DIAMOND
                    )

            if not result.ok:
                if result.reason in {"player_dead", "survival_interrupted"}:
                    continue
                attempt = policy.failures[(action.kind, action.item, action.direction)]
                delay = min(8.0, 0.5 * (2 ** min(attempt, 4)))
                record("backoff", seconds=delay, reason=result.reason)
                sleep(delay)
    except KeyboardInterrupt:
        report.update(status="stopped", reason="keyboard_interrupt")
    except CourseError as error:
        report.update(status="error", reason=str(error))
    finally:
        if guard is not None:
            try:
                guard.close()
            except CourseError as error:
                report.setdefault("cleanup_error", str(error))
        try:
            state = game.observe()
            if state.control == "agent":
                game.stop()
                game.release_control()
        except CourseError:
            pass
        report["cycles"] = policy.runtime.cycles
        report["respawns"] = policy.runtime.respawns
        report["successful_actions"] = policy.runtime.successful_actions
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-y", type=int, default=-48)
    parser.add_argument("--max-actions", type=int)
    parser.add_argument("--max-cycles", type=int)
    parser.add_argument("--tunnel-length", type=int, default=12)
    parser.add_argument("--branch-spacing", type=int, default=3)
    parser.add_argument("--branches-per-trip", type=int, default=8)
    parser.add_argument(
        "--no-survival", action="store_true",
        help="disable background reactions for controlled local experiments",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    config = MinerConfig(
        target_y=args.target_y,
        max_actions=args.max_actions,
        max_cycles=args.max_cycles,
        tunnel_length=args.tunnel_length,
        branch_spacing=args.branch_spacing,
        branches_per_trip=args.branches_per_trip,
    )
    try:
        with Game.connect() as game:
            report = run_strategy(game, config=config, survival=not args.no_survival)
    except CourseError as error:
        report = {"status": "error", "reason": str(error)}
    emit_json({"event": "finished", "report": report})
    return 0 if report["status"] in {"bounded_complete", "stopped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
