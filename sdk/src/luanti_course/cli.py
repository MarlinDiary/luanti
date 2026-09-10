import argparse,json,os,subprocess,sys
from pathlib import Path
from . import Game,CourseError,find_binary,profile_path,__version__

def main(argv=None):
    p=argparse.ArgumentParser(description='Luanti Course — visible game, simple Python control')
    p.add_argument('--version',action='version',version=__version__)
    sub=p.add_subparsers(dest='command',required=True)
    start=sub.add_parser('launch',help='Open the course client; login stays in the game UI')
    start.add_argument('--client');start.add_argument('--profile');start.add_argument('--world')
    doctor=sub.add_parser('doctor',help='Check installation and connection without moving the player')
    doctor.add_argument('--profile');doctor.add_argument('--client')
    obs=sub.add_parser('observe',help='Print a read-only state snapshot');obs.add_argument('--profile')
    stop=sub.add_parser('stop',help='Release control if the controller connection is available');stop.add_argument('--profile')
    args=p.parse_args(argv)
    try:
        if args.command=='launch':
            binary=find_binary(args.client);profile=Path(args.profile) if args.profile else profile_path();profile.mkdir(parents=True,exist_ok=True)
            command=[str(binary)]
            if args.world:command.extend(['--world',str(Path(args.world).resolve()),'--go'])
            subprocess.Popen(command,env=dict(os.environ,LUANTI_USER_PATH=str(profile)),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            print('Client opened. Join a world, then run your Python script.');return 0
        if args.command=='doctor':
            result={'sdk_version':__version__,'python':sys.version.split()[0],'profile':str(Path(args.profile) if args.profile else profile_path())}
            try:result['client']=str(find_binary(args.client))
            except CourseError as e:result['client_note']=str(e)
            try:
                with Game.connect(profile=args.profile) as game:
                    state=game.observe();result.update(connected=True,control=state.control,capabilities=game.capabilities)
            except CourseError as e:result.update(connected=False,connection_note=str(e))
            print(json.dumps(result,indent=2));return 0 if result['connected'] else 1
        with Game.connect(profile=args.profile) as game:
            if args.command=='observe':print(json.dumps(game.observe().raw,indent=2))
            else:game.release_control();print('Control released.')
        return 0
    except (CourseError,ValueError,OSError) as exc:
        print('Luanti Course: '+str(exc),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
