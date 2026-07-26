"""Regenerate the edge-case battery instances (same recipes as the earlier local battery).

Usage: python3 gen_edge_cases.py <out_dir> [loose_train_dir]
Default loose_train_dir = "/repo/train 2" (prob_1..20, the loose set).

Recipes:
  edge_n600      prob_17 (n=300) with all blocks duplicated; the copy gets
                 release_time/due_date shifted +3  -> n=600 stress
  edge_m1        prob_1 reduced to bay 0 only; every block bay_preferences=[100]
  edge_orient    prob_2 with non-contiguous orientation ids 3+2k (FAQ trap)
  edge_w1zero    prob_5 with w1=0
  edge_w2dom     prob_5 with w2-dominant weights (w1=1, w2=1000000, w3=1)
  edge_n5        prob_1 truncated to blocks[:5]
  edge_zeroslack prob_2 with due_date = release_time + processing_time
"""
import copy
import json
import os
import sys

out_dir = sys.argv[1]
loose = sys.argv[2] if len(sys.argv) > 2 else "/repo/train 2"
os.makedirs(out_dir, exist_ok=True)


def load(n):
    with open(os.path.join(loose, "prob_%d.json" % n)) as f:
        return json.load(f)


def dump(name, p):
    p["name"] = name
    with open(os.path.join(out_dir, name + ".json"), "w") as f:
        json.dump(p, f)
    print("wrote %s  (n=%d, m=%d, w=%s)"
          % (name, len(p["blocks"]), len(p["bays"]), p["weights"]))


# edge_n600: prob_17 doubled, +3 shift on the copy
p = load(17)
extra = copy.deepcopy(p["blocks"])
for b in extra:
    b["release_time"] += 3
    b["due_date"] += 3
p["blocks"] = p["blocks"] + extra
dump("edge_n600", p)

# edge_m1: prob_1, single bay, prefs [100]
p = load(1)
p["bays"] = p["bays"][:1]
for b in p["blocks"]:
    b["bay_preferences"] = [100]
dump("edge_m1", p)

# edge_orient: prob_2, orientation ids 3+2k (non-contiguous)
p = load(2)
for b in p["blocks"]:
    for k, o in enumerate(b["shape"]):
        o["orientation"] = 3 + 2 * k
dump("edge_orient", p)

# edge_w1zero: prob_5, w1=0
p = load(5)
p["weights"]["w1"] = 0
dump("edge_w1zero", p)

# edge_w2dom: prob_5, w2-dominant
p = load(5)
p["weights"] = {"w1": 1, "w2": 1000000, "w3": 1}
dump("edge_w2dom", p)

# edge_n5: prob_1 first five blocks
p = load(1)
p["blocks"] = p["blocks"][:5]
dump("edge_n5", p)

# edge_zeroslack: prob_2, zero slack everywhere
p = load(2)
for b in p["blocks"]:
    b["due_date"] = b["release_time"] + b["processing_time"]
dump("edge_zeroslack", p)
