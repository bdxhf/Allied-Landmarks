-- The DB assigns one slot set per supported Immortal Empires region.
-- The pack builder inserts the region and availability tables above these functions.
local function has_access(faction, region)
    if region:is_abandoned() then return false end
    local owner = region:owning_faction()
    return owner:name() ~= faction:name() and
        (faction:defensive_allies_with(owner) or faction:military_allies_with(owner) or owner:is_vassal_of(faction))
end

local last_site_message = {}
local selected_site
local last_picker_message
local function report_site(region, message)
    local name = region:name()
    if last_site_message[name] ~= message then
        ModLog("[allied_landmarks] " .. name .. ": " .. message)
        last_site_message[name] = message
    end
end

local function offer_landmark(context)
    local faction = cm:get_local_faction(true)
    local region = context:garrison_residence():region()
    local site = landmark_regions[region:name()]
    selected_site = site and region:name() or nil
    if not site then return end
    if not has_access(faction, region) then
        report_site(region, "no qualifying treaty with current owner")
        return
    end
    local managers = region:foreign_slot_managers()
    for i = 0, managers:num_items() - 1 do
        local existing = managers:item_at(i)
        if existing:faction():name() == faction:name() and not allied_outposts[existing:slot_set_key()] then
            if existing:slot_set_key() == site.key then
                report_site(region, "landmark slot present")
            else
                report_site(region, "other foreign slot retained: " .. existing:slot_set_key())
            end
            return
        end
    end

    for _, rule in ipairs(site.rules) do
        if (not rule[1] or rule[1] == faction:culture()) and
           (not rule[2] or rule[2] == faction:subculture()) and
           (not rule[3] or rule[3] == faction:name()) then
            local manager = cm:add_foreign_slot_set_to_region_for_faction(faction:command_queue_index(), region:cqi(), site.key)
            if manager and not manager:is_null_interface() and manager:slot_set_key() == site.key then
                report_site(region, "created landmark slot; slots=" .. manager:slots():num_items())
            else
                report_site(region, "engine did not return requested slot set: " .. site.key)
            end
            return
        end
    end
    report_site(region, "no eligible buildings for " .. faction:name())
end

-- Read the actual UI slot hovered by the player. A region CQI is not a UI slot ID.
local function report_picker(context)
    if not selected_site then return end
    local slot = UIComponent(context.component):GetContextObject("CcoCampaignBuildingSlot")
    if not slot or slot:Call("ForeignSlotSetKey") ~= landmark_regions[selected_site].key then return end
    local message = selected_site .. ": panel empty=" .. tostring(slot:Call("IsEmpty"))
        .. ", categories=" .. tostring(slot:Call("PossibleBuildingSetList.Size"))
        .. ", chains=" .. tostring(slot:Call("PossibleBuildingChainsList.Size"))
    if message ~= last_picker_message then
        ModLog("[allied_landmarks] " .. message)
        last_picker_message = message
    end
end

local function revoke_landmarks()
    local faction = cm:get_local_faction(true)
    local managers = faction:foreign_slot_managers()
    local remove = {}
    for i = 0, managers:num_items() - 1 do
        local manager = managers:item_at(i)
        local region = manager:region()
        local site = landmark_regions[region:name()]
        if site and manager:slot_set_key() == site.key and not has_access(faction, region) then
            remove[#remove + 1] = {region:cqi(), site.key}
        end
    end
    for _, entry in ipairs(remove) do
        cm:remove_faction_foreign_slots_from_region(faction:command_queue_index(), entry[1], entry[2])
    end
end

-- The native building applies the builder's half. The second half originates
-- in the host region, so "yours" resolves to its real owner. The engine handles
-- geographic range, unit/character filters and movement for both halves.
local host_bundle = "alm9_host_local"
local previous = {}
local function sync_host_bonuses()
    local tracked = cm:get_saved_value("alm9_host_regions") or {}
    local active = {}
    local faction = cm:get_local_faction(true)
    local managers = faction:foreign_slot_managers()
    for i = 0, managers:num_items() - 1 do
        local manager = managers:item_at(i)
        local region = manager:region()
        local name = region:name()
        local site = landmark_regions[name]
        if site and site.key == manager:slot_set_key() and has_access(faction, region) then
            local slots = manager:slots()
            for j = 0, slots:num_items() - 1 do
                local slot = slots:item_at(j)
                local markers = slot:has_building() and host_buildings[slot:building()]
                if markers then
                    local values = {}
                    local signature = {region:owning_faction():name(), slot:building()}
                    for _, id in ipairs(markers) do
                        local value = cm:get_regions_bonus_value(region, id)
                        if type(value) == "number" and value ~= 0 then
                            values[id] = value
                            signature[#signature + 1] = id .. "=" .. tostring(value)
                        end
                    end
                    if next(values) then
                        active[name] = true
                        local current = table.concat(signature, "|")
                        if previous[name] ~= current or not region:has_effect_bundle(host_bundle) then
                            local bundle = cm:create_new_custom_effect_bundle(host_bundle)
                            bundle:set_duration(0)
                            for _, id in ipairs(markers) do
                                if values[id] then
                                    bundle:add_effect(host_values[id][1], host_values[id][2], values[id])
                                end
                            end
                            cm:apply_custom_effect_bundle_to_region(bundle, region)
                            previous[name] = current
                        end
                    end
                end
            end
        end
    end
    local changed = false
    for name in pairs(tracked) do
        if not active[name] then
            local region = cm:get_region(name)
            if region and region:has_effect_bundle(host_bundle) then
                cm:remove_effect_bundle_from_region(host_bundle, name)
            end
            previous[name] = nil
            changed = true
        end
    end
    for name in pairs(active) do
        if not tracked[name] then changed = true end
    end
    if changed then cm:set_saved_value("alm9_host_regions", active) end
end

local refresh_pending = false
local function refresh_after_model_update()
    if refresh_pending then return end
    refresh_pending = true
    cm:callback(function()
        refresh_pending = false
        sync_host_bonuses()
    end, 0.1)
end

cm:add_first_tick_callback(function()
    -- The campaign manager can be named "main_warhammer" on both IE and IEE.
    -- The generated region keys already restrict creation to supported settlements.
    if cm:is_multiplayer() or not cm:has_local_faction() then return end
    ModLog("[allied_landmarks] campaign ready: " .. cm:get_campaign_name() .. ", faction=" .. cm:get_local_faction(true):name())
    core:add_listener("alm_select_site", "SettlementSelected", true, offer_landmark, true)
    core:add_listener("alm_picker_state", "ComponentMouseOn", function()
        return selected_site ~= nil
    end, report_picker, true)
    core:add_listener("alm_order_issued", "ForeignSlotBuildingConstructionIssued", function(context)
        return string.sub(context:building(), 1, 5) == "alm9_"
    end, function(context)
        ModLog("[allied_landmarks] queued " .. context:building() .. " at " .. context:slot():slot_manager():region():name())
    end, true)
    core:add_listener("alm_builder_item", "ForeignSlotBuildingCompleteEvent", true, function(context)
        local reward = landmark_rewards[context:building()]
        if not reward then return end
        local manager = context:slot_manager()
        local region = manager:region()
        local site = landmark_regions[region:name()]
        if not site or manager:slot_set_key() ~= site.key or not has_access(manager:faction(), region) then return end
        if cm:get_saved_value(reward.flag) == nil then
            cm:add_ancillary_to_faction(manager:faction(), reward.item, reward.silent)
            cm:set_saved_value(reward.flag, true)
        end
    end, true)
    for _, event in ipairs({"NegativeDiplomaticEvent", "PositiveDiplomaticEvent", "RegionFactionChangeEvent", "FactionTurnStart"}) do
        core:add_listener("alm_review_" .. event, event, true, function()
            revoke_landmarks()
            refresh_after_model_update()
        end, true)
    end
    for _, event in ipairs({"ForeignSlotBuildingCompleteEvent", "ForeignSlotBuildingDismantledEvent",
            "ForeignSlotManagerRemovedEvent", "BattleCompleted", "ResearchCompleted", "SettlementSelected"}) do
        core:add_listener("alm_host_" .. event, event, true, refresh_after_model_update, true)
    end
    revoke_landmarks()
    sync_host_bonuses()
end)
