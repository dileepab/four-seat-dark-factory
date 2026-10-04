#!/usr/bin/env bash
# Build a stage's container with no network, start it with no network, and
# confirm the service answers from inside the container.
#
# Usage: scripts/check-offline.sh <stage-dir> [port] [path]
# Optional env: CPUS=1 MEMORY=512m  (set to the limits published with the spec)
#
# The probe runs python3 inside the container, so the image must include it.
set -euo pipefail

STAGE=${1:?usage: scripts/check-offline.sh <stage-dir> [port] [path]}
PORT=${2:-8080}
URLPATH=${3:-/}

[ -f "$STAGE/Dockerfile" ] || { echo "FAIL: $STAGE/Dockerfile not found"; exit 1; }
docker info >/dev/null 2>&1 || { echo "FAIL: Docker is not running. Start Docker Desktop."; exit 1; }

TAG="factory-$(basename "$STAGE"):offline-check"
echo "== build (no network, no cache)"
docker build --network=none --no-cache -t "$TAG" "$STAGE"

LIMITS=()
[ -n "${CPUS:-}" ] && LIMITS+=(--cpus "$CPUS")
[ -n "${MEMORY:-}" ] && LIMITS+=(--memory "$MEMORY")

echo "== run (no network)"
CID=$(docker run -d --network=none ${LIMITS[@]+"${LIMITS[@]}"} "$TAG")
trap 'docker rm -f "$CID" >/dev/null 2>&1 || true' EXIT

# Any HTTP response, including an error status, means the service is up.
PROBE="import urllib.request, urllib.error
try:
    urllib.request.urlopen('http://127.0.0.1:${PORT}${URLPATH}', timeout=2)
except urllib.error.HTTPError:
    pass
"

for _ in $(seq 1 30); do
  if docker exec "$CID" python3 -c "$PROBE" >/dev/null 2>&1; then
    echo "OK: service answered on port $PORT inside a container with no network"
    exit 0
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$CID")" != "true" ]; then
    echo "FAIL: container exited"
    docker logs "$CID" 2>&1 | tail -50
    exit 1
  fi
  sleep 1
done

echo "FAIL: no answer within 30s"
docker logs "$CID" 2>&1 | tail -50
exit 1
