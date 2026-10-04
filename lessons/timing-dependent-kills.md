---
name: timing-dependent-kills
description: "A mutant that takes a timestamp from the clock instead of issuing it dies only when two writes share a millisecond; rerun it under load before counting, and ask for a burst test"
metadata:
  node_type: memory
  type: feedback
  originSessionId: a1f87b30-402d-4b4e-bded-ac89d9f2114d
  modified: 2026-10-04T18:43:23.353Z
---

A mutant that replaces an issued timestamp with the raw clock (for example `issue(st, now)` → `now.ts`) is caught by sequential tests only when two writes land in one millisecond.
- Stage 4's BR06 passed every W20 file once on suite 1028890.
- It also passed every builder test.
- It failed 13 of 13 runs on suite 2f9c559, whose tests for it were unchanged.
- RF46, the same change for refunds, passed the acceptance files 3 of 3 times under load.

**Why:** the critic mandate says a flaky kill is not a kill. One red run proves nothing for a mutant whose kill depends on timing, and a container's longer round trip makes collisions rarer still.

**How to apply:** for any timestamp or ordering mutant:
- Rerun it at least 6 times, with and without parallel load, before counting the kill.
- If any run passes, BLOCK and ask for a burst test: N concurrent writes must give N distinct timestamps.
- Burst tests killed BR06 and RF46 with a wide margin: only 6 to 10 of 20 timestamps were distinct.

Related: [[frozen-builds-repeat-timestamps]]; the verifier's side, writing the burst test up front, is [[issued-timestamps-need-a-burst]].
