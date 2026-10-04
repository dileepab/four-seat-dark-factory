"""W7.9 — holds under concurrency (stage-2 "Concurrent operations"; PLAN 3.13). I1, I2, I27, I32, I38.

`Service.burst` reads every tracked /me while the burst runs and fails on any read with a
negative figure, `held > total` or `available != total - held`; it asserts I1 afterwards.
"""
from __future__ import annotations

import pytest

from support import check_authorization, expect, fixture, new_key, no_failures, tally, user

pytestmark = pytest.mark.item(7)


def test_fifty_payments_and_holds_from_one_wallet_succeed_exactly_as_available_allows(svc):
    svc.must_reset(fixture([user("ada", 1_000), user("bob", 0), user("cy", 0)]))
    clients = [svc.fresh_client("ada") for _ in range(50)]
    out = svc.burst(lambda i: clients[i].pay("bob", 30) if i % 2 else clients[i].authorize("cy", 30), 50)
    no_failures(out)
    assert set(tally(out)) <= {201, 409}, tally(out)
    assert tally(out).get(201) == 33, tally(out)
    assert all(r.json()["error"]["code"] == "insufficient_funds" for r in out if r.status_code == 409)
    paid = sum(1 for i, r in enumerate(out) if i % 2 and r.status_code == 201)
    held = sum(1 for i, r in enumerate(out) if not i % 2 and r.status_code == 201)
    assert svc.client("ada").money() == (1_000 - 30 * paid, 10, 30 * held)
    assert svc.client("bob").balance() == 30 * paid


def test_concurrent_capture_and_void_have_one_winner(world):
    for _ in range(8):
        aid = expect(world.ada.authorize("bob", 100), 201)["authorization_id"]
        capturers = [world.svc.fresh_client("bob") for _ in range(10)]
        voiders = [world.svc.fresh_client("ada") for _ in range(10)]
        before_ada, before_bob = world.ada.balance(), world.bob.balance()
        out = world.svc.burst(lambda i: capturers[i // 2].capture(aid) if i % 2 else voiders[i // 2].void(aid), 20)
        no_failures(out)
        caps = [r for i, r in enumerate(out) if i % 2]
        voids = [r for i, r in enumerate(out) if not i % 2]
        a = check_authorization(world.ada.auth(aid))
        if a["status"] == "captured":
            assert [r.status_code for r in caps].count(201) == 1, tally(out)
            assert all(r.status_code == 409 and r.json()["error"]["code"] == "authorization_not_open"
                       for r in caps + voids if r.status_code != 201), tally(out)
            assert (world.ada.balance(), world.bob.balance()) == (before_ada - 100, before_bob + 100)
        else:
            assert a["status"] == "voided", a
            assert all(r.status_code == 200 for r in voids), tally(out)
            assert all(r.status_code == 409 and r.json()["error"]["code"] == "authorization_not_open"
                       for r in caps), tally(out)
            assert (world.ada.balance(), world.bob.balance()) == (before_ada, before_bob)
        assert world.ada.money()[2] == 0


def test_twenty_nonfinal_captures_never_exceed_the_authorized_amount(world):
    aid = expect(world.ada.authorize("bob", 1_000), 201)["authorization_id"]
    clients = [world.svc.fresh_client("bob") for _ in range(20)]
    out = world.svc.burst(lambda i: clients[i].capture(aid, {"amount": 150, "final": False}, key=new_key()), 20)
    no_failures(out)
    assert tally(out) == {201: 6, 422: 14}, tally(out)
    assert all(r.json()["error"]["code"] == "capture_exceeds_authorization" for r in out if r.status_code == 422)
    a = check_authorization(world.bob.auth(aid), status="open", captured_amount=900, remaining_amount=100)
    assert len(a["payment_ids"]) == 6 and len(set(a["payment_ids"])) == 6
    assert world.ada.money() == (9_100, 9_000, 100) and world.bob.balance() == 3_400


def test_twenty_nonfinal_captures_that_exhaust_the_hold_close_it_once(world):
    aid = expect(world.ada.authorize("bob", 1_000), 201)["authorization_id"]
    clients = [world.svc.fresh_client("bob") for _ in range(20)]
    out = world.svc.burst(lambda i: clients[i].capture(aid, {"amount": 100, "final": False}, key=new_key()), 20)
    no_failures(out)
    assert tally(out) == {201: 10, 409: 10}, tally(out)
    assert all(r.json()["error"]["code"] == "authorization_not_open" for r in out if r.status_code == 409)
    check_authorization(world.bob.auth(aid), status="captured", captured_amount=1_000, remaining_amount=0)
    assert world.ada.money() == (9_000, 9_000, 0)


def test_fifty_identical_captures_with_one_key_move_money_once(world):
    aid = expect(world.ada.authorize("bob", 1_000), 201)["authorization_id"]
    key = new_key()
    clients = [world.svc.fresh_client("bob") for _ in range(50)]
    out = world.svc.burst(lambda i: clients[i].capture(aid, {"amount": 400}, key=key), 50)
    no_failures(out)
    assert tally(out) == {200: 49, 201: 1}, tally(out)
    assert len({str(r.json()) for r in out}) == 1
    assert world.ada.money() == (9_600, 9_600, 0)


def test_holds_racing_for_the_same_available(svc):
    svc.must_reset(fixture([user("ada", 500), user("bob", 0), user("cy", 0)]))
    clients = [svc.fresh_client("ada") for _ in range(40)]
    out = svc.burst(lambda i: clients[i].authorize("bob" if i % 2 else "cy", 100), 40)
    no_failures(out)
    assert tally(out) == {201: 5, 409: 35}, tally(out)
    assert svc.client("ada").money() == (500, 0, 500)


def test_mixed_burst_of_holds_captures_voids_and_payments_conserves(world):
    aids = [expect(world.ada.authorize("bob", 50), 201)["authorization_id"] for _ in range(10)]
    clients = {h: [world.svc.fresh_client(h) for _ in range(10)] for h in ("ada", "bob", "cy")}

    def go(i):
        k, j = i % 5, i // 5
        if k == 0:
            return clients["bob"][j].capture(aids[j], {"amount": 20, "final": False}, key=new_key())
        if k == 1:
            return clients["ada"][j].void(aids[(j + 5) % 10])
        if k == 2:
            return clients["ada"][j].authorize("cy", 300)
        if k == 3:
            return clients["ada"][j].pay("cy", 400)
        return clients["cy"][j].pay("bob", 10)

    out = world.svc.burst(go, 50)
    no_failures(out)
    assert all(r.status_code < 500 for r in out)
    for aid in aids:
        a = check_authorization(world.bob.auth(aid))
        assert a["captured_amount"] == 20 * len(a["payment_ids"])
