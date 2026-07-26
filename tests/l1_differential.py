#!/usr/bin/env python
"""L1 differential test harness: layer-true predicate vs the official checker.

For each case a random mini-schedule (3-7 blocks, one bay, near-contact
positions, adversarial entry/exit times) is built on a REDUCED instance
(deep-copied instance whose blocks list contains only the sampled blocks,
re-indexed 0..k-1; bays/weights kept), emitted as an operations dict
(EXITs before ENTRYs per day, each group sorted by block_id) and validated
with utils.check_feasibility (ground truth).

The solver's layer-true predicate `_safe_layers_position(geom, x, y, entry,
exit_t, blockers)` is called on the LAST block given the others (module
imported with KESTREL_LAYER_TRUE=1).  A FALSE-ACCEPT (predicate True while
the checker rejects a base-feasible schedule extended by that block) is
fatal: the full repro case is printed as JSON and the process exits 1.

Exit codes:
  0  ran to completion, zero false-accepts
  1  FALSE-ACCEPT found (repro JSON printed)
  2  usage / data error
  3  predicate not implemented yet (checker-only validation pass still runs)
  4  predicate raised an exception (repro JSON printed)

Every case is reproducible from (--seed, case index): the per-case RNG is
random.Random(f"{seed}|{case_index}") and all draws are sequential.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
import os
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

TIME_MODES = ("same", "plus1", "minus1", "nested", "exit_equal", "random")


# ---------------------------------------------------------------------------
# Imports of the two subjects under test
# ---------------------------------------------------------------------------

def load_checker(utils_dir: Path):
    sys.path.insert(0, str(utils_dir))
    import utils  # noqa: F401
    return utils


def load_solver(solver_path: Path, layer_flag: str):
    os.environ["KESTREL_LAYER_TRUE"] = layer_flag
    spec = importlib.util.spec_from_file_location("myalgorithm", str(solver_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["myalgorithm"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Geometry helpers (mirror utils.Block anchoring exactly)
# ---------------------------------------------------------------------------

def anchored_layers(block: dict, orient_idx: int):
    """World layers for position (0,0): raw layers minus first vertex of
    first layer (the reference point), exactly as utils.Block does."""
    layers = [l for l in block["shape"][orient_idx]["layers"] if l]
    if not layers or not layers[0]:
        return None
    rx, ry = layers[0][0]
    return [[[float(x) - rx, float(y) - ry] for x, y in l] for l in layers]


def bbox_of_layers(layers):
    xs = [v[0] for l in layers for v in l]
    ys = [v[1] for l in layers for v in l]
    return (min(xs), min(ys), max(xs), max(ys))


def fit_range(bbox, bay):
    """Integer position ranges keeping the all-layer bbox inside the bay."""
    x_lo = int(math.ceil(-bbox[0]))
    x_hi = int(math.floor(float(bay["width"]) - bbox[2]))
    y_lo = int(math.ceil(-bbox[1]))
    y_hi = int(math.floor(float(bay["height"]) - bbox[3]))
    return x_lo, x_hi, y_lo, y_hi


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Mini-schedule generation
# ---------------------------------------------------------------------------

def gen_layout(rng: random.Random, inst: dict, bay_id: int, block_ids: list):
    """One attempt at a layout: positions (near-contact) + times for all
    sampled blocks in one bay.  Returns list of placement dicts or None."""
    bay = inst["bays"][bay_id]
    placements = []
    for i, bid in enumerate(block_ids):
        block = inst["blocks"][bid]
        n_or = len(block["shape"])
        order = list(range(n_or))
        rng.shuffle(order)
        chosen = None
        for oi in order:
            lay = anchored_layers(block, oi)
            if lay is None:
                continue
            bbox = bbox_of_layers(lay)
            x_lo, x_hi, y_lo, y_hi = fit_range(bbox, bay)
            if x_lo > x_hi or y_lo > y_hi:
                continue
            chosen = (oi, bbox, (x_lo, x_hi, y_lo, y_hi))
            break
        if chosen is None:
            return None
        oi, g, (x_lo, x_hi, y_lo, y_hi) = chosen

        if not placements:
            x = rng.randint(x_lo, x_hi)
            y = rng.randint(y_lo, y_hi)
        else:
            ref = rng.choice(placements)
            rb = ref["world_bbox"]
            w_new = g[2] - g[0]
            h_new = g[3] - g[1]
            axis = rng.choice(("x", "y"))
            side = rng.choice((-1, 1))
            d = rng.randint(-2, 2)  # overlap amount: >0 overlap, 0 touch, <0 gap
            if axis == "x":
                new_min_x = (rb[2] - d) if side > 0 else (rb[0] - w_new + d)
                lo = int(math.floor(rb[1] - h_new + 1))
                hi = int(math.ceil(rb[3] - 1))
                new_min_y = rng.randint(lo, hi) if hi >= lo else rb[1]
            else:
                new_min_y = (rb[3] - d) if side > 0 else (rb[1] - h_new + d)
                lo = int(math.floor(rb[0] - w_new + 1))
                hi = int(math.ceil(rb[2] - 1))
                new_min_x = rng.randint(lo, hi) if hi >= lo else rb[0]
            x = clamp(int(round(new_min_x - g[0])), x_lo, x_hi)
            y = clamp(int(round(new_min_y - g[1])), y_lo, y_hi)

        release = int(block["release_time"])
        proc = int(block["processing_time"])
        if not placements:
            entry = release + rng.randint(0, 2)
        else:
            ref = rng.choice(placements)
            mode = rng.choice(TIME_MODES)
            if mode == "same":
                entry = ref["entry"]
            elif mode == "plus1":
                entry = ref["entry"] + 1
            elif mode == "minus1":
                entry = ref["entry"] - 1
            elif mode == "nested":
                entry = ref["entry"] + 1
            elif mode == "exit_equal":
                entry = ref["exit"] - proc  # boundary-equal exits
            else:
                entry = ref["entry"] + rng.randint(-2, 3)
        entry = max(entry, release)  # checker Stage 1 requires entry >= release
        exit_t = entry + proc

        placements.append({
            "orig_id": bid,
            "orient_idx": oi,
            "x": x, "y": y,
            "entry": entry, "exit": exit_t,
            "world_bbox": (g[0] + x, g[1] + y, g[2] + x, g[3] + y),
        })
    return placements


def reduced_instance(inst: dict, block_ids: list):
    return {
        "name": str(inst.get("name", "reduced")) + "-reduced",
        "bays": copy.deepcopy(inst["bays"]),
        "weights": copy.deepcopy(inst.get("weights", {})),
        "blocks": [copy.deepcopy(inst["blocks"][b]) for b in block_ids],
    }


def emit_ops(placements: list, bay_id: int):
    """EXITs before ENTRYs per day; EXITs sorted by block_id, ENTRYs by
    block_id.  Block ids are the REDUCED indices (list positions)."""
    buckets = {}
    for i, p in enumerate(placements):
        buckets.setdefault(p["exit"], []).append(
            {"type": "EXIT", "block_id": i, "bay_id": bay_id})
        buckets.setdefault(p["entry"], []).append(
            {"type": "ENTRY", "block_id": i, "bay_id": bay_id,
             "x": int(p["x"]), "y": int(p["y"]),
             "orient_idx": int(p["orient_idx"])})
    operations = {}
    for t in sorted(buckets):
        ops = sorted(buckets[t],
                     key=lambda op: (0 if op["type"] == "EXIT" else 1,
                                     op["block_id"]))
        operations[str(int(t))] = ops
    return {"operations": operations}


# ---------------------------------------------------------------------------
# Reduced-instance trick self-check (run before bulk generation)
# ---------------------------------------------------------------------------

def verify_reduced_trick(utils, inst: dict):
    """Assert utils.check_feasibility semantics on a hand-built reduced
    instance: single block feasible; duplicated overlapping block infeasible;
    omitting a block from ops -> Stage-1 infeasible."""
    b0 = None
    for cand in inst["blocks"]:
        for oi in range(len(cand["shape"])):
            lay = anchored_layers(cand, oi)
            if lay is None:
                continue
            bbox = bbox_of_layers(lay)
            x_lo, x_hi, y_lo, y_hi = fit_range(bbox, inst["bays"][0])
            if x_lo <= x_hi and y_lo <= y_hi:
                b0 = (cand, oi, x_lo, y_lo)
                break
        if b0:
            break
    if b0 is None:
        raise RuntimeError("selfcheck: no block fits bay 0")
    blk, oi, x, y = b0
    entry = int(blk["release_time"])
    exit_t = entry + int(blk["processing_time"])
    pl = {"orig_id": 0, "orient_idx": oi, "x": x, "y": y,
          "entry": entry, "exit": exit_t, "world_bbox": (0, 0, 0, 0)}

    # 1) single sampled block, all others omitted -> must be feasible
    red1 = {"name": "sc1", "bays": copy.deepcopy(inst["bays"]),
            "weights": copy.deepcopy(inst.get("weights", {})),
            "blocks": [copy.deepcopy(blk)]}
    r1 = utils.check_feasibility(red1, emit_ops([pl], 0))
    assert r1["feasible"] is True, f"selfcheck-1 failed: {r1['violations'][:3]}"

    # 2) same block duplicated at identical position/time -> must be infeasible
    red2 = {"name": "sc2", "bays": copy.deepcopy(inst["bays"]),
            "weights": copy.deepcopy(inst.get("weights", {})),
            "blocks": [copy.deepcopy(blk), copy.deepcopy(blk)]}
    r2 = utils.check_feasibility(red2, emit_ops([pl, dict(pl)], 0))
    assert r2["feasible"] is False, "selfcheck-2 failed: duplicate accepted"

    # 3) block present in reduced instance but missing from ops -> Stage 1
    r3 = utils.check_feasibility(red2, emit_ops([pl], 0))
    assert r3["feasible"] is False and r3["stage"] == 1, \
        f"selfcheck-3 failed: stage={r3['stage']}"
    print("[selfcheck] reduced-instance trick verified against utils.py "
          "(single-feasible / duplicate-infeasible / unassigned->Stage1)")


# ---------------------------------------------------------------------------
# Predicate invocation
# ---------------------------------------------------------------------------

def call_predicate(myalg, red_full: dict, placements: list, bay_id: int):
    """Call myalgorithm._safe_layers_position on the LAST reduced block given
    the others (blockers = interval-overlapping others, assignment-dict
    format used throughout the solver)."""
    from shapely.affinity import translate as _translate

    geoms = myalg._precompute_geometry(red_full)
    k = len(placements)
    last = placements[-1]

    def orient_of(i, oi):
        for g in geoms[i]:
            if g.idx == oi:
                return g
        return None

    geom = orient_of(k - 1, last["orient_idx"])
    if geom is None:
        return None  # degenerate orientation; case unusable for predicate

    blockers = []
    for i in range(k - 1):
        p = placements[i]
        if not (p["entry"] < last["exit"] and last["entry"] < p["exit"]):
            continue  # half-open interval overlap only, matching the solver
        g = orient_of(i, p["orient_idx"])
        if g is None:
            return None
        poly = _translate(g.poly, xoff=p["x"], yoff=p["y"])
        blockers.append({
            "block_id": i, "bay_id": bay_id,
            "x": p["x"], "y": p["y"], "orient_idx": p["orient_idx"],
            "entry_time": p["entry"], "exit_time": p["exit"],
            "_geom": g, "_poly": poly, "_bbox": tuple(poly.bounds),
        })

    return bool(myalg._safe_layers_position(
        geom, last["x"], last["y"], last["entry"], last["exit"], blockers))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def repro_dict(seed, case_idx, inst_path, bay_id, placements, sol_full):
    return {
        "seed": seed, "case": case_idx, "instance": str(inst_path),
        "bay_id": bay_id,
        "original_block_ids": [p["orig_id"] for p in placements],
        "orient_idx": [p["orient_idx"] for p in placements],
        "positions": [[p["x"], p["y"]] for p in placements],
        "entries": [p["entry"] for p in placements],
        "exits": [p["exit"] for p in placements],
        "solution": sol_full,
        "note": ("reduced instance = deepcopy(instance); "
                 "blocks = [instance['blocks'][i] for i in original_block_ids]"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--instances", type=int, default=10,
                    help="number of training instances in the sampling pool")
    ap.add_argument("--cases", type=int, default=200)
    ap.add_argument("--timelimit-per-case", type=float, default=0.75,
                    help="soft per-case wall-time guard (seconds)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--solver", type=Path,
                    default=REPO / "submission" / "myalgorithm.py")
    ap.add_argument("--utils-dir", type=Path,
                    default=REPO / "ogc2026" / "baseline")
    ap.add_argument("--train-dirs", nargs="*", type=Path,
                    default=[REPO / "train 2", REPO / "train"])
    ap.add_argument("--layer-flag", default="1", choices=("0", "1"),
                    help="value of KESTREL_LAYER_TRUE set before solver import")
    ap.add_argument("--max-attempts", type=int, default=6,
                    help="layout retries per case until the base schedule "
                         "(first k-1 blocks) is checker-feasible")
    args = ap.parse_args()

    files = []
    for d in args.train_dirs:
        files.extend(sorted(d.glob("prob_*.json")))
    if not files:
        print(f"ERROR: no training instances under {args.train_dirs}")
        return 2
    pool_order = list(files)
    random.Random(args.seed).shuffle(pool_order)
    pool = pool_order[:max(1, min(args.instances, len(pool_order)))]

    utils = load_checker(args.utils_dir)
    try:
        myalg = load_solver(args.solver, args.layer_flag)
    except Exception as e:
        print(f"ERROR: cannot import solver {args.solver}: {e!r}")
        return 2

    has_pred = hasattr(myalg, "_safe_layers_position")
    if not has_pred:
        print("[l1] predicate _safe_layers_position NOT exposed by the solver "
              f"(KESTREL_LAYER_TRUE={args.layer_flag}); running checker-only "
              "validation pass, will exit 3.")

    inst_cache = {}

    def load_inst(p):
        if p not in inst_cache:
            inst_cache[p] = json.load(open(p))
        return inst_cache[p]

    verify_reduced_trick(utils, load_inst(pool[0]))

    stats = {
        "cases": 0, "generated": 0, "gen_failed": 0, "base_infeasible": 0,
        "checker_feasible": 0, "checker_infeasible": 0,
        "pred_accept": 0, "pred_reject": 0, "pred_unusable": 0,
        "TA": 0, "FA": 0, "FR": 0, "TR": 0,
        "overtime_cases": 0,
    }
    stage_hist = {}

    for ci in range(args.cases):
        t0 = time.monotonic()
        stats["cases"] += 1
        rng = random.Random(f"{args.seed}|{ci}")
        inst_path = pool[rng.randrange(len(pool))]
        inst = load_inst(inst_path)
        n_bays = len(inst["bays"])
        bay_id = rng.randrange(n_bays)
        k = rng.randint(3, 7)
        block_ids = rng.sample(range(len(inst["blocks"])), k)

        placements = None
        base_ok = False
        red_base = reduced_instance(inst, block_ids[:-1])
        for _attempt in range(args.max_attempts):
            cand = gen_layout(rng, inst, bay_id, block_ids)
            if cand is None:
                continue
            r_base = utils.check_feasibility(
                red_base, emit_ops(cand[:-1], bay_id))
            placements = cand
            if r_base["feasible"]:
                base_ok = True
                break
        if placements is None:
            stats["gen_failed"] += 1
            continue
        stats["generated"] += 1
        if not base_ok:
            stats["base_infeasible"] += 1
            continue

        red_full = reduced_instance(inst, block_ids)
        sol_full = emit_ops(placements, bay_id)
        r_full = utils.check_feasibility(red_full, sol_full)
        feas = bool(r_full["feasible"])
        if feas:
            stats["checker_feasible"] += 1
        else:
            stats["checker_infeasible"] += 1
            stage_hist[r_full["stage"]] = stage_hist.get(r_full["stage"], 0) + 1

        if has_pred:
            try:
                verdict = call_predicate(myalg, red_full, placements, bay_id)
            except Exception as e:
                print("PREDICATE EXCEPTION:", repr(e))
                print(json.dumps(repro_dict(args.seed, ci, inst_path, bay_id,
                                            placements, sol_full)))
                return 4
            if verdict is None:
                stats["pred_unusable"] += 1
            else:
                if verdict:
                    stats["pred_accept"] += 1
                    if feas:
                        stats["TA"] += 1
                    else:
                        stats["FA"] += 1
                        print("FALSE-ACCEPT (predicate True, checker "
                              "infeasible) — FATAL")
                        print("checker violations:",
                              r_full["violations"][:5])
                        print(json.dumps(repro_dict(
                            args.seed, ci, inst_path, bay_id, placements,
                            sol_full)))
                        _summary(stats, stage_hist)
                        return 1
                else:
                    stats["pred_reject"] += 1
                    if feas:
                        stats["FR"] += 1
                    else:
                        stats["TR"] += 1

        if time.monotonic() - t0 > args.timelimit_per_case:
            stats["overtime_cases"] += 1

    _summary(stats, stage_hist)
    if not has_pred:
        return 3
    return 0


def _summary(stats, stage_hist):
    feas = stats["checker_feasible"]
    fr_rate = (stats["FR"] / feas) if feas else 0.0
    print("---- l1_differential summary ----")
    print(f"cases={stats['cases']} generated={stats['generated']} "
          f"gen_failed={stats['gen_failed']} "
          f"base_infeasible_skipped={stats['base_infeasible']}")
    print(f"checker: feasible={stats['checker_feasible']} "
          f"infeasible={stats['checker_infeasible']} "
          f"stage_histogram={stage_hist}")
    print(f"predicate: accepts={stats['pred_accept']} "
          f"rejects={stats['pred_reject']} unusable={stats['pred_unusable']}")
    print(f"matrix: TA={stats['TA']} FA={stats['FA']} "
          f"FR={stats['FR']} TR={stats['TR']}")
    print(f"false_accepts={stats['FA']} (REQUIRED: 0)")
    print(f"false_reject_rate_among_checker_feasible={fr_rate:.4f}")
    print(f"overtime_cases={stats['overtime_cases']}")


if __name__ == "__main__":
    sys.exit(main())
