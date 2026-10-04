#!/usr/bin/env bash
# Run the event harness from the kickoff checkout, from any directory.
# Usage: scripts/harness.sh run --track <track> --repo <repo> --stage N --out <dir> [--mode isolated]
#        scripts/harness.sh check <repo> --track <track>
# KICKOFF points at the kickoff checkout with its .venv (default: ~/df-spec).
set -euo pipefail
KICKOFF="${KICKOFF:-$HOME/df-spec}"
cd "$KICKOFF"
exec .venv/bin/python -m harness "$@"
