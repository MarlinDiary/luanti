#!/usr/bin/env python3
"""A first student policy: make one wooden pickaxe, then return to start.

The SDK executes each skill.  This ordinary Python loop chooses their order,
observes the result, and replans.  Edit the constants to try another policy.
"""
import json

from luanti_course import CourseError, Game

GOAL = "wooden_pickaxe"
RESOURCE = "mcl_core:tree"
RESOURCE_COUNT = 3
MAX_STEPS = 12
MAX_RESPAWNS = 1
SEARCH_RADIUS = 24
ACTION_TIMEOUT = 120


def print_event(event):
    print(json.dumps(event, ensure_ascii=False, default=str), flush=True)


def run_strategy(game, *, emit=print_event, max_respawns=MAX_RESPAWNS):
    """Run a bounded policy and return the decisions and real skill results."""
    steps = []
    respawns = 0
    home_saved = collected = crafted = owns_control = False
    task_action_started = False
    report = {
        "objective": f"craft one additional {GOAL} and return to the start",
        "status": "step_limit",
        "reason": "max_steps_reached",
        "respawns": 0,
        "steps": steps,
    }

    def record(event, **details):
        row = {"event": event, **details}
        steps.append(row)
        emit(row)

    def finish(status, reason=""):
        report.update(status=status, reason=reason, respawns=respawns)

    def result_of(action, result):
        record("result", action=action, result=result.to_dict())
        if result.ok:
            return "continue"
        # A death is observed on the next iteration and may choose the explicit
        # respawn branch.  Other failures go straight back to the student.
        if result.reason == "player_dead":
            return "observe"
        finish("needs_replan", result.reason or result.status)
        return "stop"

    try:
        for step in range(1, MAX_STEPS + 1):
            state = game.observe()
            record(
                "observation",
                step=step,
                dead=state.dead,
                hp=state.hp,
                breath=state.raw.get("breath"),
                hunger=state.hunger,
                burning=state.burning,
                control=state.control,
                position=list(state.position),
            )

            if state.dead:
                if respawns >= max_respawns:
                    finish("stopped", "player_dead")
                    break
                record("decision", action="respawn", reason="player_dead")
                game.respawn()
                game.wait_for(lambda current: not current.dead, timeout=8)
                respawns += 1
                owns_control = False       # death invalidated the old lease
                if task_action_started:
                    record("decision", action="stop", reason="death_changed_task_state")
                    finish("needs_replan", "death_changed_task_state")
                    break
                continue

            if state.control == "manual":
                finish("stopped", "manual_takeover")
                break
            if state.control != "agent":
                record("decision", action="take_control", reason="ready")
                game.take_control()
                owns_control = True
                continue

            if not home_saved:
                home = game.remember_location("student_start")
                record("memory", name="student_start", position=list(home))
                home_saved = True

            # Small survival policy: one visible decision at a time.
            if state.raw.get("breath") is not None and state.raw["breath"] < 5:
                record("decision", action="recover_air", reason="low_breath")
                if result_of("recover_air", game.recover_air(timeout=20)) == "stop":
                    break
                continue
            if state.burning:
                record("decision", action="extinguish_fire", reason="burning")
                if result_of("extinguish_fire", game.extinguish_fire(timeout=20)) == "stop":
                    break
                continue
            if state.hunger is not None and state.hunger <= 6:
                record("decision", action="eat_best_food", reason="critical_hunger")
                if result_of("eat_best_food", game.eat_best_food(timeout=12)) == "stop":
                    break
                continue

            if crafted:
                record("decision", action="go_to_location", reason="goal_complete")
                outcome = game.go_to_location(
                    "student_start", timeout=ACTION_TIMEOUT,
                    search_radius=SEARCH_RADIUS,
                )
                decision = result_of("go_to_location", outcome)
                if decision == "continue":
                    finish("complete")
                elif decision == "observe":
                    continue
                break

            plan = game.plan_craft(GOAL, 1, radius=0)
            record("plan", goal=GOAL, plan=plan.to_dict())
            if plan.materials_ready:
                record("decision", action="craft", reason="materials_ready")
                task_action_started = True
                outcome = game.craft(
                    GOAL, 1, gather=False, allow_tool_crafting=False,
                    timeout=ACTION_TIMEOUT,
                )
                decision = result_of("craft", outcome)
                if decision == "continue":
                    crafted = True
                elif decision == "stop":
                    break
                continue

            if not plan.missing_complete or collected:
                record("decision", action="stop", reason="plan_needs_student")
                finish("needs_replan", plan.reason or "materials_still_missing")
                break

            record(
                "decision", action="collect", reason="materials_missing",
                resource=RESOURCE, count=RESOURCE_COUNT,
            )
            task_action_started = True
            outcome = game.collect(
                RESOURCE, count=RESOURCE_COUNT, search_radius=SEARCH_RADIUS,
                timeout=ACTION_TIMEOUT,
            )
            decision = result_of("collect", outcome)
            if decision == "continue":
                collected = True
            elif decision == "stop":
                break
    finally:
        # If F8 gave control to a human, this sends no new control command.
        try:
            if owns_control and game.observe().control == "agent":
                game.stop()
                game.release_control()
        except CourseError:
            pass

    return report


def main():
    try:
        with Game.connect() as game:
            report = run_strategy(game)
    except CourseError as error:
        report = {"status": "error", "reason": str(error)}
    print_event({"event": "finished", "report": report})
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
