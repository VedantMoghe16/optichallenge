#!/usr/bin/env bash
# Build the server-parity image and run the full battery.
# Host prerequisites: Docker Desktop running. Everything else is in the image.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
IMAGE=ogc2026-parity
STAMP="$(date +%Y%m%d_%H%M%S)"
RESULTS="$HERE/results/$STAMP"
SOLVER_REL="${1:-submission/myalgorithm.py}"

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon not reachable. Open Docker Desktop first." >&2
    exit 1
fi

mkdir -p "$RESULTS"

echo "== building $IMAGE (context: $HERE)"
docker build -f "$HERE/Dockerfile.server-parity" -t "$IMAGE" "$HERE"

echo "== running battery (repo ro-mounted at /repo, results at $RESULTS)"
# --cpus=4 --memory=16g mirrors the competition server envelope.
# Repo is mounted READ-ONLY: the battery can never touch the frozen v2.1 tree.
set +e
docker run --rm \
    --cpus=4 \
    --memory=16g \
    -v "$REPO":/repo:ro \
    -v "$RESULTS":/results:rw \
    -e "OGC_SOLVER_SOURCE=/repo/$SOLVER_REL" \
    "$IMAGE" \
    bash /work/parity_battery.sh
RC=$?
set -e

echo
echo "== done (exit $RC). Per-case JSON + summary inputs: $RESULTS"
exit "$RC"
