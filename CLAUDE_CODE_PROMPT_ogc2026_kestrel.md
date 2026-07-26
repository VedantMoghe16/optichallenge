# CLAUDE CODE MISSION BRIEF — OGC 2026 "Kestrel" solver
## Preliminary endgame (now → 2026-07-28 12:00 KST) + finals runway

You are Claude Code working in the repo at `/Users/vedantmoghe/Downloads/optichallenge/`.
This brief was assembled on 2026-07-27 with external facts re-verified against live sources
(§7). Treat everything in §2 and §7 as verified; treat everything marked UNVERIFIED as an
assumption to be tested, never relied on.

Your single most important property is **discipline under a clock**. The preliminary round of
this competition ends tomorrow. A worse-but-newer submission replaces a better older one. A
crash or infeasible output scores −1 per hidden instance. The winning behavior is: small
verified increments, hard gates, and shipping the *safest strictly-better* build — never the
newest.

---

## 0. ORIENT FIRST (~20 min, before writing any code)

Read in this order:

1. `HANDOFF.md` — complete state of work. This is your primary context.
2. `STRATEGY.md` §0–§2 — the three structural theorems (assignment decomposition; crane rule =
   interval-nesting forest; guaranteed feasibility via serialization).
3. `submission/TASK-layer-true-predicate.md` — the spec for the highest-value pending task.
4. `submission/myalgorithm.py` (v2.1, ~1,040 lines) — current solver. Key internals:
   `algorithm(prob_info, timelimit=60)` entry point → 4-process portfolio with a streaming
   result queue → fall-through to single-process `_solve` on any failure; `_official_check`
   gates every incumbent promotion; `_ruin_recreate(..., legacy=True)` on worker 0 reproduces
   v1's exact destroy/repair schedule so the portfolio can never search worse than v1.
5. `submission/myalgorithm_v1_backup.py` (v1, ~828 lines) — the proven baseline. READ-ONLY.
6. `ogc2026/baseline/utils.py` — the official checker. **Ground truth. READ-ONLY. Never edit,
   never ship, never "fix".** If your code and the checker disagree, your code is wrong.
7. Skim `research/00–14` and `reference-ogc2024-winner/` (2024 winner: thin Python driving a
   pybind11 C++ ALNS ⇄ Gurobi set-partitioning loop; note their per-instance time tables and
   SPARE_TIME clock paranoia — that discipline is the pattern to copy, not the C++).

Then run `date` and compute hours remaining to each deadline in §2. Every plan you produce must
state its time box and what gets cut if the box is exceeded.

If the repo is not already under git: `git init`, commit everything, and tag `v2.1-frozen`
before touching a single file. If it is under git, tag the current state `v2.1-frozen` now.
Every experiment references a SHA.

---

## 1. MISSION, HONESTLY FRAMED

- **Primary (must-have):** finish the preliminary in the top 30–40 and advance to the final
  round (Aug 3–14), with **zero risk of −1** on any hidden instance. This is achieved by a
  server-parity-tested v2.1 or better.
- **Secondary (high-value, gated):** land the layer-true predicate (§4-P1) into the Slot B
  submission **only if both of its gates pass**. If gates aren't green in time, it ships in
  the finals instead — that is a fine outcome.
- **Rank-1 is a finals objective.** The rank-1 path runs through the finals phase (new
  instances, longer runway, Technical Report). Nothing you do today may gamble the primary
  objective for it. Your job today is to secure advancement and build the runway: parity
  harness, gate infrastructure, predicate groundwork, and clean experiment logs.

---

## 2. IMMOVABLE FACTS (externally verified 2026-07-27; sources in §7)

- **Deadlines (KST = UTC+9; IST in parens):** Preliminary closes **Tue 2026-07-28 14:00 KST
  (10:30 IST)**. Final round Aug 3 14:00 KST → Aug 14 14:00 KST. Awards Sep 4. Team's internal
  target: Slot B submission email sent by **~12:00 KST (08:30 IST) tomorrow** for buffer.
- **Submission mechanics (per team's verified handoff):** ONE zip, `myalgorithm.py` at root,
  ≤15 MB, never include `utils.py`, sent to submission@optichallenge.com from the registered
  team email. **12-hour cooldown. The latest accepted submission always replaces the previous
  one — even if it is worse.** Remaining slots treated as: Slot A today, Slot B tomorrow
  morning, Slot B only if strictly better on the full gate.
- **Scoring:** per hidden instance, rank-based; **infeasible / crash / timeout = −1**
  (catastrophic). Currently 6 hidden instances P1–P6, possibly augmented later. Dashboard:
  P3 hardest (15 teams infeasible, 5 crash), P6 crash-prone (11 crashes). Time limits span
  "tens of seconds to tens of minutes"; 2025 finals precedent includes a 30 s instance.
- **Server:** Ubuntu 24.04, 4 CPU cores (firejail/cpulimit **throttling, not kill**), 16 GB
  RAM, Python 3.12 conda, shapely **2.1.2**, gurobipy 13 licensed, **no internet**. Local dev
  so far: macOS, shapely **2.0.7**, spawn-based multiprocessing. Server uses Linux **fork**.
  This mismatch is the #1 unretired risk (§4-P0).
- **The stakes are real and the failure mode is real.** The live leaderboard
  (fetched 2026-07-26 22:00 UTC snapshot) shows team "MSS" at tier 2 for six days, then
  36→36 in the final window, and "A17" going 4→29. Cause unknowable from outside (bad final
  submission or crash on hidden instances), but it is exactly the failure mode the
  replace-even-if-worse rule + −1 scoring produces. The Slot B protocol (§5) exists to make
  that outcome impossible for this team.
- **Finalist code + Technical Reports are published as open source after the competition, and
  awards can be revoked for plagiarism.** Two consequences: (a) the integrity rule is
  enforceable — prior-edition (2024/2025) open-sourced code may be adapted **with citation**;
  2026 competitor material is **ideas only, never copy**; (b) every design decision you log in
  `DECISIONS.md` (§6) is a direct input to a *required* finals deliverable. Write it as if it
  will be published, because it will be.

---

## 3. NON-NEGOTIABLE OPERATING RULES

1. `utils.py` is ground truth and read-only. So are `myalgorithm_v1_backup.py`,
   `reference-ogc2024-winner/`, and the training instance directories (`train/`, `train 2/`).
2. **Never promote an incumbent that hasn't passed the bundled official checker.** The
   invariant chain must survive every change: checker-verified serial fallback established
   first → every promotion checker-verified → deadline reserve honored → global try/except
   returns the last verified incumbent → `algorithm()` never raises, never returns infeasible.
3. **All new behavior lives behind feature flags** (module-level constants or env-var reads at
   import, defaulting OFF). The v2.1 code path must remain byte-recoverable via
   `git diff v2.1-frozen` at all times.
4. The worker-0 `legacy=True` guarantee (portfolio can never search worse than v1) stays
   unless a full gate run proves a replacement strictly dominates it.
5. Wall-clock discipline everywhere: `time.monotonic()`, deadline reserve ≥4%, margins before
   the hard limit (the 2024 winner's SPARE_TIME paranoia is the model). Remember cpulimit
   *throttles* — wall clock and CPU time diverge; budget on wall clock only.
6. Determinism per (seed, flagset) wherever feasible; log seeds with every result.
7. Time boxes are binding. If a task blows its box without passing its gate: stop, revert to
   the tag, log the failure in `DECISIONS.md`, move down the priority list. No sunk-cost
   continuation.
8. Ask the human before anything irreversible outside the repo (you never send the submission
   email; you produce the zip + a ship/no-ship recommendation and stop).

---

## 4. WORKPLAN (strict priority order; each item has a gate)

### P0 — Server-parity battery under Docker  ⏱ box: 3–4 h  🚦 gate: green before ANY slot decision

The solver has never run under the server's actual primitives (Linux fork, shapely 2.1.2,
Python 3.12). Close that gap first.

1. Write `docker/Dockerfile.server-parity`: `ubuntu:24.04` + Python 3.12 (conda or deadsnakes —
   match the conda claim if practical) + `shapely==2.1.2` + numpy + the bundled checker. 4-CPU,
   16 GB limits via `docker run --cpus=4 --memory=16g`.
2. Port the existing edge battery into it and finish the pending cells from `HANDOFF.md` §4:
   n=600 stress, m=1, **non-contiguous orientation IDs** (explicit FAQ trap), w1=0,
   w2-dominant, n=5, zero-slack, timelimit ∈ {10, 21, 30, 60}, and a 600 s soak with peak-RSS
   sampling per process (4 workers each hold their own geometry caches — check ×4 memory).
3. Fork-semantics risk review (produce a short memo with a verdict per item):
   - default `mp.get_context()` on Linux = fork; parent must be effectively single-threaded at
     fork time (verify no threads started before `Process.start()`; note `Queue`'s feeder
     thread spawns lazily on first `put` *per process* — parent never puts, so OK; confirm).
   - `terminate()` on a child mid-`put` can tear a message or leave the writer lock held.
     Confirm the parent's read path survives: main `get` loop catches Exception and continues;
     drain loop breaks on Exception. Add a battery case that SIGKILLs one worker mid-run and
     asserts the parent still returns a verified solution.
   - firejail-like restriction can break `multiprocessing` entirely (POSIX semaphores need
     /dev/shm). The code's fall-through on `Queue()` creation covers total failure — also test
     *partial* failure: monkeypatch `Queue.get` to raise after workers start and assert the
     single-process fallback still returns a feasible solution within budget.
   - edge math at `limit=20.0` and `n_blocks=8` boundaries (`child_budget`, `collect_margin`,
     `hard_end`) — assert no negative/zero budgets.
4. Re-run the two fixed regressions solo (prob_35, prob_36) inside the container to confirm
   the v2.1 numbers reproduce under shapely 2.1.2 (GEOS version differs from local 2.0.7 —
   near-contact predicates must agree; if any 40-instance objective or feasibility flips
   between shapely versions, STOP and escalate to the human immediately).

**Acceptance:** 0 crashes, 0 infeasible, RSS comfortably < 16 GB total under n=600 soak,
kill-at-deadline still returns best-so-far, all battery cells green **inside the container**.
On green → rebuild the Slot A zip (§5) from `v2.1-frozen` and recommend sending it today.

### P1 — Layer-true feasibility predicate (flag: `KESTREL_LAYER_TRUE`)  ⏱ box: 6–8 h  🚦 two gates

The known ceiling: v1/v2's union-footprint invariant forfeits same-layer-disjoint packings
that overlap in plan view, and all deliberate overhangs (35% of multi-layer blocks are
"mushrooms", median bbox fill 0.67). The congested instances (prob_25/27/33/38/40, peak
space-time demand up to 1.61× bay area) hold 90%+ of the remaining objective. Implement per
`submission/TASK-layer-true-predicate.md`: exact per-layer disjointness + crane j≥k clearance
at every co-present block's ENTRY/EXIT + EXIT-monotone overhang (strict `exit_N < exit_E`
first iteration), honoring the checker's same-day order (all EXITs then ENTRYs, in our listed
operation order).

- **GATE L1 (differential, zero-tolerance):** ≥10⁴ adversarial placements checked against
  `utils.py` with **ZERO false-accepts** (predicate says legal, checker says illegal).
  False-rejects are allowed but measured and reported. The corpus generator must cover:
  ±1-integer near-contact at every layer pairing, edge-contact-legal cases, plan-view overlap
  with disjoint layers, mushrooms overhanging shorter blocks (enter-later/exit-earlier and
  every violation of it), same-day entry/exit ties in both emission orders, and blocks with
  non-contiguous orientation IDs. **Run L1 under shapely 2.1.2 in the container** — a gate
  passed only under local 2.0.7 does not count.
- **GATE L2 (value):** full 40-instance sweep, 60 s × 2 seeds, in-container. Must beat the
  v2.1 total, no single instance worse by >2%, 0 infeasible. Wins are expected specifically on
  the congested set; if totals improve but congested instances don't move, report that honestly
  — it changes the finals plan.
- Performance: the predicate sits in the hot loop. Keep the pairwise verdict cache but key it
  with a layer-signature so cached union-verdicts can't leak into layer-true mode; add per-layer
  bbox prefilters before any shapely call.
- **Hypothesis H1 (from HANDOFF §8), test before designing around it:** with same-day exit
  ties, is `exit_N ≤ exit_E` legal when N's exit is emitted before E's ("roof-first" ordering)?
  Answer empirically with checker experiments, not by reading intent into the spec. If true,
  it widens legal nestings for free; if false, keep strict inequality.
- **Fallback rule:** if L1 or L2 is not green by **T-6h before the Slot B email**, freeze the
  flag OFF, ship v2.1 (or best gated build), and carry the predicate to finals. Log why.

### P2 — Cross-bay rebalancing operators (regime-gated)  ⏱ box: 3–4 h  🚦 gate: same 40-instance rule

STRATEGY theorem 1 makes the assignment dimension exactly searchable: Z2+Z3 deltas for any
cross-bay move are O(1) and geometry-free. Build two moves on workers 1–3 only (worker 0 stays
legacy): (a) preference-repatriation for blocks paying tardiness or regret in their current
bay; (b) Z2-balancing swaps, activated only when weight vector is w2-heavy (p25/p36/p40-like
regimes). Handoff calls "bay-assignment myopia" the open lever nobody public has built — this
is the differentiated finals bet, and any preliminary gain is a bonus. Gate identically to L2.

### P3 — Congestion triage (only if P0–P2 land with slack)  ⏱ box: 2–3 h

For instances with peak space-time demand >100% (prob_27: 119%), someone must eat tardiness.
Frame the sacrifice choice at the assignment level: a knapsack/Lagrangian view choosing which
blocks to delay far, priced by w1·(days) against the space-time they free in the peak window;
use the merged-bay EDD tardiness lower bound as the pricing oracle. Prototype offline first
(analysis notebook against prob_25/27), integrate only with a gate pass.

### P4 — Finals infrastructure (fills any remaining time; never blocks Slot B)

- Permanent submission gate = 40 instances × {30, 60, 120, 300, 600} s × 2 seeds + battery.
- Lower-bound harness: assignment-only floor (prob_1's 1,499 is already provably tight) +
  merged-bay EDD LB, reported next to every sweep so tuning effort goes where gap exists.
- 30 s / n=300 degradation ladder: measure, then codify what gets cut first as `timelimit`
  shrinks (portfolio → single-process is already automatic below 20 s; decide the next rungs —
  exact-polygon construction? R&R destroy size? candidate density?) and encode as a per-limit
  config table, 2024-winner style.
- Defensive-import speed kernels (numba, gurobipy seeds) are finals bets: structure any use as
  `try: import … except ImportError: fallback` so server availability is a bonus, never a
  dependency. UNVERIFIED whether numba exists on the server; do not bet a submission on it.

---

## 5. SLOT DECISION PROTOCOL (run the checklist verbatim; you recommend, the human sends)

**Slot A (today):** after P0 green — rebuild `ogc2026_kestrel_v2.zip` at `v2.1-frozen`,
run the checklist, recommend sending. Purpose: lock a parity-tested safe baseline on the board.

**Slot B (tomorrow, email out by ~12:00 KST / 08:30 IST):** submit **iff** the candidate build
beats the Slot A build on the *full* gate (40 × 60 s × 2 seeds minimum; wider if time) with
0 infeasible AND its battery is green in-container. Otherwise re-send nothing — Slot A stands.
The leaderboard's MSS example is what ignoring this rule looks like.

**Zip checklist (both slots):**
1. Build from a clean `git archive`/checkout of the exact tagged SHA, not the working tree.
2. `zipinfo`: `myalgorithm.py` at zip root; no `utils.py`; no cache/test artifacts; ≤15 MB.
3. Byte-compare the zipped `myalgorithm.py` against the tag.
4. Fresh-container smoke: unzip into an empty dir inside the parity image, run three instances
   (one loose, one congested, one tiny n=5) at 30 s and 60 s, checker-verify every output,
   confirm return type/shape (`{"operations": …}`) exactly matches what `utils.py` consumes.
5. Record zip SHA-256 in `RESULTS.md` next to the gate table it shipped with.

---

## 6. REPORTING (this doubles as the finals Technical Report substrate)

- `RESULTS.md` — append-only: timestamp, git SHA, flagset, seeds, per-instance table, totals,
  delta vs v2.1, gate verdict.
- `DECISIONS.md` — one short entry per gate outcome or reverted attempt: what, why, evidence.
- End of every working session, print for the human: what changed / gate outcomes / current
  ship recommendation / top 3 risks / hours to deadline.

---

## 7. VERIFIED EXTERNAL CONTEXT (fetched 2026-07-27 — use, don't re-litigate)

**Competition (public record):**
- Official: optichallenge.com. Devpost mirror confirms: hosted by LG CNS + the Korean
  Institute of Industrial Engineers (KIIE); "The Grand Shipyard Puzzle: Pack the Block, Beat
  the Clock"; Preliminary June 15 → **July 28, both 14:00 KST**; Final Aug 3–14; awards Sep 4;
  ~KRW 200M (~$130k) pool, winner ~$45–48k; any methodology allowed; **finalist code +
  Technical Reports released as open source; plagiarism → award revocation.**
  https://ogc2026.devpost.com/ · https://internshala.com/competitions/optimization-grandchallenge-2026-2/ ·
  https://www.prnewswire.com/news-releases/lg-cns-hosts-optimization-grand-challenge-2026-to-tackle-real-world-industrial-challenges-using-mathematics-302793879.html
  (Note: HANDOFF names SNU as co-host; the public record says KIIE. Immaterial to strategy;
  flagged for accuracy.)
- **Leaderboard JSON is live and machine-readable:**
  `https://d32m8h9cownzsg.cloudfront.net/public/leaderboard_group/latest.json`
  (~280 teams listed, 39 tiers, no scores exposed, 7-day tier history per team). Confirmed
  tier-1 residents incl. tishii24, 古法编程, ChatOPT, OPTALL; Qampo (professional DK firm) at
  tier 3 — the field is beatable. You (Claude Code) have no internet in the solver, but the
  human can poll this locally; a tiny `scripts/poll_leaderboard.py` that diffs tier movements
  of ~10 tracked rivals is a cheap, worthwhile P4 add.

**Literature (verified to exist; adapt ideas freely — these are published papers, cite in the
Technical Report):**
- Two-stage "dispatching priority rules + diagonal-fill placement" for shipyard block spatial
  scheduling, with a MIP reference model — validates Kestrel's multi-start priority-rule
  construction and gives a named placement alternative to test.
  https://www.sciencedirect.com/science/article/abs/pii/S0360835215002296
- Largest-contact-area placement policy (Koh et al., 2008 lineage) — Kestrel's contact-candidate
  scoring is this idea; the paper's variants are cheap A/B candidates.
- BLF + differential evolution searching *block sequence and orientation* with a placement
  decoder (Shin, Kwon & Ryu 2008, Production Planning & Control 19(6)) — direct precedent for
  the KEEL decoder-repair architecture.
  https://www.tandfonline.com/doi/abs/10.1080/09537280802474941
- Best-Contact allocation for time-constrained 3D packing view of BSS (Shang et al. 2017).
  https://www.hindawi.com/journals/mpe/2017/1923646/
- Irregular-block spatial scheduling with placeable-area computation (Lee et al. 1996 lineage;
  CAIE 2020). https://www.sciencedirect.com/science/article/abs/pii/S0360835220306550
- Tight MIP formulation for mega-block spatial scheduling (Ahn & Kim 2022, JSPD 38:193–198) —
  precedent for the P4 lower-bound harness.
  https://onepetro.org/JSPD/article-abstract/38/04/193/493575/
- Gap check: none of the public BSS literature surfaced handles the crane j≥k layered-overhang
  rule — consistent with the team's audit that this tier is the organizers' designed
  differentiator and Kestrel's novelty core. Treat the layer-true predicate as unpublished
  territory: trust only the checker.

**Could NOT be independently verified (treat accordingly):**
- `github.com/ogchallenge/ogc` did not surface in search. Use the local
  `reference-ogc2024-winner/` copy as the 2024/2025 study material; do not fetch.
- No public 2026 competitor solution repos surfaced. If the human supplies any, the integrity
  rule applies: **ideas only, never copy, and note the exposure in DECISIONS.md.**
- Hidden-instance count/limits beyond the dashboard, and server package set beyond
  {python 3.12, shapely 2.1.2, gurobipy 13}. Defensive imports for everything else.

---

## 8. QUESTIONS TO ANSWER WITH EVIDENCE (from HANDOFF §8, priority order)

1. H1 same-day exit-tie relaxation (design + run the checker experiment; §4-P1).
2. Multiprocessing risk memo with per-item verdicts (§4-P0.3).
3. The 30 s / n=300 degradation ladder: measured cut order + per-limit config table (§4-P4).
4. Portfolio composition per regime (legacy / explorer / rect-biased / congestion-specialist) —
   only after P2 exists; answer with sweep data, not intuition.

---

## FINAL INSTRUCTION

Prefer boring correctness over clever speed. When a gate and the clock conflict, the gate
decides *what* can ship and the clock decides *whether* it ships — never let hope substitute
for a green gate. Ship the safest strictly-better build. Never the newest.
