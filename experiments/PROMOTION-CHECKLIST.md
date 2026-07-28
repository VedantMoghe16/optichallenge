# Promotion checklist for the parked algorithm work

Nothing in this checklist authorizes changing the immutable `v2.2-slotA` tag.
The active `submission/myalgorithm.py` must remain identical to the selected
baseline until every prerequisite below is satisfied.

## Comparison handoff

- final comparison log ends with `FULL_COMPARE_DONE`;
- exactly 120 result JSON files exist and retain separate Kestrel/raster arms;
- all checker verdicts are feasible;
- phase-60 and phase-240 totals plus the full prob_21–40 table are recorded;
- completed dataset commit hash is available locally.

## Infrastructure-only hardening after that commit

- replace the absolute repository path in
  `scripts/build_submission_zip.sh` with a path derived from the script;
- teach the builder to include `raster_kernel.py` and `repair_oracle.py` only
  when the selected candidate imports them, and byte-compare every included
  source against the requested Git ref;
- add SciPy and OR-Tools to the parity image before testing raster and CP-SAT;
- replace the battery's wrapper-child kill targeting with the verified
  driver-worker targeting from `docker/kill_test.sh`;
- confirm the repository remains clean before algorithm promotion.

## T1 gate

Dry-run command:

```bash
PYTHONDONTWRITEBYTECODE=1 python experiments/lns_binding_gate.py --dry-run
```

Actual gate is intentionally not started while another benchmark is active.
It runs paired baseline/candidate arms for 40 instances at 60 seconds and 20
congested instances at 240 seconds, always taking objective and feasibility
from the official checker. Required result: zero infeasible, aggregate no
worse than +0.5%, and no unexplained per-instance regression above +2%.

Promote T1 only if the binding gate passes and the congested arm shows useful
gain. Preserve worker 0 as the unchanged anchor.

## T2 gate

Only after T1 is measured:

- install OR-Tools in the parity environment and run a real oracle smoke test;
- run T1 candidate versus T1+CP-SAT using `--cp-sat`;
- report calls -> proposals -> timing-improving -> decoded ->
  checker-feasible -> accepted improvements;
- reject T2 if decode yield or improvement/second does not justify its time.

## T3 integration and gate

After the completed comparison selects the boundary:

- `n <= 160` always uses the legacy exact scan;
- raster is considered only where the old path would use rectangles;
- enforce time and forced-density guards;
- on every raster miss, fall through to legacy search;
- exact Shapely confirmation remains mandatory;
- run 30/60-second budget spot checks and the complete paired gate.

## Final promotion

- append evidence to `RESULTS.md` and decisions to `DECISIONS.md`;
- run feasibility, multiprocessing failure, container parity, and objective
  gates;
- make a reviewable commit and immutable candidate tag;
- build only with `scripts/build_submission_zip.sh <tag> <name.zip>`;
- verify ZIP root layout, hashes, imports, size, and checker feasibility;
- recommend promotion only from the tagged, fully gated artifact.

