"""W7.3 — POST /authorizations/{id}/capture (stage-2 "API"; PLAN 3.4, 3.5, 3.6, 3.10, D47, D50).
I1, I5, I7, I8, I15, I16, I32, I33, I36."""
from __future__ import annotations

import pytest

from support import (MAX_AMOUNT, PLAN_TS, TWO_53, check_authorization, check_payment, expect, expect_error,
                     fixture, new_key, raw_request, user)

pytestmark = pytest.mark.item(7)


def hold(world, amount=2_000, frm="ada", to="bob", **extra) -> dict:
    return expect(world.svc.client(frm).authorize(to, amount, **extra), 201)


# ---------------------------------------------------------------- success

def test_default_capture_takes_the_whole_remainder(world):
    a = hold(world, note="deposit", visibility="private")
    aid = a["authorization_id"]
    p = expect(world.bob.capture(aid), 201)
    check_payment(p, from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob",
                  amount=2_000, currency="EUR", note="deposit", visibility="private", request_id=None,
                  settlement_id=None, authorization_id=aid)
    assert PLAN_TS.match(p["created_at"]), p
    assert world.ada.money() == (8_000, 8_000, 0)
    assert world.bob.money() == (4_500, 4_500, 0)
    check_authorization(world.ada.auth(aid), status="captured", captured_amount=2_000, remaining_amount=0,
                        payment_id=p["payment_id"], payment_ids=[p["payment_id"]], amount=2_000)


def test_smaller_final_capture_releases_the_rest_in_the_same_step(world):
    aid = hold(world)["authorization_id"]
    assert world.ada.money() == (10_000, 8_000, 2_000)
    p = expect(world.bob.capture(aid, {"amount": 1_500}), 201)
    assert p["amount"] == 1_500
    assert world.ada.money() == (8_500, 8_500, 0), "capturing 1500 of 2000 returns 500 to available at once"
    check_authorization(world.bob.auth(aid), status="captured", captured_amount=1_500, remaining_amount=0)
    expect_error(world.bob.capture(aid, {"amount": 1}), 409, "authorization_not_open")


def test_explicit_final_true_is_the_default(world):
    aid = hold(world)["authorization_id"]
    expect(world.bob.capture(aid, {"amount": 100, "final": True}), 201)
    check_authorization(world.bob.auth(aid), status="captured", captured_amount=100, remaining_amount=0)
    assert world.ada.money() == (9_900, 9_900, 0)


def test_nonfinal_captures_keep_the_rest_held_until_the_last(world):
    aid = hold(world, note="n")["authorization_id"]
    p1 = expect(world.bob.capture(aid, {"amount": 700, "final": False}), 201)
    a = check_authorization(world.ada.auth(aid), status="open", captured_amount=700, remaining_amount=1_300,
                            payment_id=p1["payment_id"], payment_ids=[p1["payment_id"]])
    assert world.ada.money() == (9_300, 8_000, 1_300)
    p2 = expect(world.bob.capture(aid, {"amount": 300, "final": False}), 201)
    check_authorization(world.ada.auth(aid), status="open", captured_amount=1_000, remaining_amount=1_000,
                        payment_id=p2["payment_id"], payment_ids=[p1["payment_id"], p2["payment_id"]])
    expect_error(world.bob.capture(aid, {"amount": 1_001}), 422, "capture_exceeds_authorization")
    p3 = expect(world.bob.capture(aid), 201)          # the remainder, final by default
    assert p3["amount"] == 1_000
    check_authorization(world.ada.auth(aid), status="captured", captured_amount=2_000, remaining_amount=0,
                        payment_id=p3["payment_id"],
                        payment_ids=[p1["payment_id"], p2["payment_id"], p3["payment_id"]])
    assert world.ada.money() == (8_000, 8_000, 0) and world.bob.money() == (4_500, 4_500, 0)
    assert a["amount"] == 2_000


def test_capturing_the_entire_remainder_with_final_false_closes_it(world):
    aid = hold(world)["authorization_id"]
    expect(world.bob.capture(aid, {"amount": 500, "final": False}), 201)
    expect(world.bob.capture(aid, {"amount": 1_500, "final": False}), 201)
    check_authorization(world.bob.auth(aid), status="captured", captured_amount=2_000, remaining_amount=0)
    expect_error(world.bob.capture(aid, {"amount": 1, "final": False}), 409, "authorization_not_open")


def test_default_amount_with_final_false_takes_the_remainder_and_closes(world):
    aid = hold(world)["authorization_id"]
    expect(world.bob.capture(aid, {"amount": 200, "final": False}), 201)
    p = expect(world.bob.capture(aid, {"final": False}), 201)
    assert p["amount"] == 1_800
    check_authorization(world.bob.auth(aid), status="captured", captured_amount=2_000, remaining_amount=0)


@pytest.mark.parametrize("raw", ["700", "700.0", "7e2", "7.00E2"])
def test_integral_capture_amount_forms_are_valid(world, raw):
    aid = hold(world)["authorization_id"]
    p = expect(world.bob.post(f"/authorizations/{aid}/capture", content=('{"amount": %s}' % raw).encode(),
                              key=new_key()), 201)
    assert p["amount"] == 700 and type(p["amount"]) is int


def test_capture_payments_follow_the_feed_rule(world):
    private = hold(world, 300, visibility="private", note="secret")["authorization_id"]
    public = hold(world, 200, note="open")["authorization_id"]
    pp = expect(world.bob.capture(private), 201)
    pu = expect(world.bob.capture(public), 201)
    feeds = {h: {p["payment_id"]: p for p in world.svc.client(h).feed()} for h in ("ada", "bob", "cy", "dee")}
    for h in ("ada", "bob"):
        assert feeds[h][pp["payment_id"]] == pp and feeds[h][pu["payment_id"]] == pu
    for h in ("cy", "dee"):
        assert pp["payment_id"] not in feeds[h], "I5: a private capture is hidden from third parties"
        assert feeds[h][pu["payment_id"]] == pu


def test_capture_may_spend_the_reserved_money(world):
    aid = hold(world, 10_000)["authorization_id"]
    assert world.ada.money() == (10_000, 0, 10_000)
    expect_error(world.ada.pay("cy", 1), 409, "insufficient_funds")
    expect(world.bob.capture(aid), 201)
    assert world.ada.money() == (0, 0, 0) and world.bob.money() == (12_500, 12_500, 0)


def test_receiver_can_spend_captured_money_at_once(world):
    aid = hold(world, 1_000, frm="ada", to="dee")["authorization_id"]
    expect(world.dee.capture(aid), 201)
    expect(world.dee.pay("cy", 1_000), 201)
    assert world.dee.money() == (0, 0, 0)


# ---------------------------------------------------------------- error rows

@pytest.mark.parametrize("amount", [0, -1, 1.5, 0.5, "10", True, False, None, [], {}], ids=repr)
def test_invalid_capture_amount_is_422(world, amount):
    aid = hold(world)["authorization_id"]
    expect_error(world.bob.capture(aid, {"amount": amount}), 422, "validation_failed")
    assert world.ada.money() == (10_000, 8_000, 2_000)
    check_authorization(world.bob.auth(aid), status="open", captured_amount=0)


@pytest.mark.parametrize("amount", [2_001, MAX_AMOUNT, MAX_AMOUNT + 1, 10 ** 12], ids=repr)
def test_amount_above_the_remainder_is_capture_exceeds(world, amount):
    """D50: compared with the remainder, even above 1000000000."""
    aid = hold(world)["authorization_id"]
    expect_error(world.bob.capture(aid, {"amount": amount}), 422, "capture_exceeds_authorization")
    assert world.ada.money() == (10_000, 8_000, 2_000)


@pytest.mark.parametrize("final", ["true", "false", 1, 0, None, [], {}], ids=repr)
def test_non_boolean_final_is_400(world, final):
    aid = hold(world)["authorization_id"]
    expect_error(world.bob.capture(aid, {"amount": 100, "final": final}), 400, "malformed_request")
    assert world.ada.money() == (10_000, 8_000, 2_000)


def test_only_the_receiver_captures(world):
    aid = hold(world)["authorization_id"]
    expect_error(world.ada.capture(aid), 403, "forbidden")
    expect_error(world.cy.capture(aid), 403, "forbidden")
    assert world.ada.money() == (10_000, 8_000, 2_000)


def test_unknown_authorization_is_404(world):
    expect_error(world.bob.capture("a_does_not_exist"), 404, "not_found")
    expect_error(world.bob.capture("x" * 300), 404, "not_found")


def test_voided_authorization_is_not_open(world):
    aid = hold(world)["authorization_id"]
    expect(world.ada.void(aid), 200)
    expect_error(world.bob.capture(aid), 409, "authorization_not_open")
    expect_error(world.bob.capture(aid, {"amount": 1}), 409, "authorization_not_open")
    assert world.ada.money() == (10_000, 10_000, 0)


def test_authentication_and_key(world):
    aid = hold(world)["authorization_id"]
    expect_error(world.svc.api().capture(aid), 401, "unauthenticated")
    expect_error(world.bob.post(f"/authorizations/{aid}/capture", json={}), 400, "missing_idempotency_key")
    expect_error(world.bob.post(f"/authorizations/{aid}/capture", json={}, headers={"Idempotency-Key": ""}),
                 400, "missing_idempotency_key")
    expect_error(world.bob.capture(aid, key="k" * 256), 422, "validation_failed")
    assert world.ada.money() == (10_000, 8_000, 2_000)


def test_precedence(world):
    """PLAN 3.5 and D50, step by step."""
    aid = hold(world)["authorization_id"]
    bob, ada, cy = world.bob, world.ada, world.cy
    # 401 before the key; key before the body
    expect_error(world.svc.api().post(f"/authorizations/{aid}/capture", content=b"{nope"), 401, "unauthenticated")
    expect_error(bob.post(f"/authorizations/{aid}/capture", content=b"{nope"), 400, "missing_idempotency_key")
    expect_error(world.svc.api().post("/authorizations/a_none/capture", json={}), 401, "unauthenticated")
    # final type before the amount value
    expect_error(bob.capture(aid, {"amount": 0, "final": "yes"}), 400, "malformed_request")
    # amount value before the lookup, the caller check and the state
    expect_error(bob.capture("a_none", {"amount": 0}), 422, "validation_failed")
    expect_error(cy.capture(aid, {"amount": -1}), 422, "validation_failed")
    # unknown before the caller check
    expect_error(cy.capture("a_none"), 404, "not_found")
    # caller before the state; state before the remainder
    expect(bob.capture(aid, {"amount": 2_000}), 201)
    expect_error(ada.capture(aid, {"amount": 10 ** 9}), 403, "forbidden")
    expect_error(bob.capture(aid, {"amount": 10 ** 9}), 409, "authorization_not_open")
    expect_error(bob.capture(aid, {"amount": 0}), 422, "validation_failed")
    # a claimed key before every check after the body
    key = new_key()
    other = hold(world, 100)["authorization_id"]
    expect(bob.capture(other, {"amount": 10, "final": False}, key=key), 201)
    expect_error(bob.capture(other, {"amount": 0, "final": "x"}, key=key), 409, "idempotency_key_reuse")


# ---------------------------------------------------------------- replays (I15, I16)

def test_replay_after_the_authorization_closed_returns_the_original_payment(world):
    aid = hold(world)["authorization_id"]
    key = new_key()
    first = expect(world.bob.capture(aid, {"amount": 600}, key=key), 201)
    after = (world.ada.money(), world.bob.money())
    for _ in range(3):
        assert expect(world.bob.capture(aid, {"amount": 600}, key=key), 200) == first
    assert (world.ada.money(), world.bob.money()) == after


def test_replay_after_a_void_returns_the_original_payment(world):
    aid = hold(world)["authorization_id"]
    key = new_key()
    first = expect(world.bob.capture(aid, {"amount": 600, "final": False}, key=key), 201)
    expect(world.ada.void(aid), 200)
    assert expect(world.bob.capture(aid, {"amount": 600, "final": False}, key=key), 200) == first
    assert world.ada.money() == (9_400, 9_400, 0)


def test_empty_body_and_explicit_amount_are_different_bodies(world):
    aid = hold(world)["authorization_id"]
    key = new_key()
    expect(world.bob.capture(aid, {}, key=key), 201)
    expect_error(world.bob.capture(aid, {"amount": 2_000}, key=key), 409, "idempotency_key_reuse")


def test_final_true_and_absent_final_are_different_bodies(world):
    aid = hold(world)["authorization_id"]
    key = new_key()
    expect(world.bob.capture(aid, {"amount": 700}, key=key), 201)
    expect_error(world.bob.capture(aid, {"amount": 700, "final": True}, key=key), 409, "idempotency_key_reuse")
    assert world.ada.money() == (9_300, 9_300, 0)


def test_capture_keys_are_scoped_by_path(world):
    """A key reused on another authorization's capture is a new request (PLAN 3.9)."""
    a1 = hold(world, 300)["authorization_id"]
    a2 = hold(world, 400)["authorization_id"]
    key = new_key()
    p1 = expect(world.bob.capture(a1, {}, key=key), 201)
    p2 = expect(world.bob.capture(a2, {}, key=key), 201)
    assert p1["payment_id"] != p2["payment_id"] and (p1["amount"], p2["amount"]) == (300, 400)
    expect(world.ada.pay("bob", 1, key=key), 201)
    expect(world.ada.authorize("bob", 1, key=key), 201)


def test_percent_encoded_id_is_the_same_canonical_path(world):
    aid = hold(world)["authorization_id"]
    key = new_key()
    first = expect(world.bob.capture(aid, {"amount": 100, "final": False}, key=key), 201)
    encoded = "".join(f"%{b:02X}" for b in aid.encode())
    status, _, body = raw_request(world.svc.base_url, "POST", f"/authorizations/{encoded}/capture",
                                  token=world.bob.token, body=b'{"amount": 100, "final": false}',
                                  extra=f"Idempotency-Key: {key}\r\nContent-Type: application/json\r\n")
    assert status == 200, body[:300]
    import json
    assert json.loads(body) == first
    assert world.ada.money() == (9_900, 8_000, 1_900)


# ---------------------------------------------------------------- 2^53 guard

def test_receivers_two_to_the_53_guard_is_422_and_changes_nothing(svc):
    svc.must_reset(fixture([user("ada", 10_000), user("bob", TWO_53 - 50)]))
    ada, bob = svc.client("ada"), svc.client("bob")
    aid = expect(ada.authorize("bob", 100), 201)["authorization_id"]
    expect_error(bob.capture(aid), 422, "validation_failed")
    expect_error(bob.capture(aid, {"amount": 51, "final": False}), 422, "validation_failed")
    assert ada.money() == (10_000, 9_900, 100) and bob.balance() == TWO_53 - 50
    check_authorization(bob.auth(aid), status="open", captured_amount=0, remaining_amount=100)
    expect(bob.capture(aid, {"amount": 50, "final": False}), 201)
    assert bob.balance() == TWO_53
    assert ada.money() == (9_950, 9_900, 50)
