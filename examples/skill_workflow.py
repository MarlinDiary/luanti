"""Advanced opt-in procurement example, not the default student skill boundary.

The course decides whether gather=True is allowed. This is not an LLM agent.
"""
from pathlib import Path
from luanti_course import Game, Traversal, ExplorationMemory

def make_iron_pickaxe(checkpoint=Path('tasks/iron-pickaxe.json')):
    with Game.connect() as game:
        game.traversal=Traversal(allow_swim=True,allow_jump_gaps=True)
        game.exploration_memory=ExplorationMemory(ttl=60)
        with game.control():
            result=game.resume(checkpoint) if checkpoint.exists() else game.craft(
                'mcl_tools:pick_iron',gather=True,checkpoint=checkpoint)
            print(result.to_dict())
            return result

if __name__=='__main__':make_iron_pickaxe()
