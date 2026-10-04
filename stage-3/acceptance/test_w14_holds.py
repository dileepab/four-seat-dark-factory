"""W14.6, W14.7 — historical holds and `closed_at` (stage-3 "Historical holds"; PLAN 3.6, 3.8, 3.10,
D71). I1, I60, I61.

Every instant comes from the service: a hold's `created_at`, `expires_at` and `closed_at`, a
capture's `created_at`, or the reset's timestamp read from a seeded record that omitted its own.
"""
from __future__ import annotations

import time

import pytest

from support import (EPOCH, FAR_FUTURE, PLAN_TS, STAGE2_AUTHZ_KEYS, check_authorization, expect, fixture,
                     fmt_instant, instant, new_key, shifted, standard_users)
from test_w14_history import seeded as seeded_payment

pytestmark = pytest.mark.item(14)


def view(c, as_of=None, known_at=None) -> tuple[int, int, int]:
    """(total, available, held) in one view; check_me_view asserts I60's identities."""
    return c.money_at(as_of, known_at)


def conserved(svc, as_of=None, known_at=None) -> None:
    s = sum(svc.client(h).me_at(as_of, known_at)["total"] for h in svc.accounts)
    assert s == svc.total, f"I1 at as_of={as_of} known_at={known_at}: {s} != {svc.total}"


# ---------------------------------------------------------------- API holds

def test_a_hold_counts_from_its_creation(world):
    a = check_authorization(expect(world.ada.authorize("bob", 1_000), 201), status="open", closed_at=None)
    c = a["created_at"]
    ada = world.ada
    assert view(ada, shifted(c, -1)) == (10_000, 10_000, 0), "one microsecond before creation: no hold"
    assert view(ada, c) == (10_000, 9_000, 1_000), "a hold starts at its creation, inclusive"
    assert view(ada) == (10_000, 9_000, 1_000), "without as_of: the read's instant"
    assert view(ada, None, shifted(c, -1)) == (10_000, 10_000, 0), "I60: a hold created after known_at holds nothing"
    assert view(ada, None, c) == (10_000, 9_000, 1_000)
    assert view(ada, FAR_FUTURE) == (10_000, 10_000, 0), "beyond its deadline an open hold holds nothing (T64)"
    assert view(ada, shifted(a["expires_at"], -1)) == (10_000, 9_000, 1_000), "a future as_of before the deadline"
    assert view(ada, a["expires_at"]) == (10_000, 10_000, 0), "expiry takes effect at expires_at"
    assert view(world.bob, c) == (2_500, 2_500, 0), "the receiver holds nothing"
    conserved(world.svc, c)


def test_a_nonfinal_capture_reduces_the_hold_at_its_time(world):
    a = expect(world.ada.authorize("bob", 1_000), 201)
    p = expect(world.bob.capture(a["authorization_id"], {"amount": 300, "final": False}), 201)
    x = p["created_at"]
    ada = world.ada
    after = check_authorization(ada.auth(a["authorization_id"]), status="open", captured_amount=300,
                                remaining_amount=700)
    assert after["closed_at"] is None, "I61: null while open, also after a nonfinal capture"
    assert view(ada, shifted(x, -1)) == (10_000, 9_000, 1_000)
    assert view(ada, x) == (9_700, 9_000, 700), "the capture moves money and reduces the hold at its time"
    assert view(world.bob, shifted(x, -1)) == (2_500, 2_500, 0) and view(world.bob, x) == (2_800, 2_800, 0)
    assert view(ada, None, shifted(x, -1)) == (10_000, 9_000, 1_000), "a capture recorded after known_at is unknown"
    assert view(ada, None, x) == (9_700, 9_000, 700)
    conserved(world.svc, x)
    conserved(world.svc, None, shifted(x, -1))
    now = ada.money()
    assert view(ada, x) == now and view(ada, None, FAR_FUTURE) == now, \
        "I67: the present view of an API hold after a nonfinal capture agrees with GET /me"


@pytest.mark.parametrize("body", [{"amount": 400}, {"amount": 400, "final": True}, {}, {"amount": 1_000},
                                  {"amount": 1_000, "final": False}])
def test_a_closing_capture_releases_the_remainder_at_its_time(world, body):
    """A final capture, or a capture of the whole remainder (even with final false), closes the hold;
    closed_at is that write's one timestamp, the capture payment's created_at (D67, D71)."""
    a = expect(world.ada.authorize("bob", 1_000), 201)
    p = expect(world.bob.capture(a["authorization_id"], body), 201)
    x, amt = p["created_at"], p["amount"]
    got = check_authorization(world.ada.auth(a["authorization_id"]), status="captured", remaining_amount=0)
    assert got["closed_at"] == x, f"I61: closed_at is the capture's issued time: {got['closed_at']} != {x}"
    ada = world.ada
    assert view(ada, shifted(x, -1)) == (10_000, 9_000, 1_000)
    assert view(ada, x) == (10_000 - amt, 10_000 - amt, 0)
    assert view(ada, FAR_FUTURE) == (10_000 - amt, 10_000 - amt, 0)
    assert view(ada, None, shifted(x, -1)) == (10_000, 9_000, 1_000)


def test_two_nonfinal_captures_then_a_void(world):
    a = expect(world.ada.authorize("bob", 1_000), 201)
    aid = a["authorization_id"]
    p1 = expect(world.bob.capture(aid, {"amount": 100, "final": False}), 201)
    p2 = expect(world.bob.capture(aid, {"amount": 250, "final": False}), 201)
    v = check_authorization(expect(world.ada.void(aid), 200), status="voided", captured_amount=350, remaining_amount=0)
    x = v["closed_at"]
    assert PLAN_TS.match(x) and instant(p2["created_at"]) < instant(x), f"I61: the void's issued time: {v}"
    again = expect(world.ada.void(aid), 200)
    assert again["closed_at"] == x, "voiding again returns the current state, the same closed_at"
    assert world.ada.auth(aid)["closed_at"] == world.bob.auth(aid)["closed_at"] == x
    ada = world.ada
    assert view(ada, a["created_at"]) == (10_000, 9_000, 1_000)
    assert view(ada, p1["created_at"]) == (9_900, 9_000, 900)
    assert view(ada, p2["created_at"]) == (9_650, 9_000, 650)
    assert view(ada, shifted(x, -1)) == (9_650, 9_000, 650)
    assert view(ada, x) == (9_650, 9_650, 0), "a void releases the remainder at its time"
    assert view(ada, FAR_FUTURE, shifted(x, -1)) == (9_650, 9_650, 0), \
        "known before the void, a future as_of passes the deadline: the hold expired at its deadline"
    assert view(ada, shifted(a["expires_at"], -1), shifted(x, -1)) == (9_650, 9_000, 650), \
        "the void is unknown before its time, so the hold still counts before the deadline"
    assert view(ada, None, shifted(p2["created_at"], -1)) == (9_900, 9_000, 900)
    for t in (a["created_at"], p1["created_at"], p2["created_at"], x):
        conserved(world.svc, t)
        conserved(world.svc, None, t)


def test_closed_at_in_every_representation(world):
    a = check_authorization(expect(world.ada.authorize("bob", 500, key=(k := new_key())), 201), closed_at=None)
    aid = a["authorization_id"]
    for c in (world.ada, world.bob):
        check_authorization(c.auth(aid), closed_at=None)
    v = check_authorization(expect(world.ada.void(aid), 200), status="voided")
    assert v["closed_at"] is not None
    for c in (world.ada, world.bob):
        assert check_authorization(c.auth(aid))["closed_at"] == v["closed_at"]
    for params in ({"status": "voided"}, {"direction": "outgoing"}, {"direction": "incoming"}):
        items = world.ada.auths(**params) + world.bob.auths(**params)
        for x in items:
            check_authorization(x)
    replay = expect(world.ada.authorize("bob", 500, key=k), 200)
    assert replay == a, "D54: a replay returns the stored original body (open, closed_at null)"


def test_expiry_by_the_clock_closes_at_expires_at(svc):
    svc.must_reset(fixture(standard_users(), ttl=1))
    ada = svc.client("ada")
    a = expect(ada.authorize("bob", 700), 201)
    aid, e = a["authorization_id"], a["expires_at"]
    deadline = time.monotonic() + 10
    while ada.auth(aid)["status"] == "open":
        assert time.monotonic() < deadline, "the hold never expired"
        time.sleep(0.2)
    got = check_authorization(ada.auth(aid), status="expired", remaining_amount=0)
    assert got["closed_at"] == e, f"I61: a clock expiry closes at expires_at, exactly as stored: {got}"
    assert view(ada, shifted(e, -1)) == (10_000, 9_300, 700)
    assert view(ada, e) == (10_000, 10_000, 0)
    assert view(ada, shifted(a["created_at"], -1)) == (10_000, 10_000, 0)
    assert view(ada) == (10_000, 10_000, 0)
    assert view(ada, shifted(e, -1), a["created_at"]) == (10_000, 9_300, 700), \
        "once creation is known, the deadline is known: known_at at creation, as_of before the deadline"
    assert view(ada, e, a["created_at"]) == (10_000, 10_000, 0)


# ---------------------------------------------------------------- seeded holds

def seeded(aid, frm, to, amount, expires_at, **extra) -> dict:
    return {"id": aid, "from_user_id": f"u_{frm}", "to_user_id": f"u_{to}", "amount": amount,
            "expires_at": expires_at, **extra}


@pytest.fixture
def seeded_world(svc):
    """Seeded holds from ada: open (from the reset), open with its own created_at, and one of each
    closed status. The deadlines are two hours after a service time mark."""
    svc.must_reset(fixture(standard_users()))
    now = svc.client("ada").service_now("bob")
    far = shifted(now, seconds=7200, digits=3)
    past = shifted(now, seconds=-7200, digits=3)
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded("a_open", "ada", "bob", 1_000, far),
        seeded("a_dated", "ada", "cy", 300, far, created_at="2026-03-01T00:00:00.5+01:00"),
        seeded("a_cap", "ada", "bob", 200, far, status="captured", captured_amount=150, payment_id="p_x"),
        seeded("a_void", "ada", "bob", 400, far, status="voided"),
        seeded("a_exp", "ada", "bob", 500, past, status="expired"),
        seeded("a_late", "ada", "dee", 600, past),          # open, but its deadline passed before the reset
        seeded("a_void_dated", "ada", "bob", 70, far, status="voided", created_at="2026-03-01T00:00:00.25-02:00"),
    ]))
    ada = svc.client("ada")
    reset_at = ada.auth("a_open")["created_at"]
    assert PLAN_TS.match(reset_at), "an omitted created_at is the reset's timestamp"
    return svc, reset_at, far, past


def test_seeded_closed_holds_hold_nothing_and_close_at_the_reset(seeded_world):
    svc, r, far, past = seeded_world
    ada = svc.client("ada")
    for aid in ("a_cap", "a_void", "a_exp"):
        got = check_authorization(ada.auth(aid))
        assert got["created_at"] == r
        assert got["closed_at"] == r, f"I61, D85: a seeded closed hold closes at its own created_at: {got}"
    dated = check_authorization(ada.auth("a_void_dated"), status="voided")
    assert dated["created_at"] == dated["closed_at"] == "2026-03-01T00:00:00.25-02:00", \
        f"I61, D85: a seeded closed hold with a supplied created_at closes at it, exactly as written: {dated}"
    late = check_authorization(ada.auth("a_late"), status="expired")
    assert late["closed_at"] == past, f"I61: a seeded open hold already past its deadline closes at expires_at: {late}"
    dated = instant("2026-03-01T00:00:00.5+01:00")
    for t in (EPOCH, past, "2026-03-01T00:00:00Z", shifted(r, -1), r, shifted(far, -1), far, FAR_FUTURE):
        want = (300 if dated <= instant(t) < instant(far) else 0) + \
            (1_000 if instant(r) <= instant(t) < instant(far) else 0)
        assert view(ada, t) == (10_000, 10_000 - want, want), f"only the two open holds count, at {t}"


def test_seeded_open_holds_count_from_their_creation(seeded_world):
    svc, r, far, _ = seeded_world
    ada = svc.client("ada")
    dated = check_authorization(ada.auth("a_dated"), status="open")
    assert dated["created_at"] == "2026-03-01T00:00:00.5+01:00", "D68: a seeded created_at, exactly as written"
    d = "2026-02-28T23:00:00.5Z"    # the same instant in UTC
    assert view(ada, EPOCH) == (10_000, 10_000, 0)
    assert view(ada, shifted(d, -1)) == (10_000, 10_000, 0)
    assert view(ada, d) == (10_000, 9_700, 300), "a seeded open hold counts from its supplied created_at"
    assert view(ada, "2026-03-01T00:00:00.5+01:00") == (10_000, 9_700, 300)
    assert view(ada, shifted(r, -1)) == (10_000, 9_700, 300), "a_open counts only from the reset"
    assert view(ada, r) == (10_000, 8_700, 1_300)
    assert view(ada) == (10_000, 8_700, 1_300)
    assert view(ada, shifted(far, -1)) == (10_000, 8_700, 1_300)
    assert view(ada, far) == (10_000, 10_000, 0), "both open holds expire at their deadline"
    assert view(ada, None, shifted(d, -1)) == (10_000, 10_000, 0), "known_at before creation: nothing held"
    assert view(ada, None, shifted(r, -1)) == (10_000, 9_700, 300)
    assert view(ada, FAR_FUTURE, shifted(r, -1)) == (10_000, 10_000, 0)


def test_capturing_and_voiding_seeded_holds_have_history(seeded_world):
    svc, r, far, _ = seeded_world
    ada, bob, cy = svc.client("ada"), svc.client("bob"), svc.client("cy")
    p = expect(bob.capture("a_open", {"amount": 250, "final": False}), 201)
    v = expect(ada.void("a_dated"), 200)
    assert v["closed_at"] is not None and instant(v["closed_at"]) > instant(p["created_at"])
    assert view(ada, shifted(p["created_at"], -1)) == (10_000, 8_700, 1_300)
    assert view(ada, p["created_at"]) == (9_750, 8_700, 1_050)
    assert view(ada, v["closed_at"]) == (9_750, 9_000, 750)
    assert view(ada) == (9_750, 9_000, 750)
    assert view(cy, v["closed_at"]) == (500, 500, 0)
    assert view(bob, p["created_at"]) == (2_750, 2_750, 0)
    for t in (EPOCH, "2026-03-01T00:00:00Z", r, p["created_at"], v["closed_at"], far):
        conserved(svc, t)


def test_a_seeded_closed_capture_is_not_a_payment(seeded_world):
    """Seeded links are display-only: a_cap's payment_id names no payment and nothing moved."""
    svc, r, _, _ = seeded_world
    ada = svc.client("ada")
    assert ada.feed() == []
    assert view(ada, r) == (10_000, 8_700, 1_300)


def test_stage_2_replay_bodies_keep_their_shape(world):
    """PLAN 3.6: the authorization fields are stage 2's plus closed_at; a replay is the stored body."""
    k = new_key()
    a = expect(world.ada.authorize("bob", 100, key=k), 201)
    assert set(a) == STAGE2_AUTHZ_KEYS | {"closed_at"}
    expect(world.bob.capture(a["authorization_id"]), 201)
    assert expect(world.ada.authorize("bob", 100, key=k), 200) == a


def test_a_seeded_partly_captured_hold_and_display_only_links(svc):
    """D84: a seeded captured_amount counts from the hold's creation; a seeded payment naming the hold and
    the hold's seeded payment_ids change nothing. I67: the present view agrees with GET /me."""
    svc.must_reset(fixture(standard_users()))
    far = shifted(svc.client("ada").service_now("bob"), seconds=7200, digits=3)
    svc.must_reset(fixture(standard_users(), payments=[
        seeded_payment("p_link", "ada", "bob", 50, "2026-03-02T00:00:00Z", authorization_id="a_part")],
        authorizations=[seeded("a_part", "ada", "bob", 1_000, far, created_at="2026-03-01T00:00:00Z",
                               captured_amount=400, payment_id="p_link", payment_ids=["p_link"])]))
    ada = svc.client("ada")
    check_authorization(ada.auth("a_part"), status="open", captured_amount=400, remaining_amount=600, closed_at=None)
    assert view(ada, "2026-02-28T23:59:59.999999Z") == (10_050, 10_050, 0)
    assert view(ada, "2026-03-01T00:00:00Z") == (10_050, 9_450, 600), "the base captured amount counts from creation"
    assert view(ada, "2026-03-01T23:59:59.999999Z") == (10_050, 9_450, 600)
    assert view(ada, "2026-03-02T00:00:00Z") == (10_000, 9_400, 600), "a display-only link reduces no hold"
    now = ada.money()
    assert now == (10_000, 9_400, 600)
    assert view(ada, "2026-03-02T00:00:00Z") == now and view(ada, None, FAR_FUTURE) == now and \
        view(ada, shifted(far, -1)) == now, "I67: the present view agrees with GET /me"
    p = expect(svc.client("bob").capture("a_part", {"amount": 100, "final": False}), 201)
    assert view(ada, shifted(p["created_at"], -1)) == (10_000, 9_400, 600)
    assert view(ada, p["created_at"]) == (9_900, 9_400, 500)
    assert view(ada, p["created_at"]) == ada.money()


def test_microsecond_boundaries_of_a_seeded_hold(svc):
    """W14.6 (critic B1): absent 1 microsecond before creation, counted at it; counted 1 microsecond before
    the deadline, released at it."""
    svc.must_reset(fixture(standard_users()))
    deadline = shifted(svc.client("ada").service_now("bob"), 321, seconds=7200)
    created = "2026-03-01T10:00:00.123456Z"
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded("a_us", "ada", "bob", 700, deadline, created_at=created)]))
    ada = svc.client("ada")
    assert ada.auth("a_us")["expires_at"] == deadline
    assert view(ada, shifted(created, -1)) == (10_000, 10_000, 0)
    assert view(ada, created) == (10_000, 9_300, 700)
    assert view(ada, shifted(deadline, -1)) == (10_000, 9_300, 700)
    assert view(ada, deadline) == (10_000, 10_000, 0)
    assert view(ada, fmt_instant(deadline, digits=9, offset="+05:30")) == (10_000, 10_000, 0)


def test_a_clock_expired_seeded_hold_closes_at_its_deadline_exactly_as_written(svc):
    """I61 (critic V03): closed_at is expires_at exactly as stored, also in a form the service never issues."""
    deadline = "2020-06-15T10:20:30.123456+05:30"
    svc.must_reset(fixture(standard_users(), authorizations=[seeded("a_old", "ada", "bob", 300, deadline)]))
    ada = svc.client("ada")
    a = check_authorization(ada.auth("a_old"), status="expired", remaining_amount=0)
    assert a["expires_at"] == a["closed_at"] == deadline, f"I61: {a}"
    assert view(ada, deadline) == (10_000, 10_000, 0) and view(ada) == (10_000, 10_000, 0)
