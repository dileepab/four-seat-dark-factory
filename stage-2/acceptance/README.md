# Stage 2 acceptance suite

Owned by the verifier. Written from the specifications
(`/Users/Dileepa/df-spec/pocketful/spec/stage-1.md`, `stage-2.md`) and `stage-2/PLAN.md`, not
from the implementation. Black-box: it talks to the service over HTTP and drives real Chromium
through Playwright. It also uses `docker` for the container checks and to build the frozen
`stage-1/` as the previous service of the upgrade checks.

## Run

From the repository root:

    stage-2/acceptance/run.sh                         # build, start A, B and the stage-1 P; run everything
    stage-2/acceptance/run.sh --upto 7                # stage-1 regression (items 1-5) and W7
    stage-2/acceptance/run.sh --shots .work/verifier-h6bh/shots/<short-hash>   # save one PNG per UI state
    stage-2/acceptance/run.sh --name pf-builder-acc --port 18101              # another seat's names and ports
    stage-2/acceptance/run.sh --stage-dir <worktree>/stage-2                  # a clean worktree of a commit
    stage-2/acceptance/run.sh -- -k authoriz -x                               # extra pytest arguments

Against services that are already running (the container checks are deselected):

    stage-2/acceptance/run.sh --base-url http://127.0.0.1:8080 --second-base-url http://127.0.0.1:8081 \
        --previous-base-url http://127.0.0.1:8082

It needs Python 3.11+ with `pytest`, `httpx` and Playwright with Chromium. It uses
`~/df-spec/.venv/bin/python` (the harness venv) unless `PYTHON` names another interpreter.

## Layout

| File | Covers |
|---|---|
| `support.py` | HTTP client, envelope and representation checks (Me, Payment, Authorization), fixtures, the `Service` model that asserts I1, I2 and I30 after every test and during every burst |
| `ui.py` | browser helpers: `data-testid` lookup, request recording, `page.route` faults (holds, aborts before and after the server commits, 5xx, non-JSON), screenshots, the I46 checks (scroll, labels, contrast, boundaries, focus) |
| `conftest.py` | options, the `item(n)` selection, `svc`, `svc_b`, `prev` (stage-1), `world`, and `page`/`ui`, which run each browser check at 375x812 and at 1280x800 |
| `test_w1_*` to `test_w5_*` | the stage-1 suite on the stage-2 contract (regression, items 1-5, always run): `GET /me` money fields, `authorization_id` on payments, the seven idempotent paths, the 401 matrix with the new endpoints |
| `test_w7_holds.py` | W7.1, W7.2: `GET /me`, `POST /authorizations`, its error rows and precedence |
| `test_w7_capture.py` | W7.3: capture, final and nonfinal, error rows, D50 precedence, replays, 2^53 guard |
| `test_w7_void.py`, `test_w7_list.py` | W7.4, W7.5 |
| `test_w7_expiry.py` | W7.6: expiry by the clock, seeded expiry compared as an instant |
| `test_w7_funds.py`, `test_w7_fixture.py`, `test_w7_concurrency.py` | W7.7, W7.8, W7.9 |
| `test_w8_export_import.py` | W8.1, W8.2, W8.4: schema 2, round trips, rejected imports |
| `test_w8_upgrade.py` | W8.3: an unchanged export of the frozen stage-1 build imported into stage 2 |
| `test_w9_routes.py` | W9.1 over HTTP: HTML routes, `Accept` negotiation, headers, assets, the `--network=none` container |
| `test_w9_session.py` | W9.2-W9.4: signup, login, logout, session, navigation, I48 |
| `test_w10_wallet.py` | W10.1, W10.2, W10.4-W10.6: wallet numbers, pay and request forms, feed, refresh |
| `test_w10_uncertain.py` | W10.3, W10.7: lost responses, retries, the upgrade in the browser |
| `test_w11_requests_ui.py`, `test_w11_split_ui.py`, `test_w11_authorizations_ui.py` | W11.1-W11.3 |
| `test_w11_states.py` | W11.4: every screen in every named state at both widths (I46 and screenshots) |

Each test carries `item(n)`, the highest work item it needs. `--upto n` runs the checks up to Wn.

## Invariants

After every test the `svc` fixture logs in as every account the test knows and asserts:
- I1: the `total`s sum to the seeded total.
- I2: no negative `total`, `available` or `held`, and `held <= total`.
- I30: `balance == total`, `available == total - held`, and `held` equals the open outgoing remainders that `GET /authorizations` lists.

`Service.burst` releases up to 50 requests together. While they run, it reads every known `/me` in a loop (I2 and I30 during the burst), and it asserts I1 when they finish.

## Screenshots

With `--shots DIR`, the browser checks save `<screen>-<state>-<width>.png` there: `w375` is 375x812 and `w1280` is 1280x800. The states include loading, load-error, empty, loaded, success, refused and uncertain on every screen. The I46 checks also run in each of those states.
