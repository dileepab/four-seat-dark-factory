#!/usr/bin/env bash
# Start stage N. Stage 1 starts empty; stage N>1 starts as a copy of stage N-1
# (the last accepted stage), so every earlier test carries over as a regression test.
# Usage: scripts/new-stage.sh <N>
set -euo pipefail
cd "$(dirname "$0")/.."

N=${1:?usage: scripts/new-stage.sh <stage-number>}
DEST="stage-$N"
[ -e "$DEST" ] && { echo "$DEST already exists"; exit 1; }

if [ "$N" -le 1 ]; then
  mkdir -p "$DEST/acceptance"
  echo "Created empty $DEST/"
else
  SRC="stage-$((N - 1))"
  [ -d "$SRC" ] || { echo "$SRC does not exist"; exit 1; }
  # PLAN.md and REVIEW.md are per stage; runtime data and caches are not source.
  rsync -a \
    --exclude 'PLAN.md' --exclude 'REVIEW.md' --exclude '.git' \
    --exclude '__pycache__' --exclude '.pytest_cache' --exclude '*.db' --exclude '*.db-*' \
    "$SRC/" "$DEST/"
  echo "Created $DEST/ from $SRC/"
fi
