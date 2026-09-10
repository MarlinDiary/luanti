from luanti_course import Game

with Game.connect() as game:
    with game.control():
        home = game.observe().position
        result = game.collect('group:tree', count=3, search_radius=24)
        print(result.to_dict())
        if result.ok:
            print(game.navigate_to(home).to_dict())
