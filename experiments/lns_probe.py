"""Sequential A/B probe for the experimental Kestrel LNS workers.

This deliberately calls the single-process ``_solve`` entry so the measurements
describe one worker rather than a four-process portfolio.  For each requested
variant it runs the same source and seed twice:

  A: ADVANCED_LNS disabled (existing Kestrel search)
  B: ADVANCED_LNS enabled  (blame + regret + late acceptance on variant 1)

Variants other than 1 remain legacy controls unless the separate CP-SAT switch
is enabled for variant 2.

Usage:
  PYTHONDONTWRITEBYTECODE=1 python experiments/lns_probe.py \
      "train/prob_33.json" --timelimit 60 --variants 1 2

Keep arms sequential and the machine otherwise idle; contention has already
produced sign-flipped verdicts in this repository.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOLVER = ROOT / "experiments" / "myalgorithm_lns_prototype.py"
CHECKER_DIR = ROOT / "ogc2026" / "baseline"


def _load_solver(name: str, advanced: bool):
    spec = importlib.util.spec_from_file_location(name, SOLVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SOLVER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.ADVANCED_LNS = bool(advanced)
    return module


def _run(problem, timelimit: float, variant: int, advanced: bool):
    name = f"_lns_probe_v{variant}_{'b' if advanced else 'a'}"
    solver = _load_solver(name, advanced)
    metrics = {}
    started = time.monotonic()
    objective, solution = solver._solve(
        problem,
        timelimit=timelimit,
        variant=variant,
        metrics=metrics,
    )
    elapsed = time.monotonic() - started

    from utils import check_feasibility

    verdict = check_feasibility(problem, solution)
    return {
        "arm": "advanced" if advanced else "existing",
        "variant": variant,
        "elapsed": elapsed,
        "returned_objective": objective,
        "feasible": bool(verdict.get("feasible")),
        "objective": verdict.get("objective"),
        "obj1": verdict.get("obj1"),
        "obj2": verdict.get("obj2"),
        "obj3": verdict.get("obj3"),
        "violations": verdict.get("violations", []),
        "metrics": metrics,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("problem", type=Path)
    parser.add_argument("--timelimit", type=float, default=60.0)
    parser.add_argument("--variants", type=int, nargs="+", default=[1, 2])
    parser.add_argument(
        "--output", type=Path,
        help="optional JSON file containing all probe rows",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(CHECKER_DIR))
    sys.path.insert(0, str(ROOT / "experiments"))
    problem = json.loads(args.problem.read_text())
    rows = []
    for variant in args.variants:
        existing = _run(problem, args.timelimit, variant, advanced=False)
        advanced = _run(problem, args.timelimit, variant, advanced=True)
        row = {
            "problem": problem.get("name", args.problem.stem),
            "timelimit": args.timelimit,
            "variant": variant,
            "existing": existing,
            "advanced": advanced,
        }
        old = existing.get("objective")
        new = advanced.get("objective")
        row["delta_pct"] = (
            100.0 * (new - old) / old
            if isinstance(old, (int, float))
            and isinstance(new, (int, float))
            and old != 0 else None
        )
        rows.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(rows, indent=2, sort_keys=True) + "\n"
        )


if __name__ == "__main__":
    main()
