import sys, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'sdk/src'))
sys.path.insert(0,str(ROOT/'tests/unit'))

from luanti_course import Entity, RecipeBook, SurvivalConfig
from luanti_course.combat import (incoming_projectiles, explosive_threats,
    count_ammo, ranged_attack, block_with_shield)
from luanti_course.supervisor import decide
from luanti_course.skills import Failure
from test_survival import state, entity


def arrow(position=(0,1,5), velocity=(0,0,-8)):
    return Entity(20,30,'mcl_bows:arrow_entity',position,position,velocity,
                  pointable=False)


class ThreatClassificationTests(unittest.TestCase):
    def test_burning_is_visible_hud_state(self):
        s=state(hud_images=['mcl_burning_hud_flame_animated.png^[opacity:180'])
        self.assertTrue(s.burning)
        self.assertEqual(decide(s,SurvivalConfig(),RecipeBook.voxelibre())['action'],'extinguish_fire')

    def test_texture_collision_does_not_guess_burning(self):
        self.assertFalse(state(hud_images=['custom:flame.png']).burning)

    def test_incoming_arrow_uses_trajectory_not_name_alone(self):
        s=state(entities=(arrow(),))
        self.assertEqual(incoming_projectiles(s)[0].ref,(20,30))
        self.assertFalse(incoming_projectiles(state(entities=(arrow(velocity=(0,0,8)),))))

    def test_near_creeper_is_explosive_threat(self):
        creeper=Entity(2,10,'mobs_mc:creeper',(0,1,4),(0,2,4),(0,0,0),pointable=True)
        self.assertEqual(explosive_threats(state(entities=(creeper,)))[0].ref,creeper.ref)

    def test_voxelibre_stalker_is_creeper_equivalent(self):
        stalker=Entity(3,11,'mobs_mc:stalker',(0,1,4),(0,2,4),(0,0,0),pointable=True)
        self.assertTrue(stalker.explosive);self.assertTrue(stalker.hostile)

    def test_projectile_precedes_food_and_ordinary_enemy(self):
        s=state(hunger=2,entities=(entity(pointable=True),arrow()))
        self.assertEqual(decide(s,SurvivalConfig(enemies='defend'),RecipeBook.voxelibre())['action'],'avoid_projectile')


class RangedTests(unittest.TestCase):
    def test_ammo_groups_are_catalog_driven(self):
        s=state(inventory={'main':{'width':9,'items':[{'name':'mcl_bows:arrow','count':3}]}})
        self.assertEqual(count_ammo(s,RecipeBook.voxelibre()),3)

    def test_no_bow_is_bounded(self):
        c=NS(read=lambda *a:state(),book=RecipeBook.voxelibre(),details={})
        with self.assertRaises(Failure) as caught:ranged_attack(c,entity(pointable=True))
        self.assertEqual(caught.exception.reason,'bow_not_held')

    def test_no_shield_is_bounded(self):
        c=NS(read=lambda *a:state(),book=RecipeBook.voxelibre(),details={})
        with self.assertRaises(Failure) as caught:block_with_shield(c,entity(pointable=True))
        self.assertEqual(caught.exception.reason,'shield_not_held')

    def test_shield_release_wait_is_part_of_skill(self):
        shield={'name':'mcl_shields:shield','count':1}
        s=state(inventory={'main':{'width':9,'items':[shield]}},wield=0,hud_images=['mcl_shield_hud.png'])
        clear=state(inventory={'main':{'width':9,'items':[shield]}},wield=0,hud_images=[])
        c=NS(read=lambda *a:s,book=RecipeBook.voxelibre(),details={},deadline=float('inf'),
             game=NS(capabilities={'hud_images'},_submit=lambda *a,**k:None),
             sleep=lambda t:None,stop_input=lambda:None,log=lambda *a,**k:None,
             wait=lambda predicate,**kw:clear if predicate(clear) else None)
        with patch('luanti_course.combat.face'),patch('luanti_course.combat.wield_slot'):
            block_with_shield(c,entity(pointable=True),duration=.01)


if __name__=='__main__':unittest.main()
