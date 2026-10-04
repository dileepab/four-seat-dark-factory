"""W8.3 — upgrade: an unchanged export from the frozen stage-1 build imports into stage 2
(stage-2 "Existing clients after an upgrade"; stage-1 §10; PLAN 3.12, D54). I15, I26, I28, I29, I37.

`prev` is a container built from the frozen stage-1/ folder. The stage-1 state is built there
with the same operations as the stage-1 W5 checks, exported, and posted byte for byte to the
stage-2 service.
"""
from __future__ import annotations

import copy

import httpx
import pytest

from support import (RESET_TIMEOUT, STAGE1_PAYMENT_KEYS, Snapshot, check_payment, expect, expect_error,
                     new_key, ts)
from test_w5_export_import import SAM_PW, build_rich_state, observe, rich_fixture

pytestmark = pytest.mark.item(8)


def stage1_export(prev) -> tuple[Snapshot, bytes]:
    resp = httpx.get(f"{prev.base_url}/_test/export", timeout=RESET_TIMEOUT)
    body = expect(resp, 200)
    return Snapshot(body, resp.text, prev.total, copy.deepcopy(prev.accounts)), resp.content


def upgrade(prev, target) -> dict:
    """Build the stage-1 state, export it unchanged and import those exact bytes into stage 2."""
    rich = build_rich_state(prev)
    rich["before"] = observe(prev, rich["handles"])
    snap, raw = stage1_export(prev)
    resp = target.import_raw(content=raw)
    assert resp.status_code == 204, f"a stage-1 export must import into stage 2: {resp.status_code} {resp.text[:300]}"
    target.accounts = copy.deepcopy(snap.accounts)
    target._by_handle.clear()
    target.total = snap.total
    rich["snap"] = snap
    return rich


def with_null_authorization(p: dict) -> dict:
    """A stage-1 payment as stage 4 shows it: authorization_id and refund_of null (stage-4 PLAN 3.6)."""
    return {**p, "authorization_id": None, "refund_of": None}


def test_stage_1_export_imports_and_reads_back_through_stage_2(prev, svc):
    rich = upgrade(prev, svc)
    for h in rich["handles"]:
        old = rich["before"][h]
        c = svc.client(h)                     # the stage-1 token
        me = c.me()
        assert {k: me[k] for k in old["me"]} == old["me"]
        assert me["balance"] == me["total"] == me["available"] and me["held"] == 0, me
        feed = c.feed()
        assert feed == [with_null_authorization(p) for p in old["feed"]], f"{h}: the feed changed in the upgrade"
        for p in feed:
            check_payment(p, authorization_id=None, refund_of=None)
        assert c.requests() == old["requests"]
        assert c.auths() == []


def test_stage_1_replays_return_the_stored_bodies_unchanged(prev, svc):
    """D54: a replay returns the stored stage-1 body verbatim, so a payment in it has no authorization_id."""
    rich = upgrade(prev, svc)
    for rp in rich["replays"]:
        r = svc.client(rp["who"]).post(rp["path"], json=rp["body"], key=rp["key"])
        assert expect(r, 200) == rp["resp"], rp["path"]
        if rp["path"] == "/payments" or rp["path"].endswith("/pay"):
            assert set(rp["resp"]) == STAGE1_PAYMENT_KEYS, rp["resp"]
    after = observe(svc, rich["handles"])
    assert {h: v["me"]["balance"] for h, v in after.items()} == \
        {h: v["me"]["balance"] for h, v in rich["before"].items()}, "a replay moved money"


def test_logins_tokens_and_permissions_survive(prev, svc):
    rich = upgrade(prev, svc)
    for h, acct in rich["snap"].accounts.items():
        assert acct.token, h
        expect(svc.api(acct.token).get("/me"), 200)
        expect(svc.login(acct.email, acct.password), 200)
    expect_error(svc.login("sam@example.com", "wrong password"), 401, "unauthenticated")
    expect(svc.login("sam@example.com", SAM_PW), 200)
    expect(svc.client("ada").settle([{"from_handle": "bob", "to_handle": "dee", "amount": 1}]), 201)
    expect_error(svc.client("bob").settle([{"from_handle": "bob", "to_handle": "dee", "amount": 1}]),
                 403, "forbidden")


def test_failed_keys_pending_requests_and_new_holds_work(prev, svc):
    rich = upgrade(prev, svc)
    expect(svc.client("cy").pay("dee", 1, key=rich["failed_key"]), 201)
    expect(svc.client("ada").pay_request(rich["pending"]), 201)
    a = expect(svc.client("ada").authorize("zed", 300), 201)
    assert svc.client("ada").money()[2] == 300
    p = expect(svc.client("zed").capture(a["authorization_id"], {"amount": 100}), 201)
    assert p["authorization_id"] == a["authorization_id"]
    assert (ts(a["expires_at"]) - ts(a["created_at"])).total_seconds() == 600, "a stage-1 state has TTL 600"


def test_new_ids_never_collide_and_time_moves_forward(prev, svc):
    rich = upgrade(prev, svc)
    before = rich["before"]
    old = set()
    stamps = []
    for v in before.values():
        old.add(v["me"]["user_id"])
        old.update(p["payment_id"] for p in v["feed"])
        old.update(r["request_id"] for r in v["requests"])
        stamps += [p["created_at"] for p in v["feed"]] + [r["created_at"] for r in v["requests"]]
    for rp in rich["replays"]:
        old.update(str(rp["resp"].get(k)) for k in ("split_id", "settlement_id") if k in rp["resp"])
    latest = max(ts(x) for x in stamps)
    ada = svc.client("ada")
    new, times = set(), []
    for _ in range(5):
        p = expect(ada.pay("bob", 1), 201)
        r = expect(ada.ask("cy", 1), 201)
        sp = expect(ada.split(2, ["ada", "dee"]), 201)
        st = expect(ada.settle([{"from_handle": "ada", "to_handle": "dee", "amount": 1}]), 201)
        a = expect(ada.authorize("bob", 1), 201)
        new |= {p["payment_id"], r["request_id"], sp["split_id"], st["settlement_id"], a["authorization_id"]}
        times += [p["created_at"], r["created_at"], sp["created_at"], st["committed_at"], a["created_at"]]
    assert not new & old, f"new ids collide with imported ones: {new & old}"
    assert all(ts(t) >= latest for t in times)


def test_upgraded_state_round_trips_through_a_stage_2_export(prev, svc, svc_b):
    """I15: replays survive a stage-1 import followed by a stage-2 export and import."""
    rich = upgrade(prev, svc)
    a = expect(svc.client("ada").authorize("bob", 50), 201)
    snap2 = svc.export()
    # Schema 3 from W17.1, schema 4 from W21.1 (test_w8_export_import: test_export_has_format_version_1_and_schema_4).
    assert snap2.body["state"].get("schema") in (2, 3, 4)
    before = observe(svc, rich["handles"])
    expect(svc_b.import_(snap2), 204)
    after = observe(svc_b, rich["handles"])
    assert after == before
    assert all(p["authorization_id"] is None for v in after.values() for p in v["feed"])
    for rp in rich["replays"]:
        r = svc_b.client(rp["who"]).post(rp["path"], json=rp["body"], key=rp["key"])
        assert expect(r, 200) == rp["resp"], rp["path"]
    expect(svc_b.client("bob").capture(a["authorization_id"]), 201)


def test_a_payment_lost_before_the_export_is_recovered_after_the_upgrade(prev, svc):
    """The response of a stage-1 payment was lost; the client retries against stage 2 with the same key."""
    prev.must_reset(rich_fixture())
    key = new_key()
    body = {"to_handle": "bob", "amount": 321, "note": "lost"}
    original = expect(prev.client("ada").post("/payments", json=body, key=key), 201)
    snap, raw = stage1_export(prev)
    assert svc.import_raw(content=raw).status_code == 204
    svc.accounts, svc.total = copy.deepcopy(snap.accounts), snap.total
    svc._by_handle.clear()
    again = expect(svc.client("ada").post("/payments", json=body, key=key), 200)
    assert again == original
    assert svc.client("ada").balance() == 10_000 - 321 and svc.client("bob").balance() == 2_500 + 321
    assert [p["payment_id"] for p in svc.client("ada").feed() if p["note"] == "lost"] == [original["payment_id"]]
