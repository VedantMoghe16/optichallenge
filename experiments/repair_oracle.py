"""Small CP-SAT scheduling repair oracle for Kestrel.

The module is optional by design.  ``propose_starts`` imports OR-Tools lazily
and returns ``None`` on an unavailable package, model failure, or timeout, so
the main solver's verified incumbent and heuristic fallback are never
dependencies of the oracle.

Geometry is deliberately absent here.  The model is an area-cumulative
relaxation that proposes start times; ``myalgorithm.py`` must decode those
times with the exact geometry engine and accept only an official-checker
improvement.
"""

from __future__ import annotations


def available() -> bool:
    try:
        from ortools.sat.python import cp_model  # noqa: F401
        return True
    except Exception:
        return False


def propose_starts(jobs, fixed, capacity, horizon_end, time_limit, seed=0):
    """Return ``{block_id: proposed_start}`` or ``None``.

    ``jobs`` entries require: id, release, due, duration, demand, current_start.
    ``fixed`` entries require: start, duration, demand.  All values are integer.
    The incumbent starts are added as hints.  Total tardiness dominates a small
    displacement tie-break that discourages unnecessary schedule churn.
    """
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None

    if not jobs or capacity <= 0 or time_limit <= 0.0:
        return None
    try:
        model = cp_model.CpModel()
        intervals = []
        demands = []
        starts = {}
        tardies = []
        deviations = []
        incumbent_tardy = 0
        horizon_end = int(horizon_end)

        for row in fixed:
            duration = max(1, int(row["duration"]))
            start = int(row["start"])
            if start >= horizon_end or start + duration <= 0:
                continue
            interval = model.new_fixed_size_interval_var(
                start, duration, f"fixed_{len(intervals)}"
            )
            intervals.append(interval)
            demands.append(max(1, int(row["demand"])))

        for row in jobs:
            bid = int(row["id"])
            duration = max(1, int(row["duration"]))
            lo = max(0, int(row["release"]))
            hi = max(lo, horizon_end - duration)
            start = model.new_int_var(lo, hi, f"start_{bid}")
            end = model.new_int_var(
                lo + duration, horizon_end, f"end_{bid}"
            )
            model.add(end == start + duration)
            interval = model.new_interval_var(
                start, duration, end, f"interval_{bid}"
            )
            intervals.append(interval)
            demands.append(max(1, int(row["demand"])))
            starts[bid] = start

            tardy = model.new_int_var(0, horizon_end, f"tardy_{bid}")
            model.add(tardy >= end - int(row["due"]))
            tardies.append(tardy)

            delta = model.new_int_var(
                -horizon_end, horizon_end, f"delta_{bid}"
            )
            model.add(delta == start - int(row["current_start"]))
            deviation = model.new_int_var(
                0, horizon_end, f"deviation_{bid}"
            )
            model.add_abs_equality(deviation, delta)
            deviations.append(deviation)
            model.add_hint(start, int(row["current_start"]))
            incumbent_tardy += max(
                0,
                int(row["current_start"]) + duration - int(row["due"]),
            )

        model.add_cumulative(intervals, demands, int(capacity))
        # The incumbent is feasible by adaptive-capacity construction in the
        # caller.  This upper bound prevents spending oracle/decode time on a
        # schedule that cannot improve the primary objective.
        model.add(sum(tardies) <= int(incumbent_tardy))
        model.minimize(1000 * sum(tardies) + sum(deviations))

        # Do not add the tempting d_i<=d_j and p_i<=p_j => i-before-j rule as a
        # hard constraint.  With release dates and cumulative capacity jobs may
        # overlap, so that single-machine dominance is not generally valid here.

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit)
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = int(seed) & 0x7FFFFFFF
        solver.parameters.log_search_progress = False
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        return {bid: int(solver.value(start)) for bid, start in starts.items()}
    except Exception:
        return None
