# Stage 4 plan — Pocketful: refunds and batch corrections

Owner: planner (`planner-h6bf`). Repository: `/Users/Dileepa/dark-factory-v3`, folder `stage-4/`, which started as a copy of the accepted `stage-3/` (`scripts/new-stage.sh 4`, commit 39ac9fa).
Specification: `/Users/Dileepa/df-spec/pocketful/spec/stage-4.md`, plus every part of `stage-1.md`, `stage-2.md` and `stage-3.md` that stage 4 does not change. All four are pasted verbatim into the handoff.
Supplied checks (a partial sample, about 16% of the graded stage-4 checks, used only to wire the service up): `/Users/Dileepa/df-spec/pocketful/test/stage_4/`. The stage-1, stage-2 and stage-3 checks also run against this folder.
Frozen references: `stage-1/` (accepted at 4baf8d9), `stage-2/` (accepted at f9eed3a) and `stage-3/` (accepted at 478ad72), each with its `PLAN.md`. Never edit them. Building them read-only, for example as the previous services in the upgrade tests, is fine.

## Status

| Item | Owner | Title | State | Commit |
|---|---|---|---|---|
| W19 | builder | Refunds: `POST /payments/{id}/refunds`, `refund_of` on every payment, corrections bounded by refunds | HANDED_OFF (2b3944a, by 16:40Z; 4484652 left out two new files) | 2b3944a |
| W20 | builder | Batch corrections: `POST /correction-batches`, settlement members, combined funds and history | BUILDING (9948ff9) | 9948ff9 |
| W21 | builder | Export schema 4; import of stage-1, stage-2, stage-3 and stage-4 exports; RUN.md | BUILDING (f4c2f9e) | f4c2f9e |
| W22 | verifier | Stage-4 acceptance suite: stage-1 to stage-3 regression, refunds, batches, upgrade | BUILDING (first suite 1028890 at 16:23Z; trace F1-F43 filled from it at 16:25Z, every row has tests) | 1028890 |

Item numbers continue from stage 3 (W1–W18). States: PLANNED, BUILDING, HANDED_OFF, VERIFIED or FAILED, APPROVED or BLOCKED, ACCEPTED.

## 0. How this stage runs

- The builder takes W19 to W21 in order and hands off each one as soon as its gate is green, then starts the next. The verifier writes W22 at once from this plan and the specification, without reading the implementation. The critic reviews this plan now (one batch), then each handoff.
- Routing, as in stages 1 to 3. Builder: `HANDOFF Wn` to the verifier, the critic and the planner. Verifier: PASS or FAIL to the critic and the planner, and to the builder on FAIL. Critic: APPROVED or BLOCKED to the planner, and to the builder on BLOCKED. The planner marks an item ACCEPTED when a PASS and an APPROVED name the same commit. Questions go to the planner, who decides.
- A verdict covers the item handed off plus every earlier item. For Wn the verdict run is: the offline build and run, the builder's tests, every acceptance test marked for W1 to Wn (the stage-1 to stage-3 regression tests carry items 1 to 18 and always run), and the supplied checks for stages 1 to 4. Supplied stage-4 checks that need a later item are expected failures, listed by name in the verdict (at W19: `test_operator_can_correct_a_payment_in_a_batch` and `test_a_batch_needs_a_settlement_operator`); every other failure counts. From W21 on, everything counts.
- Check command (a new `--out` every run; seat letters b builder, v verifier, c critic, p planner). The harness also builds the frozen earlier stages as the previous services for the upgrade checks:
  `/Users/Dileepa/dark-factory-v3/scripts/harness.sh run --track pocketful --repo <repo or worktree> --stage 4 --out /Users/Dileepa/dark-factory-v3/.work/checks/s4-<letter><nn>`
- Final check (verifier, on the final commit, main repository, clean tree):
  `/Users/Dileepa/dark-factory-v3/scripts/harness.sh run --track pocketful --repo /Users/Dileepa/dark-factory-v3 --stage 4 --mode isolated --out /Users/Dileepa/dark-factory-v3/.work/checks/s4-final-<nn>`
  The target line is `claimed stage: 4 on the shipped checks`. Stage 4 is the last stage, so no overshoot probe runs.
- The acceptance suite uses the harness venv's interpreter, `~/df-spec/.venv/bin/python`, as before. The stage-2 browser tests keep running as regression tests: the UI does not change in this stage (D103), so the full browser pass at 375 and 1280 is required at the W21 verdict and the final run; earlier verdicts may run it at one width.
- Verdict runs use a clean worktree of the named commit: `git -C /Users/Dileepa/dark-factory-v3 worktree add /Users/Dileepa/dark-factory-v3/.work/<handle>/wt-<short-hash> <commit>`, passed as `--repo`.
- Offline check (D2): `docker build --network=none -t pf-<seat>-s4 <path>/stage-4`, then `docker run -d --name pf-<seat>-s4 --network=none pf-<seat>-s4`, then `docker exec pf-<seat>-s4 node -e "fetch('http://127.0.0.1:8080/health').then(r=>r.text()).then(console.log)"`.
- Shared machine: container names `pf-<seat>-…`; host ports builder 18100–18199, verifier 18200–18299, critic 18300–18399, planner 18400–18499. Before a verdict run the verifier asks the other seats to start no container runs until the verdict is posted.
- Time marks in tests come from the service (`created_at`, `recorded_at`, `expires_at`), never from the host clock (protocol, "Shared machine and clocks").
- Commits: only your own paths, `git commit -m "<message>" -- <paths>`; never `git add -A` or `git commit -a`; if `.git/index.lock` exists, wait and retry. Never amend, rebase or force-push. Scratch files go under `.work/<your handle>/`.
- Room: this stage runs in room 7884df0c-298f-4120-abce-f6bef24337b9, as stages 1 to 3 did (D88).

## 1. Scope

Stage 4 is the last stage of the track, so nothing later constrains its outputs and no overshoot probe runs. Everything stages 1 to 3 promise still holds; this stage adds two idempotent write paths (refunds and correction batches), one field on every payment (`refund_of`), one field on revisions recorded by a batch (`correction_batch_id`), three error codes, and export schema 4.

## 2. Invariants

Each one is a check a test can perform. "Every read" includes reads taken during a concurrent burst. Stage 3's I1–I67 still hold, amended where marked; I68–I77 are new.

- **I1 Conservation (amended).** As stage 3, refunds and correction batches included: after every operation, and in every historical view, the sum of `total` over all users equals the total seeded by the last reset (after an import, the total in the imported state).
- **I2 Non-negative (amended).** As stage 3: no current read shows a negative `total`, `available` or `held`, and no accepted refund or batch creates a negative current value, or, for a consistent seeded history, a negative historical `total` or `available`.
- **I15–I19 Idempotency (amended).** As stage 3, on ten paths: stage 1's five, `POST /authorizations`, `POST /authorizations/{id}/capture`, `POST /payments/{id}/corrections`, `POST /payments/{id}/refunds` and `POST /correction-batches`.
- **I25 Reset and import atomicity (amended).** As stage 3, with schema 4: a rejected reset or import changes nothing; an accepted one replaces all state, refunds and batch revisions included.
- **I26 Export snapshot (amended).** As stage 3, and the export includes every refund link, every batch id on a revision and the keys of the two new paths.
- **I56 Revision history (amended).** As stage 3. A correction batch appends revision n + 1 to each payment it names; that revision carries `correction_batch_id`. Every other revision keeps stage 3's six fields.
- **I57 Correction money (amended).** As stage 3, for single corrections and for batches: an accepted batch moves every item's difference between that payment's two wallets, all in one step. A rejected one changes nothing and claims no key.
- **I58 Historical overdraft (amended).** As stage 3, with a batch's new revisions all applied together.
- **I62 Immutable payments (amended).** A capture (non-null `authorization_id`) or a refund (non-null `refund_of`) can never be corrected, alone or in a batch: 422 `linked_payment_immutable`. A settlement member (non-null `settlement_id`) cannot be corrected alone (422 `linked_payment_immutable`); a batch may correct it together with every other member of its settlement.
- **I63 Concurrent corrections (amended).** Of corrections (single or batch) that run concurrently and name the same payment with the same `expected_revision`, at most one succeeds; the others are 409 `stale_revision`, or a 200 replay when one repeats the winner's key and body.
- **I65 Upgrade (amended).** Unchanged exports from the frozen stage-1, stage-2 and stage-3 builds import into stage 4 with 204. Settlement membership, revisions (corrections), snapshots (their tokens page their frozen entries), keys, tokens and logins all survive; every imported payment has `refund_of: null`; refunds and batches work on imported payments. A stage-4 export round-trips with refunds and batch revisions.
- **I66 Earlier behaviour (amended).** Every stage-1, stage-2 and stage-3 check still passes, the stage-2 UI included. The only changes to existing representations are `refund_of` on every payment and `correction_batch_id` on revisions recorded by a batch.
- **I68 Refund shape.** A refund of payment P is a new payment from P's receiver to P's sender: `amount` as requested, `refund_of` = P's `payment_id`, `request_id`, `authorization_id` and `settlement_id` null, P's `note` and `visibility`, `currency` the service's, `created_at` issued by the service. Every other payment has `refund_of: null`, in every representation the service builds.
- **I69 Refund cap.** For every payment P, the sum of the amounts of its refunds never exceeds the amount of P's latest revision. A refund that would break this is 422 `refund_exceeds_payment`; so is a correction (single or batch item) whose new amount is below P's refunded total.
- **I70 Refund money.** An accepted refund moves exactly its amount from P's receiver to P's sender in one step, judged on the receiver's current `available` (409 `insufficient_funds` otherwise). It changes no request, authorization or hold: a paid request stays paid with its `payment_id`; an authorization keeps its status, `captured_amount`, `remaining_amount`, `closed_at` and `payment_ids`; a released hold stays released. A rejected refund changes nothing and claims no key.
- **I71 Refund rights and targets.** Only P's receiver may refund P (anyone else 403 `forbidden`); an unknown payment is 404. P may be a direct payment, a request payment, a capture, a settlement member or a seeded payment, but never a refund (422 `invalid_refund_target`).
- **I72 Batch result.** An accepted batch returns 201 `{"correction_batch_id", "recorded_at", "revisions"}` with one revision per item in input order. Every new revision carries the batch's `correction_batch_id` and the batch's `recorded_at`, one instant strictly later than every earlier `recorded_at` of those payments. A rejected batch leaves revisions, balances, statements and idempotency records unchanged.
- **I73 Batch settlements.** A batch that names any member of a settlement names every member of that settlement (422 `incomplete_settlement` otherwise), and gives them all the same effective instant, compared as instants whatever the spelling (422 `validation_failed` otherwise).
- **I74 Batch funds.** A batch is affordable when, with every item's difference applied together, every user's current `available` is at least 0 (409 `insufficient_funds` otherwise); then the history check of I58 runs with all its new revisions together (409 `historical_overdraft`).
- **I75 Originals stay.** Refunds and batches never change an existing payment representation, a feed item, a settlement or its replay, a request, an authorization, or any stored idempotent response. Settlement membership never changes: a refund of a member is not a member.
- **I76 Snapshots after refunds and batches.** A statement snapshot taken before a refund or a batch pages exactly its frozen entries and balances afterwards; new statements show the refund as an entry and the batch's revisions as the selected revisions. A snapshot keeps the payment form of the service that made it: one imported from a stage-3 export pages its entries without `refund_of`, exactly as the stage-3 build paged them (D106).
- **I77 Refunds are payments.** A refund appears in `GET /activity` under the feed rule with P's visibility, in both parties' statements (negative `delta` for its sender), in `GET /payments/{id}/revisions` (revision 1 at its `created_at`, to its two parties) and in every historical view from its `created_at`.

## 3. Interface contract

Stage 3's contract (`stage-3/PLAN.md` section 3, which builds on the contracts of stages 1 and 2) applies unchanged except where this section amends it. Amended or new text is marked (S4).

### 3.1 Runtime

- As stage 3, with `stage-4/Dockerfile` and build context `stage-4/`. (S4) The Dockerfile's comment names stage 4.

### 3.2 Transport and parsing

- As stage 3. The path parameter of `/payments/{id}/refunds` is decoded like the other payment routes; `/correction-batches` takes no parameter.

### 3.3 Error codes (S4: complete for stage 4)

Stage 3's codes plus: 422 `refund_exceeds_payment`, 422 `invalid_refund_target`, 422 `incomplete_settlement`.

### 3.4 Instants

- As stage 3 (D66). A batch item's `effective_at` follows the correction rules: the grammar, at or before the operation's `now`, stored and returned exactly as written.

### 3.5 Time (S4)

- As stage 3 (D67). (S4) A refund is a write that issues one timestamp, its `created_at`. A batch is a write that issues one timestamp, the `recorded_at` shared by all its new revisions; since every issued timestamp is later than the previous one, it is later than every earlier `recorded_at` of every payment in the batch (D100).

### 3.6 Representations (S4)

- Payment: stage 3's thirteen fields plus `refund_of` (D91): the target's `payment_id` for a refund, null for every other payment. Outside a statement a payment still shows its original amount (revision 1). A stored replay body is returned verbatim, so a body stored before stage 4 (in an imported state) has no `refund_of` (D54). (S4) A statement snapshot pages its entries' payments in the form of the service that made it: a snapshot imported from a schema-3 state shows stage 3's thirteen fields (no `refund_of`), and a snapshot made by stage 4 shows `refund_of` as well (D106).
- Revision: stage 3's six fields. (S4) A revision recorded by a correction batch also carries `correction_batch_id`, in the batch response, its replays and `GET /payments/{id}/revisions` (D97).
- Correction batch: `{"correction_batch_id", "recorded_at", "revisions"}`, `revisions` in input order. The id is new, unique in the state, with the prefix `cb_`.
- Every other representation is unchanged, apart from the payments it contains.

### 3.7 Ledger model (S4)

- As stage 3. (S4) A refund is a payment like any other: revision 1 at its `created_at`, moving its amount from the target's receiver to the target's sender. It takes part in every view, statement and history check. It never gets a revision 2.
- The refunded total of a payment P is the sum of the amounts of the payments whose `refund_of` is P. Refunds are never corrected, so it only grows. The cap (I69): P's refunded total is at most the amount of P's latest revision (its current corrected amount, whatever its `effective_at`; `known_at` plays no part) (D92).
- The members of a settlement are the payments whose `settlement_id` equals its id, whether created by the API, seeded or imported (D75, D98). A refund always has `settlement_id: null`.

### 3.8 Historical holds

- As stage 3. Refunds and batches never change a hold, so they change nothing in section 3.8 (D93).

### 3.9 Endpoints (S4 changes and additions)

`POST /payments/{id}/refunds` (idempotent; the ninth path) `{"amount"}`. Precedence, the first failing step answers (D90):

1. Route 404 (an unknown method or path). 2. 401. 3. Key: missing or empty 400 `missing_idempotency_key`, over 255 characters 422. 4. Body: over the size limit 422; unparseable, invalid text or not an object 400. 5. A claimed key: same body 200 with the stored refund payment, a different body 409 `idempotency_key_reuse`. 6. `amount` missing, `null`, not an integral number (booleans and strings are not numbers), below 1 or above 1000000000: 422 `validation_failed` (D89). Unknown fields are ignored. 7. Unknown payment 404. 8. The caller is not the payment's receiver (its sender or anyone else) 403 `forbidden`. 9. The payment is a refund 422 `invalid_refund_target`. 10. The payment's refunded total plus `amount` is above the amount of its latest revision 422 `refund_exceeds_payment`. 11. `amount` is above the caller's current `available` 409 `insufficient_funds`. 12. The credit would put the payment's sender's `total` above 2^53 422 `validation_failed` (D19). 13. Commit, in one synchronous step: the refund payment (section 3.6) with one issued `created_at` and revision 1, the money moved, the key stored with the 201 body. 201 Payment.

`POST /payments/{id}/corrections` (amended, D94). Steps 1 to 8 as stage 3. Then: 9. A capture, a settlement member or a refund 422 `linked_payment_immutable`. 10. `expected_revision` is not the latest revision 409 `stale_revision`. 11. (S4) `amount` is below the payment's refunded total 422 `refund_exceeds_payment` (equal is allowed). 12. The debit is above the debited party's current `available` 409 `insufficient_funds`. 13. The 2^53 guard 422. 14. History 409 `historical_overdraft`. 15. Commit, as stage 3. 201 Revision (six fields).

`POST /correction-batches` (idempotent; the tenth path) `{"corrections": [{"payment_id", "expected_revision", "amount", "effective_at", "reason"}, ...]}`. Precedence, the first failing step answers (D95):

1. Route 404. 2. 401. 3. The caller is not in `settlement_operator_ids` 403 `forbidden`, checked before the key and the body, as for `POST /settlements`. 4. Key: missing or empty 400, over 255 characters 422. 5. Body: over the size limit 422; unparseable, invalid text or not an object 400. 6. A claimed key: same body 200 with the stored batch, a different body 409 `idempotency_key_reuse`. 7. Shape, 422 `validation_failed`: `corrections` missing, not an array, empty, longer than 32, an element that is not an object, or two elements whose `payment_id` values are the same string. This check covers every element before any item is examined (as D37 for settlements). Unknown top-level fields are ignored. 8. Each item in input order; the first item with any error answers. Within an item: (a) `payment_id` not a string, or `expected_revision`, `amount`, `effective_at` or `reason` failing the correction field rules (stage 3, section 3.9 step 6): 422 `validation_failed`; (b) unknown payment 404 `not_found`; (c) a capture or a refund 422 `linked_payment_immutable`; (d) `expected_revision` is not the payment's latest revision 409 `stale_revision`; (e) `amount` below the payment's refunded total 422 `refund_exceeds_payment`. Unknown item fields are ignored. 9. A settlement has a member in the batch and another member not in it 422 `incomplete_settlement`. 10. Two members of one settlement whose `effective_at` values are not the same instant 422 `validation_failed` (D98). 11. With every item's difference applied together, some user's current `available` would be below 0 409 `insufficient_funds` (D99). 12. Some user's `total` would be above 2^53 422 `validation_failed`. 13. With every new revision applied together, some party's `total` or `available` is below 0 at some instant up to now at which one of their payments takes effect or one of their holds changes (stage 3, section 3.8; all movements at one instant combined) 409 `historical_overdraft`. 14. Commit, in one synchronous step: one issued timestamp as `recorded_at`; for each item, revision n + 1 with its `amount`, `effective_at` as sent, `reason`, that `recorded_at` and the batch's id; every difference moved; the key stored with the 201 body. 201 Correction batch.

- A settlement operator may name any payment, whatever its parties and visibility (D96). `GET /payments/{id}/revisions` stays as stage 3: the payment's two parties only, so an operator who is not a party reads it as 404.

Unchanged: every other endpoint, except that the payments they return carry `refund_of`.

### 3.10 Reset

- As stage 3. The fixture format does not change: seeded payments are never refunds (`refund_of: null`), and a `refund_of` or `correction_batch_id` field in a fixture is ignored like any unknown field (D101).

### 3.11 Export and import (S4, D102)

- `GET /_test/export`: `"schema": 4`. The state holds everything of schema 3 plus each payment's `refund_of`, each revision's `correction_batch_id` (null when no batch recorded it), each snapshot's payment form (3 or 4, D106), and the idempotency records of the two new paths like every other path's. Built in one synchronous step.
- `POST /_test/import` accepts `schema` 1, 2, 3 and 4; anything else, or a state that fails full validation, is 422 with nothing changed. Schemas 1, 2 and 3 import by their stage-3 rules, with `refund_of: null` on every payment, no batch ids, and every snapshot of a schema-3 state in the stage-3 form (D106).
- Schema-4 validation adds to schema 3's: `refund_of` is null or names an earlier payment (lower creation sequence) that is not itself a refund, with the refund's sender and receiver that payment's receiver and sender; a refund has `request_id`, `authorization_id` and `settlement_id` null, and a refund or a capture has exactly one revision; every payment's refunded total is at most its latest revision's amount; the revisions that carry one `correction_batch_id` share one `recorded_at`, and a payment has at most one revision per batch id.
- After an import: refunds keep counting toward the cap; refund and batch replays return their stored bodies; snapshot tokens page exactly as in the source, in the payment form of the service that made them; everything stage 3 promised after an import still holds.

### 3.12 Concurrency model

- As stage 3. (S4) A refund checks its target, the cap and the funds and commits in one synchronous step, so concurrent refunds of one payment never exceed the cap together. A batch checks every item, the settlements, the funds and the history and commits in one synchronous step, so of two corrections (single or batch) naming one payment with the same `expected_revision`, at most one succeeds (D105); both may fail for other reasons, such as funds (critic plan review 2).

### 3.13 UI

- Unchanged (D103). The stage-2 UI keeps working: the wallet shows the current corrected `total`, `available` and `held` from `GET /me`; the feed shows refunds as the payments they are.

### 3.14 Limits (S4)

- Refund `amount`: 1 to 1000000000. A batch: 1 to 32 items, each within the correction limits of stage 3. Refunds per payment are bounded by the cap; each one needs its own key and moves money.

## 4. Work items

### W19 Refunds (builder)

Specification: stage-4 introduction, "Refunds and corrected history", the refund sentence of the last section. Invariants: I1, I2, I15–I19, I62, I66, I68–I71, I75–I77.

- W19.1 `POST /payments/{id}/refunds`: 201 Payment per I68; it is later than every earlier timestamp; `GET /activity` shows it under the feed rule with the target's visibility; a replay 200 with the original body, also after later refunds and corrections; the key rules of the ninth path (stage 1's scenarios: missing key, over 255, reuse with another body, a failed refund claims nothing, keys scoped by user and path).
- W19.2 Precedence per section 3.9: `amount` missing, `null`, `true`, `"5"`, `1.5`, `0`, `-1`, `1000000001` 422 (`1.0` and `1e3` valid); unknown payment 404; the payment's sender and a third party 403; a refund as the target 422 `invalid_refund_target`; refunds that would together exceed the latest revision's amount 422 `refund_exceeds_payment` (exactly reaching it is accepted, one more is refused); `amount` above the caller's `available` 409 (held funds count as unavailable); the 2^53 guard. Each refusal changes nothing and leaves the key free.
- W19.3 Targets: a direct payment, a request payment, a capture, a settlement member and a seeded payment are refundable by their receiver; the cap follows the current corrected amount: after a correction down, only up to the new amount; after a correction to 0, nothing. After a batch lowers P to exactly its refunded total, a refund of 1 is 422 `refund_exceeds_payment` (critic plan review 7).
- W19.4 Side effects (I70, I75): the paid request stays `paid` with its `payment_id`; the captured authorization keeps status, `captured_amount`, `remaining_amount`, `closed_at` and `payment_ids`; a voided or expired hold stays released and `held` does not change; the settlement's members, its replay and the refunded payment's representation (feed, replays, revisions) are unchanged; the refund has `settlement_id: null`. A refund of a nonfinal capture while its hold is still open leaves the authorization's `remaining_amount`, `captured_amount` and `payment_ids` unchanged and its `closed_at` null, the payer's `held` unchanged, and the hold's history (section 3.8) unchanged (critic plan review 9).
- W19.5 `refund_of: null` on every other payment: `POST /payments`, request payments, settlement members, captures, seeded payments, imported payments, the feed, statement entries and stage-4 replays.
- W19.6 Single corrections (D94): a refund 422 `linked_payment_immutable`, as captures and settlement members still are; an amount below the refunded total 422 `refund_exceeds_payment`, equal accepted; the step order (after `stale_revision`, before `insufficient_funds`); correction debits judged on `available`.
- W19.7 History (I77, I76): a refund's revision 1 at its `created_at` for its two parties; statements with the refund as an entry (negative `delta` for its sender); `GET /me?as_of` one microsecond before and at its `created_at`; `known_at` before it leaves it out; a snapshot taken before a refund pages unchanged.
- W19.8 Concurrency: 50 concurrent refunds of one payment whose amounts sum above the cap: the accepted ones sum to at most the cap and money is conserved; refunds racing a correction that lowers the amount never break the cap.
- W19.9 Gate: `npm test` (with builder tests for the refund rules and the cap), the newest acceptance suite, the supplied checks for stages 1 to 4 (the two batch checks as expected failures), the offline build.

### W20 Batch corrections (builder)

Specification: "Batch corrections", the last section's concurrency sentence. Invariants: I1, I2, I15–I19, I56–I58, I62, I63, I66, I69, I72–I76.

- W20.1 201 Correction batch: one revision per item in input order, each n + 1, with `amount`, `effective_at` exactly as sent, `reason`, the shared `recorded_at` and `correction_batch_id`; `recorded_at` strictly later than each payment's previous `recorded_at`; `GET /payments/{id}/revisions` shows the new revisions with `correction_batch_id` and every other revision with stage 3's six fields.
- W20.2 Rights: no token 401; a non-operator 403 before the key and the body (no key, or a broken body, still 403); an operator may correct payments between other users, private ones included, and payments of any kind except captures and refunds.
- W20.3 Idempotency, the tenth path: stage 1's scenarios; a replay 200 with the original body after newer revisions; the same key on another path is independent.
- W20.4 Shape 422, before any item error: `corrections` missing, not an array, `[]`, 33 items, a non-object element, two items with one `payment_id`. A batch of 32 items is accepted (critic plan review 8).
- W20.5 Items in input order: every correction field rule (422), including `payment_id` not a string and `effective_at` later than now; unknown payment 404; a capture or a refund 422 `linked_payment_immutable`; a stale `expected_revision` 409; an amount below the refunded total 422 `refund_exceeds_payment`; the first failing item decides (an unknown payment in item 1 beats a field error in item 2, and the reverse); unknown fields ignored. No tolerance on `effective_at` (D81): an item a fraction of a second after a fresh service time mark is 422, and every batch revision's `effective_at` is at or before its `recorded_at`. An item one unit below the payment's refunded total is 422 `refund_exceeds_payment` (critic plan review 6, 7).
- W20.6 Settlements: a batch with some but not all members of a settlement 422 `incomplete_settlement`; all members with two different instants 422 `validation_failed`; one instant in two spellings (`Z` and `+05:30`) accepted; a whole settlement together with ordinary payments accepted; a single correction of a member still 422 `linked_payment_immutable`; a nonmember still correctable alone. Member instants that differ only in trailing fraction zeros (`…:00.5Z` and `…:00.500Z`) are one instant and accepted; instants 1 µs apart are 422 (critic plan review 4).
- W20.7 Funds and history: a batch whose debits are each above a user's `available` but whose combined effect is affordable is accepted (for example two payments corrected in opposite directions between the same users); a batch whose combined effect leaves a user's `available` below 0 is 409 `insufficient_funds` (held funds count); the 2^53 guard; 409 `historical_overdraft` from the combined new revisions, including a case that each item alone would pass; the order: item errors, then completeness, then the instants rule, then current funds, then history. Boundaries (critic plan review 3, 5): a batch that leaves a user's `available` at exactly 0 is accepted and one minor unit more is 409, with one case where an open hold makes that difference; a batch that moves a debit created first onto the instant of a credit created after it, where the two combine to at least 0, is 201; a dip below 0 only between two items' instants is 409 `historical_overdraft`.
- W20.8 A rejected batch changes nothing: balances, revisions, statements, snapshots, and the key, which then works for a valid body.
- W20.9 Originals and history: original payments, feed items, settlement responses and their replays unchanged; new statements use the batch's revisions; a snapshot taken before pages unchanged; `known_at` 1 µs before the batch's `recorded_at` shows the previous revisions, and exactly at it the new ones; a member corrected to 0 is one statement entry with `delta` 0.
- W20.10 Concurrency: a batch and a single correction naming one payment with the same `expected_revision`: exactly one succeeds; two overlapping batches: exactly one succeeds; 50 concurrent batches over one settlement: one winner, and money moves once.
- W20.11 Gate as W19.9, with the supplied checks for stages 1 to 4 all counting.

### W21 Export, import, upgrade, RUN.md (builder)

Specification: stage-1 §10, the last section's export sentence. Invariants: I25, I26, I65, I69.

- W21.1 Schema-4 export per section 3.11, one synchronous snapshot.
- W21.2 Round trip, in the same container and into a second one: refunds (`refund_of`, the cap still enforced, refund replays), batch revisions with their ids, batch replays, snapshot tokens paging the same results, and everything stage 3 promised. New writes after the import are later than everything imported. The pages of a stage-4 snapshot and of an imported stage-3 snapshot are equal as JSON before and after the round trip (D106).
- W21.3 Upgrade from the frozen `stage-1/`, `stage-2/` and `stage-3/` builds: 204; settlement membership kept; every revision kept; tokens of statement snapshots from a stage-3 export page their frozen entries; every payment `refund_of: null`; earlier replays return their stored bodies verbatim; a batch correcting an imported settlement's members, a refund of an imported capture and a refund of an imported settlement member all work. A statement token paged on the frozen stage-3 build, then exported, imported into stage 4 and paged again, gives bodies equal as JSON (its payments without `refund_of`), and again after a further stage-4 export and import (critic plan review 1, D106).
- W21.4 Invalid schema-4 states are 422 and change nothing: `refund_of` naming an unknown payment, a refund, or a later payment; a refund whose parties are not the target's reversed; refunds above the target's latest amount; a refund or a capture with two revisions; two revisions of one batch id with different `recorded_at`; `schema` 5.
- W21.5 RUN.md for stage 4: the image and paths, `npm test`, the acceptance suite with its prerequisites, the supplied checks with `--stage 4`.
- W21.6 Gate as W19.9, with every check counting.

### W22 Stage-4 acceptance suite (verifier)

Specification: all of `stage-4.md`, and `stage-1.md` to `stage-3.md` as they still apply. Invariants: all.

- W22.1 The stage-1 to stage-3 acceptance tests carried into `stage-4/acceptance/` and brought to the stage-4 contract (`refund_of` in payment representations; the export schema; the RUN.md check to stage 4; the upgrade tests from the frozen stage-3 build as well); the stage-2 browser tests unchanged.
- W22.2 Tests for every criterion W19.1–W21.5 and every invariant I68–I77 and amended invariant, each marked with its item so `--upto N` selects them.
- W22.3 Upgrade tests with containers built from the frozen `stage-1/`, `stage-2/` and `stage-3/` folders.
- W22.4 Concurrency: refunds racing refunds and corrections; batches racing single corrections and each other; snapshot pages read while batches and refunds commit; I1 and I2 at teardown in current and historical views, and I67.
- W22.5 Time marks from the service only.
- W22.6 The supplied stage-4 sample passes. The new stage-4 tests fail on the accepted stage-3 build, which has neither endpoint, showing that they test stage-4 behaviour.

## 5. Decisions

Stages 1 to 3's decisions D1–D87 stand. New:

- **D88 Same room, re-evaluated (D78).** Just before the stage-4 folder was created (15:39Z), the four seats had sent 217 messages to this room, 54 of them during stage 3. They were counted from the seats' session transcripts on this machine (every `sent <id>` a `band send` or `band reply` printed), and every send was accepted. Band exposes neither a room's message count nor its capacity, and every seat's receiver is bound to this room, so a move could cut delivery mid-run. The planner stays, checks every send, and moves to a new room with the same members if a send is refused.
- **D89 Refund amount.** "Invalid amount is 422" with no range given: a refund is "a new payment", so the payment amount rules apply, an integral number from 1 to 1000000000. A refund of 0 would move nothing and is refused.
- **D90 Refund precedence.** Stage 1's common steps (route, authentication, key, body, claimed key, fields), then the resource (404), then who may act (403), then what the target is (422 `invalid_refund_target`), then the cap (422 `refund_exceeds_payment`), then the funds (409), then the 2^53 guard: the same shape as the correction order (D74). A third party gets 403, as "else 403 `forbidden`" says, like a non-sender's correction (D83).
- **D91 Refund representation.** The specification lists `refund_of`, the null `request_id` and `authorization_id`, and the original note and visibility. A refund is not a settlement member ("refunds never change settlement membership"), so its `settlement_id` is null too. The target's representation never changes ("Original payments and receipts never change"), so it shows no refunded total.
- **D92 Refunded total and the cap.** "The payment's current corrected amount" is the amount of its latest revision: current, so `known_at` and effective times play no part. Refunds are never corrected, so the refunded total only grows, and a correction cannot go below it.
- **D93 Refunds leave holds and requests alone.** The specification: "Refunds never reopen a request or authorization or restore a released hold." A capture's refund is a plain payment back; the authorization and the hold history of section 3.8 are untouched.
- **D94 Correction order (D74 amended).** A refund joins captures and settlement members as immutable for single corrections (step 9). `refund_exceeds_payment` comes after `stale_revision`, because the refunded total is current state that the client's revision may predate, and before the funds, because it is a rule on the requested amount, like the item errors that precede the funds in a batch.
- **D95 Batch order.** "The same 401/403 rules as settlements": 403 before the key and the body, as stage 1 placed it for settlements. The batch shape covers every element before any item (D37), and distinct `payment_id` values are part of the shape ("1..32 objects with distinct payment_ids, else 422"). "Item errors in input order": the first item with any error answers, and within an item the single-correction order applies, without the sender rule (an operator need not be a party). Then the settlement rules: completeness, as the specification names it, then the shared instant, which needs the complete member set. Then current funds, then the 2^53 guard, then history.
- **D96 Operators may correct any payment.** "The operator may correct ordinary, request and settlement payments", with no rule about parties or visibility; settlements themselves run "across any wallets", and their members may be private. Stage 1's "This permission does not grant access to another user's requests or private activity items" still governs reads: `GET /activity`, `GET /requests` and `GET /payments/{id}/revisions` are unchanged, so an operator who is not a party reads a payment's revisions as 404.
- **D97 `correction_batch_id` only where a batch recorded the revision.** The specification asks for it on the batch's revisions ("each revision also exposes correction_batch_id"). Revisions recorded otherwise keep stage 3's six fields, because stage 3's checks still run against this folder and describe that shape.
- **D98 Settlement members and their instant.** A settlement's members are the payments with its `settlement_id`, API-made, seeded or imported (D75). "Identical effective instants (offset spellings may differ)" compares exact instants (D66); each revision still stores its own `effective_at` string as sent.
- **D99 Batch affordability.** "Affordability is determined by the combined effect of all proposed revisions", in the words stage 1 used for settlements ("every wallet's balance after all incoming and outgoing transfers is nonnegative"), judged on `available` as every debit since stage 2 is (D53). A user whose `available` is already below what a batch's other items need gains nothing from the order of the items.
- **D100 One `recorded_at` per batch.** One issued timestamp (D67) serves every new revision. It is strictly later than everything recorded before, hence than each member's previous `recorded_at`, also after an import, whose clock base is past every imported instant (D86).
- **D101 Fixtures unchanged.** Stage 4 adds nothing to the fixture format, so seeded payments are never refunds and carry `refund_of: null`. Fields stage 4 introduces are ignored in a fixture like any unknown field (stage 1's reset rule).
- **D102 Export schema 4.** `format_version` stays 1 (§10); the state's `schema` tells the import which rules apply. Schemas 1 to 3 import by stage 3's rules, so "exports produced by the same team's stages 1–3" are accepted unchanged, "retaining settlement membership, corrections and snapshots".
- **D103 UI unchanged.** Stage 4 names no screen, route, `data-testid` or UI state, as stage 3 named none (D77). The stage-2 screens stay correct: balances come from `GET /me`, and a refund is a payment, so the feed lists it like any other.
- **D104 Refunds need no history check.** A refund takes effect at its `created_at`, which is later than every effective time recorded so far, since effective times are never later than `now` (D81). So it can only lower balances from now on, and the current `available` check covers that. Later corrections see refunds in their history check like any payment.
- **D105 Concurrent corrections.** Single corrections and batches check `expected_revision` and commit in one synchronous step each, so "concurrent corrections sharing any expected payment revision cannot both succeed" holds across both endpoints.
- **D106 Snapshots keep their payment form (critic plan review 1).** Stage 3: a snapshot "pages that exact result". Stage 4: saved statements "remain available in their original form", and stage-3 exports are accepted "retaining ... snapshots". A snapshot stores a cutoff and recomputes its pages (D73), so without a rule the stage-4 payment form would add `refund_of: null` to every entry of a stage-3 snapshot after the upgrade. So each snapshot records the payment form of the service that made it, 3 for one imported from a schema-3 state and 4 for one made by stage 4, and pages its payments in that form; the schema-4 export carries the form. A stage-3 snapshot holds no refund, since its cutoff precedes every refund, so its form only omits the field.

## 6. Specification trace

Each normative line of stage-4.md, condensed (F1–F43), with the acceptance tests that exercise it (file prefix `test_` and test prefix `test_` omitted). The lines of stages 1 to 3 are carried by the regression tests in stage-4/acceptance, brought to the stage-4 contract. A row without a test when its item's tests land is a gap and becomes a criterion at once.

| F | Section | Normative line (condensed) | Plan | Tests | Status |
|---|---|---|---|---|---|
| F1 | intro | recipients can refund payments | W19 | w19_refunds: a_refund_is_a_new_payment_in_the_opposite_direction | tests at 1028890; verdict pending |
| F2 | intro | operators correct several payments in one request, settlement payments included | W20 | w20_batches: a_whole_settlement_with_ordinary_payments, an_operator_may_correct_request_settlement_and_seeded_payments | tests at 1028890; verdict pending |
| F3 | intro | existing receipts and saved statements stay available in their original form | I75 I76 D106 W19.4 W20.9 W21.3 | w19_refunds: the_refunded_payment_stays_as_it_was, a_refund_in_statements_and_history_views; w20_batches: originals_replays_and_settlement_responses_stay, new_statements_use_the_batch_and_old_snapshots_do_not; w21_upgrade: stage_3_snapshots_page_in_their_own_form (D106) | tests at 1028890; verdict pending |
| F4 | intro | ten idempotent write paths | I15–I19 W19.1 W20.3 | w2_idempotency: every scenario [refunds] and [batches], same_key_on_the_ten_paths_is_independent | tests at 1028890; verdict pending |
| F5 | refunds | `POST /payments/{id}/refunds` `{"amount"}` requires an idempotency key | W19.1 W19.2 | w2_idempotency: missing_key_is_400_and_changes_nothing[refunds]; w19_refunds: precedence_of_the_common_steps | tests at 1028890; verdict pending |
| F6 | refunds | only the original receiver may refund, else 403; unknown payment 404 | I71 D90 W19.2 | w19_refunds: who_may_refund, a_refund_cannot_be_refunded | tests at 1028890; verdict pending |
| F7 | refunds | the target may be a direct payment, request payment or capture, never a refund | I71 W19.3 | w19_refunds: a_refund_is_a_new_payment_in_the_opposite_direction (a direct payment), a_request_payment_is_refundable_and_the_request_stays_paid, a_capture_is_refundable_and_its_open_authorization_does_not_change, a_settlement_member_is_refundable_and_stays_a_member, a_seeded_payment_is_refundable | tests at 1028890; verdict pending |
| F8 | refunds | invalid amount 422 | D89 W19.2 | w19_refunds: an_invalid_amount_is_422_and_changes_nothing, integral_number_forms_are_valid | tests at 1028890; verdict pending |
| F9 | refunds | refunds cumulatively at most the current corrected amount, else 422 `refund_exceeds_payment` | I69 D92 W19.2 W19.3 | w19_refunds: refunds_together_may_reach_the_amount_but_not_pass_it, the_cap_follows_the_current_corrected_amount, the_cap_ignores_effective_time, after_a_correction_to_zero_nothing_is_refundable; w19_concurrency: fifty_refunds_of_one_payment_never_pass_the_cap | tests at 1028890; verdict pending |
| F10 | refunds | refunds of refunds 422 `invalid_refund_target` | I71 W19.2 | w19_refunds: a_refund_cannot_be_refunded | tests at 1028890; verdict pending |
| F11 | refunds | a new payment in the opposite direction: `refund_of`, null `request_id` and `authorization_id`, the original note and visibility | I68 D91 W19.1 | w19_refunds: a_refund_is_a_new_payment_in_the_opposite_direction, unknown_body_fields_are_ignored; teardown I68 (Service.assert_refund_invariants) | tests at 1028890; verdict pending |
| F12 | refunds | 201 with that payment; a replay 200 with the original body | I15 W19.1 | w19_refunds: a_replay_returns_the_original_body_after_later_refunds_and_corrections; w2_idempotency [refunds] | tests at 1028890; verdict pending |
| F13 | refunds | moves existing money from the receiver's available funds, or 409 `insufficient_funds`, atomically | I70 W19.2 | w19_refunds: held_funds_are_not_available_for_a_refund, the_cap_comes_before_the_funds; w19_concurrency: refunds_of_two_payments_racing_for_the_same_funds | tests at 1028890; verdict pending |
| F14 | refunds | never reopens a request or authorization or restores a released hold | I70 D93 W19.4 | w19_refunds: a_capture_is_refundable_and_its_open_authorization_does_not_change, refunding_a_final_capture_leaves_the_authorization_closed, refunding_a_capture_of_a_voided_hold_restores_no_hold, refunding_a_capture_of_an_expired_hold_restores_no_hold, a_request_payment_is_refundable_and_the_request_stays_paid | tests at 1028890; verdict pending |
| F15 | refunds | other payments have `refund_of: null` | I68 W19.5 | w19_refunds: every_other_payment_has_refund_of_null; support.check_payment (every payment read); w21_upgrade: stage_1_payments_carry_refund_of_null_and_replays_stay_verbatim, stage_2_payments_carry_refund_of_null_and_replays_stay_verbatim, stage_3_state_reads_back_with_refund_of_null | tests at 1028890; verdict pending |
| F16 | corrections | stage-3 corrections remain for ordinary direct and request payments | I66 W19.6 | w16_corrections (regression); w19_refunds: the_correction_order_with_refunds | tests at 1028890; verdict pending |
| F17 | corrections | captures and refunds cannot be corrected: 422 `linked_payment_immutable` | I62 W19.6 W20.5 | w19_refunds: a_refund_cannot_be_corrected; w16_corrections: captures_and_settlement_members_are_immutable; w20_batches: item_resource_errors, a_refund_of_a_member_is_not_a_member | tests at 1028890; verdict pending |
| F18 | corrections | a correction cannot go below the refunded amount: 422 `refund_exceeds_payment` | I69 D94 W19.6 W20.5 | w19_refunds: a_correction_cannot_go_below_the_refunded_total; w20_batches: item_resource_errors, a_batch_lowering_a_payment_to_its_refunded_total_leaves_nothing_to_refund | tests at 1028890; verdict pending |
| F19 | corrections | correction debits are checked against available funds | D74 W19.6 W20.7 | w19_refunds: a_correction_debit_is_judged_on_available; w20_batches: held_funds_count_in_the_combined_effect | tests at 1028890; verdict pending |
| F20 | batches | `POST /correction-batches` needs an operator and a key; 401 and 403 as settlements | D95 W20.2 | w20_batches: a_batch_needs_a_token, a_non_operator_is_403_before_the_key_and_the_body; w2_idempotency [batches] | tests at 1028890; verdict pending |
| F21 | batches | body `{"corrections": [{payment_id, expected_revision, amount, effective_at, reason}]}` | 3.9 W20.1 | w20_batches: a_batch_returns_one_revision_per_item_in_input_order | tests at 1028890; verdict pending |
| F22 | batches | 1..32 objects with distinct payment ids, else 422 | D95 W20.4 | w20_batches: a_bad_shape_is_422_before_any_item, thirty_two_items_are_accepted | tests at 1028890; verdict pending |
| F23 | batches | every item has the ordinary correction fields and validation | W20.5 | w20_batches: invalid_item_fields_are_422_and_change_nothing | tests at 1028890; verdict pending |
| F24 | batches | unknown payment 404; stale expected revision 409 `stale_revision` | W20.5 | w20_batches: item_resource_errors, the_first_failing_item_decides | tests at 1028890; verdict pending |
| F25 | batches | the operator may correct ordinary, request and settlement payments; captures and refunds stay immutable | I62 D96 W20.2 W20.5 | w20_batches: an_operator_may_correct_payments_between_other_users, an_operator_may_correct_request_settlement_and_seeded_payments, item_resource_errors | tests at 1028890; verdict pending |
| F26 | batches | correcting a settlement member needs every member of that settlement, else 422 `incomplete_settlement` | I73 W20.6 | w20_batches: some_but_not_all_members_is_incomplete_settlement, members_of_a_seeded_settlement, two_settlements_in_one_batch | tests at 1028890; verdict pending |
| F27 | batches | members of one settlement share one effective instant (spellings may differ), else 422 | I73 D98 W20.6 | w20_batches: members_need_one_effective_instant, one_instant_in_any_spelling_is_accepted, member_instants_that_differ_only_in_trailing_zeros_are_one_instant | tests at 1028890; verdict pending |
| F28 | batches | single corrections remain available for nonmembers | W20.6 | w20_batches: single_corrections_of_members_stay_immutable | tests at 1028890; verdict pending |
| F29 | batches | unknown fields are ignored | W20.5 | w20_batches: unknown_item_fields_are_ignored, unknown_top_level_fields_are_ignored | tests at 1028890; verdict pending |
| F30 | batches | precedence: item errors in input order, completeness, current available funds, then history at every boundary | D95 W20.5 W20.7 | w20_batches: the_first_failing_item_decides, completeness_is_checked_before_the_shared_instant, the_order_after_the_items | tests at 1028890; verdict pending |
| F31 | batches | the existing codes apply: `linked_payment_immutable`, `refund_exceeds_payment`, `insufficient_funds`, `historical_overdraft` | W20.5 W20.7 | w20_batches: item_resource_errors, held_funds_count_in_the_combined_effect, history_is_checked_with_every_new_revision_together | tests at 1028890; verdict pending |
| F32 | batches | affordability by the combined effect of all proposed revisions | I74 D99 W20.7 | w20_batches: affordability_is_the_combined_effect, available_at_exactly_zero_is_accepted_and_one_unit_more_is_refused, held_funds_count_in_the_combined_effect | tests at 1028890; verdict pending |
| F33 | batches | a rejected batch leaves history, balances and idempotency records unchanged | I72 W20.8 | w20_batches: a_rejected_batch_changes_nothing_and_claims_no_key (and state() in every refusal test) | tests at 1028890; verdict pending |
| F34 | batches | 201 with `correction_batch_id`, `recorded_at` and `revisions` in input order | I72 W20.1 | w20_batches: a_batch_returns_one_revision_per_item_in_input_order | tests at 1028890; verdict pending |
| F35 | batches | all new revisions share `recorded_at`, strictly later than each member's previous one | I72 D100 W20.1 | w20_batches: a_batch_returns_one_revision_per_item_in_input_order, every_batch_has_its_own_id_and_a_later_recorded_at; support.check_batch | tests at 1028890; verdict pending |
| F36 | batches | each revision exposes `correction_batch_id` | D97 W20.1 | w20_batches: a_batch_appends_revision_n_plus_1_and_other_revisions_keep_six_fields; support.check_revision | tests at 1028890; verdict pending |
| F37 | batches | effective times cannot be later than now | D81 W20.5 | w20_batches: an_effective_at_later_than_now_is_422, no_clock_tolerance_on_effective_at | tests at 1028890; verdict pending |
| F38 | batches | original payments and receipts never change; payment and settlement retries return their original bodies | I75 W20.9 | w20_batches: originals_replays_and_settlement_responses_stay | tests at 1028890; verdict pending |
| F39 | batches | new statements reflect the new revisions; earlier snapshot tokens page their frozen entries | I76 D106 W20.9 | w20_batches: new_statements_use_the_batch_and_old_snapshots_do_not; w20_concurrency: snapshot_pages_stay_frozen_while_batches_and_refunds_commit | tests at 1028890; verdict pending |
| F40 | batches | a replay returns the original batch response with 200; one more idempotent path | I15 W20.3 | w2_idempotency [batches]; w20_batches: the_common_steps | tests at 1028890; verdict pending |
| F41 | last | a settlement payment may be refunded; refunds never change settlement membership | I75 D98 W19.3 W19.4 | w19_refunds: a_settlement_member_is_refundable_and_stays_a_member; w20_batches: a_refund_of_a_member_is_not_a_member | tests at 1028890; verdict pending |
| F42 | last | concurrent corrections sharing any expected payment revision cannot both succeed | I63 D105 W20.10 | w20_concurrency: batches_and_single_corrections_on_one_revision_have_one_winner, two_overlapping_batches_have_one_winner, fifty_batches_over_one_settlement_move_money_once | tests at 1028890; verdict pending |
| F43 | last | accept exports from stages 1 to 3, retaining settlement membership, corrections and snapshots | I65 D102 D106 W21.3 | w21_upgrade (every test); w8_upgrade, w17_upgrade (regression) | tests at 1028890; verdict pending |

## 7. Handoff log

| Handoff | To | Sent | Acknowledged | State |
|---|---|---|---|---|
| Stage-4 handoff, parts 1-16 (plan 76b3707) | builder, verifier, critic | 15:51Z | critic (plan review, c8106d0), builder (W19 at 2b3944a, 16:05Z; plan revision acknowledged), verifier (after a liveness ping at 16:11Z: all 16 parts and the revision arrived; regression brought to stage 4, W19 and W20 tests drafted) | acknowledged |
| Critic plan review @ 76b3707 (REVIEW.md c8106d0: 1 defect, 1 wording, 7 criteria) -> plan revision: D106 (snapshots keep their payment form), I76, 3.6, 3.11, 3.12 wording, W19.3, W19.4, W20.4-W20.7, W21.2, W21.3 | builder, verifier, critic | 16:02Z | — | sent |
| Verifier: first W22 suite 1028890 (16:23Z) with a trace map -> planner: trace filled; 95 test names checked against 1028890, none missing; no gap found | verifier | 16:25Z | — | done |
| HANDOFF W19 @ 2b3944a (builder): npm 220/220; acceptance 1028890 --upto 19 "2688 passed, 186 deselected"; harness s4-b04: stages 1-3 pass, stage 4 3 passed and the 2 expected batch failures | verifier, critic, planner | by 16:40Z | planner | awaiting the verdict |

## 8. Stage close

Not yet.
