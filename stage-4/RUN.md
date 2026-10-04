# Pocketful stage 3 — how to build and run

An HTTP service in TypeScript on Node.js 24 (Node runs the `.ts` files directly through its
built-in type stripping). No npm dependencies: nothing is downloaded at build or run time.
State is held in memory; a restart starts empty.

Stage 3 adds history on top of stage 2's payments, requests, splits, settlements and holds:

- `GET /me?as_of=<instant>&known_at=<instant>` — balances as they stood at an effective
  instant, as known at a recorded instant; holds follow their own history (creation,
  captures, close, expiry).
- `GET /statement?from=&to=&known_at=&limit=&offset=` — the caller's payments in the window
  `[from, to)`, oldest first, with opening, running and closing balances. Every first read
  returns a `snapshot` token; `GET /statement?snapshot=<token>&limit=&offset=` pages exactly
  that result later.
- `POST /payments/{id}/corrections` (idempotent) — the sender appends a revision with a new
  amount and effective time; `GET /payments/{id}/revisions` lists them to the two parties.
- Seeded `created_at` on fixture payments and authorizations, and `closed_at` on every
  authorization.
- `GET /_test/export` writes schema 3 (every revision, opening balances, snapshots);
  `POST /_test/import` reads schemas 1, 2 and 3, so unchanged stage-1 and stage-2 exports
  import.

Instants in query parameters are percent-decoded only: a literal `+` in an offset stays a
plus sign, so `?as_of=2026-09-20T12:00:00+05:30` and `...%2B05:30` are the same instant.

## The UI

Unchanged from stage 2. Open `http://localhost:8080/` in a browser. Every page is the same
HTML shell with plain JavaScript modules and one stylesheet from `ui/` (served under
`/assets/`); nothing is loaded from another origin.

- `/login`, `/signup` — sign in or create an account; the session token is kept in the
  browser's `localStorage`.
- `/` — the wallet: available (the headline), total and held, the pay, request and authorize
  forms, and the activity feed.
- `/requests` — incoming and outgoing requests with pay, decline and cancel.
- `/split` — split a bill equally, with a live preview of each share.
- `/authorizations` — holds in both directions: authorize, capture, void.

`/requests` and `/authorizations` are shared with the JSON API: a browser (whose `Accept`
lists `text/html`) gets the page, every other client gets JSON. An unknown path answers JSON
404, or the page's not-found screen for a browser.

All commands below run from the repository root, `/Users/Dileepa/dark-factory-v3`.

## Build and run the container

```sh
docker build -t pocketful-s3 stage-3
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s3
curl http://localhost:8080/health          # {"status":"ok"}
```

- `PORT` selects the listening port inside the container (default `8080`); the service
  listens on `0.0.0.0`.
- The build needs only the base image `node:24.14.0-alpine3.22`. With that image present it
  also builds with `docker build --network=none`, and the container runs with `--network=none`.
- Before the first `POST /_test/reset` the service has no users, currency `EUR`, 2 minor units
  and an authorization lifetime of 600 seconds.

## Run without Docker

Needs Node.js 24 or later.

```sh
cd stage-3 && PORT=8080 node src/main.ts
```

## Builder tests

Unit and integration tests with `node:test`; each file starts its own in-process server on a
free port (the export and import tests also start a second service process). The upgrade tests
(`test/w8-upgrade.test.ts`, `test/w17-export.test.ts`) also start the frozen stage-1 and stage-2
services from `../stage-1/src/main.ts` and `../stage-2/src/main.ts`, read-only, as the previous
versions whose exports stage 3 must import.

```sh
cd stage-3 && npm test
```

## Acceptance suite

The verifier's suite lives in `stage-3/acceptance/` and is run through its own script, which
builds the images (this stage twice, and the frozen `stage-1/` and `stage-2/` beside it as the
previous services for the upgrade checks), starts the containers and documents its options in
its header. It runs pytest, httpx and Playwright (Chromium) from the harness venv
`~/df-spec/.venv`:

```sh
stage-3/acceptance/run.sh --upto <item> --name pf-<seat>-acc --port <first free port> \
  [--stage-dir <worktree>/stage-3] [--shots <dir>]
```

## Supplied checks

The harness runs the supplied checks of stages 1 to 3 (the stage-2 browser checks through its
own Playwright) and builds the earlier stages as the previous services:

```sh
scripts/harness.sh run --track pocketful --repo /Users/Dileepa/dark-factory-v3 --stage 3 \
  --out /Users/Dileepa/dark-factory-v3/.work/checks/s3-<nn>
```

## Layout

- `src/main.ts` — entry point; `src/app.ts` — HTTP transport, body limits, error envelope;
  `src/routes.ts` — the route table; `src/handlers/` — one module per endpoint group
  (`authorizations.ts` for holds, captures and voids; `me.ts` for `GET /me` and its history
  view; `statement.ts` for statements and snapshots; `corrections.ts` for corrections and
  revisions).
- `src/state.ts` — the in-memory state, ids, issued timestamps, the service clock, holds,
  payment revisions and statement snapshots; `src/instant.ts` — the instant grammar and exact
  comparison keys; `src/history.ts` — historical views (revision selection, totals and holds
  at an instant, the historical-overdraft check); `src/time.ts` — RFC 3339 expiry arithmetic;
  `src/context.ts` — the request context, authentication and the instant query parameters;
  `src/fixture.ts` — reset validation; `src/snapshot.ts` — export (schema 3) and import
  (schemas 1, 2 and 3); `src/idempotency.ts` — idempotent write paths; `src/ledger.ts` —
  moving money; `src/passwords.ts` — scrypt hashing and bearer tokens.
- `src/ui.ts` — the HTML shell, static files and `Accept` negotiation; `ui/index.html` and
  `ui/assets/` — the browser code (`app.js` routing and header, one module per screen,
  `money.js`, `split.js` and `retry.js` pure logic, `api.js` the page's API calls) and
  `app.css`.
- `test/` — builder tests.
