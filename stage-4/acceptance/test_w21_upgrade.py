"""W21.3 — upgrade: unchanged exports from the frozen stage-1, stage-2 and stage-3 builds import into stage 4
(stage-4 the last section; stage-1 §10; PLAN 3.6, 3.11, D54, D102, D106). I37, I65, I69, I75, I76.

`prev`, `prev2` and `prev3` are built from the frozen stage-1/, stage-2/ and stage-3/ folders. Each state is built
there, exported, and posted byte for byte to the stage-4 service. Reads on the frozen builds go through `expect`
only: their payments have no refund_of, so the stage-4 representation checks do not apply to them.
"""
from __future__ import annotations

import copy

import httpx
import pytest

from support import (EPOCH, RESET_TIMEOUT, REVISION_KEYS, STAGE1_PAYMENT_KEYS, STAGE3_PAYMENT_KEYS, batch_item as item,
                     check_batch, check_payment, expect, expect_error, fixture, instant, new_key, page_snapshot,
                     snapshot_pages, standard_users)
from test_w14_history import seeded
from test_w17_upgrade import stage2_upgrade
from test_w8_upgrade import upgrade

pytestmark = pytest.mark.item(21)


def adopt(target, source) -> None:
    target.accounts = copy.deepcopy(source.accounts)
    target._by_handle.clear()
    target.total = source.total


# ---------------------------------------------------------------- from stage 1

def test_stage_1_payments_carry_refund_of_null_and_replays_stay_verbatim(prev, svc):
    rich = upgrade(prev, svc)
    for h in rich["handles"]:
        for p in svc.client(h).feed():
            check_payment(p, refund_of=None, authorization_id=None)
    for rp in rich["replays"]:
        r = expect(svc.client(rp["who"]).post(rp["path"], json=rp["body"], key=rp["key"]), 200)
        assert r == rp["resp"], rp["path"]
        if rp["path"] == "/payments":
            assert set(r) == STAGE1_PAYMENT_KEYS, f"D54: a stored stage-1 body has no refund_of: {r}"


def _settlement(rich) -> dict:
    return [rp["resp"] for rp in rich["replays"] if rp["path"] == "/settlements"][0]


def test_an_imported_stage_1_settlement_is_corrected_as_a_whole(prev, svc):
    """W21.3: settlement membership kept, so a batch needs every member and may correct them together."""
    rich = upgrade(prev, svc)
    st = _settlement(rich)
    m, at = st["payments"], st["committed_at"]
    ada = svc.client("ada")
    expect_error(ada.correct(m[0]["payment_id"], 1, 9, at), 422, "linked_payment_immutable")
    expect_error(ada.batch([item(m[0], 1, 9, at)]), 422, "incomplete_settlement")
    b = check_batch(expect(ada.batch([item(m[0], 1, 9, at), item(m[1], 1, 5, at)]), 201), 2)
    assert [r["revision"] for r in b["revisions"]] == [2, 2]
    assert svc.client("dee").revisions(m[0]["payment_id"])[-1] == b["revisions"][0]


def test_an_imported_stage_1_settlement_member_is_refundable(prev, svc):
    rich = upgrade(prev, svc)
    st = _settlement(rich)
    m = st["payments"][0]                                          # ada -> dee 10
    dee = svc.client("dee")
    r = check_payment(expect(dee.refund(m["payment_id"], 5), 201), refund_of=m["payment_id"], settlement_id=None,
                      from_handle="dee", to_handle="ada", amount=5)
    replay = [rp for rp in rich["replays"] if rp["path"] == "/settlements"][0]
    assert expect(svc.client("ada").post("/settlements", json=replay["body"], key=replay["key"]), 200) == st
    assert r["payment_id"] not in [p["payment_id"] for p in st["payments"]]


# ---------------------------------------------------------------- from stage 2

def test_stage_2_payments_carry_refund_of_null_and_replays_stay_verbatim(prev2, svc):
    rich = stage2_upgrade(prev2, svc)
    for h in rich["before"]:
        for p in svc.client(h).feed():
            check_payment(p, refund_of=None)
    for rp in rich["replays"]:
        r = expect(svc.client(rp["who"]).post(rp["path"], json=rp["body"], key=rp["key"]), 200)
        assert r == rp["resp"], rp["path"]
        if rp["path"].endswith("/capture") or rp["path"] == "/payments":
            assert set(r) == STAGE3_PAYMENT_KEYS, f"D54: a stored stage-2 payment body has no refund_of: {r}"


def test_an_imported_stage_2_capture_is_refundable_and_its_hold_stays(prev2, svc):
    """W21.3, I70: a refund of an imported nonfinal capture leaves the open authorization and the hold alone."""
    rich = stage2_upgrade(prev2, svc)
    aid = rich["auths"]["partial"]["authorization_id"]
    cy, zed = svc.client("cy"), svc.client("zed")
    cap = [p for p in cy.feed() if p["authorization_id"] == aid][0]
    views = (zed.auth(aid), cy.auth(aid))
    held = zed.money()[2]
    r = check_payment(expect(cy.refund(cap["payment_id"], cap["amount"]), 201), refund_of=cap["payment_id"],
                      authorization_id=None, from_handle="cy", to_handle="zed")
    assert (zed.auth(aid), cy.auth(aid)) == views and zed.money()[2] == held
    expect_error(cy.refund(cap["payment_id"], 1), 422, "refund_exceeds_payment")
    assert r["visibility"] == cap["visibility"] == "private"


# ---------------------------------------------------------------- from stage 3

def stage3_state(prev3) -> dict:
    """On the frozen stage-3 build: a seeded payment, a corrected payment, a settlement, a nonfinal capture,
    statement snapshots, and the replays and snapshot pages a later stage must honour."""
    prev3.must_reset(fixture(standard_users(), operators=["u_ada"],
                             payments=[seeded("p_s", "ada", "bob", 400, "2026-01-01T00:00:00Z")]))
    replays = []

    def call(who, path, body):
        key = new_key()
        r = expect(prev3.client(who).post(path, json=body, key=key), 201)
        replays.append({"who": who, "path": path, "body": body, "key": key, "resp": r})
        return r

    s = {}
    s["p"] = call("ada", "/payments", {"to_handle": "bob", "amount": 1_000, "note": "n3"})
    s["r2"] = call("ada", f"/payments/{s['p']['payment_id']}/corrections",
                   {"expected_revision": 1, "amount": 900, "effective_at": s["p"]["created_at"], "reason": "s3 fix"})
    s["st"] = call("ada", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 100},
                                                         {"from_handle": "bob", "to_handle": "dee", "amount": 50}]})
    s["a"] = call("ada", "/authorizations", {"to_handle": "bob", "amount": 500, "note": "n-a3"})
    s["cap"] = call("bob", f"/authorizations/{s['a']['authorization_id']}/capture", {"amount": 200, "final": False})
    tokens = {}
    for h, params in (("bob", {}), ("ada", {"limit": 2, "known_at": s["r2"]["recorded_at"]}), ("cy", {"limit": 1})):
        first = expect(prev3.client(h).statement(**params), 200)
        tokens[h] = first["snapshot"]
    call("ada", "/payments", {"to_handle": "bob", "amount": 7, "note": "after the snapshots"})
    pages = {h: snapshot_pages(prev3.client(h), t) for h, t in tokens.items()}
    handles = ["ada", "bob", "cy", "dee"]
    before = {}
    for h in handles:
        c = prev3.client(h)
        feed = c.feed()
        before[h] = {"me": c.me(), "feed": feed, "requests": c.requests(), "auths": c.auths(),
                     "revisions": {p["payment_id"]: c.revisions(p["payment_id"]) for p in feed
                                   if h in (p["from_handle"], p["to_handle"])}}
    return {"s": s, "replays": replays, "tokens": tokens, "pages": pages, "before": before, "handles": handles}


def stage3_upgrade(prev3, target) -> dict:
    rich = stage3_state(prev3)
    resp = httpx.get(f"{prev3.base_url}/_test/export", timeout=RESET_TIMEOUT)
    assert expect(resp, 200)["state"]["schema"] == 3, "precondition: the frozen stage-3 build exports schema 3"
    got = target.import_raw(content=resp.content)
    assert got.status_code == 204, f"a stage-3 export must import into stage 4: {got.status_code} {got.text[:300]}"
    adopt(target, prev3)
    return rich


def test_stage_3_state_reads_back_with_refund_of_null(prev3, svc):
    """W21.3, I65: everything reads back; the only change to a payment is refund_of: null; every revision kept."""
    rich = stage3_upgrade(prev3, svc)
    for h in rich["handles"]:
        c = svc.client(h)
        old = rich["before"][h]
        assert c.me() == old["me"]
        assert c.feed() == [{**p, "refund_of": None} for p in old["feed"]]
        assert c.requests() == old["requests"] and c.auths() == old["auths"]
        for pid, revs in old["revisions"].items():
            got = c.revisions(pid)
            assert got == revs and all(set(r) == REVISION_KEYS for r in got), "every revision kept, six fields"


def test_stage_3_snapshots_page_in_their_own_form(prev3, svc, svc_b):
    """W21.3, D106 (critic plan review 1): a token paged on the frozen stage-3 build gives the same bodies as JSON
    on stage 4, without refund_of, and again after a further stage-4 export and import."""
    rich = stage3_upgrade(prev3, svc)
    for h, token in rich["tokens"].items():
        assert snapshot_pages(svc.client(h), token) == rich["pages"][h], f"D106: {h}'s stage-3 snapshot"
        entries, _, _ = page_snapshot(svc.client(h), svc.accounts[h].user_id, token,
                                      known_at=rich["pages"][h][0].get("known_at"), payment_keys=STAGE3_PAYMENT_KEYS)
        assert entries
    snap = svc.export()
    assert snap.body["state"]["schema"] == 4
    expect(svc_b.import_(snap), 204)
    for h, token in rich["tokens"].items():
        assert snapshot_pages(svc_b.client(h), token) == rich["pages"][h], f"D106: {h}'s snapshot after a round trip"
    st = expect(svc_b.client("bob").statement(limit=200), 200)
    assert all(set(e["payment"]) == STAGE3_PAYMENT_KEYS | {"refund_of"} for e in st["entries"]), \
        "a new snapshot is in the stage-4 form"


def test_stage_3_replays_return_their_stored_bodies(prev3, svc):
    rich = stage3_upgrade(prev3, svc)
    for rp in rich["replays"]:
        r = expect(svc.client(rp["who"]).post(rp["path"], json=rp["body"], key=rp["key"]), 200)
        assert r == rp["resp"], rp["path"]
    assert set(rich["s"]["p"]) == STAGE3_PAYMENT_KEYS and set(rich["s"]["r2"]) == REVISION_KEYS


def test_imported_stage_3_payments_take_refunds_and_batches(prev3, svc):
    """W21.3: a refund of an imported capture, of an imported settlement member and of an imported corrected
    payment (capped by its latest revision), and a batch over the imported settlement."""
    rich = stage3_upgrade(prev3, svc)
    s = rich["s"]
    ada, bob, cy = svc.client("ada"), svc.client("bob"), svc.client("cy")
    aid = s["a"]["authorization_id"]
    view = bob.auth(aid)
    check_payment(expect(bob.refund(s["cap"]["payment_id"], 200), 201), refund_of=s["cap"]["payment_id"])
    assert bob.auth(aid) == view
    m, at = s["st"]["payments"], s["st"]["committed_at"]
    check_payment(expect(cy.refund(m[0]["payment_id"], 30), 201), refund_of=m[0]["payment_id"], settlement_id=None)
    expect_error(bob.refund(s["p"]["payment_id"], 901), 422, "refund_exceeds_payment")
    expect(bob.refund(s["p"]["payment_id"], 900), 201)
    expect_error(ada.batch([item(m[0], 1, 29, at), item(m[1], 1, 50, at)]), 422, "refund_exceeds_payment")
    b = check_batch(expect(ada.batch([item(m[0], 1, 30, at), item(m[1], 1, 50, at), item("p_s", 1, 350,
                                                                                       "2026-01-01T00:00:00Z")]),
                           201), 3)
    latest = max(instant(t) for v in rich["before"].values() for p in v["feed"] for t in [p["created_at"]])
    assert instant(b["recorded_at"]) > max(latest, instant(s["r2"]["recorded_at"]))
    assert svc.client("dee").revisions(m[1]["payment_id"])[-1] == b["revisions"][1]
    assert ada.me_at(EPOCH)["total"] == 10_400, "ada's opening balance (10000 after the seeded 400) never changes"
