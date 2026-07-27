# MISSION PROMPT for GPT-5.6 — OGC 2026 finals solver: close the certified gap

*Copy everything below this line into the GPT-5.6 session. Repo:
`/Users/vedantmoghe/Downloads/optichallenge`, branch `finals`.*

---

You are the lead algorithm engineer for the OGC 2026 finals (opens Aug 3 14:00
KST, closes Aug 14). The preliminary submission is safe (tag `v2.2-slotA`,
never touch it). Your mandate: **maximize measured objective improvement on the
congested training instances (prob_21–40), because that is where the certified
optimality gap lives and where leaderboard ranks will separate.** We believe we
are behind the top tier; act like it — pursue the strongest mathematically
grounded methods, but every claim must survive the measurement protocol below.
No idea ships on plausibility.

## 1. Established facts you must build on (all measured in this repo — do not re-derive, do not doubt without new data)

1. **Tardiness (Z1) is 85–97% of our objective on ten congested instances**, and
   certified lower bounds (`tests/geometric_lb.py`, validated against 240
   checker-verified solutions with zero violations) prove most of it is NOT
   physically forced. Certified headroom: prob_23 1510×, prob_33 1078×,
   prob_39 1067×, prob_30 308×. Only prob_8 is proven optimal. **Scheduling
   search quality is the #1 lever.**
2. **Geometry boundary (from the 60-run A/B, experiments/full_compare.py):**
   the raster kernel (`submission/raster_kernel.py`, sound, 30× batch) applied
   *everywhere* is +11.17% worse at 60 s — because at n ≤ 160 it replaces an
   exact scan that already works, and at 60 s its ~83 s construction pass
   cannot finish. Applied *only* where the alternative is rectangle packing
   (n > 160, budget ≥ pass cost), it wins **12–20%** (prob_38 −12.3%,
   prob_33 −13.9%, prob_40 −19.7% at 240 s). The dispatch rule is written in
   `CODEX-PLAN-finals.md` §P0.5. Geometry is the #2 lever, and only via that
   selective rule.
3. **Kestrel's search gets stuck in deep local optima by construction**: strict
   improvement acceptance + destroys capped at ~12 blocks cannot cross
   worse-before-better valleys (e.g., a late block that needs three on-time
   blocks temporarily displaced). This diagnosis is consistent with fact 1.
4. **Measured dead ends — do not spend time on**: per-layer/overhang
   feasibility (0 accepts in 250,286 tests), ALNS operator-weight adaptation
   (0.14% mean across 25 published implementations, EJOR 2021), DFF area
   bounds (dominated 0.974–1.000), monolithic MIP/CP over a whole instance
   (1/25 feasible at 1 h in the closest published analogue, arXiv 2512.11864).
5. **Environment**: server Ubuntu 24.04, Python 3.12, 4 cores, 16 GB, shapely
   2.1.2, numpy/scipy/numba/cython, **gurobipy 13 LICENSED**, ortools CP-SAT,
   no internet at runtime, limits 30 s–30 min. The official checker
   `ogc2026/baseline/utils.py` is ground truth and read-only; every accepted
   incumbent must pass it; the never-infeasible fallback chain must survive
   every change.

## 2. Your task, in priority order

**T1 — Blame-driven large-neighborhood search with regret repair (do first).**
Replace the small random destroys: compute blame (w1·T_i for late blocks,
propagated fractionally to the blocks that occupied their bay-window during
[R_i, ENTRY_i]); destroy the 15–30 most-implicated related blocks (the late
block + its blockers + due-date neighbors + a random handful); recreate with
regret-k insertion (prioritize blocks whose second-best placement is much worse
than their best). Add **Late Acceptance Hill Climbing** (ring buffer L≈50–300;
scale-free, survives w1 ranging 667–29,630) on workers 1–2 only; worker 0
keeps the legacy schedule (the never-worse anchor). Measure accepted-move rate
and improvement-per-second before and after.

**T2 — CP-SAT bay-window repair oracle (after T1 is measured).**
Free 15–25 blocks in the highest-blame (bay, day-window); fix everything else;
CP-SAT intervals + `AddCumulative(capacity = α·bay_area)` with layer-0 areas as
demands, α calibrated ≈ 0.85–0.92; objective Σ T_i; dominance precedences
(d_i ≤ d_j ∧ p_i ≤ p_j ⇒ i before j) and incumbent as hint + upper bound;
`num_search_workers=1`, per-call budget ≈ 2% of remaining time. Decode the
proposed days through the normal geometric decoder; adopt only on
checker-verified improvement. **Report the funnel**: proposals → geometrically
decoded → checker-feasible → improvements. If decode rate is poor, tune α down
or hand the cycles back to T1. Literature anchors: Godard–Laborie–Nuijten
ICAPS'05 (randomized LNS on cumulative: 33/36 open instances improved); Hooker
OR 2007 logic-based Benders (25–1000× on min-tardiness structures); BALANS
arXiv 2412.14382 (LNS-over-solver: >75% primal-gap reduction).

**T3 — Selective raster dispatch (after the 60-run comparison finishes).**
Implement exactly §P0.5 of CODEX-PLAN-finals.md: n ≤ 160 → legacy exact scan;
n > 160 ∧ budget ≥ 1.6× estimated pass cost ∧ forced_density ≤ ~1.18 → raster
construction; else rectangle decoder. On raster miss, FALL THROUGH to the
legacy scan. Every raster-selected position still gets exact shapely
confirmation. Do not change the union-of-layers feasibility semantics.

**T4 — Go deeper mathematically (your research mandate).**
Where you have web access, find and evaluate stronger formulations than T1–T3;
where you don't, reason from the papers already vetted (below). Directions we
consider promising but unproven here, in descending order of our prior:
  a. **Dynasearch** on per-bay entry sequences (DP over independent adjacent
     interchanges, O(n²)/pass — finds the best *set* of swaps, not one).
  b. **Matching-based cross-bay very-large-neighborhood**: best simultaneous
     one-for-one exchange between two bays via weighted bipartite matching on
     exact Z2/Z3 deltas + estimated Z1 deltas.
  c. **Time-indexed LP per bay as a pricing/guide**: x[j,t] start binaries,
     one area row per day (≈16k binaries at n=80, T=200 — trivially in
     Gurobi's range); its LP is famously tight for ΣwT; use duals to price
     "which day-window is most oversubscribed" and aim T1/T2 there.
  d. **Sparrow-style overlap-tolerant separation** (arXiv 2509.13329, current
     published SOTA in irregular packing; integer-lattice precursor
     Umetani–Murakami arXiv 2104.04525): insert one tardiness-critical block
     with overlap allowed, then guided-local-search it to zero overlap via
     penetration-depth line searches with pair-penalty weights. Requires
     no-fit-raster tabulation with shape-class dedup (~0.25 GB — feasible).
  e. Anything better you can find and DEFEND with a measured pilot. You have
     freedom here — the constraint is the protocol, not the idea list.

## 3. Measurement protocol (binding — verdicts from violations are void)

- **Idle machine**: check `pgrep -f driver.py; pgrep -f full_compare; docker ps`
  before every run. We measured 8% phantom regressions and one sign-flipped A/B
  caused purely by CPU contention.
- **Paired sequential arms**: for each instance run baseline then candidate
  back-to-back (harness pattern: `experiments/paired_gate.py`).
- **Gate**: 40 instances @60 s (0 infeasible; total ≤ +0.5%; no instance worse
  than +2% unexplained) and, for anything touching congested behavior, the 20
  congested @240 s. Reference totals: 226,420,836 (paired 60 s baseline);
  congested-4 @240 s kestrel 128,524,894.
- Objectives come only from `utils.check_feasibility`. Never from your model.
- Log every experiment in `RESULTS.md` (append-only) and every decision with
  evidence in `DECISIONS.md`. These become the finals technical report, which
  is published — write accordingly.

## 4. Deliverables

1. T1 implemented + gated, with accepted-move-rate and improvement/sec metrics.
2. T2 implemented + the funnel report (or a measured rejection of T2).
3. T3 implemented once `experiments/results/full_compare_*.log` is complete.
4. A short `RESEARCH-NOTES.md`: what you tried from T4, pilots run, numbers,
   verdicts — including negative results (they are as valuable; see the
   dead-ends table we already paid for).
5. A submission-candidate recommendation with its full gate evidence, and the
   zip built via `scripts/build_submission_zip.sh <tag> <name>` only.

Context files, in reading order: `HANDOFF.md` → `CODEX-PLAN-finals.md` →
`FINDINGS-finals.md` → `COMPARISON-kestrel-vs-raster.md` → `research/01`
(checker rules audit with line references) → `research/02` (instance
analytics). Good luck — the gap is certified to be there; go take it.
