#!/bin/bash
set -e

# Check if the database is already initialized
if [ -f /data/database/planet-import-complete ]; then
    echo "[tile_import] Database already initialized, skipping import"
    exit 0
else
    echo "[tile_import] Database not found, running import..."
    /run.sh import
fi
