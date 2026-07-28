"""Binding-style paired gate for the parked T1 LNS prototype.

The harness creates isolated temporary arms:

  A: tracked ``submission/myalgorithm.py`` at the current frozen baseline.
  B: ``experiments/myalgorithm_lns_prototype.py`` with ADVANCED_LNS enabled on
     worker 1; workers 0, 2, and 3 retain their legacy search.

Each instance runs A then B sequentially.  Do not run this while
``full_compare`` or another driver is active.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "experiments" / "lns_arm_driver.py"
BASELINE = ROOT / "submission" / "myalgorithm.py"
CANDIDATE = ROOT / "experiments" / "myalgorithm_lns_prototype.py"
ORACLE = ROOT / "experiments" / "repair_oracle.py"
RASTER_KERNEL = ROOT / "submission" / "raster_kernel.py"


def _parse_instances(text):
    result = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(x) for x in part.split("-", 1))
            result.extend(range(lo, hi + 1))
        else:
            result.append(int(part))
    return sorted(set(result))


def _problem_path(number):
    group = "train 2" if number <= 20 else "train"
    return ROOT / group / f"prob_{number}.json"


def _busy_processes():
    hits = {}
    for pattern in ("full_compare", "driver.py"):
        try:
            proc = subprocess.run(
                ["pgrep", "-f", pattern],
                text=True, capture_output=True, check=False,
            )
        except FileNotFoundError:
            continue
        pids = [p for p in proc.stdout.split() if p != str(os.getpid())]
        if pids:
            hits[pattern] = pids
    try:
        docker = subprocess.run(
            ["docker", "ps", "-q"],
            text=True, capture_output=True, check=False,
        )
        if docker.returncode == 0 and docker.stdout.strip():
            hits["docker"] = docker.stdout.split()
    except FileNotFoundError:
        pass
    return hits


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head():
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _enable_switch(text, name):
    marker = f"{name} = False"
    if text.count(marker) != 1:
        raise RuntimeError(f"candidate {name} marker is not unique")
    return text.replace(marker, f"{name} = True", 1)


def _prepare_arms(root, cp_sat=False, raster=False, loose_polish=False,
                  candidate_file=None):
    arm_a = root / "A"
    arm_b = root / "B"
    arm_a.mkdir()
    arm_b.mkdir()
    shutil.copy2(BASELINE, arm_a / "myalgorithm.py")
    if candidate_file is not None:
        shutil.copy2(candidate_file, arm_b / "myalgorithm.py")
        return arm_a, arm_b
    text = CANDIDATE.read_text()
    text = _enable_switch(text, "ADVANCED_LNS")
    if cp_sat:
        text = _enable_switch(text, "CP_SAT_REPAIR")
    if raster:
        text = _enable_switch(text, "SELECTIVE_RASTER")
    if loose_polish:
        text = _enable_switch(text, "LOOSE_POLISH")
    (arm_b / "myalgorithm.py").write_text(text)
    shutil.copy2(ORACLE, arm_b / "repair_oracle.py")
    if raster:
        shutil.copy2(RASTER_KERNEL, arm_b / "raster_kernel.py")
    return arm_a, arm_b


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instances", default="1-40")
    parser.add_argument("--timelimit", type=float, default=60.0)
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument(
        "--candidate-file", type=Path,
        help="test this already-materialized myalgorithm.py byte-for-byte",
    )
    parser.add_argument(
        "--cp-sat", action="store_true",
        help="also enable the optional CP-SAT repair worker",
    )
    parser.add_argument(
        "--raster", action="store_true",
        help="enable corrected selective raster and package its kernel",
    )
    parser.add_argument(
        "--loose-polish", action="store_true",
        help="enable the zero-tardy Z2/Z3 polish",
    )
    parser.add_argument(
        "--explained", default="",
        help="comma/range list of pre-documented >2%% regression exceptions",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    instances = _parse_instances(args.instances)
    explained = set(_parse_instances(args.explained))
    if not instances:
        raise SystemExit("no instances selected")
    missing = [str(_problem_path(i)) for i in instances
               if not _problem_path(i).is_file()]
    if missing:
        raise SystemExit(f"missing problem files: {missing}")
    candidate_source = (
        args.candidate_file.resolve()
        if args.candidate_file is not None else CANDIDATE
    )
    if not candidate_source.is_file():
        raise SystemExit(f"missing candidate file: {candidate_source}")
    if args.candidate_file is not None and (
        args.cp_sat or args.raster or args.loose_polish
    ):
        raise SystemExit(
            "--candidate-file cannot be combined with source feature switches"
        )
    busy = _busy_processes()
    if busy:
        raise SystemExit(f"machine is not idle; gate verdict would be void: {busy}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results = (
        args.results_dir.resolve()
        if args.results_dir else
        ROOT / "experiments" / "results" / f"lns_gate_{stamp}"
    )
    if args.dry_run:
        print(json.dumps({
            "instances": instances,
            "timelimit": args.timelimit,
            "results_dir": str(results),
            "baseline": str(BASELINE),
            "candidate": str(candidate_source),
            "cp_sat": args.cp_sat,
            "raster": args.raster,
            "loose_polish": args.loose_polish,
            "explained_regressions": sorted(explained),
            "git_head": _git_head(),
            "baseline_sha256": _sha256(BASELINE),
            "candidate_sha256": _sha256(candidate_source),
            "busy": busy,
        }, indent=2))
        return
    results.mkdir(parents=True, exist_ok=False)

    rows = []
    with tempfile.TemporaryDirectory(prefix="ogc_lns_gate_") as tmp:
        arm_a, arm_b = _prepare_arms(
            Path(tmp),
            cp_sat=args.cp_sat,
            raster=args.raster,
            loose_polish=args.loose_polish,
            candidate_file=(
                candidate_source if args.candidate_file is not None else None
            ),
        )
        for number in instances:
            values = {}
            for label, arm in (("baseline", arm_a), ("candidate", arm_b)):
                out = results / f"{label}_prob_{number}.json"
                timeout = max(args.timelimit + 30.0, 1.25 * args.timelimit)
                subprocess.run(
                    [
                        sys.executable, str(DRIVER), str(arm),
                        str(_problem_path(number)), str(args.timelimit), str(out),
                    ],
                    cwd=ROOT, check=True, timeout=timeout,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                values[label] = json.loads(out.read_text())
            old = values["baseline"]["objective"]
            new = values["candidate"]["objective"]
            delta = 100.0 * (new - old) / old if old else 0.0
            row = {
                "instance": number,
                "baseline": values["baseline"],
                "candidate": values["candidate"],
                "delta_pct": delta,
            }
            rows.append(row)
            print(
                f"prob_{number:<3} baseline={old:>14,.0f} "
                f"candidate={new:>14,.0f} {delta:+7.2f}% "
                f"feasible={values['baseline']['feasible']}/"
                f"{values['candidate']['feasible']}",
                flush=True,
            )

    total_old = sum(row["baseline"]["objective"] for row in rows)
    total_new = sum(row["candidate"]["objective"] for row in rows)
    infeasible = [
        row["instance"] for row in rows
        if not row["candidate"]["feasible"]
    ]
    unexplained = [
        row["instance"] for row in rows
        if row["delta_pct"] > 2.0 and row["instance"] not in explained
    ]
    total_delta = (
        100.0 * (total_new - total_old) / total_old if total_old else 0.0
    )
    summary = {
        "created_utc": stamp,
        "git_head": _git_head(),
        "python": sys.version,
        "platform": platform.platform(),
        "baseline_sha256": _sha256(BASELINE),
        "candidate_sha256": _sha256(candidate_source),
        "cp_sat": args.cp_sat,
        "raster": args.raster,
        "loose_polish": args.loose_polish,
        "explained_regressions": sorted(explained),
        "instances": instances,
        "timelimit": args.timelimit,
        "baseline_total": total_old,
        "candidate_total": total_new,
        "delta_pct": total_delta,
        "candidate_infeasible": infeasible,
        "instances_over_plus_2_pct": unexplained,
        "passes_aggregate_gate": not infeasible and total_delta <= 0.5,
        "passes_full_gate": (
            not infeasible and not unexplained and total_delta <= 0.5
        ),
        "rows": rows,
    }
    (results / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        key: summary[key] for key in (
            "baseline_total", "candidate_total", "delta_pct",
            "candidate_infeasible", "instances_over_plus_2_pct",
            "passes_aggregate_gate", "passes_full_gate",
        )
    }, indent=2))


if __name__ == "__main__":
    main()
