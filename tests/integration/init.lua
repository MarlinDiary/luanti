-- Isolated local test instrumentation. Never distributed as student control API.
-- Fixtures grant materials / place blocks explicitly; no progression claim.
local dir = core.get_worldpath()
local scenario = "initial"
local timer = 0
-- Prepare the platform during generation, before the client ever receives it.
-- This removes the earlier spike's spawn-into-empty-air race; damage stays on.
core.register_on_generated(function(minp,maxp)
  if minp.y <= 99 and maxp.y >= 99 then
    for x=math.max(-8,minp.x),math.min(8,maxp.x) do
      for z=math.max(-8,minp.z),math.min(12,maxp.z) do
        core.set_node({x=x,y=99,z=z},{name="mcl_core:stone"})
      end
    end
  end
end)
local function snapshot(p)
  if not p then return end
  local inv = p:get_inventory()
  local lists = {}
  for name, items in pairs(inv:get_lists()) do
    lists[name] = {width=inv:get_width(name), items={}}
    for _, item in ipairs(items) do
      table.insert(lists[name].items, {name=item:get_name(), count=item:get_count(), wear=item:get_wear()})
    end
  end
  local s = {scenario=scenario, position=p:get_pos(), inventory=lists,
    armor_points=p:get_meta():get_int("mcl_armor:armor_points"),
    wield=p:get_wield_index()-1, wield_name=p:get_wielded_item():get_name(),
    dig_node=core.get_node({x=0,y=102,z=3}).name,
    controls=p:get_player_control(), us=core.get_us_time()}
  core.safe_file_write(dir.."/authoritative.json", core.write_json(s))
  return s
end
local function event(kind, detail)
  local f=io.open(dir.."/events.jsonl", "a")
  if f then f:write(core.write_json({kind=kind, detail=detail, us=core.get_us_time()}).."\n"); f:close() end
end
local function reset(p, name)
  scenario=name
  for x=-8,8 do for z=-8,12 do
    core.set_node({x=x,y=99,z=z}, {name="mcl_core:stone"})
    for y=100,105 do core.set_node({x=x,y=y,z=z}, {name="air"}) end
  end end
  core.set_node({x=0,y=102,z=3}, {name="mcl_core:dirt"})
  core.set_node({x=2,y=100,z=3}, {name="mcl_crafting_table:crafting_table"})
  p:set_pos({x=0,y=99.51,z=0}); p:set_look_horizontal(0); p:set_look_vertical(0)
  p:set_hp(20); core.set_timeofday(0.5)
  local inv=p:get_inventory()
  for _,list in ipairs({"main","craft","craftresult","armor"}) do inv:set_list(list,{}) end
  inv:set_width("craft",2); inv:set_size("craft",4)
  p:get_meta():set_int("mcl_armor:armor_points",0)
  inv:set_stack("main",1,"mcl_core:wood 12")
  inv:set_stack("main",2,"mcl_core:stick 4")
  inv:set_stack("main",3,"mcl_armor:helmet_iron")
  inv:set_stack("main",4,"mcl_tools:shovel_wood")
  event("fixture_reset",snapshot(p)); core.log("action","CONTROL_PROBE_READY "..name)
end
core.register_on_joinplayer(function(p)
  core.after(1,function()
    core.emerge_area({x=-16,y=96,z=-16},{x=16,y=111,z=16},function(_,_,remaining)
      if remaining==0 then core.after(0.1,function() reset(p,"ready") end) end
    end)
  end)
end)
core.register_chatcommand("probe", {func=function(name,param)
  local p=core.get_player_by_name(name)
  if not p or name~="singleplayer" then return false end
  if param=="finish" then event("finish",snapshot(p)); core.request_shutdown("probe finished",false,0)
  elseif param:match("^reset [%w_-]+$") then reset(p,param:sub(7))
  else event("checkpoint",snapshot(p)) end
  return true,"probe "..param
end})
core.register_globalstep(function(dt)
  timer=timer+dt
  if timer>=0.2 then timer=0; snapshot(core.get_player_by_name("singleplayer")) end
end)
core.register_on_dignode(function(pos, oldnode, p) event("dig", {position=pos,node=oldnode.name,player=p and p:get_player_name()}) end)
core.register_on_craft(function(item,p) event("craft", {item=item:to_string(),player=p:get_player_name()}) end)
core.register_on_player_inventory_action(function(p,action,inv,info) event("inventory_action", {action=action,info=info}) end)
core.after(180,function() core.request_shutdown("probe hard timeout",false,0) end)
