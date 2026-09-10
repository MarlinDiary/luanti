"""Explicit named positions bound to one running client and the same world."""
from pathlib import Path
import json,math,os,tempfile
MAX_LOCATIONS=128

def label(name):
    if not isinstance(name,str) or not name.strip() or len(name)>64 or any(ord(c)<32 or ord(c)==127 for c in name):
        raise ValueError('location name must contain 1..64 printable characters')
    return name

def position(value):
    if not isinstance(value,(list,tuple)) or len(value)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>32700 for x in value):raise ValueError('expected finite world position')
    return tuple(value)

def validate(data,scope):
    if not isinstance(data,dict) or data.get('schema')!=1 or data.get('scope')!=scope:raise ValueError('locations belong to a different client')
    values=data.get('locations')
    if not isinstance(values,dict) or len(values)>MAX_LOCATIONS:raise ValueError('invalid location book')
    return {label(k):position(v) for k,v in values.items()}

def load(path,scope):
    path=Path(path).expanduser().resolve()
    if path.stat().st_size>65536:raise ValueError('location book too large')
    return validate(json.loads(path.read_text(encoding='utf-8')),scope)

def atomic_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as f:
            tmp=Path(f.name);json.dump(data,f,ensure_ascii=False,allow_nan=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if tmp is not None and tmp.exists():tmp.unlink()

def save(path,scope,values):
    data=dict(schema=1,scope=scope,locations=values);validate(data,scope)
    path=Path(path).expanduser().resolve()
    from .persistence import checkpoint_lock
    with checkpoint_lock(path):
        if path.exists():load(path,scope)  # Never overwrite an unrelated file/world.
        atomic_json(path,data)
    return str(path)
