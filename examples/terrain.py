"""Ordinary Python; no Agent framework required. Use your own world target."""
from luanti_course import Game

with Game.connect() as game:
    with game.control():
        state = game.observe()
        target = (state.position[0] + 8, state.position[1], state.position[2])
        result = game.navigate_to(target, allow_swim=True, allow_jump_gaps=True)
        print(result.to_dict())
        # Opt in separately if the task allows modifying terrain:
        # result = game.navigate_to(target, allow_dig=True,
        #                           build_with="mcl_core:cobble", edit_budget=16)
