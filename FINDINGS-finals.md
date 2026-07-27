# FINALS DIAGNOSTIC FINDINGS — 2026-07-27 (post-preliminary)

All numbers measured on the shipped v2.2 search path (`_solve(..., variant=0)`,
single process, official checker verifying every solution). Scripts under
scratchpad/lt_diag/ (diag.py, why.py, ab_contact.py, occupancy/exhaustive probes).

## F1. The layer-true predicate is sound but the opportunity is structurally rare
Instrumented prob_25 @45 s with `KESTREL_LAYER_TRUE=1`:
`lt_calls = 250,286`, **`lt_accept = 0`**, `lt_time = 13.3 s` (30% of budget),
union-path calls collapse 2,181,219 → 703,911 (**3.1× throughput loss**),
objective 351,265 → 654,483.
Rejection attribution over 148,299 contested tests:
| relation | count | share |
|---|---|---|
| R1 same-layer collision | 142,216 | 95.9% |
| R2 entry crane | 3,980 | 2.7% |
| R5 roofed block exits first | 2,068 | 1.4% |
| same-day ties (R3/R7) + R4 | 35 | 0.02% |
| **ACCEPT** | **0** | **0%** |
Interpretation: 96% of union-contested positions are genuine same-layer
collisions that no rule can legalise. The true overhang candidates (R5, 1.4%)
are *all* rejected because a legal roof requires the NEW block to exit BEFORE
the block it covers, while EDD construction places early-exit blocks first —
the construction order is anti-correlated with the precedence the rule needs.
=> Overhang packing needs a *directed* operator (place long-stay blocks first,
then roof them with short-stay blocks whose exit <= the roofed block's exit),
not a predicate swap. Deprioritised; the certified-sound predicate is retained
behind LAYER_TRUE=False. Overhang capacity ceiling measured separately:
aggregate overhang area = 0.12–0.55 × one bay's area (largest: prob_40 0.55,
prob_26 0.53, prob_32 0.52).

## F2. Candidate generation is NOT the bottleneck
For the 6 most-tardy blocks of prob_38, an exhaustive integer scan over every
(x, y) and every orientation with the solver's own exact predicate found
**0 feasible positions** in every bay — identical to the heuristic candidate
set (which proposed 64–4,091 positions per bay). Not an enumeration gap.

## F3. Tardiness happens in bays that are less than half full (polygon area)
Occupancy audit of our own solutions on the days a tardy block was waiting:
| instance | tardy blocks | polygon occ. mean | polygon occ. max | horizon peak |
|---|---|---|---|---|
| prob_25 | 48 | 0.43 | 0.54 | 0.54 |
| prob_38 | 154 | 0.44 | 0.59 | 0.59 |
100% of waiting-days had the bay under 70% polygon-occupied.

## F4. ROOT CAUSE — envelope padding, because the polygon decoder is skipped
`_solve` sets `construct_stop = time.monotonic()` when `n_blocks > 160`
(myalgorithm.py ~L1162), so for n > 160 **all construction runs in
rectangle-envelope mode**; the polygon path is used only for re-insertions.
Same prob_38 solution measured both ways:
| measure | mean on waiting-days | max | horizon peak |
|---|---|---|---|
| polygon-area occupancy | 0.44 | 0.59 | 0.59 |
| **envelope-area occupancy** | **0.71** | **0.87** | **0.87** |
envelope/polygon = 1.62 => **38% of occupied bay area is bounding-box padding**.
Envelope occupancy 0.87 is at the practical limit for rectangle packing, so the
bays really are "full" in the model the solver is using — while 38% of the
space is recoverable by true-polygon packing. This is the mechanism behind F3
and behind the congested-set tardiness where all remaining objective mass sits.

## F5. Raising the n>160 threshold is NOT viable with the current kernel
One full exact-polygon construction pass on prob_38 (n=250) did not complete in
600 s (test killed at 10 min). At ~18 µs per shapely `relate_pattern` test
(2,181,219 calls / 39.0 s measured) the pass cost is prohibitive. The cutoff is
therefore a correct engineering decision, and **geometry-kernel throughput is
the binding constraint**, exactly as the KEEL M2 design argued.

## F6. Best-of-K time-aware contact scoring: no gain *yet*, and now explained
Added shared-edge contact scoring weighted by exit-date similarity (Koh
largest-contact-area; Shang et al. 2017 time-aware best contact), K ∈ {0,4,12,32}:
prob_25 identical for all K (654,483 — the polygon decoder never completes a
pass under load, so K cannot matter); prob_38 slightly worse with K > 0
(77.0M → 78.3–78.7M) because the extra predicate evaluations cost re-insertion
throughput while the *construction* remains envelope-based. Conclusion: layout
scoring is only worth re-testing AFTER the kernel makes polygon construction
affordable. Patch retained (`CONTACT_K = 0` default) at
scratchpad/lt_diag/myalgorithm_contact.py.
NOTE: prob_25 @45 s scored 351,265 alone vs 654,483 under 2-way CPU contention —
single-instance results on congested instances swing ~86% with available
iterations, so all future A/Bs must run un-contended.

## Consequent finals priority (evidence-ordered)
1. **Raster/bitmask geometry kernel (KEEL M2)** — bays ≤ 180×30 at integer
   positions => bit-packed per-layer occupancy grids, overlap = AND of uint64
   words, all positions scored in one pass. Target: exact-polygon construction
   affordable at n = 250–300, recovering a large share of the 38% envelope
   waste on prob_21–40. Gate: differential test vs `utils.py` with zero
   false-accepts (same protocol as the L1 gate that passed 1.05 M cases).
2. Re-test F6 contact scoring on top of the kernel (it was moot, not refuted).
3. Directed overhang roofing operator per F1 (reverse construction order).
4. Codex hardening items + geometric lower bound (agents in flight).

## F7. Raster geometry kernel built and gated (submission/raster_kernel.py)
Soundness proof in the module docstring (Lemma 1 superset rasterisation ->
Theorem 2 raster-disjoint implies zero intersection area -> Corollary 3 the
kernel can only ever be conservative, never accept an illegal placement).
Crane rule encoded via prefix-OR masks with the identity
(for all k: M_k ∩ ∪_{j>=k} occ_j = ∅) <=> (for all j: occ_j ∩ D_j = ∅).

GATE (tests/raster_gate.py, 432 comparable random near-contact pairs from real
training blocks, verdicts compared against utils.check_collisions and
utils.check_entry):
  false_accepts = 0  (same-layer 0, crane 0)   <- REQUIRED
  false_reject_rate among utils-accepted = 0.062 at S=4 (conservative only)
THROUGHPUT (prob_38 largest bay 109x27, ~40% layer-0 occupancy):
  per-test: kernel 68 us vs utils 503 us (7.4x) -- but the solver's own tuned
  shapely path is ~18 us/test, so per-test raster is NOT the win;
  BATCH: feasible_map = 1.19 ms for 1,960 positions = **0.61 us/position at
  S=4 => 30x faster than the 18 us/test path**, and it returns every legal
  position at once rather than the first bottom-left hit.
STATUS: enabling capability proven; NOT yet integrated, so no objective
improvement is claimed yet. Next step (own gate required): replace the exact
path in `_find_in_bay` with map-based candidate selection so polygon-exact
construction becomes affordable for n > 160, then re-test F6 contact scoring on
top of it. Open items: S=2 map is anomalously slow (93 ms — FFT sizing, not on
the S=4 target path); consider per-block S escalation to shrink the 6.2%
conservative-reject rate on hard blocks.

## F8. Raster integration: exact polygon construction is now affordable at n=250
Integration decision (safety): the kernel rasterises the **union footprint**, not
per-layer masks.  `_emit`'s same-day operation ordering is justified by the
union-disjoint invariant; per-layer semantics would invalidate that justification
(this is exactly why LAYER_TRUE must stay off).  Union-rastering therefore keeps
the current semantics EXACTLY and only makes the test batch-parallel.  Every
raster-selected position is still confirmed by the exact shapely predicate before
commit, so the kernel narrows the search without becoming the arbiter.
Consequently the historical `n_blocks > 160` skip of exact construction is lifted
when RASTER_EXACT is on, with the first pass capped at half the remaining budget
(a pass that cannot finish can never consume the run; the rectangle incumbent is
already checker-gated).

ONE exact-polygon construction pass, prob_38 (n=250):
| decoder | wall time | feasible | objective | Z1 |
|---|---|---|---|---|
| shapely candidate scan | **did not finish in 240 s** (>600 s earlier) | — | — | — |
| raster batch map | **83.0 s** | yes | 66,278,940 | 4,864 |
For reference the shipped build's FULL 60 s portfolio run scores 74,576,673 with
Z1 = 5,485, so a single construction pass is already **-11.1% objective and
-621 tardy days** — the first measured recovery of the 38% envelope waste (F4).
Matched-budget full-`_solve` A/B (240 s, prob_38 + prob_40) in flight; the
40-instance gate follows before anything is proposed for a submission.

## F9. Geometric lower bounds (agent track, tests/geometric_lb.py)
First non-trivial Z1 bounds on the congested set: prob_27 LB_Z1 = 71 and
prob_38 LB_Z1 = 115 (objective LB 31,156 -> 977,799 = 31x and
17,678 -> 1,550,973 = 88x).  Congested-group LB total 738,179 -> 3,218,117
(4.36x).  Sanity: LB > ours on 0/40 and LB_Z1 > ours_Z1 on 0/40; a hand-checked
self-test (five 5x5 squares in a 10x10 bay) returns exactly the true optimum
Z1 = 2.  Strongest engine: a deadline-window cover (whole P_i must fit in
[R_i, D_i + x_i), fractional knapsack over forced window overlap) -- the
tardiness analogue of Gale-Hoffman.  Proven dead ends, with measurements:
Fekete-Schepers DFFs on unit-cell coverage give d^u/area = 0.974-1.000 (every
non-trivial DFF is dominated by plain area), the naive "sum of bbox widths"
strip bound is INVALID here (interlocking concave layers overlap in x while
staying interior-disjoint; the rigorous slab repair gains +29% on prob_27 and
0 elsewhere because 90-degree orientations make min_o bbox height small), and
the crane rule adds <1% of capacity.
STRATEGIC CONSEQUENCE: w1*(ours_Z1 - LB_Z1) is 85-97% of our objective on ten
congested instances, and forced density peaks at only 0.54-0.84 on all but
prob_27/38 -- the physics does not require that tardiness.  A diagnostic
(explicitly NOT a bound) assuming bays can only ever be filled to 50% still
forces far less tardiness than we incur (prob_40 1,168 vs 6,554; prob_38 1,644
vs 5,485), so packing inefficiency explains at most ~20-30% of it within that
relaxation and the remainder is search headroom.  Largest certified headroom:
prob_23 1510x, prob_33 1078x, prob_39 1067x, prob_30 308x, prob_35 244x,
prob_40 219x.  Only prob_8 is proven optimal.

## F10. RETRACTED verdict + measurement protocol (a process failure, recorded)
A 40-instance gate of the hardening changes returned "+11.57%, 17 regressions,
0 wins, GATE FAIL". **That verdict is retracted: it was a contention artifact.**
The sweep was launched while the raster A/B (2 processes x 4 workers) and the
lower-bound agent's 425-515 s sweeps were still running, i.e. exactly the error
mode F6 already documented ("all future A/Bs must run un-contended", after
prob_25 swung 86% under 2-way load). Evidence that the verdict was wrong:
| instance | shipped, isolated | hardened, isolated | contended gate figure |
|---|---|---|---|
| prob_13 | 115,643 | **113,827** | 272,725 |
| prob_14 | 95,892 | **95,407** | 271,944 |
and in single-process `_solve` the two builds are behaviourally IDENTICAL
(prob_13 122,995 both, identical construct/sweep/ruin/find counters), so the
hardening edits cannot be the cause of a portfolio-level regression of that size.
STANDING PROTOCOL (binding for every future A/B and gate):
1. Nothing else may run on the machine - verify with pgrep/docker ps first.
2. Arms must be PAIRED and SEQUENTIAL: for each instance run arm A then arm B
   back-to-back, so residual load affects both equally.
3. A verdict from a contended run is not a verdict.
Re-run in progress with tests harness scratchpad/bisect/paired_gate.py.
CAVEAT: the F8 raster A/B (prob_38 -12.8%, prob_40 +13.0%) was also run 2-way
concurrent. Within each instance both arms ran sequentially in one process, so
the pairing is sound, but those two numbers must be reconfirmed un-contended
before the raster decoder is promoted; prob_40's regression in particular may be
partly artifact.

## Verified hardening items (synthetic instances, all checker-feasible)
| audit item | before | after |
|---|---|---|
| processing_time = 0 | EXIT before ENTRY -> missing EXIT | feasible (dwell = max(1, P)) |
| degenerate collinear layers | run aborted ("degenerate block geometry") | feasible (raw-bbox proxy orientation) |
| timelimit = 0.05 s | 0.33 s (6.6x over) | 0.05 s |
| 20000 x 5000 bay | OOM/timeout risk | feasible, 29.2 s of 30 s |
| env-var activation of experimental paths | os.environ read at import | plain module constants (LAYER_TRUE/XBAY = False) |
Item 6 (n=160/161 and max_release 60/61 threshold-cliff measurement) not done -
carried forward.
