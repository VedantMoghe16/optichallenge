#!/usr/bin/env bash
# OGC 2026 server-parity battery. Runs INSIDE the ubuntu:24.04 container.
# Expects: repo mounted read-only at /repo, writable results dir at /results,
# venv python (shapely 2.1.2) first on PATH, helpers baked into /work.
# Never aborts mid-battery: every case records a JSON verdict; the summary
# at the end decides PASS/FAIL (exit code 1 on any FAIL).
set -u

REPO=/repo
BENCH=/tmp/bench
RESULTS=/results
LOOSE="$REPO/train 2"      # prob_1..20  (loose)
CONG="$REPO/train"         # prob_21..40 (congested)

mkdir -p "$BENCH" "$RESULTS"

# ---- stage the bench: solver + official checker + driver ----------------------
cp "$REPO/submission/myalgorithm.py" "$BENCH/myalgorithm.py"
cp "$REPO/ogc2026/baseline/utils.py" "$BENCH/utils.py"
cp /work/parity_driver.py            "$BENCH/driver.py"
cp /work/gen_edge_cases.py           "$BENCH/gen_edge_cases.py"

echo "== environment"
python3 -c "import sys, shapely; print('python', sys.version.split()[0], '| shapely', shapely.__version__)" \
    | tee "$RESULTS/env.txt"
nproc | sed 's/^/cores: /' | tee -a "$RESULTS/env.txt"

# run_case NAME PROB_JSON TIMELIMIT
# Hard timeout guard = timelimit + 90s so one hung case cannot stall the battery.
run_case() {
    local name="$1" prob="$2" tl="$3"
    echo "== case $name  ($prob @ ${tl}s)"
    ( cd "$BENCH" && timeout -k 10 "$(( tl + 90 ))" python3 driver.py "$prob" "$tl" "$RESULTS/$name.json" )
    local rc=$?
    if [ $rc -ne 0 ] || [ ! -s "$RESULTS/$name.json" ]; then
        printf '{"prob": "%s", "timelimit": %s, "feasible": false, "error": "driver exited rc=%d (crash or hard timeout)"}\n' \
            "$prob" "$tl" "$rc" > "$RESULTS/$name.json"
    fi
}

# Sum RSS (KB) of a pid and all its descendants.
tree_rss_kb() {
    ps -eo pid=,ppid=,rss= | awk -v root="$1" '
        { par[$1]=$2; rss[$1]=$3 }
        END {
            total = 0
            for (p in par) {
                q = p; d = 0
                while (q != "" && q != 0 && d < 64) {
                    if (q == root) { total += rss[p]; break }
                    q = par[q]; d++
                }
            }
            print total
        }'
}

# ---- (a) solo parity runs: prob_35 / prob_36 @60s ------------------------------
# Local mac (shapely 2.0.7) references: 5,586,483 and 407,802. The summary WARNs
# on objective drift outside +/-30% and FAILs on any feasibility flip.
run_case solo_prob35 "$CONG/prob_35.json" 60
run_case solo_prob36 "$CONG/prob_36.json" 60

# ---- (b) edge cases (same recipes as the earlier local battery) ----------------
echo "== generating edge cases"
( cd "$BENCH" && python3 gen_edge_cases.py "$BENCH/edges" "$LOOSE" )

run_case edge_n600      "$BENCH/edges/edge_n600.json"      60
run_case edge_m1        "$BENCH/edges/edge_m1.json"        30
run_case edge_orient    "$BENCH/edges/edge_orient.json"    30
run_case edge_w1zero    "$BENCH/edges/edge_w1zero.json"    30
run_case edge_w2dom     "$BENCH/edges/edge_w2dom.json"     30
run_case edge_n5        "$BENCH/edges/edge_n5.json"        30
run_case edge_zeroslack "$BENCH/edges/edge_zeroslack.json" 30

# ---- (c) timelimit boundaries on prob_20 ---------------------------------------
# 10s = single-process path (<20s), 21s = just over the portfolio threshold, 30s.
run_case tl10 "$LOOSE/prob_20.json" 10
run_case tl21 "$LOOSE/prob_20.json" 21
run_case tl30 "$LOOSE/prob_20.json" 30

# ---- (d) fork-specific: SIGKILL one portfolio worker mid-run -------------------
# Parent must still return a checker-feasible dict (dead-worker resilience).
echo "== case killtest  (prob_20 @ 60s, kill -9 one worker at t=15s)"
( cd "$BENCH" && timeout -k 10 150 python3 driver.py "$LOOSE/prob_20.json" 60 "$RESULTS/killtest.json" ) &
DRIVER_PID=$!
sleep 15
KIDS="$(pgrep -P "$DRIVER_PID" 2>/dev/null || true)"
WORKER="$(echo "$KIDS" | tail -n 1)"
if [ -n "${WORKER:-}" ]; then
    echo "   killing child pid $WORKER of driver $DRIVER_PID (children: $(echo $KIDS | tr '\n' ' '))"
    kill -9 "$WORKER" 2>/dev/null || true
    printf '{"killed_pid": %s, "kill_at_s": 15}\n' "$WORKER" > "$RESULTS/killtest_meta.json"
else
    echo "   WARN: no child process found at t=15s (portfolio not up yet?)"
    printf '{"note": "no worker child found at t=15s; kill not performed"}\n' > "$RESULTS/killtest_meta.json"
fi
wait "$DRIVER_PID"
RC=$?
if [ $RC -ne 0 ] || [ ! -s "$RESULTS/killtest.json" ]; then
    printf '{"prob": "prob_20", "timelimit": 60, "feasible": false, "error": "driver died (rc=%d) after worker SIGKILL"}\n' \
        "$RC" > "$RESULTS/killtest.json"
fi

# ---- (e) 300s soak on prob_38 with peak-RSS sampling ---------------------------
echo "== case soak_prob38  (300s, RSS sampled every 2s)"
( cd "$BENCH" && timeout -k 10 420 python3 driver.py "$CONG/prob_38.json" 300 "$RESULTS/soak_prob38.json" ) &
DRIVER_PID=$!
PEAK_KB=0
while kill -0 "$DRIVER_PID" 2>/dev/null; do
    CUR_KB="$(tree_rss_kb "$DRIVER_PID")"
    [ -n "$CUR_KB" ] && [ "$CUR_KB" -gt "$PEAK_KB" ] 2>/dev/null && PEAK_KB=$CUR_KB
    sleep 2
done
wait "$DRIVER_PID"
RC=$?
if [ $RC -ne 0 ] || [ ! -s "$RESULTS/soak_prob38.json" ]; then
    printf '{"prob": "prob_38", "timelimit": 300, "feasible": false, "error": "soak driver exited rc=%d"}\n' \
        "$RC" > "$RESULTS/soak_prob38.json"
fi
printf '{"peak_rss_mb": %d}\n' "$(( PEAK_KB / 1024 ))" > "$RESULTS/soak_prob38_meta.json"
echo "   peak tree RSS: $(( PEAK_KB / 1024 )) MB"

# ---- summary -------------------------------------------------------------------
python3 /work/parity_summary.py "$RESULTS"
exit $?
