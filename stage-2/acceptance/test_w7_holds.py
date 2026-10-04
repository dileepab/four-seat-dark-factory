"""W7.1, W7.2 — GET /me money fields and POST /authorizations (stage-2 "Authorizations and captures",
"API"; PLAN 3.4-3.7, 3.10). I1, I2, I8, I9, I10, I28, I30, I31, I36."""
from __future__ import annotations

from datetime import timedelta

import pytest

from support import (MAX_AMOUNT, PLAN_TS, TWO_53, check_authorization, check_me, expect,
                     expect_error, fixture, new_key, standard_users, ts, user)

pytestmark = pytest.mark.item(7)


def hold(client, to, amount, **extra) -> dict:
    return expect(client.authorize(to, amount, **extra), 201)


# ---------------------------------------------------------------- W7.1 GET /me

def test_me_has_exactly_the_stage_2_fields_with_no_holds(world):
    for h in ("ada", "bob", "cy", "dee"):
        m = check_me(world.svc.client(h).me())
        assert m["balance"] == m["total"] == m["available"] and m["held"] == 0, m
    m = world.ada.me()
    assert (m["user_id"], m["display_name"], m["handle"], m["balance"], m["currency"], m["minor_units"]) == \
        ("u_ada", "Ada", "ada", 10_000, "EUR", 2)


def test_signed_up_user_starts_with_zero_everywhere(world):
    expect(world.svc.signup("newbie@example.com", "correct horse", "Newbie"), 201)
    m = check_me(world.svc.client("newbie").me())
    assert (m["balance"], m["total"], m["available"], m["held"]) == (0, 0, 0, 0)


def test_a_hold_reduces_available_not_total(world):
    hold(world.ada, "bob", 2_000)
    m = check_me(world.ada.me())
    assert (m["balance"], m["total"], m["available"], m["held"]) == (10_000, 10_000, 8_000, 2_000)
    b = check_me(world.bob.me())
    assert (b["total"], b["available"], b["held"]) == (2_500, 2_500, 0), "the receiver holds nothing"


def test_held_is_the_sum_of_open_outgoing_holds(world):
    hold(world.ada, "bob", 2_000)
    hold(world.ada, "cy", 300)
    hold(world.ada, "bob", 1)
    hold(world.bob, "ada", 400)          # incoming to ada: not part of ada's held
    assert world.ada.money() == (10_000, 7_699, 2_301)
    assert world.bob.money() == (2_500, 2_100, 400)


# ---------------------------------------------------------------- W7.2 create

def test_authorization_201_has_exactly_the_authorization_fields(world):
    a = hold(world.ada, "bob", 2_000, note="deposit", visibility="private")
    check_authorization(a, from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob",
                        amount=2_000, captured_amount=0, remaining_amount=2_000, currency="EUR",
                        note="deposit", visibility="private", status="open", payment_id=None,
                        payment_ids=[])
    assert a["authorization_id"].startswith("a_"), "PLAN 3.7: generated ids are a_<random>"
    assert PLAN_TS.match(a["created_at"]) and PLAN_TS.match(a["expires_at"]), a


def test_default_ttl_is_600_seconds(world):
    a = hold(world.ada, "bob", 10)
    assert ts(a["expires_at"]) - ts(a["created_at"]) == timedelta(seconds=600), a


@pytest.mark.parametrize("ttl,seconds", [(1, 1), (3600, 3600), (600.0, 600), (86_400 * 30, 86_400 * 30),
                                         (10 ** 10, 10 ** 10)], ids=repr)
def test_fixture_ttl_sets_expires_at(svc, ttl, seconds):
    svc.must_reset(fixture(standard_users(), ttl=ttl))
    a = hold(svc.client("ada"), "bob", 10)
    assert ts(a["expires_at"]) - ts(a["created_at"]) == timedelta(seconds=seconds), a
    assert PLAN_TS.match(a["expires_at"]), a


def test_note_and_visibility_default_like_payments(world):
    a = expect(world.ada.post("/authorizations", json={"to_handle": "bob", "amount": 5}, key=new_key()), 201)
    assert a["note"] == "" and a["visibility"] == "public"


@pytest.mark.parametrize("note", ["emoji 😀🎉👨‍👩‍👧", "<b>x</b> & 'q' \"d\"", "  pad  ", "nul \u0000 x",
                                  "a" * 200, "😀" * 200, ""])
def test_note_round_trips_verbatim(world, note):
    a = hold(world.ada, "bob", 5, note=note)
    assert a["note"] == note
    assert world.bob.auth(a["authorization_id"])["note"] == note


@pytest.mark.parametrize("raw", ["1000", "1000.0", "1e3", "10E2"])
def test_integral_amount_forms_are_valid(world, raw):
    a = expect(world.ada.post("/authorizations", content=('{"to_handle":"bob","amount":%s}' % raw).encode(),
                              key=new_key()), 201)
    assert a["amount"] == 1000 and type(a["amount"]) is int
    assert world.ada.money() == (10_000, 9_000, 1_000)


def test_maximum_amount_is_in_range(svc):
    svc.must_reset(fixture([user("ada", MAX_AMOUNT), user("bob", 0)]))
    a = hold(svc.client("ada"), "bob", MAX_AMOUNT)
    assert a["amount"] == MAX_AMOUNT and svc.client("ada").money() == (MAX_AMOUNT, 0, MAX_AMOUNT)


def test_unknown_fields_are_ignored_and_cannot_steer_the_hold(world):
    a = hold(world.ada, "bob", 700, status="captured", captured_amount=700, remaining_amount=0,
             authorization_id="a_mine", expires_at="2000-01-01T00:00:00Z", created_at="1999-01-01T00:00:00Z",
             from_handle="cy", payment_id="p_x", payment_ids=["p_x"], currency="USD", final=True)
    check_authorization(a, status="open", captured_amount=0, remaining_amount=700, from_handle="ada",
                        currency="EUR", payment_id=None, payment_ids=[])
    assert a["authorization_id"] != "a_mine" and not a["created_at"].startswith("1999")
    assert world.ada.money() == (10_000, 9_300, 700) and world.cy.money() == (500, 500, 0)


def test_a_hold_moves_no_money_and_is_not_a_feed_item(world):
    a = hold(world.ada, "bob", 2_000, note="deposit")
    assert world.ada.balance() == 10_000 and world.bob.balance() == 2_500
    for c in (world.ada, world.bob, world.cy, world.dee):
        assert c.feed() == [], "I5: an authorization never appears in GET /activity"
    assert world.ada.auth(a["authorization_id"]) == a == world.bob.auth(a["authorization_id"])


def test_ids_are_unique(world):
    ids = {hold(world.ada, "bob", 1)["authorization_id"] for _ in range(30)}
    assert len(ids) == 30


def test_receiver_at_two_to_the_53_can_still_be_authorized(svc):
    """PLAN 3.5: no 2^53 guard on a hold, which moves no money."""
    svc.must_reset(fixture([user("ada", 1_000), user("bob", TWO_53)]))
    hold(svc.client("ada"), "bob", 1_000)
    assert svc.client("ada").money() == (1_000, 0, 1_000)


# ---------------------------------------------------------------- W7.2 funds on available (I31)

def test_hold_of_exactly_available_succeeds_and_one_more_is_409(world):
    hold(world.ada, "bob", 6_000)
    expect_error(world.ada.authorize("bob", 4_001), 409, "insufficient_funds")
    hold(world.ada, "cy", 4_000)
    assert world.ada.money() == (10_000, 0, 10_000)
    expect_error(world.ada.authorize("bob", 1), 409, "insufficient_funds")
    expect_error(world.ada.pay("bob", 1), 409, "insufficient_funds")


def test_insufficient_available_changes_nothing(world):
    expect_error(world.cy.authorize("ada", 501), 409, "insufficient_funds")
    assert world.cy.money() == (500, 500, 0) and world.cy.auths() == []


# ---------------------------------------------------------------- W7.2 error rows

BAD_AMOUNTS = [0, -1, 0.5, 1.5, MAX_AMOUNT + 1, 10 ** 12, "100", "1e3", True, False, None, [], {}]


@pytest.mark.parametrize("amount", BAD_AMOUNTS, ids=repr)
def test_invalid_amount_is_422(world, amount):
    expect_error(world.ada.authorize("bob", amount), 422, "validation_failed")
    assert world.ada.money() == (10_000, 10_000, 0) and world.ada.auths() == []


def test_missing_amount_or_handle_is_422(world):
    expect_error(world.ada.post("/authorizations", json={"to_handle": "bob"}, key=new_key()),
                 422, "validation_failed")
    expect_error(world.ada.post("/authorizations", json={"amount": 5}, key=new_key()),
                 422, "validation_failed")


@pytest.mark.parametrize("handle", [5, None, ["bob"], {"h": "bob"}, True], ids=repr)
def test_wrong_type_to_handle_is_400(world, handle):
    expect_error(world.ada.authorize(handle, 5), 400, "malformed_request")


@pytest.mark.parametrize("handle", ["nobody", "", "BOB", "@bob", "bob "])
def test_unknown_handle_is_404(world, handle):
    expect_error(world.ada.authorize(handle, 5), 404, "not_found")


def test_own_handle_is_self_payment(world):
    expect_error(world.ada.authorize("ada", 5), 422, "self_payment")


@pytest.mark.parametrize("note", ["a" * 201, "😀" * 201, None, 5, [], {}], ids=lambda v: repr(v)[:20])
def test_invalid_note_is_422(world, note):
    expect_error(world.ada.authorize("bob", 5, note=note), 422, "validation_failed")


@pytest.mark.parametrize("vis", ["PUBLIC", "", "friends", None, 1, True, []], ids=repr)
def test_invalid_visibility_is_422(world, vis):
    expect_error(world.ada.authorize("bob", 5, visibility=vis), 422, "validation_failed")


def test_authentication_and_key_rules(world):
    anon = world.svc.api()
    expect_error(anon.authorize("bob", 5), 401, "unauthenticated")
    expect_error(world.svc.api("not-a-token").authorize("bob", 5), 401, "unauthenticated")
    expect_error(world.ada.post("/authorizations", json={"to_handle": "bob", "amount": 5}),
                 400, "missing_idempotency_key")
    expect_error(world.ada.authorize("bob", 5, key="k" * 256), 422, "validation_failed")
    expect(world.ada.authorize("bob", 5, key="k" * 255), 201)


def test_precedence(world):
    """PLAN 3.5: exactly the POST /payments order."""
    ada = world.ada
    # 401 before the key and the body
    expect_error(world.svc.api().post("/authorizations", content=b"{nope"), 401, "unauthenticated")
    # key before the body
    expect_error(ada.post("/authorizations", content=b"{nope"), 400, "missing_idempotency_key")
    # body before field types; types before values
    expect_error(ada.authorize(5, 0), 400, "malformed_request")
    # values before the handle lookup
    expect_error(ada.authorize("nobody", 0), 422, "validation_failed")
    expect_error(ada.authorize("nobody", 5, note="a" * 201), 422, "validation_failed")
    # unknown handle before funds; self before funds
    expect_error(ada.authorize("nobody", 10 ** 6), 404, "not_found")
    expect_error(world.cy.authorize("cy", 10 ** 6), 422, "self_payment")
    # a claimed key before types and values
    key = new_key()
    expect(ada.authorize("bob", 5, key=key), 201)
    expect_error(ada.authorize(5, 0, key=key), 409, "idempotency_key_reuse")
    assert ada.money() == (10_000, 9_995, 5)


def test_route_rules(world):
    for method, path in (("GET", "/authorizations/x"), ("PUT", "/authorizations"),
                         ("DELETE", "/authorizations"), ("GET", "/authorizations/x/capture"),
                         ("GET", "/authorizations/x/void"), ("POST", "/authorizations/x/refund"),
                         ("POST", "/authorizations/x/capture/y")):
        expect_error(world.ada.request(method, path), 404, "not_found")
