# GRID-BITMASK DYNAMICS — Complete Solver Architecture (OGC 2026)

## 0. One-paragraph thesis

Placements are integer-lattice by checker construction (banker's rounding, L1154), bays are ≤180×29, and the checker's only geometric predicate is `intersection.area > 0`. Therefore the entire geometry of this problem compiles down to bit algebra: rasterize every (block, orientation, layer) once with **exact integer arithmetic** (vertices ×10⁴ are exact int64), keep per-(bay, day, layer) packed-uint64 occupancy grids, and answer every Stage-2/3/4/5 question with AND/OR/popcount at ~1–3 µs per candidate and ~1 ms for *all 5,400 positions of a bay at once*. On top of this kernel: a squeaky-wheel ATC constructor that is provably bit-identical to the checker's Stage-5 replay, an ALNS over (assignment, priority) genotypes with an exact Gurobi assignment master (Z2+Z3 are pure assignment costs), a 4-process portfolio, and an unconditional feasible fallback. The novelty core is a formally proved "**roofline calculus**": the crane j≥k rule reduced to three bitwise invariants whose maintenance is O(words) per move.

---

## 1. Geometry engine

**Rasterization (exact, one-time).** Subgrid factor S=4 (cells 0.25×0.25; adaptive S=8 when n·bayarea small, S=2 if hidden instances exceed 512×64). For each (block, orient, layer), polygon vertices are scaled by 10⁴ → exact int64 (coords ≤180 → ≤1.8e6; cross products ≤ 4e12 < 2⁶³). Cell (2500-unit square, scaled) is marked iff area(cell ∩ P) > 0, computed by integer scanline (clip polygon to each row band, trapezoid x-coverage) — **zero floating-point anywhere in rasterization**. Masks stored bit-packed (uint64 rows); worst case 300 blocks × 8 orients × 4 layers ≈ 29 MB, typical block 10×9 → ~40×36 subcells → ~40 words. Per orientation, also precompute prefix-OR masks D_j = ∪_{k≤j} M_k (crane), 1-cell-dilated masks (contact scoring), and the integer offset from the reference vertex (first vertex of layer 0 — which may be negative; fact 11) to the mask origin. Integer placement (x,y) shifts a mask by exactly (S·x, S·y) cells — masks are rasterized once, translation is lossless.

**Exactness vs shapely — both directions, proved.**
- *Soundness (never accept what the checker rejects):* if two placed masks are disjoint, any positive-area real overlap would deposit positive area in some shared cell — contradiction. So raster-feasible ⇒ real intersection area = 0. Containment is exact bidirectionally (bay corners are integers, cells 1/S-aligned; flush wall contact accepted, matching non-strict ≤ at L262).
- *Immunity to the checker's float slivers (fact 14):* the dangerous case — fractional-flush contact with equal 1e-4 fractional parts, where shapely doubles see ~1e-14 area — has its contact line strictly inside a cell column (coordinate ×10⁴ not ≡ 0 mod 2500), so *both* masks mark that cell and the raster **rejects** it. Contacts the raster accepts lie on 1/4-integer-aligned lines, exactly representable in binary doubles → shapely computes exact 0. The raster is strictly safer than the checker's own arithmetic.
- *Incompleteness (the only approximation):* true clearances < √2/S ≈ 0.354 along sloped boundaries are rejected. Recovery: for the rare high-value rejected candidate (would kill a tardy day), one shapely confirm with checker-identical predicates (42 µs measured); accepted only on exact `area == 0.0` and quarantined on a "shapely-verified" list. Final gate: bundled `check_feasibility` (40–60 ms measured) on every incumbent promotion.

**State.** Per (bay, day, layer): `occ[b][d][k]` packed grid (≤11 KB each) representing occupancy during [d, d+1) **after** day-d exits and after previously-sequenced day-d entries — this exactly matches Stage-5 replay state (exits replayed first; verified facts 5–6). Also `lowmass[b][d][j] = ∪_{X present at d} ∪_{k<j} X_k` (roof-shadow grid) and `exitfield[b][d][k]` (int16 exit-day per cell, for time-aware contact scoring). Horizon ≈ maxD + ΣP/m padding; n=300 → ~60 MB/solution. Stamping = OR over [entry, exit); **unstamping = ANDNOT is exact** because same-layer co-present masks are disjoint by invariant.

**The roofline calculus (crane rule as three bitwise invariants).** Placement of mover M (layers M_0..M_{K−1}, prefix-ORs D_j) at bay b, position p, interval [t, e):

- **(I1) Stage-4:** ∀d∈[t,e), ∀k: M_k ∧ occ[d][k] = 0.
- **(I2) Entry crane (j≥k, mover-under-roof forbidden):** ∀j: occ[t][j] ∧ D_min(j,K−1) = 0. (Identity: ∀k, M_k ∩ ∪_{j≥k}occ_j = ∅ ⇔ ∀j, occ_j ∩ D_j = ∅.)
- **(I3) Overhang persistence (exit safety):** for each j with M_j ∧ lowmass[t][j] ≠ 0: (M_j ∧ lowmass[t][j]) ∧ ¬lowmass[e−1][j] = 0.

*Theorem (proved, drives correctness):* under decoder chronology (place in nondecreasing entry day; within a day sequentially), no new mass can ever appear under a placed roof (any later entrant's layer k under an existing layer j≥k violates I2), so coverage under M's overhang is non-increasing during [t,e); hence comparing day t against day e−1 is a sound **and complete** test that every overhung block outlives M (up to legal same-day exit ordering). Together with I1/I2 this implies the interval-nesting forest of fact 7 is maintained implicitly, M's exit-crane check passes, and *all* future exits remain protected by recursion. Emission ordering that realizes it: per day, all EXITs sorted by (descending entry day, descending placement index) — inner-before-outer LIFO — then all ENTRYs in placement order. This is **bit-identical to Stage-5 replay** (facts 5–6 A/C/E choreographies all reproduced), so the decoder never needs the full checker to be correct — the checker run is a belt-and-braces gate.

**Costs.** Single candidate (typical block, P=10, K=2): ~1–3 µs (numba packed AND, bbox-restricted words, early exit). Full-bay all-positions map for a stay: build union grid over [t,e) (~20 µs), then packed shifted-AND scan ≈ 0.3–1 ms, or fftconvolve fallback (1.6 ms measured, bit-exact after single exact-AND confirm of argmax). I3 is evaluated as a post-filter on the top-scored candidates only (2 grid compares each). Every number above is measured or derived from the measured 42 µs shapely baseline → **~100–1000× over the baseline's geometry**.

```
def placement_map(b, t, e, mover):            # all (x,y) at once
    U[k] = OR_{d in [t,e)} occ[b][d][k]       # stay-union per layer
    F = correlate_zero(U[k], mover.M[k]  for k)         # I1, all positions
      & correlate_zero(occ[b][t][j], mover.D[j] for j)  # I2
    for p in top_scored(F):                   # score: see §3
        if I3_ok(p, t, e) and exact_AND_confirm(p): yield p
```

## 2. Representation & decomposition

**Genotype:** assignment vector a: block→bay (Z2, Z3 exact, O(1) deltas — L1404-14) + per-bay priority vector π + per-block orientation shortlist. **Phenotype:** deterministic decoder output (x, y, orient, ENTRY, EXIT=ENTRY+P, per-day op order). Dwell is never used (space-only cost; fact 4) except it exists implicitly via re-timing in repair.

**Two-level decomposition (He/Hong/Kim 2024, hardened):** master = assignment (Z2+Z3 exact + congestion-estimated Z1); slaves = per-bay independent weighted-tardiness packing, embarrassingly parallel. Runtime regime classifier from weights at t=0: r = w3·prefGapMed/w1 (r ≳ 3 → preference-locked mode, p32/p34/p37-like; else tardiness mode) and ρ = w2·(ΣL/m)/w1 for Z2 attention (p25/p36/p40-like).

## 3. Construction (beats EDD + bottom-left)

1. **Assignment:** Gurobi MIP, n·m ≤ 1500 binaries: min w3·regret + w2·(linearized max pairwise |u_j load_j − u_j' load_j'|, ≤10 pairs) + λ·Σ bucket-overload, where overload = max(0, Σ_{i in bucket} area_i·P_i − η·bayarea·bucketlen), η=0.7, buckets = 7-day windows over [R, D]. Solves in ≪1 s; this is the LOAD relaxation from DSA — geometry-free congestion.
2. **Sequencing:** space-time ATCR: I_i(t) = exp(−max(0, D_i − P_i − t)/(κ·P̄)) · exp(−max(0,R_i−t)/(κ₂P̄)) / (area_i·P_i). κ from due-date tightness. EDD is the κ→0 limit; the area·P denominator stops one huge urgent block starving three small ones — the decisive difference on set2 (peak demand up to 1.61× bay area).
3. **Timing:** earliest feasible day ≥ R_i, scanning t with the placement map; day grids are post-exit states, so same-day EXIT→ENTRY reuse (fact 2 exploit) is automatic.
4. **Position scoring** on the map (all grid-native): contact popcount of dilated mask vs (occupancy ∪ walls), weighted by exit-date similarity from `exitfield` (Shang time-aware best contact: space frees contiguously); two-corner diagonal fill (Kwon & Lee) keeping a central corridor; small bonus for legal overhangs that pass I3 (mushroom-over-short-stay roofing — 35% of multilayer blocks are mushrooms, 40% have >1% overhang: real capacity, no one else will touch it).
5. **Squeaky-wheel wrapper:** construct → blame_i = w1·T_i + w3·regret_i + congestion share → promote blamed blocks in π (and flag for bay diversion in tardiness mode) → reconstruct. 15–40 rounds in the first seconds.

```
def decode(a, π):
    for i in sorted(blocks, key=ATCR_dynamic):       # day-major admission
        for t in R_i .. :
            for o in orient_shortlist(i):
                p = best(placement_map(bay=a[i], t, t+P_i, mask(i,o)))
                if p: stamp(i, a[i], p, o, t, t+P_i); break
    emit per day: EXITs sorted (desc entry, desc place-idx), then ENTRYs in place order
```

## 4. Improvement search

**ALNS** (Ropke–Pisinger; the OGC-2024 winner's exact skeleton) over (a, π):
- *Destroy (5–15%):* worst-blame (SWO), Shaw-related (α|Δdue|+β|Δentry|+γ spatial dist+δ same-bay), time-window [t₁,t₂] per bay, spatial cluster (grid region), bay-cluster reassign (moves Z3/Z2 mass).
- *Repair:* regret-2 insertion, most-constrained-first (fewest feasible map cells), randomized greedy; re-timing free since decoder re-derives ENTRY.
- *Acceptance:* SA, geometric cooling calibrated to the first 100 deltas; adaptive weights (rewards 20/10/2, ρ=0.5, update every 100 iters).
- **Gurobi, two bounded roles only:** (i) assignment master re-solve every macro-round with updated congestion duals from slaves (Benders-flavored; ≤1500 binaries, TimeLimit 2 s, Threads=1, warm start); (ii) optional per-bay resequencing polish on ≤60-block tardy clusters via time-indexed 1|r_j|ΣT_j relaxation (lower bound + order hint; TimeLimit 3 s). Gurobi never owns the clock.
- **Parallelism (4 cores):** fork-based processes with COW-shared masks; OMP/BLAS/Gurobi threads pinned to 1. Layout: 3 ALNS chains with distinct seeds/operator mixes/κ + 1 orchestrator running master MIP, incumbent merging (migrate best assignment every ~15 s), and checker gating. Post assignment-freeze in the last phase, chains switch to per-bay slave LNS (bays independent — zero coordination).

## 5. Time budget & anytime safety

t=0: parse, triage (n, m, regime r/ρ, congestion), warm numba on a dummy (NUMBA_CACHE_DIR set; prebuilt Ubuntu-24.04 .so as primary, numba as fallback, pure-numpy fftconvolve as last resort — triple redundancy). t<1 s: build the **verified fallback** (serialized far-future windows, fits-aware bay search — fact 9) and hold it serialized. Hard deadline = start + timelimit − max(5 s, 3%); every incumbent promotion re-serializes the full op-dict and runs the 60 ms checker, so the answer is always ready. Phase fractions (scale-invariant 60 s→1800 s): 5% construct+SWO, 70% ALNS+master, 20% assignment-frozen per-bay polish, 5% margin; if timelimit < 90 s, skip master re-solves after round 1. No wall-clock-dependent branching in solution content; fixed seeds per (fingerprint, worker).

## 6. Complexity / memory sanity (n=300, one Threadripper core)

Rasterization: exact int scanline, ≤4,800 polys, ~1–3 ms total (numba). Candidate test 1–3 µs; full-bay map 0.3–1.6 ms; full decode ≈ 300 × (≈3 day-attempts × ≈3 orients) × ~0.5 ms ≈ 1–2 s; ALNS repair of 20–40 blocks ≈ 60–150 ms → **7–15 iterations/s/core → 15–60 k destroy-repairs within 10–30 min on 3 chains**; SWO full reconstructions ~30/min during phase 1. Memory: masks ≤30 MB + day grids ≤60 MB per solution ×4 processes (COW-shared masks) < 1 GB total. Checker calls ~20/s available, used ~1/promotion. All key constants (42 µs shapely, 1.6 ms fftconvolve, 60 ms checker) are measured on the actual training data.

## 7. Novelty for the technical report

1. **Roofline calculus**: first formalization of a vertical crane-lift constraint in spatial scheduling (absent from all 15+ surveyed papers; the only removal-obstruction work — Frontiers 2026 — is horizontal). Prefix-OR mover masks × suffix-layer grids + the *monotone-shadow persistence theorem* (proof that a two-day grid comparison exactly certifies exit safety) + implicit maintenance of the interval-nesting forest, with a proof that decoder chronology + LIFO exit emission is bit-identical to the evaluator's Stage-5 replay. Ties to BRP blocking-pair theory.
2. **Exact-integer rasterization that is strictly safer than the evaluator's own floats**: the 10⁴-scaling argument showing every raster-accepted contact is exact-zero in IEEE754 shapely while the known 1-ulp sliver class is auto-rejected — a certifiable zero-clearance packing engine.
3. **Deliberate mushroom roofing** (35% of multilayer blocks) as scored capacity, priced by induced nesting — quantified on training data.
4. Exact-cost assignment master (Z2/Z3 closed-form) with LOAD-relaxation congestion feedback — a clean Benders-style matheuristic the judges' own literature lineage (He/Hong/Kim; OGC-2024 winner) endorses, extended.

## 8. Risk register (top 5)

1. **Hidden instances outside training envelope (n>300, wider bays, longer horizons).** Grid memory scales linearly; mitigation: adaptive S∈{2,4,8} chosen from bay area·horizon budget; sparse far-day grids; triage caps operator sizes; fallback unconditional.
2. **Raster incompleteness costs capacity in hyper-congested instances** (sub-0.35 diagonal fits). Mitigation: S=8 auto-upgrade when subcell budget allows; commit-time shapely rescue for candidates whose map-rejection blocks an on-time entry; measured: median convexity 0.986, so diagonal-snuggle mass is small.
3. **Emission-order / replay mismatch bug** (the classic silent −1). Mitigation: the ordering is a theorem, not a convention, and is regression-tested by replaying `utils.py` on thousands of randomized decoder outputs offline; every promotion passes the bundled checker; last-verified incumbent always retained.
4. **Cold-start/JIT or sandbox surprises eat short time limits.** Prebuilt .so + numba-cache warmup at import + pure-numpy path; deadline ledger with 5 s+3% margin (OGC-2024 winner's SPARE_TIME paranoia); construction-only degraded mode under 90 s.
5. **Weight regimes unseen in training (e.g., dominant w2/w3).** Regime classifier is computed from weights at runtime, not memorized; the assignment master optimizes Z2/Z3 *exactly* under any weights, so extreme regimes actually favor this design; portfolio chains run distinct regime priors as insurance.

Failure floor is a feasible serialized schedule (never −1); expected operating point is 15–60 k exact-geometry LNS iterations with an exact assignment master — two orders of magnitude more search over strictly finer geometry (bbox fill median 0.67 → ~33% capacity recovered vs AABB baselines) than an EDD/shapely-style competitor can perform in the same wall clock.