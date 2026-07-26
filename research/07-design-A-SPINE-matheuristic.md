# SPINE: Two-Level Matheuristic for OGC 2026 Spatial Block Scheduling

Architecture name: **SPINE** (Spatial Packing with Integer-lattice Numerics and Exact-assignment master). Philosophy committed: assignment master exactly pricing Z2+Z3 with a calibrated congestion→tardiness proxy, per-bay placement/scheduling slaves, Benders-flavored feedback loop.

---

## 1. Geometry engine — sound integer-lattice bitmask kernel

**Data structures (built once at parse, ≤3 s with vectorized rasterization):**

- **Masks.** For each (block i, orientation o, layer k): bit-packed occupancy mask at subgrid S=4 (cells 0.25×0.25), rasterized from the exact fractional-vertex polygon with the *positive-area* rule: cell marked iff area(cell ∩ polygon) > 0. Implementation: vectorized `shapely.contains_xy` on cell corners classifies interior/exterior; exact `area(intersection)` only on boundary cells (~O(perimeter) shapely calls). ≤4,800 masks/instance, <6 MB. Precompute per-mask: bbox, area, popcount, 1-cell-dilated mask (for contact scoring), and reference-point offset (reference = first vertex of layer 0, which may be negative — legal (x,y) ranges are shape-dependent, handled per mask).
- **Bay state.** Per bay: event timeline (sorted distinct ENTRY/EXIT days, ≤2n_j events) of packed occupancy grids `occ[k]` per layer k∈{0..3} (bay ≤180×29 → ≤720×120 cells = 10.8 KB packed per layer) plus **suffix-OR grids** `occ_ge[k] = OR_{j≥k} occ[j]`, and an int16 owner grid per layer for "who blocks me" queries. Updates are incremental stamp/erase; a full bay timeline snapshot is ~1–3 MB.
- **Crane rule j≥k encoding.** ENTRY/EXIT test of a block at day t = for each of its layers k: `mask[k] AND occ_ge[k](state at t) == 0`, where the entry-day state is the **post-exit** state of day t (same-day EXIT→ENTRY reuse, matching checker Stage-5 replay), and the exit-day co-present set excludes same-day entrants/exiters (checker's strict inequalities). Persistence (Stage 4) = same-index-only: `mask[k] AND occ_eq[k] == 0` for every event interval within [ENTRY, EXIT).
- **Placement enumeration.** Full-bay feasible-position map for one (block, orientation, event-interval): 2D correlation of occupancy with mask, subsampled at stride S → all ≤5,400 integer positions at once. Measured 1.6 ms with `fftconvolve`; the production kernel is numba packed-bit AND with 4 precomputed word-phase shifts (S=4 divides 64) → 50–150 µs. Single-position test: bitwise AND over ≤348 uint64 words, sub-µs. Feasibility over a dwell [t, t+P): AND of interval maps covering the window + crane maps at the two boundary days. Contact scoring (popcount of dilated-mask ∧ occupancy, weighted by neighbor exit-date similarity) comes free on the same grids.

**Exactness guarantee vs the shapely checker (protects against −1):**

- *Soundness theorem:* positions are integers, cells are 1/S-aligned with S integer, so a translated mask is an exact cell shift — no re-rasterization. If two positive-area masks are disjoint, any true overlap region would put positive area of both polygons into some common cell, contradiction ⇒ **raster-feasible ⇒ checker-feasible**, for collision, crane (same argument per suffix layer), and containment (bay corners are integers; marked-cells-inside ⇔ checker containment, exact both directions, flush wall contact allowed).
- *Incompleteness is bounded:* only true clearances < √2/S ≈ 0.354 along sloped boundaries are falsely rejected. Recovery: for high-value rejected candidates (would eliminate a tardy day), a **commit-time shapely verifier using the checker's own arithmetic** (translate-then-int, `buffer(0)`, `intersection.area > 0` — identical doubles, deterministic cross-machine) accepts exact area-0 contacts. Fractional-fractional flush (≈2% 1-ulp-overlap risk) is never emitted without this verification.
- *Final gate:* bundled `check_feasibility` (40–60 ms at n=300) runs before every incumbent promotion and once before emission. The engine can never cause an infeasible submission.

---

## 2. Solution representation and decomposition

**Exploited structure:** Z2 and Z3 are pure functions of the assignment vector `a: block → bay` (Z2 = floor(max_j u_j·load_j − min_j u_j·load_j); Z3 linear in a). Given a, bays are **independent** minimum-tardiness spatial scheduling problems. Hence:

```
Solution = ( a[0..n-1],                        # assignment vector (master variable)
             per-bay: priority list π_j,       # decoder input (search variable)
             per-bay decoded schedule:         # decoder output (derived)
               {(ENTRY_i, EXIT_i, x_i, y_i, o_i)},
             nesting digraph G_j )             # crane-induced precedence edges
```

- **Nesting digraph G_j:** edge B→A whenever A's layer j overlaps B's layer k<j in plan view while co-present (A is the overhanger ⇒ interval nesting [ENTRY_A, EXIT_A] ⊆ [ENTRY_B, EXIT_B], verified checker semantics). Construction invariant (**EXIT-monotone stacking**, imported from container-relocation): permit an overhang of A over B only if planned EXIT_A ≤ EXIT_B. This makes G_j trivially consistent, is a one-comparison filter on the bitmap candidate maps (mask out cells owned by blocks with earlier exits at lower layers), and G_j drives same-day op ordering at emission (per time key: all EXITs first, inner-before-outer for exits; outer-before-inner for entries).
- **Incrementality:** every LNS move touches one bay; Z2/Z3 deltas are O(1) exact; tardiness delta comes from the decoder's event calendar; nothing is ever re-evaluated from scratch.
- **Objective ledger:** cost(solution) = w1·Σtardiness (exact, from slaves) + w2·Z2 + w3·Z3 (exact, from a). The master optimizes the same ledger with tardiness replaced by a calibrated estimate; slaves make it exact.

---

## 3. Construction (must beat EDD + bottom-left — and does, on both axes)

**Ordering rule — ATC-space (Apparent Tardiness Cost normalized by space-time volume):**
priority_i(t) = exp(−(D_i − P_i − t)⁺ / (k·p̄)) / (area_i^α · P_i^β), with k tuned to slack spread (k≈0.5 for set2-like burst instances, 2.0 for loose), α=β≈0.7, plus a most-constrained-first override for blocks whose feasible-map popcount is in the lowest decile. EDD is the k→0, α=β=0 special case; ATC-space stops one urgent-huge block from starving several urgent-small ones — exactly the failure mode of the baseline on congested set2 (peak demand up to 1.61× bay area).

**Placement rule — true-shape contact scoring on the raster maps** (vs baseline AABB candidates that waste ~33% area at median bbox fill 0.67): candidates = all feasible positions from the correlation map, scored by
`score = w1·tardiness(entry) ⊳ contact_popcount weighted by exit-date similarity of touched neighbors ⊳ EXIT-monotone overhang bonus (roof long-stayers over short-stayers is *free* area) ⊳ corner/bottom-left tiebreak` (⊳ = lexicographic-ish weighted). Orientation pruning: rank a block's ≤8 orientations by static fit statistics, expand top-3 (all 8 only when top-3 fail).

**Timing rule:** scan entry days from max(R_i, earliest day with nonempty feasible map), using **post-exit day states** (same-day space reuse — JIT chains: predecessor exits at its due date, successor enters the same day into the same cells). EXIT_i = ENTRY_i + P_i always at construction (dwell is free but occupies space; extension is only ever introduced by the emission-repair path, never chosen). Stop at first on-time day; if none ≤ D_i − P_i, take the min-tardiness (day, position, orientation) triple.

```
DECODE_BAY(j, blocks B_j, priorities π_j):            # the slave decoder
  timeline ← empty event calendar with occ/occ_ge/owner grids
  for i in B_j sorted by π_j:
    best ← None
    for o in top_orientations(i, bay j):
      for t in entry_days from max(R_i, t_min) ascending:      # post-exit state at t
        F ← feasible_map(i,o,t..t+P_i)      # AND of: interval same-layer maps,
                                            #   crane suffix maps at t and t+P_i,
                                            #   EXIT-monotone ownership filter
        if F nonempty:
          cand ← argmax over F of contact/BL score
          best ← min(best, (tardy(t+P_i), score(cand)));  break on-time
    if best is None: mark i UNPLACED (→ master feedback / fallback window)
    else stamp i; add nesting edges; update calendar
  return schedule_j, per-block tardiness, backlog profile, blame_i
```

Cost: ~75 blocks × 3 orientations × ~5 tried days × 0.1–0.3 ms ≈ **0.1–0.3 s per bay decode** (numba kernel), so full-instance re-decode ≈ 0.5–1 s and single-block re-insertion ≈ 1–3 ms.

---

## 4. Improvement search — master ⇄ slave matheuristic

**Master (Gurobi MIP, the heart of the design).** Variables x_ij (n·m ≤ 1,500 binaries), continuous M, m, Q_jt.

```
min  w2·(M − m)                                        # Z2 exact (floor dropped; monotone)
   + w3·Σ_ij (S_i^max − S_ij)·x_ij                     # Z3 exact
   + Σ_ij ĉ_ij·x_ij                                    # per-block tardiness pseudo-costs
   + Σ_jt κ_j·Q_jt                                     # fluid backlog penalty
s.t. Σ_j x_ij = 1                        ∀i
     λ_j = u_j·Σ_i L_i x_ij;  m ≤ λ_j ≤ M ∀j
     Q_jt ≥ Σ_{i: due-bucket ≤ t} area_i·P_i·x_ij − η_j·A_j·(t·Δ − t0_j);  Q_jt ≥ 0
                                          ∀j, t ∈ buckets (Δ = max(3, medP/2), ~40 buckets)
     Σ_i (1 − x_i,a*(i)) ≤ Δ_TR          # local-branching trust region around incumbent a*
     no-good cuts on previously decoded assignment vectors
```

- **Feedback (the "learning"):** after each slave round, (i) η_j ← realized peak packing efficiency of bay j (init 0.7); (ii) κ_j ← regression of realized Σtardiness_j on Σ_t Q_jt (fluid-backlog calibration, exponential smoothing ρ=0.4); (iii) pseudo-costs ĉ_i,a(i) ← (1−ρ)ĉ + ρ·w1·T_i^realized for tardy blocks (blame prices — a Benders-flavored cut surrogate); ĉ_ij for j≠a(i) stays at the optimistic fluid marginal. Trust region Δ_TR starts at 0.08n, grows ×1.5 on stagnation, resets on improvement.
- **Size/limits:** solves in well under 1 s at this size; `TimeLimit=3 s, Threads=1, MIPFocus=1`, warm start = incumbent. Fallback chain if gurobipy misbehaves: CP-SAT (same model, integerized) → pure-Python assignment local search (swap/shift moves; Z2/Z3/pseudo-cost deltas are O(1) exact). The master is never allowed to own the clock.
- **Regime gating at t=0** (computed from weights, per instance analytics): ρ_pref = w3·gapMed/w1, congestion = peak nominal demand / bay area. LOOSE (congestion<0.5, set1-like): assignment ≈ preference-argmax, master runs once, all effort in slaves reaching zero tardiness, then a Z2 polish pass swapping preference-indifferent blocks. PREF-HARD (ρ_pref>3, e.g. p32/p34/p37): freeze near-preferred assignment, divert only with proven tardiness savings > w3·gap. TIGHT (set2-like): full loop below.

**Slave improvement — per-bay ALNS (Ropke–Pisinger, tuned to this problem):**

- Destroy (5–15% of bay, adaptive): worst-blame (SWO: blame_i = w1·T_i + congestion contribution), Shaw-related on (|Δdue|, |Δentry|, plan-view distance), time-window removal (all entries in [t1,t2]), spatial-cluster removal (connected component on the owner grid), nesting-chain removal (a digraph chain — unlocks stuck LIFO stacks), random.
- Repair: regret-2 insertion and randomized-greedy via DECODE_BAY's single-block insertion; most-constrained-first ordering.
- Acceptance: SA, T from 2%→0.02% of incumbent cost, geometric; operator weights adaptive (rewards 20/10/2, update every 100 iters).
- One **cross-bay ejection operator** inside ALNS: move a high-blame block to its 2nd/3rd bay if w1·T_i saved > w3·gap_i + w2·ΔZ2 (exact exchange-rate test) — catches what the master's granularity misses between re-solves.

**Macro loop and 4-core parallelization:**

```
MACRO():
  triage; build+verify serialized fallback         # incumbent from t≈1s, NEVER -1
  a ← MASTER(no pseudo-costs); decode all bays; verify; incumbent
  while time remains:
    burst = adaptive(6–30 s)
    parallel over 4 forked workers (read-only masks shared via fork COW):
       assign cores to bays proportional to blame mass; if m<4, spare cores run
       a duplicate seed of the worst bay (best-of-two) and/or the LOOSE Z2/Z3 polish
    collect: tardiness, blame, backlog profiles, unplaced blocks
    update η, κ, ĉ;  a ← MASTER(warm start, trust region, no-goods)
    re-decode only bays whose block set changed (warm-started from surviving placements)
    if full-checker passes and cost < best: promote incumbent, serialize to disk dict
```

---

## 5. Time-budget management (few minutes … 30 min, unknown)

Hard deadline = start + timelimit − margin, margin = max(5 s, 3.5% of limit) (OGC 2024 winner's server-clock paranoia, copied). Phase schedule as fractions, not absolutes: 2% parse/triage/fallback (feasible incumbent exists by t≈1 s — unbounded horizon + fits-aware bay choice, verified recipe), 8% construction + first master, 78% macro loop (burst length adapts so ≥6 master rounds happen even at 3 min; at 30 min, extra time goes to slave ALNS, not more master rounds), 8% endgame polish (tardiness-focused resequencing of the worst bay; Z2 tie-shaving using floor), 4% final verification + emission. Incumbent is kept **already serialized in output-dict form** and rewritten on every promotion; watchdog (signal + explicit clock checks in all loops) returns it on expiry or any exception. Numba kernels are warmed on a dummy micro-instance at import (NUMBA_CACHE_DIR set to a writable dir); a prebuilt Ubuntu 24.04 .so of the bit kernel + pure-numpy fftconvolve path give triple redundancy — engine failure degrades speed, never correctness.

## 6. Complexity / feasibility sanity (n=300, one Threadripper core)

- Masks: ≤4,800 × ≤2.7 KB ≈ 6 MB. Bay timelines: ≤5 bays × 600 events × 4 layers × 11 KB ≈ 130 MB worst case; ALNS working copies ×3 ≈ 400 MB. Gurobi model trivial. **Total < 1 GB ≪ 16 GB**, headroom for 4 forked workers (COW-shared masks).
- Kernel: single placement test <1 µs; full-bay map 50–150 µs (numba) / 1.6 ms (fallback). Single-block re-insertion 1–3 ms → destroy-repair of 10 blocks ≈ 15–40 ms → **25–60 ALNS iterations/s/core**, ~4 bays in parallel → ~10⁵–1.5·10⁵ destroy-repair moves in 15 min, each move re-placing ~10 blocks (≈10⁶ block placements examined, each over the *complete* position lattice). Full checker gate 0.06 s, used ~1×/burst. Master ≤3 s × ~15 rounds ≤ 45 s. All fits with ≥70% of wall clock in productive slave search.

## 7. Novelty angle (technical report / finals)

1. **Exit-precedence digraph for the vertical crane rule** — formalize j≥k overhang ⇒ interval nesting (LIFO), prove the EXIT-monotone invariant preserves feasibility and enables overhang-as-free-area packing (35% of multi-layer blocks are "mushrooms"); BRP blocking-pair counts as a lower bound and blame signal. Absent from all shipbuilding spatial-scheduling literature (closest work handles only horizontal transporter paths).
2. **Provably sound integer-lattice geometry** — the positive-area rasterization soundness theorem + checker-arithmetic commit verification: exact polygon packing guarantees at bitmap speed; published nesting practice approximates without guarantees.
3. **Exact-assignment matheuristic** — Z2/Z3 priced exactly in a MIP master with fluid-backlog calibration and blame pseudo-costs (a clean strengthening of He–Hong–Kim 2024's area-only Phase I), with per-bay independence exploited for parallelism.
4. Same-day EXIT→ENTRY choreography (JIT chains, same-day nest construction/unwinding via emitted op order) as a deliberately exploited rule, with verified checker semantics.

## 8. Risk register (top 5, with mitigations)

1. **Master proxy mis-prices tardiness → oscillating/bad assignments.** Mitigation: trust region keeps moves small and warm-startable; promotion only on *true* decoded objective; pseudo-cost smoothing; no-goods prevent cycling; if 3 consecutive master rounds fail to improve, freeze a and go pure per-bay ALNS.
2. **Hidden instances outside training regimes** (w3-dominant, extreme congestion, n>300, m=1, weird bay shapes). Mitigation: runtime regime classifier from (w1,w2,w3, gapMed, congestion) with three configs + a robust general fallback (OGC-2024-winner pattern); all parameters scale with n, m, bay area, median P — nothing keyed to absolute training sizes; m=1 path (Z2=0, master trivial, 4-seed portfolio).
3. **Environment failure of compiled paths** (numba JIT in sandbox, .so ABI, gurobipy license). Mitigation: triple-redundant kernel (prebuilt .so → numba with warm cache → numpy fftconvolve), Gurobi → CP-SAT → Python local search; every import wrapped; degradation is throughput-only.
4. **Sliver infeasibility or checker mismatch → −1.** Structurally excluded: raster soundness theorem, checker-identical shapely commit gate for near-fits, full bundled checker before every incumbent promotion and emission, canonical integer time keys, per-day exits-before-entries with digraph-consistent ordering, serialized fallback always on disk, global try/except + deadline watchdog.
5. **Raster incompleteness costs density on hyper-congested instances** (sub-0.35 diagonal snuggles matter when peak demand >1.3). Mitigation: congestion-triggered escalation to S=8 (memory ×4, still trivial; kernel ×4) + shapely near-fit recovery restricted to the top decile of value; measured only ~2% of contact configurations are affected, and integer-aligned contacts (the dominant case) are exact at any S.

Secondary risks tracked: timeout clock skew (3.5% margin, shaved further on n≥300), fork/memory blowup (workers cap timelines, masks shared read-only), degenerate polygons (buffer(0) at parse, mask popcount sanity vs shapely area).