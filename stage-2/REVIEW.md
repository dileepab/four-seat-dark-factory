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
