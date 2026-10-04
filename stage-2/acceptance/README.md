# Stage 1 acceptance suite

Owned by the verifier. Written from the specification
(`/Users/Dileepa/df-spec/pocketful/spec/stage-1.md`) and `stage-1/PLAN.md`, not from
the implementation. Black-box: it talks to the service over HTTP only, plus `docker`
for the container checks.

## Run

From the repository root:

    stage-1/acceptance/run.sh                 # build, start two containers, run everything
    stage-1/acceptance/run.sh --upto 2        # only checks for W1 and W2
    stage-1/acceptance/run.sh --name pf-builder-acc --port 18101   # another seat's names and ports
    stage-1/acceptance/run.sh -- -k settlement -x                 # extra pytest arguments

Against services that are already running (the container checks are deselected):

    stage-1/acceptance/run.sh --base-url http://127.0.0.1:8080 --second-base-url http://127.0.0.1:8081

It needs Python 3.11+ with `pytest` and `httpx`. It uses `~/df-spec/.venv/bin/python`
unless `PYTHON` names another interpreter.

## Layout

| File | Covers |
|---|---|
| `support.py` | HTTP client, envelope and representation checks, fixtures, the `Service` model that asserts I1/I2 after every test and during every burst |
| `conftest.py` | options, the `item(n)` work-item selection, the `svc`, `svc_b` and `world` fixtures |
| `test_w1_container.py` | W1.1, W1.2: Dockerfile, RUN.md, offline build, `PORT`, health, resource limits |
| `test_w1_transport.py` | W1.3: parsing, size limits, envelope, routes, HTTP-layer rejections, robustness |
| `test_w1_reset.py` | W1.4: fixture validation and atomicity, seeding, 1000-user reset |
| `test_w1_auth.py` | W1.5-W1.7, W1.9: signup, login, handles, tokens, 401 matrix, `GET /me`, concurrent signups |
| `test_w2_*.py` | W2: payments, idempotency, activity feed, money under load |
| `test_w3_*.py` | W3: requests, decline, cancel, listing, splits, at-most-once |
| `test_w4_*.py` | W4: settlements |
| `test_w5_*.py` | W5: export and import, including into a second container |

Each test carries `item(n)`, the highest work item it needs. `--upto n` runs the
checks for W1..Wn. There is no earlier stage, so stage 1 has no regression set.

## Invariants

After every test the `svc` fixture logs in as every account the test knows and
asserts I1 (the balances sum to the seeded total) and I2 (no negative balance).
`Service.burst` releases up to 50 requests together. While they run, it reads every
known balance in a loop (I2 during the burst), and it asserts I1 when they finish.
