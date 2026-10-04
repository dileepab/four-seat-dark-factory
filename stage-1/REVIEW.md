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
