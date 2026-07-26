#!/usr/bin/env python3
"""Differential test for Slot-B's layer-true pair predicate."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ogc2026" / "alg_tester"))
from utils import Bay, Block, check_collisions, check_entry, check_exit  # noqa: E402


def load_slot_b():
    path = ROOT / "submission" / "slot_b" / "myalgorithm.py"
    spec = importlib.util.spec_from_file_location("kestrel_slot_b", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fit_range(g, bay):
    x0, y0, x1, y1 = g.bbox
    return (math.ceil(-x0), math.floor(bay["width"] - x1),
            math.ceil(-y0), math.floor(bay["height"] - y1))


def checker_pair_safe(bay_data, block_a, block_b,
                      entry_a, exit_a, entry_b, exit_b):
    bay = Bay.from_dict(bay_data)
    if entry_a < exit_b and entry_b < exit_a:
        if check_collisions(bay, [block_a, block_b]):
            return False

    events = [
        (entry_a, 1, block_a.block_id, "A"),
        (exit_a, 0, block_a.block_id, "A"),
        (entry_b, 1, block_b.block_id, "B"),
        (exit_b, 0, block_b.block_id, "B"),
    ]
    events.sort()
    present = {}
    for _t, phase, _bid, who in events:
        target = block_a if who == "A" else block_b
        if phase == 1:
            if check_entry(bay, list(present.values()), target, fast=True):
                return False
            present[target.block_id] = target
        else:
            if check_exit(bay, list(present.values()), target, fast=True):
                return False
            present.pop(target.block_id, None)
    return True


def random_intervals(rng, pa, pb):
    mode = rng.randrange(6)
    if mode == 0:
        ea, eb = rng.randrange(0, 50), rng.randrange(0, 50)
        return ea, ea + pa, eb, eb + pb
    if mode == 1:  # same entry
        t = rng.randrange(0, 50)
        return t, t + pa, t, t + pb
    if mode == 2:  # same exit
        x = rng.randrange(max(pa, pb), 70)
        return x - pa, x, x - pb, x
    if mode == 3:  # A starts inside B
        eb = rng.randrange(0, 30)
        ea = eb + rng.randrange(1, max(2, pb))
        return ea, ea + pa, eb, eb + pb
    if mode == 4:  # B starts inside A
        ea = rng.randrange(0, 30)
        eb = ea + rng.randrange(1, max(2, pa))
        return ea, ea + pa, eb, eb + pb
    # Boundary reuse / near-disjoint.
    ea = rng.randrange(0, 40)
    xa = ea + pa
    eb = xa + rng.choice((-1, 0, 1))
    return ea, xa, eb, eb + pb


def run_instance(mod, path, samples, seed):
    # Production clears all id-keyed geometry caches at the start of every
    # solve.  Mirror that lifecycle here; otherwise CPython may reuse polygon
    # object ids after the previous instance is garbage-collected, creating a
    # test-harness-only stale-cache verdict.
    mod._MOVE_CACHE.clear()
    mod._PAIR_CACHE.clear()
    mod._LAYER_MOVE_CACHE.clear()
    mod._LAYER_PAIR_CACHE.clear()
    mod._ORIENT_CACHE.clear()
    prob = json.loads(path.read_text())
    geoms = mod._precompute_geometry(prob)
    rng = random.Random(seed)
    false_accept = false_reject = accepted = 0
    examples = []

    for _ in range(samples):
        bay_id = rng.randrange(len(prob["bays"]))
        bay_data = prob["bays"][bay_id]
        valid = [
            i for i, gs in enumerate(geoms)
            if any(mod._fits(g, bay_data) for g in gs)
        ]
        aid, bid = rng.sample(valid, 2)
        ga = rng.choice([g for g in geoms[aid] if mod._fits(g, bay_data)])
        gb = rng.choice([g for g in geoms[bid] if mod._fits(g, bay_data)])
        ax0, ax1, ay0, ay1 = fit_range(ga, bay_data)
        bx0, bx1, by0, by1 = fit_range(gb, bay_data)
        xa, ya = rng.randint(ax0, ax1), rng.randint(ay0, ay1)

        abb = mod._moved_bbox(ga, xa, ya)
        contacts_x = [
            math.ceil(abb[2] - gb.bbox[0]),
            math.floor(abb[0] - gb.bbox[2]),
            xa,
        ]
        contacts_y = [
            math.ceil(abb[3] - gb.bbox[1]),
            math.floor(abb[1] - gb.bbox[3]),
            ya,
        ]
        if ga.layer_bboxes and gb.layer_bboxes:
            la, lb = ga.layer_bboxes[0], gb.layer_bboxes[0]
            contacts_x.extend([
                math.ceil(xa + la[2] - lb[0]),
                math.floor(xa + la[0] - lb[2]),
            ])
            contacts_y.extend([
                math.ceil(ya + la[3] - lb[1]),
                math.floor(ya + la[1] - lb[3]),
            ])
        xb = min(bx1, max(bx0, rng.choice(contacts_x) + rng.randint(-3, 3)))
        yb = min(by1, max(by0, rng.choice(contacts_y) + rng.randint(-3, 3)))

        pa = int(prob["blocks"][aid]["processing_time"])
        pb = int(prob["blocks"][bid]["processing_time"])
        ea, exa, eb, exb = random_intervals(rng, pa, pb)

        poly_b = mod._translate(gb.poly, xoff=xb, yoff=yb)
        other = {
            "block_id": bid, "bay_id": bay_id,
            "x": xb, "y": yb, "orient_idx": gb.idx,
            "entry_time": eb, "exit_time": exb,
            "_geom": gb, "_poly": poly_b, "_bbox": tuple(poly_b.bounds),
        }
        predicted = mod._pair_event_safe(
            aid, ga, xa, ya, ea, exa, other
        )
        ba = Block(aid, prob["blocks"][aid], xa, ya, ga.idx)
        bb = Block(bid, prob["blocks"][bid], xb, yb, gb.idx)
        actual = checker_pair_safe(
            bay_data, ba, bb, ea, exa, eb, exb
        )
        accepted += int(predicted)
        if predicted and not actual:
            false_accept += 1
            if len(examples) < 5:
                examples.append((aid, bid, ga.idx, gb.idx, xa, ya, xb, yb,
                                 ea, exa, eb, exb))
        elif actual and not predicted:
            false_reject += 1

    return {
        "instance": prob.get("name", path.stem),
        "samples": samples,
        "accepted": accepted,
        "false_accept": false_accept,
        "false_reject": false_reject,
        "examples": examples,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=10_000,
                        help="samples per instance")
    parser.add_argument("--instances", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260727)
    args = parser.parse_args()
    mod = load_slot_b()
    paths = [
        ROOT / ("train 2" if i <= 20 else "train") / f"prob_{i}.json"
        for i in (1, 4, 9, 20, 21, 25, 27, 32, 38, 40)[:args.instances]
    ]
    total_fa = total_fr = total = 0
    for k, path in enumerate(paths):
        result = run_instance(
            mod, path, args.samples, args.seed + 1009 * k
        )
        total += result["samples"]
        total_fa += result["false_accept"]
        total_fr += result["false_reject"]
        print(json.dumps(result))
        if result["false_accept"]:
            break
    print(json.dumps({
        "total": total,
        "false_accept": total_fa,
        "false_reject": total_fr,
    }))
    raise SystemExit(1 if total_fa else 0)


if __name__ == "__main__":
    main()
