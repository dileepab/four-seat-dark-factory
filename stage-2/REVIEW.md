# Stage 2 review (critic-h6bj)

Each entry records one verdict: the commit, the verdict, the reason and the evidence I checked. My scratch work lives under `.work/critic-h6bj/`.

## Plan review: stage-2/PLAN.md @ 736690c (not a verdict)

I read the following against `stage-2/PLAN.md` at 736690c, which includes c090e8c, 9106249 (D62) and 736690c (D63):
- `stage-2.md` in full;
- the parts of `stage-1.md` that stage 2 changes or relies on: §3.4, §4, §5, §6, §7, §8 (paging, splits), §10 and §11;
- the supplied checks `test/stage_2/test_sample.py` and `test_ui.py`;
- the harness browser fixtures in `harness/plugin.py`.

Sent to the planner as one batch: 8 defects, 3 small gaps and 3 recommendations.

### Defects

1. **Expiry by the clock is not limited to open authorizations** (I34, 3.5, D50; W7.4, W7.6).
   - I34 says that once the clock reaches `expires_at` "the authorization reads `expired`", with no qualifier. Capture precedence checks "expired" before "captured or voided".
   - Only a parenthesis in 3.6 ("an open authorization past `expires_at` reads `expired`") limits expiry to open authorizations.
   - A builder may implement `now >= expires_at → expired` first. Under that implementation, a captured or voided authorization past its deadline reads `expired`:
     - it leaves `status=captured` and loses `authorization-captured-{id}`;
     - a second capture answers `authorization_expired`, where the spec says "A second capture after a final capture is 409 `authorization_not_open`";
     - voiding a voided authorization answers 409, where the spec says "Voiding an already-voided authorisation is `200`".
   - Asked for:
     - a qualified rule in I34, 3.5 and D50;
     - a criterion: with TTL 1 s, after the deadline, a fully captured and a voided authorization keep their status under the filters; a capture answers 409 `authorization_not_open`; the voided one voids again with 200.
   - Corner to decide: a seeded `expired` authorization whose `expires_at` is still in the future. The table's literal answer is `authorization_not_open`; D50 gives `authorization_expired`.
2. **The 3.14 rule "A 401 from any API call clears the token and shows `/login` ... not `auth-error`" catches a wrong-password login.**
   - `POST /auth/login` answers 401 for a wrong password or an unknown email (stage-1 §6).
   - W9.3 and the supplied `test_bad_login_shows_auth_error` need `auth-error` there.
   - Asked for: limit the rule to authenticated calls.
3. **Lists show only the first page** (3.14 Screens).
   - The spec says `activity-item-{payment_id}` is "One per visible payment" and `request-item-{request_id}` is "One per request".
   - The plan shows "the first page" of `GET /activity`, and is silent on how much of `/requests` and `/authorizations` it shows. The default limit is 50 (stage-1 §8), so the 51st visible payment has no item.
   - Asked for:
     - `limit=200`, following `has_more` until false, de-duplicated by id;
     - a criterion with more than one page.
4. **The 6 s client limit** (D43, 3.14 Writes, W10.3).
   - (a) The plan never says the page aborts at the limit. "A submit or action button may be disabled only while its own write is in flight" (D63 wording) then keeps the button disabled through a hung response.
   - (b) D43 places 6 s "below the browser checks' 10 s waits", but that 10 s is `context.set_default_timeout(10_000)` (`harness/plugin.py`). It does not reach Playwright's `expect()`.
     - `expect()` defaults to 5 s: `playwright/_impl/_assertions.py` line 98, `self._timeout or 5_000`.
     - The supplied `test_sample.py` uses `expect()`. A graded check that hangs `POST /payments` and asserts `pay-uncertain` with `expect()` would fail before 6 s.
   - Asked for: an abort at the limit that re-enables the button and ignores late responses, the same for loads, and 4 s.
5. **Lost-response and resubmission criteria cover only pay (W10.3) and request payment (W11.1).** I42, D56 and 3.14 make them contract for every money form, but:
   - W10.4 (request form) has no lost-response criterion;
   - W11.2 (split) has no lost-response criterion;
   - W11.3 has none for authorize or capture, and no unchanged-resubmission rule for authorize.
6. **Capture lacks the §7 rows** (W7.3, W7.9). W7.2 lists them for `POST /authorizations`; W7.3 has only the replay and the two 409 pairs. Missing for capture:
   - missing or empty key → 400, and an over-long key → 422;
   - a failed capture claims nothing;
   - the same key on two authorizations is two captures;
   - concurrent identical first uses give one 201 (I17).
7. **RUN.md has no owner.**
   - The plan never mentions it.
   - `stage-2/RUN.md` is the stage-1 copy: "Pocketful stage 1", `docker build -t pocketful-s1 stage-1`, `cd stage-1`.
   - Stage 1 had W1.2 for it.
8. **The import's holds check needs D49's clock** (3.12, c090e8c). "After the import's time" should be the import's `now`: the later of the wall clock and the imported state's last issued timestamp.
   - With the bare wall clock, an export from a source whose clock ran ahead is refused when it holds a hold that was already expired there and whose money was spent.
   - The destination would read that hold as expired the moment the import completes.

### Small gaps

9. §1 does not say what `closed_at` is for:
   - seeded `captured`, `voided` and `expired` authorizations;
   - a seeded `open` authorization that is already expired at reset.

   With null, "clock expiry, whose time is `expires_at`" can put a release before `created_at`, or in the future.
10. I48 (text rendering) is listed under W9, but no criterion tests it.
11. W8.2 does not cover a state upgraded from stage 1 going through a schema-2 export and import. Its stage-1 replay bodies must stay verbatim (D54).

### Recommendations (planner's call)

- A. **D46 hedge.** The spec names a route only for `authorization-list`. The authorize rows sit with the wallet rows and name no route. Rendering the authorize form on `/` as well as `/authorizations` covers both readings.
- B. **I46 widths.** I46 checks only 375 and 1280, while 3.15 switches layout at 720 and 960. Add 1024×768 to the no-horizontal-scroll check.
- C. **Item actions** (request pay, capture, void, decline, cancel).
  - After an unknown outcome, the re-read can remove the item's button. The uncertain element then stays with no retry possible. Suggested: replace it with the confirmed state.
  - If a builder adds the optional `final: false` control, a new capture key is needed when the pre-filled remainder changes, because a programmatic value change fires no `input` event.

### Read and agreed

- D61: JSON-value body equality, so `{"amount": 700}` and `{"amount": 700, "final": true}` differ. This matches the spec's `{}` versus `{"amount": 2000}`.
- D54: verbatim replays (stage-1 §7, "body identical to the original response").
- D62: links checked by type only, as reset does.
- c090e8c: only unexpired open holds are counted, which matches reset.
- D63: refresh buttons are never disabled.
- The TTL cap at 10^10 (D48) is accepted: RFC 3339 has four-digit years, so a larger TTL cannot produce a valid `expires_at`.
- Every `data-testid` the spec names is in the 3.14 table.
- The capture codes, the 403-before-state order, `final` → 400 under §5's wrong-type rule, and D53's net settlement rule on `available` all match the spec.

### Polish (recorded, not sent as defects)

- §5 lists D63 between D62 and D61.
- 3.15 "with the viewer marked 'you'" should keep both handles inside `activity-parties-{payment_id}`, adding "you" rather than replacing a handle. The supplied `test_feed_shows_a_payment_with_its_parts` checks that the viewer's own handle is there.

### Plan re-review: 45fe2dc (not a verdict)

45fe2dc applies all 14 points. I checked the new text:
- I34, 3.5, 3.6, 3.7 and D50: expiry applies only to open authorizations; the capture order; the void table; both seeded `expired` corners.
- D65, D64 (every page, read from the bare path) and D43 (4 s with an abort).
- W7.3, W7.6, W7.9, W8.2, W9.2, W9.6, W10.3–W10.5 and W11.1–W11.4.
- The import `now` in 3.12, and `closed_at` for seeded authorizations in 3.11 and §1.
- D46 and I46.
- The key rule for re-filled bodies. It is added on top of the input-event rule, which stays.

## W7: BLOCKED @ 16adbc08c6e4f775105e12c5893eccadbefb5a61

The verifier posted PASS for W7 on this commit with suite cb62939 (room message cb1d9d2a):
- npm test 129/129;
- the offline build and `--network=none` health check;
- `run.sh --upto 7`: 1459 passed;
- the supplied checks: stage 1 147/147; stage 2 failed only on the 33 UI checks that need W9–W11.

### Reason: a reset can keep the previous state's clock, and no test notices

This breaks:
- I25: "an accepted one replaces all state";
- stage-1 §10: "Reset clears all state, including imported state";
- plan 3.7 / D49: "A reset starts its state's last issued timestamp at the reset's own wall-clock time";
- W7.8: "seeded open holds count in `held` right after the reset".

Evidence:
- **Mutant X15** (`src/fixture.ts` `buildState`): `st.lastTs = formatTs(resetMs)` becomes `formatTs(Math.max(resetMs, Date.parse(store.state.lastTs) || 0))`. A reset then keeps the old clock whenever that clock ran ahead of the wall clock.
  - It survives npm test (129/129).
  - It survives suite cb62939 `--upto 7` on local servers with the container checks deselected (1452 passed, the same as the clean baseline).
- **Probe** (`.work/critic-h6bj/probe_x15.py`):
  1. Reset, export, set the export's `last_ts` to 2099, and import it (204).
  2. Reset with an open hold of 400 from ada to bob expiring in two hours.
  3. Read `GET /me` and `GET /authorizations`, then pay 1.

  | | held | hold status | hold `created_at` | next payment |
  |---|---|---|---|---|
  | Clean 16adbc0 | 400 | `open` | `2026-10-04T10:11:55.506+00:00` | dated 2026 |
  | X15 | 0 | `expired` at once | `2099-01-01T00:00:00.000+00:00` | dated 2099 |

- **Why no test catches it.** No test resets after an import whose clock is ahead. The `_shift_years` probe in `test_w5_export_import.py` (the stage-1 E04 test) stops at the import.

### Missing evidence (verifier)

A test that:
1. imports an export shifted to 2099 with `_shift_years`;
2. resets with a fixture holding an open hold that expires in two hours;
3. asserts that `held` equals the hold, that `GET /authorizations` shows it `open`, and that its `created_at` and a new payment's `created_at` are both earlier than 2099.

The product needs no change. A rerun of the touched test on 16adbc0 carries the PASS over as a tests-only delta, and I will rerun X15 against it.

### Mutants (69 on 16adbc0; `.work/critic-h6bj/mutants_w7.json`, results `results_w7_unit_*.json`, `results_w7_acc_*.json`)

- **npm test kills 64**, each for the mutated reason. Failing test names checked:
  - G01 and G02: Me fields.
  - H01, H01b, H03, H05 and H06: held, the clock, the remainder, and expiry only for open authorizations.
  - A01 to A06: funds on `available` and the boundary; the TTL; self; precedence; the holds index.
  - C01 to C17: the capture order and the seeded corner; the deadline; the remainder; closing; the records; the payment shape; the guard; release on close.
  - V01 to V05: void. L01 to L05: the list. F01 to F03: funds on `available`.
  - X01 to X12, X16, X17, X19 and X22: reset.
  - W01 and W03: payment shape, and the replay body copied rather than aliased.
  - Notes on two kills:
    - A03 (TTL ignored) also hangs three expiry tests that wait without a bound. Its clean failures ("uses the fixture TTL" and the W7.6 tests) make the kill count.
    - X06 also refuses zero-balance users. Its failing tests include "counts seeded unexpired open holds against the balance: equal is fine".
- **The suite kills X21** (the `expires_at` offset sign flipped) in `test_w7_expiry.py::test_seeded_expires_at_is_compared_as_an_instant`.
- **X15** is the reason above.
- **H02, H04 and C06d** turn `>=` into `>` at the deadline: for `held`, `status` and capture at exactly `expires_at`. C06d survives the suite. I stopped the H02 and H04 suite runs to keep the verifier's W8 verdict run unloaded; npm test does not kill them.
  - Black-box tests cannot hit that millisecond without control of the clock, so I count these as equivalent in practice at W7.
  - W8 makes a deterministic test possible: import a schema-2 state whose last issued timestamp equals an open hold's `expires_at`, both ahead of the wall clock. The import's `now` is then exactly the deadline, so the hold must read `expired`, hold nothing and answer capture with 409 `authorization_expired`. That test also kills the forced-skew variants below. I will look for it in the W8 review.
- **Forced-skew variants H04b and H02b** move expiry 300 ms after the deadline. They survive the suite: the expiry tests read later than that after the deadline. C06e was not run; it is in the same class. A read at `expires_at + 100 ms` would catch these. Recommended, not blocking, given the deterministic W8 test above.

### Clause map (W7)

| Plan clause | Code @ 16adbc0 | Killing tests (mutant) |
|---|---|---|
| 3.6 Me, I30 | `me.ts`; `state.ts` `heldBy` and `availableOf` (stored-open index; counts `expiresMs > now`; prunes at the last issued timestamp) | W7.1 tests; 50 concurrent payments and authorizations (G01, G02, H01, H01b, H03, A06) |
| 3.5 and 3.10 `POST /authorizations` | `createAuthorization`: types, values, 404, `self_payment`, `available` 409, `created_at` + TTL | POST /payments precedence rows (A04, A05); exactly `available` (A01, A02); TTL (A03, X22) |
| 3.5 and 3.10 capture | `captureAuthorization`: `final` type, amount, 404, 403, captured or voided not open, deadline expired, stored `expired` ahead not open, exceeds against the remainder, 2^53, one step | D50 order (C01, C03, C04, C05); seeded corners (C06c); expiry only for open (C06); deadline (C06b); remainder (C07, C16); closing (C08, C09, C17); records (C10, C11, C12); payment shape (C13, C13b, C14, W01); guard (C15) |
| 3.5 and 3.10 void | `voidAuthorization` with `statusAt` | V01–V05 |
| 3.10 list | `listAuthorizations` with `statusAt` | L01–L05 |
| I33 | `remainingAt`, `closeAuthorization` | H06, C17 |
| I34; 3.7 clock | `clock()` = max(wall, last issued), read without side effects; `issue()` at commit; `statusAt` turns only stored-open authorizations into expired | H01, H01b, H05, C06, C06b, L02, V03, V05; the exact boundary: see above |
| I31, D53 | `payments.ts`, `requests.ts`, `settlements.ts` on `available` | F01, F02, F03 |
| 3.11 reset | `validateFixture` and `buildState`; `time.ts` `rfc3339Ms` (calendar date, ranges, offset, millisecond rounding up) | X01–X12, X16, X17, X19, X21 (suite); the re-base: **none** (X15) |
| I15 replay of authorizations | `authorizationView` copies `payment_ids` | W03 |

### Other checks

- No special-casing: `grep` finds no fixture ids, handles, emails or sample amounts in `src/`.
- No outbound network APIs. The Dockerfile copies `package.json` and `src/` and downloads nothing.
- Every new handler is synchronous between its checks and its commit: no `await` in `authorizations.ts`. `reset` swaps a state built aside.
- Every error path throws before any change.
- `RUN.md` describes stage 2 (W9.6).

### Polish (recorded, not sent as defects)

- `stage-2/Dockerfile` still says "Pocketful stage 1" in its comment.
- Three builder expiry tests wait without a bound when expiry never comes (seen under A03). A bounded wait would fail fast instead.

## W7: APPROVED @ 16adbc08c6e4f775105e12c5893eccadbefb5a61 (re-review after the X15 block)

The product is unchanged. Suite 5e17085 changes tests only (`test_w7_fixture.py`, `test_w7_expiry.py`, `test_w8_export_import.py`). It adds:
- the W7.8 reset re-base test (X15);
- the W8.2 exact-deadline import test;
- a W7.6 test that reads about 50 ms after the deadline on the service's own clock.

The verifier reran the touched files on 16adbc0 (room message 5b1eb87e): `run.sh --upto 7 -- -k "test_w7_fixture or test_w7_expiry"` gave 100 passed. Together with the verdict run (1459 passed, suite cb62939), this carries the W7 PASS over to suite 5e17085 as a tests-only delta.

My reruns on 16adbc0 used suite 5e17085, local servers, and the named test files only (`rerun_targeted.py`, logs in `.work/critic-h6bj/rerun_logs_w7/`):

| Mutant | Result |
|---|---|
| Clean | 100 passed |
| X15 | Killed by `test_reset_after_an_import_whose_clock_ran_ahead_starts_the_clock_at_the_reset`: "the seeded hold expiring in two hours is held / assert (10000, 10000, 0) == (10000, 9600, 400)" |
| H04b (status turns 300 ms late) | Killed by `test_the_deadline_releases_the_hold_at_once_on_the_service_clock`: "authorization status: expected 'expired', got 'open'". The I30 teardown also fails: held 0 against open remainders 1000. |
| H02b (`held` released 300 ms late) | Killed by the same test: "held 1000 at most 0.063 s after the deadline / assert (10000, 9000, 1000) == (10000, 10000, 0)" |
| H02, H04, C06d (`>=` becomes `>` at exactly the deadline) | Survive at 16adbc0, which cannot import a schema-2 state. Equivalent in practice at this commit. The W8.2 exact-deadline import test is the deterministic check; see the W8 entry. |

The block is resolved, and every other W7 finding stands as recorded above.

## W8: BLOCKED @ 54acbcd31a5be2c046d9bd65ef6053268ca30538

The verifier's PASS is on 54acbcd with suite 62c4a4e (plan 35be9a4). Suite 5e17085 is a tests-only delta, and its touched files reran on 54acbcd with 123 passed. The product change since W7 (16adbc0) is `src/snapshot.ts` only (+85 lines). The product is right in every case below. The tests are not.

### Reason: four one-line breaks of the import pass every test

Each mutant changes one line of `src/snapshot.ts`. Each survives:
- `npm test`: 137 passed;
- the W7 and W8 files of suite 5e17085 on 54acbcd: 130 passed, the same as the clean baseline.

`.work/critic-h6bj/probe_w8.py` (run by `run_probe_w8.py`, log `log_probe_w8.txt`) shows the clean product right and each mutant wrong:

| Mutant | Change | Clean 54acbcd | Mutant | Why no test sees it |
|---|---|---|---|---|
| E16: D48; 3.12 "`expires_at` exactly as stored" | `expiresAt: a.expires_at` becomes `new Date(expiresMs).toISOString()` with `+00:00` | A hold seeded with `2099-06-15T10:20:30.123456+05:30` reads the same after an export and import | It reads `2099-06-15T04:50:30.124+00:00` | The round-trip fixture seeds only `hours_from_now()` values, already in the service's own form, so normalizing changes nothing |
| E17: W8.4, I32 | `isInt(a.captured_amount, 0, a.amount)` becomes `isInt(a.captured_amount, 0, MAX_AMOUNT)` | A seeded `captured` hold of 100, exported with `captured_amount` edited to 150: 422 | 204. The state then holds 150 captured against 100 authorized | "captured above amount" edits the open partial hold, which the separate open rule (`captured_amount < amount`) refuses anyway |
| E26: 3.12 "whose `expires_at` is after the import's `now`" | `a.expiresMs > importMs` becomes `>=` | Export edited: `last_ts` set to an open hold's `expires_at`, the hold raised to 1500 (payer's total 1000). Result: 204, then `expired`, held 0, available 1000 | 422 "the open authorizations of u_ada hold more than its total" | The exact-deadline test's hold of 400 fits within the payer's total, so counting it changes nothing |
| E32: 3.12 "the remainders", I33 | `+ a.amount - a.capturedAmount` becomes `+ a.amount` | ada (balance 1000) authorizes 1000 to bob; bob captures 600 with `final: false`; ada now has total 400, held 400. The unchanged export imports with 204 | 422: a state the service built does not import back | The round trip's partially captured hold is small against its payer's total |

### Missing evidence (verifier)

The product needs no change. A rerun of the touched tests on 54acbcd carries the PASS over as a tests-only delta, and I will rerun the four mutants against it. Tests that fail on these mutants:
1. E16: a round trip of a hold seeded with an `expires_at` not in the service's form, here and into a second container. Use another offset and more than three fractional digits, for example `2099-06-15T10:20:30.123456+05:30`. After the import, `GET /authorizations` returns exactly the seeded string, and a second export carries it unchanged.
2. E17: "captured above amount" also on a closed authorization (a `captured` one, and a `voided` or `expired` one). `captured_amount` = `amount` + 1 is 422 with nothing changed.
3. E26: the exact-deadline import with the hold's remainder above the payer's total. It is still 204, then `expired` with held 0, and capture is 409 `authorization_expired`.
4. E32: a round trip of a partially captured open hold whose full amount is above the payer's total but whose remainder is not. For example: authorize the payer's whole balance, then capture most of it with `final: false`. Expected, here and in a second container: 204, `held` equal to the remainder, and a later capture of the rest succeeds.

### Mutants (27 on 54acbcd; `.work/critic-h6bj/mutants_w8.json`, results `results_w8_unit2.json`, reruns `log_w8_rerun.txt` and `rerun_logs/`)

- `npm test` kills 22 for the mutated reason: E01–E10, E14, E15, E18–E23 and E27–E30. They cover:
  - the export's fields, TTL, `closed_at` and stored status;
  - the import's validation rows, clock and D62;
  - the holds check's clock and its past-deadline rule.
- Five survive `npm test`. I reran them against suite 5e17085's `test_w7_fixture.py`, `test_w7_expiry.py`, `test_w8_export_import.py` and `test_w8_upgrade.py` (`--upto 8`, local servers, the frozen stage-1 for the upgrade). Each gives 130 passed, as clean does.
  - E16, E17, E26 and E32 are the block above.
  - E31 (a schema-1 import reads an `authorizations` array if one is present) is equivalent on every input the plan defines: schema 1 is "an unchanged stage-1 export", and stage 1 never exports authorizations. Recorded only.

W7 boundary mutants, rerun on 54acbcd against suite 5e17085 (`plan_w8_rerun.json`):

| Mutant | Result |
|---|---|
| H04 (status: `>=` becomes `>` at exactly `expires_at`) | Killed by `test_an_imported_clock_at_exactly_a_deadline_expires_the_hold`: "authorization status: expected 'expired', got 'open'" |
| C06d (capture: `>=` becomes `>`) | Killed by the same test: "expected 409 authorization_expired, got 201" |
| H04b (status 300 ms late) | Killed by the same test and by `test_the_deadline_releases_the_hold_at_once_on_the_service_clock`: "expected 'expired', got 'open'" |
| H02b (`held` 300 ms late) | Killed by `test_the_deadline_releases_the_hold_at_once_on_the_service_clock` |
| X15 (a reset keeps an imported clock) | Killed by `test_reset_after_an_import_whose_clock_ran_ahead_starts_the_clock_at_the_reset` |
| H02 (`held`: `>` becomes `>=`) | Survives; equivalent in practice. `heldBy` (`src/state.ts:276`) drops holds with `expiresMs <= lastTs` before comparing with now, and now is `max(wall, lastTs)`. The two forms differ only if the wall clock reads `expires_at` to the millisecond while ahead of `lastTs`. The builder agreed. |

H04, C06d, H04b and H02b were the open boundary items of the W7 entry. The W8.2 exact-deadline test closes them.

### Clause map (W8)

| Clause | Code at 54acbcd |
|---|---|
| W8.1 export contents: `format_version` 1, `schema` 2, the TTL, each payment's `authorization_id`, and every authorization with its stored fields (stored status, `expires_at` as stored, `created_at`, `closed_at`, `payment_ids`) | `src/snapshot.ts:29-76` (`exportState`, one synchronous call) |
| 3.12: import accepts schema 1 or 2, any other is 422 | `snapshot.ts:125-126` |
| 3.12: schema 2 needs the TTL (1 to 10^10); schema 1 has TTL 600, no authorizations, payments `authorization_id: null` | `snapshot.ts:132-140`, `:178`, `:186`, `:244` (`if (v2)`) |
| 3.11 and 3.12: authorization fields. Ids unique; parties existing and different; amount; `captured_amount` 0 to `amount`; an open hold needs `captured_amount < amount`; status; `expires_at` RFC 3339, up to 64 characters; `created_at`; `closed_at` | `snapshot.ts:244-263` |
| D62: `payment_id`, `payment_ids` and a payment's `authorization_id` checked by type only | `snapshot.ts:178`, `:259-261` |
| 3.12: the last issued timestamp covers `created_at` and `closed_at` (I29; the W7.8 re-base) | `snapshot.ts:144-146`, `:264-265`, `:297` |
| 3.12 holds check: the open remainders whose `expires_at` is after `now = max(wall, last_ts)` total at most the payer's total | `snapshot.ts:302-310` |
| W8.4: every refusal is 422 with nothing changed | `handlers/system.ts:25-29`: `importState` builds a fresh state and throws before `swapState` |
| W8.2: open holds keep expiring by the clock after an import | The imported `expiresMs`, with the W7 status rule and `heldBy` (`state.ts:270-280`) |
| W8.3: stored stage-1 replay bodies are kept verbatim | `snapshot.ts:285-293` (body and response copied as given) |

Every clause has code, so there is no product defect.

### Other checks

- Special-casing grep on the W8 product diff (fixture handles, ids, `2099`, sentinel values): nothing.
- The import validates, then makes one synchronous swap. The W8 product diff has no `await`.
- The verifier's run covers the offline build. RUN.md is unchanged since W7 and needs nothing for W8.

## W8: APPROVED @ 54acbcd31a5be2c046d9bd65ef6053268ca30538 (re-review after the E16, E17, E26, E32 block)

The product is unchanged. Suite a32f7a8 changes `test_w8_export_import.py` only. The verifier reran it on 54acbcd (`run.sh --upto 8 -- -k test_w8_export_import`, 29 passed), which carries the W8 PASS over as a tests-only delta.

My reruns on 54acbcd used suite a32f7a8, local servers and `test_w8_export_import.py` only (`plan_w8_rerun2.json`, log `log_w8_rerun2.txt`):

| Mutant | Result |
|---|---|
| Clean | 29 passed |
| E16 | Killed by `test_a_seeded_expires_at_not_in_the_service_form_round_trips_exactly`: "a_odd on A / assert '2099-06-15T0...:30.124+00:00' == '2099-06-15T1....123456+05:30'" |
| E17 | Killed by `test_rejected_import_changes_nothing[captured above amount, captured / voided / expired]`: "expected 422 validation_failed, got 204". The teardown errors that follow come from the accepted import. |
| E26 | Killed by `test_an_exact_deadline_hold_above_the_total_still_imports`: "expected 204 ... -> 422 'invalid export: the open authorizations of u_ada hold more than its total'" |
| E32 | Killed by `test_a_partly_captured_hold_larger_than_the_total_round_trips`: the same 422 on the first import |

The block is resolved. E31 and H02 stay recorded as above, and every other W8 finding stands.

## W9, W10, W11: BLOCKED @ 5f9781a1f533075861f0ba5afc30e65b8a51a289

The verifier's PASS is on 5f9781a with suite 5e17085:
- `run.sh --upto 11`: 1983 passed;
- `npm test`: 150 passed;
- the supplied checks, host and isolated, claim stage 2.

I reviewed:
- the server's UI routes (`src/ui.ts`, `src/app.ts`);
- every UI file (`ui/assets/*.js`, `app.css`, `index.html`);
- the W9.5 builder tests and RUN.md;
- the screenshots of every named state.

I broke the state rules of plan 3.14 one at a time in scratch copies, then ran:
- the suite's browser files at w1280 (`test_w9_session`, `test_w10_*`, `test_w11_*`; 188 tests, local servers);
- critic probes on a scratch copy of the suite (`.work/critic-h6bj/accprobe/test_critic_probe.py`, `rerun_ui.py`, logs in `rerun_logs_ui/`).

### Reason 1 (builder): a 2xx with an empty body throws and shows nothing

`ui/assets/api.js:76` reads an empty body as `null` and returns `ok` for any 2xx. Each money form's success message then reads the null body and throws:
- `wallet.js:82` (pay) and `:110` (request);
- `holds.js:43-47` (authorize);
- `split-screen.js:71-76` (split).

Probe P1 on clean 5f9781a: the payment commits, then the page gets 201 with an empty body. After 1.5 s:
- none of `pay-uncertain`, `pay-success` or `pay-error` is shown;
- the page error is "Cannot read properties of null (reading 'amount')";
- the data is not re-read: `wallet-available` still shows 100.00 EUR, but the server holds 85.00.

Broken: 3.14 Outcomes ("a body that is not JSON is an unknown outcome: show the uncertain element, never the error element"; "After an unknown outcome it re-reads the data too") and I42 ("unreadable body"). A load answered 2xx with an empty body fails the same way, through `showUser(null)`. The UI makes no call that expects an empty 2xx, so a 2xx whose body is empty, or is not a JSON object, can count as unknown.

### Reason 2 (builder): the uncertain message of a capture or a request payment does not say what 3.15 asks

3.15: "uncertain (amber message saying the money may have moved and that retrying without changes is safe)". Capture and paying a request move money. Their uncertain element shows `UNCERTAIN_ACTION_TEXT` (`kit.js:118-119`, used by `holds.js` and `requests.js`): "We could not confirm whether this went through. The list has been refreshed; if nothing changed, try again." It says neither thing. Seen in authorizations-capture-uncertain and requests-uncertain at both widths (screenshots 5f9781a and 92d940d). Decline, cancel and void move no money and may keep a neutral text. The pay, request, split and authorize forms use `UNCERTAIN_TEXT`, which says both.

### Reason 3 (verifier): eight state and layout rules can break with every test passing

Each mutant is one change in `ui/assets`. Each passes the 188 browser tests at w1280, the same as clean: 188 passed, plus one setup error on every run (the W10.7 stage-1 upgrade test needs `--previous-base-url`, which these runs did not start). Each critic probe passes on clean and fails on its mutant for the mutated reason:

| Mutant | Change | Rule | Probe: clean, then mutant |
|---|---|---|---|
| U01 | `TIMEOUT_MS` 4000 becomes 1500 | D43 "no response within 4 s" | P4, a payment answered at 2.8 s: `pay-success`, then `pay-uncertain` (aborted at 1.5 s), so the user is told the money may have moved |
| U02 | `TIMEOUT_MS` becomes 5500 | D43 (below the 5 s `expect()` of the supplied checks) | P5, no answer: `pay-uncertain` after 4.38 s, then nothing within 4.7 s. The suite's test allows 6 s. |
| U04 | Any 4xx is a refusal, envelope or not (`api.js:83`) | D43 "Only a 4xx with the envelope is a confirmed refusal" | P6, the payment commits, then 429 `{"message": ...}`: `pay-uncertain`, then `pay-error` while the money moved (balance 8500) |
| U05 | A stale load's failure is still shown (`kit.js:54-67`) | I44 "A load's response (or failure) is shown only if no later load ... has been shown" | P2, the first refresh's `/me` unanswered, a second refresh applied, then the first times out at 4 s: no `load-error`, then `load-error` |
| U06 | No de-duplication across pages (`api.js:101`) | D64 "keeps each item once (de-duplicated by id, since pages may shift under concurrent writes)" | P3, 60 payments, one new payment between page 1 and page 2: 60 items once, then 61 with `activity-item-p_010` twice |
| U23 | The capture input is not re-filled after a re-read (`holds.js:96`) | 3.14 `authorization-capture-amount-{id}` "pre-filled with the remaining amount"; the retry rule's "capture amount the page re-filled after a re-read" | P10: bob's other device captures 4.00 of a 10.00 hold, and Collect (10.00) is refused. Clean re-fills 6.00 and the next click captures; the mutant keeps 10.00 and is refused again. |
| U30 | A failed later page is dropped and the rest shown as the whole list (`api.js:112`) | 3.14 `load-error` "Shown when a data load fails"; D64 "The page shows every item" | P7, page 2 of `/activity` fails: `load-error`, then 50 items and no `load-error` |
| U40 | A note no longer wraps (`app.css` `.note`) | 3.15 "long ... notes wrap or truncate"; I46 "no route in any named state scrolls horizontally" | P11 (`accprobe/test_critic_probe_long.py`), the longest note (200 characters, no spaces), display names (100) and handles (20) at 375: `scrollWidth` 375, then 3067 on `/`, `/requests` and `/authorizations`. The suite ran at w375 for this one: 188 passed. |

### Missing evidence

Builder:
1. A 2xx whose body is empty or not a JSON object is an unknown outcome (`api.js`), so each form shows its uncertain element and re-reads.
2. The uncertain message of a capture and of a request payment says that the money may have moved and that retrying without changes is safe.

Verifier: tests that fail on these, at both widths where the layout is not the point. The probes in `.work/critic-h6bj/accprobe/test_critic_probe.py` are a starting point, not suite code:
1. P1: a fault kind "empty-after" (commit, then 201 with an empty body) in `test_lost_payment_shows_pay_uncertain_and_an_unchanged_retry_pays_once`. Expect `pay-uncertain`, the re-read showing the payment, and an unchanged retry that pays once. Do the same for the request, split and authorize forms.
2. U01 and U02: the 4 s limit from both sides:
   - an answer held 2.8 s then released is `pay-success`, with no uncertain element at 2.8 s;
   - no answer shows `pay-uncertain` within 4.7 s of the click.
3. U04: a 4xx with a JSON body but no envelope, after the commit, shows `pay-uncertain`, not `pay-error`.
4. U05: a refresh whose load times out after a later refresh applied leaves `load-error` absent.
5. U06: a payment created between the first and second page reads leaves every `activity-item-*` once (the `/activity?` route is enough).
6. U23: with the remainder changed by another client, a refused capture re-fills the input with the new remainder, and the next unchanged click captures it.
7. U30: a failed later page of `/activity` (and of `/requests` and `/authorizations`) shows `load-error`, not a short list.
8. U40: the I46 checks with the longest content at 375: a 200-character note with no spaces, a 100-character display name and a 20-character handle. Expect no horizontal scroll on `/`, `/requests`, `/authorizations` and `/split`.

### Mutants (13 on 5f9781a; `.work/critic-h6bj/mutants_ui.json`, logs `log_ui_*.txt`, `log_css_*.txt`, `rerun_logs_ui/`)

- Survive with an observable effect: U01, U02, U04, U05, U06, U23, U30, U40 (the table above).
- U42 (the header's display name loses its ellipsis) causes no page scroll with a 100-character name. Not pursued.
- U09 survives and is equivalent in practice. It drops the "body differs" rule from `RetryIdentity`, which then mints keys only on input or change events. The forms' bodies change only through those events. A re-filled capture amount could reuse only a key the server never claimed, because the UI's captures are final and a claimed key means the hold has closed.
- Controls, killed for the mutated reason:
  - U08 (a stale load's data applied) by `test_latest_refresh_wins_when_the_earlier_one_answers_last` ("expected 10500, actual 10300") and `test_a_write_reload_beats_a_slow_earlier_refresh`;
  - U10 (a capture's uncertain never clears) by `test_capture_lost_after_commit_shows_the_confirmed_state` and `test_void_lost_after_commit_shows_the_confirmed_state` (`authorization-uncertain` stays);
  - U11 (a request action's uncertain never clears) by `test_pay_lost_after_commit_shows_the_confirmed_state` and `test_decline_lost_after_commit_shows_the_confirmed_state` (`request-uncertain` stays).

### Clause map (W9-W11)

| Clause | Code at 5f9781a |
|---|---|
| 3.14 routes: the shell on `/`, `/split`, `/signup`, `/login`; `/requests` and `/authorizations` only for `text/html`; assets with type and nosniff; the HTML 404 | `src/ui.ts:35-67`, `src/app.ts:55-66` |
| `Accept` lists `text/html` (q not 0, `*/*` does not count) | `src/ui.ts:41-50` |
| HTML headers and CSP; favicon suppressed | `src/ui.ts:10-20`, `ui/index.html:8` |
| D41: token in `localStorage`; Bearer and `Accept: application/json` on every call | `api.js:11-46`, `:53-58` |
| D65: a 401 to a call that sent the token ends the session, with a notice; sign-in refusals show `auth-error` | `api.js:84-85`, `app.js:126-131`, `auth.js:24-27` |
| Signed out, the four routes show `/login`; `/login` and `/signup` always render; logout | `app.js:95-106`, `:82-85` |
| Header and navigation, `aria-current` | `app.js:47-71` |
| D44 amounts; D45 handles; notes of at most 200 code points, no `maxlength`; `type="text" inputmode="decimal"` | `money.js:20-40`, `split.js:13-30`, `wallet.js:14-15`, `kit.js:187-189` |
| D42 retry identity (128-bit key; new key on input or change, or when the body differs) | `retry.js:6-37`, `kit.js:132-171`; request pay keys `requests.js:20, 61-64`; capture `holds.js:89-110` |
| D43 outcomes: ok, refused (4xx with envelope), unknown (network, abort, 4 s, 5xx, not JSON) | `api.js:53-89` (Reason 1: the empty body at `:76`) |
| Re-read after the response, never before; uncertain kept until a retry resolves it; item actions confirmed by the re-read | `kit.js:156-168`, `requests.js:29-59`, `holds.js:77-130` |
| I44 latest wins per resource; data clears `load-error`; 4 s for loads | `kit.js:15-79` |
| D63: `wallet-refresh` and `load-retry` never disabled | `wallet.js:27-29`, `kit.js:33` |
| D64: bare first read, then `offset`/`limit=200` while `has_more`, de-duplicated | `api.js:93-119` |
| I45 element contract (`wallet-held` at 0, `empty-*`, buttons only where allowed, `authorization-captured-*` only when captured) | `kit.js:200-220`, `wallet.js:47-56`, `requests.js:68-114`, `holds.js:132-194` |
| I48: text only (no `innerHTML`; no inline style) | `dom.js:6-27` |
| W9.5 builder tests (amounts, split rule, retry identity, routes) | `test/w9-ui.test.ts` |
| W9.6 RUN.md | `RUN.md` (image, UI routes, `npm test`, the suite with its Playwright venv and frozen `stage-1/`, supplied checks with `--stage 2`) |

Every clause has code. The only product defect is the empty 2xx body (Reason 1).

### Presentation (all 45 named states at both widths, 5f9781a and 92d940d)

- Reason 2 is the one presentation block.
- Everything else in 3.15 holds:
  - `available` is the headline, with total and held secondary and labelled;
  - status has text and colour, and private payments have a lock and the label;
  - direction is from the viewer's side, with parties as handles and "(you)" beside them;
  - times are in `<time>`, and no ids are shown;
  - the loading, refused, uncertain, empty and success states look distinct;
  - one column below 720 px, two on `/` from 960 px, tabs at 375 px;
  - every input and select has a visible label, actions are buttons and navigation is links.
- The longest names, handles and notes (P11) never scroll the page, at 375 or 1280, on 5f9781a or 92d940d.
- Consistent with the contract, so not defects:
  - `wallet-held` is absent at 0;
  - `pay-success` stays while the request form shows its own result ("until the form changes or is submitted again");
  - item actions have no success element, because the contract defines none and the item's new status is the confirmation.
- Polish, recorded only:
  - the request and split forms' uncertain text says the money may have moved, though a request moves none;
  - a refused alert whose text wraps puts its icon on a line of its own (wallet-pay-refused, authorizations-authorize-refused, signup-refused-w375);
  - card padding and heading sizes vary (not-found-signed-in, the top card of requests-empty);
  - the Collect button is shorter than its input.

### Other checks

- Special-casing grep over `ui/assets`, `src/ui.ts` and `src/app.ts`: only placeholder and hint text names sample people. No fixture ids or handles, no test-environment checks.
- No `innerHTML`, `insertAdjacentHTML`, `eval` or inline style anywhere in the UI.
- No server state changes in W9–W11 beyond ace399c (the JSON 404 no longer echoes the path).

## W13: BLOCKED @ 92d940dc8ea4774a1592a8ed09b9544bc60b51a4

The verifier's PASS is on 92d940d with suite dbfa681:
- `run.sh --upto 13`: 1986 passed;
- `npm test`: 150 passed;
- the supplied checks, host and isolated, claim stage 2.

The PASS carries over to suite a32f7a8, a tests-only delta (`test_w8_export_import.py`, 29 passed on 92d940d). W13 changes `requests.js`, `holds.js` and `app.css` only. The code does what W13.1–W13.3 ask:
- an incoming request is `item out`, with the label "Asks you to pay";
- an outgoing request is `item in`, with the label "You asked to be paid";
- the facts and controls are full-width rows, and `.mono.instant` has `nowrap` with a scroll box of its own;
- the button reads "Collect" under "Amount to collect".

The optional change, an action's messages placed at their item with a fallback above the list, keeps every testid and its presence rule.

### Reason: two of the three criteria can be undone with every test passing

Mutants on 92d940d against suite a32f7a8's `test_w13_presentation.py` (`mutants_w13.json`, `log_w13.txt`; clean: 3 passed):

| Mutant | Change | Result |
|---|---|---|
| W13a | An incoming request coloured as money in again | Killed by `test_an_amount_the_viewer_would_pay_is_not_coloured_as_money_received` [w375, w1280]: "the amount ada would pay is drawn in rgb(22, 101, 52), the colour of a received payment" |
| W13b | `.mono.instant` may wrap (`white-space: normal; overflow-wrap: anywhere`) | 3 passed. The W13.2 test seeds a 32-character expiry, which fits one line in the new full-width row with or without `nowrap`. Probe P8 (`accprobe13/test_critic_probe_w13.py`) seeds the longest expiry a fixture allows (64 characters) at w375: clean, one line (21 px at a 21 px line height), inside the viewport, no page scroll; W13b, two lines (42 px). |
| W13c | The button says "Capture" again under "Amount to collect" | 3 passed; no test reads W13.3. Probe P9: the button's text appears in its input's label on clean ("collect" in "amount to collect"), not on W13c ("capture"). |
| W13d | The outgoing label is "You asked" again | 3 passed. "The label says which way the money would go" is wording, which D58 leaves to the screenshot review. The 92d940d screenshots show "Asks you to pay" and "You asked to be paid". Recorded, not blocking. |

### Missing evidence (verifier)

The product needs no change. A rerun of the touched file on 92d940d carries the PASS over. Tests needed:
1. W13.2 at its boundary: a seeded `expires_at` of 64 characters at 375 px stays on one line (height within 1.5 line heights), inside the card, with no horizontal page scroll.
2. W13.3: on an incoming open hold, the capture button's text appears in the label of `authorization-capture-amount-{id}` (ignoring case), at both widths.

Polish, recorded only:
- a cancelled outgoing request's amount is now green, though nothing will arrive (requests-success);
- an item's own messages sit 4 px under its controls, where form messages sit 12 px under (requests-refused, authorizations-capture-refused);
- the place-hold confirmation still says "until @… captures it" (authorizations-success).
