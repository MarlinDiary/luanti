#!/usr/bin/env python3
"""Create a relocatable macOS app with private non-system dylibs and ad-hoc signing.

Ad-hoc signing is for local testing; a public release still needs Developer ID
signing/notarization and tests on the declared minimum macOS version.
"""
import argparse,hashlib,json,os,plistlib,re,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--installed',type=Path,required=True);p.add_argument('--output',type=Path,default=ROOT/'dist/Luanti Course.app');a=p.parse_args()
assert sys.platform=='darwin'
if a.output.exists():raise SystemExit('Output already exists; choose a new output path to preserve previous builds.')
app=a.output.resolve();app.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(a.installed,app,symlinks=True)
contents=app/'Contents';frameworks=contents/'Frameworks';frameworks.mkdir(exist_ok=True)
binary=contents/'MacOS/luanti'

def command(*args):return subprocess.check_output(list(map(str,args)),text=True,stderr=subprocess.STDOUT)
def deps(path):
    text=command('otool','-L',path)
    return [line.strip().split(' (compatibility')[0] for line in text.splitlines()[1:]]
def resolve(dep,parent):
    if dep.startswith('@loader_path/'):
        path=parent.parent/dep[len('@loader_path/'):]
    elif dep.startswith('@rpath/'):
        leaf=dep[len('@rpath/'):];options=[parent.parent/leaf,Path('/opt/homebrew/lib')/leaf]
        path=next((x for x in options if x.exists()),None)
        if path is None:raise RuntimeError('Unresolved dependency '+dep+' from '+str(parent))
    elif dep.startswith('@executable_path/'):
        path=binary.parent/dep[len('@executable_path/'):]
    else:path=Path(dep)
    if not path.exists():raise RuntimeError('Missing dependency '+str(path))
    return path.resolve()

seen={};origins={};queue=[(binary,binary)]
# SDL2-compat loads SDL3 via dlopen, so otool's link graph alone is incomplete.
sdl3=Path('/opt/homebrew/opt/sdl3/lib/libSDL3.dylib')
if any('SDL2' in dep for dep in deps(binary)) and sdl3.exists():
    original=sdl3.resolve(); destination=frameworks/original.name
    if not destination.exists():shutil.copy2(original,destination)
    alias=frameworks/'libSDL3.dylib'
    if not alias.exists():alias.symlink_to(original.name)
    seen[original.name]=original
    origins[original.name]={'source':str(original),'sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'reason':'SDL2-compat dlopen dependency'}
    queue.append((destination,original))
while queue:
    target,original=queue.pop(0)
    changes=[]
    for dep in deps(original):
        if dep.startswith(('/System/Library/','/usr/lib/')):continue
        source=resolve(dep,original)
        if source==original.resolve():continue # dylib's own install id
        name=source.name
        if name in seen and seen[name]!=source:raise RuntimeError('Library basename collision: '+name)
        if name not in seen:
            destination=frameworks/name
            if source!=destination.resolve():shutil.copy2(source,destination)
            destination.chmod(0o755)
            seen[name]=source;origins[name]={'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
            queue.append((destination,source))
        prefix='@executable_path/../Frameworks/' if target==binary else '@loader_path/'
        changes.append((dep,prefix+name))
    # Modifications invalidate existing signatures; they are replaced below.
    subprocess.run(['codesign','--remove-signature',str(target)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if target!=binary:command('install_name_tool','-id','@rpath/'+target.name,target)
    for old,new in changes:command('install_name_tool','-change',old,new,target)
    # No external build paths in runpath load commands.
    details=command('otool','-l',target)
    for rpath in re.findall(r'cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.*?) \(offset',details):
        if rpath.startswith(('/opt/homebrew','/Users/','/usr/local')):command('install_name_tool','-delete_rpath',rpath,target)

info=plistlib.loads((contents/'Info.plist').read_bytes())
info.update(CFBundleIdentifier='org.luanticourse.client',CFBundleName='Luanti Course',CFBundleDisplayName='Luanti Course',CFBundleShortVersionString=json.loads((ROOT/'engine/upstream.json').read_text())['course_version'],CFBundleVersion=json.loads((ROOT/'engine/upstream.json').read_text())['course_version'])
# Use our own neutral bundle identifier; this is not an official server app.
info['CFBundleIdentifier']='org.luanticourse.client'
(contents/'Info.plist').write_bytes(plistlib.dumps(info))
licenses=contents/'Resources/third-party-licenses';licenses.mkdir(exist_ok=True)
for name,source in seen.items():
    # Homebrew formula prefix (Cellar/<formula>/<version>) contains its notices.
    origin=source
    candidate=Path('/opt/homebrew/lib')/name
    if 'Cellar' not in source.parts and candidate.exists():origin=candidate.resolve()
    parts=origin.parts
    if 'Cellar' in parts:
        i=parts.index('Cellar');prefix=Path(*parts[:i+3]);dest=licenses/prefix.parent.name;dest.mkdir(exist_ok=True)
        for pattern in ['LICENSE*','COPYING*','NOTICE*','share/doc/*/copyright']:
            for f in prefix.glob(pattern):
                if f.is_file():shutil.copy2(f,dest/f.name)
    command('codesign','--force','--sign','-',frameworks/name)
command('codesign','--force','--sign','-',binary)
command('codesign','--force','--sign','-',app)
verify=command('codesign','--verify','--deep','--strict','--verbose=2',app)
load_commands={}
for file in [binary,*sorted(frameworks.iterdir())]:
    load_commands[str(file.relative_to(app))]=deps(file)
    for dep in deps(file):assert not dep.startswith(('/opt/homebrew/','/Users/','/usr/local/')),dep
result={'app':str(app),'libraries':origins,'load_commands':load_commands,'signature_verification':verify,'signing':'ad-hoc, not notarized'}
(app.parent/(app.name+'.packaging.json')).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'app':str(app),'bundled_libraries':len(seen),'external_non_system_dependencies':0,'signing':'ad-hoc'},indent=2))
