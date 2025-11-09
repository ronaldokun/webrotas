import os
import json
import subprocess
import docker
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Literal
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .cutter import apply_penalties

# ============================================================================
# Configuration
# ============================================================================

OSRM_PROFILE = os.getenv("OSRM_PROFILE", "/profiles/car_avoid.lua")
PBF_NAME = os.getenv("PBF_NAME", "region.osm.pbf")
OSRM_BASE = os.getenv("OSRM_BASE", "region")
AVOIDZONES_TOKEN = os.getenv("AVOIDZONES_TOKEN", "default-token")
OSRM_DATA_DIR = Path(os.getenv("OSRM_DATA", "/data"))
OSM_PBF_URL = os.getenv("OSM_PBF_URL", "")

# History and state directories
HISTORY_DIR = OSRM_DATA_DIR / "avoidzones_history"
LATEST_POLYGONS = OSRM_DATA_DIR / "latest_avoidzones.geojson"

HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# FastAPI Setup
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan: startup and shutdown events."""
    # Startup
    scheduler = setup_scheduler()
    yield
    # Shutdown
    scheduler.shutdown()
    logger.info("Scheduler shut down")


app = FastAPI(title="Avoid Zones API", lifespan=lifespan)

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


class Geometry(BaseModel):
    """GeoJSON Geometry model."""

    type: Literal["Polygon", "MultiPolygon"]
    coordinates: List[Any]


class Feature(BaseModel):
    """GeoJSON Feature model."""

    type: Literal["Feature"]
    geometry: Geometry
    properties: Dict[str, Any] = Field(default_factory=dict)


class FeatureCollection(BaseModel):
    """GeoJSON FeatureCollection model with validation."""

    type: Literal["FeatureCollection"]
    features: List[Feature]

    @field_validator("features")
    @classmethod
    def validate_features(cls, v):
        if not v:
            raise ValueError("FeatureCollection must contain at least one feature")
        return v


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
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )
    token = auth_header[7:]  # Remove "Bearer " prefix
    if token != AVOIDZONES_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    return token


# ============================================================================
# OSRM and Docker Helpers
# ============================================================================


def reprocess_osrm(pbf_filename: str):
    """
    Reprocess PBF through OSRM pipeline:
    1. osrm-extract: Extract features from PBF
    2. osrm-partition: Partition extracted data
    3. osrm-customize: Customize routing behavior
    
    Args:
        pbf_filename: Just the filename (e.g., 'region_avoidzones.osm.pbf'),
                     will be looked up in OSRM_DATA_DIR
    """
    try:
        # Validate filename has no path separators
        if "/" in pbf_filename or "\\" in pbf_filename:
            raise ValueError(f"pbf_filename must be a filename only, not a path: {pbf_filename}")
        
        pbf_path = OSRM_DATA_DIR / pbf_filename
        if not pbf_path.exists():
            raise ValueError(f"PBF file not found: {pbf_path}")
        
        pbf_stem = pbf_path.stem
        client = docker.from_env()
        osrm_image = "ghcr.io/project-osrm/osrm-backend:6.0.0"
        volume_bind = {str(OSRM_DATA_DIR): {"bind": "/data", "mode": "rw"}}
        
        # Helper function to run container and check exit code
        def run_osrm_command(command_name, cmd):
            logger.info(f"Running {command_name}...")
            container = None
            try:
                container = client.containers.run(
                    osrm_image,
                    cmd,
                    volumes=volume_bind,
                    rm=False,  # Don't remove yet, so we can check exit code
                    stdout=True,
                    stderr=True,
                    detach=False,
                )
                # Get exit code
                exit_code = container.wait()
                if exit_code != 0:
                    logs = container.logs(stdout=True, stderr=True).decode(errors="replace")
                    raise RuntimeError(
                        f"{command_name} failed with exit code {exit_code}. Output: {logs}"
                    )
                logger.info(f"{command_name} completed successfully")
            finally:
                if container:
                    try:
                        container.remove()
                    except Exception as e:
                        logger.warning(f"Failed to remove container: {e}")
        
        # Step 1: osrm-extract
        run_osrm_command(
            "osrm-extract",
            f"osrm-extract -p {OSRM_PROFILE} /data/{pbf_filename}"
        )
        
        # Step 2: osrm-partition
        run_osrm_command(
            "osrm-partition",
            f"osrm-partition /data/{pbf_stem}.osrm"
        )
        
        # Step 3: osrm-customize
        run_osrm_command(
            "osrm-customize",
            f"osrm-customize /data/{pbf_stem}.osrm"
        )
        
        logger.info("All OSRM preprocessing steps completed successfully")
    except Exception as e:
        logger.error(f"Failed to reprocess OSRM: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reprocess OSRM: {e}")


def restart_osrm():
    """Restart the OSRM container to reload the modified PBF."""
    try:
        client = docker.from_env()
        container = client.containers.get("osrm")
        logger.info("Restarting OSRM container...")
        container.restart(timeout=30)
        logger.info("OSRM container restarted.")
    except Exception as e:
        logger.error(f"Failed to restart OSRM: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to restart OSRM: {e}")


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
        # Defensive checks: verify download succeeded
        if not pbf_tmp.exists():
            raise ValueError(f"PBF download failed: temporary file {pbf_tmp} was not created")
        
        file_size = pbf_tmp.stat().st_size
        if file_size == 0:
            pbf_tmp.unlink()
            raise ValueError("PBF download resulted in empty file")
        
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
    modified_pbf = pbf_path.with_stem(f"{pbf_path.stem}_avoidzones")

    if not pbf_path.exists():
        raise ValueError(f"PBF file not found: {pbf_path}")

    try:
        logger.info("Applying penalties to PBF...")
        apply_penalties(pbf_path, LATEST_POLYGONS, modified_pbf)
        logger.info("Penalties applied successfully")
    except Exception as e:
        logger.error(f"Failed to apply penalties: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to apply penalties: {e}")

    # Verify modified PBF was created and has content
    if not modified_pbf.exists():
        raise HTTPException(status_code=500, detail=f"Modified PBF file was not created: {modified_pbf}")
    
    file_size = modified_pbf.stat().st_size
    if file_size == 0:
        modified_pbf.unlink()
        raise HTTPException(status_code=500, detail="Modified PBF file is empty after applying penalties")
    
    logger.info(f"Modified PBF created successfully ({file_size / 1024 / 1024:.1f} MB)")

    # Reprocess OSRM with the modified PBF
    reprocess_osrm(modified_pbf.name)
    
    # Wait for files to sync to disk before restarting container
    import time
    time.sleep(2)
    
    # Verify partition files were created by osrm-customize
    pbf_stem = modified_pbf.stem
    expected_files = [
        OSRM_DATA_DIR / f"{pbf_stem}.osrm.hsgr",
        OSRM_DATA_DIR / f"{pbf_stem}.osrm.prf",
    ]
    for f in expected_files:
        if not f.exists():
            raise HTTPException(status_code=500, detail=f"Expected partition file missing after preprocessing: {f}")
    
    # Restart OSRM to load the reprocessed data
    restart_osrm()

    return filename


# ============================================================================
# API Endpoints
# ============================================================================


@app.post("/avoidzones/apply", response_model=ApplyResponse)
async def apply_avoidzones(fc: FeatureCollection, token: str = Depends(verify_token)):
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
async def revert_avoidzones(req: RevertRequest, token: str = Depends(verify_token)):
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
