# OGC 2026 submission — Kestrel Slot B

`myalgorithm.py` is the submission entry point and exposes the required:

```python
algorithm(prob_info, timelimit=60)
```

## Method

Kestrel is an anytime spatio-temporal packing heuristic:

1. It immediately constructs a fit-aware serial solution and validates it with
   the official checker. This is the always-feasible incumbent.
2. On low-congestion instances with at most 200 blocks, one portfolio worker
   solves the exact `Z2 + Z3` bay-assignment master with Gurobi, then passes
   that assignment through the ordinary geometric decoder and repair search.
3. It builds several fast schedules using all-layer rectangle envelopes,
   urgency rules selected from the instance regime, exact marginal workload
   imbalance, and exact bay-preference regret.
4. For instances where it is computationally worthwhile, it replaces rectangle
   packing with true irregular-polygon packing.
5. It improves the incumbent with exact-objective single-block reinsertions and
   time-window/bay ruin-and-recreate neighborhoods.
6. Every promoted incumbent is accepted only after
   `utils.check_feasibility()` passes.

The core safety invariant is stronger than the formal collision rule: any two
blocks whose residence intervals overlap have disjoint interiors for the unions
of all their layers. Consequently, both the static layer constraints and every
vertical ENTRY/EXIT crane sweep are feasible without post-hoc repair. Same-day
EXIT-before-ENTRY reuse remains fully available.

## Why this differs from the baseline

The supplied baseline repeatedly discovers crane-order violations after
construction and can push repeat offenders into far-future empty-bay windows.
Kestrel makes crane safety constructive, uses actual polygon geometry rather
than AABBs in its strong decoder, calculates exact `Z2`/`Z3` assignment deltas,
solves the loose-regime assignment floor directly, and spends remaining time
on coordinated improvement.

The design follows established spatial-scheduling ideas—priority-rule decoding,
bottom-left/contact placement, and sequence search—while adapting them to the
competition's layered crane rule. Relevant literature includes Kwon and Lee's
shipbuilding spatial-scheduling work (Computers & Industrial Engineering 89,
2015), Ge and Wang's irregular-block method (Computers & Industrial Engineering
152, 2021), and Shang et al.'s best-contact plus genetic search method
(Mathematical Problems in Engineering, 2017).

## Local validation

- Python syntax compilation: passed.
- Official `utils.check_feasibility`: passed on all 40 supplied training
  instances at a deliberately short 2.5-second limit.
- Representative improvements:
  - `prob_1`: prior baseline 795,089 with 26 tardy days after 56.5 seconds;
    Kestrel 8,847 with zero tardy days.
  - `prob_25`: prior baseline 823,887 with 1,192 tardy days after 221 seconds;
    Kestrel 351,265 with 472 tardy days in a 60-second run.
- Submission uses Python's standard library, Shapely, and optionally Gurobi;
  all are present in the published OGC environment. If Gurobi import, licence,
  or solve fails, that seed is skipped and the original anytime path continues.

The server supplies/overwrites `utils.py`; it is intentionally not included.

## v2 changes (2026-07-27)

1. **4-process best-of portfolio** (the evaluation budget is 4 CPU cores):
   diversified seeds and construction-mode rotations per worker; workers
   stream checker-verified incumbents to the parent, so a worker terminated
   at the deadline still contributes. Short limits (<20 s) use the proven
   single-process path unchanged.
2. **Pairwise collision-verdict memoization** keyed by relative displacement
   (overlap of P at (x,y) vs Q at (u,v) depends only on (P, Q, x-u, y-v)).
   Verdicts are exact shapely results; the cache only avoids recomputation.
3. **Delta-objective reinsertion sweep** (O(bays) imbalance delta per trial
   instead of a full O(n) objective rescan) and per-(block, bay) orientation
   order caching.
4. **Peak-window flush** destroy operator: evicts every block entering one
   bay around a blamed block's entry date (up to 48) and re-times them
   jointly under four rotating repair orderings - a coordinated re-timing
   move single-block reinsertion cannot express.

## Slot B changes and validation (2026-07-27)

1. **Exact assignment master.** For data-derived low-congestion cases
   (`release_peak_density <= 0.49`, `n <= 200`, limit at least 8 seconds),
   worker 0 solves the binary bay assignment with exact preference regret and
   scaled-workload imbalance. It has one thread and a 1.5-second hard cap.
   The proxy never bypasses the real geometry or objective: decoded candidates
   are promoted only when their full objective improves and the official
   checker accepts them.
2. **Exact layer/event predicate, retained inactive.** Per-layer static and
   asymmetric crane relations are implemented with pairwise replay in the exact
   `_emit` order. A 100,000-case differential test across 10 diverse instances
   found zero false accepts and zero false rejects. Its constructors were
   nevertheless slower and worse on congested probes, so the production search
   deliberately retains the proven union-envelope invariant.
3. **Reproducible tester driver.** `research/benchmark_solver.py` (outside the
   zip) exercises the real multiprocessing entry point and saves UI-compatible
   solution JSON.

Evidence:

- Parent v2: full 40-instance 60-second sweep, all checker-feasible.
- Slot B: full 40-instance 2.5-second stress sweep, all checker-feasible.
- Real 4-worker 60-second runs:
  - `prob_1`: 8,847 → **1,499**, zero tardiness (assignment-floor optimum);
  - `prob_9`: 68,550 → **50,885**, zero tardiness;
  - `prob_25`: **351,265**, unchanged capacity-bound control.
