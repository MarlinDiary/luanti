#!/usr/bin/env python3
"""Run a provider-neutral LLM planner against the current visible client.

The command receives one JSON request on stdin and prints exactly one typed
SkillCall JSON object.  It may use any model/provider; this example adds no
provider SDK dependency and gives the model no private Game methods.
"""
import argparse,json
from luanti_course import Agent,CommandPlanner,Game

p=argparse.ArgumentParser()
p.add_argument('objective')
p.add_argument('--planner',required=True,help='model CLI command: JSON stdin -> JSON stdout')
p.add_argument('--max-steps',type=int,default=24)
a=p.parse_args()

with Game.connect() as game:
    with game.control():
        result=Agent(game,CommandPlanner(a.planner),max_steps=a.max_steps).run(a.objective)
print(json.dumps(result.to_dict(),ensure_ascii=False,indent=2))
