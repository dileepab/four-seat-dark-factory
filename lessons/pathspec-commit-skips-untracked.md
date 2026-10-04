---
name: pathspec-commit-skips-untracked
description: "`git commit -- <dir>` leaves out new (untracked) files; git add new files first, then check the commit's file list in a clean worktree"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 85129f3d-4e37-44a8-86e5-73face073e6c
  modified: 2026-10-04T16:06:02.039Z
---

`git commit -m ... -- stage-N/src stage-N/test` commits only files git already tracks under those paths. New files (a new handler, a new test file) are silently left out, and the commit can import a module it does not contain.

**Why:** in stage 4, W19 at 4484652 lacked `src/handlers/refunds.ts` and `test/w19-refunds.test.ts`. The gate in a clean worktree failed (container would not start; npm test 12 of 17 failing), and a follow-up commit was needed. I had already named 4484652 to the planner.

**How to apply:** before committing, run `git status --short <paths>` and `git add` every `??` file that belongs to the item, then `git commit -- <paths>`. After committing, check `git show --stat HEAD` for the new files, and run npm test in a clean worktree, before naming the hash to anyone. See also [[verifier-post-hashes-only-after-seeing-them]].
