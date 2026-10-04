"""W19.1-W19.7 — `POST /payments/{id}/refunds` and `refund_of` (stage-4 "Refunds and corrected history", the
refund sentence of the last section; PLAN 3.2, 3.3, 3.5-3.7, 3.9, D89-D94, D104). I1, I2, I62, I66, I68-I71,
I75-I77.

The idempotency scenarios of the ninth path run in test_w2_idempotency.py (`Refunds`); concurrency in
test_w19_concurrency.py. Every instant comes from the service (W18.5) or is a seeded past instant.
"""
from __future__ import annotations

import pytest

from support import (PLAN_TS, TWO_53, check_authorization, check_payment, check_request, expect, expect_error, fixture,
                     instant, is_int, new_key, page_snapshot, read_statement, shifted, standard_users, user)
from test_w14_history import seeded
from test_w7_expiry import sleep_past

pytestmark = pytest.mark.item(19)


def uid(svc, h) -> str:
    svc.client(h)
    return svc.accounts[h].user_id


def state(svc, pids=()) -> dict:
    """Everything a refused refund (or batch) must leave alone: money, feeds, requests, authorizations, statements,
    and each named payment's revisions as every account reads them."""
    out = {}
    for h in svc.accounts:
        c = svc.client(h)
        body = expect(c.statement(limit=200), 200)
        out[h] = (c.money(), c.feed(), c.requests(), c.auths(),
                  (body["opening_balance"], body["closing_balance"],
                   [(e["payment"]["payment_id"], e["revision"], e["delta"]) for e in body["entries"]]))
    for pid in pids:
        out[pid] = [svc.client(h).revisions_resp(pid).text for h in svc.accounts]
    return out


@pytest.fixture
def paid(world):
    """Ada paid bob 1000, privately, with the note "dinner". Ada 9000, bob 3500."""
    p = expect(world.ada.pay("bob", 1_000, note="dinner", visibility="private"), 201)
    world.p, world.pid = p, p["payment_id"]
    return world


# ---------------------------------------------------------------- W19.1 the refund payment

def test_a_refund_is_a_new_payment_in_the_opposite_direction(paid):
    """I68, D91: from the receiver to the sender, refund_of the target, no request, authorization or settlement,
    the target's note and visibility."""
    w = paid
    r = check_payment(expect(w.bob.refund(w.pid, 200), 201),
                      from_user_id="u_bob", from_handle="bob", to_user_id="u_ada", to_handle="ada", amount=200,
                      currency="EUR", note="dinner", visibility="private", request_id=None, settlement_id=None,
                      authorization_id=None, refund_of=w.pid)
    assert r["payment_id"] != w.pid
    assert PLAN_TS.match(r["created_at"]) and instant(r["created_at"]) > instant(w.p["created_at"]), \
        f"PLAN 3.5: a refund issues its own created_at: {r}"
    assert w.ada.money() == (9_200, 9_200, 0) and w.bob.money() == (3_300, 3_300, 0), "I70: its amount, once"
    assert w.cy.money() == (500, 500, 0) and w.dee.money() == (0, 0, 0)


def test_a_refund_is_later_than_every_earlier_timestamp(paid):
    w = paid
    q = expect(w.ada.pay("bob", 10), 201)
    c = expect(w.ada.correct(q["payment_id"], 1, 5, q["created_at"]), 201)
    rq = expect(w.cy.ask("bob", 1), 201)
    r = expect(w.bob.refund(w.pid, 1), 201)
    for t in (w.p["created_at"], q["created_at"], c["recorded_at"], rq["created_at"]):
        assert instant(r["created_at"]) > instant(t), f"D67: {r['created_at']} is not after {t}"


@pytest.mark.parametrize("visibility", ["private", "public"])
def test_the_feed_shows_a_refund_under_the_feed_rule(world, visibility):
    """I77: the refund is a payment with the target's visibility, newest first."""
    p = expect(world.ada.pay("bob", 300, note="tickets", visibility=visibility), 201)
    r = expect(world.bob.refund(p["payment_id"], 100), 201)
    for c in (world.ada, world.bob):
        assert c.feed() == [r, p], "both parties see the refund, then its target, each as created"
    third = [x["payment_id"] for x in world.cy.feed()]
    assert third == ([r["payment_id"], p["payment_id"]] if visibility == "public" else []), third


def test_a_replay_returns_the_original_body_after_later_refunds_and_corrections(paid):
    w = paid
    k = new_key()
    first = expect(w.bob.refund(w.pid, 100, key=k), 201)
    expect(w.bob.refund(w.pid, 50), 201)
    expect(w.ada.correct(w.pid, 1, 900, w.p["created_at"]), 201)
    before = state(w.svc, [w.pid])
    for _ in range(2):
        assert expect(w.bob.refund(w.pid, 100, key=k), 200) == first
    assert state(w.svc, [w.pid]) == before, "a replay moves nothing"
    expect_error(w.bob.refund(w.pid, 101, key=k), 409, "idempotency_key_reuse")


def test_keys_are_scoped_by_user_and_path(world):
    """I19: one key string on the payments path, on two payments' refund paths and by another user."""
    k = new_key()
    p1 = expect(world.ada.pay("bob", 100, key=k), 201)
    p2 = expect(world.ada.pay("bob", 100), 201)
    q = expect(world.cy.pay("dee", 100), 201)
    expect(world.bob.pay("cy", 1, key=k), 201)
    r1 = expect(world.bob.refund(p1["payment_id"], 10, key=k), 201)
    r2 = expect(world.bob.refund(p2["payment_id"], 20, key=k), 201)
    r3 = expect(world.dee.refund(q["payment_id"], 30, key=k), 201)
    assert (r1["refund_of"], r2["refund_of"], r3["refund_of"]) == (p1["payment_id"], p2["payment_id"], q["payment_id"])
    assert world.ada.balance() == 10_000 - 200 + 30
    assert world.cy.balance() == 500 - 100 + 1 + 30


def test_a_refused_refund_claims_no_key(paid):
    """I18, I70: a refused refund claims nothing; the key then works for another body."""
    w = paid
    k = new_key()
    expect_error(w.bob.refund(w.pid, 1_001, key=k), 422, "refund_exceeds_payment")
    expect_error(w.bob.refund(w.pid, 0, key=k), 422, "validation_failed")
    expect(w.bob.pay("dee", 3_400), 201)                          # bob holds 100
    expect_error(w.bob.refund(w.pid, 101, key=k), 409, "insufficient_funds")
    r = expect(w.bob.refund(w.pid, 100, key=k), 201)
    assert expect(w.bob.refund(w.pid, 100, key=k), 200) == r
    assert w.bob.money() == (0, 0, 0)


# ---------------------------------------------------------------- W19.2 validation and precedence

INVALID_AMOUNTS = {
    "missing": {}, "null": {"amount": None}, "true": {"amount": True}, "false": {"amount": False},
    "string": {"amount": "5"}, "1.5": {"amount": 1.5}, "0": {"amount": 0}, "-1": {"amount": -1},
    "1000000001": {"amount": 1_000_000_001}, "1e300": {"amount": 1e300}, "array": {"amount": [5]},
    "object": {"amount": {"value": 5}},
}


@pytest.mark.parametrize("body", INVALID_AMOUNTS.values(), ids=INVALID_AMOUNTS.keys())
def test_an_invalid_amount_is_422_and_changes_nothing(paid, body):
    """D89: the payment amount rules; the refused key stays free."""
    w = paid
    before = state(w.svc, [w.pid])
    k = new_key()
    expect_error(w.bob.refund(w.pid, body=body, key=k), 422, "validation_failed")
    assert state(w.svc, [w.pid]) == before
    expect(w.bob.refund(w.pid, 5, key=k), 201)


@pytest.mark.parametrize("raw, amount", [('{"amount": 1.0}', 1), ('{"amount": 1e3}', 1_000),
                                         ('{"amount": 2.50E2}', 250)])
def test_integral_number_forms_are_valid(paid, raw, amount):
    r = expect(paid.bob.post(f"/payments/{paid.pid}/refunds", content=raw.encode(), key=new_key()), 201)
    assert is_int(r["amount"]) and r["amount"] == amount


@pytest.mark.parametrize("raw, status, code", [
    (b"{nope", 400, "malformed_request"), (b"[]", 400, "malformed_request"), (b'"x"', 400, "malformed_request"),
    (b"", 400, "malformed_request"), (b"null", 400, "malformed_request"),
    (b'{"amount": 5, "x": "\xff"}', 400, "malformed_request"), (b"{}", 422, "validation_failed")])
def test_body_shape(paid, raw, status, code):
    expect_error(paid.bob.post(f"/payments/{paid.pid}/refunds", content=raw, key=new_key()), status, code)


def test_precedence_of_the_common_steps(paid):
    """PLAN 3.9 steps 1-7: route, 401, key, body, claimed key, fields, then the unknown payment."""
    w = paid
    path = f"/payments/{w.pid}/refunds"
    anon = w.svc.api()
    expect_error(anon.post(path, content=b"{nope"), 401, "unauthenticated")
    expect_error(anon.post("/payments/p_nope/refunds", json={"amount": 1}), 401, "unauthenticated")
    expect_error(w.bob.post(path, content=b"{nope"), 400, "missing_idempotency_key")
    expect_error(w.bob.post(path, content=b"{nope", headers={"Idempotency-Key": ""}), 400, "missing_idempotency_key")
    expect_error(w.bob.post(path, content=b"{nope", key="k" * 256), 422, "validation_failed")
    expect_error(w.bob.post(path, content=b"{nope", key=new_key()), 400, "malformed_request")
    k = new_key()
    expect(w.bob.refund(w.pid, 10, key=k), 201)
    expect_error(w.bob.refund(w.pid, 0, key=k), 409, "idempotency_key_reuse")
    expect_error(w.bob.refund("p_nope", 0), 422, "validation_failed")        # fields before 404
    expect_error(w.cy.refund(w.pid, 0), 422, "validation_failed")            # fields before 403
    expect_error(w.bob.refund("p_nope", 5), 404, "not_found")


def test_unknown_methods_and_paths_are_404(paid):
    w = paid
    expect_error(w.bob.get(f"/payments/{w.pid}/refunds"), 404, "not_found")
    expect_error(w.bob.request("DELETE", f"/payments/{w.pid}/refunds"), 404, "not_found")
    expect_error(w.bob.post(f"/payments/{w.pid}/refund", json={"amount": 1}, key=new_key()), 404, "not_found")
    expect_error(w.bob.post(f"/payments/{w.pid}/refunds/x", json={"amount": 1}, key=new_key()), 404, "not_found")


def test_who_may_refund(paid):
    """I71, D90: only the receiver; the sender and third parties 403 whatever the visibility; unknown 404."""
    w = paid
    before = state(w.svc, [w.pid])
    expect_error(w.ada.refund(w.pid, 10), 403, "forbidden")                   # the sender
    expect_error(w.cy.refund(w.pid, 10), 403, "forbidden")                    # a third party, private payment
    expect_error(w.dee.refund(w.pid, 1_000_000_000), 403, "forbidden")        # 403 before the cap and the funds
    expect_error(w.bob.refund("p_does_not_exist", 10), 404, "not_found")
    expect_error(w.svc.api().refund(w.pid, 10), 401, "unauthenticated")
    expect_error(w.svc.api("not-a-token").refund(w.pid, 10), 401, "unauthenticated")
    assert state(w.svc, [w.pid]) == before
    pub = expect(w.ada.pay("bob", 10, visibility="public"), 201)
    expect_error(w.cy.refund(pub["payment_id"], 1), 403, "forbidden")        # a public payment too


def test_a_refund_cannot_be_refunded(paid):
    """F10, I71: invalid_refund_target, after 403 and before the cap and the funds."""
    w = paid
    r = expect(w.bob.refund(w.pid, 300), 201)
    before = state(w.svc, [w.pid, r["payment_id"]])
    expect_error(w.ada.refund(r["payment_id"], 100), 422, "invalid_refund_target")   # ada received the refund
    expect_error(w.ada.refund(r["payment_id"], 1_000_000_000), 422, "invalid_refund_target")
    expect_error(w.bob.refund(r["payment_id"], 100), 403, "forbidden")               # the refund's sender
    expect_error(w.cy.refund(r["payment_id"], 100), 403, "forbidden")
    assert state(w.svc, [w.pid, r["payment_id"]]) == before


def test_refunds_together_may_reach_the_amount_but_not_pass_it(paid):
    """F9, I69: the cumulative cap is the latest revision's amount; exactly reaching it is allowed."""
    w = paid
    expect(w.bob.refund(w.pid, 600), 201)
    before = state(w.svc, [w.pid])
    expect_error(w.bob.refund(w.pid, 401), 422, "refund_exceeds_payment")
    assert state(w.svc, [w.pid]) == before
    expect(w.bob.refund(w.pid, 400), 201)
    expect_error(w.bob.refund(w.pid, 1), 422, "refund_exceeds_payment")
    assert w.ada.money() == (10_000, 10_000, 0) and w.bob.money() == (2_500, 2_500, 0)


def test_the_cap_comes_before_the_funds(paid):
    w = paid
    expect(w.bob.pay("dee", 3_400), 201)                          # bob holds 100
    expect_error(w.bob.refund(w.pid, 1_001), 422, "refund_exceeds_payment")
    expect_error(w.bob.refund(w.pid, 101), 409, "insufficient_funds")
    expect(w.bob.refund(w.pid, 100), 201)
    assert w.bob.money() == (0, 0, 0)


def test_held_funds_are_not_available_for_a_refund(paid):
    """F13, I70: the receiver's available funds."""
    w = paid
    expect(w.bob.authorize("cy", 3_000), 201)                     # bob: total 3500, held 3000, available 500
    before = state(w.svc, [w.pid])
    expect_error(w.bob.refund(w.pid, 501), 409, "insufficient_funds")
    assert state(w.svc, [w.pid]) == before
    expect(w.bob.refund(w.pid, 500), 201)
    assert w.bob.money() == (3_000, 0, 3_000)


def test_the_2_53_guard_on_the_credit(svc):
    """PLAN 3.9 step 12 (D19): the refund would put its receiver (the target's sender) above 2^53."""
    svc.must_reset(fixture([user("ada", TWO_53 - 5), user("bob", 0), user("cy", 100)]))
    ada, bob, cy = svc.client("ada"), svc.client("bob"), svc.client("cy")
    p = expect(ada.pay("bob", 5), 201)                            # ada: 2^53 - 10
    expect(cy.pay("ada", 8), 201)                                 # ada: 2^53 - 2
    expect_error(bob.refund(p["payment_id"], 3), 422, "validation_failed")
    expect(bob.refund(p["payment_id"], 2), 201)
    assert ada.balance() == TWO_53


def test_unknown_body_fields_are_ignored(paid):
    w = paid
    r = expect(w.bob.refund(w.pid, body={"amount": 5, "refund_of": "p_other", "to_handle": "cy", "note": "zz",
                                         "visibility": "public", "payment_id": "p_mine", "request_id": "rq_x",
                                         "settlement_id": "s_x"}), 201)
    check_payment(r, to_handle="ada", note="dinner", visibility="private", refund_of=w.pid, request_id=None,
                  settlement_id=None, amount=5)
    assert r["payment_id"] != "p_mine"


def test_the_path_parameter_is_decoded(svc):
    """PLAN 3.2: decoded like the other payment routes."""
    svc.must_reset(fixture(standard_users(), payments=[seeded("p_ｚ", "ada", "bob", 50, "2026-01-01T00:00:00Z")]))
    r = expect(svc.client("bob").post("/payments/p_%EF%BD%9A/refunds", json={"amount": 5}, key=new_key()), 201)
    assert r["refund_of"] == "p_ｚ"


# ---------------------------------------------------------------- W19.3 targets

def test_a_request_payment_is_refundable_and_the_request_stays_paid(world):
    rq = expect(world.bob.ask("ada", 300, note="taxi"), 201)
    k = new_key()
    p = expect(world.ada.pay_request(rq["request_id"], {"visibility": "private"}, key=k), 201)
    lists = (world.ada.requests(), world.bob.requests())
    check_payment(expect(world.bob.refund(p["payment_id"], 120), 201), refund_of=p["payment_id"], request_id=None,
                  note=p["note"], visibility="private", from_handle="bob", to_handle="ada", amount=120)
    assert (world.ada.requests(), world.bob.requests()) == lists, "I70: the request does not change"
    got = [x for x in world.ada.requests() if x["request_id"] == rq["request_id"]][0]
    check_request(got, status="paid", payment_id=p["payment_id"], amount=300)
    assert expect(world.ada.pay_request(rq["request_id"], {"visibility": "private"}, key=k), 200) == p
    expect_error(world.ada.pay_request(rq["request_id"], {"visibility": "private"}), 409, "request_not_pending")
    assert world.ada.balance() == 10_000 - 300 + 120


def test_a_capture_is_refundable_and_its_open_authorization_does_not_change(world):
    """W19.4 (critic plan review 9): a refund of a nonfinal capture while its hold is open changes neither the
    authorization nor the payer's held funds nor the hold's history."""
    a = expect(world.ada.authorize("bob", 500, note="deposit"), 201)
    aid = a["authorization_id"]
    cap = expect(world.bob.capture(aid, {"amount": 300, "final": False}), 201)
    views = (world.ada.auth(aid), world.bob.auth(aid))
    assert views[0]["closed_at"] is None and views[0]["payment_ids"] == [cap["payment_id"]]
    assert world.ada.money() == (9_700, 9_500, 200)
    marks = [shifted(a["created_at"], -1), a["created_at"], shifted(cap["created_at"], -1), cap["created_at"]]
    history = [world.ada.money_at(t) for t in marks]
    assert history == [(10_000, 10_000, 0), (10_000, 9_500, 500), (10_000, 9_500, 500), (9_700, 9_500, 200)]
    r = check_payment(expect(world.bob.refund(cap["payment_id"], 300), 201), refund_of=cap["payment_id"],
                      authorization_id=None, note="deposit", from_handle="bob", to_handle="ada", amount=300)
    assert (world.ada.auth(aid), world.bob.auth(aid)) == views, \
        "I70: status, captured_amount, remaining_amount, closed_at and payment_ids stay"
    assert world.ada.money() == (10_000, 9_800, 200), "the hold is unchanged"
    assert [world.ada.money_at(t) for t in marks] == history, "D93: the hold's history is unchanged"
    assert world.ada.money_at(shifted(r["created_at"], -1)) == (9_700, 9_500, 200)
    assert world.ada.money_at(r["created_at"]) == (10_000, 9_800, 200)
    expect(world.bob.capture(aid, {"amount": 200}), 201)
    expect_error(world.bob.capture(aid, {"amount": 1}), 409, "authorization_not_open")


def test_refunding_a_final_capture_leaves_the_authorization_closed(world):
    a = expect(world.ada.authorize("bob", 500), 201)
    aid = a["authorization_id"]
    cap = expect(world.bob.capture(aid, {"amount": 200}), 201)
    closed = check_authorization(world.ada.auth(aid), status="captured", captured_amount=200, remaining_amount=0)
    expect(world.bob.refund(cap["payment_id"], 200), 201)
    assert world.ada.auth(aid) == closed, "D93: a refund never reopens an authorization"
    assert world.ada.money() == (10_000, 10_000, 0)
    expect_error(world.bob.capture(aid, {"amount": 1}), 409, "authorization_not_open")


def test_refunding_a_capture_of_a_voided_hold_restores_no_hold(world):
    a = expect(world.ada.authorize("bob", 500), 201)
    aid = a["authorization_id"]
    cap = expect(world.bob.capture(aid, {"amount": 200, "final": False}), 201)
    expect(world.ada.void(aid), 200)
    voided = check_authorization(world.ada.auth(aid), status="voided", captured_amount=200, remaining_amount=0)
    expect(world.bob.refund(cap["payment_id"], 150), 201)
    assert world.ada.auth(aid) == voided
    assert world.ada.money() == (9_950, 9_950, 0), "I70: the released hold stays released"


def test_refunding_a_capture_of_an_expired_hold_restores_no_hold(svc):
    svc.must_reset(fixture(standard_users(), ttl=2))
    ada, bob = svc.client("ada"), svc.client("bob")
    a = expect(ada.authorize("bob", 500), 201)
    aid = a["authorization_id"]
    cap = expect(bob.capture(aid, {"amount": 100, "final": False}), 201)
    sleep_past(a["expires_at"])
    expired = check_authorization(ada.auth(aid), status="expired", captured_amount=100, remaining_amount=0)
    expect(bob.refund(cap["payment_id"], 100), 201)
    assert ada.auth(aid) == expired
    assert ada.money() == (10_000, 10_000, 0)


def test_a_settlement_member_is_refundable_and_stays_a_member(world):
    """F41, I75: a refund of a member is not a member; the settlement and its replay never change."""
    transfers = [{"from_handle": "ada", "to_handle": "cy", "amount": 100},
                 {"from_handle": "bob", "to_handle": "dee", "amount": 50}]
    k = new_key()
    st = expect(world.ada.settle(transfers, key=k), 201)
    m = st["payments"][0]
    r = check_payment(expect(world.cy.refund(m["payment_id"], 100), 201), refund_of=m["payment_id"],
                      settlement_id=None, from_handle="cy", to_handle="ada", amount=100)
    assert expect(world.ada.settle(transfers, key=k), 200) == st, "I75: the settlement's replay is unchanged"
    for c in (world.ada, world.cy):
        members = [p for p in c.feed() if p["settlement_id"] == st["settlement_id"]]
        assert sorted(members, key=lambda p: p["payment_id"]) == \
            sorted([p for p in st["payments"] if p in members], key=lambda p: p["payment_id"])
        assert m in members and r not in members
    assert world.cy.money() == (500, 500, 0) and world.ada.money() == (10_000, 10_000, 0)


def test_a_seeded_payment_is_refundable(svc):
    svc.must_reset(fixture(standard_users(), payments=[
        seeded("p_s", "ada", "bob", 400, "2026-02-01T08:00:00+01:00", note="seeded", visibility="private")]))
    bob = svc.client("bob")
    check_payment(expect(bob.refund("p_s", 400), 201), refund_of="p_s", note="seeded", visibility="private",
                  to_handle="ada", amount=400)
    expect_error(bob.refund("p_s", 1), 422, "refund_exceeds_payment")
    assert bob.money() == (2_100, 2_100, 0) and svc.client("ada").money() == (10_400, 10_400, 0)


def test_the_cap_follows_the_current_corrected_amount(paid):
    """D92: the latest revision's amount, down and up again."""
    w = paid
    expect(w.ada.correct(w.pid, 1, 600, w.p["created_at"]), 201)
    expect_error(w.bob.refund(w.pid, 601), 422, "refund_exceeds_payment")
    expect(w.bob.refund(w.pid, 250), 201)
    expect(w.ada.correct(w.pid, 2, 1_200, w.p["created_at"]), 201)
    expect_error(w.bob.refund(w.pid, 951), 422, "refund_exceeds_payment")
    expect(w.bob.refund(w.pid, 950), 201)
    assert w.ada.money() == (10_000, 10_000, 0)


def test_the_cap_ignores_effective_time(paid):
    """D92: a correction dated before the payment still sets the cap at once."""
    w = paid
    expect(w.ada.correct(w.pid, 1, 300, "2026-01-01T00:00:00Z"), 201)
    expect_error(w.bob.refund(w.pid, 301), 422, "refund_exceeds_payment")
    expect(w.bob.refund(w.pid, 300), 201)


def test_after_a_correction_to_zero_nothing_is_refundable(paid):
    w = paid
    expect(w.ada.correct(w.pid, 1, 0, w.p["created_at"]), 201)
    expect_error(w.bob.refund(w.pid, 1), 422, "refund_exceeds_payment")


# ---------------------------------------------------------------- W19.4 originals stay

def test_the_refunded_payment_stays_as_it_was(world):
    """I75: its feed item, its replay and its revisions."""
    k = new_key()
    p = expect(world.ada.pay("bob", 700, note="rent", key=k), 201)
    revs = world.ada.revisions(p["payment_id"])
    expect(world.bob.refund(p["payment_id"], 300), 201)
    expect(world.bob.refund(p["payment_id"], 100), 201)
    assert expect(world.ada.pay("bob", 700, note="rent", key=k), 200) == p
    for c in (world.ada, world.bob, world.cy):
        assert [x for x in c.feed() if x["payment_id"] == p["payment_id"]] == [p]
    assert world.ada.revisions(p["payment_id"]) == revs == world.bob.revisions(p["payment_id"])


# ---------------------------------------------------------------- W19.5 refund_of: null elsewhere

def test_every_other_payment_has_refund_of_null(svc):
    """F15, I68: POST /payments, request payments, settlement members, captures, seeded payments, the feed,
    statement entries, and their replays."""
    svc.must_reset(fixture(standard_users(), operators=["u_ada"],
                           payments=[seeded("p_s", "bob", "cy", 10, "2026-01-01T00:00:00Z")]))
    ada, bob = svc.client("ada"), svc.client("bob")
    bodies = []
    k = new_key()
    bodies += [expect(ada.pay("bob", 100, key=k), 201), expect(ada.pay("bob", 100, key=k), 200)]
    rq = expect(bob.ask("ada", 50), 201)["request_id"]
    k = new_key()
    bodies += [expect(ada.pay_request(rq, key=k), 201), expect(ada.pay_request(rq, key=k), 200)]
    t = [{"from_handle": "ada", "to_handle": "cy", "amount": 5}, {"from_handle": "cy", "to_handle": "dee", "amount": 1}]
    k = new_key()
    bodies += expect(ada.settle(t, key=k), 201)["payments"] + expect(ada.settle(t, key=k), 200)["payments"]
    aid = expect(ada.authorize("bob", 100), 201)["authorization_id"]
    k = new_key()
    bodies += [expect(bob.capture(aid, {}, key=k), 201), expect(bob.capture(aid, {}, key=k), 200)]
    r = expect(bob.refund(bodies[0]["payment_id"], 10), 201)
    for h in svc.accounts:
        c = svc.client(h)
        bodies += [p for p in c.feed() if p["payment_id"] != r["payment_id"]]
        bodies += [e["payment"] for e in read_statement(c, uid(svc, h)).entries
                   if e["payment"]["payment_id"] != r["payment_id"]]
    assert "p_s" in {b["payment_id"] for b in bodies}
    for b in bodies:
        check_payment(b, refund_of=None)


# ---------------------------------------------------------------- W19.6 single corrections

def test_a_refund_cannot_be_corrected(paid):
    """F17, I62: linked_payment_immutable for its sender, after 403 and before stale_revision."""
    w = paid
    r = expect(w.bob.refund(w.pid, 300), 201)
    before = state(w.svc, [w.pid, r["payment_id"]])
    for amount in (300, 0, 301):
        expect_error(w.bob.correct(r["payment_id"], 1, amount, r["created_at"]), 422, "linked_payment_immutable")
    expect_error(w.bob.correct(r["payment_id"], 5, 300, r["created_at"]), 422, "linked_payment_immutable")
    expect_error(w.ada.correct(r["payment_id"], 1, 0, r["created_at"]), 403, "forbidden")
    assert state(w.svc, [w.pid, r["payment_id"]]) == before
    assert [x["revision"] for x in w.bob.revisions(r["payment_id"])] == [1]


def test_a_correction_cannot_go_below_the_refunded_total(paid):
    """F18, I69, D94: below is 422 refund_exceeds_payment, equal is allowed, and then nothing is refundable."""
    w = paid
    expect(w.bob.refund(w.pid, 300), 201)
    expect(w.bob.refund(w.pid, 100), 201)
    before = state(w.svc, [w.pid])
    expect_error(w.ada.correct(w.pid, 1, 399, w.p["created_at"]), 422, "refund_exceeds_payment")
    expect_error(w.ada.correct(w.pid, 1, 0, w.p["created_at"]), 422, "refund_exceeds_payment")
    assert state(w.svc, [w.pid]) == before
    expect(w.ada.correct(w.pid, 1, 400, w.p["created_at"]), 201)
    expect_error(w.bob.refund(w.pid, 1), 422, "refund_exceeds_payment")
    assert w.ada.money() == (10_000, 10_000, 0) and w.bob.money() == (2_500, 2_500, 0)


def test_the_correction_order_with_refunds(paid):
    """D94: stale_revision, then refund_exceeds_payment, then insufficient_funds."""
    w = paid
    expect(w.bob.refund(w.pid, 500), 201)                         # ada 9500, bob 3000
    expect(w.bob.pay("dee", 3_000), 201)                          # bob holds 0
    at = w.p["created_at"]
    expect_error(w.ada.correct(w.pid, 2, 100, at), 409, "stale_revision")
    expect_error(w.ada.correct(w.pid, 1, 100, at), 422, "refund_exceeds_payment")
    expect_error(w.ada.correct(w.pid, 1, 500, at), 409, "insufficient_funds")    # debits bob 500
    expect(w.ada.correct(w.pid, 1, 1_000, at), 201)                               # unchanged: moves nothing (D82)


def test_a_correction_debit_is_judged_on_available(paid):
    """F19: a decrease debits the receiver, judged on the receiver's available funds."""
    w = paid
    expect(w.bob.authorize("cy", 3_200), 201)                     # bob: total 3500, held 3200, available 300
    expect_error(w.ada.correct(w.pid, 1, 699, w.p["created_at"]), 409, "insufficient_funds")
    expect(w.ada.correct(w.pid, 1, 700, w.p["created_at"]), 201)
    assert w.bob.money() == (3_200, 0, 3_200)


# ---------------------------------------------------------------- W19.7 history

def test_a_refund_has_revision_1_at_its_created_at(paid):
    """I77: readable by its two parties only."""
    w = paid
    r = expect(w.bob.refund(w.pid, 200), 201)
    want = [{"payment_id": r["payment_id"], "revision": 1, "amount": 200, "effective_at": r["created_at"],
             "recorded_at": r["created_at"], "reason": ""}]
    assert w.bob.revisions(r["payment_id"]) == want == w.ada.revisions(r["payment_id"])
    expect_error(w.cy.revisions_resp(r["payment_id"]), 404, "not_found")


def test_a_refund_in_statements_and_history_views(paid):
    """I76, I77: an entry in both statements, counted from its created_at as of and as known; a snapshot taken
    before it pages unchanged."""
    w = paid
    me = {h: uid(w.svc, h) for h in ("ada", "bob")}
    snaps = {h: read_statement(w.svc.client(h), me[h]) for h in ("ada", "bob")}
    r = expect(w.bob.refund(w.pid, 200), 201)
    t = r["created_at"]
    st = read_statement(w.bob, me["bob"])
    assert st.ids() == [w.pid, r["payment_id"]] and st.deltas() == [1_000, -200], "a negative delta for its sender"
    e = st.entries[1]
    assert (e["revision"], e["effective_at"], e["recorded_at"], e["payment"]) == (1, t, t, r)
    st = read_statement(w.ada, me["ada"])
    assert st.ids() == [w.pid, r["payment_id"]] and st.deltas() == [-1_000, 200]
    assert w.bob.total_at(shifted(t, -1)) == 3_500 and w.bob.total_at(t) == 3_300
    assert w.ada.total_at(shifted(t, -1)) == 9_000 and w.ada.total_at(t) == 9_200
    assert w.bob.me_at(None, shifted(t, -1))["total"] == 3_500 and w.bob.me_at(None, t)["total"] == 3_300
    assert read_statement(w.bob, me["bob"], known_at=shifted(t, -1)).ids() == [w.pid]
    for h, s in snaps.items():
        assert page_snapshot(w.svc.client(h), me[h], s.snapshot)[0] == s.entries, f"I76: {h}'s older snapshot"
