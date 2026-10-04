# Stage 2 plan — Pocketful: wallet screens and payment authorizations

Owner: planner (`planner-h6bf`). Repository: `/Users/Dileepa/dark-factory-v3`, folder `stage-2/`, which started as a copy of the accepted `stage-1/` (`scripts/new-stage.sh 2`, commit 5f5d4a4).
Specification: `/Users/Dileepa/df-spec/pocketful/spec/stage-2.md`, plus every part of `stage-1.md` that stage 2 does not change. Both are pasted verbatim into the handoff.
Supplied checks (a partial sample, about 35% of the graded stage-2 checks, used only to wire the service up): `/Users/Dileepa/df-spec/pocketful/test/stage_2/`. The stage-1 checks also run against this folder.
Frozen reference: `/Users/Dileepa/dark-factory-v3/stage-1/` with its `PLAN.md`, accepted at 4baf8d9. Never edit it. Building it read-only, for example as the previous service in the upgrade tests, is fine.

## Status

| Item | Owner | Title | State | Commit |
|---|---|---|---|---|
| W7 | builder | Holds API: `GET /me` money fields, authorizations, capture, void, list, expiry, funds judged on `available` | BLOCKED (PASS @ 16adbc0, suite cb62939; critic BLOCKED: X15, a reset keeping a clock that ran ahead, untested; test owed by the verifier, no product change) | 16adbc0 |
| W8 | builder | Export schema 2 and import of stage-1 exports (upgrade) | VERIFIED (PASS @ 54acbcd, suite 62c4a4e: 1488 passed --upto 8; npm test 137/137; supplied stage 1 147/147); awaiting critic | 54acbcd |
| W9 | builder | UI foundation: HTML routes, shell, visual system, signup, login, logout, navigation | PLANNED | — |
| W10 | builder | Wallet screen `/`: wallet numbers, pay and request forms, activity feed, refresh, uncertain outcomes, upgrade | PLANNED | — |
| W11 | builder | Requests, split and holds screens | PLANNED | — |
| W12 | verifier | Stage-2 acceptance suite: stage-1 regression, holds API, upgrade, browser | BUILDING (suite ca09237, 1980 checks, plan 45fe2dc criteria included; not yet draft-run on a product) | ca09237 |

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

Stage 3 must import exports from stage 1 and stage 2, account for authorizations and captures, and rebuild historical holds: a hold starts at creation, a nonfinal capture reduces it at the capture's time, and a final capture, a void or an expiry releases the remainder at that event's time. So the stage-2 export carries, for every authorization: id, both parties, amount, captured amount, note, visibility, stored status, `expires_at`, `created_at`, `closed_at` (the time a void, final capture or full capture closed it; the reset's timestamp for an authorization seeded as `captured`, `voided` or `expired`; null while open and for clock expiry, whose time is `expires_at`, including a seeded open hold whose `expires_at` had already passed at the reset, which holds nothing from the reset on) and the capture payment ids in order. Every payment carries `authorization_id` and `created_at`. The state also carries `authorization_ttl_seconds`.

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
- **I34 Expiry by the clock.** Once the service clock reaches `expires_at`, an open authorization, with no request at the deadline, reads `expired` (also under `status=expired`, never under `status=open`), holds nothing, capture is 409 `authorization_expired` and void is 409 `authorization_not_open`. The clock turns only open authorizations into expired ones: captured and voided authorizations keep their status, their filters and their answers after their deadline (D50).
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
- **I46 Responsive and accessible.** At 375×812 and 1280×800, and at 1024×768 for the scroll check, no route in any named state scrolls horizontally (`document.documentElement.scrollWidth <= window.innerWidth`); every input and select has a visible associated label; the keyboard focus is visible on every interactive element; text contrast is at least 4.5:1 (3:1 for text 18.66 px bold or 24 px and larger), and input borders, button boundaries and the focus indicator have at least 3:1 against their background.
- **I47 Session.** A signed-in browser stays signed in across navigation between routes and across an export/import that contains its token. `current-user` is visible on every screen while signed in, and absent after logout.
- **I48 Safe rendering (inferred).** Notes, display names and handles are rendered as text, never as HTML, and no page loads anything from another origin (no fonts, scripts, styles or images from the network). Checked with a display name and a note of `<img src=x onerror=alert(1)> &amp;`, which show literally and run nothing.
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
- `POST /authorizations/{id}/capture`: route 404, 401, key (400, 422), body (422 size, 400 unreadable), claimed key (200 replay or 409 reuse), `final` type 400, `amount` value 422 `validation_failed`, unknown authorization 404, caller not the receiver 403 (non-parties included), captured or voided 409 `authorization_not_open` (whatever the clock says), deadline passed (`now >= expires_at`, for an open or a seeded `expired` authorization) 409 `authorization_expired`, a stored `expired` whose deadline is still ahead (a seeded corner) 409 `authorization_not_open`, amount above the remaining amount 422 `capture_exceeds_authorization`, the receiver's 2^53 guard 422 `validation_failed`, commit (D50).
- `POST /authorizations/{id}/void`: route 404, 401, unknown 404, caller not the payer 403 (non-parties included), then by state: open and before its deadline → voided 200; voided → 200 with the current state (also after its deadline); captured, open past its deadline, or stored `expired` → 409 `authorization_not_open`. No key; the body is never read.
- `GET /authorizations`: 401, then query validation 422 (`direction`, `status`, `limit`, `offset`), as `GET /requests`.

### 3.6 Representations (S2: exactly these fields)

- Me: `{"user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units"}`. `balance == total`.
- Payment, identical wherever a payment appears (create, replay, pay, capture, feed, settlement): `{"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency", "note", "visibility", "request_id", "settlement_id", "authorization_id", "created_at"}`. `authorization_id` is the captured authorization or `null`. A replay returns the stored original body unchanged, so a replayed stage-1 body has no `authorization_id` (D54).
- Authorization, identical wherever one appears (create, replay, void, list): `{"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "captured_amount", "remaining_amount", "currency", "note", "visibility", "status", "expires_at", "payment_id", "payment_ids", "created_at"}`. `status` is the stored status, except that an open authorization at or past its `expires_at` reads `expired`; captured and voided ones keep their status whatever the clock says; `payment_id` is the latest capture's payment or `null`; `payment_ids` lists every capture's payment in order (`[]` when none) (D51). `closed_at` is recorded in the state for stage 3 and is not part of any response.
- Lists: `{"payments": [...], "has_more": bool}`, `{"requests": [...], "has_more": bool}`, `{"authorizations": [...], "has_more": bool}`.
- Request, Split, Settlement, signup and login: unchanged (settlement members and request payments carry `authorization_id: null`).

### 3.7 Ids, timestamps, order, paging

- (S2) Generated authorization ids are `a_<random>`, same rules as stage 1's ids (D16). Seeded ids are used verbatim.
- (S2) A created authorization's `expires_at` is its `created_at` plus `authorization_ttl_seconds`, in stage 1's timestamp form `YYYY-MM-DDTHH:MM:SS.sss+00:00`. A seeded `expires_at` is returned exactly as the fixture wrote it and compared as an instant (D48).
- (S2) Service clock (D49): `now` is the later of the wall clock and the state's last issued timestamp. An operation takes `now` once, at its start, and uses it for every expiry decision it makes. An open authorization is expired when `now >= expires_at`; the clock never turns a captured or voided authorization into an expired one. A reset starts its state's last issued timestamp at the reset's own wall-clock time; an import keeps stage 1's rule (new timestamps are never earlier than imported ones).
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
- Seeded authorizations take the reset's timestamp as `created_at`. Those seeded `captured`, `voided` or `expired` also take it as `closed_at`; seeded `open` ones have `closed_at` null. A seeded `open` authorization whose `expires_at` is at or before the reset time reads `expired` at once and holds nothing.

### 3.12 Export and import (S2)

- `GET /_test/export`: `{"track": "pocketful", "format_version": 1, "state": {...}}` with `"schema": 2`. The state holds everything of schema 1 plus `authorization_ttl_seconds`, every authorization (all stored fields, including `created_at`, `closed_at`, `expires_at` exactly as stored, and `payment_ids`) and each payment's `authorization_id`. Built in one synchronous step.
- `POST /_test/import` accepts `schema` 1 (an unchanged stage-1 export: TTL 600, no authorizations, every payment `authorization_id: null`, stored replay bodies kept verbatim) and `schema` 2. Any other schema, and any state that fails full validation, is 422 with nothing changed. Schema-2 validation adds: authorization fields as in section 3.11; `created_at` and `closed_at` (null or a timestamp); `payment_id`, `payment_ids` and each payment's `authorization_id` checked only for type, as reset checks them, because they are display-only links the service never follows and every state a reset can build must import back (D62); for every user, the remainders of the open authorizations whose `expires_at` is after the import's `now` (the later of the wall clock and the imported state's last issued timestamp: the clock the destination applies right after the swap) not above the user's `total`. Open authorizations already past their deadline hold nothing and are not counted: a payer may have spent that money after the deadline and before the export, so counting them would refuse a valid export.
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
- A 401 from an authenticated call (one that sent the token) clears the token and shows `/login` with a notice that the session ended (an ordinary notice, not `auth-error`). Every refusal of `POST /auth/signup` or `POST /auth/login`, including the 401 for a wrong password or an unknown email, shows `auth-error` (D65).
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
| `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit` | `/`, `/authorizations` | The authorize form, on both screens (one per page); same input rules as the pay form (D46) |
| `authorize-error`, `authorize-uncertain`, `authorize-success` (the last two P) | `/`, `/authorizations` | As the pay elements |
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

- Retry identity. Each idempotent form (pay, request, split, authorize, and each authorization's capture) keeps an idempotency key and the exact body of its last submission. The key is 128 random bits from `crypto.getRandomValues`, in hex. A new key is minted for the first submission, whenever any field of that form changed (an `input` or `change` event) since the last submission, and whenever the body the form would send differs from the last submitted body (for example a capture amount the page re-filled after a re-read); an unchanged resubmission sends the same key and the identical body. Paying a request uses one key per request, kept for retries, with the body `{}`.
- Outcomes. A 2xx (201, or a 200 replay) is success. A 4xx with the error envelope is a refusal: show the error element with a human message (an error code alone is not a message) and keep every input. A network failure, an abort, no response within 4 s (the page then aborts the request with an `AbortController`, ignores any late response and re-enables the button), a 5xx or a body that is not JSON is an unknown outcome: show the uncertain element, never the error element, and keep the form and its retry identity. Success removes the error and uncertain elements.
- After a success or a refusal the page re-reads its data (wallet numbers, feed, lists) once the write's response has arrived, never before. After an unknown outcome it re-reads the data too, and leaves the uncertain element in place until a retry resolves it.
- Decline, cancel and void have no key; a refusal shows the error element and re-reads the list; an unknown outcome shows the uncertain element and re-reads the list. For every item action (request pay, decline, cancel, capture, void), when the re-read after an unknown outcome shows that the action took effect (the request or authorization now shows the new status, or a larger captured amount), the uncertain element is removed and the item shows that confirmed state.
- Capture sends `{"amount": <minor units>}` and no `final`: a final capture, the API default (D47). A builder may add a "keep the rest on hold" control that sends `"final": false`, off by default. If it does, the capture key follows the body rule above, so a re-filled amount or a changed `final` gets a new key.

Refresh (I44): each screen numbers its loads of each resource (`/me`, `/activity`, each list) in the order they start; a response or failure is applied only if no later load of that resource has been applied already. The first load, the reloads after a write, `wallet-refresh` and `load-retry` all follow this rule. Data that arrives clears a load error. Loads use the same 4 s limit as writes and end in `load-error`.

Reading lists (D64): each list's first read is the bare path with no query string (`GET /activity`, `GET /requests`, `GET /authorizations`, the API's default page), and `GET /me` is read bare too, so URL patterns such as `**/activity` match them. While `has_more` is true the page reads on with `?offset=<items read so far>&limit=200` and keeps each item once (de-duplicated by id, since pages may shift under concurrent writes). The page shows every item: one per visible payment, one per request, one per authorization. `/requests` splits its one list on the client: incoming where the caller is the payer, outgoing where the caller is the requester.

Screens:

- `/`: the wallet summary (`wallet-available` as the headline, `wallet-balance` and `wallet-held` secondary, `wallet-refresh`), the pay form, the request form, the authorize form (D46) and the activity feed (every visible payment, read as above).
- `/requests`: the incoming and outgoing lists (one `GET /requests` read, split by direction), every status, each item with the counterparty, amount, note, status and date, and the actions the table allows. Actions re-read the list.
- `/split`: the split form, the live preview by the §9 rule (the same rule as the server: one shared module, or a copy pinned to the server's by builder tests), and after success a summary of the requests created.
- `/authorizations`: the wallet summary as on `/`, the authorize form and the list from `GET /authorizations` (both directions). Each item shows direction and counterparty, amount, captured and remaining amounts, status, note and expiry (the RFC 3339 text in `authorization-expires-{id}` plus a human time beside it). Capture and void re-read the list and the wallet numbers.
- `/signup`, `/login`: the forms, `auth-error`, and links between them.

### 3.15 Visual and interaction direction (S2, new; D58)

- Character: calm and trustworthy. A light neutral background, white surfaces, one accent colour, one type scale with tabular figures for money, a 4/8 px spacing scale, consistent radius, borders and elevation, the system font stack, inline SVG icons.
- Hierarchy: `available` is the largest number on `/` and `/authorizations`, labelled as what the user can spend; total and held are visibly secondary and labelled.
- Status always has text as well as colour: pending (amber), paid and captured (green), open (accent), declined, cancelled, voided and expired (grey). Private payments carry a "Private" label with a lock icon.
- Money direction from the viewer's side ("Sent", "Received", or between two other people), with any sign or arrow outside the amount element. Parties as handles (`@ada → @bob`), with the viewer marked "you" beside the handle, never instead of it: `activity-parties-{id}` always contains both handles. Times for people (for example "Today, 14:03") inside `<time datetime>`. Ids are not shown.
- States are visually distinct: loading (skeleton or spinner with text), success (green-tinted confirmation), refused (red-tinted message with the reason), uncertain (amber message saying the money may have moved and that retrying without changes is safe), empty (short helpful text with the next action), held (badge or lock).
- Layout: one column below 720 px; on `/` two columns (forms and wallet beside the feed) from 960 px; the navigation fits a 375 px screen as a row of tabs; long display names, handles and notes wrap or truncate with an ellipsis; no horizontal page scroll anywhere.
- Accessibility: every input and select has a visible `<label for>`; `:focus-visible` shows an outline of at least 2 px with at least 3:1 contrast; text contrast meets I46; status messages sit in `aria-live` regions; actions are `<button>`, navigation is `<a>`; `<html lang="en">`; forms submit with Enter.

## 4. Work items

Every handoff names its commit, the gate evidence (build, builder tests, acceptance suite, supplied checks) and its gaps.

### W7 Holds API (builder)

Specification: stage-2 "Authorizations and captures", "Model", "API" (all four endpoints and `GET /me`), "Concurrent operations"; stage-1 §7, §8 tables, §11 affordability. Invariants: I1, I2, I8, I9, I10, I15–I19, I22, I25, I27–I29, I30–I36, I38, I49.

- W7.1 `GET /me` has exactly the section 3.6 fields: `balance == total`; with no holds `available == total` and `held` 0; with holds `available = total − held`; every stage-1 field unchanged.
- W7.2 `POST /authorizations`: the 201 body exactly (status `open`, `captured_amount` 0, `remaining_amount` = amount, `payment_id` null, `payment_ids` [], `expires_at` = `created_at` + TTL for the default 600 and a fixture TTL); every error row with section 3.5 precedence; `insufficient_funds` on `available` (a hold of exactly `available` succeeds, one unit more is 409); the five rows of the §7 table, scoping by user and path, 50 concurrent identical first uses give one 201; a replay after a capture or void returns the original open body; a hold moves no money and never appears in `GET /activity`.
- W7.3 Capture: a default capture takes the whole remainder; a smaller final capture releases the rest in the same step (`available` rises by it); `final: false` keeps the rest held and allows further captures up to it; capturing the entire remainder with `final: false` closes it; `captured_amount`, `payment_id`, `payment_ids`, `remaining_amount` as specified; the 201 payment is exactly the section 3.6 shape with `authorization_id`, `request_id: null`, `settlement_id: null`, copied note and visibility, and appears in feeds by the ordinary rule; every error row (409 not open for captured and voided, 409 expired, 422 exceeds against the remainder including amounts above 1000000000, 422 for `0`, `1.5`, `"10"`, `true`, `null`, 400 for a non-boolean `final` including `null`, 403 for the payer and a non-party, 404 unknown) in section 3.5 order; an identical replay returns 200 with the original payment even after the authorization closed; `{}` and `{"amount": N}` under one key, and `{"amount": 700}` and `{"amount": 700, "final": true}` under one key, are 409 `idempotency_key_reuse`; the receiver's 2^53 guard is 422 with nothing changed. The §7 rows for capture: a missing or empty key is 400 and a key over 255 characters is 422; a failed capture (422 exceeds, 409 expired) claims nothing, and the same key with a valid body then captures; the same key on two authorizations makes two captures (the canonical paths differ).
- W7.4 Void: payer only (403 for the receiver and for a non-party); no key needed; open becomes voided with the remainder released; voided again is 200 with the current state; captured and expired (by the clock and seeded) are 409 `authorization_not_open`; a partially captured authorization keeps `captured_amount` and `payment_ids` and ends with `remaining_amount` 0; unknown is 404.
- W7.5 `GET /authorizations`: only the caller's; `direction` and `status` alone and together; an authorization expired by the clock appears under `expired` and never under `open`; newest first; `limit`, `offset`, `has_more`; invalid values 422; JSON for `Accept: application/json`, `*/*` and no `Accept`.
- W7.6 Expiry by the clock: with a fixture TTL of 1 or 2 seconds, after the deadline and with no request at the deadline, the list shows `expired`, `held` excludes it and `available` includes the remainder, capture is 409 `authorization_expired`, void is 409 `authorization_not_open`; a capture before the deadline succeeds. Seeded open holds with `expires_at` an hour in the past read `expired` right after the reset. The clock turns only open authorizations into expired ones: with a TTL of 1 s, after the deadline, a fully captured authorization and a voided one still read `captured` and `voided` (under those filters, never under `expired`), capturing either is 409 `authorization_not_open`, and the voided one voids again with 200. A seeded `expired` authorization whose `expires_at` is still ahead: capture 409 `authorization_not_open`; with `expires_at` past: capture 409 `authorization_expired`; void 409 `authorization_not_open` in both cases.
- W7.7 Funds on `available`: `POST /payments`, `POST /requests/{id}/pay` and `POST /settlements` are 409 `insufficient_funds` when `total` covers the amount but `available` does not, and succeed when `available` covers it; a payment and a request payment move money at once and leave `held` unchanged (no intermediate hold); a capture may spend held money; with no holds every stage-1 result is unchanged.
- W7.8 Fixture: TTL default and validation; every authorization rule of section 3.11 gives 422 with the previous state intact; seeded open holds count in `held` right after the reset; the sum of unexpired open seeded remainders above the balance is 422 and equal is 204; seeded captured, voided and expired holds hold nothing; seeded `expires_at` comes back exactly as written; fixtures without `authorizations` behave as in stage 1. A reset after an import whose clock ran ahead (timestamps moved to 2099) starts the clock at the reset's own time: a seeded open hold expiring in two hours counts in `held`, reads `open`, and its `created_at` and a new payment's `created_at` are earlier than 2099 (critic X15).
- W7.9 Concurrency: 50 concurrent payments and authorizations from one wallet give exactly as many 201s as `available` allows and never a negative read; a concurrent capture and void of one open authorization have one winner and the money matches the winner; 20 concurrent `final: false` captures with distinct keys never exceed the authorized amount; I1 and I2 at every read. 50 concurrent identical first uses of one capture give one 201 and 49 replays with identical bodies, and the money moves once (I17).

### W8 Export, import and upgrade (builder)

Specification: stage-1 §10; stage-2 "Existing clients after an upgrade". Invariants: I12, I15, I25, I26, I28, I37.

- W8.1 The export has `format_version` 1 and `state.schema` 2 with the TTL, every authorization (section 3.12 fields) and each payment's `authorization_id`; it is one snapshot; no plaintext password.
- W8.2 A stage-2 round trip, in the same container and into a second one, keeps open, partially captured, captured, voided and expired authorizations, holds, `available`, `held`, capture payments and replays of authorization and capture keys; an open authorization whose deadline passes after the import expires by the clock. A state upgraded from a stage-1 export, then exported again (schema 2) and imported, still replays the stage-1 bodies verbatim, and its payments read `authorization_id: null`. Expiry at exactly the deadline: an imported schema-2 state whose last issued timestamp equals an open hold's `expires_at`, both ahead of the wall clock, makes the import's `now` the deadline, so the hold reads `expired`, holds nothing and capture is 409 `authorization_expired` (critic H02, H04).
- W8.3 Upgrade: an unchanged export from a container built from the frozen `stage-1/` imports with 204; its tokens authenticate; logins work; `GET /me` shows `balance == total == available` and `held` 0; feeds and request lists match (ids, timestamps, order; payments now show `authorization_id: null`); replays of its keys return 200 with the stored stage-1 bodies unchanged; keys that failed are reusable; pending requests are payable; new authorizations work for imported users; new ids and timestamps never collide or go backwards.
- W8.4 Rejected imports leave the destination unchanged: a schema other than 1 or 2, and schema-2 states with a dangling user, an unknown status, `captured_amount` above `amount`, a duplicate authorization id, an `expires_at` that is not RFC 3339, a `payment_ids` that is not an array of strings, or unexpired open remainders above the payer's total. A state built by a reset whose fixture links an authorization to payments that do not exist exports and imports back with 204. An export whose payer spent, after a hold's deadline passed, money that hold once reserved imports with 204.

### W9 UI foundation (builder)

Specification: stage-2 introduction, route table, "Product and visual direction", "Signup and login"; stage-1 §2 (runtime assets in the image). Invariants: I45, I46, I47, I48, I49.

- W9.1 Routes and documents per section 3.14: `/`, `/split`, `/signup`, `/login` serve the shell; `/requests` and `/authorizations` serve it only when `Accept` lists `text/html` (with and without a token, with query strings) and JSON otherwise; the supplied route checks pass; unknown paths give JSON 404, or the HTML 404 screen for `text/html`; headers per section 3.14; every page and asset loads from a `--network=none` container and no page requests another origin.
- W9.2 Signup: creates the account and shows `current-user` (contains the display name) and `current-handle` (exactly the derived handle, for example `dee_ann` for `dee.ann@example.com`); refused signups (email taken, handle taken, invalid email, short password, empty display name) show `auth-error` with a human message; `auth-error` is absent when there is no error. A display name `<img src=x onerror=alert(1)> &amp;` shows literally in `current-user` and runs nothing (I48).
- W9.3 Login and logout: a wrong password and an unknown email show `auth-error`; success shows `current-user` on every route; logout removes it and shows `/login`; signed-out visits to the four signed-in routes show `/login`; `/login` and `/signup` render their forms while signed in; a 401 clears the session.
- W9.4 The shared header and the `nav-*` links on every route, the current one marked, all reachable by keyboard; every route passes the I46 checks at both widths.
- W9.5 Builder tests (`node:test`) for the browser's pure modules: amount parsing and formatting for `minor_units` 0, 2 and 3, the §9 preview against the server rule, and the retry identity.
- W9.6 `stage-2/RUN.md` tells a stranger how to build, run and test stage 2: the stage-2 image and paths, the UI routes, `npm test`, the acceptance suite with its browser prerequisite (Playwright in the harness venv) and the frozen `stage-1/` build it uses, and the supplied checks with `--stage 2`. The builder may bring it up to date from W7 on.

### W10 Wallet screen (builder)

Specification: "Balance and pay", "Activity feed", "Competing clients and uncertain outcomes", "Existing clients after an upgrade", the wallet rows of the stage-2 UI table. Invariants: I39–I45, I47.

- W10.1 Wallet numbers: `wallet-available` (headline), `wallet-balance` and `wallet-held` (absent at 0) with exact text and `data-amount`, including right after a reset with seeded open holds, and for `minor_units` 0, 2 and 3.
- W10.2 Pay form: `15`, `15.00` and `15.5` submit 1500, 1500 and 1550 (and the equivalents for `minor_units` 0 and 3); `abc`, `15.005`, `1e3`, `-1`, `1,5`, an empty field, `0`, more than 1000000000 minor units and a 201-code-point note show `pay-error` and send no request; the visibility select works; insufficient `available` (when `total` would cover it) and an unknown handle show `pay-error`; a refusal re-reads the wallet and feed and keeps every input; a success updates the numbers and the feed without a reload and keeps the values; an unchanged resubmission re-sends the same key and body (one payment, no `pay-error`); changing a field and submitting makes a second payment.
- W10.3 Uncertain outcomes: a response lost after the server committed (route `fetch` then `abort`) shows `pay-uncertain`, not `pay-error`; retrying unchanged sends the same key and body, moves the money once, removes `pay-uncertain` and `pay-error`, and refreshes the numbers and the feed; a request lost before the server saw it (abort without `fetch`) then retried moves money once; a 5xx and a response held past 4 s are uncertain too (at 4 s the page aborts the request and re-enables `pay-submit`).
- W10.4 Request form on `/`: creates a request with the decimal rules; `request-error` for a refusal (unknown handle, own handle) and for invalid input (no request sent); `request-success`; the unchanged-resubmission rule. A response lost after commit shows `request-uncertain`, not `request-error`; the unchanged retry sends the same key and body, creates the request once and clears both elements.
- W10.5 Activity feed: one item per visible payment with `data-visibility`, parties containing both handles, the exact amount and the exact note (present when empty); direct children newest first; `empty-activity` instead of the list; other people's private payments hidden; capture payments shown by the ordinary rule. More than one page of visible payments (for example 205) renders every item once, newest first. A note `<img src=x onerror=alert(1)> &amp;` shows literally and runs nothing (I48).
- W10.6 `wallet-refresh` shows another client's payment and the new numbers, keeps the pay form's values, and latest refresh wins when an earlier `/me` or `/activity` response is delayed past a later one. `wallet-refresh` stays clickable while its own load is pending: with the first refresh's `/me` and `/activity` responses held, a second click starts a new load; once it lands and the held responses are released, the second load's numbers and feed stay on screen.
- W10.7 Upgrade: a signed-in page stays signed in across an export and import of the service's own state (no reload); a payment whose response was lost before the export, retried after the import with the same key and body, shows success and the imported balance with the payment counted once; a pending request in the imported state is payable from `/requests`.

### W11 Requests, split and holds screens (builder)

Specification: "Requests", "Split", the authorization rows of the stage-2 UI table, "Competing clients and uncertain outcomes". Invariants: I39–I46.

- W11.1 `/requests`: both containers present once loaded; items with `data-status` and the exact amount; pay and decline only on pending incoming requests, cancel only on pending outgoing ones; each action updates the item's status without a reload; `empty-requests` only when both lists are empty; `request-error` for a refusal (insufficient `available`, not pending), and the lists re-read so a request cancelled elsewhere loses its stale pay button; `request-uncertain` on a lost response; a retried request payment reuses its key. More than one page of requests (for example 205) renders every item once, newest first, in the right list. After an unknown outcome whose re-read shows the action took effect, the uncertain element gives way to the confirmed state.
- W11.2 `/split`: the preview matches §9 (10.00 among three gives 3.34, 3.33, 3.33; the extra unit follows the order) before anything is posted, and the submitted split's shares equal it; `split-error` for an unknown handle (server 404), an invalid amount and a repeated handle (no request); `split-success`; an unchanged resubmission creates no second split. A response lost after commit shows `split-uncertain`, not `split-error`; the unchanged retry sends the same key and body, creates the split once and clears both elements.
- W11.3 `/authorizations`: the authorize form with the decimal rules, `authorize-error` (including insufficient `available`) and `authorize-success`; the list newest first with `data-status`, the exact amount, `authorization-captured-{id}` only when captured, the exact `expires_at` text; the capture input pre-filled with the remainder; capture and void buttons only where allowed; full capture, partial capture and void update the item and the wallet numbers without a reload; `authorization-error` for refusals (expired, not open, exceeds); `empty-authorizations`; seeded holds show right after a reset with `available` as the headline. The same authorize form on `/` creates a hold and updates the wallet numbers there. A lost authorize response shows `authorize-uncertain`; the unchanged retry creates the hold once; an unchanged resubmission after success creates no second hold. A lost capture response shows `authorization-uncertain`; the unchanged retry captures once; once the re-read shows the capture, the uncertain element gives way to the captured state. More than one page of authorizations (for example 205) renders every item once, newest first.
- W11.4 Every screen passes the I46 checks in each named state (loading, empty, loaded, success, refused, uncertain) at 375×812 and 1280×800, and the no-horizontal-scroll check at 1024×768 too.

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
- **D43 Unknown outcomes.** Only a 4xx with the envelope is a confirmed refusal; everything else that is not a 2xx is uncertain ("Unknown outcomes are not confirmed rejections"). The client limit is 4 s: far above the service's real latency, and below the 5 s default of Playwright's `expect()`, which the supplied checks use, so a hung write shows its uncertain element before such a check gives up. At the limit the page aborts the request, ignores any late response and re-enables the button. (Critic plan review 4.)
- **D44 Amount grammar.** Digits with an optional fraction of 1 to `minor_units` digits, nothing else (no sign, exponent, grouping or comma decimal), parsed without floating point, 1 to 1000000000 minor units. Stricter than a locale parser, and exactly the specification's examples (`15`, `15.00`, `15.5` valid; `15.005` refused).
- **D45 Handle inputs.** Trim and strip one leading `@`, because people write handles that way; the server still decides whether the handle exists. Split lists drop empty entries, so a trailing comma is harmless.
- **D46 Authorize form on `/` and on `/authorizations`.** The specification names a route only for the list, while the authorize rows sit with the wallet rows. The same form renders on both screens (one per page), so either reading works; `/authorizations` repeats the wallet summary so a new hold's effect shows on the same page. (Critic recommendation A.)
- **D47 Capture from the UI is a final capture by default.** It sends the amount from `authorization-capture-amount-{id}` and no `final`, matching the API default; extended capture mode is optional in the UI.
- **D48 Seeded authorizations.** Fields and defaults as section 3.11. `expires_at` is returned exactly as seeded, since the UI must show "the RFC 3339 `expires_at`" and the checks may compare it with the seed; it is compared as an instant. `captured_amount` defaults to the full amount for a seeded `captured` hold, the natural meaning of "captured". An open seed must leave something to capture. The TTL is capped at 10^10 s (about 317 years) so `expires_at` stays a four-digit-year timestamp.
- **D49 Service clock.** `now` = the later of the wall clock and the last issued timestamp, taken once per operation, so expiry agrees with the timestamps the service issues (also after an import whose timestamps are ahead of the wall clock). A reset re-bases the clock to its own time, so a fixture's expiry times are judged against the reset, as the specification states ("at least an hour from reset time").
- **D50 Capture precedence and codes.** Captured or voided: `authorization_not_open`, whatever the clock says, because the clock only expires open holds ("A second capture after a final capture is 409 `authorization_not_open`"; "Voiding an already-voided authorisation is 200"). Otherwise, once the deadline has passed, `authorization_expired`, for an open hold and for a seeded `expired` one alike: the specification's row is a time condition ("`expires_at` is at or before now"). A seeded `expired` hold whose deadline is still ahead meets only the "not open" row: `authorization_not_open`. State before amount: a closed or expired authorization answers 409 whatever the amount. An amount above the remainder is `capture_exceeds_authorization` even above 1000000000, the more specific code. `final` of another JSON type is 400 under §5's wrong-type rule. (Critic plan review 1.)
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
- **D61 Body equality is unchanged.** "New fields do not change idempotency body equality" is read as: the equality rule stays §7's JSON-value equality, so a replay must send the identical body; `{"amount": 700}` and `{"amount": 700, "final": true}` are different bodies, exactly as the specification says of `{}` and `{"amount": 2000}`. Replays return the stored original response, whatever fields later responses gained (D54).
- **D62 Import accepts whatever reset can build.** `payment_id`, `payment_ids` and a payment's `authorization_id` are display-only links: the service never follows them to move money or decide permissions, so neither reset nor import checks that they point anywhere, only their types. Otherwise a fixture-built state could export but not import back, breaking I26 and I37. (Builder question on W8.)
- **D63 Refresh buttons stay enabled.** "Latest refresh wins ... including when responses arrive out of order" needs two refreshes in flight at once, so `wallet-refresh` and `load-retry` are never disabled; only a write's own button may be disabled while that write is in flight. (Verifier question Q1.)
- **D64 Lists read every page, starting bare.** "One per visible payment" and "One per request" mean every item, not the first page of 50, so the page follows `has_more`. The first read uses the bare path because `page.route` globs such as `**/activity` do not match a URL with a query string (checked against Playwright 1.63's matcher), and a check that delays or drops the feed read must still catch it. `/requests` reads one list and splits it, for the same reason. (Critic plan review 3.)
- **D65 Session-ended rule only for authenticated calls.** Login and signup answer 401 or other refusals as part of their own flow; those show `auth-error` (supplied `test_bad_login_shows_auth_error`). Only a 401 to a call that sent the stored token ends the session. (Critic plan review 2.)

## 6. Specification trace

Each normative line of stage-2.md, condensed (S1-S130), with the acceptance tests that exercise it (file prefix `test_` and test prefix `test_` omitted). Stage 1's 97 lines (stage-1/PLAN.md section 6) are carried by the stage-1 regression tests in stage-2/acceptance, brought to the stage-2 contract. A row without a test when its item's tests land is a gap and becomes a criterion at once. Presentation lines (S4, S6, S7, S9) are also judged from the screenshots by the critic and the planner.

| N | Spec | Normative line (condensed) | Plan | Tests | Status |
|---|---|---|---|---|---|
| S1 | routes | `/`, `/requests`, `/split`, `/signup`, `/login` reachable by URL; other screens reachable through the UI | W9.1 W9.4 | w9_routes: page_routes_serve_the_shell_whatever_the_accept; w9_session: navigation_links_move_between_screens_and_keep_the_session | suite ca09237 written; not yet run on a product |
| S2 | routes | `/requests` shared: UI for `Accept: text/html`, JSON otherwise | W9.1 I49 | w9_routes: shared_paths_serve_the_shell_when_accept_lists_text_html, shared_paths_answer_json_otherwise, post_on_shared_paths_is_always_the_api | suite ca09237 written; not yet run on a product |
| S3 | testids | the listed `data-testid` attributes are exposed; extra elements allowed | I45 | every browser test (ui.py finds elements by data-testid only) | suite ca09237 written; not yet run on a product |
| S4 | direction | coherent, presentation-ready consumer finance product; calm, trustworthy | 3.15 | w11_states (screenshots); critic and planner screenshot review | suite ca09237 written; not yet run on a product |
| S5 | direction | available is the clearest money value once holds exist; total and held visibly secondary | W10.1 W11.3 3.15 | w10_wallet: available_is_the_headline_number | suite ca09237 written; not yet run on a product |
| S6 | direction | payments, requests, splits, authorizations easy to scan; status, direction, privacy, money movement understandable | 3.15 W10.5 W11 | w10_wallet: feed_items_carry_their_parts; w11_states screenshots; review | suite ca09237 written; not yet run on a product |
| S7 | direction | consistent visual system; primary actions easy to identify | 3.15 | w11_states: loaded_screen_layout_and_keyboard_focus; screenshots; review | suite ca09237 written; not yet run on a product |
| S8 | direction | available, held, pending, loading, successful, refused, uncertain states visually distinct | W11.4 | w11_states: wallet_states, requests_states, split_states, authorizations_states, loading_and_load_error_states | suite ca09237 written; not yet run on a product |
| S9 | direction | people, amounts, timestamps formatted for people; technical ids only where they help | 3.15 | w11_authorizations_ui: expires_text_is_the_api_string; screenshots; review | suite ca09237 written; not yet run on a product |
| S10 | direction | required flows usable at 375 px and desktop widths without horizontal page scrolling | I46 W9.4 W11.4 | w11_states: loaded_screen_layout_and_keyboard_focus and every *_states test (I46 at 375 and 1280); w9_session: signed_out_screens_pass_the_layout_checks | suite ca09237 written; not yet run on a product |
| S11 | direction | visible input labels, apparent keyboard focus, sufficient contrast for text and controls | I46 | w11_states: loaded_screen_layout_and_keyboard_focus; w9_session: signed_out_screens_pass_the_layout_checks | suite ca09237 written; not yet run on a product |
| S12 | direction | considered empty, loading and error states; consistent navigation across required routes | W9.4 W11.4 | w11_states: loading_and_load_error_states, wallet_states, requests_states, authorizations_states; w9_session: navigation_links_move_between_screens_and_keep_the_session, not_found_screen_keeps_the_navigation; w10_uncertain: a_load_held_past_four_seconds_ends_in_load_error | suite ca09237 written; not yet run on a product |
| S13 | signup | `signup-email`, `signup-password`, `signup-display-name`, `signup-submit` | W9.2 | w9_session: signup_shows_the_display_name_and_the_exact_derived_handle | suite ca09237 written; not yet run on a product |
| S14 | login | `login-email`, `login-password`, `login-submit` | W9.3 | w9_session: login_shows_the_signed_in_header_on_every_route, bad_login_shows_auth_error, forms_submit_with_enter | suite ca09237 written; not yet run on a product |
| S15 | auth | `auth-error` present only when there is one | W9.2 W9.3 | w9_session: refused_signup_shows_auth_error_with_a_human_message, bad_login_shows_auth_error, a_401_clears_the_session_and_shows_login_without_auth_error | suite ca09237 written; not yet run on a product |
| S16 | auth | `current-user` visible on every screen when signed in; contains the display name | W9.3 | w9_session: login_shows_the_signed_in_header_on_every_route, login_and_signup_render_their_forms_while_signed_in | suite ca09237 written; not yet run on a product |
| S17 | auth | `current-handle` exactly the handle, no `@`, no words | W9.2 | w9_session: signup_shows_the_display_name_and_the_exact_derived_handle | suite ca09237 written; not yet run on a product |
| S18 | auth | `logout-button` | W9.3 | w9_session: logout_clears_the_session | suite ca09237 written; not yet run on a product |
| S19 | pay | `wallet-balance` exactly the formatted amount with `data-amount` | W10.1 | w10_wallet: wallet_numbers_with_no_holds, wallet_formats_every_currency_exactly | suite ca09237 written; not yet run on a product |
| S20 | pay | `pay-handle`, `pay-amount` (decimal as typed), `pay-note` inputs | W10.2 | w10_wallet: typed_decimal_becomes_minor_units, amount_inputs_are_text_with_decimal_keyboard, handle_is_trimmed_and_one_at_sign_removed, note_limits_count_code_points | suite ca09237 written; not yet run on a product |
| S21 | pay | `pay-visibility` selects `public`/`private` (option values) | W10.2 | w10_wallet: visibility_select_and_default, changing_visibility_makes_a_new_payment | suite ca09237 written; not yet run on a product |
| S22 | pay | `pay-submit`; `pay-error` when refused, including insufficient funds | W10.2 | w10_wallet: insufficient_available_shows_pay_error_when_total_would_cover_it, unknown_or_own_handle_shows_pay_error | suite ca09237 written; not yet run on a product |
| S23 | pay | request form `request-handle/amount/note/submit`; `request-error` when refused | W10.4 | w10_wallet: request_form_creates_a_request_with_the_decimal_rules, request_form_refusals_show_request_error | suite ca09237 written; not yet run on a product |
| S24 | pay | values kept after success; unchanged resubmission sends no payment: balance falls once, one feed payment, no `pay-error` | W10.2 | w10_wallet: unchanged_resubmission_replays_with_the_same_key_and_body, success_updates_numbers_and_feed_without_a_reload_and_keeps_values | suite ca09237 written; not yet run on a product |
| S25 | pay | changing a field makes the next submission a new payment; retries follow §7 | W10.2 | w10_wallet: changing_any_field_makes_a_new_payment, changing_visibility_makes_a_new_payment | suite ca09237 written; not yet run on a product |
| S26 | pay | formatted amount: `minor_units` places, space, code; none for 0; no sign | W10.1 I39 | w10_wallet: wallet_formats_every_currency_exactly | suite ca09237 written; not yet run on a product |
| S27 | pay | decimal input submits minor units (`15.00`, `15` -> 1500; `15.5` -> 1550) | W10.2 | w10_wallet: typed_decimal_becomes_minor_units, decimal_rules_follow_minor_units | suite ca09237 written; not yet run on a product |
| S28 | pay | nonnumeric or too many places shows the form error without a request; `15.005` refused, not rounded | W10.2 | w10_wallet: invalid_amount_shows_pay_error_and_sends_nothing, more_places_than_minor_units_is_refused | suite ca09237 written; not yet run on a product |
| S29 | feed | `activity-list` children newest first in the DOM | W10.5 | w10_wallet: feed_items_are_direct_children_in_api_order; w10_wallet: more_than_one_page_of_payments_renders_every_item_once | suite ca09237 written; not yet run on a product |
| S30 | feed | one `activity-item-{id}` per visible payment with `data-visibility` | W10.5 | w10_wallet: feed_items_carry_their_parts; w10_wallet: more_than_one_page_of_payments_renders_every_item_once | suite ca09237 written; not yet run on a product |
| S31 | feed | `activity-parties-{id}` contains both handles | W10.5 | w10_wallet: feed_items_carry_their_parts | suite ca09237 written; not yet run on a product |
| S32 | feed | `activity-amount-{id}` exactly the formatted amount | W10.5 | w10_wallet: feed_items_carry_their_parts | suite ca09237 written; not yet run on a product |
| S33 | feed | `activity-note-{id}` exactly the note, present when empty | W10.5 | w10_wallet: feed_items_carry_their_parts | suite ca09237 written; not yet run on a product |
| S34 | feed | `empty-activity` instead of the list when nothing is visible | W10.5 | w10_wallet: empty_activity_replaces_the_list | suite ca09237 written; not yet run on a product |
| S35 | feed | equal timestamps may appear in either order | W10.5 | w10_wallet: feed_items_are_direct_children_in_api_order | suite ca09237 written; not yet run on a product |
| S36 | requests | `incoming-list`, `outgoing-list` containers | W11.1 | w11_requests_ui: lists_hold_every_status_with_the_right_actions, empty_requests_only_when_both_lists_are_empty | suite ca09237 written; not yet run on a product |
| S37 | requests | `request-item-{id}` per request with `data-status` | W11.1 | w11_requests_ui: lists_hold_every_status_with_the_right_actions; w11_requests_ui: more_than_one_page_of_requests_renders_every_item_once | suite ca09237 written; not yet run on a product |
| S38 | requests | `request-amount-{id}` exactly the formatted amount | W11.1 | w11_requests_ui: lists_hold_every_status_with_the_right_actions | suite ca09237 written; not yet run on a product |
| S39 | requests | `request-pay-{id}` only on a pending incoming request | W11.1 | w11_requests_ui: lists_hold_every_status_with_the_right_actions | suite ca09237 written; not yet run on a product |
| S40 | requests | `request-decline-{id}` only on a pending incoming request | W11.1 | w11_requests_ui: lists_hold_every_status_with_the_right_actions | suite ca09237 written; not yet run on a product |
| S41 | requests | `request-cancel-{id}` only on a pending outgoing request | W11.1 | w11_requests_ui: lists_hold_every_status_with_the_right_actions | suite ca09237 written; not yet run on a product |
| S42 | requests | `request-error` when pay, decline or cancel is refused | W11.1 | w11_requests_ui: paying_without_available_funds_shows_request_error, request_cancelled_elsewhere_loses_its_stale_pay_button; w11_requests_ui: pay_lost_after_commit_shows_the_confirmed_state, decline_lost_after_commit_shows_the_confirmed_state | suite ca09237 written; not yet run on a product |
| S43 | requests | `empty-requests` when both lists are empty | W11.1 | w11_requests_ui: empty_requests_only_when_both_lists_are_empty | suite ca09237 written; not yet run on a product |
| S44 | split | `split-amount` decimal, same rule as `pay-amount` | W11.2 | w11_split_ui: invalid_split_shows_split_error_and_sends_nothing, preview_in_other_currencies | suite ca09237 written; not yet run on a product |
| S45 | split | `split-handles` comma-separated handles, in order | W11.2 | w11_split_ui: preview_follows_the_section_9_rule_before_anything_is_posted | suite ca09237 written; not yet run on a product |
| S46 | split | `split-note`, `split-submit` | W11.2 | w11_split_ui: the_submitted_split_matches_the_preview | suite ca09237 written; not yet run on a product |
| S47 | split | `split-preview` before submitting, one `split-share-{handle}` per participant | W11.2 | w11_split_ui: preview_follows_the_section_9_rule_before_anything_is_posted, two_hundred_handles_preview | suite ca09237 written; not yet run on a product |
| S48 | split | `split-share-{handle}` exactly the formatted share | W11.2 | w11_split_ui: preview_follows_the_section_9_rule_before_anything_is_posted, preview_in_other_currencies | suite ca09237 written; not yet run on a product |
| S49 | split | `split-error` when the split is refused | W11.2 | w11_split_ui: unknown_handle_is_refused_by_the_server, invalid_split_shows_split_error_and_sends_nothing | suite ca09237 written; not yet run on a product |
| S50 | split | preview = server §9 shares before anything is posted; preview and submitted split identical | W11.2 | w11_split_ui: preview_follows_the_section_9_rule_before_anything_is_posted, the_submitted_split_matches_the_preview | suite ca09237 written; not yet run on a product |
| S51 | refresh | after any successful action, balance, feed and request lists on the page show the new state without reload | I43 W10.2 W11.1 W11.3 | w10_wallet: success_updates_numbers_and_feed_without_a_reload_and_keeps_values; w11_requests_ui: pay_updates_the_item_without_a_reload_and_sends_an_empty_body, decline_and_cancel_update_the_items; w11_authorizations_ui: authorize_form_creates_a_hold_and_updates_the_wallet, full_capture_updates_the_item_and_the_wallet, void_updates_the_item_and_the_wallet | suite ca09237 written; not yet run on a product |
| S52 | refresh | navigation waits for the write to succeed before refreshing data | I43 | w10_wallet: data_is_reread_only_after_the_write_answered | suite ca09237 written; not yet run on a product |
| S53 | refresh | no live-update requirement; refresh after own action or explicit refresh | — (no check needed) | none needed (no requirement to check) | suite ca09237 written; not yet run on a product |
| S54 | competing | `wallet-refresh` refreshes balance and feed without clearing the pay form | W10.6 | w10_wallet: refresh_shows_another_clients_payment_and_keeps_the_form | suite ca09237 written; not yet run on a product |
| S55 | competing | latest refresh wins, including out-of-order responses | W10.6 | w10_wallet: latest_refresh_wins_when_the_earlier_one_answers_last, a_write_reload_beats_a_slow_earlier_refresh | suite ca09237 written; not yet run on a product |
| S56 | competing | refused payment shows `pay-error`, refreshes balance/feed, preserves all pay inputs | W10.2 | w10_wallet: refusal_rereads_the_wallet_and_feed_and_keeps_every_input | suite ca09237 written; not yet run on a product |
| S57 | competing | request cancelled elsewhere: `request-error` on refused pay, list refresh removes the stale pay button | W11.1 | w11_requests_ui: request_cancelled_elsewhere_loses_its_stale_pay_button | suite ca09237 written; not yet run on a product |
| S58 | uncertain | lost payment response (also after commit) shows nonempty `pay-uncertain`, not `pay-error` | W10.3 | w10_uncertain: lost_payment_shows_pay_uncertain_and_an_unchanged_retry_pays_once, response_held_past_four_seconds_is_uncertain_and_the_late_answer_is_ignored | suite ca09237 written; not yet run on a product |
| S59 | uncertain | unchanged form stays retryable with the same key and body | W10.3 | w10_uncertain: lost_payment_shows_pay_uncertain_and_an_unchanged_retry_pays_once | suite ca09237 written; not yet run on a product |
| S60 | uncertain | successful retry removes error and uncertainty, refreshes balance and feed, moves money exactly once | W10.3 | w10_uncertain: lost_payment_shows_pay_uncertain_and_an_unchanged_retry_pays_once, uncertain_then_refused_retry_shows_pay_error_and_keeps_the_form | suite ca09237 written; not yet run on a product |
| S61 | uncertain | no polling or reload recovery required; same refresh rules for available and held | W10.6 | w10_wallet: refresh_shows_new_holds, latest_refresh_wins_when_the_earlier_one_answers_last | suite ca09237 written; not yet run on a product |
| S62 | upgrade | stage 2 accepts an export from the team's stage-1 service | W8.3 | w8_upgrade: stage_1_export_imports_and_reads_back_through_stage_2, logins_tokens_and_permissions_survive, stage_1_replays_return_the_stored_bodies_unchanged | suite ca09237 written; not yet run on a product |
| S63 | upgrade | a browser signed in before the export/import stays signed in | W10.7 | w10_uncertain: signed_in_page_survives_an_export_and_import_without_a_reload | suite ca09237 written; not yet run on a product |
| S64 | upgrade | existing pending requests remain payable through the request screen | W10.7 | w10_uncertain: pending_request_from_a_stage_1_export_is_payable_from_the_request_screen | suite ca09237 written; not yet run on a product |
| S65 | upgrade | payment lost before export retryable after import with same body and key; UI recovers the original and refreshes the imported balance | W10.7 | w10_uncertain: payment_lost_before_the_export_is_recovered_after_the_import; w8_upgrade: a_payment_lost_before_the_export_is_recovered_after_the_upgrade | suite ca09237 written; not yet run on a product |
| S66 | upgrade | import between browser requests; no reload or new screen; form and pending retry identity survive | W10.7 | w10_uncertain: signed_in_page_survives_an_export_and_import_without_a_reload, payment_lost_before_the_export_is_recovered_after_the_import | suite ca09237 written; not yet run on a product |
| S67 | holds | authorise now, capture later (full or less); hold reserves without moving; final capture releases remainder; nonfinal keeps it; open hold expires on its own | W7.3 W7.6 | w7_capture: default_capture_takes_the_whole_remainder, smaller_final_capture_releases_the_rest_in_the_same_step, nonfinal_captures_keep_the_rest_held_until_the_last; w7_expiry: open_hold_expires_with_no_request_at_the_deadline | suite ca09237 written; not yet run on a product |
| S68 | holds | (1) sum of totals = seeded total; holds move no money; payments, settlements, captures transfer | I1 | teardown I1 after every test (support.py); w7_holds: a_hold_moves_no_money_and_is_not_a_feed_item; w7_concurrency: mixed_burst_of_holds_captures_voids_and_payments_conserves | suite ca09237 written; not yet run on a product |
| S69 | holds | (2) available = total - held never negative; held funds cannot fund payments, authorizations, settlement net debits; captures may spend reserved money | I2 I31 W7.7 | teardown I2 and I30; w7_funds: payment_is_refused_when_total_covers_it_but_available_does_not, authorizations_are_judged_on_available, settlement_net_debit_is_judged_on_available, capture_may_spend_held_money_but_not_other_holds | suite ca09237 written; not yet run on a product |
| S70 | holds | (3) cumulative captures <= authorized; idempotent capture moves money once; closed hold not capturable | I32 W7.3 | w7_capture: default_capture_takes_the_whole_remainder, voided_authorization_is_not_open; w7_concurrency: twenty_nonfinal_captures_never_exceed_the_authorized_amount, fifty_identical_captures_with_one_key_move_money_once; w7_expiry: the_clock_expires_only_open_authorizations | suite ca09237 written; not yet run on a product |
| S71 | holds | `GET /me` keeps `balance` = `total`; adds `available`, `held`; with no holds they agree, held 0, behaviour unchanged | W7.1 | w7_holds: me_has_exactly_the_stage_2_fields_with_no_holds, a_hold_reduces_available_not_total; w7_funds: with_no_holds_stage_1_results_are_unchanged | suite ca09237 written; not yet run on a product |
| S72 | holds | `POST /payments` stays immediate: no intermediate hold, no capture | W7.7 | w7_funds: payment_with_no_holds_leaves_no_hold | suite ca09237 written; not yet run on a product |
| S73 | holds | every stage-1 `insufficient_funds` (payments, request pay, settlements) judged on `available` | W7.7 | w7_funds: payment_is_refused_when_total_covers_it_but_available_does_not, request_payment_is_judged_on_available, settlement_net_debit_is_judged_on_available, settlement_wallet_that_only_receives_is_never_refused | suite ca09237 written; not yet run on a product |
| S74 | holds | paying a request stays immediate; authorizing a request out of scope | W7.7 | w7_funds: request_payment_is_judged_on_available | suite ca09237 written; not yet run on a product |
| S75 | holds | `POST /splits` unchanged | regression | stage-1 regression: w3_splits (all) | suite ca09237 written; not yet run on a product |
| S76 | holds | seven idempotent write paths; replay rules apply independently | W7.2 W7.3 I15-I19 | w2_idempotency (seven-path matrix); w7_holds: authentication_and_key_rules; w7_capture: authentication_and_key, capture_keys_are_scoped_by_path; w7_capture: failed_captures_claim_no_key | suite ca09237 written; not yet run on a product |
| S77 | model | fixture gains `authorization_ttl_seconds` and `authorizations` | W7.8 | w7_fixture: base_fixture_is_valid, seeded_authorization_representation_and_holds | suite ca09237 written; not yet run on a product |
| S78 | model | TTL applies to every API-created authorization; default 600; if supplied a positive integer | W7.8 | w7_holds: default_ttl_is_600_seconds, fixture_ttl_sets_expires_at; w7_fixture: invalid_stage_2_fixture_is_422_and_changes_nothing | suite ca09237 written; not yet run on a product |
| S79 | model | seeded authorizations carry their own absolute `expires_at` | W7.8 | w7_fixture: seeded_expires_at_comes_back_exactly_as_written; w7_expiry: seeded_expires_at_is_compared_as_an_instant | suite ca09237 written; not yet run on a product |
| S80 | model | seeded `balance` is `total`; `available` derived, never seeded | W7.8 | w7_fixture: fixture_available_and_held_fields_are_ignored | suite ca09237 written; not yet run on a product |
| S81 | model | seeded unexpired open holds above the balance: reset 422, nothing changes | W7.8 | w7_fixture: invalid_stage_2_fixture_is_422_and_changes_nothing, unexpired_open_remainders_equal_to_the_balance_are_valid | suite ca09237 written; not yet run on a product |
| S82 | model | seeded status open, captured, voided or expired; only open holds anything | W7.8 | w7_fixture: captured_amount_default_and_what_each_status_holds, closed_seeds_may_exceed_the_balance | suite ca09237 written; not yet run on a product |
| S83 | model | an earlier fixture may omit `authorizations` | W7.8 | w7_fixture: defaults_and_unknown_fields; stage-1 regression fixtures | suite ca09237 written; not yet run on a product |
| S84 | expiry | `expires_at` at or before now: expired, holds no funds | W7.6 | w7_expiry: open_hold_expires_with_no_request_at_the_deadline, ttl_of_one_second | suite ca09237 written; not yet run on a product |
| S85 | expiry | reads and writes reflect expiry with no request at the deadline: list shows expired, `/me` releases the remainder | W7.6 | w7_expiry: open_hold_expires_with_no_request_at_the_deadline, released_money_is_spendable_after_expiry | suite ca09237 written; not yet run on a product |
| S86 | expiry | seeded expiry at least an hour from reset; new ones may be shorter | W7.6 W7.8 | w7_expiry: seeded_open_hold_an_hour_in_the_past_reads_expired_at_once | suite ca09237 written; not yet run on a product |
| S87 | me | `GET /me` shape; `balance` = `total`; `held` = open holds; `available` = total - held, never negative | W7.1 I30 | w7_holds: me_has_exactly_the_stage_2_fields_with_no_holds, held_is_the_sum_of_open_outgoing_holds; teardown I30 | suite ca09237 written; not yet run on a product |
| S88 | auth-create | `POST /authorizations`: key required; caller is the payer | W7.2 | w7_holds: authentication_and_key_rules, authorization_201_has_exactly_the_authorization_fields | suite ca09237 written; not yet run on a product |
| S89 | auth-create | `note`, `visibility` optional with the payment defaults | W7.2 | w7_holds: note_and_visibility_default_like_payments, note_round_trips_verbatim | suite ca09237 written; not yet run on a product |
| S90 | auth-create | 201 shape; `expires_at` = `created_at` + TTL | W7.2 | w7_holds: authorization_201_has_exactly_the_authorization_fields, default_ttl_is_600_seconds, fixture_ttl_sets_expires_at | suite ca09237 written; not yet run on a product |
| S91 | auth-create | errors: 409 insufficient (available), 422 amount, 422 `self_payment`, 422 note/visibility, 404 handle | W7.2 | w7_holds: hold_of_exactly_available_succeeds_and_one_more_is_409, invalid_amount_is_422, own_handle_is_self_payment, invalid_note_is_422, invalid_visibility_is_422, unknown_handle_is_404, precedence | suite ca09237 written; not yet run on a product |
| S92 | auth-create | an open authorization is never a feed item | W7.2 | w7_holds: a_hold_moves_no_money_and_is_not_a_feed_item | suite ca09237 written; not yet run on a product |
| S93 | capture | key required; only the receiver captures | W7.3 | w7_capture: only_the_receiver_captures, authentication_and_key | suite ca09237 written; not yet run on a product |
| S94 | capture | `amount` optional, default remainder; replay needs the identical body; `{}` vs `{"amount": 2000}` is 409 reuse | W7.3 | w7_capture: default_capture_takes_the_whole_remainder, empty_body_and_explicit_amount_are_different_bodies | suite ca09237 written; not yet run on a product |
| S95 | capture | 201 payment shape, `authorization_id` set, `request_id` null, captured amount, copied note and visibility, feed by ordinary rule; other payments `authorization_id: null` | W7.3 I36 | w7_capture: default_capture_takes_the_whole_remainder, capture_payments_follow_the_feed_rule; regression payment shapes (authorization_id null) | suite ca09237 written; not yet run on a product |
| S96 | capture | default: becomes captured with `captured_amount`, `payment_id`; remainder released immediately | W7.3 | w7_capture: default_capture_takes_the_whole_remainder, smaller_final_capture_releases_the_rest_in_the_same_step | suite ca09237 written; not yet run on a product |
| S97 | capture | default one final capture; a second is 409 `authorization_not_open` | W7.3 | w7_capture: default_capture_takes_the_whole_remainder (second capture 409 authorization_not_open) | suite ca09237 written; not yet run on a product |
| S98 | capture | `final: false` keeps the remainder held, status open, further captures up to it; capturing it all closes it | W7.3 | w7_capture: nonfinal_captures_keep_the_rest_held_until_the_last, capturing_the_entire_remainder_with_final_false_closes_it, default_amount_with_final_false_takes_the_remainder_and_closes | suite ca09237 written; not yet run on a product |
| S99 | capture | `final` boolean, default true | W7.3 | w7_capture: explicit_final_true_is_the_default, non_boolean_final_is_400 | suite ca09237 written; not yet run on a product |
| S100 | capture | exceeds compares with remaining; default = remainder; `captured_amount` cumulative; `payment_id` latest; `payment_ids` all in order | W7.3 | w7_capture: amount_above_the_remainder_is_capture_exceeds, nonfinal_captures_keep_the_rest_held_until_the_last | suite ca09237 written; not yet run on a product |
| S101 | capture | every authorization response has `remaining_amount` (0 when closed) | W7.2 W7.3 W7.4 W7.5 | w7_holds: authorization_201_has_exactly_the_authorization_fields; w7_list: the_list_shows_the_same_representation_as_create_and_void | suite ca09237 written; not yet run on a product |
| S102 | capture | void and expiry close a partially captured hold, release only the remainder, keep captures | W7.4 W7.6 | w7_void: void_keeps_partial_captures; w7_expiry: partially_captured_hold_expires_keeping_its_captures | suite ca09237 written; not yet run on a product |
| S103 | capture | new fields do not change idempotency body equality | W7.3 D61 | w7_capture: final_true_and_absent_final_are_different_bodies, empty_body_and_explicit_amount_are_different_bodies | suite ca09237 written; not yet run on a product |
| S104 | capture | errors: 409 not open, 409 expired, 422 exceeds, 422 validation, 403, 404 | W7.3 | w7_capture: voided_authorization_is_not_open, amount_above_the_remainder_is_capture_exceeds, invalid_capture_amount_is_422, only_the_receiver_captures, unknown_authorization_is_404, precedence; w7_expiry: open_hold_expires_with_no_request_at_the_deadline; w7_expiry: the_clock_expires_only_open_authorizations, seeded_expired_status_with_a_future_deadline_is_not_open, seeded_expired_status_with_a_past_deadline_is_expired | suite ca09237 written; not yet run on a product |
| S105 | void | only the payer; no idempotency key | W7.4 | w7_void: only_the_payer_voids, void_needs_no_key_and_never_reads_the_body | suite ca09237 written; not yet run on a product |
| S106 | void | 200 voided and released; voided again 200 current; captured or expired 409 `authorization_not_open` | W7.4 | w7_void: payer_voids_an_open_hold_and_the_remainder_is_released, voiding_again_is_200_with_the_current_state, captured_authorization_is_not_open, seeded_closed_authorizations_cannot_be_voided; w7_expiry: the_clock_expires_only_open_authorizations | suite ca09237 written; not yet run on a product |
| S107 | void | capture and void 403 for any non-permitted caller, including non-parties | W7.3 W7.4 | w7_capture: only_the_receiver_captures; w7_void: only_the_payer_voids, caller_check_comes_before_the_state | suite ca09237 written; not yet run on a product |
| S108 | list | `GET /authorizations` only involving the caller | W7.5 I35 | w7_list: only_the_callers_authorizations | suite ca09237 written; not yet run on a product |
| S109 | list | newest first by `created_at` | W7.5 | w7_list: list_is_newest_first_and_every_item_has_the_shape, seeded_authorizations_take_fixture_order_as_creation_order, created_after_seeded_comes_first | suite ca09237 written; not yet run on a product |
| S110 | list | `direction` outgoing (payer), incoming (receiver), absent both | W7.5 | w7_list: direction_filter, direction_and_status_together | suite ca09237 written; not yet run on a product |
| S111 | list | `status` one of four or absent; clock-expired matches expired, never open | W7.5 W7.6 | w7_list: status_filter, direction_and_status_together; w7_expiry: open_hold_expires_with_no_request_at_the_deadline; w7_expiry: the_clock_expires_only_open_authorizations | suite ca09237 written; not yet run on a product |
| S112 | list | `limit`, `offset`, `has_more` as `GET /requests` | W7.5 | w7_list: paging, default_limit_is_50, invalid_query_values_are_422 | suite ca09237 written; not yet run on a product |
| S113 | ui-auth | route `/authorizations`, HTML for `Accept: text/html`, JSON otherwise | W9.1 | w9_routes: shared_paths_serve_the_shell_when_accept_lists_text_html, shared_paths_answer_json_otherwise; w7_list: json_unless_accept_lists_text_html | suite ca09237 written; not yet run on a product |
| S114 | ui-auth | `wallet-balance` formatted total with `data-amount` | W10.1 | w10_wallet: wallet_numbers_with_no_holds, seeded_open_holds_show_right_after_reset | suite ca09237 written; not yet run on a product |
| S115 | ui-auth | `wallet-available` formatted available with `data-amount`; the headline number | W10.1 | w10_wallet: available_is_the_headline_number, seeded_open_holds_show_right_after_reset | suite ca09237 written; not yet run on a product |
| S116 | ui-auth | `wallet-held` formatted held with `data-amount`; absent when held is 0 | W10.1 | w10_wallet: wallet_numbers_with_no_holds, seeded_open_holds_show_right_after_reset | suite ca09237 written; not yet run on a product |
| S117 | ui-auth | authorize form `authorize-handle/amount/note/visibility/submit`, pay-form input rules | W11.3 | w11_authorizations_ui: authorize_form_creates_a_hold_and_updates_the_wallet, bhd_amounts; w11_authorizations_ui: the_authorize_form_on_the_wallet_screen | suite ca09237 written; not yet run on a product |
| S118 | ui-auth | `authorize-error` when refused, including insufficient available funds | W11.3 | w11_authorizations_ui: authorize_refusals_show_authorize_error | suite ca09237 written; not yet run on a product |
| S119 | ui-auth | `authorization-list` container, children newest first | W11.3 | w11_authorizations_ui: seeded_holds_show_right_after_reset; w11_authorizations_ui: more_than_one_page_of_authorizations_renders_every_item_once | suite ca09237 written; not yet run on a product |
| S120 | ui-auth | `authorization-item-{id}` with `data-status` | W11.3 | w11_authorizations_ui: seeded_holds_show_right_after_reset; w11_authorizations_ui: more_than_one_page_of_authorizations_renders_every_item_once | suite ca09237 written; not yet run on a product |
| S121 | ui-auth | `authorization-amount-{id}` exactly the formatted authorized amount | W11.3 | w11_authorizations_ui: seeded_holds_show_right_after_reset | suite ca09237 written; not yet run on a product |
| S122 | ui-auth | `authorization-captured-{id}` only when captured | W11.3 | w11_authorizations_ui: full_capture_updates_the_item_and_the_wallet, partial_capture_is_final_and_releases_the_rest | suite ca09237 written; not yet run on a product |
| S123 | ui-auth | `authorization-expires-{id}` text is the RFC 3339 `expires_at` | W11.3 | w11_authorizations_ui: expires_text_is_the_api_string | suite ca09237 written; not yet run on a product |
| S124 | ui-auth | `authorization-capture-amount-{id}` decimal input pre-filled with the remainder, only incoming open | W11.3 | w11_authorizations_ui: capture_input_is_prefilled_with_the_remainder, capture_input_in_jpy_has_no_decimal_point | suite ca09237 written; not yet run on a product |
| S125 | ui-auth | `authorization-capture-{id}` only incoming open | W11.3 | w11_authorizations_ui: seeded_holds_show_right_after_reset | suite ca09237 written; not yet run on a product |
| S126 | ui-auth | `authorization-void-{id}` only outgoing open | W11.3 | w11_authorizations_ui: seeded_holds_show_right_after_reset | suite ca09237 written; not yet run on a product |
| S127 | ui-auth | `authorization-error` when capture or void is refused | W11.3 | w11_authorizations_ui: capture_refused_because_voided_elsewhere, capture_above_the_remainder_is_refused, invalid_capture_input_shows_authorization_error_and_sends_nothing, capture_of_an_expired_hold_is_refused; w11_authorizations_ui: capture_lost_after_commit_shows_the_confirmed_state, void_lost_after_commit_shows_the_confirmed_state | suite ca09237 written; not yet run on a product |
| S128 | ui-auth | `empty-authorizations` when the list is empty | W11.3 | w11_authorizations_ui: empty_authorizations_keeps_the_container | suite ca09237 written; not yet run on a product |
| S129 | ui-auth | UI reflects seeded and new holds; available is the spending balance, also right after a reset with open holds | W10.1 W11.3 | w10_wallet: seeded_open_holds_show_right_after_reset; w11_authorizations_ui: seeded_holds_show_right_after_reset | suite ca09237 written; not yet run on a product |
| S130 | concurrency | concurrent operations equal some one-at-a-time order; requirements hold at every read | W7.9 I27 I38 | w7_concurrency: all seven; stage-1 regression: w3_concurrency, w2_load | suite ca09237 written; not yet run on a product |

## 7. Handoff log

| Handoff | To | Sent | Acknowledged | State |
|---|---|---|---|---|
| Stage-2 handoff, parts 1-14 (plan 46d9da6) | builder, verifier, critic | 09:13Z | builder by 09:16Z (W7), verifier by 09:19Z (W12); critic after the resend | acknowledged |
| Plan revisions c090e8c (import holds), 9106249 (D62, builder question), 736690c (D63, verifier Q1) | builder, verifier, critic | 09:16Z-09:20Z | builder (c090e8c) | sent |
| Liveness resend to critic: stage-2 handoff part 1 (plan review, then W7 review) | critic | 09:36Z | critic 09:36Z: all parts and revisions received; plan review, then W7 | acknowledged |
| Critic plan review @ 736690c (8 defects, 3 gaps, 3 recommendations; REVIEW.md df4b697) -> plan revision: D43 (4 s, abort), D46 (authorize form on `/` too), D50, D64, D65, I34, I46, I48, 3.5-3.14, W7.3, W7.6, W7.9, W8.2, W9.2, W9.6, W10.3-W10.5, W11.1-W11.4 | builder, verifier, critic | 09:41Z | — | sent |
| HANDOFF W7 @ 16adbc0 (builder) | verifier, critic | 09:54Z | verifier PASS 10:07Z (suite cb62939) | critic BLOCKED 10:24Z (X15 test gap; REVIEW.md 7e9b3df) |
| W7 block X15: tests owed (verifier acceptance tests; builder tests 5f9781a already kill X15 and the deadline mutants) | verifier, critic | 10:28Z | builder 5f9781a | suite 5e17085 10:34Z: X15 killed on 16adbc0 and 54acbcd, H04/H04b/C06d killed on 54acbcd, PASS carried over (tests-only delta); awaiting critic rerun |
| HANDOFF W8 @ 54acbcd (builder) | verifier, critic | 10:13Z | verifier PASS 10:28Z (suite 62c4a4e) | awaiting critic |

## 8. Stage close

Not yet.
