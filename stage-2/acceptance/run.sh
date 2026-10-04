#!/usr/bin/env bash
# Stage-2 acceptance suite (verifier-owned). One command:
#
#   stage-2/acceptance/run.sh [--upto N] [--name PREFIX] [--port PORT] [--shots DIR] [-- extra pytest args]
#
# Builds the image from this stage folder and the frozen stage-1/ folder beside it, starts
# three containers with the graded limits (2 vCPU, 2 GiB): A and B from this stage (B for
# the import-into-another-container checks) and P from stage-1/ (the previous service of
# the upgrade checks). It waits for /health, runs the whole suite, and removes them.
#
#   --upto N     only checks for work items up to WN (default 13 = everything). The stage-1
#                regression checks (items 1-5) always run.
#   --name P     container/image name prefix (default pf-verifier-acc). Use pf-<seat>-acc.
#   --port P     first of 16 host ports to use (default 18201). builder 181xx, verifier 182xx,
#                critic 183xx, planner 184xx.
#   --stage-dir D  the stage folder to build (default: the folder holding this suite). Lets a
#                verdict run this suite against a clean worktree of the handed-off commit.
#                The previous service is built from D/../stage-1.
#   --shots DIR  save one screenshot per named UI state at both widths into DIR.
#
# Against services that are already running (container checks are then deselected):
#
#   stage-2/acceptance/run.sh --base-url URL --second-base-url URL --previous-base-url URL [--upto N]
#
# Needs python3 with pytest, httpx and Playwright (Chromium); defaults to the harness venv
# ($PYTHON overrides).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
STAGE_DIR="$(dirname "$HERE")"
PY="${PYTHON:-$HOME/df-spec/.venv/bin/python}"
UPTO=13
NAME=pf-verifier-acc
PORT=18201
BASE_URL=""
SECOND_URL=""
PREV_URL=""
SHOTS=""
EXTRA=()

while [ $# -gt 0 ]; do
  case "$1" in
    --upto) UPTO="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --stage-dir) STAGE_DIR="$(cd "$2" && pwd)"; shift 2 ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --second-base-url) SECOND_URL="$2"; shift 2 ;;
    --previous-base-url) PREV_URL="$2"; shift 2 ;;
    --shots) mkdir -p "$2"; SHOTS="$(cd "$2" && pwd)"; shift 2 ;;
    --) shift; EXTRA=("$@"); break ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

export PYTHONDONTWRITEBYTECODE=1
SHOT_ARGS=()
[ -n "$SHOTS" ] && SHOT_ARGS=(--shots "$SHOTS")

if [ -n "$BASE_URL" ]; then
  args=(--base-url "$BASE_URL" --upto "$UPTO" -m "not container")
  [ -n "$SECOND_URL" ] && args+=(--second-base-url "$SECOND_URL")
  [ -n "$PREV_URL" ] && args+=(--previous-base-url "$PREV_URL")
  exec "$PY" -m pytest "$HERE" -p no:cacheprovider -q "${args[@]}" \
    ${SHOT_ARGS[@]+"${SHOT_ARGS[@]}"} ${EXTRA[@]+"${EXTRA[@]}"}
fi

PREV_DIR="$(cd "$STAGE_DIR/../stage-1" && pwd)"
PORT_A=$PORT
PORT_B=$((PORT + 1))
PORT_P=$((PORT + 2))
SPARE=$((PORT + 10))

cleanup() {
  docker rm -f "$NAME-a" "$NAME-b" "$NAME-p" "$NAME-nonet" "$NAME-uinonet" "$NAME-port" \
    "$NAME-defport" "$NAME-limits" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

docker build -q -t "$NAME" "$STAGE_DIR" >/dev/null
docker build -q -t "$NAME-prev" "$PREV_DIR" >/dev/null
for c in a b p; do
  p=$PORT_A; img="$NAME"
  [ "$c" = b ] && p=$PORT_B
  [ "$c" = p ] && { p=$PORT_P; img="$NAME-prev"; }
  docker run -d --name "$NAME-$c" --cpus 2 --memory 2g -e PORT=8080 \
    -p "127.0.0.1:$p:8080" "$img" >/dev/null
done

for p in "$PORT_A" "$PORT_B" "$PORT_P"; do
  ok=""
  for _ in $(seq 1 240); do
    if curl -fsS "http://127.0.0.1:$p/health" >/dev/null 2>&1; then ok=1; break; fi
    sleep 0.25
  done
  [ -n "$ok" ] || { echo "service on port $p did not become healthy within 60s" >&2; docker logs "$NAME-a" 2>&1 | tail -20 >&2; exit 1; }
done

"$PY" -m pytest "$HERE" -p no:cacheprovider -q \
  --base-url "http://127.0.0.1:$PORT_A" --second-base-url "http://127.0.0.1:$PORT_B" \
  --previous-base-url "http://127.0.0.1:$PORT_P" \
  --stage-dir "$STAGE_DIR" --container-prefix "$NAME" --spare-port "$SPARE" \
  --upto "$UPTO" ${SHOT_ARGS[@]+"${SHOT_ARGS[@]}"} ${EXTRA[@]+"${EXTRA[@]}"}
