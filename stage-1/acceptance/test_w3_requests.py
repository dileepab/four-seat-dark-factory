"""W3.1-W3.5 — requests, pay, decline, cancel, GET /requests (§4, §8; PLAN 3.5, 3.10, D5, D24, D31).

Invariants I3, I4, I6, I8, I15 (pay replay), I24 (operator reach).
"""
from __future__ import annotations

import pytest

from support import (assert_newest_first, check_payment, check_request, expect, expect_error,
                     fixture, new_key, standard_users, user)

pytestmark = pytest.mark.item(3)


def find(items, rid):
    return next(r for r in items if r["request_id"] == rid)


# ---------------------------------------------------------------- POST /requests

def test_request_201_has_exactly_the_request_fields(world):
    r = expect(world.bob.ask("ada", 1200, note="taxi"), 201)
    check_request(r, requester_id="u_bob", requester_handle="bob", payer_id="u_ada", payer_handle="ada",
                  amount=1200, currency="EUR", note="taxi", status="pending", payment_id=None)


def test_request_note_defaults_to_empty(world):
    r = expect(world.bob.post("/requests", json={"payer_handle": "ada", "amount": 5}, key=new_key()), 201)
    assert r["note"] == ""


def test_request_above_the_payers_balance_is_created_and_moves_nothing(world):
    r = expect(world.ada.ask("dee", 1_000_000_000), 201)
    assert r["status"] == "pending"
    assert world.dee.balance() == 0 and world.ada.balance() == 10_000


def test_request_appears_for_both_parties_identically(world):
    r = expect(world.bob.ask("ada", 7, note="n"), 201)
    assert find(world.bob.requests(), r["request_id"]) == r
    assert find(world.ada.requests(), r["request_id"]) == r


@pytest.mark.parametrize("amount", [0, -1, 1.5, 1_000_000_001, "5", True, None, [], {}], ids=repr)
def test_invalid_request_amount_is_422(world, amount):
    expect_error(world.bob.ask("ada", amount), 422, "validation_failed")


@pytest.mark.parametrize("raw", ["1e3", "1000.0"])
def test_integral_request_amount_forms(world, raw):
    body = ('{"payer_handle": "ada", "amount": %s}' % raw).encode()
    assert expect(world.bob.post("/requests", content=body, key=new_key()), 201)["amount"] == 1000


@pytest.mark.parametrize("note,status", [("a" * 200, 201), ("😀" * 200, 201), ("a" * 201, 422)])
def test_request_note_length(world, note, status):
    r = world.bob.ask("ada", 5, note=note)
    if status == 201:
        assert expect(r, 201)["note"] == note
    else:
        expect_error(r, 422, "validation_failed")


@pytest.mark.parametrize("note", [None, 5, [], {}], ids=repr)
def test_non_string_request_note_is_422(world, note):
    expect_error(world.bob.ask("ada", 5, note=note), 422, "validation_failed")


def test_requesting_from_yourself_is_self_request(world):
    expect_error(world.bob.ask("bob", 5), 422, "self_request")


@pytest.mark.parametrize("handle", ["nobody", "", "ADA", "@ada"])
def test_unknown_payer_is_404(world, handle):
    expect_error(world.bob.ask(handle, 5), 404, "not_found")


@pytest.mark.parametrize("handle", [5, None, ["ada"]], ids=repr)
def test_wrong_type_payer_handle_is_400(world, handle):
    expect_error(world.bob.ask(handle, 5), 400, "malformed_request")


def test_missing_payer_handle_or_amount_is_422(world):
    expect_error(world.bob.post("/requests", json={"amount": 5}, key=new_key()), 422, "validation_failed")
    expect_error(world.bob.post("/requests", json={"payer_handle": "ada"}, key=new_key()), 422, "validation_failed")


def test_request_precedence(world):
    expect_error(world.bob.ask("nobody", 0), 422, "validation_failed")
    expect_error(world.bob.ask("bob", 0), 422, "validation_failed")


def test_request_ignores_visibility_and_spoofed_fields(world):
    r = expect(world.bob.ask("ada", 5, visibility="bogus", requester_id="u_cy", status="paid"), 201)
    assert r["requester_id"] == "u_bob" and r["status"] == "pending"


def test_request_can_be_made_of_a_new_user(world):
    expect(world.svc.signup("fresh@example.com", "correct horse", "F"), 201)
    r = expect(world.bob.ask("fresh", 50), 201)
    assert find(world.svc.client("fresh").requests(), r["request_id"])["status"] == "pending"


# ---------------------------------------------------------------- pay

def test_pay_creates_a_payment_and_marks_the_request_paid(world):
    rq = expect(world.bob.ask("ada", 1200, note="taxi"), 201)
    p = expect(world.ada.pay_request(rq["request_id"], {"visibility": "private"}), 201)
    check_payment(p, from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob",
                  amount=1200, currency="EUR", note="taxi", visibility="private",
                  request_id=rq["request_id"], settlement_id=None)
    assert world.ada.balance() == 8_800 and world.bob.balance() == 3_700
    for c in (world.ada, world.bob):
        after = find(c.requests(), rq["request_id"])
        assert after == {**rq, "status": "paid", "payment_id": p["payment_id"]}
    assert world.bob.feed()[0] == p
    assert p["payment_id"] not in {i["payment_id"] for i in world.cy.feed()}


def test_pay_defaults_to_public(world):
    rq = expect(world.bob.ask("ada", 5), 201)
    p = expect(world.ada.pay_request(rq["request_id"], {}), 201)
    assert p["visibility"] == "public"
    assert p["payment_id"] in {i["payment_id"] for i in world.dee.feed()}


def test_pay_ignores_amount_and_note_in_the_body(world):
    rq = expect(world.bob.ask("ada", 40, note="orig"), 201)
    p = expect(world.ada.pay_request(rq["request_id"], {"amount": 1, "note": "x", "to_handle": "cy"}), 201)
    assert (p["amount"], p["note"], p["to_handle"]) == (40, "orig", "bob")


@pytest.mark.parametrize("vis", ["PUBLIC", "", "friends", None, 1], ids=repr)
def test_pay_with_bad_visibility_is_422(world, vis):
    rq = expect(world.bob.ask("ada", 5), 201)
    expect_error(world.ada.pay_request(rq["request_id"], {"visibility": vis}), 422, "validation_failed")
    assert find(world.ada.requests(), rq["request_id"])["status"] == "pending"


def test_pay_unknown_request_is_404(world):
    expect_error(world.ada.pay_request("rq_does_not_exist"), 404, "not_found")
    expect_error(world.ada.pay_request("x" * 300), 404, "not_found")


@pytest.mark.parametrize("who", ["bob", "cy"])
def test_only_the_payer_may_pay(world, who):
    rq = expect(world.bob.ask("ada", 5), 201)
    expect_error(world.svc.client(who).pay_request(rq["request_id"]), 403, "forbidden")
    assert find(world.ada.requests(), rq["request_id"])["status"] == "pending"


@pytest.mark.parametrize("end", ["paid", "declined", "cancelled"])
def test_paying_a_non_pending_request_is_409(world, end):
    rq = expect(world.bob.ask("ada", 5), 201)["request_id"]
    if end == "paid":
        expect(world.ada.pay_request(rq), 201)
    elif end == "declined":
        expect(world.ada.decline(rq), 200)
    else:
        expect(world.bob.cancel(rq), 200)
    before = world.ada.balance()
    expect_error(world.ada.pay_request(rq), 409, "request_not_pending")
    assert world.ada.balance() == before


def test_paying_while_short_is_409_and_payable_later(world):
    rq = expect(world.ada.ask("cy", 800), 201)["request_id"]
    key = new_key()
    expect_error(world.cy.pay_request(rq, key=key), 409, "insufficient_funds")
    assert world.cy.balance() == 500
    assert find(world.cy.requests(), rq)["status"] == "pending"
    expect(world.bob.pay("cy", 300), 201)
    p = expect(world.cy.pay_request(rq, key=key), 201)
    assert expect(world.cy.pay_request(rq, key=key), 200) == p
    assert world.cy.balance() == 0
    assert sum(1 for i in world.cy.feed() if i["request_id"] == rq) == 1


def test_pay_precedence(world):
    rq = expect(world.bob.ask("dee", 5), 201)["request_id"]
    expect_error(world.cy.pay_request("rq_nope", {"visibility": "bad"}), 422, "validation_failed")
    expect_error(world.cy.pay_request("rq_nope"), 404, "not_found")
    expect(world.bob.cancel(rq), 200)
    expect_error(world.cy.pay_request(rq), 403, "forbidden")       # 403 before 409
    expect_error(world.dee.pay_request(rq), 409, "request_not_pending")  # 409 not pending before funds


def test_pay_with_an_empty_body_is_400(world):
    """D7: an endpoint that reads a body treats zero bytes as unparseable."""
    rq = expect(world.bob.ask("ada", 5), 201)["request_id"]
    expect_error(world.ada.post(f"/requests/{rq}/pay", content=b"", key=new_key()), 400, "malformed_request")


def test_empty_object_and_explicit_public_are_different_bodies(world):
    rq = expect(world.bob.ask("ada", 5), 201)["request_id"]
    key = new_key()
    expect(world.ada.pay_request(rq, {}, key=key), 201)
    expect_error(world.ada.pay_request(rq, {"visibility": "public"}, key=key), 409, "idempotency_key_reuse")


def test_pay_replay_is_200_never_409(world):
    rq = expect(world.bob.ask("ada", 5), 201)["request_id"]
    key = new_key()
    p = expect(world.ada.pay_request(rq, key=key), 201)
    assert expect(world.ada.pay_request(rq, key=key), 200) == p
    expect_error(world.ada.pay_request(rq), 409, "request_not_pending")
    assert world.ada.balance() == 9_995


# ---------------------------------------------------------------- seeded requests

@pytest.fixture
def seeded(svc):
    svc.must_reset(fixture(standard_users(), requests=[
        {"id": "rq_pend", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi"},
        {"id": "rq_paid", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1, "status": "paid",
         "payment_id": "p_old"},
        {"id": "rq_decl", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1, "status": "declined"},
        {"id": "rq_canc", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1, "status": "cancelled"},
    ]))
    return svc


def test_seeded_pending_request_is_payable(seeded):
    p = expect(seeded.client("ada").pay_request("rq_pend"), 201)
    assert p["request_id"] == "rq_pend" and p["amount"] == 1200 and p["note"] == "taxi"
    assert find(seeded.client("bob").requests(), "rq_pend")["payment_id"] == p["payment_id"]


@pytest.mark.parametrize("rid", ["rq_paid", "rq_decl", "rq_canc"])
def test_seeded_terminal_requests_cannot_move(seeded, rid):
    ada, bob = seeded.client("ada"), seeded.client("bob")
    expect_error(ada.pay_request(rid), 409, "request_not_pending")
    status = find(ada.requests(), rid)["status"]
    if status != "declined":
        expect_error(ada.decline(rid), 409, "request_not_pending")
    if status != "cancelled":
        expect_error(bob.cancel(rid), 409, "request_not_pending")
    assert find(ada.requests(), rid)["status"] == status


# ---------------------------------------------------------------- decline and cancel

def test_decline_and_decline_again(world):
    rq = expect(world.bob.ask("ada", 5), 201)
    d1 = expect(world.ada.decline(rq["request_id"]), 200)
    assert d1 == {**rq, "status": "declined"}
    assert expect(world.ada.decline(rq["request_id"]), 200) == d1


def test_cancel_and_cancel_again(world):
    rq = expect(world.bob.ask("ada", 5), 201)
    c1 = expect(world.bob.cancel(rq["request_id"]), 200)
    assert c1 == {**rq, "status": "cancelled"}
    assert expect(world.bob.cancel(rq["request_id"]), 200) == c1


@pytest.mark.parametrize("first,then,actor", [
    ("paid", "decline", "ada"), ("cancelled", "decline", "ada"),
    ("paid", "cancel", "bob"), ("declined", "cancel", "bob"),
])
def test_terminal_states_never_change(world, first, then, actor):
    rq = expect(world.bob.ask("ada", 5), 201)["request_id"]
    {"paid": lambda: expect(world.ada.pay_request(rq), 201),
     "declined": lambda: expect(world.ada.decline(rq), 200),
     "cancelled": lambda: expect(world.bob.cancel(rq), 200)}[first]()
    c = world.svc.client(actor)
    expect_error(c.decline(rq) if then == "decline" else c.cancel(rq), 409, "request_not_pending")
    assert find(world.ada.requests(), rq)["status"] == first


@pytest.mark.parametrize("who", ["bob", "cy"])
def test_only_the_payer_may_decline(world, who):
    rq = expect(world.bob.ask("ada", 5), 201)["request_id"]
    expect_error(world.svc.client(who).decline(rq), 403, "forbidden")


@pytest.mark.parametrize("who", ["ada", "cy"])
def test_only_the_requester_may_cancel(world, who):
    rq = expect(world.bob.ask("ada", 5), 201)["request_id"]
    expect_error(world.svc.client(who).cancel(rq), 403, "forbidden")


def test_decline_and_cancel_of_unknown_request_are_404(world):
    expect_error(world.ada.decline("rq_nope"), 404, "not_found")
    expect_error(world.ada.cancel("rq_nope"), 404, "not_found")


def test_decline_and_cancel_need_no_key_and_ignore_the_body(world):
    rq1 = expect(world.bob.ask("ada", 5), 201)["request_id"]
    rq2 = expect(world.bob.ask("ada", 5), 201)["request_id"]
    expect(world.ada.post(f"/requests/{rq1}/decline", content=b"{not json"), 200)
    expect(world.bob.post(f"/requests/{rq2}/cancel", content=b"[1, 2"), 200)


def test_declined_request_moves_no_money(world):
    rq = expect(world.bob.ask("ada", 500), 201)["request_id"]
    expect(world.ada.decline(rq), 200)
    assert world.ada.balance() == 10_000 and world.bob.balance() == 2_500


# ---------------------------------------------------------------- zero-amount requests (D24, I9)

def test_zero_amount_request_from_a_split_is_payable(world):
    split = expect(world.ada.split(1, ["ada", "bob", "cy"]), 201)
    zero = [r for r in split["requests"] if r["amount"] == 0]
    assert len(zero) == 2
    p = expect(world.bob.pay_request(zero[0]["request_id"]), 201)
    assert p["amount"] == 0 and p["request_id"] == zero[0]["request_id"]
    assert find(world.bob.requests(), zero[0]["request_id"])["status"] == "paid"
    assert world.bob.balance() == 2_500


# ---------------------------------------------------------------- GET /requests

@pytest.fixture
def listed(world):
    """bob->ada (pending, paid, declined), ada->bob (cancelled), cy->ada (pending), bob->cy (pending)."""
    r = {}
    r["ba_pending"] = expect(world.bob.ask("ada", 1), 201)
    r["ba_paid"] = expect(world.bob.ask("ada", 2), 201)
    r["ba_declined"] = expect(world.bob.ask("ada", 3), 201)
    r["ab_cancelled"] = expect(world.ada.ask("bob", 4), 201)
    r["ca_pending"] = expect(world.cy.ask("ada", 5), 201)
    r["bc_pending"] = expect(world.bob.ask("cy", 6), 201)
    expect(world.ada.pay_request(r["ba_paid"]["request_id"]), 201)
    expect(world.ada.decline(r["ba_declined"]["request_id"]), 200)
    expect(world.ada.cancel(r["ab_cancelled"]["request_id"]), 200)
    return world, {k: v["request_id"] for k, v in r.items()}


@pytest.mark.parametrize("params,expected", [
    ({}, {"ba_pending", "ba_paid", "ba_declined", "ab_cancelled", "ca_pending"}),
    ({"direction": "incoming"}, {"ba_pending", "ba_paid", "ba_declined", "ca_pending"}),
    ({"direction": "outgoing"}, {"ab_cancelled"}),
    ({"status": "pending"}, {"ba_pending", "ca_pending"}),
    ({"status": "paid"}, {"ba_paid"}),
    ({"status": "declined"}, {"ba_declined"}),
    ({"status": "cancelled"}, {"ab_cancelled"}),
    ({"direction": "incoming", "status": "pending"}, {"ba_pending", "ca_pending"}),
    ({"direction": "outgoing", "status": "pending"}, set()),
    ({"direction": "outgoing", "status": "cancelled"}, {"ab_cancelled"}),
])
def test_filters_for_ada(listed, params, expected):
    world, ids = listed
    got = {r["request_id"] for r in world.ada.requests(**params)}
    assert got == {ids[k] for k in expected}


@pytest.mark.parametrize("params", [{}, {"direction": "incoming"}, {"direction": "outgoing"},
                                    {"status": "pending"}, {"status": "paid"},
                                    {"direction": "incoming", "status": "declined"}])
def test_a_non_party_sees_none_of_them(listed, params):
    world, ids = listed
    assert world.dee.requests(**params) == []
    cy = {r["request_id"] for r in world.cy.requests(**params)}
    assert cy <= {ids["ca_pending"], ids["bc_pending"]}


def test_every_listed_request_has_the_caller_as_a_party(listed):
    world, _ = listed
    for h in ("ada", "bob", "cy", "dee"):
        me = world.svc.client(h).me()["user_id"]
        for r in world.svc.client(h).requests():
            check_request(r)
            assert me in (r["requester_id"], r["payer_id"])


def test_requests_are_newest_first_and_page(world):
    made = [expect(world.bob.ask("ada", i + 1), 201)["request_id"] for i in range(7)]
    newest = list(reversed(made))
    lst = world.ada.requests()
    assert_newest_first(lst)
    assert [r["request_id"] for r in lst] == newest, "PLAN 3.7: ties go to creation order, later first"
    p1 = expect(world.ada.get("/requests", params={"limit": 3}), 200)
    p2 = expect(world.ada.get("/requests", params={"limit": 3, "offset": 3}), 200)
    p3 = expect(world.ada.get("/requests", params={"limit": 3, "offset": 6}), 200)
    assert [r["request_id"] for r in p1["requests"]] == newest[:3] and p1["has_more"] is True
    assert [r["request_id"] for r in p2["requests"]] == newest[3:6] and p2["has_more"] is True
    assert [r["request_id"] for r in p3["requests"]] == newest[6:] and p3["has_more"] is False
    assert expect(world.ada.get("/requests", params={"offset": 99}), 200) == {"requests": [], "has_more": False}


def test_has_more_respects_the_filter(world):
    for i in range(3):
        expect(world.bob.ask("ada", i + 1), 201)
    expect(world.ada.ask("bob", 9), 201)
    page = expect(world.ada.get("/requests", params={"direction": "incoming", "limit": 3}), 200)
    assert len(page["requests"]) == 3 and page["has_more"] is False


@pytest.mark.parametrize("params", [
    {"direction": "INCOMING"}, {"direction": ""}, {"direction": "both"}, {"direction": "in"},
    {"status": "Pending"}, {"status": ""}, {"status": "paid "}, {"status": "all"},
    {"limit": "0"}, {"limit": "201"}, {"limit": "1e1"}, {"limit": "4.0"}, {"limit": "+4"},
    {"offset": "-1"}, {"offset": "x"},
])
def test_invalid_request_list_parameters_are_422(world, params):
    expect_error(world.ada.get("/requests", params=params), 422, "validation_failed")


def test_request_list_ignores_unknown_parameters(world):
    expect(world.bob.ask("ada", 1), 201)
    assert len(expect(world.ada.get("/requests", params={"visibility": "x", "foo": "1"}), 200)["requests"]) == 1


# ---------------------------------------------------------------- operator reach (I24)

@pytest.mark.item(4)
def test_operator_gains_no_reach_into_other_peoples_requests(world):
    """Ada is a settlement operator in the standard world."""
    rq = expect(world.bob.ask("cy", 5), 201)["request_id"]
    p = expect(world.bob.pay("cy", 6, visibility="private"), 201)
    assert rq not in {r["request_id"] for r in world.ada.requests()}
    assert p["payment_id"] not in {i["payment_id"] for i in world.ada.feed()}
    expect_error(world.ada.pay_request(rq), 403, "forbidden")
    expect_error(world.ada.decline(rq), 403, "forbidden")
    expect_error(world.ada.cancel(rq), 403, "forbidden")
