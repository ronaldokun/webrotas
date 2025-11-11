#!/usr/bin/env python3
"""Quick validation script for Phase 1 implementation."""

import os
os.environ["OSRM_DATA"] = "/tmp/test_webrotas"

from pathlib import Path
from shapely.geometry import Polygon
from shapely.strtree import STRtree

from src.webrotas.app import (
    check_route_intersections,
    load_spatial_index,
)


def test_check_route_intersections():
    """Test route intersection calculation."""
    print("\
=" * 50)
    print("TEST: check_route_intersections")
    print("=" * 50)

    # Test 1: Route fully in zone
    print("\
1. Route fully within zone...")
    zone = Polygon([(-46.7, -23.55), (-46.6, -23.55), (-46.6, -23.5), (-46.7, -23.5)])
    route_coords = [(-46.65, -23.525), (-46.64, -23.525)]
    tree = STRtree([zone])
    result = check_route_intersections(route_coords, [zone], tree)
    print(f"   Intersection count: {result['intersection_count']}")
    print(f"   Penalty ratio: {result['penalty_ratio']:.3f}")
    print(f"   Zone length: {result['total_length_km']:.3f} km")
    print(f"   Route length: {result['route_length_km']:.3f} km")
    assert result["intersection_count"] == 1, "Should intersect zone"
    assert result["penalty_ratio"] > 0.9, "Penalty should be high"
    print("   ✓ PASS")

    # Test 2: Route avoiding zone
    print("\
2. Route avoiding zone...")
    route_coords = [(-46.5, -23.525), (-46.4, -23.525)]
    result = check_route_intersections(route_coords, [zone], tree)
    print(f"   Intersection count: {result['intersection_count']}")
    print(f"   Penalty ratio: {result['penalty_ratio']}")
    assert result["intersection_count"] == 0, "Should not intersect zone"
    assert result["penalty_ratio"] == 0.0, "Penalty should be zero"
    print("   ✓ PASS")

    # Test 3: Empty zone list
    print("\
3. Empty zone list...")
    result = check_route_intersections(route_coords, [], None)
    print(f"   Intersection count: {result['intersection_count']}")
    print(f"   Penalty ratio: {result['penalty_ratio']}")
    assert result["intersection_count"] == 0, "Should be zero"
    assert result["penalty_ratio"] == 0.0, "Penalty should be zero"
    print("   ✓ PASS")

    print("\
✓ All check_route_intersections tests passed!")


def test_load_spatial_index():
    """Test spatial index building."""
    print("\
" + "=" * 50)
    print("TEST: load_spatial_index")
    print("=" * 50)

    # Test 1: Valid FeatureCollection
    print("\
1. Valid FeatureCollection with Polygon...")
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[-46.7, -23.55], [-46.6, -23.55], [-46.6, -23.5], [-46.7, -23.5], [-46.7, -23.55]]
                    ],
                },
            }
        ],
    }
    polys, tree = load_spatial_index(geojson)
    print(f"   Polygons loaded: {len(polys)}")
    print(f"   Spatial index created: {tree is not None}")
    assert len(polys) == 1, "Should load 1 polygon"
    assert tree is not None, "Spatial index should be created"
    print("   ✓ PASS")

    # Test 2: MultiPolygon
    print("\
2. MultiPolygon feature...")
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[-46.7, -23.55], [-46.65, -23.55], [-46.65, -23.5], [-46.7, -23.5], [-46.7, -23.55]]],
                        [[[-46.63, -23.55], [-46.6, -23.55], [-46.6, -23.5], [-46.63, -23.5], [-46.63, -23.55]]],
                    ],
                },
            }
        ],
    }
    polys, tree = load_spatial_index(geojson)
    print(f"   Polygons loaded: {len(polys)}")
    assert len(polys) == 2, "Should load 2 polygons from MultiPolygon"
    assert tree is not None, "Spatial index should be created"
    print("   ✓ PASS")

    # Test 3: No valid polygons
    print("\
3. No valid polygons (only Point)...")
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-46.7, -23.55]},
            }
        ],
    }
    polys, tree = load_spatial_index(geojson)
    print(f"   Polygons loaded: {len(polys)}")
    print(f"   Spatial index: {tree}")
    assert len(polys) == 0, "Should load no polygons"
    assert tree is None, "Spatial index should be None"
    print("   ✓ PASS")

    print("\
✓ All load_spatial_index tests passed!")


def test_integration():
    """Integration test."""
    print("\
" + "=" * 50)
    print("INTEGRATION TEST")
    print("=" * 50)

    print("\
Testing realistic scenario...")
    # Create two adjacent zones
    zone1 = Polygon([(-46.7, -23.55), (-46.65, -23.55), (-46.65, -23.5), (-46.7, -23.5)])
    zone2 = Polygon([(-46.65, -23.55), (-46.6, -23.55), (-46.6, -23.5), (-46.65, -23.5)])

    # Route crossing both zones
    route_coords = [
        (-46.71, -23.525),  # Outside zone1
        (-46.675, -23.525), # Inside zone1
        (-46.625, -23.525), # Between zones
        (-46.59, -23.525),  # Outside zone2
    ]

    tree = STRtree([zone1, zone2])
    result = check_route_intersections(route_coords, [zone1, zone2], tree)

    print(f"   Zones intersected: {result['intersection_count']}")
    print(f"   Total distance in zones: {result['total_length_km']:.3f} km")
    print(f"   Total route distance: {result['route_length_km']:.3f} km")
    print(f"   Penalty score: {result['penalty_ratio']:.1%}")

    assert result["intersection_count"] >= 1, "Should intersect at least one zone"
    assert result["penalty_ratio"] > 0, "Should have penalty"
    print("\
✓ Integration test passed!")


if __name__ == "__main__":
    print("\
" + "*" * 50)
    print("PHASE 1 VALIDATION - Client-Side Zone Processing")
    print("*" * 50)

    try:
        test_check_route_intersections()
        test_load_spatial_index()
        test_integration()

        print("\
" + "*" * 50)
        print("✓ ALL VALIDATION TESTS PASSED!")
        print("*" * 50)
        print("\
Phase 1 Implementation Status:")
        print("  ✓ Imports working correctly")
        print("  ✓ Route intersection calculation working")
        print("  ✓ Spatial index building working")
        print("  ✓ Integration tests passing")
        print("\
Ready for integration testing with OSRM!\
")

    except AssertionError as e:
        print(f"\
✗ VALIDATION FAILED: {e}")
        exit(1)
    except Exception as e:
        print(f"\
✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
"