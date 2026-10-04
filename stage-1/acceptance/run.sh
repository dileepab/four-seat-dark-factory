#!/usr/bin/env bash
# Stage-1 acceptance suite (verifier-owned). One command:
#
#   stage-1/acceptance/run.sh [--upto N] [--name PREFIX] [--port PORT] [-- extra pytest args]
#
# Builds the image from this stage folder, starts two containers (A and B, for the
# import-into-another-container checks) with the graded limits (2 vCPU, 2 GiB), waits
# for /health, runs the whole suite, and removes the containers.
#
#   --upto N     only checks for work items W1..WN (default 5 = everything)
#   --name P     container/image name prefix (default pf-verifier-acc). Use pf-<seat>-acc.
#   --port P     first of 16 host ports to use (default 18201). builder 181xx, verifier 182xx,
#                critic 183xx, planner 184xx.
#   --stage-dir D  the stage folder to build (default: the folder holding this suite). Lets a
#                verdict run this suite against a clean worktree of the handed-off commit.
#
# Against services that are already running (container checks are then deselected):
#
#   stage-1/acceptance/run.sh --base-url URL --second-base-url URL [--upto N] [-- pytest args]
#
# Needs python3 with pytest and httpx; defaults to the kickoff venv ($PYTHON overrides).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
STAGE_DIR="$(dirname "$HERE")"
PY="${PYTHON:-$HOME/df-spec/.venv/bin/python}"
UPTO=5
NAME=pf-verifier-acc
PORT=18201
BASE_URL=""
SECOND_URL=""
EXTRA=()

while [ $# -gt 0 ]; do
  case "$1" in
    --upto) UPTO="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --stage-dir) STAGE_DIR="$(cd "$2" && pwd)"; shift 2 ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --second-base-url) SECOND_URL="$2"; shift 2 ;;
    --) shift; EXTRA=("$@"); break ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

export PYTHONDONTWRITEBYTECODE=1

if [ -n "$BASE_URL" ]; then
  args=(--base-url "$BASE_URL" --upto "$UPTO" -m "not container")
  [ -n "$SECOND_URL" ] && args+=(--second-base-url "$SECOND_URL")
  exec "$PY" -m pytest "$HERE" -p no:cacheprovider -q "${args[@]}" ${EXTRA[@]+"${EXTRA[@]}"}
fi

PORT_A=$PORT
PORT_B=$((PORT + 1))
SPARE=$((PORT + 10))

cleanup() {
  docker rm -f "$NAME-a" "$NAME-b" "$NAME-nonet" "$NAME-port" "$NAME-defport" "$NAME-limits" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

docker build -q -t "$NAME" "$STAGE_DIR" >/dev/null
for c in a b; do
  p=$PORT_A; [ "$c" = b ] && p=$PORT_B
  docker run -d --name "$NAME-$c" --cpus 2 --memory 2g -e PORT=8080 \
    -p "127.0.0.1:$p:8080" "$NAME" >/dev/null
done

for p in "$PORT_A" "$PORT_B"; do
  ok=""
  for _ in $(seq 1 240); do
    if curl -fsS "http://127.0.0.1:$p/health" >/dev/null 2>&1; then ok=1; break; fi
    sleep 0.25
  done
  [ -n "$ok" ] || { echo "service on port $p did not become healthy within 60s" >&2; docker logs "$NAME-a" 2>&1 | tail -20 >&2; exit 1; }
done

"$PY" -m pytest "$HERE" -p no:cacheprovider -q \
  --base-url "http://127.0.0.1:$PORT_A" --second-base-url "http://127.0.0.1:$PORT_B" \
  --stage-dir "$STAGE_DIR" --container-prefix "$NAME" --spare-port "$SPARE" \
  --upto "$UPTO" ${EXTRA[@]+"${EXTRA[@]}"}
