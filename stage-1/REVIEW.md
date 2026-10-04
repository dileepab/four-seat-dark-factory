# Stage 1 review (critic-h6bj)

Each entry records one verdict: the commit, the verdict, the reason and the evidence I checked. My scratch work lives under `.work/critic-h6bj/`: mutant definitions `mutants_w1*.py` and `mutants_w2.py`, runners `mutate.py` and `mutate_acc.py`, results `results_*.json`, probes, and clean worktrees.

## Plan review: stage-1/PLAN.md @ 8dd27a4 (not a verdict)

Sent to the planner as one batch (room message 3017b53c). It raised five points:

- D24 and I9 contradicted §8, §11 and each other on amount minimums.
- Fixture payments could not carry `settlement_id`, which §11's last sentence requires.
- A path that does not percent-decode could produce a 500.
- A keep-alive close race (advisory).
- The base-image wording (advisory).

All five were adopted in 991aa6f and 23e7601: I9, D24, 3.1, D33, D34 and D35.

## W1: BLOCKED @ 2ffcbe83b154b575be5ac6a3faf6622716d74b34
## W2: BLOCKED @ 2ffcbe83b154b575be5ac6a3faf6622716d74b34 (a W2 verdict also covers W1, per plan §0)

The verifier posted PASS for W1 and for W2 on this commit (suite @ c989868, room message d1e80ef3).

### Reason

I25 and I13 ("an accepted reset replaces all state: old users, tokens, payments and keys are gone") can be broken without any test noticing.

- **Mutant M49.** One line added to `src/fixture.ts` `buildState`, after `const st = emptyState();`:
  `for (const [k, v] of store.state.tokens) st.tokens.set(k, v);`
  With this line, a reset carries the old token table into the new state.
- **Results with the mutant:**
  - `npm test`: 44/44 pass.
  - Acceptance suite with `--upto 2 -m "not container"`: 579 passed with the suite @ c989868, and 580 passed with the suite @ ebcc839. The container checks do not touch tokens.
- **Reproduction** (`.work/critic-h6bj/probe_m49.py`): reset fixture F (u_ada); log in as ada, giving token T; reset to F again, with the same user ids; `GET /me` with T.
  - Clean 2ffcbe8: `401 unauthenticated`. This is correct.
  - Mutant: `200 {"user_id":"u_ada",...}`.
- **Why no test catches it.** `test_reset_replaces_everything` resets to a fixture with different user ids, so a carried-over token finds no user and the test passes by accident. `test_reset_clears_idempotency_records` and `test_same_handle_can_sign_up_again_after_reset` do reset to the same fixture, but they log in again or sign up again; neither reuses the pre-reset token.
- **Missing evidence:** a test that logs in, resets to a fixture that reuses the same user ids, and expects `401 unauthenticated` for the pre-reset token. The product code needs no change.

W2's own scope is clean: all 16 W2 mutants were killed or are explained below. Once the test lands and kills M49, both W1 and W2 can be approved on 2ffcbe8.

### Evidence checked

- Clean worktree `.work/critic-h6bj/wt-2ffcbe8`: `npm test` exits 0, "tests 44, pass 44, fail 0".
- Code review of every W1 and W2 source file against plan 3.1–3.13 and D1–D35. The clause map is below.
- `grep` of `src/` for fixture identifiers, handles, emails or sample amounts found no special-casing.
- No stage-2 vocabulary in `src/`: no holds, authorizations or HTML.
- No outbound network APIs in `src/`. The Dockerfile copies `package.json` and `src/` onto `node:24.14.0-alpine3.22` and downloads nothing. The verifier's offline build and `--network=none` run passed.
- The verifier's harness run (s1-v01) failed only on the expected W3–W5 routes. Its stage-2 overshoot probe failed, as it must.

### Clause map (W1, W2)

- **3.2 transport:**
  - `app.ts readBody`: 1 MiB and 64 MiB limits; the body is always drained.
  - `json.ts parseObject`: fatal UTF-8 decoding; rejects empty bodies, invalid JSON, depth over 64, unpaired surrogates in values and keys, and non-objects.
  - `routes.ts`: 404 for unknown routes; guarded decoding (D33).
  - `app.ts answerClientError`: D28.
  - `app.ts` keep-alive 65 s and headers timeout 66 s: D35.
- **3.3 / I10:** `errors.ts`; `serve()` renders every ApiError and an `internal_error` fallback in the envelope.
- **3.8:**
  - `context.ts authenticate`: bearer regex and SHA-256 token lookup.
  - `auth.ts`: order of checks (types, presence, email, password 8–1024, display name 1–100, `email_taken`, `handle_taken`); uniqueness re-checked after the async hash; login re-verified if the state was swapped.
  - `passwords.ts`: scrypt with N=2^14 for signup and 2^12 for seeded accounts, 16-byte salt, `timingSafeEqual`, 256-bit tokens, digests only.
- **3.11 / I25:** `fixture.ts validateFixture` covers every 3.11 rule plus D34. The new state is built aside in `buildState`, and `system.ts reset` swaps it in one step.
- **3.9 / I15–I19:** `idempotency.ts`:
  - Header rules: absent or empty gives 400; more than 255 code points gives 422; latin1 bytes are read as UTF-8.
  - Records are keyed by (user, method, path, key).
  - The lookup runs before field validation.
  - The record is stored in the same synchronous step as the effects.
- **3.10 payments / I1, I2, I5, I7–I9:**
  - `payments.ts`: checks in order: handle type and presence, amount, note, visibility, 404, `self_payment`, funds, 2^53 guard.
  - `ledger.ts commitTransfer`: one synchronous step.
  - `views.ts`: exact fields, newest first, `has_more`.
- **3.13:** there is no `await` between the first read and the last write in payments or idempotency. Reset and signup re-check after their only `await`, the hashing.

### Mutants

Each mutant is one change, run in a scratch copy. Each one was run against the builder tests first, and then against the acceptance suite (@ c989868, `--upto 2`, local server) if it survived them. M13 was also run in the container with 2 CPUs and 2 GiB. A kill counts only when the failure message shows the mutated reason.

| ID | Change | Killed by | Result |
|---|---|---|---|
| M01 | A fixture rejected for a bad payment still replaces the users first | builder: rejects every invalid fixture… | killed |
| M02 | No uniqueness re-check after the async hash | builder: 10 concurrent signups… | killed |
| M03 | Case-sensitive email key | builder (3 tests) | killed |
| M04 | Derived handle truncated at 21 | builder: derives handles by code point | killed |
| M05 | Login not re-verified after a reset swaps the state | — | survived (residual, below) |
| M06 | Bearer token may carry trailing junk | builder: rejects a missing header… | killed |
| M09 | A body of exactly 1 MiB refused | — | survived (recommended test) |
| M10 | 64 levels refused | builder: accepts nesting of exactly 64 levels | killed |
| M11 | Password length in UTF-16 units | acc: test_password_length_in_code_points[😀×7-422] | killed |
| M12 | Display name length in UTF-16 units | acc: test_display_name_length_in_code_points[😀×100-201] | killed |
| M13 | Seeded accounts hashed at signup cost | acc, container: 1000-user reset ReadTimeout at 10 s | killed |
| M14 | Exactly 1000 users refused | acc: test_a_thousand_users_with_distinct_passwords… | killed |
| M16 | All accounts share one zero salt | not observable before export | carried to W5 |
| M20 | Unpaired surrogate in an object key accepted | — | survived (recommended test) |
| M22 | A request the parser refuses is dropped, no envelope | acc: test_garbage_request_line_gets_400_envelope | killed |
| M23 | display_name trimmed | acc: test_new_user_me_has_derived_handle… | killed |
| M37 | Fixture display_name type not checked | acc: test_invalid_fixture_is_422…[display_name number] | killed |
| M43 | Seeded payments replayed against seeded balances | acc: test_reset_returns_204_with_no_body_and_seeds_users | killed |
| M44 | Signup takes a `handle` field from the body | acc: test_signup_ignores_a_handle_and_a_balance_in_the_body | killed |
| M45 | Signup and login refuse unknown fields | builder: accepts nesting of exactly 64 levels (its body has an unknown field) | killed |
| M46 | A login revokes earlier tokens | builder: several valid tokens per account | killed |
| M48 | /me currency fixed to EUR | builder: replaces all state… (JPY) | killed |
| **M49** | **Reset keeps the old token table** | **—** | **SURVIVED: the BLOCK above** |
| M56 | Non-whitespace control characters allowed in email | — | survived (recommended test) |
| W07 | Key claimed before the operation runs | builder: a key that failed with 4xx is a first use | killed |
| W08 | Field validation before the claimed-key lookup | builder: precedence … claimed key | killed |
| W09 | Textual body equality | builder: replays … reordered keys | killed |
| W13 | `has_more` true when the page is exactly full | acc: test_paging_with_limit_offset_and_has_more | killed |
| W20 | Funds checked before `self_payment` | acc: test_self_payment_outranks_insufficient_funds | killed |
| W25 | Query string kept in the key path | acc: test_query_string_is_not_part_of_the_key_path | killed |
| W26 | `await` between key lookup and commit | builder: 50 concurrent identical first uses | killed |
| W28 | Visibility always "public" | builder: exactly the payment fields | killed |
| W29 | Payment currency fixed to EUR | acc: test_payment_in_other_currencies[JPY] | killed |
| W30 | Timestamps end in Z | builder: exactly the payment fields | killed |
| W35 | Default limit 20 | acc: test_default_limit_is_50 | killed |
| W36 | limit 200 refused | builder: newest first and pages | killed |
| W47 | Funds checked before an `await`, committed after it | builder: a wallet drained in parts by 50 concurrent payments | killed |
| W48 | Private payment hidden from its receiver | builder: shows a payment iff … | killed |
| W49 | Exception between debit and credit | — | discarded: it only fires on a sentinel note, and nothing between the two lines can throw |
| W50 | Replay re-renders the currency | — | equivalent in W2: reset clears records, and import restores the currency along with them |

### Spec lines in W1/W2 scope that the supplied checks never ask, and the tests that cover them

- §2 `-e PORT=<port>`: test_port_env_is_honoured_and_health_is_fast.
- §2 limits: test_service_works_within_the_resource_limits.
- §3.3 repeated resets: test_repeated_resets_work.
- §3.3 "subsequent requests must see only that fixture": test_reset_replaces_everything, but only for different user ids. This is the BLOCK.
- §3.4 unknown fields and query parameters ignored: test_signup_ignores_a_handle_and_a_balance_in_the_body, VALID_EDGES "unknown fields everywhere", test_unknown_query_parameters_are_ignored.
- §3.4 timestamps: test_plan_timestamp_form.
- §4 "you do not replay seeded payments": test_reset_returns_204_with_no_body_and_seeds_users and test_seeded_payments_follow_the_feed_rule_and_representation.
- §4 integral forms and non-numbers: test_integral_amount_forms_are_valid and test_invalid_amount_is_422_and_moves_nothing.
- §4 2^53: test_payment_that_would_push_a_balance_past_2_53_is_422.
- §5 integer query parameters: test_invalid_paging_parameters_are_422.
- §5 key range: test_key_length_range.
- §6 every table row and multiple tokens: test_w1_auth.py.
- §7 concurrent first use: builder tests and test_w2_idempotency.py.
- §8 default limit: test_default_limit_is_50.

### Residual (not blocking)

- M05, `auth.ts:65`. The re-verify when a reset swaps the state during a login's scrypt verify has code. A deterministic test would need a reset to land inside a verify of about 10 ms. I kept it as a code-review item.

### Recommended tests (plan-rule boundaries, not spec; not blocking)

- A body of exactly 1 MiB is accepted (D8).
- An unpaired surrogate in an object key is 400 (D10).
- A non-whitespace control character in an email, such as U+0007, is 422 (D12).

### Polish (recorded, not blocking)

- The 1000-user reset uses 6.1 s of its 10 s budget under `--cpus 2` (builder's measurement). D22 offers N=2^11 if more headroom is wanted.
- A signup whose hash straddles a reset is added to the new state: uniqueness is re-checked against the live state, and the signup is not abandoned. This is correct for sequential use.
- Unknown-email logins skip scrypt and answer faster. The spec does not require equal timing.

## W1: APPROVED @ 2ffcbe83b154b575be5ac6a3faf6622716d74b34 (re-review)
## W2: APPROVED @ 2ffcbe83b154b575be5ac6a3faf6622716d74b34 (re-review)

The verifier posted PASS for W1 and W2 on 2ffcbe8 with suite ee19494 (room message 1303a2dd): `run.sh --upto 2 --stage-dir wt-2ffcbe8/stage-1` gave 599 passed. The suite changes from c989868 to ee19494 are tests only. The product commit is therefore unchanged and the earlier results carry over (PROTOCOL, "When the verdict commit moves").

I reran my W1 survivors against suite ee19494 (`mutate_acc.py`, `--upto 2`, local server, `-m "not container"`):

| ID | Result |
|---|---|
| M49 | killed: test_w1_reset.py::test_reset_to_the_same_fixture_invalidates_every_earlier_token ("expected 401 unauthenticated, got 200", the mutated reason) |
| M09 | killed: test_w1_transport.py::test_body_of_exactly_one_mib_is_accepted |
| M20 | killed: test_w1_transport.py::test_unparseable_signup_body_is_400[unpaired surrogate in a key] ("expected 400 malformed_request, got 201") |
| M56 | killed: test_w1_auth.py::test_email_must_be_local_at_domain[bell\x07@example.com] |

Correction: my BLOCK message showed only M49's added line. The mutant in `mutants_w1_2ffcbe8.json` also adds `store` to fixture.ts's import from state.ts. The verifier re-created the mutant with that import.

Still open, and not blocking:
- M05 remains a residual (see above).
- M16 (one shared salt) moves to the W5 review, where the export must kill it.

## W3: BLOCKED @ 2455a8d53ed6a8b70a72b3f6fbd47d1ad1a87f56

The verifier posted PASS for W3 on this commit (suite 026f116, room message b0a26ce1): npm test 65/65, the offline build, `run.sh --upto 3` 912 passed, and the harness claims stage 1 with the two expected later-item failures.

### Reason

No test fails when the 2^53 guard is removed from `POST /requests/{id}/pay`. The guard is required by plan 3.10 (pay: "422 2^53 guard"), by D19, and by I9 ("No balance exceeds 2^53 (an operation that would is refused, D19)").

- Mutant R29 deletes one line from `payRequest` in src/handlers/requests.ts: `if (!canCredit(requester, request.amount)) throw invalid(...)`.
- With R29 every test still passes: npm test 65/65, and acceptance `--upto 3 -m "not container"` (suite 026f116, local server) 905 passed.
- Repro (`.work/critic-h6bj/probe_r29.py`): reset with ada at 1000 and bob at 2^53 − 10, bob asks ada for N, and ada pays with `{}`.
  - Clean 2455a8d: N = 11 and N = 12 both give 422 `validation_failed`, and nothing changes.
  - R29 with N = 11: 201. bob reads 2^53, because 2^53 + 1 is not representable. ada reads 989, so the sum is one unit short of the seeded total (I1).
  - R29 with N = 12: 201, and bob reads 2^53 + 2 (I9).
- Why no test catches it:
  - The guard is tested on `POST /payments` (test_w2_payments.py::test_payment_that_would_push_a_balance_past_2_53_is_422) and on `POST /settlements` (test_w4_settlements.py::test_settlement_past_2_53_is_422_and_changes_nothing).
  - No builder or acceptance test seeds a requester near 2^53 and then pays a request.
  - Trace row N32 lists only the payments test.

### Missing evidence

An acceptance test for item 3. Seed the requester at 2^53 − 10 and give the payer enough to pay. Then check:
- Paying a request of 11 is 422 `validation_failed`. Both balances are unchanged, the request is still `pending` with `payment_id: null`, no payment with that `request_id` appears in either party's feed, and the key is unclaimed.
- Paying a request of 10 is 201, and the requester then reads exactly 2^53.

No product change is needed. When the test lands I rerun R29. A tests-only delta keeps every other result below.

### Clause map (W3)

| Plan clause | Code @ 2455a8d | Killing tests (mutant) |
|---|---|---|
| 3.10 `POST /requests`: 400 non-string `payer_handle`, 422 field rules, 404, 422 `self_request` after 404, payer balance never read, `visibility` ignored | requests.ts `createRequest`; `openRequest` (pending, `payment_id` null, no balance read) | test_w3_requests: request_precedence, request_above_the_payers_balance_is_created_and_moves_nothing, request_ignores_visibility_and_spoofed_fields |
| 3.10 pay order: 422 visibility, 404, 403 for any non-payer (D5), 409 not pending, 409 funds, 422 guard | `payRequest` lines 65–71 | pay_precedence (R05, R06), only_the_payer_may_pay (R04), pay_with_bad_visibility_is_422; guard: none (R29) |
| 3.10 pay effect: payment copies amount and note (D31), visibility from the body, request `paid` with `payment_id` in the same step, a 0 request is payable | `payRequest` lines 72–78, `commitTransfer` | pay_creates_a_payment_and_marks_the_request_paid (R01, R08), zero_amount_request_from_a_split_is_payable (R09) |
| I3, I27 at most once | one synchronous callback inside `idempotent`; no `await` between the pending check and the commit | test_w3_concurrency: twenty_concurrent_pays_with_distinct_keys_pay_once (R01); builder "20 concurrent pays" (R02) |
| 3.10 decline and cancel: no key, body never read, 404, 403, `pending` → target, repeat 200, other final 409 | `settleRequest` | terminal_states_never_change and pay_racing_decline_or_cancel_has_one_winner (R03, R34), decline_and_cancel_need_no_key_and_ignore_the_body (R25) |
| 3.10 `GET /requests`: party scope, `direction`, `status`, empty or other case 422, paging | `listRequests` | filters_for_ada (R33), invalid_request_list_parameters_are_422 (R13, R13b), requests_are_newest_first_and_page (R35) |
| 3.10 `POST /splits`: 400 types first, 422 rules, 404 first unknown in order, no balance check, §9 shares, one request per non-caller with share and note, one `created_at`, caller-only `[]` | splits.ts `createSplit`, `equalShares` | specification_rounding_table and extra_unit_follows_handle_order (R32), more_than_200_participants_is_422 (R19), split note (R20), split_and_its_requests_share_one_created_at (R21b), replay of the original (R36) |
| W3.7 requests and splits never in `GET /activity` | `activity` reads `st.payments` only | test_w2_activity::test_requests_and_splits_never_appear_in_the_feed |

Error paths leave state unchanged:
- A split resolves every handle before it creates anything.
- Pay checks everything before `commitTransfer`.
- Decline and cancel change nothing before their 404, 403 or 409.

Nothing was built beyond the spec, and there is no stage-2 code.

### Mutants (21: npm test for all of them; acceptance `--upto 3 -m "not container"`, suite 026f116, for R01–R09, R21, R21b and R29)

19 killed for the mutated reason, R21 equivalent in practice, R29 survived. (Correction to my W3 room message be4e590e, which said 22 mutants and 20 killed.)

| ID | Break | Result |
|---|---|---|
| R01 | paying does not mark the request paid | killed: builder 20-concurrent-pays; test_twenty_concurrent_pays_with_distinct_keys_pay_once |
| R02 | `await` between the pending check and the commit | killed: builder 20-concurrent-pays (the mutated reason); acceptance test_pay_precedence |
| R03 | a non-pending request moves to the other final state | killed: builder decline/cancel; test_pay_racing_decline_or_cancel_has_one_winner[cancel] |
| R04 | a non-party gets 404 on pay | killed: builder error order; test_only_the_payer_may_pay[cy] |
| R05 | `request_not_pending` before the payer check | builder survived; killed: test_pay_precedence (a non-party paying a cancelled request expects 403) |
| R06 | funds before `request_not_pending` | killed: builder error order; test_pay_precedence |
| R08 | the paid payment's note is empty | killed: both suites |
| R09 | a 0 request is not payable | killed: both suites |
| R13, R13b | empty `direction` treated as absent; case-insensitive `status` | killed: builder paging and parameters |
| R19 | more than 200 participants accepted | killed: builder |
| R20 | split requests have an empty note | killed: builder |
| R21 | each split request stamped by its own `nextTs` | survived both: equivalent in practice, because the whole split runs within one millisecond |
| R21b | split requests stamped 1 ms after the split | killed: builder; test_split_and_its_requests_share_one_created_at |
| R25 | decline reads the body | killed: builder |
| R29 | no 2^53 guard on pay | **survived both: this block** |
| R32 | the extra unit goes to the last participants | killed: builder |
| R33 | `outgoing` also lists incoming | killed: builder |
| R34 | cancel turns a declined request into cancelled | killed: builder |
| R35 | listing ignores `offset` | killed: builder |
| R36 | a split replay re-renders its requests from the current state | killed: builder |

### Spec lines in W3 scope that the supplied checks never ask, and the tests that cover them

- §1 "at most once" under concurrency: test_w3_concurrency, all seven tests.
- §8 pay replay "must not return 409", "moves no additional money": test_pay_replay_is_200_never_409.
- §8 decline twice and cancel twice are 200, and the other final states are 409 in both directions: decline_and_decline_again, cancel_and_cancel_again, terminal_states_never_change.
- §8 `POST /requests` amount and note rules: invalid_request_amount_is_422, request_note_length, non_string_request_note_is_422.
- §8 `GET /requests` newest first: requests_are_newest_first_and_page.
- §8 split `shares` cover the caller and `requests` keep the order: caller_in_the_middle_keeps_order.
- §9 every table row: specification_rounding_table.
- §4 money arriving later makes the same request payable: paying_while_short_is_409_and_payable_later.
- §4 "no operation produces a balance outside ±2^53", on the pay path: **no test**. This is the block above.

## W4: BLOCKED @ e143cf11dcb300af2fc9c4e4cdacc35df93eb0cb

The verifier posted PASS for W4 on this commit (suite 026f116, room message 8a160745): npm test 77/77, the offline build, `run.sh --upto 4` 1025 passed, and the harness claims stage 1 with the one expected W5 failure.

### Reason

The code and plan 3.10 disagree on where a non-object entry in `transfers` is refused, and no test pins either order. W4.2 asks for "Validation per section 3.10".

- Plan 3.10: "422 if `transfers` is missing, not an array, empty, longer than 32, or holds an entry that is not an object. Then each entry in input order".
- Code: src/handlers/settlements.ts:18 checks object-ness inside `readTransfer`, which runs per entry in the input-order loop. An earlier entry's 404 or `self_payment` therefore wins over a later non-object entry.
- Probe on clean e143cf1 (`.work/critic-h6bj/probe_settle.py`):
  - `[{"from_handle":"ghost","to_handle":"bob","amount":1}, 5]` → 404 `not_found`. The plan says 422 `validation_failed`.
  - `[{"from_handle":"ada","to_handle":"ada","amount":1}, "x"]` → 422 `self_payment`. The plan says 422 `validation_failed`.
  - `[{"from_handle":"ada","to_handle":"ghost","amount":1}, null]` → 404. The plan says 422.
  - `[[], {"from_handle":"ghost","to_handle":"bob","amount":1}]` → 422 `validation_failed`. Both orders agree here.
- Why no test catches it: every non-object case in both suites puts the non-object entry first, or after a valid entry (`[5]`, `["x"]`, `[null]`, `[[]]`, `[valid, 7]`). Both orders answer those with 422 `validation_failed`.
- Mutant S18 adds the plan's batch-level check before the entry loop. It survives both suites: npm test 77/77, and acceptance `--upto 4 -m "not container"` 1018 passed.

### Missing evidence

The planner decides which order holds. Either way a test must pin it.

- (a) Recommended: keep plan 3.10. The builder checks that every entry is an object before the entry loop. A test pins `[t("nobody","bob",1), 7]` → 422 `validation_failed` and `[t("bob","bob",1), "x"]` → 422 `validation_failed`. This is the plan's text, and the closer reading of §11 ("transfers contains 1..32 objects", "malformed batch shape is 422").
- (b) Amend plan 3.10 to the code's per-entry order. A test then pins `[t("nobody","bob",1), 7]` → 404 `not_found`. This one is tests-only.

### Clause map (W4)

| Plan clause | Code @ e143cf1 | Killing tests (mutant) |
|---|---|---|
| 3.10 and D18: 403 for a non-operator, before the key and the body | settlements.ts:42 | test_non_operator_is_403_before_key_and_body[no key] (S01) |
| 3.10: `transfers` missing, not an array, empty, or more than 32 is 422 | :47–48 | test_malformed_batch_shape_is_422 (S09); test_key_that_failed_with_4xx_is_a_first_use_later[settlements] (S10) |
| 3.10: a non-object entry is 422 before any entry is examined | :18, but per entry, which is the deviation above | **none pins the order** (S18) |
| 3.10 per entry, in input order: handles present and strings, then amount, note and visibility (422, D27); unknown `from_handle`, then unknown `to_handle` (404); self 422 | `readTransfer` :19–29 | test_invalid_entry_is_422 (S17), test_entry_errors_in_input_order_before_funds (S08, S14), test_settlement_201_shape_and_members (S16) |
| 3.10 and I22: net affordability (409), then the 2^53 guard (422) | :52–64 | test_net_affordability_chain_through_an_empty_wallet (S02, S15), test_settlement_past_2_53_is_422_and_changes_nothing (S13) |
| 3.10, I22 and I23: one atomic step; members carry `settlement_id`, `request_id: null` and `created_at` = `committed_at`; balances move by net | :66–72, ledger.ts `recordPayment` | test_settlement_201_shape_and_members (S05, S04b), test_unaffordable_settlement_is_409_and_changes_nothing (S03, S03b) |
| 3.10: 201 with payments in input order; replay | :73 and `idempotent` | test_members_are_listed_in_input_order_newest_first, test_replay_returns_the_complete_original |
| I24 operator reach | no operator branch in `GET /requests` or `GET /activity` | test_operator_gains_no_reach_into_other_peoples_requests, test_members_follow_the_ordinary_feed_rule |

The ledger split (`recordPayment` versus `commitTransfer`) keeps `POST /payments` and pay synchronous, with the same effects as before. Nothing was built beyond the spec, and there is no stage-2 code.

### Mutants (16: npm test and acceptance `--upto 4 -m "not container"`, suite 026f116, for all of them)

| ID | Break | Result |
|---|---|---|
| S01 | operator check after the key and the body | killed: both suites (non-operator without a key expects 403) |
| S02 | affordability judged per transfer in input order | killed: test_net_affordability_chain_through_an_empty_wallet |
| S03 | a failing settlement still moves the first transfer's money | killed: test_unaffordable_settlement_is_409_and_changes_nothing[second-unaffordable] |
| S03b | a failing settlement still records a payment | killed: the same test, [empty-sender] |
| S04 | each member stamped by its own `nextTs` | survived both: equivalent in practice, because one settlement runs within one millisecond |
| S04b | members stamped 1 ms after `committed_at` | killed: test_settlement_201_shape_and_members; builder receipts test |
| S05 | members carry `settlement_id: null` | killed: test_settlement_201_shape_and_members |
| S08 | every entry's field rules checked before any entry's handles | killed: test_entry_errors_in_input_order_before_funds[case0] |
| S09 | 33 transfers accepted | killed: test_malformed_batch_shape_is_422 (33 entries) |
| S10 | empty `transfers` accepted | killed: both suites |
| S13 | no 2^53 guard | killed: test_settlement_past_2_53_is_422_and_changes_nothing |
| S14 | self-transfer checked before unknown handles | killed: test_entry_errors_in_input_order_before_funds[case6] |
| S15 | gross outgoing instead of net | killed: test_net_affordability_chain_through_an_empty_wallet |
| S16 | transfer note and visibility ignored | killed: test_settlement_201_shape_and_members |
| S17 | a non-string handle inside a transfer is 400 | killed: test_invalid_entry_is_422 (missing `from_handle`) |
| S18 | the plan's order: non-object entries rejected before the entry loop | **survived both: this block** |

### Spec lines in W4 scope that the supplied checks never ask

The supplied checks hold only test_sample.py::test_operator_can_settle_two_transfers. Every other §11 line is covered by test_w4_settlements.py, as trace rows N91–N97 list, and the kills above confirm the main ones. The gap here is at plan level: the order for a non-object entry.
