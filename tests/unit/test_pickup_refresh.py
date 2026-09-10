import sys,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'sdk/src'))
from luanti_course.skills import pickup,Failure,keep_partial_pickup
from luanti_course import RecipeBook
from test_survival import state
class Captured(Exception):pass
class PickupRefreshTests(unittest.TestCase):
    def test_partial_inventory_progress_continues_recovery(self):
        rows=[];c=NS(recover=True,operation='collect',details={},log=lambda *a,**k:rows.append((a,k)))
        self.assertTrue(keep_partial_pickup(c,0,0,3,2,Failure('pickup_unconfirmed')))
        self.assertEqual(c.details['collected'],2);self.assertEqual(rows[0][1]['remaining'],1)
        c.recover=False
        self.assertFalse(keep_partial_pickup(c,0,0,3,2,Failure('pickup_unconfirmed')))
    def callback(self):
        book=RecipeBook.voxelibre();item={'id':10,'item':'mcl_core:tree 1','position':(0,1,0)}
        observed=state(item_entities=[item]);w=NS(nodes={(0,1,0):None},standable=lambda p:True,start=lambda p:(0,1,0),path=lambda *a,**k:([(0,1,0)],{}))
        c=NS(read=lambda *a:observed,book=book,ignored_drops=set(),world=w,blocked=set(),within=lambda p:True,log=lambda *a,**k:None)
        callbacks=[]
        def navigate(*a,**kw):callbacks.append(kw['until']);raise Captured()
        with patch('luanti_course.skills.navigate',navigate),self.assertRaises(Captured):pickup(c,'mcl_core:tree',1)
        return callbacks[0],item
    def test_disappeared_target_at_recent_landing_ends_leg(self):
        cb,item=self.callback();self.assertTrue(cb(state(position=(0,.5,0),item_entities=[])))
    def test_replacement_id_does_not_abandon_nearby_merged_stack(self):
        cb,item=self.callback();self.assertFalse(cb(state(position=(0,0,0),item_entities=[dict(item,id=11)])))
    def test_visible_target_without_inventory_is_not_finished(self):
        cb,item=self.callback();self.assertFalse(cb(state(item_entities=[item])))
    def test_replication_gap_does_not_abandon_recent_safe_approach(self):
        cb,item=self.callback();self.assertFalse(cb(state(position=(2.5,.5,0),item_entities=[])))
    def test_disappeared_distant_target_stops_stale_chase(self):
        cb,item=self.callback();self.assertTrue(cb(state(position=(4,.5,0),item_entities=[])))
    def test_inventory_remains_the_success_condition(self):
        cb,item=self.callback();s=state(item_entities=[item],inventory={'main':{'width':9,'items':[{'name':'mcl_core:tree','count':1}]}});self.assertTrue(cb(s))
    def test_pickup_approaches_entity_inside_cell_not_loose_cell_centre(self):
        book=RecipeBook.voxelibre();item={'id':10,'item':'mcl_core:tree 1','position':(.34,1,.31)}
        observed=state(item_entities=[item]);w=NS(nodes={(0,1,0):None},standable=lambda p:True,
            start=lambda p:(0,1,0),path=lambda *a,**k:([(0,1,0)],{}))
        c=NS(read=lambda *a:observed,book=book,ignored_drops=set(),world=w,blocked=set(),
             within=lambda p:True,log=lambda *a,**k:None)
        called={}
        def navigate(ctx,target,**kw):called.update(target=target,kw=kw);raise Captured()
        with patch('luanti_course.skills.navigate',navigate),self.assertRaises(Captured):pickup(c,'mcl_core:tree',1)
        self.assertEqual(called['target'],(.34,.5,.31))
        self.assertEqual(called['kw']['tolerance'],.05)
    def test_removed_node_fallback_uses_normal_arrival_radius(self):
        book=RecipeBook.voxelibre();observed=state(item_entities=[])
        w=NS(nodes={(0,1,0):None},standable=lambda p:True,start=lambda p:(0,1,0),
             path=lambda *a,**k:([(0,1,0)],{}))
        c=NS(read=lambda *a:observed,book=book,ignored_drops=set(),world=w,blocked=set(),
             within=lambda p:True,log=lambda *a,**k:None)
        called={}
        def navigate(ctx,target,**kw):called.update(target=target,kw=kw);raise Captured()
        with patch('luanti_course.skills.navigate',navigate),self.assertRaises(Captured):
            pickup(c,'mcl_core:tree',1,[(0,1,0)])
        self.assertEqual(called['kw']['tolerance'],.45)
    def test_floating_item_ranks_player_collection_height_not_surface_feet(self):
        book=RecipeBook.voxelibre();item={'id':10,'item':'mcl_core:tree 1','position':(0,100.4,0)}
        observed=state(position=(0,99.5,0),item_entities=[item])
        w=NS(nodes={(0,100,0):None,(0,101,0):None},standable=lambda p:True,start=lambda p:(0,100,0),
             path=lambda start,goal,**k:([start,next(p for p in ((0,100,0),(0,101,0)) if goal(p))],{}))
        c=NS(read=lambda *a:observed,book=book,ignored_drops=set(),world=w,blocked=set(),
             within=lambda p:True,log=lambda *a,**k:None)
        called={}
        def navigate(ctx,target,**kw):called.update(target=target,kw=kw);raise Captured()
        with patch('luanti_course.skills.navigate',navigate),self.assertRaises(Captured):pickup(c,'mcl_core:tree',1)
        self.assertEqual(called['target'][1],99.5)

if __name__=='__main__':unittest.main()
