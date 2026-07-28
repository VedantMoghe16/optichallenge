# TONIGHT PLAN — final preliminary submission (feed this to Codex verbatim)

*Written 2026-07-27 ~20:50 IST. Repo `/Users/vedantmoghe/Downloads/optichallenge`,
branch `finals`. The official checker `ogc2026/baseline/utils.py` is ground
truth and read-only. Baseline solver: `submission/myalgorithm.py` (hardened,
40-gate PASS, reference paired total 226,420,836 @60 s).*

## 0. Clock and the one rule that overrides everything

- Submission window opens **22:27 IST / 01:57 KST**. Preliminary closes
  **10:30 IST / 14:00 KST tomorrow**. Whatever we email next is FINAL (the
  cooldown makes any later window useless). Latest accepted submission
  REPLACES v2.2 even if worse.
- **Send target: 07:30–08:00 IST.** HARD STOP RULE: if the gate (§4) is not
  green by 07:45 IST, DO NOT SUBMIT — v2.2 stands at tier 18. One infeasible
  hidden instance costs ≈370 rank points (25–35 tiers); six teams are ending
  the preliminary buried by exactly that mistake. A worse-but-sent build is
  strictly worse than not sending.

## 1. Where the points are (from OUR results email + the official interim report + live dashboard forensics)

Our v2.2 hidden scores: P1 12,560 · P2 31,368 · P3 167,458 · P4 5,344,045 ·
P5 24,082,721 · P6 47,892,811. Field frontier (interim, 07-10 — the field is
better now): P1 11,280 (mass-achieved by 100+ teams) · P2 31,368 · P3 81,620 ·
P4 3.19M · P5 9.81M · P6 28.1M.

| target | why | effort share |
|---|---|---|
| **Never −1** | −370 rank pts per infeasible; already banked via hardening — keep every guard | gate only |
| **P5/P6/P4-class congested tardiness** | our worst relative scores (×2.45 / ×1.70 / ×1.67 off best); widest score spread in the field = where 100–300-rank jumps happen; proxies below | **~65%** |
| **P1-class loose polish** | 100+ teams tie at 11,280 and ALL of them currently beat our 12,560; closing it neutralizes an entire instance worth of rank deficit | ~25% |
| P2 | already tied with the best — DO NOT TOUCH its behavior class | 0% |

Training proxies (map hidden→training for all tuning tonight):
- P1/P2-class: prob_8, prob_2, prob_1 (small loose; we are LB-PROVEN optimal on
  prob_8 = 11,252 — the machinery can do it, P1 just isn't getting enough of it)
- P3-class: prob_29, prob_22, prob_25 (small congested burst)
- P4/P5-class: prob_30, prob_33, prob_31 (mid congested)
- P6-class: prob_38, prob_40 (big congested, crash-prone class — also memory-guard here)

## 2. Work items, in execution order

### W1 — Selective raster dispatch  ⏱ ~1.5 h  [prototype exists, boundary now fully measured]
Port `experiments/myalgorithm_raster_prototype.py` pieces into
`submission/myalgorithm.py` with the CORRECTED dispatch (this is the fix for
the prototype's +11.17%-overall result):
```
in _find_in_bay exact mode:
    if n_blocks <= 160:            -> legacy shapely scan (unchanged, proven)
    elif raster import OK and remaining_budget >= 1.6 * est_pass_cost:
                                   -> raster batch map;
                                      on miss AT A TIME POINT, fall through to
                                      the legacy scan for that time point
    else:                          -> legacy rectangle path (unchanged)
in _solve: lift the n>160 construct skip ONLY when the raster branch is active;
           first polygon pass capped at 50% of remaining budget.
est_pass_cost = 83 s * (n/250) * (avg_bay_cells/3270)   # measured @ n=250
```
Ship `submission/raster_kernel.py` in the zip. Defensive imports: any failure
of numpy/scipy/raster ⇒ identical-to-today behavior. Measured expectation:
prob_38 −12%, prob_40 −20%, prob_33 −14% at 240 s; zero change at n ≤ 160 and
at short limits BY CONSTRUCTION (that's the point of the dispatch).

### W2 — Blame-driven destroy + regret-2 repair + LAHC  ⏱ ~2.5 h  [pure Python, no deps]
In `_ruin_recreate` (workers 1–3 only; worker 0 legacy untouched):
1. Blame: blame_i = w1·max(0, exit_i − D_i); propagate 0.5× shares to blocks
   that occupied bay(i) during [R_i, entry_i). New destroy method: remove the
   top-blame block + its blockers + same-due-band neighbors + 3 random, total
   18–30 blocks.
2. Recreate with regret-2: for each removed block compute best and second-best
   insertion cost (bay × day × position via existing `_best_insertion`
   machinery); insert the block with the LARGEST (second−best) gap first.
3. Acceptance on workers 1–2: Late Acceptance Hill Climbing, ring buffer
   L = 120 of past objectives; accept candidate if better than buffer[i mod L];
   best-ever incumbent still checker-gated and never replaced by a worse one.
   Worker 3 keeps strict descent (diversity).
This attacks P3/P4/P5/P6-class instances; certified bounds say the headroom is
huge (tardiness 85–97% of our objective there, mostly not forced).

### W3 — P1-class loose polish  ⏱ ~1 h
On loose instances the improvement loop converges early and idles in
reconstruction kicks. Add: when Z1 == 0 and no improvement for 3 rounds,
switch workers 1–3 to a Z3/Z2-only mode: preference-repatriation destroy
(move exiled blocks toward argmax-preference bays; the XBAY method-4 code
exists behind `KESTREL_XBAY` — enable JUST that operator in this mode) +
Z2-balance swaps. Verify on prob_1/2/8 at 60 s AND at 300 s (P1's real limit
is unknown; make sure long budgets keep improving instead of idling).

### W4 — ONLY IF W1–W3 gate green early: CP-SAT bay-window repair oracle
Spec in CODEX-PLAN-finals.md §P1. Do not start after 04:00 IST.

## 3. What NOT to do tonight
- No per-layer/overhang geometry (measured dead end). No ALNS weight adaptation
  (0.14%). No monolithic MIP. No Cython/numba adventures (JIT risk at unknown
  short limits). No touching `_emit`, the fallback chain, or worker 0.
- Do not "improve" P2-class behavior — we are already at the field's best there;
  any change is pure downside risk.

## 4. The gate (time-boxed for tonight; every arm PAIRED and UN-CONTENDED)
1. **Proxy gate (~70 min):** paired baseline-vs-candidate on
   {prob_1, prob_2, prob_8 @120 s} ∪ {prob_29, prob_22 @120 s} ∪
   {prob_30, prob_33 @240 s} ∪ {prob_38, prob_40 @240 s}.
   PASS = 0 infeasible; no proxy worse >1%; congested proxies improve ≥5% in
   aggregate; loose proxies improve OR tie.
2. **Robustness (~25 min):** edge battery (tests/fuzz_instances.py smoke of 20
   cases + the 7 synthetic edges) + timelimit boundaries {10, 21, 30 s} on
   prob_20 + one 600 s soak on prob_38 with RSS check.
3. **Container parity (~20 min):** `docker/run_parity.sh` on the candidate;
   plus the corrected `docker/kill_test.sh`.
4. **Full 40-instance paired sweep at 60 s (~85 min) if the clock allows** —
   run it in parallel with nothing else, after 1–3 are green.
5. Zip via `scripts/build_submission_zip.sh <new-tag> <name.zip>` (byte-verified
   vs tag; must contain myalgorithm.py + README + raster_kernel.py), then
   fresh-container smoke of the zip artifact itself (loose+congested+tiny).
6. Ledger entries in RESULTS.md/DECISIONS.md; tag; push.

## 5. Schedule (IST)
21:00 W1 port → 22:30 W2 → 01:00 W3 → 01:30 proxy gate → 03:00 fixes/iterate →
04:30 second proxy gate + battery + container → 06:00 full sweep if green →
07:30 zip + checklist → **07:45 GO/NO-GO** → send by 08:00. Machine must be
idle for every measurement (pgrep first — a background full_compare/pilot may
still be finishing early in the night; kill them before gating:
`pkill -f full_compare; pkill -f gurobi_pilot`).

## 6. Success definition
Realistic winning outcome: P5/P6/P4 improve 10–20% (raster + blame-LNS),
P3 improves 10%+ (blame-LNS + LAHC), P1 drops toward 11,280 (W3), P2 unchanged.
Per the rank forensics (19 genuine ≥10-tier weekly jumps; scores tightly
clustered mid-pack), that profile is a plausible tier-18 → single-digit-tier
move. If only PART of it gates green, ship the green part — any strict
improvement beats standing still in a field where 48% drift backward weekly.
