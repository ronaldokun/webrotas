# Tile Server Optimization

## Changes Made

Modified the `tile_import` and `tile_server` services in `docker-compose.yml` to:

1. **Use Brazil PBF data only** instead of downloading the entire planet
2. **Persist imported data** across container restarts 
3. **Optimize import performance** with better osm2pgsql settings

## What Changed

### tile_import Service

**Before:** The container would download Luxembourg as a sample (or the entire planet if misconfigured), taking hours and potentially failing.

**After:**
- Creates a symlink from your Brazil PBF file (`brazil-latest.osm.pbf`) to the expected location (`/data/region.osm.pbf`)
- Imports only Brazil data (much faster)
- Uses optimized osm2pgsql settings:
  - `-C 4096`: 4GB cache for faster processing
  - `--slim`: Stores node locations in database (needed for updates, uses less RAM)
  - `--drop`: Drops intermediate tables after import (saves disk space)
- Sets `THREADS: "4"` for parallel processing

### tile_server Service

**After:**
- Reuses the imported PostgreSQL database from `tile_import`
- Shares the same volumes so no re-import is needed on restart
- Uses 4 threads for tile rendering

### Persistent Volumes

Two Docker named volumes ensure data persists across restarts:

- **`tiles-db`**: PostgreSQL database with imported OSM data
  - Mounted at `/var/lib/postgresql/15/main`
  - Persists the entire imported database
  
- **`tiles-cache`**: Rendered tile cache
  - Mounted at `/var/cache/renderd`
  - Speeds up repeated tile requests

## Usage

### First Time Import

```bash
# Start only the import service (this will take 30-60 minutes for Brazil)
docker-compose up tile_import

# Once complete, start the tile server
docker-compose up -d tile_server
```

### Subsequent Restarts

The data is now persisted in Docker volumes, so restarts are fast:

```bash
# Restart tile server (no re-import needed!)
docker-compose restart tile_server

# Or stop and start all services
docker-compose down
docker-compose up -d
```

### Full Re-import

If you need to completely re-import the data (e.g., after updating the Brazil PBF file):

```bash
# Remove the persistent volumes
docker-compose down
docker volume rm webrotas_tiles-db webrotas_tiles-cache

# Re-import
docker-compose up tile_import
docker-compose up -d tile_server
```

### Checking Import Progress

```bash
# Follow import logs
docker-compose logs -f tile_import

# Check database size (after import)
docker exec -it tile_import du -sh /var/lib/postgresql/15/main
```

## Performance Notes

### Import Time Estimates

For Brazil PBF data (~1.2GB compressed):
- **Import time**: 30-60 minutes (depending on CPU/disk)
- **Database size**: ~20-30GB after import
- **RAM usage**: 4-6GB during import (controlled by `-C 4096`)

### Memory Configuration

The osm2pgsql cache is set to 4GB (`-C 4096`). Adjust based on your available RAM:

```yaml
OSM2PGSQL_EXTRA_ARGS: "-C 2048 --slim --drop"  # 2GB cache
OSM2PGSQL_EXTRA_ARGS: "-C 8192 --slim --drop"  # 8GB cache
```

More cache = faster import, but requires more RAM.

### Thread Count

Both services use 4 threads by default. Adjust based on your CPU:

```yaml
THREADS: "2"   # For dual-core CPUs
THREADS: "8"   # For 8+ core CPUs
```

## Troubleshooting

### Import Fails with "Out of Memory"

Reduce the osm2pgsql cache:
```yaml
OSM2PGSQL_EXTRA_ARGS: "-C 2048 --slim --drop"
```

### Import Takes Too Long

- Increase cache if you have more RAM available
- Increase thread count if you have more CPU cores
- Ensure you're using an SSD for the `OSRM_DATA` directory

### Tiles Not Rendering

Check tile server logs:
```bash
docker-compose logs -f tile_server
```

Verify PostgreSQL database is accessible:
```bash
docker exec -it osmtiles psql -U renderer -d gis -c "SELECT COUNT(*) FROM planet_osm_point;"
```

### Want to Clear Everything and Start Fresh

```bash
# Stop all services
docker-compose down

# Remove volumes (WARNING: deletes all imported data)
docker volume rm webrotas_tiles-db webrotas_tiles-cache

# Restart from scratch
docker-compose up tile_import
docker-compose up -d tile_server
```

## Technical Details

### How the Symlink Works

The tile server expects the PBF file at `/data/region.osm.pbf`. Our command creates a symbolic link:

```bash
ln -sf /data/brazil-latest.osm.pbf /data/region.osm.pbf
```

This points to your actual Brazil PBF file without copying it (saves disk space).

### Volume Persistence

Docker named volumes are stored in Docker's internal storage (usually `/var/lib/docker/volumes/`). The data persists even if containers are removed, unless you explicitly delete the volumes.

### Why `--slim --drop`?

- `--slim`: Stores node locations in database tables (allows updates later, uses less RAM)
- `--drop`: Removes intermediate tables after import (saves ~50% disk space)

These are optimal settings for a production tile server that doesn't need frequent updates.
