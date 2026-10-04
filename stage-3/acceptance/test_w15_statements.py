"""W15.1-W15.7 — `GET /statement`: shape, order, windows, pages, `known_at`, snapshots and holds
(stage-3 "`GET /statement`", "Statement requirements", "Stable statement pagination", "Historical
holds"; PLAN 3.5, 3.6, 3.9, D67, D72, D73). I54, I55, I59, I64.

`read_statement` (support.py) reads a first page and every page of its snapshot and asserts I54
over the full window: running balances, the identity, the order and the half-open bounds.
"""
from __future__ import annotations

import json
import time

import pytest

from support import (EPOCH, FAR_FUTURE, check_payment, check_statement_page, expect, expect_error, fixture,
                     instant, new_key, page_snapshot, raw_request, read_statement, shifted, standard_users, user)
from test_w14_history import DISAGREE, DISAGREE_NEWEST_FIRST, HISTORY, OPENING, disagree_fixture, seeded
from test_w14_instants import INVALID, VALID

pytestmark = pytest.mark.item(15)


def uid(svc, h) -> str:
    svc.client(h)
    return svc.accounts[h].user_id


@pytest.fixture
def hist(svc):
    svc.must_reset(fixture(standard_users(), payments=HISTORY))
    return svc


# ---------------------------------------------------------------- W15.1 shape and order

def test_the_sample_walks_the_balance_forward(world):
    for amount in (300, 200):
        expect(world.ada.pay("bob", amount), 201)
    st = read_statement(world.ada, uid(world.svc, "ada"))
    assert st.deltas() == [-300, -200]
    assert (st.opening, st.closing) == (10_000, 9_500)
    assert [e["balance_after"] for e in st.entries] == [9_700, 9_500]
    assert st.first["has_more"] is False


def test_entries_carry_revision_1_of_each_payment(world):
    """W14.2, I56, PLAN 3.6: with no corrections each entry is revision 1 at the payment's created_at."""
    p = expect(world.ada.pay("bob", 120, note="lunch", visibility="private"), 201)
    rq = expect(world.bob.ask("ada", 80), 201)
    rp = expect(world.ada.pay_request(rq["request_id"]), 201)
    a = expect(world.ada.authorize("bob", 500), 201)
    cp = expect(world.bob.capture(a["authorization_id"], {"amount": 50}), 201)
    stm = expect(world.ada.settle([{"from_handle": "ada", "to_handle": "cy", "amount": 30}]), 201)
    made = [p, rp, cp] + stm["payments"]
    st = read_statement(world.ada, uid(world.svc, "ada"))
    assert [e["payment"] for e in st.entries] == made, "T45: the payments exactly as created, oldest first"
    for e in st.entries:
        assert e["revision"] == 1 and e["effective_at"] == e["recorded_at"] == e["payment"]["created_at"]
    assert st.deltas() == [-120, -80, -50, -30]
    assert st.entries[2]["payment"]["authorization_id"] == a["authorization_id"]
    assert st.entries[3]["effective_at"] == stm["committed_at"], "T56: a member's revision 1 is at committed_at"


def test_seeded_history_order_ties_and_zero_amounts(hist):
    """T18, T44: by effective_at (exact instants), ties by payment_id in code-point order; 0 deltas."""
    st = read_statement(hist.client("cy"), uid(hist, "cy"))
    assert st.ids() == ["p_2", "p_3", "p_5", "p_6", "p_7", "p_8"], st.ids()
    assert st.deltas() == [300, 0, 100, 0, 0, 0]
    assert st.opening == OPENING["cy"] and st.closing == 500
    created = {s["id"]: s.get("created_at") for s in HISTORY}
    for e in st.entries:
        assert e["payment"]["created_at"] == created[e["payment"]["payment_id"]], "a seeded created_at, as written"
        assert e["effective_at"] == e["payment"]["created_at"]


def test_ties_sort_by_payment_id_code_points(svc):
    ids = ["p_b", "p_B", "p_a", "p_A", "p_10", "p_9", "q", "P"]
    at = "2026-05-01T10:00:00Z"
    svc.must_reset(fixture([user("ada", 1_000), user("bob", 0)],
                           payments=[seeded(i, "bob", "ada", 1, at) for i in ids]))
    st = read_statement(svc.client("ada"), uid(svc, "ada"))
    assert st.ids() == sorted(ids), "D72: ties by payment_id in code-point order"
    assert st.opening == 1_000 - len(ids) and st.closing == 1_000


def test_sent_is_negative_and_received_positive(world):
    expect(world.ada.pay("bob", 400), 201)
    expect(world.bob.pay("ada", 150), 201)
    assert read_statement(world.ada, uid(world.svc, "ada")).deltas() == [-400, 150]
    assert read_statement(world.bob, uid(world.svc, "bob")).deltas() == [400, -150]


def test_a_zero_amount_request_payment_is_an_entry(world):
    sp = expect(world.ada.split(1, ["ada", "bob", "cy"]), 201)
    zero = [r for r in sp["requests"] if r["amount"] == 0]
    assert zero, sp
    payer = zero[0]["payer_handle"]
    p = expect(world.svc.client(payer).pay_request(zero[0]["request_id"]), 201)
    st = read_statement(world.svc.client(payer), uid(world.svc, payer))
    assert [(e["payment"]["payment_id"], e["delta"]) for e in st.entries] == [(p["payment_id"], 0)]


# ---------------------------------------------------------------- W15.2 windows

def test_the_window_is_half_open(world):
    ps = [expect(world.ada.pay("bob", amt), 201) for amt in (100, 200, 300, 400)]
    me = uid(world.svc, "ada")
    st = read_statement(world.ada, me, **{"from": ps[1]["created_at"], "to": ps[3]["created_at"]})
    assert st.ids() == [ps[1]["payment_id"], ps[2]["payment_id"]], "a payment at from is in, one at to is out"
    assert (st.opening, st.closing) == (9_900, 9_400), "T19: the balances immediately before from and before to"
    st = read_statement(world.ada, me, **{"from": shifted(ps[1]["created_at"], 1),
                                          "to": shifted(ps[3]["created_at"], 1)})
    assert st.ids() == [ps[2]["payment_id"], ps[3]["payment_id"]]
    assert (st.opening, st.closing) == (9_700, 9_000)


def test_from_absent_is_the_opening_and_to_absent_is_now(hist):
    ada = hist.client("ada")
    me = uid(hist, "ada")
    p = expect(ada.pay("dee", 10), 201)
    st = read_statement(ada, me)
    assert st.opening == OPENING["ada"], "from absent: the opening of the wallet (I51)"
    assert st.ids()[-1] == p["payment_id"], "D67: a payment made just before the read is in the default window"
    assert st.closing == 9_990
    st2 = read_statement(ada, me, to=FAR_FUTURE)
    assert st2.entries == st.entries
    st3 = read_statement(ada, me, **{"from": EPOCH})
    assert st3.entries == st.entries and st3.opening == OPENING["ada"]


def test_the_last_payment_is_in_the_default_window_every_time(world):
    """D67: the default `to` is the read's instant plus a millisecond, so a payment issued in the
    same millisecond as the read is never cut off."""
    me = uid(world.svc, "ada")
    for i in range(30):
        p = expect(world.ada.pay("bob", 1), 201)
        body = expect(world.ada.statement(offset=i), 200)
        assert [e["payment"]["payment_id"] for e in body["entries"]] == [p["payment_id"]], f"read {i}: {body}"


def test_seeded_windows_and_balances(hist):
    ada = hist.client("ada")
    me = uid(hist, "ada")
    st = read_statement(ada, me, **{"from": "2026-03-01T09:00:00Z", "to": "2026-03-01T12:00:00.000001Z"})
    assert st.ids() == ["p_1"] and (st.opening, st.closing) == (9_500, 10_500)
    st = read_statement(ada, me, **{"from": "2026-03-01T09:00:00.000000001Z", "to": "2026-03-01T17:30:00.0000011+05:30"})
    assert st.ids() == ["p_2"] and (st.opening, st.closing) == (10_500, 10_200)


def test_from_equal_to_is_an_empty_window(hist):
    me = uid(hist, "ada")
    for t in ("2026-03-01T09:00:00Z", "2026-03-01T12:00:00.000001Z", EPOCH, FAR_FUTURE):
        st = read_statement(hist.client("ada"), me, **{"from": t, "to": t})
        assert st.entries == [] and st.opening == st.closing, f"from == to == {t}: {st.first}"
    st = read_statement(hist.client("ada"), me, **{"from": "2026-03-01T14:00:00+05:00", "to": "2026-03-01T09:00:00Z"})
    assert st.entries == [] and st.opening == st.closing == 9_500, "the same instant in two offsets: before p_1"


@pytest.mark.parametrize("frm, to", [("2026-03-01T09:00:00.000001Z", "2026-03-01T09:00:00Z"),
                                     (FAR_FUTURE, EPOCH), ("2026-03-01T10:00:00+00:00", "2026-03-01T10:59:59+01:00")])
def test_from_later_than_to_is_422(hist, frm, to):
    expect_error(hist.client("ada").statement(**{"from": frm, "to": to}), 422, "validation_failed")


@pytest.mark.parametrize("frm", [FAR_FUTURE, "2999-01-01t00:00:00+05:30"])
def test_a_future_from_without_to_is_an_empty_window(world, frm):
    """D72 (revised): with `to` omitted, a future `from` is an empty window at the balance of the read."""
    expect(world.ada.pay("bob", 25), 201)
    st = read_statement(world.ada, uid(world.svc, "ada"), **{"from": frm})
    assert st.entries == [] and st.opening == st.closing == 9_975


def test_seeds_whose_string_order_disagrees_sort_by_instant(svc):
    """W15.1 (critic B5): +05:30 against Z, ...:00Z against ...:00.000001Z, a lowercase t."""
    svc.must_reset(disagree_fixture(svc))
    st = read_statement(svc.client("dee"), uid(svc, "dee"))
    assert st.ids() == list(reversed(DISAGREE_NEWEST_FIRST))
    assert [e["effective_at"] for e in st.entries] == [dict(DISAGREE)[i] for i in st.ids()]


def test_future_instants_are_allowed(world):
    expect(world.ada.pay("bob", 5), 201)
    st = read_statement(world.ada, uid(world.svc, "ada"), to=FAR_FUTURE, known_at=FAR_FUTURE)
    assert st.deltas() == [-5]
    st = read_statement(world.ada, uid(world.svc, "ada"), **{"from": "9999-01-01T00:00:00Z", "to": FAR_FUTURE})
    assert st.entries == [] and st.opening == st.closing == 9_995


@pytest.mark.parametrize("param", ["from", "to", "known_at"])
@pytest.mark.parametrize("value", INVALID.values(), ids=INVALID.keys())
def test_invalid_instants_are_422(world, param, value):
    expect_error(world.ada.statement(**{param: value}), 422, "validation_failed")


@pytest.mark.parametrize("value", VALID)
def test_valid_instants_are_accepted(world, value):
    expect(world.ada.statement(**{"from": value, "to": FAR_FUTURE}), 200)
    expect(world.ada.statement(to=value), 200)
    body = expect(world.ada.statement(known_at=value), 200)
    assert body["known_at"] == value


@pytest.mark.parametrize("param", ["from", "to", "known_at"])
def test_a_literal_plus_in_statement_instants(world, param):
    status, _, raw = raw_request(world.svc.base_url, "GET", f"/statement?{param}=2026-01-01T05:30:00+05:30",
                                 token=world.ada.token)
    assert status == 200, raw[:200]
    if param == "known_at":
        assert json.loads(raw)["known_at"] == "2026-01-01T05:30:00+05:30"


def test_a_token_is_checked_first(world):
    anon = world.svc.api()
    expect_error(anon.statement(), 401, "unauthenticated")
    expect_error(anon.statement(**{"from": "x", "limit": 0}), 401, "unauthenticated")
    expect_error(anon.statement(snapshot="nope"), 401, "unauthenticated")
    expect_error(anon.statement(snapshot="nope", to="x"), 401, "unauthenticated")


# ---------------------------------------------------------------- W15.3 only the caller's payments

def test_only_the_callers_payments_whatever_their_visibility(world):
    mine_private = expect(world.ada.pay("bob", 10, visibility="private"), 201)
    expect(world.bob.pay("cy", 20, visibility="public"), 201)          # public, between two others
    expect(world.cy.pay("dee", 30, visibility="private"), 201)
    to_me = expect(world.bob.pay("ada", 40, visibility="private"), 201)
    st = read_statement(world.ada, uid(world.svc, "ada"))
    assert st.ids() == [mine_private["payment_id"], to_me["payment_id"]], "T22"
    assert st.deltas() == [-10, 40]
    assert read_statement(world.dee, uid(world.svc, "dee")).deltas() == [30]


# ---------------------------------------------------------------- W15.4 pages

@pytest.fixture
def many(world):
    """Ada pays bob 1..120 and receives 5 from cy after every tenth payment: 132 entries."""
    for i in range(1, 121):
        expect(world.ada.pay("bob", i), 201)
        if i % 10 == 0:
            expect(world.cy.pay("ada", 5), 201)
    return world


def test_pages_keep_the_window_balances(many):
    ada = many.ada
    me = uid(many.svc, "ada")
    full = read_statement(ada, me)
    assert len(full.entries) == 132
    assert full.first["has_more"] is True and len(full.first["entries"]) == 50, "limit defaults to 50"
    for limit, offset in ((50, 50), (7, 0), (7, 125), (200, 0), (1, 131), (40, 120), (1, 132), (10, 500)):
        body = check_statement_page(expect(ada.statement_page(full.snapshot, limit=limit, offset=offset), 200), me,
                                    snapshot=full.snapshot)
        assert (body["opening_balance"], body["closing_balance"]) == (full.opening, full.closing), \
            "T21: paging never changes the window balances"
        assert body["entries"] == full.entries[offset:offset + limit]
        assert body["has_more"] == (offset + limit < 132), f"has_more at offset {offset}, limit {limit}"
    # The same through fresh first reads with limit and offset.
    for limit, offset in ((60, 60), (12, 120), (5, 200)):
        st = read_statement(ada, me, limit=limit, offset=offset)
        assert st.entries == full.entries
        assert st.first["entries"] == full.entries[offset:offset + limit]
        assert (st.first["opening_balance"], st.first["closing_balance"]) == (10_000, full.closing)


def test_second_page_continues_the_running_balance(many):
    ada = many.ada
    first = expect(ada.statement(limit=50), 200)
    second = expect(ada.statement_page(first["snapshot"], limit=50, offset=50), 200)
    assert second["opening_balance"] == first["opening_balance"] == 10_000
    assert second["closing_balance"] == first["closing_balance"]
    assert second["entries"][0]["balance_after"] == first["entries"][-1]["balance_after"] + second["entries"][0]["delta"]


BAD_PAGING = [{"limit": "0"}, {"limit": "201"}, {"limit": "-1"}, {"limit": "1.5"}, {"limit": "1e2"},
              {"limit": "+4"}, {"limit": ""}, {"limit": "ten"}, {"offset": "-1"}, {"offset": "1.0"},
              {"offset": ""}, {"offset": "x"}, {"offset": "+1"}]


@pytest.mark.parametrize("params", BAD_PAGING, ids=[json.dumps(p) for p in BAD_PAGING])
def test_invalid_paging_is_422_as_on_requests(world, params):
    expect_error(world.ada.get("/requests", params=params), 422, "validation_failed")   # the reference rule
    expect_error(world.ada.statement(**params), 422, "validation_failed")
    snap = expect(world.ada.statement(), 200)["snapshot"]
    expect_error(world.ada.statement(snapshot=snap, **params), 422, "validation_failed")


def test_valid_paging_edges(world):
    expect(world.ada.pay("bob", 1), 201)
    for params in ({"limit": "1"}, {"limit": "200"}, {"offset": "0"}, {"offset": "1000000"}):
        expect(world.ada.statement(**params), 200)


@pytest.mark.parametrize("params", [{"limit": "007"}, {"limit": " 5"}, {"offset": "00"}, {"limit": "5 "},
                                    {"offset": "99999999999999999999"}])
def test_paging_edges_match_requests(world, params):
    """T15: limit and offset behave exactly as in GET /requests."""
    want = world.ada.get("/requests", params=params).status_code
    assert world.ada.statement(**params).status_code == want, f"{params}: GET /requests gives {want}"


def test_unknown_parameters_are_ignored(world):
    expect(world.ada.pay("bob", 1), 201)
    body = expect(world.ada.statement(page="2", size="1", snapshots="x", fromm="y"), 200)
    assert [e["delta"] for e in body["entries"]] == [-1]
    snap = body["snapshot"]
    body = expect(world.ada.statement(snapshot=snap, page="2", foo="bar"), 200)
    assert [e["delta"] for e in body["entries"]] == [-1]


# ---------------------------------------------------------------- W15.5 known_at

def test_known_at_hides_later_payments_and_is_echoed_on_every_page(world):
    ps = [expect(world.ada.pay("bob", amt), 201) for amt in (10, 20, 30)]
    me = uid(world.svc, "ada")
    k = ps[1]["created_at"]
    st = read_statement(world.ada, me, known_at=k, limit=1)
    assert st.deltas() == [-10, -20] and st.closing == 9_970
    for off in (0, 1, 2):
        page = expect(world.ada.statement_page(st.snapshot, limit=1, offset=off), 200)
        assert page["known_at"] == k, "I59: known_at on every page read through the snapshot"
    st = read_statement(world.ada, me, known_at=shifted(ps[0]["created_at"], -1))
    assert st.entries == [] and st.opening == st.closing == 10_000
    body = expect(world.ada.statement(), 200)
    assert "known_at" not in body and "known_at" not in expect(world.ada.statement_page(body["snapshot"]), 200)


def test_known_at_on_seeded_history(hist):
    st = read_statement(hist.client("ada"), uid(hist, "ada"), known_at="2026-03-01T12:00:00Z")
    assert st.ids() == ["p_1"] and st.closing == 10_500
    st = read_statement(hist.client("ada"), uid(hist, "ada"), known_at="2026-03-01T12:00:00Z",
                        to="2026-03-01T09:00:00Z")
    assert st.ids() == [] and st.closing == 9_500


# ---------------------------------------------------------------- W15.6 snapshots

def test_every_first_read_returns_a_new_snapshot(world):
    tokens = {expect(world.ada.statement(), 200)["snapshot"] for _ in range(5)}
    assert len(tokens) == 5, "I55: every first read stores a new snapshot"


def test_a_snapshot_is_frozen_against_every_later_write(world):
    """T47, T53, T70: payments, request payments, settlements, authorizations, captures, voids, expiries."""
    svc = world.svc
    svc.must_reset(fixture(standard_users(), operators=["u_ada"], ttl=2))
    ada, bob, cy = svc.client("ada"), svc.client("bob"), svc.client("cy")
    expect(ada.pay("bob", 100), 201)
    a_open = expect(ada.authorize("bob", 300), 201)        # expires in two seconds
    me = uid(svc, "ada")
    before = read_statement(ada, me, limit=1)
    expect(ada.pay("bob", 7), 201)
    rq = expect(bob.ask("ada", 11), 201)
    expect(ada.pay_request(rq["request_id"]), 201)
    expect(ada.settle([{"from_handle": "ada", "to_handle": "cy", "amount": 13}]), 201)
    a = expect(ada.authorize("cy", 40), 201)
    expect(cy.capture(a["authorization_id"], {"amount": 15, "final": False}), 201)
    expect(ada.void(a["authorization_id"]), 200)
    deadline = time.monotonic() + 10
    while ada.auth(a_open["authorization_id"])["status"] == "open":
        assert time.monotonic() < deadline
        time.sleep(0.2)
    entries, opening, closing = page_snapshot(ada, me, before.snapshot, page_limit=1)
    assert (entries, opening, closing) == (before.entries, before.opening, before.closing), \
        "I55: a snapshot pages exactly its first result"
    now = read_statement(ada, me)
    assert len(now.entries) == 5 and now.closing == 10_000 - 100 - 7 - 11 - 13 - 15


@pytest.mark.parametrize("extra", [{"from": EPOCH}, {"to": FAR_FUTURE}, {"known_at": FAR_FUTURE},
                                   {"from": ""}, {"known_at": "bad"}])
def test_snapshot_with_window_parameters_is_422(world, extra):
    snap = expect(world.ada.statement(), 200)["snapshot"]
    expect_error(world.ada.statement(snapshot=snap, **extra), 422, "validation_failed")


def test_unknown_foreign_and_pre_reset_tokens_are_404(world):
    svc = world.svc
    snap = expect(world.ada.statement(), 200)["snapshot"]
    expect_error(world.bob.statement(snapshot=snap), 404, "not_found")
    for bogus in ("nope", snap + "x", snap[:-1], "ss_" + "0" * 40, "x" * 5000, "", snap.upper()):
        if bogus != snap:
            expect_error(world.ada.statement(snapshot=bogus), 404, "not_found")   # PLAN 3.14: any length
    svc.must_reset(fixture(standard_users()))
    expect_error(svc.client("ada").statement(snapshot=snap), 404, "not_found")


def test_a_snapshot_survives_other_users_reads(world):
    me = uid(world.svc, "ada")
    expect(world.ada.pay("bob", 3), 201)
    st = read_statement(world.ada, me)
    for _ in range(3):
        expect(world.bob.statement(), 200)
    assert page_snapshot(world.ada, me, st.snapshot)[0] == st.entries


# ---------------------------------------------------------------- W15.7 holds are not entries

def test_holds_are_not_entries_and_each_capture_is_one(world):
    svc = world.svc
    a1 = expect(world.ada.authorize("bob", 500), 201)
    a2 = expect(world.ada.authorize("bob", 300), 201)
    a3 = expect(world.ada.authorize("cy", 200), 201)
    c1 = expect(world.bob.capture(a1["authorization_id"], {"amount": 100, "final": False}), 201)
    c2 = expect(world.bob.capture(a1["authorization_id"], {"amount": 400}), 201)
    expect(world.ada.void(a2["authorization_id"]), 200)
    for c, me in ((world.ada, "ada"), (world.bob, "bob")):
        st = read_statement(c, uid(svc, me))
        assert st.ids() == [c1["payment_id"], c2["payment_id"]], "T69: captures only, once each"
        assert {e["payment"]["authorization_id"] for e in st.entries} == {a1["authorization_id"]}
    assert read_statement(world.cy, uid(svc, "cy")).entries == []
    assert a3["status"] == "open"
