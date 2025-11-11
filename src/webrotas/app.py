import os
import json
import subprocess
import docker
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Literal, Optional
import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Client-side zone processing imports
import httpx
from shapely.geometry import LineString, shape
from shapely.strtree import STRtree

# from .cutter import apply_penalties
from .lua_converter import write_lua_zones_file

# ============================================================================
# Configuration
# ============================================================================

OSRM_PROFILE = os.getenv("OSRM_PROFILE", "/profiles/car_avoid.lua")
PBF_NAME = os.getenv("PBF_NAME", "region.osm.pbf")
OSRM_BASE = os.getenv("OSRM_BASE", "region")
AVOIDZONES_TOKEN = os.getenv("AVOIDZONES_TOKEN", "default-token")
OSRM_DATA_DIR = Path(os.getenv("OSRM_DATA", "/data"))
OSM_PBF_URL = os.getenv("OSM_PBF_URL", "")

# OSRM server URL for routing requests
OSRM_URL = os.getenv("OSRM_URL", "http://localhost:5000")

# Docker resource limits for OSRM preprocessing
DOCKER_MEMORY_LIMIT = os.getenv("DOCKER_MEMORY_LIMIT", "16g")
DOCKER_CPUS_LIMIT = float(os.getenv("DOCKER_CPUS_LIMIT", "4.0"))

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


class IntersectionInfo(BaseModel):
    """Information about route intersection with avoid zones."""
    intersection_count: int
    total_length_km: float
    penalty_ratio: float
    route_length_km: float


class ZonesAppliedInfo(BaseModel):
    """Metadata about the avoid zones configuration applied to routing."""
    version: str
    polygon_count: int


class RouteWithZonesResponse(BaseModel):
    """Response model for route with zones filtering."""
    routes: List[Dict[str, Any]]
    zones_applied: ZonesAppliedInfo
    intersection_info: Dict[str, IntersectionInfo]


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
            raise ValueError(
                f"pbf_filename must be a filename only, not a path: {pbf_filename}"
            )

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
                    mem_limit=DOCKER_MEMORY_LIMIT,
                    memswap_limit=DOCKER_MEMORY_LIMIT,
                    cpus=DOCKER_CPUS_LIMIT,
                )
                # Get exit code
                exit_code = container.wait()
                if exit_code != 0:
                    logs = container.logs(stdout=True, stderr=True).decode(
                        errors="replace"
                    )
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
            "osrm-extract", f"osrm-extract -p {OSRM_PROFILE} /data/{pbf_filename}"
        )

        # Step 2: osrm-partition
        run_osrm_command("osrm-partition", f"osrm-partition /data/{pbf_stem}.osrm")

        # Step 3: osrm-customize
        run_osrm_command("osrm-customize", f"osrm-customize /data/{pbf_stem}.osrm")

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
        container.restart(timeout=300)
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
            raise ValueError(
                f"PBF download failed: temporary file {pbf_tmp} was not created"
            )

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
# OSRM Proxy Handler
# ============================================================================


async def request_osrm(
    coordinates: str,
    alternatives: int = 1,
    overview: str = "full",
    geometries: str = "geojson",
) -> Dict[str, Any]:
    """
    Request route from OSRM with specified parameters.
    
    Args:
        coordinates: OSRM format coordinates "lng1,lat1;lng2,lat2"
        alternatives: Number of alternative routes (1-3)
        overview: Detail level ("simplified", "full", "false")
        geometries: Geometry format ("geojson", "polyline", "polyline6")
        
    Returns:
        OSRM response as dictionary
        
    Raises:
        HTTPException: On connection or OSRM errors
    """
    try:
        url = f"{OSRM_URL}/route/v1/driving/{coordinates}"
        
        params = {
            "alternatives": alternatives,
            "overview": overview,
            "geometries": geometries,
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            logger.info(f"Requesting route from OSRM: {url}")
            response = await client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"OSRM returned {len(data.get('routes', []))} routes")
            return data
            
    except httpx.HTTPError as e:
        logger.error(f"OSRM HTTP error: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"OSRM routing request failed: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Error requesting OSRM: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error requesting OSRM: {str(e)}",
        )


# ============================================================================
# Client-Side Zone Processing Helpers
# ============================================================================


def check_route_intersections(coords: List[List[float]], polygons: List, tree: Optional[STRtree]) -> Dict[str, Any]:
    """
    Calculate route-polygon intersections for a given route and set of avoid zone polygons.
    
    Args:
        coords: List of [longitude, latitude] coordinates forming the route
        polygons: List of shapely polygon objects representing avoid zones
        tree: STRtree spatial index of polygons (or None if no polygons)
        
    Returns:
        Dictionary with intersection statistics:
        - intersection_count: Number of polygons route intersects
        - total_length_km: Total length of route within avoid zones
        - penalty_ratio: Fraction of route within zones (0.0-1.0)
        - route_length_km: Total route length in kilometers
    """
    if not polygons or tree is None:
        return {
            "intersection_count": 0,
            "total_length_km": 0.0,
            "penalty_ratio": 0.0,
            "route_length_km": 0.0,
        }
    
    try:
        route_line = LineString(coords)
        intersection_count = 0
        total_intersection_length = 0
        
        # Query spatial index for candidate polygons
        candidate_indices = tree.query(route_line)
        
        for idx in candidate_indices:
            polygon = polygons[idx]
            if route_line.intersects(polygon):
                intersection_count += 1
                intersection = route_line.intersection(polygon)
                # Handle both Point and LineString/MultiLineString intersections
                if hasattr(intersection, 'length'):
                    total_intersection_length += intersection.length
        
        total_route_length = route_line.length
        penalty_ratio = (
            total_intersection_length / total_route_length 
            if total_route_length > 0 
            else 0.0
        )
        
        # Convert to km for readability
        total_intersection_km = total_intersection_length / 1000
        route_length_km = total_route_length / 1000
        
        return {
            "intersection_count": intersection_count,
            "total_length_km": round(total_intersection_km, 3),
            "penalty_ratio": min(penalty_ratio, 1.0),  # Cap at 100%
            "route_length_km": round(route_length_km, 3),
        }
    except Exception as e:
        logger.error(f"Error calculating route intersections: {e}")
        return {
            "intersection_count": 0,
            "total_length_km": 0.0,
            "penalty_ratio": 0.0,
            "route_length_km": 0.0,
        }


def load_zones_version(version_id: Optional[str]) -> Dict[str, Any]:
    """
    Load specific avoid zones version from history.
    
    Args:
        version_id: "latest" or "avoidzones_YYYYMMDD_HHMMSS" (without .geojson)
        
    Returns:
        Parsed GeoJSON dictionary
        
    Raises:
        FileNotFoundError: If zones version not found
        ValueError: If invalid version format
    """
    if version_id == "latest" or version_id is None:
        file_path = LATEST_POLYGONS
    else:
        # Validate version_id format to prevent directory traversal
        if not version_id.startswith("avoidzones_"):
            raise ValueError(f"Invalid version format: {version_id}")
        if "." in version_id or "/" in version_id or "\\" in version_id:
            raise ValueError(f"Invalid version format: {version_id}")
        file_path = HISTORY_DIR / f"{version_id}.geojson"
    
    if not file_path.exists():
        raise FileNotFoundError(f"Zones version not found: {file_path}")
    
    try:
        geojson = json.loads(file_path.read_text(encoding="utf-8"))
        return geojson
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in zones file: {e}")


def load_spatial_index(geojson: Dict[str, Any]) -> tuple[List, Optional[STRtree]]:
    """
    Build spatial index from GeoJSON for fast polygon queries.
    
    Args:
        geojson: GeoJSON FeatureCollection or Feature
        
    Returns:
        Tuple of (list of shapely polygons, STRtree spatial index)
        Returns ([], None) if no valid polygons found
    """
    try:
        features = geojson.get("features", []) if geojson.get("type") == "FeatureCollection" else [geojson]
        
        polys = []
        for feature in features:
            geom = feature.get("geometry")
            if geom and geom.get("type") in ("Polygon", "MultiPolygon"):
                try:
                    poly = shape(geom)
                    if poly.is_valid:
                        polys.append(poly)
                except Exception as e:
                    logger.warning(f"Could not convert geometry to polygon: {e}")
                    continue
        
        if not polys:
            logger.info("No valid polygons found in GeoJSON")
            return [], None
        
        tree = STRtree(polys)
        return polys, tree
    except Exception as e:
        logger.error(f"Error building spatial index: {e}")
        return [], None


# ============================================================================
# Avoid Zones Processing
# ============================================================================


def _apply_pbf_penalties_background():
    """
    Background task to apply PBF penalties. This runs in a separate thread
    to avoid blocking the API and to isolate memory usage.
    """
    try:
        from .cutter import apply_penalties

        pbf_path = OSRM_DATA_DIR / PBF_NAME
        modified_pbf = pbf_path.with_stem(f"{pbf_path.stem}_avoidzones")

        if not pbf_path.exists():
            logger.error(f"PBF file not found: {pbf_path}")
            return

        logger.info("[BG] Applying penalties to PBF...")
        apply_penalties(
            pbf_path, LATEST_POLYGONS, modified_pbf, location_store="mmap"
        )
        logger.info("[BG] Penalties applied successfully")

        size_mb = modified_pbf.stat().st_size / 1024 / 1024
        logger.info(f"[BG] Modified PBF created ({size_mb:.1f} MB)")
        logger.info("[BG] Reprocessing OSRM...")
        reprocess_osrm(modified_pbf.name)

        import time

        time.sleep(2)

        pbf_stem = modified_pbf.stem
        expected_files = [
            OSRM_DATA_DIR / f"{pbf_stem}.osrm.hsgr",
            OSRM_DATA_DIR / f"{pbf_stem}.osrm.prf",
        ]
        for f in expected_files:
            if not f.exists():
                logger.error(f"[BG] Expected partition file missing: {f}")
                return

        logger.info("[BG] Restarting OSRM container...")
        restart_osrm()
        logger.info("[BG] PBF reprocessing completed successfully")
    except Exception as e:
        logger.error(f"[BG] Error during PBF reprocessing: {e}")


def process_avoidzones(geojson: dict) -> str:
    """
    Process avoid zones:
    1. Save the geojson to history
    2. Convert polygons to Lua format
    3. Start PBF reprocessing in background thread (non-blocking)

    Returns the filename of the saved history entry immediately,
    while PBF reprocessing happens in the background.
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
    logger.info(f"Saved as latest polygons: {LATEST_POLYGONS}")

    # Convert to Lua format
    lua_zones_file = OSRM_DATA_DIR / "profiles" / "avoid_zones_data.lua"
    try:
        logger.info("Converting polygons to Lua format...")
        if write_lua_zones_file(LATEST_POLYGONS, lua_zones_file):
            logger.info(f"Lua zones file written to {lua_zones_file}")
        else:
            logger.warning("Failed to write Lua zones file, continuing anyway")
    except Exception as e:
        logger.error(f"Failed to convert polygons to Lua: {e}")
        logger.warning("Continuing despite Lua conversion error")

    # Start PBF reprocessing in background thread (non-blocking)
    logger.info("Scheduling PBF reprocessing in background...")
    thread = threading.Thread(
        target=_apply_pbf_penalties_background,
        name="PBF-Reprocessing",
        daemon=True,
    )
    thread.start()

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


@app.get("/route/v1/driving/{coordinates}")
async def route_with_zones(
    coordinates: str,
    zones_version: Optional[str] = Query(None, description="Avoid zones version ID (latest or avoidzones_YYYYMMDD_HHMMSS)"),
    avoid_mode: str = Query("penalize", description="'filter' (exclude routes) or 'penalize' (score routes)"),
    alternatives: int = Query(1, ge=1, le=3, description="Number of alternative routes"),
) -> Dict[str, Any]:
    """
    Route with client-side avoid zones filtering.
    
    Request route from OSRM, then filter/penalize based on avoid zones.
    
    Args:
        coordinates: OSRM format "lng1,lat1;lng2,lat2"
        zones_version: Avoid zones config to use ("latest" or version ID)
        avoid_mode: "filter" (exclude routes in zones) or "penalize" (return all routes with scores)
        alternatives: Number of alternative routes (1-3)
        
    Returns:
        OSRM response with added penalties and zones metadata
    """
    try:
        # Validate avoid_mode
        if avoid_mode not in ("filter", "penalize"):
            raise HTTPException(
                status_code=400,
                detail="avoid_mode must be 'filter' or 'penalize'",
            )
        
        # Load zones configuration
        logger.info(f"Loading zones version: {zones_version or 'latest'}")
        geojson = load_zones_version(zones_version)
        polys, tree = load_spatial_index(geojson)
        
        polygon_count = len(polys)
        logger.info(f"Loaded {polygon_count} avoid zone polygons")
        
        # Request route from OSRM
        logger.info(f"Requesting {alternatives} route(s) from OSRM")
        osrm_response = await request_osrm(
            coordinates,
            alternatives=alternatives,
            overview="full",
            geometries="geojson",
        )
        
        if not osrm_response.get("routes"):
            logger.warning("No routes found from OSRM")
            return osrm_response
        
        # Process routes through zones
        processed_routes = []
        intersection_info = {}
        
        for idx, route in enumerate(osrm_response["routes"]):
            coords = route["geometry"]["coordinates"]
            intersection_data = check_route_intersections(coords, polys, tree)
            
            # Apply avoid mode logic
            if avoid_mode == "filter" and intersection_data["intersection_count"] > 0:
                logger.info(f"Route {idx} filtered (crosses {intersection_data['intersection_count']} zones)")
                continue  # Skip routes with intersections
            elif avoid_mode == "penalize":
                # Add penalty information to route
                if "penalties" not in route:
                    route["penalties"] = {}
                route["penalties"] = {
                    "zone_intersections": intersection_data["intersection_count"],
                    "intersection_length_km": intersection_data["total_length_km"],
                    "penalty_score": intersection_data["penalty_ratio"],
                }
            
            processed_routes.append(route)
            intersection_info[f"route_{len(processed_routes)-1}"] = intersection_data
        
        # Sort routes by penalty score (best first)
        if avoid_mode == "penalize":
            processed_routes.sort(
                key=lambda r: r.get("penalties", {}).get("penalty_score", 0)
            )
        
        # Return processed response
        osrm_response["routes"] = processed_routes
        osrm_response["zones_applied"] = {
            "version": zones_version or "latest",
            "polygon_count": polygon_count,
        }
        osrm_response["intersection_info"] = intersection_info
        
        logger.info(
            f"Returning {len(processed_routes)} route(s) with {polygon_count} zones applied"
        )
        return osrm_response
        
    except FileNotFoundError as e:
        logger.error(f"Zones file not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        logger.error(f"Invalid version format: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in route_with_zones: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Routing failed: {str(e)}")


# ============================================================================
# Scheduled Tasks (Cron)
# ============================================================================


def auto_refresh_pbf():
    """Scheduled task: re-pull PBF (no longer reapplies with Lua-only approach)."""
    logger.info("[CRON] Auto-refresh task starting...")

    if not OSM_PBF_URL:
        logger.warning("[CRON] OSM_PBF_URL not set, skipping PBF download")
        return

    # Download fresh PBF
    if not download_pbf():
        logger.error("[CRON] Failed to download PBF")
        return

    logger.info("[CRON] PBF downloaded successfully")

    # NOTE: With Lua-only approach, we no longer need to reapply polygons
    # The Lua profile will use whatever zones are defined in avoid_zones_data.lua
    # This makes the cron task much faster.
    #
    # COMMENTED OUT:
    # if LATEST_POLYGONS.exists():
    #     try:
    #         geojson = json.loads(LATEST_POLYGONS.read_text(encoding="utf-8"))
    #         process_avoidzones(geojson)
    #     except Exception as e:
    #         logger.error(f"[CRON] Failed to reapply polygons: {e}")
    #
    # To reapply polygons after PBF refresh in the future, call /avoidzones/apply again


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
