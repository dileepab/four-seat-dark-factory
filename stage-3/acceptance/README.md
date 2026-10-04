# Stage 3 acceptance suite

Owned by the verifier. Written from the specifications
(`/Users/Dileepa/df-spec/pocketful/spec/stage-1.md`, `stage-2.md`, `stage-3.md`) and `stage-3/PLAN.md`,
not from the implementation. Black-box: it talks to the service over HTTP and drives real Chromium
through Playwright. It also uses `docker` for the container checks and to build the frozen
`stage-1/` and `stage-2/` folders as the previous services of the upgrade checks.

## Run

From the repository root:

    stage-3/acceptance/run.sh                         # build, start A, B, the stage-1 P and the stage-2 Q; run everything
    stage-3/acceptance/run.sh --upto 14               # stage-1 and stage-2 regression (items 1-13) and W14
    stage-3/acceptance/run.sh --shots .work/verifier-h6bh/shots/<short-hash>   # save one PNG per UI state
    stage-3/acceptance/run.sh --name pf-builder-acc --port 18101              # another seat's names and ports
    stage-3/acceptance/run.sh --stage-dir <worktree>/stage-3                  # a clean worktree of a commit
    stage-3/acceptance/run.sh -- -k statement -x                              # extra pytest arguments

Against services that are already running (the container checks are deselected):

    stage-3/acceptance/run.sh --base-url http://127.0.0.1:8080 --second-base-url http://127.0.0.1:8081 \
        --previous-base-url http://127.0.0.1:8082 --previous2-base-url http://127.0.0.1:8083

It needs Python 3.11+ with `pytest`, `httpx` and Playwright with Chromium. It uses
`~/df-spec/.venv/bin/python` (the harness venv) unless `PYTHON` names another interpreter.

## Layout

| File | Covers |
|---|---|
| `support.py` | HTTP client, envelope and representation checks (Me and its history views, Payment, Authorization with `closed_at`, Revision, Statement and Entry), exact instants (`instant`, `fmt_instant`, `shifted`: never rounded), `read_statement` (a first page plus every page of its snapshot, checked against I54), fixtures, the `Service` model that asserts I1, I2 and I30 after every test and during every burst, and from `--upto 14` I1 and I2 in historical views |
| `ui.py` | browser helpers: `data-testid` lookup, request recording, `page.route` faults, screenshots, the I46 checks |
| `conftest.py` | options, the `item(n)` selection, `svc`, `svc_b`, `prev` (stage-1), `prev2` (stage-2), `world`, and `page`/`ui`, which run each browser check at 375x812 and at 1280x800 |
| `test_w1_*` to `test_w13_*` | the stage-1 and stage-2 suites on the stage-3 contract (regression, items 1-13, always run): `closed_at` on authorizations, seeded `created_at` honoured, export schema 3 (the "invalid schema" probes use 4), the eighth idempotent path in `test_w2_idempotency.py` (marked 16), the stage-2 browser checks unchanged |
| `test_w14_instants.py` | W14.4, W14.5: the PLAN 3.4 grammar on `as_of` and `known_at` (valid forms echoed, invalid 422), raw `+`, `%2B`, repeats, 401 first |
| `test_w14_history.py` | W14.1, W14.3-W14.5: seeded `created_at` (exact, ordering by instant, future and invalid 422), strictly increasing issued times, opening balances, inclusive and exact `as_of`, `known_at`, I1 in every view |
| `test_w14_holds.py` | W14.6, W14.7: historical holds (creation, nonfinal and closing captures, void, expiry, future deadlines, seeded open and closed holds) and `closed_at` |
| `test_w15_statements.py` | W15.1-W15.7: shape, order and ties, windows, only the caller's payments, pages, `known_at`, snapshots, holds are not entries |
| `test_w16_corrections.py` | W16.1-W16.10: the new revision, idempotency beyond the shared scenarios, every field rule, precedence, permissions, linked payments, stale revisions, money, funds and historical overdraft, history reads, the revisions read |
| `test_w16_concurrency.py` | W16.6, W18.4: 50 corrections with one expected revision, retries, corrections racing payments and captures, snapshot pages read while corrections commit |
| `test_w17_export.py` | W17.1, W17.2, W17.4: schema 3, round trips (revisions, opening balances, views, statements, snapshot tokens, correction replays), rejected schema-3 states |
| `test_w17_upgrade.py` | W17.3: unchanged exports of the frozen stage-1 and stage-2 builds imported into stage 3 |

Each test carries `item(n)`, the highest work item it needs. `--upto n` runs the checks up to Wn.

## Invariants

After every test the `svc` fixture logs in as every account the test knows and asserts:
- I1: the `total`s sum to the seeded total.
- I2: no negative `total`, `available` or `held`, and `held <= total`.
- I30: `balance == total`, `available == total - held`, and `held` equals the open outgoing remainders that `GET /authorizations` lists.
- From `--upto 14` (`Service.assert_history_invariants`): I1 in historical views (`as_of` at the epoch and far in the future, `known_at` at the epoch, and at up to 12 instants of the accounts' history), and, when the seeded history is consistent (`history_is_consistent`), I2 and I60 at those instants: `total` and `available` never negative, `balance == total`, `available == total - held`. The history instants come from the feed before W15 and from the statement (effective times) from W15 on.

`Service.burst` releases up to 50 requests together. While they run, it reads every known `/me` in a loop (I2 and I30 during the burst), and it asserts I1 when they finish.

## Time marks

Every instant a test compares with comes from the service (W18.5): a `created_at`, `recorded_at`, `expires_at` or `closed_at`, or `Api.service_now`, which creates a pending request and returns its `created_at`. Microsecond, nanosecond and offset forms are built from those values by `fmt_instant` and `shifted`, exactly.

## Screenshots

With `--shots DIR`, the browser checks save `<screen>-<state>-<width>.png` there: `w375` is 375x812 and `w1280` is 1280x800. The states include loading, load-error, empty, loaded, success, refused and uncertain on every screen. The I46 checks also run in each of those states.
