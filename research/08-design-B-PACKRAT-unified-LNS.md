# UNIFIED-LNS SOLVER: "PACKRAT" — single space-time solution object, pure ruin-and-recreate, zero MIP

## 1. Geometry engine — "crane-aware raster calculus"

**Core representation.** Sub-grid factor S=4 (cells 0.25×0.25; escalate to S=8 for blocks flagged hard-to-place, degrade to S=2/1 under memory pressure — soundness is preserved at any S). All placements are integer (checker rounds via `int(round())`), so translation = shift by S·t cells exactly; masks are rasterized **once** per (block, orientation, layer) with the *positive-area* rule: cell ∈ mask ⇔ area(cell ∩ polygon) > 0 (exact scanline/trapezoid clip in C, milliseconds total; vertices ≤12, ≤4,800 polys/instance). Bit-packed uint64 rows; 16 pre-shifted phase copies per mask (x mod 16, since 64/S=16) so any x-test is word-aligned AND. Memory: ≤200 MB worst case, lazily materialized per orientation actually explored.

**Soundness theorem (protects against −1).** If shifted masks are disjoint, shapely intersection area is exactly 0 (any positive-area overlap must deposit positive area in a shared cell). Containment is exact both directions (bay corners integral, cells 1/S-aligned). The only approximation is *incompleteness*: true clearance < √2/S ≈ 0.354 along sloped fractional edges may be rejected. Commit-time recovery: for high-value rejected positions (kills ≥1 tardy day), re-test with shapely using the checker's own predicates (`buffer(0)`, `intersection.area > 0`) — same library, same doubles as the server. Integer-aligned flush contact is accepted by construction (matches checker's `area > 0` + strict-`<` AABB prefilter).

**Temporal structure.** Per (bay, layer, day) packed occupancy grid, half-open stamping [ENTRY, EXIT). Grid = ≤720×116 bits ≈ 11 KB; 200 days × 4 layers × 5 bays ≈ 45 MB. Same-layer occupancy among co-present blocks is provably overlap-free, so **removal = ANDNOT of the mask — exact O(words) unstamp**, the property that makes unified LNS cheap.

**Three exact query primitives** (all pure bit-ops):
- *Same-layer collision over interval [t,e)*: forbidden ⇔ mask_k ∩ (OR of day-grids k over [t,e)) ≠ ∅. The interval union is **exact**, not conservative: same-layer overlap is illegal with *any* time-overlapping block, so avoiding the union is necessary and sufficient. Union cached per (bay,t,e,layer) and reused across all positions/orientations/blocks in one repair.
- *Own crane at ENTRY/EXIT*: mask_k ∩ suffix-union(day-grid[t], layers ≥ k) for entry; day-grid[e−1] for exit. Suffix unions = OR of ≤4 layer grids on the fly. This encodes j ≥ k directly.
- *Reverse crane* (the check everyone else will miss): placing C must not break *other* blocks' entry/exit lifts occurring strictly inside (ENTRY_C, EXIT_C). Maintain per (bay, day) event masks EV[t][k] = union of layer-k masks of blocks with an event at t. Check: ∀k: EV[t][k] ∩ C_ge[k] = ∅ for each event day t inside C's open interval (~2–5 word-ANDs per event day). This *automatically prices overhangs*: an overhang over X is accepted only if X's exit doesn't fall inside our interval — the BRP exit-monotone stacking rule emerges from the engine instead of being a bolted-on heuristic.

**Stage-5 choreography via the Monotone Listing Invariant (MLI).** Same-day op ordering rule: a newly inserted block's ENTRY is *appended* to its day's entry list; its EXIT is *prepended* to its day's exit list (insertion-time LIFO). Claim (verified against the checker's replay semantics, tests A–G in the rules analysis): if every insertion passes the conservative day-state checks above (which include *all* same-day co-entrants/co-exiters), then the replayed per-day EXIT*-then-ENTRY* sequence checks each op against a **subset** of what the engine checked ⇒ Stage 5 passes. Removal only relaxes. Result: same-day exit→entry space reuse and same-day nest construction/unwinding are legal *by invariant* — no explicit DAG bookkeeping in the hot loop (a lightweight overhang digraph is kept only for diagnostics/report).

**Costs.** Candidate-point test: mask-window AND ≈ 40–160 word-ops ≈ 0.1–0.5 µs (C via pybind11). Full-bay position map (rare, for desperate blocks): packed correlation ≈ 1–3 ms. vs shapely 42 µs/single position — ~100–400× per test, exhaustive when needed.

## 2. Solution representation & exploited decomposition

One flat solution object: arrays `bay[i], x[i], y[i], o[i], entry[i]` (`exit[i] = entry[i]+P[i]` invariant; dwell extension exists only as an explicit "roofing" move), plus per-bay day-grids, per-day event lists under MLI, and incremental objective state: Z1 = Σ tardiness (O(1) delta), Z2 = per-bay total loads + max pairwise |u·Δ| recomputed over m ≤ 5 bays in 25 ops, Z3 per-block regret (O(1)). **Exploit: Z2/Z3 depend only on `bay[i]`** — every cross-bay move has an *exact* O(1) assignment-cost delta, so the LNS never needs to estimate them; only Z1 requires geometry. Bays are independent given assignment ⇒ (a) intra-bay destroy-repair touches one bay's grids only (cache-friendly, lock-free), (b) parallelization: **4 independent full-solution ALNS replicas** (distinct seeds, operator mixes, acceptance schedules) with incumbent migration every ~15 s through the parent process; the migrated solution is re-gated by the bundled `check_feasibility` (40–60 ms) before adoption. Replicas beat intra-solution parallelism here: no synchronization in the hot loop, natural portfolio robustness against hidden-instance variety.

Runtime regime triage at t=0 (drives operator weights): tardiness-dominant (w3·gapMed/w1 < 1, set1-like) vs preference-locked (p32/p34/p37-like, ratio > 3: treat Z3 as near-hard, restrict cross-bay ops to indifferent blocks) vs Z2-sensitive (w2·(ΣL/m)/w1 > 5: enable balance operator); congestion = peak Σ(area·P)/bayArea decides packing aggressiveness (candidate density, S escalation).

## 3. Construction — beats EDD+bottom-left on three independent axes

```
construct():
  for each block: pre-rank bays by  w3*regret + w2*ΔZ2 + λ*congestion(bay, R_i..D_i)   # LOAD ratio per 5-day bucket
  t = 0..horizon (day-major decode):
    ready = {unplaced i : R_i <= t}, sorted by ATC-space index
       I_i(t) = exp(-max(0, D_i - P_i - t)/ (k * meanP)) / (area_i * P_i)      # scarce resource is space-time volume
    for i in ready (index desc):
      for bay in first 2 ranked bays (3rd if tardy otherwise):
        C = candidate points: skyline/corner + contact points of grids at day t (post-exit state — free same-day reuse)
        feas = {c in C passing primitives 1-3}                                  # true polygons, not AABBs
        score(c) = contact_popcount weighted by |exit_mine - exit_neighbor|^-1  # temporal best-contact
                   + wall bonus + diagonal-fill corner bias - tiny*y
        if feas: place argmax, entry=t, exit=t+P_i; stamp; break
    (blocks failing everywhere get retried each day; ATC index rises as slack burns)
```
Axes of superiority over baseline: (1) **true-polygon raster vs AABB candidates** — median bbox fill 0.67 ⇒ ~33% effective capacity recovered, decisive on set2 where peak demand exceeds 1.0; (2) **ATC-space ordering vs EDD** — exponential slack discount normalized by area·P stops one huge urgent block starving several small ones; (3) **temporal best-contact + diagonal fill vs bottom-left** — freed space stays contiguous in space *and* time. Overhang positions are tried like any other; the reverse-crane primitive rejects exactly the exit-incompatible ones. Expected: near-zero Z1 on set1 (then construction bay-ranking already optimizes Z3/Z2), 20–40% Z1 cut on set2 from capacity alone.

## 4. Improvement — ALNS, engineered around the insertion move

```
ALNS_replica(seed, budget):
  T = calibrate SA temp so a 1-tardy-day-equiv uphill move accepts w.p. 0.5; cool by fraction-of-budget
  repeat until deadline:
    op_d = roulette(destroy_weights); op_r = roulette(repair_weights)
    q ~ U(0.05n, 0.15n)
    removed = op_d(sol, q);  unstamp all (exact ANDNOT), O(1) Z-deltas
    order removed by op_r ∈ { most-constrained-first (fewest cached feasible slots),
                              regret-2 over (bay, entry-day) pairs, randomized-greedy(softmax) }
    for b in removed: insert_best(b)          # pseudocode below
    if any block uninsertable: entry = first day with feasible slot (may be late) — never fails (horizon unbounded)
    Δ = w1ΔZ1 + w2ΔZ2 + w3ΔZ3;  accept if Δ<0 or exp(-Δ/T)>rand;  else rollback (re-stamp saved states)
    update op weights (rewards 20/10/2, segment 100 iters, decay 0.5)
    every accepted global improvement: left-shift compaction sweep (entry-order, try earlier days; monotone Z1 gain)
    every K improvements: full utils.check_feasibility gate → serialize incumbent dict (anytime checkpoint)

insert_best(b):
  best = (+inf, ·)
  for bay in top-3 assignment-ranked bays:
    for t in {R_b, due-P_b, first-gap days from bay's exit-event calendar}  (≤6 entry days):
      U[k] = interval-union grids (cached);  C = corner/contact/skyline points ∪ same-day-exit footprints
      for c in C: if AND-tests(U, entry/exit suffix, reverse-crane EV) pass:
          cost = w1*max(0,t+P_b-D_b) + w2ΔZ2(bay) + w3*regret(b,bay) + ε*packing_score
          best = min(best, cost)
  stamp best; append ENTRY / prepend EXIT (MLI)
```
**Destroy portfolio** (adaptive weights): (1) *blame removal* (SWO): top blocks by w1·T_i + w3·regret_i plus their space-time neighbors; (2) *Shaw-related*: α|Δentry| + β centroid-dist + γ·same-bay + δ|ΔD|; (3) *time-window ruin* (one bay, [t1,t2], all intersecting blocks); (4) *spatial-cell ruin* (rectangle × window); (5) *bay-flush* (subset of the worst tardiness-density bay → cross-bay reinsertion; exact Z2/Z3 deltas make this the assignment search — no master problem needed); (6) *preference repatriation*: exiled blocks + the blockers occupying their preferred bay's window (directly attacks Z3, the ranking currency on set1); (7) Z2-balance swap (enabled only in Z2-sensitive regime). Repairs as above. Acceptance: SA in 3 replicas, record-to-record (deviation = 2% of incumbent) in the 4th — portfolio hedges acceptance-schedule risk. Restarts: replica whose incumbent lags global best by >10% for 60 s reseeds from global best + big ruin (30%). **No Gurobi/CP anywhere** — every cycle the solvers would spend, this design spends on ~10³ more destroy-repair iterations; the assignment dimension is fully covered by operators (5)–(7) with exact deltas.

## 5. Time budget & anytime safety

`deadline = start + timelimit − max(5 s, 3%)`. t≈0: parse, triage, **serialized far-future fallback** (fits-aware bay choice — verified recipe) written to the output dict immediately; then construction (≤2% budget); fork 4 replicas (fork-context, read-only masks shared, `OMP/OPENBLAS/NUMBA threads=1`); parent holds the last checker-verified incumbent dict at all times and answers the deadline signal by returning it — a crash in any replica costs iterations, never feasibility. Cooling and operator schedules keyed to elapsed-fraction, so "few minutes" and "30 minutes" both work untouched. Last 2%: freeze, final full-checker pass on best (already pre-verified), emit canonical integer-string time keys only. Score −1 is structurally impossible: every emitted solution has passed the bundled checker.

## 6. Complexity / feasibility sanity (n=300, Threadripper core)

Candidate test 0.1–0.5 µs; interval-union build 10–20 µs (amortized); one block insertion (3 bays × ≤6 days × ~100 candidates + crane/EV checks) ≈ 0.3–1.5 ms; repair of q≈30 blocks ≈ 10–45 ms; **⇒ 20–60 ALNS iterations/s/core, ×4 cores, ×(180 s…1800 s) ⇒ ~1.5×10⁴–4×10⁵ destroy-repair cycles ≈ 10⁶–10⁷ block-level placements** — versus the shapely baseline's ~10³ total placements. Memory: day-grids 45 MB + phased masks ≤200 MB + EV masks ≤20 MB + rollback buffers ≈ <1 GB per replica, <4 GB total. Deliverable: pybind11 C++ .so prebuilt for Ubuntu 24.04 + build-at-import fallback + numba fallback (pre-warmed, `NUMBA_CACHE_DIR` set) + pure-python emergency mode (construction only) — quadruple redundancy, per OGC-2024 winner practice.

## 7. Novelty for the technical report

(a) **Crane-aware raster calculus**: proof that interval-union correlation is *exact* (not conservative) for the same-layer constraint, and that entry/exit suffix-unions + reverse-crane event masks capture the full j ≥ k lift rule in O(words) bit-ops with provable soundness against the official shapely checker — no published spatial-scheduling work handles layered lift constraints at all (closest: horizontal transporter obstruction, Frontiers 2026). (b) **Monotone Listing Invariant**: a one-line ordering rule (append entries, prepend exits by insertion time) with a subset-argument proof that conservative day-state checks imply Stage-5 replay feasibility — turning same-day nest choreography and zero-turnaround space reuse from a scheduling problem into a free invariant. (c) **Emergent exit-monotone overhang pricing** (BRP/container-relocation import): the LIFO precedence induced by overhangs is enforced implicitly by the reverse-crane primitive, letting LNS *search over* deliberate overhang placements (35% of multi-layer blocks are mushrooms) rather than forbidding them. (d) Blame-fused ALNS where the destroy distribution is the SWO analysis step. Each is provable, ablatable (report ablation table: AABB→raster, EDD→ATC-space, no-overhang→priced-overhang), and none appears in the 15-paper related-work sweep.

## 8. Risk register

| # | Failure mode | Mitigation |
|---|---|---|
| 1 | Hidden instances outside training envelope (n≫300, bays≫180 wide, horizon≫200 days) blow grid memory/iteration cost | All sizes computed at runtime: adaptive S (4→2→1, soundness invariant), sparse day-grid allocation (only days with occupancy), candidate-count governor keyed to measured iter/s; fallback path is size-independent |
| 2 | Super-congested hidden instances where sub-0.35 diagonal clearances matter (raster incompleteness loses the packing war) | Per-block S=8 escalation for repeatedly-failing blocks; commit-time shapely recovery using checker-identical arithmetic; congestion triage enables it only when needed |
| 3 | Engine/checker semantic drift (Stage-5 subtlety, banker's rounding, key formatting) silently corrupts search | Bundled `utils.check_feasibility` is the sole arbiter: gates every incumbent adoption and every replica migration (~1 Hz affordable); property-based differential tests engine-vs-checker on 10⁵ random placements per training instance in CI |
| 4 | .so ABI/build failure or numba cold-JIT burn on the evaluation box | Quadruple runtime ladder (prebuilt .so → source build at import → numba warm-cached → pure python); ladder exercised in a Ubuntu 24.04 container pre-submission; JIT warmed on a dummy instance inside `algorithm()` before the clock-critical phase |
| 5 | Pathological weight/structure regimes (w2 dominant, m=1, all-zero-slack, preference ties) mis-tune operators | t=0 triage computes exchange rates from actual w1/w2/w3 and enables/disables operators accordingly (m=1 kills cross-bay ops; Z2-heavy enables balance-swap; preference-locked freezes exiles); the general parameter set is the tested default, per-regime tables only override it (OGC-2024 winner's fingerprint-with-general-fallback pattern) |

Residual risk of −1: none by construction (fallback verified feasible on prob_17/prob_40 at n=300/250; unbounded horizon confirmed in checker). Primary competitive risk is #2 — bounded by the fact that rivals using shapely or AABBs face the same or worse geometry loss at 100–400× fewer iterations.