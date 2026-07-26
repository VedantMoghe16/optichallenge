"""Aggregate parity battery results into a PASS/FAIL summary table.

Usage: python3 parity_summary.py <results_dir>
Exit code: 0 if no FAIL, 1 otherwise (WARNs do not fail the battery).

Verdict rules per case JSON (written by parity_driver.py / parity_battery.sh):
  FAIL  if feasible is not True, or the driver crashed (error key),
        or elapsed > timelimit + GRACE (server timeout = -1, catastrophic).
  WARN  if objective is outside the expected band (solo parity cases only)
        -> flags shapely 2.0.7 (local mac) vs 2.1.2 (this container) divergence,
        or soak peak RSS above the memory watermark.
  PASS  otherwise.
"""
import glob
import json
import os
import sys

results_dir = sys.argv[1] if len(sys.argv) > 1 else "/results"
GRACE = 1.0  # seconds of wall-clock slack past the declared timelimit

# Local macOS (shapely 2.0.7) reference objectives @60s from the v2.1 solo re-runs.
# Band is deliberately wide (+/-30%): the solver is a stochastic anytime heuristic;
# a WARN here means "look at it", a feasibility flip means FAIL.
EXPECT_BAND = {
    "solo_prob35": (5586483 * 0.70, 5586483 * 1.30),
    "solo_prob36": (407802 * 0.70, 407802 * 1.30),
}
SOAK_RSS_WARN_MB = 14000  # 16 GB server minus headroom

rows = []
n_fail = 0
n_warn = 0

for path in sorted(glob.glob(os.path.join(results_dir, "*.json"))):
    name = os.path.splitext(os.path.basename(path))[0]
    if name.endswith("_meta"):
        continue
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        rows.append((name, "-", "-", "-", "FAIL", "unreadable result json: %s" % e))
        n_fail += 1
        continue

    notes = []
    verdict = "PASS"

    if d.get("error"):
        verdict = "FAIL"
        notes.append(str(d["error"]))
    elif d.get("feasible") is not True:
        verdict = "FAIL"
        notes.append("infeasible stage=%s %s"
                     % (d.get("stage"), (d.get("violations") or [""])[0][:60]))

    tl = d.get("timelimit")
    el = d.get("elapsed")
    if verdict == "PASS" and isinstance(tl, (int, float)) and isinstance(el, (int, float)):
        if el > tl + GRACE:
            verdict = "FAIL"
            notes.append("overran timelimit: %.1fs > %ss+%.0fs" % (el, tl, GRACE))

    if verdict == "PASS" and name in EXPECT_BAND:
        lo, hi = EXPECT_BAND[name]
        obj = d.get("objective")
        if obj is None or not (lo <= obj <= hi):
            verdict = "WARN"
            notes.append("objective %s outside local-mac band [%d, %d] "
                         "-> possible shapely 2.0.7 vs 2.1.2 divergence"
                         % (obj, lo, hi))

    # sidecar meta (killtest / soak)
    meta_path = os.path.join(results_dir, name + "_meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
        if "peak_rss_mb" in meta:
            notes.append("peak RSS %.0f MB" % meta["peak_rss_mb"])
            if verdict == "PASS" and meta["peak_rss_mb"] > SOAK_RSS_WARN_MB:
                verdict = "WARN"
                notes.append("RSS above %d MB watermark" % SOAK_RSS_WARN_MB)
        if "killed_pid" in meta:
            notes.append("SIGKILLed worker pid %s at t=%ss"
                         % (meta["killed_pid"], meta.get("kill_at_s", "?")))
        if meta.get("note"):
            notes.append(str(meta["note"]))

    if verdict == "FAIL":
        n_fail += 1
    elif verdict == "WARN":
        n_warn += 1

    obj = d.get("objective")
    rows.append((name,
                 "yes" if d.get("feasible") is True else "NO",
                 ("%.0f" % obj) if isinstance(obj, (int, float)) else "-",
                 ("%.1f/%s" % (el, tl)) if isinstance(el, (int, float)) else "-",
                 verdict,
                 "; ".join(notes)))

w = [max(len(str(r[i])) for r in rows + [("case", "feas", "objective", "t/limit", "verdict", "notes")])
     for i in range(6)] if rows else [4, 4, 9, 7, 7, 5]
hdr = ("case", "feas", "objective", "t/limit", "verdict", "notes")
line = "  ".join(h.ljust(w[i]) for i, h in enumerate(hdr))
print()
print("=" * len(line))
print("PARITY BATTERY SUMMARY  (%s)" % results_dir)
print("=" * len(line))
print(line)
print("-" * len(line))
for r in rows:
    print("  ".join(str(r[i]).ljust(w[i]) for i in range(6)))
print("-" * len(line))
print("total: %d cases, %d FAIL, %d WARN" % (len(rows), n_fail, n_warn))
if not rows:
    print("NO RESULT FILES FOUND -> FAIL")
    sys.exit(1)
sys.exit(1 if n_fail else 0)
