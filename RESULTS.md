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
