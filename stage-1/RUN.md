# Pocketful stage 1 — how to build and run

An HTTP service in TypeScript on Node.js 24 (Node runs the `.ts` files directly through its
built-in type stripping). No npm dependencies: nothing is downloaded at build or run time.
State is held in memory; a restart starts empty.

All commands below run from the repository root, `/Users/Dileepa/dark-factory-v3`.

## Build and run the container

```sh
docker build -t pocketful-s1 stage-1
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s1
curl http://localhost:8080/health          # {"status":"ok"}
```

- `PORT` selects the listening port inside the container (default `8080`); the service
  listens on `0.0.0.0`.
- The build needs only the base image `node:24.14.0-alpine3.22`. With that image present it
  also builds with `docker build --network=none`, and the container runs with `--network=none`.
- Before the first `POST /_test/reset` the service has no users, currency `EUR`, 2 minor units.

## Run without Docker

Needs Node.js 24 or later.

```sh
cd stage-1 && PORT=8080 node src/main.ts
```

## Builder tests

Unit and integration tests with `node:test`; each file starts its own in-process server on a
free port.

```sh
cd stage-1 && npm test
```

## Acceptance suite

The verifier's suite lives in `stage-1/acceptance/` and is run through its own script, which
documents its options:

```sh
stage-1/acceptance/run.sh
```

## Supplied checks

```sh
scripts/harness.sh run --track pocketful --repo /Users/Dileepa/dark-factory-v3 --stage 1 \
  --out /Users/Dileepa/dark-factory-v3/.work/checks/s1-<nn>
```

## Layout

- `src/main.ts` — entry point; `src/app.ts` — HTTP transport, body limits, error envelope;
  `src/routes.ts` — the route table; `src/handlers/` — one module per endpoint group.
- `src/state.ts` — the in-memory state, ids and timestamps; `src/fixture.ts` — reset
  validation; `src/passwords.ts` — scrypt hashing and bearer tokens.
- `test/` — builder tests.
