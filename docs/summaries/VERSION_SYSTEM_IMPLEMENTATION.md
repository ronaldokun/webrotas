# Version System Implementation Summary

## Overview

A new version system has been implemented for the webrotas avoid zones configuration management, replacing the previous timestamp-based approach with a clean, sequential numbering scheme (v1, v2, v3, etc.) and automatic deduplication.

## Key Changes

### 1. **New Version Manager Module**
Created `src/webrotas/version_manager.py` with the following components:

#### Functions:
- **`save_version(geojson, history_dir, check_duplicates=True)`**
  - Saves a new version with sequential naming (v1, v2, v3...)
  - Returns `(version_filename, is_new_version)` tuple
  - Automatically detects and reuses duplicate configurations
  - Validates GeoJSON format before saving

- **`load_version(version_id, history_dir)`**
  - Loads a specific version from history
  - Accepts multiple formats: `"latest"`, `"v5"`, `"5"`, or `None` (defaults to latest)
  - Normalizes version IDs automatically

- **`list_versions(history_dir)`**
  - Returns all versions sorted in descending order (newest first)
  - Includes metadata: version number, filename, size, feature count

- **`find_duplicate_version(geojson, history_dir)`**
  - Checks if a configuration already exists in history
  - Uses canonical JSON comparison for reliability
  - Feature order independent: two configurations with same features in different order are detected as duplicates

- **`find_next_version_number(history_dir)`**
  - Scans history directory and returns next sequential version number
  - Starts from 1 if directory is empty

- **`cleanup_old_versions(history_dir, keep_count=0)`**
  - Optional maintenance function for removing old versions
  - Default behavior keeps all versions (keep_count=0)

### 2. **Updated API Models**

**HistoryItem** (changed):
```python
class HistoryItem(BaseModel):
    version: str          # e.g., "v5"
    filename: str         # e.g., "v5.geojson"
    size_bytes: int       # File size in bytes
    features_count: int   # Number of features in configuration
```

### 3. **Integration with app.py**

Updated key functions:

- **`process_avoidzones(geojson)`**
  - Now uses `save_version()` with deduplication enabled
  - Only triggers PBF reprocessing for new versions
  - Skips costly reprocessing when a duplicate is detected

- **`load_zones_version(version_id)`**
  - Simplified wrapper around `load_version()` from version manager

- **`/avoidzones/history` endpoint**
  - Now uses `list_versions()` directly
  - Returns simplified metadata without timestamps

## Deduplication Strategy

### Normalization Process
1. **JSON Canonicalization**: Convert to standard JSON with sorted keys
2. **Feature Sorting**: Sort features consistently to handle feature order differences
3. **Comparison**: Compare normalized canonical JSON strings

### Benefits
- **Prevents duplicate PBF reprocessing**: Expensive operations only run for truly new configurations
- **Storage efficient**: Identical configurations aren't stored multiple times
- **Transparent**: Users don't need to manually check for duplicates
- **Order-independent**: Features can be in any order; still detected as duplicates

### Example
```python
# These are detected as the same version despite different order:
config_a = {"zones": [zone1, zone2]}
config_b = {"zones": [zone2, zone1]}

v1, _ = save_version(config_a, history_dir)  # Returns v1 (new)
v2, _ = save_version(config_b, history_dir)  # Returns v1 (duplicate found)
```

## Filename Format

**Old System**: `avoidzones_YYYYMMDD_HHMMSS.geojson`
```
avoidzones_20241111_171850.geojson
avoidzones_20241111_172015.geojson
```

**New System**: `vN.geojson`
```
v1.geojson
v2.geojson
v3.geojson
```

## API Endpoint Changes

### `/avoidzones/history` (GET)
**Response Format** (Old):
```json
[
  {
    "filename": "avoidzones_20241111_171850.geojson",
    "ts": "2024-11-11 17:18:50",
    "size": 2048
  }
]
```

**Response Format** (New):
```json
[
  {
    "version": "v3",
    "filename": "v3.geojson",
    "size_bytes": 2048,
    "features_count": 2
  }
]
```

### `/route/v1/driving/{coordinates}` (GET)
**zones_version parameter** (backwards compatible):
- Old: `zones_version=avoidzones_20241111_171850`
- New: `zones_version=v5` or `zones_version=5` (prefix "v" optional)
- Both formats supported for backward compatibility

### `/avoidzones/apply` (POST)
**Response Format** (Both):
```json
{
  "status": "success",
  "filename": "v3"
}
```

## Testing

Comprehensive test suite in `tests/test_version_system.py` with 15 test cases covering:
- Sequential version numbering
- Deduplication detection and reuse
- Feature order independence
- Version loading (latest, specific, by number)
- List operations and metadata
- Input validation
- Error handling

**All tests pass ✓**

## Migration Notes

### For Existing Deployments

The new version system is independent of the old timestamp-based files. During migration:

1. New configurations will be saved as `v1.geojson`, `v2.geojson`, etc.
2. Old `avoidzones_YYYYMMDD_HHMMSS.geojson` files remain untouched in the history directory
3. The `/avoidzones/history` endpoint will only list new sequential versions
4. To preserve history, manually rename old files to new format if desired

### Backward Compatibility

The API maintains backward compatibility in some areas:
- Version IDs can be specified with or without "v" prefix
- `load_zones_version()` accepts multiple formats
- Existing integrations using old timestamps may need updates

## Performance Implications

### Improvements
- **Reduced reprocessing**: Deduplication skips unnecessary OSRM rebuilds
- **Faster lookups**: Simple sequential numbering is faster than timestamp parsing
- **Cleaner storage**: No timestamp overhead in filenames

### Storage
- Each version is a separate `.geojson` file
- Size depends on polygon complexity, not version count
- No storage savings from deduplication (identical files are detected but not deduplicated)

## Future Enhancements

Potential improvements for future versions:

1. **Compression**: Store deduplicated configurations with symlinks or hardlinks
2. **Cleanup policies**: Auto-remove old versions based on retention policy
3. **Versioning metadata**: Store creation/modification timestamps in JSON metadata
4. **Configuration branching**: Support multiple configuration branches
5. **Diff visualization**: Show differences between versions in UI

## Configuration

No environment variables or configuration changes needed. The version system works automatically with existing configurations.

## Troubleshooting

### "Version not found: v5"
- Version v5 doesn't exist. Check available versions with `/avoidzones/history`
- Alternatively, use `/avoidzones/download/v5.geojson` to verify existence

### Duplicate detected unexpectedly
- Deduplication is based on coordinate and feature data
- Minor differences in floating-point precision may prevent deduplication
- Try with `check_duplicates=False` if genuinely different configurations are incorrectly flagged

### Old timestamp-based files not appearing
- The new system only lists sequential versions
- Old files are preserved on disk but not exposed through the API
- Direct filesystem access shows them in the history directory

## Files Modified/Created

### Created:
- `src/webrotas/version_manager.py` - Core versioning logic
- `tests/test_version_system.py` - Comprehensive test suite

### Modified:
- `src/webrotas/app.py` - Integration of version manager
  - Updated `HistoryItem` model
  - Updated `process_avoidzones()` function
  - Updated `load_zones_version()` function
  - Updated `/avoidzones/history` endpoint
  - Optimized to skip PBF reprocessing for duplicate configurations

## Conclusion

The new version system provides a cleaner, more efficient approach to managing avoid zones configurations with automatic deduplication to prevent unnecessary reprocessing of expensive PBF operations.
