"""Full paired comparison: Kestrel base decoder (arm C) vs raster decoder (arm D).
Protocol F10: un-contended, arms run back-to-back per instance.
Phase 1 = all 40 @60s.  Phase 2 = congested 20 @240s (where the raster
construction pass can actually complete)."""
import json, subprocess, sys
from pathlib import Path
SC = Path("/private/tmp/claude-501/-Users-vedantmoghe-Downloads-optichallenge/828d3afa-14fe-4679-bfb6-c94c0e22ac75/scratchpad/bisect")
BASE = Path("/Users/vedantmoghe/Downloads/optichallenge")

def run(nums, tl, tag):
    print(f"\n##### PHASE {tag}: {len(nums)} instances @ {tl:.0f}s\n", flush=True)
    tc = td = 0.0
    for i in nums:
        p = BASE / ("train 2" if i <= 20 else "train") / f"prob_{i}.json"
        v = {}
        for arm in ("C", "D"):
            out = f"fc{tag}_prob_{i}.json"
            subprocess.run(["/opt/anaconda3/bin/python", "driver.py", str(p), str(tl), out],
                           cwd=SC / arm, capture_output=True)
            v[arm] = json.loads((SC / arm / out).read_text())
        c, d = v["C"], v["D"]
        tc += c["objective"]; td += d["objective"]
        dl = (d["objective"] - c["objective"]) / c["objective"] * 100 if c["objective"] else 0
        print(f"prob_{i:<3} kestrel={c['objective']:>14,.0f} (Z1={c['obj1']:>6.0f})  "
              f"raster={d['objective']:>14,.0f} (Z1={d['obj1']:>6.0f})  {dl:+7.2f}%  "
              f"feas={c['feasible']}/{d['feasible']}", flush=True)
    print(f"\nPHASE {tag} TOTAL kestrel={tc:,.0f} raster={td:,.0f} "
          f"({(td-tc)/tc*100:+.2f}%)", flush=True)

run(list(range(1, 41)), 60.0, "60")
run(list(range(21, 41)), 240.0, "240")
print("\nFULL_COMPARE_DONE", flush=True)
