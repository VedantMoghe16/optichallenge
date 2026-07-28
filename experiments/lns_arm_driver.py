"""Run one full-portfolio solver arm and persist the official checker verdict."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    if len(sys.argv) != 5:
        raise SystemExit(
            "usage: lns_arm_driver.py SOLVER_DIR PROBLEM TIMELIMIT OUTPUT"
        )
    solver_dir = Path(sys.argv[1]).resolve()
    problem_path = Path(sys.argv[2]).resolve()
    timelimit = float(sys.argv[3])
    output_path = Path(sys.argv[4]).resolve()

    sys.path.insert(0, str(ROOT / "ogc2026" / "baseline"))
    sys.path.insert(0, str(solver_dir))
    import myalgorithm
    from utils import check_feasibility

    problem = json.loads(problem_path.read_text())
    started = time.monotonic()
    solution = myalgorithm.algorithm(problem, timelimit)
    elapsed = time.monotonic() - started
    verdict = check_feasibility(problem, solution)
    row = {
        "problem": problem.get("name", problem_path.stem),
        "timelimit": timelimit,
        "elapsed": elapsed,
        "feasible": bool(verdict.get("feasible")),
        "objective": verdict.get("objective"),
        "obj1": verdict.get("obj1"),
        "obj2": verdict.get("obj2"),
        "obj3": verdict.get("obj3"),
        "violations": verdict.get("violations", []),
    }
    output_path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
