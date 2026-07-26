# DECISIONS.md — append-only decision log (finals Technical Report substrate)

## 2026-07-27 ~03:00 KST — v2 → v2.1: legacy worker-0 guarantee
40-instance 60 s gate on v2 showed 23 wins / 15 ties / 2 regressions (prob_35 +1.6%, prob_36
+5.0%) vs v1. Root cause: new ruin schedule (%4 methods + rotating repair orders) changed
variant 0's trajectory. Decision: worker 0 runs v1's exact legacy schedule (`legacy=True`);
workers 1–3 explore. Evidence: solo re-runs flipped both regressions to wins (prob_35 −6.9%,
prob_36 −3.3%) with prob_13/28 wins preserved. Structural property: portfolio ≥ v1 by
construction.

## 2026-07-27 ~04:00 KST — edge battery green; v2.1 zip built
All cells feasible: n=600, m=1, non-contiguous orientation IDs, w1=0, w2-dominant, n=5,
zero-slack, TL ∈ {10, 21, 30} s, 600 s soak (peak RSS 360 MB). Zip byte-verified against the
battery-tested build (sha256 287057b8…). Slot A recommendation: ship after Docker parity
(pending daemon).

## 2026-07-27 ~08:00 KST — GATE L1 PASSED (layer-true predicate soundness)
3 seeds × 10⁴ adversarial near-contact cases (≈29.6 k generated): **0 false-accepts**,
false-reject rate 0.13–0.22%, 0 overtime. Predicate (R1–R7 relations incl. reverse-crane and
both-direction same-day ties) certified equivalent-or-conservative vs `utils.py` under local
shapely 2.0.7. Container re-run under 2.1.2 pending Docker daemon.

## 2026-07-27 ~08:10 KST — GATE L2 NOT PASSED (layer-true value) → flag stays OFF for prelim
Probes: naive integration collapsed prob_25 (651 k vs 351 k) — cause: sound-but-unpriced
overhangs create LIFO exit-precedence that taxes later insertions (legal ≠ profitable);
zero rejected promotions proved soundness. Entry-day-dominance integration (contested
positions only when no union-free position exists at day t) recovered to 356.6 k (−1.5% vs
flag-off) and prob_27 exactly flag-off-equal. Decision per fallback rule: KESTREL_LAYER_TRUE
default OFF for Slot B; carry to finals with priced-overhang scoring inside the improvement
loop (the KEEL "P4-priced roofing" design), where the runway allows proper integration.

## 2026-07-27 ~08:20 KST — P2 cross-bay operators: flat on probes, kept behind KESTREL_XBAY
Repatriation + Z2-swap destroys (workers 1–3 only): p32 6,275,991 (flat vs v2, −4.9% vs v1),
p36 408,698 (flat vs v2.1 solo). v2.1's bay-flush + exact-delta insertion already covers most
cross-bay value at 60 s. Default ON as diversity insurance pending the full-gate A/B; flip to
OFF if the sweep shows any net regression.

## 2026-07-27 ~08:25 KST — mp drain-hang fix (memo item 2)
`docs/MP_RISK_MEMO.md` identified: post-terminate `queue.get_nowait()` can block forever on a
frame torn by `terminate()` (partial `_recv_bytes()` with no timeout; uncatchable) → wall-clock
overshoot → −1. Fix: drain before terminate (no torn frames while children live), 0.4 s
time-guarded, never read the queue after terminate. Portfolio smoke re-verified (prob_2 30 s →
3,690, feasible, 28.97 s elapsed).

## Integrity note (standing)
Prior-edition finalist code (official open source, github.com/ogchallenge/ogc) may be adapted
with citation. Current-2026 competitor repos were examined for intelligence only (etharthinas,
drimdrim2002, blockforge, Dev-angPatil) — no code copied; techniques independently re-derived
(pairwise memoization from translation invariance; window-destroy from ALNS literature).

## 2026-07-27 ~10:00 KST — Slot A candidate = v2.2-slotA; XBAY default OFF
Gate flagged 4 instances; solo re-runs proved 3 contention artifacts and 1 real cadence
regression (prob_11 +18.8% with XBAY on). XBAY default flipped OFF → candidate is
v2.1 search behavior + drain-hang fix + raw-bbox containment fix + dormant flags
(KESTREL_LAYER_TRUE, KESTREL_XBAY) — strictly safer than v2.1-frozen, search-identical.
prob_11 residual deltas shown to be ±12% same-build portfolio timing variance.
XBAY and layer-true carry to finals as gated experiments.
