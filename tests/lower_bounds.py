"""Rigorous lower bounds on the OGC 2026 objective, per instance.

Two provable relaxations, combined additively (valid because the objective is a
sum of three nonneg terms, each bounded below independently):

LB = w1 * LB_Z1  +  LP( w2*Z2 + w3*Z3 )

--- LB_Z1: energetic / area-capacity tardiness bound -----------------------
For every block i let a_i = min_o area(layer 0 of orientation o) and let
C = sum_j W_j*H_j be the total bay area.  The competition's same-layer
collision constraint (utils.check_collisions, layer index 0) forces, at every
instant t and in every bay j, the layer-0 polygons of co-present blocks to be
interior-disjoint and inside the bay, hence

    sum_{i present at t} a_i  <=  C            (summed over bays)

so the resource "layer-0 area" has capacity C.  Fix r,d and let
S = {i : R_i >= r, D_i <= d}.  No block of S can start before r, so the total
area-time the resource can deliver in [r, T] is at most C*(T-r).  Since S
demands E = sum_{i in S} a_i*P_i, the last completion T_last among S obeys
C*(T_last - r) >= E.  Every i in S has D_i <= d, therefore

    Z1 >= max_i T_i >= T_last - d >= (E - C*(d-r)) / C.

Maximizing over all (r,d) in (releases x due dates) gives LB_Z1.

--- LP(w2*Z2 + w3*Z3): assignment relaxation ------------------------------
Z2 and Z3 depend only on the assignment vector (utils L1404-1414).  With
x_ij in [0,1], sum_j x_ij = 1, load_j = sum_i L_i x_ij, u_j = avgArea/area_j:
    min w2*(M - m) + w3*sum_ij regret_ij x_ij
    s.t. u_j*load_j <= M,  u_j*load_j >= m  for all j.
Any integral solution is LP-feasible, so the LP optimum is a valid lower
bound.  Z2 = floor(max pairwise gap) >= floor(LP gap) by monotonicity of floor.
"""
import json, glob, math, sys
from pathlib import Path
from shapely.geometry import Polygon
import numpy as np
from scipy.optimize import linprog

def layer0_area(block):
    best = None
    for shape in block["shape"]:
        lays = [l for l in shape["layers"] if l]
        if not lays:
            continue
        try:
            p = Polygon([(float(x), float(y)) for x, y in lays[0]])
            if not p.is_valid:
                p = p.buffer(0)
            a = float(p.area)
        except Exception:
            continue
        if a > 0 and (best is None or a < best):
            best = a
    return best or 0.0

def lb_tardiness(inst):
    blocks = inst["blocks"]
    C = float(sum(b["width"] * b["height"] for b in inst["bays"]))
    a = [layer0_area(b) for b in blocks]
    R = [int(b["release_time"]) for b in blocks]
    D = [int(b["due_date"]) for b in blocks]
    P = [int(b["processing_time"]) for b in blocks]
    rs, ds = sorted(set(R)), sorted(set(D))
    best = 0.0
    for r in rs:
        idx = [i for i in range(len(blocks)) if R[i] >= r]
        if not idx:
            continue
        for d in ds:
            if d <= r:
                continue
            E = sum(a[i] * P[i] for i in idx if D[i] <= d)
            if E <= 0:
                continue
            v = (E - C * (d - r)) / C
            if v > best:
                best = v
    return best

def lb_assign(inst):
    blocks, bays = inst["blocks"], inst["bays"]
    n, m = len(blocks), len(bays)
    w = inst.get("weights", {})
    w2, w3 = float(w.get("w2", 1)), float(w.get("w3", 1))
    if m < 2:
        # Z2 = 0 by definition (utils L1428); Z3 minimised at 0 (single bay)
        return 0.0, 0.0, 0.0
    areas = [float(b["width"] * b["height"]) for b in bays]
    avg = sum(areas) / m
    u = [avg / A for A in areas]
    L = [float(b["workload"]) for b in blocks]
    reg = [[max(b["bay_preferences"]) - b["bay_preferences"][j] for j in range(m)]
           for b in blocks]
    # variables: x (n*m), M, mm
    nv = n * m + 2
    c = np.zeros(nv)
    for i in range(n):
        for j in range(m):
            c[i * m + j] = w3 * reg[i][j]
    c[-2], c[-1] = w2, -w2                     # +w2*M - w2*mm
    Aeq = np.zeros((n, nv)); beq = np.ones(n)
    for i in range(n):
        Aeq[i, i * m:(i + 1) * m] = 1.0
    Aub = np.zeros((2 * m, nv)); bub = np.zeros(2 * m)
    for j in range(m):
        for i in range(n):
            Aub[j, i * m + j] = u[j] * L[i]     # u_j*load_j - M <= 0
            Aub[m + j, i * m + j] = -u[j] * L[i]  # -u_j*load_j + mm <= 0
        Aub[j, -2] = -1.0
        Aub[m + j, -1] = 1.0
    bounds = [(0, 1)] * (n * m) + [(0, None), (0, None)]
    res = linprog(c, A_ub=Aub, b_ub=bub, A_eq=Aeq, b_eq=beq, bounds=bounds,
                  method="highs")
    if not res.success:
        return 0.0, 0.0, 0.0
    x = res.x
    gap = max(0.0, x[-2] - x[-1])
    z3 = sum(reg[i][j] * x[i * m + j] for i in range(n) for j in range(m))
    return w2 * math.floor(gap) + w3 * z3, math.floor(gap), z3

if __name__ == "__main__":
    base = Path("/Users/vedantmoghe/Downloads/optichallenge")
    ours = {}
    for f in glob.glob(str(base / "../../private/tmp" / "**"), recursive=False):
        pass
    # our shipped-build objectives (gateB v21 arm == v2.2 search-identical)
    SC = Path("/private/tmp/claude-501/-Users-vedantmoghe-Downloads-optichallenge/"
              "828d3afa-14fe-4679-bfb6-c94c0e22ac75/scratchpad/gateB/v21")
    for f in SC.glob("res_prob_*.json"):
        r = json.loads(f.read_text()); ours[r["instance"]] = r
    rows = []
    for i in range(1, 41):
        p = base / ("train 2" if i <= 20 else "train") / f"prob_{i}.json"
        inst = json.loads(p.read_text())
        w1 = float(inst.get("weights", {}).get("w1", 1))
        lz1 = lb_tardiness(inst)
        la, gap, z3 = lb_assign(inst)
        lb = w1 * lz1 + la
        o = ours.get(f"prob_{i}", {}).get("objective")
        rows.append((f"prob_{i}", lb, o, lz1, gap, z3,
                     ours.get(f"prob_{i}", {}).get("obj1")))
        print(f"prob_{i:<3} LB={lb:>14,.0f}  ours={o if o is None else format(o, ',.0f'):>14}"
              f"  ratio={'' if not o or lb<=0 else format(o/lb, '.2f'):>6}"
              f"  LB_Z1={lz1:>8.1f} ours_Z1={rows[-1][6]}", flush=True)
    tot_lb = sum(r[1] for r in rows)
    tot_ours = sum(r[2] for r in rows if r[2])
    print(f"\nTOTAL LB={tot_lb:,.0f}  ours={tot_ours:,.0f}  ratio={tot_ours/tot_lb:.2f}")
