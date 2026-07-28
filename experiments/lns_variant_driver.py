"""Diagnostic: run one portfolio variant directly and print checker metrics."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("solver", type=Path)
    parser.add_argument("problem", type=Path)
    parser.add_argument("timelimit", type=float)
    parser.add_argument("variant", type=int)
    parser.add_argument("--advanced", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "ogc2026" / "baseline"))
    solver_path = args.solver.resolve()
    if solver_path.is_dir():
        solver_path = solver_path / "myalgorithm.py"
    spec = importlib.util.spec_from_file_location("myalgorithm", solver_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {solver_path}")
    myalgorithm = importlib.util.module_from_spec(spec)
    sys.modules["myalgorithm"] = myalgorithm
    spec.loader.exec_module(myalgorithm)
    from utils import check_feasibility

    if hasattr(myalgorithm, "ADVANCED_LNS"):
        myalgorithm.ADVANCED_LNS = bool(args.advanced)
    problem = json.loads(args.problem.read_text())
    metrics = {}
    started = time.monotonic()
    objective, solution = myalgorithm._solve(
        problem, args.timelimit, variant=args.variant, metrics=metrics,
    )
    verdict = check_feasibility(problem, solution)
    print(json.dumps({
        "variant": args.variant,
        "advanced_switch": args.advanced,
        "advanced_active": metrics.get("advanced_lns"),
        "elapsed": time.monotonic() - started,
        "returned_objective": objective,
        "feasible": verdict.get("feasible"),
        "objective": verdict.get("objective"),
        "metrics": metrics,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
