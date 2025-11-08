-- car_avoid.lua — stock car with a penalty hook
api_version = 4
local WayHandlers = require('lib/way_handlers')

local car = require('profiles/car')
local profile = {
  properties = {
    weight_name = 'routability',
    max_speed_for_map_matching = 180/3.6,
    weight_precision = 1
  },

  default_mode = mode.driving,
  default_speed = 10,
  oneway_handling = true,
  turn_handling = true,

  speeds = car.speeds,
  road_classification = car.road_classification,
  access_tag_blacklist = car.access_tag_blacklist,
  access_tag_whitelist = car.access_tag_whitelist,
  restricted_access_tag_list = car.restricted_access_tag_list,
  restricted_highway_whitelist = car.restricted_highway_whitelist,
  service_tag_forbidden = car.service_tag_forbidden,
  construction_whitelist = car.construction_whitelist,
  barrier_whitelist = car.barrier_whitelist,
  access_tags_hierachy = car.access_tags_hierachy,
  surface_speeds = car.surface_speeds,
  tracktype_speeds = car.tracktype_speeds,
  smoothness_speeds = car.smoothness_speeds,
  max_speed_for_map_matching = car.max_speed_for_map_matching
}

function process_node(profile, node, result)
  result.barrier = WayHandlers.node_barrier(profile, node)
  result.traffic_lights = WayHandlers.traffic_lights(node)
end

function process_way(profile, way, result, relations)
  local data = WayHandlers.get_data(way)
  local handlers = WayHandlers.get_handlers(profile)
  WayHandlers.run(profile, way, result, data, handlers, relations)

  -- Penalty hook
  local az = way:get_value_by_key('avoid_zone')
  if az == 'yes' then
    local f = tonumber(way:get_value_by_key('avoid_factor')) or 0.05
    if f < 0.01 then f = 0.01 end
    if f > 0.99 then f = 0.99 end
    if result.forward_mode ~= mode.inaccessible and result.forward_speed and result.forward_speed > 0 then
      result.forward_speed  = math.max(1, result.forward_speed  * f)
    end
    if result.backward_mode ~= mode.inaccessible and result.backward_speed and result.backward_speed > 0 then
      result.backward_speed = math.max(1, result.backward_speed * f)
    end
  end
end

function process_turn(profile, turn)
  WayHandlers.process_turn(profile, turn)
end

return profile
