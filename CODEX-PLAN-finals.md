# CODEX IMPLEMENTATION PLAN — OGC 2026 finals build
*Written 2026-07-27 by the Claude planning track. Self-contained: read this file
plus the referenced repo files and you have everything needed. Every claim below
is either measured in this repo (cited to FINDINGS-finals.md / RESULTS.md) or
sourced from verified literature (links in the two research reports embedded in
§9). Do not re-derive; do not assume beyond what is stated.*

---

## 0. Ground rules (non-negotiable, same as the preliminary)

1. `ogc2026/baseline/utils.py` is the official checker. **Ground truth, read-only.**
   Every incumbent promotion must pass it before adoption. Nothing is ever
   emitted that has not passed it.
2. The never-infeasible chain must survive every change: checker-verified serial
   fallback built first → improvement only replaces a verified incumbent →
   deadline reserve ≥ 4% → global try/except returns the last verified solution.
3. `v2.2-slotA` (git tag) is the shipped preliminary submission. Never modify it.
   All work on branch `finals`.
4. **Measurement protocol F10 (binding):** nothing else running on the machine
   (`pgrep`/`docker ps` first); arms PAIRED and SEQUENTIAL per instance; a
   verdict from a contended run is not a verdict. Rationale: an 8% phantom
   regression and a sign-flipped A/B both came from contention
   (FINDINGS-finals.md F10).
5. Gate for ANY change: full 40-instance paired sweep at 60 s — 0 infeasible,
   total not worse than baseline by > 0.5%, no instance worse by > 2% without a
   written explanation. Congested-set changes additionally gate at 240 s.
6. The union-of-all-layers disjointness invariant **stays**. `_emit`'s same-day
   ordering is only correct because of it. Do not switch to per-layer
   feasibility (`LAYER_TRUE`) — measured dead end, see §8.
7. Solver = `submission/myalgorithm.py`. Entry `algorithm(prob_info, timelimit)`.
   Server: Ubuntu 24.04, Python 3.12, 4 cores (cpulimit throttling), 16 GB,
   shapely 2.1.2, numpy/scipy/numba/cython, **gurobipy 13 licensed**, ortools
   CP-SAT, no internet. Zip ≤ 15 MB, `myalgorithm.py` at root. Time limits
   30 s – 30 min (2025 finals: 14 instances, 30–600 s).

## 1. Where the objective mass is (measured — this directs everything)

- Tardiness (Z1) is **85–97% of our objective on ten congested instances**
  (prob_23/25/26/27/30/33/35/38/39/40), and certified lower bounds prove most of
  it is NOT forced by physics (`tests/geometric_lb.py`; bounds validated against
  240 checker-verified solutions, zero violations). Certified headroom up to
  1510× (prob_23). Only prob_8 is proven optimal.
- Root cause #1 (fixed in prototype): for n > 160 construction packs bounding
  rectangles → 38% of bay area wasted as padding (envelope occupancy 0.87 vs
  polygon 0.44). The raster kernel (`submission/raster_kernel.py`, sound: 0
  false-accepts, 30× batch throughput) makes exact-polygon construction finish
  in 83 s at n = 250 (was > 600 s). Paired 240 s A/B on 4 congested instances:
  **−4.0% total** (prob_40 −19.7%, prob_33 −13.9%, prob_38 −12.3%,
  prob_27 +19.6%).
- Root cause #2 (unaddressed): the improvement search is weak relative to the
  certified gap — packing efficiency explains at most ~20–30% of our tardiness
  within the LB relaxation; the rest is SCHEDULING search headroom.

## 2. Work items, strict priority order

### P0 — Finish the raster decoder integration  ⏱ 0.5–1 day  [prototype exists]
File: `scratchpad/lt_diag/myalgorithm_raster.py` is the working prototype
(diff it against `submission/myalgorithm.py`; the pieces are `_raster_orient`,
`_find_in_bay_raster`, the `RASTER_EXACT` dispatch in `_find_in_bay`, and the
lifted `n>160` construct gate with a half-budget first-pass cap).
1. Port the prototype into `submission/myalgorithm.py` behind module constant
   `RASTER_EXACT = True`, with defensive import of `raster_kernel` (fall back to
   the proven path when scipy/numpy import fails).
2. Ship `raster_kernel.py` inside the zip next to `myalgorithm.py` (zip already
   allows extra files at root).
3. **Budget policy (the piece that turns −4.0% into ~−8%):** at startup compute
   `forced_density` = peak over t of Σ layer-0 area of blocks with
   D_i − P_i ≤ t < R_i + P_i, divided by total bay area (code exists in
   `tests/geometric_lb.py`, engine W; also `tests/lower_bounds.py`
   mandatory-presence test). Rule from measurement: prob_27 (1.21) lost 20%,
   prob_38 (1.15) won 12%, prob_33 (0.80) won 14%, prob_40 (0.84) won 20%.
   Policy: if `forced_density > 1.18` (only prob_27 qualifies in training) OR
   `timelimit < 1.6 × estimated_pass_cost`, keep the rectangle construction and
   spend the budget on improvement; else run the raster polygon construction.
   `estimated_pass_cost ≈ 83 s × (n/250) × (avg bay cells / 3270)` — calibrate
   on training, log it.
4. Gate per §0.5 at 60 s AND 240 s. The 60 s side is the risk: a pass that
   cannot finish must not eat the budget (the half-budget cap handles this —
   verify explicitly at 30 s and 60 s on prob_38).
5. **LIVE FINDING from the in-flight full comparison (43/60 runs,
   experiments/results/full_compare_PARTIAL_43of60.log): the prototype
   REGRESSES on small congested instances at 240 s (prob_21 +73%, prob_22
   +32%, prob_23 +22%).** Root cause hypothesis (verify): for n ≤ 160 the
   legacy exact scan already runs and works; the prototype's raster dispatch
   *replaces* it and is strictly more conservative (6.2% over-rejection,
   24-candidate cap, `continue` skips the scan fallback on a raster miss), so
   quality drops where the scan was fine. FIX REQUIRED in the port: apply the
   raster path ONLY where the alternative is rectangle packing (n > 160 or
   scan-unaffordable), and on a raster miss FALL THROUGH to the legacy scan
   instead of skipping the time point. The gain (prob_33/38/40, n = 250) and
   the loss (prob_21/22/23, n ≤ 150) are cleanly separated by exactly this
   condition.

### P1 — Solver-as-repair oracle (CP-SAT bay-window resequencing)  ⏱ 1–2 days  [highest expected gain]
This attacks the certified scheduling gap directly. Literature anchors: Godard
et al. ICAPS'05 (randomized LNS on cumulative scheduling: better-than-published
on 33/36 open instances); Hooker OR 2007 (logic-based Benders on min-tardiness:
25×–1000×); BALANS IJCAI'25 (LNS-over-MIP: >75% primal-gap reduction).
1. New module `repair_oracle.py` (shipped in zip): given (bay b, window
   [t0, t1], incumbent), FREE the 15–25 blocks whose intervals intersect the
   window; everything else in b is a fixed interval. Model in CP-SAT:
   - interval per free block, start ≥ R_i, duration = max(1, P_i);
   - `AddCumulative` with capacity = `0.88 × bay_area(b)` and demand =
     layer-0 polygon area of each block (0.88 = measured packing-efficiency
     margin — CALIBRATE: it must over-estimate what the geometry can actually
     realize rarely enough that repairs usually re-place successfully);
   - objective Σ w1·T_i with T_i ≥ end_i − D_i, T_i ≥ 0;
   - the two tricks from ortools' `weighted_tardiness_sat.cc`: dominance
     precedences (d_i ≤ d_j ∧ p_i ≤ p_j ⇒ i before j — weights are uniform
     here so the w-condition is free) and incumbent objective as upper bound;
   - `add_hint` = incumbent times; `num_search_workers = 1`;
     `max_time_in_seconds` ≈ 2% of remaining budget (BALANS ratio), floor 0.5 s.
2. Decode the oracle's day assignments back through the (raster) placement
   path; blocks that fail geometric placement at their assigned day get the
   earliest feasible later day (existing `_find_in_bay` machinery). If total
   objective (checker-verified) improves → adopt.
   IMPORTANT: never trust the oracle's objective — only the checker's.
3. Wire as a new recreate operator inside `_ruin_recreate` (a new method id),
   destroy = "blame window": the (bay, day-window) with the largest accumulated
   w1·T over blocks entering there. Runs on ONE portfolio worker only (see P4).
4. Fallback chain: gurobipy time-indexed variant (x[j,t] start binaries, one
   area row per day — n=80, T=200 ⇒ 16k binaries, LP is tight for ΣwT) if
   CP-SAT import fails, then the existing heuristic recreate. Defensive imports
   everywhere; the oracle must be a bonus, never a dependency.
5. Gate per §0.5; expect the win on prob_21–40, especially the ten instances in
   §1. Also verify at 30 s (oracle should be skipped below ~45 s budgets).

### P2 — Acceptance + neighborhood upgrades in the existing loop  ⏱ 0.5 day  [cheapest big win]
Three independent, individually-gateable edits (literature: Ropke–Pisinger
operator diversity; EJOR 2021 meta-analysis — ALNS *weight adaptation* is worth
0.14%, do NOT build it; LAHC = scale-free acceptance):
1. **Late Acceptance Hill Climbing** replacing strict descent in the improvement
   loop: accept if better than the objective L iterations ago (ring buffer,
   L = 100; tune once on training). Scale-free ⇒ survives w1 swinging 667→29630
   across instances where any SA temperature would not.
2. **Bigger, smarter destroys:** current q ≤ 12 → allow 20–40% of n, sampled by
   {random, related (same due-band + same bay + nearby), worst (top w1·T_i)}.
   Keep worker 0's legacy schedule untouched (§0 rule: the never-worse-than-v1
   guarantee stays).
3. **Dynasearch intensification** per bay: DP over non-overlapping adjacent
   interchanges of the bay's entry order (O(n²) per pass), applied to the two
   worst bays after each accepted destroy-repair.
Gate each edit separately (they are ~20–50 lines each).

### P3 — ISWO blame propagation on construction  ⏱ 0.5 day
Wrap the existing multi-start construction in the Improved-Squeaky-Wheel cycle
(Joslin–Clements; arXiv 0803.1993): blame_i = w1·T_i; ALSO propagate a fraction
of blame_i to the blocks that occupied bay(i)'s area during [R_i, ENTRY_i]
(they caused the wait — this is what plain priority bumping misses). Bump
priorities, probabilistically discard top-blame + a random handful, reconstruct
only the discarded set. Reuses the existing greedy verbatim. Also: use the
blame map to choose P1's destroy window instead of uniform sampling.

### P4 — Portfolio restructure: 3 diversified + 1 oracle  ⏱ 0.5 day
Evidence: ManySAT (diversified same-solver portfolio won SAT-Race), ParBalans
(monotone gains 2→128 workers from differently-configured workers + best-gap
sharing), and our own flat P2-probe result for identical replicas.
1. Worker 0: legacy v1 schedule (unchanged — the safety anchor).
2. Workers 1–2: P2/P3 loop with deliberately divergent configs (destroy sizes
   10%/25%/40%, LAHC L ∈ {50, 200}, different priority rules, different seeds).
3. Worker 3: the P1 oracle loop (its CP-SAT/Gurobi at Threads=1 — NEVER let
   4 workers each spawn multi-threaded solvers).
4. Sharing stays as-is (queue streaming of checker-passed incumbents) plus ONE
   addition: a worker that hasn't improved for 10% of the budget adopts the
   global best and applies a 30% random kick. Never synchronize all workers.

### P5 — Sparrow-style separation/compression layer on the raster lattice  ⏱ 2–3 days  [research bet, gate hard]
The current published SOTA in irregular packing (sparrow, arXiv 2509.13329;
integer-lattice precursor Umetani–Murakami arXiv 2104.04525) is overlap-
TOLERANT: place with overlap allowed, then repair by guided local search.
Use it to force ONE more tardiness-critical block into a full day-window:
1. Pairwise penetration-depth queries: no-fit-raster tabulation with
   shape-class dedup (dedupe by hashing the vertex lists; training instances
   repeat shapes heavily) + lazy LRU; bit-packed uint64 rows; horizontal
   penetration depth = shift-AND scans (Umetani's O(1) trick).
2. GLS loop: insert the critical block at min-overlap position; iterate
   per-item x/y line searches minimizing Σ weight(i,j)·penetration(i,j);
   multiply weight on colliding pairs, decay when resolved; strikes/backtrack;
   accept only when overlap hits 0 AND the checker passes.
3. This also unlocks re-testing best-of-K contact scoring
   (`scratchpad/lt_diag/myalgorithm_contact.py`, CONTACT_K default 0) — it was
   moot without a working polygon decoder, not refuted.
Budget guard: only run when `timelimit ≥ 240 s` until measured.

### P6 — Engineering hardening  ⏱ 1 day, parallel to the above
1. **Cython AOT for the bit kernels** (raster stamp/unstamp/point-query +
   penetration scans): with a 30 s minimum limit, numba cold-JIT (3–4 s/function,
   tens of seconds for a suite) is disqualifying unless the server persists the
   cache — UNVERIFIED, so Cython compiled at package time (Linux wheel built in
   the parity container, `docker/`) with `__builtin_popcountll`; pure-python
   fallback via defensive import.
2. Fail-fast surrogate cascade (jagua-rs): 2–4 poles-of-inaccessibility circles
   per shape tested before any exact work in the *point-query* path.
3. Per-block sub-grid escalation S=4 → S=8 for blocks that repeatedly fail to
   place (kernel over-rejection is 6.2% at S=4, halves per S doubling).
4. Finish audit item 6: measure the n=160/161 and max_release=60/61 cliffs
   (may dissolve entirely once P0 lands).

## 3. What NOT to build (measured/verified dead ends — do not spend time)

| idea | evidence |
|---|---|
| Per-layer feasibility / overhang predicate (LAYER_TRUE) | 0 accepts in 250,286 contested tests; construction order anti-correlated with the required exit precedence (F1). Only viable as a *directed* roofing operator, parked. |
| ALNS operator-weight adaptation | 0.14% mean gain across 25 implementations (EJOR 2021 meta-analysis) |
| Better area-type lower bounds (DFFs) | measured d^u/area = 0.974–1.000; dominated by plain area (F9) |
| Monolithic MIP/CP over a whole instance | CP-SAT/Gurobi found feasible on 1 of 25 real instances at 1h in the closest published analogue (arXiv 2512.11864) |
| Naive pairwise NFP tabulation without dedup | ~9 GB; with shape-class dedup ~0.25 GB (fine) |
| A raw Python SA arms race | 100–1000× iteration deficit vs compiled rivals; buy back per-iteration power (P1) or compile the inner loop (P6), never brute-force in Python |

## 4. Measurement & gates (copy exactly)

- Harness: `scratchpad/bisect/paired_gate.py` pattern — paired sequential arms,
  idle machine, checker objectives only. 40 × 60 s always; +20 congested × 240 s
  for anything touching construction or the oracle; +30 s spot-checks on
  prob_20/38 for anything touching budget logic.
- Reference numbers (paired, un-contended, 60 s): total 226,420,836 for the
  hardened baseline; per-instance values in `scratchpad/bisect/paired_gate.log`.
  240 s congested-4 reference: kestrel 128,524,894 / raster 123,381,786.
- Edge battery + container parity (`docker/run_parity.sh`) before any zip.
- Zip checklist: `scripts/build_submission_zip.sh <tag> <name.zip>` — extend it
  to include `raster_kernel.py`, `repair_oracle.py`, and any compiled `.so`
  (built in the container, with source + build-at-import fallback).

## 5. Suggested sequence for Codex

Day 1: P0 (port + budget policy + gates). Day 2: P2 (three small gated edits),
P3. Day 3–4: P1 oracle + P4 portfolio. Day 5+: P5 if P0–P4 are green and
banked; P6 alongside. Submit-worthy checkpoints after P0, after P2/P3, after
P1/P4. Finals open Aug 3 14:00 KST; 12 h cooldown; latest accepted submission
replaces previous — same discipline as the preliminary: ship the safest
strictly-better build, never the newest.

## 6. Files map

| file | role |
|---|---|
| `submission/myalgorithm.py` | solver (branch `finals`, hardened; P0–P4 edit here) |
| `submission/raster_kernel.py` | sound raster geometry (done; ship in zip) |
| `scratchpad/lt_diag/myalgorithm_raster.py` | P0 prototype to port |
| `scratchpad/lt_diag/myalgorithm_contact.py` | contact-scoring patch (re-test after P0) |
| `tests/geometric_lb.py`, `tests/lower_bounds.py` | certified bounds; forced_density code for P0.3 |
| `tests/raster_gate.py` | kernel differential gate (extend if kernel changes) |
| `tests/l1_differential.py`, `tests/fuzz_instances.py`, `tests/mp_robustness.py` | regression harnesses |
| `scratchpad/bisect/paired_gate.py` | THE measurement harness (protocol F10) |
| `docker/` | server-parity container (build wheels here) |
| `FINDINGS-finals.md`, `RESULTS.md`, `DECISIONS.md` | evidence ledgers — append, never rewrite |

## 7. Expected value summary (honest, order-of-magnitude)

| item | expected objective effect | confidence |
|---|---|---|
| P0 raster + budget policy | −6–10% total on congested set | high (measured −4.0% without the policy) |
| P1 repair oracle | −20–60% of remaining tardiness on congested set | medium (strong literature analogues, untested here) |
| P2 LAHC + destroys + dynasearch | −10–30% on congested | medium-high (cheap, standard) |
| P3 ISWO blame | −5–15% additional | medium |
| P4 portfolio diversity | −5–15% over identical replicas | medium-high |
| P5 separation layer | unlocks last-block insertions; unknown | low-medium (research bet) |

These do not add linearly; the certified bounds say the total available on the
congested set is enormous (§1), so overlapping gains are expected to keep
paying until the harness says otherwise.

## 8. Context: why the raster engine wasn't in the preliminary
It was planned from day one (KEEL M2 in STRATEGY.md) but correctly sequenced
behind the deadline: the preliminary verdict was keep-and-stretch on a proven
build, and the evidence that the rectangle fallback cost 38% of bay area only
existed after the post-submission diagnostics (F3–F5). The preliminary
submission (v2.2, sha256 d9e581d8…) is safe, tested against 1,420 fuzz
instances + 1.05 M differential cases, and cannot score −1 by construction.

## 9. Research reports backing this plan
Full texts with all links are archived in the session task outputs and
summarized in FINDINGS-finals.md. Key verified sources: sparrow
(arXiv 2509.13329, SOTA irregular packing) and jagua-rs (arXiv 2508.08341);
Umetani–Murakami (arXiv 2104.04525); Godard–Laborie–Nuijten ICAPS'05; Hooker OR
2007 logic-based Benders; BALANS (arXiv 2412.14382) + ParBalans
(arXiv 2508.06736); Turkeš et al. EJOR 2021 (ALNS adaptiveness = 0.14%);
MAPF-LNS bandit sizing (arXiv 2312.16767); ManySAT JSAT 2009; Minaiev's SA
engineering ladder; terry-u16 AHC writeups; ortools weighted_tardiness_sat.cc.
