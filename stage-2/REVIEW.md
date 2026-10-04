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
