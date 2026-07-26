# OGC 2026 — Finals Strategy: "KEEL"
### Exact-raster unified LNS with decoder-repair and a bounded assignment seed

*Produced 2026-07-27 by an 11-agent orchestrated analysis: instance analytics over all 40 training
instances, line-level adversarial audit of the official checker (`utils.py`), baseline benchmarking,
4 literature sweeps (shipyard spatial scheduling, irregular packing/nesting, isomorphic problems,
competition engineering incl. prior OGC editions), 3 independently designed solver architectures,
and an adversarial judge synthesis.*

---

## 0. Executive summary

The problem is a layered-polygon spatial scheduling problem (blocks = polygonal prisms occupying
bay × position × layers × time). Three structural theorems decide the whole strategy:

1. **Assignment decomposition.** Z2 (workload imbalance) and Z3 (preference regret) are pure
   functions of the bay-assignment vector; given the assignment, bays decouple into independent
   "minimize weighted tardiness under spatial + crane feasibility" subproblems (parallelizable
   over the 4 allowed cores). Every cross-bay move has an *exact O(1)* Z2+Z3 delta — the
   assignment dimension can be searched exactly without geometry.
2. **Crane rule = interval-nesting forest.** The j ≥ k lift rule means block A's upper layer may
   overhang block B's lower layer only if A enters after B and exits before B (boundary equality
   legal via same-day op ordering). Overhangs are *free packing area priced by LIFO precedence* —
   35% of multi-layer blocks are "mushrooms" (upper layer larger than base). No published paper
   handles this constraint; it is our novelty core.
3. **Guaranteed feasibility.** Time is unbounded above; serializing blocks into empty-bay windows
   is always feasible (verified through the checker at n=300). A submission must **never** score
   −1; 100% of the clock goes to improvement over an always-held feasible incumbent.

Economics: w1 (tardiness) ∈ [667, 29630] per day vs w3 ∈ [13, 600] per preference point and
w2 ∈ [1, 10]. The baseline's objective on prob_1 is **95% tardiness** on an instance where zero
tardiness is achievable — tardiness elimination via denser true-polygon packing is where the
leaderboard is won, with Z3 the tiebreaker on loose instances.

The winning architecture (**KEEL**) = exact integer rasterized geometry (bit-ops, 100–1000× the
baseline's shapely throughput) + unified ALNS with a chronological *decoder-repair* operator +
a 1-second Gurobi assignment seed + 3 search replicas + 1 orchestrator on 4 cores + a
never-infeasible anytime shell.

---

## 1. Verified rules of the game (checker `utils.py` is ground truth, all verified by execution)

| # | Fact | Consequence |
|---|------|-------------|
| 1 | Violation requires `intersection.area > 0`; AABB prefilter is strict `<` | Flush edge/corner contact is legal → zero-clearance packing |
| 2 | Stage 2/3 use strict `entry < t < exit` (same-day events excluded); Stage 5 replays ops **in our listed order**, all EXITs before ENTRYs per day | Same-day EXIT→ENTRY space reuse (JIT chains); same-day nest construction/unwinding via op order |
| 3 | Crane j ≥ k confirmed: 2-layer block may enter overhanging a co-present 1-layer block; the short one then can't exit until the roof leaves | Overhang ⇒ interval nesting `[E_A,X_A] ⊆ [E_B,X_B]`; K=1 vs K=1 co-present plan-view overlap is never legal |
| 4 | Stage 4 checks only same-index layers k↔k for time-overlapping pairs | Standing overhangs are never re-checked statically — only at ENTRY/EXIT events |
| 5 | `int(round())` = banker's rounding; positions are effectively integers; time keys must be canonical decimal-int strings; out-of-range block_id **crashes the checker** | Emit defensively; integer lattice makes raster geometry exact |
| 6 | No upper bound on times; fallback verified feasible at n=300 (must search bays — some blocks don't fit every bay) | −1 is structurally avoidable |
| 7 | Fractional-flush contact (equal 1e-4 fractional parts): ~2.15% of configs show 1-ulp overlap → area ~1e-14 > 0 → violation | Never emit fractional-fractional flush unverified; integer-aligned contact and ≥1e-4 gaps are safe |
| 8 | Full `check_feasibility` costs 40–60 ms at n=300 | Affordable as a gate on every incumbent promotion, not in inner loops |
| 9 | PDF vs code: code is *more permissive* (PDF's N(t,j) would outlaw same-day nesting choreography; the code legalizes it) | Optimize against the code, document the difference in the report |

## 2. Instance regimes (from analytics over all 40 instances)

- **Set 1 (prob_1–20)**: staggered releases (0–141), short P (3–13), demand/supply 0.14–0.29,
  peak instantaneous demand 0.28–0.47 of bay area → **loose**. Zero tardiness achievable;
  ranking is decided by Z3 (median best-vs-2nd preference gap ≈ 45 points) and residual Z2.
- **Set 2 (prob_21–40)**: burst arrivals (all R ∈ 0–47), long P (5–31), peak demand 0.51–1.61;
  p25/p27/p33/p38/p40 have peak > 1.0 (physically impossible to run all blocks on time) →
  **congested**. Packing density is the binding constraint; objective mass lives here.
- **Regime classifier at t=0** (compute from weights, not memorized): preference-locked if
  w3·gapMed/w1 > 3 (p32≈8.1, p37≈7.7, p34≈5.8 — treat Z3 as near-hard there); Z2-sensitive if
  w2·(ΣL/m)/w1 > 5 (p40≈16, p37≈14, p34≈13, p32, p33, p36, p25).
- Slack: **no negative slack anywhere**; 21.5% of blocks have zero slack (must enter at R, exit
  at R+P to be on time); median slack 2.
- Shapes: ≤12 vertices, median convexity 0.986, **median bbox fill 0.67** → true-polygon packing
  recovers ~33% capacity vs AABB (the baseline's core weakness, decisive on set 2).
- Layers: 86.7% multi-layer; 35.7% pyramids, **34.9% mushrooms**; mean overhang 15.6% of area.
- Fit: ≥93% of blocks fit every bay → assignment is nearly unconstrained by geometry.
- Preferences uncorrelated with size (r ∈ −0.13..0.18): no structural excuse needed to divert.

## 3. Baseline diagnosis (measured locally, 240 s limit, anaconda shapely)

| Instance | n | Regime | Time | Objective | obj1 (days) | obj2 | obj3 | Tardiness share |
|----------|---|--------|------|-----------|-------------|------|------|-----------------|
| prob_1  | 100 | loose (peak 0.47)  | 56.5 s  | 795,089   | 26    | 389   | 180   | **95%** |
| prob_9  | 200 | loose (peak 0.33)  | 183.0 s | 2,362,394 | 168   | 1,120 | 779   | **95%** |
| prob_25 | 100 | congested (peak 1.26), tiny weights | 221.0 s | 823,887 | 1,192 | 463 | 1,418 | **96%** |

Tardiness is 95–96% of the baseline objective in *every* regime — including loose instances where
zero tardiness is achievable (prob_1/prob_9 → ~20× objective reduction is on the table from
scheduling/packing alone). Root causes: AABB-only candidates (median 33% wasted area), EDD myopia,
no improvement phase, ~10³ shapely placements total, and no use of the leftover time budget.
Every component is beatable by an order of magnitude.

---

## 4. KEEL architecture

### 4.1 Geometry engine — exact integer raster calculus
- Scale all vertices ×10⁴ → exact int64; **integer scanline rasterization** (zero floating point):
  cell marked iff area(cell ∩ polygon) > 0. Sub-grid S=4 (0.25 cells), S=8 escalation for
  hard-to-place blocks, S=2 memory degrade. Bays ≤ 180×29 → masks are tiny; ≤30 MB total.
- Bit-packed uint64 rows; 64/S pre-shifted phase copies per mask → any position test is
  word-aligned AND. Per (block, orient, layer): mask, prefix-OR D_j = ∪_{k≤j} M_k, 1-cell-dilated
  contact mask. Per (bay, day, layer): packed occupancy grid stamped half-open [entry, exit),
  post-exit day states (matches Stage-5 replay), plus per-day event masks.
- **Soundness theorem** (protects against −1): positive-area marking + integer translation ⇒
  raster-disjoint ⇒ shapely area exactly 0. The known 1-ulp sliver class is auto-rejected (its
  contact line falls strictly inside a cell column) — *the raster is strictly safer than the
  evaluator's own floats*. Only cost: false rejection of clearances < √2/S ≈ 0.35; commit-time
  shapely rescue (checker-identical arithmetic) for candidates that would kill a tardy day.
- **Four O(words) primitives**:
  - **P1** same-layer collision over stay: mask ∧ (OR of day-grids over [t,e)) — exact, not conservative.
  - **P2** entry crane: occ[t][j] ∧ D_j = 0 for all j (identity form of j ≥ k).
  - **P3** exit crane: same test vs day-grid[e−1].
  - **P4** reverse crane: placing me must not break *other* blocks' lifts occurring strictly
    inside my interval — event-mask AND per event day. **Mandatory**: without P4, out-of-order
    insertion under/over existing blocks silently produces Stage-2 violations (proven by
    counterexample during judging). P4 also *prices overhangs automatically* — an overhang is
    accepted exactly when the roofed block's exit doesn't fall inside our interval.
- Cost: single candidate test 0.1–3 µs; full-bay all-positions map 0.3–3 ms; vs 42 µs per single
  shapely test. Implementation ladder: **numba `@njit(cache=True)` first** (set NUMBA_CACHE_DIR,
  warm on a dummy instance inside `algorithm()`), prebuilt Ubuntu-24.04 pybind11 .so as optional
  accelerator, numpy fftconvolve as last resort. Build C++ only if E1 shows numba can't hit
  ≤5 µs/candidate.

### 4.2 Representation
Flat arrays `bay[i], x[i], y[i], o[i], entry[i]` with `exit = entry + P` invariant (dwell is never
chosen — it only costs space). **Monotone Listing Invariant (MLI)** for Stage-5 choreography: a
newly inserted block's ENTRY is *appended* to its day's entry list, its EXIT *prepended* to its
day's exit list — with conservative day-state checks, Stage-5 replay then checks each op against a
subset of what the engine already checked ⇒ Stage 5 passes by invariant (validated in E2).
Incremental objective ledger: O(1) Z2/Z3 deltas, exact Z1.

### 4.3 Construction (~5% of budget)
1. **Assignment seed** — Gurobi MIP, ≤1500 binaries: min w3·regret + w2·(linearized pairwise
   imbalance) + λ·bucket-overload (LOAD relaxation: per 7-day bucket, Σ area·P ≤ η·bayArea·len,
   η = 0.7). TimeLimit 1 s, Threads 1; fallback CP-SAT → greedy regret ranking.
2. **Day-major ATC-space admission**: priority_i(t) = exp(−(D_i−P_i−t)⁺/(k·p̄)) / (area_i^α·P_i^β)
   — EDD is the k→0, α=β=0 special case; the space-time denominator stops one huge urgent block
   starving several small ones (the baseline's failure mode on congested instances).
3. **Placement scoring** on the raster maps: contact popcount weighted by neighbor exit-date
   similarity (space frees contiguously in time), diagonal fill (grow from two opposite corners,
   keep a central corridor — also reduces crane blocking), wall bonus, and a P4-priced
   **mushroom-roofing bonus** (overhang long-stayers over shorter-exit neighbors = free area).
4. **Squeaky-wheel wrapper**: construct → blame_i = w1·T_i + w3·regret_i → promote blamed blocks
   in the priority order → reconstruct; 10–30 rounds.

### 4.4 Improvement — ALNS (~88% of budget)
- **Destroy** (adaptive weights, 5–15% of n): worst-blame/SWO, Shaw-related, time-window ruin,
  spatial-cell ruin, bay-flush, preference-repatriation (attacks Z3 — the ranking currency on
  set 1), Z2-balance swap (regime-gated). Cross-bay moves use the exact O(1) Z2+Z3 deltas — the
  operators *are* the assignment master.
- **Repair**: regret-2, most-constrained-first, randomized greedy — all via the fast insertion
  primitive (top-3 bays × ≤6 candidate entry days × contact/skyline candidates × P1–P4).
- **DECODER-REPAIR (the hybrid's key operator)**: pick a bay and day t0; unstamp every block with
  entry ≥ t0 plus the destroyed set; re-run the day-major constructor from t0 over the freed
  state. This is the *coordinated re-timing* move pure insertion-LNS lacks (its most likely
  failure mode on congested instances: "push k blocks 2 days later and repack the hole" is
  otherwise a chain of k independent uphill moves SA will never sequence). Cost 50–300 ms,
  weight-adapted like any operator.
- **Acceptance**: SA calibrated so a 1-tardy-day-equivalent uphill move accepts w.p. 0.5 at start,
  cooled by elapsed fraction; one replica runs record-to-record (2% deviation) as a hedge.
- Every K improvements: left-shift compaction sweep. Every incumbent promotion: bundled
  `check_feasibility` gate (40–60 ms) + re-serialization of the output dict.

### 4.5 Gurobi — two bounded roles only
(1) the construction assignment seed; (2) regime-gated re-solve every ~60 s (only when
preference-locked or Z2-heavy per §2 classifier) with realized-tardiness pseudo-costs for visited
pairs and a trust region Σ(1−x_{i,a*}) ≤ 0.05n, applied as a targeted bay-flush; skipped below
5-minute limits. Full Benders-style master⇄slave iteration was judged **non-convergent**
(optimism bias on unvisited pairs) and is deliberately excluded. E3 decides whether even role (2)
earns its keep.

### 4.6 Parallelization (4 cores)
Fork after construction (COW-shared masks; OMP/OPENBLAS/NUMBA/Gurobi threads pinned to 1).
**3 ALNS replicas** (distinct seeds, operator mixes, cooling; one record-to-record) + **1
orchestrator** (checker gating, incumbent migration every ~15 s with re-verification, regime-gated
MIP re-solves, serialization). Lagging replica (>10% behind for 60 s) reseeds from global best +
30% ruin. m=1: cross-bay ops disabled, replicas differ by seed.

### 4.7 Never −1 (anytime shell)
t < 1 s: fits-aware far-future serialized fallback held on disk. Hard deadline = start +
timelimit − max(5 s, 3%). Signal watchdog + explicit clock checks in every loop + global
try/except, all returning the last checker-verified serialized incumbent. Canonical decimal-int
time keys; block/bay-id range asserts before emission. Nothing is ever emitted that has not
passed the bundled checker.

Budget: 2% parse/triage/fallback · 5% construct+SWO · 88% ALNS · 5% verify/emit — all keyed to
elapsed fraction so 3-minute and 30-minute limits work untouched.

---

## 5. Six-milestone roadmap (ordered by leaderboard value per effort)

| # | Milestone | Definition of done |
|---|-----------|--------------------|
| M1 (wk 1, ~3 d) | **Safety floor**: parser, fits-aware fallback, canonical emitter, deadline watchdog, 40-instance batch harness | Feasible dict on every training instance at {60, 300, 1800} s, zero crashes across 5 seeded runs; harness prints Z1/Z2/Z3 |
| M2 (wk 1–2) | **Geometry kernel**: exact rasterizer, packed masks, day-grids, P1–P4, numba warm-cached, shapely rescue | Differential test vs `utils.py` on ≥10⁵ random placements/instance: **zero false-accepts**; false-reject < 5% of near-contact candidates at S=4; ≤5 µs/candidate, ≤3 ms full-bay map, <300 MB at n=300 |
| M3 (wk 2–3) | **Constructor + SWO**: MIP seed, day-major ATC-space decoder, contact/diagonal/overhang scoring, same-day reuse | Beats baseline on ≥35/40 instances within 60 s; Z1=0 on ≥15/20 set-1 instances; 100% checker pass |
| M4 (wk 3–4) | **Single-core ALNS**: MLI insertion, full destroy/repair portfolio incl. decoder-repair, SA, compaction, checker-gated promotion | ≥15 sustained iter/s at n=300 on p38 (worst case); ≥15% mean improvement over M3 at 5 min on set 2; 0 checker rejections over 40×3 runs |
| M5 (wk 4–5) | **Assignment layer + 4-core portfolio**: cross-bay ops with exact exchange-rate tests, regime classifier, gated MIP re-solve, replicas + orchestrator | Set 1: Z1=0 with Z3 within 5% of preference-argmax on ≥18/20; p32/p34/p37 ≥10% better than frozen-assignment ablation; 4-core@5min ≥ 1-core@15min |
| M6 (wk 5–6) | **Hardening + report assets**: adaptive S, memory governor, degraded modes, Ubuntu 24.04 container sweep, ablation runs, report skeleton | Container sweep 40 × {180, 600, 1800} s: zero crashes/timeouts; ablation table complete |

## 6. Three de-risking experiments to run FIRST

- **E1 — kernel differential test** (gates the whole geometry bet): ≥10⁵ near-contact-biased random
  placements per instance; assert raster-accept ⇒ checker-accept (must be exactly 0 violations);
  measure false-reject rate vs S and the reverse-crane (P4) scan cost on long-P dense states
  (p27/p38) to validate realized iterations/s.
- **E2 — Stage-5 choreography stress** (gates the MLI invariant): thousands of randomized insertion
  sequences (same-day exit→entry reuse, nest construction/unwinding, boundary-equal nestings,
  same-day cascades) emitted under MLI and replayed through `check_feasibility`; include the
  out-of-order-overhang counterexample class with and without P4 (without must fail, with must
  100% pass).
- **E3 — value-of-information on the assignment dimension** (gates Gurobi's scope): on
  {p1, p8, p20, p27, p32, p40}, 5-minute budget, compare (i) preference-argmax frozen,
  (ii) MIP seed frozen, (iii) + cross-bay LNS ops, (iv) + one mid-run MIP re-solve. Decides
  with data whether the re-solve earns its complexity.

## 7. Technical-report novelty package (finals are judged on report + presentation too)

1. **Reverse-crane raster calculus**: first formalization of a vertical layered lift constraint in
   spatial scheduling (closest published work handles only horizontal transporter obstruction);
   prefix-OR mover masks × suffix-layer grids, the monotone-shadow persistence theorem, and the P4
   event-mask primitive with a proof of bit-identical equivalence to the evaluator's Stage-5 replay.
2. **Monotone Listing Invariant**: a one-line op-ordering rule with a subset-argument proof that
   turns same-day nest choreography and zero-turnaround space reuse into a free invariant.
3. **Exact-integer rasterization strictly safer than the evaluator's own floats**: the ×10⁴ scaling
   argument (every raster-accepted contact is exact-zero in IEEE754 shapely; the 1-ulp sliver
   class is auto-rejected) — a certifiable zero-clearance packing engine.
4. **Priced mushroom roofing**: deliberate overhang packing (35% of multi-layer blocks) with
   LIFO-nesting cost emerging from P4, tied to Block-Relocation-Problem blocking-pair theory.
5. **Ablation table** (report gold): AABB→raster, EDD→ATC-space, no-overhang→priced overhang,
   no-decoder-repair→full portfolio, frozen→searched assignment.

## 8. Literature anchors (for the report's related-work section)

He, Hong & Kim, *J. Scheduling* 2024 (two-phase matheuristic, 637–810 blocks, rectangles-only —
our decomposition's published ancestor); Lee, Lee & Choi 1996 (DAS-CURVE, field-founding);
Kwon & Lee, *CAIE* 2015 (diagonal fill); Shang et al. 2017 (time-aware best contact); Ge & Wang
2018/2021 (irregular blocks, angle-simplified geometry — nobody does exact geometry in-loop);
Frontiers Mar. Sci. 2026 (only removal-obstruction paper — horizontal, not vertical); Tanaka et
al. (BRP blocking pairs); Bennell & Oliveira tutorials (raster representation legitimacy);
Burke et al. 2006 BLF; Chehrazad et al. 2021 (semi-discrete BLF, ms-scale); Egeblad et al. 2007
(overlap-landscape moves); Joslin & Clements 1999 (SWO); Ruiz & Stützle 2007 (iterated greedy);
Ropke & Pisinger (ALNS); ATC/ATCR family for weighted tardiness.

**Prior OGC intelligence**: OGC 2024 winner (SNU "DMS") code is public — thin Python entry →
pybind11 C++ ALNS ⇄ Gurobi set-partitioning, per-instance parameter tables with general fallback,
explicit SPARE_TIME clock paranoia. Copied to `reference-ogc2024-winner/` in this folder (incl.
their presentation). OGC 2025 (RoRo stowage with port-LIFO precedence — a cousin problem) winner:
SNU "tryAgain". The committee's revealed preference: ALNS-matheuristic hybrids with compiled
cores, novelty spent on problem structure.

## 9. Top risks and mitigations

| Risk | Mitigation |
|------|------------|
| Hidden instances outside training envelope (n≫300, huge bays/horizons) | All sizes computed at runtime; adaptive S ∈ {2,4,8}; sparse day-grids; size-independent fallback |
| Raster incompleteness loses the packing war on hyper-congested instances | Per-block S=8 escalation; commit-time shapely rescue restricted to tardy-day-killing candidates |
| Engine/checker semantic drift → silent corruption | Bundled checker is sole arbiter: gates every promotion and migration; E1/E2 differential CI |
| numba cold-JIT / sandbox surprises | NUMBA_CACHE_DIR + dummy warmup inside `algorithm()`; .so and numpy fallbacks; ladder tested in Ubuntu 24.04 container |
| Weight regimes unseen in training (dominant w2/w3, m=1) | Runtime regime classifier from actual weights; exact Z2/Z3 handling favors us in extreme regimes; portfolio hedges |

## 10. Immediate next actions

1. Register + verify submission pipeline with a trivial feasible solver (M1 skeleton) — bank a
   leaderboard entry early; 12 h cooldown makes cadence planning matter.
2. Run E1/E2 this week (they gate everything).
3. Build M2 kernel; wire the batch harness into every commit (40 instances × 3 seeds).
4. Study `reference-ogc2024-winner/` (esp. time-budget ledger and ALNS constants) before M4.
