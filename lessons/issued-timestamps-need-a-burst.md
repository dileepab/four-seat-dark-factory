---
name: issued-timestamps-need-a-burst
description: "tests of \"two writes never share a timestamp\" must send ~20 writes at once; sequential writes catch a clock-not-issued mutant only by chance"
metadata:
  node_type: memory
  type: feedback
  originSessionId: addc8efb-7949-4d8b-ac04-c5bd4572d663
  modified: 2026-10-04T18:42:57.104Z
---

To test that a new write path issues its timestamp (strictly later than every earlier one, never shared), send about 20 writes of that path at once with `Service.burst`, then assert that all the returned timestamps are distinct and each is later than its payment's created_at. If the burst commits within fewer than 20 ms, a mutant that reads the raw clock must repeat a value (pigeonhole). It failed 5 of 5 runs on node and in a container.

**Why:** in stage 4 the critic blocked W20 (BR06) because the sequential batch tests caught `recorded_at = now.ts` only when two writes happened to share a millisecond. The refund path (RF46) had the same gap.

**How to apply:** whenever a stage adds an idempotent write path that issues created_at or recorded_at, add the burst test in that item's concurrency file in the first suite commit, and check it against a copy where the issue call is replaced by the clock reading. This is the verifier side of [[timing-dependent-kills]]: write the burst test up front so the critic has nothing to block on.
