"""Which relation rejects contested positions?  Re-implement the predicate's
decision tree with per-relation counters (same logic, instrumented)."""
import json, os, sys, collections
os.environ["KESTREL_LAYER_TRUE"] = "1"
sys.path.insert(0, ".")
import myalgorithm as M, utils

R = collections.Counter()
_static, _crane = M._lt_static_ok, M._lt_crane_ok

def probe(geom, x, y, t, e, blockers):
    """Mirror of _safe_layers_position with reason accounting."""
    bb = M._moved_bbox(geom, x, y)
    verdict = True
    reasons = []
    for a in blockers:
        if not M._bbox_overlap(bb, a["_bbox"]):
            continue
        ga, xa, ya = a["_geom"], a["x"], a["y"]
        bE, bX = a["entry_time"], a["exit_time"]
        if not _static(geom, x, y, ga, xa, ya):
            reasons.append("R1_same_layer"); verdict = False; break
        if bE < t:
            if not _crane(geom, x, y, ga, xa, ya):
                reasons.append("R2_entry_crane"); verdict = False; break
        elif bE == t:
            if not _crane(geom, x, y, ga, xa, ya):
                reasons.append("R3a_sameday_entry_fwd"); verdict = False; break
            if not _crane(ga, xa, ya, geom, x, y):
                reasons.append("R3b_sameday_entry_rev"); verdict = False; break
        else:
            if not _crane(ga, xa, ya, geom, x, y):
                reasons.append("R4_reverse_entry"); verdict = False; break
        if bX < e:
            if not _crane(ga, xa, ya, geom, x, y):
                reasons.append("R5_roofed_exits_first"); verdict = False; break
        elif bX == e:
            if not _crane(geom, x, y, ga, xa, ya):
                reasons.append("R7a_sameday_exit_fwd"); verdict = False; break
            if not _crane(ga, xa, ya, geom, x, y):
                reasons.append("R7b_sameday_exit_rev"); verdict = False; break
        else:
            if not _crane(geom, x, y, ga, xa, ya):
                reasons.append("R6_exit_crane"); verdict = False; break
    R["ACCEPT" if verdict else reasons[-1]] += 1
    return verdict

M._safe_layers_position = probe
prob = json.load(open(sys.argv[1]))
obj, sol = M._solve(prob, timelimit=float(sys.argv[2]), variant=0)
print(json.dumps(dict(R.most_common()), indent=1))
tot = sum(R.values())
print(f"total contested tests: {tot}, accept rate: {R['ACCEPT']/max(1,tot):.5f}")
