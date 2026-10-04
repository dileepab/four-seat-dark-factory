"""W19.8, W22.4 — refunds under concurrency (stage-4 "Refunds and corrected history"; PLAN 3.12, D105). I1, I2,
I69, I70.

`Service.burst` asserts I2 and I30 on reads taken during each burst and I1 after it; the `svc` teardown checks
I1, I2 and I67 in historical views and I68 and I69 over every refund.
"""
from __future__ import annotations

import pytest

from support import error_code, expect, expect_error, instant, no_failures, tally

pytestmark = pytest.mark.item(19)


def test_fifty_refunds_of_one_payment_never_pass_the_cap(world):
    """I69: 50 refunds of 30 against a cap of 1000: exactly 33 succeed (990) and the rest are refused."""
    p = expect(world.ada.pay("bob", 1_000), 201)
    clients = [world.svc.fresh_client("bob") for _ in range(50)]
    out = world.svc.burst(lambda i: clients[i].refund(p["payment_id"], 30), 50)
    no_failures(out)
    assert tally(out) == {201: 33, 422: 17}, tally(out)
    for r in out:
        if r.status_code == 422:
            expect_error(r, 422, "refund_exceeds_payment")
    ids = {r.json()["payment_id"] for r in out if r.status_code == 201}
    assert len(ids) == 33
    assert world.ada.money() == (9_990, 9_990, 0) and world.bob.money() == (2_510, 2_510, 0)
    mine = [x for x in world.bob.feed() if x["refund_of"] == p["payment_id"]]
    assert {x["payment_id"] for x in mine} == ids


def test_twenty_refunds_at_once_each_get_their_own_created_at(world):
    """PLAN 3.9 refund step 13 (one issued created_at; stage-3 3.5: two writes never share a created_at): 20 refunds of
    20 payments committed at once have 20 distinct created_at values, each later than its target's."""
    ps = [expect(world.ada.pay("bob", 10), 201) for _ in range(20)]
    clients = [world.svc.fresh_client("bob") for _ in range(20)]
    out = world.svc.burst(lambda i: clients[i].refund(ps[i]["payment_id"], 1 + i % 10), 20)
    no_failures(out)
    assert tally(out) == {201: 20}, tally(out)
    rs = [r.json() for r in out]
    for p, r in zip(ps, rs):
        assert r["refund_of"] == p["payment_id"] and instant(r["created_at"]) > instant(p["created_at"])
    created = [instant(r["created_at"]) for r in rs]
    assert len(set(created)) == 20, f"refunds share a created_at: {sorted(r['created_at'] for r in rs)}"
    assert len(set(created) | {instant(p["created_at"]) for p in ps}) == 40, "an issued timestamp is shared"


def test_refunds_racing_a_correction_that_lowers_the_amount(world):
    """I69, D105: whichever order they commit in, the refunds never pass the amount of the latest revision."""
    p = expect(world.ada.pay("bob", 1_000), 201)
    pid, at = p["payment_id"], p["created_at"]
    bobs = [world.svc.fresh_client("bob") for _ in range(20)]
    adas = [world.svc.fresh_client("ada") for _ in range(5)]
    out = world.svc.burst(lambda i: bobs[i].refund(pid, 40) if i < 20 else adas[i - 20].correct(pid, 1, 500, at), 25)
    no_failures(out)
    refunds = [r for r in out[:20] if r.status_code == 201]
    for r in out[:20]:
        if r.status_code != 201:
            expect_error(r, 422, "refund_exceeds_payment")
    wins = [r for r in out[20:] if r.status_code == 201]
    assert len(wins) <= 1, tally(out[20:])
    for r in out[20:]:
        if r.status_code != 201:
            assert (r.status_code, error_code(r)) in {(409, "stale_revision"), (422, "refund_exceeds_payment")}, \
                tally(out[20:])
    latest = world.ada.revisions(pid)[-1]["amount"]
    refunded = 40 * len(refunds)
    assert refunded <= latest, f"I69: refunds {refunded} above the latest amount {latest}"
    assert world.bob.balance() == 2_500 + latest - refunded and world.ada.balance() == 10_000 - latest + refunded


def test_refunds_of_two_payments_racing_for_the_same_funds(world):
    """I70: the funds are checked and taken in one step, so one refund of 600 fits in 1000 and no second one."""
    p1 = expect(world.ada.pay("bob", 1_000), 201)
    p2 = expect(world.ada.pay("bob", 1_000), 201)
    expect(world.bob.pay("dee", 3_500), 201)                      # bob holds 1000
    clients = [world.svc.fresh_client("bob") for _ in range(20)]
    out = world.svc.burst(lambda i: clients[i].refund((p1 if i % 2 else p2)["payment_id"], 600), 20)
    no_failures(out)
    assert [r.status_code for r in out].count(201) == 1, tally(out)
    for r in out:
        if r.status_code != 201:
            assert (r.status_code, error_code(r)) in {(409, "insufficient_funds"), (422, "refund_exceeds_payment")}, \
                tally(out)
    assert world.bob.money() == (400, 400, 0) and world.ada.money() == (8_600, 8_600, 0)
