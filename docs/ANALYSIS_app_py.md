# Deep Analysis of src/webrotas/app.py

## Critical Issues Found

### 1. **PBF Download Success Not Checked (Line 242)**
**Location:** `download_pbf()` function, line 242-248

**Issue:** The subprocess result is assigned to `result` but never validated for success.
```python
result = subprocess.run(
    ["curl", "-L", "--fail", "-o", str(pbf_tmp), OSM_PBF_URL],
    check=True,
    capture_output=True,
    text=True,
    timeout=3600,
)
pbf_tmp.rename(pbf_path)  # ← Proceeds immediately without checking result
```

**Problem:** While `check=True` will raise an exception if the process fails, the `result` object is not inspected for actual success indicators. The temp file rename happens unconditionally after subprocess call.

**Correct Approach:** The current approach actually works because `check=True` raises `CalledProcessError` if curl fails. However, we should:
- Verify the temp file exists before renaming (defensive programming)
- Check file size is non-zero

**Recommendation:**
```python
result = subprocess.run(
    ["curl", "-L", "--fail", "-o", str(pbf_tmp), OSM_PBF_URL],
    check=True,
    capture_output=True,
    text=True,
    timeout=3600,
)
# Defensive checks
if not pbf_tmp.exists():
    raise ValueError(f"PBF download failed: {pbf_tmp} does not exist")
file_size = pbf_tmp.stat().st_size
if file_size == 0:
    pbf_tmp.unlink()
    raise ValueError("PBF download resulted in empty file")
pbf_tmp.rename(pbf_path)
```

---

### 2. **Docker Container Commands Don't Check Exit Code**
**Location:** `reprocess_osrm()` function, lines 156-205

**Issue:** The Docker API's `containers.run()` method returns output but doesn't explicitly validate exit codes. The function only logs output but doesn't check if commands actually succeeded.

**Problem:**
- `client.containers.run()` returns stdout/stderr output
- No validation that the container exited with code 0
- An OSRM preprocessing command could silently fail and output nothing

**Example failure scenario:**
```python
result = client.containers.run(
    osrm_image,
    f"osrm-extract -p {OSRM_PROFILE} /data/{pbf_name}",  # Profile might not exist
    volumes=volume_bind,
    rm=True,
)
# If profile is missing, this silently fails with no error raised
logger.info(f"osrm-extract completed: {result}")  # Logs empty result
```

**Recommendation:** Check container exit code:
```python
container = client.containers.run(
    osrm_image,
    f"osrm-extract -p {OSRM_PROFILE} /data/{pbf_name}",
    volumes=volume_bind,
    rm=False,  # Don't remove, so we can check status
)
exit_code = container.wait()
if exit_code != 0:
    logs = container.logs(stdout=True, stderr=True).decode()
    container.remove()
    raise RuntimeError(f"osrm-extract failed with exit code {exit_code}: {logs}")
container.remove()
```

---

### 3. **Modified PBF File Not Verified Before Reprocessing**
**Location:** `process_avoidzones()` function, lines 303-310

**Issue:** After `apply_penalties()` creates `modified_pbf`, the file is passed to `reprocess_osrm()` without verifying it was successfully created.

```python
apply_penalties(pbf_path, LATEST_POLYGONS, modified_pbf)  # Creates file
logger.info("Penalties applied successfully")

# No check that modified_pbf exists or has valid content
reprocess_osrm(modified_pbf.name)  # Uses filename only, not full path
```

**Problems:**
1. `apply_penalties()` could fail silently without creating the file
2. `reprocess_osrm()` receives only filename, not full path, creating ambiguity
3. If file doesn't exist, Docker will fail with unclear error

**Recommendation:**
```python
apply_penalties(pbf_path, LATEST_POLYGONS, modified_pbf)
logger.info("Penalties applied successfully")

# Verify modified PBF was created and has content
if not modified_pbf.exists():
    raise ValueError(f"Modified PBF file not created: {modified_pbf}")
file_size = modified_pbf.stat().st_size
if file_size == 0:
    modified_pbf.unlink()
    raise ValueError("Modified PBF file is empty after applying penalties")
logger.info(f"Modified PBF created successfully ({file_size / 1024 / 1024:.1f} MB)")

# Pass full path instead of just name
reprocess_osrm(str(modified_pbf))
```

---

### 4. **PBF Path vs Filename Confusion in reprocess_osrm()**
**Location:** `reprocess_osrm()` function, line 310

**Issue:** The function receives `pbf_name` (only filename from `modified_pbf.name`), but constructs Docker paths assuming it's relative to `/data`:

```python
def reprocess_osrm(pbf_name: str):  # pbf_name = "region_avoidzones.osm.pbf"
    pbf_stem = Path(pbf_name).stem   # stem = "region_avoidzones"
    # ...
    f"osrm-extract -p {OSRM_PROFILE} /data/{pbf_name}"  # /data/region_avoidzones.osm.pbf
```

**Problems:**
1. Only works if `pbf_name` is a simple filename (no directory separators)
2. If someone passes a full path, `Path.stem` will parse incorrectly
3. Type hint should clarify "filename only" vs "full path"

**Recommendation:**
```python
def reprocess_osrm(pbf_filename: str):
    """
    Reprocess PBF through OSRM pipeline.
    
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
        # ... rest of function
```

---

### 5. **OSRM Container Restart Race Condition**
**Location:** `process_avoidzones()` function, lines 310-313

**Issue:** After `reprocess_osrm()` completes preprocessing, `restart_osrm()` is called immediately:

```python
reprocess_osrm(modified_pbf.name)  # Runs extract/partition/customize
restart_osrm()                      # Restarts container immediately after
```

**Problem:** The OSRM container might not have finished mounting/reading the newly created partition files before restart:
1. Partition files (`.osrm.hsgr`, `.osrm.prf`, etc.) are being written
2. Container is restarted before files are fully synced to disk
3. OSRM might fail to load incomplete partition files

**Recommendation:** Add delay or health check:
```python
reprocess_osrm(modified_pbf.name)

# Wait for files to sync to disk
import time
time.sleep(2)

# Verify partition files exist before restarting
pbf_stem = Path(modified_pbf).stem
expected_files = [
    OSRM_DATA_DIR / f"{pbf_stem}.osrm.hsgr",
    OSRM_DATA_DIR / f"{pbf_stem}.osrm.prf",
]
for f in expected_files:
    if not f.exists():
        raise ValueError(f"Expected partition file missing: {f}")

restart_osrm()
```

---

### 6. **No Validation of OSRM_PROFILE Path**
**Location:** Lines 23 and 158

**Issue:** `OSRM_PROFILE` is used directly in Docker command without validation:

```python
OSRM_PROFILE = os.getenv("OSRM_PROFILE", "/profiles/car_avoid.lua")  # Line 23
# ...
f"osrm-extract -p {OSRM_PROFILE} /data/{pbf_name}"  # Line 158
```

**Problems:**
1. Profile file might not exist in the container
2. Path might be wrong (e.g., if mounted incorrectly)
3. Docker will fail with unclear error message
4. No logging of which profile is being used

**Recommendation:** Log the profile being used:
```python
logger.info(f"Running osrm-extract with profile: {OSRM_PROFILE}")
# Consider adding a health check that the profile exists
```

---

### 7. **Unhandled JSON Parse Error in process_avoidzones()**
**Location:** Line 279-280

**Issue:** The GeoJSON type check is minimal:

```python
if geojson.get("type") != "FeatureCollection":
    raise ValueError("Expected FeatureCollection")
```

**Problem:** This doesn't validate the GeoJSON structure is actually valid:
- Features might be malformed
- Geometry coordinates might be invalid
- Pydantic validation happens upstream but could be more explicit here

**Recommendation:** Add more detailed validation or trust Pydantic (current approach is acceptable but could be more defensive).

---

### 8. **CORS Misconfiguration**
**Location:** Lines 59-65

**Issue:** Allow all origins with `allow_origins=["*"]` and `allow_credentials=True`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # ← Allows any origin
    allow_credentials=True,        # ← But also allows credentials (conflicting!)
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Problem:** This combination is a security issue:
- Browsers will reject CORS requests because you can't use `*` with credentials
- Effectively disables CORS for credential-based requests
- Should use specific origins in production

**Recommendation:**
```python
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:8081").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
```

---

### 9. **Auto-Refresh Task Not Catching All Exceptions**
**Location:** `auto_refresh_pbf()` function, lines 402-425

**Issue:** The function catches and logs exceptions but doesn't prevent task failure:

```python
try:
    process_avoidzones(geojson)  # Could raise HTTPException
    logger.info("[CRON] Auto-refresh completed successfully")
except Exception as e:
    logger.error(f"[CRON] Failed to reapply polygons: {e}")
    # Task silently fails - scheduler might mark job as failed
```

**Problem:**
1. `HTTPException` raised from `process_avoidzones()` isn't appropriate for background tasks
2. Scheduler might stop retrying failed jobs
3. No way to alert operators that auto-refresh failed

**Recommendation:**
```python
def auto_refresh_pbf():
    """Scheduled task: re-pull PBF and reapply latest polygons."""
    try:
        logger.info("[CRON] Auto-refresh task starting...")
        
        if not OSM_PBF_URL:
            logger.warning("[CRON] OSM_PBF_URL not set, skipping PBF download")
            return
        
        if not download_pbf():
            logger.error("[CRON] Failed to download PBF - task aborted")
            return
        
        if LATEST_POLYGONS.exists():
            geojson = json.loads(LATEST_POLYGONS.read_text(encoding="utf-8"))
            process_avoidzones(geojson)  # This raises HTTPException
        else:
            logger.info("[CRON] No saved polygons to reapply")
            
        logger.info("[CRON] Auto-refresh completed successfully")
    except Exception as e:
        logger.error(f"[CRON] Auto-refresh task failed: {e}", exc_info=True)
        # Consider sending alert/notification here
```

---

### 10. **Missing Error Handling for File Operations**
**Location:** Multiple locations (lines 288, 292)

**Issue:** File write operations don't have explicit error handling:

```python
history_file.write_text(json.dumps(geojson, indent=2), encoding="utf-8")  # Line 288
LATEST_POLYGONS.write_text(json.dumps(geojson, indent=2), encoding="utf-8")  # Line 292
```

**Problems:**
1. Disk full errors not handled
2. Permission errors not handled
3. Both operations succeed or both fail atomically
4. No verification of write success

**Recommendation:**
```python
try:
    history_file.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
except IOError as e:
    raise ValueError(f"Failed to write history file: {e}")

try:
    LATEST_POLYGONS.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
except IOError as e:
    # Clean up history file on failure
    if history_file.exists():
        history_file.unlink()
    raise ValueError(f"Failed to write latest polygons file: {e}")
```

---

## Summary of Severity Levels

| Issue | Severity | Type | Location |
|-------|----------|------|----------|
| Docker container exit codes not checked | **CRITICAL** | Runtime | `reprocess_osrm()` |
| Modified PBF not verified before use | **CRITICAL** | Runtime | `process_avoidzones()` |
| OSRM restart race condition | **HIGH** | Logic | `process_avoidzones()` |
| PBF filename/path confusion | **HIGH** | Design | `reprocess_osrm()` |
| OSRM_PROFILE path not validated | **MEDIUM** | Runtime | Configuration |
| CORS misconfiguration | **MEDIUM** | Security | App setup |
| Auto-refresh error handling | **MEDIUM** | Robustness | `auto_refresh_pbf()` |
| File write error handling | **MEDIUM** | Robustness | `process_avoidzones()` |
| PBF download check (original issue) | **LOW** | Code clarity | `download_pbf()` |
| GeoJSON validation | **LOW** | Robustness | `process_avoidzones()` |

---

## Recommended Action Plan

1. **Immediate (Critical):**
   - Add exit code checks to Docker container runs in `reprocess_osrm()`
   - Add file existence validation after `apply_penalties()` completes

2. **Short-term (High Priority):**
   - Fix PBF path handling and type hints in `reprocess_osrm()`
   - Add sync delay and file verification before OSRM restart
   - Validate OSRM_PROFILE path at startup

3. **Medium-term:**
   - Fix CORS configuration
   - Improve error handling in background tasks
   - Add defensive file I/O error handling

4. **Long-term:**
   - Add integration tests for the full pipeline
   - Add monitoring/alerting for failed operations
   - Consider adding transaction-like semantics (all-or-nothing operations)
