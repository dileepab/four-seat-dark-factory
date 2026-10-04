"""W7.4 — POST /authorizations/{id}/void (stage-2 "API"; PLAN 3.5, 3.6, 3.10). I8, I33, I35."""
from __future__ import annotations

import pytest

from support import check_authorization, expect, expect_error, fixture, seeded_auth, standard_users

pytestmark = pytest.mark.item(7)


def hold(world, amount=2_000, frm="ada", to="bob", **extra) -> dict:
    return expect(world.svc.client(frm).authorize(to, amount, **extra), 201)


def test_payer_voids_an_open_hold_and_the_remainder_is_released(world):
    a = hold(world, note="deposit", visibility="private")
    v = expect(world.ada.void(a["authorization_id"]), 200)
    check_authorization(v, status="voided", captured_amount=0, remaining_amount=0, payment_id=None,
                        payment_ids=[], amount=2_000, note="deposit", visibility="private")
    for k in ("authorization_id", "from_user_id", "to_user_id", "amount", "currency", "expires_at", "created_at"):
        assert v[k] == a[k], k
    assert world.ada.money() == (10_000, 10_000, 0) and world.bob.money() == (2_500, 2_500, 0)
    assert world.ada.auth(a["authorization_id"]) == v == world.bob.auth(a["authorization_id"])
    assert world.ada.feed() == [], "a void moves no money and adds no feed item"


def test_voiding_again_is_200_with_the_current_state(world):
    aid = hold(world)["authorization_id"]
    v1 = expect(world.ada.void(aid), 200)
    v2 = expect(world.ada.void(aid), 200)
    assert v1 == v2
    assert world.ada.money() == (10_000, 10_000, 0)


def test_void_keeps_partial_captures(world):
    aid = hold(world)["authorization_id"]
    p = expect(world.bob.capture(aid, {"amount": 700, "final": False}), 201)
    v = expect(world.ada.void(aid), 200)
    check_authorization(v, status="voided", captured_amount=700, remaining_amount=0,
                        payment_id=p["payment_id"], payment_ids=[p["payment_id"]])
    assert world.ada.money() == (9_300, 9_300, 0) and world.bob.money() == (3_200, 3_200, 0)
    assert any(x["payment_id"] == p["payment_id"] for x in world.ada.feed())


def test_only_the_payer_voids(world):
    aid = hold(world)["authorization_id"]
    expect_error(world.bob.void(aid), 403, "forbidden")
    expect_error(world.cy.void(aid), 403, "forbidden")
    check_authorization(world.ada.auth(aid), status="open", remaining_amount=2_000)
    assert world.ada.money() == (10_000, 8_000, 2_000)


def test_captured_authorization_is_not_open(world):
    aid = hold(world)["authorization_id"]
    expect(world.bob.capture(aid, {"amount": 5}), 201)
    expect_error(world.ada.void(aid), 409, "authorization_not_open")
    check_authorization(world.ada.auth(aid), status="captured", captured_amount=5)


def test_seeded_closed_authorizations_cannot_be_voided(svc):
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_cap", "ada", "bob", 100, status="captured"),
        seeded_auth("a_exp", "ada", "bob", 100, status="expired"),
        seeded_auth("a_past", "ada", "bob", 100, hours=-1.5),
        seeded_auth("a_void", "ada", "bob", 100, status="voided")]))
    ada = svc.client("ada")
    for aid in ("a_cap", "a_exp", "a_past"):
        expect_error(ada.void(aid), 409, "authorization_not_open")
    v = expect(ada.void("a_void"), 200)
    check_authorization(v, status="voided", authorization_id="a_void")
    assert ada.money() == (10_000, 10_000, 0)


def test_unknown_is_404_and_auth_first(world):
    expect_error(world.ada.void("a_none"), 404, "not_found")
    expect_error(world.cy.void("a_none"), 404, "not_found")
    aid = hold(world)["authorization_id"]
    expect_error(world.svc.api().void(aid), 401, "unauthenticated")
    expect_error(world.svc.api().void("a_none"), 401, "unauthenticated")


def test_caller_check_comes_before_the_state(world):
    aid = hold(world)["authorization_id"]
    expect(world.bob.capture(aid), 201)
    expect_error(world.bob.void(aid), 403, "forbidden")
    expect_error(world.cy.void(aid), 403, "forbidden")


def test_void_needs_no_key_and_never_reads_the_body(world):
    a1 = hold(world, 100)["authorization_id"]
    a2 = hold(world, 200)["authorization_id"]
    a3 = hold(world, 300)["authorization_id"]
    expect(world.ada.post(f"/authorizations/{a1}/void", content=b"{nope"), 200)
    expect(world.ada.post(f"/authorizations/{a2}/void", key="any-key", json={"status": "open"}), 200)
    expect(world.ada.post(f"/authorizations/{a3}/void", content=b"[1, 2"), 200)
    assert world.ada.money() == (10_000, 10_000, 0)
