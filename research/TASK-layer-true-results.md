# Layer-true predicate task — measured result

Date: 2026-07-27

## Correctness result

The checker semantics were implemented as a pairwise event predicate:

- same-index layers only for static co-presence;
- asymmetric `moving layer k` versus `existing layer j >= k` crane checks;
- exact replay of the emitted pair events, ordered by
  `(day, EXIT-before-ENTRY, block_id)`;
- both forward and reverse crane directions, so inserting a block earlier than
  an already scheduled block remains sound.

Differential test:

```text
10 instances × 10,000 near-contact placements = 100,000
false accepts = 0
false rejects = 0
```

Evidence: `research/layer_true_differential_100k.log`.

The test clears the solver's identity-keyed geometry caches between instances,
matching the production `_solve` lifecycle. Without that reset, CPython object
ID reuse can create a harness-only stale-cache verdict.

## Performance/value result

The exact predicate was optimized by testing necessary same-layer legality
first. On `prob_25`, a full layer-aware mode-0 construction improved from about
104 seconds to 52 seconds, but its objective was 399,039 versus the frozen v2
union solver's 351,265. Other generic priority modes were also worse or failed
to finish in 65 seconds. Layer-contact generation increased cost further.

Single-block and coordinated ruin/recreate probes from the 351,265 incumbent
found no improving layer-aware move in their bounded tests.

Decision: **do not activate layer-true search in Slot B.** Correctness passed,
but the required objective/value gate did not. The code remains in the working
copy for future candidate-generation research; production keeps the proven
union-envelope invariant.

## Improvement that did pass

The investigation showed that loose instances were assignment-cost bound, not
geometry bound. A one-thread, time-capped Gurobi master now solves exact bay
preference regret plus scaled workload imbalance, then hands the assignment to
the unchanged geometric decoder and repair search.

The master is data-gated (`n <= 200`, release-peak density `<= 0.49`, time limit
at least 8 seconds), runs only in portfolio worker 0, and cannot promote a
candidate without both a lower full objective and an official checker pass.
Import/licence/solve failures fall through to the original solver.

Real 4-worker, 60-second results:

| Instance | Frozen v2 | Slot B | Tardiness | Status |
|---|---:|---:|---:|---|
| prob_1 | 8,847 | **1,499** | 0 | feasible |
| prob_9 | 68,550 | **50,885** | 0 | feasible |
| prob_25 | 351,265 | **351,265** | 472 | feasible |

The `prob_25` control confirms that the congested path is unchanged.
