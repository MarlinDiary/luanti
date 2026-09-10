from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

@dataclass(frozen=True)
class Item:
    name: str
    count: int
    wear: int = 0
    stack_key: str = ""

@dataclass(frozen=True)
class InventoryList:
    width: int
    items: Tuple[Item, ...]
    @property
    def size(self): return len(self.items)
    def count(self, name): return sum(i.count for i in self.items if i.name == name)
    def find(self, name): return next((n for n, i in enumerate(self.items) if i.name == name and i.count), None)
    def empty_slot(self): return next((n for n, i in enumerate(self.items) if not i.count), None)

@dataclass(frozen=True)
class Snapshot:
    position: Tuple[float, float, float]
    eye: Tuple[float, float, float]
    yaw: float
    pitch: float
    hp: int
    dead: bool
    control: str
    control_epoch: int
    frame: int
    inventory_revision: int
    inventory: Dict[str, InventoryList]
    raw: Dict[str, Any]
    @property
    def entities(self):
        from .entities import Entity
        return tuple(Entity.from_dict(e,self.raw.get('observation_source','')) for e in self.raw.get('entities',()))
    @property
    def hunger(self):
        from .entities import hunger_from_hud
        return hunger_from_hud(self.raw)
    @property
    def burning(self):
        """Whether the visible VoxeLibre burning overlay is currently shown.

        Unknown/custom overlays stay false; this is deliberately not inferred
        from damage, nearby fire, particles, or server-only state.
        """
        return any(isinstance(x,str) and x.startswith('mcl_burning_hud_flame_animated.png')
                   for x in self.raw.get('hud_images',()))
    @property
    def pointed_entity(self):
        e=self.raw.get('pointed_entity')
        return (e['id'],e['instance']) if e else None
    @property
    def item_entities(self):
        return tuple(self.raw.get("item_entities", ()))
    @property
    def pointed_node(self):
        value=self.raw.get('pointed_node')
        return tuple(value) if value is not None else None
    @property
    def form(self): return self.raw['form']
    @classmethod
    def from_dict(cls, value):
        inv={name:InventoryList(info['width'],tuple(Item(i['name'],i['count'],i.get('wear',0),i.get('stack_key','')) for i in info['items'])) for name,info in value['inventory'].items()}
        return cls(tuple(value['position']),tuple(value['eye']),value['yaw'],value['pitch'],value['hp'],value['dead'],value['control'],value['control_epoch'],value['frame'],value['inventory_revision'],inv,value)

@dataclass(frozen=True)
class Submission:
    """The client accepted a request. This does not assert server-side completion."""
    request_id: int
    frame: int
    operation: str
    status: str = 'submitted'
