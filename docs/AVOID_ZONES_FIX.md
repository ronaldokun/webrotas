# Avoid Zones Implementation Fix

## Problem Identified

The avoid zones functionality was **not working** because the PBF reprocessing logic was **completely disabled** in `app.py`. This meant:

1. ✅ Polygon configurations were being saved
2. ✅ OSRM container was being restarted
3. ❌ **The PBF file was NOT being modified with penalty tags**
4. ❌ **Routes were never affected by the avoid zones**

## Root Cause

The Lua profile (`car_avoid.lua`) cannot dynamically check if a way intersects with polygons because:
- OSRM's `process_way()` hook does NOT provide node coordinates
- The Lua profile can only read tags that were already in the PBF file
- Without reprocessing the PBF to add `avoid_zone` and `avoid_factor` tags, the profile has no data to work with

## Implementation Details

### How Penalty Application Works

The system uses a **two-stage approach**:

#### Stage 1: PBF Reprocessing (Python)
The `cutter.py` module implements `Penalizer`, an OSM handler that:
1. Loads polygon geometries from GeoJSON
2. Scans all highway ways in the PBF file
3. Uses shapely's STRtree for efficient spatial indexing
4. For each way:
   - If completely inside a polygon → apply `INSIDE_FACTOR` (0.02, very restrictive)
   - If touching/crossing polygon boundary → apply `TOUCH_FACTOR` (0.10, moderate)
5. Writes modified PBF with `avoid_zone=yes` and `avoid_factor` tags

#### Stage 2: OSRM Reprocessing
After PBF modification:
1. Run `osrm-extract` with the custom profile
2. Run `osrm-partition` to partition the graph
3. Run `osrm-customize` to optimize for routing
4. Restart OSRM service to load the new routing data

#### Stage 3: Lua Profile Enforcement
The `car_avoid.lua` profile applies speed penalties:
- When routing, OSRM calls `process_way()` for each road
- Profile checks for `avoid_zone=yes` tag
- Multiplies the way's speed by `avoid_factor`
- Routes naturally avoid these slowed-down ways

### Penalty Factors

- **INSIDE_FACTOR = 0.02**: Ways completely inside avoid zone get 2% speed
  - A 100 km/h road becomes 2 km/h (extremely restrictive)
  - Strongly discourages routing through the zone
  
- **TOUCH_FACTOR = 0.10**: Ways touching zone boundary get 10% speed
  - A 100 km/h road becomes 10 km/h (moderately restrictive)
  - Allows passage but heavily penalizes it

## Changes Made

### 1. Enabled PBF Reprocessing (app.py, lines 340-374)
```python
# Uncommented the PBF reprocessing pipeline:
# 1. Load polygons from GeoJSON
# 2. Call apply_penalties() from cutter.py
# 3. Call reprocess_osrm() with modified PBF
# 4. Verify output files were created
# 5. Restart OSRM container
```

### 2. Added curl to Docker Image (Dockerfile)
- Added `curl` to the final production stage
- This fixed the health check which was failing silently
- The container can now execute health checks properly

### 3. Fixed Container Permissions (docker-compose.yml)
- Added `user: "root"` to avoidzones service
- Required for Docker socket access to restart OSRM

### 4. Increased Health Check Start Period (docker-compose.yml)
- Changed `start_period` from 5s to 30s
- Allows the service more time to stabilize before health checks begin

## Testing the Fix

To verify avoid zones are working:

### 1. Apply a Test Polygon

```bash
curl -X POST http://localhost:9090/avoidzones/apply \
  -H "Authorization: Bearer Melancia-sem1-Caroço" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "FeatureCollection",
    "features": [{
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [-43.5, -23.5],
          [-43.4, -23.5],
          [-43.4, -23.4],
          [-43.5, -23.4],
          [-43.5, -23.5]
        ]]
      }
    }]
  }'
```

### 2. Watch the Process

Monitor the avoidzones container logs:
```bash
docker compose logs -f avoidzones
```

You should see:
1. "Applying penalties to PBF..."
2. "Running osrm-extract..."
3. "Running osrm-partition..."
4. "Running osrm-customize..."
5. "Reprocessing OSRM..."
6. "Restarting OSRM container..."

### 3. Compare Routes

Before and after applying the avoid zone, routes should differ:
- Before: Direct route through the zone
- After: Route avoids the zone (takes longer but lower speed penalty)

## Performance Considerations

- **PBF Reprocessing Time**: 5-30 minutes depending on region size and hardware
- **Memory Usage**: Requires 8GB+ RAM during processing
- **Resource Limits**: Set in docker-compose.yml:
  - Memory: 8GB
  - CPUs: 4.0

## Important Notes

1. **First-time setup**: If the PBF hasn't been processed yet, the initial apply will take a long time
2. **Cron task**: The automatic daily refresh still only downloads PBF (doesn't reapply polygons) - call `/avoidzones/apply` manually after a fresh PBF download if needed
3. **Zone persistence**: Avoid zones are persisted in history. Reverting to old configurations is supported
4. **Real-time updates**: Changes to avoid zones require full PBF reprocessing - not real-time

## File Locations

- **PBF Input**: `/media/ronaldo/Homelab/webrotas/region.osm.pbf`
- **PBF Output**: `/media/ronaldo/Homelab/webrotas/region_avoidzones.osm.pbf`
- **OSRM Data**: `/media/ronaldo/Homelab/webrotas/region_avoidzones.osrm*`
- **History**: `/media/ronaldo/Homelab/webrotas/avoidzones_history/`
- **Latest Config**: `/media/ronaldo/Homelab/webrotas/latest_avoidzones.geojson`
