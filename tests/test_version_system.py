"""
Tests for the new version system with sequential versioning and deduplication.
"""

import json
import sys
import tempfile
from pathlib import Path
import pytest

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.webrotas.version_manager import (
    save_version,
    load_version,
    list_versions,
    find_next_version_number,
    find_duplicate_version,
)


@pytest.fixture
def temp_history_dir():
    """Create a temporary history directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_sample_geojson(num_features: int = 1) -> dict:
    """Create a sample GeoJSON FeatureCollection."""
    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [0 + i, 0],
                        [1 + i, 0],
                        [1 + i, 1],
                        [0 + i, 1],
                        [0 + i, 0],
                    ]
                ],
            },
            "properties": {"name": f"zone_{i}"},
        }
        for i in range(num_features)
    ]
    return {"type": "FeatureCollection", "features": features}


def test_save_first_version(temp_history_dir):
    """Test saving the first version."""
    geojson = create_sample_geojson()
    version_name, is_new = save_version(geojson, temp_history_dir)

    assert version_name == "v1"
    assert is_new is True
    assert (temp_history_dir / "v1.geojson").exists()


def test_save_sequential_versions(temp_history_dir):
    """Test that versions are numbered sequentially."""
    geojson1 = create_sample_geojson(1)
    geojson2 = create_sample_geojson(2)
    geojson3 = create_sample_geojson(3)

    v1, is_new1 = save_version(geojson1, temp_history_dir)
    v2, is_new2 = save_version(geojson2, temp_history_dir)
    v3, is_new3 = save_version(geojson3, temp_history_dir)

    assert v1 == "v1"
    assert v2 == "v2"
    assert v3 == "v3"
    assert all([is_new1, is_new2, is_new3])


def test_deduplication(temp_history_dir):
    """Test that duplicate configurations are detected and reused."""
    geojson = create_sample_geojson(1)

    v1, is_new1 = save_version(geojson, temp_history_dir, check_duplicates=True)
    v2, is_new2 = save_version(geojson, temp_history_dir, check_duplicates=True)

    assert v1 == "v1"
    assert v2 == "v1"  # Should return existing version
    assert is_new1 is True
    assert is_new2 is False  # Duplicate detected


def test_deduplication_disabled(temp_history_dir):
    """Test that deduplication can be disabled."""
    geojson = create_sample_geojson(1)

    v1, is_new1 = save_version(geojson, temp_history_dir, check_duplicates=True)
    v2, is_new2 = save_version(geojson, temp_history_dir, check_duplicates=False)

    assert v1 == "v1"
    assert v2 == "v2"  # New version created despite being duplicate
    assert is_new1 is True
    assert is_new2 is True


def test_load_latest_version(temp_history_dir):
    """Test loading the latest version."""
    geojson1 = create_sample_geojson(1)
    geojson2 = create_sample_geojson(2)

    save_version(geojson1, temp_history_dir)
    save_version(geojson2, temp_history_dir)

    loaded = load_version("latest", temp_history_dir)
    assert loaded["features"].__len__() == 2


def test_load_specific_version(temp_history_dir):
    """Test loading a specific version by number."""
    geojson1 = create_sample_geojson(1)
    geojson2 = create_sample_geojson(2)

    save_version(geojson1, temp_history_dir)
    save_version(geojson2, temp_history_dir)

    loaded = load_version("v1", temp_history_dir)
    assert len(loaded["features"]) == 1


def test_load_version_by_number_only(temp_history_dir):
    """Test loading a version by number without 'v' prefix."""
    geojson = create_sample_geojson(1)
    save_version(geojson, temp_history_dir)

    # Should work with just the number
    loaded = load_version("1", temp_history_dir)
    assert len(loaded["features"]) == 1


def test_load_nonexistent_version(temp_history_dir):
    """Test that loading a nonexistent version raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_version("v999", temp_history_dir)


def test_list_versions_empty(temp_history_dir):
    """Test listing versions when directory is empty."""
    versions = list_versions(temp_history_dir)
    assert versions == []


def test_list_versions_ordering(temp_history_dir):
    """Test that versions are listed in descending order."""
    for i in range(3):
        geojson = create_sample_geojson(i + 1)
        save_version(geojson, temp_history_dir)

    versions = list_versions(temp_history_dir)

    assert len(versions) == 3
    assert versions[0]["version"] == "v3"
    assert versions[1]["version"] == "v2"
    assert versions[2]["version"] == "v1"


def test_list_versions_includes_metadata(temp_history_dir):
    """Test that list_versions includes all required metadata."""
    geojson = create_sample_geojson(2)
    save_version(geojson, temp_history_dir)

    versions = list_versions(temp_history_dir)

    assert len(versions) == 1
    v = versions[0]
    assert "version" in v
    assert "filename" in v
    assert "size_bytes" in v
    assert "features_count" in v
    assert v["version"] == "v1"
    assert v["filename"] == "v1.geojson"
    assert v["features_count"] == 2


def test_find_next_version_number(temp_history_dir):
    """Test finding the next version number."""
    assert find_next_version_number(temp_history_dir) == 1

    geojson = create_sample_geojson()
    save_version(geojson, temp_history_dir)
    assert find_next_version_number(temp_history_dir) == 2

    save_version(geojson, temp_history_dir, check_duplicates=False)
    assert find_next_version_number(temp_history_dir) == 3


def test_invalid_geojson_validation(temp_history_dir):
    """Test that invalid GeoJSON is rejected."""
    # Missing 'features'
    with pytest.raises(ValueError):
        save_version(
            {"type": "FeatureCollection", "features": []}, temp_history_dir
        )

    # Wrong type
    with pytest.raises(ValueError):
        save_version({"type": "Feature"}, temp_history_dir)


def test_find_duplicate_version(temp_history_dir):
    """Test the find_duplicate_version function directly."""
    geojson = create_sample_geojson(2)
    save_version(geojson, temp_history_dir)

    # Same GeoJSON should be found as duplicate
    duplicate = find_duplicate_version(geojson, temp_history_dir)
    assert duplicate == "v1"

    # Different GeoJSON should not be found
    different_geojson = create_sample_geojson(1)
    duplicate = find_duplicate_version(different_geojson, temp_history_dir)
    assert duplicate is None


def test_feature_order_independence(temp_history_dir):
    """Test that feature order doesn't affect deduplication."""
    geojson1 = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
                "properties": {"name": "zone_a"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]],
                },
                "properties": {"name": "zone_b"},
            },
        ],
    }

    # Same features but different order
    geojson2 = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]],
                },
                "properties": {"name": "zone_b"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
                "properties": {"name": "zone_a"},
            },
        ],
    }

    v1, is_new1 = save_version(geojson1, temp_history_dir)
    v2, is_new2 = save_version(geojson2, temp_history_dir, check_duplicates=True)

    # Should detect as duplicate despite different feature order
    assert v1 == "v1"
    assert v2 == "v1"
    assert is_new1 is True
    assert is_new2 is False
