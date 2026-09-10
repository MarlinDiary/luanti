-- Local-only survival validation. Never included in the shipped client or SDK.
assert(core.settings:get_bool('course_test_fixture'))
local root=core.get_worldpath()
local tracked={}
local function record(event, fields)
  fields=fields or {};fields.event=event;fields.time=core.get_us_time()/1e6
  local f=assert(io.open(root..'/survival.jsonl','a'));f:write(core.write_json(fields)..'\n');f:close()
end
core.register_entity('persistent_fixture:target',{
 initial_properties={physical=true,collide_with_objects=true,collisionbox={-.3,0,-.3,.3,1.8,.3},
  selectionbox={-.3,0,-.3,.3,1.8,.3},visual='cube',textures={'default_stone.png','default_stone.png','default_stone.png','default_stone.png','default_stone.png','default_stone.png'},hp_max=20},
 on_activate=function(self)self.object:set_armor_groups({fleshy=100});self.object:set_acceleration({x=0,y=-9.81,z=0}) end,
 on_punch=function(self,puncher,interval,tool,dir,damage)
  record('punch',{damage=damage,hp=self.object:get_hp(),player=puncher and puncher:get_player_name()})
  local obj=self.object
  core.after(.01,function()if obj:get_pos() and obj:get_hp()<=0 then record('target_dead');obj:remove() end end)
 end,
 on_step=function(self,dt)
  if not self.config then return end
  local p=core.get_player_by_name('singleplayer');if not p then return end
  local pos=self.object:get_pos();local d=vector.subtract(p:get_pos(),pos);local len=vector.length(d)
  if self.config.chase and len>.8 then
   local v=vector.multiply(vector.normalize(d),self.config.speed or 2);v.y=self.object:get_velocity().y;self.object:set_velocity(v)
  end
  self.timer=(self.timer or 0)+dt
  if self.config.damage and len<3 and self.timer>1 then
   self.timer=0;p:punch(self.object,1,{full_punch_interval=1,damage_groups={fleshy=self.config.damage}},vector.normalize(d));record('incoming_damage',{hp=p:get_hp()})
  end
 end,
})
function course_survival_fixture(p,spec)
 tracked={}
 mcl_hunger.set_hunger(p,spec.hunger or 20,true);mcl_hunger.set_saturation(p,0)
 if spec.night then core.set_timeofday(0) end
 for _,t in ipairs(spec.entities or {}) do
  assert(core.registered_entities[t.name],'unknown entity')
  local obj=core.add_entity({x=t.position[1],y=t.position[2],z=t.position[3]},t.name)
  assert(obj,'entity spawn failed');tracked[#tracked+1]=obj
  local ent=obj:get_luaentity();if t.name=='persistent_fixture:target' then ent.config=t end
 end
 record('reset',{id=spec.id,hunger=spec.hunger or 20,entities=#tracked})
end
