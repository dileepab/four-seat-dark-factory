"""W14.1, W14.3, W14.4, W14.5 — seeded instants, opening balances, `as_of` and `known_at` on
`GET /me` (stage-3 "Payment timestamps", "`GET /me` as of an instant", "Effective time, recorded
time, and corrections"; PLAN 3.4, 3.5, 3.7, 3.10, D66-D70). I1, I29, I50-I52, I59.

The HISTORY fixture is consistent (D69): replayed from the opening balances in time order, no wallet
goes below zero. Its seeded instants use several offsets and precisions; ORDER is its feed order.
"""
from __future__ import annotations

import pytest

from support import (EPOCH, FAR_FUTURE, PLAN_TS, check_payment, expect, expect_error, fixture, fmt_instant,
                     instant, new_key, shifted, standard_users, user)
from test_w14_instants import INVALID

pytestmark = pytest.mark.item(14)


def seeded(pid: str, frm: str, to: str, amount: int, created_at: str | None = None, **extra) -> dict:
    p = {"id": pid, "from_user_id": f"u_{frm}", "to_user_id": f"u_{to}", "amount": amount, **extra}
    if created_at is not None:
        p["created_at"] = created_at
    return p


# Opening balances (I51): ada 9500, bob 3400, cy 100, dee 0.
HISTORY = [
    seeded("p_1", "bob", "ada", 1_000, "2026-03-01T09:00:00Z"),
    seeded("p_2", "ada", "cy", 300, "2026-03-01T12:00:00.000001Z"),
    seeded("p_3", "cy", "dee", 0, "2026-03-02T00:00:00+05:30"),           # 2026-03-01T18:30Z
    seeded("p_5", "bob", "cy", 100, "2026-03-01T20:00:00Z", visibility="private"),
    seeded("p_8", "dee", "cy", 0, "2026-03-01T21:00:00.0000000001Z"),     # 0.1 ns after p_6 and p_7
    seeded("p_6", "dee", "cy", 0, "2026-03-01T21:00:00Z"),
    seeded("p_7", "cy", "dee", 0, "2026-03-02T02:30:00+05:30"),           # the same instant as p_6
    seeded("p_4", "ada", "bob", 200),                                     # the reset's timestamp
]
OPENING = {"ada": 9_500, "bob": 3_400, "cy": 100, "dee": 0}
# Newest first by instant, ties later-created first (I29).
ORDER = ["p_4", "p_8", "p_7", "p_6", "p_5", "p_3", "p_2", "p_1"]


@pytest.fixture
def hist(svc):
    svc.must_reset(fixture(standard_users(), payments=HISTORY))
    assert svc.consistent, "precondition: HISTORY is a consistent seeded history"
    return svc


def feed_ids(c) -> list[str]:
    return [p["payment_id"] for p in c.feed()]


def reset_time(svc) -> str:
    """The reset's timestamp, read from the seeded payment that omitted created_at."""
    return [p for p in svc.client("ada").feed() if p["payment_id"] == "p_4"][0]["created_at"]


# ---------------------------------------------------------------- W14.1 seeded created_at

def test_seeded_created_at_comes_back_exactly_as_written(hist):
    feed = {p["payment_id"]: p for p in hist.client("bob").feed()}
    for s in HISTORY:
        if "created_at" in s and s.get("visibility") != "private":
            assert feed[s["id"]]["created_at"] == s["created_at"], \
                f"I50: a seeded created_at is returned exactly as written: {feed[s['id']]}"
    assert feed["p_5"]["created_at"] == "2026-03-01T20:00:00Z"   # bob's own private payment
    r = feed["p_4"]["created_at"]
    assert PLAN_TS.match(r), f"an omitted created_at is the reset's timestamp, in the service's form: {r}"


def test_activity_is_newest_first_by_instant_with_ties_later_created_first(hist):
    """I29 (amended), W14.1: compared as instants, not as strings; exact beyond microseconds."""
    assert feed_ids(hist.client("cy")) == ORDER
    assert feed_ids(hist.client("ada")) == [i for i in ORDER if i != "p_5"]    # p_5 is private


def test_api_payments_sort_above_seeded_ones_and_reset_time_is_earlier(hist):
    ada = hist.client("ada")
    r = reset_time(hist)
    p = check_payment(expect(ada.pay("bob", 1), 201))
    assert instant(r) < instant(p["created_at"]), "I50: the reset's timestamp is earlier than the first API payment"
    assert feed_ids(hist.client("cy"))[:2] == [p["payment_id"], "p_4"]


def test_the_first_authorization_after_a_reset_is_later_than_the_reset(hist):
    """I50, W14.1 (revised): strictly later, for the first authorization as for the first payment."""
    a = expect(hist.client("ada").authorize("bob", 5), 201)
    assert instant(reset_time(hist)) < instant(a["created_at"])


# Seeds whose string order disagrees with their instant order (W14.1, W15.1, critic B5):
# +05:30 against Z, ...:00Z against ...:00.000001Z, and a lowercase t.
DISAGREE = [("q_1", "2026-04-01T10:00:00+05:30"),       # 04:30Z
            ("q_2", "2026-04-01T05:00:00Z"),
            ("q_3", "2026-04-01T06:00:00.000001Z"),
            ("q_4", "2026-04-01T06:00:00Z"),
            ("q_5", "2026-04-01t05:30:00Z")]
DISAGREE_NEWEST_FIRST = ["q_3", "q_4", "q_5", "q_2", "q_1"]


def disagree_fixture(svc) -> dict:
    svc.must_reset(fixture(standard_users()))
    far = shifted(svc.client("ada").service_now("bob"), seconds=7200, digits=3)
    return fixture(standard_users(), payments=[seeded(i, "dee", "cy", 0, at) for i, at in DISAGREE],
                   authorizations=[{"id": "a" + i, "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
                                    "expires_at": far, "created_at": at} for i, at in DISAGREE])


def test_feed_and_authorizations_order_by_instant_not_by_string(svc):
    svc.must_reset(disagree_fixture(svc))
    assert feed_ids(svc.client("dee")) == DISAGREE_NEWEST_FIRST
    assert [a["authorization_id"] for a in svc.client("bob").auths()] == ["a" + i for i in DISAGREE_NEWEST_FIRST]
    for a in svc.client("ada").auths():
        assert a["created_at"] == dict(DISAGREE)[a["authorization_id"][1:]], "a seeded created_at, exactly as written"


def test_two_payments_in_a_row_have_strictly_increasing_created_at(world):
    """D67: every write issues a timestamp strictly later than the previous one."""
    stamps = []
    for i in range(20):
        p = expect(world.ada.pay("bob", 1), 201)
        assert PLAN_TS.match(p["created_at"]), p
        stamps.append(instant(p["created_at"]))
    assert all(a < b for a, b in zip(stamps, stamps[1:])), f"created_at must strictly increase: {stamps}"


@pytest.mark.parametrize("value", INVALID.values(), ids=INVALID.keys())
def test_an_invalid_seeded_created_at_is_422_and_changes_nothing(world, value):
    svc = world.svc
    expect(world.ada.pay("bob", 7), 201)
    before = world.ada.feed()
    fx = fixture(standard_users(), payments=[seeded("p_x", "ada", "bob", 5, value)])
    expect_error(svc.reset(fx), 422, "validation_failed")
    assert world.ada.feed() == before and world.ada.money() == (9_993, 9_993, 0)


@pytest.mark.parametrize("bad", [5, True, ["2026-01-01T00:00:00Z"], {"at": "x"}])
def test_a_non_string_seeded_created_at_is_422(world, bad):
    fx = fixture(standard_users(), payments=[{**seeded("p_x", "ada", "bob", 5), "created_at": bad}])
    expect_error(world.svc.reset(fx), 422, "validation_failed")
    assert world.ada.money() == (10_000, 10_000, 0)


@pytest.mark.parametrize("ahead", [3600, 10])
def test_a_seeded_created_at_in_the_future_is_422_and_changes_nothing(world, ahead):
    """T6, D68: later than the reset's own timestamp. The future is measured from a service time mark."""
    svc = world.svc
    now = world.ada.service_now("bob")
    expect(world.ada.pay("bob", 7), 201)
    before = (world.ada.feed(), world.bob.requests())
    future = shifted(now, seconds=ahead, digits=3)
    for item in ("payments", "authorizations"):
        if item == "payments":
            fx = fixture(standard_users(), payments=[seeded("p_x", "ada", "bob", 5, future)])
        else:
            fx = fixture(standard_users(), authorizations=[
                {"id": "a_x", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
                 "expires_at": shifted(now, seconds=7200, digits=3), "created_at": future}])
        expect_error(svc.reset(fx), 422, "validation_failed")
        assert (world.ada.feed(), world.bob.requests()) == before, f"a rejected reset ({item}) changed the state"
        assert world.ada.money() == (9_993, 9_993, 0)
    # The control: the same records dated at the time mark (in the past) are accepted.
    svc.must_reset(fixture(standard_users(), payments=[seeded("p_x", "ada", "bob", 5, now)], authorizations=[
        {"id": "a_x", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
         "expires_at": shifted(now, seconds=7200, digits=3), "created_at": now}]))
    assert svc.client("ada").auth("a_x")["created_at"] == now


def test_a_seeded_created_at_just_before_the_reset_is_accepted(svc):
    """D68: at or before the reset's own timestamp is fine; one in the past by a second is accepted."""
    svc.must_reset(fixture(standard_users()))
    now = svc.client("ada").service_now("bob")
    svc.must_reset(fixture(standard_users(), payments=[seeded("p_x", "ada", "bob", 5, now)]))
    assert [p["created_at"] for p in svc.client("ada").feed()] == [now]


# ---------------------------------------------------------------- W14.3 opening balances

def test_a_fixture_balance_is_the_current_total_after_reset(hist):
    """T7: loading seeded payments changes no balance."""
    for h, u in zip(("ada", "bob", "cy", "dee"), standard_users()):
        assert hist.client(h).money() == (u["balance"], u["balance"], 0)


@pytest.mark.parametrize("as_of", [EPOCH, "2026-03-01T08:59:59.999999999Z", "2026-03-01T13:59:59.999999999+05:00"])
def test_as_of_before_every_payment_is_the_opening_balance(hist, as_of):
    """I51: the seeded balance minus the net of the user's seeded payments."""
    for h, opening in OPENING.items():
        m = hist.client(h).me_at(as_of)
        assert (m["total"], m["held"]) == (opening, 0), f"{h} at {as_of}: {m}"


def test_a_signup_opens_at_zero(world):
    svc = world.svc
    expect(svc.signup("zoe@example.com", "pw-zoe-Correct-Horse-9", "Zoe"), 201)
    handle = [h for h, a in svc.accounts.items() if a.email == "zoe@example.com"][0]
    zoe = svc.client(handle)
    assert zoe.me_at(EPOCH)["total"] == 0
    p = expect(world.ada.pay(handle, 50), 201)
    assert zoe.me_at(shifted(p["created_at"], -1))["total"] == 0
    assert zoe.me_at(p["created_at"])["total"] == 50
    assert zoe.me_at(EPOCH)["total"] == 0, "I51: corrections or payments never change an opening balance"


# ---------------------------------------------------------------- W14.4 as_of

@pytest.mark.parametrize("as_of, ada, cy", [
    ("2026-03-01T09:00:00Z", 10_500, 100),                    # p_1 at exactly as_of counts
    ("2026-03-01T08:59:59.999999Z", 9_500, 100),               # one microsecond earlier
    ("2026-03-01T12:00:00Z", 10_500, 100),                    # p_2 is one microsecond later
    ("2026-03-01T12:00:00.0000009Z", 10_500, 100),            # 0.9 microseconds: still before p_2
    ("2026-03-01T12:00:00.000001Z", 10_200, 400),             # exactly p_2
    ("2026-03-01T12:00:00.000001000000Z", 10_200, 400),       # the same instant, more digits
    ("2026-03-01T17:30:00.000001+05:30", 10_200, 400),        # the same instant, another offset
    ("2026-03-01t07:00:00.000001-05:00", 10_200, 400),
    ("2026-03-01T20:00:00Z", 10_200, 500),                    # p_5
    ("2026-03-01T19:59:59.999999999Z", 10_200, 400),
])
def test_as_of_is_inclusive_and_exact(hist, as_of, ada, cy):
    assert hist.client("ada").me_at(as_of)["total"] == ada
    assert hist.client("cy").me_at(as_of)["total"] == cy


def test_as_of_at_the_reset_time_and_after_is_current(hist):
    r = reset_time(hist)
    ada = hist.client("ada")
    assert ada.me_at(r)["total"] == 10_000, "p_4 at exactly the reset's timestamp counts"
    assert ada.me_at(shifted(r, -1))["total"] == 10_200, "one microsecond before the reset's timestamp"
    assert ada.me_at(FAR_FUTURE)["total"] == 10_000
    assert hist.client("bob").me_at(shifted(r, -1))["total"] == 2_300


def test_as_of_at_an_api_payment_in_every_form(world):
    """I52 with the service's own created_at: inclusive; one microsecond earlier excludes it (W18.5)."""
    p = expect(world.ada.pay("bob", 250), 201)
    c = p["created_at"]
    for same in (c, fmt_instant(c, digits=3, offset="Z"), fmt_instant(c, digits=9, offset="+05:30"),
                 fmt_instant(c, digits=6, offset="-11:15", t="t"), fmt_instant(c, digits=3, offset="z")):
        assert world.ada.me_at(same)["total"] == 9_750, f"as_of {same} is the payment's instant"
        assert world.bob.me_at(same)["total"] == 2_750
    for before in (shifted(c, -1), shifted(c, -1, digits=9, offset="+14:00"), shifted(c, -1, digits=7)):
        assert world.ada.me_at(before)["total"] == 10_000, f"as_of {before} is before the payment"
        assert world.bob.me_at(before)["total"] == 2_500


def test_as_of_between_api_payments(world):
    ps = [expect(world.ada.pay("bob", amt), 201) for amt in (100, 200, 400)]
    totals = [world.ada.me_at(p["created_at"])["total"] for p in ps]
    assert totals == [9_900, 9_700, 9_300]
    assert world.ada.me_at(shifted(ps[2]["created_at"], -1))["total"] == 9_700


def test_without_parameters_the_current_values(hist):
    expect(hist.client("ada").pay("dee", 1_000), 201)
    m = hist.client("ada").me()
    assert (m["total"], m["available"], m["held"]) == (9_000, 9_000, 0)


def test_conservation_in_every_view(hist):
    """I1 (amended): the totals sum to the seeded total at every as_of and known_at."""
    total = sum(u["balance"] for u in standard_users())
    expect(hist.client("ada").pay("dee", 100), 201)
    instants = [EPOCH, "2026-03-01T09:00:00Z", "2026-03-01T12:00:00.0000009Z", "2026-03-01T18:30:00Z",
                reset_time(hist), FAR_FUTURE]
    for t in instants:
        for view in ({"as_of": t}, {"known_at": t}, {"as_of": t, "known_at": "2026-03-01T12:00:00Z"}):
            s = sum(hist.client(h).me_at(**view)["total"] for h in OPENING)
            assert s == total, f"I1 in the view {view}: {s} != {total}"


# ---------------------------------------------------------------- W14.5 known_at

def test_known_at_hides_payments_recorded_after_it(hist):
    """I59: a seeded payment is recorded at its created_at; nothing recorded yet contributes nothing."""
    ada, bob = hist.client("ada"), hist.client("bob")
    assert ada.me_at(None, "2026-03-01T08:00:00Z")["total"] == 9_500
    assert ada.me_at(None, "2026-03-01T09:00:00Z")["total"] == 10_500, "recorded at exactly known_at counts"
    assert ada.me_at(None, "2026-03-01T08:59:59.999999999Z")["total"] == 9_500
    assert bob.me_at(None, "2026-03-01T20:00:00Z")["total"] == 2_300
    assert ada.me_at(None, FAR_FUTURE)["total"] == 10_000, "a known_at in the future means everything"


def test_known_at_with_api_payments(world):
    p1 = expect(world.ada.pay("bob", 100), 201)
    p2 = expect(world.ada.pay("bob", 200), 201)
    ada = world.ada
    assert ada.me_at(None, shifted(p1["created_at"], -1))["total"] == 10_000
    assert ada.me_at(None, p1["created_at"])["total"] == 9_900
    assert ada.me_at(None, shifted(p2["created_at"], -1))["total"] == 9_900
    assert ada.me_at(None, p2["created_at"])["total"] == 9_700
    m = ada.me_at(FAR_FUTURE, p1["created_at"])
    assert m["total"] == 9_900 and m["as_of"] == FAR_FUTURE and m["known_at"] == p1["created_at"]


def test_as_of_and_known_at_together(hist):
    """Effective times decide after the revision selection (I59)."""
    ada = hist.client("ada")
    # Known at 13:00Z: p_1 and p_2 are known. As of 10:00Z only p_1 has taken effect.
    assert ada.me_at("2026-03-01T10:00:00Z", "2026-03-01T13:00:00Z")["total"] == 10_500
    assert ada.me_at("2026-03-01T13:00:00Z", "2026-03-01T13:00:00Z")["total"] == 10_200
    # Known at 10:00Z: p_2 is unknown even as of later instants.
    assert ada.me_at(FAR_FUTURE, "2026-03-01T10:00:00Z")["total"] == 10_500
    assert ada.me_at(EPOCH, FAR_FUTURE)["total"] == 9_500


def test_history_reads_change_nothing(hist):
    before = [hist.client(h).me() for h in OPENING], hist.client("cy").feed()
    for t in (EPOCH, "2026-03-01T12:00:00Z", FAR_FUTURE):
        for h in OPENING:
            hist.client(h).me_at(t, t)
    assert ([hist.client(h).me() for h in OPENING], hist.client("cy").feed()) == before


def test_history_of_request_payments_and_settlements(world):
    """W14.2 through as_of: request payments and settlement members take effect at their created_at."""
    svc = world.svc
    rq = expect(world.bob.ask("ada", 300), 201)
    paid = expect(world.ada.pay_request(rq["request_id"]), 201)
    st = expect(world.ada.settle([{"from_handle": "bob", "to_handle": "cy", "amount": 50},
                                  {"from_handle": "cy", "to_handle": "dee", "amount": 20}]), 201)
    t = st["committed_at"]
    assert all(p["created_at"] == t for p in st["payments"])
    assert world.ada.me_at(shifted(paid["created_at"], -1))["total"] == 10_000
    assert world.ada.me_at(paid["created_at"])["total"] == 9_700
    assert world.bob.me_at(shifted(t, -1))["total"] == 2_800
    assert world.bob.me_at(t)["total"] == 2_750
    assert world.cy.me_at(t)["total"] == 530 and world.dee.me_at(t)["total"] == 20
    assert world.dee.me_at(shifted(t, -1))["total"] == 0
    assert svc.total == sum(svc.client(h).me_at(t)["total"] for h in ("ada", "bob", "cy", "dee"))


def test_a_new_users_opening_balance_with_seeded_payments_elsewhere(svc):
    """I51 for a user with no seeded payments: the opening balance is the fixture balance."""
    svc.must_reset(fixture([user("ada", 500), user("bob", 0), user("cy", 70)],
                           payments=[seeded("p_1", "ada", "bob", 0, "2026-01-01T00:00:00Z")]))
    assert svc.client("cy").me_at(EPOCH)["total"] == 70
    assert svc.client("ada").me_at(EPOCH)["total"] == 500
    key = new_key()
    expect(svc.client("ada").pay("cy", 30, key=key), 201)
    assert svc.client("cy").me_at(EPOCH)["total"] == 70


def test_trailing_fraction_zeros_do_not_change_an_instant(svc):
    """3.4, D66 (critic G16): .500Z and .5+05:30 seeds are one instant, so the feed puts the later-created
    first, as_of at .5Z counts both, and 1e-7 s earlier counts neither."""
    svc.must_reset(fixture(standard_users(), payments=[
        seeded("p_first", "cy", "dee", 10, "2026-01-01T00:00:00.500Z"),
        seeded("p_second", "cy", "dee", 20, "2026-01-01T05:30:00.5+05:30")]))
    assert feed_ids(svc.client("cy")) == ["p_second", "p_first"]
    cy = svc.client("cy")
    assert cy.me_at("2026-01-01T00:00:00.5Z")["total"] == 500
    assert cy.me_at("2026-01-01T00:00:00.5000000000Z")["total"] == 500
    assert cy.me_at("2026-01-01T00:00:00.4999999Z")["total"] == 530
    assert cy.me_at(None, "2026-01-01T00:00:00.50Z")["total"] == 500
