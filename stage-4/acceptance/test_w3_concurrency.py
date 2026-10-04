"""W3.3 — at most once under concurrency (§1.3, §7; PLAN 3.13). I1, I2, I3, I17, I27."""
from __future__ import annotations

import pytest

from support import expect, fixture, new_key, no_failures, standard_users, tally, user

pytestmark = pytest.mark.item(3)


def find(items, rid):
    return next(r for r in items if r["request_id"] == rid)


def payments_for(client, rid):
    return [p for p in client.feed() if p["request_id"] == rid]


def test_twenty_concurrent_pays_with_distinct_keys_pay_once(world):
    rq = expect(world.bob.ask("ada", 700), 201)["request_id"]
    clients = [world.svc.fresh_client("ada") for _ in range(20)]
    out = world.svc.burst(lambda i: clients[i].pay_request(rq, key=new_key()), 20)
    no_failures(out)
    assert tally(out) == {201: 1, 409: 19}, tally(out)
    assert all(r.json()["error"]["code"] == "request_not_pending" for r in out if r.status_code == 409)
    assert world.ada.balance() == 9_300 and world.bob.balance() == 3_200
    assert len(payments_for(world.ada, rq)) == 1


def test_fifty_concurrent_pays_with_one_key_pay_once(world):
    rq = expect(world.bob.ask("ada", 700), 201)["request_id"]
    key = new_key()
    clients = [world.svc.fresh_client("ada") for _ in range(50)]
    out = world.svc.burst(lambda i: clients[i].pay_request(rq, {"visibility": "private"}, key=key), 50)
    no_failures(out)
    assert tally(out) == {200: 49, 201: 1}, tally(out)
    assert len({r.text for r in out}) == 1 or len({str(r.json()) for r in out}) == 1
    assert world.ada.balance() == 9_300
    assert len(payments_for(world.bob, rq)) == 1


def test_shared_key_and_distinct_keys_racing_pay_once(world):
    rq = expect(world.bob.ask("ada", 700), 201)["request_id"]
    shared = new_key()
    clients = [world.svc.fresh_client("ada") for _ in range(40)]
    out = world.svc.burst(lambda i: clients[i].pay_request(rq, key=shared if i % 2 else new_key()), 40)
    no_failures(out)
    wins = [r for r in out if r.status_code == 201]
    assert len(wins) == 1, tally(out)
    for r in out:
        if r.status_code == 200:
            assert r.json() == wins[0].json()
        elif r.status_code == 409:
            assert r.json()["error"]["code"] == "request_not_pending"
        else:
            assert r.status_code == 201
    assert world.ada.balance() == 9_300
    assert len(payments_for(world.ada, rq)) == 1


@pytest.mark.parametrize("rival", ["decline", "cancel"])
def test_pay_racing_decline_or_cancel_has_one_winner(world, rival):
    for _ in range(8):
        rq = expect(world.bob.ask("ada", 10), 201)["request_id"]
        payers = [world.svc.fresh_client("ada") for _ in range(10)]
        rivals = [world.svc.fresh_client("ada" if rival == "decline" else "bob") for _ in range(10)]

        def go(i):
            if i % 2:
                return payers[i // 2].pay_request(rq, key=new_key())
            c = rivals[i // 2]
            return c.decline(rq) if rival == "decline" else c.cancel(rq)

        before = world.ada.balance()
        out = world.svc.burst(go, 20)
        no_failures(out)
        pays = [r for i, r in enumerate(out) if i % 2]
        others = [r for i, r in enumerate(out) if not i % 2]
        status = find(world.ada.requests(), rq)["status"]
        paid = [r for r in pays if r.status_code == 201]
        if status == "paid":
            assert len(paid) == 1 and all(r.status_code == 409 for r in others), tally(out)
            assert world.ada.balance() == before - 10
        else:
            assert status == ("declined" if rival == "decline" else "cancelled")
            assert not paid and all(r.status_code == 200 for r in others), tally(out)
            assert world.ada.balance() == before
        assert all(r.status_code in (201, 409) for r in pays)


def test_decline_racing_cancel_has_one_winner(world):
    for _ in range(8):
        rq = expect(world.bob.ask("ada", 10), 201)["request_id"]
        a = [world.svc.fresh_client("ada") for _ in range(10)]
        b = [world.svc.fresh_client("bob") for _ in range(10)]
        out = world.svc.burst(lambda i: a[i // 2].decline(rq) if i % 2 else b[i // 2].cancel(rq), 20)
        no_failures(out)
        status = find(world.ada.requests(), rq)["status"]
        winners = [r for i, r in enumerate(out) if (i % 2 == 1) == (status == "declined")]
        losers = [r for i, r in enumerate(out) if (i % 2 == 1) != (status == "declined")]
        assert all(r.status_code == 200 for r in winners) and all(r.status_code == 409 for r in losers), tally(out)


def test_one_payer_short_for_many_requests_pays_what_it_can(svc):
    users = [user("ada", 1_000)] + [user(f"r{i}", 0) for i in range(10)]
    svc.must_reset(fixture(users))
    rqs = [expect(svc.client(f"r{i}").ask("ada", 300), 201)["request_id"] for i in range(10)]
    clients = [svc.fresh_client("ada") for _ in range(10)]
    out = svc.burst(lambda i: clients[i].pay_request(rqs[i]), 10)
    no_failures(out)
    assert tally(out) == {201: 3, 409: 7}, tally(out)
    assert all(r.json()["error"]["code"] == "insufficient_funds" for r in out if r.status_code == 409)
    assert svc.client("ada").balance() == 100


def test_mixed_burst_of_every_write_conserves(world):
    rqs = [expect(world.bob.ask("cy", 20), 201)["request_id"] for _ in range(10)]
    clients = {h: [world.svc.fresh_client(h) for _ in range(10)] for h in ("ada", "bob", "cy", "dee")}

    def go(i):
        k = i % 5
        j = i // 5
        if k == 0:
            return clients["ada"][j].pay("dee", 7)
        if k == 1:
            return clients["cy"][j].pay_request(rqs[j])
        if k == 2:
            return clients["dee"][j].pay("cy", 3)
        if k == 3:
            return clients["bob"][j].split(30, ["bob", "ada", "dee"])
        return clients["cy"][j].decline(rqs[(j + 5) % 10])

    out = world.svc.burst(go, 50)
    no_failures(out)
    for rid in rqs:
        r = find(world.cy.requests(), rid)
        n = len(payments_for(world.cy, rid))
        assert n == (1 if r["status"] == "paid" else 0)
