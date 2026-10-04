"""W2.4 — money under load (§1 invariants, §2 limits, §5 no 5xx). I1, I2, I8, I11, I27.

Every burst goes through Service.burst: balances are read throughout (I2) and the
total is checked when it ends (I1).
"""
from __future__ import annotations

import random
import threading
import time

import httpx
import pytest

from support import expect, fixture, new_key, no_failures, tally, user

pytestmark = pytest.mark.item(2)


def test_one_wallet_drained_in_parts_by_fifty_payments(svc):
    svc.must_reset(fixture([user("ada", 1_000), user("bob", 0)]))
    clients = [svc.fresh_client("ada") for _ in range(50)]
    out = svc.burst(lambda i: clients[i].pay("bob", 30), 50)
    no_failures(out)
    assert tally(out) == {201: 33, 409: 17}, tally(out)
    assert all(r.json()["error"]["code"] == "insufficient_funds" for r in out if r.status_code == 409)
    assert svc.client("ada").balance() == 10 and svc.client("bob").balance() == 990
    assert len(svc.client("bob").feed()) == 33


def test_fifty_clients_each_try_to_send_everything(svc):
    svc.must_reset(fixture([user("ada", 1_000), user("bob", 0)]))
    clients = [svc.fresh_client("ada") for _ in range(50)]
    out = svc.burst(lambda i: clients[i].pay("bob", 1_000), 50)
    no_failures(out)
    assert tally(out) == {201: 1, 409: 49}, tally(out)


def test_three_wallets_paying_around_a_cycle(svc):
    svc.must_reset(fixture([user("ann", 100), user("ben", 100), user("cat", 100)]))
    ring = ["ann", "ben", "cat"]
    clients = {h: [svc.fresh_client(h) for _ in range(17)] for h in ring}
    plan = [(ring[i % 3], ring[(i + 1) % 3], 7 + (i % 5)) for i in range(51)]

    def go(i):
        frm, to, amt = plan[i]
        return clients[frm][i // 3].pay(to, amt)

    out = svc.burst(go, 51)
    no_failures(out)
    ledger = {h: 100 for h in ring}
    for (frm, to, amt), r in zip(plan, out):
        assert r.status_code in (201, 409), r.text
        if r.status_code == 201:
            ledger[frm] -= amt
            ledger[to] += amt
    assert {h: svc.client(h).balance() for h in ring} == ledger


def test_conservation_across_fifty_wallets(svc):
    rnd = random.Random(1)
    users = [user(f"w{i:02d}", rnd.randint(0, 300)) for i in range(50)]
    svc.must_reset(fixture(users))
    handles = [u["handle"] for u in users]
    clients = {h: svc.fresh_client(h) for h in handles}
    for round_ in range(3):
        plan = [(handles[i], handles[(i + 1 + rnd.randint(0, 48)) % 50], rnd.randint(1, 150))
                for i in range(50)]
        plan = [(a, b if b != a else handles[(handles.index(a) + 1) % 50], m) for a, b, m in plan]
        expected = {h: svc.client(h).balance() for h in handles}
        out = svc.burst(lambda i: clients[plan[i][0]].pay(plan[i][1], plan[i][2]), 50)
        no_failures(out)
        for (a, b, m), r in zip(plan, out):
            assert r.status_code in (201, 409), r.text
            if r.status_code == 201:
                expected[a] -= m
                expected[b] += m
        assert {h: svc.client(h).balance() for h in handles} == expected, f"round {round_}"


def test_every_response_within_five_seconds_and_health_stays_responsive(svc):
    svc.must_reset(fixture([user("ada", 100_000), user("bob", 0)]))
    clients = [svc.fresh_client("ada") for _ in range(49)]
    health_times: list[float] = []
    health_errors: list[str] = []
    stop = threading.Event()

    def probe():
        with httpx.Client(base_url=svc.base_url, timeout=5) as c:
            while not stop.is_set():
                t = time.monotonic()
                try:
                    r = c.get("/health")
                    if r.status_code != 200:
                        health_errors.append(f"{r.status_code} {r.text[:80]}")
                except httpx.HTTPError as exc:
                    health_errors.append(repr(exc))
                health_times.append(time.monotonic() - t)

    th = threading.Thread(target=probe, daemon=True)
    th.start()
    try:
        for _ in range(3):
            out = svc.burst(lambda i: clients[i].pay("bob", 1), 49, watch=False)
            no_failures(out)
            assert tally(out) == {201: 49}
    finally:
        stop.set()
        th.join(10)
    assert not health_errors, health_errors[:3]
    assert health_times and max(health_times) < 5
    svc.assert_invariants()


def test_feed_matches_the_successful_payments_after_a_burst(svc):
    svc.must_reset(fixture([user("ada", 500), user("bob", 500), user("cy", 0)]))
    a = [svc.fresh_client("ada") for _ in range(25)]
    b = [svc.fresh_client("bob") for _ in range(25)]
    out = svc.burst(lambda i: (a[i // 2] if i % 2 == 0 else b[i // 2]).pay("cy", 40, visibility="private"), 50)
    no_failures(out)
    ok = {r.json()["payment_id"]: r.json() for r in out if r.status_code == 201}
    assert len(ok) == 24, tally(out)   # 12 of 40 from each 500 wallet
    cy_feed = {p["payment_id"]: p for p in svc.client("cy").feed()}
    assert cy_feed == ok
    assert svc.client("cy").balance() == 960


def test_mixed_valid_and_invalid_burst_has_no_5xx(world):
    bodies = [
        {"to_handle": "bob", "amount": 1}, {"to_handle": "bob", "amount": 0},
        {"to_handle": "nobody", "amount": 1}, {"to_handle": "ada", "amount": 1},
        {"to_handle": 5, "amount": 1}, {"to_handle": "bob", "amount": "x"},
        {"to_handle": "bob", "amount": 10 ** 12}, {"to_handle": "cy", "amount": 3, "note": "😀" * 10},
    ]
    clients = [world.svc.fresh_client("ada") for _ in range(48)]
    out = world.svc.burst(lambda i: clients[i].post("/payments", json=bodies[i % len(bodies)],
                                                    key=new_key()), 48)
    no_failures(out)
    assert {r.status_code for r in out} <= {201, 400, 404, 409, 422}
