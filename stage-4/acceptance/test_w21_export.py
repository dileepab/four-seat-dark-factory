"""W21.1, W21.2, W21.4 — export schema 4, round trips and rejected schema-4 imports (stage-1 §10; stage-4 the last
section; PLAN 3.6, 3.11, D102, D106). I25, I26, I65, I69, I72, I76.

The state format is opaque apart from `schema` (PLAN 3.11 names what it holds, not how). The corruption probes find
what to corrupt by values the suite itself put into the state: payment ids, sentinel correction reasons, a batch's
recorded_at. A probe changes one rule only: every other rule of PLAN 3.11 still holds for the corrupted state.
"""
from __future__ import annotations

import copy
import json

import httpx
import pytest

from support import (EPOCH, FAR_FUTURE, RESET_TIMEOUT, Snapshot, batch_item as item, describe, error_code, expect,
                     expect_error, fixture, instant, new_key, no_failures, read_statement, shifted, snapshot_pages, user)
from test_w8_export_import import _swap

pytestmark = pytest.mark.item(21)

HANDLES = ["ada", "bob", "cy", "dee"]


def build_state(svc) -> dict:
    """Refunds, a capture, a settlement, corrections and a batch over ordinary payments and a whole settlement,
    snapshots before and after, and the payments the probes below re-point refunds at."""
    svc.must_reset(fixture([user("ada", 10_000), user("bob", 5_000), user("cy", 5_000), user("dee", 1_000)],
                           operators=["u_ada"]))
    replays = []

    def call(who, path, body):
        key = new_key()
        r = expect(svc.client(who).post(path, json=body, key=key), 201)
        replays.append({"who": who, "path": path, "body": body, "key": key, "resp": r})
        return r

    s = {}
    s["p"] = call("ada", "/payments", {"to_handle": "bob", "amount": 1_000, "note": "n-p"})
    s["q0"] = call("bob", "/payments", {"to_handle": "ada", "amount": 700, "note": "n-q0"})
    s["r0"] = call("ada", f"/payments/{s['q0']['payment_id']}/refunds", {"amount": 650})        # ada -> bob
    s["cyd"] = call("cy", "/payments", {"to_handle": "dee", "amount": 700, "note": "n-p"})
    s["u"] = call("ada", "/payments", {"to_handle": "bob", "amount": 500, "note": "n-p"})
    s["r1"] = call("bob", f"/payments/{s['p']['payment_id']}/refunds", {"amount": 600})          # bob -> ada
    s["r2"] = call("bob", f"/payments/{s['u']['payment_id']}/refunds", {"amount": 450})
    s["late"] = call("ada", "/payments", {"to_handle": "bob", "amount": 900, "note": "n-p"})
    s["x"] = call("bob", "/payments", {"to_handle": "ada", "amount": 50, "note": "n-p"})
    s["xr"] = call("bob", f"/payments/{s['x']['payment_id']}/corrections",
                   {"expected_revision": 1, "amount": 50, "effective_at": s["x"]["created_at"], "reason": "zz-x-fix"})
    s["a"] = call("ada", "/authorizations", {"to_handle": "bob", "amount": 300, "note": "n-a"})
    s["cap"] = call("bob", f"/authorizations/{s['a']['authorization_id']}/capture", {"amount": 100, "final": False})
    s["y"] = call("ada", "/payments", {"to_handle": "bob", "amount": 50, "note": "n-a"})
    s["yr"] = call("ada", f"/payments/{s['y']['payment_id']}/corrections",
                   {"expected_revision": 1, "amount": 50, "effective_at": s["y"]["created_at"], "reason": "zz-y-fix"})
    s["b1"] = call("bob", "/payments", {"to_handle": "cy", "amount": 100, "note": "n-b1"})
    s["b2"] = call("cy", "/payments", {"to_handle": "dee", "amount": 100, "note": "n-b2"})
    s["st"] = call("ada", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 30},
                                                         {"from_handle": "dee", "to_handle": "bob", "amount": 20}]})
    m, at = s["st"]["payments"], s["st"]["committed_at"]
    s["batch"] = call("ada", "/correction-batches", {"corrections": [
        item(s["b1"], 1, 90, reason="zz-b-1"), item(s["b2"], 1, 80, reason="zz-b-2"),
        item(m[0], 1, 25, at, reason="zz-b-m0"), item(m[1], 1, 20, at, reason="zz-b-m1")]})
    s["rm"] = call("cy", f"/payments/{m[0]['payment_id']}/refunds", {"amount": 10})
    failed = new_key()
    expect_error(svc.client("bob").refund(s["p"]["payment_id"], 401, key=failed), 422, "refund_exceeds_payment")
    rec = s["batch"]["recorded_at"]
    snaps = {"bob": read_statement(svc.client("bob"), svc.accounts["bob"].user_id),
             "ada": read_statement(svc.client("ada"), svc.accounts["ada"].user_id, limit=2,
                                   known_at=shifted(rec, -1))}
    # Written after the snapshots, so the snapshots must not see them.
    s["r3"] = call("bob", f"/payments/{s['p']['payment_id']}/refunds", {"amount": 10})
    marks = [s["p"]["created_at"], s["r1"]["created_at"], shifted(rec, -1), rec, at, s["rm"]["created_at"]]
    return {"s": s, "replays": replays, "snaps": snaps, "marks": marks, "failed_key": failed}


def observe(svc, rich, handles=HANDLES) -> dict:
    """Everything a caller can read: me, feed, requests, authorizations, revisions, history views, statements and
    the stored snapshots' pages (as JSON)."""
    out = {}
    rec = rich["s"]["batch"]["recorded_at"]
    for h in handles:
        c = svc.client(h)
        feed = c.feed()
        st = read_statement(c, svc.accounts[h].user_id)
        out[h] = {"me": c.me(), "feed": feed, "requests": c.requests(), "auths": c.auths(),
                  "revisions": {p["payment_id"]: c.revisions(p["payment_id"]) for p in feed
                                if h in (p["from_handle"], p["to_handle"])},
                  "views": [c.me_at(t, k) for t in [EPOCH] + rich["marks"] + [FAR_FUTURE]
                            for k in (None, shifted(rec, -1))],
                  "statement": (st.opening, st.closing, st.entries)}
    for h, st in rich["snaps"].items():
        out[f"snapshot_{h}"] = snapshot_pages(svc.client(h), st.snapshot)
    return out


def assert_restored(svc, rich, before) -> None:
    assert observe(svc, rich) == before
    for rp in rich["replays"]:
        r = svc.client(rp["who"]).post(rp["path"], json=rp["body"], key=rp["key"])
        assert expect(r, 200) == rp["resp"], f"a replay after import: {rp['path']}"
    assert observe(svc, rich) == before, "replays after import changed state"


# ---------------------------------------------------------------- W21.1 export

def test_export_is_schema_4_and_holds_refunds_batches_and_keys(svc):
    """I26 (amended): every refund link, every batch id on a revision and the keys of the two new paths."""
    rich = build_state(svc)
    body = svc.export().body
    assert body["track"] == "pocketful" and body["format_version"] == 1 and type(body["format_version"]) is int
    assert body["state"].get("schema") == 4 and type(body["state"]["schema"]) is int, "PLAN 3.11: schema 4"
    text = json.dumps(body, ensure_ascii=False)
    s = rich["s"]
    for v in (s["r1"]["payment_id"], s["rm"]["payment_id"], s["batch"]["correction_batch_id"], "zz-b-m1",
              *[rp["key"] for rp in rich["replays"] if rp["path"].endswith("/refunds")
                or rp["path"] == "/correction-batches"]):
        assert v in text, f"PLAN 3.11: the export holds {v!r}"


def test_export_is_read_only(svc):
    rich = build_state(svc)
    before = observe(svc, rich)
    for _ in range(3):
        svc.export()
    assert observe(svc, rich) == before


# ---------------------------------------------------------------- W21.2 round trips

def test_round_trip_in_the_same_container(svc):
    rich = build_state(svc)
    before = observe(svc, rich)
    snap = svc.export()
    s = rich["s"]
    expect(svc.client("bob").refund(s["p"]["payment_id"], 5), 201)
    expect(svc.client("ada").batch([item(s["b1"], 2, 70)]), 201)
    extra = read_statement(svc.client("cy"), svc.accounts["cy"].user_id).snapshot
    expect(svc.import_(snap), 204)
    assert_restored(svc, rich, before)
    expect_error(svc.client("cy").statement(snapshot=extra), 404, "not_found")


def test_round_trip_into_a_second_container(svc, svc_b):
    """W21.2, D106: the same reads, the same snapshot pages as JSON, every replay; the failed key is free."""
    rich = build_state(svc)
    before = observe(svc, rich)
    snap = svc.export()
    svc_b.must_reset(fixture([user("ada", 1)]))
    expect(svc_b.import_(snap), 204)
    assert_restored(svc_b, rich, before)
    expect(svc_b.client("bob").refund(rich["s"]["p"]["payment_id"], 380, key=rich["failed_key"]), 201)


def test_after_import_the_cap_links_and_immutability_hold(svc, svc_b):
    """W21.2, I69: refunds keep counting toward the cap; a refund stays a refund; batch revisions keep their id."""
    rich = build_state(svc)
    s = rich["s"]
    expect(svc_b.import_(svc.export()), 204)
    bob, ada, cy = svc_b.client("bob"), svc_b.client("ada"), svc_b.client("cy")
    pid = s["p"]["payment_id"]                                    # 1000, refunded 600 + 10
    expect_error(bob.refund(pid, 391), 422, "refund_exceeds_payment")
    expect(bob.refund(pid, 390), 201)
    expect_error(ada.refund(s["r1"]["payment_id"], 1), 422, "invalid_refund_target")
    expect_error(bob.correct(s["r1"]["payment_id"], 1, 1, s["r1"]["created_at"]), 422, "linked_payment_immutable")
    expect_error(ada.correct(pid, 1, 999, s["p"]["created_at"]), 422, "refund_exceeds_payment")
    m = s["st"]["payments"]
    expect_error(ada.correct(m[0]["payment_id"], 2, 26, s["st"]["committed_at"]), 422, "linked_payment_immutable")
    expect_error(ada.batch([item(m[0], 2, 9, s["st"]["committed_at"]), item(m[1], 2, 20, s["st"]["committed_at"])]),
                 422, "refund_exceeds_payment")
    revs = cy.revisions(m[0]["payment_id"])
    assert revs[-1]["correction_batch_id"] == s["batch"]["correction_batch_id"]
    assert [x for x in cy.feed() if x["payment_id"] == s["rm"]["payment_id"]][0]["refund_of"] == m[0]["payment_id"]


def test_new_writes_after_import_are_later_than_everything_imported(svc, svc_b):
    rich = build_state(svc)
    s = rich["s"]
    expect(svc_b.import_(svc.export()), 204)
    latest = max(instant(t) for t in [s["r3"]["created_at"], s["batch"]["recorded_at"], s["rm"]["created_at"]])
    r = expect(svc_b.client("bob").refund(s["u"]["payment_id"], 1), 201)
    b = expect(svc_b.client("ada").batch([item(s["b2"], 2, 70)]), 201)
    assert instant(r["created_at"]) > latest and instant(b["recorded_at"]) > instant(r["created_at"])
    assert b["correction_batch_id"] != s["batch"]["correction_batch_id"]


def test_export_during_a_burst_of_refunds_and_batches_is_one_snapshot(svc, svc_b):
    """W21.1: built in one synchronous step, so every export validates and imports (the cap included)."""
    svc.must_reset(fixture([user("ada", 10_000), user("bob", 5_000), user("cy", 500), user("dee", 0)],
                           operators=["u_ada"]))
    ada = svc.client("ada")
    pays = [expect(ada.pay("bob", 100), 201) for _ in range(20)]
    exports: list = []

    def work(i):
        if i % 5 == 0:
            resp = httpx.get(f"{svc.base_url}/_test/export", timeout=RESET_TIMEOUT)
            exports.append(resp)
            return resp
        p = pays[i % 20]
        if i % 2:
            return svc.fresh_client("bob").refund(p["payment_id"], 60)
        return svc.fresh_client("ada").batch([item(p, 1, 70)])

    out = svc.burst(work, 40)
    no_failures(out)
    writes = [(i, r) for i, r in enumerate(out) if i % 5]
    for i, r in writes:
        if r.status_code != 201:
            assert (r.status_code, error_code(r)) in {(409, "stale_revision"), (422, "refund_exceeds_payment")}, \
                (i, describe(r))
    assert any(r.status_code == 201 for i, r in writes if i % 2) and any(r.status_code == 201 for i, r in writes
                                                                        if not i % 2), "refunds and batches committed"
    for resp in exports:
        snap = Snapshot(expect(resp, 200), resp.text, svc.total, copy.deepcopy(svc.accounts))
        expect(svc_b.import_(snap), 204)
        assert sum(svc_b.client(h).balance() for h in ("ada", "bob", "cy", "dee")) == svc.total


# ---------------------------------------------------------------- W21.4 rejected schema-4 imports

def _records_holding_all(node, values, out=None) -> list[dict]:
    """Every object that holds each of `values` (type-exact) directly as a field value."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if all(any(type(x) is type(v) and x == v for x in node.values()) for v in values):
            out.append(node)
        for v in node.values():
            _records_holding_all(v, values, out)
    elif isinstance(node, list):
        for v in node:
            _records_holding_all(v, values, out)
    return out


def _repoint(state, refund: dict, old_target: str, new_target) -> None:
    """Make every record of `refund` that names `old_target` name `new_target` instead (its payment record, and
    its stored 201 body, which only a replay reads)."""
    recs = _records_holding_all(state, (refund["payment_id"], old_target))
    assert recs, f"no record holds {refund['payment_id']} with {old_target}; this probe cannot run"
    for rec in recs:
        _swap(rec, old_target, new_target)


def _link(state, linked: dict, link_value: str, payment: dict) -> None:
    """Give `payment` the link field `linked` has (the field whose value is `link_value`), in every record of
    `payment` that holds that field as null: a refund_of or an authorization_id on a corrected payment."""
    fields = {k for rec in _records_holding_all(state, (linked["payment_id"], link_value))
              for k, v in rec.items() if type(v) is str and v == link_value}
    assert fields, f"no record of {linked['payment_id']} holds {link_value}; this probe cannot run"
    n = 0
    for rec in _records_holding_all(state, (payment["payment_id"],)):
        for k in fields:
            if k in rec and rec[k] is None:
                rec[k] = link_value
                n += 1
    assert n, f"no record of {payment['payment_id']} has a null {sorted(fields)}; this probe cannot run"


def corrupt(body: dict, rich: dict, how: str) -> dict:
    body = copy.deepcopy(body)
    state = body["state"]
    s = rich["s"]
    r1, p = s["r1"], s["p"]["payment_id"]
    if how == "refund_of an unknown payment":
        _repoint(state, r1, p, "p_ghost_target")
    elif how == "refund_of a refund":
        _repoint(state, r1, p, s["r0"]["payment_id"])              # r0 is ada -> bob, 650, earlier than r1
    elif how == "refund_of a later payment":
        _repoint(state, r1, p, s["late"]["payment_id"])            # ada -> bob 900, created after r1
    elif how == "refund parties not the target's reversed":
        _repoint(state, r1, p, s["cyd"]["payment_id"])             # cy -> dee 700, earlier, not a refund
    elif how == "refunds above the target's latest amount":
        _repoint(state, s["r2"], s["u"]["payment_id"], p)          # p: 600 + 10 + 450 > 1000
    elif how == "a refund with two revisions":
        _link(state, r1, p, s["x"])                                # x: bob -> ada 50, corrected once
    elif how == "a capture with two revisions":
        _link(state, s["cap"], s["a"]["authorization_id"], s["y"])  # y: ada -> bob 50, corrected once
    elif how == "one batch id with two recorded_at":
        rec = s["batch"]["recorded_at"]
        recs = _records_holding_all(state, ("zz-b-2", rec))
        assert recs, "no record holds the batch revision of b2; this probe cannot run"
        for r in recs:
            _swap(r, rec, shifted(rec, 1_000, digits=3))
    elif how.startswith("schema "):
        state["schema"] = json.loads(how.split(" ", 1)[1])
    else:
        raise AssertionError(how)
    return body


REJECTS = ["refund_of an unknown payment", "refund_of a refund", "refund_of a later payment",
           "refund parties not the target's reversed", "refunds above the target's latest amount",
           "a refund with two revisions", "a capture with two revisions", "one batch id with two recorded_at",
           "schema 5", "schema 0"]


@pytest.mark.parametrize("how", REJECTS)
def test_rejected_schema_4_import_changes_nothing(svc, how):
    """W21.4, I25: 422 validation_failed and nothing changes."""
    rich = build_state(svc)
    snap = svc.export()
    bad = corrupt(snap.body, rich, how)
    assert bad != snap.body
    before = observe(svc, rich)
    expect_error(svc.import_raw(bad), 422, "validation_failed")
    assert observe(svc, rich) == before, f"a rejected import ({how}) changed the state"


def test_the_uncorrupted_export_imports(svc):
    """The control for the probes above: the same export, unchanged, imports with 204."""
    rich = build_state(svc)
    before = observe(svc, rich)
    expect(svc.import_(svc.export()), 204)
    assert observe(svc, rich) == before
