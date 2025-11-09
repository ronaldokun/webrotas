# Recommendations for Remaining Issues in app.py

This document outlines recommended fixes for issues that were identified but not yet applied.

---

## Medium Priority Fixes

### 1. CORS Configuration Issue

**Current Problem:**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # Wildcard
    allow_credentials=True,        # With credentials - conflicting!
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Why it's a problem:**
- Browsers reject this combination as a security risk
- CORS headers won't be sent for credentialed requests
- Frontend won't be able to make authenticated API calls

**Recommended Fix:**

```python
import os

# Add to configuration section (after line 28)
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8081").split(",")

# Update CORS middleware (replace lines 59-65)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

logger.info(f"CORS enabled for origins: {ALLOWED_ORIGINS}")
```

**Environment Variable:**
In `.env` file:
```
# Comma-separated list of allowed origins
ALLOWED_ORIGINS=http://localhost:8081,https://example.com,https://routing.example.com
```

**Deployment:**
In `docker-compose.yml`:
```yaml
environment:
  ALLOWED_ORIGINS: ${ALLOWED_ORIGINS:-http://localhost:8081}
```

---

### 2. File Write Error Handling

**Current Problem:**
```python
# Lines 288, 292 - no error handling
history_file.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
LATEST_POLYGONS.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
```

**Risks:**
- Disk full errors crash the API
- Permission errors aren't distinguished from logic errors
- No transactional semantics (both succeed or both fail)

**Recommended Fix:**

```python
def process_avoidzones(geojson: dict) -> str:
    """..."""
    # ... existing code ...
    
    # Serialize GeoJSON once
    geojson_str = json.dumps(geojson, indent=2)
    
    # Save to history with error handling
    try:
        history_file.write_text(geojson_str, encoding="utf-8")
    except IOError as e:
        logger.error(f"Failed to write history file {history_file}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save configuration to history: {e}"
        )
    
    # Save as latest with rollback on failure
    try:
        LATEST_POLYGONS.write_text(geojson_str, encoding="utf-8")
    except IOError as e:
        logger.error(f"Failed to write latest polygons file: {e}")
        # Clean up history file to maintain consistency
        try:
            history_file.unlink()
        except Exception as cleanup_err:
            logger.error(f"Failed to clean up history file during rollback: {cleanup_err}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save configuration: {e}"
        )
    
    logger.info(f"Saved avoidzones to history: {filename}")
    
    # ... rest of function ...
```

---

### 3. OSRM_PROFILE Validation at Startup

**Current Problem:**
- Profile path is never validated
- Errors occur only when first OSRM command runs
- Takes a long time to discover the problem

**Recommended Fix:**

Add to `setup_scheduler()` or create a new startup check:

```python
def validate_configuration():
    """Validate configuration at startup."""
    logger.info("Validating configuration...")
    
    # Check OSRM_DATA_DIR exists
    if not OSRM_DATA_DIR.exists():
        logger.warning(f"OSRM_DATA_DIR does not exist: {OSRM_DATA_DIR}")
        logger.info("It will be created when Docker volume is mounted")
    
    # Check history directory
    if not HISTORY_DIR.exists():
        try:
            HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created history directory: {HISTORY_DIR}")
        except Exception as e:
            logger.error(f"Failed to create history directory: {e}")
            raise
    
    # Validate token is set
    if AVOIDZONES_TOKEN == "default-token":
        logger.warning("AVOIDZONES_TOKEN is set to default value - change for production!")
    
    # Check for OSRM profile in volume (when Docker is running)
    profile_path = OSRM_DATA_DIR / OSRM_PROFILE.lstrip("/")
    logger.info(f"OSRM profile path: {profile_path}")
    if OSRM_DATA_DIR.exists() and not profile_path.exists():
        logger.warning(
            f"OSRM profile not found at {profile_path}. "
            f"It will be checked when Docker container runs."
        )
    
    logger.info("Configuration validation complete")

# Update lifespan to call validation
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan: startup and shutdown events."""
    # Startup
    validate_configuration()
    scheduler = setup_scheduler()
    yield
    # Shutdown
    scheduler.shutdown()
    logger.info("Scheduler shut down")
```

---

### 4. Auto-Refresh Task Better Error Handling

**Current Problem:**
```python
def auto_refresh_pbf():
    # ...
    try:
        process_avoidzones(geojson)  # Raises HTTPException
        logger.info("[CRON] Auto-refresh completed successfully")
    except Exception as e:
        logger.error(f"[CRON] Failed to reapply polygons: {e}")
        # ← Silent failure, no notification
```

**Issues:**
- HTTPException is not meant for background tasks
- Task failure isn't reported anywhere
- Scheduler might not retry properly

**Recommended Fix:**

```python
def auto_refresh_pbf():
    """Scheduled task: re-pull PBF and reapply latest polygons."""
    logger.info("[CRON] Auto-refresh task starting...")
    
    try:
        if not OSM_PBF_URL:
            logger.warning("[CRON] OSM_PBF_URL not set, skipping PBF download")
            return

        # Download fresh PBF
        if not download_pbf():
            logger.error("[CRON] Failed to download PBF - aborting auto-refresh")
            # Note: We still have the previous PBF, so routing still works
            return

        # Reapply latest polygons if they exist
        if LATEST_POLYGONS.exists():
            try:
                logger.info("[CRON] Reapplying latest polygons...")
                geojson = json.loads(LATEST_POLYGONS.read_text(encoding="utf-8"))
                # Call process_avoidzones but catch HTTPException
                try:
                    process_avoidzones(geojson)
                except HTTPException as e:
                    # Convert HTTPException to regular error for background task
                    raise RuntimeError(f"Failed to process avoidzones: {e.detail}")
                logger.info("[CRON] Auto-refresh completed successfully")
            except Exception as e:
                logger.error(f"[CRON] Failed to reapply polygons: {e}", exc_info=True)
                # TODO: Add monitoring/alerting here (e.g., send to Slack, PagerDuty)
                # send_alert(f"Auto-refresh failed: {e}")
        else:
            logger.info("[CRON] No saved polygons to reapply, rebuilt from fresh PBF only")

    except Exception as e:
        logger.error(f"[CRON] Unexpected error in auto-refresh: {e}", exc_info=True)
        # TODO: Add monitoring/alerting here
        # send_alert(f"Auto-refresh task failed: {e}")
```

**Monitoring Integration Example:**

```python
def send_alert(message: str):
    """Send alert to monitoring system (example using environment variables)."""
    slack_webhook = os.getenv("SLACK_WEBHOOK_URL")
    if slack_webhook:
        try:
            import requests
            requests.post(slack_webhook, json={"text": f"🚨 webrotas: {message}"})
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")
    
    # Could also integrate with other systems
    # PagerDuty, Datadog, CloudWatch, etc.
```

Add to environment:
```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

---

## Low Priority Improvements

### 5. Enhanced GeoJSON Validation

**Current Implementation:**
```python
if geojson.get("type") != "FeatureCollection":
    raise ValueError("Expected FeatureCollection")
```

**Enhancement:**
```python
def validate_geojson(geojson: dict) -> None:
    """Validate GeoJSON structure."""
    if geojson.get("type") != "FeatureCollection":
        raise ValueError("Expected FeatureCollection")
    
    features = geojson.get("features", [])
    if not features:
        raise ValueError("FeatureCollection must contain at least one feature")
    
    for i, feature in enumerate(features):
        if feature.get("type") != "Feature":
            raise ValueError(f"Feature {i}: Expected type 'Feature'")
        
        geometry = feature.get("geometry")
        if not geometry:
            raise ValueError(f"Feature {i}: Missing geometry")
        
        geom_type = geometry.get("type")
        if geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"Feature {i}: Geometry type '{geom_type}' not supported. Use Polygon or MultiPolygon.")
        
        coords = geometry.get("coordinates")
        if not coords:
            raise ValueError(f"Feature {i}: Missing coordinates")

# Use in process_avoidzones
def process_avoidzones(geojson: dict) -> str:
    """..."""
    try:
        validate_geojson(geojson)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # ... rest of function ...
```

---

### 6. Better Logging for Debugging

**Enhancement:**
```python
# Add to OSRM helpers for better debugging
def reprocess_osrm(pbf_filename: str):
    """..."""
    try:
        pbf_path = OSRM_DATA_DIR / pbf_filename
        pbf_stem = pbf_path.stem
        pbf_size = pbf_path.stat().st_size / (1024 * 1024)
        
        logger.info(
            f"Starting OSRM reprocessing: "
            f"filename={pbf_filename}, "
            f"size={pbf_size:.1f}MB, "
            f"stem={pbf_stem}"
        )
        
        # ... rest of function ...
        
        logger.info(
            f"Completed OSRM reprocessing for {pbf_filename}: "
            f"extract+partition+customize took ~XX seconds"
        )
```

---

## Implementation Priority

**Immediate (this release):**
1. ✅ Docker exit code validation (DONE)
2. ✅ Modified PBF file verification (DONE)
3. ✅ PBF path/filename confusion (DONE)
4. ✅ OSRM restart race condition (DONE)

**Next release (High):**
1. CORS configuration fix
2. File write error handling
3. OSRM_PROFILE validation at startup

**Following release (Medium):**
1. Auto-refresh task error handling with alerts
2. Enhanced GeoJSON validation
3. Better structured logging

---

## Testing Strategy

Before implementing each fix:

1. **Unit tests** - Test the specific function in isolation
2. **Integration tests** - Test within the full API flow
3. **Error case tests** - Test the specific error condition
4. **Manual testing** - Verify in Docker environment

### Example Unit Test Template

```python
# tests/test_app.py
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from src.webrotas.app import app

client = TestClient(app)

def test_cors_configuration():
    """Verify CORS headers are set correctly."""
    os.environ["ALLOWED_ORIGINS"] = "http://localhost:8081,http://localhost:3000"
    # Reload app to pick up new env var
    # ... test CORS headers in response ...

def test_file_write_error_handling(tmp_path):
    """Test that file write errors are handled gracefully."""
    # Mock read-only filesystem
    # Test that HTTPException is raised with appropriate status code

def test_auto_refresh_failure_handling():
    """Test that auto-refresh logs errors without crashing."""
    # Mock download_pbf to fail
    # Verify task completes without unhandled exception
```

---

## Deployment Checklist

- [ ] Review analysis document with team
- [ ] Code review of fixes
- [ ] Run all existing tests
- [ ] Add new unit tests for edge cases
- [ ] Test in staging environment
- [ ] Update API documentation if needed
- [ ] Plan rollback strategy
- [ ] Deploy and monitor logs
- [ ] Verify OSRM routing still works after deployment
- [ ] Plan implementation of remaining fixes for next release
