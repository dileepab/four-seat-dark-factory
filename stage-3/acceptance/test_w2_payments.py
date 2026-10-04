"""W2.1, W2.2 — POST /payments (§4, §5, §8; PLAN 3.4, 3.5, 3.10, D4, D19). I7, I8, I9, I10, I20."""
from __future__ import annotations

import pytest

from support import (MAX_AMOUNT, TWO_53, check_payment, expect, expect_error, fixture, new_key,
                     standard_users, user)

pytestmark = pytest.mark.item(2)


def feed_ids(client) -> list[str]:
    return [p["payment_id"] for p in client.feed()]


# ---------------------------------------------------------------- success

def test_payment_201_has_exactly_the_payment_fields(world):
    p = expect(world.ada.pay("bob", 1500, note="dinner", visibility="public"), 201)
    check_payment(p, from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob",
                  amount=1500, currency="EUR", note="dinner", visibility="public",
                  request_id=None, settlement_id=None)


def test_payment_moves_money_both_ways(world):
    expect(world.ada.pay("bob", 1500), 201)
    assert world.ada.balance() == 8_500 and world.bob.balance() == 4_000


def test_note_and_visibility_default(world):
    p = expect(world.ada.post("/payments", json={"to_handle": "bob", "amount": 1}, key=new_key()), 201)
    assert p["note"] == "" and p["visibility"] == "public"


def test_private_visibility_is_kept(world):
    p = expect(world.ada.pay("bob", 1, visibility="private"), 201)
    assert p["visibility"] == "private"


def test_paying_exactly_the_balance_leaves_zero(world):
    expect(world.cy.pay("ada", 500), 201)
    assert world.cy.balance() == 0


def test_new_user_can_receive_and_then_pay(world):
    expect(world.svc.signup("newbie@example.com", "correct horse", "Newbie"), 201)
    newbie = world.svc.client("newbie")
    expect(world.ada.pay("newbie", 300), 201)
    assert newbie.balance() == 300
    expect(newbie.pay("dee", 300), 201)
    assert newbie.balance() == 0 and world.dee.balance() == 300


@pytest.mark.parametrize("note", [
    "  surrounding spaces  ",
    "emoji 😀🎉👨‍👩‍👧",
    "<b>html</b> & 'single' \"double\" \\backslash",
    "accents é ü ñ Å",
    "é combining (not NFC)",
    "line\nbreak\ttab\rreturn",
    "zero​width ‮RTL",
    "nul \u0000 inside",
    "中文 日本語 한국어",
    "",
])
def test_note_round_trips_verbatim_everywhere(world, note):
    p = expect(world.ada.pay("bob", 7, note=note), 201)
    assert p["note"] == note
    for client in (world.ada, world.bob, world.cy):
        item = next(i for i in client.feed() if i["payment_id"] == p["payment_id"])
        assert item["note"] == note


@pytest.mark.parametrize("note,status", [
    ("a" * 200, 201), ("a" * 201, 422), ("😀" * 200, 201), ("😀" * 201, 422),
    ("é" * 100, 201), ("é" * 100 + "x", 422),
])
def test_note_length_counts_code_points(world, note, status):
    r = world.ada.pay("bob", 1, note=note)
    if status == 201:
        assert expect(r, 201)["note"] == note
    else:
        expect_error(r, 422, "validation_failed")


@pytest.mark.parametrize("raw", ["1000", "1000.0", "1e3", "1E3", "10e2", "1000.000"])
def test_integral_amount_forms_are_valid(world, raw):
    body = ('{"to_handle": "bob", "amount": %s}' % raw).encode()
    p = expect(world.ada.post("/payments", content=body, key=new_key()), 201)
    assert p["amount"] == 1000 and type(p["amount"]) is int
    assert world.ada.balance() == 9_000


def test_maximum_amount_is_in_range(svc):
    svc.must_reset(fixture([user("ada", MAX_AMOUNT), user("bob", 0)]))
    p = expect(svc.client("ada").pay("bob", MAX_AMOUNT), 201)
    assert p["amount"] == MAX_AMOUNT
    assert svc.client("bob").balance() == MAX_AMOUNT


def test_maximum_amount_without_funds_is_insufficient_not_invalid(world):
    expect_error(world.cy.pay("ada", MAX_AMOUNT), 409, "insufficient_funds")


# ---------------------------------------------------------------- field rules (422 / 400 / 404)

BAD_AMOUNTS = [0, -1, -0.0, 0.0, 1.5, 0.999, MAX_AMOUNT + 1, 10 ** 10 + 1, "100", "1e3", True, False,
               None, [], {}, [100]]


@pytest.mark.parametrize("amount", BAD_AMOUNTS, ids=repr)
def test_invalid_amount_is_422_and_moves_nothing(world, amount):
    expect_error(world.ada.pay("bob", amount), 422, "validation_failed")
    assert world.ada.balance() == 10_000 and world.bob.balance() == 2_500


@pytest.mark.parametrize("raw", ["1e400", "-1e400", "1e-400", "1.0000000001", "1000000000.5"])
def test_non_finite_or_fractional_raw_amount_is_422(world, raw):
    body = ('{"to_handle": "bob", "amount": %s}' % raw).encode()
    expect_error(world.ada.post("/payments", content=body, key=new_key()), 422, "validation_failed")
    assert world.ada.balance() == 10_000


def test_missing_amount_is_422(world):
    expect_error(world.ada.post("/payments", json={"to_handle": "bob"}, key=new_key()),
                 422, "validation_failed")


def test_missing_to_handle_is_422(world):
    expect_error(world.ada.post("/payments", json={"amount": 5}, key=new_key()),
                 422, "validation_failed")


@pytest.mark.parametrize("handle", [5, None, ["bob"], {"h": "bob"}, True], ids=repr)
def test_wrong_type_to_handle_is_400(world, handle):
    expect_error(world.ada.pay(handle, 5), 400, "malformed_request")


@pytest.mark.parametrize("handle", ["nobody", "", "BOB", "@bob", "bob ", " bob", "b" * 21,
                                    "x" * 5000, "bob\u0000", "😀"])
def test_handle_that_names_no_user_is_404(world, handle):
    expect_error(world.ada.pay(handle, 5), 404, "not_found")
    assert world.ada.balance() == 10_000


@pytest.mark.parametrize("note", [None, 5, True, [], {}, ["x"]], ids=repr)
def test_non_string_note_is_422(world, note):
    expect_error(world.ada.pay("bob", 5, note=note), 422, "validation_failed")


@pytest.mark.parametrize("vis", ["PUBLIC", "Private", "", "friends", " public", None, 1, True, [], {}],
                         ids=repr)
def test_visibility_other_than_public_or_private_is_422(world, vis):
    expect_error(world.ada.pay("bob", 5, visibility=vis), 422, "validation_failed")


def test_paying_your_own_handle_is_self_payment(world):
    expect_error(world.ada.pay("ada", 5), 422, "self_payment")
    assert world.ada.balance() == 10_000


def test_insufficient_funds_is_409_and_leaves_no_trace(world):
    before_feeds = {h: feed_ids(c) for h, c in (("cy", world.cy), ("dee", world.dee))}
    expect_error(world.cy.pay("dee", 501), 409, "insufficient_funds")
    expect_error(world.dee.pay("cy", 1), 409, "insufficient_funds")
    assert world.cy.balance() == 500 and world.dee.balance() == 0
    assert {h: feed_ids(c) for h, c in (("cy", world.cy), ("dee", world.dee))} == before_feeds


def test_unknown_fields_are_ignored_and_cannot_spoof_the_sender(world):
    p = expect(world.ada.post("/payments", key=new_key(), json={
        "to_handle": "bob", "amount": 5, "from_handle": "cy", "from_user_id": "u_cy",
        "currency": "USD", "created_at": "1999-01-01T00:00:00+00:00", "payment_id": "p_mine",
        "request_id": "rq_x", "settlement_id": "st_x", "extra": {"deep": [1, 2]}}), 201)
    check_payment(p, from_user_id="u_ada", from_handle="ada", currency="EUR", request_id=None,
                  settlement_id=None)
    assert p["payment_id"] != "p_mine" and not p["created_at"].startswith("1999")
    assert world.cy.balance() == 500 and world.ada.balance() == 9_995


# ---------------------------------------------------------------- precedence (PLAN 3.5)

def test_missing_key_outranks_an_invalid_body(world):
    r = world.ada.post("/payments", content=b"{nope")
    expect_error(r, 400, "missing_idempotency_key")


@pytest.mark.parametrize("key", [None, ""])
def test_absent_or_empty_key_is_400(world, key):
    headers = {"Idempotency-Key": key} if key is not None else None
    r = world.ada.post("/payments", json={"to_handle": "bob", "amount": 5}, headers=headers)
    expect_error(r, 400, "missing_idempotency_key")
    assert world.ada.balance() == 10_000


@pytest.mark.parametrize("length,status", [(1, 201), (255, 201), (256, 422), (10_000, 422)])
def test_key_length_range(world, length, status):
    r = world.ada.pay("bob", 5, key="k" * length)
    if status == 201:
        expect(r, 201)
    else:
        expect_error(r, 422, "validation_failed")


def test_long_key_outranks_an_invalid_body(world):
    expect_error(world.ada.post("/payments", content=b"{nope", key="k" * 256), 422, "validation_failed")


def test_type_error_outranks_value_error(world):
    expect_error(world.ada.pay(5, 0), 400, "malformed_request")


def test_value_error_outranks_unknown_handle(world):
    expect_error(world.ada.pay("nobody", 0), 422, "validation_failed")


def test_value_error_outranks_self_payment(world):
    expect_error(world.ada.pay("ada", 0), 422, "validation_failed")


def test_unknown_handle_outranks_insufficient_funds(world):
    expect_error(world.dee.pay("nobody", 5), 404, "not_found")


def test_self_payment_outranks_insufficient_funds(world):
    expect_error(world.dee.pay("dee", 5), 422, "self_payment")


# ---------------------------------------------------------------- 2^53 guard (D19)

def test_payment_that_would_push_a_balance_past_2_53_is_422(svc):
    svc.must_reset(fixture([user("ada", 1_000), user("bob", TWO_53 - 10)]))
    ada = svc.client("ada")
    expect_error(ada.pay("bob", 11), 422, "validation_failed")
    assert ada.balance() == 1_000 and svc.client("bob").balance() == TWO_53 - 10
    expect(ada.pay("bob", 10), 201)
    assert svc.client("bob").balance() == TWO_53


def test_large_balances_are_exact(svc):
    svc.must_reset(fixture([user("ada", TWO_53 - 1), user("bob", TWO_53 - 3)]))
    ada, bob = svc.client("ada"), svc.client("bob")
    expect(ada.pay("bob", 1), 201)
    assert ada.balance() == TWO_53 - 2 and bob.balance() == TWO_53 - 2


@pytest.mark.parametrize("currency", ["JPY", "BHD"])
def test_payment_in_other_currencies(svc, currency):
    svc.must_reset(fixture(standard_users(), currency=currency))
    p = expect(svc.client("ada").pay("bob", 1001), 201)
    assert p["currency"] == currency and p["amount"] == 1001
    assert svc.client("bob").balance() == 3_501


# ---------------------------------------------------------------- 401 and robustness

WEIRD = [None, True, -1, 1.5, 1e308, "", "x" * 5000, [], {}, ["a"], "\u0000", "😀" * 300, 2 ** 64]


@pytest.mark.parametrize("field", ["to_handle", "amount", "note", "visibility"])
@pytest.mark.parametrize("value", WEIRD, ids=lambda v: repr(v)[:16])
def test_payments_never_5xx_on_weird_values(world, field, value):
    body = {"to_handle": "bob", "amount": 5}
    body[field] = value
    r = world.ada.post("/payments", json=body, key=new_key())
    assert r.status_code in (201, 400, 404, 409, 422), r.text[:200]
    if r.status_code >= 400:
        assert r.json()["error"]["code"]
