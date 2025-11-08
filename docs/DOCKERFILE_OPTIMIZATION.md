# Dockerfile Optimization: OSRM → Python Base Image

## Problem Identified

The FastAPI avoidzones service was being built from `ghcr.io/project-osrm/osrm-backend:6.0.0`, which was unnecessary and problematic.

## Why This Was Wrong

1. **Bloated Image**: OSRM backend includes routing binaries, libraries, and dependencies that the FastAPI service doesn't need
2. **Slower Builds**: OSRM image is much larger (~600MB+) vs Python slim (~150MB)
3. **Unnecessary Complexity**: Added surface area for potential security issues and updates
4. **Confusing Architecture**: Makes it unclear what the service actually does

## What the FastAPI Service Actually Needs

The avoidzones service only needs:
- **Python 3.13+** runtime
- **Build tools** (g++ for compiling native extensions)
- **Geospatial libraries** (libproj for shapely/pyosmium)
- **curl** (for uv installation)

It does **NOT** need:
- OSRM routing binaries
- OSRM configuration tools
- Lua runtime for profiles
- Other OSRM-specific dependencies

## Solution Applied

**Before:**
```dockerfile
FROM ghcr.io/project-osrm/osrm-backend:6.0.0
RUN apt-get install -y python3 python3-venv g++ libproj-dev proj-data proj-bin curl
```

**After:**
```dockerfile
FROM python:3.13-slim
RUN apt-get install -y g++ libproj-dev proj-data proj-bin curl
```

## Benefits of the Fix

1. **Smaller Image Size**: ~70% reduction in base image size
2. **Faster Builds**: Quicker pulls and builds
3. **Clearer Separation**: Service responsibilities are more obvious
4. **Security**: Reduced attack surface with fewer unnecessary binaries
5. **Maintenance**: Easier to understand and maintain

## Service Architecture Clarification

- **OSRM Container**: Handles routing calculations, reads PBF files
- **FastAPI Container**: 
  - Processes PBF files (adds avoid zone tags)
  - Manages history and configuration
  - Restarts OSRM container via Docker API
  - Serves web API

The separation is now clearer: one container for routing, one for management.

## Testing the Change

After rebuilding:
```bash
docker-compose up -d --build avoidzones
docker images | grep avoidzones  # Should be significantly smaller
docker-compose logs avoidzones   # Should start normally
```

The functionality remains exactly the same — only the base image changed.