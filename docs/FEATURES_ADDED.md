# Features Added

## 1. Duplicate & Edit Flow for Past Entries

### Frontend (`frontend/index.html`)
- Added **Edit** button to each history item
- Clicking Edit loads the saved GeoJSON configuration into the drawing interface
- Users can then modify the polygons/rectangles and click "Apply" to create a new version
- History preserves all versions, allowing easy comparison and branching

### Backend (`avoidzones/app.py`)
- `/avoidzones/download/{filename}` endpoint: Download a specific avoid zones configuration as GeoJSON
- Prevents directory traversal attacks by validating filenames
- Returns the GeoJSON with proper CORS headers for frontend access

**Workflow:**
1. User views history with timestamps and file sizes
2. Clicks "Edit" on a past configuration
3. Polygons are loaded into the Leaflet drawing interface
4. User modifies the polygons as desired
5. Clicks "Apply" to save as a new timestamped history entry
6. Each edit creates a new version, preserving the full audit trail

---

## 2. Server-Side Cron for Auto PBF Re-Pull

### Backend (`avoidzones/app.py`)
- Uses **APScheduler** (Background Scheduler) for cron task management
- **Default schedule:** Daily at 2 AM UTC (configurable via `REFRESH_CRON_HOUR` environment variable)
- **Scheduled task:** `auto_refresh_pbf()`
  - Re-downloads fresh PBF from `OSM_PBF_URL`
  - Re-applies the latest saved polygon configuration to the new data
  - Restarts the OSRM container with the updated PBF

### Configuration
Set in Docker Compose environment or `.env`:
```bash
REFRESH_CRON_HOUR=2          # Hour in UTC (0-23)
OSM_PBF_URL=https://...      # PBF source URL
```

### Features
- Automatic PBF updates without manual intervention
- Seamless re-application of avoid zones to new data
- Graceful degradation: if no polygons exist, just rebuilds with fresh PBF
- Comprehensive logging with `[CRON]` prefix for easy troubleshooting

---

## 3. Switch to `uv` in Dockerfile

### avoidzones/Dockerfile
- Replaced `pip3` with `uv` for faster, more reliable dependency installation
- **Benefits:**
  - Significantly faster pip operations (often 5-10x faster)
  - Built-in Python version management
  - Deterministic dependency resolution
  
### Changes
- Added `curl` to build dependencies (for installing uv)
- Installs uv from official source: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Uses `/root/.cargo/bin/uv pip install` instead of `pip3 install`
- Maintains exact same requirements.txt format

### Dependencies Added
- `requirements.txt`: Added `apscheduler>=3.10.0` for cron functionality

---

## API Endpoints Summary

### Authentication
All endpoints (except `/health`) require a Bearer token:
```
Authorization: Bearer <AVOIDZONES_TOKEN>
```

### Endpoints
- **POST** `/avoidzones/apply` — Apply new avoid zones and rebuild OSRM
- **GET** `/avoidzones/history` — List all saved configurations (timestamp, filename, size)
- **GET** `/avoidzones/download/{filename}` — Download a specific configuration as GeoJSON
- **POST** `/avoidzones/revert` — Revert to a previous configuration and rebuild
- **GET** `/health` — Health check (no auth required)

---

## Testing

### Manual Testing
```bash
# Rebuild the service
docker-compose up -d --build avoidzones

# Check logs
docker-compose logs -f avoidzones

# Test the API
curl -H "Authorization: Bearer Melancia-sem1-Caroco" \
  http://localhost:9090/avoidzones/history

# Manually trigger the cron task (can add an admin endpoint if needed)
```

### Browser Testing
1. Open http://localhost:8081
2. Enter the API token: `Melancia-sem1-Caroco`
3. Draw some polygons and click "Apply"
4. Refresh history to see the entry
5. Click "Edit" to load it back into the editor
6. Modify and click "Apply" again to create a new version
7. Use "Revert" to switch between versions

---

## Environment Variables

Add to your `.env` or docker-compose environment:

```bash
# Existing variables
OSRM_DATA=/media/ronaldo/Homelab/webrotas
OSM_PBF_URL=https://download.geofabrik.de/south-america/brazil-latest.osm.pbf
PBF_NAME=region-latest.osm.pbf
OSRM_BASE=region
OSRM_PROFILE=/profiles/car_avoid.lua
AVOIDZONES_TOKEN=Melancia-sem1-Caroco

# New variables (optional)
REFRESH_CRON_HOUR=2  # Auto-refresh time in UTC (0-23), default: 2
```

---

## Notes

- All history files are stored in `${OSRM_DATA}/avoidzones_history/`
- Latest configuration is saved to `${OSRM_DATA}/latest_avoidzones.geojson` for cron tasks
- The Docker socket is mounted in the avoidzones container (`/var/run/docker.sock`) to allow OSRM container restarts
- File size in history is in bytes; divided by 1024² to get MB
- All timestamps are UTC-based
