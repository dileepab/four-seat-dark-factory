# Stage 1 plan — Pocketful: payments and settlements

Owner: planner (`planner-h6bf`). Repository: `/Users/Dileepa/dark-factory-v3`, folder `stage-1/`.
Specification: `/Users/Dileepa/df-spec/pocketful/spec/stage-1.md` (pasted verbatim into every handoff).
Supplied checks (a partial sample, used only to wire the service up): `/Users/Dileepa/df-spec/pocketful/test/stage_1/`.

## Status

| Item | Owner | Title | State | Commit |
|---|---|---|---|---|
| W1 | builder | Foundation: container, transport, errors, reset, auth, `GET /me` | ACCEPTED (PASS + APPROVED @ 2ffcbe8, suite ee19494) | 2ffcbe8 |
| W2 | builder | Idempotency engine, payments, activity feed | ACCEPTED (PASS + APPROVED @ 2ffcbe8, suite ee19494) | 2ffcbe8 |
| W3 | builder | Requests and splits | VERIFIED (PASS @ 2455a8d, suite 026f116); awaiting critic | 2455a8d |
| W4 | builder | Settlements | VERIFIED (PASS @ e143cf1, suite 026f116); awaiting critic | e143cf1 |
| W5 | builder | Export and import | HANDED_OFF | 295378c |
| W6 | verifier | Acceptance suite for W1–W5 and I1–I29 | HANDED_OFF (complete in outline, 1037 checks; W3-W5 parts draft-run per item) | dd3097b |

States: PLANNED, BUILDING, HANDED_OFF, VERIFIED or FAILED, APPROVED or BLOCKED, ACCEPTED.

## 0. How this stage runs

- The builder takes W1 to W5 in order and hands off each one as soon as its gate is green, then starts the next. The verifier writes W6 from this plan and the specification at once, without reading the implementation.
- Routing. Builder: `HANDOFF Wn` to the verifier, the critic and the planner. Verifier: PASS or FAIL to the critic and the planner, and to the builder on FAIL. Critic: APPROVED or BLOCKED to the planner, and to the builder on BLOCKED. The planner marks an item ACCEPTED when a PASS and an APPROVED name the same commit. Questions go to the planner, who decides.
- A verdict covers the item handed off plus every earlier item. For Wn the verdict run is: the offline build and run, the builder's tests, every acceptance test marked for W1 to Wn (the verifier marks each test with the item it checks), and the supplied checks. Supplied checks that need a route from a later item (W(n+1) onward) are listed as expected failures with their names; every other failure counts. From W5 on, everything counts.
- Check command (new `--out` every run; seat letters keep runs apart: b builder, v verifier, c critic, p planner):
  `/Users/Dileepa/dark-factory-v3/scripts/harness.sh run --track pocketful --repo <repo or worktree> --stage 1 --out /Users/Dileepa/dark-factory-v3/.work/checks/s1-<letter><nn>`
- Final check (verifier, on the final commit, main repository with a clean tree):
  `/Users/Dileepa/dark-factory-v3/scripts/harness.sh run --track pocketful --repo /Users/Dileepa/dark-factory-v3 --stage 1 --mode isolated --out /Users/Dileepa/dark-factory-v3/.work/checks/s1-final-<nn>`
  The target line is `claimed stage: 1 on the shipped checks`; the stage-2 suite runs as an overshoot probe and must fail.
- Verdict runs use a clean worktree of the named commit, never the shared working tree (another seat's uncommitted files live there):
  `git -C /Users/Dileepa/dark-factory-v3 worktree add /Users/Dileepa/dark-factory-v3/.work/<handle>/wt-<short-hash> <commit>` and pass that path as `--repo`.
- Offline check (D2): `docker build --network=none -t pf-<seat>-s1 <path>/stage-1`, then `docker run -d --name pf-<seat>-s1 --network=none pf-<seat>-s1`, then `docker exec pf-<seat>-s1 node -e "fetch('http://127.0.0.1:8080/health').then(r=>r.text()).then(console.log)"`. `scripts/check-offline.sh` needs python3 inside the image, which this image does not have.
- Shared machine: container names `pf-<seat>-…`; host ports builder 18100–18199, verifier 18200–18299, critic 18300–18399, planner 18400–18499. Before a verdict run the verifier asks the other seats to start no container runs until the verdict is posted.
- Commits: commit only your own paths, `git commit -m "<message>" -- <paths>`; never `git add -A` or `git commit -a`; if `.git/index.lock` exists, wait and retry. Never amend, rebase or force-push.
- Scratch files: `.work/<your handle>/` (ignored by git).

## 1. Look-ahead: what stage 2 needs from stage 1's outputs

Stage 2 must import an export produced by this stage, keep browsers signed in across that import, keep pending requests payable, and replay a payment key from before the export with the same body. So:

- The export `state` carries `"schema": 1` and every collection the service needs (section 3.12). Nothing is derived from outside the export.
- Idempotency records keep the exact original response body, so a later stage can return it unchanged on replay.
- Nothing from stage 2 is built here: no holds, no authorizations, no `available` or `held`, no `authorization_id`, no HTML pages.

## 2. Invariants

Each one is a check a test can perform. "Every read" includes reads taken during a concurrent burst.

- **I1 Conservation.** After every operation (bursts, retries, failed calls, imports), the sum of `GET /me` `balance` over all users equals the total seeded by the last reset (after an import, the total in the imported state).
- **I2 Non-negative.** No read ever shows a negative `balance`, including reads taken during a concurrent burst.
- **I3 At-most-once requests.** A request has at most one payment. Across any mix of concurrent and repeated pay calls, with the same or different keys, the payer is debited the request amount at most once and the feed holds at most one payment with that `request_id`.
- **I4 Request lifecycle.** Status is `pending`, then exactly one of `paid`, `declined`, `cancelled`; a non-pending request never changes again. Only the payer pays or declines; only the requester cancels.
- **I5 Feed rule.** `GET /activity` for caller C contains payment P if and only if P is `public` or C is P's sender or receiver. Requests and splits never appear in it.
- **I6 Request scoping.** `GET /requests` under any filter returns only requests where the caller is the requester or the payer.
- **I7 One visibility.** Every representation of a payment (create response, replay, every feed, settlement response) carries the same `visibility`; a `private` payment is visible to both of its parties.
- **I8 Atomic payment.** Debit and credit happen together. A failed payment changes no balance, adds no feed item and claims no key. Money moves only between existing wallets.
- **I9 Exact range.** Amounts and balances are exact integers. Every amount a client submits (`POST /payments`, `POST /requests`, `POST /splits`, each settlement transfer) is an integral number from 1 to 1000000000. Only derived amounts may be 0: split shares, the requests a split creates, the payments that pay them, and fixture or import records. No balance exceeds 2^53 (an operation that would is refused, D19).
- **I10 Error envelope.** Every 4xx and 5xx body is `{"error": {"code": <non-empty string>, "message": <string>}}` with the specified status and code.
- **I11 No 5xx.** No input (malformed, oversized, wrong types, Unicode edge cases) and no load up to 50 requests in flight produces a 5xx, a dropped connection, or a response slower than 5 s (10 s for reset).
- **I12 Password storage.** No plaintext password appears in service state or in `GET /_test/export`; hashing is scrypt, bcrypt or Argon2 with a per-account salt.
- **I13 Tokens.** Tokens never expire; every token issued to an account stays valid until a reset or import replaces the state; an account may hold many.
- **I14 Handles.** Unique across the service, matching `^[a-z0-9_]{1,20}$`, never changing.
- **I15 Replay.** On each of the five idempotent paths, the same user, method, path, key and JSON-equal body returns 200 with a body JSON-equal to the original 201 body, moves no money and changes nothing, even after the resource changed or was cancelled, and after an export and import.
- **I16 Key reuse.** The same user, method, path and key with a different body returns 409 `idempotency_key_reuse` and changes nothing, whether or not the new body is valid.
- **I17 Concurrent first use.** N concurrent identical requests with an unused key give exactly one 201 and N−1 200s with identical bodies; the effect happens once.
- **I18 Failures claim nothing.** A call that fails with a 4xx leaves its key unclaimed (a later first use succeeds normally) and leaves no state change.
- **I19 Key scope.** Keys are scoped per user and per method and path: the same key from another user, or on another path, is an independent first use.
- **I20 Verbatim note.** `note` comes back exactly as sent, code point for code point, everywhere it appears.
- **I21 Split arithmetic.** Shares are integers, sum to `amount`, differ by at most one, and the larger shares go to the earliest handles; the created requests equal the non-caller shares, in order.
- **I22 Settlement atomicity.** Every transfer of a settlement commits or none does; affordability is judged on net positions; no wallet goes negative; a failed settlement creates no payment and claims no key.
- **I23 Settlement membership.** Every member payment carries the settlement's `settlement_id`, `request_id: null` and `created_at` equal to `committed_at`; every other payment has `settlement_id: null`.
- **I24 Operator reach.** Operator status grants no read access to other users' requests or private payments.
- **I25 Reset and import atomicity.** A rejected reset or import changes nothing; an accepted one replaces all state (old users, tokens, payments and keys are gone) and the next request sees only the new state.
- **I26 Export snapshot.** An export is a consistent point-in-time snapshot unaffected by later writes; importing it, once or repeatedly, restores exactly that state (ids, timestamps, balances, tokens, keys, permissions, settlement membership) with nothing duplicated or replayed, into this or another container.
- **I27 Serializable (inferred).** Concurrent operations give the results of some one-at-a-time order (for example, a concurrent pay and decline of one request: exactly one wins).
- **I28 Unique ids (inferred).** Within each entity type, ids are unique across seeded, imported and generated entities; every id is at most 64 characters.
- **I29 Time and order (inferred).** List endpoints return newest first by `created_at`; timestamps are RFC 3339 with an explicit offset and never decrease in creation order.

## 3. Interface contract

### 3.1 Runtime

- `stage-1/Dockerfile`, build context `stage-1/`. The Dockerfile downloads nothing: it copies the source onto a pinned `node:24` base image (W1 uses `node:24.14.0-alpine3.22`) (D1, D2) and runs as a non-root user.
- Listen on `0.0.0.0:$PORT`, default 8080. `GET /health` returns 200 `{"status": "ok"}` as soon as the server listens (target under 5 s from container start).
- State is in memory; a restart starts empty. Before any reset there are no users, currency `EUR`, `minor_units` 2 (D29).

### 3.2 Transport and parsing (every endpoint)

- Responses are JSON with `Content-Type: application/json; charset=utf-8`; a 204 has no body. The request `Content-Type` is not checked; a body is read as UTF-8 JSON.
- Body limit: 1 MiB on API endpoints, 64 MiB on `POST /_test/reset` and `POST /_test/import`. A larger body gets 422 `validation_failed`; the server drains the body before answering so the client always reads the response (D8).
- 400 `malformed_request` when a body that the endpoint reads is: not valid UTF-8, not valid JSON, empty (zero bytes or whitespace), nested deeper than 64 levels, holding a string with an unpaired surrogate such as `"\ud800"`, or not a JSON object at the top level (D7, D9, D10). Decline and cancel never read the body.
- Header blocks up to 1 MiB are accepted. When the HTTP layer itself rejects a request, the answer still carries the envelope: 422 `validation_failed` for oversized headers, 400 `malformed_request` otherwise (D28).
- Unknown body fields and unknown query parameters are ignored. A repeated query parameter uses its first occurrence (D25).
- "Characters" means Unicode code points everywhere: note, password and display name lengths, key length, handle derivation and truncation (D11).
- An unknown path, or a known path with a method it does not serve, is 404 `not_found` (D3). A path that does not percent-decode (for example `/requests/%E0%A4%A/pay`) is also 404 `not_found`, never a 5xx (D33).
- An unexpected internal error answers 500 with code `internal_error`; this must never happen (I11).

### 3.3 Error codes (complete for stage 1)

400 `malformed_request`, 400 `missing_idempotency_key`, 401 `unauthenticated`, 403 `forbidden`, 404 `not_found`, 409 `idempotency_key_reuse`, 409 `insufficient_funds`, 409 `request_not_pending`, 409 `email_taken`, 409 `handle_taken`, 422 `validation_failed`, 422 `self_payment`, 422 `self_request`, 500 `internal_error` (never expected).

### 3.4 Field rules

| Field | Wrong JSON type (including `null`) | Missing | Bad value |
|---|---|---|---|
| `amount` (every endpoint) | 422 `validation_failed` | 422 | 422 when not integral (`1.5`), below 1, above 1000000000, or not finite. Integral forms `1000.0` and `1e3` are valid. |
| `note` | 422 | defaults to `""` | 422 when longer than 200 code points |
| `visibility` | 422 | defaults to `"public"` | 422 unless exactly `"public"` or `"private"` |
| `to_handle`, `payer_handle` | 400 `malformed_request` | 422 | any string that names no user, including `""`, `"ADA"`, `"@ada"`, is 404 `not_found` (D4) |
| `participant_handles` | 400 when not an array or any element is not a string | 422 | see `POST /splits` |
| `email`, `password`, `display_name` | 400 | 422 | see section 3.8 |
| `transfers` and every field inside it | 422 `validation_failed` (D27) | 422 | see `POST /settlements` |

### 3.5 Precedence (the first failing step answers)

1. Route: unknown path or method, 404.
2. Authentication (non-exempt endpoints): 401.
3. Caller permission that does not depend on the body (settlements: non-operator), 403.
4. Idempotent paths: `Idempotency-Key` absent or empty, 400 `missing_idempotency_key`; longer than 255 characters, 422.
5. Body: over the size limit, 422; unreadable or not an object, 400.
6. Idempotent paths: claimed-key resolution (section 3.9). A record for (user, method, canonical path, key) with a JSON-equal body answers 200 with the stored body; with a different body, 409 `idempotency_key_reuse`.
7. Field types that give 400 (section 3.4).
8. Field presence and value rules, 422 `validation_failed`.
9. Referenced resource missing, 404 (handles; the request in the path).
10. Party permission, 403.
11. Semantic rules, 422 `self_payment` or `self_request`.
12. State rules, 409 (`request_not_pending`, `email_taken`, `handle_taken`).
13. Funds, 409 `insufficient_funds`; then the 2^53 guard, 422 `validation_failed` (D19).
14. Commit every effect in one atomic step; on an idempotent path the key record is stored in that same step.

### 3.6 Representations (exactly these fields; no extra fields in stage 1)

- Me: `{"user_id", "display_name", "handle", "balance", "currency", "minor_units"}`.
- Payment, identical wherever a payment appears (create, replay, pay, feed, settlement): `{"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency", "note", "visibility", "request_id", "settlement_id", "created_at"}`. `request_id` is the paid request or `null`; `settlement_id` is the settlement or `null`.
- Request: `{"request_id", "requester_id", "requester_handle", "payer_id", "payer_handle", "amount", "currency", "note", "status", "payment_id", "created_at"}`.
- Split: `{"split_id", "amount", "currency", "note", "shares": [{"handle", "amount"}], "requests": [Request], "created_at"}`.
- Settlement: `{"settlement_id", "committed_at", "payments": [Payment]}`.
- Signup and login: `{"user_id", "display_name", "token"}`.
- Lists: `{"payments": [...], "has_more": bool}` and `{"requests": [...], "has_more": bool}`.

### 3.7 Ids, timestamps, order, paging

- Seeded ids are used verbatim. Generated ids are `<prefix>_<random>` with prefixes `u`, `p`, `rq`, `sp`, `st`, at least 80 random bits, at most 64 characters, redrawn if equal to an existing id of the same type (D16).
- Timestamps are UTC in exactly the form `YYYY-MM-DDTHH:MM:SS.sss+00:00` (three fractional digits). Each issued timestamp is at least the previous one issued (D14). Seeded payments and requests take the reset's timestamp; timestamps inside a fixture are ignored; fixture array order is creation order (D15).
- Lists are newest first by `created_at`; ties go to creation order, later first. Settlement members are created in input order.
- `limit` defaults to 50 and `offset` to 0. A value must be ASCII digits only (`^[0-9]+$`), else 422; `limit` 1 to 200; `offset` 0 or more with no upper bound, and an offset past the end returns an empty page with `has_more: false` (D26). `has_more` is true when matching items exist after the returned page.

### 3.8 Authentication

- Exempt endpoints never read `Authorization`, even an invalid one: `GET /health`, `POST /_test/reset`, `GET /_test/export`, `POST /_test/import`, `POST /auth/signup`, `POST /auth/login`.
- Every other endpoint needs `Authorization: Bearer <token>` (scheme case-insensitive, one or more spaces, a non-empty token without spaces). Missing header, other scheme, empty token or unknown token is 401 `unauthenticated`.
- Tokens: at least 256 random bits, base64url, stored only as SHA-256 hashes (D30). They never expire. Each signup and login issues a new token; earlier tokens stay valid.

`POST /auth/signup` `{"email", "password", "display_name"}`:

- Each field must be a string (else 400) and present (else 422).
- `email`: exactly one `@`, a non-empty local part and domain, no whitespace or control characters, at most 254 code points; else 422 (D12).
- `password`: 8 to 1024 code points; else 422 (D13).
- `display_name`: 1 to 100 code points, stored verbatim; else 422 (D13).
- Email already registered, compared case-insensitively: 409 `email_taken` (D12).
- Derived handle already taken: 409 `handle_taken`, and no account is created. Derivation: take the local part, lowercase it, replace every code point outside `[a-z0-9_]` with `_`, keep the first 20 code points. `Dee.Ann+tag@example.com` gives `dee_ann_tag`.
- Order: types, presence, email, password, display name, `email_taken`, `handle_taken`. Uniqueness is checked again when the account is committed, so concurrent signups produce exactly one winner and the right 409 for the rest.
- 201 `{"user_id", "display_name", "token"}`; the new wallet holds 0.

`POST /auth/login` `{"email", "password"}`: string types (400), presence (422), email form (422); unknown email (case-insensitive) or wrong password is 401 `unauthenticated`. No password-length rule at login. 200 `{"user_id", "display_name", "token"}`.

Password hashing (D22): scrypt with a 16-byte random salt per account and the parameters stored with the hash; signup uses N=2^14, r=8, p=1 or stronger; seeded accounts may use N=2^12 so a large reset fits its budget. Verification is constant-time. Hashing runs off the event loop; anything written after it re-checks the current state, because a reset or import may have happened meanwhile.

### 3.9 Idempotency

- Paths: `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`.
- A record is keyed by (user id, method, canonical path, key). The canonical path is the route with its decoded path parameter and no query string, for example `/requests/rq_4/pay`.
- Body equality is JSON-value equality after parsing: objects compare as key sets, arrays in order, strings by code points, numbers by numeric value (`1000`, `1000.0`, `1e3` are equal). `{}` and `{"visibility": "public"}` differ.
- A record is stored only when the call succeeds with 201, in the same atomic step as its effects: the parsed body and the exact response body. A 4xx stores nothing.
- Calls that share a record key are serialized; a duplicate that waited sees the first call's outcome (a 200 replay if it succeeded, a first use if it failed).
- Records are part of the exported state; reset clears them.

### 3.10 Endpoints

`GET /me`: 200 Me.

`POST /payments` (idempotent) `{"to_handle", "amount", "note"?, "visibility"?}`: 422 for field rules; 404 if no user has `to_handle`; 422 `self_payment` if it is the caller's handle; 409 `insufficient_funds` if the caller's balance is below `amount`; 422 if the receiver would exceed 2^53. 201 Payment with `request_id: null`, `settlement_id: null`.

`GET /activity?limit&offset`: 200 `{"payments", "has_more"}` by rule I5. Other parameters, including `direction` and `status`, are ignored.

`POST /requests` (idempotent) `{"payer_handle", "amount", "note"?}`: 422 field rules; 404 unknown payer; 422 `self_request`; the payer's balance is never checked. 201 Request with `status: "pending"`, `payment_id: null`. A `visibility` field is ignored.

`POST /requests/{id}/pay` (idempotent) `{"visibility"?}`: 422 visibility rule; 404 unknown request; 403 `forbidden` if the caller is not the payer, including callers who are not a party (D5); 409 `request_not_pending`; 409 `insufficient_funds`; 422 2^53 guard. 201 Payment with `request_id` set, `visibility` from the body (default `public`), `amount` and `note` copied from the request (D31). In the same step the request becomes `paid` with `payment_id`. A request of amount 0 is payable and creates a payment of 0 (D24).

`POST /requests/{id}/decline` (no key, body ignored): 404 unknown; 403 unless the caller is the payer; `pending` becomes `declined` (200); `declined` stays (200, current state); `paid` or `cancelled` is 409 `request_not_pending`. 200 Request.

`POST /requests/{id}/cancel` (no key, body ignored): the same for the requester: `pending` becomes `cancelled`; `cancelled` stays (200); `paid` or `declined` is 409.

`GET /requests?direction&status&limit&offset`: 200 `{"requests", "has_more"}` where the caller is a party. `direction` is `incoming` (caller is payer) or `outgoing` (caller is requester) or absent; `status` is one of the four or absent; any other value, including empty or a different case, is 422.

`POST /splits` (idempotent) `{"amount", "participant_handles", "note"?}`:

- 400 if `participant_handles` is not an array or has a non-string element.
- 422 if `amount` is invalid; `participant_handles` is missing, empty, longer than 200 entries (D20) or holds the same string twice; `note` is invalid.
- 404 for the first handle, in order, that names no user.
- No balance is checked. The caller may be listed or not.
- Shares, n = number of handles: `base = floor(amount / n)`, `r = amount − base·n`, share i (from 0) is `base + 1` if `i < r`, else `base`, in the given order.
- For each participant other than the caller, in order, a pending request with the caller as requester, that participant as payer, the share as amount (0 is allowed) and the split's note. Split and requests are created in one step with one `created_at`.
- 201 Split; a split listing only the caller has `"requests": []`.

`POST /settlements` (idempotent, operators only):

- 401 without a valid token; 403 `forbidden` if the caller is not in `settlement_operator_ids`, checked before the key and the body.
- 422 if `transfers` is missing, not an array, empty, longer than 32, or holds an entry that is not an object.
- Then each entry in input order; the first entry with any error decides the answer. Within an entry: `from_handle` and `to_handle` present and strings, `amount`, `note`, `visibility` by the payment rules (422); unknown `from_handle`, then unknown `to_handle` (404); `from_handle` equal to `to_handle` (422 `self_payment`).
- Affordable when, for every wallet, balance + incoming − outgoing ≥ 0; otherwise 409 `insufficient_funds`. Then the 2^53 guard (422).
- One atomic step: one Payment per transfer, with the new `settlement_id`, `request_id: null` and `created_at` equal to `committed_at`; balances move by their net amounts.
- 201 Settlement with payments in input order.

### 3.11 Reset

`POST /_test/reset` (unauthenticated), body is the fixture, 204 on success. A body that is not a JSON object is 400. Any rule below that fails is 422 `validation_failed` and nothing changes (D21):

- `currency`: string matching `^[A-Z]{3}$`. `minor_units`: integer 0, 2 or 3.
- `users`: array of at most 1000 objects, each with `id` (string, 1 to 64 characters), `email` (signup email rule), `password` (non-empty string), `display_name` (string), `handle` (`^[a-z0-9_]{1,20}$`), `balance` (integer 0 to 2^53). Ids, emails (case-insensitive) and handles are unique.
- `payments`: optional array (default `[]`) of objects with `id` (string, 1 to 64, unique), `from_user_id` and `to_user_id` (existing users, different), `amount` (integer 0 to 1000000000), `note` (optional string, default `""`), `visibility` (optional, `public` or `private`, default `public`), `request_id` (optional string or null), `settlement_id` (optional string or null, shown unchanged in every representation of that payment, D34).
- `requests`: optional array (default `[]`) of objects with `id` (string, 1 to 64, unique), `requester_id` and `payer_id` (existing users, different), `amount` (integer 0 to 1000000000), `note` (optional string, default `""`), `status` (optional, one of the four, default `pending`), `payment_id` (optional string or null).
- `settlement_operator_ids`: optional array (default `[]`) of strings, each an existing user id.
- Unknown fields are ignored. Balances are taken as given; seeded payments are not replayed.
- Seeded passwords are hashed before the swap; the whole state is swapped in one step. A 1000-user fixture with distinct passwords answers within 10 s on 2 vCPU.

### 3.12 Export and import

`GET /_test/export` (unauthenticated): 200 `{"track": "pocketful", "format_version": 1, "state": {...}}`. `state` holds `"schema": 1` and everything the service needs: currency, minor units, users with password hash records, token hashes, payments, requests, splits, settlements, operator ids, idempotency records (user, method, path, key, parsed body, response body), the creation sequence and the last issued timestamp. It is built in one synchronous step, so later writes do not change it.

`POST /_test/import` (unauthenticated), body is an export object:

- 400 `malformed_request` for invalid JSON or a non-object body.
- 422 `validation_failed` if `track` is not `"pocketful"`, `format_version` is not the number 1, `state` is missing or not an object, or `state` fails full validation (`schema` 1, types, references, unique ids, balances integers 0 to 2^53, valid statuses). Nothing changes.
- Otherwise the whole state is replaced in one step: 204. Earlier users, tokens and keys are gone. Importing the same export twice gives the same state.
- After import: imported tokens authenticate, logins work with the imported hashes, replays of imported keys return 200 with the stored body, failed keys are reusable, new ids never collide, new timestamps are not earlier than imported ones.

### 3.13 Concurrency model

- One process with in-memory state. Each operation's read-check-write runs synchronously with no `await` between its first read and its last write, so the event loop is the single serialization point. Only password hashing is asynchronous, and the code after it re-validates against the current state (a generation counter changes on every reset and import).
- Reset and import build the new state aside, then swap it in one synchronous step.
- 50 requests in flight each complete within 5 s; `GET /health` stays responsive.
- Idle keep-alive connections stay open at least 65 s (`server.keepAliveTimeout` ≥ 65 000 ms, `server.headersTimeout` above it), so a client pool that reuses a connection after 5 s idle never races a server-side close (D35).

## 4. Work items

Every item's handoff names its commit, the gate evidence (build, builder tests, acceptance suite, supplied checks) and its gaps.

### W1 Foundation (builder)

Specification: §2, §3, §4 (users, handles, fixture), §5, §6, §8 `GET /me`. Invariants: I10, I11, I12, I13, I14, I25, I28, I29.

- W1.1 `docker build --network=none stage-1` succeeds once the base image is present; `docker run -e PORT=9123` serves on 9123 and without `PORT` on 8080; `GET /health` is 200 `{"status": "ok"}` within 60 s (expected under 5 s); the container works with `--network=none`.
- W1.2 `RUN.md` gives exact commands to build, run, run the builder tests and run the acceptance suite, with no manual setup.
- W1.3 Every rule of sections 3.2 and 3.3, each with the envelope; unknown route is 404; a path that does not percent-decode is 404; an idle keep-alive connection reused after 6 s still gets its response.
- W1.4 Reset per section 3.11: each failing rule gives 422 and leaves the previous state intact (old logins still work); a valid fixture gives 204 and only that fixture is visible; repeated resets work; the 1000-user fixture answers within 10 s; a fixture payment with `settlement_id` shows it in the feed, one without shows `null`; a token issued before a reset is 401 after it, even when the new fixture reuses the same user ids (critic M49).
- W1.5 Signup and login per section 3.8: every row of the table, derived handles (`Dee.Ann+tag@example.com` → `dee_ann_tag`, 30 × `a` → 20 × `a`, upper case and non-ASCII local parts), `handle_taken` creates no account, `email_taken` is case-insensitive, seeded users log in at once, several tokens per account all work.
- W1.6 Every non-exempt endpoint rejects a missing header, another scheme, an empty token and an unknown token with 401; exempt endpoints ignore even an invalid `Authorization` header.
- W1.7 `GET /me` per section 3.6 for seeded and new users (new users hold 0 in the service currency).
- W1.8 Passwords are stored only as salted hashes (code review now; re-checked through export in W5).
- W1.9 50 concurrent logins each answer within 5 s with no 5xx; 10 concurrent signups with one email give one 201 and nine 409 `email_taken`; concurrent signups that derive one handle give one 201 and the rest 409 `handle_taken`.

### W2 Idempotency engine, payments, feed (builder)

Specification: §1, §4 (payments, feed, arithmetic), §5, §7, §8 `POST /payments`, `GET /activity`. Invariants: I1, I2, I5, I7, I8, I9, I10, I11, I15–I20, I27, I29.

- W2.1 `POST /payments` 201 per section 3.6; defaults for note and visibility; notes round-trip verbatim (surrounding spaces, emoji, HTML, accents); 200 emoji accepted, 201 code points refused.
- W2.2 Every error row of `POST /payments`, every field rule of section 3.4 and the precedence of section 3.5 (missing key before a bad body; a claimed key before an invalid new body; `self_payment`; `insufficient_funds`; the 2^53 guard).
- W2.3 Idempotency per section 3.9 on `POST /payments`: all five rows of the specification's table; scoping by user and by path; 50 concurrent identical first uses give one 201 and 49 identical 200s and move money once; a replay after the balance changed returns the original; a key that failed with 4xx is a first use later.
- W2.4 Money under load: a wallet drained in parts by 50 concurrent payments gives exactly floor(balance / amount) 201s and 409 for the rest, with the remainder left and no negative read; three wallets paying around a cycle; conservation across 50 wallets.
- W2.5 `GET /activity`: rule I5 for sender, receiver and third party with public and private payments; newest first; `limit`, `offset`, `has_more`; invalid paging values are 422; unknown parameters ignored; every item JSON-equal to the receipt that created it.

### W3 Requests and splits (builder)

Specification: §4 (requests), §8 request endpoints and `POST /splits`, §9. Invariants: I1, I3, I4, I6, I15, I21, I27.

- W3.1 `POST /requests`: representation; a request above the payer's balance is 201 `pending`; 422, 404 and `self_request` with section 3.5 precedence.
- W3.2 Pay: representation; the request becomes `paid` with `payment_id`; visibility from the body, default public; errors in the order 422, 404, 403, 409 `request_not_pending`, 409 `insufficient_funds`; replaying a successful pay returns 200 with the original, never 409; `{}` and `{"visibility": "public"}` are different bodies; a key refused for funds is reusable after funding and pays once; seeded requests are payable and seeded non-pending ones are 409.
- W3.3 At most once: 20 concurrent pays of one request with distinct keys give one 201 and 409 `request_not_pending` for the rest; concurrent pay and decline, and pay and cancel, have exactly one winner; money moves at most once.
- W3.4 Decline and cancel: transitions; repeating the same action is 200; other terminal states are 409; the wrong party, including a non-party, is 403; unknown is 404; no key needed.
- W3.5 `GET /requests`: a non-party sees nothing under any filter; filters work alone and together; invalid `direction`, `status`, `limit`, `offset` are 422; newest first; paging and `has_more`.
- W3.6 `POST /splits`: the specification's §9 table; the extra unit moves with handle order; caller listed or not; zero shares still create requests; a caller-only split creates none; empty, duplicate, more than 200 and 1000-handle lists are 422; an unknown handle is 404; a non-string handle is 400; no balance checks; replays; conservation after all split requests are paid.
- W3.7 Requests and splits never appear in `GET /activity`.

### W4 Settlements (builder)

Specification: §11. Invariants: I1, I2, I15–I19, I22, I23, I24.

- W4.1 Permission comes from `settlement_operator_ids` in the fixture; no token is 401; a non-operator is 403 even without a key or with a bad body.
- W4.2 Validation per section 3.10: batch shape 422; 1 to 32 entries; entry errors decided in input order, each before any funds check.
- W4.3 Net affordability: a chain through a wallet that starts at 0 succeeds; any wallet ending below zero gives 409 and nothing changes.
- W4.4 Response in input order; members carry `settlement_id`, `request_id: null`, `created_at` equal to `committed_at`; ordinary payments carry `settlement_id: null`; members appear in feeds by the ordinary rule, so a private member between two other users is hidden from the operator's feed.
- W4.5 Replay returns 200 with the complete original; a failed settlement leaves its key unclaimed; concurrent settlements and payments stay conserved and non-negative.
- W4.6 An operator gains no read access to other users' requests or private payments.

### W5 Export and import (builder)

Specification: §10, last paragraph of §11. Invariants: I12, I15, I25, I26, I28.

- W5.1 Export shape; unauthenticated; later writes do not change an export already returned; no plaintext password anywhere in it.
- W5.2 Round trip in the same container after a reset, and into a second container: tokens from before the export work, logins work, `GET /me`, feeds and request lists are identical (ids, timestamps, order), replays of earlier keys return 200 with the original bodies, keys that failed earlier are reusable, settlements and operator permissions survive; users and tokens created after the export are gone; importing twice equals importing once; a reset after an import clears it.
- W5.3 Rejected imports (invalid JSON 400; missing `track`, `format_version` or `state`, wrong track, wrong version, non-object state, a corrupt state such as a negative balance or a dangling user reference, all 422) leave the destination unchanged.
- W5.4 After an import, new payments, requests, splits and settlements get ids that never collide with imported ones, and new timestamps are not earlier than imported ones.

### W6 Acceptance suite (verifier)

Specification: all of stage 1. Invariants: all.

- W6.1 `stage-1/acceptance/` holds a suite written from this plan and the specification, not from the code, runnable with one documented command against a base URL.
- W6.2 Every criterion W1.1–W5.4 and every invariant I1–I29 has at least one test; I1 and I2 are asserted after every state-changing test and during every burst.
- W6.3 It covers bursts of 50, duplicates and concurrent duplicates, import into a second container, and the boundary inputs of sections 3.2 to 3.11.
- W6.4 Its path and commit are posted before the W1 verdict; it grows whenever the trace (section 6) finds a gap.

## 5. Decisions

- **D1 Stack.** Node.js 24 with TypeScript run through Node's built-in type stripping, the `node:http` server, `node:crypto` scrypt, `node:test` for builder tests, in-memory state, no npm runtime dependencies. One language for the API now and the browser UI in stage 2; the event loop gives a single serialization point for every read-check-write; nothing to download at build time.
- **D2 Offline build.** The Dockerfile installs nothing, so the image builds with `--network=none` and the verifier's offline build check works. The image has no python3; probe with `node -e`.
- **D3 Unmatched routes.** 404 `not_found` for unknown paths and unsupported methods. The specification defines no 405 code, and every 4xx must carry a defined code.
- **D4 Handle lookups.** A handle string that names no user is 404, whatever its format. The tables say "No user has that handle: 404"; a malformed handle is such a case, and §5's format rule yields to endpoint-specific errors.
- **D5 Non-parties on request actions.** 403 `forbidden`. The tables say "The caller is not the request's payer: 403", which covers non-parties; stage 2 states the same rule explicitly for its new resource.
- **D6 Precedence.** Section 3.5. The specification fixes the key resolution point (after parse and authentication, before validation); the rest follows the usual cheapest-first order, so a request is never told about state it was not entitled to change.
- **D7 Empty body.** An empty body on an endpoint that reads one is 400 (it is not parseable JSON). Decline and cancel take no body and never read one.
- **D8 Body limits.** 1 MiB for API calls, 64 MiB for reset and import; larger is 422 (§5: values exceeding a stated maximum), drained first so the client reads the answer.
- **D9 Depth.** Nesting deeper than 64 is unparseable for this service: 400.
- **D10 Invalid text.** Invalid UTF-8 and unpaired surrogates are 400: such a body is not valid text and could not round-trip byte for byte.
- **D11 Characters.** Unicode code points everywhere, as the 200-emoji note rule requires.
- **D12 Email.** Exactly one `@`, non-empty local part and domain, no whitespace, at most 254 code points. Uniqueness and login lookup ignore case. Login applies the email-form rule (the table covers both endpoints) but not the password-length rule (a wrong password of any length is 401).
- **D13 Lengths.** Password 8 to 1024 code points; display name 1 to 100. Bounds every unbounded string input.
- **D14 Timestamps.** UTC, `+00:00`, exactly three fractional digits, never decreasing: string order equals time order.
- **D15 Seeded times.** Seeded records take the reset time; fixture timestamps are ignored (the fixture format defines none); fixture order is creation order.
- **D16 Ids.** Seeded ids verbatim; generated ids random with a type prefix and a collision check, so seeded and imported ids can never be reissued.
- **D17 Idempotency scope.** (user, method, canonical path, key), JSON-value body equality with numeric equality; stored only on 201 in the same atomic step. §7: "same method, the same path and the same body", "same JSON value after parsing", 4xx keys are a first use.
- **D18 Settlement permission first.** A non-operator gets 403 before the key and body are examined: permission depends only on the caller.
- **D19 Range guard.** An operation that would push a balance above 2^53 is refused with 422 `validation_failed` and changes nothing; fixtures and imports with a balance above 2^53 are 422. This keeps "no operation produces a balance outside ±2^53" true whether it is read as a promise or as a requirement.
- **D20 Split size.** At most 200 participants; more is 422. The specification sets no bound; 200 matches the largest page, and a 1000-handle list must be refused without a crash.
- **D21 Fixture validation.** Validate what the service needs to operate (types, references, uniqueness, enums, integer ranges, at most 1000 users); stay lenient elsewhere (any note length, any display name, optional fields with defaults) so a valid fixture is never refused.
- **D22 Password hashing.** scrypt, per-account salt; seeded accounts may use the lower work factor N=2^12 so a 1000-user reset stays under the 10 s reset timeout; signups use N=2^14 or stronger.
- **D23 Import validation.** Full validation of the state before any change; `format_version` must equal the number 1.
- **D24 Zero-amount requests.** A zero share is a legal request (§9) and paying it moves 0: the payment carries amount 0. Every client-submitted amount keeps the 1-minimum (§8 tables, §11 "ordinary payment amount rules"); only derived amounts may be 0.
- **D25 Repeated query parameter.** The first occurrence is used.
- **D26 Large offset.** Valid; returns an empty page.
- **D27 Settlement shape errors.** Everything inside `transfers` that is malformed is 422, never 400: §11 says "malformed batch shape is 422".
- **D28 HTTP-layer rejections.** Header blocks up to 1 MiB; anything the HTTP layer refuses still carries the envelope.
- **D29 Initial state.** Empty, EUR with 2 minor units, until the first reset.
- **D30 Token storage.** SHA-256 hashes of tokens in state and export; the bearer value itself is never stored.
- **D31 Payment note when paying a request.** Copied from the request, as are the amount and the parties; the visibility comes from the payer's body.
- **D32 Login timing.** An unknown-email login may answer faster than a wrong-password one: the specification asks for 401 in both cases, not for equal timing, and a dummy hash would add CPU to every bad login.
- **D22 measured (W1, 99d2431).** A 1000-user reset with 1000 distinct passwords at N=2^12 answers 204 in 6.1 s under `--cpus 2 --memory 2g`; kept, since only our own 1000-user envelope comes near the 10 s budget.
- **D33 Undecodable paths.** 404 `not_found`: no resource has that name, and §5 forbids a 5xx. (Critic plan review.)
- **D34 Fixture settlement membership.** Fixture payments accept `settlement_id`, because §11 says a reset must preserve settlement membership; without it a seeded member would read back as `null`. (Critic plan review.)
- **D35 Keep-alive.** Server idle timeout above the client pool's 5 s, so I11's "no dropped connection" holds for reused connections. (Critic plan review.)
- **D36 Stored request bodies (W5 gap, accepted).** Idempotency records keep the parsed body, so a state holding more than about 64 MiB of stored bodies would export but exceed the 64 MiB import limit. Accepted as is: notes are capped at 200 characters, no specified flow stores large bodies, and raising the import limit would risk the 2 GiB memory limit while parsing.

## 6. Specification trace

Each normative line of stage-1.md, condensed, with the acceptance tests that exercise it (file prefix `test_` and test prefix `test_` omitted). Rows without tests wait for the W2 to W5 parts of the suite; a row still empty when its item's tests land is a gap and becomes a criterion at once.

| N | Spec | Normative line (condensed) | Plan | Tests | Status |
|---|---|---|---|---|---|
| N1 | §1 | Sum of balances always equals total seeded by last reset | I1 | w2_load: one_wallet_drained_in_parts_by_fifty_payments, three_wallets_paying_around_a_cycle, conservation_across_fifty_wallets; support: I1 after every test | covered by c989868 |
| N2 | §1 | No balance negative, including transiently | I2 | w2_load: every burst reads balances while it runs; support: I2 after every test | covered by c989868 |
| N3 | §1 | A payment request moves money at most once | I3 | w3_concurrency: twenty_concurrent_pays_with_distinct_keys_pay_once, fifty_concurrent_pays_with_one_key_pay_once, shared_key_and_distinct_keys_racing_pay_once | covered by dd3097b (not yet run on a W3+ product) |
| N4 | §1 | Amounts are exact integer minor units | I9 | w2_payments: large_balances_are_exact, integral_amount_forms_are_valid, payment_in_other_currencies | covered by c989868 |
| N5 | §1 | Money moves only between existing wallets | I8 | w2_payments: handle_that_names_no_user_is_404, insufficient_funds_is_409_and_leaves_no_trace | covered by c989868 |
| N6 | §2 | Dockerfile + RUN.md command builds and starts with no manual setup | W1.1 W1.2 | w1_container: stage_folder_has_dockerfile_and_run_md_and_no_git, run_md_gives_build_run_and_test_commands | covered by 16f24a6 |
| N7 | §2 | Image runs alone with -e PORT and a port mapping; no runtime outbound network; deps and seed inside | W1.1 | w1_container: offline_image_serves_health_with_no_network_on_default_port, port_env_is_honoured_and_health_is_fast | covered by 16f24a6 |
| N8 | §2 | 2 vCPU, 2 GiB, healthy within 60 s, 50 in flight, 5 s per request (10 s reset) | I11 W1.9 W2.4 | w1_container: service_works_within_the_resource_limits; w1_auth: fifty_concurrent_logins; w1_reset: a_thousand_users_with_distinct_passwords_reset_within_ten_seconds (money paths under load: W2) | covered by 16f24a6 |
| N9 | §2 | Runtime assets inside the image | W1.1 | w1_container: offline_image_serves_health_with_no_network_on_default_port | covered by 16f24a6 |
| N10 | §3.1 | Listen on 0.0.0.0:PORT, default 8080 | W1.1 | w1_container: default_port_is_8080, port_env_is_honoured_and_health_is_fast | covered by 16f24a6 |
| N11 | §3.2 | GET /health 200 {"status":"ok"} once ready, within 60 s | W1.1 | w1_transport: health_is_200_status_ok; w1_container: port_env_is_honoured_and_health_is_fast | covered by 16f24a6 |
| N12 | §3.3 | Reset replaces all state, 204, next requests see only the fixture, repeatable, unauthenticated | I25 W1.4 | w1_reset: reset_returns_204_with_no_body_and_seeds_users, reset_replaces_everything, repeated_resets_work, reset_ignores_an_invalid_authorization_header | covered by 16f24a6 |
| N13 | §3.4 | JSON utf-8 requests and responses | W1.3 | support: content-type asserted on every JSON response; w1_transport: request_content_type_is_not_checked | covered by 16f24a6 |
| N14 | §3.4 | Timestamps RFC 3339 with explicit offset | I29 | w1_reset: plan_timestamp_form (item 2) | covered by 16f24a6 |
| N15 | §3.4 | Unknown body fields ignored | W1.3 | w1_auth: signup_ignores_a_handle_and_a_balance_in_the_body; w1_reset: valid_fixture_edges[unknown fields everywhere] | covered by 16f24a6 |
| N16 | §3.4 | Unknown query parameters ignored | W1.3 W2.5 | w1_transport: unknown_query_parameters_are_ignored | covered by 16f24a6 |
| N17 | §3.4 | Ids opaque, at most 64 characters | I28 | support: every id checked as 1..64 chars; w1_reset: invalid_fixture[user id 65 chars], valid_fixture_edges[user id of 64 chars] | covered by 16f24a6 |
| N18 | §4 | One currency from the fixture; /me reports currency and minor_units | W1.7 | w1_reset: currency_and_minor_units_come_from_the_fixture; w1_auth: new_user_in_a_jpy_service_holds_zero_yen | covered by 16f24a6 |
| N19 | §4 | 1000, 1000.0, 1e3 valid and equal; booleans and strings are not numbers | §3.4 W2.2 | w2_payments: integral_amount_forms_are_valid, invalid_amount_is_422_and_moves_nothing, non_finite_or_fractional_raw_amount_is_422; w2_idempotency: numerically_equal_numbers_are_the_same_body | covered by c989868 |
| N20 | §4 | Handle unique, ^[a-z0-9_]{1,20}$, never changes | I14 | w1_reset: invalid_fixture[duplicate handle, handle upper case, handle with dash, handle 21 chars, handle empty]; w1_auth: signup_ignores_a_handle_and_a_balance_in_the_body | covered by 16f24a6 |
| N21 | §4 | Seeded users take the fixture handle | W1.4 | w1_auth: me_for_every_seeded_user | covered by 16f24a6 |
| N22 | §4 | Signup derives handle (lowercase, non [a-z0-9_] to _, 20 chars); taken fails | W1.5 | w1_auth: handle_is_derived_from_the_local_part, taken_derived_handle_is_409_and_creates_no_account, truncation_collision_is_handle_taken | covered by 16f24a6 |
| N23 | §4 | New users start at 0, can receive and be asked immediately | W1.7 | w1_auth: new_user_me_has_derived_handle_zero_balance_and_service_currency; w2_payments: new_user_can_receive_and_then_pay; w3_requests: request_can_be_made_of_a_new_user | covered by dd3097b (not yet run on a W3+ product) |
| N24 | §4 | Payment moves money immediately and atomically, direct or by paying a request | I8 | w2_payments: payment_moves_money_both_ways; w3_requests: pay_creates_a_payment_and_marks_the_request_paid | covered by dd3097b (not yet run on a W3+ product) |
| N25 | §4 | Request lifecycle; only payer pays/declines; only requester cancels | I4 | w3_requests: only_the_payer_may_pay, only_the_payer_may_decline, only_the_requester_may_cancel, terminal_states_never_change; w3_concurrency: pay_racing_decline_or_cancel_has_one_winner, decline_racing_cancel_has_one_winner | covered by dd3097b (not yet run on a W3+ product) |
| N26 | §4 | Request may exceed payer balance; pay while short is 409 and changes nothing; payable later | W3.1 W3.2 | w3_requests: request_above_the_payers_balance_is_created_and_moves_nothing, paying_while_short_is_409_and_payable_later; w3_concurrency: one_payer_short_for_many_requests_pays_what_it_can | covered by dd3097b (not yet run on a W3+ product) |
| N27 | §4 | Visibility belongs to the payment, chosen by the payer; requests have none and never appear in feeds | I5 I7 | w3_requests: pay_defaults_to_public, pay_creates_a_payment_and_marks_the_request_paid, request_ignores_visibility_and_spoofed_fields; w2_activity: requests_and_splits_never_appear_in_the_feed | covered by dd3097b (not yet run on a W3+ product) |
| N28 | §4 | Feed iff public or caller is sender/receiver; no other rule | I5 | w2_activity: feed_rule_for_sender_receiver_and_third_parties, new_user_sees_only_public_payments | covered by c989868 |
| N29 | §4 | Requests never in feed; GET /requests only the caller's | I5 I6 | w2_activity: requests_and_splits_never_appear_in_the_feed; w3_requests: a_non_party_sees_none_of_them, every_listed_request_has_the_caller_as_a_party | covered by dd3097b (not yet run on a W3+ product) |
| N30 | §4 | Split not a feed item; its requests visible to their parties; fulfilling payments follow the feed rule | I5 W3.7 | w2_activity: requests_and_splits_never_appear_in_the_feed; w3_splits: split_requests_are_listed_for_their_two_parties_only; w3_requests: pay_creates_a_payment_and_marks_the_request_paid | covered by dd3097b (not yet run on a W3+ product) |
| N31 | §4 | Visibility one value seen identically; private hidden from third parties only | I7 | w2_activity: private_payment_is_visible_to_both_parties_with_one_visibility, feed_items_equal_their_receipts_for_everyone_who_sees_them | covered by c989868 |
| N32 | §4 | amount at most 1e9; balances within 2^53; exact arithmetic | I9 | w2_payments: maximum_amount_is_in_range, payment_that_would_push_a_balance_past_2_53_is_422, large_balances_are_exact | covered by c989868 |
| N33 | §4 | Fixture format: currency, minor_units, users, payments, requests | W1.4 | w1_reset: reset_returns_204_with_no_body_and_seeds_users, valid_fixture_edges | covered by 16f24a6 |
| N34 | §4 | Seeded users log in immediately | W1.5 | w1_reset: seeded_users_log_in_immediately, one_character_seeded_password_logs_in | covered by 16f24a6 |
| N35 | §4 | Seeded balance is after seeded payments; no replay | W1.4 | w1_reset: seeded_payments_follow_the_feed_rule_and_representation (item 2) | covered by 16f24a6 |
| N36 | §4 | Negative fixture balance: 422, nothing changes | I25 W1.4 | w1_reset: invalid_fixture_is_422_and_changes_nothing[negative balance (spec)] | covered by 16f24a6 |
| N37 | §4 | minor_units 0, 2 or 3 (EUR, JPY, BHD) | W1.4 | w1_reset: invalid_fixture[minor_units 1, 4, string, fraction, missing], currency_and_minor_units_come_from_the_fixture | covered by 16f24a6 |
| N38 | §5 | Every 4xx/5xx carries the envelope | I10 | support: envelope asserted by every expect_error | covered by 16f24a6 |
| N39 | §5 | Error table codes and statuses | §3.3 | w2_payments: error rows; w2_idempotency: missing_key_is_400_and_changes_nothing, same_key_different_body_is_409_and_changes_nothing | covered by c989868 |
| N40 | §5 | Correct type, bad format or range: 422 | §3.4 | w2_payments: note_length_counts_code_points, invalid_amount_is_422_and_moves_nothing; w2_activity: invalid_paging_parameters_are_422 | covered by c989868 |
| N41 | §5 | amount/note/visibility type errors 422; omission gives defaults; other wrong types 400 | §3.4 | w2_payments: non_string_note_is_422, visibility_other_than_public_or_private_is_422, invalid_amount_is_422_and_moves_nothing, wrong_type_to_handle_is_400, note_and_visibility_default | covered by c989868 |
| N42 | §5 | Integer query params plain digits; 1e9, 4.0, +4 are 422 | §3.7 | w2_activity: invalid_paging_parameters_are_422 | covered by c989868 |
| N43 | §5 | Key 1..255, limit 1..200, offset >= 0 on every endpoint taking them | §3.5 §3.7 | w2_payments: key_length_range; w2_idempotency: key_over_255_characters_is_422; w2_activity: invalid_paging_parameters_are_422, valid_paging_edges (requests listing: W3) | covered by c989868 |
| N44 | §5 | No 5xx, including under concurrent load | I11 | w2_load: every_response_within_five_seconds_and_health_stays_responsive, mixed_valid_and_invalid_burst_has_no_5xx; w2_payments: payments_never_5xx_on_weird_values; w1_transport: weird values, oversized bodies | covered by c989868 |
| N45 | §6 | Signup 201 {user_id, display_name, token} | W1.5 | w1_auth: signup_returns_201_with_exactly_user_id_display_name_token | covered by 16f24a6 |
| N46 | §6 | Login 200 {user_id, display_name, token} | W1.5 | w1_auth: login_returns_200_with_user_id_display_name_token, login_after_signup_returns_the_same_user | covered by 16f24a6 |
| N47 | §6 | email_taken 409; password < 8 422; email form 422; login 401; handle_taken 409 creates nothing | W1.5 | w1_auth: registered_email_is_email_taken_case_insensitively, password_length_in_code_points, email_must_be_local_at_domain, wrong_password_or_unknown_email_is_401, taken_derived_handle_is_409_and_creates_no_account | covered by 16f24a6 |
| N48 | §6 | Bearer token on every endpoint except health, reset, signup, login (and export/import) | W1.6 | w1_auth: bad_or_missing_bearer_is_401 (every endpoint), signup_/login_ignores_an_invalid_authorization_header; w1_transport: health_ignores_an_invalid_authorization_header; w1_reset: reset_ignores_an_invalid_authorization_header | covered by 16f24a6 |
| N49 | §6 | Tokens never expire; many tokens and sessions per account | I13 | w1_auth: every_issued_token_stays_valid, tokens_are_long_random_base64url | covered by 16f24a6 |
| N50 | §6 | Password hashing; no plaintext | I12 | w5: export_holds_no_plaintext_password_or_bearer_token | covered by dd3097b (not yet run on a W3+ product) |
| N51 | §7 | Five write paths require Idempotency-Key | W2.3 W3.2 W3.6 W4.5 | w2_idempotency: missing_key_is_400_and_changes_nothing (all five paths are marked by item; W3-W5 paths run with their items) | covered by c989868 |
| N52 | §7 | Key scoped to the user | I19 | w2_idempotency: keys_are_scoped_per_user_on_payments | covered by c989868 |
| N53 | §7 | Replay = same user, method, path, body; other path is a first use | I19 | w2_idempotency: same_key_on_every_path_is_independent, query_string_is_not_part_of_the_key_path, settlement_key_is_independent_of_other_paths_and_users | covered by c989868 |
| N54 | §7 | Table: 400 missing, 201 first, 200 replay identical, 409 reuse, 4xx reuse is first use | I15 I16 I18 | w2_idempotency: missing_key_is_400..., replay_is_200_with_the_original_body_and_no_effect, same_key_different_body_is_409..., key_that_failed_with_4xx_is_a_first_use_later | covered by c989868 |
| N55 | §7 | Same body = same JSON value after parsing | §3.9 | w2_idempotency: replay_with_reordered_keys_and_whitespace_is_a_replay, numerically_equal_numbers_are_the_same_body | covered by c989868 |
| N56 | §7 | Concurrent identical first use: one 201, others 200, effect once | I17 | w2_idempotency: fifty_concurrent_identical_first_uses, concurrent_same_key_with_two_bodies_has_one_winner | covered by c989868 |
| N57 | §7 | Replay returns original after resource changes; no further state change | I15 | w2_idempotency: replay_after_the_resource_changed_returns_the_original, replay_by_another_token_of_the_same_user | covered by c989868 |
| N58 | §7 | Claimed key resolved before validation and resource checks | I16 | w2_idempotency: claimed_key_outranks_an_invalid_new_body, unparseable_body_with_a_claimed_key_is_400 | covered by c989868 |
| N59 | §8 | GET /me shape | W1.7 | w1_auth: me_for_every_seeded_user, new_user_me_has_derived_handle_zero_balance_and_service_currency | covered by 16f24a6 |
| N60 | §8 | POST /payments body, defaults, 201 shape | W2.1 | w2_payments: payment_201_has_exactly_the_payment_fields, note_and_visibility_default, private_visibility_is_kept | covered by c989868 |
| N61 | §8 | POST /payments error table | W2.2 | w2_payments: insufficient_funds_is_409_and_leaves_no_trace, invalid_amount_is_422..., paying_your_own_handle_is_self_payment, note_length_counts_code_points, visibility_other_than_public_or_private_is_422, handle_that_names_no_user_is_404, precedence tests | covered by c989868 |
| N62 | §8 | Debit and credit atomic; failed payment leaves no trace | I8 | w2_payments: payment_moves_money_both_ways, insufficient_funds_is_409_and_leaves_no_trace; w2_load: feed_matches_the_successful_payments_after_a_burst | covered by c989868 |
| N63 | §8 | note verbatim, Unicode byte for byte | I20 | w2_payments: note_round_trips_verbatim_everywhere, note_length_counts_code_points | covered by c989868 |
| N64 | §8 | POST /requests 201 shape; caller is requester | W3.1 | w3_requests: request_201_has_exactly_the_request_fields, request_appears_for_both_parties_identically, request_note_defaults_to_empty | covered by dd3097b (not yet run on a W3+ product) |
| N65 | §8 | POST /requests error table | W3.1 | w3_requests: invalid_request_amount_is_422, request_note_length, non_string_request_note_is_422, requesting_from_yourself_is_self_request, unknown_payer_is_404, wrong_type_payer_handle_is_400, missing_payer_handle_or_amount_is_422, request_precedence | covered by dd3097b (not yet run on a W3+ product) |
| N66 | §8 | Payer balance not checked at request creation | W3.1 | w3_requests: request_above_the_payers_balance_is_created_and_moves_nothing | covered by dd3097b (not yet run on a W3+ product) |
| N67 | §8 | Pay: payer only; optional visibility default public; replay needs identical body | W3.2 | w3_requests: only_the_payer_may_pay, pay_defaults_to_public, pay_with_bad_visibility_is_422, empty_object_and_explicit_public_are_different_bodies, pay_with_an_empty_body_is_400 | covered by dd3097b (not yet run on a W3+ product) |
| N68 | §8 | Pay 201 payment with request_id; request paid with payment_id | W3.2 | w3_requests: pay_creates_a_payment_and_marks_the_request_paid, pay_ignores_amount_and_note_in_the_body | covered by dd3097b (not yet run on a W3+ product) |
| N69 | §8 | Pay error table | W3.2 | w3_requests: paying_a_non_pending_request_is_409, paying_while_short_is_409_and_payable_later, only_the_payer_may_pay, pay_unknown_request_is_404, pay_precedence | covered by dd3097b (not yet run on a W3+ product) |
| N70 | §8 | Pay replay 200 original, even when paid; no extra money; never 409 | I15 W3.2 | w3_requests: pay_replay_is_200_never_409; w3_concurrency: fifty_concurrent_pays_with_one_key_pay_once | covered by dd3097b (not yet run on a W3+ product) |
| N71 | §8 | Decline rules | W3.4 | w3_requests: decline_and_decline_again, only_the_payer_may_decline, terminal_states_never_change, decline_and_cancel_need_no_key_and_ignore_the_body, declined_request_moves_no_money, decline_and_cancel_of_unknown_request_are_404 | covered by dd3097b (not yet run on a W3+ product) |
| N72 | §8 | Cancel rules | W3.4 | w3_requests: cancel_and_cancel_again, only_the_requester_may_cancel, terminal_states_never_change, decline_and_cancel_need_no_key_and_ignore_the_body | covered by dd3097b (not yet run on a W3+ product) |
| N73 | §8 | GET /requests filters, order, paging, 422s, has_more | W3.5 | w3_requests: filters_for_ada, requests_are_newest_first_and_page, has_more_respects_the_filter, invalid_request_list_parameters_are_422, request_list_ignores_unknown_parameters, a_non_party_sees_none_of_them | covered by dd3097b (not yet run on a W3+ product) |
| N74 | §8 | Splits: one pending request per non-caller participant; caller optional; §9 shares in order | W3.6 | w3_splits: caller_may_be_omitted, caller_in_the_middle_keeps_order, specification_rounding_table | covered by dd3097b (not yet run on a W3+ product) |
| N75 | §8 | Split response: shares (all, in order, sum) and requests (non-callers, in order) | W3.6 | w3_splits: specification_rounding_table, caller_in_the_middle_keeps_order, split_and_its_requests_share_one_created_at | covered by dd3097b (not yet run on a W3+ product) |
| N76 | §8 | Split error table | W3.6 | w3_splits: invalid_split_amount_is_422, empty_or_duplicate_participants_are_422, missing_participants_is_422, missing_amount_is_422, non_array_or_non_string_participants_are_400, more_than_200_participants_is_422, split_note_rules, first_unknown_handle_is_404, split_precedence, failed_split_creates_nothing | covered by dd3097b (not yet run on a W3+ product) |
| N77 | §8 | Caller-only split valid with requests []; no balance checks | W3.6 | w3_splits: caller_only_split_creates_no_requests, split_checks_nobody_balance | covered by dd3097b (not yet run on a W3+ product) |
| N78 | §8 | GET /activity: feed rule, newest first, paging as /requests | W2.5 | w2_activity: feed_rule_for_sender_receiver_and_third_parties, feed_is_newest_first_in_creation_order, paging_with_limit_offset_and_has_more, default_limit_is_50, empty_feed, invalid_paging_parameters_are_422, activity_ignores_other_parameters | covered by c989868 |
| N79 | §9 | Shares whole, sum, differ by 1, larger first; table rows | I21 | w3_splits: specification_rounding_table, splits_in_other_currencies | covered by dd3097b (not yet run on a W3+ product) |
| N80 | §9 | Order moves the extra unit; zero share legal and gets a request | W3.6 | w3_splits: extra_unit_follows_handle_order, zero_shares_still_produce_requests; w3_requests: zero_amount_request_from_a_split_is_payable | covered by dd3097b (not yet run on a W3+ product) |
| N81 | §9 | Splits independent; balances sum to seeded total after splits paid | I1 W3.6 | w3_splits: many_splits_are_independent_and_conserve, paying_every_share_conserves_money | covered by dd3097b (not yet run on a W3+ product) |
| N82 | §10 | Export and import unauthenticated | W5.1 | w5: export_shape_and_unauthenticated, import_ignores_an_invalid_authorization_header | covered by dd3097b (not yet run on a W3+ product) |
| N83 | §10 | Export 200 {track, format_version 1, state} accepted unchanged by import | W5.1 | w5: export_shape_and_unauthenticated, round_trip_in_the_same_container | covered by dd3097b (not yet run on a W3+ product) |
| N84 | §10 | Import atomic, 204, no dependency on source process/files/port/network | W5.2 | w5: round_trip_into_a_second_container, round_trip_in_the_same_container | covered by dd3097b (not yet run on a W3+ product) |
| N85 | §10 | Import replaces, never merges; repeat gives no duplicates | W5.2 | w5: importing_twice_equals_importing_once | covered by dd3097b (not yet run on a W3+ product) |
| N86 | §10 | Invalid JSON 400; missing fields, wrong track/version, invalid state 422, destination unchanged | W5.3 | w5: rejected_import_changes_nothing, import_over_64_mib_is_422_and_changes_nothing | covered by dd3097b (not yet run on a W3+ product) |
| N87 | §10 | Export is an atomic read-only snapshot | I26 W5.1 | w5: export_is_read_only, snapshot_is_not_affected_by_later_writes, export_during_a_burst_is_a_consistent_snapshot, export_of_a_large_state_round_trips_within_the_time_limit | covered by dd3097b (not yet run on a W3+ product) |
| N88 | §10 | Preserve accounts, hashed logins, tokens, currency, balances, payments, requests, permissions, idempotency bodies and responses | I26 W5.2 | w5: round_trip_in_the_same_container, round_trip_into_a_second_container, import_preserves_failed_keys_pending_requests_and_operators | covered by dd3097b (not yet run on a W3+ product) |
| N89 | §10 | No regenerated ids/timestamps, no replay; failed keys reusable; receipts, tokens, retries valid | W5.2 W5.4 | w5: new_ids_never_collide_and_time_moves_forward_after_import, import_preserves_failed_keys_pending_requests_and_operators, round trips (replays of all five paths) | covered by dd3097b (not yet run on a W3+ product) |
| N90 | §10 | Import removes earlier data and credentials; reset clears imported state | W5.2 | w5: round_trip_in_the_same_container (post-export users and tokens gone), reset_after_import_clears_it | covered by dd3097b (not yet run on a W3+ product) |
| N91 | §11 | settlement_operator_ids default []; operators settle any wallets; no extra read access | W4.1 I24 | w4: operator_list_comes_from_the_fixture, no_operators_by_default, signed_up_user_is_not_an_operator, operator_can_move_money_between_two_other_wallets, members_follow_the_ordinary_feed_rule; w3_requests: operator_gains_no_reach_into_other_peoples_requests | covered by dd3097b (not yet run on a W3+ product) |
| N92 | §11 | Settlements need operator and key; 401 without token; 403 non-operator | W4.1 | w4: no_token_is_401, non_operator_is_403_before_key_and_body, operator_without_key_is_400 | covered by dd3097b (not yet run on a W3+ product) |
| N93 | §11 | transfers 1..32, payment field rules, 404, self_payment, 422 shape, input-order precedence before funds | W4.2 | w4: malformed_batch_shape_is_422, thirty_two_transfers_are_allowed, invalid_entry_is_422, unknown_handles_are_404, self_transfer_is_self_payment, entry_errors_in_input_order_before_funds, unknown_fields_are_ignored | covered by dd3097b (not yet run on a W3+ product) |
| N94 | §11 | Net affordability; 409; all or none; failure claims no key and creates nothing | I22 W4.3 | w4: net_affordability_chain_through_an_empty_wallet, exactly_zero_after_netting_is_affordable, unaffordable_settlement_is_409_and_changes_nothing, failed_validation_claims_no_key, settlement_past_2_53_is_422_and_changes_nothing | covered by dd3097b (not yet run on a W3+ product) |
| N95 | §11 | 201 {settlement_id, committed_at, payments in order}; membership fields | I23 W4.4 | w4: settlement_201_shape_and_members, ordinary_payments_have_null_settlement_id, members_are_listed_in_input_order_newest_first, same_pair_twice_gives_two_payments | covered by dd3097b (not yet run on a W3+ product) |
| N96 | §11 | Members follow feed visibility; response holds every receipt; replay 200 original | W4.4 W4.5 | w4: members_follow_the_ordinary_feed_rule, replay_returns_the_complete_original, settlement_201_shape_and_members, concurrent_settlements_and_payments_conserve | covered by dd3097b (not yet run on a W3+ product) |
| N97 | §11 | Reset/import preserve operator permissions, payments, requests, membership, retry responses | W5.2 | w5: import_preserves_failed_keys_pending_requests_and_operators, round trips; w1_reset: fixture_settlement_id_is_shown_unchanged; w4: operator_list_comes_from_the_fixture | covered by dd3097b (not yet run on a W3+ product) |

## 7. Handoff log

| Handoff | To | Sent | Acknowledged | State |
|---|---|---|---|---|
| Stage-1 handoff, parts 1-9 (plan 8dd27a4) | builder, verifier, critic | 06:36Z | critic (plan review), verifier (W6), builder (W1), all by 06:40Z | acknowledged |
| HANDOFF W1 @ 99d2431 (builder) | verifier, critic | 06:47Z | — | awaiting verifier run (suite W6 in progress) |
| Plan revision after critic plan review (I9, D24, D33-D35, 3.1, 3.2, 3.11, 3.13, W1.3, W1.4) and verdict scope (section 0) | builder, verifier, critic | 06:53Z | — | sent |
| HANDOFF W2 @ 1bd9c8d (builder) | verifier, critic | 06:55Z | verified and approved at 2ffcbe8 instead (1bd9c8d lacks D34/D35) | ACCEPTED |
| HANDOFF W1 @ 2ffcbe8 (builder; replaces 99d2431, adds D33-D35, carries W2) | verifier, critic | 06:57Z | critic BLOCKED W1+W2 07:16Z (M49), verifier test ee19494, critic APPROVED W1+W2 (REVIEW.md 493fc0c); verifier PASS W1+W2 07:03Z | ACCEPTED |
| HANDOFF W3 @ 2455a8d (builder) | verifier, critic | 07:29Z | verifier PASS 07:33Z | awaiting critic |
| HANDOFF W4 @ e143cf1 (builder) | verifier, critic | 07:34Z | verifier PASS 07:41Z | awaiting critic |
| HANDOFF W5 @ 295378c (builder) | verifier, critic | 07:49Z | — | awaiting verifier run |
