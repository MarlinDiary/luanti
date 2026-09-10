"""Run a bounded survival loop around an ordinary student's planner (no LLM dependency)."""
import argparse,time
from luanti_course import Game,SurvivalConfig

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds',type=float,default=30)
    p.add_argument('--enemies',choices=('avoid','defend','off'),default='avoid')
    args=p.parse_args()
    if not 0<args.seconds<=600:p.error('seconds must be in (0, 600]')
    with Game.connect() as game:
        with game.control(),game.survival(SurvivalConfig(enemies=args.enemies)) as survival:
            end=time.monotonic()+args.seconds
            while time.monotonic()<end:
                state=game.observe()
                if state.control!='agent' or state.dead:break
                for event in survival.events():print(event)
                # Insert a student/LLM decision here only when not survival.busy.
                # A cancelled skill is not automatically replayed; observe/replan.
                time.sleep(.2)
            for event in survival.events():print(event)
if __name__=='__main__':main()
