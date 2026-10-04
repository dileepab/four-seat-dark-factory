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
