"""
Version manager for avoid zones configurations.

Implements sequential versioning (v1, v2, v3...) without timestamps
and provides deduplication of identical configurations.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


def _normalize_geojson_for_comparison(geojson: Dict[str, Any]) -> str:
    """
    Normalize GeoJSON to a comparable string form.
    
    Sorts features and coordinates consistently to enable comparison.
    """
    # Create a copy to avoid modifying the original
    normalized = json.loads(json.dumps(geojson))
    
    # Sort features by their stringified geometry for consistency
    if normalized.get("type") == "FeatureCollection":
        normalized["features"] = sorted(
            normalized["features"],
            key=lambda f: json.dumps(f, sort_keys=True, separators=(',', ':'))
        )
    
    # Return canonical JSON string
    return json.dumps(normalized, sort_keys=True, separators=(',', ':'))


def find_next_version_number(history_dir: Path) -> int:
    """
    Find the next sequential version number.
    
    Scans the history directory for existing versioned files (v1.geojson, v2.geojson, etc.)
    and returns the next number.
    
    Args:
        history_dir: Path to the history directory
        
    Returns:
        Next sequential version number (starting from 1)
    """
    if not history_dir.exists():
        return 1
    
    max_version = 0
    for f in history_dir.glob("v*.geojson"):
        try:
            # Extract version number from filename like "v123.geojson"
            version_str = f.stem[1:]  # Remove 'v' prefix
            version_num = int(version_str)
            max_version = max(max_version, version_num)
        except (ValueError, IndexError):
            # Skip files that don't match pattern
            continue
    
    return max_version + 1


def find_duplicate_version(
    new_geojson: Dict[str, Any], 
    history_dir: Path
) -> Optional[str]:
    """
    Check if the new GeoJSON already exists in history (exact duplicate).
    
    Args:
        new_geojson: The new GeoJSON to check
        history_dir: Path to the history directory
        
    Returns:
        Filename of the duplicate version (without .geojson) if found, else None
    """
    if not history_dir.exists():
        return None
    
    new_canonical = _normalize_geojson_for_comparison(new_geojson)
    
    # Check all versioned files
    for f in sorted(history_dir.glob("v*.geojson")):
        try:
            existing_geojson = json.loads(f.read_text(encoding="utf-8"))
            existing_canonical = _normalize_geojson_for_comparison(existing_geojson)
            
            if new_canonical == existing_canonical:
                return f.stem  # Return filename without .geojson
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read version file {f}: {e}")
            continue
    
    return None


def save_version(
    geojson: Dict[str, Any],
    history_dir: Path,
    check_duplicates: bool = True
) -> Tuple[str, bool]:
    """
    Save a new version of avoid zones GeoJSON.
    
    Implements versioning scheme (v1.geojson, v2.geojson, etc.) with optional
    deduplication. If a duplicate is found and check_duplicates is True,
    returns the existing version instead of creating a new one.
    
    Args:
        geojson: The GeoJSON FeatureCollection to save
        history_dir: Path to the history directory
        check_duplicates: If True, check for duplicates and reuse existing version
        
    Returns:
        Tuple of (filename_without_extension, is_new_version)
        - filename_without_extension: e.g., "v5" (without .geojson)
        - is_new_version: True if new version was created, False if duplicate was found
        
    Raises:
        ValueError: If GeoJSON is invalid
    """
    # Validate GeoJSON
    if geojson.get("type") != "FeatureCollection":
        raise ValueError("Expected FeatureCollection")
    
    if not geojson.get("features"):
        raise ValueError("FeatureCollection must contain at least one feature")
    
    # Create history directory if needed
    history_dir.mkdir(parents=True, exist_ok=True)
    
    # Check for duplicates
    if check_duplicates:
        duplicate = find_duplicate_version(geojson, history_dir)
        if duplicate:
            logger.info(f"Found duplicate configuration: {duplicate}")
            return duplicate, False
    
    # Generate new version number
    next_version = find_next_version_number(history_dir)
    version_filename = f"v{next_version}"
    version_file = history_dir / f"{version_filename}.geojson"
    
    # Save to file
    version_file.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
    logger.info(f"Saved new version: {version_filename}")
    
    return version_filename, True


def load_version(version_id: Optional[str], history_dir: Path) -> Dict[str, Any]:
    """
    Load a specific version from history.
    
    Args:
        version_id: Version identifier ("latest", "v5", "5", or None for latest)
        history_dir: Path to the history directory
        
    Returns:
        Parsed GeoJSON dictionary
        
    Raises:
        FileNotFoundError: If version not found
        ValueError: If invalid version format or JSON is corrupted
    """
    if version_id is None or version_id == "latest":
        # Find the highest version number
        next_ver = find_next_version_number(history_dir)
        if next_ver <= 1:
            raise FileNotFoundError("No versions found in history")
        version_id = f"v{next_ver - 1}"
    else:
        # Normalize version_id format
        if not version_id.startswith("v"):
            version_id = f"v{version_id}"
        
        # Validate format to prevent directory traversal
        if "." in version_id or "/" in version_id or "\\" in version_id:
            raise ValueError(f"Invalid version format: {version_id}")
    
    file_path = history_dir / f"{version_id}.geojson"
    
    if not file_path.exists():
        raise FileNotFoundError(f"Version not found: {version_id}")
    
    try:
        geojson = json.loads(file_path.read_text(encoding="utf-8"))
        return geojson
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in version file: {e}")


def list_versions(history_dir: Path) -> list[Dict[str, Any]]:
    """
    List all versions in history, sorted by version number (descending).
    
    Args:
        history_dir: Path to the history directory
        
    Returns:
        List of dicts with keys: version, filename, size_bytes, features_count
    """
    items = []
    
    if not history_dir.exists():
        return items
    
    # Collect and sort versioned files
    version_files = []
    for f in history_dir.glob("v*.geojson"):
        try:
            version_str = f.stem[1:]  # Remove 'v' prefix
            version_num = int(version_str)
            version_files.append((version_num, f))
        except (ValueError, IndexError):
            continue
    
    # Sort by version number (descending)
    version_files.sort(key=lambda x: x[0], reverse=True)
    
    for version_num, file_path in version_files:
        try:
            stat = file_path.stat()
            geojson = json.loads(file_path.read_text(encoding="utf-8"))
            features_count = len(geojson.get("features", []))
            
            items.append({
                "version": f"v{version_num}",
                "filename": file_path.name,
                "size_bytes": stat.st_size,
                "features_count": features_count,
            })
        except (IOError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to read version {version_num}: {e}")
            continue
    
    return items


def cleanup_old_versions(history_dir: Path, keep_count: int = 0) -> int:
    """
    Remove old versions from history (optional cleanup).
    
    Args:
        history_dir: Path to the history directory
        keep_count: Number of recent versions to keep (0 = keep all)
        
    Returns:
        Number of versions deleted
        
    Note:
        This is an optional maintenance function. By default (keep_count=0),
        all versions are preserved.
    """
    if keep_count <= 0:
        return 0  # Don't delete anything by default
    
    if not history_dir.exists():
        return 0
    
    # Collect all versioned files
    version_files = []
    for f in history_dir.glob("v*.geojson"):
        try:
            version_str = f.stem[1:]
            version_num = int(version_str)
            version_files.append((version_num, f))
        except (ValueError, IndexError):
            continue
    
    # Sort by version number (ascending)
    version_files.sort(key=lambda x: x[0])
    
    # Remove all but the most recent keep_count versions
    deleted_count = 0
    for version_num, file_path in version_files[:-keep_count]:
        try:
            file_path.unlink()
            logger.info(f"Deleted old version: v{version_num}")
            deleted_count += 1
        except OSError as e:
            logger.warning(f"Failed to delete version v{version_num}: {e}")
    
    return deleted_count
