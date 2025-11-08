# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

**webrotas** is a routing application that combines OSRM (Open Source Routing Machine) with custom avoid zones functionality. It provides:
- A web frontend for route visualization and interaction
- An avoid zones API service (Python/FastAPI) that penalizes certain areas in routing calculations
- Integration with OpenStreetMap tile servers
- Custom OSRM profiles supporting zone-based speed penalties

## Architecture

The system is deployed via Docker Compose with five main services:

### Core Services

**pbf_fetcher**: Downloads OpenStreetMap PBF data from Geofabrik (e.g., Brazil). Uses curl to fetch large OSM datasets.

**osrm**: OSRM routing engine that processes the PBF data through extract → partition → customize → serve pipeline. Serves routing API on port 5000. Uses custom Lua profiles for route calculation.

**tile_server**: OpenStreetMap tile server (PostgreSQL-based) running on port 8080. Handles map tile rendering for the frontend.

**avoidzones**: FastAPI service (Python) running on port 9090. Core component that processes OSM PBF files to add penalty tags to highway ways based on GeoJSON avoid zones.

**frontend**: Nginx server serving the web UI on port 8081. Static HTML/CSS interface for route visualization and requests.

### Avoid Zones Processing Pipeline

The avoid zones system works by:
1. Loading polygon geometries from a GeoJSON file
2. Scanning the OSM PBF file for all highway ways
3. Checking spatial intersection with polygons using STRtree (spatial index)
4. Adding `avoid_zone=yes` and `avoid_factor` tags to intersecting ways
5. Writing a modified PBF file back to OSRM
6. The custom `car_avoid.lua` profile applies speed penalties based on `avoid_factor` tags

Key implementation details:
- **INSIDE_FACTOR** (0.02): Ways completely covered by avoid zones get 2% speed multiplier
- **TOUCH_FACTOR** (0.10): Ways touching polygon boundaries get 10% speed multiplier
- Uses `pyosmium` for efficient PBF parsing and `shapely` for geometric operations

## Development Commands

### Environment Setup

Set Python version:
```bash
python3.13 # or use pyenv if .python-version is set
```

Configure environment variables in `.env`:
- `OSRM_DATA`: Directory for shared volume (OSM data, profiles, frontend)
- `OSM_PBF_URL`: Source URL for PBF data
- `PBF_NAME`: Filename for downloaded PBF
- `OSRM_BASE`: Base name for OSRM data files
- `OSRM_PROFILE`: Profile path (typically `/profiles/car_avoid.lua`)
- `AVOIDZONES_TOKEN`: Simple auth token for avoidzones API

### Docker Commands

Start all services:
```bash
docker-compose up -d
```

View logs for all services:
```bash
docker-compose logs -f
```

View logs for specific service:
```bash
docker-compose logs -f avoidzones
```

Rebuild avoidzones service after code changes:
```bash
docker-compose up -d --build avoidzones
```

Stop all services:
```bash
docker-compose down
```

### Avoidzones Service Development

Install dependencies:
```bash
pip install -r avoidzones/requirements.txt
# or with uv (if available):
uv pip install -r avoidzones/requirements.txt
```

Run FastAPI server locally (for testing):
```bash
cd avoidzones
uvicorn app:app --reload --port 9090
```

Test the `cutter.py` module directly:
```bash
python3 -c "from cutter import apply_penalties; apply_penalties(in_pbf, geojson_file, out_pbf)"
```

## Key Files and Components

- `avoidzones/app.py`: FastAPI application endpoints (currently empty, main logic to be added)
- `avoidzones/cutter.py`: Core PBF processing logic using pyosmium and shapely
- `profiles/car_avoid.lua`: OSRM Lua profile with penalty hook for avoid zones
- `frontend/index.html`: Web UI for routing requests
- `docker-compose.yml`: Service orchestration with dependency management
- `.env`: Environment configuration for all services
- `pyproject.toml`: Python project metadata (Python 3.13+)

## Dependencies

**Python (avoidzones service)**:
- `fastapi==0.115.0`: Web framework
- `uvicorn[standard]==0.30.6`: ASGI server
- `shapely>=2.0`: Geometric operations and spatial indexing (STRtree)
- `pyosmium>=3.6.0`: Efficient OpenStreetMap PBF parsing and writing

**Docker images**:
- `ghcr.io/project-osrm/osrm-backend:latest`: OSRM routing engine
- `overv/openstreetmap-tile-server:latest`: Tile server with PostgreSQL
- `nginx:alpine`: Frontend web server

## Notes

- The project is in early stages (0.1.0)
- All services depend on `pbf_fetcher` completing successfully (PBF download)
- The avoid zones API requires the modified PBF from the cutter pipeline before routing works correctly
- Profile changes require rerunning OSRM extract/partition/customize steps
- Frontend directory is served read-only by nginx from the shared `OSRM_DATA` volume
