# TEAM HANDOFF — OGC 2026 "Kestrel" (updated 2026-07-27 22:15 KST)

*This replaces the pre-submission handoff (see git history for the old one).
Everything below is either measured in this repo or cited; the evidence ledgers
are `RESULTS.md`, `DECISIONS.md`, `FINDINGS-finals.md`.*

---

## 0. TL;DR and the one live decision

- **Preliminary submission is IN and safe**: `submission/ogc2026_kestrel_v22.zip`
  (SHA-256 `d9e581d8bdee3279818f4402b8122d6858ff5444014be528a404c492d95db96a`),
  emailed ~13:45 KST 2026-07-27, built from git tag `v2.2-slotA`.
- **CORRECTED TIMELINE (a scripting bug earlier reported the close a day early):**
  preliminary closes **2026-07-28 14:00 KST** (~16 h from this writing); finals
  run **Aug 3 14:00 → Aug 14 14:00 KST**; top 30–40 teams advance; awards Sep 4.
- **Live decision:** the 12 h cooldown ends ~01:45 KST tonight, so ONE more
  preliminary submission is possible before the close. Standing rule (do not
  break it): submit only a build that beats v2.2 on the FULL gate ladder
  (40-instance paired sweep + edge battery + container parity). No current
  build qualifies: the "hardened" build passed the 40-gate (quality-neutral,
  +0.09%) but has not been container-verified; the raster build is not fully
  gated. **Default: let v2.2 stand.** If you finish P0 of `CODEX-PLAN-finals.md`
  tonight AND it clears the full ladder by ~10:00 KST, that is the only
  legitimate use of the slot. Remember: the newest accepted submission REPLACES
  the old one even if worse — teams MSS (2→36) and A17 (4→29) died exactly there.

## 1. Competition facts (verified against the live site + official checker code)

- Problem: n (100–300) irregular multi-layer polygonal blocks → m (2–5)
  rectangular bays; choose bay, integer (x, y), orientation, ENTRY/EXIT days.
  Constraints: containment; same-layer-index interior-disjointness among
  co-present blocks; vertical crane rule (layer k must clear co-present layers
  j ≥ k at ENTRY/EXIT); per day all EXITs execute before all ENTRYs, in our
  listed order. Objective: `w1·tardiness + w2·workload_imbalance +
  w3·preference_regret`, w1 dominant (667–29,630/day).
- `ogc2026/baseline/utils.py` = the official checker = ground truth. Read-only.
- Server: Ubuntu 24.04, Python 3.12, shapely 2.1.2, 4 cores (cpulimit
  *throttling*), 16 GB, gurobipy 13 LICENSED + xpress + ortools, no internet.
  Time limits 30 s–30 min (2025 finals precedent: 14 instances, 30–600 s).
- Submission: email ONE zip to submission@optichallenge.com from the registered
  team address; `myalgorithm.py` at zip root; ≤ 15 MB; never include utils.py;
  12 h cooldown; infeasible/crash/timeout = **−1 per instance** (catastrophic
  under rank scoring).
- Public intel: leaderboard JSON (no auth):
  `https://d32m8h9cownzsg.cloudfront.net/public/leaderboard_group/latest.json`
  (`scripts/poll_leaderboard.py` diffs a watchlist). Hidden set currently
  P1–P6, may be augmented in finals. Prior-edition finalist code is officially
  open-sourced (adapt WITH citation): local copy `reference-ogc2024-winner/`.
  Current-2026 competitor repos are IDEAS ONLY — copying = plagiarism =
  award revocation (rule 5.3).

## 2. What was built (version history, all objectives via the official checker)

| build | what | evidence |
|---|---|---|
| v1 "kestrel" | GPT-5.6 Codex original: anytime heuristic, union-of-layers safety invariant, checker-gated promotions, never-infeasible fallback chain | beat organizer baseline ~20×; beat best public competitor 1.5–19× |
| v2 | + 4-process portfolio (diversified seeds/mode-orders, streamed incumbents), pairwise-verdict cache (relative displacement), delta-objective sweep, peak-window-flush destroy | 40-sweep: 23 wins / 15 ties / 2 regressions vs v1, −3.0% total |
| v2.1 | worker 0 pinned to v1's exact legacy schedule ⇒ portfolio can never search worse than v1 | both regressions flipped to wins (prob_35 −6.9%, prob_36 −3.3%) |
| **v2.2 = SHIPPED** | + mp drain-hang fix (torn-message hang after terminate → −1 class), + raw-vertex containment bbox fix (checker-exact; fuzz-found), XBAY/LAYER_TRUE dormant | full gate PASS; **parity battery in Ubuntu container 14/14**; fork kill-test PASS |
| finals branch HEAD | + audit hardening: P=0 dwell guard, degenerate-polygon proxy orientations, huge-bay grid cap, deadline-aware preprocessing (0.33 s → 0.05 s at tiny limits), env-flags → module constants | 40-gate PASS (+0.09%, quality-neutral); synthetic repros all feasible; NOT container-verified yet |

**Robustness evidence for the shipped build:** 1,420 randomized adversarial
instances across 3 fuzz lanes (incl. one under Linux fork in the parity
container) — zero failures; 1.05 M differential geometry cases — zero
false-accepts; kill-a-worker mid-run (spawn AND fork) — returns feasible;
600 s soak peak RSS 360 MB (1.4 GB under fork ×4 workers) vs 16 GB.

## 3. Post-submission finals work (the valuable stuff — all on branch `finals`)

Read `FINDINGS-finals.md` (F1–F10) in full; the headlines:

1. **Root cause of congested-set tardiness found and prototyped away.** For
   n > 160 construction packs bounding RECTANGLES: envelope occupancy 0.87 vs
   true polygon occupancy 0.44 ⇒ **38% of bay area wasted**. Exact polygon
   construction was unaffordable (> 600 s at n=250) — the new raster kernel
   (`submission/raster_kernel.py`, soundness proof in docstring, differential
   gate 0 false-accepts, batch 0.61 µs/position = 30×) brings it to **83 s**.
   Paired 240 s A/B on 4 congested instances: **−4.0% total** (prob_40 −19.7%,
   prob_33 −13.9%, prob_38 −12.3%, prob_27 +19.6% — the one over-subscribed
   instance where re-timing beats packing; a startup budget policy fixes this,
   spec'd in CODEX-PLAN P0.3).
2. **Certified lower bounds** (`tests/geometric_lb.py`, validated against 240
   checker-verified solutions, 0 violations): tardiness is 85–97% of our
   objective on ten congested instances and mostly NOT forced by physics;
   certified headroom up to 1510× (prob_23). Only prob_8 proven optimal.
   ⇒ scheduling search is the other big lever besides geometry.
3. **Dead ends closed with measurements** (don't reopen): per-layer overhang
   feasibility (0 accepts / 250,286 tests — construction order anti-correlated
   with the required exit precedence); DFF area bounds (dominated, 0.974–1.000);
   ALNS weight adaptation (0.14% per 25-implementation meta-analysis);
   monolithic MIP (1/25 feasible at 1 h in closest published analogue).
4. **Deep-research-backed implementation plan**: `CODEX-PLAN-finals.md` — P0
   raster integration + budget policy, P1 CP-SAT bay-window repair oracle
   (attacks item 2; uses the licensed solvers), P2 LAHC + big destroys +
   dynasearch, P3 squeaky-wheel blame propagation, P4 portfolio
   diversification, P5 sparrow-style overlap-tolerant separation (research
   bet), P6 Cython kernels. Expected-value table and full gate specs inside.

## 4. Discipline that must survive the handoff

1. **Measurement protocol F10:** idle machine (`pgrep`, `docker ps` first),
   paired sequential arms per instance, checker objectives only. We measured
   ~8% phantom regressions and one sign-flipped A/B caused purely by CPU
   contention. Harness: `scratchpad/bisect/paired_gate.py` pattern.
   Reference totals (paired, un-contended, 60 s): 226,420,836.
2. **Gate ladder before any submission:** 40-instance paired sweep (60 s; +240 s
   congested for construction changes) → edge battery → container parity
   (`docker/run_parity.sh`) → zip via `scripts/build_submission_zip.sh <tag>
   <name>` (byte-compares zip against the git tag) → fresh-container smoke of
   the actual zip.
3. Never edit: `utils.py`, `myalgorithm_v1_backup.py`, training instances,
   `reference-ogc2024-winner/`. Never rewrite ledgers — append.
4. macOS gotcha: any driver script that calls `algorithm()` MUST have an
   `if __name__ == "__main__":` guard (spawn re-imports it per worker;
   we process-bombed ourselves twice).

## 5. Mistakes made and corrected (so you don't re-trust stale claims)

- **Deadline off-by-one-day** (this file, §0): scripts computed the close as
  07-27 14:00; the real close is **07-28 14:00 KST**. The submission simply
  went in ~24 h early — no harm, but earlier chat urgency was wrong, and one
  more submission window exists tonight.
- **Contended gate verdicts retracted** (F10): a "+11.6% FAIL" was pure
  contention; re-run paired/idle it was +0.09% PASS.
- **"prob_1 = 1,499 is the proven floor" — RETRACTED** (RESULTS.md): the claim
  came from a heuristic estimate; the LP bound is 988. Never present it as
  proof in the technical report.
- The 30 OVERTIME files in `fuzz_failures/` are self-contention artifacts
  (window 09:19–09:39 while an external audit ran); all three worst repros pass
  solo. Kept for the record.

## 6. Jobs possibly still running / recent artifacts

- `scratchpad/bisect/full_compare.py` — full 40-instance kestrel-vs-raster
  paired comparison at 60 s and 240 s (32/60 runs done at this writing);
  results append to `COMPARISON-kestrel-vs-raster.md` §5.2. Keep the machine
  otherwise idle until it finishes, or kill it (`pkill -f full_compare`) and
  rerun later — partial results are in `scratchpad/bisect/{C,D}/fc*_prob_*.json`.
- Fuzz lanes and the L1 marathon are stopped. Docker image `ogc-parity` is
  built and ready.

## 7. File map

| path | what |
|---|---|
| `submission/myalgorithm.py` | solver, finals branch (hardened) |
| `submission/ogc2026_kestrel_v22.zip` | THE shipped artifact (from tag `v2.2-slotA`) |
| `submission/raster_kernel.py` | sound raster geometry kernel (P0 ships it) |
| `submission/myalgorithm_v1_backup.py` | v1 reference, read-only |
| `submission/TASK-layer-true-predicate.md` | historical spec (dead end — see F1) |
| `CODEX-PLAN-finals.md` | **the implementation plan — start here** |
| `FINDINGS-finals.md` / `RESULTS.md` / `DECISIONS.md` | evidence ledgers |
| `COMPARISON-kestrel-vs-raster.md` | engine comparison + improvement scope |
| `STRATEGY.md` | original KEEL strategy (context; M2 = the raster kernel) |
| `research/00–14` | 16-agent recon: rules audit (line-refs!), instance analytics, literature, leaderboard/competitor intel, action plans |
| `tests/` | `l1_differential.py`, `raster_gate.py`, `fuzz_instances.py`, `mp_robustness.py`, `lower_bounds.py`, `geometric_lb.py` |
| `docker/` | server-parity container + battery + runbook |
| `scripts/` | `build_submission_zip.sh`, `poll_leaderboard.py` |
| `scratchpad (session tmp)` | harnesses & prototypes: `bisect/paired_gate.py`, `lt_diag/myalgorithm_raster.py` (P0 prototype), `lt_diag/myalgorithm_contact.py` |
| git | branch `finals` (all work), tag `v2.2-slotA` (shipped, frozen) |

## 8. Suggested first day for the new owner

1. Read `CODEX-PLAN-finals.md` end to end (30 min). Skim FINDINGS F1–F10.
2. Let `full_compare` finish; paste its tables into
   `COMPARISON-kestrel-vs-raster.md` §5.2.
3. Implement P0 (raster port + budget policy) — the prototype is 90% of it.
   Gate per §4.2. If it clears the FULL ladder before ~10:00 KST 07-28 you may
   use tonight's submission window; otherwise bank it for finals Aug 3.
4. Then P2 (three small gated edits) and P1 (the oracle — the biggest bet).
5. Keep every result in the ledgers; the technical report for finals is
   assembled from them (finalist code + reports are published — write
   accordingly, cite the literature listed in CODEX-PLAN §9 and the
   independently-re-derived competitor-intel notes in DECISIONS.md).
