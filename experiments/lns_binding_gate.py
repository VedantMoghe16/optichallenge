"""Run the complete two-stage T1/T2 gate without touching submission sources.

Stage 1 is all 40 instances at 60 seconds.  Stage 2 is the 20 congested
instances at 240 seconds.  Each stage delegates to ``lns_gate.py``, which
enforces an idle machine and paired baseline-then-candidate execution.

This is intentionally an explicit, long-running command.  Use ``--dry-run`` to
inspect the exact commands and output locations before committing machine time.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "experiments" / "lns_gate.py"


def _command(instances, timelimit, results, cp_sat):
    command = [
        sys.executable,
        str(GATE),
        "--instances", instances,
        "--timelimit", str(timelimit),
        "--results-dir", str(results),
    ]
    if cp_sat:
        command.append("--cp-sat")
    return command


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cp-sat", action="store_true")
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (
        args.results_dir.resolve()
        if args.results_dir else
        ROOT / "experiments" / "results" / f"lns_binding_gate_{stamp}"
    )
    stages = [
        ("all_40_at_60s", "1-40", 60.0),
        ("congested_20_at_240s", "21-40", 240.0),
    ]
    commands = [
        _command(instances, seconds, root / name, args.cp_sat)
        for name, instances, seconds in stages
    ]
    if args.dry_run:
        print(json.dumps({
            "results_dir": str(root),
            "cp_sat": args.cp_sat,
            "commands": commands,
            "estimated_solver_seconds": 14400,
        }, indent=2))
        return

    root.mkdir(parents=True, exist_ok=False)
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)

    summaries = {
        name: json.loads((root / name / "summary.json").read_text())
        for name, _, _ in stages
    }
    combined = {
        "created_utc": stamp,
        "cp_sat": args.cp_sat,
        "passes_full_gate": all(
            row["passes_full_gate"] for row in summaries.values()
        ),
        "stages": summaries,
    }
    (root / "combined_summary.json").write_text(
        json.dumps(combined, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "results_dir": str(root),
        "passes_full_gate": combined["passes_full_gate"],
    }, indent=2))


if __name__ == "__main__":
    main()
