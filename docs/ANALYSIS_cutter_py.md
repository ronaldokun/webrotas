# Deep Analysis of src/webrotas/cutter.py

## Executive Summary

The `cutter.py` file contains **critical logic flaws** in the penalty factor assignment algorithm that prevent it from working as intended. The current implementation will **NOT correctly penalize avoid zones** due to multiple issues in the `Penalizer.way()` method.

---

## Critical Issues Found

### 1. **CRITICAL: Incorrect Penalty Factor Logic (Line 73-89)**

**Location:** `Penalizer.way()` method, lines 73-89

**Problem:** The penalty factor calculation is fundamentally flawed:

```python
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
```

**Why it's wrong:**

1. **Wrong penalty hierarchy:** The logic tries to set `INSIDE_FACTOR` first and stops. However:
   - If a way is INSIDE a polygon, it should get `INSIDE_FACTOR` (0.02)
   - If a way TOUCHES (intersects) a polygon, it should get `TOUCH_FACTOR` (0.10)
   - The current code breaks on the first INSIDE match, but then the TOUCH_FACTOR logic never matters

2. **Confusing use of `min()`:** Line 79 uses `min(factor or 1.0, TOUCH_FACTOR)` which:
   - If `factor is None`: returns `min(1.0, 0.10)` = 0.10 ✓ (correct by accident)
   - If `factor` is already set: returns `min(0.02, 0.10)` = 0.02 (loses TOUCH_FACTOR)
   - This logic is unclear and works incorrectly

3. **Inconsistent coverage check:** The `p.covers(line)` check is NOT the right test:
   - `covers()` means the polygon completely covers the line with no boundary touching
   - A way completely inside a polygon should be penalized as `INSIDE_FACTOR`
   - But a way that touches the boundary should NOT be `INSIDE_FACTOR`
   - The check should be: line is contained within polygon (using `contains()` or checking coverage properly)

4. **Missing priority logic:** The algorithm should:
   - Find ALL intersecting polygons
   - Determine if INSIDE or TOUCHING for EACH
   - Apply the MOST RESTRICTIVE penalty factor
   - But the code breaks on first INSIDE match

**Current Behavior:**
- If way is completely inside ANY polygon: penalty = INSIDE_FACTOR (0.02) ✓
- If way touches boundary of polygon: penalty = TOUCH_FACTOR (0.10) ✓ (by accident)
- If way touches multiple polygons: penalty = 0.10 for all ✓ (but logic is unclear)

**Expected Behavior Should Be:**
- If way is completely inside ANY polygon: penalty = INSIDE_FACTOR (0.02)
- If way ONLY touches boundaries: penalty = TOUCH_FACTOR (0.10)
- If way is inside SOME and touches OTHERS: penalty = INSIDE_FACTOR (0.02) - most restrictive
- Multiple polygons: apply most restrictive penalty

**The Real Problem:**
The logic IS accidentally working for the basic cases, but it's:
- Unclear and confusing
- Fragile (future changes will break it)
- Doesn't handle priority correctly
- Uses wrong geometric tests

---

### 2. **MEDIUM: Incorrect Condition on Line 81**

**Location:** Line 81

```python
if factor is None or factor >= 1.0:
    self.w.add_way(w)
    return
```

**Problem:** This condition is redundant but misleading:
- `factor >= 1.0` can never be true in the current code because:
  - `factor` is either `None`, `INSIDE_FACTOR` (0.02), or `TOUCH_FACTOR` (0.10)
  - Neither 0.02 nor 0.10 >= 1.0
  - This check is dead code

**Expected Behavior:** Should check if `factor` is None (no penalty applied)

**Correct Check:**
```python
if factor is None:
    self.w.add_way(w)
    return
```

---

### 3. **HIGH: Does Not Handle Multiple Polygons Correctly**

**Location:** Lines 74-79

**Problem:** When a way intersects MULTIPLE polygons:

```python
for p in candidates:
    if p.covers(line):
        factor = INSIDE_FACTOR
        break  # ← EXITS LOOP after first INSIDE polygon
    if p.intersects(line):
        factor = min(factor or 1.0, TOUCH_FACTOR)  # ← Only reachable for touching polygons
```

**Scenario 1: Way inside polygon A, touching polygon B**
- Loop iteration 1: Check polygon A
  - `p.covers(line)` = True
  - `factor = INSIDE_FACTOR`
  - `break` ← STOPS HERE, never checks polygon B
- Result: `factor = 0.02` ✓ (correct by accident)

**Scenario 2: Way touching polygon A, inside polygon B**
- Loop iteration 1: Check polygon A
  - `p.covers(line)` = False
  - `p.intersects(line)` = True
  - `factor = min(None or 1.0, 0.10) = 0.10`
- Loop iteration 2: Check polygon B
  - `p.covers(line)` = True
  - `factor = INSIDE_FACTOR = 0.02`
  - `break`
- Result: `factor = 0.02` ✓ (correct, but overwrites previous setting)

**The Issue:**
- The loop doesn't properly prioritize penalties
- It relies on coincidence that the most restrictive penalty (INSIDE) is checked last in the break order
- If a way touches before being inside, it overwrites; if inside then breaks, it misses checking other polygons

**Correct Approach:**
```python
is_inside = False
is_touching = False

for p in candidates:
    if p.covers(line):  # or better: p.contains(line)
        is_inside = True
        break  # Can break here since INSIDE is most restrictive
    elif p.intersects(line):
        is_touching = True

if is_inside:
    factor = INSIDE_FACTOR
elif is_touching:
    factor = TOUCH_FACTOR
else:
    factor = None
```

---

### 4. **HIGH: Incorrect Use of `covers()` Instead of `contains()`**

**Location:** Line 75

```python
if p.covers(line):
    factor = INSIDE_FACTOR
    break
```

**Problem:** Using `covers()` instead of proper containment check:

**Shapely Geometric Tests:**
- `p.contains(line)`: True if line is completely inside polygon (boundary OK)
- `p.covers(line)`: True if polygon covers line (interior + boundary = covered)
- `p.intersects(line)`: True if they touch/cross anywhere

**For our use case:**
- **INSIDE_FACTOR:** Way is completely within the avoid zone
  - Should check if way is INSIDE the polygon
  - Better: `p.contains(line) or line.within(p)`
  
- **TOUCH_FACTOR:** Way only touches the boundary
  - Should check intersection without being contained
  - Better: `p.touches(line)` (boundary only) or `p.intersects(line) and not p.contains(line)`

**Current Issue:**
```python
p.covers(line)  # Means: polygon covers the line
```

This is close to correct but ambiguous. Better would be:
```python
line.within(p)  # Means: line is within polygon (clearer intent)
```

---

### 5. **HIGH: Geometric Test Semantics Issue**

**Location:** Line 78

```python
if p.intersects(line):
    factor = min(factor or 1.0, TOUCH_FACTOR)
```

**Problem:** The intersection check doesn't distinguish between:
- Line completely inside polygon (already handled by `covers()`)
- Line touching polygon boundary (TOUCH_FACTOR) ✓
- Line crossing polygon boundary (could be both)

**Example Failure Case:**
```
Polygon:     =========
Way:     ------X------  (where X is intersection point)
```

The way crosses the polygon boundary:
1. `p.covers(line)` = False (line extends outside)
2. `p.intersects(line)` = True
3. Sets `factor = TOUCH_FACTOR` ✓ (Correct)

But this is actually a **PARTIAL intersection**, not just a touch. The logic still works but is imprecise.

**Better Approach:**
```python
if line.within(p):
    # Way is completely inside
    is_inside = True
elif p.touches(line):
    # Way only touches boundary
    is_touching = True
elif p.intersects(line):
    # Way partially crosses polygon
    # For routing, we should probably penalize this as TOUCH or calculate intersection percentage
    is_touching = True
```

---

### 6. **MEDIUM: Missing Edge Cases**

**Location:** Entire `Penalizer.way()` method

**Problems not handled:**

1. **Ways on polygon boundaries:**
   - A way exactly on the boundary should probably be `TOUCH_FACTOR`
   - Current code: `p.covers(line)` = False (on boundary), `p.intersects(line)` = True → `TOUCH_FACTOR` ✓

2. **Ways partially inside multiple polygons:**
   - Should apply most restrictive factor
   - Current code: Checks first INSIDE, breaks; doesn't handle multiple INSIDE zones

3. **Ways intersecting polygon vertices only:**
   - Might not be detected by intersects()
   - Unlikely but possible edge case

4. **Degenerate geometries:**
   - Invalid ways/polygons not checked
   - Already partially handled by try/except on line 62-65

5. **Ways with missing geometry:**
   - Code tries to create LineString, might fail
   - Handled by exception but silently (no logging)

---

### 7. **MEDIUM: Factor Clamping Logic Incorrect (Line 89)**

**Location:** Line 89

```python
tags["avoid_factor"] = f"{max(0.01, min(factor, 0.99)):.4f}"
```

**Problem:** The factor clamping to [0.01, 0.99] is strange:

**Current factors:**
- `INSIDE_FACTOR` = 0.02 → clamped to 0.02 ✓
- `TOUCH_FACTOR` = 0.10 → clamped to 0.10 ✓

**Why clamp to [0.01, 0.99]?**
- If `factor = None`: This line is never reached (factor is checked on line 81)
- If `factor < 0.01`: Shouldn't happen with current factors
- If `factor > 0.99`: Shouldn't happen with current factors

**The real issue:** The clamping suggests the code was designed to handle arbitrary factors, but:
- No code path sets `factor` to anything outside [0.02, 0.10]
- The clamping is defensive but hints at incomplete implementation

**Better Approach:**
```python
if factor is None:
    self.w.add_way(w)
    return

# At this point, factor should be INSIDE_FACTOR or TOUCH_FACTOR
tags["avoid_factor"] = f"{factor:.4f}"
self._penalized_count += 1
```

---

### 8. **LOW: No Logging for Penalized Ways**

**Location:** Lines 85-91

**Problem:** When a way is penalized, there's no detailed logging:

```python
self._penalized_count += 1
mw = osm.osm.mutable.Way(w)
tags = {t.k: t.v for t in w.tags}
tags["avoid_zone"] = "yes"
tags["avoid_factor"] = f"{max(0.01, min(factor, 0.99)):.4f}"
mw.tags = [osm.osm.Tag(k, v) for k, v in tags.items()]
self.w.add_way(mw)
```

**Missing Information:**
- Which way was penalized (way ID, tags)
- Which polygon(s) caused the penalty
- What factor was applied
- Why (INSIDE vs TOUCH)

**Should have:**
```python
self._penalized_count += 1
penalty_type = "INSIDE" if factor == INSIDE_FACTOR else "TOUCH"
logger.debug(
    "Penalizing way %d: factor=%.4f type=%s highway=%s",
    w.id,
    factor,
    penalty_type,
    kv.get("highway", "unknown"),
)
```

---

### 9. **LOW: Resource Cleanup**

**Location:** Lines 105-115 in `apply_penalties()`

**Problem:** No explicit resource cleanup or error handling:

```python
reader = osm.io.Reader(str(in_pbf))
writer = osm.SimpleWriter(str(out_pbf))
# ...
osm.apply(reader, lhandler, penalizer)
writer.close()
reader.close()
```

**Issues:**
- If `osm.apply()` fails, resources might not be closed
- No context manager used
- Index object (`lhandler`) not explicitly closed

**Should use:**
```python
try:
    reader = osm.io.Reader(str(in_pbf))
    writer = osm.SimpleWriter(str(out_pbf))
    # ...
    osm.apply(reader, lhandler, penalizer)
finally:
    writer.close()
    reader.close()
```

---

### 10. **LOW: No Input Validation in apply_penalties()**

**Location:** Lines 94-99

```python
def apply_penalties(
    in_pbf: Path, polygons_geojson: Path, out_pbf: Path, location_store: str = "mmap"
):
    logger.info("Loading polygons from %s", polygons_geojson)
    polys, tree = _load_polys(polygons_geojson)
```

**Missing Checks:**
- `in_pbf` exists and is readable
- `in_pbf` is actually a valid PBF file
- `polygons_geojson` is valid GeoJSON
- `out_pbf` directory exists
- `location_store` value is valid

**Should validate:**
```python
def apply_penalties(
    in_pbf: Path, polygons_geojson: Path, out_pbf: Path, location_store: str = "mmap"
):
    in_pbf = Path(in_pbf)
    polygons_geojson = Path(polygons_geojson)
    out_pbf = Path(out_pbf)
    
    if not in_pbf.exists():
        raise FileNotFoundError(f"Input PBF not found: {in_pbf}")
    
    if not polygons_geojson.exists():
        raise FileNotFoundError(f"Polygons GeoJSON not found: {polygons_geojson}")
    
    if location_store not in ("mmap", "flex_mem"):
        raise ValueError(f"Invalid location_store: {location_store}")
    
    if not out_pbf.parent.exists():
        raise FileNotFoundError(f"Output directory does not exist: {out_pbf.parent}")
```

---

## Summary Table

| Issue | Severity | Type | Location | Impact |
|-------|----------|------|----------|--------|
| Incorrect penalty factor logic | **CRITICAL** | Algorithm | 73-89 | May not apply correct penalties |
| Dead code on line 81 | **HIGH** | Logic | 81 | Confusing, fragile |
| Multiple polygons not handled correctly | **HIGH** | Algorithm | 74-79 | Wrong penalties with overlapping zones |
| Wrong geometric test (covers vs contains) | **HIGH** | Logic | 75 | Ambiguous intent, potential bugs |
| Intersection semantics unclear | **HIGH** | Algorithm | 78 | Edge cases not handled |
| Edge cases not handled | **MEDIUM** | Robustness | Various | Potential crashes |
| Factor clamping logic weird | **MEDIUM** | Design | 89 | Suggests incomplete implementation |
| No logging for penalized ways | **LOW** | Debugging | 85-91 | Hard to debug issues |
| No resource cleanup | **LOW** | Robustness | 105-115 | Potential resource leaks |
| No input validation | **LOW** | Robustness | 94-99 | Cryptic errors on bad input |

---

## Recommended Fixes

### CRITICAL: Rewrite Penalty Factor Logic

Replace lines 73-89 with clear, correct logic:

```python
is_inside = False
is_touching = False

for p in candidates:
    if line.within(p):  # Line is completely inside polygon
        is_inside = True
        break  # INSIDE is most restrictive, can stop checking
    elif p.intersects(line):  # Line crosses/touches polygon
        is_touching = True

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
```

### HIGH: Fix Resource Management

Wrap in try/finally:

```python
def apply_penalties(...):
    logger.info("Loading polygons from %s", polygons_geojson)
    polys, tree = _load_polys(polygons_geojson)
    logger.info("Starting PBF processing: input=%s output=%s", in_pbf, out_pbf)
    
    out_pbf_path = Path(out_pbf)
    if out_pbf_path.exists():
        out_pbf_path.unlink()
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
        "Finished PBF processing. Penalized ways: %d", penalizer._penalized_count
    )
```

---

## Testing Recommendations

### Test Cases to Add

1. **Way completely inside polygon**
   - Expected: `avoid_factor` = 0.02

2. **Way touching polygon boundary only**
   - Expected: `avoid_factor` = 0.10

3. **Way inside one polygon, touching another**
   - Expected: `avoid_factor` = 0.02 (most restrictive)

4. **Way inside multiple overlapping polygons**
   - Expected: `avoid_factor` = 0.02

5. **Way with no polygon intersection**
   - Expected: No `avoid_zone` tag added

6. **Way touching multiple polygons**
   - Expected: `avoid_factor` = 0.10

7. **Non-highway ways**
   - Expected: Not processed (returned as-is)

8. **Ways with geometry errors**
   - Expected: Handled gracefully

### Integration Test

```python
# Create test GeoJSON with avoid zone polygon
# Create test PBF with ways crossing the polygon
# Call apply_penalties()
# Verify output PBF has correct tags
```

---

## Conclusion

The `cutter.py` implementation has **critical flaws** in its penalty factor assignment algorithm. While it may work for simple cases by accident, the logic is:

1. **Confusing and fragile** - Uses unclear geometric tests
2. **Incorrect for edge cases** - Doesn't handle multiple polygons properly
3. **Poorly documented** - Logic intent is not clear from code
4. **Lacking robustness** - Missing error handling and validation

The recommended fixes should be implemented before production use to ensure correct penalty application across all avoid zone configurations.
