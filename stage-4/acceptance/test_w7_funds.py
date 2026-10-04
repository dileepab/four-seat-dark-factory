"""W7.7 — funds are judged on `available` (stage-2 "Authorizations and captures"; PLAN 3.10, D53).
I22, I31, I36."""
from __future__ import annotations

import pytest

from support import check_payment, expect, expect_error, fixture, standard_users

pytestmark = pytest.mark.item(7)


def test_payment_is_refused_when_total_covers_it_but_available_does_not(world):
    expect(world.ada.authorize("bob", 9_000), 201)
    expect_error(world.ada.pay("cy", 1_001), 409, "insufficient_funds")
    assert world.ada.money() == (10_000, 1_000, 9_000)
    p = expect(world.ada.pay("cy", 1_000), 201)
    check_payment(p, authorization_id=None, request_id=None, settlement_id=None)
    assert world.ada.money() == (9_000, 0, 9_000), "a payment moves money at once and leaves held unchanged"
    assert world.cy.money() == (1_500, 1_500, 0)


def test_payment_with_no_holds_leaves_no_hold(world):
    expect(world.ada.pay("bob", 2_500), 201)
    assert world.ada.money() == (7_500, 7_500, 0)
    assert world.ada.auths() == [], "POST /payments never creates an authorization"


def test_request_payment_is_judged_on_available(world):
    rq = expect(world.bob.ask("cy", 400), 201)["request_id"]
    a = expect(world.cy.authorize("dee", 200), 201)["authorization_id"]
    expect_error(world.cy.pay_request(rq), 409, "insufficient_funds")
    assert world.cy.money() == (500, 300, 200)
    expect(world.cy.void(a), 200)
    p = expect(world.cy.pay_request(rq), 201)
    check_payment(p, request_id=rq, authorization_id=None, settlement_id=None)
    assert world.cy.money() == (100, 100, 0)


def test_settlement_net_debit_is_judged_on_available(world):
    """D53: available + incoming - outgoing >= 0 for every wallet."""
    expect(world.bob.authorize("cy", 2_000), 201)              # bob: total 2500, available 500
    expect_error(world.ada.settle([{"from_handle": "bob", "to_handle": "dee", "amount": 501}]),
                 409, "insufficient_funds")
    expect_error(world.ada.settle([{"from_handle": "bob", "to_handle": "dee", "amount": 601},
                                   {"from_handle": "dee", "to_handle": "bob", "amount": 100}]),
                 409, "insufficient_funds")
    assert world.bob.money() == (2_500, 500, 2_000) and world.dee.money() == (0, 0, 0)
    s = expect(world.ada.settle([{"from_handle": "bob", "to_handle": "dee", "amount": 600},
                                 {"from_handle": "dee", "to_handle": "bob", "amount": 100}]), 201)
    for p in s["payments"]:
        check_payment(p, authorization_id=None, settlement_id=s["settlement_id"])
    assert world.bob.money() == (2_000, 0, 2_000) and world.dee.money() == (500, 500, 0)


def test_settlement_wallet_that_only_receives_is_never_refused(world):
    expect(world.ada.authorize("dee", 10_000), 201)           # ada: available 0
    s = expect(world.ada.settle([{"from_handle": "bob", "to_handle": "ada", "amount": 100}]), 201)
    assert s["payments"][0]["amount"] == 100
    assert world.ada.money() == (10_100, 100, 10_000)


def test_authorizations_are_judged_on_available(world):
    expect(world.cy.authorize("ada", 300), 201)
    expect_error(world.cy.authorize("bob", 201), 409, "insufficient_funds")
    expect(world.cy.authorize("bob", 200), 201)
    assert world.cy.money() == (500, 0, 500)


def test_capture_may_spend_held_money_but_not_other_holds(world):
    a1 = expect(world.cy.authorize("ada", 300), 201)["authorization_id"]
    a2 = expect(world.cy.authorize("bob", 200), 201)["authorization_id"]
    expect(world.ada.capture(a1), 201)
    assert world.cy.money() == (200, 0, 200)
    expect_error(world.cy.pay("dee", 1), 409, "insufficient_funds")
    expect(world.bob.capture(a2), 201)
    assert world.cy.money() == (0, 0, 0)


def test_receiving_does_not_free_held_money_but_raises_available(world):
    expect(world.cy.authorize("ada", 500), 201)
    expect(world.ada.pay("cy", 100), 201)
    assert world.cy.money() == (600, 100, 500)
    expect(world.cy.pay("dee", 100), 201)
    expect_error(world.cy.pay("dee", 1), 409, "insufficient_funds")


def test_with_no_holds_stage_1_results_are_unchanged(svc):
    svc.must_reset(fixture(standard_users(), operators=["u_ada"]))
    cy = svc.client("cy")
    expect_error(cy.pay("ada", 501), 409, "insufficient_funds")
    expect(cy.pay("ada", 500), 201)
    assert cy.money() == (0, 0, 0)
