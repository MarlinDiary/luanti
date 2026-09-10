"""Explicit student decisions; the SDK handles execution, not the whole campaign."""
from luanti_course import Game

with Game.connect() as game:
    with game.control():
        # Three logs cover a new table, sticks and one wooden pickaxe.
        for job in (lambda: game.collect("mcl_core:tree", 3),
                    lambda: game.craft("wooden_pickaxe")):
            result = job()
            print(result.to_dict())
            if not result.ok:
                break  # Inspect the result; do not blindly replay.
