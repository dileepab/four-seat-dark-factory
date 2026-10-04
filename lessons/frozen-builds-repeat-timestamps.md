---
name: frozen-builds-repeat-timestamps
description: Frozen stage-1/stage-2 builds can give two writes the same millisecond; upgrade tests must space events or not assume order
metadata:
  node_type: memory
  type: project
  originSessionId: 85129f3d-4e37-44a8-86e5-73face073e6c
  modified: 2026-10-04T15:37:47.658Z
---

The frozen `stage-1/` and `stage-2/` services issue never-decreasing but repeatable timestamps, so two writes made back to back (a hold and its capture, two payments) can share one millisecond. Stage 3 onward issues strictly increasing ones (D67).

**Why:** in stage 3 this made two tests flaky: a statement ordered same-millisecond imported payments by id, and an "1 µs before the capture" view was also before the hold. A third flake: `effective_at = t + 1 µs` is 422 when the correction lands in t's millisecond (no tolerance, D81).

**How to apply:** in builder tests that populate a frozen build for an upgrade, put a few ms of sleep between events whose order the test relies on. Before sending `t + 1 µs` as an instant that must be "not later than now", make a write first.
