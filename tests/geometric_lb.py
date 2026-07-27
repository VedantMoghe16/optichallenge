r"""Geometric / energetic LOWER BOUNDS on Z1 (and hence on the OGC-2026 objective).

Companion to tests/lower_bounds.py.  That module's tardiness bound is an
`(r,d)`-window *area* bound and evaluates to exactly 0.0 on all 40 training
instances; this module replaces it with a family of strictly stronger, still
provably valid bounds and reports the best.  Everything below is a relaxation
of the *published* feasibility system (ogc2026/baseline/utils.py, read-only):

  S1 entry_i >= R_i                                    (utils L1131)
  S2 exit_i - entry_i >= P_i                           (utils L1127)
  S3 entry_i, exit_i integer                           (utils L1047: float(int(key)))
  S4 x_i, y_i integer                                  (utils L1154: int(round(.)))
  S5 the *all-layer* bounding rect of block i must lie in [0,W_j]x[0,H_j]
                                                       (utils L252-266, L1247-1260)
  S6 blocks co-present in a bay (half-open intervals [entry,exit) overlap) have
     interior-disjoint polygons at every SHARED layer index k, i.e. for every
     k < min(K_a,K_b)                                  (utils L461-543, L1262-1282)
  S7 crane rule at every ENTRY/EXIT: the moving block's layer k is disjoint from
     co-present blocks' layers j >= k                  (utils L603-826, Stages 2/3/5)
  Z1 = sum_i max(0, exit_i - D_i)                      (utils L1411); by S3 every
     tardiness term is a NON-NEGATIVE INTEGER, so any valid fractional bound may
     be rounded up with ceil().  (Used at the very end only.)

S7 is only ever *dropped*, never used, except where stated: dropping constraints
keeps a lower bound valid.

===============================================================================
P1.  THE RESOURCE: layer-0 area is a cumulative resource of capacity sum_j W_j*H_j
===============================================================================
Every block has at least one layer, so layer index 0 is shared by every pair of
blocks and S6 applies to it unconditionally.  Fix an instant t and a bay j.  The
layer-0 polygons of the blocks present in bay j at t are pairwise
interior-disjoint (S6) and each is contained in [0,W_j]x[0,H_j] (S5, since the
all-layer bbox contains the layer-0 polygon).  Hence

    sum_{i present in bay j at t} area(L0_i)  <=  W_j * H_j .            (P1)

Summing over a set Q of bays gives a cumulative resource of capacity
C_Q = sum_{j in Q} W_j*H_j whose per-block requirement is a_i = area(L0_i)
(orientation-invariant up to congruence; we still take min over orientations,
see P3).  This is the resource used by tests/lower_bounds.py.

===============================================================================
P2.  STRIP / SLAB RELAXATION  (strictly generalises the "tall blocks" idea)
===============================================================================
The naive strip argument -- "two blocks taller than H/2 cannot be stacked, so
their bbox widths add up to at most W" -- is FALSE for the concave layers in
these instances: two interlocking L/staircase polygons can have overlapping
x-projections while remaining interior-disjoint, so no inequality on bounding-box
widths follows from S5+S6.  The measure-theoretic repair is valid:

Let sigma = [alpha,beta] subset [0,H_j] be a horizontal slab of bay j
(alpha,beta integers).  For block i define the GUARANTEED SLAB OCCUPANCY

    g_i(j,sigma) = min over orientations o admissible in bay j,
                   min over admissible INTEGER y-offsets y,
                       area( (L0_i^o + (x,y)) intersect (R x [alpha,beta]) ),

which is independent of x.  "Admissible" = the all-layer bbox of orientation o
fits in bay j and an integer x,y placement exists (S4,S5); if no orientation is
admissible, bay j is impossible for block i.  Because the polygons present in
bay j at instant t are interior-disjoint (S6) and contained in the bay, their
restrictions to the slab are interior-disjoint subsets of a
W_j x (beta-alpha) rectangle, so

    sum_{i present in bay j at t} g_i(j,sigma)  <=  W_j * (beta - alpha) .  (P2)

Hence *each choice of one slab per bay* yields another valid cumulative resource
with capacity C_Q = sum_{j in Q} W_j*(beta_j-alpha_j) and requirement
d_i = min_{j admissible for i} g_i(j,sigma_j).  sigma_j = [0,H_j] recovers P1
exactly.  For a rectangle w x h with h > H/2 and the slab (H-h,h) the ratio
d/capacity equals w/W, i.e. P2 contains the strip bound as a special case, and
degrades gracefully (rather than becoming invalid) for concave layers.
Because the enumeration is over INTEGER y-offsets (S4) the minimum is exact.
Implementation: candidate slabs are centred, thickness t_j = round(rho*H_j) for
a grid of rho; the max over all evaluated (Q, rho) is reported (a max of valid
bounds is valid).

  Measured: on prob_21..40 the best slab resource raises the peak forced
  density by only 0-5% over P1 -- because the 8 orientations of every block
  include a 90-degree rotation, so min_o (bbox height) is small and nothing is
  forced to be "tall".  Kept because it is instance-independent and provable.

===============================================================================
P3.  BAY-SUBSET RESTRICTION
===============================================================================
Let B_i = { j : some orientation of i is admissible in bay j } (S4,S5).  The bay
actually used by i lies in B_i.  For any set Q of bays, every block with
B_i subset Q is certainly assigned inside Q, so (P1)/(P2) restricted to Q hold
with the eligible set {i : B_i subset Q} and capacity C_Q.  Blocks with
B_i not subset Q are simply dropped (a relaxation).  Taking d_i = min_{j in B_i}
g_i(j,sigma_j) is valid because the true bay of i is in B_i.

===============================================================================
P4.  MANDATORY PRESENCE (compulsory part) AS A FUNCTION OF THE TARDINESS
===============================================================================
Let x_i = max(0, exit_i - D_i) >= 0 be the tardiness of block i.  Then
exit_i <= D_i + x_i, and with S1/S2:

    entry_i <= exit_i - P_i <= D_i + x_i - P_i ,      exit_i >= R_i + P_i .

Therefore block i is present (its interval [entry_i,exit_i) contains t) for
EVERY t with

    D_i + x_i - P_i  <=  t  <  R_i + P_i .                                (P4)

So block i occupies its bay -- and consumes d_i of the resource of P1/P2 -- on
at least  len_i(x_i, a, b) = |[D_i+x_i-P_i, R_i+P_i) intersect [a,b)|  of the
days of any window [a,b), and by S3 all these endpoints are integers.  This is
the classical "compulsory part" of energetic reasoning (Baptiste, Le Pape,
Nuijten, *Constraint-Based Scheduling*, 2001, ch. 3; Lopez & Esquirol 1996),
here made a function of the cost variable x_i.

===============================================================================
P5.  ENERGETIC-WINDOW COVERING BOUND (engine W)
===============================================================================
Fix a window [a,b), a >= any integer, and a resource (Q, slab choice) from
P1/P2/P3.  Integrating the instantaneous inequality (P1)/(P2) over [a,b) gives

    sum_{i eligible} d_i * len_i(x_i,a,b)  <=  C_Q * (b-a) .              (P5.1)

With L_i = len_i(0,a,b) = min(b,R_i+P_i) - max(a,D_i-P_i) (clipped at 0) and
c0_i = max(0, a - (D_i-P_i)), the compulsory part shrinks by exactly one day per
unit of tardiness, but only after the left edge D_i+x_i-P_i has passed a:

    len_i(x_i,a,b) >= L_i - max(0, x_i - c0_i)  and  len_i >= 0 ,
    so the reduction obtainable from block i is
        rho_i(x_i) = d_i * min( max(0, x_i - c0_i), L_i )   <=  d_i * L_i .

Let X = sum_i d_i*L_i - C_Q*(b-a).  If X > 0 the schedule MUST buy at least X
units of reduction, and buying rho_i > 0 from block i costs
x_i >= c0_i + rho_i/d_i.  Relaxing the choice to y_i = rho_i/(d_i*L_i) in [0,1]
with cost y_i*(c0_i + L_i) is a lower bound on x_i (because y_i <= 1 implies
y_i*c0_i <= c0_i), so

    Z1 = sum_i x_i  >=  min { sum_i y_i (c0_i + L_i) : sum_i y_i d_i L_i >= X,
                              y in [0,1]^n }                              (P5.2)

which is a fractional knapsack cover, solved exactly by sorting on the ratio
(c0_i+L_i)/(d_i*L_i).  Every window [a,b) and every resource gives a valid
bound; we report the max.  Note b = a+1 reproduces the single-instant
"mandatory presence" test of RESULTS.md 2026-07-27, so engine W dominates it.

===============================================================================
P5b. DEADLINE-WINDOW COVERING BOUND (engine F)  -- strongest engine in practice
===============================================================================
The compulsory part of P4 is short (its length is R_i+2P_i-D_i, i.e. P_i minus
the slack); a second, independent and usually much stronger inequality comes
from the fact that the WHOLE processing requirement has to fit between the
release and the tardiness-shifted due date.  Fix a window [a,b).  Because
[entry_i,exit_i) is contained in A_i(x_i) = [R_i, D_i+x_i) and has length >= P_i,

    |[entry_i,exit_i) cap [a,b)|  >=  P_i - |A_i(x_i) \ [a,b)|
        = P_i - max(0, min(a,D_i+x_i) - R_i) - max(0, D_i+x_i - b) .

We only ever use windows with a <= D_i (blocks with D_i < a are dropped, which
is a relaxation).  Then min(a,D_i+x_i) = a for every x_i >= 0, so with

    F_i = max(0, P_i - max(0,a-R_i) - max(0,D_i-b)) ,  c0_i = max(0, b-D_i)

the forced overlap is >= F_i - max(0, x_i - c0_i), clipped at 0: tardiness only
starts to relieve the window once the deadline D_i+x_i has passed b.  Combining
with (P1)/(P2) integrated over [a,b),

    sum_i d_i * ( F_i - max(0, x_i - c0_i) )^+  <=  C_Q * (b-a) ,

and with X = sum_i d_i*F_i - C_Q*(b-a) > 0 the fractional cover of P5.2 applies
verbatim with (L_i, c0_i) replaced by (F_i, max(0,b-D_i)).  This is the
tardiness-cost analogue of the Gale-Hoffman / Hoffman-circulation feasibility
condition for the preemptive transportation relaxation of P6, and it is the
engine that produces the reported non-zero bounds (2.3x engine W on prob_38).

===============================================================================
P6.  PREEMPTIVE WHOLE-HORIZON LP (engine L)
===============================================================================
z_{it} in [0,1] models "block i is present on day t" (t >= R_i, t <= Tmax),
x_i >= 0 its tardiness.  For any feasible solution, z_{it} = 1{entry_i<=t<exit_i}
and x_i = tardiness_i satisfy

  (1) sum_i d_i z_{it} <= C_Q                        for all t      [P1/P2]
  (2) sum_t z_{it} >= P_i                            (exit-entry >= P_i, S2)
  (3) x_i >= (t+1-D_i) * z_{it}                      (present on day t  =>
                                                      exit_i >= t+1, S3)
  (4) x_i >= (t+P_i-D_i+1) * (1 - z_{it})   for D_i-P_i <= t < R_i+P_i
                                                     (contrapositive of P4 with
                                                      integrality S3)
  (5) sum_{t in [a,b)} z_{it} + x_i >= L_i(a,b)      for any window  [P4]

so the LP minimum of sum_i x_i is a valid lower bound on Z1.  Tmax is chosen
large enough that the LP is feasible (>= max_i(R_i+P_i) + ceil(E/C_Q) + max P_i),
so no upper truncation is imposed on the schedule.  Cuts (5) are generated for
the windows found violated in P5.  Engines W and L do not dominate each other
(L relaxes contiguity, W relaxes multi-window interaction), so the max is taken.

===============================================================================
P7.  PREFIX / REARRANGEMENT ENERGETIC BOUND (engine R)
===============================================================================
Fix r and let S = {i eligible : R_i >= r}, m = |S|.  No block of S consumes the
resource before r, so integrating (P1)/(P2) over [r,tau] gives, for the k blocks
of S with the smallest exit times, sum of their energies <= C_Q*(tau-r) at
tau = the k-th smallest exit T_(k).  Their energy is at least E_k = the sum of
the k smallest values of d_i*P_i over S (each block consumes d_i for >= P_i
days, S2).  Hence T_(k) >= r + E_k/C_Q =: L_k.  For any bijection sigma between
sorted exits and blocks, sum_i (T_i - D_i)^+ >= sum_k (L_k - D_sigma(k))^+ >=
min over pairings, attained by sorting both L and D ascending (rearrangement).
So Z1 >= sum_k (L_k - D_(k))^+ with both sequences sorted ascending.  This is a
strict strengthening of the max-form bound in tests/lower_bounds.py (which is
the single largest term of the same sum, restricted to D_i <= d).

===============================================================================
P8.  COMBINATION WITH THE ASSIGNMENT LP, AND WHAT WAS TRIED AND REJECTED
===============================================================================
objective = w1*Z1 + w2*Z2 + w3*Z3 with Z2,Z3 >= 0 depending only on the
assignment vector; each term is bounded below independently over the whole
feasible set, so LB = w1*ceil(LB_Z1) + LP(w2*Z2+w3*Z3) is valid, where the
second term is the LP of tests/lower_bounds.lb_assign (unchanged).

Rejected after implementation/measurement (all *valid*, none useful here):
 * Dual feasible functions on unit-cell coverage.  Positions are integer (S4)
   and W_j,H_j are integer, so the bay is exactly W_j*H_j unit cells and the
   coverage pattern of a block over cells is fixed per orientation up to integer
   translation.  Interior-disjointness gives, per cell, sum_i c_i(cell) <= 1, so
   for any dual feasible function u (u superadditive, non-decreasing, u(1)=1;
   Fekete & Schepers, *Math. Prog.* 91:11-31 (2001); Carlier, Clautiaux,
   Moukrim, *Comput. Oper. Res.* 34:2223-2250 (2007)) the demand
   d_i^u = min_o sum_cells u(c_i^o(cell)) is valid against capacity W_j*H_j.
   MEASURED with the family f_{0,eps}(c) = 1 if c>1-eps, c if eps<=c<=1-eps,
   0 otherwise: d^u/area = 0.974..1.000 on prob_21/27/38 for eps in [0,0.5] --
   i.e. every non-trivial DFF is DOMINATED by plain area, because the boundary
   cells of these polygons have coverages spread over (0,1) rather than
   concentrated near 1.  Not shipped.
 * The crane rule S7.  For co-present a,b it implies (later-entering)_0 is
   disjoint from the *whole footprint* of the earlier one, and the block that
   exits last has its whole footprint disjoint from every other layer-0.
   Peeling those regions yields
   sum_i area(L0_i) + max_i (area(union of layers of i) - area(L0_i)) <= W_j*H_j,
   i.e. one block's upper-layer surplus -- < 1% of capacity.  Not shipped.
 * Layer index k > 0 in S6: valid with eligible set {i : K_i > k}, but layer-1
   polygons are smaller and only a subset of blocks has K_i > 1, so it is
   dominated by k = 0 on every instance.  Not shipped.

USAGE.  `python tests/geometric_lb.py [--results DIR] [--crosscheck DIR ...]`
        `python tests/geometric_lb.py selftest`
--results points the comparison columns at another build's res_prob_*.json;
--crosscheck re-validates the bounds against further solution sets (a valid lower
bound must hold for EVERY feasible solution, so more sets = a stronger test).

REPRODUCIBILITY.  Engine L runs HiGHS under a 25 s cap.  If the cap is hit the
engine contributes nothing (`res.success` False -> 0.0) and the reported bound
falls back to max(W, F, R), which is still valid -- so a slower machine can only
report a WEAKER bound, never an invalid one.  Only prob_27 depends on engine L
at all (71 with L, 67 without).  Everything else is deterministic.

DIAGNOSTIC (NOT A BOUND).  LB_Z1(delta) is engine W/L run with capacity
delta*C_Q.  It is a valid lower bound only under the *unproven* hypothesis
"at no instant can layer-0 polygons occupy more than a delta fraction of a bay".
It is printed to quantify how much of our achieved Z1 could be explained by
packing inefficiency; it is never added to the reported LB.
"""
import glob
import json
import os
import math
import sys
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog
from shapely.geometry import Polygon

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lower_bounds import lb_assign, lb_tardiness      # noqa: E402

BASE = Path(__file__).resolve().parent.parent
# Directory holding res_prob_*.json (instance / objective / obj1..3) of the build we
# compare against.  Default = shipped gateB v21 (== v2.2-slotA).  Override with
#   python tests/geometric_lb.py --results <DIR>      or   GEOM_LB_RESULTS=<DIR>
# so the table can be regenerated against a newer build without touching the bounds.
SHIPPED = Path(os.environ.get(
    "GEOM_LB_RESULTS",
    "/private/tmp/claude-501/-Users-vedantmoghe-Downloads-optichallenge/"
    "828d3afa-14fe-4679-bfb6-c94c0e22ac75/scratchpad/gateB/v21"))
EPS = 1e-9

# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


def _shapely(verts):
    p = Polygon([(float(a), float(b)) for a, b in verts])
    if not p.is_valid:
        p = p.buffer(0)
    return p


def _shoelace(v):
    x = np.asarray([p[0] for p in v], float)
    y = np.asarray([p[1] for p in v], float)
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def _clip_below(v, Y):
    """Sutherland-Hodgman clip of a simple polygon against the half-plane y<=Y.

    The output ring may contain zero-area bridges; its shoelace area equals the
    area of the clipped region exactly.
    """
    out = []
    n = len(v)
    for i in range(n):
        ax, ay = v[i]
        bx, by = v[(i + 1) % n]
        ain, bin_ = ay <= Y, by <= Y
        if ain:
            out.append((ax, ay))
        if ain != bin_:
            t = (Y - ay) / (by - ay)
            out.append((ax + t * (bx - ax), Y))
    return out


def _cum_area_table(verts, poly):
    """A[Y-y0] = area of the polygon below the horizontal line y=Y, Y integer.

    Exact.  Uses the analytic clip when it agrees with shapely (always, in
    practice); otherwise falls back to shapely per level so the result is a
    faithful area of the *repaired* polygon the checker uses.
    """
    y0 = math.floor(poly.bounds[1])
    y1 = math.ceil(poly.bounds[3])
    total = poly.area
    fast = abs(_shoelace(verts) - total) <= 1e-7 * max(1.0, total)
    if fast:
        mid = (y0 + y1) // 2
        a_fast = _shoelace(_clip_below(verts, mid)) if mid > y0 else 0.0
        a_ref = poly.intersection(
            Polygon([(poly.bounds[0] - 1, y0 - 1), (poly.bounds[2] + 1, y0 - 1),
                     (poly.bounds[2] + 1, mid), (poly.bounds[0] - 1, mid)])).area
        fast = abs(a_fast - a_ref) <= 1e-7 * max(1.0, total)
    A = np.empty(y1 - y0 + 1)
    for k, Y in enumerate(range(y0, y1 + 1)):
        if Y <= y0:
            A[k] = 0.0
        elif Y >= y1:
            A[k] = total
        elif fast:
            c = _clip_below(verts, Y)
            A[k] = _shoelace(c) if len(c) >= 3 else 0.0
        else:
            A[k] = poly.intersection(
                Polygon([(poly.bounds[0] - 1, y0 - 1), (poly.bounds[2] + 1, y0 - 1),
                         (poly.bounds[2] + 1, Y), (poly.bounds[0] - 1, Y)])).area
    return y0, y1, A, total


def build_geometry(inst, layer=0):
    """Per (block, orientation): all-layer bbox relative to the reference point
    (= first vertex of layer 0, which the checker maps to the integer (x,y)),
    plus the cumulative-area table of the layer-`layer` polygon."""
    geo = []
    for b in inst["blocks"]:
        ors = []
        for s in b["shape"]:
            lays = [l for l in s["layers"] if l]
            if len(lays) <= layer:
                ors.append(None)
                continue
            rx, ry = float(lays[0][0][0]), float(lays[0][0][1])
            allv = [(float(x) - rx, float(y) - ry) for l in lays for x, y in l]
            mnx = min(p[0] for p in allv); mxx = max(p[0] for p in allv)
            mny = min(p[1] for p in allv); mxy = max(p[1] for p in allv)
            v = [(float(x) - rx, float(y) - ry) for x, y in lays[layer]]
            P = _shapely(v)
            if P.is_empty or P.area <= 0:
                ors.append(None)
                continue
            y0, y1, A, tot = _cum_area_table(v, P)
            ors.append(dict(mnx=mnx, mxx=mxx, mny=mny, mxy=mxy,
                            w=mxx - mnx, h=mxy - mny, y0=y0, y1=y1, A=A, area=tot))
        geo.append(ors)
    return geo


def admissible(o, W, H):
    """Can orientation `o` be placed in a W x H bay at integer coordinates? (S4,S5)"""
    if o is None or o["w"] > W + EPS or o["h"] > H + EPS:
        return None
    xlo = math.ceil(-o["mnx"] - EPS); xhi = math.floor(W - o["mxx"] + EPS)
    ylo = math.ceil(-o["mny"] - EPS); yhi = math.floor(H - o["mxy"] + EPS)
    if xlo > xhi or ylo > yhi:
        return None
    return ylo, yhi


def bay_sets(inst, geo):
    """B_i (P3), as a tuple of bay indices."""
    bays = [(int(b["width"]), int(b["height"])) for b in inst["bays"]]
    out = []
    for ors in geo:
        s = tuple(j for j, (W, H) in enumerate(bays)
                  if any(admissible(o, W, H) for o in ors))
        out.append(s)
    return out


def slab_tables(inst, geo, Bset):
    """tabs[i][j][t-1] = g_i(j, centred slab of thickness t), t = 1..H_j   (P2).

    Exhaustive over orientations admissible in bay j and over ALL admissible
    integer y-offsets, so the minimum is exact (S4).
    """
    bays = [(int(b["width"]), int(b["height"])) for b in inst["bays"]]
    tabs = []
    for i in range(len(geo)):
        per = {}
        for j in Bset[i]:
            W, H = bays[j]
            ts = np.arange(1, H + 1)
            a = (H - ts) // 2
            bnd = a + ts
            best = np.full(H, np.inf)
            for o in geo[i]:
                rng = admissible(o, W, H)
                if rng is None:
                    continue
                ylo, yhi = rng
                ys = np.arange(ylo, yhi + 1)
                A, y0, y1 = o["A"], o["y0"], o["y1"]
                hi = A[np.clip(bnd[:, None] - ys[None, :], y0, y1) - y0]
                lo = A[np.clip(a[:, None] - ys[None, :], y0, y1) - y0]
                best = np.minimum(best, (hi - lo).min(axis=1))
            per[j] = np.maximum(best, 0.0)
        tabs.append(per)
    return tabs


def slab_demand(tabs, Bset, thick):
    """d_i = min_{j in B_i} g_i(j, sigma_j)   (P2 + P3)."""
    d = np.zeros(len(tabs))
    for i in range(len(tabs)):
        best = math.inf
        for j in Bset[i]:
            v = float(tabs[i][j][int(thick[j]) - 1])
            if v < best:
                best = v
        d[i] = 0.0 if best is math.inf else max(0.0, best)
    return d


# ---------------------------------------------------------------------------
# engines
# ---------------------------------------------------------------------------


def engine_W(d, R, D, P, C, elig, max_windows=400):
    """P5: energetic-window fractional cover.  Returns (value, window, cuts)."""
    if C <= 0 or not len(elig):
        return 0.0, None, []
    d = d[elig]; R = R[elig].astype(int); D = D[elig].astype(int); P = P[elig].astype(int)
    Rp = R + P
    Dm = D - P
    lo = int(min(Dm.min(), 0)); hi = int(Rp.max())
    T = hi - lo + 1
    rho = np.zeros(T)                       # forced demand per day, at x = 0
    for i in range(len(d)):
        s = max(int(Dm[i]), lo) - lo; e = int(Rp[i]) - lo
        if e > s:
            rho[s:e] += d[i]
    cum = np.concatenate([[0.0], np.cumsum(rho)])
    best = 0.0; arg = None; cand = []
    for a in range(T):
        F = cum[a + 1:] - cum[a]
        ln = np.arange(1, len(F) + 1)
        X = F - C * ln
        for ci in np.where(X > 1e-9)[0]:
            cand.append((float(X[ci]), a + lo, a + 1 + ci + lo))
    cand.sort(reverse=True)
    cuts = [(a, b) for _, a, b in cand[:max_windows]]
    for Xv, a, b in cand[:max_windows]:
        L = np.clip(np.minimum(b, Rp) - np.maximum(a, Dm), 0, None).astype(float)
        cap = d * L
        c0 = np.maximum(0.0, a - Dm).astype(float)
        p = cap > 1e-12
        if not p.any():
            continue
        cost = c0[p] + L[p]; cp = cap[p]
        order = np.argsort(cost / cp)
        cs = np.cumsum(cp[order])
        k = int(np.searchsorted(cs, Xv))
        if k >= len(cs):
            continue                        # cannot be covered -> no valid bound
        tot = cost[order][:k].sum()
        if k > 0:
            Xv -= cs[k - 1]
        tot += Xv / cp[order][k] * cost[order][k]
        if tot > best:
            best, arg = float(tot), (a, b)
    return best, arg, cuts


def engine_F(d, R, D, P, C, elig, max_windows=400):
    """P5b: deadline-window fractional cover.  Returns (value, window, cuts)."""
    if C <= 0 or not len(elig):
        return 0.0, None, []
    d = d[elig]; R = R[elig].astype(int); D = D[elig].astype(int); P = P[elig].astype(int)
    lo = int(R.min()); hi = int(D.max()) + 1
    bs = np.arange(lo, hi + 1)
    cand = []
    for a in range(lo, hi):
        left = np.clip(a - R, 0, None)                 # valid because D_i >= a below
        sel = bs > a
        b_ = bs[sel]
        Fm = np.clip(P[:, None] - left[:, None]
                     - np.clip(D[:, None] - b_[None, :], 0, None), 0, None).astype(float)
        Fm[D < a, :] = 0.0                      # drop blocks whose deadline precedes a
        X = d @ Fm - C * (b_ - a)
        for k in np.where(X > 1e-9)[0]:
            cand.append((float(X[k]), a, int(b_[k])))
    cand.sort(reverse=True)
    cuts = [(a, b) for _, a, b in cand[:max_windows]]
    best = 0.0; arg = None
    for Xv, a, b in cand[:max_windows]:
        left = np.clip(a - R, 0, None)                 # valid because D_i >= a below
        F = np.clip(P - left - np.clip(D - b, 0, None), 0, None).astype(float)
        F[D < a] = 0.0
        cap = d * F
        c0 = np.clip(b - D, 0, None).astype(float)
        p = cap > 1e-12
        if not p.any():
            continue
        cost = c0[p] + F[p]; cp = cap[p]
        order = np.argsort(cost / cp)
        cs = np.cumsum(cp[order])
        k = int(np.searchsorted(cs, Xv))
        if k >= len(cs):
            continue
        tot = cost[order][:k].sum()
        if k > 0:
            Xv -= cs[k - 1]
        tot += Xv / cp[order][k] * cost[order][k]
        if tot > best:
            best, arg = float(tot), (a, b)
    return best, arg, cuts


def engine_R(d, R, D, P, C, elig):
    """P7: prefix / rearrangement energetic bound."""
    if C <= 0 or not len(elig):
        return 0.0
    d = d[elig]; R = R[elig]; D = D[elig]; P = P[elig]
    best = 0.0
    for r in np.unique(R):
        S = np.where(R >= r)[0]
        if not len(S):
            continue
        e = np.sort(d[S] * P[S])
        L = r + np.cumsum(e) / C
        v = float(np.maximum(0.0, np.ceil(L - 1e-9) - np.sort(D[S])).sum())
        best = max(best, v)
    return best


def engine_L(d, R, D, P, C, elig, cuts=(), time_budget=40.0):
    """P6: preemptive whole-horizon LP (+ mandatory-presence and window cuts)."""
    if C <= 0 or not len(elig):
        return 0.0
    d = d[elig]; R = R[elig].astype(int); D = D[elig].astype(int); P = P[elig].astype(int)
    n = len(d)
    E = float((d * P).sum())
    Tmax = int(max((R + P).max(), R.max() + math.ceil(E / C) + 1) + P.max() + 1)
    if n * (Tmax - R.min()) > 400000:
        return 0.0                                     # keep the run time bounded
    col = {}
    for i in range(n):
        for t in range(int(R[i]), Tmax):
            col[(i, t)] = len(col)
    nz = len(col)
    NV = nz + n
    ri = []; ci = []; va = []; bub = []

    def add(ent, rhs):
        r = len(bub)
        for c, v in ent:
            ri.append(r); ci.append(c); va.append(v)
        bub.append(rhs)

    for t in range(Tmax):                                                  # (1)
        ent = [(col[(i, t)], d[i]) for i in range(n) if R[i] <= t and d[i] > 0]
        if ent:
            add(ent, C)
    for i in range(n):                                                     # (2)
        add([(col[(i, t)], -1.0) for t in range(int(R[i]), Tmax)], -float(P[i]))
    for i in range(n):                                                     # (3)
        for t in range(max(int(R[i]), int(D[i])), Tmax):
            add([(col[(i, t)], float(t + 1 - D[i])), (nz + i, -1.0)], 0.0)
    for i in range(n):                                                     # (4)
        for t in range(max(int(R[i]), int(D[i] - P[i])), min(Tmax, int(R[i] + P[i]))):
            c = float(t + P[i] - D[i] + 1)
            if c > 0:
                add([(col[(i, t)], -c), (nz + i, -1.0)], -c)
    for (a, b) in cuts:                                                    # (5)
        for i in range(n):
            L = min(b, R[i] + P[i]) - max(a, D[i] - P[i])          # compulsory part
            F = (P[i] - max(0, a - R[i]) - max(0, D[i] - b)) if D[i] >= a else 0
            rhs = max(L, F)
            if rhs <= 0:
                continue
            ent = [(col[(i, t)], -1.0) for t in range(max(a, int(R[i])), min(b, Tmax))]
            if ent:
                add(ent + [(nz + i, -1.0)], -float(rhs))
    A = sp.coo_matrix((va, (ri, ci)), shape=(len(bub), NV)).tocsr()
    c = np.zeros(NV); c[nz:] = 1.0
    res = linprog(c, A_ub=A, b_ub=np.asarray(bub),
                  bounds=[(0, 1)] * nz + [(0, None)] * n, method="highs",
                  options={"time_limit": time_budget})
    return float(res.fun) if res.success and res.fun is not None else 0.0


# ---------------------------------------------------------------------------
# per-instance driver
# ---------------------------------------------------------------------------

RHO_GRID = (1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.6, 0.5)


def q_candidates(Bset, m):
    """Candidate bay subsets Q for P3 (unions of the distinct B_i, plus all bays)."""
    distinct = sorted(set(Bset), key=len)
    cands = {tuple(range(m))}
    for s in distinct:
        cands.add(tuple(sorted(s)))
    for i, s1 in enumerate(distinct):
        for s2 in distinct[i + 1:]:
            cands.add(tuple(sorted(set(s1) | set(s2))))
    return sorted(cands, key=len)


def lb_z1(inst, geo, Bset, delta=1.0, use_lp=True, verbose=False):
    bays = [(int(b["width"]), int(b["height"])) for b in inst["bays"]]
    m = len(bays)
    R = np.array([b["release_time"] for b in inst["blocks"]], float)
    D = np.array([b["due_date"] for b in inst["blocks"]], float)
    P = np.array([b["processing_time"] for b in inst["blocks"]], float)
    best = 0.0; tag = "-"; best_cfg = None
    tabs = slab_tables(inst, geo, Bset)
    for Q in q_candidates(Bset, m):
        elig = np.array([i for i in range(len(Bset)) if set(Bset[i]) <= set(Q)], int)
        if not len(elig):
            continue

        def res(thick, Q=Q):
            d = slab_demand(tabs, Bset, thick)
            return d, delta * sum(bays[j][0] * thick[j] for j in Q)

        # Phase 1: matched-thickness grid + exhaustive per-bay coordinate ascent,
        # driven by the cheap engine W.
        cands = [tuple(max(1, int(round(rho * H))) for (_, H) in bays) for rho in RHO_GRID]
        bth, bval = cands[0], -1.0
        for th in cands:
            d, C = res(th)
            v = engine_W(d, R, D, P, C, elig)[0]
            if v > bval:
                bth, bval = th, v
        for _ in range(3):
            moved = False
            for j in range(m):
                for t in range(1, bays[j][1] + 1):
                    th = tuple(t if k == j else bth[k] for k in range(m))
                    if th == bth:
                        continue
                    d, C = res(th)
                    v = engine_W(d, R, D, P, C, elig)[0]
                    if v > bval + 1e-9:
                        bth, bval, moved = th, v, True
            if not moved:
                break
        # Phase 2: all engines on the grid plus the ascent winner
        for th in sorted(set(cands) | {bth}):
            d, C = res(th)
            for lab, fn in (("W", engine_W), ("F", engine_F)):
                v, win, cuts = fn(d, R, D, P, C, elig)
                if v > best:
                    best, tag = v, f"{lab} t={th} Q={Q} win={win}"
                    best_cfg = (d, C, elig, cuts)
            vr = engine_R(d, R, D, P, C, elig)
            if vr > best:
                best, tag = vr, f"R t={th} Q={Q}"
                best_cfg = (d, C, elig, [])
    if use_lp:
        if best_cfg is None:               # nothing violated: run L on the P1 resource
            thick = [H for (_, H) in bays]
            d = slab_demand(tabs, Bset, thick)
            C = delta * sum(W * H for (W, H) in bays)
            best_cfg = (d, C, np.arange(len(Bset)), [])
        d, C, elig, cuts = best_cfg
        vl = engine_L(d, R, D, P, C, elig, cuts[:120], time_budget=25.0)
        if vl > best:
            best, tag = vl, "L " + tag
    return best, tag


def diagnostics(inst, geo, Bset):
    """Peak forced layer-0 density and horizon utilisation (measured, not bounds)."""
    bays = [(int(b["width"]), int(b["height"])) for b in inst["bays"]]
    d = slab_demand(slab_tables(inst, geo, Bset), Bset, [H for (_, H) in bays])
    C = float(sum(W * H for (W, H) in bays))
    R = np.array([b["release_time"] for b in inst["blocks"]], float)
    D = np.array([b["due_date"] for b in inst["blocks"]], float)
    P = np.array([b["processing_time"] for b in inst["blocks"]], float)
    peak = 0.0
    for tau in range(int(min((D - P).min(), 0)), int((R + P).max()) + 1):
        peak = max(peak, float(d[(D - P <= tau) & (tau < R + P)].sum()) / C)
    span = max(1.0, float(D.max() - R.min()))
    util = float((d * P).sum()) / (C * span)
    return peak, util


def main(results_dir=None, extra_dirs=()):
    src = Path(results_dir) if results_dir else SHIPPED
    ours = {}
    for f in src.glob("res_prob_*.json"):
        r = json.loads(f.read_text())
        ours[r["instance"]] = r
    if not ours:
        raise SystemExit(f"no res_prob_*.json under {src} -- pass --results <DIR>")
    print(f"# reference solutions: {src}  ({len(ours)} instances)")
    hdr = (f"{'instance':<9}{'ours_obj':>13}{'old_LB':>13}{'new_LB':>13}"
           f"{'ours/LB':>9}{'ours_Z1':>9}{'LB_Z1':>8}{'peak':>7}{'util':>6}  tight")
    print(hdr); print("-" * len(hdr))
    rows = []
    for i in range(1, 41):
        p = BASE / ("train 2" if i <= 20 else "train") / f"prob_{i}.json"
        inst = json.loads(p.read_text())
        name = f"prob_{i}"
        w1 = float(inst.get("weights", {}).get("w1", 1))
        geo = build_geometry(inst, 0)
        Bset = bay_sets(inst, geo)
        z1, tag = lb_z1(inst, geo, Bset)
        z1 = math.ceil(z1 - 1e-9)                    # Z1 is a non-negative integer
        la, _, _ = lb_assign(inst)
        old = w1 * lb_tardiness(inst) + la
        new = w1 * z1 + la
        peak, util = diagnostics(inst, geo, Bset)
        o = ours.get(name, {})
        oo, oz1 = o.get("objective"), o.get("obj1")
        rows.append(dict(name=name, ours=oo, ours_z1=oz1, old=old, new=new,
                         z1=z1, tag=tag, peak=peak, util=util, w1=w1, la=la))
        rat = "" if not oo or new <= 0 else f"{oo / new:.2f}"
        print(f"{name:<9}{oo:>13,.0f}{old:>13,.0f}{new:>13,.0f}{rat:>9}"
              f"{oz1:>9,.0f}{z1:>8}{peak:>7.2f}{util:>6.2f}  {tag}", flush=True)

    if extra_dirs:
        print("\nCROSS-CHECK: the same bounds against every other checker-verified")
        print("solution set available (a valid LB must hold for ALL feasible solutions).")
        by = {r["name"]: r for r in rows}
        print(f"{'result set':<26}{'n':>4}{'LB>obj':>8}{'LB_Z1>Z1':>10}{'total obj':>16}")
        for dname in extra_dirs:
            dd = Path(dname)
            n = v1 = v2 = 0; tot = 0.0
            for f in sorted(dd.glob("res_prob_*.json")):
                r = json.loads(f.read_text())
                b = by.get(r.get("instance"))
                if b is None or not r.get("feasible"):
                    continue
                n += 1; tot += r["objective"]
                v1 += b["new"] > r["objective"] + 1e-6
                v2 += b["z1"] > r["obj1"] + 1e-6
            print(f"{dd.name if dd.name else dname:<26}{n:>4}{v1:>8}{v2:>10}{tot:>16,.0f}")

    print("\nSANITY: a bound above the achieved (checker-verified) objective is a BUG.")
    bad = [r for r in rows if r["ours"] is not None and r["new"] > r["ours"] + 1e-6]
    badz = [r for r in rows if r["ours_z1"] is not None and r["z1"] > r["ours_z1"] + 1e-6]
    print(f"  LB > ours on {len(bad)} / {len(rows)} instances: "
          f"{[r['name'] for r in bad] or 'NONE -- all bounds consistent'}")
    print(f"  LB_Z1 > ours_Z1 on {len(badz)} / {len(rows)} instances: "
          f"{[r['name'] for r in badz] or 'NONE -- all bounds consistent'}")

    for lab, sel in (("prob_1-20  (loose)", rows[:20]), ("prob_21-40 (congested)", rows[20:])):
        so = sum(r["ours"] for r in sel)
        sn = sum(r["new"] for r in sel)
        sold = sum(r["old"] for r in sel)
        sz = sum(r["ours_z1"] for r in sel)
        sl = sum(r["z1"] for r in sel)
        print(f"\n{lab}: ours={so:,.0f} old_LB={sold:,.0f} new_LB={sn:,.0f} "
              f"ratio={so / sn if sn else float('inf'):.2f} | Z1 ours={sz:,.0f} LB={sl:,.0f}")
    nz = [r["name"] for r in rows if r["z1"] > 0]
    print(f"\nInstances with a PROVEN non-zero Z1: {nz or 'none'}")
    tight = sorted((r for r in rows if r["ours"]), key=lambda r: r["ours"] / max(r["new"], 1e-9))
    print("Tightest (near-optimal):  " +
          ", ".join(f"{r['name']}={r['ours'] / max(r['new'], 1e-9):.2f}x" for r in tight[:6]))
    print("Largest certified gap:    " +
          ", ".join(f"{r['name']}={r['ours'] / max(r['new'], 1e-9):.0f}x" for r in tight[-6:][::-1]))

    print("\nZ1-ELIMINATION UPSIDE (w1*(ours_Z1 - LB_Z1) as a share of our objective);")
    print("low `peak` means the forced-density argument is far from binding, so the")
    print("tardiness is the most likely to be removable by better packing/sequencing.")
    print(f"{'instance':<9}{'share':>8}{'w1*dZ1':>14}{'ours_Z1':>9}{'LB_Z1':>7}{'peak':>7}")
    for r in sorted(rows, key=lambda r: -(r["w1"] * ((r["ours_z1"] or 0) - r["z1"]))
                    / max(r["ours"] or 1.0, 1.0)):
        gain = r["w1"] * ((r["ours_z1"] or 0) - r["z1"])
        if gain <= 0:
            continue
        print(f"{r['name']:<9}{gain / r['ours'] * 100:>7.1f}%{gain:>14,.0f}"
              f"{r['ours_z1']:>9,.0f}{r['z1']:>7}{r['peak']:>7.2f}")

    print("\nDIAGNOSTIC -- NOT A BOUND: LB_Z1 under the unproven hypothesis that at most")
    print("a fraction delta of a bay's area can be occupied at any instant (engines W/F/R).")
    print(f"{'instance':<9}{'ours_Z1':>9}" + "".join(f"{'d=' + str(x):>9}"
                                                    for x in (1.0, 0.7, 0.6, 0.5)))
    for i in range(21, 41):
        p = BASE / "train" / f"prob_{i}.json"
        inst = json.loads(p.read_text())
        geo = build_geometry(inst, 0)
        Bset = bay_sets(inst, geo)
        vals = [math.ceil(lb_z1(inst, geo, Bset, delta=dl, use_lp=False)[0] - 1e-9)
                for dl in (1.0, 0.7, 0.6, 0.5)]
        print(f"prob_{i:<4}{ours[f'prob_{i}']['obj1']:>9,.0f}" +
              "".join(f"{v:>9,}" for v in vals), flush=True)


def selftest():
    """Exactness check on an instance whose optimum is known by hand.

    One 10x10 bay, five 5x5 square blocks (area 25 each), R=0, D=P=2.  Four
    squares tile the bay exactly, so a zero-tardiness schedule for four of them
    exists; the fifth cannot be co-present (5*25 = 125 > 100), so it must enter
    at 2 and exit at 4 -> Z1_opt = 2 exactly (Z2 = Z3 = 0 with a single bay).
    The bound must therefore return exactly 2.0: not more (validity) and not
    less (tightness on this instance).
    """
    sq = [[0, 0], [5, 0], [5, 5], [0, 5]]
    blk = dict(release_time=0, due_date=2, processing_time=2, workload=1,
               bay_preferences=[0], shape=[dict(orientation=0, layers=[sq])])
    inst = dict(name="selftest", bays=[dict(width=10, height=10)],
                blocks=[dict(blk) for _ in range(5)],
                weights=dict(w1=1, w2=1, w3=1))
    geo = build_geometry(inst, 0)
    Bset = bay_sets(inst, geo)
    v, tag = lb_z1(inst, geo, Bset)
    print(f"selftest: LB_Z1 = {v:.6f} (exact optimum 2)  [{tag}]")
    assert abs(v - 2.0) < 1e-6, "engine F/W is not exact on the 5-squares instance"
    inst4 = dict(inst, blocks=[dict(blk) for _ in range(4)])
    geo4 = build_geometry(inst4, 0)
    v4, _ = lb_z1(inst4, geo4, bay_sets(inst4, geo4))
    print(f"selftest: 4 squares (feasible on time) LB_Z1 = {v4:.6f} (must be 0)")
    assert v4 <= 1e-9
    print("selftest PASS")


if __name__ == "__main__":
    t0 = time.time()
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
        raise SystemExit(0)
    rd = None
    if "--results" in sys.argv:
        rd = sys.argv[sys.argv.index("--results") + 1]
    extra = []
    if "--crosscheck" in sys.argv:                 # extra solution sets to validate against
        extra = [a for a in sys.argv[sys.argv.index("--crosscheck") + 1:]
                 if not a.startswith("--")]
    main(rd, extra)
    print(f"\ntotal wall time {time.time() - t0:.0f}s")
