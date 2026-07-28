# T1 LNS current probe — NOT A PROMOTION GATE

Date: 2026-07-27  
Baseline: `f116296`, single-process `_solve`, variant 1  
Candidate: uncommitted `experiments/myalgorithm_lns_prototype.py`  
Protocol: sequential existing then advanced arm; official-checker objectives.

This file records the post-review prototype, after blame was widened to the
full `[release, entry)` waiting window, destruction was fixed at 15–30 blocks,
and LAHC memory was scaled to 50–300. It supersedes neither the append-only
project logs nor the required paired portfolio gate.

| instance | limit | existing | advanced | delta | feasibility |
|---|---:|---:|---:|---:|---|
| prob_33 | 10 s | 18,307,403 | 18,874,763 | +3.10% | true / true |
| prob_33 | 30 s | 16,807,377 | 16,558,333 | −1.48% | true / true |

The 30-second advanced arm completed two large-neighborhood moves:

- destroy sizes: 15–16 blocks, 46 removals over three proposals;
- completed / accepted: 2 / 2 (100% among completed moves);
- direct large-neighborhood gain: 611,125 objective units;
- direct improvement rate: 74,310 objective units per LNS-second;
- retained legacy polish gain: 2,843,382;
- retained legacy ruin/recreate gain: 456,142;
- official checker: feasible, no violations.

The 10-second arm completed no large repair and was worse. Therefore the
activation rule must reserve enough time for at least one full regret repair;
the short-budget result is a rejection of unconditional activation, not a gate
verdict on T1.

Late acceptance itself remains unproven in this sample: both completed moves
were improving. Worker 1 has the LAHC policy; workers 0, 2, and 3 retain their
legacy paths so the portfolio does not discard two previously productive arms.

An earlier full-portfolio screen that replaced both workers 1 and 2 failed:
prob_27 regressed 3.59% and the four-instance aggregate regressed 0.92%.
That failure established that one unchanged worker is only a feasibility
anchor, not an objective guarantee against the old four-worker portfolio. The
current one-worker activation is the correction and requires a fresh screen.

## Full-portfolio timing diagnosis

The local 30-second screen was not stable enough for a quality verdict:

| dataset | baseline prob_27 | candidate prob_27 | observation |
|---|---:|---:|---|
| `lns_screen_4x30_current` | 35,113,516 | 36,373,424 | initial two-worker failure |
| `lns_screen_4x30_one_worker` | 35,113,516 | 36,373,424 | disabled hot path still had metric overhead |
| `lns_screen_p27_30_hotpath` | 35,113,516 | 51,727,606 | candidate missed near-deadline exact result |
| `lns_screen_p27_30_trace` | 51,727,606 | 53,131,603 | baseline itself degraded 47% versus earlier runs |

The current disabled hot path ties exactly on prob_27 at 10 seconds
(`lns_screen_p27_10_hotpath`). The trace dataset confirms candidate queue
messages are arriving; its best delivered worker value was 53,131,603.
Because the baseline changed from 35,113,516 to 51,727,606 under the nominally
same 30-second command, these later runs demonstrate machine/timing drift and
cannot decide T1. No binding gate was started.

Queue tracing was enabled only for the diagnostic dataset and confirmed normal
arrival order. The prototype retains the hardened baseline's throttled queue
behavior; no unmeasured IPC policy change is included in T1.
