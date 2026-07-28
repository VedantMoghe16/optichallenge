"""Time-boxed paired proxy gate for the final preliminary candidate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "experiments" / "lns_gate.py"
STAGES = [
    ("loose_120s", "1,2,8", 120.0, "loose"),
    ("small_congested_120s", "22,29", 120.0, "congested"),
    ("mid_congested_240s", "30,33", 240.0, "congested"),
    ("big_congested_240s", "38,40", 240.0, "congested"),
]


def _command(instances, seconds, output):
    return [
        sys.executable,
        str(GATE),
        "--instances", instances,
        "--timelimit", str(seconds),
        "--results-dir", str(output),
        "--raster",
        "--loose-polish",
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (
        args.results_dir.resolve()
        if args.results_dir else
        ROOT / "experiments" / "results" / f"tonight_proxy_{stamp}"
    )
    commands = [
        _command(instances, seconds, root / name)
        for name, instances, seconds, _ in STAGES
    ]
    if args.dry_run:
        print(json.dumps({
            "results_dir": str(root),
            "commands": commands,
            "estimated_solver_seconds": 3120,
        }, indent=2))
        return

    root.mkdir(parents=True, exist_ok=False)
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)

    summaries = {
        name: json.loads((root / name / "summary.json").read_text())
        for name, _, _, _ in STAGES
    }
    rows = [
        {**row, "class": kind}
        for name, _, _, kind in STAGES
        for row in summaries[name]["rows"]
    ]
    infeasible = [
        row["instance"] for row in rows
        if not row["candidate"]["feasible"]
    ]
    over_one = [
        row["instance"] for row in rows if row["delta_pct"] > 1.0
    ]
    loose = [row for row in rows if row["class"] == "loose"]
    congested = [row for row in rows if row["class"] == "congested"]

    def totals(group):
        old = sum(row["baseline"]["objective"] for row in group)
        new = sum(row["candidate"]["objective"] for row in group)
        delta = 100.0 * (new - old) / old if old else 0.0
        return old, new, delta

    loose_old, loose_new, loose_delta = totals(loose)
    cong_old, cong_new, cong_delta = totals(congested)
    passed = bool(
        not infeasible
        and not over_one
        and loose_new <= loose_old + 1e-7
        and cong_delta <= -5.0
    )
    combined = {
        "created_utc": stamp,
        "passes_proxy_gate": passed,
        "candidate_infeasible": infeasible,
        "instances_over_plus_1_pct": over_one,
        "loose_baseline_total": loose_old,
        "loose_candidate_total": loose_new,
        "loose_delta_pct": loose_delta,
        "congested_baseline_total": cong_old,
        "congested_candidate_total": cong_new,
        "congested_delta_pct": cong_delta,
        "rows": rows,
        "stages": summaries,
    }
    (root / "combined_summary.json").write_text(
        json.dumps(combined, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        key: combined[key] for key in (
            "passes_proxy_gate",
            "candidate_infeasible",
            "instances_over_plus_1_pct",
            "loose_delta_pct",
            "congested_delta_pct",
        )
    }, indent=2))


if __name__ == "__main__":
    main()
