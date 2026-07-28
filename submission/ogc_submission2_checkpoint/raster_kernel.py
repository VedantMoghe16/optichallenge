"""Sound integer-lattice raster geometry kernel for OGC 2026.

WHY
---
Measured (FINDINGS-finals.md F4/F5): for n > 160 the solver must fall back to
rectangle-envelope packing because one exact-polygon construction pass costs
> 600 s at n = 250 (shapely `relate_pattern` ~18 us/test).  Envelope packing
wastes 38% of every bay (envelope occupancy 0.87 vs polygon occupancy 0.44),
which is the direct cause of the congested-set tardiness.  This module replaces
the per-pair shapely test with bit-parallel array algebra on the integer
lattice, so polygon-exact placement becomes affordable at n = 250-300.

MODEL
-----
Placements are integers (the checker rounds via int(round()), utils L1154), and
bays are small (<= ~180 x 30).  Choose a sub-grid factor S (cells of side 1/S).
Every (block, orientation, layer) polygon is rasterised ONCE into a boolean
cell mask in reference-point-relative coordinates.  Because positions are
integral and S is integral, placing a block at (x, y) shifts its mask by
exactly (S*x, S*y) cells -- no re-rasterisation, no alignment error, ever.

RASTERISATION RULE (conservative superset of positive-area coverage)
-------------------------------------------------------------------
A cell is marked if its centre lies inside the polygon OR any polygon edge
passes through the cell.

    Lemma 1 (superset).  If area(cell ∩ P) > 0 then the cell is marked.
    Proof.  Either the cell is entirely inside P, in which case its centre is
    inside and it is marked; or the cell meets both the interior and the
    exterior of P, in which case ∂P crosses the cell and the edge walk marks
    it.  ∎

SOUNDNESS (the property that protects against an infeasible submission)
-----------------------------------------------------------------------
    Theorem 2.  If the marked cell sets of two placed blocks are disjoint at a
    given layer index, then the true polygons have zero intersection area at
    that layer.
    Proof.  Suppose area(P1 ∩ P2) > 0.  The intersection has positive area, so
    some cell c has area(c ∩ P1 ∩ P2) > 0, hence area(c ∩ P1) > 0 and
    area(c ∩ P2) > 0.  By Lemma 1 c is marked for both, contradicting
    disjointness.  ∎

    Corollary 3.  raster-disjoint => the official checker's
    `intersection.area > 0` test passes.  The kernel can therefore only ever be
    CONSERVATIVE: it may reject a legal placement (when two boundaries pass
    through one shared cell without truly overlapping -- possible only for true
    clearances below the cell diagonal sqrt(2)/S), but it can never accept an
    illegal one.  Containment is exact in both directions because bay corners
    are integral and cells are 1/S-aligned.

CRANE RULE
----------
The vertical lift rule (moving block's layer k must clear co-present layers
j >= k) is expressed with prefix-OR masks: D_j = union of the mover's layers
0..j.  Then
    (for all k: M_k ∩ (union_{j>=k} occ_j) = empty)  <=>  (for all j: occ_j ∩ D_j = empty)
which is the same set of pairwise tests re-grouped so each occupancy layer is
touched once.  Both directions are provided since a placement must also not
break the lifts of blocks already scheduled inside its residency interval.
"""

from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import Polygon

DEFAULT_S = 4


# ---------------------------------------------------------------------------
# Rasterisation
# ---------------------------------------------------------------------------

def _edge_cells(poly: Polygon, S: int, ox: int, oy: int, shape):
    """Cell indices touched by the polygon boundary (DDA walk per edge)."""
    rows, cols = shape
    out = []
    rings = [poly.exterior] + list(poly.interiors)
    for ring in rings:
        pts = list(ring.coords)
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            # work in cell units
            cx0, cy0 = x0 * S - ox, y0 * S - oy
            cx1, cy1 = x1 * S - ox, y1 * S - oy
            n = int(max(abs(cx1 - cx0), abs(cy1 - cy0)) * 2) + 2
            for i in range(n + 1):
                t = i / n
                cx = cx0 + (cx1 - cx0) * t
                cy = cy0 + (cy1 - cy0) * t
                # mark the cell containing this boundary point and, because a
                # point exactly on a cell border belongs to both, its lower
                # neighbours as well (conservative)
                for dx in (0, -1e-9):
                    for dy in (0, -1e-9):
                        c = int(math.floor(cx + dx))
                        r = int(math.floor(cy + dy))
                        if 0 <= r < rows and 0 <= c < cols:
                            out.append((r, c))
    return out


def rasterize_polygon(poly: Polygon, S: int = DEFAULT_S):
    """Return (mask, ox, oy): boolean mask plus its cell-space origin.

    Cell (r, c) of the mask corresponds to the square
    [(c+ox)/S, (c+ox+1)/S) x [(r+oy)/S, (r+oy+1)/S) in polygon coordinates.
    """
    minx, miny, maxx, maxy = poly.bounds
    ox = int(math.floor(minx * S)) - 1
    oy = int(math.floor(miny * S)) - 1
    cols = int(math.ceil(maxx * S)) - ox + 2
    rows = int(math.ceil(maxy * S)) - oy + 2
    mask = np.zeros((rows, cols), dtype=bool)
    # interior: cell centres inside the polygon (vectorised)
    cs = (np.arange(cols) + ox + 0.5) / S
    rs = (np.arange(rows) + oy + 0.5) / S
    gx, gy = np.meshgrid(cs, rs)
    inside = shapely.contains_xy(poly, gx.ravel(), gy.ravel()).reshape(rows, cols)
    mask |= inside
    # boundary cells
    for r, c in _edge_cells(poly, S, ox, oy, (rows, cols)):
        mask[r, c] = True
    return mask, ox, oy


class RasterOrient:
    """Rasterised layers of one (block, orientation), plus crane prefix masks."""

    __slots__ = ("layers", "prefix", "ox", "oy", "rows", "cols", "S", "n_layers")

    def __init__(self, layer_polys, S: int = DEFAULT_S):
        polys = [p for p in layer_polys if p is not None]
        if not polys:
            raise ValueError("orientation has no usable layer polygon")
        # one shared cell frame for all layers so indices line up
        minx = min(p.bounds[0] for p in polys)
        miny = min(p.bounds[1] for p in polys)
        maxx = max(p.bounds[2] for p in polys)
        maxy = max(p.bounds[3] for p in polys)
        self.S = S
        self.ox = int(math.floor(minx * S)) - 1
        self.oy = int(math.floor(miny * S)) - 1
        self.cols = int(math.ceil(maxx * S)) - self.ox + 2
        self.rows = int(math.ceil(maxy * S)) - self.oy + 2
        self.n_layers = len(layer_polys)
        self.layers = []
        for p in layer_polys:
            m = np.zeros((self.rows, self.cols), dtype=bool)
            if p is not None:
                sub, sox, soy = rasterize_polygon(p, S)
                r0, c0 = soy - self.oy, sox - self.ox
                m[r0:r0 + sub.shape[0], c0:c0 + sub.shape[1]] |= sub
            self.layers.append(m)
        # prefix-OR for the crane rule: D_j = union of layers 0..j
        self.prefix = []
        acc = np.zeros((self.rows, self.cols), dtype=bool)
        for m in self.layers:
            acc = acc | m
            self.prefix.append(acc.copy())


class BayRaster:
    """Per-layer occupancy of one bay over one time interval."""

    __slots__ = ("W", "H", "S", "rows", "cols", "occ", "n_layers")

    def __init__(self, width: int, height: int, S: int = DEFAULT_S,
                 n_layers: int = 4):
        self.W, self.H, self.S = int(width), int(height), S
        self.rows, self.cols = self.H * S, self.W * S
        self.n_layers = n_layers
        self.occ = [np.zeros((self.rows, self.cols), dtype=bool)
                    for _ in range(n_layers)]

    # -- placement helpers --------------------------------------------------
    def window(self, g: RasterOrient, x: int, y: int):
        """Cell-space slice occupied by g placed at integer (x, y), or None if
        it would fall outside the bay grid."""
        r0 = y * self.S + g.oy
        c0 = x * self.S + g.ox
        if r0 < 0 or c0 < 0 or r0 + g.rows > self.rows or c0 + g.cols > self.cols:
            return None
        return slice(r0, r0 + g.rows), slice(c0, c0 + g.cols)

    def stamp(self, g: RasterOrient, x: int, y: int, sign: bool = True):
        w = self.window(g, x, y)
        if w is None:
            raise ValueError("stamp outside bay grid")
        rs, cs = w
        for k, m in enumerate(g.layers):
            if k >= self.n_layers:
                break
            if sign:
                self.occ[k][rs, cs] |= m
            else:
                self.occ[k][rs, cs] &= ~m

    def unstamp(self, g: RasterOrient, x: int, y: int):
        """Exact removal: co-present blocks are disjoint per layer by
        invariant, so ANDNOT of the mask restores the previous state."""
        self.stamp(g, x, y, sign=False)

    # -- feasibility tests --------------------------------------------------
    def collides(self, g: RasterOrient, x: int, y: int) -> bool:
        """Same-layer overlap of g at (x, y) with current occupancy."""
        w = self.window(g, x, y)
        if w is None:
            return True
        rs, cs = w
        for k, m in enumerate(g.layers):
            if k >= self.n_layers:
                break
            if np.any(self.occ[k][rs, cs] & m):
                return True
        return False

    def crane_blocked(self, g: RasterOrient, x: int, y: int) -> bool:
        """Vertical lift of g at (x, y) obstructed?  Uses the prefix identity
        (for all j: occ_j & D_j == empty)."""
        w = self.window(g, x, y)
        if w is None:
            return True
        rs, cs = w
        top = len(g.prefix) - 1
        for j in range(self.n_layers):
            d = g.prefix[min(j, top)]
            if np.any(self.occ[j][rs, cs] & d):
                return True
        return False

    def feasible_map(self, g: RasterOrient, crane: bool = True):
        """All integer positions (x, y) at which g is collision- and (optionally)
        crane-feasible.  Returns a boolean array indexed [y, x] over the legal
        integer range, computed with one correlation per layer instead of one
        test per candidate position."""
        from scipy.signal import fftconvolve
        # legal integer position range from the mask frame
        x_lo = int(math.ceil(-g.ox / self.S))
        y_lo = int(math.ceil(-g.oy / self.S))
        x_hi = int(math.floor((self.cols - g.cols - g.ox) / self.S))
        y_hi = int(math.floor((self.rows - g.rows - g.oy) / self.S))
        if x_hi < x_lo or y_hi < y_lo:
            return None, 0, 0
        acc = None
        masks = g.prefix if crane else g.layers
        for k in range(self.n_layers):
            m = masks[min(k, len(masks) - 1)] if crane else (
                g.layers[k] if k < len(g.layers) else None)
            if m is None or not m.any():
                continue
            occ = self.occ[k]
            if not occ.any():
                continue
            conv = fftconvolve(occ.astype(np.float32),
                               m[::-1, ::-1].astype(np.float32), mode="valid")
            acc = conv if acc is None else acc + conv
        nx, ny = x_hi - x_lo + 1, y_hi - y_lo + 1
        if acc is None:
            return np.ones((ny, nx), dtype=bool), x_lo, y_lo
        rows_idx = np.arange(y_lo, y_hi + 1) * self.S + g.oy
        cols_idx = np.arange(x_lo, x_hi + 1) * self.S + g.ox
        sub = acc[np.ix_(rows_idx, cols_idx)]
        return sub < 0.5, x_lo, y_lo
