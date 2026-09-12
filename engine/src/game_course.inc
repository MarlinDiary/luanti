// SPDX-License-Identifier: LGPL-2.1-or-later
// Included in game.cpp: engine operations always execute on the game thread.
void Game::courseRelease(bool relinquish)
{
    m_course_released.insert(m_course_keys.begin(), m_course_keys.end());
    m_course_keys.clear(); m_course_pressed.clear(); m_course_steering.clear();
    m_course_attack_instance = 0; m_course_attack_id = 0;
    if (relinquish) {
        m_course_control.observe();
        input->clear();
    }
    CourseBridge::blockHumanInput(m_course_control.agent());
}

void Game::courseControlEvents()
{
    if (!m_course_control.enabled()) return;
    const auto escape = CourseBridge::manualEpoch();
    const auto manual = CourseBridge::toggleEpoch();
    if (escape != m_course_manual) {
        // Emergency stop has priority, including when a formspec owns focus.
        if (m_course_control.agent() || m_course_control.manual()) courseRelease(true);
        else m_course_control.observe(); // Keep native Esc available for the pause menu.
    } else if (manual != m_course_manual_toggle && !isMenuActive()
            && device->isWindowFocused()) {
        courseRelease(false);
        m_course_control.toggleManual();
        input->clear();
        CourseBridge::blockHumanInput(false);
        m_first_loop_after_window_activation = true;
    }
    m_course_manual = escape;
    m_course_manual_toggle = manual;
    // A human alt-tabbing away has not consented to automatic recapture later.
    if (m_course_control.manual() && !device->isWindowFocused()) courseRelease(true);
}

void Game::courseStep(CameraOrientation *cam, float dtime)
{
    if (!m_course) return;
    ++m_course_frame;
    const auto now = std::chrono::steady_clock::now();
    const uint64_t session = m_course->session();
    if (session != m_course_session) {
        // A read-only script arriving/leaving must not interrupt manual play.
        if (m_course_control.agent()) courseRelease(true);
        m_course_session = session;
    }
    auto *player = client->getEnv().getLocalPlayer();
    if (!player->getCAO()) return; // Initial object replication is still in flight.
    if (player->isDead() || (isMenuActive() && m_game_formspec.coursePaused())) courseRelease(true);
    if (now >= m_course_deadline || isMenuActive()) courseRelease(false);
    for (const auto &request : m_course->take()) {
        if (!session || request.session != session) continue;
        const auto &q = request.value;
        Json::Value r(Json::objectValue); r["id"] = q.get("id", Json::Value());
        r["protocol"] = 1; r["frame"] = Json::UInt64(m_course_frame);
        r["status"] = "submitted";
        try {
            auto integer = [&](const char *key, int low, int high) {
                if (!q[key].isInt() || q[key].asInt() < low || q[key].asInt() > high)
                    throw std::runtime_error(std::string("invalid_parameter:") + key);
                return q[key].asInt();
            };
            auto vec = [](v3f p) {
                Json::Value out(Json::arrayValue); out.append(p.X / BS); out.append(p.Y / BS); out.append(p.Z / BS); return out;
            };
            auto listJSON = [](const InventoryList *list) {
                Json::Value value, items(Json::arrayValue);
                value["width"] = list->getWidth(); value["size"] = list->getSize();
                if (list->getSize() > 4096) throw std::runtime_error("inventory_too_large");
                for (u32 i = 0; i < list->getSize(); ++i) {
                    const ItemStack &stack = list->getItem(i); Json::Value item;
                    ItemStack identity = stack; identity.count = stack.empty() ? 0 : 1;
                    item["stack_key"] = identity.getItemString();
                    item["name"] = stack.name; item["count"] = stack.count; item["wear"] = stack.wear; items.append(item);
                }
                value["items"] = items; return value;
            };
            if (!q["id"].isUInt64() || !q["op"].isString()) throw std::runtime_error("invalid_request");
            const std::string op = q["op"].asString();
            auto displayed = m_game_formspec.courseLists();
            const std::set<std::string> own_lists = {"main", "craft", "craftresult", "craftpreview", "armor", "offhand", "hand"};
            auto resolve = [&](const char *location, const char *list, const char *slot) {
                std::string where = q.get(location, "player").asString();
                if (!q[list].isString()) throw std::runtime_error("invalid_inventory_list");
                std::string name = q[list].asString(); InventoryLocation loc;
                loc.setCurrentPlayer(); int min_slot = 0, max_slot = 4095;
                if (where == "player") {
                    if (!own_lists.count(name) || name == "hand" || name == "craftpreview") throw std::runtime_error("inventory_list_not_writable");
                } else {
                    if (!q["form_id"].isUInt64() || q["form_id"].asUInt64() != m_game_formspec.courseFormId())
                        throw std::runtime_error("stale_form");
                    bool found = false;
                    for (size_t i = 0; i < displayed.size(); ++i) {
                        auto *shown = displayed[i];
                        if (where != "form:" + std::to_string(i) || name != shown->getListname()) continue;
                        loc = shown->getInventoryloc(); min_slot = shown->courseFirstSlot();
                        max_slot = shown->courseLastSlot(); found = true; break;
                    }
                    if (!found) throw std::runtime_error("inventory_not_in_open_form");
                }
                auto *inv = client->getInventory(loc);
                auto *items = inv ? inv->getList(name) : nullptr;
                if (!items) throw std::runtime_error("inventory_not_available");
                max_slot = std::min(max_slot, (int)items->getSize() - 1);
                int index = integer(slot, min_slot, max_slot);
                return std::make_tuple(loc, name, index);
            };
            if (op == "hello") {
                r["status"] = "ready"; r["course_version"] = "0.9.0"; r["engine_version"] = "5.17.0";
                r["capabilities"] = Json::Value(Json::arrayValue);
                for (const char *name : {"observe", "input", "look", "wield", "inventory_open", "inventory_close", "move_items", "craft", "drop", "chat", "screenshot", "acquire", "release", "stop", "respawn", "inspect_node", "steer", "item_entities", "steer_sneak", "swim_height", "independent_heading", "physics_swim", "steer_place", "collision_boxes", "movement_physics", "node_groups", "inspect_item", "living_entities", "hud_statbars", "hud_images", "attack", "weapon_stats", "local_hazards"}) r["capabilities"].append(name);
                r["observation_schema"] = 7; r["max_input_ms"] = 3000; r["max_observation_radius"] = 6; r["slot_base"] = 0;
            } else if (op == "observe") {
                int radius = q.isMember("radius") ? integer("radius", 0, 6) : 0;
                r["status"] = "snapshot"; r["position"] = vec(player->getPosition());
                r["eye"] = vec(player->getEyePosition()); r["velocity"] = vec(player->getSpeed());
                r["yaw"] = player->getYaw(); r["pitch"] = player->getPitch(); r["hp"] = player->hp;
                r["breath"] = player->getBreath(); r["climbing"] = player->is_climbing;
                r["in_liquid"] = player->in_liquid || player->in_liquid_stable;
                r["swim_height_active"] = m_course_steering.swim;
                r["touching_ground"] = player->touching_ground;
                const auto &physics = player->physics_override;
                r["physics"]["walk_speed"] = player->movement_speed_walk / BS * physics.speed_walk * physics.speed;
                r["physics"]["jump_speed"] = player->movement_speed_jump / BS * physics.jump;
                r["physics"]["gravity"] = 2 * player->movement_gravity / BS * physics.gravity;
                r["physics"]["air_acceleration"] = player->movement_acceleration_air * physics.acceleration_air * physics.speed;
                r["physics"]["ground_acceleration"] = player->movement_acceleration_default * physics.acceleration_default * physics.speed;
                r["physics"]["step_height"] = player->getCAO()->getStepHeight() / BS;
                const auto &player_box = player->getCAO()->getProperties().collisionbox;
                r["physics"]["collision_box"] = Json::Value(Json::arrayValue);
                for (float v : {player_box.MinEdge.X, player_box.MinEdge.Y, player_box.MinEdge.Z,
                        player_box.MaxEdge.X, player_box.MaxEdge.Y, player_box.MaxEdge.Z}) r["physics"]["collision_box"].append(v);
                r["dead"] = player->isDead(); r["wield"] = player->getWieldIndex();
                r["hotbar_size"] = player->hud_hotbar_itemcount;
                r["control"] = m_course_control.name();
                r["human_input_enabled"] = m_course_control.humanInput();
                r["cursor_visible"] = device->getCursorControl() && device->getCursorControl()->isVisible();
                r["control_epoch"] = Json::UInt64(m_course_control.epoch());
                r["input_active"] = !m_course_keys.empty();
                r["steering_active"] = m_course_steering.active;
                // Report the controller's own rate state. RPC arrival and
                // render-frame clocks are asynchronous, so deriving an
                // instantaneous rate from two observe replies is not sound.
                r["steering_yaw_velocity"] = m_course_steering.yaw_velocity;
                r["steering_pitch_velocity"] = m_course_steering.pitch_velocity;
                r["steering_speed"] = m_course_steering.speed;
#if USE_SOUND
                r["audio_enabled"] = bool(g_sound_manager_singleton);
#else
                r["audio_enabled"] = false;
#endif
                r["focused"] = device->isWindowFocused();
                r["menu_open"] = isMenuActive(); r["paused"] = m_game_formspec.coursePaused();
                r["inventory_revision"] = Json::UInt64(client->courseInventoryRevision());
                Json::Value inv(Json::objectValue);
                for (const auto *list : player->inventory.getLists()) if (own_lists.count(list->getName())) inv[list->getName()] = listJSON(list);
                r["inventory"] = inv;
                r["form"]["id"] = Json::UInt64(m_game_formspec.courseFormId());
                r["form"]["lists"] = Json::Value(Json::arrayValue);
                for (size_t i = 0; i < displayed.size(); ++i) {
                    auto *shown = displayed[i]; auto *container = client->getInventory(shown->getInventoryloc());
                    auto *list = container ? container->getList(shown->getListname()) : nullptr;
                    if (!list) continue;
                    Json::Value item = listJSON(list); item["location"] = "form:" + std::to_string(i);
                    item["name"] = shown->getListname(); item["first_slot"] = shown->courseFirstSlot(); item["last_slot"] = shown->courseLastSlot();
                    r["form"]["lists"].append(item);
                }
                if (runData.pointed_old.type == POINTEDTHING_NODE) {
                    v3s16 p = runData.pointed_old.node_undersurface;
                    Json::Value pos(Json::arrayValue); pos.append(p.X); pos.append(p.Y); pos.append(p.Z); r["pointed_node"] = pos;
                    p = runData.pointed_old.node_abovesurface;
                    Json::Value above(Json::arrayValue); above.append(p.X); above.append(p.Y); above.append(p.Z); r["pointed_above"] = above;
                }
                if (runData.pointed_old.type == POINTEDTHING_OBJECT) {
                    auto *obj = client->getEnv().getGenericCAO(runData.pointed_old.object_id);
                    if (obj) { r["pointed_entity"]["id"] = obj->getId();
                        r["pointed_entity"]["instance"] = Json::UInt64(obj->courseInstance()); }
                }
                r["hud_statbars"] = Json::Value(Json::arrayValue);
                for (const auto &element : player->hud.getElements()) {
                    if (!element || element->type != HUD_ELEM_STATBAR) continue;
                    Json::Value bar;
                    bar["texture"] = element->text.substr(0, 256);
                    bar["background"] = element->text2.substr(0, 256);
                    bar["number"] = element->number; bar["max"] = element->item;
                    r["hud_statbars"].append(bar);
                    if (r["hud_statbars"].size() >= 128) break;
                }
                // Export only textures already rendered on the local player's
                // HUD. This detects normal game status overlays without
                // exposing server metadata, Lua tables or arbitrary text.
                r["hud_images"] = Json::Value(Json::arrayValue);
                for (const auto &element : player->hud.getElements()) {
                    if (!element || element->type != HUD_ELEM_IMAGE) continue;
                    r["hud_images"].append(element->text.substr(0, 256)); if (r["hud_images"].size() >= 128) break;
                }
                r["csm_restrictions"] = Json::UInt64(client->getCSMRestrictionFlags());
                // Only replicated, visible, unattached item-shaped objects nearby.
                // A render item is a pickup candidate, not proof of a server item/count.
                r["entities"] = Json::Value(Json::arrayValue);
                r["entity_radius"] = 16;
                r["entities_truncated"] = false;
                r["item_entities"] = Json::Value(Json::arrayValue);
                r["entities_available"] = !client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_LOAD_CLIENT_MODS);
                if (r["entities_available"].asBool()) {
                    std::vector<DistanceSortedActiveObject> objects;
                    client->getEnv().getActiveObjects(player->getPosition(), 16 * BS, objects);
                    std::sort(objects.begin(), objects.end());
                    for (const auto &entry : objects) {
                        auto *obj = client->getEnv().getGenericCAO(entry.obj->getId());
                        if (!obj || obj == player->getCAO() || obj->getParent()) continue;
                        if (obj->isPlayer() && client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_READ_PLAYERINFO)) continue;
                        const auto &prop = obj->getProperties();
                        if (!prop.is_visible) continue;
                        aabb3f selection(v3f(0, 0, 0));
                        if (obj->getSelectionBox(&selection)) {
                            if (r["entities"].size() < 128) {
                                Json::Value entity;
                                entity["id"] = obj->getId();
                                entity["instance"] = Json::UInt64(obj->courseInstance());
                                entity["name"] = obj->getName().substr(0, 256);
                                entity["is_player"] = obj->isPlayer();
                                entity["pointable"] = prop.pointable == PointabilityType::POINTABLE;
                                entity["immortal"] = obj->isImmortal();
                                entity["position"] = vec(obj->getPosition());
                                entity["aim"] = vec(obj->getPosition() + selection.getCenter());
                                entity["velocity"] = vec(obj->getVelocity());
                                entity["hp"] = Json::nullValue; // client-predicted CAO HP is not server confirmation
                                r["entities"].append(entity);
                            } else r["entities_truncated"] = true;
                        }
                        if (obj->isPlayer() || prop.visual != OBJECTVISUAL_WIELDITEM ||
                                (obj->getPosition() - player->getPosition()).getLength() > 8 * BS) continue;
                        std::string item = prop.wield_item;
                        if (item.empty() && !prop.textures.empty()) item = prop.textures[0];
                        if (item.empty() || item.size() > 256) continue;
                        Json::Value value;
                        value["id"] = obj->getId(); value["item"] = item;
                        value["position"] = vec(obj->getPosition()); value["velocity"] = vec(obj->getVelocity());
                        r["item_entities"].append(value);

                    }
                }
                r["hazards"] = Json::Value(Json::arrayValue);
                if (r["entities_available"].asBool() && !client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_READ_NODEDEFS)) {
                    v3s16 p = floatToInt(player->getPosition() + v3f(0, .1f * BS, 0), BS);
                    for (int dy=-1; dy<=1; ++dy) {
                        v3s16 q = p + v3s16(0, dy, 0); bool known = false;
                        auto n = client->CSMGetNode(q, &known);
                        if (!known) continue;
                        const auto &d = nodedef_manager->get(n);
                        if (!d.damage_per_second) continue;
                        Json::Value h, pos(Json::arrayValue); pos.append(q.X); pos.append(q.Y); pos.append(q.Z);
                        h["position"] = pos; h["name"] = d.name; h["damage_per_second"] = d.damage_per_second;
                        r["hazards"].append(h);
                    }
                }
                r["weapons"] = Json::Value(Json::arrayValue);
                if (r["entities_available"].asBool() && !client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_READ_ITEMDEFS)) {
                    ItemStack selected, hand; player->getWieldedItem(&selected, &hand);
                    auto *main = player->inventory.getList("main");
                    if (main) for (u32 slot=0; slot<std::min<u32>(128, main->getSize()); ++slot) {
                        const auto &stack = main->getItem(slot);
                        const auto &tool = stack.empty() ? hand : stack;
                        const auto &caps = tool.getToolCapabilities(itemdef_manager, &hand);
                        Json::Value weapon; weapon["slot"] = slot; weapon["name"] = stack.name;
                        weapon["interval"] = caps.full_punch_interval;
                        weapon["usable"] = itemdef_manager->get(tool.name).usable;
                        weapon["damage_groups"] = Json::Value(Json::objectValue);
                        for (const auto &g : caps.damageGroups) weapon["damage_groups"][g.first] = g.second;
                        r["weapons"].append(weapon);
                    }
                }
                r["nodes"] = Json::Value(Json::arrayValue);
                r["node_defs"] = Json::Value(Json::objectValue);
                if (radius) {
                    if (client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_LOAD_CLIENT_MODS))
                        throw std::runtime_error("node_observation_restricted_by_server");
                    v3s16 origin = floatToInt(player->getPosition(), BS);
                    for (int x=-radius; x<=radius; ++x) for (int y=-radius; y<=radius; ++y) for (int z=-radius; z<=radius; ++z) {
                        v3s16 p = origin + v3s16(x,y,z); bool known = false;
                        MapNode node = client->CSMGetNode(p, &known); Json::Value item, pos(Json::arrayValue);
                        pos.append(p.X); pos.append(p.Y); pos.append(p.Z); item["position"] = pos; item["known"] = known;
                        if (known) {
                            const auto &def = nodedef_manager->get(node); item["name"] = def.name;
                            if (!client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_READ_NODEDEFS)) {
                                item["walkable"] = def.walkable; item["liquid"] = def.isLiquid();
                                auto &geometry = r["node_defs"][def.name];
                                geometry["groups"] = Json::Value(Json::objectValue);
                                for (const auto &group : def.groups) geometry["groups"][group.first] = group.second;
                                geometry["walkable"] = def.walkable; geometry["liquid"] = def.isLiquid();
                                geometry["damage_per_second"] = def.damage_per_second;
                                geometry["drowning"] = def.drowning; geometry["climbable"] = def.climbable;
                                geometry["buildable_to"] = def.buildable_to;
                                // Match MapNode::getCollisionBoxes' actual fallback.
                                const auto &box = def.collision_box.fixed.empty() ? def.node_box : def.collision_box;
                                geometry["full_cube"] = box.type == NODEBOX_REGULAR;
                                item["param2"] = node.param2;
                                item["collision_boxes"] = Json::Value(Json::arrayValue);
                                if (def.walkable) {
                                    bool geometry_known = true;
                                    if (def.drawtype == NDT_NODEBOX && def.node_box.type == NODEBOX_CONNECTED) {
                                        for (v3s16 offset : {v3s16(1,0,0),v3s16(-1,0,0),v3s16(0,1,0),
                                                v3s16(0,-1,0),v3s16(0,0,1),v3s16(0,0,-1)}) {
                                            bool neighbor_known = false;
                                            client->CSMGetNode(p + offset, &neighbor_known);
                                            geometry_known = geometry_known && neighbor_known;
                                        }
                                    }
                                    if (!geometry_known) {
                                        item.removeMember("collision_boxes");
                                        item["collision_geometry_known"] = false;
                                    } else {
                                    std::vector<aabb3f> boxes;
                                    node.getCollisionBoxes(nodedef_manager, &boxes,
                                        node.getNeighbors(p, &client->getEnv().getClientMap()));
                                    for (const auto &bounds : boxes) {
                                        Json::Value b(Json::arrayValue);
                                        for (float v : {bounds.MinEdge.X, bounds.MinEdge.Y, bounds.MinEdge.Z,
                                                bounds.MaxEdge.X, bounds.MaxEdge.Y, bounds.MaxEdge.Z}) b.append(v / BS);
                                        item["collision_boxes"].append(b);
                                    }
                                    }
                                }
                            }
                        }
                        r["nodes"].append(item);
                    }
                }
            } else if (op == "inspect_item") {
                if (client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_LOAD_CLIENT_MODS)
                        || client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_READ_NODEDEFS))
                    throw std::runtime_error("node_observation_restricted_by_server");
                if (!q["name"].isString() || q["name"].asString().size() > 256)
                    throw std::runtime_error("invalid_item_name");
                const auto &def = nodedef_manager->get(q["name"].asString());
                if (def.name != q["name"].asString()) throw std::runtime_error("unknown_node_item");
                const auto &box = def.collision_box.fixed.empty() ? def.node_box : def.collision_box;
                r["status"] = "snapshot"; r["name"] = def.name;
                r["full_cube"] = box.type == NODEBOX_REGULAR;
                r["walkable"] = def.walkable; r["liquid"] = def.isLiquid();
                r["damage_per_second"] = def.damage_per_second;
                r["groups"] = Json::Value(Json::objectValue);
                for (const auto &g : def.groups) r["groups"][g.first] = g.second;
            } else if (op == "inspect_node") {
                if (client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_LOAD_CLIENT_MODS)
                        || client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_READ_NODEDEFS))
                    throw std::runtime_error("node_observation_restricted_by_server");
                v3s16 pos(integer("x", -32760, 32760), integer("y", -32760, 32760), integer("z", -32760, 32760));
                if ((intToFloat(pos, BS) - player->getPosition()).getLength() > 8 * BS)
                    throw std::runtime_error("node_out_of_inspection_range");
                bool known = false; MapNode node = client->CSMGetNode(pos, &known);
                if (!known) throw std::runtime_error("node_not_loaded");
                const auto &def = nodedef_manager->get(node);
                r["status"] = "snapshot"; r["name"] = def.name;
                r["groups"] = Json::Value(Json::objectValue);
                for (const auto &g : def.groups) r["groups"][g.first] = g.second;
                ItemStack selected, hand; player->getWieldedItem(&selected, &hand);
                auto *main = player->inventory.getList("main");
                r["tools"] = Json::Value(Json::arrayValue);
                if (main) for (u32 slot = 0; slot < std::min<u32>(main->getSize(), 128); ++slot) {
                    const auto &stack = main->getItem(slot);
                    const auto &tool = stack.empty() ? hand : stack;
                    DigParams params = getDigParams(def.groups, &tool.getToolCapabilities(itemdef_manager, &hand), tool.wear);
                    if (!params.diggable) params = getDigParams(def.groups, &hand.getToolCapabilities(itemdef_manager));
                    Json::Value candidate; candidate["slot"] = slot; candidate["name"] = stack.name;
                    candidate["diggable"] = params.diggable; candidate["time"] = params.time;
                    r["tools"].append(candidate);
                }
            } else if (op == "stop") { courseRelease(false);
            } else if (op == "release") { if (!m_course_control.manual()) courseRelease(true);
            } else if (op == "acquire") {
                if (m_course_control.manual()) throw std::runtime_error("manual_control_active");
                if (isMenuActive()) throw std::runtime_error("close_menu_before_acquire");
                if (player->isDead()) throw std::runtime_error("player_dead");
                if (!q["control_epoch"].isUInt64() || q["control_epoch"].asUInt64() != m_course_control.epoch())
                    throw std::runtime_error("stale_control_epoch");
                courseRelease(false);
                if (!m_course_control.acquire(q["control_epoch"].asUInt64())) throw std::runtime_error("stale_control_epoch");
                input->clear();
                CourseBridge::blockHumanInput(true);
                // Agent mode must not inherit previously toggled continuous movement.
                g_settings->setBool("continuous_forward", false);
            } else if (op == "screenshot") {
                client->makeScreenshot();
            } else if (op == "respawn") {
                if (!player->isDead()) throw std::runtime_error("player_not_dead");
                courseRelease(true);
                // Modern servers use their displayed death formspec's handler.
                // The legacy packet alone is ignored by those servers.
                if (m_game_formspec.courseFormId()) m_game_formspec.courseClose();
                else client->sendRespawnLegacy();
            } else {
                if (!m_course_control.agent() || !q["control_epoch"].isUInt64() || q["control_epoch"].asUInt64() != m_course_control.epoch())
                    throw std::runtime_error("control_released");
                if (player->isDead()) throw std::runtime_error("player_dead");
                if (op == "attack") {
                    if (isMenuActive()) throw std::runtime_error("close_menu_before_input");
                    if (client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_LOAD_CLIENT_MODS))
                        throw std::runtime_error("entity_observation_restricted_by_server");
                    int id = integer("target_id", 1, 65535);
                    auto *target = client->getEnv().getGenericCAO(id);
                    if (!q["instance"].isUInt64() || !target || target->courseInstance() != q["instance"].asUInt64())
                        throw std::runtime_error("stale_entity");
                    if (target->isPlayer()) throw std::runtime_error("player_target_excluded");
                    if (runData.pointed_old.type != POINTEDTHING_OBJECT || runData.pointed_old.object_id != id)
                        throw std::runtime_error("entity_not_in_crosshair");
                    courseRelease(false);
                    m_course_attack_id = id; m_course_attack_instance = target->courseInstance();
                    m_course_keys.insert(KeyType::DIG); m_course_pressed.insert(KeyType::DIG);
                    m_course_deadline = now + std::chrono::milliseconds(100);
                } else if (op == "steer") {
                    m_course_attack_instance = 0;
                    if (isMenuActive()) throw std::runtime_error("close_menu_before_input");
                    int ms = integer("duration_ms", 1, 1000);
                    if (!q["heading"].isNumeric() || !std::isfinite(q["heading"].asDouble()) || std::abs(q["heading"].asDouble())>36000
                            || !q["speed"].isNumeric() || !std::isfinite(q["speed"].asDouble()) || q["speed"].asDouble()<0 || q["speed"].asDouble()>1
                            || (q.isMember("swim_y") && (!q["swim_y"].isNumeric() || !std::isfinite(q["swim_y"].asDouble()) || std::abs(q["swim_y"].asDouble())>32760))
                            || (q.isMember("move_heading") && (!q["move_heading"].isNumeric() || !std::isfinite(q["move_heading"].asDouble()) || std::abs(q["move_heading"].asDouble())>36000))
                            || (q.isMember("place") && !q["place"].isBool())
                            || !q["jump"].isBool() || (q.isMember("sneak") && !q["sneak"].isBool())
                            || (q.isMember("pitch") && (!q["pitch"].isNumeric() || !std::isfinite(q["pitch"].asDouble()) || std::abs(q["pitch"].asDouble())>89.9))) throw std::runtime_error("invalid_steering");
                    std::set<GameKeyType> keys;
                    if (q["speed"].asFloat()>0) keys.insert(KeyType::FORWARD);
                    if (q["jump"].asBool()) keys.insert(KeyType::JUMP);
                    if (q.get("sneak",false).asBool()) keys.insert(KeyType::SNEAK);
                    if (q.get("place",false).asBool()) keys.insert(KeyType::PLACE);
                    for (auto k:m_course_keys) if (!keys.count(k)) m_course_released.insert(k);
                    for (auto k:keys) if (!m_course_keys.count(k)) m_course_pressed.insert(k);
                    m_course_keys=std::move(keys); m_course_deadline=now+std::chrono::milliseconds(ms);
                    m_course_steering.swim=q.isMember("swim_y"); m_course_steering.swim_y=q.get("swim_y",0).asFloat();
                    m_course_steering.active=true; m_course_steering.heading=q["heading"].asFloat();
                    m_course_steering.move_heading=q.get("move_heading",q["heading"]).asFloat();
                    m_course_steering.pitch=q.get("pitch",0).asFloat(); m_course_steering.speed=q["speed"].asFloat();
                } else if (op == "input") {
                    m_course_attack_instance = 0;
                    m_course_steering.clear();
                    if (isMenuActive()) throw std::runtime_error("close_menu_before_input");
                    int ms = integer("duration_ms", 1, 3000);
                    if (!q["keys"].isArray() || q["keys"].size()>9) throw std::runtime_error("invalid_keys");
                    const std::map<std::string,GameKeyType> names = {{"forward",KeyType::FORWARD},{"backward",KeyType::BACKWARD},{"left",KeyType::LEFT},{"right",KeyType::RIGHT},{"jump",KeyType::JUMP},{"aux1",KeyType::AUX1},{"sneak",KeyType::SNEAK},{"dig",KeyType::DIG},{"place",KeyType::PLACE}};
                    std::set<GameKeyType> keys;
                    for (const auto &v:q["keys"]) {
                        if (!v.isString() || !names.count(v.asString())) throw std::runtime_error("unknown_key");
                        keys.insert(names.at(v.asString()));
                    }
                    for (auto k:m_course_keys) if (!keys.count(k)) m_course_released.insert(k);
                    for (auto k:keys) if (!m_course_keys.count(k)) m_course_pressed.insert(k);
                    m_course_keys=std::move(keys); m_course_deadline=now+std::chrono::milliseconds(ms);
                } else if (op == "look") {
                    if (!q["yaw"].isNumeric() || !q["pitch"].isNumeric() || !std::isfinite(q["yaw"].asDouble()) || !std::isfinite(q["pitch"].asDouble()) || std::abs(q["yaw"].asDouble())>36000 || std::abs(q["pitch"].asDouble())>89.9) throw std::runtime_error("invalid_orientation");
                    m_course_steering.clear();
                    cam->camera_yaw=q["yaw"].asFloat(); cam->camera_pitch=q["pitch"].asFloat();
                } else if (op == "wield") {
                    auto *main=player->inventory.getList("main");
                    if (!main) throw std::runtime_error("inventory_not_available");
                    int slot=integer("slot",0,std::min((int)main->getSize(),player->hud_hotbar_itemcount)-1);
                    runData.new_playeritem=slot; client->setPlayerItem(slot);
                } else if (op == "inventory_open") {
                    courseRelease(false); m_game_formspec.showPlayerInventory(nullptr);
                } else if (op == "inventory_close") {
                    if (m_game_formspec.coursePaused()) throw std::runtime_error("manual_pause_active");
                    m_game_formspec.courseClose();
                } else if (op == "move_items") {
                    int count=integer("count",1,99);
                    auto from=resolve("from_inventory","from_list","from_slot"), to=resolve("to_inventory","to_list","to_slot");
                    if (std::get<1>(to)=="craftresult") throw std::runtime_error("craft_result_is_output");
                    auto action=std::make_unique<IMoveAction>(); action->count=count;
                    std::tie(action->from_inv,action->from_list,action->from_i)=from;
                    std::tie(action->to_inv,action->to_list,action->to_i)=to;
                    client->inventoryAction(action.release());
                } else if (op == "drop") {
                    int count=integer("count",1,99); auto from=resolve("from_inventory","from_list","from_slot");
                    auto action=std::make_unique<IDropAction>(); action->count=count;
                    std::tie(action->from_inv,action->from_list,action->from_i)=from; client->inventoryAction(action.release());
                } else if (op == "craft") {
                    int count=integer("count",1,64);
                    if (!player->inventory.getList("craft")) throw std::runtime_error("craft_grid_unavailable");
                    auto action=std::make_unique<ICraftAction>(); action->count=count; action->craft_inv.setCurrentPlayer(); client->inventoryAction(action.release());
                } else if (op == "chat") {
                    if (client->checkCSMRestrictionFlag(CSMRestrictionFlags::CSM_RF_CHAT_MESSAGES)) throw std::runtime_error("chat_restricted_by_server");
                    if (!q["text"].isString() || q["text"].asString().size()>256 || q["text"].asString().find_first_of("\r\n")!=std::string::npos) throw std::runtime_error("invalid_chat");
                    client->sendChatMessage(utf8_to_wide(q["text"].asString()));
                } else throw std::runtime_error("unknown_operation");
            }
        } catch (const std::exception &e) { r["status"]="error"; r["error"]=e.what(); }
        r["control_epoch"] = Json::UInt64(m_course_control.epoch());
        m_course->reply(request.session,r);
    }
    m_course_steering.step(cam->camera_yaw, cam->camera_pitch, dtime);
    if (m_course_label) {
        const wchar_t *label = m_course_control.agent()
            ? L"AGENT | Mouse free | Esc: stop | F8: manual"
            : m_course_control.manual() ? L"MANUAL | Esc / F8: stop and free mouse"
            : L"WATCHING | Mouse free | F8: manual play";
        m_course_label->setText(label); m_course_label->setVisible(!isMenuActive());
        m_course_label->setRelativePosition(core::rect<s32>(12, 8,
            (s32)driver->getScreenSize().Width - 12, g_fontengine->getTextHeight() + 16));
    }
}
