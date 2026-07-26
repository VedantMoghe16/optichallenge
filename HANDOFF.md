# HANDOFF — OGC 2026 "Kestrel" solver: complete state of work
*(Self-contained brief for pasting into another AI session. Written 2026-07-27, ~07:30 KST.)*

## 1. The competition (facts, all verified)

- **OGC 2026** (optichallenge.com, LG CNS + Seoul National University): "The Grand Shipyard Puzzle."
  400 teams. **Preliminary closes 2026-07-28 14:00 KST (tomorrow). Final round Aug 3–14. Top 30–40 advance.**
- Submission: email ONE zip (myalgorithm.py at root, ≤15 MB, never include utils.py) to
  submission@optichallenge.com from the registered team email. **12-hour cooldown; the latest accepted
  submission always replaces the previous one — even if it's worse.** We treat remaining slots as 2:
  Slot A today, Slot B tomorrow morning (email by ~12:00 KST for buffer), Slot B only if strictly better.
- Scoring: per hidden instance, rank-based; infeasible/crash/timeout = −1 (catastrophic). Currently 6
  hidden instances P1–P6 (may be augmented). Dashboard shows P3 is hardest (15 teams infeasible, 5 crash)
  and P6 crash-prone (11 crashes). Time limits "tens of seconds to tens of minutes" (2025 finals precedent:
  14 instances, 30–600 s).
- Server: Ubuntu 24.04, 4 CPU cores (firejail/cpulimit throttling, not kill), 16 GB, Python 3.12 conda,
  shapely 2.1.2, gurobipy 13 licensed, no internet. Entry point `algorithm(prob_info, timelimit=60)`.

## 2. The problem (one paragraph)

n blocks (100–300 in training), each with 1–4 stacked polygon layers and 2–8 fixed orientations, must each
be assigned to one of m rectangular bays (2–5), given an integer position (x, y), an ENTRY day ≥ release,
and an EXIT day ≥ ENTRY + processing. Co-present blocks in a bay must not overlap at the SAME layer index
(edge contact legal); a vertical crane rule requires, at any block's ENTRY/EXIT, its layer k to be clear of
co-present blocks' layers j ≥ k (so a taller block may legally overhang a shorter one only if it enters
later and exits earlier — LIFO nesting). Objective: minimize w1·(total tardiness) + w2·(bay workload
imbalance) + w3·(bay-preference regret), with w1 huge (667–29,630/day) — tardiness dominates. Crucial
structure: w2 and w3 terms depend ONLY on the assignment vector; given assignments, bays are independent.
The official checker `utils.py` (shapely-based, 5 stages) is ground truth; per-day op order is
all-EXITs-then-ENTRYs in OUR listed order.

## 3. What exists (chronological)

- **v1 "kestrel"** (written by GPT-5.6 Codex, 811 lines, `submission/myalgorithm_v1_backup.py`): anytime
  single-process heuristic. Safety invariant: co-present blocks keep disjoint interiors of the UNION of all
  their layers (stronger than the rules → crane feasibility for free, any same-day op order safe).
  Pipeline: fit-aware serial fallback (checker-verified immediately) → multi-start construction under 5
  priority rules (fast rectangle-envelope mode with row bitsets, then true-polygon mode with contact
  candidates, DE-9IM `relate_pattern("2********")` overlap tests) → improvement: blame-ordered single-block
  reinsertion sweeps + ruin-and-recreate (3 destroy methods, q ≤ 12) with stagnation kicks. Every promotion
  passes the bundled official checker; deadline reserve 4%; global try/except returns last verified
  incumbent. **Never infeasible by construction.**
- **v2 (my stretch, backed up as the current `submission/myalgorithm.py`)**, four additive patches:
  1. **Pairwise collision-verdict cache** keyed by relative displacement (id(P), id(Q), x−u, y−v) — exact
     shapely verdicts, translation-invariance re-derivation; only skips recomputation.
  2. **Delta-objective reinsertion sweep** (O(bays) imbalance delta per trial instead of O(n) rescan) +
     per-(block, bay) orientation-order cache.
  3. **Peak-window flush** destroy (4th method): evict up to 48 blocks entering one bay around a blamed
     block's entry date, re-time jointly under 4 rotating repair orderings (coordinated re-timing move).
  4. **4-process portfolio**: workers = diversified variants (seed bump 7919·v, construction-mode
     rotation); each streams checker-verified incumbents to the parent via a queue (throttled 0.5 s), so a
     worker killed at deadline still contributes; parent picks min-objective; limits < 20 s or n < 8 use
     the single-process path; any multiprocessing failure falls through to single-process with remaining
     budget.
- **v2.1 (current)**: after the 40-instance gate showed 2 regressions (prob_35 +1.6%, prob_36 +5.0%),
  worker 0 now runs v1's EXACT legacy destroy/repair schedule (`legacy=True`: methods %3, fixed repair
  order) — so the portfolio can never search worse than v1 by construction; workers 1–3 explore the new
  operators. Solo re-runs confirm: prob_35 → 5,586,483 (−6.9% vs v1), prob_36 → 407,802 (−3.3%), prob_13
  win preserved (119,955, −56%).

## 4. Proven results (all via official checker, local M-series Mac, /opt/anaconda3 python + shapely 2.0.7)

- **40-instance sweep @60 s, v1 vs v2**: 23 wins / 15 ties / 2 regressions (both since fixed in v2.1),
  0 infeasible, total objective 254.75M → 247.02M (−3.0%). Set-1 (loose): obj1=0 everywhere except
  prob_20 (5 tardy days); huge wins from preference repatriation + tardiness kills (prob_13: 4→0 tardy
  days, −52%; prob_14: 7→0, −65%; prob_1: 8,847→1,499 which EQUALS the assignment-only theoretical floor).
  v2 correctly trades cheap imbalance (w2≈4–10) for expensive preference/tardiness.
- **120 s probes**: prob_1 = 1,499 (provable floor), prob_9 = 50,885, prob_25 = 351,265 (unchanged —
  capacity-bound). Organizer baseline: 795k / 2.36M / 824k. Best public 2026 competitor (etharthinas):
  151k / 106k / ~898k. We beat every measurable artifact.
- **Edge battery** (running now, partial): solo re-runs green; pending: n=600 stress, m=1, non-contiguous
  orientation IDs (an explicit FAQ trap), w1=0, w2-dominant, n=5, zero-slack, time limits 10/21/30 s,
  600 s soak with peak-RSS sampling. One known gap: portfolio only tested under macOS spawn; server uses
  Linux fork (safer primitive + clean fall-through to single-process, but untested in Docker yet).

## 5. Intelligence (from a 16-agent orchestrated recon; integrity rule 5.3: prior-edition open-source code
   = adapt WITH citation; current-2026 competitor repos = ideas only, NEVER copy)

- Leaderboard is public JSON: https://d32m8h9cownzsg.cloudfront.net/public/leaderboard_group/latest.json
  (400 teams, 39 tiers, scores hidden). Tier 1: tishii24 (AtCoder elite, expect compiled Rust annealer),
  古法编程, ChatOPT, OPTALL, etc. Qampo (professional DK optimization firm) only Tier 3 — the field is
  beatable.
- OGC 2024/2025 finalist code is officially open-sourced (github.com/ogchallenge/ogc releases). The 2024
  winner (DMS): thin Python → pybind11 C++ ALNS ⇄ Gurobi set-partitioning, per-instance time tables,
  SPARE_TIME clock paranoia. 2025 problem (RoRo stowage with port-LIFO) is a structural cousin — their
  finalists' code is legal study material.
- Organizer DNA: the crane-lift/overhang tier is the designed differentiator (Woo lab: crane-LIFO +
  nesting; K. Lee/Joung: knapsack/IP). Instance-generation writeups get published post-competition.
- Full research corpus lives in `research/` (checker rules audit with line refs, 40-instance analytics,
  4 literature sweeps, 3 solver designs + judge synthesis "KEEL", action plan).

## 6. The known ceiling and the next big lever

v1/v2's union-footprint invariant FORFEITS: (a) same-layer-disjoint packings where different layers overlap
in plan view, (b) deliberate overhangs (35% of multi-layer blocks are "mushrooms"; median bbox fill 0.67).
The congested instances (prob_25/27/33/38/40, peak space-time demand up to 1.61× bay area) are exactly
where our remaining objective sits (90%+ tardiness) and where the union invariant caps packing density.
**The layer-true predicate task** (full spec: `submission/TASK-layer-true-predicate.md`) replaces it with
exact per-layer + crane j≥k semantics + EXIT-monotone overhang rule (strict exit_N < exit_E first
iteration). NON-NEGOTIABLE GATE: differential test vs utils.py with ZERO false-accepts on ≥10⁴
near-contact placements, then full 40-instance sweep beating v2.1 totals. Target: Slot B or finals.

## 7. Remaining backlog (from the judged action plan, by value/effort)

5. Cross-bay rebalancing ops regime-gated by weights (preference-repatriation for tardy blocks; Z2-swap
   for w2-heavy instances p25/p36/p40-like) — "bay-assignment myopia" is the known open lever nobody
   public has built.
6. Congestion-adaptive destroy sizing; elite restart pool instead of full-reconstruction kicks.
7. Local lower-bound harness (assignment-only floor; merged-bay EDD tardiness LB) to direct tuning.
8. Permanent submission gate = 40 instances × {30, 60, 120, 300, 600} s × 2 seeds + edge battery.
9. Fail-fast geometry surrogates (inner-circle/pier prechecks), profiling-gated.
10. Finals bets (pick ≤2, VOI-gated): numba bit-raster kernel; overlap-tolerant separation for
    over-subscribed instances (peak demand >110%); bounded Gurobi/CP-SAT assignment seed.

## 8. What a better prompt/roadmap should optimize (suggested asks for the AI reading this)

- Attack the layer-true predicate design: is the strict EXIT-monotone rule leaving too much on the table?
  Is there a cheap sound relaxation for same-day exit ties (roof-first emission ordering)?
- Congested-instance strategy: with peak demand >100% (prob_27: 119%), which blocks to sacrifice
  (delay far) and how to choose them — a Lagrangian/knapsack view of "who eats the tardiness"?
- Portfolio composition: with 4 workers, what's the optimal variant mix (legacy/explorer/rect-biased/
  congestion-specialist) per regime (loose/congested/preference-locked/w2-heavy)?
- Risk review of the multiprocessing parent (queue semantics, terminate-at-deadline, fork vs spawn).
- Time-limit adaptivity: 2025 finals had a 30 s instance; what should be cut first under 30 s with n=300?

## 9. File map (local repo `/Users/vedantmoghe/Downloads/optichallenge/`)

- `submission/myalgorithm.py` — v2.1 (current); `myalgorithm_v1_backup.py` — v1; `ogc2026_kestrel_v2.zip`
  — needs rebuild to v2.1 after battery passes; `TASK-layer-true-predicate.md` — GPT-5.6 task spec.
- `STRATEGY.md` — full KEEL strategy; `HANDOFF.md` — this file; `research/00–14` — all agent reports;
  `reference-ogc2024-winner/` — 2024 winner code+slides; `ogc2026/baseline/utils.py` — official checker
  (ground truth); training instances in `train 2/` (prob_1–20, loose) and `train/` (prob_21–40, congested).
