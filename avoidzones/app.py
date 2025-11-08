import os
import json
import subprocess
import docker
from pathlib import Path
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Request, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from cutter import apply_penalties

# ============================================================================
# Configuration
# ============================================================================

OSRM_PROFILE = os.getenv("OSRM_PROFILE", "/profiles/car_avoid.lua")
PBF_NAME = os.getenv("PBF_NAME", "region-latest.osm.pbf")
OSRM_BASE = os.getenv("OSRM_BASE", "region")
AVOIDZONES_TOKEN = os.getenv("AVOIDZONES_TOKEN", "default-token")
OSRM_DATA_DIR = Path(os.getenv("OSRM_DATA", "/data"))
OSM_PBF_URL = os.getenv("OSM_PBF_URL", "")

# History and state directories
HISTORY_DIR = OSRM_DATA_DIR / "avoidzones_history"
STATE_FILE = OSRM_DATA_DIR / "current_avoidzones.geojson"
LATEST_POLYGONS = OSRM_DATA_DIR / "latest_avoidzones.geojson"

HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# FastAPI Setup
# ============================================================================

app = FastAPI(title="Avoid Zones API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Models
# ============================================================================


class FeatureCollection(BaseModel):
    type: str
    features: list


class ApplyResponse(BaseModel):
    status: str
    filename: str


class HistoryItem(BaseModel):
    filename: str
    ts: str
    size: int


class RevertRequest(BaseModel):
    filename: str


# ============================================================================
# Authentication
# ============================================================================


async def verify_token(request: Request):
    """Extract and verify bearer token from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header[7:]  # Remove "Bearer " prefix
    if token != AVOIDZONES_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    return token


# ============================================================================
# OSRM and Docker Helpers
# ============================================================================


def restart_osrm():
    """Restart the OSRM container to reload the modified PBF."""
    try:
        client = docker.from_env()
        container = client.containers.get("osrm")
        logger.info("Restarting OSRM container...")
        container.restart()
        logger.info("OSRM container restarted.")
    except Exception as e:
        logger.error(f"Failed to restart OSRM: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to restart OSRM: {e}")


def get_docker_client():
    """Get a Docker client, supporting socket mounting."""
    try:
        return docker.from_env()
    except Exception as e:
        logger.error(f"Failed to connect to Docker: {e}")
        return None


# ============================================================================
# PBF Management
# ============================================================================


def download_pbf():
    """Download the latest PBF file from OSM_PBF_URL."""
    if not OSM_PBF_URL:
        logger.warning("OSM_PBF_URL not set, skipping PBF download")
        return False

    pbf_path = OSRM_DATA_DIR / PBF_NAME
    pbf_tmp = OSRM_DATA_DIR / f"{PBF_NAME}.tmp"

    try:
        logger.info(f"Downloading PBF from {OSM_PBF_URL}...")
        result = subprocess.run(
            ["curl", "-L", "--fail", "-o", str(pbf_tmp), OSM_PBF_URL],
            check=True,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour timeout
        )
        pbf_tmp.rename(pbf_path)
        size_mb = pbf_path.stat().st_size / (1024 * 1024)
        logger.info(f"PBF downloaded successfully ({size_mb:.1f} MB)")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to download PBF: {e.stderr}")
        if pbf_tmp.exists():
            pbf_tmp.unlink()
        return False
    except Exception as e:
        logger.error(f"Unexpected error downloading PBF: {e}")
        if pbf_tmp.exists():
            pbf_tmp.unlink()
        return False


# ============================================================================
# Avoid Zones Processing
# ============================================================================


def process_avoidzones(geojson: dict) -> str:
    """
    Process avoid zones:
    1. Save the geojson to history
    2. Apply penalties to PBF
    3. Rebuild OSRM
    Returns the filename of the saved history entry.
    """
    # Validate GeoJSON
    if geojson.get("type") != "FeatureCollection":
        raise ValueError("Expected FeatureCollection")

    # Generate timestamp-based filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"avoidzones_{timestamp}.geojson"
    history_file = HISTORY_DIR / filename

    # Save to history
    history_file.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
    logger.info(f"Saved avoidzones to history: {filename}")

    # Save as latest
    LATEST_POLYGONS.write_text(json.dumps(geojson, indent=2), encoding="utf-8")

    # Apply penalties
    pbf_path = OSRM_DATA_DIR / PBF_NAME
    modified_pbf = OSRM_DATA_DIR / f"{OSRM_BASE}.osrm.pbf"

    if not pbf_path.exists():
        raise ValueError(f"PBF file not found: {pbf_path}")

    try:
        logger.info("Applying penalties to PBF...")
        apply_penalties(pbf_path, LATEST_POLYGONS, modified_pbf)
        logger.info("Penalties applied successfully")
    except Exception as e:
        logger.error(f"Failed to apply penalties: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to apply penalties: {e}")

    # Restart OSRM
    restart_osrm()

    return filename


# ============================================================================
# API Endpoints
# ============================================================================


@app.post("/avoidzones/apply", response_model=ApplyResponse)
async def apply_avoidzones(
    fc: FeatureCollection, token: str = Depends(verify_token)
):
    """Apply avoid zones polygon(s) and rebuild OSRM."""
    try:
        filename = process_avoidzones(fc.dict())
        return ApplyResponse(status="success", filename=filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in apply_avoidzones: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/avoidzones/history")
async def get_history(token: str = Depends(verify_token)):
    """List all saved avoid zones configurations."""
    items = []
    if HISTORY_DIR.exists():
        for f in sorted(HISTORY_DIR.glob("avoidzones_*.geojson"), reverse=True):
            stat = f.stat()
            items.append(
                HistoryItem(
                    filename=f.name,
                    ts=datetime.fromtimestamp(stat.st_mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    size=stat.st_size,
                )
            )
    return items


@app.get("/avoidzones/download/{filename}")
async def download_history(filename: str, token: str = Depends(verify_token)):
    """Download a specific avoid zones configuration."""
    # Prevent directory traversal
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = HISTORY_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path, media_type="application/json", filename=filename)


@app.post("/avoidzones/revert")
async def revert_avoidzones(
    req: RevertRequest, token: str = Depends(verify_token)
):
    """Revert to a previous avoid zones configuration."""
    # Prevent directory traversal
    if ".." in req.filename or "/" in req.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = HISTORY_DIR / req.filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        geojson = json.loads(file_path.read_text(encoding="utf-8"))
        filename = process_avoidzones(geojson)
        return {"status": "success", "filename": filename}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid GeoJSON in history file")
    except Exception as e:
        logger.error(f"Error in revert_avoidzones: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# ============================================================================
# Scheduled Tasks (Cron)
# ============================================================================


def auto_refresh_pbf():
    """Scheduled task: re-pull PBF and reapply latest polygons."""
    logger.info("[CRON] Auto-refresh task starting...")

    if not OSM_PBF_URL:
        logger.warning("[CRON] OSM_PBF_URL not set, skipping PBF download")
        return

    # Download fresh PBF
    if not download_pbf():
        logger.error("[CRON] Failed to download PBF")
        return

    # Reapply latest polygons if they exist
    if LATEST_POLYGONS.exists():
        try:
            logger.info("[CRON] Reapplying latest polygons...")
            geojson = json.loads(LATEST_POLYGONS.read_text(encoding="utf-8"))
            process_avoidzones(geojson)
            logger.info("[CRON] Auto-refresh completed successfully")
        except Exception as e:
            logger.error(f"[CRON] Failed to reapply polygons: {e}")
    else:
        logger.info("[CRON] No saved polygons to reapply, just rebuilt from fresh PBF")


# ============================================================================
# App Lifecycle
# ============================================================================


def setup_scheduler():
    """Initialize the background scheduler for cron tasks."""
    scheduler = BackgroundScheduler()

    # Schedule auto-refresh daily at 2 AM UTC
    # Can be customized via environment variable REFRESH_CRON_HOUR (0-23)
    refresh_hour = int(os.getenv("REFRESH_CRON_HOUR", "2"))
    scheduler.add_job(
        auto_refresh_pbf,
        CronTrigger(hour=refresh_hour, minute=0),
        id="auto_refresh_pbf",
        name="Auto-refresh PBF and polygons",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started. Auto-refresh scheduled daily at {refresh_hour:02d}:00 UTC"
    )

    return scheduler


# Start scheduler on app startup
scheduler = setup_scheduler()


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up scheduler on shutdown."""
    scheduler.shutdown()
    logger.info("Scheduler shut down")