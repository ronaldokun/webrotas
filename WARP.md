# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

**webrotas** is a routing application that combines OSRM (Open Source Routing Machine) with custom avoid zones functionality. It provides:
- A web frontend for route visualization and interaction
- An avoid zones API service (Python/FastAPI) that penalizes certain areas in routing calculations
- Integration with OpenStreetMap tile servers
- Custom OSRM profiles supporting zone-based speed penalties

## Architecture

The system is deployed via Docker Compose with six main services:

### Core Services

**pbf_fetcher**: Downloads OpenStreetMap PBF data from Geofabrik (e.g., Brazil). Uses curl to fetch large OSM datasets.

**osrm**: OSRM routing engine (version 6.0.0) that processes the PBF data through extract → partition → customize → serve pipeline. Serves routing API on port 5000. Uses custom Lua profiles for route calculation.

**tile_import** & **tile_server**: OpenStreetMap tile server (PostgreSQL-based) running on port 8080. Handles map tile rendering for the frontend. `tile_import` runs once to initialize the database, then `tile_server` serves tiles.

**avoidzones**: FastAPI service (Python 3.13+) running on port 9090. Core component that:
- Processes OSM PBF files to add penalty tags to highway ways based on GeoJSON avoid zones
- Manages avoid zones history with versioning and revert capability
- Implements scheduled cron tasks for automatic PBF re-pulling and re-application
- Restarts OSRM containers to reload modified PBF files

**frontend**: Nginx server serving the web UI on port 8081. Static HTML/CSS interface for route visualization and editing polygon constraints.

### Avoid Zones Processing Pipeline

The avoid zones system works by:
1. Loading polygon geometries from a GeoJSON file
2. Scanning the OSM PBF file for all highway ways using pyosmium
3. Checking spatial intersection with polygons using STRtree spatial indexing
4. Adding `avoid_zone=yes` and `avoid_factor` tags to intersecting ways
5. Writing a modified PBF file back to OSRM
6. The custom `car_avoid.lua` profile applies speed penalties based on `avoid_factor` tags

Key implementation details:
- **INSIDE_FACTOR** (0.02): Ways completely covered by avoid zones get 2% speed multiplier
- **TOUCH_FACTOR** (0.10): Ways touching polygon boundaries get 10% speed multiplier
- Uses `pyosmium` for efficient PBF parsing and `shapely` for geometric operations
- Uses STRtree spatial indexing for fast polygon-way intersection detection

### Version Control & History

The avoidzones service maintains a complete audit trail:
- All avoid zone configurations are timestamped and stored in `${OSRM_DATA}/avoidzones_history/`
- Latest configuration is saved to `${OSRM_DATA}/latest_avoidzones.geojson`
- Frontend allows editing past configurations to create new versions without losing history

## Development Environment

### Setup

Python 3.13+ is required. The project uses `uv` for dependency management.

Install dependencies:
```bash
uv sync
```

This creates a virtual environment with all dependencies from `pyproject.toml`.

### Local Development

**Run avoidzones service locally:**
```bash
uv run uvicorn app:app --reload --port 9090
```

The `--reload` flag enables auto-restart on code changes.

**Test the cutter module directly:**
```bash
uv run python -c "from cutter import apply_penalties; print('Module loads OK')"
```

### Docker Commands

**Start all services:**
```bash
docker-compose up -d
```

**View logs for all services:**
```bash
docker-compose logs -f
```

**View logs for specific service:**
```bash
docker-compose logs -f avoidzones
```

**Rebuild avoidzones service after code changes:**
```bash
docker-compose up -d --build avoidzones
```

**Restart OSRM after manual PBF modifications:**
```bash
docker-compose restart osrm
```

**Stop all services:**
```bash
docker-compose down
```

**Clean up and rebuild everything (useful after changing profiles or major changes):**
```bash
docker-compose down && docker-compose up -d
```

### Debugging

Check avoidzones container logs for errors:
```bash
docker-compose logs -f avoidzones | grep -i error
```

Check OSRM preprocessing/serving status:
```bash
docker-compose logs osrm | tail -50
```

Check tile server import progress:
```bash
docker-compose logs tile_import | tail -20
```

## API Endpoints

All endpoints (except `/health`) require Bearer token authentication via `Authorization: Bearer <AVOIDZONES_TOKEN>`.

### Core Endpoints

- **POST** `/avoidzones/apply` — Apply new avoid zones and rebuild OSRM
  - Request body: GeoJSON FeatureCollection
  - Returns: `{status: "success", filename: "avoidzones_YYYYMMDD_HHMMSS.geojson"}`

- **GET** `/avoidzones/history` — List all saved configurations
  - Returns: Array of `{filename, ts, size}`

- **GET** `/avoidzones/download/{filename}` — Download a specific configuration as GeoJSON
  - Prevents directory traversal via filename validation

- **POST** `/avoidzones/revert` — Revert to a previous configuration and rebuild
  - Request body: `{filename: "avoidzones_YYYYMMDD_HHMMSS.geojson"}`

- **GET** `/health` — Health check (no authentication required)
  - Returns: `{status: "ok"}`

## Testing

Currently there are no automated tests in the project. When adding tests:

```bash
# Run tests
uv run pytest

# Run tests in a specific file
uv run pytest tests/test_cutter.py

# Run with verbose output
uv run pytest -v
```

Tests should be added to a `tests/` directory. Use `pytest` and `pytest-asyncio` (already in optional dev dependencies).

## Configuration

Environment variables are configured in `.env` and passed to services via `docker-compose.yml`:

- `OSRM_DATA`: Directory for shared volume (OSM data, profiles, frontend)
- `OSM_PBF_URL`: Source URL for PBF data (Geofabrik or similar)
- `PBF_NAME`: Filename for downloaded PBF (e.g., `brazil-latest.osm.pbf`)
- `OSRM_BASE`: Base name for OSRM data files (used for `.osrm` file naming)
- `OSRM_PROFILE`: Profile path inside containers (e.g., `/profiles/car_avoid.lua`)
- `AVOIDZONES_TOKEN`: Simple bearer token for API authentication
- `REFRESH_CRON_HOUR`: Hour (0-23 UTC) for automatic daily PBF re-pull (default: 2)

## Key Files and Components

### Source Code
- `app.py`: FastAPI application with all API endpoints and Docker integration
- `cutter.py`: Core PBF processing logic using pyosmium and shapely

### Configuration
- `pyproject.toml`: Python dependencies and build configuration
- `docker-compose.yml`: Service orchestration with volume and port mappings
- `.env`: Environment configuration (local variables, tokens, URLs)
- `Dockerfile`: Multi-stage build for avoidzones service

### Profiles
- `profiles/car_avoid.lua`: OSRM Lua profile with penalty hook for avoid zones

### Frontend
- `frontend/index.html`: Web UI for routing requests and polygon editing
- `frontend/styles.css`: Styling for the interface

### Documentation
- `docs/FEATURES_ADDED.md`: Detailed feature documentation
- `docs/MIGRATION_PYPROJECT.md`: Migration from requirements.txt to pyproject.toml

## Dependencies

**Python packages** (from `pyproject.toml`):
- `fastapi>=0.121.0` — Web framework and API routing
- `uvicorn[standard]>=0.38.0` — ASGI server
- `osmium>=4.2.0` — PBF file parsing and writing
- `shapely>=2.1.2` — Geometric operations and spatial indexing (STRtree)
- `docker>=7.1.0` — Docker API client for container management
- `apscheduler>=3.11.1` — Cron scheduling for auto-refresh tasks

**Dev dependencies**:
- `pytest>=7.0` — Testing framework
- `pytest-asyncio>=0.21.0` — Async test support

**Docker base images**:
- `ghcr.io/project-osrm/osrm-backend:6.0.0` — OSRM routing engine
- `overv/openstreetmap-tile-server:latest` — Tile server with PostgreSQL
- `nginx:alpine` — Frontend web server
- `curlimages/curl:8.10.1` — PBF download utility

## Important Notes

- The project uses Python 3.13+ and requires `uv` for dependency management
- All services depend on `pbf_fetcher` completing successfully (PBF download)
- The avoid zones API requires the modified PBF from the cutter pipeline before routing works correctly
- Profile changes (modifying `car_avoid.lua`) require rerunning OSRM extract/partition/customize steps (triggered by restarting osrm container)
- Frontend directory is served read-only by nginx from the shared `OSRM_DATA` volume
- The avoidzones container mounts the Docker socket at `/var/run/docker.sock:ro` to manage OSRM restarts
- Automatic PBF re-pulls happen daily (configurable via `REFRESH_CRON_HOUR`) and automatically reapply the latest saved polygon configuration
- All timestamps are UTC-based

## Common Development Workflows

### Adding a new API endpoint
1. Add the endpoint function in `app.py`
2. Include `token: str = Depends(verify_token)` parameter for authentication
3. Test with curl using the Bearer token
4. Rebuild with `docker-compose up -d --build avoidzones`

### Modifying avoid zones processing logic
1. Edit logic in `cutter.py` (the `Penalizer` class processes ways)
2. Modify penalty factors (`INSIDE_FACTOR`, `TOUCH_FACTOR`) as needed
3. Test with `uv run python -c "from cutter import ..."`
4. Changes take effect on next `/avoidzones/apply` call

### Updating OSRM routing profile
1. Edit `profiles/car_avoid.lua`
2. The penalty hook (lines 44-57) applies avoid zone speed multipliers
3. Restart OSRM to reprocess PBF with new profile: `docker-compose restart osrm`

### Testing polygon intersection logic
The cutter uses shapely's STRtree for spatial indexing. Test polygon intersection:
```bash
uv run python -c "
from pathlib import Path
from cutter import _load_polys
polys, tree = _load_polys(Path('path/to/geojson.geojson'))
print(f'Loaded {len(polys)} polygons')
"
```
