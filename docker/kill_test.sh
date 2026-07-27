#!/bin/bash
# Corrected fork kill-test (the battery's own process targeting killed the
# driver, not a worker -- see RESULTS.md 2026-07-27 ~10:45 KST).
# Verified result 2026-07-27 (image ogc-parity): 4 fork workers spawned
# (pids 17/18/19/20), SIGKILLed worker 20 at t=15s, driver rc=0, output
# checker-feasible: prob_20 obj=305,288 Z1=5, elapsed 56.49s of 60s.
docker run --rm --cpus=4 -v "$(cd "$(dirname "$0")/.." && pwd)":/repo:ro ogc-parity bash -c '
mkdir -p /tmp/bench && cd /tmp/bench
cp /repo/submission/myalgorithm.py /repo/ogc2026/baseline/utils.py /repo/docker/parity_driver.py .
python3 parity_driver.py "/repo/train 2/prob_20.json" 60 /tmp/bench/kill2.json &
DRV=$!
sleep 15
W=$(pgrep -P $DRV | tail -1)
if [ -n "$W" ]; then echo "SIGKILL worker $W (workers: $(pgrep -P $DRV | tr "\n" " "))"; kill -9 $W; else echo "NO WORKERS FOUND"; fi
wait $DRV; echo "driver rc=$?"
cat /tmp/bench/kill2.json'
