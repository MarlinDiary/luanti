#!/usr/bin/env python3
"""Developer-only recipe export from a pinned local VoxeLibre installation.

This runs an isolated local server once. No mod is installed on a course server.
Students receive the generated, versioned data file in the Python package.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

EXPORT = r'''
core.register_on_mods_loaded(function()
  core.after(0, function()
    local out = {schema=2, items={}, recipes={}, cooking={}, fuels={}, aliases=core.registered_aliases}
    for name,def in pairs(core.registered_items) do
      local item = {groups=def.groups or {}, stack_max=def.stack_max or 99,
        type=def.type, diggroups=def._mcl_diggroups or {}}
      if def.type == "node" then
        item.on_rightclick = type(def.on_rightclick) == "function"
        item.on_receive_fields = type(def.on_receive_fields) == "function"
        -- Raw drop declarations are data, not guarantees about callbacks or loot.
        if type(def.drop)=="string" then item.drop=def.drop
        elseif def.drop==nil then item.drop=name end
      end
      out.items[name] = item
      local fuel,after=core.get_craft_result({method="fuel",width=1,items={ItemStack(name)}})
      if fuel.time>0 and after.items[1]:is_empty() then out.fuels[name]=fuel.time end
      local cooked=core.get_craft_result({method="cooking",width=1,items={ItemStack(name)}})
      if cooked.time>0 and not cooked.item:is_empty() then
        table.insert(out.cooking,{input=name,output=cooked.item:get_name(),count=cooked.item:get_count(),time=cooked.time})
      end
      local recipes = core.get_all_craft_recipes(name)
      if recipes then
        for _,r in ipairs(recipes) do
          local stack=ItemStack(r.output)
          if r.method=="normal" and r.width<=3 and #r.items<=9 and
              stack:get_wear()==0 and next(stack:get_meta():to_table().fields)==nil then
            table.insert(out.recipes, {output=stack:get_name(),count=stack:get_count(),
              width=r.width,items=r.items,replacements=r.replacements or {}})
          end
        end
      end
    end
    assert(core.safe_file_write(core.get_worldpath().."/catalog.json",core.write_json(out)))
    core.request_shutdown("catalog exported", false, 0)
  end)
end)
'''

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--client', type=Path, required=True)
    p.add_argument('--game', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    commit = subprocess.check_output(['git', '-C', str(a.game), 'rev-parse', 'HEAD'], text=True).strip()
    a.work.mkdir(parents=True, exist_ok=False)
    profile = a.work/'profile'
    (profile/'games').mkdir(parents=True)
    (profile/'games/voxelibre').symlink_to(a.game.resolve(), target_is_directory=True)
    world = profile/'world'
    mod = world/'worldmods/course_catalog_export'
    mod.mkdir(parents=True)
    (mod/'mod.conf').write_text('name = course_catalog_export\n')
    (mod/'init.lua').write_text(EXPORT)
    (world/'world.mt').write_text('gameid = voxelibre\nbackend = sqlite3\nplayer_backend = sqlite3\nauth_backend = sqlite3\n')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    config = a.work/'export.conf'
    config.write_text(f'bind_address = 127.0.0.1\nserver_announce = false\nport = {port}\nmg_name = singlenode\n')
    command = [str(a.client.resolve()), '--server', '--world', str(world.resolve()), '--config', str(config.resolve()), '--logfile', '']
    result = subprocess.run(command, env=dict(os.environ, LUANTI_USER_PATH=str(profile.resolve())), capture_output=True, text=True, timeout=90)
    (a.work/'run.json').write_text(json.dumps(dict(command=command, stdout=result.stdout, stderr=result.stderr, exit_status=result.returncode), indent=2))
    if result.returncode:
        raise SystemExit(result.stderr)
    data = json.loads((world/'catalog.json').read_text())
    data['source'] = {'game': 'VoxeLibre', 'repository': 'https://github.com/VoxeLibre/VoxeLibre', 'commit': commit,
                      'engine': 'Luanti 5.17.0', 'scope': 'Normal grid and cooking recipes; fuel burn times; live server output remains authoritative.'}
    data['recipes'] = [r for r in data['recipes'] if r.get('output') and r.get('items')]
    for recipe in data['recipes']:
        recipe['items'] = [value or '' for value in recipe['items']]
    data['cooking'].sort(key=lambda r:(r['output'],r['input']))
    data['recipes'].sort(key=lambda r: (r['output'], r['width'], r['items']))
    # Strip generated player skin variants: use the exported default hand rules.
    data['hand_diggroups'] = next(v['diggroups'] for k,v in sorted(data['items'].items()) if k.startswith('mcl_meshhand:') and k.endswith('_surv'))
    data['items'] = {k:v for k,v in data['items'].items() if not k.startswith('mcl_meshhand:')}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(data, sort_keys=True, separators=(',', ':'))+'\n')
    print(json.dumps({'output': str(a.output), 'recipes': len(data['recipes']), 'items': len(data['items']), 'commit': commit}))

if __name__ == '__main__':
    main()
