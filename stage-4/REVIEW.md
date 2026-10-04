# Stage 4 review (critic-h6bj)

Each entry records one verdict: the commit, the verdict, the reason and the evidence I checked. My scratch work lives under `.work/critic-h6bj/`.

## Plan review: stage-4/PLAN.md @ 76b3707 (not a verdict)

I read the following against `stage-4/PLAN.md` at 76b3707:
- `stage-4.md` in full;
- the parts of `stage-3.md` that stage 4 builds on: revisions, `known_at`, statements, stable pagination, settlement history and historical holds;
- stage 1 §7, §10 and §11;
- the supplied checks `test/stage_4/test_sample.py`. No supplied check of stages 1 to 3 asserts a payment's exact key set, so `refund_of` on every payment breaks none of them.

I also read the stage-3 code the plan carries over, one level below its clauses:
- `stage-3/src/handlers/statement.ts`: how a snapshot page renders its entries;
- `stage-3/src/views.ts`: `paymentView`;
- `stage-3/src/snapshot.ts`: settlement membership on import, the snapshot record;
- stage-1 D18: the non-operator 403 before the key and the body.

Sent to the planner as one batch: 1 defect, 1 wording fix, 7 criteria to add, and polish recorded.

### Defect

1. **A saved statement from stage 3 does not keep its original form after the upgrade** (intro "saved statements must remain available in their original form", F3, F43, I65, I76, W21.2, W21.3).
   - Stage 3 says a snapshot "pages that exact result". Stage 4 adds that saved statements "remain available in their original form", and the service "must accept exports produced by the same team's stages 1–3, retaining ... snapshots".
   - A stage-3 snapshot stores a cutoff, and every page recomputes its entries. `statement.ts:82` renders each entry's `payment` as `{...paymentView(st, p), amount: <selected>}`.
   - Stage 4 adds `refund_of` to every payment representation (3.6). So the same token, paged after the import, returns entries whose `payment` objects carry `refund_of: null`. The stage-3 build never returned that field.
   - So a check that pages a stage-3 token before the export and again after the import, and compares the two bodies, fails. The comparison is the plain reading of "that exact result".
   - Within stage 4 nothing else moves. A page excludes refunds and batch revisions by the cutoff, and a payment's other fields never change. The `refund_of` field is the only difference.
   - Asked for:
     - Each snapshot keeps the payment form of the service that created it. A snapshot imported from a schema-3 state pages its entries' payments in the stage-3 form, without `refund_of`. A snapshot taken in stage 4 includes it.
     - The schema-4 export carries that form for each snapshot, so a stage-4 round trip keeps it. A stage-3 snapshot can hold no refund, so the stage-3 form only omits the field.
     - Criteria for W21.3 and W21.2: page a snapshot token on the frozen stage-3 build, export, import into stage 4, and page it again. The bodies are equal as JSON, `has_more` and `snapshot` included. The same holds after a further stage-4 export and import.

### Wording

2. 3.12 says that of two corrections naming one payment with the same `expected_revision`, "exactly one can succeed". I63 says "at most one succeeds": both can fail for other reasons, for example funds. Use I63's words.

### Criteria to add (one level below the boundaries the plan names)

3. **W20.7, combined funds at the boundary.**
   - A batch whose combined effect leaves a user's `available` at exactly 0 is accepted.
   - The same batch with one more minor unit is 409 `insufficient_funds`.
   - Build one case where an open hold makes that difference.
4. **W20.6 and D98, member instants at the precision boundary.**
   - Members whose `effective_at` values differ only by trailing fraction zeros (`…:00.5Z` against `…:00.500Z`) are one instant and are accepted.
   - Members 1 µs apart are 422 `validation_failed`.
   - The plan names only the `Z` against `+05:30` case.
5. **W20.7 and I58, one instant combined, with the debit created first.**
   - A batch moves a debit onto the instant of a credit that was created after it. At that instant the two combine to at least 0. Expect 201.
   - A case that dips below 0 only between two items' instants is 409 `historical_overdraft`.
   - Stage 3 needed exactly this test (K12): a sweep that takes one instant's events in creation order passes any case where the credit was created first.
6. **W20.5 and D81, no tolerance on a batch item's `effective_at`.**
   - An item whose `effective_at` is a fraction of a second after a fresh service time mark is 422. A 201 must not have `recorded_at` earlier than an item's `effective_at`.
   - Every batch revision has `effective_at` ≤ `recorded_at`.
   - This is stage 3's K25b one level below "later than now".
7. **W19.3 and W20.5, the cap follows a batch correction as well as a single one.**
   - A batch lowers P to exactly its refunded total and is accepted. A refund of 1 more is then 422 `refund_exceeds_payment`.
   - A batch item one minor unit below the refunded total is 422 `refund_exceeds_payment`.
8. **W20.4, the upper shape boundary.** A batch of 32 items is accepted. The plan names only 33 (refused).
9. **W19.4, a refund of a capture from a hold that is still open.**
   - After a nonfinal capture, the hold stays `open`. Its receiver refunds the capture.
   - The hold's `remaining_amount`, `captured_amount`, `payment_ids` and `closed_at` (null) are unchanged. The payer's `held` is unchanged. The hold's history at every instant is unchanged.
   - The plan's case names only a "captured" (closed) authorization.

### Checked and fine

- D89, refund amount: 1 to 1000000000, required, `1.0` and `1e3` valid. A refund body has no default, unlike a capture's.
- D90 and D94, the refund and correction orders. 403 comes before `invalid_refund_target`, as a non-sender's correction gets 403 before `linked_payment_immutable`. A refund of a refund by its own receiver reaches 422. The cap comes before the funds.
- D91, the refund's shape. `settlement_id` null follows from "refunds never change settlement membership".
- D92, the cap on the latest revision's amount, whatever `known_at` says.
- D93, holds and requests untouched.
- D95: 403 before the key and the body, as stage-1 D18 does for settlements. The shape covers every element before any item. Item errors come in input order, then completeness, then the instants rule, then funds, then the 2^53 guard, then history. That matches the specification's order.
- D96: operators may correct any payment. `GET /payments/{id}/revisions` stays party-only (stage-3 spec: "Only the two parties can read it"), so a non-party operator reads 404.
- D97, `correction_batch_id` only on batch revisions. Statement entries keep stage 3's fields (3.6, "Every other representation is unchanged").
- D98 and D100: members found by `settlement_id`; one issued `recorded_at` per batch, strictly later than everything before, also after an import.
- D99, combined affordability on `available`.
- D104, refunds need no history check. A refund's `created_at` is later than every effective time:
  - corrections take effect no later than their `now`;
  - seeded times are no later than the reset;
  - imported instants move the clock.

  So a refund changes balances only from now on, and a later hold event only raises `available`.
- D105 and 3.12: one synchronous check-and-commit per refund and per batch.
- D101 (fixtures unchanged) and D102 (schema 4; schemas 1 to 3 by stage 3's rules).
- 3.11's schema-4 validation list. A refund or a capture keeps one revision, since both are immutable. Settlement members may carry batch revisions.
- The trace: F1 to F43 cover every normative line of `stage-4.md`.

### Polish (recorded only)

- D103 keeps the UI unchanged, and the dispatch confirms it. A refund then shows in the feed as an ordinary payment from the original receiver, with the original note, so "Bob → Ada 2.00 dinner" reads like a new payment for dinner.
  - A small "Refund" label driven by `refund_of` would make the money movement clear. It would leave the tested elements (`activity-amount-*`, `activity-note-*`) exact.
  - Stage 4 names no UI state, so this is recorded, not asked for.
- Schema-4 import does not check that a batch which corrected a settlement member also corrected every other member at one instant. No export from this service can break that, and a state that did would still conserve money.

## W19 @ 2b3944a: BLOCKED

- Commit: `2b3944aa9a330c96588cf194fff05c72d99739b7`, the builder's HANDOFF W19. Its `src/` is 4484652's plus `src/handlers/refunds.ts`, which 4484652 left out. A `diff -r` of the two `git archive` trees shows it is byte for byte the tree I probed.
- Suite: `102889077cd7e2f64492f58e8dfcda03c2ee0ea9` (W22, first commit).
- Reason: 2b3944a meets the plan in every probe, and I found no product defect. But one plan rule has no test. In a scratch copy, a swap of refund steps 11 and 12 (3.9, D90) passes every acceptance test and every builder test.
- Missing evidence: a suite commit with a test that fails on RF18 below (verifier). No product change is needed. On that commit I rerun RF18; the other results carry over (PROTOCOL, "When the verdict commit moves").

### What I checked

1. **Every clause of the plan mapped to the code that enforces it.**
   - Refund steps (3.9):
     - step 1: `routes.ts:38`;
     - steps 2 to 5: `refunds.ts:13-16`, with the claimed key in `idempotency.ts:39-41`;
     - step 6: `refunds.ts:18`, `requireAmount`, an integral number from 1 to 1000000000 (`fields.ts:45-56`);
     - step 7: `refunds.ts:19-20`;
     - step 8, the receiver only: `refunds.ts:21`;
     - step 9: `refunds.ts:22`;
     - step 10, the cap on the latest revision's amount: `refunds.ts:23-27`;
     - step 11, `available`: `refunds.ts:31`;
     - step 12, the 2^53 guard on the target's sender: `refunds.ts:32-33`;
     - step 13, one synchronous commit: `refunds.ts:36-39`. `state.ts:301` adds the refund to its target's refunded total, and `idempotency.ts:43-44` stores the key.
   - I68: the note, visibility, null links and `refund_of` at `refunds.ts:37-38`; `refund_of` on every payment at `views.ts:26`.
   - Corrections (D94):
     - step 9 adds refunds: `corrections.ts:63`;
     - step 11: `corrections.ts:71`. It comes after `stale_revision` (`:67`) and before the funds (`:81`). Equal to the refunded total is allowed.
   - D101: `fixture.ts:296`, `refund_of` null on seeded payments.
   - 3.11, schemas 1 to 3: `snapshot.ts:244`, `refund_of` null on imported payments.
   - I77: a refund is an ordinary payment in `paymentsOf`, so `history.ts` (`totalIn`, `historyStaysCovered`) and `statementPage` count it.
   - Every clause has code. No product code special-cases a sample input, fixture id or expected output.
2. **Probes.** `probe_w19.py` makes 91 checks one level below the boundaries the plan names, including the critic plan review's open-hold case (9). On 2b3944a: "0 failed" (`log_probe_w19_2b3944a.txt`). Among them:
   - the step order at every pair of adjacent steps, with inputs that fail both;
   - refunds reaching the cap exactly, then one unit more;
   - exactly the available funds, and a hold that makes the difference;
   - the cap following a revision 3 that is effective earlier than revision 2 (D92);
   - one key with one body on two targets, and on `POST /payments`;
   - a failed refund leaving its key free;
   - 20 concurrent refunds with 20 distinct `created_at`;
   - the open, captured and voided holds unchanged after a refund;
   - snapshots with the default `to` and with a far-future `to`;
   - a later correction's history check counting a refund (D104);
   - concurrent refunds limited by the cap, by a racing correction and by the refunder's funds.
3. **Mutants.** 67 small changes, each in a scratch copy (`gen_mutants_s4_w19.py`, `mutants_s4_w19.json`). Each one fails at least one probe check (`log_probe_mut_w19_pre.txt`), so none is equivalent.
   - Acceptance, suite 1028890: `test_w19_refunds.py`, `test_w19_concurrency.py` and `test_w2_idempotency.py`, `--upto 19`, `-m "not container"`, two local servers.
     - The clean run: "196 passed, 15 deselected" (`rerun_logs_s4/CLEAN_W19_2b3944a.txt`).
     - 64 are killed. I read each failure for its reason with `classify.py`; logs are in `rerun_logs_s4/`.
     - Survivors: RF18, RH03, RV09.
   - Builder tests: `node --test test/*.test.ts` on a copy with the frozen stage folders linked beside it.
     - The clean run: "tests 220, pass 220".
     - 65 are killed (`rerun_logs_builder/`).
     - Survivors: RF18, RX03.
   - Of those survivors:
     - RH03 (later corrections' history checks ignore refunds) dies in `w19-refunds.test.ts:379`: "expected 409 historical_overdraft, got 201".
     - RV09 (imported payments without `refund_of`) dies in six builder export and import tests.
     - RX03 (the refund's funds read before an await) dies in `test_refunds_of_two_payments_racing_for_the_same_funds`: "I2/I30 violated during a burst".
     - Only RF18 survives both suites. It also passes the whole acceptance suite at `--upto 19`, `-m "not container"`: "2680 passed, 194 deselected in 683.33s" (`log_s4_w19_rf18full.txt`).
4. **The other mandate checks.**
   - Each refund checks and commits in one synchronous step. RX01 to RX03 (each check on a value read before an await) die.
   - Every refusal leaves state and the key unchanged. RF83 (a failed refund claims its key) dies.
   - `refunds.ts` imports only local modules.
   - The handoff names the export's schema 3 and the batch case of W19.3 as gaps for W20 and W21. I agree; they are not W19 points.

### The survivor and the missing test

**RF18, 3.9 refund steps 11 and 12 (D90): the funds come before the 2^53 guard.**
- Change: in `refunds.ts`, the guard (lines 32-33) moves above the funds check (line 31).
- Test: Ada, seeded at 2^53 − 60, pays Bob 100. Cy pays Ada 150, so Ada holds 2^53 − 10. Bob pays Dee 50, so Bob holds 50. Bob refunds 100:
  - it is above his available funds;
  - its credit would take Ada above 2^53;
  - expect 409 `insufficient_funds`. RF18 answers 422 `validation_failed`.
- `probe_w19.py`, "3.9 11 before 12: above available and over 2^53: 409", passes on 2b3944a and fails on RF18.
- The suite tests the guard alone (`test_the_2_53_guard_on_the_credit`) and the cap before the funds (`test_the_cap_comes_before_the_funds`). No test has a refund that fails both steps 11 and 12.

### Sent to the verifier with this verdict (suite 1028890, W20, not a W19 point)

On f4c2f9e, the clean run of `test_w20_batches.py`, `test_w20_concurrency.py` and `test_w2_idempotency.py` at `--upto 20` gives "2 failed, 289 passed" (`rerun_logs_s4/CLEAN_w20files_f4c2f9e.txt`). Both failures are expectations that contradict the plan; the product answers correctly.
- `test_a_batch_returns_one_revision_per_item_in_input_order` expects Cy at 550.
  - Cy starts at 500, receives 50 and pays 20, so Cy holds 530.
  - The batch moves +10 (p3 from 20 to 10) and −10 (p2 from 50 to 40), so Cy stays at 530. The service answers 530.
- `test_members_of_a_seeded_settlement` expects 201 for p_one (Cy to Dee, seeded, 10) corrected to 5.
  - Dee's seeded balance is 0. The correction debits Dee 5.
  - So 409 `insufficient_funds` is right (I74, D99), and the service answers that.

## W19 @ 2b3944a, suite 2f9c559: APPROVED

- Commit: `2b3944aa9a330c96588cf194fff05c72d99739b7`, the same commit as the BLOCKED entry above. No product code changed.
- Suite: `2f9c559d3b115636139619b801c11d99640d3caa` (W22.7). It changes tests only: `test_w16_corrections.py`, `test_w19_refunds.py` and `test_w20_batches.py`.
- Verifier: PASS at 2b3944a on suite 1028890. It carries over to 2f9c559 (PLAN.md, W19 row: the touched tests on 2b3944a gave "179 passed, 137 deselected").
- Reason: the one survivor, RF18, now fails a test for its reason. Every other result carries over (PROTOCOL: a tests-only commit, the critic reruns its survivors).

### What I reran

- Files: `test_w19_refunds.py`, `test_w19_concurrency.py`, `test_w16_corrections.py` and `test_w2_idempotency.py`, `--upto 19`, `-m "not container"`, two local servers. Logs are in `rerun_logs_s4_2f9c559/`.
- The clean run on 2b3944a: "318 passed, 15 deselected".
- RF18, the refund's 2^53 guard moved above the funds: "1 failed, 317 passed".
  - It fails in `test_the_guard_comes_after_the_403_the_cap_and_the_funds`: "expected 409 insufficient_funds, got 422 validation_failed ... the refund would take the payment's sender above 2^53".
  - That is its reason.
- I also made two mutants for the correction steps that W22.7 now tests (`mutants_s4_w19_extra.json`). Each fails for its reason:
  - RC07, correction steps 12 and 13 swapped, so the guard comes before the funds: `test_the_funds_come_before_the_guard`, "expected 409 insufficient_funds, got 422 validation_failed".
  - RC08, the guard moved after history: `test_the_guard_comes_before_history`, "expected 422 validation_failed, got 409 historical_overdraft".
- A third extra mutant ran on suite 1028890: RC06, a correction's debit judged on the total, not on `available` (W19.6, D53).
  - It fails in `test_a_correction_debit_is_judged_on_available`: "expected 409 insufficient_funds, got 409 historical_overdraft" (`rerun_logs_s4/RC06.txt`).
  - My probe has no case with a hold under a correction's debit, so it does not see RC06. The suite does.
- Probes: `probe_w19.py` now also checks correction steps 12/13 and 13/14 with inputs that fail both. On 2b3944a it makes 93 checks: "0 failed" (`log_probe_w19_2b3944a_v2.txt`). RC07 and RC08 each fail one of the new checks (`log_probe_mut_w19_extra.txt`).

### Result

- 70 mutants: the 67 above plus RC06 to RC08.
- Each one now fails at least one acceptance or builder test for its reason. None survives both suites.
- W19 at 2b3944a is APPROVED on suite 2f9c559.

## W20 @ 9948ff9: BLOCKED

- Commit: `9948ff97e99919ead98df10aa76b68dc956d8959`, the builder's HANDOFF W20, on top of W19 2b3944a.
- Suite: `2f9c559d3b115636139619b801c11d99640d3caa` (W22.7). The verifier's PASS is on this commit and suite. The next suite commit, 8dac300, changes only `test_w17_export.py`.
- Reason: 9948ff9 meets the plan in every probe, and I found no product defect. But the tests for one rule catch a break only when two writes happen to share a millisecond.
  - BR06 below breaks batch step 14 (D100, D67).
  - In one run it passes every W20 acceptance test. It also passes every builder test.
- Missing evidence: a suite commit with a test that fails on BR06 whatever the timing (verifier). No product change is needed. On that commit I rerun BR06; the other results carry over.

### What I checked

1. **Every clause of the plan mapped to the code that enforces it.**
   - Batch steps (3.9):
     - step 1: `routes.ts:40`;
     - step 2: `batches.ts:18`;
     - step 3, the 403 before the key and the body: `batches.ts:20`;
     - steps 4 to 6: `batches.ts:21-23`, with the key scoped by user, method and path (`idempotency.ts:37`);
     - step 7, the shape, over every element before any item: `batches.ts:29-41`;
     - step 8, each item in input order:
       - (a) `batches.ts:47-48`, through `correctionFields`, stage 3's field rules with no tolerance on `effective_at`;
       - (b) `:49-50`;
       - (c) captures and refunds only: `:51-53`;
       - (d) `:54-57`;
       - (e) `:58-60`, where equal to the refunded total is allowed;
       - there is no party check (D96);
     - step 9: `batches.ts:70-77`, through `st.membersOf`. That index is filled in `addPayment` (`state.ts:311`), which the API (`ledger.ts:37`), the fixture (`fixture.ts:296`) and import (`snapshot.ts:241`) all use (D98);
     - step 10: `batches.ts:78-86`, on exact instant keys;
     - step 11: `batches.ts:90-101`, each wallet's combined difference against `available` now;
     - step 12: `batches.ts:102-104`;
     - step 13: `batches.ts:107-112`, every party of every item with all proposed revisions together (`historyStaysCovered` takes a map, `history.ts:69`);
     - step 14: `batches.ts:115-131`:
       - one `issue` gives `recorded_at`;
       - a `cb_` id with 96 random bits, unique in the state (`state.ts:274-279`);
       - revision n + 1 per item, with the batch id;
       - the money moved;
       - the response in input order;
       - `idempotent` stores the key only after the step returns.
   - D97: `corrections.ts:27` adds `correction_batch_id` only to a revision a batch recorded.
   - A single correction of a settlement member is still 422 `linked_payment_immutable` (`corrections.ts:68`).
   - 3.12: the batch's checks and its commit run in one synchronous step.
   - Every clause has code. No product code special-cases a sample input, fixture id or expected output. `batches.ts` imports only local modules.
2. **Probes.** `probe_w20.py` makes 70 checks. On 9948ff9: "0 failed" (`log_probe_w20_9948ff9.txt`). Among them:
   - 32 items accepted and 33 refused;
   - member instants that differ only in trailing zeros, in `Z` and `+05:30`, and 1 µs apart;
   - `available` left at exactly 0, then one unit more, with a hold making the difference;
   - a debit created first, moved onto the instant of a credit created after it;
   - a dip between two items' instants;
   - every pair of adjacent steps, with inputs that fail both, including 11/12 and 12/13;
   - a replay after newer revisions;
   - 12 concurrent batches with 12 distinct `recorded_at`.
3. **Mutants.** 51 small changes (`gen_mutants_s4_w20.py`, plus BH05 in `mutants_s4_w20_extra.json`). Each one fails at least one probe check (`log_probe_mut_w20_v2.txt`).
   - Acceptance, suite 1028890: `test_w20_batches.py`, `test_w20_concurrency.py` and `test_w2_idempotency.py`, `--upto 20`, `-m "not container"`, with the two tests that contradicted the plan deselected.
     - 47 are killed. I read each failure for its reason (`classify.py`, `rerun_logs_s4/`).
     - Survivors: BF08, BC07, BR06, BH05.
   - Acceptance, suite 2f9c559, the same files with nothing deselected:
     - The clean run: "293 passed".
     - BF08 (the guard before the funds) fails `test_the_combined_funds_come_before_the_guard`: "expected 409 insufficient_funds, got 422 validation_failed".
     - BH05 (history before the guard) fails `test_the_guard_comes_before_history`: "expected 422 validation_failed, got 409 historical_overdraft".
     - BC07 (seeded members missed) fails `test_members_of_a_seeded_settlement`: "expected 422 incomplete_settlement, got 201".
     - BR06: see below. Logs are in `rerun_logs_s4_2f9c559/`.
   - Builder tests: the clean run gives "tests 243, pass 243". 43 are killed (`log_builder_w20_0.txt`).
     - Survivors: BI08, BI11, BC02, BF08, BH03, BR06, BR10, BH05.
     - Each of them except BR06 dies in the acceptance suite for its reason.
4. **The other mandate checks.**
   - Atomic: BX01 (expected revisions read before an await) dies, with two overlapping batches both 201, and 50 batches all 201.
   - A rejected batch changes nothing and claims no key: BR09 dies.
   - Keys are per path: BR10 dies in `test_same_key_on_the_ten_paths_is_independent`.
   - The handoff names one gap: exports stay schema 3 until W21, so a round trip drops `correction_batch_id`. I agree. It is W21's.

### The survivor and the missing test

**BR06, batch step 14 (D100, D67): `recorded_at` is the request's clock reading, not an issued timestamp.**
- Change: in `batches.ts:115`, `issue(st, now)` becomes `now.ts`. The clock never runs backwards, but a batch's `recorded_at` can then equal the timestamp of the write before it, and two batches in one millisecond share one.
- Passing output:
  - suite 1028890, the W20 files: "289 passed, 2 deselected in 52.62s" (`rerun_logs_s4/BR06.txt`). The four tests that caught BR06 on 2f9c559 are unchanged since 1028890, and so is `support.py`;
  - the builder tests: "tests 243, pass 243" (`rerun_logs_builder/BR06.txt`). That includes "gives two batches in one millisecond strictly increasing recorded_at", whose two batches landed in different milliseconds.
- On 2f9c559, the W20 files failed with BR06 in 13 of 13 runs, with one to three other test runs beside them.
  - Each run failed 1 to 4 tests, and every failure was two writes in one millisecond: I56 ("recorded_at values strictly increase"), or b1 < b2 < b3.
  - So the kill depends on timing, not on the rule. A slower host, or a container's longer round trip, makes the coincidence rarer.
- `probe_w20.py` fails on BR06 in 6 of 6 runs with "D100 12 concurrent batches: 12 distinct recorded_at". A burst reaches the service faster than one millisecond per request, whatever the round trip.
- A test that would close it: make 20 payments, then correct each one in its own batch, all 20 batches at once (`Service.burst`). Expect 20 distinct `recorded_at` values, each strictly later than its payment's `created_at`. Stage 3's 3.5 says "two writes never share a `created_at` or `recorded_at`" (D67), and D100 applies it to batches.
- The same pattern already exists for refunds:
  - The builder's test at `w19-refunds.test.ts:395` sends 50 concurrent refunds and asserts "one timestamp each".
  - RF46 makes the same change for refunds. It passed `test_w19_refunds.py` and `test_w19_concurrency.py` in 3 of 3 runs on 2f9c559 under load (`rerun_logs_s4_2f9c559/RF46r1-3.txt`).
  - That builder test kills RF46 in 6 of 6 runs for its reason (`log_builder_rf46.txt`), so the W19 count stands.
  - An acceptance burst for refunds would be cheap in the same commit, but W19 does not need it.

## W20 @ 9948ff9, suite da8d92b: APPROVED

- Commit: `9948ff97e99919ead98df10aa76b68dc956d8959`, the same commit as the BLOCKED entry above. No product code changed.
- Suite: `da8d92b92fbb5141895e10e722f942246dd893ca` (W22.8). It changes tests only: `test_w20_concurrency.py` and `test_w19_concurrency.py`. Its parent, 8dac300, changes only `test_w17_export.py`.
- Verifier: PASS at 9948ff9 on suite 2f9c559. It carries over to da8d92b, because the touched files pass on 9948ff9 ("10 passed").
- Reason: BR06, the one survivor, now fails a test for its reason in every run. The other results carry over (PROTOCOL: a tests-only commit, the critic reruns its survivors).

### What I reran

- The clean run on 9948ff9, with `test_w20_batches.py`, `test_w20_concurrency.py` and `test_w2_idempotency.py` at `--upto 20`, `-m "not container"`: "294 passed" (`rerun_logs_s4_da8d92b/`).
- BR06 (`batches.ts:115`, `issue(st, now)` replaced by `now.ts`) failed in 6 of 6 runs, while two W21 mutation runs, a builder-test run and the verifier's container run shared the machine.
  - Once on the three files: "3 failed, 291 passed".
  - Five times on `test_w20_concurrency.py`: 1 or 2 failed each time.
  - Every run fails `test_twenty_batches_at_once_each_get_their_own_recorded_at`: "batches share a recorded_at". Only 7 to 10 of the 20 `recorded_at` values were distinct, so the test has a wide margin.
- RF46 (the refund's `created_at` not issued) failed `test_twenty_refunds_at_once_each_get_their_own_created_at` in 3 of 3 runs on 2b3944a at `--upto 19`: "refunds share a created_at", with 6 or 7 of 20 distinct. The clean run gave "4 passed". So the acceptance suite now also kills it, as well as the builder test.

### Result

- 51 mutants. Each one fails at least one acceptance test for its reason, and BR06's kill no longer depends on timing.
- W20 at 9948ff9 is APPROVED on suite da8d92b.

## W21 @ 328508d: BLOCKED

- Commit: `328508d01e35040e46f6d76317cc3c9c258453b0`, the builder's HANDOFF W21. It is the W21 product, f4c2f9e, plus a builder-test fix; its `src/` is byte for byte f4c2f9e's.
- Suites:
  - the export files on 8dac300;
  - the upgrade files on 2f9c559. They are unchanged through da8d92b, the suite of the verifier's W21 run.
- Reason: 328508d meets the plan in every probe, and I found no product defect. But two schema-4 import rules have no test. An import that accepts a payment without `refund_of`, or a revision without `correction_batch_id`, as if the field were null passes every acceptance and builder test.
- Missing evidence: a suite commit with tests that fail on VA14 and VA15 below (verifier). No product change is needed. On that commit I rerun VA14 and VA15; the other results carry over.

### What I checked

1. **Every clause of the plan mapped to the code that enforces it** (`snapshot.ts` and `statement.ts` at 328508d).
   - Export (3.11, W21.1):
     - schema 4: `snapshot.ts:27`;
     - `refund_of`: `:54`;
     - `correction_batch_id` on every revision: `:57`;
     - each snapshot's `payment_form`: `:84`;
     - the idempotency records of every path, the two new ones included: `:86`;
     - built in one synchronous function.
   - Import (3.11, W21.2, W21.3):
     - schemas 1 to 4: `:198-201`;
     - schemas 1 to 3 import by stage 3's rules: `refund_of` null (`:273`), no batch ids (`revisionsOf` gets no batch map), and their snapshots in form 3 (`:423`).
   - Schema-4 validation (3.11, W21.4):
     - `refund_of` is null or a string (`:264`). It must name an earlier payment that is not a refund (`:286-287`), with the parties reversed (`:288-289`). A refund links to no request, authorization or settlement (`:290-291`);
     - a refund or a capture has one revision: `:277-279`;
     - each payment's refunded total is at most its latest amount: `:295-297`;
     - one batch id has one `recorded_at` (`:175`), at most one revision per payment (`:176`), and never revision 1 (`:169`);
     - `payment_form` is 3 or 4: `:419`;
     - idempotency records of any path are taken as stored: `:427-438`.
   - After an import, these are rebuilt: refunded totals (`:293`), settlement members (`addPayment`), batch ids (`:299`) and the clock (`:217-223`).
   - D106: `statement.ts:55` makes new snapshots form 4. `:85` drops `refund_of` from a form-3 snapshot's payments.
   - RUN.md (W21.5) covers the image and paths, `npm test`, the acceptance suite and the supplied checks with `--stage 4`. It names the repository root the same way stage 3's did.
   - Every clause has code. No product code special-cases a sample input, fixture id or expected output. `snapshot.ts` imports only local modules.
2. **Probes.** `probe_w21.py` makes 42 checks. On 328508d: "0 failed" (`log_probe_w21_328508d_v2.txt`). Among them:
   - the round trip in one process and into a second;
   - the D106 upgrade through the frozen stage-3 build, with a token paged before and after;
   - every W21.4 invalid state;
   - one level below them, the missing-field cases: `refund_of`, and `correction_batch_id` on a revision 1 and on a batch revision.
3. **Mutants.** 27 small changes (`gen_mutants_s4_w21.py`, plus VA15 in `mutants_s4_w21_extra.json`).
   - Each fails a probe check except VA10, which is equivalent. A second revision of one batch on one payment always fails the shared-`recorded_at` check first (`:175` before `:176`), because a payment's `recorded_at` values strictly increase.
   - Acceptance, `--upto 21`, `-m "not container"`:
     - the export files on 8dac300 (`test_w21_export.py`, `test_w5_export_import.py`, `test_w8_export_import.py`, `test_w17_export.py`): clean "111 passed";
     - the upgrade files on 2f9c559 (`test_w21_upgrade.py`, `test_w17_upgrade.py`, `test_w8_upgrade.py`), run one at a time against the frozen stage-1 to stage-3 services: clean "25 passed";
     - 21 are killed. I read each failure for its reason (`rerun_logs_s4_8dac300/`, `rerun_logs_s4_2f9c559/*_B.txt`). Each VA mutant fails exactly its own case of `test_rejected_schema_4_import_changes_nothing`;
     - survivors: VA05, VA10, VA11, VA12, VA14, VA15;
     - on 2f9c559, the clean run of the export files was "1 failed, 110 passed". The failure is the schema-3 probe the verifier fixed in 8dac300. I counted that test for no mutant.
   - Builder tests at 328508d:
     - the clean run: "tests 248, pass 248";
     - 24 are killed. VA05, VA11 and VA12 die in `w21-export.test.ts:251` ("are 422 and change nothing"). Each of them removes one check, so the 204 can only come from that check's own case;
     - survivors: VA10, VA14, VA15.
4. **The other mandate checks.** The export runs in one synchronous step. An import validates the whole state before it replaces the old one, so a rejected import changes nothing (W21.4, tested for every case above).

### The survivors and the missing tests

**VA14 (3.11): a schema-4 payment without a `refund_of` field is accepted as if `refund_of` were null.**
- Change: `snapshot.ts:264` also accepts a missing field (`p.refund_of === undefined || isRef(p.refund_of)`), and `:276` and `:277` compare with `!= null` and `== null`.
- The rule: 3.11 says the schema-4 state "holds everything of schema 3 plus each payment's `refund_of`", and schema-4 validation requires that `refund_of` "is null or names an earlier payment". A payment without the field fails full validation: 422, with nothing changed.
- Passing output:
  - the export files on 8dac300: "111 passed";
  - the upgrade files: "25 passed";
  - the builder tests: "tests 248, pass 248".
- `probe_w21.py`, "W21.4 a schema-4 payment without refund_of: 422 and nothing changed", passes on 328508d and fails on VA14 (204).
- The suite's cases set `refund_of` to an unknown payment, a refund or a later payment, and the builder's set it to 5. None removes it.

**VA15 (3.11): a schema-4 revision without a `correction_batch_id` field is accepted as if the field were null.**
- Change: `snapshot.ts:169`, `o.correction_batch_id === null`, becomes `== null`; `:171` falls back with `?? null`.
- The rule: 3.11 says the state holds "each revision's `correction_batch_id` (null when no batch recorded it)".
- Under VA15, a batch revision without its id imports as an ordinary correction, and the batch silently loses that member.
- Passing output:
  - the export files on 8dac300: "111 passed";
  - the upgrade files: "25 passed";
  - the builder tests: "tests 248, pass 248".
- `probe_w21.py`, "a schema-4 batch revision without correction_batch_id" and "a schema-4 revision 1 without correction_batch_id", pass on 328508d and fail on VA15 (204).

**Tests that would close both.** Start from a schema-4 export that holds a refund and a batch, and make three imports, each expected to be 422 with nothing changed:
1. without `refund_of` on one payment;
2. without `correction_batch_id` on a batch revision;
3. without `correction_batch_id` on a revision 1.
