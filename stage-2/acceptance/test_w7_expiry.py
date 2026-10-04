"""W7.6 — expiry by the clock (stage-2 "Model"; PLAN 3.7 service clock, 3.13, D49, D50). I15, I33, I34."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from support import check_authorization, expect, expect_error, fixture, seeded_auth, standard_users, ts

pytestmark = pytest.mark.item(7)

MARGIN = 0.6    # seconds after the deadline; covers a small clock difference between host and container


def sleep_past(expires_at: str) -> None:
    """Wait, sending nothing, until the deadline has passed."""
    delay = ts(expires_at).timestamp() + MARGIN - time.time()
    if delay > 0:
        time.sleep(delay)


@pytest.fixture
def short(svc):
    svc.must_reset(fixture(standard_users(), ttl=2))
    return svc


def test_open_hold_expires_with_no_request_at_the_deadline(short):
    ada, bob = short.client("ada"), short.client("bob")
    a = expect(ada.authorize("bob", 1_000, note="n"), 201)
    early = expect(ada.authorize("bob", 1_000), 201)
    expect(bob.capture(early["authorization_id"]), 201)          # before the deadline: allowed
    assert ada.money() == (9_000, 8_000, 1_000)
    sleep_past(a["expires_at"])
    aid = a["authorization_id"]
    got = check_authorization(ada.auth(aid), status="expired", remaining_amount=0, captured_amount=0)
    assert got["expires_at"] == a["expires_at"] and got["created_at"] == a["created_at"]
    assert bob.auth(aid) == got
    assert aid in [x["authorization_id"] for x in ada.auths(status="expired")]
    assert aid not in [x["authorization_id"] for x in ada.auths(status="open")]
    assert aid in [x["authorization_id"] for x in bob.auths(direction="incoming", status="expired")]
    assert ada.money() == (9_000, 9_000, 0), "an expired hold holds nothing"
    expect_error(bob.capture(aid), 409, "authorization_expired")
    expect_error(bob.capture(aid, {"amount": 1, "final": False}), 409, "authorization_expired")
    expect_error(ada.void(aid), 409, "authorization_not_open")
    assert ada.money() == (9_000, 9_000, 0)


def test_released_money_is_spendable_after_expiry(short):
    cy = short.client("cy")
    a = expect(cy.authorize("ada", 500), 201)
    expect_error(cy.pay("dee", 1), 409, "insufficient_funds")
    sleep_past(a["expires_at"])
    expect(cy.pay("dee", 500), 201)
    assert cy.money() == (0, 0, 0)


def test_partially_captured_hold_expires_keeping_its_captures(short):
    ada, bob = short.client("ada"), short.client("bob")
    a = expect(ada.authorize("bob", 1_000), 201)
    key = "capture-before-expiry"
    p = expect(bob.capture(a["authorization_id"], {"amount": 300, "final": False}, key=key), 201)
    assert ada.money() == (9_700, 9_000, 700)
    sleep_past(a["expires_at"])
    check_authorization(ada.auth(a["authorization_id"]), status="expired", captured_amount=300,
                        remaining_amount=0, payment_id=p["payment_id"], payment_ids=[p["payment_id"]])
    assert ada.money() == (9_700, 9_700, 0)
    # I15: replays still return the originals after the authorization expired.
    assert expect(bob.capture(a["authorization_id"], {"amount": 300, "final": False}, key=key), 200) == p
    assert ada.money() == (9_700, 9_700, 0)


def test_creation_replay_after_expiry_returns_the_original_open_body(short):
    ada = short.client("ada")
    key = "auth-before-expiry"
    a = expect(ada.authorize("bob", 100, key=key), 201)
    sleep_past(a["expires_at"])
    assert expect(ada.authorize("bob", 100, key=key), 200) == a
    assert ada.money() == (10_000, 10_000, 0)


def test_ttl_of_one_second(svc):
    svc.must_reset(fixture(standard_users(), ttl=1))
    a = expect(svc.client("ada").authorize("bob", 10), 201)
    assert ts(a["expires_at"]) - ts(a["created_at"]) == timedelta(seconds=1)
    sleep_past(a["expires_at"])
    check_authorization(svc.client("bob").auth(a["authorization_id"]), status="expired")


def test_seeded_open_hold_an_hour_in_the_past_reads_expired_at_once(svc):
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_past", "cy", "bob", 100_000, hours=-1.5, note="old"),      # above cy's 500: not held
        seeded_auth("a_live", "cy", "bob", 200)]))
    cy, bob = svc.client("cy"), svc.client("bob")
    check_authorization(cy.auth("a_past"), status="expired", remaining_amount=0, amount=100_000)
    assert cy.money() == (500, 300, 200)
    expect_error(bob.capture("a_past"), 409, "authorization_expired")
    expect_error(cy.void("a_past"), 409, "authorization_not_open")
    assert [x["authorization_id"] for x in cy.auths(status="open")] == ["a_live"]


def test_seeded_expired_status_with_a_future_deadline_is_not_open(svc):
    """D50 (plan 45fe2dc): a stored `expired` whose deadline is still ahead meets only the "not open" row."""
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_exp", "ada", "bob", 100, status="expired", hours=5)]))
    check_authorization(svc.client("ada").auth("a_exp"), status="expired", remaining_amount=0)
    expect_error(svc.client("bob").capture("a_exp"), 409, "authorization_not_open")
    expect_error(svc.client("ada").void("a_exp"), 409, "authorization_not_open")
    assert svc.client("ada").money() == (10_000, 10_000, 0)


def test_seeded_expired_status_with_a_past_deadline_is_expired(svc):
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_exp", "ada", "bob", 100, status="expired", hours=-3)]))
    check_authorization(svc.client("bob").auth("a_exp"), status="expired", remaining_amount=0)
    expect_error(svc.client("bob").capture("a_exp"), 409, "authorization_expired")
    expect_error(svc.client("ada").void("a_exp"), 409, "authorization_not_open")


def test_the_clock_expires_only_open_authorizations(svc):
    """I34 (plan 45fe2dc): captured and voided holds keep their status, filters and answers after the deadline."""
    svc.must_reset(fixture(standard_users(), ttl=1))
    ada, bob = svc.client("ada"), svc.client("bob")
    cap = expect(ada.authorize("bob", 300), 201)
    expect(bob.capture(cap["authorization_id"]), 201)
    part = expect(ada.authorize("bob", 400), 201)
    expect(bob.capture(part["authorization_id"], {"amount": 100}), 201)       # final: captured with 100
    void = expect(ada.authorize("bob", 500), 201)
    voided = expect(ada.void(void["authorization_id"]), 200)
    sleep_past(max(cap["expires_at"], part["expires_at"], void["expires_at"], key=lambda x: ts(x)))
    check_authorization(ada.auth(cap["authorization_id"]), status="captured", captured_amount=300)
    check_authorization(ada.auth(part["authorization_id"]), status="captured", captured_amount=100)
    assert ada.auth(void["authorization_id"]) == voided
    ids = lambda **q: {x["authorization_id"] for x in ada.auths(**q)}     # noqa: E731
    assert ids(status="captured") == {cap["authorization_id"], part["authorization_id"]}
    assert ids(status="voided") == {void["authorization_id"]}
    assert ids(status="expired") == set()
    for aid in (cap["authorization_id"], part["authorization_id"], void["authorization_id"]):
        expect_error(bob.capture(aid), 409, "authorization_not_open")
    expect_error(ada.void(cap["authorization_id"]), 409, "authorization_not_open")
    assert expect(ada.void(void["authorization_id"]), 200) == voided
    assert ada.money() == (9_600, 9_600, 0)


def test_failed_captures_claim_no_key(short):
    """W7.3 (§7 rows): a 422 exceeds and a 409 expired claim nothing; the same key then captures."""
    ada, bob = short.client("ada"), short.client("bob")
    live = expect(ada.authorize("bob", 300), 201)
    key = "capture-key-after-failures"
    expect_error(bob.capture(live["authorization_id"], {"amount": 301}, key=key), 422, "capture_exceeds_authorization")
    p = expect(bob.capture(live["authorization_id"], {"amount": 300}, key=key), 201)
    assert expect(bob.capture(live["authorization_id"], {"amount": 300}, key=key), 200) == p
    gone = expect(ada.authorize("bob", 200), 201)
    sleep_past(gone["expires_at"])
    key2 = "capture-key-after-expiry"
    expect_error(bob.capture(gone["authorization_id"], key=key2), 409, "authorization_expired")
    # The key was not claimed: another body under it is still judged on the state, not as key reuse.
    expect_error(bob.capture(gone["authorization_id"], {"amount": 5}, key=key2), 409, "authorization_expired")
    assert ada.money() == (9_700, 9_700, 0)


def _in_offset(dt: datetime, hours: int) -> str:
    tz = timezone(timedelta(hours=hours))
    local = dt.astimezone(tz)
    sign = "+" if hours >= 0 else "-"
    return local.strftime("%Y-%m-%dT%H:%M:%S") + f"{sign}{abs(hours):02d}:00"


def test_seeded_expires_at_is_compared_as_an_instant(svc):
    """D48: a past instant written in +14:00 reads later than now as text; a future one in -12:00 reads earlier."""
    now = datetime.now(timezone.utc)
    past = _in_offset(now - timedelta(hours=1, minutes=30), 14)
    future = _in_offset(now + timedelta(hours=2), -12)
    svc.must_reset(fixture(standard_users(), authorizations=[
        {"id": "a_past", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "expires_at": past},
        {"id": "a_future", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 200, "expires_at": future}]))
    ada = svc.client("ada")
    assert ada.auth("a_past")["status"] == "expired" and ada.auth("a_past")["expires_at"] == past
    assert ada.auth("a_future")["status"] == "open" and ada.auth("a_future")["expires_at"] == future
    assert ada.money() == (10_000, 9_800, 200)
