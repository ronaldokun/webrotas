# Version System Quick Reference

## For Users/API Consumers

### List all versions
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:9090/avoidzones/history
```

Response:
```json
[
  {
    "version": "v3",
    "filename": "v3.geojson",
    "size_bytes": 2048,
    "features_count": 2
  },
  {
    "version": "v2",
    "filename": "v2.geojson",
    "size_bytes": 1024,
    "features_count": 1
  }
]
```

### Use a specific version for routing
```bash
curl "http://localhost:9090/route/v1/driving/13.3,-13;13.4,-13.1?zones_version=v2"
```

Accepted formats:
- `zones_version=v2` (with v prefix)
- `zones_version=2` (without v prefix)
- `zones_version=latest` (latest version)
- No parameter defaults to latest

### Apply new zones (automatic versioning)
```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d @zones.geojson \
  http://localhost:9090/avoidzones/apply
```

Response (if new):
```json
{
  "status": "success",
  "filename": "v4"
}
```

Response (if duplicate):
```json
{
  "status": "success",
  "filename": "v2"
}
```

### Download a version
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  -o zones_v2.geojson \
  http://localhost:9090/avoidzones/download/v2.geojson
```

### Revert to a previous version
```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"filename": "v2.geojson"}' \
  http://localhost:9090/avoidzones/revert
```

## For Developers

### Import the version manager
```python
from src.webrotas.version_manager import (
    save_version,
    load_version,
    list_versions,
    find_duplicate_version,
    find_next_version_number,
    cleanup_old_versions,
)
from pathlib import Path
```

### Save a new version (with deduplication)
```python
history_dir = Path("/data/avoidzones_history")
geojson = {...}  # Your GeoJSON FeatureCollection

version_name, is_new = save_version(
    geojson, 
    history_dir, 
    check_duplicates=True  # Detect duplicates
)

if is_new:
    print(f"New version created: {version_name}")
else:
    print(f"Duplicate found, using existing: {version_name}")
```

### Load a version
```python
# Load latest
geojson = load_version("latest", history_dir)

# Load specific
geojson = load_version("v3", history_dir)  # or just "3"
```

### List all versions
```python
versions = list_versions(history_dir)
for v in versions:
    print(f"{v['version']}: {v['features_count']} features, {v['size_bytes']} bytes")
```

### Check for duplicates before saving
```python
duplicate = find_duplicate_version(geojson, history_dir)
if duplicate:
    print(f"This configuration already exists as {duplicate}")
else:
    print("Configuration is new")
```

### Save without deduplication (force new version)
```python
version_name, _ = save_version(
    geojson, 
    history_dir, 
    check_duplicates=False  # Always create new version
)
```

### Find next version number
```python
next_num = find_next_version_number(history_dir)
print(f"Next version will be: v{next_num}")
```

### Clean up old versions (keep only 10 most recent)
```python
deleted = cleanup_old_versions(history_dir, keep_count=10)
print(f"Deleted {deleted} old versions")
```

## Key Concepts

### Deduplication
- **What**: Automatic detection of identical configurations
- **How**: Canonical JSON comparison with sorted features
- **Feature order independence**: Features in different order still detected as duplicates
- **Benefit**: Prevents expensive PBF reprocessing for duplicate configs

### Sequential Versioning
- **Format**: `v1`, `v2`, `v3`, ... (simple incremental numbers)
- **File naming**: `v1.geojson`, `v2.geojson`, etc.
- **Sorting**: Handled automatically (no timestamp parsing needed)

### Version ID Formats (all equivalent)
```python
load_version("v5", history_dir)     # With v prefix
load_version("5", history_dir)      # Without v prefix  
load_version("latest", history_dir) # Latest version
load_version(None, history_dir)     # None defaults to latest
```

## Performance Notes

✓ **Deduplication enabled by default**: Saves PBF reprocessing time
✓ **Fast lookups**: Sequential numbering is simpler than timestamp parsing
✓ **Independent feature order**: Comparison still works efficiently

⚠ **No file deduplication**: Duplicate configs still stored separately (not hardlinked)

## Common Patterns

### Pattern 1: Apply zones and handle duplicates
```python
geojson = load_geojson_from_file("new_zones.json")
version, is_new = save_version(geojson, history_dir)

if is_new:
    reprocess_osrm()  # Expensive operation
    restart_osrm()
else:
    log(f"Using existing configuration: {version}")
```

### Pattern 2: Get latest zones for routing
```python
try:
    zones_geojson = load_version(None, history_dir)  # Latest
    polys, tree = build_spatial_index(zones_geojson)
except FileNotFoundError:
    log("No zones configured yet")
    polys, tree = [], None
```

### Pattern 3: Manage version history
```python
versions = list_versions(history_dir)

# Show history to user
for v in versions:
    print(f"{v['version']}: {v['features_count']} zones")

# Keep only last 20 versions
cleanup_old_versions(history_dir, keep_count=20)
```

## Troubleshooting

### Q: Why didn't a new version get created?
**A**: The configuration matches an existing version (deduplication). Disable with `check_duplicates=False` if this is incorrect.

### Q: How do I force creating a new version?
**A**: Use `save_version(..., check_duplicates=False)`

### Q: Can I access old timestamp-based versions?
**A**: Old files are preserved but not listed by the version system. Direct filesystem access shows them.

### Q: What if I want to keep all versions forever?
**A**: Use `cleanup_old_versions(history_dir, keep_count=0)` (default) to keep all versions.
