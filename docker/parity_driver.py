"""Minimal bench driver: run algorithm() on one instance, checker-verify, dump JSON.

Usage: python3 driver.py <prob.json> <timelimit_seconds> <out.json>
Runs from /tmp/bench where myalgorithm.py + utils.py were copied.
"""
import json
import sys
import time

sys.path.insert(0, "/tmp/bench")
import utils          # official checker (ground truth)
import myalgorithm    # v2.1 solver under test

prob_path, timelimit, out_path = sys.argv[1], float(sys.argv[2]), sys.argv[3]
with open(prob_path) as f:
    prob = json.load(f)

t0 = time.time()
sol = myalgorithm.algorithm(prob, timelimit=timelimit)
elapsed = time.time() - t0

res = utils.check_feasibility(prob, sol)
out = {
    "prob": prob_path,
    "name": prob.get("name"),
    "timelimit": timelimit,
    "elapsed": round(elapsed, 2),
    "feasible": bool(res["feasible"]),
    "stage": res["stage"],
    "objective": res["objective"],
    "obj1": res["obj1"],
    "obj2": res["obj2"],
    "obj3": res["obj3"],
    "violations": list(res["violations"])[:5],
}
with open(out_path, "w") as f:
    json.dump(out, f, indent=1)
print(json.dumps(out))
