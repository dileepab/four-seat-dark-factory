# The factory

A band of four coding-agent seats that plans, builds, independently verifies and reviews a service one stage at a time. A run is unattended: the task dispatched into the room is the only human input, and the planner ends each stage with a report.

The standing instructions are [`PROTOCOL.md`](PROTOCOL.md) (shared) and one mandate per seat in [`mandates/`](mandates/). They name nothing about the product. The product arrives as a task dispatched into the room ([`tasks/run.md`](tasks/run.md)).

**Result of the submitted run:**
- All four pocketful stages were built, accepted and closed in one unattended run, in one room, with no pause.
- Each stage folder claims its own stage in isolated mode, and each fails the next stage's suite, as the overshoot probe requires.
- The run took 12 h 26 min from the dispatch to the final report.
- It cost about $412 at list prices (Band's prices, not a bill).
- Review intervened 15 times before acceptance: 4 plan reviews, each of which revised the plan while the build was under way, and 11 blocking reviews with 18 BLOCKED item verdicts, each of which stopped its item until new evidence resolved it. Each one changed the product, the plan or the tests. They are listed [below](#what-it-caught-in-the-submitted-run).

## The crew

| Seat | Mandate | Harness and model | Effort | The one job it owns |
|---|---|---|---|---|
| planner-h6bf | [planner-h6bf.md](mandates/planner-h6bf.md) | Claude Code, `claude-opus-5-5` | max | Turn the task into a plan with an interface contract, numbered invariants and recorded decisions; accept work or re-plan; report the stage |
| builder-h6bg | [builder-h6bg.md](mandates/builder-h6bg.md) | Claude Code, `claude-opus-5-5` | xhigh | Implement each work item, commit, and prove it with the full gate |
| verifier-h6bh | [verifier-h6bh.md](mandates/verifier-h6bh.md) | Claude Code, `claude-opus-5-5` | xhigh | Write acceptance tests from the specification, not the code; run every check on the handed-off commit; PASS or FAIL |
| critic-h6bj | [critic-h6bj.md](mandates/critic-h6bj.md) | Claude Code, `claude-opus-5-5` | max | Review every plan and change against the specification and invariants, and break it in a scratch copy; APPROVED or BLOCKED |

Each seat runs as its own Claude Code session in BAND Desktop (the band-peer plugin's `/jam as <role>`), with auto-compact at 500k tokens. Each seat is started with its role as its git identity, so every commit names the seat that made it.

**Why four seats:** the verifier and the critic are two different kinds of independence.
- The verifier asks "does it do what the specification says?" from tests written without reading the code.
- The critic asks "what would slip through?" It mutates the code and re-reads the specification for what no check covers.

## Who talks to whom

- **Human to planner:** one dispatch for the whole run, and nothing else.
- **Planner to builder and verifier at once:** the builder gets the work items and the verifier gets the criteria. Each gets the full specification text it needs, so the tests are written independently of the code.
- **Builder to verifier:** a handoff naming a commit, with evidence.
- **Verifier to critic:** a PASS. **Verifier to builder:** a FAIL with a reproducing command.
- **Critic to planner:** APPROVED. **Critic to the seat that must act:** BLOCKED, with the missing evidence.
- **Every HANDOFF and every verdict** also goes to the planner, so it always knows the state of every item.
- **The verifier stays out of design discussion** between the planner and the builder, so its tests stay independent of the implementation.

## One flow, end to end

    Human dispatches the run -> @planner reads this stage's spec (and the next one's, for what this stage must carry)
      -> PLAN.md: contract, invariants, limits for every unbounded input, decisions -> @critic reviews the plan in one batch
      -> @builder implements the items   while   @verifier writes the acceptance suite from the plan alone
      -> @planner traces every normative line of the spec to a test as soon as the first suite lands; each gap becomes a criterion
      -> @verifier runs the clean build and every check on the handed-off commit -> FAIL with repro -> @builder fixes -> PASS
      -> @critic mutates the product in a scratch copy; a mutant no test notices -> BLOCKED -> @verifier adds the test -> PASS
      -> @critic APPROVED on the same commit as the PASS -> @planner ACCEPTED
      -> @verifier runs the final isolated check on the final commit -> stage report -> next stage starts from a copy

## How it catches bad work

- **Evidence rule:** a claim without the command and its output in the room does not count.
- **Same-commit verdicts:** every verdict names a commit. ACCEPTED needs a PASS and an APPROVED on that exact commit.
  - When a fix changes only tests, the earlier PASS carries over, and only the touched tests and the critic's survivors rerun.
  - When product code changes, everything reruns.
- **Plan review before any verdict:** the critic reviewed every stage's plan in one batch before any code was judged. The builder starts on the first items while the review runs. So in stages 1 to 3 some code already existed when the review landed, and was changed to match: W1 in a follow-up commit (`2ffcbe8`), W7 before its handoff, and W14 to W17 in `0acff74`.
  - Between them, the four reviews raised 16 defects, 7 gaps or wording points, and 17 criteria or recommendations.
  - Each was in the plan within minutes.
- **Mutation review:** the critic changes one line to break one rule, in a scratch copy. If the suites stay green, the suites are the defect.
  - It ran 121 mutants in stage 3 and 148 in stage 4.
  - Every survivor became a test, or was shown to be equivalent with the reason recorded.
- **Spec trace, early:** the planner maps every normative line of the specification to a test as soon as the verifier's first suite lands, while the build is still running.
  - That was 97, 130, 70 and 43 lines for the four stages.
  - Gaps become criteria at once.
- **Limits up front:** the first plan states a limit and a refusal for every unbounded input (size, count, depth, range). The critic attacks one envelope instead of discovering limits one round at a time.
- **Anti-overfitting:** the supplied checks are wired to but never coded against. Product code that special-cases sample inputs is blocked on sight.
- **Liveness:** each handoff is acknowledged in one line. After about 20 minutes with no acknowledgement, the planner re-sends the handoff or sends one ping.
  - It did this four times in this run: two re-sends to the critic (07:50 and 09:35 UTC) and two pings to the verifier (13:42 and 16:11 UTC).
  - Each time the seat was busy, not stalled, and replied within three minutes.
  - The first re-send was not needed: the critic had already acknowledged W3 and W4 in replies addressed to the builder, and the planner missed them.
- **Shared machine:** before a verdict run, the verifier asks the other seats in the room to start no container runs until it posts the verdict.
  - In stage 4 the builder confirmed every hold in the room and twice stopped a gate run it had under way. It did the same once in stage 2, for W7.
  - The critic confirmed three of the four stage-4 holds.
  - In stages 1 to 3 most holds got no reply in the room.

## What it caught in the submitted run

Each of these was found by one seat in another seat's work, before acceptance. The full record is in:
- each stage's `PLAN.md` (decisions D1–D106);
- each stage's `REVIEW.md` (the critic's entries);
- the stage reports and the room log.

| Stage | Who caught it | What was wrong | What changed |
|---|---|---|---|
| 1 | critic (plan review) | 5 points, among them plan decision D24, which contradicted the specification on amount minimums | All 5 in the plan (23e7601) before any code was judged |
| 1 | critic | M49: no test would notice if a reset to the same user ids kept old login tokens alive (the product itself was correct and returned 401) | Test (W1/W2, suite ee19494) |
| 1 | critic | R29: no test covered the 2^53 guard on paying a request | Tests (W3). Rules that span endpoints are now traced endpoint by endpoint |
| 1 | critic | S18: a non-object settlement entry was refused only when its turn came, so an earlier entry's 404 or self_payment won. The plan checks that every entry is an object before any entry is examined | **Product fix** D37 (484349f) |
| 1 | critic | E19, E04: no test caught a torn export during a burst, or time running backwards after an import. Also, reset and import accepted 80 levels of nesting against the plan's 64, with no decision recorded | Tests (fc36063, 850f706), and decision D38 (80 levels on the test hooks) |
| 2 | critic (plan review) | 8 defects, 3 gaps and 3 recommendations. Among them: only open holds expire; the browser must give up before a check does | All in the plan (45fe2dc) before W7 was handed off |
| 2 | critic | X15: a reset after an import whose clock ran ahead could keep that clock, and no test noticed (the product was right) | Tests (W7; 5f9781a, 5e17085) |
| 2 | critic | E16, E17, E26, E32: four import validation faults passed every test | Tests (W8) |
| 2 | planner (screenshot review) | Money to pay was coloured as money received; a hold's expiry wrapped at 375 px; the collect control mixed two words | **Product fix**, new item W13 (92d940d) |
| 2 | critic | A success answer with an empty body threw a script error and showed no outcome, instead of saying the outcome was unknown. The text for an unconfirmed capture or request payment did not say the money may have moved. Also, 8 UI rules could break with every test passing | **Product fix** (095b027) and tests (75c06e8, df5b2bd) |
| 2 | builder | A probe in the acceptance suite parsed a missing field as a value | Suite fix (62c4a4e) |
| 3 | critic (plan review) | 3 defects (which captures count, seeded closed holds, instant forms on import), 2 smaller ones and 5 criteria | **Product change** before any verdict (0acff74) |
| 3 | builder, critic | Two timing races in the draft acceptance tests could fail a correct build | Suite fix (b4f6d16) |
| 3 | critic | 9 of 121 mutants survived. Among them: trailing fraction zeros, code-point ties, a correction's clock tolerance | 9 tests (3c5b827) |
| 4 | critic (plan review) | A stage-3 saved statement would lose its original form after the upgrade | **Product rule** D106, before W21 was built |
| 4 | critic | RF18: the funds check and the 2^53 guard could swap places with every test passing | Tests (2f9c559) |
| 4 | critic | BR06: a batch's time taken from the clock was caught only when two writes shared a millisecond | Burst tests: 20 batches and 20 refunds at once (da8d92b) |
| 4 | critic | VA14, VA15: an import could accept a missing refund_of or correction_batch_id as null with every test passing | Tests (c6daf51) |

**In stage 4 no review found a product defect.** Every BLOCKED asked only for tests, and the product code never changed after a handoff.

**No verifier FAIL verdict was posted in the run.** Every commit that a standing verdict names passed the verifier's suite. Not every handed-off commit did:
- The W2 handoff at 1bd9c8d failed the W1 checks that plan 23e7601 revised just after it, and the verdict went to 2ffcbe8 instead.
- The W4 and W5 PASSes at e143cf1 and 295378c were withdrawn after the critic's S18 finding (502613c), and re-verified at 484349f.
- The W9–W11 and W13 commits 5f9781a and 92d940d failed the critic's new empty-body tests until the fix 095b027 passed.

What the suite missed was found by the critic's plan and code reviews, probes and mutants, by the planner's screenshot review and trace, and by the builder.

## The submitted run

- **Dispatch:** Oct 4, 2026, 11:48 IST (06:18 UTC). One message, [`tasks/run.md`](tasks/run.md), for all four stages.
- **Final report:** Oct 5, 00:14 IST (18:44 UTC).
- **Room:** one Band room, `7884df0c-298f-4120-abce-f6bef24337b9`, with 10,347 events.
  - [`room.json`](room.json) is the console's full-session download: all 10,347 events, from the seats joining (06:17 UTC) to the end of the run.
  - [`rooms/`](rooms/) holds two cross-checks: the console's filtered download of every message, and the complete API read of the room ([rooms/README.md](rooms/README.md)).

| Stage | Working time | Final commit | Shipped checks (isolated) | Acceptance suite | Builder tests | Items | Decisions |
|---|---|---|---|---|---|---|---|
| 1 | 2 h 34 min | 4baf8d9 | 147/147; stage 2 fails | 1,076 | 89 | W1–W6 | D1–D38 |
| 2 | 4 h 10 min | f9eed3a | 147 + 35/35; stage 3 fails | 2,026 | 155 | W7–W13 | D39–D65 |
| 3 | 2 h 35 min | 478ad72 | 147 + 35 + 6/6; stage 4 fails | 2,614 | 203 | W14–W18 | D66–D87 |
| 4 | 3 h 6 min | 2287601 | 147 + 35 + 6 + 5/5 | 2,887 | 248 | W19–W22 | D88–D106 |

- **Suites:** each acceptance suite carries the earlier stages' suites, brought to the new contract. From stage 2 on, each includes:
  - the offline build and a `--network=none` run;
  - upgrades from containers built from every earlier frozen folder;
  - browser tests at 375 and 1280 px, with 46 named states (48 in stage 4) rendered as screenshots.
- **The final checks** ran with `--mode isolated` (no outbound network, 2 vCPU, 2 GiB).
- **Independent check:** after the run, an observer re-ran all four folders in isolated mode. Each claimed its own stage, with no overshoot.
- **Who did the work:**
  - Commits: planner 94, builder 28, verifier 27, critic 24.
  - Room text messages: planner 101, verifier 85, critic 50, builder 45, human 1.

### Cost

- **Model:** `claude-opus-5-5` for all four seats.
- **Tokens:** Band's usage report shows 1.19 billion tokens across the four seats, most of them cache reads.
- **List-price estimate** (Band's `band usage agents`, read 7 minutes after the final report; not a bill): critic $129.24, builder $96.36, verifier $94.78, planner $89.36. Total **$409.74**.
  - Band had logged the seats' activity up to 12 to 19 minutes before the final report.
  - At Band's prices, the seats' own transcripts up to the final report come to about **$412**.
- **What it was paid with:** a Claude Max subscription, with no paid overflow.
  - The run used about 28 points of the weekly allowance, observer included.
  - The 5-hour window peaked at 89%. The observer had a guard ready to pause the seats at 95%, and it never had to fire.
- **Where the time went:** most of the working time was proof, not code.
  - Each stage opened with its plan, the critic's review and the handoff. That took between 25 minutes and an hour.
  - A whole-suite verdict run grew with the suite. It took about 3 minutes in stage 1 (1,076 tests) and about 10 minutes in stage 2. In stage 3 it took 13.5 minutes, and in stage 4 14 to 16.5 minutes (2,887 tests).

### Human input, and everything a human did

- **In the room:** exactly one message, the dispatch. There was no steering, approval, hint or rerun.
- **Before the run:** a human started the four seats with their git identities (the setup in [README.md](README.md)). At the human's request, the observer session did the rest:
  - it wrote the factory commit (`6413631`);
  - it created the room under the planner's identity, invited the other three seats and added the human;
  - it posted the dispatch ([`tasks/run.md`](tasks/run.md)) from the human's account.
- **During the run:** nothing. There was no pause and no signal to any seat, and nothing was typed into any seat's terminal.
- **Observer:** a separate Claude Code session the human worked in. From the dispatch (06:18 UTC) to the final report (18:44 UTC) it only read the room and the repository, to report progress. Its writes came before the run (the setup above) and after it (the packaging below).
- **After the run:** the human, working with the observer session, added the repository's root packaging:
  - FACTORY.md and README.md;
  - the room downloads and `rooms/`;
  - `lessons/`;
  - the mandate files renamed to the seats' handles.

  Everything under `stage-*/` is the band's.

### Commit identities

- **The band:** each of the band's 173 commits carries the name of the seat that made it.
- **The human:** the one commit before the dispatch (`6413631`, the factory itself) carries the human's name, as do the packaging commits after the final report. These commits carry a `Co-Authored-By: Claude` trailer, because the observer session wrote them.

## Design choices and what they cost

- **Two independent checkers (verifier and critic):**
  - The gain: tests that come from the specification rather than the code, and a critic whose mutants prove the tests.
  - The cost: every item waits for two verdicts on one commit.
- **Planner and critic at max effort; builder and verifier at xhigh:** planning and review decisions are the expensive ones to get wrong. Building and running checks are the high-volume ones.
- **One dispatch for all four stages:** the run needs no human between stages. The cost is that the planner must close each stage fully, with a report and a frozen folder, before it starts the next.
- **Same-commit verdicts and frozen stages:** any product change after a PASS moves the verdict commit, and the proof reruns. No accepted folder was edited after its acceptance.
- **A workspace inside the repository** (`.work/<handle>/`, ignored by git): every seat's scratch files and check outputs stay in the repository, so no seat ever hits a permission prompt for a path outside it.
- **Plans first:** each stage opens with its plan. The critic's review of it runs alongside the first build and lands before any verdict. In return, most defects are found as criteria rather than as rework, though in stages 1 and 3 the review still sent written code back (`2ffcbe8`, `0acff74`).

## How it got here

This is the factory's third full run. Each earlier run had its own room and repository, and its lessons went into the standing instructions before the next one. BAND confirmed on Discord that a team may make several fresh runs and submit one.

- **Development run (v1), Sep 27:**
  - Room `30e52fd8`; all four stages accepted.
  - The critic stalled for 8 hours on a permission prompt, and nothing in the protocol noticed.
  - v2 added liveness (acks, one re-send after 20 minutes), the `.work/` workspace inside the repository, a 500k auto-compact window and one dispatch for the whole run.
- **Second run (v2), Sep 27–29:**
  - All four stages accepted, in 19 h 34 min of working time.
  - The machine had to travel, and the seats were paused for 14 h 14 min.
  - Tool activity filled the first room's 10,000-message limit in stage 3, and the planner moved the band to a second room.
  - 52 of the planner's commits used the machine's global git identity.
  - Review caught at least 12 defects. Several came from the same few causes, and those causes became v3's changes.
- **What v3 changed.** Every change is generic, so the instructions still name nothing about the product:
  - **Routing:** every HANDOFF and verdict goes to the planner too. The critic sends its points as one batch.
  - **Shared machine and clocks:**
    - container names and ports unique to each seat;
    - holds during verdict runs;
    - time marks taken from the service under test;
    - no verdict on a run that spans a pause.
  - **When the verdict commit moves:** test-only deltas carry the earlier results over.
  - **Room capacity:** the planner checks the room at every stage start.
  - **Commit identity:** each seat's git identity comes from its environment.
  - **Planner:**
    - look ahead to the next stage's specification;
    - state limits for every unbounded input up front;
    - check decisions against the specification's exact wording;
    - start the spec trace when the first suite lands;
    - re-read the specification before the last items are accepted.
  - **Verifier and critic:**
    - confirm each new test against the mutant it is for;
    - draft-run every test before posting a suite;
    - map every plan clause to code before mutating;
    - probe one level below each boundary.

| | v2 | v3 (submitted) |
|---|---|---|
| Dispatch to final report | 19 h 34 min of work, plus a 14 h 14 min pause | 12 h 26 min, no pause |
| Rooms | 2 (the first hit the 10,000-message limit) | 1 |
| Accepted stages reopened later | 1 (stage 3) | 0 |
| The band's commits under the seat's own name | 105 of 157 | 173 of 173 |
| List-price estimate to the final report, at Band's prices | about $649 (v2's own FACTORY.md says $510.61: Band had not yet logged its last 4 h 37 min) | about $412 |

The v1 and v2 seats' notes stay with those runs. This run's seats started with an empty memory, and the notes they wrote are in [`lessons/`](lessons/).

## What breaks without the room

Remove the room and nothing independent checks the builder. The verifier's tests and the critic's veto exist only as separate seats that read the builder's evidence and can stop it. In this run the critic's veto stopped an item 11 times, and its plan reviews changed the plan 4 times while the build was under way ([above](#what-it-caught-in-the-submitted-run)).

## Standing it up

[README.md](README.md) has the exact commands: four terminals, one room, one dispatch. Point [`tasks/run.md`](tasks/run.md) at another problem's specifications and checks, and nothing in `mandates/`, `PROTOCOL.md` or `CLAUDE.md` changes.
