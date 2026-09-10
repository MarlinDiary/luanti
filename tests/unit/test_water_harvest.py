"""Water approaches must keep their support, height and opt-in boundary."""
import sys,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/src'))
from luanti_course.navigation import Node,Traversal
from luanti_course.skills import find_resource,follow_path
from test_skills import world

class Captured(Exception):pass
class WaterHarvestTests(unittest.TestCase):
    def shallow(self):
        w=world();w.traversal=Traversal(allow_swim=True)
        for x in range(-2,3):
            for z in range(-2,3):w.nodes[x,1,z]=Node('water',False,liquid=True,drowning=1)
        return w
    def test_shallow_ground_pose(self):
        w=self.shallow();self.assertTrue(w.standable((0,1,0)));self.assertEqual(w.point((0,1,0)),(0,.5,0))
        self.assertEqual(w.start((0,.5,0)),(0,1,0))
    def test_shallow_ground_corridor_and_path(self):
        w=self.shallow();self.assertTrue(w.corridor_clear((0,.5,0),(1,.5,0)))
        self.assertIsNotNone(w.path((0,1,0),lambda p:p==(1,1,0))[0])
    def test_shallow_water_is_opt_in(self):
        w=self.shallow();w.traversal=Traversal();self.assertFalse(w.standable((0,1,0)))
    def test_shallow_water_requires_clear_head_and_known_floor(self):
        for field,node in [((0,2,0),Node('water',False,liquid=True,drowning=1)),((0,2,0),Node('roof',True)),((0,0,0),None),((0,1,0),Node('lava',False,liquid=True,damage=4))]:
            w=self.shallow()
            if node is None:w.nodes.pop(field)
            else:w.nodes[field]=node
            self.assertFalse(w.standable((0,1,0)),field)
    def test_harvest_rejects_target_support_but_other_interaction_keeps_it(self):
        w=world();w.nodes[0,1,0]=Node('tree',True)
        self.assertTrue(w.approach((0,2,0),(0,1,0)))
        self.assertFalse(w.harvest_approach((0,2,0),(0,1,0)))
        self.assertTrue(w.harvest_approach((1,1,0),(0,1,0)))
    def test_harvest_rejects_partial_height_target_support(self):
        w=world();w.nodes[0,1,0]=Node('slab',True,full_cube=False,boxes=((-.5,-.5,-.5,.5,0,.5),))
        self.assertTrue(w.supported_by((0,1,0),(0,1,0)))
        self.assertFalse(w.harvest_approach((0,1.5,0),(0,1,0)))
    def test_underfoot_resource_can_be_found_from_another_stance(self):
        w=world();w.nodes[0,1,0]=Node('tree',True)
        book=NS(resources=lambda _:set(['tree']),candidates=lambda _:[],items={})
        c=NS(read=lambda *a:NS(position=(0,1.5,0)),world=w,book=book,blocked=set(),within=lambda _:True,log=lambda *a,**k:None,visited=Counter(),radius=8)
        with patch('luanti_course.skills.navigate',side_effect=AssertionError('must not explore away from known reachable tree')):
            self.assertEqual(find_resource(c,'tree',for_dig=True),(0,1,0))
    def test_batch_station_avoids_resources_without_repeated_full_search(self):
        from luanti_course.skills import collect
        w=world(6);w.traversal=Traversal(allow_swim=True)
        cluster=[(x,1,3) for x in (-1,0,1)]
        for p in list(w.nodes):
            if p[1]==1:w.nodes[p]=Node('water',False,liquid=True,drowning=1)
        for p in cluster:w.nodes[p]=Node('tree',True)
        book=NS(resources=lambda _:set(['tree']),candidates=lambda _:[],items={})
        ctx=NS(read=lambda *a:NS(position=(0,.5,0)),world=w,book=book,blocked=set(),within=lambda _:True,
               operation='collect',details={},log=lambda *a,**k:None)
        destinations=[]
        def move(c,target,**kw):destinations.append(target);raise Captured()
        with patch('luanti_course.skills.find_resource',return_value=cluster[0]),patch('luanti_course.skills.count_items',return_value=0),patch('luanti_course.skills.drop_candidates',return_value=[]),patch('luanti_course.skills.navigate',move),patch.object(w,'path',wraps=w.path) as search,self.assertRaises(Captured):
            collect(ctx,'tree',3)
        self.assertEqual(search.call_count,1,'do not evaluate every station with a separate A* while the actor sinks')
        self.assertEqual(destinations[0][1],.5)
        self.assertFalse(any(w.supported_by(destinations[0],p) for p in cluster))

    def test_dig_navigation_goal_survives_path_search(self):
        from luanti_course.skills import navigate
        w=world();w.nodes[0,1,0]=Node('tree',True)
        state=NS(position=(0,1.5,0),raw={},yaw=0)
        ctx=NS(world=w,read=lambda *a:state,game=NS(capabilities=('steer',)),blocked=set(),within=lambda _:True,
               stop_input=lambda:None,sleep=lambda _:None,log=lambda *a,**k:None)
        with patch('luanti_course.skills.follow_path',side_effect=Captured),self.assertRaises(Captured):
            navigate(ctx,(0,1,0),approach=True,for_dig=True)

    def test_surface_recovery_keeps_same_cell_horizontal_destination(self):
        w=world();w.traversal=Traversal(allow_swim=True)
        for x in range(-2,3):
            for z in range(-2,3):
                for y in range(1,7):w.nodes[x,y,z]=Node('water',False,liquid=True,drowning=1) if y<=3 else Node('air',False)
        state=NS(position=(0,.5,0),yaw=0,raw={'in_liquid':True,'velocity':(0,0,0),'touching_ground':False})
        calls=[]
        def submit(op,**kw):
            calls.append(kw)
            if len(calls)==1:state.position=(0,3.05,0)
            else:raise Captured()
        c=NS(world=w,read=lambda *a:state,game=NS(capabilities=('swim_height',),_submit=submit),sleep=lambda _:None,within=lambda _:True)
        with self.assertRaises(Captured):follow_path(c,[(0,4,0)],(.4,3.05,0))
        self.assertEqual(calls[0]['speed'],0)
        self.assertGreater(calls[1]['speed'],0,'the ascent must not overwrite the requested horizontal destination')

    def test_surface_only_route_recovers_height_before_bankward_motion(self):
        w=world();w.traversal=Traversal(allow_swim=True)
        for y in (1,2,3):w.nodes[0,y,0]=Node('water',False,liquid=True,drowning=1)
        for x in range(-2,3):
            for z in range(-2,3):
                for y in (4,5,6):w.nodes[x,y,z]=Node('air',False)
        w.nodes[1,3,0]=Node('bank',True)
        state=NS(position=(0,.5,0),yaw=0,raw={'in_liquid':True,'velocity':(0,0,0),'touching_ground':True})
        calls=[]
        def submit(op,**kw):calls.append(kw);raise Captured()
        c=NS(world=w,read=lambda *a:state,game=NS(capabilities=('swim_height',),_submit=submit),sleep=lambda _:None,within=lambda _:True)
        with self.assertRaises(Captured):follow_path(c,[(0,4,0),(1,4,0)],(1,3.5,0))
        self.assertEqual(calls[0]['speed'],0,'do not steer sideways into the bank while still below its collision floor')
        self.assertAlmostEqual(calls[0]['swim_y'],3.05)

if __name__=='__main__':unittest.main()
