# RESULTS.md — append-only experiment ledger

All results via the official `utils.check_feasibility`. Machine: macOS M-series,
/opt/anaconda3/bin/python (shapely 2.0.7). Solver seeds derive deterministically from
instance name + variant; portfolio = 4 processes.

## 2026-07-27 v1 vs v2 — 40 × 60 s sweep (git 1138370 pre-tag; contended: v1 4-way, v2 2-way)
Totals: v1 254,752,424 → v2 247,016,861 (−3.0%). 23 wins / 15 ties / 2 regressions
(prob_35 +1.6%, prob_36 +5.0%) / 0 infeasible. Per-instance table in
`research/` sweep logs and scratchpad sweep dirs. Set-1 highlights: prob_1 8,847→1,499
(= assignment-only floor), prob_13 −52% (4→0 tardy), prob_14 −65% (7→0 tardy).
Set-2 highlights: prob_28 −36.6%, prob_38 −3.4% (−180 tardy-days), prob_40 −5.1%.

## 2026-07-27 v2.1 solo re-runs (git 1138370, tag v2.1-frozen), 60 s
prob_35 5,586,483 (v1 6,000,966; −6.9%) · prob_36 407,802 (v1 421,789; −3.3%) ·
prob_13 119,955 (−56% vs v1) · prob_28 2,614,435 (−36.6% vs v1). Regressions eliminated.

## 2026-07-27 v2.1 edge battery (tag v2.1-frozen)
n600 feasible 57.7 s obj 972,088 · m1 feasible obj2=obj3=0 · orient-ids feasible ·
w1=0 feasible · w2=100k feasible obj2=8 · n5 feasible · zero-slack feasible obj1=0 ·
TL 10/21/30 s feasible (9.64/20.21/29.21 s elapsed) · 600 s soak prob_38: 74.73 M→71.54 M,
peak RSS 360 MB. Zero log errors.

## 2026-07-27 GATE L1 — layer-true differential (git 71cf4a1)
tests/l1_differential.py, 10⁴ cases × seeds {42, 1337, 20260727}: generated 9,922/9,832/9,828;
false_accepts **0/0/0**; FR rate 0.0014/0.0013/0.0022; overtime 0. PASSED (local shapely 2.0.7;
container 2.1.2 re-run pending).

## 2026-07-27 GATE L2 probes — layer-true value (git 71cf4a1+)
prob_25 @60 s: flag-off 351,265 | LT naive 363,492 | LT+layer0-candidates 379,259 |
LT+fast-accept 651,769 (search pathology, 0 rejected promotions → soundness confirmed) |
LT+entry-day-dominance 356,618. prob_27 @60 s: LT 51,727,606 = flag-off equal. NOT PASSED →
flag OFF for prelim.

## 2026-07-27 P2 probes — cross-bay operators (KESTREL_XBAY=1), 60 s solo
prob_32 6,275,991 (v2 contended 6,278,827; v1 6,601,623) · prob_36 408,698 (v2.1 407,802).
Flat. Full-gate A/B pending (tonight).

## 2026-07-27 mp robustness (frozen v2.1 snapshot)
kill-worker mid-run: PASS (feasible, obj 50,885 on prob_9@45 s) · boundary math
{20.0, 20.1, 21, 300, 1800} × n {7, 8, 9}: all budgets > 0, toggles exact. Drain-hang fix
applied after memo finding; portfolio smoke re-verified (prob_2 @30 s → 3,690, 28.97 s).

## Reference points
Organizer baseline (240 s): prob_1 795,089 · prob_9 2,362,394 · prob_25 823,887.
Best public 2026 competitor (etharthinas alg4/alg8): prob_1 151,662 · prob_9 106,065 ·
prob_25 ~744–898 k. Assignment-only floor prob_1: 1,499 (achieved).

## 2026-07-27 Slot-B gate sweep (git 85d75af cand vs v2.1-frozen), 40 × 60 s
Totals 246,244,956 → 245,523,873 (−0.29%), 0 infeasible, 9 wins / 27 ties / 4 flagged.
Flagged re-run solo (clean CPU): prob_13 −2.7% (artifact), prob_14 0.0% (artifact),
prob_32 0.0% (artifact), prob_11 +18.8% REAL (XBAY cadence). prob_11 variance analysis:
v2.1-frozen scored 46,011 / 52,955 / 56,917 across three contexts (±12% timing variance);
cand with XBAY=0 → 52,955 (= historical v2 value) → search-equivalent, PASS.

## 2026-07-27 Container gates (ubuntu 24.04, python 3.12.3, shapely 2.1.2)
GATE L1 in-container: 9,922 cases seed 42 → FA=0, FR=3 (0.14%) — matrix identical to
local shapely 2.0.7 (no version divergence). Parity battery on v2.2-slotA: running.

## 2026-07-27 Fuzz campaign (tests/fuzz_instances.py) — first blood
Found + fixed: (1) containment bbox from repaired-union bounds ≠ checker raw-vertex bbox
(out-of-bay emissions on degenerate shapes; zero training impact, proven); (2) harness
driver __main__ guard (macOS spawn process bomb — server fork immune; live-validated the
worker-crash fall-through: 4 dead workers → feasible single-process finish). Post-fix
smoke: 9/9 OK.

## 2026-07-27 ~10:45 KST — SLOT A ARTIFACT SHIPPED-READY
Parity battery (ubuntu 24.04 container, fork, shapely 2.1.2): 14/14 PASS after correcting the
battery's kill-test process targeting (it had killed the driver; proper grandchild-worker
SIGKILL → feasible, rc=0, 4 fork workers confirmed). Soak peak RSS 1,402 MB (fork, 4 workers).
Zip: submission/ogc2026_kestrel_v22.zip built from tag v2.2-slotA via git archive;
sha256 d9e581d8bdee3279818f4402b8122d6858ff5444014be528a404c492d95db96a; fresh-container smoke
on the artifact itself: loose 3,690 / congested 351,265 / tiny 3,150 — all feasible, return
shape verified.

## 2026-07-27 overnight robustness campaign — summary (as of ~08:00 IST / 11:30 KST)
Four engines, ~2h of continuous adversarial testing against the v2.2-slotA build:
- Fuzz lane A (macOS spawn): 330 randomized instances — ALL OK.
- Fuzz lane B (macOS spawn): 310 randomized instances — ALL OK.
- Fuzz lane C (ubuntu container, Linux fork, shapely 2.1.2): 330 randomized instances — ALL OK.
- L1 soundness marathon (container, shapely 2.1.2): 130 batches × 5,000 = 650,000 adversarial
  placement cases — 0 false-accepts throughout.
Instance envelope covered: n ∈ [1, 700], m ∈ [1, 8], bays 12–200 wide, tiny/huge/mono-bay/
8-bay/duplicate/congested profiles, sliver/concave/box shapes, K 1–4 (pyramid+mushroom),
non-contiguous orientation IDs, weights incl. w1=0 / w2=10⁶-dominant / all-zero, due<release,
zero-slack, releases up to 500, time limits 6–60 s. Zero crashes, zero infeasibles, zero
overtime, zero hangs since the two fixes (raw-bbox containment; harness __main__ guard).
Earlier tonight the same campaign found and fixed those two defects — the shipped Slot A
artifact (sha256 d9e581d8…) contains both fixes.

## 2026-07-27 overnight campaign — FINAL (~09:00 IST / 12:30 KST)
Lanes at loop close (still running to their own 240-min budgets, ending ~10:00 IST):
lane A 480 OK / lane B 460 OK / lane C (Linux fork container) 480 OK = 1,420 randomized
adversarial instances, ZERO failures of any class. L1 marathon: 188 clean batches =
940,000 differential placement cases under shapely 2.1.2, ZERO false-accepts.
Campaign totals incl. the discovery phase: 2 solver defects found+fixed (raw-bbox
containment; mp drain-hang), 1 harness defect fixed, both fixes shipped in v2.2-slotA
(sha256 d9e581d8bdee3279818f4402b8122d6858ff5444014be528a404c492d95db96a).

## 2026-07-27 ~13:45 KST — Rigorous lower-bound audit (tests/lower_bounds.py)
Two provable relaxations of the published objective (statement §1.7, code utils L1397-1430):
(a) energetic area-capacity tardiness bound — layer-0 same-layer disjointness (utils L521)
    implies capacity C = Σ_j W_j·H_j for the resource "layer-0 area"; for any (r,d),
    Z1 ≥ [Σ_{i: R_i≥r, D_i≤d} a_i·P_i − C(d−r)]/C with a_i = min_o area(layer0);
(b) LP relaxation of the assignment problem for w2·Z2 + w3·Z3 (exact for the LP, valid LB
    for the integer problem; floor() monotone).
RESULTS: (a) evaluates to **0.0 on all 40 instances** — the area relaxation is VACUOUS.
Mandatory-presence test (block must occupy its bay at t iff D_i−P_i ≤ t < R_i+P_i):
peak/bayArea > 1 on only **2/40** (prob_27 1.21, prob_38 1.15) → tardiness provably forced
on 2 instances only, while our build incurs Z1 > 0 on 21.
PROVEN OPTIMAL: prob_8 (LB 11,252 = ours 11,252, ratio 1.00).
PROVEN TARDINESS-OPTIMAL: 19/20 loose instances (Z1 = 0 = min).
RETRACTION: the earlier note that prob_1's 1,499 equals "the assignment-only floor" came from
a heuristic multi-start estimate, not a proof; the LP relaxation gives 988, so 1,499 is NOT
proven optimal. Corrected here for report integrity.
SCIENTIFIC CONCLUSION: raw area is never the binding resource; the binding resource is
*packing-feasible* area (median bbox fill 0.67, irregular layers, crane precedence). Our
tardiness on 19 instances is therefore attributable to packing efficiency, not physical
impossibility — which independently validates the layer-true/overhang programme (the
union-footprint invariant is the measured ceiling) as the top finals lever, and means an
area-based LB cannot certify optimality on the congested set (a geometric LB is finals work).

## 2026-07-27 ~17:30 KST — GEOMETRIC/ENERGETIC LOWER BOUND ON Z1 (tests/geometric_lb.py)
Follow-up to the 13:45 audit, which found the area-energetic Z1 bound of tests/lower_bounds.py
to be 0.0 on all 40 instances. New module `tests/geometric_lb.py` (7 min for all 40, self-test
included) derives five provably valid relaxations and reports the max; every proof is in the
module docstring with the exact utils.py line references it relies on.

RESOURCES (what is provably scarce)
* P1 layer-0 area, capacity Σ_j W_j·H_j — layer 0 is shared by every pair, so utils L521
  applies unconditionally; containment via the ALL-layer bbox (utils L252-266).
* P2 **slab / strip relaxation** (generalises the "tall blocks cannot stack" idea). The naive
  form — two blocks with bbox height > H/2 must have Σ bbox widths ≤ W — is **FALSE** here:
  interlocking concave layers can overlap in x while staying interior-disjoint. The valid
  repair is the guaranteed slab occupancy g_i(j,σ) = min over admissible orientations and over
  all admissible INTEGER y-offsets (positions are integers, utils L1154) of the layer-0 area
  inside a horizontal slab σ ⊂ [0,H_j]; then Σ_present g_i ≤ W_j·(β−α). It contains the strip
  bound exactly (rectangle w×h, h>H/2, slab (H−h,h) ⇒ d/cap = w/W) and degrades instead of
  breaking on concave shapes. Slab thickness optimised per bay (matched-ρ grid + exhaustive
  coordinate ascent). MEASURED GAIN: +29% on prob_27 (t=(18,14) vs the full (20,16)), 0
  elsewhere — because all 8 orientations include 90° rotations, so min_o(bbox height) is small
  and nothing is forced to be tall. Kept (provable, instance-independent).
* P3 bay-subset restriction B_i. Nearly vacuous on this set: ≥97% of blocks fit every bay.

ENGINES (how scarcity is converted into forced tardiness)
* W energetic-window cover: compulsory part [D_i+x_i−P_i, R_i+P_i) shrinks 1 day per unit of
  tardiness ⇒ fractional knapsack cover of the window excess. Subsumes the single-instant
  mandatory-presence test of the 13:45 audit.
* F **deadline-window cover** — the strongest engine: the whole P_i must fit inside
  [R_i, D_i+x_i), giving forced overlap ≥ F_i − (x_i − (b−D_i)^+)^+ with
  F_i = (P_i − (a−R_i)^+ − (D_i−b)^+)^+. Tardiness-cost analogue of the Gale–Hoffman condition
  for the preemptive transportation relaxation. 2.3× engine W on prob_38, 1.2× on prob_27.
* L preemptive whole-horizon LP (30-110k cols) with mandatory-presence and window cuts; wins
  only on prob_27 (+5%).  R prefix/rearrangement energetic bound (strengthens the old max-form
  to a sum-form): 0 on all 40.
* Free strengthening: exit times are integers (utils L1047) ⇒ Z1 ∈ ℤ≥0 ⇒ ceil() the bound.

RESULTS (vs shipped gateB/v21 = v2.2-slotA objectives)
* PROVEN NON-ZERO Z1 on 2/40: prob_27 LB_Z1 = 71 (ours 3,744), prob_38 LB_Z1 = 115 (ours 5,485).
  Objective LB: prob_27 31,156 → 977,799 (**31.4×**), prob_38 17,678 → 1,550,973 (**87.7×**).
* Congested group prob_21-40: old_LB 738,179 → new_LB 3,218,117 (4.36×); ours/LB 114.5 → 76.1.
  Loose group prob_1-20: unchanged at 502,748 (ours/LB 2.81) — Z1 = 0 is proven optimal on
  19/20; prob_20 (Z1 = 5) is NOT certified.
* SANITY (required): LB > ours on **0/40**, LB_Z1 > ours_Z1 on **0/40**. Self-test
  (`python tests/geometric_lb.py selftest`): five 5×5 squares in one 10×10 bay, R=0, D=P=2 —
  four tile the bay, the fifth cannot be co-present, optimum Z1 = 2; the bound returns
  **exactly 2.0**, and 0.0 for the 4-square variant. So the machinery is tight where the
  binding constraint really is area, and the weakness below is a property of the instances.
* Peak *forced* layer-0 density (mandatory presence / bay area): 0.22-0.36 on prob_1-20,
  0.41-1.21 on prob_21-40; horizon utilisation Σa_i·P_i/(C·span) = 0.13-0.27 vs 0.25-0.72.

REJECTED WITH PROOF + MEASUREMENT (documented in the docstring, not shipped)
* Dual feasible functions (Fekete–Schepers 2001; Carlier–Clautiaux–Moukrim 2007) applied to
  unit-cell coverage — valid because positions and bay dimensions are integral, so each cell
  obeys Σ_i c_i(cell) ≤ 1. Measured with f_{0,ε}: d^u/area = 0.974-1.000 for ε ∈ [0,0.5] on
  prob_21/27/38, i.e. **every non-trivial DFF is dominated by plain area** (boundary-cell
  coverages are spread over (0,1), not concentrated near 1).
* Crane rule (utils Stages 2/3/5). It does add area: the last-exiting block's whole footprint
  is disjoint from every other layer-0, giving Σ area(L0_i) + max_i(area(∪layers_i) −
  area(L0_i)) ≤ W_j·H_j — one block's upper-layer surplus, <1% of capacity.
* Layer index k>0 in the disjointness constraint: valid on {i : K_i > k} but always dominated.

CONCLUSION / WHERE THE FINALS EFFORT SHOULD GO
1. No congested instance is certified near-optimal. Certified headroom is largest on
   prob_23 (1510×), prob_33 (1078×), prob_39 (1067×), prob_30 (308×), prob_35 (244×),
   prob_40 (219×). Proven optimal: prob_8 (1.00×). Tight-ish: prob_10 1.32×, prob_3 1.46×,
   prob_17 1.48×, prob_1 1.52×.
2. Z1-ELIMINATION UPSIDE — w1·(ours_Z1 − LB_Z1) as a share of our objective, which is the
   *maximum* the tardiness term could still yield: prob_40 97.3%, prob_39 96.6%, prob_33 96.1%,
   prob_35 93.0%, prob_23 92.8%, prob_25 89.6%, prob_37 88.3%, prob_32 88.3%, prob_34 86.1%,
   prob_31 84.9%. On all of these the forced density peaks at 0.54-0.84 — i.e. the physics
   does not require the tardiness we are paying for. Tardiness reduction, not Z2/Z3 polish, is
   the dominant finals lever on prob_21-40.
3. Density-sensitivity DIAGNOSTIC (NOT a bound; assumes an unproven max packing density δ):
   even at δ = 0.5, forced tardiness stays far below ours — prob_40 1,168 vs 6,554,
   prob_39 396 vs 1,978, prob_33 687 vs 2,560, prob_38 1,644 vs 5,485. So packing
   inefficiency alone (down to 50% fill) explains at most ~20-30% of our tardiness under this
   relaxation; the remainder is search/sequencing headroom, or slack in the relaxation itself.
   Honest limit of the audit: area-type relaxations cannot certify more, because any additive
   functional valid under interior-disjointness alone is dominated by area (the DFF result
   above is the concrete evidence). Certifying the congested set would require exact
   irregular-packing feasibility reasoning, which is out of scope for the finals window.
