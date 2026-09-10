"""Conservative, bounded A* over observed voxels; never treats unknown as air."""
import heapq
import math
import time
from dataclasses import dataclass, field
from functools import wraps


def cached_geometry(fn):
    @wraps(fn)
    def call(self,*args,**kwargs):
        cache=getattr(self,'_planning_cache',None)
        if cache is None:return fn(self,*args,**kwargs)
        def key(x):return tuple(key(v) for v in x) if isinstance(x,(list,tuple)) else frozenset(x) if isinstance(x,set) else x
        k=(fn.__name__,tuple(key(a) for a in args),tuple((n,key(v)) for n,v in sorted(kwargs.items())))
        if k not in cache:
            value=fn(self,*args,**kwargs)
            if len(cache)<150000:cache[k]=value.copy() if isinstance(value,(list,set,dict)) else value
            return value
        value=cache[k]
        return value.copy() if isinstance(value,(list,set,dict)) else value
    return call


def cell(position):
    return tuple(math.floor(v + .5 + (1e-4 if i == 1 else 0)) for i, v in enumerate(position))


def feet(node):
    return (node[0], node[1] - .5, node[2])


def distance(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


@dataclass(frozen=True)
class Node:
    name: str
    walkable: bool
    liquid: bool = False
    damage: int = 0
    drowning: int = 0
    full_cube: bool = True
    buildable: bool = False
    climbable: bool = False
    boxes: tuple = None
    groups: dict = field(default_factory=dict)

    @property
    def collision_boxes(self):
        if not self.walkable: return ()
        if self.boxes is not None: return self.boxes
        return ((-.5,-.5,-.5,.5,.5,.5),)

    @property
    def harmless(self):
        return not (self.liquid or self.damage or self.drowning)


@dataclass(frozen=True)
class Traversal:
    allow_swim: bool = False
    allow_climb: bool = True
    allow_jump_gaps: bool = False
    allow_dive: bool = False
    allow_interact: bool = True
    allow_dig: bool = False
    build_with: str = None
    max_drop: float = 1.0
    max_gap: int = 2
    edit_budget: int = 32

    def __post_init__(self):
        if any(not isinstance(v,bool) for v in (self.allow_swim,self.allow_climb,self.allow_jump_gaps,self.allow_dive,self.allow_interact,self.allow_dig)):
            raise ValueError('traversal flags must be boolean')
        if self.allow_dive and not self.allow_swim:raise ValueError('allow_dive requires allow_swim')
        if self.build_with is not None and (not isinstance(self.build_with,str) or not self.build_with):raise ValueError('build_with must name a held block')
        if isinstance(self.max_drop,bool) or not isinstance(self.max_drop,(int,float)) or not math.isfinite(self.max_drop) or not 0<=self.max_drop<=3:raise ValueError('max_drop must be 0..3')
        if type(self.max_gap) is not int or not 1<=self.max_gap<=3:raise ValueError('max_gap must be 1..3')
        if type(self.edit_budget) is not int or not 0<=self.edit_budget<=128:raise ValueError('edit_budget must be 0..128')


class World:
    def __init__(self, traversal=None):
        self.traversal = traversal or Traversal()
        self.nodes = {}
        self.observed = {}
        self.version = 0
        self.edge_actions = {}
        self.unusable = set()
        self.radius = .31
        self.height = 1.8
        self.physics = dict(walk_speed=4.,jump_speed=6.5,gravity=19.62,step_height=.6)

    def update(self, snapshot):
        definitions = snapshot.raw.get('node_defs')
        if not definitions:
            raise ValueError('Node geometry is missing or restricted; use Course client 0.2 with permitted node observations.')
        self.version += 1
        self.edge_actions.clear()
        self.physics.update(snapshot.raw.get('physics',{}))
        bounds=self.physics.get('collision_box')
        if bounds and len(bounds)==6 and bounds[4]>bounds[1]:
            self.radius=max(abs(bounds[i]) for i in (0,2,3,5))+.02
            self.height=bounds[4] # Luanti position is the object origin.

        for raw in snapshot.raw['nodes']:
            p = tuple(raw['position'])
            self.observed[p] = time.monotonic()
            d = definitions.get(raw.get('name'))
            if not raw.get('known') or not d:
                self.nodes.pop(p, None)
                continue
            if p in self.nodes and self.nodes[p].name!=raw['name']:self.unusable.discard(p)
            self.nodes[p] = Node(raw['name'], d['walkable'], d['liquid'],
                                 d['damage_per_second'], d['drowning'],
                                 d['full_cube'], d['buildable_to'], d['climbable'],
                                 tuple(tuple(b) for b in raw['collision_boxes']) if 'collision_boxes' in raw else None,d.get('groups',{}))
        # Bound retained observations; keep the local map nearest the player.
        if len(self.nodes) > 60000:
            keep = sorted(self.nodes, key=lambda p: distance(p, snapshot.position))[:45000]
            self.nodes = {p:self.nodes[p] for p in keep}

    def clear(self, p):
        n = self.nodes.get(p)
        return n is not None and n.harmless and ((not n.walkable and not n.climbable) or self.ladder(p))

    def ladder(self, p):
        n=self.nodes.get(p)
        return self.traversal.allow_climb and n is not None and n.climbable and (not n.walkable or not n.full_cube) and n.harmless

    @cached_geometry
    def surface_water(self, p):
        floor=self.nodes.get((p[0],p[1]-1,p[2]))
        return (self.traversal.allow_swim and floor is not None and floor.liquid
                and not floor.damage and self.clear(p) and self.clear((p[0],p[1]+1,p[2])))

    @cached_geometry
    def wading(self, p):
        """Known, supported shallow water with clear breathing space."""
        n=self.nodes.get(p)
        return (self.traversal.allow_swim and n is not None and n.liquid and not n.damage
                and self.clear((p[0],p[1]+1,p[2])) and self.supported(feet(p))
                and self.body_clear(feet(p),water=True))

    @cached_geometry
    def swimmable(self, p):
        n=self.nodes.get(p)
        return (self.traversal.allow_dive and n is not None and n.liquid and not n.damage
                and self.body_clear(feet(p),water=True))

    @cached_geometry
    def body_clear(self, position, radius=None, height=None, water=False, ignored=frozenset()):
        """Swept AABB against engine-transformed node-instance collision boxes.

        Missing occupied cells block. One-cell padding catches fences/boxes
        extending above or outside their owner node, without treating that
        non-occupied padding itself as required free space.
        """
        radius=self.radius if radius is None else radius
        height=self.height if height is None else height
        x,y,z=position
        lo=(x-radius,y+.001,z-radius);hi=(x+radius,y+height,z+radius)
        first=cell(lo);last=cell(tuple(v-.001 for v in hi))
        for nx in range(first[0]-1,last[0]+2):
            for ny in range(first[1]-1,last[1]+2):
                for nz in range(first[2]-1,last[2]+2):
                    p=(nx,ny,nz)
                    if p in ignored:continue
                    n=self.nodes.get(p)
                    occupied=all(first[i]<=p[i]<=last[i] for i in range(3))
                    if n is None:
                        if occupied:return False
                        continue
                    if occupied and ((not n.harmless and not (water and n.liquid and not n.damage)) or (n.climbable and not self.traversal.allow_climb)):
                        return False
                    for box in n.collision_boxes:
                        if all(lo[i]<p[i]+box[i+3]-.0001 and hi[i]>p[i]+box[i]+.0001 for i in range(3)):
                            return False
        return True

    @cached_geometry
    def support_heights(self, x, z, near_y):
        heights=set()
        for ny in range(math.floor(near_y)-math.ceil(self.traversal.max_drop)-2,math.floor(near_y)+2):
            n=self.nodes.get((x,ny,z))
            if n is None or not n.harmless or not n.walkable or (n.boxes is None and not n.full_cube):continue
            for b in n.collision_boxes:
                # Rotated node boxes can put a mathematical centre edge at
                # -6e-17 instead of zero. Match the collision/support epsilon;
                # otherwise two stair orientations lose their entire top pose.
                if b[0]<=1e-6 and b[3]>=-1e-6 and b[2]<=1e-6 and b[5]>=-1e-6:
                    heights.add(round(ny+b[4]+.5,6))
        return heights

    @cached_geometry
    def standable(self, p):
        x,y,z=p
        # Ladder and surface-water topology remains discrete; other ground
        # surfaces use their actual (possibly fractional) support height.
        if y==int(y) and (self.ladder(p) or self.surface_water(p)):
            return self.clear(p) and self.clear((x,y+1,z))
        if self.swimmable(p) or self.wading(p):return True
        return y in self.support_heights(x,z,y) and self.body_clear(self.point(p))

    @cached_geometry
    def poses(self, x, z, near_y):
        heights=self.support_heights(x,z,near_y)
        for y in range(math.floor(near_y)-1,math.floor(near_y)+2):
            if self.ladder((x,y,z)) or self.surface_water((x,y,z)) or self.swimmable((x,y,z)):heights.add(y)
        return [(x,y,z) for y in sorted(heights,key=lambda y:(abs(y-near_y),y))
                if self.standable((x,y,z))]

    def interactive(self, n):
        return any(n.groups.get(k,0)>0 for k in ('door','trapdoor','fence_gate'))

    @cached_geometry
    def supported(self, position):
        """Actual support at a continuous point, not the centre of its voxel."""
        x,y,z=position;cx,cy,cz=cell(position)
        for nx in range(cx-1,cx+2):
            for ny in range(cy-2,cy+1):
                for nz in range(cz-1,cz+2):
                    n=self.nodes.get((nx,ny,nz))
                    if n is None or not n.harmless or not n.walkable or (n.boxes is None and not n.full_cube):continue
                    for box in n.collision_boxes:
                        if abs(ny+box[4]-y)<.025 and nx+box[0]-.001<=x<=nx+box[3]+.001 and nz+box[2]-.001<=z<=nz+box[5]+.001:return True
        return False

    @cached_geometry
    def sweep(self, p, q, ignored=frozenset(), jump=False):
        origin,dest=self.point(p,ignored=ignored),self.point(q,ignored=ignored)
        lift=max(origin[1],dest[1])
        if jump:
            gravity=self.physics['gravity'];v=self.physics['jump_speed']
            if gravity<=0:return False
            lift=max(lift,origin[1]+v*v/(2*gravity))
        count=max(2,math.ceil(distance(origin,dest)/.12))
        wet=any(self.surface_water(r) or self.swimmable(r) or self.wading(r) for r in (p,q))
        for i in range(count+1):
            t=i/count;pos=(origin[0]+(dest[0]-origin[0])*t,lift,origin[2]+(dest[2]-origin[2])*t)
            if not self.body_clear((pos[0],max(origin[1],dest[1]),pos[2]),height=self.height+lift-max(origin[1],dest[1]),water=wet,ignored=ignored):return False
        return True

    def blockers(self,p,q):
        """Small local envelope used to propose normal interactions or mining."""
        lo=[min(p[i],q[i]) for i in range(3)];hi=[max(p[i],q[i]) for i in range(3)]
        result=set()
        for x in range(math.floor(lo[0]),math.ceil(hi[0])+1):
            for z in range(math.floor(lo[2]),math.ceil(hi[2])+1):
                for y in range(math.ceil(lo[1]),math.floor(hi[1])+math.ceil(self.height)):
                    pos=(x,y,z);n=self.nodes.get(pos)
                    if n and n.walkable:result.add(pos)
        return result

    @cached_geometry
    def edge_plan(self,p,q):
        dy=q[1]-p[1];jump=dy>self.physics['step_height']+.02
        if self.sweep(p,q,jump=jump):return ()
        blockers=self.blockers(p,q)
        doors={pos for pos in blockers if pos not in self.unusable and self.interactive(self.nodes[pos])}
        if self.traversal.allow_interact and doors and self.sweep(p,q,ignored=doors,jump=jump):
            return (('interact',min(doors,key=lambda v:distance(v,p))),)
        return None

    @cached_geometry
    def editable(self,p,q):
        policy=self.traversal
        if not (policy.allow_interact or policy.allow_dig or policy.build_with):return None
        actions=[];ignored=set();x,y,z=q
        if y!=int(y):return None
        floor=(x,y-1,z);support=self.nodes.get(floor)
        if support is None or not support.harmless:return None
        if not (support.walkable and support.full_cube):
            if not policy.build_with or not support.buildable:return None
            # A step-up scaffold first needs a lower foundation face.
            if y>p[1]:
                lower=(x,y-2,z);n=self.nodes.get(lower)
                if n is None or not n.harmless:return None
                if not n.walkable:
                    if not n.buildable:return None
                    actions.append(('build',lower))
            actions.append(('build',floor))
        blocks=self.blockers(p,q)
        for pos in sorted(blocks,key=lambda pos:(-pos[1],distance(pos,p))):
            if pos in ((p[0],p[1]-1,p[2]),floor):continue
            n=self.nodes[pos]
            if pos in self.unusable:return None
            if self.interactive(n) and policy.allow_interact:
                actions.append(('interact',pos));ignored.add(pos)
            elif policy.allow_dig and n.harmless and n.full_cube and not n.groups.get('falling_node',0) and not n.groups.get('unbreakable',0):
                actions.append(('dig',pos));ignored.add(pos)
            else:return None
        if not actions or len(actions)>6:return None
        if not self.body_clear(feet(q),ignored=ignored):return None
        if not self.sweep(p,q,ignored=ignored,jump=y-p[1]>self.physics['step_height']+.02):return None
        return tuple(actions)

    def neighbors(self, p):
        x,y,z=p;policy=self.traversal
        if self.swimmable(p) or self.surface_water(p):
            for dy in (-1,1):
                q=(x,y+dy,z)
                if self.swimmable(q) or self.surface_water(q):yield q,1.8
        if self.ladder(p):
            for dy in (-1,1):
                q=(x,y+dy,z)
                if self.standable(q):yield q,1.8
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
            yielded=set()
            for q in self.poses(x+dx,z+dz,y):
                dy=q[1]-y
                if not -policy.max_drop-.001<=dy<=1.001:continue
                plan=self.edge_plan(p,q)
                if plan is None:continue
                if dy<0 and not self.body_clear((q[0],y-.5,q[2]),water=self.swimmable(q) or self.surface_water(q) or self.wading(q)):continue
                if plan:self.edge_actions[p,q]=plan
                yielded.add(q);yield q,1+.6*abs(dy)+(2 if plan else 0)+(1 if self.surface_water(q) else 0)
            # Observed jump geometry plus actual server speed/gravity bound.
            if policy.allow_jump_gaps and not self.ladder(p) and not self.surface_water(p):
                for gap in range(1,policy.max_gap+1):
                    q=(x+(gap+1)*dx,y,z+(gap+1)*dz)
                    if not self.standable(q) or self.surface_water(q) or self.ladder(q):continue
                    known=True
                    for i in range(1,gap+1):
                        n=self.nodes.get((x+i*dx,y-1,z+i*dz));under=self.nodes.get((x+i*dx,y-2,z+i*dz))
                        if n is None or n.walkable or not n.harmless or under is None or not under.harmless:known=False;break
                    g=self.physics['gravity'];flight=2*self.physics['jump_speed']/g if g>0 else 0
                    if known and gap+.2 <= self.physics['walk_speed']*flight and self.sweep(p,q,jump=True):
                        self.edge_actions[p,q]=(('jump',q),);yield q,gap+2.5
            for dy in (0,-1,1):
                q=(x+dx,y+dy,z+dz)
                if q in yielded:continue
                plan=self.editable(p,q)
                if plan:
                    self.edge_actions[p,q]=plan
                    yield q,1+sum(5 if k=='dig' else 4 if k=='build' else 2 for k,_ in plan)

    def start(self, position):
        x,y,z=cell(position)
        candidates=[p for p in self.poses(x,z,position[1]+.5) if abs(feet(p)[1]-position[1])<2]
        n=self.nodes.get((x,y,z))
        if self.traversal.allow_swim and n and n.liquid and not n.damage:
            # The character keeps sinking while a script acquires observations.
            # Surface-only mode may recover from existing submersion; it must
            # not fail merely because the surface fell outside poses' +/-1 band.
            for sy in range(y,y+7):
                q=(x,sy,z)
                if not self.surface_water(q):continue
                dest=self.point(q);count=max(1,math.ceil(abs(dest[1]-position[1])/.2))
                if all(self.body_clear((position[0],position[1]+(dest[1]-position[1])*i/count,position[2]),water=True) for i in range(count+1)):
                    candidates.append(q)
        return min(candidates,key=lambda p:abs(self.point(p)[1]-position[1]),default=None)

    @cached_geometry
    def point(self, p, ignored=frozenset()):
        x,y,z=feet(p)
        if self.surface_water(p):return (x,y-.45,z)
        if self.body_clear((x,y,z),water=self.wading(p),ignored=ignored):return (x,y,z)
        # Thin opened doors leave an asymmetric corridor. Track a clearance
        # offset rather than repeatedly toggling an already-open door or
        # pretending the player's real collision box is smaller.
        for amount in (.10,.18):
            for dx,dz in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                q=(x+dx*amount,y,z+dz*amount)
                if self.supported(q) and self.body_clear(q,ignored=ignored):return q
        return (x,y,z)

    def frontier(self, p):
        p=cell(feet(p))
        return any((p[0]+dx,p[1],p[2]+dz) not in self.nodes
                   or (p[0]+dx,p[1]+1,p[2]+dz) not in self.nodes
                   for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)))

    def visible(self, origin, target):
        """Conservative voxel ray; the target itself is allowed to be solid."""
        length = distance(origin, target)
        for i in range(1, max(2, math.ceil(length*10))):
            t = i/max(2, math.ceil(length*10))
            p = cell(tuple(a+(b-a)*t for a,b in zip(origin, target)))
            if p == tuple(target):
                return True
            n = self.nodes.get(p)
            if n is None or n.walkable:
                return False
        return True

    def interaction_point(self, eye, target):
        """Prefer the old centre aim, then an exposed full-cube face.

        A low tunnel can expose a wall block's near face while hiding its
        centre behind the block above. This only chooses a ray to an observed
        block; it does not mine occluders or extend interaction reach.
        """
        target=tuple(target)
        if distance(eye,target)<=3.5 and self.visible(eye,target):return target
        node=self.nodes.get(target)
        if node is None or not node.walkable or not node.full_cube:return None
        faces=[tuple(target[i]+(.49*sign if i==axis else 0) for i in range(3))
               for axis in range(3) for sign in (-1,1)]
        for point in sorted(faces,key=lambda q:distance(eye,q)):
            if distance(eye,point)<=3.5 and self.visible(eye,point):return point
        # An overhang can hide a face centre but leave its lower/side region
        # exposed through a previously mined neighbor. Bounded inset samples
        # stay away from voxel edges and never treat unknown space as clear.
        for point in sorted(faces,key=lambda q:distance(eye,q)):
            axis=next(i for i in range(3) if point[i]!=target[i])
            for other in range(3):
                if other==axis:continue
                for offset in (-.35,.35):
                    aim=tuple(point[i]+(offset if i==other else 0) for i in range(3))
                    if distance(eye,aim)<=3.5 and self.visible(eye,aim):return aim
        return None

    def supported_by(self, position, target):
        n=self.nodes.get(target)
        if n is None:return False
        x,y,z=(position[i]-target[i] for i in range(3))
        return any(abs(b[4]-y)<.025 and b[0]-.001<=x<=b[3]+.001
                   and b[2]-.001<=z<=b[5]+.001 for b in n.collision_boxes)

    def harvest_approach(self, p, target):
        # Reposition rather than removing the block under the actor. Other
        # interactions (e.g. opening a workstation) may keep that stance.
        return self.approach(p,target) and not self.supported_by(self.point(p),target)

    def approach(self, p, target):
        # Keep a short reach and check the real crosshair again before digging.
        eye = (p[0], p[1]+1.125, p[2])
        return self.supported(self.point(p)) and 1 <= distance(p, target) <= 3.0 and distance(eye, target) <= 3.5 and self.interaction_point(eye,target) is not None

    def corridor_clear(self, origin, target, radius=None):
        """Continuous support and player-width collision sweep; flat only."""
        if abs(origin[1]-target[1])>.12:return False
        count=max(1,math.ceil(math.hypot(target[0]-origin[0],target[2]-origin[2])/.12))
        for i in range(count+1):
            t=i/count;pos=tuple(a+(b-a)*t for a,b in zip(origin,target));p=cell(pos)
            water=self.surface_water(p) or self.swimmable(p) or self.wading(p)
            if water:
                if not self.standable(p):return False
            elif not self.supported(pos):return False
            if not self.body_clear(pos,radius=radius,water=water):return False
        return True

    def swim_corridor_clear(self, origin, target):
        """Observed continuous water corridor, including a 3D ascent/descent.

        Topology cells are not swimming steering targets. Keep the full player
        volume clear and wet support present; never shortcut across unknown
        space, dry gaps, hazards, or an unrequested dive.
        """
        if not self.traversal.allow_swim:return False
        if not self.traversal.allow_dive and target[1]<origin[1]-.2:return False
        count=max(1,math.ceil(distance(origin,target)/.15))
        for i in range(count+1):
            t=i/count;pos=tuple(a+(b-a)*t for a,b in zip(origin,target))
            wet=self.nodes.get(cell((pos[0],pos[1]-.05,pos[2])))
            if wet is None or not wet.liquid or wet.damage:return False
            if not self.body_clear(pos,water=True):return False
        return True

    def path(self, start, goal, heuristic=lambda p:0, *, blocked=frozenset(), max_nodes=10000, within=lambda p:True):
        previous=getattr(self,'_planning_cache',None);self._planning_cache={}
        try:return self._path(start,goal,heuristic,blocked=blocked,max_nodes=max_nodes,within=within)
        finally:self._planning_cache=previous

    def _path(self, start, goal, heuristic=lambda p:0, *, blocked=frozenset(), max_nodes=10000, within=lambda p:True):
        if start is None:
            return None, {}
        queue = [(heuristic(start),0.0,start)]
        cost = {start:0.0}
        parent = {}
        closed = set()
        while queue and len(closed) < max_nodes:
            _,g,p = heapq.heappop(queue)
            if p in closed:
                continue
            closed.add(p)
            if len(closed)%16==0 and getattr(self,"planning_check",None):self.planning_check()
            if goal(p):
                return self.reconstruct(parent,p), cost
            for q,step in self.neighbors(p):
                if (p,q) in blocked or not within(q):
                    continue
                new = g+step
                if new < cost.get(q,math.inf):
                    cost[q] = new
                    parent[q] = p
                    heapq.heappush(queue,(new+heuristic(q),new,q))
        return None, {p:cost[p] for p in closed}

    @staticmethod
    def reconstruct(parent, end):
        path = [end]
        while path[-1] in parent:
            path.append(parent[path[-1]])
        return path[::-1]
