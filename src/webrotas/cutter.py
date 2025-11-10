# cutter.py
import json
import os
from pathlib import Path
from typing import List
import osmium as osm
from shapely.geometry import shape
from shapely.strtree import STRtree
from shapely import wkb as shapely_wkb
import logging

# Configurable penalty factors (can be overridden via environment variables)
INSIDE_FACTOR = float(os.getenv("AVOIDZONE_INSIDE_FACTOR", "0.02"))
TOUCH_FACTOR = float(os.getenv("AVOIDZONE_TOUCH_FACTOR", "0.10"))

logger = logging.getLogger(__name__)


def _load_polys(geojson_path: Path):
    gj = json.loads(geojson_path.read_text(encoding="utf-8"))
    feats = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
    polys = [
        shape(f["geometry"])
        for f in feats
        if f.get("geometry") and f["geometry"]["type"] in ("Polygon", "MultiPolygon")
    ]
    if not polys:
        raise ValueError("No (Multi)Polygon features in avoidzones GeoJSON.")
    return polys, STRtree(polys)


class Penalizer(osm.SimpleHandler):
    def __init__(self, writer, polys: List, tree: STRtree):
        super().__init__()
        self.w = writer
        self.polys = polys
        self.tree = tree
        self.wkbf = osm.geom.WKBFactory()
        self._way_count = 0
        self._penalized_count = 0

    def node(self, n):
        self.w.add_node(n)

    def relation(self, r):
        self.w.add_relation(r)

    def way(self, w):
        self._way_count += 1
        if self._way_count % 500000 == 0:
            logger.info(
                "Processed %d ways (penalized=%d)",
                self._way_count,
                self._penalized_count,
            )

        kv = dict(w.tags)
        if "highway" not in kv and kv.get("route") != "ferry":
            self.w.add_way(w)
            return
        try:
            wkb = self.wkbf.create_linestring(w)
        except Exception as e:
            logger.debug("Failed to create linestring for way %d: %s", w.id, str(e))
            self.w.add_way(w)
            return

        line = shapely_wkb.loads(wkb, hex=False)
        candidate_indices = self.tree.query(line)
        if len(candidate_indices) == 0:
            self.w.add_way(w)
            return

        # Determine penalty: check if way is inside or touching avoid zones
        # INSIDE_FACTOR (0.02) is most restrictive, applied when way is completely within polygon
        # TOUCH_FACTOR (0.10) is applied when way only touches/crosses polygon boundary
        is_inside = False
        is_touching = False
        penalty_reason = None

        for idx in candidate_indices:
            p = self.polys[idx]
            if line.within(p):
                # Way is completely inside polygon - most restrictive penalty
                is_inside = True
                break  # Can stop checking since INSIDE is most restrictive
            elif p.intersects(line):
                # Way touches or crosses polygon boundary
                is_touching = True
                # Continue checking other polygons to see if any fully contain the way

        # Apply most restrictive penalty
        if is_inside:
            factor = INSIDE_FACTOR
            penalty_reason = "INSIDE"
        elif is_touching:
            factor = TOUCH_FACTOR
            penalty_reason = "TOUCHING"
        else:
            factor = None
            penalty_reason = None

        # No penalty if way doesn't intersect avoid zones
        if factor is None:
            self.w.add_way(w)
            return

        self._penalized_count += 1
        logger.debug(
            "Penalizing way %d: factor=%.4f reason=%s highway=%s",
            w.id,
            factor,
            penalty_reason,
            kv.get("highway", "unknown"),
        )

        mw = osm.osm.mutable.Way(w)
        tags = {t.k: t.v for t in w.tags}
        tags["avoid_zone"] = "yes"
        tags["avoid_factor"] = f"{factor:.4f}"
        mw.tags = [osm.osm.Tag(k, v) for k, v in tags.items()]
        self.w.add_way(mw)


def apply_penalties(
    in_pbf: Path, polygons_geojson: Path, out_pbf: Path, location_store: str = "mmap"
):
    """Apply avoid zone penalties to OSM PBF file.
    
    Args:
        in_pbf: Input OSM PBF file path
        polygons_geojson: GeoJSON file with polygon avoid zones
        out_pbf: Output PBF file path with penalties applied
        location_store: Storage backend for node locations ('mmap' or 'flex_mem')
    
    Raises:
        FileNotFoundError: If input files don't exist or output directory doesn't exist
        ValueError: If invalid location_store value or invalid GeoJSON
    """
    # Input validation
    in_pbf = Path(in_pbf)
    polygons_geojson = Path(polygons_geojson)
    out_pbf = Path(out_pbf)
    
    if not in_pbf.exists():
        raise FileNotFoundError(f"Input PBF file not found: {in_pbf}")
    if not polygons_geojson.exists():
        raise FileNotFoundError(f"Polygons GeoJSON file not found: {polygons_geojson}")
    if location_store not in ("mmap", "flex_mem"):
        raise ValueError(f"Invalid location_store: {location_store}. Must be 'mmap' or 'flex_mem'")
    if not out_pbf.parent.exists():
        raise FileNotFoundError(f"Output directory does not exist: {out_pbf.parent}")
    
    logger.info("Loading polygons from %s", polygons_geojson)
    polys, tree = _load_polys(polygons_geojson)
    logger.info("Loaded %d avoid zone polygons", len(polys))
    logger.info("Starting PBF processing: input=%s output=%s location_store=%s", in_pbf, out_pbf, location_store)
    
    # Remove existing output file if it exists (osmium.io.Writer won't overwrite)
    if out_pbf.exists():
        out_pbf.unlink()
        logger.info("Removed existing output file: %s", out_pbf)
    
    reader = osm.io.Reader(str(in_pbf))
    writer = osm.SimpleWriter(str(out_pbf))
    
    try:
        if location_store == "mmap":
            index = osm.index.create_map("dense_mmap_array")
        else:
            index = osm.index.create_map("flex_mem")
        
        lhandler = osm.NodeLocationsForWays(index)
        penalizer = Penalizer(writer, polys, tree)
        osm.apply(reader, lhandler, penalizer)
    finally:
        writer.close()
        reader.close()
    
    logger.info(
        "Finished PBF processing. Total ways: %d, Penalized ways: %d", 
        penalizer._way_count,
        penalizer._penalized_count
    )
