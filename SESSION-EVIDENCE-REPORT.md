# SESSION EVIDENCE REPORT — every measurement from the 2026-07-27 shell session
*Companion to `TONIGHT-SUBMISSION-PLAN.md` (the action plan). This file is the
complete measured record backing every decision, for GPT-5.6 to execute from.
Every number here came from running code in this repo; objectives are from the
official checker `ogc2026/baseline/utils.py` unless marked otherwise. Git
branch `finals`, latest commit at writing `ed17583`; shipped submission is tag
`v2.2-slotA` (zip sha256 d9e581d8bdee3279818f4402b8122d6858ff5444014be528a404c492d95db96a).*

---

## 1. Environment facts (verified)

- Local: macOS, 8 logical / 4 performance cores; `/opt/anaconda3/bin/python`
  (Python 3.12, shapely 2.0.7, gurobipy 13.0.1 size-limited academic license).
- Server (verified in-container): Ubuntu 24.04, Python 3.12.3, shapely 2.1.2,
  4 cores (cpulimit THROTTLING not kill), 16 GB, gurobipy 13 full license,
  ortools CP-SAT, no internet. Docker image `ogc-parity` is built locally and
  reproduces this stack (`docker/`).
- Submission mechanics: email zip to submission@optichallenge.com;
  myalgorithm.py at zip root; ≤15 MB; 12 h cooldown; LATEST accepted submission
  replaces previous even if worse; infeasible/crash/timeout = −1/instance.
- CRITICAL CLOCK FACT: preliminary closes 2026-07-28 14:00 KST (10:30 IST).
  Our v2.2 was submitted 2026-07-27 04:57:35 UTC; cooldown ended 16:57 UTC
  (22:27 IST). The NEXT submission is FINAL.

## 2. Shipped-build provenance (v2.2 = tag v2.2-slotA)

Version chain, each step gated:
- v1 (GPT-5.6 original): union-of-layers safety invariant; anytime; checker
  gates every promotion; never-infeasible fallback chain.
- v2: +4-process portfolio, pairwise-verdict cache keyed by relative
  displacement, delta-objective sweep, peak-window-flush destroy.
  40×60 s sweep vs v1: 23 wins / 15 ties / 2 regressions, total −3.0%
  (254,752,424 → 247,016,861).
- v2.1: worker 0 pinned to v1's exact legacy schedule ⇒ portfolio can never
  search worse than v1. Fixed both v2 regressions (prob_35 −6.9% vs v1,
  prob_36 −3.3%; prob_13 −56%, prob_28 −37% preserved).
- v2.2 (SHIPPED): +mp drain-hang fix, +raw-vertex containment bbox fix (both
  fuzz-discovered, see §5), experimental flags dormant.

## 3. Robustness evidence for the shipped build (all green)

- Edge battery (all official-checker feasible): n=600 stress (57.7 s/60);
  m=1; non-contiguous orientation IDs; w1=0; w2=10⁶-dominant; n=5;
  zero-slack (obj1=0!); timelimits 10/21/30 s (9.64/20.21/29.21 s elapsed);
  600 s soak on prob_38: 74.73 M→71.54 M, peak RSS 360 MB (macOS) / 1,402 MB
  (Linux fork ×4 workers).
- Container parity battery: 14/14 PASS (after correcting the battery's own
  kill-test bug — it killed the driver, not a worker; corrected script:
  `docker/kill_test.sh`). Fork kill-test: 4 fork workers (pids observed),
  SIGKILL one at t=15 s → driver rc=0, feasible output.
- Fuzz campaign: 1,597 randomized adversarial instances over 3 lanes
  (macOS spawn ×2, Linux-fork container ×1): 1,567 OK + 30 OVERTIME later
  PROVEN to be self-contention artifacts (window 09:19–09:39 IST coincided
  with an external audit hammering the same laptop; all 3 worst repros pass
  solo: 57.36/60 s, 42.95/45 s, 5.76/6 s).
- L1 differential (layer-true predicate soundness): local shapely 2.0.7:
  3 seeds × 10⁴ cases → 0 false-accepts, FR 0.13–0.22%. In-container shapely
  2.1.2: 9,922 cases → FA=0, FR=3 (0.14%), outcome matrix IDENTICAL to local
  → no shapely-version divergence in near-contact predicates. Marathon:
  210 batches × 5,000 = 1.05 M cases, 0 false-accepts.

## 4. Hidden-instance reality (results email + official interim report)

Our v2.2 hidden scores vs field (interim 2026-07-10; field is better now):

| P | ours | best | median | our position |
|---|---|---|---|---|
| P1 | 12,560 | 11,280 | 12,690 | ≈median; 100+ teams sit at EXACTLY 11,280 and all beat us |
| P2 | 31,368 | 31,368 | 43,292 | TIED WITH BEST — never touch this behavior class |
| P3 | 167,458 | 81,620 | 344,665 | mid; congested-small class (dashboard: 15 infeasible teams = feasibility-hardest) |
| P4 | 5,344,045 | 3,193,472 | 9,595,946 | ×1.67 off best |
| P5 | 24,082,721 | 9,814,507 | 24,312,982 | ≈median, ×2.45 off best — OUR WORST |
| P6 | 47,892,811 | 28,117,781 | 53,860,016 | ×1.70 off best; crash-heavy giant (10 team crashes) |

Rank forensics (live feeds, 402 teams): we are tier 18 (~ranks 171–180); top
30–40 advance. 19 teams made genuine ≥10-tier single-week jumps (Cook 16→4 =
our exact required move); 48% of the field drifts down 1–3 tiers weekly
(scores tightly clustered); one infeasible instance ≈ −370 rank points
(25–35 tiers) and 6 teams end the prelim buried by that. Training proxies:
P1/P2 ↔ prob_1/2/8; P3 ↔ prob_29/22/25; P4/P5 ↔ prob_30/33/31;
P6 ↔ prob_38/40.

## 5. Bugs found and fixed this session (each with repro evidence)

1. **mp drain-hang (v2.2 fix)**: post-terminate `queue.get_nowait()` can block
   forever on a message torn by `terminate()` (partial `_recv_bytes`, no
   timeout, uncatchable) → wall-clock overshoot → −1 class. Fix: drain BEFORE
   terminate, 0.4 s guard, never read queue after terminate.
2. **Containment bbox (v2.2 fix, fuzz-found)**: kestrel used repaired-union
   bounds where the checker uses RAW-vertex bbox (utils Block.bounding_rect);
   on degenerate shapes this emitted out-of-bay placements (reproduced:
   Stage-2 "exceeds bay boundary", kestrel bbox (…,0.15,…,2.53) vs checker
   (…,−0.118,…,3.0)). Fix: raw-vertex bbox for containment; proven zero
   effect on all 40 training instances (raw==union everywhere there).
3. **Hardening set (finals branch, gate-passed)**: P=0 dwell guard (was:
   same-day EXIT-before-own-ENTRY → missing-EXIT infeasible); degenerate
   collinear layers (was: whole run aborted → now proxy orientation, feasible);
   huge-bay grid cap (20000×5000 bay now feasible in 29.2 s/30); deadline-aware
   preprocessing (timelimit=0.05 s honored: was 0.33 s → now 0.05 s);
   env flags → module constants. Paired 40-gate: +0.09% (quality-neutral),
   0 infeasible → PASS.
4. **Harness traps (for the implementer)**: (a) any driver script calling
   `algorithm()` MUST have `if __name__ == "__main__":` — macOS spawn
   re-executes the entry script per worker (we process-bombed twice; Linux
   fork immune); (b) gurobipy models report NumVars=0 before `update()` (lazy);
   (c) heredoc-in-heredoc shell quoting corrupted one runner — write runners
   as .py files; (d) importlib-loaded modules can't be pickled by spawn
   workers — load solver copies via files on sys.path, not importlib specs.

## 6. The measurement-protocol lesson (retractions on record)

- A 40-instance gate returned "+11.57%, 17 regressions, FAIL" for the
  hardening build — RETRACTED: it ran while other sweeps used the machine.
  Clean paired re-run: +0.09% PASS. Same-instance contended-vs-clean examples:
  prob_13 272,725 → 113,827; prob_14 271,944 → 95,407.
- prob_25@45 s measured 351,265 solo vs 654,483 under 2-way contention (86%
  swing). prob_11 shows ±12% run-to-run variance on IDENTICAL code
  (46,011 / 52,955 / 56,917).
- Also retracted: "prob_1 = 1,499 is the proven floor" (heuristic estimate,
  not a proof; LP bound is 988).
- BINDING PROTOCOL: idle machine (pgrep/docker ps first), paired sequential
  arms per instance, checker objectives only. Harness:
  `experiments/paired_gate.py`. Reference paired-clean totals @60 s:
  baseline (hardened) **226,420,836**; per-instance in
  `experiments/results/paired_gate_hardening.log`.

## 7. Diagnostic chain on congested-instance tardiness (FINDINGS F1–F5)

1. Layer-true predicate (exact per-layer + crane rules, certified sound by
   §3 L1 gates) accepts **0 of 250,286** contested positions on prob_25;
   costs 30% of budget; 3.1× throughput loss. Rejection attribution over
   148,299 tests: 95.9% same-layer collisions (unfixable by any rule), 2.7%
   entry-crane, 1.4% exit-order (all genuine overhang candidates die because
   EDD construction is anti-correlated with the required exit precedence).
   → measured DEAD END as a predicate swap.
2. Exhaustive integer scan (every (x,y) × every orientation) for the 6 most
   tardy blocks of prob_38: **0 feasible positions** — candidate enumeration
   is NOT the bottleneck.
3. Occupancy audit: on days tardy blocks waited, bays were 43–46% full by
   POLYGON area (peak 0.59 over whole horizon) yet nothing fit.
4. Same solution measured by RECTANGLE envelopes: 0.71 mean / 0.87 peak —
   i.e. **38% of occupied area is bounding-box padding**, because for
   n > 160 the solver skips polygon construction entirely (one exact pass at
   n=250 did NOT finish in 600 s; solver's shapely path ≈18 µs/test,
   2,181,219 calls / 39.0 s measured).
5. Certified lower bounds (`tests/geometric_lb.py`; validated vs 240
   checker-verified solutions, 0 violations; hand-check self-test returns the
   exact optimum): Z1 is 85–97% of our objective on ten congested instances
   and mostly NOT physics-forced; certified headroom up to 1510× (prob_23);
   only prob_8 proven optimal (11,252 = LB). Forced tardiness proven only on
   prob_27 (LB_Z1=71) and prob_38 (LB_Z1=115). A ≤50%-fill diagnostic says
   packing inefficiency explains at most ~20–30% of our tardiness — the rest
   is SEARCH headroom.

## 8. Raster kernel results (the geometry fix)

- `submission/raster_kernel.py`: integer-lattice masks, S=4; written proof
  chain (superset rasterisation → disjoint masks ⇒ zero true intersection ⇒
  kernel can only be conservative). Differential gate
  (`tests/raster_gate.py`, 432 near-contact pairs from real blocks vs
  utils primitives): **0 false-accepts** (collision AND crane), 6.2%
  conservative over-rejection.
- Throughput: single test 68 µs (slower than solver's tuned 18 µs shapely —
  per-test raster is NOT the win); batch feasible-map **1.19 ms for 1,960
  positions = 0.61 µs/position at S=4 (30×)**. S=2 map anomalously slow
  (93 ms, FFT sizing) — do not use S=2 on the map path.
- One exact polygon construction pass, prob_38 (n=250): shapely scan DID NOT
  FINISH in 240 s (nor 600 s); raster batch **83.0 s**, feasible,
  obj 66,278,940 (Z1 4,864) — vs the shipped build's full 60 s portfolio run
  74,576,673 (Z1 5,485).

## 9. FULL 60-run comparison (COMPLETE; log `experiments/results/full_compare_COMPLETE_60runs.log`; 120/120 JSONs archived; 0 infeasible/failed/missing)

Arms: C = base decoder (finals build), D = raster prototype applied
EVERYWHERE (deliberately blunt, to map the boundary). Paired, un-contended.

- **Phase 1 (all 40 @ 60 s): C 227,458,029 vs D 252,861,564 (+11.17%)** —
  expected: the 83 s pass can't finish at 60 s and the prototype replaces the
  working scan at n ≤ 160.
- **Phase 2 (congested 20 @ 240 s): C 216,974,102 vs D 212,603,809 (−2.01%)**:

| inst | n | C (kestrel) | Z1 | D (raster) | Z1 | delta |
|---|---|---:|---:|---:|---:|---:|
| prob_21 | 100 | 1,196,330 | 60 | 2,074,252 | 124 | +73.38% |
| prob_22 | 100 | 859,937 | 7 | 1,134,136 | 14 | +31.89% |
| prob_23 | 100 | 3,814,626 | 261 | 4,648,641 | 317 | +21.86% |
| prob_24 | 100 | 522,640 | 20 | 844,484 | 38 | +61.58% |
| prob_25 | 100 | 351,265 | 472 | 461,816 | 632 | +31.47% |
| prob_26 | 150 | 13,937,342 | 996 | 17,050,975 | 1,220 | +22.34% |
| prob_27 | 150 | 35,072,828 | 2,504 | 42,345,549 | 3,055 | +20.74% |
| prob_28 | 150 | 2,614,435 | 145 | 5,320,429 | 346 | +103.50% |
| prob_29 | 150 | 553,907 | 5 | 767,118 | 18 | +38.49% |
| prob_30 | 150 | 5,007,693 | 353 | 7,395,431 | 523 | +47.68% |
| prob_31 | 200 | 15,368,404 | 961 | **13,169,640** | 798 | **−14.31%** |
| prob_32 | 200 | 5,333,834 | 1,353 | **4,994,088** | 1,261 | **−6.37%** |
| prob_33 | 200 | 16,504,011 | 2,373 | **14,146,686** | 2,048 | **−14.28%** |
| prob_34 | 200 | 2,343,152 | 571 | 2,400,062 | 644 | +2.43% |
| prob_35 | 200 | 5,021,433 | 346 | **2,759,465** | 175 | **−45.05%** |
| prob_36 | 250 | 376,411 | 392 | 397,348 | 406 | +5.56% |
| prob_37 | 250 | 6,808,140 | 1,812 | **6,188,913** | 1,557 | **−9.10%** |
| prob_38 | 250 | 72,507,727 | 5,327 | **64,010,483** | 4,675 | **−11.72%** |
| prob_39 | 250 | 24,689,358 | 1,786 | **19,214,476** | 1,366 | **−22.18%** |
| prob_40 | 250 | 4,090,629 | 5,949 | **3,279,817** | 4,721 | **−19.82%** |

**CONFIRMED ACTIVATION RULE (implement exactly):** raster construction only
when n > 160 AND remaining budget ≥ 1.6 × est_pass_cost
(est_pass_cost ≈ 83 s × (n/250) × (avg_bay_cells/3270)); on a raster miss at
a time point, FALL THROUGH to the legacy scan; optional regime guard: skip
raster when preference-locked/Z2-heavy (prob_34/36 class: tiny w1). Selective
aggregate = −14.7% on the seven winning n≥200 instances, ~0 elsewhere.

## 10. Gurobi pilot (honest result)

Oracle-sized bay-window time-indexed MIP on prob_38: model builds and solves
in MILLISECONDS at 15–22 blocks (status OPTIMAL 0.02 s) — solver speed is a
non-issue for the CP-SAT/Gurobi repair oracle. BUT the pilot windowed the
easiest (earliest-due) blocks which trivially have zero tardiness, and read
NumVars before model.update() (reported 0) — so it proves SPEED, not VALUE.
The oracle's value must be measured by the funnel (proposals → decoded →
checker-feasible → improvements) during implementation. Local license is
size-limited (fine at oracle sizes); server license is full.

## 11. Where every artifact lives

| artifact | path |
|---|---|
| Action plan for tonight | `TONIGHT-SUBMISSION-PLAN.md` |
| Full finals plan | `CODEX-PLAN-finals.md` (P0.5 has the raster fix spec) |
| Findings F1–F10 | `FINDINGS-finals.md` |
| Ledgers | `RESULTS.md`, `DECISIONS.md` (append-only) |
| Paired-gate harness + reference log | `experiments/paired_gate.py`, `experiments/results/paired_gate_hardening.log` |
| Raster prototype to port | `experiments/myalgorithm_raster_prototype.py` |
| Contact-scoring prototype (re-test after raster lands) | `experiments/myalgorithm_contact_prototype.py` |
| Instrumentation used for F1 | `experiments/diag_instrumentation.py`, `experiments/diag_rejection_attribution.py` |
| 60-run comparison | `experiments/full_compare.py`, `experiments/results/full_compare_COMPLETE_60runs.log`, `experiments/results/full_compare_json/` |
| Kernel + gate | `submission/raster_kernel.py`, `tests/raster_gate.py` |
| Bounds | `tests/lower_bounds.py`, `tests/geometric_lb.py` |
| Fuzz/mp/L1 harnesses | `tests/fuzz_instances.py`, `tests/mp_robustness.py`, `tests/l1_differential.py` |
| Container stack | `docker/` (`run_parity.sh`, `kill_test.sh`, image `ogc-parity`) |
| Zip builder (byte-verifies vs tag) | `scripts/build_submission_zip.sh` |
| Leaderboard poller | `scripts/poll_leaderboard.py` |

## 12. Execution reminders for GPT-5.6

1. Follow `TONIGHT-SUBMISSION-PLAN.md` W1→W2→W3 (W4 only if early), gate per
   its §4, GO/NO-GO 07:45 IST. A not-green gate means SEND NOTHING — v2.2
   stands; a worse final submission is unrecoverable.
2. Never edit: utils.py, myalgorithm_v1_backup.py, training instances,
   worker-0 legacy schedule, `_emit`, the fallback chain, P2-class behavior.
3. Idle machine before every measurement; paired sequential arms; checker
   objectives only; append results to RESULTS.md; commit per work item;
   `git push origin finals` after each gate.
