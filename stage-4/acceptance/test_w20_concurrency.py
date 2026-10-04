"""W20.10, W22.4 — batches under concurrency (stage-4 "Concurrent corrections sharing any expected payment revision
cannot both succeed"; stage-3 "Existing snapshots remain unchanged during concurrent payments or corrections";
PLAN 3.12, D105). I1, I2, I55, I63, I69, I72, I76.

`Service.burst` asserts I2 and I30 on reads taken during each burst and I1 after it; the `svc` teardown checks
I1, I2 and I67 in historical views and I68 and I69 over every refund.
"""
from __future__ import annotations

import pytest

from support import (batch_item as item, error_code, expect, expect_error, instant, no_failures, page_snapshot,
                     read_statement, tally)
from test_w19_refunds import uid

pytestmark = pytest.mark.item(20)


def test_batches_and_single_corrections_on_one_revision_have_one_winner(world):
    """F42, I63, D105: ten batches and ten single corrections, all expecting revision 1: one 201, the money once."""
    p = expect(world.ada.pay("bob", 1_000), 201)
    pid, at = p["payment_id"], p["created_at"]
    clients = [world.svc.fresh_client("ada") for _ in range(20)]
    out = world.svc.burst(lambda i: clients[i].batch([item(p, 1, 500 + i)]) if i % 2
                          else clients[i].correct(pid, 1, 500 + i, at), 20)
    no_failures(out)
    assert tally(out) == {201: 1, 409: 19}, tally(out)
    for r in out:
        if r.status_code == 409:
            expect_error(r, 409, "stale_revision")
    revs = world.ada.revisions(pid)
    assert [r["revision"] for r in revs] == [1, 2]
    assert world.ada.balance() == 10_000 - revs[1]["amount"] and world.bob.balance() == 2_500 + revs[1]["amount"]


def test_twenty_batches_at_once_each_get_their_own_recorded_at(world):
    """D100, D67 (stage-3 3.5: two writes never share a created_at or recorded_at): 20 batches committed at once have
    20 distinct issued recorded_at values, each later than its payment's created_at (critic's W20 review, BR06)."""
    ps = [expect(world.ada.pay("bob", 10 + i), 201) for i in range(20)]
    clients = [world.svc.fresh_client("ada") for _ in range(20)]
    out = world.svc.burst(lambda i: clients[i].batch([item(ps[i], 1, 1 + i)]), 20)
    no_failures(out)
    assert tally(out) == {201: 20}, tally(out)
    bs = [r.json() for r in out]
    for p, b in zip(ps, bs):
        assert instant(b["recorded_at"]) > instant(p["created_at"]), "D100"
        assert [r["recorded_at"] for r in b["revisions"]] == [b["recorded_at"]]
    recorded = [instant(b["recorded_at"]) for b in bs]
    assert len(set(recorded)) == 20, f"batches share a recorded_at: {sorted(b['recorded_at'] for b in bs)}"
    assert len(set(recorded) | {instant(p["created_at"]) for p in ps}) == 40, "an issued timestamp is shared"
    assert world.bob.balance() == 2_500 + 20 * 1 + sum(range(20))


def test_two_overlapping_batches_have_one_winner(world):
    """I63: two batches sharing one payment's revision; each round exactly one commits, all of its items or none."""
    ada2 = world.svc.fresh_client("ada")
    for _ in range(5):
        x = [expect(world.ada.pay("bob", 10), 201), expect(world.bob.pay("cy", 10), 201),
             expect(world.cy.pay("dee", 10), 201)]
        bodies = [[item(x[0], 1, 5), item(x[1], 1, 5)], [item(x[1], 1, 6), item(x[2], 1, 6)]]
        out = world.svc.burst(lambda i: (world.ada if i == 0 else ada2).batch(bodies[i]), 2)
        no_failures(out)
        assert sorted(r.status_code for r in out) == [201, 409], tally(out)
        expect_error([r for r in out if r.status_code == 409][0], 409, "stale_revision")
        won = 0 if out[0].status_code == 201 else 1
        counts = [len(world.bob.revisions(x[0]["payment_id"])), len(world.cy.revisions(x[1]["payment_id"])),
                  len(world.dee.revisions(x[2]["payment_id"]))]
        assert counts == ([2, 2, 1] if won == 0 else [1, 2, 2]), (won, counts)


def test_fifty_batches_over_one_settlement_move_money_once(world):
    """I63, I72: one winner over a whole settlement; its amounts, and only its, have moved."""
    st = expect(world.ada.settle([{"from_handle": "ada", "to_handle": "cy", "amount": 100},
                                  {"from_handle": "bob", "to_handle": "dee", "amount": 50}]), 201)
    m, at = st["payments"], st["committed_at"]
    clients = [world.svc.fresh_client("ada") for _ in range(50)]
    out = world.svc.burst(lambda i: clients[i].batch([item(m[0], 1, 90 - i % 10, at), item(m[1], 1, 40, at)]), 50)
    no_failures(out)
    assert tally(out) == {201: 1, 409: 49}, tally(out)
    win = [r.json() for r in out if r.status_code == 201][0]
    a0 = win["revisions"][0]["amount"]
    assert world.cy.money() == (500 + a0, 500 + a0, 0) and world.ada.money() == (10_000 - a0, 10_000 - a0, 0)
    assert world.bob.money() == (2_460, 2_460, 0) and world.dee.money() == (40, 40, 0)
    assert world.cy.revisions(m[0]["payment_id"])[-1] == win["revisions"][0]


def test_refunds_racing_a_batch_that_lowers_the_amount(world):
    """I69 across both paths: whichever commits first, the refunds never pass the latest amount."""
    p = expect(world.ada.pay("bob", 1_000), 201)
    bobs = [world.svc.fresh_client("bob") for _ in range(20)]
    adas = [world.svc.fresh_client("ada") for _ in range(5)]
    out = world.svc.burst(lambda i: bobs[i].refund(p["payment_id"], 40) if i < 20
                          else adas[i - 20].batch([item(p, 1, 500)]), 25)
    no_failures(out)
    for r in out[:20]:
        if r.status_code != 201:
            expect_error(r, 422, "refund_exceeds_payment")
    assert [r.status_code for r in out[20:]].count(201) <= 1, tally(out[20:])
    for r in out[20:]:
        if r.status_code != 201:
            assert (r.status_code, error_code(r)) in {(409, "stale_revision"), (422, "refund_exceeds_payment")}, \
                tally(out[20:])
    latest = world.ada.revisions(p["payment_id"])[-1]["amount"]
    refunded = 40 * [r.status_code for r in out[:20]].count(201)
    assert refunded <= latest
    assert world.bob.balance() == 2_500 + latest - refunded


def test_snapshot_pages_stay_frozen_while_batches_and_refunds_commit(world):
    """W22.4, I55, I76: pages of one snapshot read during a burst of refunds and batches equal its frozen result."""
    pays = [expect(world.ada.pay("bob", 100), 201) for _ in range(30)]
    me = uid(world.svc, "bob")
    base = read_statement(world.bob, me)
    frozen = (base.entries, base.opening, base.closing)
    readers = [world.svc.fresh_client("bob") for _ in range(10)]
    bobs = [world.svc.fresh_client("bob") for _ in range(15)]
    adas = [world.svc.fresh_client("ada") for _ in range(15)]

    def work(i):
        if i < 10:
            return [page_snapshot(readers[i], me, base.snapshot, page_limit=7) for _ in range(3)]
        if i < 25:
            return bobs[i - 10].refund(pays[i - 10]["payment_id"], 10)
        return adas[i - 25].batch([item(pays[i - 10], 1, 80)])

    out = world.svc.burst(work, 40)
    for reads in out[:10]:
        assert not isinstance(reads, Exception), reads
        for got in reads:
            assert got == frozen, "a snapshot page changed while refunds and batches committed"
    no_failures(out[10:])
    assert all(r.status_code == 201 for r in out[10:]), tally(out[10:])
    assert world.bob.money() == (2_500 + 3_000 - 150 - 300, 2_500 + 3_000 - 150 - 300, 0)
    assert page_snapshot(world.bob, me, base.snapshot) == frozen
