---
name: verifier-post-hashes-only-after-seeing-them
description: Never send a room message that names a commit hash in the same batch as the commit; wait for the commit output
metadata:
  node_type: memory
  type: feedback
  originSessionId: addc8efb-7949-4d8b-ac04-c5bd4572d663
  modified: 2026-10-04T13:02:16.364Z
---

Name a commit hash in a BAND room message only after the `git commit` / `git log -1` output that shows it is visible. Twice in the stage-2 session a reply named a hash that did not exist (35c41a7 for 62c4a4e, 59ea2e8 for df5b2bd), because the message was written in parallel with the commit. Both times a correction had to be posted.

**Why:** PROTOCOL.md requires every verdict and suite announcement to name the full commit hash. Other seats rerun tests and mutants against the hash they are given, so a wrong one wastes their runs.
**How to apply:** commit first, read the hash from the output, then send the message in a later tool call (never in the same parallel batch). Related: [[harness-isolated-needs-absolute-repo]].
