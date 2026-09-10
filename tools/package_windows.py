#!/usr/bin/env python3
"""Build a self-contained Windows zip from a tested RUN_IN_PLACE tree."""
import argparse,hashlib,json,shutil,tempfile,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
source=a.source.resolve();exe=source/'bin/luanti.exe'
if not exe.is_file():raise SystemExit('missing bin/luanti.exe')
if a.output.exists():raise SystemExit('output exists; preserve it and choose a new path')
include=('bin','builtin','client','fonts','textures','locale')
with tempfile.TemporaryDirectory() as t:
    root=Path(t)/'Luanti Course'
    for name in include:
        item=source/name
        if item.is_dir():shutil.copytree(item,root/name)
    for name in ('LICENSE.txt','README.md'):
        if (source/name).is_file():shutil.copy2(source/name,root/name)
    (root/'COURSE-VERSION.txt').write_text(json.loads((ROOT/'engine/upstream.json').read_text())['course_version']+'\n')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(a.output,'x',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(x for x in root.rglob('*') if x.is_file()):z.write(f,f.relative_to(root.parent))
with zipfile.ZipFile(a.output) as z:
    bad=z.testzip();names=z.namelist()
    if bad or 'Luanti Course/bin/luanti.exe' not in names:raise SystemExit('zip verification failed: '+str(bad))
manifest={'archive':str(a.output.resolve()),'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),'files':len(names),'contains_exe':True}
a.output.with_suffix(a.output.suffix+'.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
