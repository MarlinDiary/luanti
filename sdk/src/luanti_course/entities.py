"""Replicated entity observations, with explicit instance identity and unknowns."""
from dataclasses import dataclass
from typing import Tuple
from .navigation import distance

# VoxeLibre adapter: identity comes from the replicated Lua entity name, not a
# texture guess. Neutral animals/players and unfamiliar mods remain unclassified.
HOSTILES = frozenset('''skeleton stray wither_skeleton zombie baby_zombie husk baby_husk
zombie_villager spider cave_spider stalker stalker_overloaded creeper creeper_charged silverfish endermite witch
pillager vindicator evoker vex blaze ghast slime magma_cube zoglin hoglin
wither guardian elder_guardian shulker'''.split())

PROJECTILES = frozenset(('mcl_bows:arrow_entity','mcl_throwing:snowball_entity',
    'mcl_throwing:egg_entity','mcl_fireballs:fireball','mcl_fireballs:small_fireball'))

@dataclass(frozen=True)
class Entity:
    id: int
    instance: int
    name: str
    position: Tuple[float, float, float]
    aim: Tuple[float, float, float]
    velocity: Tuple[float, float, float]
    is_player: bool = False
    pointable: bool = False
    engine_immortal: bool = False
    source: str = ""

    @property
    def ref(self): return (self.id, self.instance)
    @property
    def hostile(self):
        return not self.is_player and self.name.startswith('mobs_mc:') and self.name.split(':',1)[1] in HOSTILES
    @property
    def projectile(self):
        return not self.is_player and (self.name in PROJECTILES or self.name.endswith(('_arrow_entity',':arrow_entity')))
    @property
    def explosive(self):
        # Current VoxeLibre names the creeper-equivalent mob "stalker" while
        # older worlds/mod compatibility may still replicate creeper names.
        return not self.is_player and self.name in ('mobs_mc:stalker','mobs_mc:stalker_overloaded',
                                                     'mobs_mc:creeper','mobs_mc:creeper_charged')
    @classmethod
    def from_dict(cls, row, source=""):
        return cls(row['id'],row['instance'],row['name'],tuple(row['position']),tuple(row['aim']),
                   tuple(row['velocity']),row['is_player'],row['pointable'],row['immortal'],source)

def target_ref(value):
    if not isinstance(value, Entity):raise ValueError('target must be an Entity from observe().entities')
    if value.is_player:raise ValueError('player targets are excluded')
    if not value.pointable:raise ValueError('target is not attackable')
    return value.ref

def hostiles(state, radius=16):
    return tuple(sorted((e for e in state.entities if e.hostile and distance(e.position,state.position)<=radius),
                        key=lambda e:distance(e.position,state.position)))

def hunger_from_hud(raw):
    """Read the pinned VoxeLibre proportional 20-part HUD; hidden/changed is None."""
    bars=[b for b in raw.get('hud_statbars',()) if b.get('texture')=='hbhunger_icon.png'
          and b.get('background')=='hbhunger_bgicon.png' and b.get('max')==20
          and type(b.get('number')) is int and 0<=b['number']<=20]
    return bars[0]['number'] if len(bars)==1 else None
