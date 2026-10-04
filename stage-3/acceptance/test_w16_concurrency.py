"""W16.6 and W18.4 — corrections under concurrency (stage-3 "Stable statement pagination": "Concurrent
corrections using the same expected revision cannot both succeed", "Existing snapshots remain
unchanged during concurrent payments or corrections"; PLAN 3.12). I1, I2, I55, I58, I63.

`Service.burst` asserts I2 and I30 on reads taken during each burst and I1 after it; the `svc`
teardown checks I1 and I2 in historical views.
"""
from __future__ import annotations

import threading

import pytest

from support import (error_code, expect, expect_error, fixture, new_key, no_failures, page_snapshot,
                     read_statement, tally, user)

pytestmark = pytest.mark.item(16)


def test_fifty_corrections_with_one_expected_revision_have_one_winner(world):
    """I63: exactly one 201, 49 stale_revision, and the money moves once."""
    p = expect(world.ada.pay("bob", 1_000), 201)
    pid, at = p["payment_id"], p["created_at"]
    clients = [world.svc.fresh_client("ada") for _ in range(50)]
    out = world.svc.burst(lambda i: clients[i].correct(pid, 1, 100 + i, at, key=new_key()), 50)
    no_failures(out)
    assert tally(out) == {201: 1, 409: 49}, tally(out)
    for r in out:
        if r.status_code == 409:
            expect_error(r, 409, "stale_revision")
    win = [r.json() for r in out if r.status_code == 201][0]
    revs = world.ada.revisions(pid)
    assert [x["revision"] for x in revs] == [1, 2] and revs[1] == win
    assert world.ada.balance() == 10_000 - win["amount"] and world.bob.balance() == 2_500 + win["amount"]


def test_fifty_retries_of_one_correction_apply_once(world):
    """I15/I17: one key, one body: one 201 and 49 replays."""
    p = expect(world.ada.pay("bob", 1_000), 201)
    key = new_key()
    clients = [world.svc.fresh_client("ada") for _ in range(50)]
    out = world.svc.burst(lambda i: clients[i].correct(p["payment_id"], 1, 400, p["created_at"], key=key), 50)
    no_failures(out)
    assert tally(out) == {201: 1, 200: 49}, tally(out)
    assert all(r.json() == out[0].json() for r in out), "every retry returns the one revision"
    assert world.ada.balance() == 9_600


def test_successive_revisions_race_in_order(world):
    """Each round races ten corrections on the latest revision; exactly one wins per round."""
    p = expect(world.ada.pay("bob", 500), 201)
    clients = [world.svc.fresh_client("ada") for _ in range(10)]
    for rnd in range(1, 6):
        out = world.svc.burst(lambda i: clients[i].correct(p["payment_id"], rnd, 100 * rnd + i, p["created_at"]), 10)
        no_failures(out)
        assert tally(out) == {201: 1, 409: 9}, (rnd, tally(out))
    revs = world.ada.revisions(p["payment_id"])
    assert [r["revision"] for r in revs] == list(range(1, 7))
    assert world.ada.balance() == 10_000 - revs[-1]["amount"]


def test_corrections_race_payments_and_captures_on_the_same_wallets(svc):
    """No 5xx; every outcome is a documented one; conservation and non-negative reads throughout."""
    svc.must_reset(fixture([user("ada", 5_000), user("bob", 1_000), user("cy", 300)]))
    ada, bob, cy = svc.client("ada"), svc.client("bob"), svc.client("cy")
    pays = [expect(ada.pay("bob", 200), 201) for _ in range(5)] + [expect(bob.pay("cy", 100), 201) for _ in range(3)]
    auths = [expect(ada.authorize("cy", 300), 201) for _ in range(4)]
    clients = {h: [svc.fresh_client(h) for _ in range(12)] for h in ("ada", "bob", "cy")}
    revs = {p["payment_id"]: 1 for p in pays}
    lock = threading.Lock()

    def work(i):
        kind = i % 6
        if kind in (0, 1):
            p = pays[i % len(pays)]
            who = p["from_handle"]
            with lock:
                rev = revs[p["payment_id"]]
            r = clients[who][i % 12].correct(p["payment_id"], rev, (i * 37) % 600, p["created_at"])
            if r.status_code == 201:
                with lock:
                    revs[p["payment_id"]] = max(revs[p["payment_id"]], r.json()["revision"])
            return r
        if kind == 2:
            return clients["bob"][i % 12].pay("ada", 150)
        if kind == 3:
            return clients["cy"][i % 12].capture(auths[i % 4]["authorization_id"], {"amount": 50, "final": False})
        if kind == 4:
            return clients["ada"][i % 12].pay("bob", 250)
        return clients["cy"][i % 12].pay("bob", 40)

    allowed = {(201, None), (409, "stale_revision"), (409, "insufficient_funds"), (409, "historical_overdraft"),
               (409, "authorization_not_open"), (422, "capture_exceeds_authorization")}
    for _ in range(3):
        out = svc.burst(work, 72)
        no_failures(out)
        outcomes = [(r.status_code, error_code(r) if r.status_code >= 400 else None) for r in out]
        bad = [o for o in outcomes if o not in allowed]
        assert not bad, f"unexpected outcomes: {bad[:5]}"
    for h in ("ada", "bob", "cy"):
        st = read_statement(svc.client(h), svc.accounts[h].user_id)
        assert st.closing == svc.client(h).balance(), f"{h}: the statement closes at the current balance"


def test_snapshot_pages_are_stable_while_corrections_commit(world):
    """T53, I55: pages read during a burst of corrections and payments equal the first result."""
    svc = world.svc
    pays = [expect(world.ada.pay("bob", 100 + i), 201) for i in range(30)]
    me = svc.accounts["ada"].user_id
    st = read_statement(world.ada, me, limit=7)
    readers = [svc.fresh_client("ada") for _ in range(20)]
    writers = [svc.fresh_client("ada") for _ in range(20)]

    def work(i):
        if i % 2:
            off = (i * 3) % 30
            return ("page", off, readers[i // 2].statement_page(st.snapshot, limit=5, offset=off))
        p = pays[i % 30]
        if i % 4 == 0:
            return ("write", 0, writers[i // 2].pay("bob", 1))
        return ("write", 0, writers[i // 2].correct(p["payment_id"], 1, 1 + i, p["created_at"]))

    for _ in range(3):
        out = svc.burst(work, 40)
        errors = [x for x in out if isinstance(x, Exception)]
        assert not errors, errors[:2]
        for kind, off, r in out:
            assert r.status_code < 500, r.text
            if kind == "page":
                body = expect(r, 200)
                assert body["entries"] == st.entries[off:off + 5], f"I55: the snapshot page at offset {off} changed"
                assert (body["opening_balance"], body["closing_balance"]) == (st.opening, st.closing)
    assert page_snapshot(world.ada, me, st.snapshot)[0] == st.entries
    fresh = read_statement(world.ada, me)
    assert fresh.closing == world.ada.balance()
