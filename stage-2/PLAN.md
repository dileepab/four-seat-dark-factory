# Stage 2 plan — Pocketful: wallet screens and payment authorizations

Owner: planner (`planner-h6bf`). Repository: `/Users/Dileepa/dark-factory-v3`, folder `stage-2/`, which started as a copy of the accepted `stage-1/` (`scripts/new-stage.sh 2`, commit 5f5d4a4).
Specification: `/Users/Dileepa/df-spec/pocketful/spec/stage-2.md`, plus every part of `stage-1.md` that stage 2 does not change. Both are pasted verbatim into the handoff.
Supplied checks (a partial sample, about 35% of the graded stage-2 checks, used only to wire the service up): `/Users/Dileepa/df-spec/pocketful/test/stage_2/`. The stage-1 checks also run against this folder.
Frozen reference: `/Users/Dileepa/dark-factory-v3/stage-1/` with its `PLAN.md`, accepted at 4baf8d9. Never edit it. Building it read-only, for example as the previous service in the upgrade tests, is fine.

## Status

| Item | Owner | Title | State | Commit |
|---|---|---|---|---|
| W7 | builder | Holds API: `GET /me` money fields, authorizations, capture, void, list, expiry, funds judged on `available` | PLANNED | — |
| W8 | builder | Export schema 2 and import of stage-1 exports (upgrade) | PLANNED | — |
| W9 | builder | UI foundation: HTML routes, shell, visual system, signup, login, logout, navigation | PLANNED | — |
| W10 | builder | Wallet screen `/`: wallet numbers, pay and request forms, activity feed, refresh, uncertain outcomes, upgrade | PLANNED | — |
| W11 | builder | Requests, split and holds screens | PLANNED | — |
| W12 | verifier | Stage-2 acceptance suite: stage-1 regression, holds API, upgrade, browser | PLANNED | — |

Item numbers continue from stage 1 (W1–W6) so room messages stay unambiguous. States: PLANNED, BUILDING, HANDED_OFF, VERIFIED or FAILED, APPROVED or BLOCKED, ACCEPTED.

## 0. How this stage runs

- The builder takes W7 to W11 in order and hands off each one as soon as its gate is green, then starts the next. The verifier writes W12 at once from this plan and the specification, without reading the implementation. The critic reviews this plan now (one batch), then each handoff.
- Routing, as in stage 1. Builder: `HANDOFF Wn` to the verifier, the critic and the planner. Verifier: PASS or FAIL to the critic and the planner, and to the builder on FAIL. Critic: APPROVED or BLOCKED to the planner, and to the builder on BLOCKED. The planner marks an item ACCEPTED when a PASS and an APPROVED name the same commit. Questions go to the planner, who decides.
- A verdict covers the item handed off plus every earlier item. For Wn the verdict run is: the offline build and run, the builder's tests, every acceptance test marked for W1 to Wn (the stage-1 regression tests carry items 1 to 5 and always run), and the supplied checks for stages 1 and 2. Supplied stage-2 checks that need a later item are expected failures, listed by name in the verdict; every other failure counts. From W11 on, everything counts.
- Check command (a new `--out` every run; seat letters b builder, v verifier, c critic, p planner). The harness also builds the frozen `stage-1/` as the previous service for the upgrade checks:
  `/Users/Dileepa/dark-factory-v3/scripts/harness.sh run --track pocketful --repo <repo or worktree> --stage 2 --out /Users/Dileepa/dark-factory-v3/.work/checks/s2-<letter><nn>`
- Final check (verifier, on the final commit, main repository, clean tree):
  `/Users/Dileepa/dark-factory-v3/scripts/harness.sh run --track pocketful --repo /Users/Dileepa/dark-factory-v3 --stage 2 --mode isolated --out /Users/Dileepa/dark-factory-v3/.work/checks/s2-final-<nn>`
  The target line is `claimed stage: 2 on the shipped checks`. The stage-3 suite runs as an overshoot probe and must fail.
- Browser: the harness venv `/Users/Dileepa/df-spec/.venv` has Playwright 1.63 with Chromium (the supplied stage-2 checks use it). The acceptance suite uses that interpreter, `~/df-spec/.venv/bin/python`, as in stage 1.
- Verdict runs use a clean worktree of the named commit: `git -C /Users/Dileepa/dark-factory-v3 worktree add /Users/Dileepa/dark-factory-v3/.work/<handle>/wt-<short-hash> <commit>`, passed as `--repo`.
- Offline check (D2): `docker build --network=none -t pf-<seat>-s2 <path>/stage-2`, then `docker run -d --name pf-<seat>-s2 --network=none pf-<seat>-s2`, then `docker exec pf-<seat>-s2 node -e "fetch('http://127.0.0.1:8080/health').then(r=>r.text()).then(console.log)"`. The UI's pages and assets must also load from a `--network=none` container (W9.1).
- Shared machine: container names `pf-<seat>-…`; host ports builder 18100–18199, verifier 18200–18299, critic 18300–18399, planner 18400–18499. Before a verdict run the verifier asks the other seats to start no container runs until the verdict is posted.
- Screenshots: the verifier's browser tests save one screenshot of every named UI state at 375×812 and at 1280×800 under `.work/verifier-h6bh/shots/<short-hash>/` and post the path with each UI verdict, so the critic and the planner can review the presentation.
- Commits: only your own paths, `git commit -m "<message>" -- <paths>`; never `git add -A` or `git commit -a`; if `.git/index.lock` exists, wait and retry. Never amend, rebase or force-push. Scratch files go under `.work/<your handle>/`.

## 1. Look-ahead: what stage 3 needs from stage 2's outputs

Stage 3 must import exports from stage 1 and stage 2, account for authorizations and captures, and rebuild historical holds: a hold starts at creation, a nonfinal capture reduces it at the capture's time, and a final capture, a void or an expiry releases the remainder at that event's time. So the stage-2 export carries, for every authorization: id, both parties, amount, captured amount, note, visibility, stored status, `expires_at`, `created_at`, `closed_at` (the time a void, final capture or full capture closed it; null while open and for clock expiry, whose time is `expires_at`) and the capture payment ids in order. Every payment carries `authorization_id` and `created_at`. The state also carries `authorization_ttl_seconds`.

Nothing from stage 3 is built here: no `as_of` or `known_at`, no statements, no corrections or revisions, no `closed_at` in API responses, no seeded `created_at`.

## 2. Invariants

Each one is a check a test can perform. "Every read" includes reads taken during a concurrent burst. Stage 1's I1–I29 still hold, amended where marked; I30–I49 are new.

- **I1 Conservation (amended).** After every operation (bursts, retries, failed calls, captures, voids, expiries, imports), the sum of `GET /me` `total` over all users equals the total seeded by the last reset (after an import, the total in the imported state). Holds move no money; payments, request payments, settlements and captures transfer it.
- **I2 Non-negative (amended).** No read shows a negative `total`, `available` or `held`: `held ≤ total` at every read, including during bursts.
- **I3 At-most-once requests.** Unchanged.
- **I4 Request lifecycle.** Unchanged.
- **I5 Feed rule (amended).** `GET /activity` for caller C contains payment P if and only if P is `public` or C is P's sender or receiver. Capture payments follow this rule. Requests, splits and authorizations never appear in it.
- **I6 Request scoping.** Unchanged.
- **I7 One visibility (amended).** Every representation of a payment carries the same `visibility`; a capture payment's `visibility` and `note` equal its authorization's.
- **I8 Atomic payment (amended).** Debit and credit happen together, for captures too. A failed operation changes no balance or hold, adds no feed item and claims no key.
- **I9 Exact range (amended).** Every client-submitted amount is integral: `POST /payments`, `POST /requests`, `POST /splits`, settlement transfers and `POST /authorizations` take 1 to 1000000000; a capture amount is at least 1 and at most the authorization's remaining amount. No balance exceeds 2^53.
- **I10 Error envelope (amended).** As stage 1, with the new codes of section 3.3.
- **I11 No 5xx.** Unchanged, for every new endpoint and for the HTML routes.
- **I12–I14.** Unchanged.
- **I15 Replay (amended).** On each of the seven idempotent paths, the same user, method, path, key and JSON-equal body returns 200 with a body JSON-equal to the original 201 body, moves no money and changes nothing, even after the resource changed or closed, and after an export and import (including a stage-1 export imported into stage 2).
- **I16–I19 (amended).** Key reuse, concurrent first use, failures claim nothing, key scope: unchanged, on all seven paths.
- **I20–I24.** Unchanged. I22's affordability is judged on `available` (I31).
- **I25 Reset and import atomicity (amended).** A rejected reset or import changes nothing; an accepted one replaces all state, authorizations and the TTL included.
- **I26 Export snapshot (amended).** As stage 1, and the snapshot includes authorizations with their captures, holds and expiry times.
- **I27 Serializable (inferred, amended).** Concurrent operations, holds included, give the results of some one-at-a-time order.
- **I28 Unique ids (inferred).** Unchanged; authorization ids included.
- **I29 Time and order (inferred, amended).** List endpoints, `GET /authorizations` included, return newest first by `created_at`.
- **I30 Money fields.** Every `GET /me` has `balance == total`, `held` = the sum of `remaining_amount` over the caller's open outgoing authorizations, and `available == total − held`.
- **I31 Held funds are reserved.** `POST /payments`, `POST /requests/{id}/pay`, settlement net debits and `POST /authorizations` succeed only when `available` covers them; they are 409 `insufficient_funds` when `total` would cover them but `available` does not. Captures may spend the money reserved for them. With no open holds every stage-1 result is unchanged.
- **I32 Capture bound.** Cumulative `captured_amount` never exceeds `amount`; each first-use capture moves exactly its amount, once; a replay moves nothing; a closed authorization (captured, voided or expired) never captures again.
- **I33 Remainder.** While open, `remaining_amount = amount − captured_amount` and that amount is held; when closed, `remaining_amount` is 0. A final capture, a void or an expiry releases exactly the remainder in the same step; a nonfinal capture keeps the rest held; captured amounts and capture records survive every close.
- **I34 Expiry by the clock.** Once the service clock reaches `expires_at`, with no request at the deadline, the authorization reads `expired` (also under `status=expired`, never under `status=open`), holds nothing, capture is 409 `authorization_expired` and void is 409 `authorization_not_open`.
- **I35 Authorization scoping.** `GET /authorizations` returns only authorizations where the caller is payer or receiver, and the direction and status filters are exact. Only the receiver captures and only the payer voids; anyone else, including a non-party, gets 403.
- **I36 Capture payments.** A capture returns, and the feed shows, a payment in exactly the `POST /payments` shape with `authorization_id` set, `request_id: null`, `settlement_id: null` and the captured amount. Every payment not made by a capture carries `authorization_id: null`.
- **I37 Upgrade.** An unchanged export from the frozen stage-1 build imports into stage 2 (204) and everything stage 1's I26 promises holds afterwards, read through stage 2 (with `held` 0 and `available == total`). A stage-2 export round-trips with every authorization, capture and hold intact.
- **I38 Holds under concurrency (inferred).** Concurrent payments, authorizations, captures and voids on one wallet never make `available` negative and never over-capture; a concurrent capture and void of one open authorization have exactly one winner.
- **I39 Formatted amounts.** In the UI every amount element with a `data-testid` is exactly `<integer part>.<minor_units digits> <CUR>` (`100.00 EUR`), with no decimal point when `minor_units` is 0 (`1200 JPY`), and nothing else in the element. Where the contract names `data-amount`, it is the integer minor units.
- **I40 Amount input.** A decimal typed into any amount field becomes exact minor units (`15` and `15.00` → 1500, `15.5` → 1550 with `minor_units` 2). Nonnumeric text, more places than `minor_units`, an empty field or an amount outside 1..1000000000 minor units shows that form's error element and sends no request.
- **I41 One payment per unchanged form.** Submitting a form again without changing any field re-sends the same idempotency key and the identical body, so money moves once and no error shows. Changing any field makes the next submission a new key.
- **I42 Uncertain is not refused.** A lost response (network failure, abort, client timeout, 5xx, unreadable body) shows the uncertain element, never the error element, and keeps the form and its key. Retrying the unchanged form sends the same key and body, moves money exactly once, removes the error and uncertain elements and refreshes the data. A refusal (4xx) shows the error element, keeps every input and refreshes the data.
- **I43 Fresh after the page's own action.** After any successful action the balance numbers, the feed and the request and authorization lists on the same page show the new state without a manual reload. Data is re-read only after the write's response arrived.
- **I44 Latest refresh wins.** A load's response (or failure) is shown only if no later load of the same data has been shown already, whatever order responses arrive in.
- **I45 Element contract.** Every `data-testid` element of section 3.14 exists exactly when the contract says, with the text it says. "Present only when" means absent from the DOM otherwise, not hidden or disabled. List items are direct children of their container, in API order.
- **I46 Responsive and accessible.** At 375×812 and 1280×800, no route in any named state scrolls horizontally (`document.documentElement.scrollWidth <= window.innerWidth`); every input and select has a visible associated label; the keyboard focus is visible on every interactive element; text contrast is at least 4.5:1 (3:1 for text 18.66 px bold or 24 px and larger), and input borders, button boundaries and the focus indicator have at least 3:1 against their background.
- **I47 Session.** A signed-in browser stays signed in across navigation between routes and across an export/import that contains its token. `current-user` is visible on every screen while signed in, and absent after logout.
- **I48 Safe rendering (inferred).** Notes, display names and handles are rendered as text, never as HTML, and no page loads anything from another origin (no fonts, scripts, styles or images from the network).
- **I49 Earlier behaviour (inferred).** Every stage-1 check still passes. `GET /requests` answers JSON unless the `Accept` header lists `text/html`.

## 3. Interface contract

Stage 1's contract (`stage-1/PLAN.md` section 3) applies unchanged except where this section amends it. Amended or new text is marked (S2).

### 3.1 Runtime

- As stage 1: `stage-2/Dockerfile`, build context `stage-2/`, pinned `node:24.14.0-alpine3.22`, the Dockerfile downloads nothing, non-root user, `0.0.0.0:$PORT` (default 8080), `GET /health` 200 `{"status": "ok"}`, in-memory state, EUR with 2 minor units and a TTL of 600 s before any reset.
- (S2) The image also contains every UI file (HTML shell, JavaScript modules, stylesheet, icons). The server reads them at start-up. Pages reference only same-origin URLs and use the system font stack.

### 3.2 Transport and parsing

- (S2) The JSON API is unchanged: `application/json; charset=utf-8`, the body limits (1 MiB API, 64 MiB reset and import), the 400 rules (D7, D9, D10, D38), unknown body fields and query parameters ignored, the first occurrence of a repeated query parameter, code points everywhere, 404 for an unknown path or method or an undecodable path (D3, D33), the HTTP-layer envelopes (D28).
- (S2) HTML documents and static files are added by section 3.14. `Accept` "lists `text/html`" when one of its comma-separated media ranges, with parameters removed, trimmed and lowercased, is `text/html` and its `q` is not 0 (D40). `*/*`, `application/json`, an empty `Accept` and no `Accept` do not list it.

### 3.3 Error codes (S2: complete for stage 2)

Stage 1's codes plus: 409 `authorization_not_open`, 409 `authorization_expired`, 422 `capture_exceeds_authorization`.

### 3.4 Field rules (S2 additions)

| Field | Wrong JSON type (including `null`) | Missing | Bad value |
|---|---|---|---|
| `amount` on `POST /authorizations` | 422 `validation_failed` | 422 | as `POST /payments`: 422 when not integral, below 1, above 1000000000 |
| `amount` on capture | 422 `validation_failed` | defaults to the remaining amount | 422 `validation_failed` when not integral or below 1; 422 `capture_exceeds_authorization` when above the remaining amount, however large (D50) |
| `final` on capture | 400 `malformed_request` | `true` | — |
| `to_handle`, `note`, `visibility` on `POST /authorizations` | as `POST /payments` | as `POST /payments` | as `POST /payments` |

### 3.5 Precedence (S2 additions; the first failing step answers)

- `POST /authorizations`: exactly as `POST /payments`: route, 401, key (400, 422), body (422 size, 400 unreadable), claimed key (200 replay or 409 reuse), types (400 `to_handle`), field values (422), unknown handle 404, `self_payment` 422, `insufficient_funds` 409 on `available`, commit. No 2^53 guard: a hold moves no money.
- `POST /authorizations/{id}/capture`: route 404, 401, key (400, 422), body (422 size, 400 unreadable), claimed key (200 replay or 409 reuse), `final` type 400, `amount` value 422 `validation_failed`, unknown authorization 404, caller not the receiver 403 (non-parties included), expired 409 `authorization_expired`, captured or voided 409 `authorization_not_open`, amount above the remaining amount 422 `capture_exceeds_authorization`, the receiver's 2^53 guard 422 `validation_failed`, commit (D50).
- `POST /authorizations/{id}/void`: route 404, 401, unknown 404, caller not the payer 403 (non-parties included), then by state: open → voided 200; voided → 200 with the current state; captured or expired (by the clock or seeded) → 409 `authorization_not_open`. No key; the body is never read.
- `GET /authorizations`: 401, then query validation 422 (`direction`, `status`, `limit`, `offset`), as `GET /requests`.

### 3.6 Representations (S2: exactly these fields)

- Me: `{"user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units"}`. `balance == total`.
- Payment, identical wherever a payment appears (create, replay, pay, capture, feed, settlement): `{"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency", "note", "visibility", "request_id", "settlement_id", "authorization_id", "created_at"}`. `authorization_id` is the captured authorization or `null`. A replay returns the stored original body unchanged, so a replayed stage-1 body has no `authorization_id` (D54).
- Authorization, identical wherever one appears (create, replay, void, list): `{"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "captured_amount", "remaining_amount", "currency", "note", "visibility", "status", "expires_at", "payment_id", "payment_ids", "created_at"}`. `status` is the status at the time of the read (an open authorization past `expires_at` reads `expired`); `payment_id` is the latest capture's payment or `null`; `payment_ids` lists every capture's payment in order (`[]` when none) (D51). `closed_at` is recorded in the state for stage 3 and is not part of any response.
- Lists: `{"payments": [...], "has_more": bool}`, `{"requests": [...], "has_more": bool}`, `{"authorizations": [...], "has_more": bool}`.
- Request, Split, Settlement, signup and login: unchanged (settlement members and request payments carry `authorization_id: null`).

### 3.7 Ids, timestamps, order, paging

- (S2) Generated authorization ids are `a_<random>`, same rules as stage 1's ids (D16). Seeded ids are used verbatim.
- (S2) A created authorization's `expires_at` is its `created_at` plus `authorization_ttl_seconds`, in stage 1's timestamp form `YYYY-MM-DDTHH:MM:SS.sss+00:00`. A seeded `expires_at` is returned exactly as the fixture wrote it and compared as an instant (D48).
- (S2) Service clock (D49): `now` is the later of the wall clock and the state's last issued timestamp. An operation takes `now` once, at its start, and uses it for every expiry decision it makes. An authorization is expired when `now >= expires_at`. A reset starts its state's last issued timestamp at the reset's own wall-clock time; an import keeps stage 1's rule (new timestamps are never earlier than imported ones).
- (S2) `GET /authorizations` is newest first by `created_at`, ties later-created first; seeded authorizations take the reset's timestamp and fixture order is creation order. Paging exactly as `GET /requests`.

### 3.8 Authentication

- Unchanged for the API. (S2) The HTML routes and `/assets/` files are public: they never read `Authorization`.

### 3.9 Idempotency (S2)

- Seven paths: `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`, `POST /authorizations`, `POST /authorizations/{id}/capture` (canonical path `/authorizations/<decoded id>/capture`).
- Everything else as stage 1: (user, method, canonical path, key); JSON-value body equality, so `{}` and `{"amount": 2000}` differ, and `{"amount": 700}` and `{"amount": 700, "final": true}` differ; a record is stored only on 201, in the same step as the effects; a 4xx stores nothing; duplicates are serialized.

### 3.10 Endpoints (S2 changes and additions)

`GET /me`: 200 Me. `held` and `available` are computed at the read's `now`.

`POST /payments`, `POST /requests/{id}/pay`: unchanged except that 409 `insufficient_funds` compares `available` (not `total`) with the amount. Their payments carry `authorization_id: null`.

`POST /settlements`: unchanged except that a settlement is affordable when, for every wallet, `available + incoming − outgoing ≥ 0` (D53). The 2^53 guard still applies to `total`.

`POST /splits`, `POST /requests`, decline, cancel, `GET /requests`, `GET /activity`: unchanged (`GET /requests` serves the HTML shell when `Accept` lists `text/html`, section 3.14).

`POST /authorizations` (idempotent) `{"to_handle", "amount", "note"?, "visibility"?}`: the caller is the payer. Errors per section 3.5. 201 Authorization with `status: "open"`, `captured_amount: 0`, `remaining_amount` = `amount`, `payment_id: null`, `payment_ids: []`, `expires_at` = `created_at` + TTL. The hold reserves `amount` of the payer's `available` and moves nothing. It never appears in `GET /activity`.

`POST /authorizations/{id}/capture` (idempotent) `{"amount"?, "final"?}`: only the receiver. `amount` defaults to the remaining amount; `final` defaults to `true`. In one step: a payment from payer to receiver of `amount`, with `authorization_id` set, `request_id: null`, `settlement_id: null`, the authorization's `note` and `visibility`; the payer's `total` and `held` fall by `amount` and the receiver's `total` rises by it; `captured_amount += amount`; the payment is appended to `payment_ids` and becomes `payment_id`. Then, if `final` is true or nothing remains, the authorization becomes `captured`, its remainder is released and `closed_at` is set; otherwise it stays `open` with the rest held. 201 Payment.

`POST /authorizations/{id}/void` (no key, body ignored): only the payer. Open: becomes `voided`, the remainder is released, `closed_at` is set, captures are kept; 200 Authorization. Voided: 200 with the current state. Captured or expired: 409 `authorization_not_open`.

`GET /authorizations?direction&status&limit&offset` (JSON unless `Accept` lists `text/html`): authorizations where the caller is payer or receiver. `direction` is `outgoing` (caller is payer), `incoming` (caller is receiver) or absent; `status` is `open`, `captured`, `voided`, `expired` or absent, judged at the read's `now`; any other value, including empty or another case, is 422. 200 `{"authorizations", "has_more"}`.

### 3.11 Reset (S2 additions)

Every rule of stage 1 stands. Any rule below that fails is 422 `validation_failed` and nothing changes (D48):

- `authorization_ttl_seconds`: optional, default 600; when present, an integral number from 1 to 10000000000 (10^10 s). `600.0` is valid; `0`, `-1`, `1.5`, `"600"`, `null` and above 10^10 are 422.
- `authorizations`: optional array (default `[]`; its length is bounded only by the 64 MiB body) of objects with: `id` (string, 1 to 64 characters, unique among authorizations); `from_user_id` and `to_user_id` (existing users, different); `amount` (integer 0 to 1000000000); `captured_amount` (optional integer 0 to `amount`; default `amount` when `status` is `captured`, otherwise 0); `note` (optional string, default `""`); `visibility` (optional, `public` or `private`, default `public`); `status` (optional, `open`, `captured`, `voided` or `expired`, default `open`); `expires_at` (required string of at most 64 characters, an RFC 3339 date-time with `T` or `t`, optional fraction, and `Z`, `z` or `±HH:MM`, a real calendar date, hours 00–23, minutes and seconds 00–59); `payment_id` (optional string or null) and `payment_ids` (optional array of strings), shown as given (default: `payment_ids` is `[payment_id]` when only `payment_id` is given, else `[]`; `payment_id` is the last of `payment_ids`, else null). An `open` authorization needs `captured_amount < amount`. Unknown fields, `created_at` included, are ignored.
- Seeded payments may carry `authorization_id` (optional string or null), shown unchanged, as D34 does for `settlement_id`.
- A user's `balance` is still `total`. A fixture user's `available` or `held` field is ignored: `available` is derived, never seeded.
- For every user, the sum of `amount − captured_amount` over that user's seeded `open` authorizations whose `expires_at` is after the reset's time must not exceed the user's `balance`; equal is fine.
- Seeded authorizations take the reset's timestamp as `created_at`; a seeded `open` authorization whose `expires_at` is at or before the reset time reads `expired` at once.

### 3.12 Export and import (S2)

- `GET /_test/export`: `{"track": "pocketful", "format_version": 1, "state": {...}}` with `"schema": 2`. The state holds everything of schema 1 plus `authorization_ttl_seconds`, every authorization (all stored fields, including `created_at`, `closed_at`, `expires_at` exactly as stored, and `payment_ids`) and each payment's `authorization_id`. Built in one synchronous step.
- `POST /_test/import` accepts `schema` 1 (an unchanged stage-1 export: TTL 600, no authorizations, every payment `authorization_id: null`, stored replay bodies kept verbatim) and `schema` 2. Any other schema, and any state that fails full validation, is 422 with nothing changed. Schema-2 validation adds: authorization fields as in section 3.11; `created_at` and `closed_at` (null or a timestamp); `payment_id`, `payment_ids` and each payment's `authorization_id` checked only for type, as reset checks them, because they are display-only links the service never follows and every state a reset can build must import back (D62); for every user, the remainders of the open authorizations whose `expires_at` is after the import's time not above the user's `total`. Open authorizations already past their deadline hold nothing and are not counted: a payer may have spent that money after the deadline and before the export, so counting them would refuse a valid export.
- After an import, everything of stage 1's 3.12 holds, and open authorizations keep expiring by the clock.

### 3.13 Concurrency model

- As stage 1: each operation's read-check-write is synchronous; reset and import swap a whole state in one step. (S2) Expiry needs no timer: every read and write judges it from `now` (section 3.7), so an authorization whose deadline passed with no request at the deadline is already expired at the next read.

### 3.14 UI contract (S2, new)

Routes and documents:

- `GET /`, `/split`, `/signup`, `/login`: 200, the HTML shell, whatever the `Accept` header.
- `GET /requests`, `GET /authorizations`: the HTML shell when `Accept` lists `text/html` (any query string); otherwise the JSON API. `POST` on those paths is always the API.
- `GET /assets/<name>`: the UI's static files with the right `Content-Type` (`text/javascript`, `text/css`, `image/svg+xml`). Any other `/assets/` path is 404.
- Any other unknown `GET` path: JSON 404 as in stage 1, except that when `Accept` lists `text/html` the answer is 404 with the HTML shell, which shows a "page not found" screen with the navigation (D59).
- HTML responses carry `Content-Type: text/html; charset=utf-8`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`. Asset responses carry `X-Content-Type-Options: nosniff`. The shell suppresses the favicon request (for example `<link rel="icon" href="data:,">`).

Session (D41):

- Signup and login store the returned token in `localStorage`. Every API call from the page sends `Authorization: Bearer <token>` and `Accept: application/json`.
- After signup or login the page reads `GET /me`, shows the signed-in header and goes to `/`.
- A 401 from any API call clears the token and shows `/login` with a notice that the session ended (an ordinary notice, not `auth-error`).
- Signed out, `/`, `/requests`, `/split` and `/authorizations` show `/login`. `/login` and `/signup` always render their forms, signed in or not.
- `logout-button` clears the token and shows `/login`; `current-user` is then absent.

Shared header, on every screen: the product name; when signed in, the navigation links `nav-wallet` (`/`), `nav-requests` (`/requests`), `nav-split` (`/split`) and `nav-authorizations` (`/authorizations`) with the current one marked (`aria-current="page"`), `current-user`, `current-handle` and `logout-button`; when signed out, links to `/login` and `/signup`.

Elements. The specification's `data-testid` names, plus the plan's own (marked P), which the acceptance suite also uses (D57). Every element below is found by its `data-testid` alone.

| `data-testid` | Screen | Element and rule |
|---|---|---|
| `signup-email`, `signup-password`, `signup-display-name`, `signup-submit` | `/signup` | Inputs and button |
| `login-email`, `login-password`, `login-submit` | `/login` | Inputs and button |
| `auth-error` | `/signup`, `/login` | Error message. Present only when there is one |
| `current-user` | every screen, signed in | Visible. Text contains the display name |
| `current-handle` | every screen, signed in | Text is exactly the handle: no `@` (draw any `@` with CSS outside the text) and no other words |
| `logout-button` | every screen, signed in | Button |
| `nav-wallet`, `nav-requests`, `nav-split`, `nav-authorizations` (P) | every screen, signed in | Links to the four signed-in routes |
| `loading` (P) | each screen with data | Visible while the screen's first data load is in flight; absent afterwards |
| `load-error`, `load-retry` (P) | each screen with data | Shown when a data load fails (network, timeout, 5xx); the button loads again. Absent otherwise |
| `wallet-available` | `/`, `/authorizations` | Formatted `available` with `data-amount`. The headline number: the largest money figure on the screen |
| `wallet-balance` | `/`, `/authorizations` | Formatted `total` with `data-amount`. Visible, secondary |
| `wallet-held` | `/`, `/authorizations` | Formatted `held` with `data-amount`, secondary. Absent when `held` is 0 |
| `wallet-refresh` | `/` | Button: reloads the wallet numbers and the feed without touching the pay form |
| `pay-handle`, `pay-amount`, `pay-note` | `/` | Text inputs (`pay-amount` is a decimal, D44) |
| `pay-visibility` | `/` | `<select>` with option values `public` (default) and `private` |
| `pay-submit` | `/` | Button |
| `pay-error` | `/` | Present only while the last payment attempt was refused or the form input was invalid |
| `pay-uncertain` | `/` | Nonempty text. Present only while the last payment attempt's outcome is unknown |
| `pay-success` (P) | `/` | Present only after a confirmed payment, until the form changes or is submitted again |
| `request-handle`, `request-amount`, `request-note`, `request-submit` | `/` | The request form |
| `request-error` | `/`, `/requests` | Present only while the last request-form submission (on `/`) or request action (on `/requests`) was refused or invalid |
| `request-uncertain`, `request-success` (P) | `/`, `/requests` (uncertain); `/` (success) | As the pay elements, for the request form and for request actions |
| `activity-list` | `/` | Container; its direct children are the items, newest first. Absent when nothing is visible |
| `activity-item-{payment_id}` | `/` | One per visible payment, a direct child of `activity-list`, with `data-visibility="public"` or `"private"` |
| `activity-parties-{payment_id}` | `/` | Text contains both handles |
| `activity-amount-{payment_id}` | `/` | Exactly the formatted amount (direction signs or arrows go outside it) |
| `activity-note-{payment_id}` | `/` | Exactly the note; present even when the note is empty |
| `empty-activity` | `/` | Shown instead of `activity-list` when nothing is visible |
| `incoming-list`, `outgoing-list` | `/requests` | Containers, present once loaded, even when empty. Items are direct children, newest first |
| `request-item-{request_id}` | `/requests` | One per request (every status), with `data-status` |
| `request-amount-{request_id}` | `/requests` | Exactly the formatted amount |
| `request-pay-{id}`, `request-decline-{id}` | `/requests` | Buttons, present only on a pending incoming request |
| `request-cancel-{id}` | `/requests` | Button, present only on a pending outgoing request |
| `empty-requests` | `/requests` | Present only when both lists are empty (the containers stay) |
| `split-amount`, `split-handles`, `split-note`, `split-submit` | `/split` | Inputs and button (`split-handles`: comma-separated handles, in order) |
| `split-preview` | `/split` | Present whenever the amount and the handle list are valid, before anything is posted; holds one `split-share-{handle}` per participant, in order |
| `split-share-{handle}` | `/split` | Exactly the formatted share |
| `split-error`, `split-uncertain`, `split-success` (the last two P) | `/split` | As the pay elements |
| `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit` | `/authorizations` | The authorize form; same input rules as the pay form (D46) |
| `authorize-error`, `authorize-uncertain`, `authorize-success` (the last two P) | `/authorizations` | As the pay elements |
| `authorization-list` | `/authorizations` | Container, present once loaded, even when empty; direct children newest first (both directions) |
| `authorization-item-{id}` | `/authorizations` | With `data-status` (the API status) |
| `authorization-amount-{id}` | `/authorizations` | Exactly the formatted authorized amount |
| `authorization-captured-{id}` | `/authorizations` | Exactly the formatted `captured_amount`; present only when `status` is `captured` |
| `authorization-expires-{id}` | `/authorizations` | Text is exactly the API's `expires_at` string (a human-friendly time may sit beside it) |
| `authorization-capture-amount-{id}` | `/authorizations` | Decimal input pre-filled with the remaining amount in decimal form (`20.00`; `2000` for JPY); present only on an incoming open authorization |
| `authorization-capture-{id}` | `/authorizations` | Button; present only on an incoming open authorization |
| `authorization-void-{id}` | `/authorizations` | Button; present only on an outgoing open authorization |
| `authorization-error`, `authorization-uncertain` (the last P) | `/authorizations` | As the pay elements, for capture and void |
| `empty-authorizations` | `/authorizations` | Present only when the list is empty (the container stays) |

Inputs and validation:

- Amount format (I39): `formatMoney(minor, minor_units, currency)`, no grouping separators, no sign.
- Amount input (D44): trim surrounding whitespace; the text must match `^[0-9]+(\.[0-9]{1,m})?$` with `m = minor_units` (no `.` at all when `m` is 0); the value is the integer part times 10^m plus the fraction padded on the right to `m` digits, computed without floating point; it must be 1 to 1000000000 minor units. Anything else shows that form's error element with a human message and sends nothing. Amount fields are `<input type="text" inputmode="decimal">`, never `type="number"`, so any text can be typed. Currency and `minor_units` come from `GET /me`.
- Handles (D45): trimmed, one leading `@` removed. `split-handles` is split on commas; each entry is trimmed and `@`-stripped; empty entries are dropped; a repeated handle or more than 200 handles shows `split-error` and sends nothing.
- Notes: no `maxlength` attribute (a 200-emoji note is valid and is 400 UTF-16 units); a note over 200 code points shows the form's error and sends nothing.
- Submit buttons are never disabled for invalid input (clicking shows the error). A submit or action button may be disabled only while its own write is in flight. `wallet-refresh` and `load-retry` are never disabled: a click while a load is pending starts a newer load, and the newer load wins (D63).

Writes (D42, D43, D56):

- Retry identity. Each idempotent form (pay, request, split, authorize, and each authorization's capture) keeps an idempotency key and the exact body of its last submission. The key is 128 random bits from `crypto.getRandomValues`, in hex. A new key is minted for the first submission and whenever any field of that form changed (an `input` or `change` event) since the last submission; an unchanged resubmission sends the same key and the identical body. Paying a request uses one key per request, kept for retries, with the body `{}`.
- Outcomes. A 2xx (201, or a 200 replay) is success. A 4xx with the error envelope is a refusal: show the error element with a human message (an error code alone is not a message) and keep every input. A network failure, an abort, no response within 6 s, a 5xx or a body that is not JSON is an unknown outcome: show the uncertain element, never the error element, and keep the form and its retry identity. Success removes the error and uncertain elements.
- After a success or a refusal the page re-reads its data (wallet numbers, feed, lists) once the write's response has arrived, never before. After an unknown outcome it re-reads the data too, and leaves the uncertain element in place until a retry resolves it.
- Decline, cancel and void have no key; a refusal shows the error element and re-reads the list; an unknown outcome shows the uncertain element and re-reads the list.
- Capture sends `{"amount": <minor units>}` and no `final`: a final capture, the API default (D47). A builder may add a "keep the rest on hold" control that sends `"final": false`, off by default.

Refresh (I44): each screen numbers its loads of each resource (`/me`, `/activity`, each list) in the order they start; a response or failure is applied only if no later load of that resource has been applied already. The first load, the reloads after a write, `wallet-refresh` and `load-retry` all follow this rule. Data that arrives clears a load error.

Screens:

- `/`: the wallet summary (`wallet-available` as the headline, `wallet-balance` and `wallet-held` secondary, `wallet-refresh`), the pay form, the request form and the activity feed from `GET /activity` (the first page; a "show more" control that reads the next page is welcome).
- `/requests`: incoming (`direction=incoming`) and outgoing (`direction=outgoing`) lists of every status, each item with the counterparty, amount, note, status and date, and the actions the table allows. Actions re-read both lists.
- `/split`: the split form, the live preview by the §9 rule (the same rule as the server: one shared module, or a copy pinned to the server's by builder tests), and after success a summary of the requests created.
- `/authorizations`: the wallet summary as on `/`, the authorize form and the list from `GET /authorizations` (both directions). Each item shows direction and counterparty, amount, captured and remaining amounts, status, note and expiry (the RFC 3339 text in `authorization-expires-{id}` plus a human time beside it). Capture and void re-read the list and the wallet numbers.
- `/signup`, `/login`: the forms, `auth-error`, and links between them.

### 3.15 Visual and interaction direction (S2, new; D58)

- Character: calm and trustworthy. A light neutral background, white surfaces, one accent colour, one type scale with tabular figures for money, a 4/8 px spacing scale, consistent radius, borders and elevation, the system font stack, inline SVG icons.
- Hierarchy: `available` is the largest number on `/` and `/authorizations`, labelled as what the user can spend; total and held are visibly secondary and labelled.
- Status always has text as well as colour: pending (amber), paid and captured (green), open (accent), declined, cancelled, voided and expired (grey). Private payments carry a "Private" label with a lock icon.
- Money direction from the viewer's side ("Sent", "Received", or between two other people), with any sign or arrow outside the amount element. Parties as handles (`@ada → @bob`), with the viewer marked "you". Times for people (for example "Today, 14:03") inside `<time datetime>`. Ids are not shown.
- States are visually distinct: loading (skeleton or spinner with text), success (green-tinted confirmation), refused (red-tinted message with the reason), uncertain (amber message saying the money may have moved and that retrying without changes is safe), empty (short helpful text with the next action), held (badge or lock).
- Layout: one column below 720 px; on `/` two columns (forms and wallet beside the feed) from 960 px; the navigation fits a 375 px screen as a row of tabs; long display names, handles and notes wrap or truncate with an ellipsis; no horizontal page scroll anywhere.
- Accessibility: every input and select has a visible `<label for>`; `:focus-visible` shows an outline of at least 2 px with at least 3:1 contrast; text contrast meets I46; status messages sit in `aria-live` regions; actions are `<button>`, navigation is `<a>`; `<html lang="en">`; forms submit with Enter.

## 4. Work items

Every handoff names its commit, the gate evidence (build, builder tests, acceptance suite, supplied checks) and its gaps.

### W7 Holds API (builder)

Specification: stage-2 "Authorizations and captures", "Model", "API" (all four endpoints and `GET /me`), "Concurrent operations"; stage-1 §7, §8 tables, §11 affordability. Invariants: I1, I2, I8, I9, I10, I15–I19, I22, I25, I27–I29, I30–I36, I38, I49.

- W7.1 `GET /me` has exactly the section 3.6 fields: `balance == total`; with no holds `available == total` and `held` 0; with holds `available = total − held`; every stage-1 field unchanged.
- W7.2 `POST /authorizations`: the 201 body exactly (status `open`, `captured_amount` 0, `remaining_amount` = amount, `payment_id` null, `payment_ids` [], `expires_at` = `created_at` + TTL for the default 600 and a fixture TTL); every error row with section 3.5 precedence; `insufficient_funds` on `available` (a hold of exactly `available` succeeds, one unit more is 409); the five rows of the §7 table, scoping by user and path, 50 concurrent identical first uses give one 201; a replay after a capture or void returns the original open body; a hold moves no money and never appears in `GET /activity`.
- W7.3 Capture: a default capture takes the whole remainder; a smaller final capture releases the rest in the same step (`available` rises by it); `final: false` keeps the rest held and allows further captures up to it; capturing the entire remainder with `final: false` closes it; `captured_amount`, `payment_id`, `payment_ids`, `remaining_amount` as specified; the 201 payment is exactly the section 3.6 shape with `authorization_id`, `request_id: null`, `settlement_id: null`, copied note and visibility, and appears in feeds by the ordinary rule; every error row (409 not open for captured and voided, 409 expired, 422 exceeds against the remainder including amounts above 1000000000, 422 for `0`, `1.5`, `"10"`, `true`, `null`, 400 for a non-boolean `final` including `null`, 403 for the payer and a non-party, 404 unknown) in section 3.5 order; an identical replay returns 200 with the original payment even after the authorization closed; `{}` and `{"amount": N}` under one key, and `{"amount": 700}` and `{"amount": 700, "final": true}` under one key, are 409 `idempotency_key_reuse`; the receiver's 2^53 guard is 422 with nothing changed.
- W7.4 Void: payer only (403 for the receiver and for a non-party); no key needed; open becomes voided with the remainder released; voided again is 200 with the current state; captured and expired (by the clock and seeded) are 409 `authorization_not_open`; a partially captured authorization keeps `captured_amount` and `payment_ids` and ends with `remaining_amount` 0; unknown is 404.
- W7.5 `GET /authorizations`: only the caller's; `direction` and `status` alone and together; an authorization expired by the clock appears under `expired` and never under `open`; newest first; `limit`, `offset`, `has_more`; invalid values 422; JSON for `Accept: application/json`, `*/*` and no `Accept`.
- W7.6 Expiry by the clock: with a fixture TTL of 1 or 2 seconds, after the deadline and with no request at the deadline, the list shows `expired`, `held` excludes it and `available` includes the remainder, capture is 409 `authorization_expired`, void is 409 `authorization_not_open`; a capture before the deadline succeeds. Seeded open holds with `expires_at` an hour in the past read `expired` right after the reset.
- W7.7 Funds on `available`: `POST /payments`, `POST /requests/{id}/pay` and `POST /settlements` are 409 `insufficient_funds` when `total` covers the amount but `available` does not, and succeed when `available` covers it; a payment and a request payment move money at once and leave `held` unchanged (no intermediate hold); a capture may spend held money; with no holds every stage-1 result is unchanged.
- W7.8 Fixture: TTL default and validation; every authorization rule of section 3.11 gives 422 with the previous state intact; seeded open holds count in `held` right after the reset; the sum of unexpired open seeded remainders above the balance is 422 and equal is 204; seeded captured, voided and expired holds hold nothing; seeded `expires_at` comes back exactly as written; fixtures without `authorizations` behave as in stage 1.
- W7.9 Concurrency: 50 concurrent payments and authorizations from one wallet give exactly as many 201s as `available` allows and never a negative read; a concurrent capture and void of one open authorization have one winner and the money matches the winner; 20 concurrent `final: false` captures with distinct keys never exceed the authorized amount; I1 and I2 at every read.

### W8 Export, import and upgrade (builder)

Specification: stage-1 §10; stage-2 "Existing clients after an upgrade". Invariants: I12, I15, I25, I26, I28, I37.

- W8.1 The export has `format_version` 1 and `state.schema` 2 with the TTL, every authorization (section 3.12 fields) and each payment's `authorization_id`; it is one snapshot; no plaintext password.
- W8.2 A stage-2 round trip, in the same container and into a second one, keeps open, partially captured, captured, voided and expired authorizations, holds, `available`, `held`, capture payments and replays of authorization and capture keys; an open authorization whose deadline passes after the import expires by the clock.
- W8.3 Upgrade: an unchanged export from a container built from the frozen `stage-1/` imports with 204; its tokens authenticate; logins work; `GET /me` shows `balance == total == available` and `held` 0; feeds and request lists match (ids, timestamps, order; payments now show `authorization_id: null`); replays of its keys return 200 with the stored stage-1 bodies unchanged; keys that failed are reusable; pending requests are payable; new authorizations work for imported users; new ids and timestamps never collide or go backwards.
- W8.4 Rejected imports leave the destination unchanged: a schema other than 1 or 2, and schema-2 states with a dangling user, an unknown status, `captured_amount` above `amount`, a duplicate authorization id, an `expires_at` that is not RFC 3339, a `payment_ids` that is not an array of strings, or unexpired open remainders above the payer's total. A state built by a reset whose fixture links an authorization to payments that do not exist exports and imports back with 204. An export whose payer spent, after a hold's deadline passed, money that hold once reserved imports with 204.

### W9 UI foundation (builder)

Specification: stage-2 introduction, route table, "Product and visual direction", "Signup and login"; stage-1 §2 (runtime assets in the image). Invariants: I45, I46, I47, I48, I49.

- W9.1 Routes and documents per section 3.14: `/`, `/split`, `/signup`, `/login` serve the shell; `/requests` and `/authorizations` serve it only when `Accept` lists `text/html` (with and without a token, with query strings) and JSON otherwise; the supplied route checks pass; unknown paths give JSON 404, or the HTML 404 screen for `text/html`; headers per section 3.14; every page and asset loads from a `--network=none` container and no page requests another origin.
- W9.2 Signup: creates the account and shows `current-user` (contains the display name) and `current-handle` (exactly the derived handle, for example `dee_ann` for `dee.ann@example.com`); refused signups (email taken, handle taken, invalid email, short password, empty display name) show `auth-error` with a human message; `auth-error` is absent when there is no error.
- W9.3 Login and logout: a wrong password and an unknown email show `auth-error`; success shows `current-user` on every route; logout removes it and shows `/login`; signed-out visits to the four signed-in routes show `/login`; `/login` and `/signup` render their forms while signed in; a 401 clears the session.
- W9.4 The shared header and the `nav-*` links on every route, the current one marked, all reachable by keyboard; every route passes the I46 checks at both widths.
- W9.5 Builder tests (`node:test`) for the browser's pure modules: amount parsing and formatting for `minor_units` 0, 2 and 3, the §9 preview against the server rule, and the retry identity.

### W10 Wallet screen (builder)

Specification: "Balance and pay", "Activity feed", "Competing clients and uncertain outcomes", "Existing clients after an upgrade", the wallet rows of the stage-2 UI table. Invariants: I39–I45, I47.

- W10.1 Wallet numbers: `wallet-available` (headline), `wallet-balance` and `wallet-held` (absent at 0) with exact text and `data-amount`, including right after a reset with seeded open holds, and for `minor_units` 0, 2 and 3.
- W10.2 Pay form: `15`, `15.00` and `15.5` submit 1500, 1500 and 1550 (and the equivalents for `minor_units` 0 and 3); `abc`, `15.005`, `1e3`, `-1`, `1,5`, an empty field, `0`, more than 1000000000 minor units and a 201-code-point note show `pay-error` and send no request; the visibility select works; insufficient `available` (when `total` would cover it) and an unknown handle show `pay-error`; a refusal re-reads the wallet and feed and keeps every input; a success updates the numbers and the feed without a reload and keeps the values; an unchanged resubmission re-sends the same key and body (one payment, no `pay-error`); changing a field and submitting makes a second payment.
- W10.3 Uncertain outcomes: a response lost after the server committed (route `fetch` then `abort`) shows `pay-uncertain`, not `pay-error`; retrying unchanged sends the same key and body, moves the money once, removes `pay-uncertain` and `pay-error`, and refreshes the numbers and the feed; a request lost before the server saw it (abort without `fetch`) then retried moves money once; a 5xx and a response held past 6 s are uncertain too.
- W10.4 Request form on `/`: creates a request with the decimal rules; `request-error` for a refusal (unknown handle, own handle) and for invalid input (no request sent); `request-success`; the unchanged-resubmission rule.
- W10.5 Activity feed: one item per visible payment with `data-visibility`, parties containing both handles, the exact amount and the exact note (present when empty); direct children newest first; `empty-activity` instead of the list; other people's private payments hidden; capture payments shown by the ordinary rule.
- W10.6 `wallet-refresh` shows another client's payment and the new numbers, keeps the pay form's values, and latest refresh wins when an earlier `/me` or `/activity` response is delayed past a later one. `wallet-refresh` stays clickable while its own load is pending: with the first refresh's `/me` and `/activity` responses held, a second click starts a new load; once it lands and the held responses are released, the second load's numbers and feed stay on screen.
- W10.7 Upgrade: a signed-in page stays signed in across an export and import of the service's own state (no reload); a payment whose response was lost before the export, retried after the import with the same key and body, shows success and the imported balance with the payment counted once; a pending request in the imported state is payable from `/requests`.

### W11 Requests, split and holds screens (builder)

Specification: "Requests", "Split", the authorization rows of the stage-2 UI table, "Competing clients and uncertain outcomes". Invariants: I39–I46.

- W11.1 `/requests`: both containers present once loaded; items with `data-status` and the exact amount; pay and decline only on pending incoming requests, cancel only on pending outgoing ones; each action updates the item's status without a reload; `empty-requests` only when both lists are empty; `request-error` for a refusal (insufficient `available`, not pending), and the lists re-read so a request cancelled elsewhere loses its stale pay button; `request-uncertain` on a lost response; a retried request payment reuses its key.
- W11.2 `/split`: the preview matches §9 (10.00 among three gives 3.34, 3.33, 3.33; the extra unit follows the order) before anything is posted, and the submitted split's shares equal it; `split-error` for an unknown handle (server 404), an invalid amount and a repeated handle (no request); `split-success`; an unchanged resubmission creates no second split.
- W11.3 `/authorizations`: the authorize form with the decimal rules, `authorize-error` (including insufficient `available`) and `authorize-success`; the list newest first with `data-status`, the exact amount, `authorization-captured-{id}` only when captured, the exact `expires_at` text; the capture input pre-filled with the remainder; capture and void buttons only where allowed; full capture, partial capture and void update the item and the wallet numbers without a reload; `authorization-error` for refusals (expired, not open, exceeds); `empty-authorizations`; seeded holds show right after a reset with `available` as the headline.
- W11.4 Every screen passes the I46 checks in each named state (loading, empty, loaded, success, refused, uncertain) at both widths.

### W12 Acceptance suite (verifier)

Specification: all of stage 2 and everything of stage 1 that stage 2 keeps. Invariants: all.

- W12.1 `stage-2/acceptance/` holds the suite, runnable with one documented command: the stage-1 suite brought to the stage-2 contract (new fields, `/` is now a page, funds on `available`) plus the new tests. It builds the frozen `stage-1/` as the previous service for the upgrade tests.
- W12.2 Every criterion W7.1–W11.4 and every invariant I1–I49 has at least one test; I1 and I2 (with `held ≤ total`) are asserted after every state-changing test and during every burst.
- W12.3 Browser tests drive real Chromium (Playwright from the harness venv) at 375×812 and 1280×800 using only the `data-testid` names of section 3.14, and inject faults with `page.route`: delays, aborts before and after the server commits, out-of-order responses, 5xx.
- W12.4 Every named UI state is screenshotted at both widths under `.work/verifier-h6bh/shots/<short-hash>/`, and the path is posted with each UI verdict.
- W12.5 Its path and commit are posted before the W7 verdict; it grows whenever the trace (section 6) finds a gap.

## 5. Decisions

Stage 1's D1–D38 continue to apply. New decisions:

- **D39 UI architecture.** A client-rendered page: one HTML shell for every UI route, JavaScript ES modules and one stylesheet, served by the same Node process from files in `stage-2/` read at start-up. No framework, bundler or npm dependency; nothing is downloaded. Reason: `pay-uncertain`, same-key retries and latest-refresh-wins need the page to own its requests (a plain form POST cannot show an uncertain state after a lost response), the JSON API already exists, and the offline build (D2) stays. The browser code is plain JavaScript, since browsers do not run TypeScript; pure logic is kept in small modules the builder tests import.
- **D40 Content negotiation.** `/requests` and `/authorizations` serve HTML only when `Accept` lists `text/html` (section 3.2), as the specification says ("Return the UI for `Accept: text/html`; API requests without that header receive JSON"). Browsers send it on navigation; API clients and the page's own `fetch` calls do not.
- **D41 Session in `localStorage`.** The API authenticates with bearer tokens only, so the page holds the token and sends it. No cookies means no CSRF surface; strict CSP and text-only rendering (I48) protect the token. It survives navigation and, because the token is part of the exported state, an export and import.
- **D42 Retry identity.** One key per form submission identity, kept until a field changes: this is the specification's "submitting it again without changing a field must not send another payment" and "changing a field makes the next submission a new payment request", and it is also what makes a lost response safely retryable. Keys come from `crypto.getRandomValues`, which works in insecure contexts too.
- **D43 Unknown outcomes.** Only a 4xx with the envelope is a confirmed refusal; everything else that is not a 2xx is uncertain ("Unknown outcomes are not confirmed rejections"). The 6 s client limit sits above the 5 s per-request budget and below the browser checks' 10 s waits.
- **D44 Amount grammar.** Digits with an optional fraction of 1 to `minor_units` digits, nothing else (no sign, exponent, grouping or comma decimal), parsed without floating point, 1 to 1000000000 minor units. Stricter than a locale parser, and exactly the specification's examples (`15`, `15.00`, `15.5` valid; `15.005` refused).
- **D45 Handle inputs.** Trim and strip one leading `@`, because people write handles that way; the server still decides whether the handle exists. Split lists drop empty entries, so a trailing comma is harmless.
- **D46 Authorize form on `/authorizations`.** The form sits with the list it adds to, under the only route the specification gives authorizations, and that screen repeats the wallet summary so a new hold's effect is visible on the same page. `/` shows the wallet numbers and links to it.
- **D47 Capture from the UI is a final capture by default.** It sends the amount from `authorization-capture-amount-{id}` and no `final`, matching the API default; extended capture mode is optional in the UI.
- **D48 Seeded authorizations.** Fields and defaults as section 3.11. `expires_at` is returned exactly as seeded, since the UI must show "the RFC 3339 `expires_at`" and the checks may compare it with the seed; it is compared as an instant. `captured_amount` defaults to the full amount for a seeded `captured` hold, the natural meaning of "captured". An open seed must leave something to capture. The TTL is capped at 10^10 s (about 317 years) so `expires_at` stays a four-digit-year timestamp.
- **D49 Service clock.** `now` = the later of the wall clock and the last issued timestamp, taken once per operation, so expiry agrees with the timestamps the service issues (also after an import whose timestamps are ahead of the wall clock). A reset re-bases the clock to its own time, so a fixture's expiry times are judged against the reset, as the specification states ("at least an hour from reset time").
- **D50 Capture precedence and codes.** State before amount: a closed or expired authorization answers 409 whatever the amount, because there is no remainder to compare with. Expired (by the clock or seeded) is `authorization_expired`; captured or voided is `authorization_not_open`. An amount above the remainder is `capture_exceeds_authorization` even above 1000000000, the more specific code. `final` of another JSON type is 400 under §5's wrong-type rule.
- **D51 Representations.** `remaining_amount` and `payment_ids` are in every authorization representation ("Every authorization response adds `remaining_amount`"); `closed_at` stays internal until stage 3 asks for it.
- **D52 Export schema 2.** `format_version` stays 1 as §10 fixes it; the state's own `schema` tells the import which layout it reads.
- **D53 Settlement affordability.** `available + incoming − outgoing ≥ 0` per wallet: held funds cannot fund settlement net debits, and a wallet that only receives is never refused.
- **D54 Verbatim replays.** A replay returns the stored original body, so a stage-1 body comes back without `authorization_id` (§7: "body identical to the original response").
- **D55 Lists and empty states.** `empty-activity` replaces `activity-list` ("shown instead of the list"); the request and authorization containers stay present when empty and `empty-requests` and `empty-authorizations` appear beside them (the supplied route check waits for `incoming-list` on an empty fixture). Items are direct children, because the checks read `activity-list > *`.
- **D56 Every money form behaves like the pay form.** Request, split and authorize forms keep their values after success and follow D42, so a double submit never creates a duplicate request, split or hold.
- **D57 Plan testids.** `nav-*`, `loading`, `load-error`, `load-retry`, and the `*-success` and `*-uncertain` elements beyond `pay-uncertain`, let the acceptance suite check navigation and every named state without reading the code.
- **D58 Visual direction.** Section 3.15, from the specification's product and visual direction; the acceptance suite checks the measurable parts (I46) and the critic and planner review the screenshots for the rest.
- **D59 HTML 404.** A browser that follows a wrong link gets the app's not-found screen with navigation instead of a JSON body; API clients still get the stage-1 envelope.
- **D60 Request payments from the UI are public.** `request-pay-{id}` sends `{}`, the API default; the specification gives the request screen no visibility control.
- **D62 Import accepts whatever reset can build.** `payment_id`, `payment_ids` and a payment's `authorization_id` are display-only links: the service never follows them to move money or decide permissions, so neither reset nor import checks that they point anywhere, only their types. Otherwise a fixture-built state could export but not import back, breaking I26 and I37. (Builder question on W8.)
- **D63 Refresh buttons stay enabled.** "Latest refresh wins ... including when responses arrive out of order" needs two refreshes in flight at once, so `wallet-refresh` and `load-retry` are never disabled; only a write's own button may be disabled while that write is in flight. (Verifier question Q1.)
- **D61 Body equality is unchanged.** "New fields do not change idempotency body equality" is read as: the equality rule stays §7's JSON-value equality, so a replay must send the identical body; `{"amount": 700}` and `{"amount": 700, "final": true}` are different bodies, exactly as the specification says of `{}` and `{"amount": 2000}`. Replays return the stored original response, whatever fields later responses gained (D54).

## 6. Specification trace

Filled in once W12's first suite lands: each normative line of stage-2.md, and each stage-1 line that stage 2 changes, with the tests that exercise it. A row without a test when its item's tests land is a gap and becomes a criterion at once.

## 7. Handoff log

| Handoff | To | Sent | Acknowledged | State |
|---|---|---|---|---|
| Stage-2 handoff, parts 1-14 (plan 46d9da6) | builder, verifier, critic | 09:13Z | — | sent |

## 8. Stage close

Not yet.
