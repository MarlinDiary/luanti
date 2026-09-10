-- Local acceptance fixture only: generated terrain/logs, no starting items.
-- This is not part of the student client, and is never sent to a course server.
local root=core.get_worldpath()
local scenario='loading'
local tick=0
local changed_material=false
-- Use the supported prediction callback to model a custom server rule.
-- Do not erase registered recipes after the engine has hashed its definitions.
core.register_craft_predict(function(itemstack)
  if scenario=='mismatch' and itemstack:get_name()=='mcl_core:stick' then
    return ItemStack('')
  end
end)
local function snapshot(p)
  if not p then return end
  local counts={}
  for _,s in ipairs(p:get_inventory():get_list('main')) do
    counts[s:get_name()]=(counts[s:get_name()] or 0)+s:get_count()
  end
  core.safe_file_write(root..'/state.json',core.write_json({scenario=scenario,pos=p:get_pos(),hp=p:get_hp(),counts=counts,control=p:get_player_control()}))
end
local function event(kind,value)
  local f=io.open(root..'/events.jsonl','a')
  if f then f:write(core.write_json({kind=kind,value=value,time=core.get_us_time()})..'\n');f:close() end
end
core.register_on_generated(function(a,b)
  if a.y<=99 and b.y>=99 then
    for x=math.max(-22,a.x),math.min(22,b.x) do for z=math.max(-22,a.z),math.min(22,b.z) do
      core.set_node({x=x,y=99,z=z},{name='mcl_core:stone'})
    end end
  end
end)
local function reset(p,name)
  changed_material=false
  for x=-20,20 do for z=-20,20 do
    core.set_node({x=x,y=99,z=z},{name='mcl_core:stone'})
    for y=96,98 do core.set_node({x=x,y=y,z=z},{name='air'}) end
    for y=100,106 do core.set_node({x=x,y=y,z=z},{name='air'}) end
  end end
  for _,obj in ipairs(core.get_objects_inside_radius({x=0,y=100,z=0},45)) do
    if not obj:is_player() then obj:remove() end
  end
  local inv=p:get_inventory()
  for _,l in ipairs({'main','craft','craftresult','armor'}) do inv:set_list(l,{}) end
  inv:set_width('craft',2);inv:set_size('craft',4)
  p:set_pos({x=0,y=99.51,z=0});p:set_look_horizontal(0);p:set_look_vertical(0);p:set_hp(20)
  core.set_timeofday(.5)
  if name=='nav_a' or name=='nav_b' then
    local gap=name=='nav_a' and 3 or -3
    for t=-10,10 do if t~=gap then for y=100,102 do
      local pos=name=='nav_a' and {x=0,y=y,z=t} or {x=t,y=y,z=0}
      core.set_node(pos,{name='mcl_core:stone'})
    end end end
    p:set_pos(name=='nav_a' and {x=-6,y=99.51,z=-5} or {x=-5,y=99.51,z=-6})
  elseif name=='steps' then
    for x=2,12 do for z=-8,8 do core.set_node({x=x,y=100,z=z},{name='mcl_core:stone'}) end end
  elseif name=='oak' or name=='spruce' or name=='far' then
    local nodes=name=='oak' and {{-4,-3},{5,4},{-6,6}} or name=='far' and {{10,0},{11,3}} or {{4,-5},{-5,4},{6,6}}
    for _,v in ipairs(nodes) do for y=100,102 do
      core.set_node({x=v[1],y=y,z=v[2]},{name=name=='spruce' and 'mcl_core:sprucetree' or 'mcl_core:tree'})
    end end
    if name=='oak' then
      for z=2,4 do core.set_node({x=2,y=101,z=z},{name='mcl_core:stone'}) end
    end
  elseif name=='metadata_output' then
    inv:set_stack('main',1,'mcl_core:wood 8')
    local special=ItemStack('mcl_core:stick');special:get_meta():set_string('description','Keep my label');inv:set_stack('main',2,special)
  elseif name=='batch' or name=='replan' then
    inv:set_stack('main',1,'mcl_core:wood 16')
  elseif name=='collect_batch' then
    inv:set_stack('main',1,'mcl_tools:pick_wood')
    for z=-1,1 do core.set_node({x=3,y=100,z=z},{name='mcl_core:stone'}) end
  elseif name=='tool_recovery' then
    inv:set_stack('main',1,'mcl_core:wood 8');inv:set_stack('main',2,'mcl_core:stick 4')
    core.set_node({x=0,y=101,z=3},{name='mcl_core:stone'})
  elseif name=='pickup_shift' then
    local obj=core.add_item({x=7,y=100,z=2},'mcl_core:tree 3')
    if obj then obj:set_velocity({x=1,y=0,z=0}) end
  elseif name=='organize' or name=='full' then
    for i=1,inv:get_size('main') do inv:set_stack('main',i,'mcl_core:wood '..(name=='full' and '64' or '1')) end
    if name=='organize' then
      local special=ItemStack('mcl_core:wood');special:get_meta():set_string('description','Keep my label');inv:set_stack('main',3,special)
    end
  elseif name=='equip_place' then
    inv:set_stack('main',20,'mcl_tools:pick_wood');inv:set_stack('main',21,'mcl_core:cobble 3')
    inv:set_stack('main',22,'mcl_armor:helmet_iron');inv:set_stack('main',23,'mcl_armor:helmet_gold')
  elseif name=='gap' then
    for z=-20,20 do
      core.set_node({x=2,y=99,z=z},{name='air'});core.set_node({x=2,y=98,z=z},{name='air'})
      core.set_node({x=2,y=97,z=z},{name='mcl_core:stone'})
    end
  elseif name=='ladder' then
    for y=100,104 do
      core.set_node({x=3,y=y,z=0},{name='mcl_core:stone'})
      core.set_node({x=2,y=y,z=0},{name='mcl_core:ladder',param2=2})
    end
  elseif name=='slabs' or name=='stairs' or name=='stairs_rotated' or name=='snow' then
    for x=2,8 do for z=-6,6 do
      if name=='slabs' then
        core.set_node({x=x,y=100,z=z},{name='mcl_stairs:slab_stone'})
      elseif name=='snow' then
        core.set_node({x=x,y=100,z=z},{name='mcl_core:snow'})
      else
        core.set_node({x=x,y=100,z=z},{name=x==2 and 'mcl_stairs:stair_stone_rough' or 'mcl_core:stone',param2=name=='stairs_rotated' and 1 or 3})
      end
    end end
  elseif name=='low_ceiling' then
    for x=-1,1 do for z=-1,1 do
      core.set_node({x=x,y=102,z=z},{name='mcl_core:stone'})
      if x~=0 or z~=0 then core.set_node({x=x,y=100,z=z},{name='mcl_stairs:slab_stone'}) end
    end end
  elseif name=='swim_deep' or name=='swim_turn' or name=='dive' then
    for x=2,13 do for z=-20,20 do
      core.set_node({x=x,y=95,z=z},{name='mcl_core:stone'})
      for y=96,99 do core.set_node({x=x,y=y,z=z},{name='mcl_core:water_source'}) end
    end end
    if name=='swim_turn' then
      for x=5,6 do for z=-20,2 do for y=95,102 do
        core.set_node({x=x,y=y,z=z},{name='mcl_core:stone'})
      end end end
    end
    if name=='dive' then p:set_pos({x=4,y=99.05,z=0}) end
  elseif name=='swim' then
    for x=2,7 do for z=-20,20 do
      core.set_node({x=x,y=98,z=z},{name='mcl_core:stone'})
      core.set_node({x=x,y=99,z=z},{name='mcl_core:water_source'})
    end end
  elseif name=='stone' then
    core.set_node({x=0,y=101,z=3},{name='mcl_core:stone'})
  elseif name=='geometry' then
    core.set_node({x=2,y=100,z=0},{name='mcl_stairs:slab_stone'})
    core.set_node({x=3,y=100,z=0},{name='mcl_core:lava_source'})
  elseif name=='mismatch' then
    inv:set_stack('main',1,'mcl_core:wood 2')
  elseif name=='wall' then
    for x=-1,1 do for z=-1,1 do if x~=0 or z~=0 then for y=100,103 do
      core.set_node({x=x,y=y,z=z},{name='mcl_core:stone'})
    end end end end
  end
  scenario=name;snapshot(p);event('reset',{scenario=name,inventory_counts={}})
end
core.register_on_joinplayer(function(p)
  core.after(1,function()
    core.emerge_area({x=-20,y=96,z=-20},{x=20,y=111,z=20},function(_,_,remaining)
      if remaining==0 then core.after(.1,function()reset(p,'ready')end) end
    end)
  end)
end)
core.register_chatcommand('skills',{func=function(name,param)
  local p=core.get_player_by_name(name)
  if name~='singleplayer' or not p then return false end
  if param=='finish' then core.after(1,function()core.request_shutdown('finished',false,0)end)
  elseif param:match('^reset [%w_]+$') then reset(p,param:sub(7)) end
  return true,'skills '..param
end})
core.register_globalstep(function(dt)tick=tick+dt;if tick>.15 then tick=0;snapshot(core.get_player_by_name('singleplayer'))end end)
if core.settings:get_bool('course_motion_trace', false) then
  local clock=0
  core.register_globalstep(function(dt)
    clock=clock+dt
    local p=core.get_player_by_name('singleplayer')
    if p then
      local f=io.open(root..'/motion.jsonl','a')
      if f then
        f:write(core.write_json({time=clock,scenario=scenario,pos=p:get_pos(),
          velocity=p:get_velocity(),yaw=p:get_look_horizontal(),control=p:get_player_control()})..'\n')
        f:close()
      end
    end
  end)
end
core.register_on_player_inventory_action(function(player,action,inventory,info)
  if scenario=='replan' and not changed_material and action=='move' and info.from_list=='main' and info.to_list=='craft' then
    changed_material=true
    for i,stack in ipairs(inventory:get_list('main')) do
      if stack:get_name()=='mcl_core:wood' then inventory:set_stack('main',i,'mcl_core:sprucewood '..stack:get_count()) end
    end
    event('material_changed','sprucewood')
  end
end)
core.register_on_dignode(function(pos,node,p)event('dig',{pos=pos,node=node.name})end)
core.register_on_craft(function(item,p)
  event('craft',item:to_string())
end)
core.after(1200,function()core.request_shutdown('test timeout',false,0)end)
