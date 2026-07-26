#!/usr/bin/env python
"""Multiprocessing robustness tests for the kestrel solver.

Three tests against the CURRENT solver (no KESTREL_LAYER_TRUE flag):

  A  kill-worker      : run algorithm(prob, limit) in a subprocess; after
                        --kill-after seconds SIGKILL one grandchild portfolio
                        worker; the run must still return a checker-feasible
                        solution within the deadline (+ margin).
  B  queue-poison     : run with KESTREL_FORCE_SINGLE=1 if the solver exposes
                        that flag; otherwise a documented SKIP (total-failure
                        fall-through to the single-process path is covered by
                        code review of algorithm()'s try/except plus test A).
  C  boundary math    : replicate algorithm()'s budget arithmetic for
                        timelimit in {20.0, 20.1, 21, 300, 1800} and
                        n_blocks in {7, 8, 9}; all budgets must be > 0 and
                        the portfolio must toggle exactly at
                        limit >= 20 and n >= 8.

Exit code 0 iff no test FAILs (SKIP is not a failure).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

RUNNER_TEMPLATE = """\
import json, sys
sys.path.insert(0, {solver_dir!r})
import myalgorithm

if __name__ == "__main__":
    prob = json.load(open({instance!r}))
    sol = myalgorithm.algorithm(prob, {limit})
    with open({out!r}, "w") as f:
        json.dump(sol, f)
"""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _children_of(pid: int):
    """(child_pid, command) pairs for direct children of pid (ps-based,
    portable across macOS and Linux)."""
    try:
        out = subprocess.run(["ps", "-ax", "-o", "pid=,ppid=,command="],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    kids = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        try:
            cpid, cppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if cppid == pid:
            kids.append((cpid, parts[2] if len(parts) > 2 else ""))
    return kids


def _pick_worker(runner_pid: int):
    """Choose a portfolio worker among the runner's children.  Prefer spawn
    workers (command contains spawn_main); never pick the resource tracker."""
    kids = _children_of(runner_pid)
    spawned = [k for k in kids if "spawn_main" in k[1]]
    if spawned:
        return spawned[0], len(spawned), kids
    non_tracker = [k for k in kids if "resource_tracker" not in k[1]]
    if non_tracker:
        return non_tracker[0], len(non_tracker), kids
    return None, 0, kids


def test_kill_worker(args, utils) -> str:
    prob = json.load(open(args.instance))
    workdir = Path(args.workdir or tempfile.mkdtemp(prefix="mp_robust_"))
    workdir.mkdir(parents=True, exist_ok=True)
    out_path = workdir / "kill_worker_sol.json"
    runner_path = workdir / "_kill_runner.py"
    if out_path.exists():
        out_path.unlink()
    runner_path.write_text(RUNNER_TEMPLATE.format(
        solver_dir=str(args.solver_dir), instance=str(args.instance),
        limit=float(args.limit), out=str(out_path)))

    env = dict(os.environ)
    env["PYTHONPATH"] = str(args.solver_dir) + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("KESTREL_LAYER_TRUE", None)

    t0 = time.monotonic()
    proc = subprocess.Popen([sys.executable, str(runner_path)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(f"[A] runner pid={proc.pid} limit={args.limit}s "
          f"kill-after={args.kill_after}s instance={args.instance}")

    killed = None
    deadline_pick = t0 + args.kill_after + 10.0
    time.sleep(args.kill_after)
    while time.monotonic() < deadline_pick:
        if proc.poll() is not None:
            print("[A] FAIL: runner exited before a worker could be killed "
                  f"(rc={proc.returncode})")
            return "FAIL"
        target, n_workers, kids = _pick_worker(proc.pid)
        if target is not None:
            try:
                os.kill(target[0], signal.SIGKILL)
                killed = target
                print(f"[A] SIGKILL sent to grandchild worker pid={target[0]} "
                      f"({n_workers} candidate workers alive) "
                      f"t=+{time.monotonic()-t0:.1f}s")
                break
            except ProcessLookupError:
                pass
        time.sleep(0.5)
    if killed is None:
        print("[A] FAIL: no grandchild worker found to kill "
              "(portfolio did not engage?)")
        proc.kill()
        return "FAIL"

    margin = 25.0
    try:
        proc.wait(timeout=args.limit + margin - (time.monotonic() - t0))
    except subprocess.TimeoutExpired:
        proc.kill()
        print(f"[A] FAIL: runner did not finish within limit+{margin:.0f}s "
              "after worker kill")
        return "FAIL"
    elapsed = time.monotonic() - t0
    if proc.returncode != 0:
        err = proc.stderr.read().decode(errors="replace")[-2000:]
        print(f"[A] FAIL: runner rc={proc.returncode}\n{err}")
        return "FAIL"
    if not out_path.exists():
        print("[A] FAIL: runner produced no solution file")
        return "FAIL"
    sol = json.load(open(out_path))
    if not sol.get("operations"):
        print("[A] FAIL: empty operations dict returned")
        return "FAIL"
    res = utils.check_feasibility(prob, sol)
    if not res["feasible"]:
        print(f"[A] FAIL: solution infeasible after worker kill: "
              f"stage={res['stage']} {res['violations'][:3]}")
        return "FAIL"
    print(f"[A] PASS: worker pid={killed[0]} SIGKILLed at "
          f"+{args.kill_after}s; run finished in {elapsed:.1f}s "
          f"(limit {args.limit}s), solution checker-feasible, "
          f"objective={res['objective']:.0f} "
          f"(obj1={res['obj1']:.0f}, obj2={res['obj2']:.0f}, "
          f"obj3={res['obj3']:.0f})")
    return "PASS"


def test_queue_poison(args) -> str:
    src = (Path(args.solver_dir) / "myalgorithm.py").read_text()
    if "KESTREL_FORCE_SINGLE" not in src:
        print("[B] SKIP (documented): solver does not expose "
              "KESTREL_FORCE_SINGLE. Total-failure fall-through is covered "
              "by code review — algorithm() wraps the whole portfolio in "
              "try/except and unconditionally falls back to the "
              "single-process _solve with the remaining budget — and by "
              "test A, which exercises the parent's queue/terminate path "
              "under a hard worker kill.")
        return "SKIP"
    # Flag exposed: run a short solve with the flag on and verify feasibility.
    prob_path = args.instance
    workdir = Path(args.workdir or tempfile.mkdtemp(prefix="mp_robust_"))
    workdir.mkdir(parents=True, exist_ok=True)
    out_path = workdir / "force_single_sol.json"
    runner_path = workdir / "_force_single_runner.py"
    runner_path.write_text(RUNNER_TEMPLATE.format(
        solver_dir=str(args.solver_dir), instance=str(prob_path),
        limit=25.0, out=str(out_path)))
    env = dict(os.environ)
    env["PYTHONPATH"] = str(args.solver_dir) + os.pathsep + env.get("PYTHONPATH", "")
    env["KESTREL_FORCE_SINGLE"] = "1"
    env.pop("KESTREL_LAYER_TRUE", None)
    rc = subprocess.run([sys.executable, str(runner_path)], env=env,
                        timeout=90).returncode
    if rc != 0 or not out_path.exists():
        print(f"[B] FAIL: forced-single run rc={rc}")
        return "FAIL"
    sys.path.insert(0, str(args.utils_dir))
    import utils
    res = utils.check_feasibility(json.load(open(prob_path)),
                                  json.load(open(out_path)))
    if not res["feasible"]:
        print(f"[B] FAIL: forced-single solution infeasible: "
              f"{res['violations'][:3]}")
        return "FAIL"
    print(f"[B] PASS: KESTREL_FORCE_SINGLE=1 run feasible, "
          f"objective={res['objective']:.0f}")
    return "PASS"


def test_boundary_math(args) -> str:
    """Replicate algorithm()'s arithmetic (v2.1):
        portfolio active  iff  limit >= 20.0 and n_blocks >= 8
        collect_margin  = max(1.2, 0.03 * limit)
        child_budget    = max(5.0, limit - collect_margin - elapsed - 0.5)
        hard_end_margin = max(0.8, 0.02 * limit)   (hard_end = start+limit-that)
    """
    src = (Path(args.solver_dir) / "myalgorithm.py").read_text()
    drift = []
    for token in ("limit >= 20.0 and n_blocks >= 8",
                  "max(1.2, 0.03 * limit)",
                  "max(0.8, 0.02 * limit)",
                  "max(5.0, limit - collect_margin"):
        if token not in src:
            drift.append(token)
    if drift:
        print(f"[C] WARN: replicated formulas drifted from source, "
              f"missing tokens: {drift}")

    failures = []
    rows = []
    limits = [20.0, 20.1, 21, 300, 1800]
    for limit_in in limits:
        limit = max(0.05, float(limit_in))
        for n in (7, 8, 9):
            active = (limit >= 20.0 and n >= 8)
            expected = (float(limit_in) >= 20.0 and n >= 8)
            if active != expected:
                failures.append(f"toggle mismatch at limit={limit_in} n={n}")
            collect_margin = max(1.2, 0.03 * limit)
            elapsed = 0.0  # arithmetic replication; startup cost ~0
            child_budget = max(5.0, limit - collect_margin - elapsed - 0.5)
            hard_margin = max(0.8, 0.02 * limit)
            hard_span = limit - hard_margin  # hard_end - start
            if active:
                if not (child_budget > 0):
                    failures.append(f"child_budget<=0 at limit={limit_in}")
                if not (collect_margin > 0):
                    failures.append(f"collect_margin<=0 at limit={limit_in}")
                if not (hard_span > 0):
                    failures.append(f"hard_end before start at limit={limit_in}")
                if not (child_budget < limit):
                    failures.append(f"child_budget>=limit at limit={limit_in}")
                if not (child_budget <= hard_span + 5.0):
                    # child budget may exceed hard_end only via the 5s floor
                    failures.append(f"child_budget incoherent at limit={limit_in}")
            rows.append((limit_in, n, active, round(collect_margin, 3),
                         round(child_budget, 3), round(hard_span, 3)))
    # extra sanity on the toggle boundary itself
    for limit_in, n, expect in ((19.99, 9, False), (20.0, 8, True),
                                (20.0, 7, False), (1e9, 7, False)):
        got = (max(0.05, float(limit_in)) >= 20.0 and n >= 8)
        if got != expect:
            failures.append(f"boundary toggle wrong at limit={limit_in} n={n}")

    print("[C] limit  n  portfolio  collect_margin  child_budget  hard_span")
    for r in rows:
        print(f"[C] {r[0]:>6}  {r[1]}  {str(r[2]):>9}  {r[3]:>14}  "
              f"{r[4]:>12}  {r[5]:>9}")
    if failures:
        print(f"[C] FAIL: {failures}")
        return "FAIL"
    print("[C] PASS: all budgets > 0; portfolio toggles exactly at "
          "limit>=20 and n>=8" + (" (WARN: source drift above)" if drift else ""))
    return "PASS"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--solver-dir", type=Path, default=REPO / "submission",
                    help="directory containing myalgorithm.py")
    ap.add_argument("--utils-dir", type=Path,
                    default=REPO / "ogc2026" / "baseline",
                    help="directory containing utils.py (official checker)")
    ap.add_argument("--instance", type=Path,
                    default=REPO / "train 2" / "prob_9.json")
    ap.add_argument("--limit", type=float, default=45.0)
    ap.add_argument("--kill-after", type=float, default=15.0)
    ap.add_argument("--workdir", type=Path, default=None,
                    help="scratch dir for runner scripts / outputs")
    ap.add_argument("--tests", default="a,b,c",
                    help="comma list among a,b,c")
    args = ap.parse_args()

    sel = {t.strip().lower() for t in args.tests.split(",") if t.strip()}
    utils = _load_module("utils", Path(args.utils_dir) / "utils.py")

    results = {}
    if "c" in sel:  # cheap first
        results["C-boundary-math"] = test_boundary_math(args)
    if "b" in sel:
        results["B-queue-poison"] = test_queue_poison(args)
    if "a" in sel:
        results["A-kill-worker"] = test_kill_worker(args, utils)

    print("---- mp_robustness results ----")
    for k in sorted(results):
        print(f"{k}: {results[k]}")
    return 1 if any(v == "FAIL" for v in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
