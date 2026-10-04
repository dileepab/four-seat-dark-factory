# Stage 4 acceptance suite

Owned by the verifier. Written from the specifications
(`/Users/Dileepa/df-spec/pocketful/spec/stage-1.md` to `stage-4.md`) and `stage-4/PLAN.md`,
not from the implementation. Black-box: it talks to the service over HTTP and drives real Chromium
through Playwright. It also uses `docker` for the container checks and to build the frozen
`stage-1/`, `stage-2/` and `stage-3/` folders as the previous services of the upgrade checks.

## Run

From the repository root:

    stage-4/acceptance/run.sh                         # build, start A, B and the frozen P (stage 1), Q (stage 2), R (stage 3); run everything
    stage-4/acceptance/run.sh --upto 19               # stage-1 to stage-3 regression (items 1-18) and W19
    stage-4/acceptance/run.sh --shots .work/verifier-h6bh/shots/<short-hash>   # save one PNG per UI state
    stage-4/acceptance/run.sh --name pf-builder-acc --port 18101              # another seat's names and ports
    stage-4/acceptance/run.sh --stage-dir <worktree>/stage-4                  # a clean worktree of a commit
    stage-4/acceptance/run.sh -- -k refund -x                                 # extra pytest arguments

Against services that are already running (the container checks are deselected):

    stage-4/acceptance/run.sh --base-url http://127.0.0.1:8080 --second-base-url http://127.0.0.1:8081 \
        --previous-base-url http://127.0.0.1:8082 --previous2-base-url http://127.0.0.1:8083 \
        --previous3-base-url http://127.0.0.1:8084

It needs Python 3.11+ with `pytest`, `httpx` and Playwright with Chromium. It uses
`~/df-spec/.venv/bin/python` (the harness venv) unless `PYTHON` names another interpreter.

## Layout

| File | Covers |
|---|---|
| `support.py` | HTTP client (with `refund` and `batch`), envelope and representation checks (Me and its history views, Payment with `refund_of`, Authorization with `closed_at`, Revision with `correction_batch_id` when a batch recorded it, Correction batch, Statement and Entry, the stage-3 payment form for stored bodies and imported snapshots), exact instants (`instant`, `fmt_instant`, `shifted`: never rounded), `read_statement` (a first page plus every page of its snapshot, checked against I54), `snapshot_pages` (raw pages, compared as JSON), fixtures, the `Service` model that asserts I1, I2 and I30 after every test and during every burst, from `--upto 14` I67 and I1 and I2 in historical views, and from `--upto 19` I68 and I69 over every refund |
| `ui.py` | browser helpers: `data-testid` lookup, request recording, `page.route` faults, screenshots, the I46 checks |
| `conftest.py` | options, the `item(n)` selection, `svc`, `svc_b`, `prev` (stage-1), `prev2` (stage-2), `prev3` (stage-3), `world`, and `page`/`ui`, which run each browser check at 375x812 and at 1280x800 |
| `test_w1_*` to `test_w13_*` | the stage-1 and stage-2 suites on the stage-4 contract (regression, always run): `refund_of: null` on payments, `closed_at` on authorizations, seeded `created_at` honoured, export schema 4 (`test_export_has_format_version_1_and_schema_4`, marked 21; the "invalid schema" probes use 5), RUN.md for stage 4 (marked 21), the eighth to tenth idempotent paths in `test_w2_idempotency.py` (marked 16, 19 and 20), the stage-2 browser checks unchanged |
| `test_w14_instants.py` | W14.4, W14.5: the PLAN 3.4 grammar on `as_of` and `known_at` (valid forms echoed, invalid 422), raw `+`, `%2B`, repeats, 401 first |
| `test_w14_history.py` | W14.1, W14.3-W14.5: seeded `created_at` (exact, ordering by instant, future and invalid 422), strictly increasing issued times, opening balances, inclusive and exact `as_of`, `known_at`, I1 in every view |
| `test_w14_holds.py` | W14.6, W14.7: historical holds (creation, nonfinal and closing captures, void, expiry, future deadlines, seeded open and closed holds) and `closed_at` |
| `test_w15_statements.py` | W15.1-W15.7: shape, order and ties, windows, only the caller's payments, pages, `known_at`, snapshots, holds are not entries |
| `test_w16_corrections.py` | W16.1-W16.10: the new revision, idempotency beyond the shared scenarios, every field rule, precedence, permissions, linked payments, stale revisions, money, funds and historical overdraft, history reads, the revisions read |
| `test_w16_concurrency.py` | W16.6, W18.4: 50 corrections with one expected revision, retries, corrections racing payments and captures, snapshot pages read while corrections commit |
| `test_w17_export.py` | W17.1, W17.2, W17.4: schema 3, round trips (revisions, opening balances, views, statements, snapshot tokens, correction replays), every instant form and the clock base (D85, D86), rejected schema-3 states; W18.7 (b): a partly captured hold across a round trip |
| `test_w17_upgrade.py` | W17.3: unchanged exports of the frozen stage-1 and stage-2 builds imported (payments now carry `refund_of: null`); W18.7 (a): a stage-2 seeded partly captured hold with display-only links and an API capture |
| `test_w19_refunds.py` | W19.1-W19.7: the refund payment (I68), the feed, replays, keys, every amount rule, precedence (D90), who may refund, refunds of refunds, the cap (I69, D92), held funds, the 2^53 guard, every target kind with its request, authorization, hold and settlement unchanged (I70, I75), `refund_of: null` everywhere else, single corrections of refunds and below the refunded total (D94), history, statements and snapshots (I76, I77) |
| `test_w19_ui.py` | PLAN 3.13 (D103): after a refund the wallet shows the corrected numbers and the feed lists the refund as a payment (marked 19); after a batch the wallet shows the corrected total and the feed the original payment (marked 20) |
| `test_w19_concurrency.py` | W19.8: 50 refunds against one cap, refunds racing a correction, refunds of two payments racing for one balance |
| `test_w20_batches.py` | W20.1-W20.9: the batch result (I72, D97, D100), rights (403 before the key and the body, D95, D96), shape, every item field rule, item order, settlements (completeness, one instant in any spelling, seeded members, refunds of members), combined funds with and without holds, the 2^53 guard, history with every new revision together (dips, combined instants, past holds), the order after the items, rejected batches, originals, statements and snapshots |
| `test_w20_concurrency.py` | W20.10, W22.4: batches and single corrections on one revision, overlapping batches, 50 batches over one settlement, refunds racing a batch, snapshot pages read while refunds and batches commit |
| `test_w21_export.py` | W21.1, W21.2, W21.4: schema 4, round trips (refund links, the cap, batch ids, replays, snapshot pages as JSON, later timestamps), an export during a burst, rejected schema-4 states (each probe breaks one rule) |
| `test_w21_upgrade.py` | W21.3: unchanged exports of the frozen stage-1, stage-2 and stage-3 builds imported; `refund_of: null`; replays verbatim; refunds and batches on imported settlements, captures and corrected payments; stage-3 snapshots paged in their own form before and after a stage-4 round trip (D106) |

Each test carries `item(n)`, the highest work item it needs. `--upto n` runs the checks up to Wn.

## Invariants

After every test the `svc` fixture logs in as every account the test knows and asserts:
- I1: the `total`s sum to the seeded total.
- I2: no negative `total`, `available` or `held`, and `held <= total`.
- I30: `balance == total`, `available == total - held`, and `held` equals the open outgoing remainders that `GET /authorizations` lists.
- From `--upto 14` (`Service.assert_history_invariants`): I67, `GET /me` equals the view with `known_at` far in the future for every account (compared only when two `GET /me` reads around it agree, so an expiry between the reads is not a failure); I1 in historical views (`as_of` at the epoch and far in the future, `known_at` at the epoch, and at up to 12 instants of the accounts' history), and, when the seeded history is consistent (`history_is_consistent`), I2 and I60 at those instants: `total` and `available` never negative, `balance == total`, `available == total - held`. The history instants come from the feed before W15 and from the statement (effective times) from W15 on.
- From `--upto 19` (`Service.assert_refund_invariants`): I68 and I69 over every refund a tracked account sent, read from its statement: the target is not a refund, the refund is the target reversed with its note and visibility and is later than it, and the refunds of each target sum to at most the amount of its latest revision.

`Service.burst` releases up to 50 requests together. While they run, it reads every known `/me` in a loop (I2 and I30 during the burst), and it asserts I1 when they finish.

## Time marks

Every instant a test compares with comes from the service (W18.5): a `created_at`, `recorded_at`, `expires_at` or `closed_at`, or `Api.service_now`, which creates a pending request and returns its `created_at`. Microsecond, nanosecond and offset forms are built from those values by `fmt_instant` and `shifted`, exactly.

## Screenshots

With `--shots DIR`, the browser checks save `<screen>-<state>-<width>.png` there: `w375` is 375x812 and `w1280` is 1280x800. The states include loading, load-error, empty, loaded, success, refused and uncertain on every screen. The I46 checks also run in each of those states.
