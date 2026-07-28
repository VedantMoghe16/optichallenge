# Research notes — pre-gate draft

This is an isolated draft. Move its confirmed facts into the append-only
project report only after the comparison and paired gates have completed.

## T1: blame/regret large-neighborhood search

Implemented in `myalgorithm_lns_prototype.py`:

- objective blame plus fractional propagation to blocks occupying a late
  block's bay during `[release, entry)`;
- 15–30 block related destruction using causal links, bay/time proximity,
  due/release proximity, spatial overlap, and a small random component;
- bounded regret-2 recreation with incumbent-slot reservations, which gives
  every attempted neighborhood a safe completion path;
- one LAHC worker with a 50–300 entry history; the other three workers preserve
  their legacy portfolio paths;
- exact Shapely decoding and official-checker gating before best-incumbent
  promotion;
- accepted-move rate, direct improvement/second, move deltas, completion,
  checker rejection, excursion, and restart metrics.

Current evidence is diagnostic, not promotable. On prob_33 the current
prototype is +3.10% at 10 seconds and -1.48% at 30 seconds. At 30 seconds, two
completed large moves produced 611,125 direct objective gain at about 74,310
units per LNS-second. No worsening LAHC move was accepted, so its incremental
value remains unmeasured.

The first full-portfolio screen replaced workers 1 and 2. It failed at +0.92%
over four instances because prob_27 regressed 3.59%. Although worker 0 was
unchanged, it did not preserve the best result formerly found by every other
legacy variant. The design now activates T1 only on worker 1, only for
`n >= 161` and budgets at least 25 seconds; workers 0, 2, and 3 are unchanged.
This correction needs a fresh screen before the binding gate.

Subsequent 30-second screens became timing-invalid: the baseline prob_27 result
itself moved from 35,113,516 to 51,727,606. Queue tracing showed healthy worker
messages, and a 10-second disabled-path check tied exactly. The experiment was
stopped rather than turning unstable wall-clock effects into an algorithm
claim. Re-run only after the comparison machine is genuinely idle.

Verdict: retain as an experiment and run the complete paired gate. Do not copy
it into `submission/` from these pilots.

## T2: bounded CP-SAT repair

Implemented as an optional, default-off worker:

- frees 15–25 blocks in the highest-blame bay/window;
- fixes all other intervals in that bay;
- uses integer interval variables and a cumulative layer-0-area relaxation at
  `alpha = 0.88`;
- minimizes tardiness with a small displacement tie-break;
- applies the incumbent as a hint and its tardiness as an upper bound;
- uses one CP-SAT worker and approximately 2% of remaining time, capped at two
  seconds per call;
- decodes proposed starts through exact geometry, then requires an official
  checker improvement;
- records proposals, timing improvements, decode attempts, decoded schedules,
  checker-feasible schedules, and actual improvements.

The suggested pairwise dominance precedence was deliberately not encoded as a
hard constraint. In a release-date cumulative schedule, jobs may overlap and
the single-machine implication `d_i <= d_j and p_i <= p_j` does not generally
prove that `i` must precede `j`; imposing it could delete valid improvements.

OR-Tools is absent on this workstation, so the model path has not received a
real CP-SAT pilot here. The full decode/checker funnel is covered by an
injected deterministic proposer in `tests/lns_smoke.py`. T2 remains off until
T1's binding gate establishes the heuristic baseline and the parity image
contains OR-Tools.

Verdict: implementation-ready, evidence-pending.

## T3: selective raster

The policy is isolated in `raster_selector.py`:

- `n <= 160`: legacy exact;
- above the calibrated size boundary: raster only if forced density is at most
  1.18 and remaining time is at least 1.6 times estimated pass cost;
- otherwise: rectangle construction;
- invalid/non-finite selector inputs fail closed to rectangles.

The unresolved `n=161..200` boundary is explicitly marked provisional. The
policy must not be wired into the solver until the completed comparison
contains all 120 JSON artifacts and the `FULL_COMPARE_DONE` terminator.
Integration must also make a raster miss fall through to the exact scan and
retain exact Shapely confirmation.

Verdict: policy and tests ready; selector calibration and solver integration
blocked on the final comparison rows.

## T4 triage

No T4 method has a valid measured pilot yet.

1. Dynasearch is the first follow-up after T1 because it can coordinate
   non-overlapping sequence interchanges without introducing a second
   feasibility model.
2. A matching-based cross-bay neighborhood is next, but only if exact
   re-decoding can preserve simultaneous exchange gains.
3. A time-indexed LP is more valuable initially as a congestion/pricing guide
   than as a schedule owner; the existing research warns that optimistic
   master feedback can fail to converge.
4. Overlap-tolerant separation depends on the raster boundary and is therefore
   deferred until T3 is gated.

Starting any of these before T1/T3 evidence settles would mix mechanisms and
make the measured verdict uninterpretable.
