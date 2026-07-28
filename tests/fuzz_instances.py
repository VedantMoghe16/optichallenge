"""Adversarial instance fuzzer for the OGC 2026 kestrel solver.

Generates randomized synthetic instances spanning (and exceeding) the plausible
hidden-instance envelope, runs the full solver via a subprocess with a hard
watchdog, and asserts the three survival properties:

    1. returns within the time limit,
    2. output passes the official checker (feasible),
    3. no exception / no crash.

Any violation archives the full repro (instance JSON + result + seed) under
fuzz_failures/ and is counted in the running summary.

Usage:
    python tests/fuzz_instances.py --minutes 300 --lane A --seed 1
Lanes only affect the RNG stream so parallel lanes explore different cases.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAIL_DIR = REPO / "fuzz_failures"
PY = sys.executable


# ---------------------------------------------------------------------------
# Geometry generation
# ---------------------------------------------------------------------------

def rand_polygon(rng, w, h, nv=None, concave=False):
    """Random simple polygon inside a w x h box (radial construction)."""
    nv = nv or rng.randint(3, 10)
    cx, cy = w / 2.0, h / 2.0
    angles = sorted(rng.uniform(0, 2 * math.pi) for _ in range(nv))
    pts = []
    for a in angles:
        r = rng.uniform(0.35, 1.0) if concave else rng.uniform(0.75, 1.0)
        px = cx + math.cos(a) * cx * r
        py = cy + math.sin(a) * cy * r
        pts.append([round(px, 4), round(py, 4)])
    # dedupe consecutive near-identical points
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) > 1e-3 or abs(p[1] - out[-1][1]) > 1e-3:
            out.append(p)
    return out if len(out) >= 3 else [[0.0, 0.0], [w, 0.0], [w / 2.0, h]]


def transform(pts, angle_deg, anchor_first=True):
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    rot = [[round(x * c - y * s, 4), round(x * s + y * c, 4)] for x, y in pts]
    if anchor_first:
        dx, dy = rot[0]
        rot = [[round(x - dx, 4), round(y - dy, 4)] for x, y in rot]
    return rot


def make_block(rng, bays, style):
    """One block dict; guaranteed to fit at least one bay in orientation 0."""
    bay = rng.choice(bays)
    max_w = max(2.0, bay["width"] * rng.choice([0.08, 0.15, 0.3, 0.6, 0.95]))
    max_h = max(2.0, bay["height"] * rng.choice([0.15, 0.3, 0.5, 0.8, 0.95]))
    if style == "sliver":
        base = [[0.0, 0.0], [round(max_w, 4), 0.02], [round(max_w * 0.5, 4), 0.35]]
    elif style == "boxfill":
        base = [[0.0, 0.0], [round(max_w, 4), 0.0],
                [round(max_w, 4), round(max_h, 4)], [0.0, round(max_h, 4)]]
    else:
        base = rand_polygon(rng, max_w, max_h,
                            concave=(style == "concave"))
    # layers: pyramid / mushroom / identical / single
    k = rng.choice([1, 1, 2, 2, 2, 3, 4])
    kind = rng.choice(["pyr", "mush", "same"])
    layers0 = [base]
    for _ in range(k - 1):
        f = {"pyr": rng.uniform(0.4, 0.9), "mush": rng.uniform(1.02, 1.5),
             "same": 1.0}[kind]
        prev = layers0[-1]
        cx = sum(p[0] for p in prev) / len(prev)
        cy = sum(p[1] for p in prev) / len(prev)
        layers0.append([[round(cx + (x - cx) * f, 4), round(cy + (y - cy) * f, 4)]
                        for x, y in prev])
    # anchor layer0 first vertex to (0,0) sometimes; leave shifted sometimes
    if rng.random() < 0.8:
        dx, dy = layers0[0][0]
        layers0 = [[[round(x - dx, 4), round(y - dy, 4)] for x, y in lay]
                   for lay in layers0]
    n_orient = rng.choice([1, 2, 4, 8])
    shape = []
    oid = 0
    for i in range(n_orient):
        # orientation 0 stays axis-aligned so the block provably fits the
        # bay it was sized for (the competition guarantees every block has
        # a feasible placement; unplaceable blocks = malformed instance).
        ang = 0 if i == 0 else rng.choice([0, 45, 90, 135, 180, 225, 270, 315])
        shape.append({
            "orientation": oid,
            "layers": [transform(lay, ang, anchor_first=(i == 0))
                       for lay in layers0],
        })
        oid += rng.choice([1, 1, 2, 5])   # non-contiguous orientation ids
    # hard guarantee: orientation-0 all-layer bbox fits the sized-for bay
    all_pts = [p for lay in shape[0]["layers"] for p in lay]
    bw = max(p[0] for p in all_pts) - min(p[0] for p in all_pts)
    bh = max(p[1] for p in all_pts) - min(p[1] for p in all_pts)
    if not any(bw <= by["width"] - 1 and bh <= by["height"] - 1
               for by in bays):
        # degenerate corner (mushroom growth overflow): shrink to smallest bay
        smallest = min(bays, key=lambda b: b["width"] * b["height"])
        fx = (smallest["width"] - 2) / max(bw, 1e-6)
        fy = (smallest["height"] - 2) / max(bh, 1e-6)
        f = max(0.05, min(fx, fy, 1.0))
        for s in shape:
            s["layers"] = [[[round(x * f, 4), round(y * f, 4)]
                            for x, y in lay] for lay in s["layers"]]
    r = rng.choice([0, 0, rng.randint(0, 60), rng.randint(0, 500)])
    p = rng.randint(1, 40)
    due_style = rng.random()
    if due_style < 0.15:
        d = r                       # due before completion possible
    elif due_style < 0.25:
        d = rng.randint(0, max(1, r - 1)) if r > 0 else 0   # due < release
    else:
        d = r + p + rng.randint(0, 30)
    return {
        "release_time": r, "due_date": d, "processing_time": p,
        "workload": rng.choice([0, 1, rng.randint(1, 50), 500]),
        "bay_preferences": _prefs(rng, len(bays)),
        "shape": shape,
    }


def _prefs(rng, m):
    if m == 1:
        return [100]
    cuts = sorted(rng.randint(0, 100) for _ in range(m - 1))
    vals = [a - b for a, b in zip(cuts + [100], [0] + cuts)]
    rng.shuffle(vals)
    return vals


def make_instance(rng, idx):
    profile = rng.choice(["tiny", "small", "medium", "large", "huge",
                          "monobay", "manybay", "dup", "congested"])
    if profile == "tiny":
        m, n = rng.randint(1, 2), rng.randint(1, 6)
    elif profile == "small":
        m, n = rng.randint(2, 3), rng.randint(10, 50)
    elif profile == "medium":
        m, n = rng.randint(2, 4), rng.randint(80, 200)
    elif profile == "large":
        m, n = rng.randint(3, 5), rng.randint(250, 400)
    elif profile == "huge":
        m, n = rng.randint(4, 6), rng.randint(450, 700)
    elif profile == "monobay":
        m, n = 1, rng.randint(20, 150)
    elif profile == "manybay":
        m, n = 8, rng.randint(60, 160)
    elif profile == "dup":
        m, n = rng.randint(2, 3), rng.randint(50, 200)
    else:  # congested: everything released at once, short dues
        m, n = rng.randint(2, 3), rng.randint(80, 220)

    bays = [{"width": rng.randint(12, 200), "height": rng.randint(12, 30)}
            for _ in range(m)]
    styles = ["plain", "plain", "concave", "sliver", "boxfill"]
    if profile == "dup":
        proto = make_block(rng, bays, rng.choice(styles))
        blocks = [json.loads(json.dumps(proto)) for _ in range(n)]
        for b in blocks:
            b["release_time"] = rng.randint(0, 30)
            b["due_date"] = b["release_time"] + b["processing_time"] \
                + rng.randint(0, 10)
    else:
        blocks = [make_block(rng, bays, rng.choice(styles)) for _ in range(n)]
    if profile == "congested":
        for b in blocks:
            b["release_time"] = 0
            b["due_date"] = b["processing_time"] + rng.randint(0, 5)

    wstyle = rng.random()
    if wstyle < 0.55:
        weights = {"w1": rng.choice([667, 3333, 13333, 29630]),
                   "w2": rng.randint(1, 10), "w3": rng.choice([13, 150, 600])}
    elif wstyle < 0.7:
        weights = {"w1": 0, "w2": rng.randint(1, 10), "w3": rng.randint(0, 600)}
    elif wstyle < 0.8:
        weights = {"w1": rng.randint(0, 100), "w2": 10 ** rng.randint(3, 6),
                   "w3": rng.randint(0, 100)}
    elif wstyle < 0.9:
        weights = {"w1": 10 ** 9, "w2": 0, "w3": 0}
    else:
        weights = {"w1": 0, "w2": 0, "w3": 0}
    return {"name": f"fuzz_{idx}", "bays": bays, "blocks": blocks,
            "weights": weights}, profile


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

DRIVER = r"""
import json, sys, time

def main():
    sys.path.insert(0, sys.argv[4])
    import myalgorithm, utils
    prob = json.load(open(sys.argv[1]))
    tl = float(sys.argv[2])
    t0 = time.time()
    sol = myalgorithm.algorithm(prob, timelimit=tl)
    elapsed = time.time() - t0
    r = utils.check_feasibility(prob, sol)
    json.dump({"elapsed": elapsed, "feasible": bool(r["feasible"]),
               "objective": r["objective"], "stage": r.get("stage"),
               "violations": r.get("violations", [])[:3]},
              open(sys.argv[3], "w"))

# The __main__ guard is mandatory: macOS spawn re-imports this script in
# every portfolio worker; without the guard each worker would recursively
# run the whole driver (process bomb).  Linux fork (the server) is immune.
if __name__ == "__main__":
    main()
"""


def run_case(inst, timelimit, workdir):
    inst_f = workdir / "inst.json"
    out_f = workdir / "out.json"
    drv_f = workdir / "drv.py"
    inst_f.write_text(json.dumps(inst))
    drv_f.write_text(DRIVER)
    if out_f.exists():
        out_f.unlink()
    t0 = time.time()
    try:
        proc = subprocess.run(
            [PY, str(drv_f), str(inst_f), str(timelimit), str(out_f),
             str(workdir)],
            timeout=timelimit + 40, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return {"verdict": "HANG", "elapsed": time.time() - t0}
    if proc.returncode != 0:
        return {"verdict": "CRASH", "stderr": proc.stderr[-2000:]}
    if not out_f.exists():
        return {"verdict": "NO_OUTPUT", "stderr": proc.stderr[-2000:]}
    res = json.loads(out_f.read_text())
    if not res["feasible"]:
        return {"verdict": "INFEASIBLE", **res}
    if res["elapsed"] > timelimit + 0.25:
        return {"verdict": "OVERTIME", **res}
    return {"verdict": "OK", **res}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument(
        "--cases", type=int,
        help="optional exact case limit for a bounded smoke run",
    )
    ap.add_argument("--lane", default="A")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--solver-dir", type=Path,
                    default=REPO / "submission")
    ap.add_argument("--utils-dir", type=Path,
                    default=REPO / "ogc2026" / "baseline")
    args = ap.parse_args()

    rng = random.Random((args.seed << 16) ^ hash(args.lane) & 0xFFFF)
    FAIL_DIR.mkdir(exist_ok=True)
    end = time.time() + args.minutes * 60
    counts = {}
    i = 0
    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)
        # stage solver + checker once (immune to concurrent edits)
        (workdir / "myalgorithm.py").write_text(
            (args.solver_dir / "myalgorithm.py").read_text())
        (workdir / "utils.py").write_text(
            (args.utils_dir / "utils.py").read_text())
        while (
            time.time() < end
            and (args.cases is None or i < max(0, args.cases))
        ):
            i += 1
            inst, profile = make_instance(rng, f"{args.lane}{i}")
            n = len(inst["blocks"])
            tl = rng.choice([6, 10, 15, 20, 20.5, 25, 35, 45]) \
                if n <= 250 else rng.choice([20, 35, 60])
            res = run_case(inst, tl, workdir)
            v = res["verdict"]
            counts[v] = counts.get(v, 0) + 1
            counts["_cases"] = i
            if v != "OK":
                stamp = f"{args.lane}_{i}_{int(time.time())}_{v}"
                (FAIL_DIR / f"{stamp}.json").write_text(json.dumps(
                    {"instance": inst, "timelimit": tl, "result": res,
                     "profile": profile, "lane": args.lane,
                     "seed": args.seed}, indent=1))
                print(f"[{args.lane}#{i}] {v} archived: {stamp} "
                      f"(profile={profile} n={n} tl={tl})", flush=True)
            if i % 10 == 0:
                print(f"[{args.lane}] {json.dumps(counts)}", flush=True)
    print(f"[{args.lane}] FINAL {json.dumps(counts)}")


if __name__ == "__main__":
    main()
