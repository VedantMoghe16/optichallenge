"""Differential soundness + throughput gate for submission/raster_kernel.py.

SOUNDNESS (must be zero false-accepts): for random pairs of real training-block
placements, compare the kernel's same-layer verdict and crane verdict against
the official utils.py primitives (check_collisions / check_entry).  A kernel
ACCEPT that utils rejects is fatal.  Kernel REJECT + utils accept is allowed
(conservative) but measured.
"""
import argparse, json, math, random, sys, time
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "submission"))
sys.path.insert(0, str(REPO / "ogc2026" / "baseline"))
import utils
from raster_kernel import RasterOrient, BayRaster, DEFAULT_S
from shapely.geometry import Polygon

def layer_polys(block, oi):
    lays = [l for l in block["shape"][oi]["layers"] if l]
    rx, ry = lays[0][0]
    out = []
    for l in lays:
        p = Polygon([(float(x) - rx, float(y) - ry) for x, y in l])
        if not p.is_valid:
            p = p.buffer(0)
        out.append(None if p.is_empty else p)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("-S", type=int, default=DEFAULT_S)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    files = sorted(list((REPO / "train 2").glob("prob_*.json")) +
                   list((REPO / "train").glob("prob_*.json")))
    stats = {"cases": 0, "kernel_accept": 0, "false_accept": 0,
             "false_reject": 0, "utils_accept": 0,
             "crane_cases": 0, "crane_false_accept": 0}
    t_kernel = t_utils = 0.0
    for _ in range(a.cases):
        inst = json.loads(rng.choice(files).read_text())
        bays, blocks = inst["bays"], inst["blocks"]
        j = rng.randrange(len(bays))
        bay = bays[j]; ub = utils.Bay.from_dict(bay, j)
        i1, i2 = rng.randrange(len(blocks)), rng.randrange(len(blocks))
        o1 = rng.randrange(len(blocks[i1]["shape"]))
        o2 = rng.randrange(len(blocks[i2]["shape"]))
        try:
            g1 = RasterOrient(layer_polys(blocks[i1], o1), a.S)
            g2 = RasterOrient(layer_polys(blocks[i2], o2), a.S)
        except ValueError:
            continue
        grid = BayRaster(bay["width"], bay["height"], a.S,
                         n_layers=max(4, g1.n_layers, g2.n_layers))
        # place block 2 somewhere legal, then probe block 1 nearby (near-contact)
        w2 = None
        for _try in range(20):
            x2 = rng.randrange(0, max(1, bay["width"]))
            y2 = rng.randrange(0, max(1, bay["height"]))
            w2 = grid.window(g2, x2, y2)
            if w2 is not None:
                break
        if w2 is None:
            continue
        grid.stamp(g2, x2, y2)
        b2 = utils.Block(block_id=i2, block_data=blocks[i2], x=x2, y=y2, orient_idx=o2)
        # probe positions clustered around block 2 (bias to near contact)
        bb = b2.bounding_rect()
        x1 = int(round(bb[2] + rng.randint(-3, 3)))
        y1 = int(round(bb[1] + rng.randint(-3, 3)))
        if grid.window(g1, x1, y1) is None:
            continue
        b1 = utils.Block(block_id=i1, block_data=blocks[i1], x=x1, y=y1, orient_idx=o1)
        if not ub.contains_block(b1):
            continue
        stats["cases"] += 1
        t0 = time.perf_counter(); k_col = grid.collides(g1, x1, y1); t_kernel += time.perf_counter() - t0
        t0 = time.perf_counter(); u_col = bool(utils.check_collisions(ub, [b1, b2])); t_utils += time.perf_counter() - t0
        if not k_col:
            stats["kernel_accept"] += 1
            if u_col:
                stats["false_accept"] += 1
                print(f"FALSE ACCEPT (same-layer): inst={inst['name']} bay={j} "
                      f"b1={i1}/o{o1}@({x1},{y1}) b2={i2}/o{o2}@({x2},{y2})")
        if not u_col:
            stats["utils_accept"] += 1
            if k_col:
                stats["false_reject"] += 1
        # crane direction: kernel crane verdict vs utils.check_entry
        stats["crane_cases"] += 1
        k_crane = grid.crane_blocked(g1, x1, y1)
        u_crane = bool(utils.check_entry(ub, [b2], b1, fast=True))
        if not k_crane and u_crane:
            stats["crane_false_accept"] += 1
            print(f"FALSE ACCEPT (crane): inst={inst['name']} b1={i1}/o{o1}@({x1},{y1}) "
                  f"b2={i2}/o{o2}@({x2},{y2})")
    n = max(1, stats["cases"])
    print(json.dumps(stats, indent=1))
    print(f"false_accepts total = {stats['false_accept'] + stats['crane_false_accept']} (REQUIRED 0)")
    print(f"false_reject_rate among utils-accepted = "
          f"{stats['false_reject']/max(1,stats['utils_accept']):.4f}")
    print(f"speed: kernel {1e6*t_kernel/n:.1f} us/test | utils {1e6*t_utils/n:.1f} us/test "
          f"| speedup {t_utils/max(1e-9,t_kernel):.1f}x")
    return 1 if (stats["false_accept"] + stats["crane_false_accept"]) else 0

if __name__ == "__main__":
    sys.exit(main())
