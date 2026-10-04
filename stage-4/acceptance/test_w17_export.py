"""W17.1, W17.2, W17.4 — export schema 3, round trips and rejected schema-3 imports (stage-1 §10;
stage-3 "Settlement history", "Stable statement pagination"; PLAN 3.11, D73, D76). I25, I26, I55, I65.

The state format is opaque apart from `schema` (PLAN 3.11 names what it holds, not how). The
corruption probes find what to corrupt by values the suite itself put into the state: sentinel
correction reasons, a sentinel opening balance, a snapshot token, a user id.
"""
from __future__ import annotations

import copy
import json

import httpx
import pytest

from support import (EPOCH, FAR_FUTURE, RESET_TIMEOUT, REVISION_KEYS, Snapshot, expect, expect_error, fixture,
                     instant, new_key, page_snapshot, read_statement, shifted, standard_users, user)
from test_w5_export_import import _replace_value
from test_w8_export_import import _list_holding, _record_holding_all, _swap
from test_w14_history import seeded

pytestmark = pytest.mark.item(17)

REASON = "zz-sentinel-correction"
OPENING_ZED = 731_337          # zed's opening balance; appears nowhere else in the state
HANDLES = ["ada", "bob", "cy", "dee", "zed"]


BASE_CAPTURED = 377            # a_sent's seeded captured_amount; appears nowhere else in the state


def history_fixture(far: str) -> dict:
    users = standard_users() + [user("zed", OPENING_ZED + 63)]
    return fixture(users, operators=["u_ada"], payments=[
        seeded("p_z", "ada", "zed", 63, "2026-02-01T00:00:00.000001+01:00"),
        seeded("p_old", "bob", "cy", 25, "2026-02-02T00:00:00Z", note="old")],
        authorizations=[{"id": "a_sent", "from_user_id": "u_zed", "to_user_id": "u_ada", "amount": 5_000,
                         "expires_at": far, "captured_amount": BASE_CAPTURED}])


def build_history(svc) -> dict:
    """Revisions, opening balances, snapshots, correction keys and holds: everything schema 3 adds."""
    svc.must_reset(fixture(standard_users()))
    far = shifted(svc.client("ada").service_now("bob"), seconds=7200, digits=3)
    svc.must_reset(history_fixture(far))
    ada, bob, cy = svc.client("ada"), svc.client("bob"), svc.client("cy")
    expect(ada.capture("a_sent", {"amount": 100, "final": False}), 201)    # captured 477 = base 377 + 100
    replays = []

    def correct(c, who, pid, rev, amount, at, reason):
        key = new_key()
        body = {"expected_revision": rev, "amount": amount, "effective_at": at, "reason": reason}
        r = expect(c.correct(pid, body=body, key=key), 201)
        replays.append({"who": who, "path": f"/payments/{pid}/corrections", "body": body, "key": key, "resp": r})
        return r

    p1 = expect(ada.pay("bob", 100, note="n1"), 201)
    r2 = correct(ada, "ada", p1["payment_id"], 1, 60, "2026-01-15T00:00:00Z", REASON + "-2")
    r3 = correct(ada, "ada", p1["payment_id"], 2, 80, "2026-01-15T00:00:00Z", REASON + "-3")
    p2 = expect(bob.pay("cy", 40, note="n2", visibility="private"), 201)
    correct(bob, "bob", p2["payment_id"], 1, 0, p2["created_at"], "reverse")
    correct(bob, "bob", "p_old", 1, 20, "2026-02-01T12:00:00Z", "seeded fix")
    failed = new_key()
    expect_error(ada.correct(p1["payment_id"], 1, 70, p1["created_at"], key=failed), 409, "stale_revision")
    a = expect(ada.authorize("cy", 300), 201)
    cap = expect(cy.capture(a["authorization_id"], {"amount": 100, "final": False}), 201)
    v = expect(ada.authorize("dee", 50), 201)
    expect(ada.void(v["authorization_id"]), 200)
    snaps = {
        "ada": read_statement(ada, svc.accounts["ada"].user_id, limit=2,
                              **{"from": "2026-01-01T00:00:00Z", "known_at": r2["recorded_at"]}),
        "bob": read_statement(bob, svc.accounts["bob"].user_id),
    }
    # Written after the snapshots, so the snapshots must not see them.
    expect(ada.pay("bob", 7), 201)
    r4 = correct(ada, "ada", p1["payment_id"], 3, 90, "2026-01-16T00:00:00Z", REASON + "-4")
    return {"p1": p1, "p2": p2, "r2": r2, "r3": r3, "r4": r4, "cap": cap, "replays": replays, "failed_key": failed,
            "snaps": snaps, "marks": ["2026-01-15T00:00:00Z", "2026-02-01T00:00:00Z", "2026-02-01T12:00:00Z",
                                      p1["created_at"], cap["created_at"], r2["recorded_at"], r3["recorded_at"]]}


def observe(svc, rich, handles=HANDLES) -> dict:
    """Everything stage 3 lets a caller read: stage 2's reads, revisions, history views, statements and
    the stored snapshots' pages."""
    out = {}
    for h in handles:
        c = svc.client(h)
        uid = svc.accounts[h].user_id
        feed = c.feed()
        st = read_statement(c, uid)
        out[h] = {"me": c.me(), "feed": feed, "requests": c.requests(), "auths": c.auths(),
                  "revisions": {p["payment_id"]: c.revisions(p["payment_id"]) for p in feed
                                if h in (p["from_handle"], p["to_handle"])},
                  "views": [c.me_at(t, k) for t in [EPOCH] + rich["marks"] + [FAR_FUTURE]
                            for k in (None, rich["r2"]["recorded_at"])],
                  "statement": (st.opening, st.closing, st.entries)}
    for h, st in rich["snaps"].items():
        out[f"snapshot_{h}"] = page_snapshot(svc.client(h), svc.accounts[h].user_id, st.snapshot,
                                             known_at=st.first.get("known_at"))
    return out


def assert_restored(svc, rich, before) -> None:
    assert observe(svc, rich) == before
    for rp in rich["replays"]:
        r = svc.client(rp["who"]).post(rp["path"], json=rp["body"], key=rp["key"])
        assert expect(r, 200) == rp["resp"], f"a correction replay after import: {rp['path']}"
    assert observe(svc, rich) == before, "replays after import changed state"


# ---------------------------------------------------------------- W17.1 export

def test_export_holds_schema_3_and_the_snapshots_are_frozen_in_it(svc):
    rich = build_history(svc)
    assert rich["snaps"]["ada"].entries[0]["revision"] == 2, "known_at at revision 2's recorded_at selects it"
    body = svc.export().body
    assert body["format_version"] == 1 and body["state"]["schema"] == 3
    text = json.dumps(body)
    for s in (REASON + "-2", REASON + "-3", REASON + "-4", rich["snaps"]["ada"].snapshot, rich["snaps"]["bob"].snapshot):
        assert s in text, f"PLAN 3.11: the export holds {s!r}"


def test_export_is_read_only(svc):
    rich = build_history(svc)
    before = observe(svc, rich)
    for _ in range(3):
        svc.export()
    assert observe(svc, rich) == before


def test_a_snapshot_read_stores_nothing(svc):
    """PLAN 3.9 (revised): a snapshot read returns the requested page and stores nothing."""
    rich = build_history(svc)
    before = svc.export().text
    for h, st in rich["snaps"].items():
        page_snapshot(svc.client(h), svc.accounts[h].user_id, st.snapshot, known_at=st.first.get("known_at"),
                      page_limit=1)
    assert svc.export().text == before


# ---------------------------------------------------------------- W17.2 round trips

def test_round_trip_in_the_same_container(svc):
    rich = build_history(svc)
    before = observe(svc, rich)
    snap = svc.export()
    p = expect(svc.client("ada").pay("cy", 11), 201)
    expect(svc.client("ada").correct(p["payment_id"], 1, 5, p["created_at"]), 201)
    expect(svc.client("ada").correct(rich["p1"]["payment_id"], 4, 1, p["created_at"]), 201)
    extra = read_statement(svc.client("cy"), svc.accounts["cy"].user_id).snapshot
    expect(svc.import_(snap), 204)
    assert_restored(svc, rich, before)
    # I25: an import invalidates every token not in the new state.
    expect_error(svc.client("cy").statement(snapshot=extra), 404, "not_found")


def test_round_trip_into_a_second_container(svc, svc_b):
    rich = build_history(svc)
    before = observe(svc, rich)
    snap = svc.export()
    svc_b.must_reset(fixture(standard_users()))
    expect(svc_b.import_(snap), 204)
    assert_restored(svc_b, rich, before)
    # A key that failed before the export is free after it.
    expect(svc_b.client("ada").correct(rich["p1"]["payment_id"], 4, 70, rich["p1"]["created_at"],
                                       key=rich["failed_key"]), 201)


def test_a_round_trip_keeps_opening_balances_after_corrections(svc, svc_b):
    rich = build_history(svc)
    expect(svc_b.import_(svc.export()), 204)
    for h, opening in (("zed", OPENING_ZED), ("ada", 10_063), ("bob", 2_525), ("cy", 475), ("dee", 0)):
        assert svc_b.client(h).me_at(EPOCH)["total"] == opening, h
    assert rich["p1"]


def test_new_snapshots_and_corrections_after_import(svc, svc_b):
    rich = build_history(svc)
    expect(svc_b.import_(svc.export()), 204)
    ada = svc_b.client("ada")
    r = expect(ada.correct(rich["p1"]["payment_id"], 4, 50, rich["p1"]["created_at"]), 201)
    assert r["revision"] == 5
    assert instant(r["recorded_at"]) > max(instant(x["recorded_at"]) for x in ada.revisions(rich["p1"]["payment_id"])[:-1])
    st = read_statement(ada, svc_b.accounts["ada"].user_id)
    assert st.snapshot not in (rich["snaps"]["ada"].snapshot, rich["snaps"]["bob"].snapshot)


def test_export_during_a_burst_of_corrections_is_one_snapshot(svc, svc_b):
    """W17.1: built in one synchronous step, so it always validates and imports (opening + latest = balance)."""
    svc.must_reset(fixture(standard_users()))
    ada = svc.client("ada")
    pays = [expect(ada.pay("bob", 100), 201) for _ in range(20)]
    exports: list = []

    def work(i):
        if i % 5 == 0:
            resp = httpx.get(f"{svc.base_url}/_test/export", timeout=RESET_TIMEOUT)
            exports.append(resp)
            return resp
        p = pays[i % 20]
        return svc.fresh_client("ada").correct(p["payment_id"], 1, 50 + i, p["created_at"])

    out = svc.burst(work, 40)
    assert all(not isinstance(r, Exception) and r.status_code < 500 for r in out), out[:3]
    for resp in exports:
        body = expect(resp, 200)
        snap = Snapshot(body, resp.text, svc.total, copy.deepcopy(svc.accounts))
        expect(svc_b.import_(snap), 204)
        balances = [svc_b.client(h).balance() for h in ("ada", "bob", "cy", "dee")]
        assert sum(balances) == svc.total


# ---------------------------------------------------------------- W17.4 rejected schema-3 imports

def _records_holding(node, value, out=None) -> list[dict]:
    """Every innermost object that holds `value` (type-exact) as a field value."""
    out = [] if out is None else out
    if isinstance(node, dict):
        before = len(out)
        for v in node.values():
            _records_holding(v, value, out)
        if len(out) == before and any(type(x) is type(value) and x == value for x in node.values()):
            out.append(node)
    elif isinstance(node, list):
        for v in node:
            _records_holding(v, value, out)
    return out


def _revision_records(state, rev: dict) -> list[dict]:
    """The stored revision records of the revision `rev` (a correction's 201 body): the objects holding its
    reason and its recorded_at, apart from a stored 201 body, which has exactly the Revision fields (a
    revision record also carries its sequence number, PLAN 3.11). A stored request body has no recorded_at."""
    recs = [r for r in _records_holding(state, rev["reason"])
            if set(r) != REVISION_KEYS and rev["recorded_at"] in r.values()]
    assert recs, f"no revision record holds {rev['reason']!r} and {rev['recorded_at']!r}; this probe cannot run"
    return recs


class _Many:
    """Apply one swap to every candidate record."""
    def __init__(self, recs):
        self.recs = recs


def _revision_record(state, rev: dict) -> _Many:
    return _Many(_revision_records(state, rev))


def _snapshot_record(state, token: str) -> dict:
    """The stored snapshot holding `token`, as a field value or as its key."""
    rec = _record_holding_all(state, (token,))
    if rec is not None:
        return rec
    stack = [state]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if isinstance(node.get(token), dict):
                return node[token]
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    raise AssertionError("no snapshot record holds the token; this probe cannot run")


def _swap_all(target, old, new) -> None:
    for rec in (target.recs if isinstance(target, _Many) else [target]):
        _swap(rec, old, new)


def corrupt(body: dict, rich: dict, how: str) -> dict:
    body = copy.deepcopy(body)
    state = body["state"]
    if how == "revision gap":
        _swap_all(_revision_record(state, rich["r3"]), 3, 5)
    elif how == "revision 1 differs from its payment":
        recs = [r for r in _records_holding(state, rich["p1"]["created_at"])
                if 100 in r.values() and "" in r.values() and "n1" not in r.values() and set(r) != REVISION_KEYS]
        assert recs, "no revision-1 record for p1; this probe cannot run"
        _swap_all(_Many(recs), 100, 101)
    elif how == "recorded_at decreases":
        r2, r3 = _revision_record(state, rich["r2"]), _revision_record(state, rich["r3"])
        a, b = rich["r2"]["recorded_at"], rich["r3"]["recorded_at"]
        _swap_all(r2, a, "\x00")
        _swap_all(r3, b, a)
        _swap_all(r2, "\x00", b)
    elif how == "opening balance does not add up":
        assert _replace_value(state, OPENING_ZED, OPENING_ZED + 1) == 1, \
            "zed's opening balance is not exactly one value in the export; this probe cannot run"
    elif how == "snapshot owner unknown":
        _swap(_snapshot_record(state, rich["snaps"]["ada"].snapshot), "u_ada", "u_ghost")
    elif how == "duplicate snapshot token":
        rec = _record_holding_all(state, (rich["snaps"]["ada"].snapshot,))
        lst = _list_holding(state, rec)
        if lst is None:
            pytest.skip("the snapshots are keyed by token, so a duplicate token cannot be written")
        lst.append(copy.deepcopy(rec))
    elif how == "correction reason empty":
        _swap_all(_revision_record(state, rich["r2"]), REASON + "-2", "")
    elif how == "correction amount above the maximum":
        _swap_all(_revision_record(state, rich["r4"]), 90, 1_000_000_001)
    elif how == "correction effective_at not an instant":
        _swap_all(_revision_record(state, rich["r2"]), "2026-01-15T00:00:00Z", "2026-01-15")
    elif how == "snapshot cutoff beyond the sequence":
        rec = _snapshot_record(state, rich["snaps"]["bob"].snapshot)
        ints = [k for k, v in rec.items() if type(v) is int]
        assert len(ints) == 1, f"the snapshot record has {len(ints)} integer fields, not one cutoff; this probe cannot run"
        rec[ints[0]] = 10 ** 12
    elif how == "base captured amount not adding up":
        rec = _record_holding_all(state, ("a_sent", 477))
        assert rec is not None, "no authorization record holds a_sent with captured_amount 477; this probe cannot run"
        _swap(rec, BASE_CAPTURED, BASE_CAPTURED + 1)
    elif how.startswith("schema "):
        state["schema"] = json.loads(how.split(" ", 1)[1])
    else:
        raise AssertionError(how)
    return body


REJECTS = ["revision gap", "revision 1 differs from its payment", "recorded_at decreases",
           "opening balance does not add up", "snapshot owner unknown", "duplicate snapshot token",
           "correction reason empty", "correction amount above the maximum",
           "correction effective_at not an instant", "snapshot cutoff beyond the sequence",
           "base captured amount not adding up", "schema 4", "schema 0"]


@pytest.mark.parametrize("how", REJECTS)
def test_rejected_schema_3_import_changes_nothing(svc, how):
    rich = build_history(svc)
    snap = svc.export()
    bad = corrupt(snap.body, rich, how)
    assert bad != snap.body
    before = observe(svc, rich)
    resp = svc.import_raw(bad)
    expect_error(resp, 422, "validation_failed")
    assert observe(svc, rich) == before, f"a rejected import ({how}) changed the state"


def test_the_uncorrupted_export_imports(svc):
    """The control for the probes above: the same export, unchanged, imports with 204."""
    rich = build_history(svc)
    before = observe(svc, rich)
    expect(svc.import_(svc.export()), 204)
    assert observe(svc, rich) == before


# ---------------------------------------------------------------- W17.2 instant forms (D85, D86)

FORMS = ["2026-01-02T03:04:05Z", "2026-01-02T03:04:06z", "2026-01-02t03:04:07Z", "2026-01-02T08:34:08+05:30",
         "2026-01-02T03:04:09-00:00", "2026-01-02T03:04:10.123456Z", "2026-01-02T03:04:11+00:00"]
HOLD_FORMS = [f.replace("2026-01-02", "2026-01-03") for f in FORMS]
CLOSED_AT = "2026-01-02t04:04:12.5+01:00"


def forms_fixture(svc) -> dict:
    svc.must_reset(fixture(standard_users()))
    far = shifted(svc.client("ada").service_now("bob"), seconds=7200, digits=3)
    return fixture(standard_users(),
                   payments=[seeded(f"f_{i}", "ada", "bob", i + 1, at) for i, at in enumerate(FORMS)],
                   authorizations=[{"id": f"h_{i}", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 1,
                                    "expires_at": far, "created_at": at} for i, at in enumerate(HOLD_FORMS)] +
                   [{"id": "h_closed", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 5, "expires_at": far,
                     "status": "voided", "created_at": CLOSED_AT}])


def observe_forms(svc) -> dict:
    out = {}
    for h in ("ada", "bob", "cy"):
        c = svc.client(h)
        st = read_statement(c, svc.accounts[h].user_id)
        out[h] = {"me": c.me(), "feed": c.feed(), "auths": c.auths(), "statement": (st.opening, st.closing, st.entries),
                  "views": [c.me_at(t) for t in FORMS + HOLD_FORMS + [CLOSED_AT]] +
                           [c.me_at(None, t) for t in FORMS + HOLD_FORMS]}
    return out


def test_a_state_seeded_in_every_instant_form_round_trips(svc, svc_b):
    """W17.2 (revised), D85, D86: 204, the same reads, and new writes later than everything imported."""
    svc.must_reset(forms_fixture(svc))
    closed = svc.client("bob").auth("h_closed")
    assert closed["created_at"] == closed["closed_at"] == CLOSED_AT
    before = observe_forms(svc)
    snap = svc.export()
    svc_b.must_reset(fixture(standard_users()))
    expect(svc_b.import_(snap), 204)
    assert observe_forms(svc_b) == before
    p = expect(svc_b.client("ada").pay("bob", 1), 201)
    a = expect(svc_b.client("bob").authorize("cy", 1), 201)
    latest = max(instant(t) for t in FORMS + HOLD_FORMS + [CLOSED_AT])
    assert instant(p["created_at"]) > latest and instant(a["created_at"]) > latest


def test_the_clock_base_of_an_import_is_an_exact_instant(svc, svc_b):
    """D86: a seeded instant written so that its string sorts low but its instant is the latest in the state
    (an hour ahead, at -11:00) still sets the clock base: the next write is later than it."""
    svc.must_reset(forms_fixture(svc))
    snap = svc.export()
    ahead = shifted(svc.client("ada").service_now("cy"), seconds=3600, digits=6, offset="-11:00")
    body = copy.deepcopy(snap.body)
    n = _replace_value(body["state"], FORMS[3], ahead)
    assert n >= 2, f"f_3's created_at and its revision 1 appear {n} times in the export; this probe cannot run"
    svc_b.must_reset(fixture(standard_users()))
    expect(svc_b.import_(Snapshot(body, json.dumps(body), snap.total, copy.deepcopy(snap.accounts))), 204)
    assert [p["created_at"] for p in svc_b.client("ada").feed() if p["payment_id"] == "f_3"] == [ahead]
    p = expect(svc_b.client("ada").pay("bob", 1), 201)
    assert instant(p["created_at"]) > instant(ahead), \
        f"D86: the clock base is the latest instant compared exactly: {p['created_at']} is not after {ahead}"


# ---------------------------------------------------------------- W18.7 (b): D84 across a round trip

PART_MARKS = ["2026-02-28T23:59:59.999999Z", "2026-03-01T00:00:00Z", "2026-03-01T23:59:59.999999Z",
              "2026-03-02T00:00:00Z"]


def partly_captured_state(svc) -> list[str]:
    """A seeded partly captured hold, display-only links naming existing records, and two API captures."""
    svc.must_reset(fixture(standard_users()))
    far = shifted(svc.client("ada").service_now("bob"), seconds=7200, digits=3)
    svc.must_reset(fixture(standard_users(), payments=[
        seeded("p_link", "ada", "bob", 50, "2026-03-02T00:00:00Z", authorization_id="a_part")],
        authorizations=[{"id": "a_part", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1_000,
                         "expires_at": far, "created_at": "2026-03-01T00:00:00Z", "captured_amount": 400,
                         "payment_id": "p_link", "payment_ids": ["p_link"]}]))
    bob = svc.client("bob")
    c1 = expect(bob.capture("a_part", {"amount": 100, "final": False}), 201)["created_at"]
    c2 = expect(bob.capture("a_part", {"amount": 50, "final": False}), 201)["created_at"]
    return PART_MARKS + [shifted(c1, -1), c1, shifted(c2, -1), c2, shifted(far, -1), far]


def observe_partly(svc, marks) -> dict:
    out = {}
    for h in ("ada", "bob"):
        c = svc.client(h)
        out[h] = {"me": c.me(), "auths": c.auths(), "views": [c.money_at(t) for t in marks],
                  "known": [c.money_at(None, t) for t in marks], "present": c.money_at(None, FAR_FUTURE)}
    return out


def test_a_partly_captured_hold_round_trips_with_its_history(svc, svc_b):
    """D84, I67: the same history views after an export and import, in the same container and a second one."""
    marks = partly_captured_state(svc)
    before = observe_partly(svc, marks)
    assert before["ada"]["views"][:4] == [(10_050, 10_050, 0), (10_050, 9_450, 600), (10_050, 9_450, 600),
                                          (10_000, 9_400, 600)], "D84 before the export"
    assert before["ada"]["views"][5] == (9_900, 9_400, 500) and before["ada"]["views"][7] == (9_850, 9_400, 450)
    for h in ("ada", "bob"):
        m = before[h]["me"]
        assert before[h]["present"] == (m["total"], m["available"], m["held"]), f"I67 for {h}"
    snap = svc.export()
    expect(svc.import_(snap), 204)
    assert observe_partly(svc, marks) == before
    svc_b.must_reset(fixture(standard_users()))
    expect(svc_b.import_(snap), 204)
    assert observe_partly(svc_b, marks) == before
    expect(svc_b.client("bob").capture("a_part", {"amount": 50, "final": False}), 201)
    assert svc_b.client("ada").money() == (9_800, 9_400, 400)
