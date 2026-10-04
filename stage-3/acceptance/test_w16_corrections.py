"""W16.1-W16.10 — `POST /payments/{id}/corrections` and `GET /payments/{id}/revisions` (stage-3
"Effective time, recorded time, and corrections", "Settlement history", "Historical holds"; PLAN 3.3,
3.6, 3.7, 3.9 steps 1-14, D67, D74, D75, D80-D83). I1, I2, I56-I59, I62.

The idempotency scenarios of the eighth path run in test_w2_idempotency.py (`Corrections`).
Every instant comes from the service (W18.5); "the future" is a service time mark plus a second.
"""
from __future__ import annotations

import json

import pytest

from support import (EPOCH, FAR_FUTURE, PLAN_TS, TWO_53, check_revision, expect, expect_error, fixture, instant,
                     new_key, page_snapshot, read_statement, shifted, standard_users, user)
from test_w14_history import seeded
from test_w14_instants import INVALID

pytestmark = pytest.mark.item(16)


def uid(svc, h) -> str:
    svc.client(h)
    return svc.accounts[h].user_id


def state(svc, pids=()) -> dict:
    """Everything a rejected correction must leave alone (T36): money, feeds, revisions, statements."""
    out = {}
    for h in svc.accounts:
        c = svc.client(h)
        out[h] = (c.money(), [p["payment_id"] for p in c.feed()])
        body = expect(c.statement(limit=200), 200)
        out[h + "_statement"] = (body["opening_balance"], body["closing_balance"],
                                 [(e["payment"]["payment_id"], e["revision"], e["delta"]) for e in body["entries"]])
    for pid in pids:
        r = svc.client("ada").revisions_resp(pid)
        out[pid] = r.text if r.status_code == 200 else None
    return out


@pytest.fixture
def paid(world):
    """Ada paid bob 100."""
    p = expect(world.ada.pay("bob", 100, note="dinner", visibility="private"), 201)
    world.p = p
    world.pid = p["payment_id"]
    return world


# ---------------------------------------------------------------- W16.1 the new revision

def test_a_correction_returns_the_new_revision(paid):
    w = paid
    r = check_revision(expect(w.ada.correct(w.pid, 1, 60, w.p["created_at"], "correct amount"), 201),
                       payment_id=w.pid, revision=2, amount=60, effective_at=w.p["created_at"], reason="correct amount")
    assert PLAN_TS.match(r["recorded_at"]) and instant(r["recorded_at"]) > instant(w.p["created_at"]), \
        f"T29/T30: recorded_at is issued by the service, after revision 1: {r}"
    revs = w.ada.revisions(w.pid)
    assert revs == [{"payment_id": w.pid, "revision": 1, "amount": 100, "effective_at": w.p["created_at"],
                     "recorded_at": w.p["created_at"], "reason": ""}, r]
    assert w.bob.revisions(w.pid) == revs
    assert w.ada.money() == (9_940, 9_940, 0) and w.bob.money() == (2_560, 2_560, 0)


@pytest.mark.parametrize("effective_at", ["2026-01-01t00:00:00.123456789z", "2026-01-01T05:30:00+05:30",
                                          "2026-01-01T00:00:00-00:00", "2025-12-31T23:59:59.5-23:59"])
def test_effective_at_is_kept_exactly_as_sent(paid, effective_at):
    r = expect(paid.ada.correct(paid.pid, 1, 100, effective_at), 201)
    assert r["effective_at"] == effective_at
    assert paid.ada.revisions(paid.pid)[1]["effective_at"] == effective_at


def test_recorded_at_strictly_increases_across_quick_corrections(paid):
    """D67: two corrections in one millisecond still get strictly increasing recorded_at."""
    w = paid
    out = []
    for n in range(1, 11):
        out.append(expect(w.ada.correct(w.pid, n, 100 - n, w.p["created_at"]), 201))
    assert [r["revision"] for r in out] == list(range(2, 12))
    times = [instant(w.p["created_at"])] + [instant(r["recorded_at"]) for r in out]
    assert all(a < b for a, b in zip(times, times[1:])), [r["recorded_at"] for r in out]
    assert [r["amount"] for r in w.ada.revisions(w.pid)] == [100] + [100 - n for n in range(1, 11)]
    assert w.ada.balance() == 10_000 - 90


def test_correcting_a_seeded_payment(svc):
    svc.must_reset(fixture(standard_users(), payments=[seeded("p_s", "ada", "bob", 400, "2026-02-01T08:00:00+01:00")]))
    ada = svc.client("ada")
    revs = ada.revisions("p_s")
    assert revs == [{"payment_id": "p_s", "revision": 1, "amount": 400, "effective_at": "2026-02-01T08:00:00+01:00",
                     "recorded_at": "2026-02-01T08:00:00+01:00", "reason": ""}], "T24: a seeded created_at is revision 1"
    expect(ada.correct("p_s", 1, 300, "2026-02-01T08:00:00+01:00"), 201)
    assert ada.money() == (10_100, 10_100, 0) and svc.client("bob").money() == (2_400, 2_400, 0)
    assert ada.me_at(EPOCH)["total"] == 10_400, "T25: corrections never change an opening balance"
    assert svc.client("bob").me_at(EPOCH)["total"] == 2_100


def test_correcting_a_request_payment(world):
    rq = expect(world.bob.ask("ada", 300, note="taxi"), 201)
    k = new_key()
    p = expect(world.ada.pay_request(rq["request_id"], key=k), 201)
    expect(world.ada.correct(p["payment_id"], 1, 250, p["created_at"]), 201)
    assert world.ada.balance() == 9_750 and world.bob.balance() == 2_750
    assert expect(world.ada.pay_request(rq["request_id"], key=k), 200) == p, "T38: the original response"
    r = [x for x in world.ada.requests() if x["request_id"] == rq["request_id"]][0]
    assert (r["status"], r["amount"], r["payment_id"]) == ("paid", 300, p["payment_id"])


# ---------------------------------------------------------------- W16.2 idempotency (beyond the shared scenarios)

def test_a_failed_correction_claims_no_key(paid):
    w = paid
    k = new_key()
    expect_error(w.ada.correct(w.pid, 2, 60, w.p["created_at"], key=k), 409, "stale_revision")
    expect_error(w.ada.correct(w.pid, 1, 100_000, w.p["created_at"], key=k), 409, "insufficient_funds")
    expect_error(w.bob.correct(w.pid, 1, 60, w.p["created_at"], key=k), 403, "forbidden")
    r = expect(w.ada.correct(w.pid, 1, 60, w.p["created_at"], key=k), 201)
    assert expect(w.ada.correct(w.pid, 1, 60, w.p["created_at"], key=k), 200) == r


def test_a_replay_returns_the_original_revision_after_newer_ones(paid):
    w = paid
    k = new_key()
    r2 = expect(w.ada.correct(w.pid, 1, 60, w.p["created_at"], "first", key=k), 201)
    expect(w.ada.correct(w.pid, 2, 80, w.p["created_at"], "second"), 201)
    expect(w.ada.correct(w.pid, 3, 0, w.p["created_at"], "third"), 201)
    before = (w.ada.money(), w.bob.money())
    assert expect(w.ada.correct(w.pid, 1, 60, w.p["created_at"], "first", key=k), 200) == r2, "T32"
    assert (w.ada.money(), w.bob.money()) == before
    expect_error(w.ada.correct(w.pid, 1, 61, w.p["created_at"], "first", key=k), 409, "idempotency_key_reuse")


def test_keys_are_scoped_by_path(world):
    k = new_key()
    p1 = expect(world.ada.pay("bob", 100, key=k), 201)
    p2 = expect(world.ada.pay("bob", 50, key=new_key()), 201)
    r1 = expect(world.ada.correct(p1["payment_id"], 1, 90, p1["created_at"], key=k), 201)
    r2 = expect(world.ada.correct(p2["payment_id"], 1, 40, p2["created_at"], key=k), 201)
    assert (r1["payment_id"], r2["payment_id"]) == (p1["payment_id"], p2["payment_id"])
    assert world.ada.balance() == 10_000 - 130
    k2 = new_key()
    expect(world.bob.pay("ada", 5, key=k2), 201)
    q = expect(world.bob.pay("cy", 5), 201)
    expect(world.bob.correct(q["payment_id"], 1, 4, q["created_at"], key=k2), 201)


def test_the_same_key_on_all_eight_paths_is_independent(world):
    ada, bob = world.ada, world.bob
    k = new_key()
    p = expect(ada.pay("bob", 5, key=k), 201)
    expect(ada.ask("bob", 5, key=k), 201)
    rq = expect(bob.ask("ada", 10, key=k), 201)["request_id"]
    expect(ada.pay_request(rq, key=k), 201)
    expect(ada.split(30, ["ada", "bob"], key=k), 201)
    expect(ada.settle([{"from_handle": "ada", "to_handle": "dee", "amount": 1}], key=k), 201)
    a = expect(ada.authorize("bob", 100, key=k), 201)["authorization_id"]
    expect(bob.capture(a, {}, key=k), 201)
    r = expect(ada.correct(p["payment_id"], 1, 4, p["created_at"], key=k), 201)
    assert r["revision"] == 2
    assert ada.money() == (10_000 - 4 - 10 - 1 - 100, 10_000 - 4 - 10 - 1 - 100, 0)


# ---------------------------------------------------------------- W16.3 validation

def _body(p, **over):
    b = {"expected_revision": 1, "amount": 60, "effective_at": p["created_at"], "reason": "fix"}
    for k, v in over.items():
        if v is _DROP:
            b.pop(k)
        else:
            b[k] = v
    return b


_DROP = object()

FIELD_ERRORS = {
    "expected_revision missing": {"expected_revision": _DROP},
    "expected_revision null": {"expected_revision": None},
    "expected_revision true": {"expected_revision": True},
    "expected_revision false": {"expected_revision": False},
    "expected_revision string": {"expected_revision": "1"},
    "expected_revision 1.5": {"expected_revision": 1.5},
    "expected_revision 0": {"expected_revision": 0},
    "expected_revision -1": {"expected_revision": -1},
    "expected_revision 2^53+2": {"expected_revision": TWO_53 + 2},
    "expected_revision 1e300": {"expected_revision": 1e300},
    "expected_revision array": {"expected_revision": [1]},
    "expected_revision object": {"expected_revision": {"n": 1}},
    "amount missing": {"amount": _DROP},
    "amount null": {"amount": None},
    "amount true": {"amount": True},
    "amount string": {"amount": "60"},
    "amount 1.5": {"amount": 1.5},
    "amount -1": {"amount": -1},
    "amount 1000000001": {"amount": 1_000_000_001},
    "amount array": {"amount": [60]},
    "effective_at missing": {"effective_at": _DROP},
    "effective_at null": {"effective_at": None},
    "effective_at number": {"effective_at": 1767225600},
    "effective_at true": {"effective_at": True},
    "effective_at array": {"effective_at": ["2026-01-01T00:00:00Z"]},
    **{f"effective_at {k}": {"effective_at": v} for k, v in INVALID.items()},
    "reason missing": {"reason": _DROP},
    "reason null": {"reason": None},
    "reason number": {"reason": 5},
    "reason empty": {"reason": ""},
    "reason 201 characters": {"reason": "r" * 201},
    "reason 201 astral code points": {"reason": "\U0001F600" * 201},
    "reason array": {"reason": ["fix"]},
}


@pytest.mark.parametrize("over", FIELD_ERRORS.values(), ids=FIELD_ERRORS.keys())
def test_invalid_fields_are_422_and_change_nothing(paid, over):
    """D80: every correction field error is 422 validation_failed."""
    w = paid
    before = state(w.svc, [w.pid])
    k = new_key()
    expect_error(w.ada.correct(w.pid, body=_body(w.p, **over), key=k), 422, "validation_failed")
    assert state(w.svc, [w.pid]) == before
    expect(w.ada.correct(w.pid, body=_body(w.p), key=k), 201)


def test_effective_at_later_than_now_is_422(paid):
    """D81: no tolerance; one second after a service time mark is later than the operation's now."""
    w = paid
    mark = w.ada.service_now("cy")
    before = state(w.svc, [w.pid])
    for ahead in (1, 60, 3600):
        expect_error(w.ada.correct(w.pid, 1, 60, shifted(mark, seconds=ahead, digits=3)), 422, "validation_failed")
    expect_error(w.ada.correct(w.pid, 1, 60, FAR_FUTURE), 422, "validation_failed")
    assert state(w.svc, [w.pid]) == before
    expect(w.ada.correct(w.pid, 1, 60, mark), 201)


@pytest.mark.parametrize("raw", [
    '{"expected_revision": 1.0, "amount": 60, "effective_at": "%s", "reason": "fix"}',
    '{"expected_revision": 1, "amount": 6e1, "effective_at": "%s", "reason": "fix"}',
    '{"expected_revision": 1E0, "amount": 60.000, "effective_at": "%s", "reason": "fix"}',
])
def test_integral_number_forms_are_valid(paid, raw):
    r = expect(paid.ada.post(f"/payments/{paid.pid}/corrections", content=(raw % paid.p["created_at"]).encode(),
                             key=new_key()), 201)
    assert (r["revision"], r["amount"]) == (2, 60)


@pytest.mark.parametrize("reason", [" ", "r" * 200, "\U0001F600" * 200, "é" * 200, "line\nbreak"])
def test_reason_limits_count_code_points(paid, reason):
    r = expect(paid.ada.correct(paid.pid, 1, 60, paid.p["created_at"], reason), 201)
    assert r["reason"] == reason


def test_amount_bounds(svc):
    svc.must_reset(fixture([user("ada", 2_000_000_000), user("bob", 0)]))
    ada = svc.client("ada")
    p = expect(ada.pay("bob", 1), 201)
    expect(ada.correct(p["payment_id"], 1, 1_000_000_000, p["created_at"]), 201)
    assert svc.client("bob").balance() == 1_000_000_000
    expect(ada.correct(p["payment_id"], 2, 0, p["created_at"]), 201)
    assert (ada.balance(), svc.client("bob").balance()) == (2_000_000_000, 0), "amount 0 reverses the payment"


def test_unknown_body_fields_are_ignored(paid):
    r = expect(paid.ada.correct(paid.pid, body={**_body(paid.p), "payment_id": "p_other", "revision": 9,
                                                "recorded_at": EPOCH, "to_user_id": "u_cy", "visibility": "public"}), 201)
    assert (r["payment_id"], r["revision"]) == (paid.pid, 2) and r["recorded_at"] != EPOCH
    feed = {p["payment_id"]: p for p in paid.bob.feed()}
    assert feed[paid.pid] == paid.p, "T28: parties and visibility never change"


@pytest.mark.parametrize("raw, status, code", [
    (b"{nope", 400, "malformed_request"), (b"[]", 400, "malformed_request"), (b'"x"', 400, "malformed_request"),
    (b"", 400, "malformed_request"), (b"null", 400, "malformed_request"), (b"{}", 422, "validation_failed")])
def test_body_shape(paid, raw, status, code):
    expect_error(paid.ada.post(f"/payments/{paid.pid}/corrections", content=raw, key=new_key()), status, code)


def test_precedence_of_the_common_steps(paid):
    """PLAN 3.9 steps 1-6: route, 401, key, body, claimed key, fields."""
    w = paid
    path = f"/payments/{w.pid}/corrections"
    anon = w.svc.api()
    expect_error(anon.post(path, content=b"{nope"), 401, "unauthenticated")
    expect_error(anon.post("/payments/p_nope/corrections", json={}), 401, "unauthenticated")
    expect_error(w.ada.post(path, content=b"{nope"), 400, "missing_idempotency_key")
    expect_error(w.ada.post(path, content=b"{nope", key="k" * 256), 422, "validation_failed")
    expect_error(w.ada.post(path, content=b"{nope", key=new_key()), 400, "malformed_request")
    k = new_key()
    expect(w.ada.correct(w.pid, body=_body(w.p), key=k), 201)
    expect_error(w.ada.correct(w.pid, body=_body(w.p, reason=""), key=k), 409, "idempotency_key_reuse")
    expect_error(w.ada.correct("p_nope", body=_body(w.p, amount=-1)), 422, "validation_failed")
    expect_error(w.cy.correct(w.pid, body=_body(w.p, amount=-1)), 422, "validation_failed")


def test_unknown_methods_on_the_routes_are_404(paid):
    expect_error(paid.ada.get(f"/payments/{paid.pid}/corrections"), 404, "not_found")
    expect_error(paid.ada.post(f"/payments/{paid.pid}/revisions", json={}, key=new_key()), 404, "not_found")


# ---------------------------------------------------------------- W16.4 permissions

def test_permissions(paid):
    w = paid
    body = _body(w.p)
    before = state(w.svc, [w.pid])
    expect_error(w.svc.api().correct(w.pid, body=body), 401, "unauthenticated")
    expect_error(w.ada.correct("p_does_not_exist", body=body), 404, "not_found")
    expect_error(w.bob.correct(w.pid, body=body), 403, "forbidden")      # the receiver
    expect_error(w.cy.correct(w.pid, body=body), 403, "forbidden")      # a third party, private payment (D83)
    assert state(w.svc, [w.pid]) == before
    pub = expect(w.ada.pay("bob", 10), 201)
    expect_error(w.dee.correct(pub["payment_id"], body=_body(pub)), 403, "forbidden")   # public


def test_resource_precedence(svc):
    """PLAN 3.9 steps 7-11: 404, 403, linked 422, stale 409, funds 409."""
    svc.must_reset(fixture(standard_users(), operators=["u_ada"]))
    ada, bob = svc.client("ada"), svc.client("bob")
    a = expect(ada.authorize("bob", 100), 201)
    cap = expect(bob.capture(a["authorization_id"], {"amount": 50}), 201)
    at = cap["created_at"]
    expect_error(bob.correct(cap["payment_id"], 7, 10**9, at), 403, "forbidden")            # 403 before linked
    expect_error(ada.correct(cap["payment_id"], 7, 10**9, at), 422, "linked_payment_immutable")   # before stale
    p = expect(ada.pay("bob", 10), 201)
    expect_error(ada.correct(p["payment_id"], 2, 10**9, at), 409, "stale_revision")         # before funds
    expect_error(ada.correct(p["payment_id"], 1, 10**9, at), 409, "insufficient_funds")


# ---------------------------------------------------------------- W16.5 linked payments

def test_captures_and_settlement_members_are_immutable(world):
    a = expect(world.ada.authorize("bob", 500), 201)
    cap = expect(world.bob.capture(a["authorization_id"], {"amount": 200, "final": False}), 201)
    st = expect(world.ada.settle([{"from_handle": "ada", "to_handle": "cy", "amount": 30},
                                  {"from_handle": "bob", "to_handle": "dee", "amount": 20}]), 201)
    before = state(world.svc)
    for c, p in ((world.ada, cap), (world.ada, st["payments"][0]), (world.bob, st["payments"][1])):
        for amount in (p["amount"], 0, p["amount"] + 1):
            expect_error(c.correct(p["payment_id"], 1, amount, p["created_at"]), 422, "linked_payment_immutable")
    assert state(world.svc) == before
    assert [r["revision"] for r in world.ada.revisions(cap["payment_id"])] == [1]
    assert world.ada.revisions(st["payments"][0]["payment_id"])[0]["effective_at"] == st["committed_at"]


def test_seeded_linked_payments_are_immutable(svc):
    """D75: a payment that claims a link is linked, whether created by the API or seeded."""
    svc.must_reset(fixture(standard_users(), payments=[
        seeded("p_cap", "ada", "bob", 100, "2026-01-01T00:00:00Z", authorization_id="a_gone"),
        seeded("p_mem", "ada", "bob", 100, "2026-01-01T00:00:00Z", settlement_id="s_gone"),
        seeded("p_free", "ada", "bob", 100, "2026-01-01T00:00:00Z")]))
    ada = svc.client("ada")
    for pid in ("p_cap", "p_mem"):
        expect_error(ada.correct(pid, 1, 50, "2026-01-01T00:00:00Z"), 422, "linked_payment_immutable")
    expect(ada.correct("p_free", 1, 50, "2026-01-01T00:00:00Z"), 201)


# ---------------------------------------------------------------- W16.6 stale revisions

def test_stale_revisions_are_409(paid):
    w = paid
    at = w.p["created_at"]
    for rev in (2, 3, 9, TWO_53):
        expect_error(w.ada.correct(w.pid, rev, 60, at), 409, "stale_revision")
    expect(w.ada.correct(w.pid, 1, 60, at), 201)
    for rev in (1, 3):
        expect_error(w.ada.correct(w.pid, rev, 70, at), 409, "stale_revision")
    expect(w.ada.correct(w.pid, 2, 70, at), 201)
    assert [r["amount"] for r in w.ada.revisions(w.pid)] == [100, 60, 70]


# ---------------------------------------------------------------- W16.7 money

def test_increase_decrease_and_reversal_move_the_difference(world):
    p = expect(world.ada.pay("bob", 100), 201)
    pid, at = p["payment_id"], p["created_at"]
    others = (world.cy.money(), world.dee.money())
    expect(world.ada.correct(pid, 1, 150, at), 201)
    assert (world.ada.balance(), world.bob.balance()) == (9_850, 2_650), "an increase debits the sender"
    expect(world.ada.correct(pid, 2, 40, at), 201)
    assert (world.ada.balance(), world.bob.balance()) == (9_960, 2_540), "a decrease debits the receiver"
    expect(world.ada.correct(pid, 3, 0, at), 201)
    assert (world.ada.balance(), world.bob.balance()) == (10_000, 2_500), "zero reverses the payment"
    expect(world.ada.correct(pid, 4, 100, at), 201)
    assert (world.ada.balance(), world.bob.balance()) == (9_900, 2_600)
    assert (world.cy.money(), world.dee.money()) == others, "I57: no other wallet changes"


def test_the_original_payment_and_responses_stay(paid):
    w = paid
    k = new_key()
    p = expect(w.ada.pay("bob", 70, key=k), 201)
    expect(w.ada.correct(p["payment_id"], 1, 20, p["created_at"]), 201)
    assert expect(w.ada.pay("bob", 70, key=k), 200) == p, "T38: the original idempotent response"
    for c in (w.ada, w.bob):
        feed = [x for x in c.feed() if x["payment_id"] == p["payment_id"]]
        assert feed == [p], "T38: the feed shows the original payment"
    assert len(w.ada.feed()) == 2, "a correction is not a feed payment"
    assert w.cy.feed() == [p], "a public payment is still public, with its original amount"


def test_an_unchanged_amount_moves_nothing_now_but_moves_history(paid):
    """D82: valid; it appends a revision and moves its effect to the new effective_at."""
    w = paid
    r = expect(w.ada.correct(w.pid, 1, 100, "2026-01-01T00:00:00Z", "dated"), 201)
    assert r["amount"] == 100 and r["revision"] == 2
    assert (w.ada.balance(), w.bob.balance()) == (9_900, 2_600)
    assert w.ada.me_at("2026-01-01T00:00:00Z")["total"] == 9_900
    assert w.ada.me_at("2025-12-31T23:59:59.999999Z")["total"] == 10_000
    assert w.bob.me_at("2026-06-01T00:00:00Z")["total"] == 2_600


# ---------------------------------------------------------------- W16.8 funds and history

def test_a_current_debit_above_available_is_insufficient_funds(world):
    c = expect(world.cy.pay("dee", 100), 201)
    before = state(world.svc, [c["payment_id"]])
    expect_error(world.cy.correct(c["payment_id"], 1, 501, c["created_at"]), 409, "insufficient_funds")
    expect(world.cy.authorize("bob", 350), 201)
    before = state(world.svc, [c["payment_id"]])
    expect_error(world.cy.correct(c["payment_id"], 1, 151, c["created_at"]), 409, "insufficient_funds")
    assert state(world.svc, [c["payment_id"]]) == before, "T36: a failure changes nothing"
    expect(world.cy.correct(c["payment_id"], 1, 150, c["created_at"]), 201)
    assert world.cy.money() == (350, 0, 350)


def test_a_decrease_the_receiver_cannot_afford_is_insufficient_funds(world):
    p = expect(world.ada.pay("dee", 500), 201)
    expect(world.dee.pay("cy", 450), 201)
    expect_error(world.ada.correct(p["payment_id"], 1, 400, p["created_at"]), 409, "insufficient_funds")
    expect(world.ada.correct(p["payment_id"], 1, 450, p["created_at"]), 201)
    assert world.dee.money() == (0, 0, 0)


@pytest.fixture
def spent(world):
    """Ada paid dee 500 (t1); dee then paid cy 500 (t2). Dee holds 0."""
    p1 = expect(world.ada.pay("dee", 500), 201)
    p2 = expect(world.dee.pay("cy", 500), 201)
    world.p1, world.p2 = p1, p2
    return world


def test_an_earlier_effective_at_before_the_money_arrived_is_historical_overdraft(spent):
    w = spent
    t1 = w.p1["created_at"]
    before = state(w.svc, [w.p1["payment_id"], w.p2["payment_id"]])
    k = new_key()
    expect_error(w.dee.correct(w.p2["payment_id"], 1, 500, shifted(t1, -1), key=k), 409, "historical_overdraft")
    expect_error(w.dee.correct(w.p2["payment_id"], 1, 500, EPOCH, key=k), 409, "historical_overdraft")
    assert state(w.svc, [w.p1["payment_id"], w.p2["payment_id"]]) == before, "T36"
    r = expect(w.dee.correct(w.p2["payment_id"], 1, 500, t1, key=k), 201)
    assert r["effective_at"] == t1, "movements at one instant are combined: +500 and -500 at t1 is 0"
    assert w.dee.me_at(t1)["total"] == 0 and w.dee.me_at(shifted(t1, -1))["total"] == 0


def test_a_later_effective_at_after_the_receiver_spent_it_is_historical_overdraft(spent):
    w = spent
    t2 = w.p2["created_at"]
    # A write first, so the service's now is a millisecond past t2 and t2 + 1 us is not in the future (D81).
    w.ada.service_now("bob")
    expect_error(w.ada.correct(w.p1["payment_id"], 1, 500, shifted(t2, 1)), 409, "historical_overdraft")
    later = w.ada.service_now("bob")
    expect_error(w.ada.correct(w.p1["payment_id"], 1, 500, later), 409, "historical_overdraft")
    expect(w.ada.correct(w.p1["payment_id"], 1, 500, t2), 201)
    assert [r["effective_at"] for r in w.ada.revisions(w.p1["payment_id"])][-1] == t2


def test_an_increase_in_the_past_beyond_the_balance_then_is_historical_overdraft(world):
    """Dee had 500 when she paid cy 100; a later top-up makes 900 affordable now but not then."""
    expect(world.ada.pay("dee", 500), 201)
    p = expect(world.dee.pay("cy", 100), 201)
    expect(world.ada.pay("dee", 1_000), 201)
    expect_error(world.dee.correct(p["payment_id"], 1, 900, p["created_at"]), 409, "historical_overdraft")
    expect(world.dee.correct(p["payment_id"], 1, 500, p["created_at"]), 201)
    assert world.dee.money() == (1_000, 1_000, 0)


def test_a_past_hold_making_available_negative_is_historical_overdraft(world):
    p1 = expect(world.ada.pay("dee", 500), 201)
    a = expect(world.dee.authorize("cy", 500), 201)
    t2 = a["created_at"]
    assert world.dee.money() == (500, 0, 500)
    # A write first, so the service's now is a millisecond past t2 and t2 + 1 us is not in the future (D81).
    world.ada.service_now("bob")
    expect_error(world.ada.correct(p1["payment_id"], 1, 500, shifted(t2, 1)), 409, "historical_overdraft")
    expect(world.ada.correct(p1["payment_id"], 1, 500, t2), 201)
    assert world.dee.money_at(t2) == (500, 0, 500)


def test_insufficient_funds_outranks_historical_overdraft(spent):
    w = spent
    # A write first, so the service's now is a millisecond past t2 and t2 + 1 us is not in the future (D81).
    w.ada.service_now("bob")
    expect_error(w.ada.correct(w.p1["payment_id"], 1, 100, shifted(w.p2["created_at"], 1)), 409, "insufficient_funds")


def test_the_2_53_guard_on_the_credit(svc):
    svc.must_reset(fixture([user("ada", 1_000), user("bob", TWO_53 - 10)]))
    p = expect(svc.client("ada").pay("bob", 5), 201)                 # bob holds 2^53 - 5
    expect_error(svc.client("ada").correct(p["payment_id"], 1, 11, p["created_at"]), 422, "validation_failed")
    expect(svc.client("ada").correct(p["payment_id"], 1, 10, p["created_at"]), 201)
    assert svc.client("bob").balance() == TWO_53


# ---------------------------------------------------------------- W16.9 history reads

def test_history_follows_the_latest_revision(world):
    p0 = expect(world.ada.pay("bob", 10), 201)
    p = expect(world.ada.pay("bob", 100), 201)
    pid, c = p["payment_id"], p["created_at"]
    me = uid(world.svc, "ada")
    snap = read_statement(world.ada, me)
    r = expect(world.ada.correct(pid, 1, 60, "2026-01-01T00:00:00Z", "dated and reduced"), 201)
    ada = world.ada
    assert ada.me_at("2025-12-31T23:59:59.999999999Z")["total"] == 10_000
    assert ada.me_at("2026-01-01T00:00:00Z")["total"] == 9_940
    assert ada.me_at(shifted(p0["created_at"], -1))["total"] == 9_940
    assert ada.me_at(c)["total"] == 9_930
    k_before = shifted(r["recorded_at"], -1)
    assert ada.me_at(None, k_before)["total"] == 9_890, "known before the correction: revision 1"
    assert ada.me_at("2026-06-01T00:00:00Z", k_before)["total"] == 10_000
    assert ada.me_at(None, r["recorded_at"])["total"] == 9_930
    st = read_statement(ada, me)
    assert st.ids() == [pid, p0["payment_id"]], "T42: ordered by the selected effective_at"
    e = st.entries[0]
    assert (e["revision"], e["effective_at"], e["recorded_at"], e["delta"], e["payment"]["amount"]) == \
        (2, "2026-01-01T00:00:00Z", r["recorded_at"], -60, 60), "T43: the selected revision"
    assert {k: v for k, v in e["payment"].items() if k != "amount"} == \
        {k: v for k, v in p.items() if k != "amount"}
    old = read_statement(ada, me, known_at=k_before)
    assert old.ids() == [p0["payment_id"], pid] and old.entries[1]["revision"] == 1 and old.deltas() == [-10, -100]
    at = read_statement(ada, me, known_at=r["recorded_at"])
    assert at.ids() == [pid, p0["payment_id"]] and at.entries[0]["revision"] == 2, \
        "W16.9 (critic B3): known_at exactly at the correction's recorded_at selects the new revision"
    inside = read_statement(ada, me, **{"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"})
    assert inside.ids() == [pid], "T52: a correction moves a payment into a window"
    out = read_statement(ada, me, **{"from": p0["created_at"]})
    assert out.ids() == [p0["payment_id"]], "T52: and out of one"
    assert page_snapshot(ada, me, snap.snapshot)[0] == snap.entries, "T47: an old snapshot pages its old result"


def test_a_zero_amount_revision_is_an_entry_with_zero_delta(paid):
    w = paid
    expect(w.ada.correct(w.pid, 1, 0, w.p["created_at"]), 201)
    st = read_statement(w.bob, uid(w.svc, "bob"))
    assert [(e["payment"]["payment_id"], e["delta"], e["revision"], e["payment"]["amount"]) for e in st.entries] == \
        [(w.pid, 0, 2, 0)], "T44: one entry, the selected revision, zero delta"
    st = read_statement(w.ada, uid(w.svc, "ada"))
    assert [(e["delta"], e["revision"], e["payment"]["amount"]) for e in st.entries] == [(0, 2, 0)]


# ---------------------------------------------------------------- W16.10 revisions read

def test_revisions_read_permissions(paid):
    w = paid
    assert w.ada.revisions(w.pid) == w.bob.revisions(w.pid)
    expect_error(w.cy.revisions_resp(w.pid), 404, "not_found")
    pub = expect(w.ada.pay("bob", 5, visibility="public"), 201)
    assert pub in w.cy.feed()
    expect_error(w.cy.revisions_resp(pub["payment_id"]), 404, "not_found")    # T39: even a public payment
    expect_error(w.ada.revisions_resp("p_nope"), 404, "not_found")
    expect_error(w.svc.api().revisions_resp(w.pid), 401, "unauthenticated")
    expect_error(w.svc.api().revisions_resp("p_nope"), 401, "unauthenticated")
    expect_error(w.svc.api("not-a-token").revisions_resp(w.pid), 401, "unauthenticated")


def test_one_instant_is_combined_with_the_debit_created_first(svc):
    """I58, stage-3 "the combined effect of all movements at that instant" (critic K12): dee's debit is created
    before the credit she moves it onto, so checking after each event instead of each instant would refuse it."""
    svc.must_reset(fixture([user("ada", 10_000), user("bob", 2_500), user("cy", 500), user("dee", 300)]))
    dee, ada = svc.client("dee"), svc.client("ada")
    debit = expect(dee.pay("cy", 300), 201)
    credit = expect(ada.pay("dee", 500), 201)
    t = credit["created_at"]
    r = expect(dee.correct(debit["payment_id"], 1, 500, t), 201)
    assert r["effective_at"] == t
    assert dee.me_at(t)["total"] == 300 and dee.me_at(shifted(t, -1))["total"] == 300
    assert dee.money() == (300, 300, 0)


def test_no_clock_tolerance_on_effective_at(paid):
    """D81 (critic K25b): 200 ms after a fresh service time mark is later than now. A slow host that accepts
    it must still have recorded it at or after its effective_at (effective_at <= now <= recorded_at)."""
    w = paid
    for n in range(3):
        mark = w.ada.service_now("cy")
        at = shifted(mark, 200_000, digits=3)
        r = w.ada.correct(w.pid, 1 + sum(1 for x in w.ada.revisions(w.pid)[1:]), 50 + n, at)
        if r.status_code == 201:
            assert instant(r.json()["recorded_at"]) >= instant(at), f"D81: accepted before its effective_at: {r.json()}"
        else:
            expect_error(r, 422, "validation_failed")
