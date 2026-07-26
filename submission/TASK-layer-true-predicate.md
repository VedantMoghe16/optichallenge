# Task spec: layer-true collision + crane predicate for kestrel (backlog item 3)

*Hand this to the GPT-5.6 terminal. Work on a COPY of `submission/myalgorithm.py`
(current v2). Do not touch the v2 zip. Target: Slot B / finals submission, gated
by the differential test below.*

## Goal

Replace kestrel's over-conservative safety invariant — "co-present blocks have
disjoint interiors of the UNION of all their layers" (built at
`_precompute_geometry`, `union = unary_union(layer_polys)`) — with the exact
competition rules. This unlocks (a) same-layer-disjoint packings where different
layers may overlap in plan view, and (b) deliberate overhangs ("mushroom
roofing": 35% of multi-layer blocks have upper layers larger than the base).
Median bbox fill is 0.67, so the capacity recovery is large exactly on the
congested instances (p25/p27/p33/p38/p40) where tardiness still dominates.

## Exact semantics (verified line-by-line against ogc2026/baseline/utils.py — the checker is ground truth)

Let block A have layers A_0..A_{Ka-1} (translated to its position), B likewise.
All tests are "interior intersection area > 0" (edge/point contact is legal).

1. **Static co-presence (checker Stage 4)**: for two blocks whose residence
   intervals [entry, exit) overlap in time and are in the same bay:
   only SAME-INDEX layers matter — require area(A_k ∩ B_k) = 0 for all
   k < min(Ka, Kb). Cross-index overlap (A_j over B_k, j≠k) is legal at rest.
2. **Crane ENTRY of A at day t (Stage 2/5)**: against every block B present at
   the moment of entry: require area(A_k ∩ B_j) = 0 for ALL pairs j ≥ k.
   (A descends vertically; its layer k sweeps all heights ≥ k.)
   "Present at entry" for Stage 2 = entry_B < t < exit_B (strict, same-day
   events excluded); Stage 5 replays ops in listed order per day with all
   EXITs before all ENTRYs — kestrel's `_emit` already orders EXIT-before-ENTRY,
   and within-ENTRY order is by (bay, block_id). IMPORTANT consequence: if two
   blocks entering the SAME day overlap in the crane sense (A_k ∩ B_j ≠ 0 for
   j ≥ k), the later-listed one fails Stage 5. Safe policy for the first
   iteration: treat same-day co-entrants in the same bay as fully present
   (conservative), i.e., include them in the blocker set with the j ≥ k rule.
3. **Crane EXIT of A at day t (Stage 3/5)**: same j ≥ k rule against blocks
   with entry_B < t < exit_B. Consequence: if B's layer j overhangs A's layer
   k (j > k) while co-present, A cannot exit before B (interval nesting).
   Safe policy: only allow a placement of A that creates/there exists an
   overhang relationship if the induced order is consistent — simplest sound
   rule (adopt it): **EXIT-monotone stacking** — permit a NEW block N whose
   layer j would overlap (plan view) an existing co-present block E's layer k
   with j > k ONLY IF exit_N ≤ exit_E... CAREFUL, direction: N's higher layer
   over E's lower layer means N is the roof, so N must enter after E (true —
   N is being inserted now) and N must EXIT BEFORE OR WITH E, i.e., require
   exit_N ≤ exit_E. Reject the reverse case (N's lower layer under E's higher
   layer, i.e., sliding under an existing roof) — it is crane-infeasible at
   entry by rule 2 anyway (j ≥ k covers it).
   With EXIT ties (exit_N == exit_E): legal only if at that day the roof is
   listed/exits first. kestrel emits EXITs sorted by (bay, block_id) — NOT
   safe for ties. Either (a) require strict exit_N < exit_E, or (b) extend
   `_emit` to order same-day EXITs roof-first (track nesting depth). Start
   with (a) strict; measure; only do (b) if it costs measurable objective.

## Implementation sketch

1. In `_precompute_geometry`, keep the union (fast bbox path + rectangle mode
   unchanged) and ADD `layers: tuple[Polygon, ...]` to `Orient` (translated
   copies via the same reference-point subtraction).
2. Add `_safe_layers_position(geom, x, y, entry, exit_t, blockers)`:
   - bbox prefilter as today (union bbox);
   - for each near blocker B (an assignment dict with `_geom`, `x`, `y`,
     `entry_time`, `exit_time`):
     - static rule: same-index layer pairs k, area test;
     - crane-at-entry rule vs B if B present at entry (plus same-day
       co-entrants, conservative);
     - crane-at-exit rule vs B if B present at exit_t;
     - EXIT-monotone check for any j > k plan-view overlap created.
   - Cache verdicts per (P-orient id, B-orient id, dx, dy, relation-type) —
     same relative-displacement trick as `_PAIR_CACHE` in v2, but the verdict
     now depends on which rule applies; key must include the rule flavor
     (static / entry-crane / exit-crane) NOT the times themselves.
3. `_find_in_bay` (exact mode): pass entry/exit to the new predicate; blocker
   set must include ALL blocks whose interval overlaps [t, exit_t) (as today)
   — the predicate decides per-rule which pairs matter. Candidate positions:
   today's contact points come from union AABBs; add layer-0 AABB contact
   points too (denser packing candidates under the relaxed rule).
4. Leave `exact=False` (rectangle) mode and `_serial_fallback` untouched.

## Non-negotiable gate (before this ever ships)

Differential test vs the official checker:
- Generator: for ≥10 random training instances, produce ≥10,000 random
  placements each (biased toward near-contact: offsets sampled within ±3 of
  touching), build small schedules (5-30 blocks), run kestrel's predicate,
  then `utils.check_feasibility` on the emitted solution.
- REQUIRED: **zero false-accepts** (predicate says safe, checker says
  infeasible). False-rejects are allowed (only cost packing density).
- Also run the full 40-instance sweep at 60 s and 240 s: all feasible, and
  total objective must beat v2's sweep totals before it replaces v2.

## Files

- Solver: `/Users/vedantmoghe/Downloads/optichallenge/submission/myalgorithm.py` (v2)
- Checker (ground truth): `/Users/vedantmoghe/Downloads/optichallenge/ogc2026/baseline/utils.py`
- Rules audit with line refs: `/Users/vedantmoghe/Downloads/optichallenge/research/01-checker-rules-audit.md`
- Instance analytics: `/Users/vedantmoghe/Downloads/optichallenge/research/02-instance-analytics.md`
- Python: `/opt/anaconda3/bin/python` (has shapely 2.0.7)
