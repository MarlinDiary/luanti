-- Test-only persistent fixture. Never installed on a teaching server.
assert(core.settings:get_bool('course_test_fixture'), 'isolated fixture setting required')
local root=core.get_worldpath()
local survival=core.get_modpath(core.get_current_modname())..'/survival_fixture.lua'
local sf=io.open(survival,'r');if sf then sf:close();dofile(survival) end
local scenario='loading'
local generation=0
local active_spec={}
local phase_time=0
local sequence=0
local function write(p)
  if not p then return end
  local counts={}
  for _,s in ipairs(p:get_inventory():get_list('main')) do
    if not s:is_empty() then counts[s:get_name()]=(counts[s:get_name()] or 0)+s:get_count() end
  end
  core.safe_file_write(root..'/state.json',core.write_json({scenario=scenario,generation=generation,sequence=sequence,pos=p:get_pos(),hp=p:get_hp(),breath=p:get_breath(),counts=counts}))
end
local function node(p,n,param2)
  core.set_node(p,{name=n,param2=param2 or 0})
  local d=core.registered_nodes[n]
  if d and d.on_construct then d.on_construct(p) end
end
local function reset(p,spec)
  assert(type(spec.id)=='string' and spec.id:match('^[%w_-]+$'))
  -- Validate the entire edit request before clearing the previous scene.
  local function xyz(v)
    assert(type(v)=='table' and #v>=3, 'invalid coordinate')
    for i=1,3 do assert(type(v[i])=='number' and v[i]==math.floor(v[i]), 'noninteger coordinate') end
    assert(v[1]>=-32 and v[1]<=32 and v[2]>=88 and v[2]<=118 and v[3]>=-32 and v[3]<=32, 'fixture bounds')
  end
  local function nodes(list)
    for _,n in ipairs(list or {}) do xyz(n);assert(core.registered_nodes[n[4]], 'unknown fixture node') end
  end
  for _,f in ipairs(spec.fill or {}) do
    xyz(f.min);xyz(f.max);for i=1,3 do assert(f.min[i]<=f.max[i], 'reversed fill') end
    assert(core.registered_nodes[f.name], 'unknown fixture node')
  end
  nodes(spec.nodes);for _,c in ipairs(spec.changes or {}) do nodes(c.nodes) end
  local a,b={x=-32,y=88,z=-32},{x=32,y=118,z=32}
  for _,q in ipairs(core.find_nodes_with_meta(a,b)) do core.get_meta(q):from_table(nil) end
  for _,obj in ipairs(core.get_objects_inside_radius({x=0,y=100,z=0},65)) do if not obj:is_player() then obj:remove() end end
  local vm=VoxelManip();local lo,hi=vm:read_from_map(a,b);local area=VoxelArea:new({MinEdge=lo,MaxEdge=hi})
  local data=vm:get_data();local p2=vm:get_param2_data();local air=core.get_content_id('air');local stone=core.get_content_id('mcl_core:stone')
  for z=-32,32 do for y=88,118 do for x=-32,32 do local i=area:index(x,y,z);data[i]=(y==99 and stone or air);p2[i]=0 end end end
  for _,f in ipairs(spec.fill or {}) do
    assert(core.registered_nodes[f.name], 'unknown fixture node '..f.name)
    local id=core.get_content_id(f.name)
    for z=f.min[3],f.max[3] do for y=f.min[2],f.max[2] do for x=f.min[1],f.max[1] do
      assert(x>=-32 and x<=32 and y>=88 and y<=118 and z>=-32 and z<=32)
      local i=area:index(x,y,z);data[i]=id;p2[i]=f.param2 or 0
    end end end
  end
  vm:set_data(data);vm:set_param2_data(p2);vm:write_to_map();vm:update_liquids()
  for _,n in ipairs(spec.nodes or {}) do node({x=n[1],y=n[2],z=n[3]},n[4],n[5]) end
  for _,item in ipairs(spec.items or {}) do core.add_item({x=item[1],y=item[2],z=item[3]},item[4]) end
  local inv=p:get_inventory()
  for _,l in ipairs({'main','craft','craftresult','armor','offhand'}) do inv:set_list(l,{}) end
  inv:set_width('craft',2);inv:set_size('craft',4)
  for i,s in ipairs(spec.inventory or {}) do inv:set_stack('main',i,s) end
  local pos=spec.spawn or {0,99.51,0}
  p:set_pos({x=pos[1],y=pos[2],z=pos[3]});p:add_velocity(-p:get_velocity())
  p:set_look_horizontal(0);p:set_look_vertical(0);p:set_hp(spec.hp or 20);p:set_breath(spec.breath or 10)
  p:set_physics_override({speed=1,jump=1,gravity=1})
  if spec.physics then p:set_physics_override(spec.physics) end
  core.settings:set('fps_max',tostring(spec.fps or 60));core.settings:set('fps_max_unfocused',tostring(spec.fps or 60))
  core.set_timeofday(.5)
  if course_survival_fixture then course_survival_fixture(p,spec) end
  generation=generation+1;scenario=spec.id;active_spec=spec;phase_time=0;sequence=0
  write(p)
end
core.register_chatcommand('fixture',{func=function(name,param)
  local p=core.get_player_by_name(name)
  if name~='singleplayer' or not p then return false,'fixture only' end
  if param=='reset' then
    local spec
    local ok,err=pcall(function()
      local f=assert(io.open(root..'/request.json','r'));spec=core.parse_json(f:read('*a'));f:close();reset(p,spec)
    end)
    if not ok then
      core.safe_file_write(root..'/reset-error.json',core.write_json({id=type(spec)=='table' and spec.id or '',error=tostring(err)}))
      return false,'fixture reset rejected: '..tostring(err)
    end
  elseif param=='finish' then core.after(.2,function()core.request_shutdown('fixture shutdown',false,0)end)
  elseif param=='respawn' then p:set_hp(20);p:set_breath(10)
  end
  return true,'fixture '..param
end})
core.register_on_joinplayer(function(p)
  core.after(1,function()
    core.emerge_area({x=-32,y=88,z=-32},{x=32,y=118,z=32},function(_,_,remaining)
      if remaining==0 then core.after(.1,function()reset(p,{id='ready',trace=false})end) end
    end)
  end)
end)
local clock=0
core.register_globalstep(function(dt)
  local p=core.get_player_by_name('singleplayer');if not p then return end
  clock=clock+dt;phase_time=phase_time+dt;sequence=sequence+1
  for _,change in ipairs(active_spec.changes or {}) do
    if not change.done and phase_time>=change.at then
      for _,n in ipairs(change.nodes or {}) do node({x=n[1],y=n[2],z=n[3]},n[4],n[5]) end
      change.done=true
    end
  end
  if sequence%5==0 then write(p) end
  local f=active_spec.trace~=false and io.open(root..'/motion.jsonl','a')
  if f then
    f:write(core.write_json({time=clock,phase_time=phase_time,scenario=scenario,generation=generation,sequence=sequence,pos=p:get_pos(),velocity=p:get_velocity(),yaw=p:get_look_horizontal(),control=p:get_player_control(),hp=p:get_hp(),breath=p:get_breath()})..'\n');f:close()
  end
end)
