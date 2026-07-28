# OGC 2026 submission — Kestrel

`myalgorithm.py` is the submission entry point and exposes the required:

```python
algorithm(prob_info, timelimit=60)
```

## Method

Kestrel is an anytime spatio-temporal packing heuristic:

1. It immediately constructs a fit-aware serial solution and validates it with
   the official checker. This is the always-feasible incumbent.
2. It builds several fast schedules using all-layer rectangle envelopes,
   urgency rules selected from the instance regime, exact marginal workload
   imbalance, and exact bay-preference regret.
3. For instances where it is computationally worthwhile, it replaces rectangle
   packing with true irregular-polygon packing.
4. It improves the incumbent with exact-objective single-block reinsertions and
   time-window/bay ruin-and-recreate neighborhoods.
5. Every promoted incumbent is accepted only after
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
and spends remaining time on coordinated improvement.

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
- Submission uses only Python's standard library and Shapely, both present in
  the published OGC environment.

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

v2.1: portfolio worker 0 pinned to the proven v1 destroy/repair schedule
(the portfolio can never search worse than the prior submission); workers
1-3 explore the extended operators.

Validation (all via the official checker): 40-instance sweep at 60 s all
feasible, 23 wins / 15 ties / 0 regressions after v2.1 (total objective
-3.0% vs v1, before the v2.1 fix which further improved prob_35 -6.9% and
prob_36 -3.3%); 120 s probes prob_1 8,847 -> 1,499 (assignment-floor
optimum), prob_9 -> 50,885; edge battery all feasible (n=600 stress, m=1,
non-contiguous orientation ids, w1=0, dominant w2, n=5, zero-slack;
time limits 10/21/30 s each finishing inside deadline); 600 s soak on
prob_38 feasible, peak RSS 360 MB across all processes.
