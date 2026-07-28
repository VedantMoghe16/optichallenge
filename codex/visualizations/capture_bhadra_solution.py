#!/usr/bin/env python3
"""Run one exact Bhadra solve and preserve its checked operation stream."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--problem", type=Path, required=True)
    parser.add_argument("--timelimit", type=float, default=60.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    solver = args.solver.resolve()
    problem_path = args.problem.resolve()
    output = args.output.resolve()
    if not solver.is_file():
        raise SystemExit(f"missing solver: {solver}")
    if not problem_path.is_file():
        raise SystemExit(f"missing problem: {problem_path}")

    sys.path.insert(0, str(ROOT / "ogc2026" / "baseline"))
    sys.path.insert(0, str(solver.parent))
    import myalgorithm  # type: ignore
    from utils import check_feasibility  # type: ignore

    problem = json.loads(problem_path.read_text())
    started = time.monotonic()
    solution = myalgorithm.algorithm(problem, float(args.timelimit))
    elapsed = time.monotonic() - started
    verdict = check_feasibility(problem, solution)
    if not verdict.get("feasible"):
        raise SystemExit(
            f"{problem_path.stem}: Bhadra returned an infeasible solution: "
            f"{verdict.get('violations', [])[:5]}"
        )

    payload = {
        "schema": "bhadra-bay-replay-v1",
        "problem": problem.get("name", problem_path.stem),
        "problem_path": str(problem_path.relative_to(ROOT)),
        "solver_path": str(solver.relative_to(ROOT)),
        "solver_sha256": sha256(solver),
        "timelimit": float(args.timelimit),
        "elapsed": elapsed,
        "verdict": {
            "feasible": True,
            "stage": verdict.get("stage"),
            "objective": verdict.get("objective"),
            "obj1": verdict.get("obj1"),
            "obj2": verdict.get("obj2"),
            "obj3": verdict.get("obj3"),
            "violations": list(verdict.get("violations", [])),
        },
        "solution": solution,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":")))
    print(
        json.dumps(
            {
                "problem": payload["problem"],
                "elapsed": round(elapsed, 3),
                "objective": verdict.get("objective"),
                "feasible": True,
                "output": str(output),
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
