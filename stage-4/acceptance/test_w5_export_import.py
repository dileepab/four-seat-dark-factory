"""W5 — export and import (§10, §11 last paragraph; PLAN 3.12, D23, D30). I12, I13, I15, I25, I26, I28, I29.

The state format is opaque. The corruption probes find what to corrupt by the values
the suite itself put into the state (a sentinel balance, a sentinel email), never by
the implementation's field names.
"""
from __future__ import annotations

import copy
import json

import httpx
import pytest

from support import (RFC3339, Snapshot, assert_newest_first, expect, expect_error, fixture, new_key,
                     no_failures, standard_users, ts, user)

pytestmark = pytest.mark.item(5)

SENTINEL_BALANCE = 7_777_731
SAM_PW = "sam-Secret-Pass-77"


def rich_fixture() -> dict:
    users = standard_users() + [user("zed", SENTINEL_BALANCE, email="zed@example.com")]
    return fixture(users, operators=["u_ada"], payments=[
        {"id": "p_seed", "from_user_id": "u_zed", "to_user_id": "u_ada", "amount": 9, "note": "seed"}],
        requests=[{"id": "rq_seed", "requester_id": "u_zed", "payer_id": "u_bob", "amount": 4}])


def observe(svc, handles) -> dict:
    """Everything a caller can read: me, feed and request list for each account."""
    out = {}
    for h in handles:
        c = svc.client(h)
        out[h] = {"me": c.me(), "feed": c.feed(), "requests": c.requests()}
    return out


def build_rich_state(svc) -> dict:
    """Every kind of record, with the replays a later stage must honour."""
    svc.must_reset(rich_fixture())
    expect(svc.signup("sam@example.com", SAM_PW, "Sam"), 201)
    ada, bob, cy, dee = (svc.client(h) for h in ("ada", "bob", "cy", "dee"))
    replays = []

    def keep(client_handle, path, body, resp):
        replays.append({"who": client_handle, "path": path, "body": body, "key": resp[0], "resp": resp[1]})

    def call(handle, path, body):
        key = new_key()
        r = expect(svc.client(handle).post(path, json=body, key=key), 201)
        keep(handle, path, body, (key, r))
        return r

    call("ada", "/payments", {"to_handle": "bob", "amount": 100, "note": "pub"})
    call("bob", "/payments", {"to_handle": "cy", "amount": 50, "visibility": "private"})
    pending = call("bob", "/requests", {"payer_handle": "ada", "amount": 300, "note": "keep pending"})
    paid = call("cy", "/requests", {"payer_handle": "ada", "amount": 20})
    call("ada", f"/requests/{paid['request_id']}/pay", {"visibility": "private"})
    declined = call("ada", "/requests", {"payer_handle": "dee", "amount": 5})
    expect(dee.decline(declined["request_id"]), 200)
    cancelled = call("bob", "/requests", {"payer_handle": "cy", "amount": 7})
    expect(bob.cancel(cancelled["request_id"]), 200)
    split = call("ada", "/splits", {"amount": 300, "participant_handles": ["ada", "bob", "cy"], "note": "sp"})
    expect(bob.pay_request(split["requests"][0]["request_id"]), 201)
    call("ada", "/settlements", {"transfers": [
        {"from_handle": "ada", "to_handle": "dee", "amount": 10},
        {"from_handle": "dee", "to_handle": "sam", "amount": 5, "visibility": "private"}]})
    failed_key = new_key()
    expect_error(cy.pay("dee", 10 ** 6, key=failed_key), 409, "insufficient_funds")
    return {"replays": replays, "failed_key": failed_key, "pending": pending["request_id"],
            "handles": ["ada", "bob", "cy", "dee", "zed", "sam"]}


def assert_restored(svc, rich, before) -> None:
    """The imported service reads back exactly as the exported one did, and every retry is honoured."""
    assert observe(svc, rich["handles"]) == before
    for rp in rich["replays"]:
        r = svc.client(rp["who"]).post(rp["path"], json=rp["body"], key=rp["key"])
        assert expect(r, 200) == rp["resp"], rp["path"]
    assert observe(svc, rich["handles"]) == before, "replays after import changed state"


def all_ids(observed) -> set[str]:
    out = set()
    for v in observed.values():
        out.add(v["me"]["user_id"])
        out.update(p["payment_id"] for p in v["feed"])
        out.update(r["request_id"] for r in v["requests"])
    return out


# ---------------------------------------------------------------- export shape

def test_export_shape_and_unauthenticated(world):
    r = httpx.get(f"{world.svc.base_url}/_test/export", timeout=10)
    body = expect(r, 200)
    assert body["track"] == "pocketful" and body["format_version"] == 1 and type(body["format_version"]) is int
    assert isinstance(body["state"], dict)
    r2 = httpx.get(f"{world.svc.base_url}/_test/export", timeout=10,
                   headers={"Authorization": "Bearer nonsense"})
    assert expect(r2, 200)["track"] == "pocketful"


def test_export_holds_no_plaintext_password_or_bearer_token(svc):
    rich = build_rich_state(svc)
    snap = svc.export()
    for u in rich_fixture()["users"]:
        assert u["password"] not in snap.text, f"plaintext password of {u['handle']} in the export"
    assert SAM_PW not in snap.text
    for acct in svc.accounts.values():
        if acct.token:
            assert acct.token not in snap.text, "PLAN D30: bearer values are stored only as hashes"


def _record_holding(node, value):
    """The innermost object that holds `value` as one of its field values."""
    if isinstance(node, dict):
        for v in node.values():
            found = _record_holding(v, value)
            if found is not None:
                return found
        if value in node.values():
            return node
    elif isinstance(node, list):
        for v in node:
            found = _record_holding(v, value)
            if found is not None:
                return found
    return None


def _long_strings(node, out=None) -> set[str]:
    out = set() if out is None else out
    if isinstance(node, dict):
        for v in node.values():
            _long_strings(v, out)
    elif isinstance(node, list):
        for v in node:
            _long_strings(v, out)
    elif isinstance(node, str) and len(node) >= 16:
        out.add(node)
    return out


def test_equal_passwords_are_hashed_with_different_salts(svc):
    """I12: a per-account salt. Two accounts with one password share no long string in their records."""
    same = "the-very-same-password"
    svc.must_reset(fixture([user("ann", 1, password=same, display_name="Ann"),
                            user("ben", 2, password=same, display_name="Ben")]))
    expect(svc.signup("cat@example.com", same, "Cat"), 201)
    expect(svc.signup("dan@example.com", same, "Dan"), 201)
    state = svc.export().body["state"]
    records = {}
    for email in ("ann@example.com", "ben@example.com", "cat@example.com", "dan@example.com"):
        rec = _record_holding(state, email)
        assert rec is not None, f"no record holds {email}; this probe cannot run"
        records[email] = _long_strings(rec) - {email}
    for a, b in (("ann@example.com", "ben@example.com"), ("cat@example.com", "dan@example.com")):
        shared = records[a] & records[b]
        assert not shared, f"{a} and {b} share stored strings (a common salt or hash?): {shared}"
        assert records[a], f"the record of {a} holds no hash-like string"


def test_export_is_read_only(svc):
    rich = build_rich_state(svc)
    before = observe(svc, rich["handles"])
    for _ in range(3):
        svc.export()
    assert observe(svc, rich["handles"]) == before


# ---------------------------------------------------------------- round trips

def test_round_trip_in_the_same_container(svc):
    rich = build_rich_state(svc)
    before = observe(svc, rich["handles"])
    snap = svc.export()
    # Writes after the export must vanish on import.
    expect(svc.signup("late@example.com", "correct horse", "Late"), 201)
    late_token = svc.accounts["late"].token
    expect(svc.client("ada").pay("bob", 1), 201)
    svc.must_reset(fixture([user("other", 1)]))
    expect(svc.import_(snap), 204)
    assert_restored(svc, rich, before)
    expect_error(svc.login("late@example.com", "correct horse"), 401, "unauthenticated")
    expect_error(svc.api(late_token).get("/me"), 401, "unauthenticated")
    expect_error(svc.login("other@example.com", "pw-other-Correct-Horse-9"), 401, "unauthenticated")
    expect(svc.login("sam@example.com", SAM_PW), 200)
    expect_error(svc.login("sam@example.com", "wrong password"), 401, "unauthenticated")
    expect(svc.login("ZED@example.com", "pw-zed-Correct-Horse-9"), 200)


def test_import_drops_tokens_issued_after_the_export_for_the_same_users(svc, svc_b):
    """I25/I13 for import: tokens not in the imported state stop working, even for user ids that exist in it."""
    rich = build_rich_state(svc)
    snap = svc.export()
    after = {h: expect(svc.login(a.email, a.password), 200)["token"]
             for h, a in svc.accounts.items() if h in ("ada", "sam")}
    expect(svc.import_(snap), 204)
    for t in after.values():
        expect_error(svc.api(t).get("/me"), 401, "unauthenticated")
    assert svc.client("ada").me()["user_id"] == "u_ada"     # the exported token still works
    # The same in a second container that already holds its own token for the same user ids.
    svc_b.must_reset(rich_fixture())
    b_token = svc_b.client("ada").token
    expect(svc_b.import_(snap), 204)
    expect_error(svc_b.api(b_token).get("/me"), 401, "unauthenticated")


def test_round_trip_into_a_second_container(svc, svc_b):
    rich = build_rich_state(svc)
    before = observe(svc, rich["handles"])
    snap = svc.export()
    expect(svc_b.import_(snap), 204)
    assert_restored(svc_b, rich, before)
    expect(svc_b.login("sam@example.com", SAM_PW), 200)
    # The two containers are independent afterwards.
    expect(svc_b.client("ada").pay("bob", 1), 201)
    assert svc.client("ada").balance() == before["ada"]["me"]["balance"]


def test_importing_twice_equals_importing_once(svc):
    rich = build_rich_state(svc)
    before = observe(svc, rich["handles"])
    snap = svc.export()
    expect(svc.import_(snap), 204)
    expect(svc.import_(snap), 204)
    assert_restored(svc, rich, before)


def test_import_preserves_failed_keys_pending_requests_and_operators(svc, svc_b):
    rich = build_rich_state(svc)
    snap = svc.export()
    expect(svc_b.import_(snap), 204)
    cy = svc_b.client("cy")
    expect(cy.pay("dee", 1, key=rich["failed_key"]), 201)   # failed keys stay reusable
    expect(svc_b.client("ada").pay_request(rich["pending"]), 201)   # pending stays payable
    expect(svc_b.client("ada").settle([{"from_handle": "bob", "to_handle": "dee", "amount": 1}]), 201)
    expect_error(svc_b.client("bob").settle([{"from_handle": "bob", "to_handle": "dee", "amount": 1}]),
                 403, "forbidden")


def test_new_ids_never_collide_and_time_moves_forward_after_import(svc, svc_b):
    rich = build_rich_state(svc)
    before = observe(svc, rich["handles"])
    old = {"user": set(), "payment": set(), "request": set(), "split": set(), "settlement": set()}
    for v in before.values():
        old["user"].add(v["me"]["user_id"])
        old["payment"].update(p["payment_id"] for p in v["feed"])
        old["settlement"].update(p["settlement_id"] for p in v["feed"] if p["settlement_id"])
        old["request"].update(r["request_id"] for r in v["requests"])
    for rp in rich["replays"]:
        if "split_id" in rp["resp"]:
            old["split"].add(rp["resp"]["split_id"])
    stamps = [p["created_at"] for v in before.values() for p in v["feed"]] + \
             [r["created_at"] for v in before.values() for r in v["requests"]]
    latest = max(ts(x) for x in stamps)
    snap = svc.export()
    for target in (svc_b, svc):
        if target is svc:
            target.must_reset(fixture([user("other", 1)]))
        expect(target.import_(snap), 204)
        ada = target.client("ada")
        new = {k: set() for k in old}
        times = []
        for _ in range(5):
            p = expect(ada.pay("bob", 1), 201)
            new["payment"].add(p["payment_id"]); times.append(p["created_at"])
            r = expect(ada.ask("cy", 1), 201)
            new["request"].add(r["request_id"]); times.append(r["created_at"])
            sp = expect(ada.split(2, ["ada", "dee"]), 201)
            new["split"].add(sp["split_id"]); times.append(sp["created_at"])
            new["request"].update(x["request_id"] for x in sp["requests"])
            st = expect(ada.settle([{"from_handle": "ada", "to_handle": "dee", "amount": 1}]), 201)
            new["settlement"].add(st["settlement_id"]); times.append(st["committed_at"])
            new["payment"].update(x["payment_id"] for x in st["payments"])
        body = expect(target.signup(f"newcomer{len(times)}@example.com", "correct horse", "N"), 201)
        new["user"].add(body["user_id"])
        for kind in old:
            assert not (new[kind] & old[kind]), f"new {kind} ids collide with imported ones: {new[kind] & old[kind]}"
        for stamp in times:
            assert ts(stamp) >= latest, f"new timestamp {stamp} is earlier than imported {latest}"


def test_export_during_a_burst_is_a_consistent_snapshot(svc, svc_b):
    """§10 and I26: an export is one point in time. Each imported balance must equal the
    seeded 1000 plus what that user received minus what it sent, over the imported payments."""
    users = [user(f"b{i}", 1_000) for i in range(10)]
    for round_ in range(3):
        svc.must_reset(fixture(users))
        clients = [svc.fresh_client(f"b{i % 10}") for i in range(49)]

        def go(i):
            if i == 0:
                return svc.export()
            return clients[i - 1].pay(f"b{(i + 3) % 10}", 37)

        out = svc.burst(go, 50)
        snap = out[0]
        assert isinstance(snap, Snapshot), f"export during the burst failed: {snap!r}"
        no_failures(out[1:])
        assert {r.status_code for r in out[1:]} <= {201, 409}
        expect(svc_b.import_(snap), 204)
        svc_b.assert_invariants(" in an export taken mid-burst")
        torn = {}
        for u in users:
            h = u["handle"]
            c = svc_b.client(h)
            own = [p for p in c.feed() if h in (p["from_handle"], p["to_handle"])]
            ledger = 1_000 + sum(p["amount"] for p in own if p["to_handle"] == h) \
                - sum(p["amount"] for p in own if p["from_handle"] == h)
            if c.balance() != ledger:
                torn[h] = (c.balance(), ledger)
        assert not torn, f"round {round_}: exported balances disagree with exported payments {torn}"


def test_snapshot_is_not_affected_by_later_writes(svc):
    rich = build_rich_state(svc)
    before = observe(svc, rich["handles"])
    snap = svc.export()
    frozen = copy.deepcopy(snap.body)
    for _ in range(5):
        expect(svc.client("ada").pay("bob", 1), 201)
    again = svc.export()
    assert snap.body == frozen
    expect(svc.import_(snap), 204)
    assert observe(svc, rich["handles"]) == before
    expect(svc.import_(again), 204)
    assert svc.client("ada").balance() == before["ada"]["me"]["balance"] - 5


def _shift_years(node, year: str) -> int:
    """Move every RFC 3339 timestamp string in the state to the given year."""
    n = 0
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and RFC3339.match(v):
                node[k] = year + v[4:]
                n += 1
            else:
                n += _shift_years(v, year)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, str) and RFC3339.match(v):
                node[i] = year + v[4:]
                n += 1
            else:
                n += _shift_years(v, year)
    return n


def test_time_never_runs_backwards_after_importing_a_later_clock(svc, svc_b):
    """W5.4, I29: an export from a source whose clock runs ahead. New records come after the imported ones."""
    rich = build_rich_state(svc)
    snap = svc.export()
    body = copy.deepcopy(snap.body)
    assert _shift_years(body["state"], "2099"), "no timestamp-shaped string in the export; this probe cannot run"
    moved = Snapshot(body, json.dumps(body), snap.total, copy.deepcopy(snap.accounts))
    expect(svc_b.import_(moved), 204)
    ada = svc_b.client("ada")
    imported = [ts(p["created_at"]) for p in ada.feed()] + [ts(r["created_at"]) for r in ada.requests()]
    latest = max(imported)
    assert latest.year == 2099
    p = expect(ada.pay("bob", 1), 201)
    r = expect(ada.ask("cy", 1), 201)
    sp = expect(ada.split(2, ["ada", "dee"]), 201)
    st = expect(ada.settle([{"from_handle": "ada", "to_handle": "dee", "amount": 1}]), 201)
    for stamp in (p["created_at"], r["created_at"], sp["created_at"], st["committed_at"]):
        assert ts(stamp) >= latest, f"new timestamp {stamp} is earlier than imported {latest}"
    feed = ada.feed()
    assert feed[0]["payment_id"] == st["payments"][0]["payment_id"] or feed[0]["settlement_id"] == st["settlement_id"]
    assert_newest_first(feed)
    assert_newest_first(ada.requests())


def test_reset_after_import_clears_it(svc):
    rich = build_rich_state(svc)
    snap = svc.export()
    expect(svc.import_(snap), 204)
    sam_token = svc.accounts["sam"].token
    svc.must_reset(fixture([user("ann", 3)]))
    expect_error(svc.api(sam_token).get("/me"), 401, "unauthenticated")
    expect_error(svc.login("sam@example.com", SAM_PW), 401, "unauthenticated")
    assert svc.client("ann").balance() == 3
    ann_feed = svc.client("ann").feed()
    assert ann_feed == [], "no imported payment survives a reset"


def test_import_ignores_an_invalid_authorization_header(svc):
    build_rich_state(svc)
    snap = svc.export()
    r = httpx.post(f"{svc.base_url}/_test/import", json=snap.body, timeout=10,
                   headers={"Authorization": "Bearer junk"})
    assert r.status_code == 204


# ---------------------------------------------------------------- rejected imports (I25)

def _replace_value(node, old, new) -> int:
    n = 0
    if isinstance(node, dict):
        for k, v in node.items():
            if type(v) is type(old) and v == old:
                node[k] = new
                n += 1
            else:
                n += _replace_value(v, old, new)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if type(v) is type(old) and v == old:
                node[i] = new
                n += 1
            else:
                n += _replace_value(v, old, new)
    return n


def _remove_record_with_value(node, value) -> bool:
    """Remove the innermost object that holds `value` as a field value from its container."""
    if isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, dict) and value in v.values():
                del node[i]
                return True
            if _remove_record_with_value(v, value):
                return True
    elif isinstance(node, dict):
        for k, v in list(node.items()):
            if isinstance(v, dict) and value in v.values():
                del node[k]
                return True
            if _remove_record_with_value(v, value):
                return True
    return False


def corrupt(snap: Snapshot, how: str):
    body = copy.deepcopy(snap.body)
    if how == "negative balance":
        n = _replace_value(body["state"], SENTINEL_BALANCE, -1)
        n += _replace_value(body["state"], str(SENTINEL_BALANCE), "-1")
        assert n, "the sentinel balance does not appear in the export; this probe cannot run"
        return body
    if how == "dangling user":
        assert _remove_record_with_value(body["state"], "zed@example.com"), \
            "no record holds zed's email; this probe cannot run"
        return body
    if how == "schema 4":
        assert type(body["state"].get("schema")) is int, "PLAN 3.12: the state carries its schema number"
        body["state"]["schema"] = 4    # stage 3 imports schemas 1, 2 and 3 only (PLAN 3.11, S3)
        return body
    raise AssertionError(how)


REJECTS = {
    "invalid json": (b"{nope", 400, "malformed_request"),
    "array": (b"[]", 400, "malformed_request"),
    "string": (b'"x"', 400, "malformed_request"),
    "empty": (b"", 400, "malformed_request"),
    "empty object": ({}, 422, None),
    "missing track": ("-track", 422, None),
    "wrong track": ({"track": "tablekeeper"}, 422, None),
    "track in upper case": ({"track": "POCKETFUL"}, 422, None),
    "track with a space": ({"track": "pocketful "}, 422, None),
    "missing version": ("-format_version", 422, None),
    "version 2": ({"format_version": 2}, 422, None),
    "version string": ({"format_version": "1"}, 422, None),
    "missing state": ("-state", 422, None),
    "state string": ({"state": "x"}, 422, None),
    "state array": ({"state": []}, 422, None),
    "state empty": ({"state": {}}, 422, None),
    "state only schema": ({"state": {"schema": 1}}, 422, None),
    "negative balance": ("corrupt", 422, None),
    "dangling user": ("corrupt", 422, None),
    "schema 4": ("corrupt", 422, None),
}


@pytest.mark.parametrize("name", list(REJECTS))
def test_rejected_import_changes_nothing(svc, name):
    rich = build_rich_state(svc)
    snap = svc.export()
    expect(svc.client("ada").pay("cy", 1), 201)     # the destination now differs from the export
    before = observe(svc, rich["handles"])
    spec, status, _ = REJECTS[name]
    if isinstance(spec, bytes):
        r = svc.import_raw(content=spec)
    elif spec == "corrupt":
        r = svc.import_raw(corrupt(snap, name))
    elif isinstance(spec, str) and spec.startswith("-"):
        body = copy.deepcopy(snap.body)
        body.pop(spec[1:])
        r = svc.import_raw(body)
    else:
        body = copy.deepcopy(snap.body) if spec else {}
        body.update(spec)
        r = svc.import_raw(body)
    expect_error(r, status, "malformed_request" if status == 400 else "validation_failed")
    assert observe(svc, rich["handles"]) == before


@pytest.mark.parametrize("inside,status", [(79, 204), (80, 400)], ids=["80-levels", "81-levels"])
def test_import_nesting_limit_is_80_levels(svc, inside, status):
    """PLAN 3.2 (D38): import takes up to 80 levels (the top-level object is level 1); 81 is 400."""
    rich = build_rich_state(svc)
    snap = svc.export()
    expect(svc.client("ada").pay("cy", 1), 201)
    before = observe(svc, rich["handles"])
    text = json.dumps(snap.body)[:-1] + ', "pad": ' + "[" * inside + "]" * inside + "}"
    r = svc.import_raw(content=text.encode())
    if status == 204:
        expect(r, 204)
        svc.accounts, svc.total = copy.deepcopy(snap.accounts), snap.total
        assert svc.client("ada").balance() == before["ada"]["me"]["balance"] + 1
    else:
        expect_error(r, 400, "malformed_request")
        assert observe(svc, rich["handles"]) == before


def test_import_over_64_mib_is_422_and_changes_nothing(world):
    body = b'{"track": "pocketful", "format_version": 1, "state": {}, "pad": "' + b"a" * (65 * 1024 * 1024) + b'"}'
    r = world.svc.import_raw(content=body)
    expect_error(r, 422, "validation_failed")
    assert world.ada.balance() == 10_000


def test_export_of_a_large_state_round_trips_within_the_time_limit(svc, svc_b):
    users = [user(f"m{i:03d}", 1_000) for i in range(300)]
    svc.reset(fixture(users), track=False)
    a = svc.client("m000")
    for i in range(1, 60):
        expect(a.pay(f"m{i:03d}", 1), 201)
    snap = svc.export()
    expect(svc_b.import_(snap), 204)
    assert svc_b.client("m000").balance() == 1_000 - 59
