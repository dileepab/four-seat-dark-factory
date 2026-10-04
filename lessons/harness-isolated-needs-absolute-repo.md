---
name: harness-isolated-needs-absolute-repo
description: "scripts/harness.sh --mode isolated fails with \"stage-2 does not exist\" when --repo is a relative path"
metadata:
  node_type: memory
  type: reference
  originSessionId: addc8efb-7949-4d8b-ac04-c5bd4572d663
  modified: 2026-10-04T13:02:12.372Z
---

`scripts/harness.sh run --track pocketful --repo <path> --stage N --mode isolated` must get an absolute `--repo` path. With a relative one (for example `.work/verifier-h6bh/wt-xxxx`), it exits 2 with "cannot build the service: <path>/stage-2 does not exist". Host mode works with a relative path.

**Why:** isolated mode resolves the repo from a different working directory (seen 2026-10-04 on the stage-2 W9-W11 verdict run).
**How to apply:** always pass `/Users/Dileepa/dark-factory-v3/...` absolute paths to harness.sh, in both modes. Related: [[verifier-post-hashes-only-after-seeing-them]].
