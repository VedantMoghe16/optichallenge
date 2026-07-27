"""Paired, fully sequential gate: for each instance run arm A then arm B
back-to-back so any residual machine load affects both arms equally.
Contention is the dominant error term on congested instances (F6), so this
design is required for a valid verdict."""
import json, subprocess, sys, time
from pathlib import Path
SC = Path("/private/tmp/claude-501/-Users-vedantmoghe-Downloads-optichallenge/828d3afa-14fe-4679-bfb6-c94c0e22ac75/scratchpad/bisect")
BASE = Path("/Users/vedantmoghe/Downloads/optichallenge")
TL = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
rows = []
for i in range(1, 41):
    p = BASE / ("train 2" if i <= 20 else "train") / f"prob_{i}.json"
    vals = {}
    for arm in ("A", "B"):
        out = f"pg_prob_{i}.json"
        subprocess.run(["/opt/anaconda3/bin/python", "driver.py", str(p), str(TL), out],
                       cwd=SC / arm, capture_output=True)
        vals[arm] = json.loads((SC / arm / out).read_text())
    a, b = vals["A"], vals["B"]
    d = (b["objective"] - a["objective"]) / a["objective"] * 100 if a["objective"] else 0.0
    rows.append((f"prob_{i}", a["objective"], b["objective"], d,
                 a["feasible"], b["feasible"]))
    print(f"prob_{i:<3} shipped={a['objective']:>13,.0f} hardened={b['objective']:>13,.0f} "
          f"{d:+7.2f}%  feas={a['feasible']}/{b['feasible']}", flush=True)
ta = sum(r[1] for r in rows); tb = sum(r[2] for r in rows)
wins = sum(1 for r in rows if r[3] < -0.5); reg = sum(1 for r in rows if r[3] > 0.5)
infeas = [r[0] for r in rows if not r[5]]
print(f"\nTOTAL shipped={ta:,.0f} hardened={tb:,.0f} ({(tb-ta)/ta*100:+.2f}%)")
print(f"wins={wins} ties={len(rows)-wins-reg} regressions={reg} infeasible={infeas or 'NONE'}")
print("GATE:", "PASS" if not infeas and (tb-ta)/ta*100 <= 0.5 else "FAIL")
