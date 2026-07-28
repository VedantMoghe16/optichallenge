"""OGC 2026 submission -- Kestrel spatio-temporal packing heuristic.

The solver deliberately maintains a strong safety invariant: for any two
blocks whose residence intervals overlap, the unions of all their layer
polygons have disjoint interiors.  This is stronger than the competition's
same-layer collision rule, but it has a valuable consequence: every ENTRY and
EXIT crane operation is feasible in any same-day order.  It removes the costly
post-hoc crane repair used by the baseline while still exploiting true
irregular polygons (rather than bounding rectangles).

The algorithm is anytime:
  1. build and retain an immediately feasible, fit-aware serial fallback;
  2. construct schedules with several urgency/space priority rules;
  3. improve the best schedule with exact-delta single-block and ruin/recreate
     moves until the wall-clock guard fires;
  4. return only a solution accepted by the official ``utils`` checker.

Only packages listed in the official OGC environment are used.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Optional

from shapely.affinity import translate as _translate
from shapely.geometry import Polygon
from shapely.ops import unary_union


# ---------------------------------------------------------------------------
# Dev switches.  These are plain module constants on purpose: the submitted
# build must behave identically no matter what the evaluation environment has
# in os.environ, so nothing here reads the environment.  To experiment, edit
# the single line (False -> True) and re-run the gate.
# ---------------------------------------------------------------------------
# Layer-true feasibility mode (exact per-layer + crane j>=k semantics instead
# of the conservative union-footprint invariant).  Default OFF: with the flag
# off this module behaves exactly like the proven v2.1 build.
LAYER_TRUE = False
# Cross-bay rebalancing destroy operators (workers 1-3 only; worker 0 keeps
# the legacy v1 schedule regardless).  Default OFF: the 2026-07-27 gate found
# a reproducible +18.8% regression on prob_11 from the cadence shift
# (RESULTS.md).
XBAY = False
# Advanced large-neighborhood search.  Keep OFF until its paired gate passes.
# When enabled, workers 0, 2, and 3 retain their previous diversified paths;
# worker 1 alone exercises blame/regret + late acceptance.  This preserves
# three quarters of the measured legacy portfolio instead of merely one
# feasibility anchor.  The experiment harness explicitly enables this switch.
ADVANCED_LNS = False
# Optional CP-SAT time-window repair added to legacy worker 2.  This remains OFF
# until the LNS gate is complete and is also conditional on OR-Tools being
# available in the evaluation environment.
CP_SAT_REPAIR = False
ADVANCED_LNS_MIN_LIMIT = 90.0
ADVANCED_LNS_MIN_BLOCKS = 100
# Selective batch-raster acceleration for exact construction.  The flag merely
# permits runtime selection: n<=160 and budget-insufficient runs remain on the
# hardened baseline paths.
SELECTIVE_RASTER = False
RASTER_S = 4
RASTER_PASS_SECONDS = 83.0
RASTER_REFERENCE_N = 250.0
RASTER_REFERENCE_BAY_CELLS = 3270.0
RASTER_BUDGET_SAFETY = 1.60
RASTER_MIN_REMAINING_SECONDS = 180.0
RASTER_FORCED_DENSITY_LIMIT = 1.18
RASTER_PREFERENCE_RATIO_LIMIT = 3.00
RASTER_LARGE_Z2_RATIO_LIMIT = 5.00
RASTER_SCAN_ON_MISS = False
RASTER_FIRST_PASS_FRACTION = 0.50
# Keep raster additive inside the four-worker portfolio.  Earlier integration
# enabled it in every worker and replaced every legacy large-n path; fresh
# 240-second pairs then regressed prob_38 by 5.23% and prob_40 by 11.27%.
# Workers 2/3 run the fast raster decoder while worker 0 preserves the legacy
# safety anchor and worker 1 supplies the independent LNS path.
RASTER_MID_VARIANTS = (2, 3)
RASTER_LARGE_VARIANTS = (2, 3)
# Loose Z2/Z3 polish is separately gateable and never runs on worker 0.
LOOSE_POLISH = False

EPS = 1e-10
# Smallest side length of the positive-area stand-in used when an orientation's
# layer polygons are all degenerate (see _proxy_orient).
DEGEN_MIN_SIDE = 1e-3
# Cell budget for the row-bitmask placement grid in _rectangle_position.  The
# supplied contract keeps bays at most 179 x 29 (~5.2e3 cells); the cap only
# guards hypothetical finals instances with huge bays, where one Python int per
# grid row would cost time and memory in every one of the four workers.
RECT_GRID_MAX_CELLS = 2_000_000
_MOVE_CACHE = {}
# Pairwise collision verdicts.  Overlap of polygon P translated to (x, y)
# with polygon Q translated to (u, v) depends only on (P, Q, x-u, y-v), so
# verdicts are cached by relative displacement.  Entries are exact shapely
# results; the cache can never change a verdict, only avoid recomputing it.
_PAIR_CACHE = {}
_PAIR_CACHE_MAX = 800_000
_ORIENT_CACHE = {}
# Layer-true verdict caches, keyed by relative displacement like _PAIR_CACHE.
# _LT_STATIC is symmetric (key normalized); _LT_CRANE is directional
# (mover, present).  Verdicts are exact shapely results.
_LT_STATIC = {}
_LT_CRANE = {}
_LT_CACHE_MAX = 700_000
_RASTER_CACHE = {}
_RASTER_ACTIVE = False


def _clear_geometry_caches():
    """Reset caches whose keys are valid only within one problem instance."""
    _MOVE_CACHE.clear()
    _PAIR_CACHE.clear()
    _ORIENT_CACHE.clear()
    _LT_STATIC.clear()
    _LT_CRANE.clear()
    _RASTER_CACHE.clear()


@dataclass(frozen=True)
class Orient:
    """Geometry of one orientation in reference-point coordinates."""

    idx: int
    poly: object
    bbox: tuple[float, float, float, float]
    area: float
    layers: tuple = ()
    layer_bboxes: tuple = ()


def _dwell(block) -> int:
    """Integer bay residence used for every derived EXIT time.

    Stage 1 of the checker only requires ``exit_time - entry_time >=
    processing_time`` (utils.py L1126-1130), so a *longer* dwell is always
    feasible.  A dwell of 0 is not: ``_emit`` would put the block's EXIT and
    ENTRY under the same time key with EXIT first (mandatory ordering), and the
    Stage-5 replay then reports "EXIT block i is not present in bay"
    (utils.py L1367).  Clamping to >= 1 keeps every emitted schedule
    replayable.  ``ceil`` additionally covers a hypothetical fractional
    processing_time, which a bare ``int()`` would truncate below the Stage-1
    bound.
    """
    p = float(block["processing_time"])
    return max(1, int(math.ceil(p - 1e-9)))


def _polygon(vertices):
    if len(vertices) < 3:
        return None
    try:
        p = Polygon(vertices)
        if not p.is_valid:
            p = p.buffer(0)
        return None if p.is_empty else p
    except Exception:
        return None


def _proxy_orient(oi, raw_layers) -> Orient:
    """Positive-area stand-in for an orientation with no usable layer polygon.

    Degenerate layers (fewer than three vertices, collinear, or zero area)
    are dropped by ``_polygon``; an orientation whose every layer is degenerate
    would otherwise vanish, and a block whose every orientation vanishes would
    abort the whole run.  The proxy is the RAW-vertex bounding box over all
    layers -- exactly the rectangle the checker itself reasons about for
    containment (``Block.bounding_rect``, utils.py L365-383) -- dilated to a
    tiny positive extent when that box is itself degenerate.  Because the
    rectangle covers the true (sub-)geometry, every placement the solver
    admits under it is still accepted by the checker, which keeps using the
    raw vertices and remains authoritative.
    """
    if raw_layers and raw_layers[0]:
        ref_x = float(raw_layers[0][0][0])
        ref_y = float(raw_layers[0][0][1])
    else:
        ref_x = ref_y = 0.0
    # Single-pass min/max: this runs on the deadline-pressed preprocessing
    # path, where allocating intermediate vertex lists is measurable.
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    for layer in raw_layers:
        for vx, vy in layer:
            vx = float(vx) - ref_x
            vy = float(vy) - ref_y
            if vx < x0:
                x0 = vx
            if vx > x1:
                x1 = vx
            if vy < y0:
                y0 = vy
            if vy > y1:
                y1 = vy
    if x0 > x1:                       # no vertices at all
        x0 = y0 = x1 = y1 = 0.0
    if x1 - x0 < DEGEN_MIN_SIDE:
        x1 = x0 + DEGEN_MIN_SIDE
    if y1 - y0 < DEGEN_MIN_SIDE:
        y1 = y0 + DEGEN_MIN_SIDE
    poly = Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    bbox = (x0, y0, x1, y1)
    n = max(1, len(raw_layers))
    layers = (poly,) * n
    return Orient(oi, poly, bbox, (x1 - x0) * (y1 - y0),
                  layers=layers,
                  layer_bboxes=(bbox,) * n)


def _precompute_geometry(prob, deadline=None):
    """Per-block orientation geometry.

    ``deadline`` makes preprocessing itself wall-clock aware: once the clock
    passes it, remaining blocks get raw-bbox rectangle proxies instead of
    exact polygon unions.  Proxies are strictly more conservative than the
    true union, so the resulting placements stay checker-legal; this bounds
    the fixed cost on very short time limits, where the exact build alone can
    consume the whole budget.
    """
    result = []
    rushed = False
    for block in prob["blocks"]:
        if (deadline is not None and not rushed
                and time.monotonic() >= deadline):
            rushed = True
        block_orients = []
        degenerate = []
        shapes = block.get("shape") or []
        for oi, shape in enumerate(shapes):
            raw_layers = [layer for layer in (shape.get("layers") or [])
                          if layer]
            if not raw_layers:
                continue
            if rushed:
                block_orients.append(_proxy_orient(oi, raw_layers))
                continue
            # The statement guarantees layer-0 vertex 0 is the reference point,
            # but subtract it explicitly to remain robust to equivalent inputs.
            ref_x, ref_y = raw_layers[0][0]
            # Indexed layers preserve the physical layer level even if some
            # polygon is degenerate (None) -- the checker keeps j-indexing and
            # skips unusable layers per test, and so must we.
            indexed_layers = [
                _polygon([(float(x) - ref_x, float(y) - ref_y)
                          for x, y in layer])
                for layer in raw_layers
            ]
            layer_polys = [p for p in indexed_layers if p is not None]
            if not layer_polys:
                # Every layer of this orientation is degenerate.  Remember it
                # in case NO orientation of this block survives.
                degenerate.append((oi, raw_layers))
                continue
            union = unary_union(layer_polys)
            if not union.is_valid:
                union = union.buffer(0)
            # Containment bbox must be the RAW-vertex bounding box over all
            # layers -- exactly what the checker's Block.bounding_rect uses
            # (utils.py L365-383).  buffer(0) repair can shrink an invalid
            # polygon, and a bbox from the repaired union would then admit
            # placements the checker rejects as out-of-bay.
            raw_pts = [(float(x) - ref_x, float(y) - ref_y)
                       for layer in raw_layers for x, y in layer]
            raw_bbox = (min(p[0] for p in raw_pts),
                        min(p[1] for p in raw_pts),
                        max(p[0] for p in raw_pts),
                        max(p[1] for p in raw_pts))
            block_orients.append(
                Orient(oi, union, raw_bbox,
                       float(union.area),
                       layers=tuple(indexed_layers),
                       layer_bboxes=tuple(
                           tuple(map(float, p.bounds)) if p is not None
                           else None
                           for p in indexed_layers))
            )
        if not block_orients:
            # A block with zero orientations is unplaceable and used to abort
            # the entire solve ("degenerate block geometry").  Substituting a
            # conservative proxy keeps the block -- and therefore the whole
            # run -- alive; the checker still validates against raw vertices.
            for oi, raw_layers in degenerate:
                block_orients.append(_proxy_orient(oi, raw_layers))
        if not block_orients:
            # No layer data at all.  Emit a minimal proxy per declared
            # orientation so downstream code never sees an empty list.
            for oi in range(max(1, len(shapes))):
                block_orients.append(_proxy_orient(oi, []))
        result.append(block_orients)
    return result


def _fits(geom: Orient, bay) -> bool:
    x0, y0, x1, y1 = geom.bbox
    return (math.ceil(-x0) <= math.floor(float(bay["width"]) - x1)
            and math.ceil(-y0) <= math.floor(float(bay["height"]) - y1))


def _minimum_position(geom: Orient):
    return int(math.ceil(-geom.bbox[0])), int(math.ceil(-geom.bbox[1]))


def _overlap_time(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def _bbox_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _moved_bbox(geom: Orient, x: int, y: int):
    b = geom.bbox
    return (b[0] + x, b[1] + y, b[2] + x, b[3] + y)


def _safe_polygon_position(geom: Orient, x: int, y: int, blockers,
                           exact=True) -> bool:
    """Exact positive-area test, matching the judge's collision semantics."""
    bb = _moved_bbox(geom, x, y)
    near = [a for a in blockers if _bbox_overlap(bb, a["_bbox"])]
    if not near:
        return True
    if not exact:
        return False
    gid = id(geom.poly)
    moved = None
    for other in near:
        pair_key = (gid, id(other["_geom"].poly),
                    x - other["x"], y - other["y"])
        verdict = _PAIR_CACHE.get(pair_key)
        if verdict is None:
            if moved is None:
                cache_key = (gid, x, y)
                moved = _MOVE_CACHE.get(cache_key)
                if moved is None:
                    moved = _translate(geom.poly, xoff=x, yoff=y)
                    # Bound memory on unusual hidden instances with enormous
                    # coordinate ranges while retaining the high-hit-rate
                    # construction working set.
                    if len(_MOVE_CACHE) < 250_000:
                        _MOVE_CACHE[cache_key] = moved
            try:
                # DE-9IM interior/interior dimension 2 is exactly positive-area
                # polygon overlap. It preserves legal edge contact and is
                # substantially faster than building an intersection geometry.
                verdict = not moved.relate_pattern(other["_poly"], "2********")
            except Exception:
                # Geometry exceptions are rare; rejecting is the safe direction.
                verdict = False
            if len(_PAIR_CACHE) < _PAIR_CACHE_MAX:
                _PAIR_CACHE[pair_key] = verdict
        if not verdict:
            return False
    return True


# ---------------------------------------------------------------------------
# Layer-true feasibility (KESTREL_LAYER_TRUE=1)
#
# Exact competition semantics per the official checker (utils.py):
#   static  : co-present blocks may not overlap at the SAME layer index
#             (interior area > 0; edge contact legal).
#   crane   : at mover M's ENTRY or EXIT, M's layer k must be interior-
#             disjoint from every present block's layer j for all j >= k.
# Relations tested for a candidate M on [t, e) against blocker B on
# [bE, bX) overlapping in time (bE < e and bX > t):
#   R1 static           always
#   R2 bE <  t          M-mover crane (B present at M's entry)
#   R3 bE == t          both-direction crane (same-day co-entry: makes every
#                       Stage-5 listing order of same-day ENTRYs feasible)
#   R4 t < bE           B-mover crane (B enters during M's stay - reverse)
#   R5 bX <  e          B-mover crane (B exits during M's stay - reverse)
#   R6 bX >  e          M-mover crane (B present at M's exit)
#   R7 bX == e          both-direction crane (same-day co-exit: makes every
#                       Stage-5 listing order of same-day EXITs feasible)
# R4/R5 are the reverse-crane checks: placing M must not break OTHER blocks'
# already-validated lifts occurring inside M's residency.
# ---------------------------------------------------------------------------

def _lt_layer_overlap(pa, pb):
    """True iff the two layer polygons overlap with positive interior area."""
    try:
        return pa.relate_pattern(pb, "2********")
    except Exception:
        return True  # rejecting is the safe direction


def _lt_moved_layer(geom: Orient, li: int, x: int, y: int):
    p = geom.layers[li]
    if p is None:
        return None
    key = (id(p), x, y)
    moved = _MOVE_CACHE.get(key)
    if moved is None:
        moved = _translate(p, xoff=x, yoff=y)
        if len(_MOVE_CACHE) < 250_000:
            _MOVE_CACHE[key] = moved
    return moved


def _lt_bb_hit(ba, bb_, dxa, dya, dxb, dyb):
    """Strict AABB overlap of two layer bboxes under their translations."""
    return (ba[0] + dxa < bb_[2] + dxb and bb_[0] + dxb < ba[2] + dxa
            and ba[1] + dya < bb_[3] + dyb and bb_[1] + dyb < ba[3] + dya)


def _lt_static_ok(ga: Orient, xa, ya, gb: Orient, xb, yb) -> bool:
    """Same-index layers of the two placed blocks are interior-disjoint."""
    ka, kb = id(ga.poly), id(gb.poly)
    if ka <= kb:
        key = (ka, kb, xa - xb, ya - yb)
    else:
        key = (kb, ka, xb - xa, yb - ya)
    v = _LT_STATIC.get(key)
    if v is None:
        v = True
        for k in range(min(len(ga.layers), len(gb.layers))):
            bba, bbb = ga.layer_bboxes[k], gb.layer_bboxes[k]
            if bba is None or bbb is None:
                continue
            if not _lt_bb_hit(bba, bbb, xa, ya, xb, yb):
                continue
            pa = _lt_moved_layer(ga, k, xa, ya)
            pb = _lt_moved_layer(gb, k, xb, yb)
            if pa is None or pb is None:
                continue
            if _lt_layer_overlap(pa, pb):
                v = False
                break
        if len(_LT_STATIC) < _LT_CACHE_MAX:
            _LT_STATIC[key] = v
    return v


def _lt_crane_ok(gm: Orient, xm, ym, gp: Orient, xp, yp) -> bool:
    """Mover M can be craned vertically past present block P:
    M's layer k is interior-disjoint from P's layer j for all j >= k."""
    key = (id(gm.poly), id(gp.poly), xm - xp, ym - yp)
    v = _LT_CRANE.get(key)
    if v is None:
        v = True
        n_m, n_p = len(gm.layers), len(gp.layers)
        for k in range(n_m):
            if not v:
                break
            bbm = gm.layer_bboxes[k]
            if bbm is None:
                continue
            pm = None
            for j in range(k, n_p):
                bbp = gp.layer_bboxes[j]
                if bbp is None:
                    continue
                if not _lt_bb_hit(bbm, bbp, xm, ym, xp, yp):
                    continue
                if pm is None:
                    pm = _lt_moved_layer(gm, k, xm, ym)
                    if pm is None:
                        break
                pj = _lt_moved_layer(gp, j, xp, yp)
                if pj is None:
                    continue
                if _lt_layer_overlap(pm, pj):
                    v = False
                    break
        if len(_LT_CRANE) < _LT_CACHE_MAX:
            _LT_CRANE[key] = v
    return v


def _safe_layers_position(geom: Orient, x: int, y: int, t: int, e: int,
                          blockers) -> bool:
    """Exact layer-true feasibility of placing (geom, x, y) on [t, e)."""
    bb = _moved_bbox(geom, x, y)
    for a in blockers:
        if not _bbox_overlap(bb, a["_bbox"]):
            continue
        ga = a["_geom"]
        xa, ya = a["x"], a["y"]
        if not _lt_static_ok(geom, x, y, ga, xa, ya):            # R1
            return False
        bE, bX = a["entry_time"], a["exit_time"]
        if bE < t:                                               # R2
            if not _lt_crane_ok(geom, x, y, ga, xa, ya):
                return False
        elif bE == t:                                            # R3
            if not _lt_crane_ok(geom, x, y, ga, xa, ya):
                return False
            if not _lt_crane_ok(ga, xa, ya, geom, x, y):
                return False
        else:                                                    # R4
            if not _lt_crane_ok(ga, xa, ya, geom, x, y):
                return False
        if bX < e:                                               # R5
            if not _lt_crane_ok(ga, xa, ya, geom, x, y):
                return False
        elif bX == e:                                            # R7
            if not _lt_crane_ok(geom, x, y, ga, xa, ya):
                return False
            if not _lt_crane_ok(ga, xa, ya, geom, x, y):
                return False
        else:                                                    # R6
            if not _lt_crane_ok(geom, x, y, ga, xa, ya):
                return False
    return True


def _estimated_raster_pass_seconds(prob):
    """Measured first-order cost model for one batch-raster construction."""
    bays = prob.get("bays", [])
    if not bays:
        return float("inf")
    avg_cells = sum(
        float(b["width"]) * float(b["height"]) for b in bays
    ) / len(bays)
    return (
        RASTER_PASS_SECONDS
        * len(prob.get("blocks", [])) / RASTER_REFERENCE_N
        * avg_cells / RASTER_REFERENCE_BAY_CELLS
    )


def _peak_forced_density(prob, geoms):
    """Mandatory-presence layer-0 density used by the raster selector."""
    events = []
    for bid, block in enumerate(prob.get("blocks", [])):
        areas = []
        for geom in geoms[bid]:
            layer0 = geom.layers[0] if geom.layers else None
            areas.append(float(layer0.area) if layer0 is not None else 0.0)
        area = min(areas) if areas else 0.0
        duration = _dwell(block)
        lo = float(block["due_date"]) - duration
        hi = float(block["release_time"]) + duration
        if lo < hi:
            # Ends sort before starts at a shared time, matching half-open
            # residence intervals and avoiding a false density spike.
            events.append((lo, 1, area))
            events.append((hi, 0, -area))
    load = 0.0
    peak = 0.0
    for _, _, delta in sorted(events):
        load += delta
        peak = max(peak, load)
    capacity = sum(
        float(bay["width"]) * float(bay["height"])
        for bay in prob.get("bays", [])
    )
    return peak / capacity if capacity > 0.0 else float("inf")


def _raster_objective_ratios(prob):
    """Normalize assignment penalties into equivalent tardy-day costs."""
    weights = prob.get("weights", {})
    w1 = float(weights.get("w1", 1.0))
    scale = max(abs(w1), 1e-9)
    gaps = []
    for block in prob.get("blocks", []):
        prefs = sorted(block.get("bay_preferences", []), reverse=True)
        gaps.append(
            float(prefs[0] - prefs[1]) if len(prefs) > 1 else 0.0
        )
    gaps.sort()
    median_gap = gaps[len(gaps) // 2] if gaps else 0.0
    preference_ratio = (
        float(weights.get("w3", 1.0)) * median_gap / scale
    )
    bays = prob.get("bays", [])
    mean_load = (
        sum(float(block.get("workload", 0.0))
            for block in prob.get("blocks", []))
        / max(1, len(bays))
    )
    z2_ratio = float(weights.get("w2", 1.0)) * mean_load / scale
    return preference_ratio, z2_ratio


def _select_raster(prob, usable_seconds, forced_density):
    """Fail-closed runtime selector; importing raster is never a dependency."""
    if not SELECTIVE_RASTER or len(prob.get("blocks", [])) <= 160:
        return False
    estimated = _estimated_raster_pass_seconds(prob)
    required = max(
        RASTER_MIN_REMAINING_SECONDS,
        RASTER_BUDGET_SAFETY * estimated,
    )
    if float(usable_seconds) < required:
        return False
    density = float(forced_density)
    if (
        not math.isfinite(density)
        or density < 0.0
        or density > RASTER_FORCED_DENSITY_LIMIT
    ):
        return False
    try:
        from scipy.signal import fftconvolve  # noqa: F401
        from raster_kernel import BayRaster, RasterOrient  # noqa: F401
        return True
    except Exception:
        return False


def _raster_worker_enabled(n_blocks, variant, forced_density,
                           preference_ratio=0.0, z2_ratio=0.0):
    del forced_density
    if float(preference_ratio) > RASTER_PREFERENCE_RATIO_LIMIT:
        return False
    if int(n_blocks) >= 250:
        if float(z2_ratio) > RASTER_LARGE_Z2_RATIO_LIMIT:
            return False
        variants = RASTER_LARGE_VARIANTS
    else:
        variants = RASTER_MID_VARIANTS
    return int(variant) in variants


def _raster_orient(bid, geom):
    """Cached conservative union-footprint mask for one orientation."""
    key = (bid, geom.idx)
    raster = _RASTER_CACHE.get(key)
    if raster is None:
        try:
            from raster_kernel import RasterOrient
            raster = RasterOrient([geom.poly], RASTER_S)
        except Exception:
            raster = False
        _RASTER_CACHE[key] = raster
    return raster or None


def _find_in_bay_raster(bid, bay_id, deadline, t, exit_t, blockers,
                        fitting, bay):
    """Try a conservative raster map, with exact confirmation of every hit."""
    try:
        from raster_kernel import BayRaster
        grid = BayRaster(
            int(bay["width"]), int(bay["height"]), RASTER_S, n_layers=1
        )
        for other in blockers:
            raster = _raster_orient(other["block_id"], other["_geom"])
            if raster is None or grid.window(
                    raster, int(other["x"]), int(other["y"])) is None:
                return None
            grid.stamp(raster, int(other["x"]), int(other["y"]))
        for geom in fitting:
            if time.monotonic() >= deadline:
                return None
            raster = _raster_orient(bid, geom)
            if raster is None:
                continue
            feasible, x_lo, y_lo = grid.feasible_map(raster, crane=False)
            if feasible is None or not feasible.any():
                continue
            ys, xs = feasible.nonzero()
            order = sorted(range(len(ys)), key=lambda i: (ys[i], xs[i]))
            for i in order[:24]:
                x = int(xs[i]) + x_lo
                y = int(ys[i]) + y_lo
                if not _safe_polygon_position(
                        geom, x, y, blockers, exact=True):
                    continue
                poly = _translate(geom.poly, xoff=x, yoff=y)
                if not (
                    poly.bounds[0] >= -EPS
                    and poly.bounds[1] >= -EPS
                    and poly.bounds[2] <= float(bay["width"]) + EPS
                    and poly.bounds[3] <= float(bay["height"]) + EPS
                ):
                    continue
                return {
                    "block_id": bid,
                    "bay_id": bay_id,
                    "x": x,
                    "y": y,
                    "orient_idx": geom.idx,
                    "entry_time": int(t),
                    "exit_time": int(exit_t),
                    "_geom": geom,
                    "_poly": poly,
                    "_bbox": tuple(poly.bounds),
                }
    except Exception:
        return None
    return None


def _candidate_positions(geom: Orient, bay, blockers, diagonal=False):
    """Corner/contact candidates for irregular bottom-left placement.

    With fixed orientation a translationally stable packing has a piece against
    a wall or against another piece in x/y.  Integer coordinates make the
    ceil/floor contacts below conservative even when source vertices are
    fractional.  Enumerating the Cartesian product of contact coordinates is
    inexpensive because bay heights are at most a few dozen units in the
    supplied data.
    """
    gx0, gy0, gx1, gy1 = geom.bbox
    x_lo = int(math.ceil(-gx0))
    x_hi = int(math.floor(float(bay["width"]) - gx1))
    y_lo = int(math.ceil(-gy0))
    y_hi = int(math.floor(float(bay["height"]) - gy1))
    if x_lo > x_hi or y_lo > y_hi:
        return []

    xs = {x_lo, x_hi}
    ys = {y_lo, y_hi}
    for a in blockers:
        bx0, by0, bx1, by1 = a["_bbox"]
        # Place the new full-layer envelope immediately right/left or
        # above/below an existing envelope.  The rounding leaves no overlap.
        xs.add(int(math.ceil(bx1 - gx0)))
        xs.add(int(math.floor(bx0 - gx1)))
        ys.add(int(math.ceil(by1 - gy0)))
        ys.add(int(math.floor(by0 - gy1)))
        if LAYER_TRUE:
            # Layer-true mode legalizes plan-view overlap between different
            # layers (overhangs), but envelope contacts never propose such
            # positions.  Add contacts of MY layer-0 box against the
            # blocker's layer-0 box so mushroom-roofing placements become
            # reachable; the exact predicate filters the illegal ones.
            g0 = geom.layer_bboxes[0] if geom.layer_bboxes else None
            a0 = a["_geom"].layer_bboxes[0] if a["_geom"].layer_bboxes else None
            if g0 is not None and a0 is not None:
                ax0 = a0[0] + a["x"]
                ay0 = a0[1] + a["y"]
                ax1 = a0[2] + a["x"]
                ay1 = a0[3] + a["y"]
                xs.add(int(math.ceil(ax1 - g0[0])))
                xs.add(int(math.floor(ax0 - g0[2])))
                ys.add(int(math.ceil(ay1 - g0[1])))
                ys.add(int(math.floor(ay0 - g0[3])))

    xs = [x for x in xs if x_lo <= x <= x_hi]
    ys = [y for y in ys if y_lo <= y <= y_hi]
    candidates = [(x, y) for y in ys for x in xs]
    if diagonal:
        candidates.sort(key=lambda q: (
            min(q[0] - x_lo, x_hi - q[0])
            + min(q[1] - y_lo, y_hi - q[1]),
            max(q[1] - y_lo, q[0] - x_lo),
            q[0] + q[1],
        ))
    else:
        candidates.sort(key=lambda q: (
            q[1] - y_lo,
            q[0] - x_lo,
            (q[0] + gx1) * (q[1] + gy1),
        ))
    return candidates


def _rectangle_position(geom: Orient, bay, blockers, diagonal=False):
    """Find an integer placement whose all-layer AABB misses every blocker.

    Forbidden reference-point coordinates for one rectangular blocker form an
    integer rectangle.  Row bitsets therefore test every grid position at once,
    making the conservative constructor orders of magnitude faster on dense
    long-processing instances.
    """
    gx0, gy0, gx1, gy1 = geom.bbox
    x_lo = int(math.ceil(-gx0))
    x_hi = int(math.floor(float(bay["width"]) - gx1))
    y_lo = int(math.ceil(-gy0))
    y_hi = int(math.floor(float(bay["height"]) - gy1))
    if x_lo > x_hi or y_lo > y_hi:
        return None
    nx = x_hi - x_lo + 1
    ny = y_hi - y_lo + 1
    if nx * ny > RECT_GRID_MAX_CELLS:
        # One Python big-int per grid row: build cost and peak memory both
        # scale with bay_width * bay_height, and the price is paid in all four
        # portfolio workers.  Above the cap decline the bitmask model; the
        # caller then relies on the polygon candidate path, whose cost depends
        # on the blocker count rather than on the bay dimensions.
        return None
    rows = [0] * ny
    for a in blockers:
        bx0, by0, bx1, by1 = a["_bbox"]
        # Strict AABB overlap:
        #   bx0-gx1 < x < bx1-gx0, and analogously for y.
        fx0 = max(x_lo, int(math.floor(bx0 - gx1)) + 1)
        fx1 = min(x_hi, int(math.ceil(bx1 - gx0)) - 1)
        fy0 = max(y_lo, int(math.floor(by0 - gy1)) + 1)
        fy1 = min(y_hi, int(math.ceil(by1 - gy0)) - 1)
        if fx0 > fx1 or fy0 > fy1:
            continue
        width = fx1 - fx0 + 1
        mask = ((1 << width) - 1) << (fx0 - x_lo)
        for yy in range(fy0 - y_lo, fy1 - y_lo + 1):
            rows[yy] |= mask

    full = (1 << nx) - 1
    y_indices = range(len(rows))
    for yi in y_indices:
        free = full & ~rows[yi]
        if not free:
            continue
        if diagonal and (yi & 1):
            xi = free.bit_length() - 1
        else:
            low = free & -free
            xi = low.bit_length() - 1
        return x_lo + xi, y_lo + yi
    return None


def _orientation_order(orients, bay):
    fitting = [g for g in orients if _fits(g, bay)]
    # Low height is valuable because shipyard bays are shallow.  Union area and
    # width break ties; retain mirrored shapes because their concavities differ.
    fitting.sort(key=lambda g: (
        g.bbox[3] - g.bbox[1],
        (g.bbox[2] - g.bbox[0]) * (g.bbox[3] - g.bbox[1]),
        g.bbox[2] - g.bbox[0],
        g.idx,
    ))
    return fitting


def _orientation_order_cached(geoms, bid, bay_id, bay):
    """The fitting order depends only on (block, bay); cache it per pair."""
    key = (bid, bay_id)
    fitting = _ORIENT_CACHE.get(key)
    if fitting is None:
        fitting = _orientation_order(geoms[bid], bay)
        _ORIENT_CACHE[key] = fitting
    return fitting


def _objective(prob, assignments):
    blocks = prob["blocks"]
    bays = prob["bays"]
    n_bays = len(bays)
    weights = prob.get("weights", {})
    w1 = float(weights.get("w1", 1.0))
    w2 = float(weights.get("w2", 1.0))
    w3 = float(weights.get("w3", 1.0))

    tardy = 0.0
    loads = [0.0] * n_bays
    regret = 0.0
    for bid, a in assignments.items():
        b = blocks[bid]
        tardy += max(0.0, a["exit_time"] - b["due_date"])
        loads[a["bay_id"]] += b["workload"]
        regret += max(b["bay_preferences"]) - b["bay_preferences"][a["bay_id"]]

    if n_bays > 1:
        areas = [float(b["width"] * b["height"]) for b in bays]
        avg = sum(areas) / n_bays
        scaled = [(avg / areas[j]) * loads[j] for j in range(n_bays)]
        imbalance = math.floor(max(scaled) - min(scaled))
    else:
        imbalance = 0
    return w1 * tardy + w2 * imbalance + w3 * regret


def _imbalance(prob, loads):
    bays = prob["bays"]
    if len(bays) < 2:
        return 0
    areas = [float(b["width"] * b["height"]) for b in bays]
    avg = sum(areas) / len(areas)
    scaled = [(avg / areas[j]) * loads[j] for j in range(len(bays))]
    return math.floor(max(scaled) - min(scaled))


def _serial_fallback(prob, geoms, deadline=None):
    """Fast, structurally feasible incumbent available before optimization.

    ``deadline`` bounds the fixed cost on very short time limits: past it the
    per-block bay choice stops scoring every bay and simply takes the first
    fitting one.  The schedule is still complete and structurally feasible
    (per bay the residence intervals are serial and disjoint), which is what
    the incumbent is for; only its quality degrades.
    """
    n_bays = len(prob["bays"])
    ends = [0] * n_bays
    assignments = {}
    loads = [0.0] * n_bays
    w2 = float(prob.get("weights", {}).get("w2", 1.0))
    w3 = float(prob.get("weights", {}).get("w3", 1.0))

    order = sorted(range(len(prob["blocks"])),
                   key=lambda i: (prob["blocks"][i]["due_date"],
                                  prob["blocks"][i]["processing_time"], i))
    for bid in order:
        block = prob["blocks"][bid]
        choices = []
        rushed = deadline is not None and time.monotonic() >= deadline
        old_imb = 0 if rushed else _imbalance(prob, loads)
        for j, bay in enumerate(prob["bays"]):
            fitting = _orientation_order_cached(geoms, bid, j, bay)
            if not fitting:
                continue
            g = fitting[0]
            entry = max(int(block["release_time"]), ends[j])
            exit_t = entry + _dwell(block)
            if rushed:
                choices.append((0.0, entry,
                                -block["bay_preferences"][j], j, g))
                break
            new_loads = loads.copy()
            new_loads[j] += block["workload"]
            score = (
                float(prob.get("weights", {}).get("w1", 1.0))
                * max(0, exit_t - block["due_date"])
                + w3 * (max(block["bay_preferences"])
                        - block["bay_preferences"][j])
                + w2 * (_imbalance(prob, new_loads) - old_imb)
            )
            choices.append((score, entry, -block["bay_preferences"][j], j, g))
        if not choices:
            raise ValueError("Instance contains an unplaceable block")
        _, entry, _, j, g = min(choices, key=lambda q: q[:4])
        x, y = _minimum_position(g)
        exit_t = entry + _dwell(block)
        poly = _translate(g.poly, xoff=x, yoff=y)
        a = {
            "block_id": bid, "bay_id": j, "x": x, "y": y,
            "orient_idx": g.idx, "entry_time": entry, "exit_time": exit_t,
            "_geom": g, "_poly": poly, "_bbox": tuple(poly.bounds),
        }
        assignments[bid] = a
        ends[j] = exit_t
        loads[j] += block["workload"]
    return assignments


def _event_times(block, others, bay_id):
    r = int(block["release_time"])
    times = {r}
    for a in others.values():
        if a["bay_id"] == bay_id and a["exit_time"] >= r:
            times.add(int(a["exit_time"]))
    return sorted(times)


def _find_in_bay(prob, geoms, bid, bay_id, others, deadline, diagonal=False,
                 exact=True):
    """Earliest feasible placement in one bay, or None on timeout/no fit."""
    block = prob["blocks"][bid]
    bay = prob["bays"][bay_id]
    proc = _dwell(block)
    fitting = _orientation_order_cached(geoms, bid, bay_id, bay)
    if not fitting:
        return None
    if not exact:
        # Mirrored orientations often have identical envelopes.  They are
        # distinct for polygon packing but redundant in rectangle mode.
        unique = []
        seen_dims = set()
        for g in fitting:
            dims = (round(g.bbox[2] - g.bbox[0], 7),
                    round(g.bbox[3] - g.bbox[1], 7))
            if dims not in seen_dims:
                seen_dims.add(dims)
                unique.append(g)
        fitting = unique

    # Exact geometry is only needed for contemporaneous blocks.  At a time
    # boundary the blocker set can improve only when an existing block exits,
    # hence release + existing exit times is a complete useful event set for
    # earliest-start insertion into a fixed partial schedule.
    for t in _event_times(block, others, bay_id):
        if time.monotonic() >= deadline:
            return None
        exit_t = t + proc
        blockers = [
            a for a in others.values()
            if a["bay_id"] == bay_id
            and _overlap_time(t, exit_t, a["entry_time"], a["exit_time"])
        ]
        if exact and _RASTER_ACTIVE:
            hit = _find_in_bay_raster(
                bid, bay_id, deadline, t, exit_t, blockers, fitting, bay
            )
            if hit is not None:
                return hit
            # Above n=160 the hardened solver does not run this exhaustive
            # Shapely scan at all: one pass is measured above 600 seconds.
            # Raster workers therefore advance to the next event after a miss,
            # while separate portfolio workers preserve the legacy rectangle
            # path.  This keeps the measured 83-second raster throughput.
            if not RASTER_SCAN_ON_MISS:
                continue
        best = None
        for g in fitting:
            if not exact:
                pos = _rectangle_position(g, bay, blockers, diagonal)
                if pos is None:
                    continue
                x, y = pos
                poly = _translate(g.poly, xoff=x, yoff=y)
                return {
                    "block_id": bid, "bay_id": bay_id, "x": int(x), "y": int(y),
                    "orient_idx": g.idx, "entry_time": int(t),
                    "exit_time": int(exit_t), "_geom": g, "_poly": poly,
                    "_bbox": tuple(poly.bounds),
                }
            positions = _candidate_positions(g, bay, blockers, diagonal)
            contested = [] if LAYER_TRUE else None
            for k, (x, y) in enumerate(positions):
                if (k & 127) == 0 and time.monotonic() >= deadline:
                    return None
                if LAYER_TRUE:
                    # Entry-day dominance: prefer union-free positions (the
                    # proven v2.1 behavior, cheap and LIFO-free).  Contested
                    # positions -- legal only under the exact layer/crane
                    # predicate, e.g. overhang roofing -- are deferred and
                    # used only when day t offers no union-free position,
                    # i.e. exactly when they buy a strictly earlier entry.
                    if not _safe_polygon_position(g, x, y, blockers,
                                                  exact=True):
                        if len(contested) < 96:
                            contested.append((x, y))
                        continue
                elif not _safe_polygon_position(g, x, y, blockers, exact=exact):
                    continue
                bb = _moved_bbox(g, x, y)
                if exact:
                    poly = _MOVE_CACHE.get((id(g.poly), x, y))
                    if poly is None:
                        poly = _translate(g.poly, xoff=x, yoff=y)
                    return {
                        "block_id": bid, "bay_id": bay_id,
                        "x": int(x), "y": int(y), "orient_idx": g.idx,
                        "entry_time": int(t), "exit_time": int(exit_t),
                        "_geom": g, "_poly": poly, "_bbox": tuple(poly.bounds),
                    }
                # Compact, wall-supported layouts leave larger contiguous holes.
                touch = sum(
                    1 for z in blockers
                    if (abs(bb[0] - z["_bbox"][2]) < EPS
                        or abs(bb[2] - z["_bbox"][0]) < EPS
                        or abs(bb[1] - z["_bbox"][3]) < EPS
                        or abs(bb[3] - z["_bbox"][1]) < EPS)
                )
                compact = (bb[3], bb[2], -touch, g.idx, x, y)
                if best is None or compact < best[0]:
                    best = (compact, g, x, y)
                    # Candidate order is bottom-left; a wall corner is already
                    # optimal for the compactness tie-break.
                    if compact[0] <= g.bbox[3] - g.bbox[1] + EPS:
                        break
            if LAYER_TRUE and exact and contested:
                # No union-free position for this orientation at day t: try
                # the deferred contested positions under the exact layer
                # predicate (an accept here strictly beats waiting a day).
                for (x, y) in contested:
                    if time.monotonic() >= deadline:
                        return None
                    if _safe_layers_position(g, x, y, int(t), int(exit_t),
                                             blockers):
                        poly = _translate(g.poly, xoff=x, yoff=y)
                        return {
                            "block_id": bid, "bay_id": bay_id,
                            "x": int(x), "y": int(y), "orient_idx": g.idx,
                            "entry_time": int(t), "exit_time": int(exit_t),
                            "_geom": g, "_poly": poly,
                            "_bbox": tuple(poly.bounds),
                        }
            if best is not None and best[0][0] <= g.bbox[3] - g.bbox[1] + EPS:
                break
        if best is not None:
            _, g, x, y = best
            poly = _translate(g.poly, xoff=x, yoff=y)
            return {
                "block_id": bid, "bay_id": bay_id, "x": int(x), "y": int(y),
                "orient_idx": g.idx, "entry_time": int(t),
                "exit_time": int(exit_t), "_geom": g, "_poly": poly,
                "_bbox": tuple(poly.bounds),
            }
    return None


def _best_insertion(prob, geoms, bid, others, deadline, diagonal=False,
                    exact=True):
    block = prob["blocks"][bid]
    n_bays = len(prob["bays"])
    weights = prob.get("weights", {})
    w1 = float(weights.get("w1", 1.0))
    w2 = float(weights.get("w2", 1.0))
    w3 = float(weights.get("w3", 1.0))

    loads = [0.0] * n_bays
    for oid, a in others.items():
        loads[a["bay_id"]] += prob["blocks"][oid]["workload"]
    old_imb = _imbalance(prob, loads)
    prefs = block["bay_preferences"]
    smax = max(prefs)

    best = None
    # Preference first is a useful search order but every fitting bay is scored.
    bay_order = sorted(range(n_bays),
                       key=lambda j: (-prefs[j], -prob["bays"][j]["width"]
                                      * prob["bays"][j]["height"], j))
    for j in bay_order:
        if time.monotonic() >= deadline:
            break
        candidate = _find_in_bay(
            prob, geoms, bid, j, others, deadline,
            diagonal=(diagonal ^ bool(j & 1)),
            exact=exact,
        )
        if candidate is None:
            continue
        new_loads = loads.copy()
        new_loads[j] += block["workload"]
        tardy = max(0, candidate["exit_time"] - block["due_date"])
        exact_delta = (
            w1 * tardy
            + w3 * (smax - prefs[j])
            + w2 * (_imbalance(prob, new_loads) - old_imb)
        )
        # A tiny non-objective term breaks exact ties toward space-efficient
        # bays/placements without ever overriding one objective unit.
        bay_area = prob["bays"][j]["width"] * prob["bays"][j]["height"]
        density_tie = (candidate["_geom"].area * block["processing_time"]
                       / max(1.0, bay_area)) * 1e-6
        key = (exact_delta + density_tie, candidate["exit_time"],
               candidate["_bbox"][3], -prefs[j], j)
        if best is None or key < best[0]:
            best = (key, candidate)
    return None if best is None else best[1]


def _priority_order(prob, geoms, mode, seed):
    rng = random.Random(seed)
    keys = {}
    for i, b in enumerate(prob["blocks"]):
        min_area = min((g.area for g in geoms[i]), default=1.0)
        p = max(1, int(b["processing_time"]))
        r = int(b["release_time"])
        d = int(b["due_date"])
        slack = d - r - p
        noise = rng.random()
        if mode == 0:       # earliest due date, large tight blocks first
            key = (d, slack, -(min_area * p), noise)
        elif mode == 1:     # latest-start urgency
            key = (d - p, slack, d, -min_area, noise)
        elif mode == 2:     # scarcity/space-time aware
            key = (slack, d, -(min_area * p), noise)
        elif mode == 3:     # modified due date / shortest urgent work
            key = (max(r + p, d), slack, p, -min_area, noise)
        else:               # randomized restricted EDD
            key = (d + rng.randint(-2, 2), slack, -min_area, noise)
        keys[i] = key
    return sorted(keys, key=keys.get)


def _construct(prob, geoms, mode, seed, deadline, exact=True):
    assignments = {}
    order = _priority_order(prob, geoms, mode, seed)
    for rank, bid in enumerate(order):
        if time.monotonic() >= deadline:
            return None
        a = _best_insertion(prob, geoms, bid, assignments, deadline,
                            diagonal=bool((mode + rank) & 1), exact=exact)
        if a is None:
            return None
        assignments[bid] = a
    return assignments


def _blame_order(prob, assignments):
    w1 = float(prob.get("weights", {}).get("w1", 1.0))
    w3 = float(prob.get("weights", {}).get("w3", 1.0))
    scored = []
    for bid, a in assignments.items():
        b = prob["blocks"][bid]
        tardy = max(0, a["exit_time"] - b["due_date"])
        regret = max(b["bay_preferences"]) - b["bay_preferences"][a["bay_id"]]
        scored.append((-(w1 * tardy + w3 * regret), b["due_date"], bid))
    return [bid for _, _, bid in sorted(scored)]


def _metric_add(metrics, key, value=1.0):
    """Accumulate optional experiment metrics without affecting submissions."""
    if metrics is not None:
        metrics[key] = metrics.get(key, 0.0) + value


def _metric_extreme(metrics, key, value, choose_min=True):
    """Track a minimum/maximum experiment metric."""
    if metrics is None:
        return
    old = metrics.get(key)
    if old is None or (value < old if choose_min else value > old):
        metrics[key] = value


def _lahc_history_length(n_blocks):
    """Tonight's fixed, scale-free late-acceptance memory."""
    del n_blocks
    return 120


def _advanced_lns_enabled(n_blocks, limit, variant):
    """Enable W2 on its dedicated portfolio worker when search time exists."""
    return bool(
        ADVANCED_LNS
        and int(variant) == 1
        and int(n_blocks) >= ADVANCED_LNS_MIN_BLOCKS
        and float(limit) >= ADVANCED_LNS_MIN_LIMIT
    )


def _accept_lns_candidate(value, search_obj, best_obj, history_threshold,
                          late_accept):
    """Pure acceptance predicate used by worker 1 and structural tests."""
    if value <= search_obj + 1e-7:
        return True
    cap = best_obj + max(1.0, 0.0125 * max(1.0, best_obj))
    return bool(
        late_accept
        and value <= history_threshold + 1e-7
        and value <= cap + 1e-7
    )


def _advanced_blame_scores(prob, assignments):
    """Objective blame with temporal/spatial propagation to likely blockers.

    Direct tardiness identifies the victim but not the coordinated move needed
    to help it.  For a late block, project its current placement into the
    latest zero-tardy interval and pass part of its cost to blocks occupying
    that bay/time window.  AABB overlap at the victim's current position is a
    stronger signal because that block is an actual geometric obstruction for
    at least one useful placement.  The returned links drive related removal;
    the scalar scores decide which hot spot to attack first.
    """
    blocks = prob["blocks"]
    weights = prob.get("weights", {})
    w1 = float(weights.get("w1", 1.0))
    w2 = float(weights.get("w2", 1.0))
    w3 = float(weights.get("w3", 1.0))
    scores = {i: 0.0 for i in assignments}
    links = {i: {} for i in assignments}
    by_bay = [[] for _ in prob["bays"]]

    for bid, a in assignments.items():
        by_bay[a["bay_id"]].append(bid)
        b = blocks[bid]
        tardy = max(0.0, a["exit_time"] - b["due_date"])
        regret = max(b["bay_preferences"]) - b["bay_preferences"][a["bay_id"]]
        scores[bid] += w1 * tardy + w3 * regret

    for bid, a in assignments.items():
        b = blocks[bid]
        tardy = max(0.0, a["exit_time"] - b["due_date"])
        if tardy <= 0.0 or w1 <= 0.0:
            continue
        dwell = _dwell(b)
        release = int(b["release_time"])
        target_entry = max(
            release, int(math.floor(float(b["due_date"]))) - dwell
        )
        target_exit = target_entry + dwell
        # Binding T1 definition: blame jobs that occupied this bay while the
        # late block waited, [R_i, ENTRY_i).  The latest zero-tardy interval is
        # retained as an extra signal inside that broader causal window.
        wait_start = release
        wait_end = int(a["entry_time"])
        if wait_end <= wait_start:
            continue
        pressure = w1 * tardy
        weighted = []
        for oid in by_bay[a["bay_id"]]:
            if oid == bid:
                continue
            other = assignments[oid]
            overlap = (
                min(wait_end, int(other["exit_time"]))
                - max(wait_start, int(other["entry_time"]))
            )
            if overlap <= 0:
                continue
            strength = 1.0 + 2.0 * overlap / max(1.0, wait_end - wait_start)
            if _overlap_time(
                    target_entry, target_exit,
                    other["entry_time"], other["exit_time"]):
                strength += 1.5
            if _bbox_overlap(a["_bbox"], other["_bbox"]):
                strength += 2.5
            # Occupiers ending after the desired start are especially useful
            # to move because their EXIT creates one of the decoder's event
            # times at which the late block can enter.
            if other["exit_time"] > target_entry:
                strength += min(
                    1.5,
                    (other["exit_time"] - target_entry) / max(1.0, dwell),
                )
            weighted.append((oid, strength))
        denom = sum(weight for _, weight in weighted)
        if denom > 0.0:
            propagated = 0.50 * pressure
            for oid, weight in weighted:
                share = propagated * weight / denom
                scores[oid] += share
                links[bid][oid] = links[bid].get(oid, 0.0) + share
                links[oid][bid] = links[oid].get(bid, 0.0) + 0.35 * share

    # When imbalance is valuable, assign some blame to movable jobs in the
    # heaviest normalized bay.  Preference-flexible jobs receive more because
    # they can be moved at lower Z3 cost.
    if w2 > 0.0 and len(prob["bays"]) > 1 and assignments:
        areas = [float(b["width"] * b["height"]) for b in prob["bays"]]
        avg = sum(areas) / len(areas)
        loads = [0.0] * len(areas)
        for bid, a in assignments.items():
            loads[a["bay_id"]] += blocks[bid]["workload"]
        scaled = [(avg / areas[j]) * loads[j] for j in range(len(areas))]
        heavy = max(range(len(areas)), key=scaled.__getitem__)
        imbalance_cost = w2 * max(0.0, max(scaled) - min(scaled))
        pool = by_bay[heavy]
        if pool and imbalance_cost > 0.0:
            base = 0.20 * imbalance_cost / len(pool)
            for bid in pool:
                prefs = blocks[bid]["bay_preferences"]
                flexibility = 1.0
                if len(prefs) > 1:
                    top = sorted(prefs, reverse=True)
                    flexibility += 1.0 / (1.0 + max(0.0, top[0] - top[1]))
                scores[bid] += base * flexibility

    return scores, links


def _related_destroy_set(prob, incumbent, rng, iteration, max_removed=None):
    """Choose a large, coherent neighborhood around a high-blame block."""
    n = len(incumbent)
    scores, links = _advanced_blame_scores(prob, incumbent)
    ranked = sorted(
        incumbent,
        key=lambda i: (-scores[i], prob["blocks"][i]["due_date"], i),
    )
    if not ranked:
        return [], scores

    anchor = ranked[0]
    aa = incumbent[anchor]
    ba = prob["blocks"][anchor]
    dwells = sorted(_dwell(b) for b in prob["blocks"])
    time_scale = max(1.0, float(dwells[len(dwells) // 2]))
    max_blame = max(max(scores.values()), 1.0)

    related = []
    for bid, a in incumbent.items():
        if bid == anchor:
            affinity = float("inf")
        else:
            b = prob["blocks"][bid]
            if aa["exit_time"] <= a["entry_time"]:
                gap = a["entry_time"] - aa["exit_time"]
            elif a["exit_time"] <= aa["entry_time"]:
                gap = aa["entry_time"] - a["exit_time"]
            else:
                gap = 0
            affinity = 3.5 / (1.0 + gap / time_scale)
            affinity += 2.0 / (
                1.0 + abs(float(b["due_date"]) - float(ba["due_date"]))
                / time_scale
            )
            affinity += 1.0 / (
                1.0 + abs(float(b["release_time"]) - float(ba["release_time"]))
                / time_scale
            )
            if a["bay_id"] == aa["bay_id"]:
                affinity += 5.0
                if _bbox_overlap(a["_bbox"], aa["_bbox"]):
                    affinity += 2.5
            affinity += 3.0 * scores[bid] / max_blame
            affinity += 5.0 * links.get(anchor, {}).get(bid, 0.0) / max_blame
            affinity += 2.0 * links.get(bid, {}).get(anchor, 0.0) / max_blame
            affinity += 0.15 * rng.random()
        related.append((-affinity, -scores[bid], bid))

    related.sort()
    target = max(18, int(round(math.sqrt(n) * 1.50)))
    target += iteration % max(1, min(5, target // 4 + 1))
    target = min(30, n, target)
    if max_removed is not None:
        target = min(target, max(6, int(max_removed)))
    core_size = max(1, target - min(3, max(0, n - 1)))
    removed = [bid for _, _, bid in related[:core_size]]
    pool = [bid for _, _, bid in related[core_size:] if bid not in removed]
    if pool:
        removed.extend(rng.sample(pool, min(target - len(removed), len(pool))))
    return removed, scores


def _assignment_fits_partial(candidate, partial, exact=True):
    """Check a cached/fallback assignment against the current partial state."""
    blockers = [
        a for a in partial.values()
        if a["bay_id"] == candidate["bay_id"]
        and _overlap_time(
            candidate["entry_time"], candidate["exit_time"],
            a["entry_time"], a["exit_time"],
        )
    ]
    if LAYER_TRUE and exact:
        return _safe_layers_position(
            candidate["_geom"], candidate["x"], candidate["y"],
            candidate["entry_time"], candidate["exit_time"], blockers,
        )
    return _safe_polygon_position(
        candidate["_geom"], candidate["x"], candidate["y"], blockers,
        exact=exact,
    )


def _insertion_options(prob, geoms, bid, others, deadline, diagonal=False,
                       exact=True, fallback=None):
    """Return the best scored placement in every bay plus a safe fallback.

    Regret repair needs more information than ``_best_insertion`` exposes: the
    cost of losing the best alternative.  This routine deliberately remains
    separate so the legacy workers retain their exact call order and timing.
    """
    block = prob["blocks"][bid]
    n_bays = len(prob["bays"])
    weights = prob.get("weights", {})
    w1 = float(weights.get("w1", 1.0))
    w2 = float(weights.get("w2", 1.0))
    w3 = float(weights.get("w3", 1.0))
    loads = [0.0] * n_bays
    for oid, a in others.items():
        loads[a["bay_id"]] += prob["blocks"][oid]["workload"]
    old_imb = _imbalance(prob, loads)
    prefs = block["bay_preferences"]
    smax = max(prefs)
    options = []
    seen = set()

    def append_candidate(candidate):
        signature = (
            candidate["bay_id"], candidate["orient_idx"],
            candidate["x"], candidate["y"],
            candidate["entry_time"], candidate["exit_time"],
        )
        if signature in seen:
            return
        seen.add(signature)
        j = candidate["bay_id"]
        new_loads = loads.copy()
        new_loads[j] += block["workload"]
        cost = (
            w1 * max(0.0, candidate["exit_time"] - block["due_date"])
            + w3 * (smax - prefs[j])
            + w2 * (_imbalance(prob, new_loads) - old_imb)
        )
        bay_area = prob["bays"][j]["width"] * prob["bays"][j]["height"]
        tie = (
            candidate["exit_time"],
            candidate["_bbox"][3],
            candidate["_geom"].area * _dwell(block) / max(1.0, bay_area),
            -prefs[j], j,
        )
        options.append((float(cost), tie, candidate))

    bay_order = sorted(
        range(n_bays),
        key=lambda j: (
            -prefs[j],
            -prob["bays"][j]["width"] * prob["bays"][j]["height"],
            j,
        ),
    )
    for pos, j in enumerate(bay_order):
        now = time.monotonic()
        if now >= deadline:
            break
        bays_left = max(1, len(bay_order) - pos)
        bay_deadline = min(
            deadline,
            now + max(0.025, 1.35 * (deadline - now) / (bays_left + 1)),
        )
        candidate = _find_in_bay(
            prob, geoms, bid, j, others, bay_deadline,
            diagonal=(diagonal ^ bool(j & 1)), exact=exact,
        )
        if candidate is not None:
            append_candidate(candidate)

    # The incumbent position guarantees a recovery path when it is still
    # compatible with already repaired blocks.  This sharply reduces wasted
    # neighborhoods when a time slice is too short to rediscover it.
    if fallback is not None and _assignment_fits_partial(
            fallback, others, exact=exact):
        append_candidate(fallback)

    options.sort(key=lambda item: (item[0], item[1]))
    return options


def _regret_recreate(prob, geoms, incumbent, removed, scores, deadline, rng,
                     iteration, exact=True, metrics=None):
    """Bounded regret-2 recreation of a related destroy neighborhood."""
    removed_set = set(removed)
    partial = {i: a for i, a in incumbent.items() if i not in removed_set}
    pending = list(removed)
    step = 0

    while pending:
        now = time.monotonic()
        if now >= deadline:
            return None
        ranked = sorted(
            pending,
            key=lambda i: (
                -scores.get(i, 0.0),
                prob["blocks"][i]["due_date"] - _dwell(prob["blocks"][i]),
                prob["blocks"][i]["due_date"], i,
            ),
        )
        # Evaluate the two most urgent alternatives plus an occasional diverse
        # candidate.  Full regret over q blocks at every step is O(q^2*m) exact
        # geometry calls and consumes the entire competition budget.
        shortlist = ranked[:min(2, len(ranked))]
        if len(ranked) > 3 and (step + iteration) % 3 == 0:
            tail = ranked[2:]
            shortlist.append(tail[rng.randrange(len(tail))])

        evaluated = []
        for bid in shortlist:
            now = time.monotonic()
            if now >= deadline:
                return None
            work = max(1, len(pending) + 2 * len(shortlist))
            probe_deadline = min(
                deadline,
                now + max(0.06, 1.25 * (deadline - now) / work),
            )
            options = _insertion_options(
                prob, geoms, bid, partial, probe_deadline,
                diagonal=bool((iteration + step + bid) & 1),
                exact=exact, fallback=incumbent[bid],
            )
            # Preserve a completion certificate: a chosen placement may not
            # invalidate the incumbent positions of blocks that remain
            # uninserted.  Those reservations disappear as repair progresses,
            # so later steps still have increasing freedom.  Without this
            # guard an early attractive move frequently strands the last block
            # and wastes the whole neighborhood.
            reserved = {
                oid: incumbent[oid]
                for oid in pending if oid != bid
            }
            reserved_options = [
                option for option in options
                if _assignment_fits_partial(
                    option[2], reserved, exact=exact
                )
            ]
            _metric_add(
                metrics, "lns_reserved_options_rejected",
                len(options) - len(reserved_options),
            )
            options = reserved_options
            _metric_add(metrics, "lns_regret_blocks_evaluated")
            _metric_add(metrics, "lns_insertion_options", len(options))
            if not options:
                # Adding more blocks cannot make this partial schedule easier.
                return None
            regret = (
                options[1][0] - options[0][0]
                if len(options) > 1 else 0.0
            )
            scarcity = 1 if len(options) == 1 else 0
            evaluated.append((
                scarcity, regret, scores.get(bid, 0.0),
                -float(prob["blocks"][bid]["due_date"]),
                bid, options[0][2],
            ))

        # Classical regret prioritizes scarce blocks, then the largest penalty
        # for losing the best placement.  Blame and due date break ties.
        chosen = max(evaluated)
        bid, candidate = chosen[-2], chosen[-1]
        partial[bid] = candidate
        pending.remove(bid)
        _metric_add(metrics, "lns_regret_insertions")
        step += 1

    return partial


def _advanced_lns_move(prob, geoms, incumbent, deadline, rng, iteration,
                       max_removed=None, exact=True, metrics=None):
    """One blame-related destroy followed by bounded regret recreation."""
    started = time.monotonic()
    removed, scores = _related_destroy_set(
        prob, incumbent, rng, iteration, max_removed=max_removed,
    )
    _metric_add(metrics, "lns_moves_proposed")
    _metric_add(metrics, "lns_blocks_removed", len(removed))
    if len(removed) < 2:
        _metric_add(metrics, "lns_seconds", time.monotonic() - started)
        return None
    candidate = _regret_recreate(
        prob, geoms, incumbent, removed, scores, deadline, rng, iteration,
        exact=exact, metrics=metrics,
    )
    _metric_add(metrics, "lns_seconds", time.monotonic() - started)
    if candidate is not None and len(candidate) == len(incumbent):
        _metric_add(metrics, "lns_moves_completed")
        return candidate
    _metric_add(metrics, "lns_moves_aborted")
    return None


def _minimum_layer0_area(orients):
    """Smallest usable layer-0 area across a block's orientations."""
    areas = []
    for geom in orients:
        if geom.layers and geom.layers[0] is not None:
            areas.append(float(geom.layers[0].area))
    if areas:
        return max(1e-6, min(areas))
    return max(1e-6, min((g.area for g in orients), default=1.0))


def _oracle_neighborhood(prob, incumbent, scores, max_jobs=25):
    """Select one late bay/window for the bounded scheduling oracle."""
    blocks = prob["blocks"]
    late = [
        bid for bid, a in incumbent.items()
        if a["exit_time"] > blocks[bid]["due_date"]
    ]
    if not late:
        return None, []
    anchor = max(
        late,
        key=lambda i: (
            incumbent[i]["exit_time"] - blocks[i]["due_date"],
            scores.get(i, 0.0), -blocks[i]["due_date"], -i,
        ),
    )
    aa = incumbent[anchor]
    bay = aa["bay_id"]
    durations = sorted(_dwell(block) for block in blocks)
    radius = max(
        2, durations[len(durations) // 2], _dwell(blocks[anchor])
    )
    desired = max(
        int(blocks[anchor]["release_time"]),
        int(math.floor(float(blocks[anchor]["due_date"])))
        - _dwell(blocks[anchor]),
    )
    window_lo = desired - radius
    window_hi = aa["entry_time"] + _dwell(blocks[anchor]) + radius
    candidates = [
        bid for bid, a in incumbent.items()
        if a["bay_id"] == bay
        and _overlap_time(
            window_lo, window_hi, a["entry_time"], a["exit_time"]
        )
    ]
    candidates.sort(key=lambda i: (
        0 if i == anchor else 1,
        -scores.get(i, 0.0),
        abs(incumbent[i]["entry_time"] - desired),
        blocks[i]["due_date"], i,
    ))
    return bay, candidates[:max_jobs]


def _oracle_repair(prob, geoms, incumbent, deadline, seed=0, metrics=None,
                   proposer=None, solve_time_limit=None):
    """Propose starts with CP-SAT, then decode through exact Kestrel geometry."""
    started = time.monotonic()
    _metric_add(metrics, "oracle_calls")
    if proposer is None:
        try:
            import repair_oracle
        except Exception:
            _metric_add(metrics, "oracle_unavailable")
            return None
        if not repair_oracle.available():
            _metric_add(metrics, "oracle_unavailable")
            return None
        proposer = repair_oracle.propose_starts

    scores, _ = _advanced_blame_scores(prob, incumbent)
    bay_id, free = _oracle_neighborhood(prob, incumbent, scores)
    if bay_id is None or len(free) < 8:
        _metric_add(metrics, "oracle_skipped_small")
        return None
    blocks = prob["blocks"]
    scale = 100
    demands = {
        bid: max(1, int(math.ceil(
            scale * _minimum_layer0_area(geoms[bid]) - 1e-9
        )))
        for bid in incumbent
    }
    bay_area = float(
        prob["bays"][bay_id]["width"] * prob["bays"][bay_id]["height"]
    )

    # This is intentionally a conservative relaxation rather than a proof of
    # geometric feasibility.  Lower alpha reduces the decoder's rejection
    # rate; exact geometry and the official checker still own acceptance.
    capacity = max(1, int(math.floor(0.88 * scale * bay_area)))

    free_set = set(free)
    jobs = [{
        "id": bid,
        "release": int(blocks[bid]["release_time"]),
        "due": int(math.floor(float(blocks[bid]["due_date"]))),
        "duration": _dwell(blocks[bid]),
        "demand": demands[bid],
        "current_start": int(incumbent[bid]["entry_time"]),
    } for bid in free]
    fixed = [{
        "start": int(a["entry_time"]),
        "duration": int(a["exit_time"] - a["entry_time"]),
        "demand": demands[bid],
    } for bid, a in incumbent.items()
        if a["bay_id"] == bay_id and bid not in free_set]
    durations = sorted(job["duration"] for job in jobs)
    margin = max(durations[-1], 2 * durations[len(durations) // 2])
    horizon_end = max(
        max(a["exit_time"] for a in incumbent.values()),
        max(job["due"] for job in jobs),
    ) + margin

    now = time.monotonic()
    remaining = deadline - now
    if remaining < 0.8:
        _metric_add(metrics, "oracle_skipped_time")
        return None
    requested = (
        0.02 * remaining
        if solve_time_limit is None else float(solve_time_limit)
    )
    solve_seconds = min(
        max(0.05, remaining - 0.25),
        min(2.0, max(0.25, requested)),
    )
    proposed = proposer(
        jobs, fixed, capacity, horizon_end, solve_seconds, seed=seed,
    )
    _metric_add(metrics, "oracle_solver_seconds", time.monotonic() - now)
    if not proposed:
        _metric_add(metrics, "oracle_no_solution")
        return None
    if set(proposed) != free_set:
        _metric_add(metrics, "oracle_incomplete_proposals")
        return None
    _metric_add(metrics, "oracle_proposals")

    old_tardy = sum(
        max(0, incumbent[bid]["exit_time"] - blocks[bid]["due_date"])
        for bid in free
    )
    proposed_tardy = sum(
        max(0, proposed[bid] + _dwell(blocks[bid])
            - blocks[bid]["due_date"])
        for bid in free
    )
    if proposed_tardy >= old_tardy:
        _metric_add(metrics, "oracle_no_timing_gain")
        return None
    _metric_add(metrics, "oracle_timing_improving")

    partial = {
        bid: a for bid, a in incumbent.items() if bid not in free_set
    }
    _metric_add(metrics, "oracle_decode_attempts")
    order = sorted(
        free,
        key=lambda bid: (
            proposed[bid], blocks[bid]["due_date"], -scores.get(bid, 0.0), bid
        ),
    )
    # Preserve the hot legacy decoder byte-for-byte: express proposed starts
    # as temporary release bounds in an oracle-only problem view instead of
    # adding a branch to every normal `_find_in_bay` call.
    oracle_prob = dict(prob)
    oracle_blocks = list(blocks)
    for bid in free:
        shifted = dict(blocks[bid])
        shifted["release_time"] = max(
            float(blocks[bid]["release_time"]), float(proposed[bid])
        )
        oracle_blocks[bid] = shifted
    oracle_prob["blocks"] = oracle_blocks
    for k, bid in enumerate(order):
        now = time.monotonic()
        if now >= deadline:
            _metric_add(metrics, "oracle_decode_aborted")
            return None
        slice_end = min(
            deadline,
            now + max(
                0.08,
                1.5 * (deadline - now) / max(1, len(order) - k),
            ),
        )
        candidate = _find_in_bay(
            oracle_prob, geoms, bid, bay_id, partial, slice_end,
            diagonal=bool((seed + k) & 1), exact=True,
        )
        if candidate is None:
            _metric_add(metrics, "oracle_decode_failed")
            return None
        partial[bid] = candidate

    _metric_add(metrics, "oracle_seconds", time.monotonic() - started)
    _metric_add(metrics, "oracle_decoded")
    if _objective(prob, partial) + 1e-7 < _objective(prob, incumbent):
        _metric_add(metrics, "oracle_objective_improving")
        return partial
    _metric_add(metrics, "oracle_decode_no_gain")
    return None


def _single_reinsert_sweep(prob, geoms, incumbent, deadline, phase,
                           exact=True):
    blocks = prob["blocks"]
    weights = prob.get("weights", {})
    w1 = float(weights.get("w1", 1.0))
    w2 = float(weights.get("w2", 1.0))
    w3 = float(weights.get("w3", 1.0))

    current = dict(incumbent)
    loads = [0.0] * len(prob["bays"])
    for bid, a in current.items():
        loads[a["bay_id"]] += blocks[bid]["workload"]
    imb_current = _imbalance(prob, loads)

    improved = False
    order = _blame_order(prob, current)
    if phase & 1:
        # Alternating direction prevents the same high-blame prefix from
        # consuming every short time limit.
        order.reverse()
    for k, bid in enumerate(order):
        now = time.monotonic()
        if now >= deadline:
            break
        old = current[bid]
        others = {i: a for i, a in current.items() if i != bid}
        # A single pathological insertion must not monopolize the remaining
        # wall clock.  Dense large instances benefit more from touching many
        # blamed blocks than from exhausting every event time for one block.
        remaining_jobs = max(1, len(order) - k)
        slice_end = min(deadline, now + max(
            0.08, 1.8 * (deadline - now) / remaining_jobs
        ))
        replacement = _best_insertion(
            prob, geoms, bid, others, slice_end,
            diagonal=bool((phase + k) & 1),
            exact=exact,
        )
        if replacement is None:
            continue
        # Exact objective delta from the per-block separable terms plus an
        # O(bays) imbalance recomputation; equivalent to the previous full
        # _objective(trial) comparison but without the O(n) rescan per trial.
        b = blocks[bid]
        prefs = b["bay_preferences"]
        d_tardy = (max(0.0, replacement["exit_time"] - b["due_date"])
                   - max(0.0, old["exit_time"] - b["due_date"]))
        d_regret = prefs[old["bay_id"]] - prefs[replacement["bay_id"]]
        loads[old["bay_id"]] -= b["workload"]
        loads[replacement["bay_id"]] += b["workload"]
        imb_new = _imbalance(prob, loads)
        delta = (w1 * d_tardy + w3 * d_regret
                 + w2 * (imb_new - imb_current))
        if delta < -1e-7:
            others[bid] = replacement
            current = others
            imb_current = imb_new
            improved = True
        else:
            loads[old["bay_id"]] += b["workload"]
            loads[replacement["bay_id"]] -= b["workload"]
    return current, improved


def _ruin_recreate(prob, geoms, incumbent, deadline, rng, iteration,
                   exact=True, legacy=False, z2_heavy=False,
                   forced_method=None):
    n = len(incumbent)
    if n < 4:
        return incumbent
    blame = _blame_order(prob, incumbent)
    q = max(2, min(12, int(round(math.sqrt(n) * 0.45))))

    # legacy=True reproduces the proven v1 destroy/repair schedule exactly
    # (portfolio worker 0), so the portfolio can never search worse than the
    # previous submission; other workers explore the extended operator set.
    if forced_method is not None:
        method = int(forced_method)
    elif legacy:
        method = iteration % 3
    elif XBAY:
        method = iteration % (6 if z2_heavy else 5)
    else:
        method = iteration % 4
    if method == 0:
        removed = blame[:q]
    elif method == 1:
        # Time-window ruin coordinates several jobs competing around one date.
        center = rng.choice(list(incumbent.values()))["entry_time"]
        removed = sorted(
            incumbent,
            key=lambda i: abs(incumbent[i]["entry_time"] - center)
        )[:q]
    elif method == 2:
        # Bay-flush fragment enables cross-bay reassignment and repacking.
        bay = rng.randrange(len(prob["bays"]))
        candidates = [i for i, a in incumbent.items() if a["bay_id"] == bay]
        rng.shuffle(candidates)
        removed = candidates[:q]
        if len(removed) < 2:
            removed = rng.sample(list(incumbent), q)
    elif method == 3:
        # Peak-window flush: evict every block entering one bay around a
        # blamed block's entry date and let the repair re-time them jointly.
        # This is the coordinated re-timing move that single-block
        # reinsertion cannot express on congested instances.
        anchor_bid = blame[rng.randrange(max(1, min(8, len(blame))))] \
            if len(blame) > 1 else blame[0]
        anchor = incumbent[anchor_bid]
        bay = anchor["bay_id"]
        center = anchor["entry_time"]
        procs = sorted(int(prob["blocks"][i]["processing_time"])
                       for i in incumbent)
        half = max(2, procs[len(procs) // 2])
        window = [i for i, a in incumbent.items()
                  if a["bay_id"] == bay
                  and center - half <= a["entry_time"] <= center + half]
        window.sort(key=lambda i: abs(incumbent[i]["entry_time"] - center))
        removed = window[:48]
        if len(removed) < 3:
            removed = blame[:q]
    elif method == 4:
        # Preference repatriation: take the highest-blame exiles (blocks not
        # in their most-preferred bay) plus the occupiers of their preferred
        # bay around their release window, and let the repair renegotiate
        # the whole neighborhood with exact w1/w2/w3 deltas.
        exiles = [
            i for i in blame
            if incumbent[i]["bay_id"] != max(
                range(len(prob["bays"])),
                key=lambda j: prob["blocks"][i]["bay_preferences"][j])
        ][:max(3, q // 2)]
        if not exiles:
            removed = blame[:q]
        else:
            lead = prob["blocks"][exiles[0]]
            target = max(range(len(prob["bays"])),
                         key=lambda j: lead["bay_preferences"][j])
            r0 = int(lead["release_time"])
            r1 = r0 + int(lead["processing_time"]) * 2
            occupiers = sorted(
                (i for i, a in incumbent.items()
                 if a["bay_id"] == target and i not in exiles
                 and a["entry_time"] <= r1 and a["exit_time"] >= r0),
                key=lambda i: abs(incumbent[i]["entry_time"] - r0))
            removed = (exiles + occupiers)[:max(q, 16)]
    else:
        # Z2-balancing (w2-heavy regimes only): drain preference-indifferent
        # blocks from the most over-loaded bay (in u_j-scaled terms) so the
        # repair can rebalance workloads at exact marginal cost.
        bays = prob["bays"]
        areas = [float(b["width"] * b["height"]) for b in bays]
        avg = sum(areas) / len(areas)
        loads = [0.0] * len(bays)
        for i, a in incumbent.items():
            loads[a["bay_id"]] += prob["blocks"][i]["workload"]
        heavy = max(range(len(bays)), key=lambda j: (avg / areas[j]) * loads[j])
        pool = [i for i, a in incumbent.items() if a["bay_id"] == heavy]
        pool.sort(key=lambda i: (
            max(prob["blocks"][i]["bay_preferences"])
            - sorted(prob["blocks"][i]["bay_preferences"])[-2]
            if len(bays) > 1 else 0,
            -prob["blocks"][i]["workload"],
        ))
        removed = pool[:q]
        if len(removed) < 2:
            removed = blame[:q]

    partial = {i: a for i, a in incumbent.items() if i not in set(removed)}
    style = 0 if legacy else (iteration // 4) % 4
    bdata = prob["blocks"]
    if style == 0:
        removed.sort(key=lambda i: (
            bdata[i]["due_date"] - bdata[i]["processing_time"],
            bdata[i]["due_date"], i,
        ))
    elif style == 1:
        removed.sort(key=lambda i: (
            bdata[i]["due_date"] + rng.randint(-2, 2),
            bdata[i]["processing_time"], i,
        ))
    elif style == 2:
        removed.sort(key=lambda i: (
            bdata[i]["due_date"], bdata[i]["processing_time"], i,
        ))
    else:
        removed.sort(key=lambda i: (
            bdata[i]["release_time"], bdata[i]["due_date"], i,
        ))
    for k, bid in enumerate(removed):
        now = time.monotonic()
        if now >= deadline:
            return incumbent
        slice_end = min(deadline, now + max(
            0.10, 1.6 * (deadline - now) / max(1, len(removed) - k)
        ))
        a = _best_insertion(prob, geoms, bid, partial, slice_end,
                            diagonal=bool((iteration + k) & 1), exact=exact)
        if a is None:
            return incumbent
        partial[bid] = a
    return partial if _objective(prob, partial) < _objective(prob, incumbent) else incumbent


def _emit(assignments):
    buckets = {}
    for bid, a in assignments.items():
        entry = int(a["entry_time"])
        exit_t = int(a["exit_time"])
        bay = int(a["bay_id"])
        buckets.setdefault(exit_t, []).append({
            "type": "EXIT", "block_id": int(bid), "bay_id": bay,
        })
        buckets.setdefault(entry, []).append({
            "type": "ENTRY", "block_id": int(bid), "bay_id": bay,
            "x": int(a["x"]), "y": int(a["y"]),
            "orient_idx": int(a["orient_idx"]),
        })

    operations = {}
    for t in sorted(buckets):
        # The safety invariant makes within-type order irrelevant.  EXIT before
        # ENTRY is still mandatory and enables exact same-day space reuse.
        ops = sorted(buckets[t],
                     key=lambda op: (0 if op["type"] == "EXIT" else 1,
                                     op["bay_id"], op["block_id"]))
        operations[str(int(t))] = ops
    return {"operations": operations}


def _official_check(prob, assignments):
    try:
        from utils import check_feasibility
        sol = _emit(assignments)
        result = check_feasibility(prob, sol)
        return bool(result.get("feasible")), sol, result
    except Exception:
        return False, None, None


def _solve(prob_info, timelimit=60, variant=0, report=None, metrics=None):
    """Full anytime solve; returns (best_objective, best_solution_dict).

    ``variant`` diversifies the search (seed, construction-mode rotation) for
    portfolio workers.  ``report(obj, sol)`` is called on every checker-passed
    incumbent promotion so a parent process always holds the latest incumbent
    even if this worker is terminated at the deadline.  Passing a mutable
    ``metrics`` dict enables experiment-only LNS instrumentation; the public
    submission path leaves it as ``None`` and performs no reporting I/O.
    """
    global _RASTER_ACTIVE
    start = time.monotonic()
    limit = max(0.05, float(timelimit))
    reserve = max(0.20, min(4.0, 0.04 * limit))
    deadline = start + max(0.01, limit - reserve)
    variant_id = int(variant)
    problem_size = len(prob_info.get("blocks", []) or [])
    advanced_variant = _advanced_lns_enabled(
        problem_size, limit, variant_id
    )
    if metrics is not None:
        metrics["variant"] = variant_id
        metrics["advanced_lns"] = bool(advanced_variant)
        metrics["late_acceptance"] = bool(advanced_variant and variant_id == 1)

    try:
        _clear_geometry_caches()
        _RASTER_ACTIVE = False
        # Preprocessing (geometry build + serial fallback + its official
        # check) is a fixed cost that used to ignore the clock entirely: at
        # timelimit=0.05 with n=100 the call returned only after ~0.33 s.
        # Half of the usable budget is a generous ceiling -- on the supplied
        # instances the exact build needs ~0.3 s against a 28 s ceiling at
        # timelimit=60, so nothing here changes for a normal run.
        prep_deadline = start + max(0.01, 0.50 * (deadline - start))
        geoms = _precompute_geometry(prob_info, prep_deadline)
        if any(not gs for gs in geoms):
            raise ValueError("degenerate block geometry")
        forced_density = _peak_forced_density(prob_info, geoms)
        preference_ratio, raster_z2_ratio = _raster_objective_ratios(
            prob_info
        )
        raster_selected = _select_raster(
            prob_info, max(0.0, deadline - time.monotonic()), forced_density
        )
        _RASTER_ACTIVE = bool(
            raster_selected
            and _raster_worker_enabled(
                problem_size, variant_id, forced_density,
                preference_ratio, raster_z2_ratio,
            )
        )
        if metrics is not None:
            metrics["raster_selected"] = bool(raster_selected)
            metrics["raster_active"] = bool(_RASTER_ACTIVE)
            metrics["raster_forced_density"] = float(forced_density)
            metrics["raster_preference_ratio"] = float(preference_ratio)
            metrics["raster_z2_ratio"] = float(raster_z2_ratio)
            metrics["raster_estimated_pass_seconds"] = float(
                _estimated_raster_pass_seconds(prob_info)
            )

        fallback = _serial_fallback(prob_info, geoms, prep_deadline)
        if time.monotonic() < prep_deadline:
            ok, best_sol, best_result = _official_check(prob_info, fallback)
            if not ok:
                # This should only occur for a malformed instance; allowing the
                # outer fallback path to run is safer than returning a known
                # failure.
                raise ValueError("serial fallback rejected by checker")
            best_obj = float(best_result["objective"])
        else:
            # Budget already gone.  The serial fallback is feasible by
            # construction -- per bay the residences are serial and disjoint
            # (so no crane or collision interaction exists), every orientation
            # was pre-filtered by _fits for bay containment, and _emit lists
            # EXIT before ENTRY -- so emit it unverified rather than overrun
            # the limit inside the O(n^2) checker.
            best_sol = _emit(fallback)
            best_obj = _objective(prob_info, fallback)
        best = fallback

        def _notify():
            if report is not None:
                try:
                    report(best_obj, best_sol)
                except Exception:
                    pass

        _notify()

        # Deterministic seed: stable across Python hash randomization.
        name = str(prob_info.get("name", "instance"))
        n_blocks = len(prob_info["blocks"])
        seed = (sum((i + 1) * ord(c) for i, c in enumerate(name))
                + 1009 * len(prob_info["blocks"]) + 9176 * len(prob_info["bays"])
                + 7919 * variant_id)
        rng = random.Random(seed)

        # First obtain a fast rectangle-envelope schedule.  It is conservative
        # but finishes in short limits and is normally far stronger than the
        # serial safety floor.  Polygon-true passes then spend the larger budget.
        fast_fraction = 0.28 if n_blocks > 160 else 0.18
        fast_stop = min(deadline, start + max(0.8, fast_fraction * (deadline - start)))
        max_release = max((b["release_time"] for b in prob_info["blocks"]),
                          default=0)
        w1_now = float(prob_info.get("weights", {}).get("w1", 1.0))
        w2_now = float(prob_info.get("weights", {}).get("w2", 1.0))
        # Regime gate for the Z2-balancing destroy operator: enabled when a
        # full one-bay imbalance is worth >= ~5 tardy-days (p25/p36/p40-like),
        # or when tardiness is free (w1 == 0).
        _mean_load = (sum(b["workload"] for b in prob_info["blocks"])
                      / max(1, len(prob_info["bays"])))
        z2_heavy = w2_now * _mean_load > 5.0 * max(w1_now, 1e-9)
        if n_blocks > 160 and max_release > 60:
            fast_modes = (1, 0, 4, 3, 2, 4, 4)
        elif n_blocks > 160 and w1_now < 1000:
            fast_modes = (3, 0, 1, 4, 2, 4, 4)
        elif n_blocks > 160:
            fast_modes = (4, 0, 3, 1, 2, 4, 4)
        else:
            fast_modes = (0, 1, 2, 3, 4, 4, 4)
        if variant:
            r = int(variant) % len(fast_modes)
            fast_modes = fast_modes[r:] + fast_modes[:r]
        for fast_pass, fast_mode in enumerate(fast_modes):
            if time.monotonic() >= fast_stop:
                break
            fast_candidate = _construct(
                prob_info, geoms, fast_mode, seed + 3571 * fast_pass,
                fast_stop, exact=False
            )
            if fast_candidate is not None:
                value = _objective(prob_info, fast_candidate)
                if value + 1e-7 < best_obj:
                    ok, sol, result = _official_check(prob_info, fast_candidate)
                    if ok:
                        best, best_obj, best_sol = fast_candidate, value, sol
                        _notify()

        # Cheap exact-objective optimization inside the conservative rectangle
        # model.  This coordinates assignment and timing before expensive
        # polygon work, particularly valuable for n=200--300 instances.
        rect_improve_stop = (
            min(deadline, start + max(1.0, 0.28 * (deadline - start)))
            if n_blocks > 160 else time.monotonic()
        )
        rect_phase = 0
        while time.monotonic() < rect_improve_stop and rect_phase < 2:
            candidate, _ = _single_reinsert_sweep(
                prob_info, geoms, best, rect_improve_stop, rect_phase,
                exact=False,
            )
            value = _objective(prob_info, candidate)
            if value + 1e-7 < best_obj:
                ok, sol, result = _official_check(prob_info, candidate)
                if ok:
                    best, best_obj, best_sol = candidate, value, sol
                    _notify()
            rect_phase += 1

        # Allocate most of the remaining construction budget to the strong
        # polygon decoder.  An unfinished pass is harmless because the fast
        # incumbent above has already been checker-gated.
        # Full polygon reconstruction has superlinear cost.  Up to 160 blocks
        # it is the strongest use of time; above that, exact-delta reinsertion
        # from several completed rectangle schedules has much better coverage.
        construct_stop = (
            start + 0.99 * max(0.0, deadline - start)
            if n_blocks <= 160 or _RASTER_ACTIVE
            else time.monotonic()
        )
        modes = [0, 1, 2, 3, 4]
        if variant:
            r = int(variant) % len(modes)
            modes = modes[r:] + modes[:r]
        previous_construct_seconds = None
        for pass_no, mode in enumerate(modes):
            now = time.monotonic()
            if now >= construct_stop:
                break
            if (previous_construct_seconds is not None
                    and construct_stop - now < 1.12 * previous_construct_seconds):
                break
            pass_start = now
            pass_cap = min(deadline, construct_stop)
            if (
                _RASTER_ACTIVE
                and n_blocks > 160
                and previous_construct_seconds is None
            ):
                pass_cap = min(
                    pass_cap,
                    now + RASTER_FIRST_PASS_FRACTION * (
                        construct_stop - now
                    ),
                )
            candidate = _construct(
                prob_info, geoms, mode, 1 + pass_no,
                pass_cap, exact=True,
            )
            if candidate is None:
                break
            previous_construct_seconds = time.monotonic() - pass_start
            value = _objective(prob_info, candidate)
            if value + 1e-7 < best_obj:
                ok, sol, result = _official_check(prob_info, candidate)
                if ok:
                    best, best_obj, best_sol = candidate, value, sol
                    _notify()

        # W2 is for tardiness-bearing schedules.  Zero-tardy loose instances
        # use the separately gateable W3 polish, while worker 0 always remains
        # on the hardened legacy path.
        has_tardiness = any(
            a["exit_time"] > prob_info["blocks"][bid]["due_date"]
            for bid, a in best.items()
        )
        advanced_variant = bool(advanced_variant and has_tardiness)
        if metrics is not None:
            metrics["advanced_lns"] = bool(advanced_variant)
            metrics["late_acceptance"] = bool(
                advanced_variant and variant_id in (1, 2)
            )

        phase = 0
        if advanced_variant:
            # Workers 1/2 use late acceptance; worker 3 is strict.  Worker 0
            # remains the legacy safety anchor.
            search = best
            search_obj = best_obj
            lns_start_obj = best_obj
            late_accept = variant_id in (1, 2)
            history_len = _lahc_history_length(n_blocks)
            excursion = max(1.0, 0.0125 * max(1.0, best_obj))
            history = [best_obj + excursion] * history_len
            without_best = 0
            excursion_active = False

            if metrics is not None:
                metrics["lns_start_objective"] = float(lns_start_obj)
                metrics["lns_history_length"] = int(history_len)

            while time.monotonic() < deadline:
                before_best = best_obj
                now = time.monotonic()

                # Preserve the strongest part of the existing Kestrel search
                # before spending time on the experimental neighborhood.  The
                # first exact sweep receives a substantial warm-start slice;
                # later sweeps are shorter so regret repair still gets trials.
                sweep_fraction = 0.55 if phase == 0 else 0.18
                sweep_cap = 12.0 if phase == 0 else 3.0
                sweep_end = min(
                    deadline,
                    now + max(
                        0.20,
                        min(sweep_cap, sweep_fraction * (deadline - now)),
                    ),
                )
                polished, changed = _single_reinsert_sweep(
                    prob_info, geoms, search, sweep_end, phase, exact=True,
                )
                polished_obj = _objective(prob_info, polished)
                if polished_obj + 1e-7 < search_obj:
                    search, search_obj = polished, polished_obj
                    _metric_add(metrics, "lns_polish_accepted")
                if polished_obj + 1e-7 < best_obj:
                    ok, sol, result = _official_check(prob_info, polished)
                    if ok:
                        gain = best_obj - polished_obj
                        best, best_obj, best_sol = polished, polished_obj, sol
                        search, search_obj = polished, polished_obj
                        _metric_add(metrics, "lns_best_improvements")
                        _metric_add(metrics, "lns_best_gain", gain)
                        _metric_add(metrics, "lns_polish_best_gain", gain)
                        if excursion_active:
                            _metric_add(
                                metrics, "lns_escape_best_improvements"
                            )
                            _metric_add(
                                metrics, "lns_escape_best_gain", gain
                            )
                            excursion_active = False
                        _notify()
                    else:
                        # A failed checker verdict can only come from a defect
                        # in an experimental path.  Drop all descendants of it.
                        search, search_obj = best, best_obj
                        _metric_add(metrics, "lns_checker_rejections")

                now = time.monotonic()
                if now >= deadline:
                    break
                # Retain the established small destroy/recreate operator as a
                # warm-start/control move.  The advanced branch is additive,
                # not a wholesale replacement of a productive search path.
                if phase % 2 == 0:
                    repair_end = min(
                        deadline,
                        now + max(0.25, min(
                            3.0, 0.12 * (deadline - now)
                        )),
                    )
                    repaired = _ruin_recreate(
                        prob_info, geoms, search, repair_end, rng, phase,
                        exact=True, legacy=False, z2_heavy=z2_heavy,
                    )
                    repaired_obj = _objective(prob_info, repaired)
                    if repaired_obj + 1e-7 < search_obj:
                        search, search_obj = repaired, repaired_obj
                        _metric_add(metrics, "lns_legacy_repair_accepted")
                    if repaired_obj + 1e-7 < best_obj:
                        ok, sol, result = _official_check(
                            prob_info, repaired
                        )
                        if ok:
                            gain = best_obj - repaired_obj
                            best, best_obj, best_sol = (
                                repaired, repaired_obj, sol
                            )
                            search, search_obj = best, best_obj
                            _metric_add(metrics, "lns_best_improvements")
                            _metric_add(metrics, "lns_best_gain", gain)
                            _metric_add(
                                metrics, "lns_legacy_best_gain", gain
                            )
                            if excursion_active:
                                _metric_add(
                                    metrics, "lns_escape_best_improvements"
                                )
                                _metric_add(
                                    metrics, "lns_escape_best_gain", gain
                                )
                                excursion_active = False
                            _notify()
                        else:
                            search, search_obj = best, best_obj
                            _metric_add(metrics, "lns_checker_rejections")

                now = time.monotonic()
                if now >= deadline:
                    break
                remaining = deadline - now
                if remaining < 1.50:
                    break
                # One completed repair is more informative and useful than
                # several time-sliced attempts that strand their last blocks.
                move_budget = min(10.0, max(1.20, 0.45 * remaining))
                move_end = min(deadline, now + move_budget)
                max_removed = min(
                    30, max(18, int(10 + 1.7 * move_budget))
                )
                candidate = _advanced_lns_move(
                    prob_info, geoms, search, move_end, rng, phase,
                    max_removed=max_removed, exact=True, metrics=metrics,
                )

                slot = phase % history_len
                threshold = history[slot]
                if candidate is not None:
                    value = _objective(prob_info, candidate)
                    delta_from_search = value - search_obj
                    _metric_add(
                        metrics, "lns_candidate_delta_sum", delta_from_search
                    )
                    _metric_extreme(
                        metrics, "lns_candidate_best_delta", delta_from_search
                    )
                    _metric_extreme(
                        metrics, "lns_candidate_worst_delta",
                        delta_from_search, choose_min=False,
                    )
                    # Equal-objective repairs can materially change geometry
                    # and open a later improving move.  Workers 1/2 may also
                    # accept a genuinely worse state through the history
                    # threshold; worker 3 remains strict.
                    accepted = _accept_lns_candidate(
                        value, search_obj, best_obj, threshold, late_accept
                    )

                    checker_ok = True
                    promoted = False
                    if accepted and value + 1e-7 < best_obj:
                        ok, sol, result = _official_check(prob_info, candidate)
                        checker_ok = ok
                        if ok:
                            gain = best_obj - value
                            best, best_obj, best_sol = candidate, value, sol
                            _metric_add(metrics, "lns_best_improvements")
                            _metric_add(metrics, "lns_best_gain", gain)
                            _metric_add(metrics, "lns_move_best_gain", gain)
                            _notify()
                            promoted = True
                        else:
                            _metric_add(metrics, "lns_checker_rejections")

                    if accepted and checker_ok:
                        if value > search_obj + 1e-7:
                            _metric_add(metrics, "lns_worsening_accepted")
                            _metric_add(
                                metrics, "lns_worsening_delta_sum",
                                value - search_obj,
                            )
                            _metric_extreme(
                                metrics, "lns_worsening_max_delta",
                                value - search_obj, choose_min=False,
                            )
                            excursion_active = True
                        elif value + 1e-7 < search_obj:
                            _metric_add(metrics, "lns_improving_accepted")
                        else:
                            _metric_add(metrics, "lns_equal_accepted")
                        search, search_obj = candidate, value
                        _metric_add(metrics, "lns_moves_accepted")
                        if promoted:
                            if excursion_active:
                                _metric_add(
                                    metrics,
                                    "lns_escape_best_improvements",
                                )
                                _metric_add(
                                    metrics, "lns_escape_best_gain", gain
                                )
                                excursion_active = False
                            search, search_obj = best, best_obj
                    else:
                        _metric_add(metrics, "lns_moves_rejected")

                history[slot] = search_obj
                without_best = (
                    without_best + 1
                    if best_obj >= before_best - 1e-7 else 0
                )
                phase += 1

                # Do not let an unproductive excursion monopolize a worker.
                # Restart from the verified best but warm the history above it
                # so worker 1 can cross another shallow objective barrier.
                if without_best >= history_len:
                    search, search_obj = best, best_obj
                    excursion = max(1.0, 0.0125 * max(1.0, best_obj))
                    history = [best_obj + excursion] * history_len
                    without_best = 0
                    excursion_active = False
                    _metric_add(metrics, "lns_restarts")

            if metrics is not None:
                metrics["lns_iterations"] = int(phase)
                metrics["lns_final_objective"] = float(best_obj)
                seconds = float(metrics.get("lns_seconds", 0.0))
                metrics["lns_improvement_per_second"] = (
                    float(metrics.get("lns_move_best_gain", 0.0)) / seconds
                    if seconds > 0.0 else 0.0
                )
                completed = float(metrics.get("lns_moves_completed", 0.0))
                metrics["lns_acceptance_rate"] = (
                    float(metrics.get("lns_moves_accepted", 0.0)) / completed
                    if completed > 0.0 else 0.0
                )
                metrics["lns_candidate_mean_delta"] = (
                    float(metrics.get("lns_candidate_delta_sum", 0.0))
                    / completed
                    if completed > 0.0 else 0.0
                )
        else:
            # Proven Kestrel path, retained for workers 0, 2, and 3.  Worker 2
            # receives only the optional, default-off CP-SAT repair below.
            stagnant = 0
            if metrics is not None:
                metrics["legacy_start_objective"] = float(best_obj)
            while time.monotonic() < deadline:
                before = best_obj
                if metrics is not None:
                    move_started = time.monotonic()
                candidate, changed = _single_reinsert_sweep(
                    prob_info, geoms, best, deadline, phase, exact=True
                )
                if metrics is not None:
                    _metric_add(
                        metrics, "legacy_search_seconds",
                        time.monotonic() - move_started,
                    )
                    _metric_add(metrics, "legacy_moves_proposed")
                value = _objective(prob_info, candidate)
                if value + 1e-7 < best_obj:
                    ok, sol, result = _official_check(prob_info, candidate)
                    if ok:
                        if metrics is not None:
                            _metric_add(
                                metrics, "legacy_best_gain", best_obj - value
                            )
                        best, best_obj, best_sol = candidate, value, sol
                        if metrics is not None:
                            _metric_add(metrics, "legacy_moves_accepted")
                        _notify()

                if time.monotonic() >= deadline:
                    break
                if metrics is not None:
                    move_started = time.monotonic()
                ruined = _ruin_recreate(
                    prob_info, geoms, best, deadline, rng, phase, exact=True,
                    legacy=(variant_id == 0), z2_heavy=z2_heavy,
                )
                if metrics is not None:
                    _metric_add(
                        metrics, "legacy_search_seconds",
                        time.monotonic() - move_started,
                    )
                    _metric_add(metrics, "legacy_moves_proposed")
                value = _objective(prob_info, ruined)
                if value + 1e-7 < best_obj:
                    ok, sol, result = _official_check(prob_info, ruined)
                    if ok:
                        if metrics is not None:
                            _metric_add(
                                metrics, "legacy_best_gain", best_obj - value
                            )
                        best, best_obj, best_sol = ruined, value, sol
                        if metrics is not None:
                            _metric_add(metrics, "legacy_moves_accepted")
                        _notify()

                now = time.monotonic()
                if (CP_SAT_REPAIR and variant_id == 2
                        and phase % 3 == 0 and now < deadline):
                    full_remaining = deadline - now
                    oracle_solve_seconds = min(
                        2.0, max(0.50, 0.02 * full_remaining)
                    )
                    oracle_end = min(
                        deadline,
                        now + max(1.5, min(
                            8.0,
                            oracle_solve_seconds + 0.08 * full_remaining,
                        )),
                    )
                    repaired = _oracle_repair(
                        prob_info, geoms, best, oracle_end,
                        seed=seed + 65537 * phase, metrics=metrics,
                        solve_time_limit=oracle_solve_seconds,
                    )
                    if repaired is not None:
                        repaired_obj = _objective(prob_info, repaired)
                        ok, sol, result = _official_check(
                            prob_info, repaired
                        )
                        if ok:
                            _metric_add(metrics, "oracle_checker_feasible")
                            if repaired_obj + 1e-7 < best_obj:
                                gain = best_obj - repaired_obj
                                best, best_obj, best_sol = (
                                    repaired, repaired_obj, sol
                                )
                                _metric_add(
                                    metrics, "oracle_moves_accepted"
                                )
                                _metric_add(
                                    metrics, "oracle_best_improvements"
                                )
                                _metric_add(
                                    metrics, "oracle_best_gain", gain
                                )
                                _notify()
                        else:
                            _metric_add(
                                metrics, "oracle_checker_rejections"
                            )

                stagnant = stagnant + 1 if best_obj >= before - 1e-7 else 0
                phase += 1
                if stagnant >= 3 and time.monotonic() < deadline:
                    loose_improved = False
                    zero_tardy = not any(
                        a["exit_time"] > prob_info["blocks"][bid]["due_date"]
                        for bid, a in best.items()
                    )
                    if (
                        LOOSE_POLISH
                        and variant_id in (1, 2, 3)
                        and zero_tardy
                    ):
                        now = time.monotonic()
                        polish_end = min(
                            deadline,
                            now + max(
                                0.50,
                                min(5.0, 0.30 * (deadline - now)),
                            ),
                        )
                        polished = _ruin_recreate(
                            prob_info,
                            geoms,
                            best,
                            polish_end,
                            rng,
                            phase,
                            exact=True,
                            legacy=False,
                            z2_heavy=True,
                            forced_method=4 + (phase & 1),
                        )
                        still_zero = not any(
                            a["exit_time"]
                            > prob_info["blocks"][bid]["due_date"]
                            for bid, a in polished.items()
                        )
                        value = _objective(prob_info, polished)
                        if still_zero and value + 1e-7 < best_obj:
                            ok, sol, result = _official_check(
                                prob_info, polished
                            )
                            if ok:
                                best, best_obj, best_sol = (
                                    polished, value, sol
                                )
                                loose_improved = True
                                _metric_add(
                                    metrics, "loose_polish_improvements"
                                )
                                _notify()

                    if not loose_improved and time.monotonic() < deadline:
                        # Retain the randomized EDD kick when the specialized
                        # zero-tardy operator has no gain.
                        if metrics is not None:
                            move_started = time.monotonic()
                        candidate = _construct(
                            prob_info, geoms, 4,
                            seed + 104729 * phase, deadline, exact=True,
                        )
                        if metrics is not None:
                            _metric_add(
                                metrics, "legacy_search_seconds",
                                time.monotonic() - move_started,
                            )
                            _metric_add(metrics, "legacy_moves_proposed")
                        if candidate is not None:
                            value = _objective(prob_info, candidate)
                            if value + 1e-7 < best_obj:
                                ok, sol, result = _official_check(
                                    prob_info, candidate
                                )
                                if ok:
                                    if metrics is not None:
                                        _metric_add(
                                            metrics, "legacy_best_gain",
                                            best_obj - value,
                                        )
                                    best, best_obj, best_sol = (
                                        candidate, value, sol
                                    )
                                    if metrics is not None:
                                        _metric_add(
                                            metrics, "legacy_moves_accepted"
                                        )
                                    _notify()
                    stagnant = 0
            if metrics is not None:
                metrics["legacy_final_objective"] = float(best_obj)
                seconds = float(metrics.get("legacy_search_seconds", 0.0))
                moves = float(metrics.get("legacy_moves_proposed", 0.0))
                metrics["legacy_improvement_per_second"] = (
                    float(metrics.get("legacy_best_gain", 0.0)) / seconds
                    if seconds > 0.0 else 0.0
                )
                metrics["legacy_acceptance_rate"] = (
                    float(metrics.get("legacy_moves_accepted", 0.0)) / moves
                    if moves > 0.0 else 0.0
                )

        if metrics is not None:
            metrics["elapsed_seconds"] = time.monotonic() - start
            metrics["final_objective"] = float(best_obj)
        return best_obj, best_sol
    except Exception:
        # Last-resort construction without Shapely-dependent search.  The main
        # path normally creates and validates the fallback before any risky work.
        try:
            if "best_sol" in locals() and best_sol is not None:
                obj = best_obj if "best_obj" in locals() else float("inf")
                return obj, best_sol
            geoms = _precompute_geometry(prob_info, start + 0.75 * limit)
            return float("inf"), _emit(
                _serial_fallback(prob_info, geoms, start + 0.85 * limit))
        except Exception:
            return float("inf"), {"operations": {}}


def _portfolio_worker(prob_info, budget, variant, queue):
    """Worker body for the multi-process portfolio.

    Pushes every checker-passed incumbent promotion (throttled) so the parent
    holds a current solution even if this process is terminated at deadline.
    """
    try:
        state = {"t": 0.0}

        def report(obj, sol):
            now = time.monotonic()
            if now - state["t"] >= 0.5:
                state["t"] = now
                try:
                    queue.put_nowait((float(obj), int(variant), sol))
                except Exception:
                    pass

        obj, sol = _solve(prob_info, budget, variant=variant, report=report)
        if sol is not None:
            queue.put((float(obj), int(variant), sol))
    except Exception:
        pass


def algorithm(prob_info, timelimit=60):
    """Required OGC entry point.

    Runs a 4-process best-of portfolio of diversified anytime solvers (the
    evaluation budget is 4 CPU cores); falls back to the proven single-process
    path on short limits or if multiprocessing is unavailable.
    """
    start = time.monotonic()
    limit = max(0.05, float(timelimit))
    n_blocks = len(prob_info.get("blocks", []) or [])

    if limit >= 20.0 and n_blocks >= 8:
        try:
            import multiprocessing as _mp
            ctx = _mp.get_context()
            queue = ctx.Queue()
            collect_margin = max(1.2, 0.03 * limit)
            child_budget = max(5.0, limit - collect_margin
                               - (time.monotonic() - start) - 0.5)
            workers = []
            for v in range(4):
                p = ctx.Process(target=_portfolio_worker,
                                args=(prob_info, child_budget, v, queue),
                                daemon=True)
                p.start()
                workers.append(p)

            hard_end = start + limit - max(0.8, 0.02 * limit)
            best = None
            while time.monotonic() < hard_end:
                alive = any(p.is_alive() for p in workers)
                try:
                    wait = min(0.5, max(0.05, hard_end - time.monotonic()))
                    item = queue.get(timeout=wait)
                except Exception:
                    if not alive:
                        break
                    continue
                if best is None or item[0] < best[0]:
                    best = item
            # Drain BEFORE terminating: while children are alive (or exited
            # normally) the queue holds no torn frames.  Draining after
            # terminate() risks a partial message whose _recv_bytes() blocks
            # forever (uncatchable hang -> wall-clock overshoot -> -1), so we
            # never read the queue again once terminate() has been issued.
            drain_end = time.monotonic() + 0.4
            while time.monotonic() < drain_end:
                try:
                    item = queue.get(timeout=0.05)
                except Exception:
                    break
                if best is None or item[0] < best[0]:
                    best = item
            for p in workers:
                if p.is_alive():
                    p.terminate()
            for p in workers:
                p.join(0.05)
            if best is not None and best[2] and best[2].get("operations"):
                return best[2]
        except Exception:
            pass

    remaining = max(0.05, limit - (time.monotonic() - start))
    _, sol = _solve(prob_info, remaining, variant=0)
    return sol if sol is not None else {"operations": {}}
