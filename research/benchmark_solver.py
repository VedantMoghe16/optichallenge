#!/usr/bin/env python3
"""Run one submission through its real entry point and the official checker.

Using a physical script with a ``__main__`` guard is important on macOS, where
the 4-worker portfolio uses multiprocessing ``spawn``.  The resulting solution
JSON can be opened directly in the official Algorithm Tester UI or passed to
``research/visualize_solution.py``.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("instance", type=Path)
    parser.add_argument("--solver", type=Path,
                        default=Path("submission/slot_b"))
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    solver = (root / args.solver).resolve()
    checker = (root / "ogc2026" / "alg_tester").resolve()
    sys.path.insert(0, str(checker))
    sys.path.insert(0, str(solver))

    algorithm_module = importlib.import_module("myalgorithm")
    utils = importlib.import_module("utils")
    problem = json.loads((root / args.instance).read_text())

    started = time.monotonic()
    solution = algorithm_module.algorithm(problem, args.time_limit)
    elapsed = time.monotonic() - started
    result = utils.check_feasibility(problem, solution)

    summary = {
        "instance": str(args.instance),
        "solver": str(args.solver),
        "time_limit": args.time_limit,
        "elapsed": round(elapsed, 6),
        "feasible": bool(result.get("feasible")),
        "objective": result.get("objective"),
        "obj1": result.get("obj1"),
        "obj2": result.get("obj2"),
        "obj3": result.get("obj3"),
        "violations": result.get("violations", []),
    }
    print(json.dumps(summary, indent=2))

    if args.output:
        output = (root / args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(solution, indent=2))
    return 0 if summary["feasible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
