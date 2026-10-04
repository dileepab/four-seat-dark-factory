---
name: planner-times-from-the-clock
description: "When logging times in PLAN.md or room messages, read `date -u` first; times written ahead of the clock kept slipping in as future times"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 62e69f10-84a3-4fec-ae24-41e6c76ab279
  modified: 2026-10-04T18:44:48.367Z
---

Write a time into PLAN.md, a log row or a room message only after reading it from `date -u`, a band send result or a commit's `%cI`. Never put in the time you expect the send or commit to happen. In the pocketful run (2026-10-04) the planner did that six times: 14:16Z, ~14:58Z and 16:01Z in stage 3, then 17:56Z, 18:17Z and 18:47Z in stage 4. Each was caught only when it was rechecked against the clock.

**Why:** the run forbids placeholder, fabricated or future times. A plan log is evidence, and a time written ahead of the clock is wrong evidence.

**How to apply:** when a script writes a log row, pass it `$(date -u +%H:%M)` from the same shell call. When a message and a log row share a time, send first, read the clock, then write the row. For "by HH:MM" upper bounds, use the time you last read, never a later one. See also [[verifier-post-hashes-only-after-seeing-them]], the same rule for commit hashes.
