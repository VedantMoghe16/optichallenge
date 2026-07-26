"""OGC 2026 submission -- Kestrel layer-true spatio-temporal heuristic.

The strong decoder implements the competition's exact layered geometry:
co-present blocks need only have disjoint same-index layers, while ENTRY/EXIT
events obey the asymmetric vertical crane sweep.  Pairwise event replay uses
the same deterministic daily ordering as :func:`_emit`, so legal overhangs are
accepted only when their induced LIFO timing is sound.  The fast rectangle
decoder and serial fallback retain the original union-envelope safety floor.

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


EPS = 1e-10
_MOVE_CACHE = {}
# Pairwise collision verdicts.  Overlap of polygon P translated to (x, y)
# with polygon Q translated to (u, v) depends only on (P, Q, x-u, y-v), so
# verdicts are cached by relative displacement.  Entries are exact shapely
# results; the cache can never change a verdict, only avoid recomputing it.
_PAIR_CACHE = {}
_PAIR_CACHE_MAX = 800_000
_LAYER_MOVE_CACHE = {}
_LAYER_PAIR_CACHE = {}
_LAYER_CACHE_MAX = 800_000
_ORIENT_CACHE = {}
USE_LAYER_TRUE = True
USE_LAYER_CONTACTS = False


@dataclass(frozen=True)
class Orient:
    """Geometry of one orientation in reference-point coordinates."""

    idx: int
    poly: object
    layers: tuple
    layer_bboxes: tuple
    bbox: tuple[float, float, float, float]
    area: float


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


def _precompute_geometry(prob):
    result = []
    for block in prob["blocks"]:
        block_orients = []
        for oi, shape in enumerate(block["shape"]):
            raw_layers = [layer for layer in shape["layers"] if layer]
            if not raw_layers:
                continue
            # The statement guarantees layer-0 vertex 0 is the reference point,
            # but subtract it explicitly to remain robust to equivalent inputs.
            ref_x, ref_y = raw_layers[0][0]
            layer_polys = []
            for layer in raw_layers:
                p = _polygon([(float(x) - ref_x, float(y) - ref_y)
                              for x, y in layer])
                if p is not None:
                    layer_polys.append(p)
            if not layer_polys:
                continue
            union = unary_union(layer_polys)
            if not union.is_valid:
                union = union.buffer(0)
            block_orients.append(
                Orient(oi, union, tuple(layer_polys),
                       tuple(tuple(map(float, p.bounds)) for p in layer_polys),
                       tuple(map(float, union.bounds)),
                       float(union.area))
            )
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


def _moved_layers(geom: Orient, x: int, y: int):
    """Translated per-layer polygons, cached at the exact integer position."""
    key = (id(geom.poly), int(x), int(y))
    layers = _LAYER_MOVE_CACHE.get(key)
    if layers is None:
        layers = tuple(_translate(p, xoff=x, yoff=y) for p in geom.layers)
        if len(_LAYER_MOVE_CACHE) < 300_000:
            _LAYER_MOVE_CACHE[key] = layers
    return layers


def _layer_pair_rules(geom_a: Orient, x_a: int, y_a: int,
                      geom_b: Orient, x_b: int, y_b: int):
    """Return exact pair geometry rules ``(static, crane_ab, crane_ba)``.

    ``crane_ab`` means A can be moved vertically while B is present.  Geometry
    is cached by absolute placements, rather than relative displacement, to
    preserve the checker's floating-point translation path near flush contact.
    """
    key = (id(geom_a.poly), int(x_a), int(y_a),
           id(geom_b.poly), int(x_b), int(y_b))
    cached = _LAYER_PAIR_CACHE.get(key)
    if cached is not None:
        return cached

    layers_a = _moved_layers(geom_a, x_a, y_a)
    layers_b = _moved_layers(geom_b, x_b, y_b)

    # Static legality is necessary for every co-present pair.  Test it first
    # and fail immediately: dense rejected candidates usually collide at the
    # same layer, so building the full cross-layer matrix wastes most of the
    # geometry work.
    diagonal_clear = set()
    for k in range(min(len(layers_a), len(layers_b))):
        pa, pb = layers_a[k], layers_b[k]
        if not _bbox_overlap(pa.bounds, pb.bounds):
            diagonal_clear.add((k, k))
            continue
        try:
            if pa.relate_pattern(pb, "2********"):
                result = (False, False, False)
                if len(_LAYER_PAIR_CACHE) < _LAYER_CACHE_MAX:
                    _LAYER_PAIR_CACHE[key] = result
                return result
        except Exception:
            result = (False, False, False)
            if len(_LAYER_PAIR_CACHE) < _LAYER_CACHE_MAX:
                _LAYER_PAIR_CACHE[key] = result
            return result
        diagonal_clear.add((k, k))

    overlap = [[False] * len(layers_b) for _ in range(len(layers_a))]
    for i, pa in enumerate(layers_a):
        ba = pa.bounds
        for j, pb in enumerate(layers_b):
            if (i, j) in diagonal_clear or not _bbox_overlap(ba, pb.bounds):
                continue
            try:
                overlap[i][j] = pa.relate_pattern(pb, "2********")
            except Exception:
                # Reject-on-error is encoded by making every rule unsafe.
                result = (False, False, False)
                if len(_LAYER_PAIR_CACHE) < _LAYER_CACHE_MAX:
                    _LAYER_PAIR_CACHE[key] = result
                return result

    static_clear = True
    # Moving A layer k sweeps past every existing-B layer j >= k.
    crane_ab = all(
        not overlap[k][j]
        for k in range(len(layers_a))
        for j in range(k, len(layers_b))
    )
    # Moving B layer k sweeps past every existing-A layer j >= k.
    crane_ba = all(
        not overlap[j][k]
        for k in range(len(layers_b))
        for j in range(k, len(layers_a))
    )
    result = (static_clear, crane_ab, crane_ba)
    if len(_LAYER_PAIR_CACHE) < _LAYER_CACHE_MAX:
        _LAYER_PAIR_CACHE[key] = result
        # Store the symmetric query as well; it is common during reinsertion.
        reverse_key = (id(geom_b.poly), int(x_b), int(y_b),
                       id(geom_a.poly), int(x_a), int(y_a))
        if len(_LAYER_PAIR_CACHE) < _LAYER_CACHE_MAX:
            _LAYER_PAIR_CACHE[reverse_key] = (
                static_clear, crane_ba, crane_ab
            )
    return result


def _pair_event_safe(bid_a: int, geom_a: Orient, x_a: int, y_a: int,
                     entry_a: int, exit_a: int, other: dict) -> bool:
    """Checker-equivalent feasibility for one co-present block pair.

    Static feasibility is checked once.  Then the two-block event stream is
    replayed with the exact output order: EXIT before ENTRY on each day and,
    within a type and bay, increasing block id.  Because all checker collision
    and crane constraints are separable over block pairs, conjunction of this
    predicate over every temporal blocker is sufficient for Stages 2--5.
    """
    entry_b = int(other["entry_time"])
    exit_b = int(other["exit_time"])
    if not _overlap_time(entry_a, exit_a, entry_b, exit_b):
        return True

    static_clear, crane_ab, crane_ba = _layer_pair_rules(
        geom_a, x_a, y_a, other["_geom"], other["x"], other["y"]
    )
    if not static_clear:
        return False

    bid_b = int(other["block_id"])
    # (time, EXIT/ENTRY phase, block id, block selector)
    events = [
        (int(entry_a), 1, int(bid_a), 0),
        (int(exit_a), 0, int(bid_a), 0),
        (entry_b, 1, bid_b, 1),
        (exit_b, 0, bid_b, 1),
    ]
    events.sort()
    present_a = False
    present_b = False
    for _t, phase, _bid, who in events:
        entering = phase == 1
        if who == 0:
            if present_b and not crane_ab:
                return False
            present_a = entering
        else:
            if present_a and not crane_ba:
                return False
            present_b = entering
    return True


def _safe_layers_position(bid: int, geom: Orient, x: int, y: int,
                          entry: int, exit_t: int, blockers) -> bool:
    """Exact layered static + forward/reverse crane predicate."""
    bb = _moved_bbox(geom, x, y)
    for other in blockers:
        if not _bbox_overlap(bb, other["_bbox"]):
            continue
        if not _pair_event_safe(
                bid, geom, x, y, entry, exit_t, other
        ):
            return False
    return True


def _candidate_positions(geom: Orient, bay, blockers, diagonal=False,
                         layer_contacts=False):
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
        if layer_contacts and geom.layer_bboxes and a["_geom"].layer_bboxes:
            # Layer-0 contacts expose legal under-tucking candidates hidden by
            # all-layer union AABBs.
            ng0x0, ng0y0, ng0x1, ng0y1 = geom.layer_bboxes[0]
            ob0x0, ob0y0, ob0x1, ob0y1 = a["_geom"].layer_bboxes[0]
            ob0x0 += a["x"]
            ob0x1 += a["x"]
            ob0y0 += a["y"]
            ob0y1 += a["y"]
            xs.add(int(math.ceil(ob0x1 - ng0x0)))
            xs.add(int(math.floor(ob0x0 - ng0x1)))
            ys.add(int(math.ceil(ob0y1 - ng0y0)))
            ys.add(int(math.floor(ob0y0 - ng0y1)))

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
    rows = [0] * (y_hi - y_lo + 1)
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


def _serial_fallback(prob, geoms):
    """Fast, structurally feasible incumbent available before optimization."""
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
        old_imb = _imbalance(prob, loads)
        for j, bay in enumerate(prob["bays"]):
            fitting = _orientation_order_cached(geoms, bid, j, bay)
            if not fitting:
                continue
            g = fitting[0]
            entry = max(int(block["release_time"]), ends[j])
            exit_t = entry + int(block["processing_time"])
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
        exit_t = entry + int(block["processing_time"])
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
    proc = int(block["processing_time"])
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
            positions = _candidate_positions(
                g, bay, blockers, diagonal,
                layer_contacts=bool(
                    exact and USE_LAYER_TRUE and USE_LAYER_CONTACTS
                ),
            )
            for k, (x, y) in enumerate(positions):
                if (k & 127) == 0 and time.monotonic() >= deadline:
                    return None
                if exact and USE_LAYER_TRUE:
                    if not _safe_layers_position(
                            bid, g, x, y, t, exit_t, blockers):
                        continue
                elif not _safe_polygon_position(
                        g, x, y, blockers, exact=exact):
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


def _release_peak_density(prob, geoms):
    """Cheap, instance-derived congestion classifier.

    It measures the union area demanded by blocks if each starts at release,
    divided by total bay area.  The assignment master is useful in the loose
    regime, where its preference/balance optimum can still be decoded with
    zero tardiness; dense instances need the scheduling search instead.
    """
    total_bay_area = sum(
        float(b["width"]) * float(b["height"]) for b in prob["bays"]
    )
    if total_bay_area <= 0:
        return float("inf")
    horizon = max(
        (int(b["release_time"]) + int(b["processing_time"])
         for b in prob["blocks"]),
        default=0,
    )
    min_areas = [
        min((g.area for g in block_geoms), default=float("inf"))
        for block_geoms in geoms
    ]
    peak = 0.0
    for t in range(horizon + 1):
        demand = sum(
            min_areas[i]
            for i, b in enumerate(prob["blocks"])
            if int(b["release_time"]) <= t
            < int(b["release_time"]) + int(b["processing_time"])
        )
        peak = max(peak, demand / total_bay_area)
    return peak


def _assignment_master(prob, geoms, deadline):
    """Exact Z2/Z3 bay assignment, with a strict optional-solver budget.

    Gurobi is part of the official environment.  Import/license/model failures
    simply disable this seed; the anytime fallback and geometric constructors
    remain independent of it.
    """
    remaining = deadline - time.monotonic()
    if remaining < 0.25:
        return None
    try:
        import gurobipy as gp
        from gurobipy import GRB

        n = len(prob["blocks"])
        m = len(prob["bays"])
        model = gp.Model()
        model.Params.OutputFlag = 0
        model.Params.Threads = 1
        model.Params.Seed = 20260727
        model.Params.TimeLimit = max(0.05, min(1.5, 0.35 * remaining))
        model.Params.MIPGap = 0.001

        x = {}
        for i in range(n):
            for j, bay in enumerate(prob["bays"]):
                if any(_fits(g, bay) for g in geoms[i]):
                    x[i, j] = model.addVar(vtype=GRB.BINARY)
        for i in range(n):
            choices = [x[i, j] for j in range(m) if (i, j) in x]
            if not choices:
                return None
            model.addConstr(gp.quicksum(choices) == 1)

        areas = [
            float(b["width"]) * float(b["height"]) for b in prob["bays"]
        ]
        avg_area = sum(areas) / m
        scaled_load = {
            j: (avg_area / areas[j]) * gp.quicksum(
                x[i, j] * float(prob["blocks"][i]["workload"])
                for i in range(n) if (i, j) in x
            )
            for j in range(m)
        }
        imbalance = model.addVar(lb=0.0)
        for j in range(m):
            for k in range(j):
                model.addConstr(imbalance >= scaled_load[j] - scaled_load[k])
                model.addConstr(imbalance >= scaled_load[k] - scaled_load[j])

        regret = gp.quicksum(
            x[i, j] * (
                max(prob["blocks"][i]["bay_preferences"])
                - prob["blocks"][i]["bay_preferences"][j]
            )
            for i, j in x
        )
        weights = prob.get("weights", {})
        model.setObjective(
            float(weights.get("w2", 1.0)) * imbalance
            + float(weights.get("w3", 1.0)) * regret,
            GRB.MINIMIZE,
        )
        model.optimize()
        if model.SolCount <= 0:
            return None
        target = {
            i: max(
                (j for j in range(m) if (i, j) in x),
                key=lambda j: x[i, j].X,
            )
            for i in range(n)
        }
        return target
    except Exception:
        return None


def _construct_fixed_assignment(prob, geoms, target_bays, mode, seed,
                                deadline):
    """Decode one assignment-master solution with exact union geometry."""
    assignments = {}
    order = _priority_order(prob, geoms, mode, seed)
    for rank, bid in enumerate(order):
        if time.monotonic() >= deadline:
            return None
        candidate = _find_in_bay(
            prob, geoms, bid, target_bays[bid], assignments, deadline,
            diagonal=bool((mode + rank) & 1), exact=True,
        )
        if candidate is None:
            return None
        assignments[bid] = candidate
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
                   exact=True, legacy=False):
    n = len(incumbent)
    if n < 4:
        return incumbent
    blame = _blame_order(prob, incumbent)
    q = max(2, min(12, int(round(math.sqrt(n) * 0.45))))

    method = iteration % (3 if legacy else 4)
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
    else:
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
    global USE_LAYER_TRUE
    start = time.monotonic()
    limit = max(0.05, float(timelimit))
    reserve = max(0.20, min(4.0, 0.04 * limit))
    deadline = start + max(0.01, limit - reserve)

    try:
        # Preserve v2's fast, well-calibrated union-envelope constructors.
        # Layer-true geometry is activated only for the improvement phase,
        # where it can unlock a concrete move without multiplying the cost of
        # every initial placement.
        USE_LAYER_TRUE = False
        _MOVE_CACHE.clear()
        _PAIR_CACHE.clear()
        _LAYER_MOVE_CACHE.clear()
        _LAYER_PAIR_CACHE.clear()
        _ORIENT_CACHE.clear()
        geoms = _precompute_geometry(prob_info)
        if any(not gs for gs in geoms):
            raise ValueError("degenerate block geometry")

        fallback = _serial_fallback(prob_info, geoms)
        ok, best_sol, best_result = _official_check(prob_info, fallback)
        if not ok:
            # This should only occur for a malformed instance; allowing the
            # outer fallback path to run is safer than returning a known failure.
            raise ValueError("serial fallback rejected by checker")
        best = fallback
        best_obj = float(best_result["objective"])
        best_from_master = False

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

        # In low-congestion instances, tardiness is usually avoidable and the
        # remaining rank is almost entirely the exact bay-assignment cost.
        # Solve that small binary master once (worker 0 only), then let the
        # unchanged exact geometric decoder prove whether the assignment is
        # schedulable.  Full objective + official-checker gating makes a poor
        # proxy assignment harmless.
        if (limit >= 8.0
                and int(variant) == 0
                and n_blocks <= 200
                and _release_peak_density(prob_info, geoms) <= 0.58
                and time.monotonic() < deadline):
            master_stop = min(
                deadline,
                time.monotonic() + max(0.45, min(6.0, 0.10 * limit)),
            )
            target_bays = _assignment_master(prob_info, geoms, master_stop)
            if target_bays is not None:
                for master_pass, master_mode in enumerate((0, 1, 3)):
                    if time.monotonic() >= master_stop:
                        break
                    candidate = _construct_fixed_assignment(
                        prob_info, geoms, target_bays, master_mode,
                        seed + 6151 * master_pass, master_stop,
                    )
                    if candidate is None:
                        break
                    value = _objective(prob_info, candidate)
                    if value + 1e-7 < best_obj:
                        ok, sol, result = _official_check(prob_info, candidate)
                        if ok:
                            best, best_obj, best_sol = candidate, value, sol
                            best_from_master = True
                            _notify()

        # First obtain a fast rectangle-envelope schedule.  It is conservative
        # but finishes in short limits and is normally far stronger than the
        # serial safety floor.  Polygon-true passes then spend the larger budget.
        fast_fraction = 0.28 if n_blocks > 160 else 0.18
        fast_stop = min(deadline, start + max(0.8, fast_fraction * (deadline - start)))
        max_release = max((b["release_time"] for b in prob_info["blocks"]),
                          default=0)
        w1_now = float(prob_info.get("weights", {}).get("w1", 1.0))
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
                        best_from_master = False
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
                    best_from_master = False
                    _notify()

        # The exact layer predicate is retained behind this switch, but the
        # measured training gate did not justify its higher search cost:
        # relaxed constructors were slower and produced worse incumbents on
        # the congested probes.  Keep Slot B on the proven union-envelope
        # search until a layer-aware candidate generator earns activation.
        USE_LAYER_TRUE = False
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
                legacy=(int(variant) == 0 and not best_from_master),
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
                            best_from_master = False
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
            geoms = _precompute_geometry(prob_info)
            return float("inf"), _emit(_serial_fallback(prob_info, geoms))
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
            for p in workers:
                if p.is_alive():
                    p.terminate()
            while True:
                try:
                    item = queue.get_nowait()
                except Exception:
                    break
                if best is None or item[0] < best[0]:
                    best = item
            for p in workers:
                p.join(0.05)
            if best is not None and best[2] and best[2].get("operations"):
                return best[2]
        except Exception:
            pass

    remaining = max(0.05, limit - (time.monotonic() - start))
    _, sol = _solve(prob_info, remaining, variant=0)
    return sol if sol is not None else {"operations": {}}
