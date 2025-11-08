# cutter.py
import json
from pathlib import Path
from typing import List
import osmium as osm
from shapely.geometry import shape
from shapely.strtree import STRtree
from shapely import wkb as shapely_wkb

INSIDE_FACTOR = 0.02
TOUCH_FACTOR = 0.10


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

    def node(self, n):
        self.w.add_node(n)

    def relation(self, r):
        self.w.add_relation(r)

    def way(self, w):
        kv = dict(w.tags)
        if "highway" not in kv and kv.get("route") != "ferry":
            self.w.add_way(w)
            return
        try:
            wkb = self.wkbf.create_linestring(w)
        except osm.geom.GeometryError:
            self.w.add_way(w)
            return

        line = shapely_wkb.loads(wkb, hex=False)
        candidates = self.tree.query(line)
        if not candidates:
            self.w.add_way(w)
            return

        factor = None
        for p in candidates:
            if p.covers(line):
                factor = INSIDE_FACTOR
                break
            if p.intersects(line):
                factor = min(factor or 1.0, TOUCH_FACTOR)

        if factor is None or factor >= 1.0:
            self.w.add_way(w)
            return

        mw = osm.osm.mutable.Way(w)
        tags = {t.k: t.v for t in w.tags}
        tags["avoid_zone"] = "yes"
        tags["avoid_factor"] = f"{max(0.01, min(factor, 0.99)):.4f}"
        mw.tags = [osm.osm.Tag(k, v) for k, v in tags.items()]
        self.w.add_way(mw)


def apply_penalties(
    in_pbf: Path, polygons_geojson: Path, out_pbf: Path, location_store: str = "mmap"
):
    polys, tree = _load_polys(polygons_geojson)
    reader = osm.io.Reader(str(in_pbf))
    writer = osm.io.Writer(str(out_pbf))
    if location_store == "mmap":
        lhandler = osm.NodeLocationsForWays(
            osm.index.Map("dense_mmap_array"), ignore_errors=True
        )
    else:
        lhandler = osm.NodeLocationsForWays(
            osm.index.Map("flex_mem"), ignore_errors=True
        )
    penalizer = Penalizer(writer, polys, tree)
    osm.apply(reader, lhandler, penalizer)
    writer.close()
    reader.close()
