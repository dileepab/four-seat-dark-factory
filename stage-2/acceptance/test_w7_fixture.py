"""W7.8 — the stage-2 fixture: authorization_ttl_seconds and authorizations (stage-2 "Model";
PLAN 3.11, D48, D62). I25, I30, I33."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from support import (AUTHZ_KEYS, Snapshot, check_authorization, check_payment, expect, expect_error, fixture,
                     seeded_auth, standard_users, ts)
from test_w5_export_import import _shift_years

pytestmark = pytest.mark.item(7)

FAR = "2099-06-15T10:20:30Z"


def base() -> dict:
    return fixture(standard_users(), ttl=600, authorizations=[
        {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2_000, "note": "deposit",
         "visibility": "public", "status": "open", "expires_at": FAR},
        {"id": "a_2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100, "status": "captured",
         "expires_at": FAR, "payment_id": "p_9"}])


def _a(fx, i=0):
    return fx["authorizations"][i]


INVALID = {
    "ttl 0": lambda fx: fx.update(authorization_ttl_seconds=0),
    "ttl -1": lambda fx: fx.update(authorization_ttl_seconds=-1),
    "ttl 1.5": lambda fx: fx.update(authorization_ttl_seconds=1.5),
    "ttl string": lambda fx: fx.update(authorization_ttl_seconds="600"),
    "ttl null": lambda fx: fx.update(authorization_ttl_seconds=None),
    "ttl boolean": lambda fx: fx.update(authorization_ttl_seconds=True),
    "ttl above 10^10": lambda fx: fx.update(authorization_ttl_seconds=10 ** 10 + 1),
    "authorizations string": lambda fx: fx.update(authorizations="a_1"),
    "authorizations object": lambda fx: fx.update(authorizations={"a_1": _a(fx)}),
    "authorization not object": lambda fx: fx["authorizations"].append(5),
    "authorization null": lambda fx: fx["authorizations"].append(None),
    "id missing": lambda fx: _a(fx).pop("id"),
    "id empty": lambda fx: _a(fx).update(id=""),
    "id 65 chars": lambda fx: _a(fx).update(id="a" * 65),
    "id number": lambda fx: _a(fx).update(id=7),
    "duplicate id": lambda fx: _a(fx, 1).update(id="a_1"),
    "payer missing": lambda fx: _a(fx).pop("from_user_id"),
    "payer unknown": lambda fx: _a(fx).update(from_user_id="u_ghost"),
    "receiver missing": lambda fx: _a(fx).pop("to_user_id"),
    "receiver unknown": lambda fx: _a(fx).update(to_user_id="u_ghost"),
    "payer is receiver": lambda fx: _a(fx).update(to_user_id="u_ada"),
    "amount missing": lambda fx: _a(fx).pop("amount"),
    "amount negative": lambda fx: _a(fx).update(amount=-1),
    "amount fraction": lambda fx: _a(fx).update(amount=1.5),
    "amount string": lambda fx: _a(fx).update(amount="10"),
    "amount above max": lambda fx: _a(fx, 1).update(amount=1_000_000_001),
    "amount boolean": lambda fx: _a(fx).update(amount=True),
    "captured negative": lambda fx: _a(fx).update(captured_amount=-1),
    "captured above amount": lambda fx: _a(fx, 1).update(captured_amount=101),
    "captured fraction": lambda fx: _a(fx).update(captured_amount=1.5),
    "captured string": lambda fx: _a(fx).update(captured_amount="5"),
    "open fully captured": lambda fx: _a(fx).update(captured_amount=2_000),
    "open amount zero": lambda fx: _a(fx).update(amount=0),
    "note number": lambda fx: _a(fx).update(note=5),
    "visibility unknown": lambda fx: _a(fx).update(visibility="secret"),
    "visibility upper case": lambda fx: _a(fx).update(visibility="PUBLIC"),
    "status unknown": lambda fx: _a(fx).update(status="pending"),
    "status upper case": lambda fx: _a(fx).update(status="OPEN"),
    "status number": lambda fx: _a(fx).update(status=1),
    "expires_at missing": lambda fx: _a(fx).pop("expires_at"),
    "expires_at number": lambda fx: _a(fx).update(expires_at=4_102_444_800),
    "expires_at null": lambda fx: _a(fx).update(expires_at=None),
    "expires_at empty": lambda fx: _a(fx).update(expires_at=""),
    "expires_at words": lambda fx: _a(fx).update(expires_at="tomorrow"),
    "expires_at month 13": lambda fx: _a(fx).update(expires_at="2099-13-01T00:00:00Z"),
    "expires_at 29 Feb 2099": lambda fx: _a(fx).update(expires_at="2099-02-29T00:00:00Z"),
    "expires_at 31 Apr": lambda fx: _a(fx).update(expires_at="2099-04-31T00:00:00Z"),
    "expires_at hour 24": lambda fx: _a(fx).update(expires_at="2099-01-01T24:00:00Z"),
    "expires_at minute 60": lambda fx: _a(fx).update(expires_at="2099-01-01T00:60:00Z"),
    "expires_at second 60": lambda fx: _a(fx).update(expires_at="2099-01-01T00:00:60Z"),
    "expires_at space": lambda fx: _a(fx).update(expires_at="2099-01-01 00:00:00Z"),
    "expires_at no offset": lambda fx: _a(fx).update(expires_at="2099-01-01T00:00:00"),
    "expires_at offset without colon": lambda fx: _a(fx).update(expires_at="2099-01-01T00:00:00+0200"),
    "expires_at no seconds": lambda fx: _a(fx).update(expires_at="2099-01-01T00:00Z"),
    "expires_at short month": lambda fx: _a(fx).update(expires_at="2099-1-01T00:00:00Z"),
    "expires_at date only": lambda fx: _a(fx).update(expires_at="2099-01-01"),
    "expires_at 65 chars": lambda fx: _a(fx).update(expires_at="2099-01-01T00:00:00." + "0" * 44 + "Z"),
    "payment_id number": lambda fx: _a(fx).update(payment_id=5),
    "payment_ids string": lambda fx: _a(fx).update(payment_ids="p_1"),
    "payment_ids with a number": lambda fx: _a(fx).update(payment_ids=["p_1", 5]),
    "payment_ids with null": lambda fx: _a(fx).update(payment_ids=[None]),
    "seeded payment authorization_id number": lambda fx: fx["payments"].append(
        {"id": "p_s", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1, "authorization_id": 5}),
    "open remainders above the balance": lambda fx: fx["authorizations"].append(
        {"id": "a_cy", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 501, "expires_at": FAR}),
    "two open remainders above the balance": lambda fx: fx["authorizations"].extend([
        {"id": "a_c1", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 300, "expires_at": FAR},
        {"id": "a_c2", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 300, "captured_amount": 99,
         "expires_at": FAR}]),
}


@pytest.mark.parametrize("name", list(INVALID))
def test_invalid_stage_2_fixture_is_422_and_changes_nothing(world, name):
    held = expect(world.ada.authorize("cy", 1_234), 201)
    expect(world.svc.signup("keepme@example.com", "correct horse", "Keep"), 201)
    before = (world.ada.me(), world.ada.auths(), world.cy.auths())
    bad = copy.deepcopy(base())
    INVALID[name](bad)
    expect_error(world.svc.api().post("/_test/reset", json=bad), 422, "validation_failed")
    assert (world.ada.me(), world.ada.auths(), world.cy.auths()) == before
    assert world.ada.money() == (10_000, 8_766, 1_234)
    assert world.svc.client("keepme").balance() == 0
    expect(world.cy.capture(held["authorization_id"], {"amount": 1}), 201)    # the old state still works


def test_base_fixture_is_valid(svc):
    svc.must_reset(base())


# ---------------------------------------------------------------- accepted fixtures

def test_seeded_authorization_representation_and_holds(svc):
    before = datetime.now(timezone.utc)
    svc.must_reset(base())
    after = datetime.now(timezone.utc)
    ada, bob, cy = svc.client("ada"), svc.client("bob"), svc.client("cy")
    a1 = check_authorization(ada.auth("a_1"), authorization_id="a_1", from_user_id="u_ada", from_handle="ada",
                             to_user_id="u_bob", to_handle="bob", amount=2_000, captured_amount=0,
                             remaining_amount=2_000, currency="EUR", note="deposit", visibility="public",
                             status="open", expires_at=FAR, payment_id=None, payment_ids=[])
    created = ts(a1["created_at"])
    assert before - timedelta(seconds=2) <= created <= after + timedelta(seconds=2), \
        "seeded authorizations take the reset's timestamp"
    check_authorization(cy.auth("a_2"), status="captured", captured_amount=100, remaining_amount=0,
                        payment_id="p_9", payment_ids=["p_9"], note="", visibility="public")
    assert ada.money() == (10_000, 8_000, 2_000), "seeded open holds count right after the reset"
    assert bob.money() == (2_500, 2_500, 0), "a seeded captured hold holds nothing"
    assert ada.auth("a_1") == bob.auth("a_1")


def test_defaults_and_unknown_fields(svc):
    svc.must_reset(fixture(standard_users(), authorizations=[
        {"id": "a_min", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 50, "expires_at": FAR,
         "created_at": "2001-01-01T00:00:00Z", "remaining_amount": 7, "from_handle": "zz", "extra": [1]}]))
    a = check_authorization(svc.client("bob").auth("a_min"), status="open", captured_amount=0,
                            remaining_amount=50, note="", visibility="public", payment_id=None,
                            payment_ids=[], from_handle="ada")
    assert not a["created_at"].startswith("2001"), "a seeded created_at is ignored"
    assert set(a) == AUTHZ_KEYS


@pytest.mark.parametrize("written", [
    "2099-01-01t00:00:00z", "2099-06-15T10:20:30.123456+05:30", "2099-12-31T23:59:59-08:00",
    "2099-02-28T00:00:00.5Z", "2096-02-29T12:00:00+00:00"])
def test_seeded_expires_at_comes_back_exactly_as_written(svc, written):
    svc.must_reset(fixture(standard_users(), authorizations=[seeded_auth("a_x", "ada", "bob", 5, expires_at=written)]))
    a = svc.client("ada").auth("a_x")
    assert a["expires_at"] == written and a["status"] == "open"


@pytest.mark.parametrize("status,captured,held", [
    ("open", 0, 300), ("open", 100, 200), ("captured", None, 0), ("captured", 120, 0),
    ("voided", None, 0), ("voided", 50, 0), ("expired", None, 0), ("expired", 299, 0)])
def test_captured_amount_default_and_what_each_status_holds(svc, status, captured, held):
    extra = {"status": status}
    if captured is not None:
        extra["captured_amount"] = captured
    svc.must_reset(fixture(standard_users(), authorizations=[seeded_auth("a_s", "ada", "bob", 300, **extra)]))
    a = check_authorization(svc.client("ada").auth("a_s"), status=status)
    want = captured if captured is not None else (300 if status == "captured" else 0)
    assert a["captured_amount"] == want
    assert a["remaining_amount"] == held
    assert svc.client("ada").money() == (10_000, 10_000 - held, held)


def test_closed_seeds_may_exceed_the_balance(svc):
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_c", "dee", "bob", 900_000, status="captured"),
        seeded_auth("a_v", "dee", "bob", 900_000, status="voided"),
        seeded_auth("a_e", "dee", "bob", 900_000, status="expired"),
        seeded_auth("a_p", "dee", "bob", 900_000, hours=-2)]))
    assert svc.client("dee").money() == (0, 0, 0)


def test_unexpired_open_remainders_equal_to_the_balance_are_valid(svc):
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_1", "cy", "bob", 300), seeded_auth("a_2", "cy", "ada", 400, captured_amount=200)]))
    assert svc.client("cy").money() == (500, 0, 500)
    expect_error(svc.client("cy").pay("dee", 1), 409, "insufficient_funds")


def test_payment_links_are_shown_as_given(svc):
    """PLAN 3.11 and D62: payment_id and payment_ids are display-only links, checked for type only."""
    svc.must_reset(fixture(standard_users(), payments=[
        {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 10, "authorization_id": "a_ids"},
        {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 20, "authorization_id": None},
        {"id": "p_3", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 30}],
        authorizations=[
            seeded_auth("a_one", "ada", "bob", 100, status="captured", payment_id="p_missing"),
            seeded_auth("a_ids", "ada", "bob", 100, status="captured", payment_ids=["p_1", "p_nowhere"]),
            seeded_auth("a_none", "ada", "bob", 100, status="voided", payment_id=None)]))
    ada = svc.client("ada")
    check_authorization(ada.auth("a_one"), payment_id="p_missing", payment_ids=["p_missing"])
    check_authorization(ada.auth("a_ids"), payment_id="p_nowhere", payment_ids=["p_1", "p_nowhere"])
    check_authorization(ada.auth("a_none"), payment_id=None, payment_ids=[])
    feed = {p["payment_id"]: p for p in ada.feed()}
    check_payment(feed["p_1"], authorization_id="a_ids")
    check_payment(feed["p_2"], authorization_id=None)
    check_payment(feed["p_3"], authorization_id=None)


def test_fixture_available_and_held_fields_are_ignored(svc):
    users = standard_users()
    users[0].update(available=1, held=9_999, total=5)
    svc.must_reset(fixture(users))
    assert svc.client("ada").money() == (10_000, 10_000, 0)


def test_reset_replaces_authorizations_and_the_ttl(world):
    expect(world.ada.authorize("bob", 100), 201)
    world.svc.must_reset(fixture(standard_users(), ttl=60))
    assert world.svc.client("ada").auths() == []
    a = expect(world.svc.client("ada").authorize("bob", 1), 201)
    assert ts(a["expires_at"]) - ts(a["created_at"]) == timedelta(seconds=60)
    world.svc.must_reset(fixture(standard_users()))
    a = expect(world.svc.client("ada").authorize("bob", 1), 201)
    assert ts(a["expires_at"]) - ts(a["created_at"]) == timedelta(seconds=600), "the TTL returns to 600"
    assert world.svc.client("ada").money() == (10_000, 9_999, 1)


def test_reset_after_an_import_whose_clock_ran_ahead_starts_the_clock_at_the_reset(svc):
    """W7.8, D49, I25, stage-1 §10 "Reset clears all state, including imported state" (critic X15):
    after an import dated 2099 the reset's own time is the clock, so a hold seeded two hours ahead is open."""
    svc.must_reset(fixture(standard_users()))
    expect(svc.client("ada").pay("bob", 1), 201)
    snap = svc.export()
    body = copy.deepcopy(snap.body)
    assert _shift_years(body["state"], "2099"), "no timestamp-shaped string in the export; this probe cannot run"
    expect(svc.import_(Snapshot(body, json.dumps(body), snap.total, copy.deepcopy(snap.accounts))), 204)
    ahead = expect(svc.client("ada").pay("bob", 1), 201)
    assert ts(ahead["created_at"]).year == 2099, "precondition: the imported clock runs ahead of the wall clock"
    svc.must_reset(fixture(standard_users(), authorizations=[seeded_auth("a_live", "ada", "bob", 400)]))
    ada = svc.client("ada")
    assert ada.money() == (10_000, 9_600, 400), "the seeded hold expiring in two hours is held"
    a = check_authorization(ada.auth("a_live"), status="open", remaining_amount=400, captured_amount=0)
    assert ts(a["created_at"]).year < 2099, f"the seeded hold is dated {a['created_at']}, by the imported clock"
    assert [x["authorization_id"] for x in ada.auths(status="open")] == ["a_live"]
    p = expect(ada.pay("bob", 1), 201)
    assert ts(p["created_at"]).year < 2099, f"a new payment is dated {p['created_at']}, by the imported clock"
    assert ts(a["created_at"]) <= ts(p["created_at"])
    expect(svc.client("bob").capture("a_live", {"amount": 400}), 201)
    assert ada.money() == (9_599, 9_599, 0)


def test_seeded_hold_is_capturable_and_voidable(svc):
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_cap", "ada", "bob", 1_000, note="seeded", visibility="private"),
        seeded_auth("a_void", "ada", "cy", 500)]))
    p = expect(svc.client("bob").capture("a_cap", {"amount": 400}), 201)
    check_payment(p, authorization_id="a_cap", amount=400, note="seeded", visibility="private",
                  from_user_id="u_ada", to_user_id="u_bob", request_id=None, settlement_id=None)
    expect(svc.client("ada").void("a_void"), 200)
    assert svc.client("ada").money() == (9_600, 9_600, 0)


def test_many_seeded_authorizations(svc):
    auths = [seeded_auth(f"a_{i:04d}", "ada", "bob", 1, status="voided") for i in range(2_000)]
    svc.must_reset(fixture(standard_users(), authorizations=auths))
    page = expect(svc.client("bob").get("/authorizations", params={"limit": 200}), 200)
    assert page["has_more"] is True and page["authorizations"][0]["authorization_id"] == "a_1999"
