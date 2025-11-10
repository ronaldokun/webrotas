"""
Convert GeoJSON avoid zones to Lua data format for profile loading.

This allows the Lua profile to access polygon data at startup without
reprocessing the PBF file.
"""

import json
from pathlib import Path
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


def geojson_to_lua_data(geojson_path: Path) -> str:
    """
    Convert GeoJSON FeatureCollection to Lua data structure.

    Returns a Lua chunk that defines a table of polygons with their coordinates.

    Args:
        geojson_path: Path to GeoJSON file with polygon features

    Returns:
        Lua code string defining the avoid_zones_data table
    """
    try:
        gj = json.loads(geojson_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to read GeoJSON: {e}")
        return "return {}"

    features = gj.get("features", []) if gj.get("type") == "FeatureCollection" else [gj]

    polygons = []
    for feature in features:
        geom = feature.get("geometry")
        if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue

        if geom["type"] == "Polygon":
            # Extract exterior ring only (first coordinate array)
            coords = geom.get("coordinates", [])[0]
            if len(coords) >= 3:
                polygons.append(coords)
        elif geom["type"] == "MultiPolygon":
            # Extract exterior rings from all polygons
            for polygon_coords in geom.get("coordinates", []):
                coords = polygon_coords[0]  # exterior ring
                if len(coords) >= 3:
                    polygons.append(coords)

    if not polygons:
        logger.warning("No valid polygons found in GeoJSON")
        return "return {}"

    # Generate Lua table
    lua_code = "-- Auto-generated avoid zones data\n"
    lua_code += "return {\n"

    for i, polygon in enumerate(polygons):
        lua_code += f"  {{\n"
        lua_code += f"    coords = {{\n"
        for lon, lat in polygon:
            lua_code += f"      {{{lon}, {lat}}},\n"
        lua_code += f"    }},\n"
        lua_code += f"    is_inside = true,\n"
        lua_code += f"    is_touching = true,\n"
        lua_code += f"  }},\n"

    lua_code += "}\n"

    return lua_code


def write_lua_zones_file(geojson_path: Path, lua_output_path: Path) -> bool:
    """
    Convert GeoJSON to Lua file.

    Args:
        geojson_path: Path to GeoJSON file
        lua_output_path: Path where to write the Lua data file

    Returns:
        True if successful, False otherwise
    """
    try:
        lua_code = geojson_to_lua_data(geojson_path)
        lua_output_path.parent.mkdir(parents=True, exist_ok=True)
        lua_output_path.write_text(lua_code, encoding="utf-8")
        logger.info(f"Wrote Lua zones file to {lua_output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to write Lua zones file: {e}")
        return False
