# Server-parity kit (Docker)

Replays the v2.1 validation battery inside an environment that matches the
competition server: **Ubuntu 24.04, python 3.12 (apt), shapely 2.1.2, 4 CPUs,
16 GB**. The local mac runs shapely 2.0.7 with spawn multiprocessing; the
server runs 2.1.2 with fork — this kit is the only local way to catch a
divergence between the two before submission.

## Run it

```bash
# 1. Open Docker Desktop and wait until the whale icon says "running".
# 2. Then:
bash docker/run_parity.sh
```

That is the whole procedure. The script:

1. builds the image from `Dockerfile.server-parity` (first build downloads the
   ubuntu base + pip wheels, ~2-4 min; later builds are cached),
2. runs the container with `--cpus=4 --memory=16g`, the repo mounted
   **read-only** at `/repo`, and a fresh timestamped results dir mounted at
   `/results`,
3. executes `/work/parity_battery.sh` inside and prints a PASS/FAIL table at
   the end. Exit code 0 = no FAILs.

Results land in `docker/results/<timestamp>/` — one JSON per case plus
`*_meta.json` sidecars (kill-test pid, soak peak RSS) and `env.txt`.

## What the battery covers (~17 min of solver time + overhead)

| step | cases | limit | checks |
|---|---|---|---|
| a | prob_35, prob_36 solo | 60s | feasible; objective within ±30% of mac refs (5.59M / 408k) — drift ⇒ WARN flags shapely 2.0.7 vs 2.1.2 divergence, feasibility flip ⇒ FAIL |
| b | 7 regenerated edge cases (n600, m1, orient 3+2k, w1zero, w2dom, n5, zeroslack) | 30–60s | checker-feasible |
| c | prob_20 at timelimits 10 / 21 / 30 | — | feasible; wall time ≤ limit + 1s (10s = single-process path, 21s = just over the 20s portfolio threshold) |
| d | kill-test: prob_20 @60s, `kill -9` one portfolio worker at t=15s | 60s | parent still returns a checker-feasible dict (fork-specific resilience) |
| e | soak: prob_38 @300s with 2s process-tree RSS sampling | 300s | feasible; peak RSS < 14 GB (else WARN) |

## Files

- `Dockerfile.server-parity` — ubuntu:24.04 + apt python3 (3.12) + venv with
  `shapely==2.1.2 numpy`. No conda, deliberately.
- `run_parity.sh` — host-side build + run wrapper (the only file you invoke).
- `parity_battery.sh` — runs inside the container; stages
  `submission/myalgorithm.py` + `ogc2026/baseline/utils.py` + driver into
  `/tmp/bench`, runs all cases, writes JSON, prints the summary.
- `parity_driver.py` — 15-line bench driver: `algorithm()` →
  `utils.check_feasibility()` → JSON.
- `gen_edge_cases.py` — regenerates the 7 edge instances from the training
  set with the exact recipes used by the earlier local battery.
- `parity_summary.py` — aggregates `/results/*.json` into the PASS/FAIL table
  (FAIL on infeasible/crash/timeout-overrun, WARN on objective drift or RSS).

## Notes

- The repo mount is read-only; nothing in the frozen v2.1 tree can be modified
  by the battery.
- Objective WARNs are expected noise up to a point: the solver is a stochastic
  anytime heuristic, and container CPU scheduling differs from bare metal.
  Investigate a WARN; treat any FAIL (feasibility flip, crash, overrun) as a
  submission blocker.
- Apple silicon: the image builds/runs under emulation or as native arm64
  ubuntu; either is fine for correctness parity (timing will differ from the
  x86 server either way).
