"""Bounded observation memory and declarative, client-bound quantity checkpoints."""
from collections import Counter
import copy,json,math,os,time
from contextlib import contextmanager
from pathlib import Path
from .navigation import World

class ExplorationMemory:
    def __init__(self, *, ttl=60, max_nodes=60000):
        if isinstance(ttl,bool) or not isinstance(ttl,(int,float)) or not math.isfinite(ttl) or not 0<ttl<=3600:raise ValueError('ttl must be 0..3600 seconds')
        if type(max_nodes) is not int or not 1<=max_nodes<=60000:raise ValueError('max_nodes must be 1..60000')
        self.ttl,self.max_nodes=ttl,max_nodes;self.clear()
    def clear(self):self.scope=None;self.nodes={};self.seen={};self.visited=Counter();self.unusable=set();self.saved_at=0
    def load(self,scope):
        w=World()
        if scope!=self.scope:return w,Counter()
        now=time.monotonic();keep={p for p in self.nodes if now-self.seen.get(p,0)<=self.ttl}
        w.nodes={p:copy.deepcopy(self.nodes[p]) for p in keep};w.observed={p:self.seen[p] for p in keep}
        if now-self.saved_at<min(self.ttl,5):w.unusable=set(self.unusable)&keep
        return w,Counter({p:n for p,n in self.visited.items() if p in keep})
    def store(self,scope,world,visited):
        self.scope=scope;now=time.monotonic();self.saved_at=now;self.unusable=set(world.unusable)
        times=getattr(world,'observed',{});keep=sorted(world.nodes,key=lambda p:times.get(p,now),reverse=True)[:self.max_nodes]
        self.nodes={p:copy.deepcopy(world.nodes[p]) for p in keep};self.seen={p:times.get(p,now) for p in keep}
        self.visited=Counter({p:n for p,n in visited.items() if p in self.nodes})

class Checkpoint:
    def __init__(self,path,scope,operation,request,current):
        self.path=Path(path).expanduser().resolve();request=json.loads(json.dumps(request,allow_nan=False))
        if self.path.exists():
            if self.path.stat().st_size>65536:raise ValueError('checkpoint too large')
            self.data=json.loads(self.path.read_text(encoding='utf-8'))
            if self.data.get('schema')!=1 or self.data.get('scope')!=scope or self.data.get('operation')!=operation or self.data.get('request')!=request:raise ValueError('checkpoint request or client changed')
        else:
            self.data=dict(schema=1,scope=scope,operation=operation,request=request,initial=current,target=current+request['count'],last=current,complete=False,station=None)
            self.save()
        if any(type(self.data.get(k)) is not int or self.data[k]<0 for k in ('initial','target','last')) or type(self.data.get('complete')) is not bool or self.data['target']!=self.data['initial']+request['count'] or self.data['last']<self.data['initial']:
            raise ValueError('invalid checkpoint quantity ledger')
        self.remaining(current)
    def remaining(self,current):
        if self.data['complete']:return 0
        if current<self.data['last']:raise ValueError('checkpoint inventory decreased; reconcile before continuing')
        return max(0,self.data['target']-current)
    def progress(self,current,complete=False):
        self.remaining(current)
        self.data['last']=max(self.data['last'],current);self.data['complete']=self.data['complete'] or complete
        self.save()
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_name(self.path.name+'.'+str(os.getpid())+'.tmp')
        with tmp.open('w',encoding='utf-8') as f:
            json.dump(self.data,f,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
        os.replace(tmp,self.path)

def owned_count(state,item,book):
    # craftpreview is a prediction; displayed forms duplicate inventories.
    return sum(i.count for name,inv in state.inventory.items() if name in ('main','craft','craftresult','offhand','armor') for i in inv.items if book.matches(i.name,item))

def _quantity_task(ctx,operation,item,count,path,request,execute):
    from .skills import Failure
    if path is None:return execute(count)
    try:cp=Checkpoint(path,str(ctx.game.endpoint.resolve()),operation,request,owned_count(ctx.read(),item,ctx.book))
    except (ValueError,OSError) as exc:raise Failure('checkpoint_conflict',{'message':str(exc)})
    ctx.checkpoint=cp
    try:
        pending=cp.data.get('station')
        if pending and operation!='smelt':
            from .workstations import smelt
            needed=max(0,pending['target']-owned_count(ctx.read(),pending['item'],ctx.book))
            if needed:smelt(ctx,pending['item'],needed,furnace=pending['position'])
            else:cp.data['station']=None;cp.save()
        if operation=='craft':
            from .skills import clear_grid
            state=ctx.read()
            if any(i.count for name in ('craft','craftresult') if name in state.inventory for i in state.inventory[name].items):
                if not state.raw['menu_open']:
                    ctx.game.open_inventory();ctx.wait(lambda s:s.raw['menu_open'])
                clear_grid(ctx)
        remaining=cp.remaining(owned_count(ctx.read(),item,ctx.book))
        ctx.details.update(checkpoint=str(cp.path),remaining=remaining)
        if remaining:execute(remaining)
        current=owned_count(ctx.read(),item,ctx.book)
        if cp.remaining(current):raise Failure('checkpoint_target_unconfirmed')
        cp.progress(current,complete=True)
        ctx.details.update(remaining=0,total_completed=max(0,current-cp.data['initial']))
    finally:
        # Last confirmed observation only. No command is replayed here.
        if ctx.last:
            current=owned_count(ctx.last,item,ctx.book)
            if current>=cp.data['last']:cp.progress(current)
        ctx.checkpoint=None

@contextmanager
def checkpoint_lock(path):
    path=Path(path).expanduser().resolve();path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_name(path.name+'.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as exc:raise ValueError('checkpoint is in use') from exc
        else:
            import fcntl
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc:raise ValueError('checkpoint is in use') from exc
        try:yield
        finally:
            if os.name=='nt':lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(lock,fcntl.LOCK_UN)

def quantity_task(ctx,operation,item,count,path,request,execute):
    if path is None:return execute(count)
    from .skills import Failure
    try:
        with checkpoint_lock(path):return _quantity_task(ctx,operation,item,count,path,request,execute)
    except (ValueError,OSError) as exc:
        raise Failure('checkpoint_conflict',{'message':str(exc)})

def legacy_request(data):
    if not isinstance(data,dict):raise ValueError('expected a legacy checkpoint object')
    op=data.get('operation');request=data.get('request')
    if op not in ('collect','craft') or not isinstance(request,dict):raise ValueError('expected a legacy collect/craft checkpoint')
    if 'allow_tool_crafting' in request:raise ValueError('checkpoint already has a tool policy')
    key='item' if op=='craft' else 'resource'
    if not isinstance(request.get(key),str) or not request[key]:raise ValueError('checkpoint has no item/resource')
    if type(request.get('count')) is not int or not 1<=request['count']<=64:raise ValueError('invalid checkpoint requested count')
    return op,request,request[key]

def upgrade_checkpoint(source,destination,scope,current,*,allow_tool_crafting=False,expected_sha256=None):
    """Copy a legacy quantity ledger with an explicit tool policy; never replay it."""
    import hashlib
    from .locations import atomic_json
    source=Path(source).expanduser().resolve();destination=Path(destination).expanduser().resolve()
    if source==destination:raise ValueError('upgrade requires a new checkpoint path')
    if type(allow_tool_crafting) is not bool:raise ValueError('allow_tool_crafting must be boolean')
    # Consistent lock ordering also prevents two opposite migrations deadlocking.
    from contextlib import ExitStack
    with ExitStack() as stack:
        for path in sorted((source,destination)):stack.enter_context(checkpoint_lock(path))
        if destination.exists():raise ValueError('destination checkpoint already exists')
        if source.stat().st_size>65536:raise ValueError('checkpoint too large')
        raw=source.read_bytes()
        if expected_sha256 is not None and hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('source checkpoint changed during observation')
        data=json.loads(raw);op,request,_=legacy_request(data)
        # All normal ledger/scope/inventory checks run before creating any output.
        cp=Checkpoint(source,scope,op,request,current)
        migrated=copy.deepcopy(cp.data);migrated['request']['allow_tool_crafting']=allow_tool_crafting
        migrated['migration']=dict(source_sha256=hashlib.sha256(raw).hexdigest(),tool_policy=allow_tool_crafting)
        if len(json.dumps(migrated).encode())>65536:raise ValueError('migrated checkpoint too large')
        if source.read_bytes()!=raw:raise ValueError('source checkpoint changed during upgrade')
        atomic_json(destination,migrated)
        return dict(checkpoint=str(destination),operation=op,remaining=cp.remaining(current),complete=cp.data['complete'],
                    allow_tool_crafting=allow_tool_crafting,gather=request.get('gather'),station=copy.deepcopy(cp.data.get('station')))
