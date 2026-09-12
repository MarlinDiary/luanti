import json
import math
from pathlib import Path
import sys
import threading
import unittest
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course import Game, SkillResult, RecipeBook, ActionError
from luanti_course.navigation import World, Node, cell, feet
from luanti_course.recipes import PlanningError, TABLE
from luanti_course.skills import ActionLock, positive

AIR=Node('air',False)
STONE=Node('stone',True)

def world(n=5):
    w=World()
    for x in range(-n,n+1):
        for z in range(-n,n+1):
            w.nodes[(x,0,z)]=STONE
            for y in (1,2,3):w.nodes[(x,y,z)]=AIR
    return w

class PathTests(unittest.TestCase):
    def test_blocked_precise_endpoint_does_not_replan_same_cell_forever(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from luanti_course.skills import navigate, Failure
        w=world()
        s=SimpleNamespace(position=(0,.5,0),raw={})
        ctx=SimpleNamespace(world=w,read=lambda r=0:s,game=SimpleNamespace(capabilities=('steer',)),
                            blocked=set(),within=lambda p:True,log=lambda *a,**k:None,
                            stop_input=lambda:None,sleep=lambda _:None)
        with patch('luanti_course.skills.follow_path',return_value=(False,((0,1,0),(0,1,0)))) as follow:
            with self.assertRaises(Failure) as error:navigate(ctx,(.4,.5,0),tolerance=.05)
        self.assertEqual(error.exception.reason,'movement_blocked')
        self.assertEqual(follow.call_count,1)

    def test_coordinate_convention(self):
        self.assertEqual(cell((0,99.5,-2)),(0,100,-2))
        self.assertEqual(feet((0,100,-2)),(0,99.5,-2))
    def test_straight_path(self):
        w=world();p,_=w.path((0,1,0),lambda p:p==(3,1,0))
        self.assertEqual(len(p),4)
    def test_wall_detour_multiple_layouts(self):
        for gap in (-3,0,3):
            w=world()
            for z in range(-4,5):
                if z!=gap:
                    for y in (1,2):w.nodes[(0,y,z)]=STONE
            p,_=w.path((-3,1,1),lambda p:p==(3,1,1))
            self.assertIsNotNone(p)
            self.assertIn((0,1,gap),p)
    def test_unknown_is_not_air(self):
        w=world();del w.nodes[(1,1,0)]
        self.assertFalse(w.standable((1,1,0)))
    def test_liquid_damage_and_partial_support(self):
        for node in [Node('water',False,liquid=True),Node('lava',True,damage=4),Node('slab',True,full_cube=False)]:
            w=world();w.nodes[(1,0,0)]=node
            self.assertFalse(w.standable((1,1,0)))
    def test_jump_needs_headroom(self):
        w=world();w.nodes[(1,1,0)]=STONE
        self.assertIn((1,2,0),dict(w.neighbors((0,1,0))))
        w.nodes[(0,3,0)]=STONE
        self.assertNotIn((1,2,0),dict(w.neighbors((0,1,0))))
    def test_big_drop_is_blocked(self):
        w=world();w.nodes[(1,0,0)]=AIR;w.nodes[(1,-2,0)]=STONE;w.nodes[(1,-1,0)]=AIR
        self.assertFalse(any(p[0]==1 and p[2]==0 for p,_ in w.neighbors((0,1,0))))
    def test_dynamic_obstacle_replans(self):
        w=world();target=(3,1,0);p,_=w.path((0,1,0),lambda p:p==target)
        w.nodes[p[1]]=STONE;w.nodes[(p[1][0],2,p[1][2])]=STONE
        revised,_=w.path((0,1,0),lambda p:p==target)
        self.assertNotIn(p[1],revised)
    def test_radius_and_expansion_bound(self):
        w=world(8);p,_=w.path((0,1,0),lambda p:p==(8,1,0),within=lambda p:abs(p[0])<4)
        self.assertIsNone(p)
        p,seen=w.path((0,1,0),lambda p:False,max_nodes=3)
        self.assertLessEqual(len(seen),3)
    def test_revealed_map_exploration_does_not_oscillate(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from luanti_course.skills import navigate
        complete=world(20)
        for z in range(-10,11):
            if z!=3:
                complete.nodes[(0,1,z)]=STONE;complete.nodes[(0,2,z)]=STONE
        class Context:
            def __init__(self):
                self.position=(-6,.5,-5);self.origin=self.position;self.world=World();self.blocked=set();self.calls=0;self.game=SimpleNamespace(capabilities=("steer",))
            def read(self,radius=0):
                self.calls+=1
                if self.calls>150:raise AssertionError('exploration oscillated')
                current=cell(self.position)
                self.world.nodes.update({p:n for p,n in complete.nodes.items() if all(abs(p[i]-current[i])<=6 for i in range(3))})
                return SimpleNamespace(position=self.position)
            def within(self,p):return True
            def log(self,*args,**kwargs):pass
            def stop_input(self):pass
            def sleep(self,seconds):pass
        context=Context()
        def move(c,path,target,*args):c.position=target;return True,None
        with patch('luanti_course.skills.follow_path',move):navigate(context,(6,.5,-5))
        self.assertLess(context.calls,80)

    def test_ray_obstruction(self):
        w=world();self.assertTrue(w.visible((0,2,0),(3,1,0)))
        w.nodes[(1,2,0)]=STONE
        self.assertFalse(w.visible((0,2,0),(3,1,0)))

    def test_smoothing_checks_player_width_and_ground(self):
        w=world()
        self.assertTrue(w.corridor_clear((0,.5,0),(3,.5,0)))
        w.nodes[(1,1,1)]=STONE;w.nodes[(1,2,1)]=STONE
        self.assertFalse(w.corridor_clear((0,.5,0),(3,.5,3)))
        del w.nodes[(1,0,0)]
        self.assertFalse(w.corridor_clear((0,.5,0),(3,.5,0)))
        self.assertFalse(w.corridor_clear((0,.5,0),(3,1.5,0)))

    def test_follower_does_not_stop_at_each_cell(self):
        from types import SimpleNamespace
        from luanti_course.skills import follow_path
        w=world(10);position=[0,.5,0];commands=[];velocity=[0,0,0]
        def submit(op,**args):
            commands.append((op,args))
            self.assertEqual(op,'steer')
            self.assertEqual(args['duration_ms'],400)
            h=math.radians(args['heading']);v=args['speed']*4
            velocity[:]=[-math.sin(h)*v,0,math.cos(h)*v]
            position[0]+=velocity[0]*.05;position[2]+=velocity[2]*.05
        def read(radius=0):
            return SimpleNamespace(position=tuple(position),raw={'velocity':tuple(velocity)})
        ctx=SimpleNamespace(world=w,read=read,last=read(),game=SimpleNamespace(_submit=submit),sleep=lambda _:None)
        ok,_=follow_path(ctx,[(i,1,0) for i in range(7)],(6,.5,0))
        self.assertTrue(ok);self.assertGreater(len(commands),10)
        self.assertTrue(all(c[1]['speed']>0 for c in commands))
        self.assertLess(abs(position[0]-6),.3)

    def test_rounded_corner_advances_without_crossing_endpoint_plane(self):
        from types import SimpleNamespace
        from luanti_course.skills import follow_path
        w=world(10);position=[-6,.5,-5];velocity=[0,0,0];commands=[]
        path=[(-6,1,z) for z in range(-5,-9,-1)]+[(x,1,-8) for x in range(-5,1)]
        def submit(op,**args):
            commands.append(args)
            self.assertLess(len(commands),160,'rounded corner oscillation')
            h=math.radians(args['heading']);v=args['speed']*4
            velocity[:]=[-math.sin(h)*v,0,math.cos(h)*v]
            position[0]+=velocity[0]*.05;position[2]+=velocity[2]*.05
        def read(radius=0):return SimpleNamespace(position=tuple(position),raw={'velocity':tuple(velocity)})
        ctx=SimpleNamespace(world=w,read=read,last=read(),game=SimpleNamespace(_submit=submit),sleep=lambda _:None)
        self.assertTrue(follow_path(ctx,path,(0,.5,-8))[0])

class RecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.book=RecipeBook.voxelibre()
    def test_catalog_version_and_scale(self):
        self.assertEqual(self.book.source['commit'],'4e68979e942a53e0b4c4e657bee3e5d3cb971cca')
        self.assertGreater(sum(map(len,self.book.recipes.values())),1000)
    def test_empty_to_wood_pickaxe_dependency_chain(self):
        p=self.book.plan('wooden_pickaxe',1,{},nearby=['mcl_core:tree'])
        self.assertEqual(sum(s.count for s in p if s.kind=='collect' and s.item=='mcl_core:tree'),3)
        self.assertEqual(sum(s.kind=='workbench' for s in p),1)
        self.assertEqual(p[-1].item,'mcl_tools:pick_wood')
    def test_existing_table_and_materials(self):
        p=self.book.plan('mcl_tools:pick_wood',1,{'mcl_core:wood':3,'mcl_core:stick':2},gather=False,has_table=True)
        self.assertEqual(len(p),1)
    def test_group_uses_existing_birch(self):
        p=self.book.plan(TABLE,1,{'mcl_core:birchwood':4},gather=False)
        self.assertEqual(p[-1].ingredients,('mcl_core:birchwood',)*4)
    def test_visible_spruce_over_default_oak(self):
        p=self.book.plan('mcl_tools:pick_wood',1,{},nearby=['mcl_core:sprucetree'])
        self.assertTrue(all(s.item=='mcl_core:sprucetree' for s in p if s.kind=='collect'))
    def test_output_counts_and_leftovers(self):
        p=self.book.plan('mcl_core:stick',5,{'mcl_core:wood':4},gather=False)
        self.assertEqual(sum(s.count for s in p if s.kind=='craft'),8)
    def test_no_gather_missing_materials(self):
        with self.assertRaises(PlanningError):self.book.plan('mcl_tools:pick_wood',1,{},gather=False)
    def test_unknown_recipe(self):
        with self.assertRaises(PlanningError):self.book.plan('unknown:thing',1,{})
    def test_input_inventory_not_mutated(self):
        inv={'mcl_core:wood':4};self.book.plan(TABLE,1,inv,gather=False)
        self.assertEqual(inv,{'mcl_core:wood':4})
    def test_harvest_tool_tiers(self):
        self.assertFalse(self.book.harvestable('mcl_core:stone',''))
        self.assertTrue(self.book.harvestable('mcl_core:stone','mcl_tools:pick_wood'))
        self.assertFalse(self.book.harvestable('mcl_core:stone_with_iron','mcl_tools:pick_wood'))
        self.assertTrue(self.book.harvestable('mcl_core:tree',''))
    def test_recipe_cycle_is_bounded(self):
        b=RecipeBook({'items':{'a':{},'b':{}},'recipes':[{'output':'a','count':1,'width':1,'items':['b']},{'output':'b','count':1,'width':1,'items':['a']}]})
        with self.assertRaises(PlanningError):b.plan('a',1,{})
    def test_procurement_scout_includes_recipe_alternatives(self):
        nodes=self.book.procurement_nodes('wooden_pickaxe')
        self.assertIn('mcl_core:tree',nodes)
        self.assertIn('mcl_core:sprucetree',nodes)
        self.assertIn('mcl_bamboo:bamboo',nodes)

    def test_plan_limit(self):
        with self.assertRaises(PlanningError):self.book.plan('mcl_core:stick',256,{},nearby=['mcl_core:tree'],max_steps=3)

class SkillContractTests(unittest.TestCase):
    def test_observation_directives_do_not_hide_fields(self):
        import re
        source=(Path(__file__).resolve().parents[2]/'engine/src/game_course.inc').read_text()
        self.assertFalse(re.search(r'^#endif[ \t]+[^/\n\s]',source,re.M))
        self.assertIn('r["focused"] = device->isWindowFocused();',source)
    def fake_game(self):
        from types import SimpleNamespace
        state=SimpleNamespace(control='agent',control_epoch=1,dead=False,hp=20,position=(0,.5,0))
        return SimpleNamespace(_action_lock=ActionLock(),_epoch=1,_skill_depth=0,
            _cancel=threading.Event(),_closed=False,recipe_book=object(),
            observe=lambda radius:state,_submit=lambda op:None)
    def test_resource_coordinates_not_overwritten_by_player(self):
        from luanti_course.skills import run
        result=run(self.fake_game(),'find_resource',lambda c:c.details.update(position=(4,1,3)),timeout=1)
        self.assertEqual(result.details['position'],(4,1,3))
        self.assertEqual(result.details['player_position'],(0,.5,0))
    def test_initial_connection_error_is_structured(self):
        from luanti_course.skills import run
        from luanti_course.errors import ConnectionError
        fake=self.fake_game()
        def disconnected(radius):raise ConnectionError('closed')
        fake.observe=disconnected
        result=run(fake,'navigate_to',lambda c:None,timeout=1)
        self.assertEqual(result.status,'blocked')
        self.assertEqual(result.reason,'connection_error')
        self.assertFalse(fake._action_lock.locked())
    def test_result_is_not_a_submission(self):
        r=SkillResult('collect','blocked','pickup_unconfirmed',{'collected':0})
        self.assertFalse(r.ok);self.assertEqual(r.to_dict()['status'],'blocked')
    def test_reentrant_lock_excludes_other_threads(self):
        lock=ActionLock();self.assertTrue(lock.acquire(False));self.assertTrue(lock.acquire(False))
        got=[]
        t=threading.Thread(target=lambda:got.append(lock.acquire(False)));t.start();t.join()
        self.assertEqual(got,[False]);lock.release();self.assertTrue(lock.locked());lock.release();self.assertFalse(lock.locked())
    def test_bounds(self):
        for x in (0,-1,True,float('inf'),float('nan')):
            with self.assertRaises(ValueError):positive(x,'test',128)
    def test_full_inventory_is_explicit(self):
        from types import SimpleNamespace
        from luanti_course import Item, InventoryList
        from luanti_course.skills import main_space, Failure
        state=SimpleNamespace(inventory={'main':InventoryList(2,(Item('stone',99),Item('stone',99)))})
        context=SimpleNamespace(read=lambda:state,book=SimpleNamespace(items={'wood':{'stack_max':64}}))
        with self.assertRaises(Failure) as raised:main_space(context,'wood',1)
        self.assertEqual(raised.exception.reason,'inventory_full')
    def test_skill_without_control_is_read_only(self):
        from types import SimpleNamespace
        from luanti_course.skills import run
        fake=SimpleNamespace(_action_lock=ActionLock(),_epoch=None,_skill_depth=0)
        result=run(fake,'collect',lambda c:self.fail('Should not execute'),timeout=1)
        self.assertEqual(result.reason,'control_required')
        self.assertFalse(fake._action_lock.locked())

    def test_methods_present(self):
        for name in ('navigate_to','find_resource','collect','craft'):
            self.assertTrue(callable(getattr(Game,name,None)),name)

if __name__=='__main__':unittest.main()
