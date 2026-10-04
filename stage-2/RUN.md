# Pocketful stage 2 — how to build and run

An HTTP service in TypeScript on Node.js 24 (Node runs the `.ts` files directly through its
built-in type stripping). No npm dependencies: nothing is downloaded at build or run time.
State is held in memory; a restart starts empty.

Stage 2 adds payment authorizations (holds): `POST /authorizations`, capture, void and
`GET /authorizations`, with `GET /me` reporting `total`, `available` and `held`. The browser
UI arrives with W9 to W11 and is served by the same process.

All commands below run from the repository root, `/Users/Dileepa/dark-factory-v3`.

## Build and run the container

```sh
docker build -t pocketful-s2 stage-2
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s2
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
cd stage-2 && PORT=8080 node src/main.ts
```

## Builder tests

Unit and integration tests with `node:test`; each file starts its own in-process server on a
free port (the export and import tests also start a second service process).

```sh
cd stage-2 && npm test
```

## Acceptance suite

The verifier's suite lives in `stage-2/acceptance/` and is run through its own script, which
builds the images (this stage twice, and the frozen `stage-1/` beside it as the previous
service for the upgrade checks), starts the containers and documents its options. It runs
pytest, httpx and Playwright (Chromium) from the harness venv `~/df-spec/.venv`:

```sh
stage-2/acceptance/run.sh --upto <item> --name pf-<seat>-acc --port <first free port> \
  [--stage-dir <worktree>/stage-2]
```

## Supplied checks

The harness runs the supplied checks of stages 1 and 2 (the stage-2 browser checks through its
own Playwright) and builds the frozen `stage-1/` as the previous service:

```sh
scripts/harness.sh run --track pocketful --repo /Users/Dileepa/dark-factory-v3 --stage 2 \
  --out /Users/Dileepa/dark-factory-v3/.work/checks/s2-<nn>
```

## Layout

- `src/main.ts` — entry point; `src/app.ts` — HTTP transport, body limits, error envelope;
  `src/routes.ts` — the route table; `src/handlers/` — one module per endpoint group
  (`authorizations.ts` for holds, captures and voids).
- `src/state.ts` — the in-memory state, ids, timestamps, the service clock and holds;
  `src/time.ts` — RFC 3339 instants; `src/fixture.ts` — reset validation; `src/snapshot.ts` —
  export and import; `src/idempotency.ts` — idempotent write paths; `src/ledger.ts` — moving
  money; `src/passwords.ts` — scrypt hashing and bearer tokens.
- `test/` — builder tests.
