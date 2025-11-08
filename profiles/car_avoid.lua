-- car_avoid.lua — stock car with a penalty hook for avoid zones

api_version = 4

-- Import base car profile
local car_base = require('car')

function setup()
  -- Start with base car profile setup
  return car_base.setup()
end

function process_node(profile, node, result)
  -- Use base car profile's node processor
  return car_base.process_node(profile, node, result)
end

function process_way(profile, way, result, relations)
  -- Process the way using base car profile
  car_base.process_way(profile, way, result, relations)

  -- Penalty hook for avoid zones
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
  -- Use base car profile's turn processor
  return car_base.process_turn(profile, turn)
end

return {
  setup = setup,
  process_way = process_way,
  process_node = process_node,
  process_turn = process_turn
}
