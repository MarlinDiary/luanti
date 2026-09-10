#!/usr/bin/env python3
"""Apply the maintained overlay to a clean, pinned upstream checkout (idempotent)."""
import argparse,json,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args();source=a.source.resolve()
pin=json.loads((ROOT/'engine/upstream.json').read_text())['commit']
assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()==pin,'Wrong upstream revision'
patch=ROOT/'engine/patches/0001-course-control.patch'
r=subprocess.run(['git','apply','--check',str(patch)],cwd=source,capture_output=True,text=True)
if r.returncode==0:subprocess.run(['git','apply',str(patch)],cwd=source,check=True)
else:
    reverse=subprocess.run(['git','apply','--reverse','--check',str(patch)],cwd=source,capture_output=True,text=True)
    if reverse.returncode:raise SystemExit('Checkout is neither clean baseline nor the expected course overlay: '+r.stderr)
for path in (ROOT/'engine/src').iterdir():shutil.copy2(path,source/'src/client'/path.name)
print('Course overlay ready:',source)
