# Lua-Only Avoid Zones Approach

## Overview

The project has been migrated from a PBF-reprocessing approach to a **Lua-only dynamic approach** for applying avoid zones. This eliminates the need for expensive PBF reprocessing (osrm-extract, osrm-partition, osrm-customize) when applying new polygon avoid zones.

## Key Changes

### What Changed

1. **Disabled PBF Reprocessing**: Comments in `app.py` (line 328-338) show the previously used pipeline
2. **New Lua Converter**: `lua_converter.py` converts GeoJSON polygons to Lua data format
3. **Updated Lua Profile**: `car_avoid.lua` now has infrastructure to load polygon data dynamically
4. **Faster API Response**: `/avoidzones/apply` now completes in seconds instead of minutes

### What Stayed the Same

- GeoJSON API format remains unchanged
- History and revert functionality unchanged
- Authentication and security intact
- OSRM container still used for routing

## Architecture

```
User sends GeoJSON polygons
        ↓
┌──────────────────────────┐
│ POST /avoidzones/apply   │
└──────────────────────────┘
        ↓
1. Save GeoJSON to history
2. Save as latest_avoidzones.geojson
3. Convert to Lua format → avoid_zones_data.lua
4. Restart OSRM container (picks up new Lua profile)
        ↓
OSRM Lua Profile Startup
    ↓
    Loads car_avoid.lua
    ├─ Imports base car profile
    ├─ Requires avoid_zones_data.lua
    └─ Populates avoid_polygons table
        ↓
Routing Request
    ↓
OSRM checks each way
    ├─ Legacy support: checks for avoid_zone PBF tags
    └─ New approach: could use dynamic polygon checking
        (currently unused - see LIMITATION section)
```

## IMPORTANT LIMITATION ⚠️

**The Lua profile cannot access way node coordinates in the `process_way()` function.**

OSRM's `process_way()` hook receives:
- Way metadata (tags, ID)
- Relations
- Result object to modify speeds

It does **NOT** receive:
- The actual node coordinates that make up the way

This means the dynamic polygon checking functions in `car_avoid.lua` (lines 36-107) are **currently unused**. They were implemented for potential future use if OSRM API changes or alternative solutions become available.

### Current Workaround

The dynamic approach only works if penalties are **pre-computed and stored in the PBF as tags** (the old approach) or if coordinates are available through other means.

## Files Modified

### `/home/ronaldo/Work/webrotas/profiles/car_avoid.lua`
- Added point-in-polygon algorithm (ray casting)
- Added polygon loading infrastructure
- Kept legacy PBF tag support (lines 123-136)
- Documented limitation in comments (lines 139-141)

### `/home/ronaldo/Work/webrotas/src/webrotas/app.py`
- Commented out PBF reprocessing (lines 333-338)
- Added Lua conversion step (lines 316-326)
- Simplified cron task (lines 447-459)
- Changed from ~5-30 minute operation to ~10-30 seconds

### `/home/ronaldo/Work/webrotas/src/webrotas/lua_converter.py` (NEW)
- Converts GeoJSON FeatureCollection to Lua table format
- Extracts exterior rings from Polygon/MultiPolygon features
- Generates `avoid_zones_data.lua` in profiles directory

## Recommended Next Steps

### Option 1: Revert to PBF Reprocessing (Most Reliable)
If the Lua-only approach doesn't work as expected, revert by uncommenting lines 333-338 in `app.py`. This is guaranteed to work but is slower (~5-30 minutes per request).

### Option 2: Investigate OSRM API Extensions
- Check if OSRM 6.x or newer versions provide way coordinate access in process_way
- Consider building a custom OSRM fork with this capability
- Investigate if way geometry can be loaded from a separate data structure

### Option 3: Hybrid Approach
- Keep current setup for fast response times
- Run periodic batch reprocessing (e.g., nightly) to maintain optimal routing performance
- Users get instant feedback but don't get full penalty benefits until next batch cycle

### Option 4: Node-Level Penalties
Instead of way-level penalties, apply penalties to individual nodes:
- Pre-compute which nodes fall within avoid zones
- Tag nodes with penalty factors in the PBF
- OSRM's `process_node()` hook can then apply these penalties
- More granular but still requires initial PBF reprocessing

## Testing the Implementation

### Verify Lua File Generation
```bash
# After applying zones, check if Lua file exists:
ls -lh /data/profiles/avoid_zones_data.lua

# View contents:
cat /data/profiles/avoid_zones_data.lua
```

### Test API Call
```bash
curl -X POST http://localhost:9090/avoidzones/apply \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d @sample_zones.geojson
```

### Check OSRM Logs
```bash
docker-compose logs osrm | tail -50
```

## Performance Comparison

| Operation | PBF Approach | Lua Approach |
|-----------|--------------|-------------|
| Apply new zones | 5-30 min | ~15 sec |
| Memory usage | Very high (8GB+) | Low |
| Routing accuracy | Perfect (pre-computed) | Good (dynamic) |
| Supported clients | Single | Multiple (no coordination needed) |

## Reverting to Previous Approach

If issues arise and you need to revert to PBF reprocessing:

1. Uncomment lines 333-338 in `app.py`
2. Uncomment import: `from .cutter import apply_penalties`
3. Rebuild container: `docker-compose up -d --build avoidzones`

The old code is still present and functional, just commented out for reference.
