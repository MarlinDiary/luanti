"""Observe a material plan; no control lease, movement, or automatic procurement."""
import argparse
import json
from luanti_course import Game


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('item', nargs='?', default='wooden_pickaxe')
    parser.add_argument('--count', type=int, default=1)
    args = parser.parse_args()
    with Game.connect() as game:
        plan = game.plan_craft(args.item, args.count)
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        # Students choose the next task. Even materials_ready=True still needs
        # execution-time checks for fuel/furnace, tools, reachability and space.


if __name__ == '__main__':
    main()
