"""W8.1, W8.2, W8.4 — export schema 2, stage-2 round trips and rejected imports (stage-1 §10;
PLAN 3.12, D52, D62). I1, I2, I15, I25, I26, I28, I30, I34, I37.

The state format is opaque apart from `schema` (PLAN 3.12). The corruption probes find what
to corrupt by values the suite itself put into the state (a sentinel amount, a sentinel
note), never by the implementation's field names.
"""
from __future__ import annotations

import copy
import json
import time

import pytest

from support import (RFC3339, Snapshot, check_authorization, expect, expect_error, fixture, new_key,
                     seeded_auth, standard_users, ts, user)

pytestmark = pytest.mark.item(8)

SENTINEL_AMOUNT = 4_242_421
SENTINEL_NOTE = "zz-sentinel-hold-note"
SENTINEL_CAPTURE = 1_111
HANDLES = ["ada", "bob", "cy", "dee", "zed"]


def rich_fixture() -> dict:
    users = standard_users() + [user("zed", 7_777_731)]
    return fixture(users, operators=["u_ada"], ttl=900, authorizations=[
        seeded_auth("a_seed_open", "zed", "ada", 500, note="seeded open"),
        seeded_auth("a_seed_past", "zed", "ada", 300, hours=-2),
        seeded_auth("a_seed_exp", "zed", "bob", 200, status="expired"),
        seeded_auth("a_seed_cap", "bob", "zed", 100, status="captured", payment_id="p_ghost"),
    ], payments=[{"id": "p_seed", "from_user_id": "u_zed", "to_user_id": "u_ada", "amount": 9,
                  "authorization_id": "a_elsewhere"}])


def build_holds(svc) -> dict:
    """Every authorization state, with the replays a later stage must honour."""
    svc.must_reset(rich_fixture())
    ada, bob, cy, zed = (svc.client(h) for h in ("ada", "bob", "cy", "zed"))
    replays = []

    def call(handle, path, body):
        key = new_key()
        r = expect(svc.client(handle).post(path, json=body, key=key), 201)
        replays.append({"who": handle, "path": path, "body": body, "key": key, "resp": r})
        return r

    a = {}
    a["open"] = call("ada", "/authorizations", {"to_handle": "bob", "amount": 1_000, "note": "open"})
    a["partial"] = call("zed", "/authorizations", {"to_handle": "cy", "amount": SENTINEL_AMOUNT,
                                                   "note": SENTINEL_NOTE, "visibility": "private"})
    call("cy", f"/authorizations/{a['partial']['authorization_id']}/capture",
         {"amount": SENTINEL_CAPTURE, "final": False})
    a["captured"] = call("ada", "/authorizations", {"to_handle": "cy", "amount": 400})
    call("cy", f"/authorizations/{a['captured']['authorization_id']}/capture", {"amount": 250})
    a["full"] = call("bob", "/authorizations", {"to_handle": "ada", "amount": 77})
    call("ada", f"/authorizations/{a['full']['authorization_id']}/capture", {})
    a["voided"] = call("ada", "/authorizations", {"to_handle": "dee", "amount": 60})
    expect(ada.void(a["voided"]["authorization_id"]), 200)
    a["voided_partial"] = call("cy", "/authorizations", {"to_handle": "bob", "amount": 90})
    call("bob", f"/authorizations/{a['voided_partial']['authorization_id']}/capture", {"amount": 30, "final": False})
    expect(cy.void(a["voided_partial"]["authorization_id"]), 200)
    call("ada", "/payments", {"to_handle": "bob", "amount": 5})
    failed_key = new_key()
    expect_error(bob.capture(a["open"]["authorization_id"], {"amount": 5_000}, key=failed_key),
                 422, "capture_exceeds_authorization")
    return {"replays": replays, "auths": a, "failed_key": failed_key}


def observe(svc, handles=HANDLES) -> dict:
    out = {}
    for h in handles:
        c = svc.client(h)
        out[h] = {"me": c.me(), "feed": c.feed(), "requests": c.requests(), "auths": c.auths()}
    return out


def assert_restored(svc, rich, before) -> None:
    assert observe(svc) == before
    for rp in rich["replays"]:
        r = svc.client(rp["who"]).post(rp["path"], json=rp["body"], key=rp["key"])
        assert expect(r, 200) == rp["resp"], rp["path"]
    assert observe(svc) == before, "replays after import changed state"


# ---------------------------------------------------------------- W8.1 export

@pytest.mark.item(17)    # the schema number changes in W17.1
def test_export_has_format_version_1_and_schema_3(world):
    body = world.svc.export().body
    assert body["track"] == "pocketful" and body["format_version"] == 1
    assert body["state"].get("schema") == 3 and type(body["state"]["schema"]) is int, \
        "PLAN 3.11 (S3, D76): the state carries schema 3 and format_version stays 1"


def test_export_holds_no_plaintext_password(svc):
    build_holds(svc)
    snap = svc.export()
    for u in rich_fixture()["users"]:
        assert u["password"] not in snap.text


# ---------------------------------------------------------------- W8.2 round trips

def test_round_trip_in_the_same_container(svc):
    rich = build_holds(svc)
    before = observe(svc)
    snap = svc.export()
    expect(svc.client("ada").authorize("bob", 1), 201)
    svc.must_reset(fixture([user("other", 1)], ttl=5))
    expect(svc.import_(snap), 204)
    assert_restored(svc, rich, before)
    assert before["zed"]["me"]["held"] == SENTINEL_AMOUNT - SENTINEL_CAPTURE + 500


def test_round_trip_into_a_second_container(svc, svc_b):
    rich = build_holds(svc)
    before = observe(svc)
    snap = svc.export()
    svc_b.must_reset(fixture([user("other", 1)], ttl=3))
    expect(svc_b.import_(snap), 204)
    assert_restored(svc_b, rich, before)
    # The holds keep working: capture, void, and the TTL of the imported state.
    a = rich["auths"]
    expect(svc_b.client("cy").capture(a["partial"]["authorization_id"], {"amount": 1}), 201)
    expect(svc_b.client("ada").void(a["open"]["authorization_id"]), 200)
    expect_error(svc_b.client("ada").void(a["captured"]["authorization_id"]), 409, "authorization_not_open")
    expect_error(svc_b.client("ada").capture("a_seed_past"), 409, "authorization_expired")
    new = expect(svc_b.client("ada").authorize("bob", 10), 201)
    assert (ts(new["expires_at"]) - ts(new["created_at"])).total_seconds() == 900, "the TTL is part of the state"
    assert svc_b.client("zed").money() == (before["zed"]["me"]["total"] - 1, before["zed"]["me"]["total"] - 1 - 500,
                                           500)


def test_import_replays_failed_keys_and_new_ids(svc, svc_b):
    rich = build_holds(svc)
    snap = svc.export()
    expect(svc_b.import_(snap), 204)
    bob = svc_b.client("bob")
    a = rich["auths"]
    # a key that failed stays unclaimed
    p = expect(bob.capture(a["open"]["authorization_id"], {"amount": 10}, key=rich["failed_key"]), 201)
    old_ids = {x["authorization_id"] for v in observe(svc).values() for x in v["auths"]}
    new_ids = {expect(svc_b.client("ada").authorize("cy", 1), 201)["authorization_id"] for _ in range(20)}
    assert not new_ids & old_ids
    latest = max(ts(x["created_at"]) for v in observe(svc).values() for x in v["auths"])
    assert ts(p["created_at"]) >= latest


def test_open_hold_expires_by_the_clock_after_import(svc, svc_b):
    svc.must_reset(fixture(standard_users(), ttl=3))
    a = expect(svc.client("ada").authorize("bob", 1_000), 201)
    snap = svc.export()
    expect(svc_b.import_(snap), 204)
    ada_b = svc_b.client("ada")
    check_authorization(ada_b.auth(a["authorization_id"]), status="open")
    assert ada_b.money() == (10_000, 9_000, 1_000)
    time.sleep(max(0.0, ts(a["expires_at"]).timestamp() + 0.6 - time.time()))
    check_authorization(ada_b.auth(a["authorization_id"]), status="expired", remaining_amount=0)
    assert ada_b.money() == (10_000, 10_000, 0)
    expect_error(svc_b.client("bob").capture(a["authorization_id"]), 409, "authorization_expired")


def _set_every_timestamp(node, value: str) -> int:
    """Set every RFC 3339 timestamp string in the state, the last issued timestamp included, to one instant."""
    n = 0
    slots = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
    for k, v in list(slots):
        if isinstance(v, str) and RFC3339.match(v):
            node[k] = value
            n += 1
        else:
            n += _set_every_timestamp(v, value)
    return n


def test_an_imported_clock_at_exactly_a_deadline_expires_the_hold(svc):
    """W8.2, D49, I34 (critic H02, H04): the state's last issued timestamp equals an open hold's expires_at,
    both ahead of the wall clock. The import's now is then the deadline itself, and at the deadline the
    hold is expired ("`expires_at` is at or before now")."""
    deadline = "2099-06-15T10:20:30.000+00:00"
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_edge", "ada", "bob", 400, expires_at=deadline)]))
    svc.client("ada"), svc.client("bob")        # log in now, so nothing after the import issues a timestamp
    assert svc.client("ada").money() == (10_000, 9_600, 400)
    snap = svc.export()
    body = copy.deepcopy(snap.body)
    # The hold's created_at and expires_at, and the state's last issued timestamp.
    assert _set_every_timestamp(body["state"], deadline) >= 3, "too few timestamps in the export; this probe cannot run"
    expect(svc.import_(Snapshot(body, json.dumps(body), snap.total, copy.deepcopy(snap.accounts))), 204)
    ada, bob = svc.client("ada"), svc.client("bob")
    got = check_authorization(ada.auth("a_edge"), status="expired", remaining_amount=0, captured_amount=0)
    assert got["expires_at"] == deadline
    assert ada.money() == (10_000, 10_000, 0), "a hold at exactly its deadline holds nothing"
    assert [x["authorization_id"] for x in ada.auths(status="expired")] == ["a_edge"]
    assert ada.auths(status="open") == []
    expect_error(bob.capture("a_edge"), 409, "authorization_expired")
    expect_error(bob.capture("a_edge", {"amount": 1, "final": False}), 409, "authorization_expired")
    expect_error(ada.void("a_edge"), 409, "authorization_not_open")
    p = expect(ada.pay("bob", 10_000), 201)       # the 400 the hold once reserved is spendable
    assert ts(p["created_at"]) >= ts(deadline)
    check_authorization(ada.auth("a_edge"), status="expired", remaining_amount=0)


def test_a_seeded_expires_at_not_in_the_service_form_round_trips_exactly(svc, svc_b):
    """W8.2, D48 (critic E16): expires_at comes back exactly as stored, after an import here and into a second
    container, and a second export carries it unchanged."""
    odd = {"a_odd": "2099-06-15T10:20:30.123456+05:30", "a_odd_cap": "2099-01-02T03:04:05-07:00",
           "a_odd_exp": "2026-01-02T03:04:05.1+14:00", "a_odd_void": "2099-01-01t00:00:00z"}
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_odd", "ada", "bob", 100, expires_at=odd["a_odd"]),
        seeded_auth("a_odd_cap", "bob", "ada", 50, status="captured", expires_at=odd["a_odd_cap"]),
        seeded_auth("a_odd_exp", "cy", "ada", 70, expires_at=odd["a_odd_exp"]),
        seeded_auth("a_odd_void", "ada", "dee", 30, status="voided", expires_at=odd["a_odd_void"])]))
    svc.client("ada"), svc.client("bob"), svc.client("cy")
    snap = svc.export()
    svc_b.must_reset(fixture([user("other", 1)]))
    expect(svc.import_(snap), 204)
    expect(svc_b.import_(snap), 204)
    for s in (svc, svc_b):
        ada = s.client("ada")
        for aid, written in odd.items():
            assert ada.auth(aid)["expires_at"] == written, f"{aid} on {s.name}"
        assert ada.auth("a_odd")["status"] == "open" and ada.auth("a_odd_exp")["status"] == "expired"
        assert ada.money() == (10_000, 9_900, 100)
        again = s.export().body["state"]
        for aid, written in odd.items():
            assert _record_holding_all(again, (aid, written)) is not None, \
                f"the export from {s.name} after the import does not carry {aid}'s expires_at {written!r}"


def test_a_partly_captured_hold_larger_than_the_total_round_trips(svc, svc_b):
    """W8.2, 3.12 "the remainders" (critic E32): the holds check counts what a hold still holds, so a state the
    service built imports back, here and into a second container."""
    svc.must_reset(fixture(standard_users()))
    ada, bob = svc.client("ada"), svc.client("bob")
    aid = expect(ada.authorize("bob", 10_000), 201)["authorization_id"]
    expect(bob.capture(aid, {"amount": 6_000, "final": False}), 201)
    assert ada.money() == (4_000, 0, 4_000)                    # the amount 10 000 is above the total 4 000
    before = observe(svc, ["ada", "bob"])
    snap = svc.export()
    svc_b.must_reset(fixture([user("other", 1)]))
    expect(svc.import_(snap), 204)
    expect(svc_b.import_(snap), 204)
    for s in (svc, svc_b):
        assert observe(s, ["ada", "bob"]) == before, s.name
        check_authorization(s.client("ada").auth(aid), status="open", captured_amount=6_000, remaining_amount=4_000)
    expect(svc_b.client("bob").capture(aid, {"amount": 4_000}), 201)
    assert svc_b.client("ada").money() == (0, 0, 0)
    check_authorization(svc_b.client("ada").auth(aid), status="captured", captured_amount=10_000)


def test_spending_released_money_after_a_deadline_still_exports_and_imports(svc, svc_b):
    """W8.4 (plan c090e8c): an open hold past its deadline holds nothing, so its payer may spend that money."""
    svc.must_reset(fixture(standard_users(), ttl=1))
    a = expect(svc.client("cy").authorize("ada", 500), 201)
    time.sleep(max(0.0, ts(a["expires_at"]).timestamp() + 0.6 - time.time()))
    expect(svc.client("cy").pay("dee", 500), 201)
    snap = svc.export()
    expect(svc_b.import_(snap), 204)
    expect(svc.import_(snap), 204)
    check_authorization(svc_b.client("cy").auth(a["authorization_id"]), status="expired")
    assert svc_b.client("cy").money() == (0, 0, 0)


def test_fixture_built_state_with_dangling_links_round_trips(svc, svc_b):
    """D62: payment_id, payment_ids and a payment's authorization_id are checked for type only."""
    svc.must_reset(rich_fixture())
    before = observe(svc)
    snap = svc.export()
    expect(svc_b.import_(snap), 204)
    assert observe(svc_b) == before
    expect(svc.import_(snap), 204)
    assert observe(svc) == before


def test_export_during_a_burst_of_holds_is_one_snapshot(svc, svc_b):
    users = [user(f"h{i}", 1_000) for i in range(10)]
    for round_ in range(3):
        svc.must_reset(fixture(users))
        aids = [expect(svc.client(f"h{i}").authorize(f"h{(i + 1) % 10}", 400), 201)["authorization_id"]
                for i in range(10)]
        cl = {f"h{i}": [svc.fresh_client(f"h{i}") for _ in range(5)] for i in range(10)}

        def go(i):
            if i == 0:
                return svc.export()
            j = i % 10
            kind = (i // 10) % 5
            payer, receiver = f"h{j}", f"h{(j + 1) % 10}"
            if kind == 0:
                return cl[receiver][0].capture(aids[j], {"amount": 50, "final": False}, key=new_key())
            if kind == 1:
                return cl[payer][1].authorize(receiver, 60)
            if kind == 2:
                return cl[payer][2].void(aids[j])
            if kind == 3:
                return cl[payer][3].pay(receiver, 70)
            return cl[receiver][4].capture(aids[j], {"amount": 30, "final": False}, key=new_key())

        out = svc.burst(go, 50)
        snap = out[0]
        assert isinstance(snap, Snapshot), f"export during the burst failed: {snap!r}"
        assert all(r.status_code < 500 for r in out[1:])
        expect(svc_b.import_(snap), 204)
        svc_b.assert_invariants(f" in an export taken mid-burst (round {round_})")
        torn = {}
        for u in users:
            h = u["handle"]
            c = svc_b.client(h)
            own = [p for p in c.feed() if h in (p["from_handle"], p["to_handle"])]
            ledger = 1_000 + sum(p["amount"] for p in own if p["to_handle"] == h) \
                - sum(p["amount"] for p in own if p["from_handle"] == h)
            if c.balance() != ledger:
                torn[h] = (c.balance(), ledger)
            for a in c.auths(direction="incoming"):
                captured = sum(p["amount"] for p in own if p["authorization_id"] == a["authorization_id"])
                if captured != a["captured_amount"]:
                    torn[a["authorization_id"]] = (a["captured_amount"], captured)
        assert not torn, f"round {round_}: exported balances or captures disagree with exported payments {torn}"


# ---------------------------------------------------------------- W8.4 rejected imports

def _record_holding_all(node, values):
    """The innermost object that holds every one of `values` as field values (type-exact)."""
    if isinstance(node, dict):
        for v in node.values():
            found = _record_holding_all(v, values)
            if found is not None:
                return found
        if all(any(type(x) is type(want) and x == want for x in node.values()) for want in values):
            return node
    elif isinstance(node, list):
        for v in node:
            found = _record_holding_all(v, values)
            if found is not None:
                return found
    return None


def _list_holding(node, item):
    if isinstance(node, list):
        if any(x is item for x in node):
            return node
        for v in node:
            found = _list_holding(v, item)
            if found is not None:
                return found
    elif isinstance(node, dict):
        for v in node.values():
            found = _list_holding(v, item)
            if found is not None:
                return found
    return None


def _swap(record: dict, old, new) -> None:
    keys = [k for k, v in record.items() if type(v) is type(old) and v == old]
    assert keys, f"the record holds no {old!r}; this probe cannot run"
    for k in keys:
        record[k] = new


def _authorization_record(state, aid: str, status: str) -> dict:
    """The exported authorization record with this id and stored status (3.11 field names)."""
    rec = _record_holding_all(state, (aid, status))
    assert rec is not None and "amount" in rec and "captured_amount" in rec, \
        f"no authorization record holds {aid!r} with status {status!r}; this probe cannot run"
    return rec


def corrupt(snap: Snapshot, how: str, api_view: dict, rich: dict | None = None):
    body = copy.deepcopy(snap.body)
    state = body["state"]
    if how == "schema missing":
        state.pop("schema")
        return body
    if how.startswith("schema "):
        state["schema"] = json.loads(how.split(" ", 1)[1])
        return body
    closed = {"captured above amount, captured": ("captured", "captured"),
              "captured above amount, voided": ("voided_partial", "voided"),
              "captured above amount, expired": ("a_seed_exp", "expired")}
    if how in closed:
        which, status = closed[how]
        aid = which if which.startswith("a_seed") else rich["auths"][which]["authorization_id"]
        rec = _authorization_record(state, aid, status)
        rec["captured_amount"] = rec["amount"] + 1
        return body
    # The capture payment copies the note, so the authorization is the record with the note and the amount.
    rec = _record_holding_all(state, (SENTINEL_NOTE, SENTINEL_AMOUNT))
    assert rec is not None, "no record holds the sentinel note and amount; this probe cannot run"
    if how == "unknown status":
        _swap(rec, "open", "frozen")
    elif how == "captured above amount":
        _swap(rec, SENTINEL_CAPTURE, SENTINEL_AMOUNT + 1)
    elif how == "duplicate authorization id":
        holder = _list_holding(state, rec)
        assert holder is not None, "the authorization records are not in a list; this probe cannot run"
        holder.append(copy.deepcopy(rec))
    elif how == "expires_at not RFC 3339":
        _swap(rec, api_view["expires_at"], "next tuesday")
    elif how == "payment_ids not strings":
        _swap(rec, api_view["payment_ids"], [5])
    elif how == "dangling payer":
        _swap(rec, "u_zed", "u_ghost")
    elif how == "open remainder above the payer's total":
        _swap(rec, SENTINEL_AMOUNT, 999_999_999)
    else:
        raise AssertionError(how)
    return body


REJECTS = ["schema 0", "schema 4", 'schema "2"', "schema null", "schema 2.5", "schema missing",
           "unknown status", "captured above amount", "captured above amount, captured",
           "captured above amount, voided", "captured above amount, expired", "duplicate authorization id",
           "expires_at not RFC 3339",
           "payment_ids not strings", "dangling payer", "open remainder above the payer's total"]


@pytest.mark.parametrize("how", REJECTS)
def test_rejected_import_changes_nothing(svc, how):
    rich = build_holds(svc)
    snap = svc.export()
    api_view = svc.client("zed").auth(rich["auths"]["partial"]["authorization_id"])
    expect(svc.client("ada").authorize("cy", 1), 201)        # the destination now differs from the export
    before = observe(svc)
    expect_error(svc.import_raw(corrupt(snap, how, api_view, rich)), 422, "validation_failed")
    assert observe(svc) == before
    expect(svc.import_(snap), 204)                             # the uncorrupted export still imports


def test_an_exact_deadline_hold_above_the_total_still_imports(svc):
    """W8.4, 3.12 "open authorizations whose expires_at is after the import's now" (critic E26): a hold whose
    deadline is the import's now holds nothing, so its remainder above the payer's total does not refuse it."""
    deadline = "2099-06-15T10:20:30.000+00:00"
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_edge", "ada", "bob", 400, expires_at=deadline)]))
    svc.client("ada"), svc.client("bob")        # log in now, so nothing after the import issues a timestamp
    snap = svc.export()
    body = copy.deepcopy(snap.body)
    assert _set_every_timestamp(body["state"], deadline) >= 3, "too few timestamps in the export; this probe cannot run"
    rec = _authorization_record(body["state"], "a_edge", "open")
    rec["amount"] = 15_000                       # above ada's total of 10 000
    expect(svc.import_(Snapshot(body, json.dumps(body), snap.total, copy.deepcopy(snap.accounts))), 204)
    ada, bob = svc.client("ada"), svc.client("bob")
    check_authorization(ada.auth("a_edge"), status="expired", amount=15_000, remaining_amount=0)
    assert ada.money() == (10_000, 10_000, 0)
    expect_error(bob.capture("a_edge"), 409, "authorization_expired")
    assert ada.money() == (10_000, 10_000, 0)
