"""Fast structural smoke test for blame/regret LNS.

This is intentionally not a quality benchmark.  It checks that related removal
selects the requested neighborhood size, regret recreation returns a complete
assignment, and the official checker accepts that assignment.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ogc2026" / "baseline"))
sys.path.insert(0, str(ROOT / "experiments"))
sys.path.insert(0, str(ROOT / "submission"))

import myalgorithm_lns_prototype as solver
from utils import check_feasibility


def _square_problem(n=10):
    shape = [{
        "orientation": 0,
        "layers": [[
            [0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0]
        ]],
    }]
    return {
        "name": f"lns_square_{n}",
        "bays": [{"width": 50, "height": 10}],
        "blocks": [{
            "release_time": 0,
            "due_date": 5,
            "processing_time": 5,
            "workload": 1,
            "bay_preferences": [0],
            "shape": shape,
        } for _ in range(n)],
        "weights": {"w1": 1000, "w2": 1, "w3": 1},
    }


def main():
    solver._clear_geometry_caches()
    problem = json.loads(
        (ROOT / "ogc2026" / "alg_tester" / "example"
         / "example_B2_b10.json").read_text()
    )
    deadline = time.monotonic() + 5.0
    geoms = solver._precompute_geometry(problem, deadline)
    incumbent = solver._serial_fallback(problem, geoms, deadline)
    initial = check_feasibility(problem, solver._emit(incumbent))
    assert initial.get("feasible"), initial.get("violations")

    removed, scores = solver._related_destroy_set(
        problem, incumbent, random.Random(7), iteration=0, max_removed=6,
    )
    assert len(removed) == 6, removed
    assert set(scores) == set(incumbent)
    _, links = solver._advanced_blame_scores(problem, incumbent)
    assert sum(len(neighbors) for neighbors in links.values()) > 0, links

    metrics = {}
    candidate = solver._regret_recreate(
        problem, geoms, incumbent, removed, scores,
        time.monotonic() + 4.0, random.Random(11), iteration=0,
        metrics=metrics,
    )
    assert candidate is not None
    assert set(candidate) == set(incumbent)
    verdict = check_feasibility(problem, solver._emit(candidate))
    assert verdict.get("feasible"), verdict.get("violations")
    assert metrics.get("lns_regret_insertions") == len(removed), metrics

    # T1 parameter contract and pure late-acceptance behavior.
    assert solver._lahc_history_length(1) == 120
    assert solver._lahc_history_length(250) == 120
    previous_switch = solver.ADVANCED_LNS
    solver.ADVANCED_LNS = True
    try:
        assert not solver._advanced_lns_enabled(250, 89.9, 1)
        assert not solver._advanced_lns_enabled(250, 60, 0)
        assert solver._advanced_lns_enabled(160, 120, 1)
        assert not solver._advanced_lns_enabled(99, 120, 1)
        assert not solver._advanced_lns_enabled(250, 120, 2)
        assert not solver._advanced_lns_enabled(250, 120, 3)
        assert solver._advanced_lns_enabled(250, 120, 1)
    finally:
        solver.ADVANCED_LNS = previous_switch
    assert solver._accept_lns_candidate(999, 1000, 1000, 1010, False)
    assert not solver._accept_lns_candidate(1005, 1000, 1000, 1010, False)
    assert solver._accept_lns_candidate(1005, 1000, 1000, 1010, True)
    assert not solver._accept_lns_candidate(1015, 1000, 1000, 1020, True)

    previous_raster = solver.SELECTIVE_RASTER
    solver.SELECTIVE_RASTER = True
    try:
        selector_stub = {
            "blocks": [{} for _ in range(250)],
            "bays": [{"width": 109, "height": 30}],
        }
        assert not solver._select_raster(selector_stub, 120.0, 0.8)
        assert not solver._select_raster(selector_stub, 179.9, 0.8)
        assert solver._select_raster(selector_stub, 240.0, 0.8)
        assert not solver._select_raster(selector_stub, 240.0, 1.19)
        assert solver._raster_worker_enabled(200, 2, 0.8)
        assert solver._raster_worker_enabled(200, 3, 0.8)
        assert not solver._raster_worker_enabled(250, 2, 0.8)
        assert not solver._raster_worker_enabled(250, 3, 0.8)
        assert not solver._raster_worker_enabled(250, 0, 1.1)
        assert solver._raster_worker_enabled(250, 3, 1.1)
        selector_stub["blocks"] = selector_stub["blocks"][:160]
        assert not solver._select_raster(selector_stub, 240.0, 0.8)
    finally:
        solver.SELECTIVE_RASTER = previous_raster

    solver._clear_geometry_caches()
    larger = _square_problem(20)
    larger_geoms = solver._precompute_geometry(
        larger, time.monotonic() + 2.0
    )
    larger_incumbent = solver._serial_fallback(
        larger, larger_geoms, time.monotonic() + 2.0
    )
    larger_removed, _ = solver._related_destroy_set(
        larger, larger_incumbent, random.Random(13),
        iteration=0, max_removed=30,
    )
    assert len(larger_removed) == 18, larger_removed

    solver._clear_geometry_caches()
    loose = _square_problem(10)
    loose["bays"].append({"width": 50, "height": 10})
    for bid, block in enumerate(loose["blocks"]):
        block["due_date"] = 100
        block["bay_preferences"] = (
            [10, 0] if bid % 2 == 0 else [0, 10]
        )
    loose_geoms = solver._precompute_geometry(
        loose, time.monotonic() + 2.0
    )
    loose_incumbent = solver._serial_fallback(
        loose, loose_geoms, time.monotonic() + 2.0
    )
    for method in (4, 5):
        polished = solver._ruin_recreate(
            loose, loose_geoms, loose_incumbent,
            time.monotonic() + 2.0, random.Random(31 + method),
            iteration=method, exact=True, forced_method=method,
        )
        polished_verdict = check_feasibility(loose, solver._emit(polished))
        assert polished_verdict.get("feasible"), polished_verdict
        assert all(
            a["exit_time"] <= loose["blocks"][bid]["due_date"]
            for bid, a in polished.items()
        )

    # Exercise the complete CP-SAT funnel without requiring OR-Tools locally:
    # the injected proposer supplies a valid, strictly earlier schedule, while
    # the production path still uses repair_oracle.propose_starts.
    solver._clear_geometry_caches()
    oracle_problem = _square_problem(10)
    oracle_geoms = solver._precompute_geometry(
        oracle_problem, time.monotonic() + 2.0
    )
    oracle_incumbent = solver._serial_fallback(
        oracle_problem, oracle_geoms, time.monotonic() + 2.0
    )

    def fake_proposer(jobs, fixed, capacity, horizon_end, time_limit, seed=0):
        del fixed, capacity, horizon_end, time_limit, seed
        return {int(job["id"]): 0 for job in jobs}

    oracle_metrics = {}
    oracle_candidate = solver._oracle_repair(
        oracle_problem, oracle_geoms, oracle_incumbent,
        time.monotonic() + 5.0, seed=17, metrics=oracle_metrics,
        proposer=fake_proposer,
    )
    assert oracle_candidate is not None, oracle_metrics
    oracle_verdict = check_feasibility(
        oracle_problem, solver._emit(oracle_candidate)
    )
    assert oracle_verdict.get("feasible"), oracle_verdict.get("violations")
    assert oracle_metrics.get("oracle_proposals") == 1, oracle_metrics
    assert oracle_metrics.get("oracle_decoded") == 1, oracle_metrics
    assert oracle_metrics.get("oracle_objective_improving") == 1, oracle_metrics

    print(
        "LNS_SMOKE_OK",
        f"removed={len(removed)}",
        f"options={int(metrics.get('lns_insertion_options', 0))}",
        f"objective={verdict.get('objective')}",
        f"oracle_objective={oracle_verdict.get('objective')}",
    )


if __name__ == "__main__":
    main()
