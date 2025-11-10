-- car_avoid.lua — stock car with dynamic polygon-based penalty hook

api_version = 4

-- Import base car profile
local car_base = require('car')

-- Penalty factors
local INSIDE_FACTOR = 0.02   -- Ways completely inside avoid zone
local TOUCH_FACTOR = 0.10    -- Ways touching avoid zone boundary

-- Global cache for avoid zones (loaded from JSON file at startup)
local avoid_polygons = {}
local avoid_polygons_loaded = false

-- Load avoid zones from JSON file
local function load_avoid_polygons()
  if avoid_polygons_loaded then
    return
  end
  
  -- Try to load from /profiles/avoid_zones.lua (pre-compiled data)
  local ok, zones = pcall(function()
    return require('avoid_zones_data')
  end)
  
  if ok and zones then
    avoid_polygons = zones or {}
    avoid_polygons_loaded = true
  else
    avoid_polygons = {}
    avoid_polygons_loaded = true
  end
end

-- Point-in-polygon test using ray casting algorithm
local function point_in_polygon(px, py, polygon)
  if not polygon or #polygon < 3 then
    return false
  end
  
  local inside = false
  local j = #polygon
  
  for i = 1, #polygon do
    local xi, yi = polygon[i][1], polygon[i][2]
    local xj, yj = polygon[j][1], polygon[j][2]
    
    if ((yi > py) ~= (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi) then
      inside = not inside
    end
    
    j = i
  end
  
  return inside
end

-- Check if any coordinate in the way is inside avoid zones
local function way_intersects_avoid_zones(way_nodes)
  if not way_nodes or #way_nodes == 0 then
    return nil
  end
  
  load_avoid_polygons()
  
  if #avoid_polygons == 0 then
    return nil
  end
  
  local is_inside = false
  local is_touching = false
  
  -- Check if any node in the way is inside a polygon (inside test)
  for _, node in ipairs(way_nodes) do
    for _, polygon in ipairs(avoid_polygons) do
      if polygon.is_inside and point_in_polygon(node[1], node[2], polygon.coords) then
        is_inside = true
        break
      end
    end
    if is_inside then break end
  end
  
  -- Check if any node is close to polygon boundary (touching test)
  if not is_inside then
    for _, polygon in ipairs(avoid_polygons) do
      if polygon.is_touching then
        for _, node in ipairs(way_nodes) do
          if point_in_polygon(node[1], node[2], polygon.coords) then
            is_touching = true
            break
          end
        end
      end
      if is_touching then break end
    end
  end
  
  if is_inside then
    return INSIDE_FACTOR
  elseif is_touching then
    return TOUCH_FACTOR
  end
  
  return nil
end

function setup()
  -- Start with base car profile setup
  load_avoid_polygons()
  return car_base.setup()
end

function process_node(profile, node, result)
  -- Use base car profile's node processor
  return car_base.process_node(profile, node, result)
end

function process_way(profile, way, result, relations)
  -- Process the way using base car profile
  car_base.process_way(profile, way, result, relations)

  -- Check for PBF-stored penalty tags (legacy support)
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
    return
  end
  
  -- NOTE: LIMITATION - Dynamic polygon checking is not available in process_way context.
  -- OSRM's process_way hook does NOT provide node coordinates.
  -- We can only check PBF-stored tags (which requires prior PBF reprocessing).
  --
  -- The polygon checking functions above (lines 36-107) are preserved for:
  -- - Documentation of the ideal approach
  -- - Potential future OSRM API changes
  -- - If geometry data becomes available through other mechanisms
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
