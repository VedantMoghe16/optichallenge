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
    pts = [(float(x), float(y)) for layer in raw_layers for x, y in layer]
    if raw_layers and raw_layers[0]:
        ref_x, ref_y = float(raw_layers[0][0][0]), float(raw_layers[0][0][1])
    elif pts:
        ref_x, ref_y = pts[0]
    else:
        ref_x = ref_y = 0.0
    rel = [(px - ref_x, py - ref_y) for px, py in pts] or [(0.0, 0.0)]
    x0 = min(p[0] for p in rel)
    y0 = min(p[1] for p in rel)
    x1 = max(p[0] for p in rel)
    y1 = max(p[1] for p in rel)
    if x1 - x0 < DEGEN_MIN_SIDE:
        x1 = x0 + DEGEN_MIN_SIDE
    if y1 - y0 < DEGEN_MIN_SIDE:
        y1 = y0 + DEGEN_MIN_SIDE
    poly = Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    bbox = (x0, y0, x1, y1)
    n = max(1, len(raw_layers))
    return Orient(oi, poly, bbox, float(poly.area),
                  layers=tuple([poly] * n),
                  layer_bboxes=tuple([bbox] * n))


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
                   exact=True, legacy=False, z2_heavy=False):
    n = len(incumbent)
    if n < 4:
        return incumbent
    blame = _blame_order(prob, incumbent)
    q = max(2, min(12, int(round(math.sqrt(n) * 0.45))))

    # legacy=True reproduces the proven v1 destroy/repair schedule exactly
    # (portfolio worker 0), so the portfolio can never search worse than the
    # previous submission; other workers explore the extended operator set.
    if legacy:
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


def _solve(prob_info, timelimit=60, variant=0, report=None):
    """Full anytime solve; returns (best_objective, best_solution_dict).

    ``variant`` diversifies the search (seed, construction-mode rotation) for
    portfolio workers.  ``report(obj, sol)`` is called on every checker-passed
    incumbent promotion so a parent process always holds the latest incumbent
    even if this worker is terminated at the deadline.
    """
    start = time.monotonic()
    limit = max(0.05, float(timelimit))
    reserve = max(0.20, min(4.0, 0.04 * limit))
    deadline = start + max(0.01, limit - reserve)

    try:
        _MOVE_CACHE.clear()
        _PAIR_CACHE.clear()
        _ORIENT_CACHE.clear()
        _LT_STATIC.clear()
        _LT_CRANE.clear()
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
                + 7919 * int(variant))
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
            if n_blocks <= 160 else time.monotonic()
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
            candidate = _construct(
                prob_info, geoms, mode, 1 + pass_no,
                min(deadline, construct_stop), exact=True,
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

        phase = 0
        stagnant = 0
        while time.monotonic() < deadline:
            before = best_obj
            candidate, changed = _single_reinsert_sweep(
                prob_info, geoms, best, deadline, phase, exact=True
            )
            value = _objective(prob_info, candidate)
            if value + 1e-7 < best_obj:
                ok, sol, result = _official_check(prob_info, candidate)
                if ok:
                    best, best_obj, best_sol = candidate, value, sol
                    _notify()

            if time.monotonic() >= deadline:
                break
            ruined = _ruin_recreate(
                prob_info, geoms, best, deadline, rng, phase, exact=True,
                legacy=(int(variant) == 0), z2_heavy=z2_heavy,
            )
            value = _objective(prob_info, ruined)
            if value + 1e-7 < best_obj:
                ok, sol, result = _official_check(prob_info, ruined)
                if ok:
                    best, best_obj, best_sol = ruined, value, sol
                    _notify()

            stagnant = stagnant + 1 if best_obj >= before - 1e-7 else 0
            phase += 1
            if stagnant >= 3 and time.monotonic() < deadline:
                # A randomized EDD reconstruction is a large neighborhood and
                # often escapes a locally rigid spatial layout.
                candidate = _construct(
                    prob_info, geoms, 4, seed + 104729 * phase, deadline,
                    exact=True,
                )
                if candidate is not None:
                    value = _objective(prob_info, candidate)
                    if value + 1e-7 < best_obj:
                        ok, sol, result = _official_check(prob_info, candidate)
                        if ok:
                            best, best_obj, best_sol = candidate, value, sol
                            _notify()
                stagnant = 0

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
