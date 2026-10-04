"""W1.4 — reset and seed (§3.3, §4 fixture; PLAN 3.11, D15, D21). Invariants I25, I28, I29."""
from __future__ import annotations

import copy
import time

import httpx
import pytest

from support import (TWO_53, check_me, check_payment, check_request, expect, expect_error,
                     fixture, new_key, standard_users, user, PLAN_TS)

pytestmark = pytest.mark.item(1)


def base_fixture() -> dict:
    fx = fixture(standard_users(), operators=["u_ada"],
                 payments=[{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob",
                            "amount": 500, "note": "coffee", "visibility": "public"}],
                 requests=[{"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada",
                            "amount": 1200, "note": "taxi", "status": "pending"}])
    return fx


def _u(fx, i):
    return fx["users"][i]


INVALID = {
    "negative balance (spec)": lambda fx: _u(fx, 1).update(balance=-1),
    "currency missing": lambda fx: fx.pop("currency"),
    "currency lowercase": lambda fx: fx.update(currency="eur"),
    "currency four letters": lambda fx: fx.update(currency="EURO"),
    "currency number": lambda fx: fx.update(currency=978),
    "minor_units 1": lambda fx: fx.update(minor_units=1),
    "minor_units 4": lambda fx: fx.update(minor_units=4),
    "minor_units string": lambda fx: fx.update(minor_units="2"),
    "minor_units fraction": lambda fx: fx.update(minor_units=2.5),
    "minor_units missing": lambda fx: fx.pop("minor_units"),
    "users missing": lambda fx: fx.pop("users"),
    "users not array": lambda fx: fx.update(users="ada"),
    "user not object": lambda fx: fx["users"].append(5),
    "user id missing": lambda fx: _u(fx, 0).pop("id"),
    "user id empty": lambda fx: _u(fx, 3).update(id=""),
    "user id 65 chars": lambda fx: _u(fx, 3).update(id="u" * 65),
    "user id number": lambda fx: _u(fx, 3).update(id=7),
    "duplicate user id": lambda fx: _u(fx, 3).update(id="u_cy"),
    "duplicate email": lambda fx: _u(fx, 3).update(email="cy@example.com"),
    "duplicate email other case": lambda fx: _u(fx, 3).update(email="CY@Example.com"),
    "duplicate handle": lambda fx: _u(fx, 3).update(handle="cy"),
    "email without at": lambda fx: _u(fx, 3).update(email="dee.example.com"),
    "email missing": lambda fx: _u(fx, 3).pop("email"),
    "email number": lambda fx: _u(fx, 3).update(email=5),
    "password empty": lambda fx: _u(fx, 3).update(password=""),
    "password missing": lambda fx: _u(fx, 3).pop("password"),
    "password number": lambda fx: _u(fx, 3).update(password=12345678),
    "display_name number": lambda fx: _u(fx, 3).update(display_name=5),
    "display_name missing": lambda fx: _u(fx, 3).pop("display_name"),
    "handle upper case": lambda fx: _u(fx, 3).update(handle="Dee"),
    "handle with dash": lambda fx: _u(fx, 3).update(handle="d-e"),
    "handle 21 chars": lambda fx: _u(fx, 3).update(handle="d" * 21),
    "handle empty": lambda fx: _u(fx, 3).update(handle=""),
    "handle missing": lambda fx: _u(fx, 3).pop("handle"),
    "balance fraction": lambda fx: _u(fx, 3).update(balance=1.5),
    "balance string": lambda fx: _u(fx, 3).update(balance="100"),
    "balance boolean": lambda fx: _u(fx, 3).update(balance=True),
    "balance null": lambda fx: _u(fx, 3).update(balance=None),
    "balance missing": lambda fx: _u(fx, 3).pop("balance"),
    # 2^53 + 2, not + 1: a JSON number parser with IEEE doubles reads 2^53 + 1 as 2^53.
    "balance above 2^53": lambda fx: _u(fx, 3).update(balance=TWO_53 + 2),
    "payments not array": lambda fx: fx.update(payments="p"),
    "payment not object": lambda fx: fx["payments"].append("p"),
    "payment id missing": lambda fx: fx["payments"][0].pop("id"),
    "payment duplicate id": lambda fx: fx["payments"].append(dict(fx["payments"][0])),
    "payment unknown sender": lambda fx: fx["payments"][0].update(from_user_id="u_ghost"),
    "payment unknown receiver": lambda fx: fx["payments"][0].update(to_user_id="u_ghost"),
    "payment to self": lambda fx: fx["payments"][0].update(to_user_id="u_ada"),
    "payment negative amount": lambda fx: fx["payments"][0].update(amount=-1),
    "payment amount over max": lambda fx: fx["payments"][0].update(amount=1_000_000_001),
    "payment amount string": lambda fx: fx["payments"][0].update(amount="500"),
    "payment bad visibility": lambda fx: fx["payments"][0].update(visibility="secret"),
    "payment note number": lambda fx: fx["payments"][0].update(note=5),
    "requests not array": lambda fx: fx.update(requests={}),
    "request duplicate id": lambda fx: fx["requests"].append(dict(fx["requests"][0])),
    "request unknown payer": lambda fx: fx["requests"][0].update(payer_id="u_ghost"),
    "request unknown requester": lambda fx: fx["requests"][0].update(requester_id="u_ghost"),
    "request to self": lambda fx: fx["requests"][0].update(payer_id="u_bob"),
    "request negative amount": lambda fx: fx["requests"][0].update(amount=-5),
    "request bad status": lambda fx: fx["requests"][0].update(status="weird"),
    "request status number": lambda fx: fx["requests"][0].update(status=1),
    "operators not array": lambda fx: fx.update(settlement_operator_ids="u_ada"),
    "operator not string": lambda fx: fx.update(settlement_operator_ids=[5]),
    "operator unknown user": lambda fx: fx.update(settlement_operator_ids=["u_ghost"]),
    "1001 users": lambda fx: fx.update(users=[user(f"x{i}", 1) for i in range(1001)],
                                       payments=[], requests=[], settlement_operator_ids=[]),
}


@pytest.mark.parametrize("name", list(INVALID))
def test_invalid_fixture_is_422_and_changes_nothing(world, name):
    before_me = world.ada.me()
    signup = world.svc.signup("keepme@example.com", "correct horse", "Keep")
    expect(signup, 201)
    bad = base_fixture()
    for u in bad["users"]:
        u["balance"] += 1   # a different, otherwise valid state
    bad = copy.deepcopy(bad)
    INVALID[name](bad)
    expect_error(world.svc.api().post("/_test/reset", json=bad), 422, "validation_failed")
    # Nothing changed: old tokens, old balances and the signed-up account all survive.
    assert world.ada.me() == before_me
    assert world.svc.client("keepme").balance() == 0
    expect(world.svc.login("keepme@example.com", "correct horse"), 200)


def test_reset_returns_204_with_no_body_and_seeds_users(svc):
    fx = base_fixture()
    resp = httpx.post(f"{svc.base_url}/_test/reset", json=fx, timeout=10)
    assert resp.status_code == 204 and resp.content == b""
    svc.must_reset(fx)
    for u in fx["users"]:
        me = check_me(svc.client(u["handle"]).me())
        assert me == {"user_id": u["id"], "display_name": u["display_name"], "handle": u["handle"],
                      "balance": u["balance"], "currency": "EUR", "minor_units": 2}


def test_seeded_users_log_in_immediately(svc):
    fx = base_fixture()
    svc.must_reset(fx)
    for u in fx["users"]:
        body = expect(svc.login(u["email"], u["password"]), 200)
        assert body["user_id"] == u["id"] and body["display_name"] == u["display_name"]


def test_reset_ignores_an_invalid_authorization_header(svc):
    r = httpx.post(f"{svc.base_url}/_test/reset", json=base_fixture(), timeout=10,
                   headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 204


def test_reset_replaces_everything(world):
    old_token = world.ada.token
    expect(world.svc.signup("gone@example.com", "correct horse", "Gone"), 201)
    other = fixture([user("zed", 7, email="zed@example.com"), user("ann", 3)])
    world.svc.must_reset(other)
    expect_error(world.svc.api(old_token).get("/me"), 401, "unauthenticated")
    expect_error(world.svc.login("ada@example.com", "pw-ada-Correct-Horse-9"), 401, "unauthenticated")
    expect_error(world.svc.login("gone@example.com", "correct horse"), 401, "unauthenticated")
    assert world.svc.client("zed").balance() == 7
    assert world.svc.client("ann").balance() == 3


def test_repeated_resets_work(svc):
    for i in range(3):
        fx = fixture([user("ada", 100 + i), user("bob", i)])
        svc.must_reset(fx)
        assert svc.client("ada").balance() == 100 + i
        assert svc.client("bob").balance() == i


def test_same_handle_can_sign_up_again_after_reset(world):
    expect(world.svc.signup("fresh@example.com", "correct horse", "F"), 201)
    world.svc.must_reset(world.fixture)
    expect(world.svc.signup("fresh@example.com", "correct horse", "F"), 201)


VALID_EDGES = {
    "no payments or requests keys": lambda fx: (fx.pop("payments"), fx.pop("requests")),
    "no operators key": lambda fx: fx.pop("settlement_operator_ids"),
    "unknown fields everywhere": lambda fx: (fx.update(extra=1), _u(fx, 0).update(extra=[1]),
                                             fx["payments"][0].update(extra={}),
                                             fx["requests"][0].update(extra=None)),
    "balance exactly 2^53": lambda fx: _u(fx, 3).update(balance=TWO_53),
    "long seeded note": lambda fx: fx["payments"][0].update(note="n" * 500),
    "empty and long display names": lambda fx: (_u(fx, 2).update(display_name=""),
                                                _u(fx, 3).update(display_name="D" * 300)),
    "seeded payment of zero": lambda fx: fx["payments"][0].update(amount=0),
    "user id of 64 chars": lambda fx: (_u(fx, 3).update(id="u" * 64)),
    "all four request statuses": lambda fx: fx["requests"].extend([
        {"id": "rq_p", "requester_id": "u_cy", "payer_id": "u_dee", "amount": 1, "status": "paid"},
        {"id": "rq_d", "requester_id": "u_cy", "payer_id": "u_dee", "amount": 1, "status": "declined"},
        {"id": "rq_c", "requester_id": "u_cy", "payer_id": "u_dee", "amount": 1, "status": "cancelled"}]),
    "optional payment fields omitted": lambda fx: (fx["payments"][0].pop("note"),
                                                   fx["payments"][0].pop("visibility")),
    "empty users list": lambda fx: fx.update(users=[], payments=[], requests=[], settlement_operator_ids=[]),
}


@pytest.mark.parametrize("name", list(VALID_EDGES))
def test_valid_fixture_edges_are_accepted(svc, name):
    fx = base_fixture()
    VALID_EDGES[name](fx)
    svc.must_reset(fx)


def test_one_character_seeded_password_logs_in(svc):
    """No password-length rule applies at login (D12) or to fixtures (PLAN 3.11)."""
    svc.must_reset(fixture([user("ada", 5, password="x"), user("bob", 0)]))
    expect(svc.login("ada@example.com", "x"), 200)


def test_seeded_email_is_matched_case_insensitively(svc):
    svc.must_reset(fixture([user("ada", 5, email="Ada.Lovelace@Example.COM"), user("bob", 0)]))
    expect(svc.login("ada.lovelace@example.com", "pw-ada-Correct-Horse-9"), 200)


@pytest.mark.parametrize("currency,units", [("EUR", 2), ("JPY", 0), ("BHD", 3)])
def test_currency_and_minor_units_come_from_the_fixture(svc, currency, units):
    svc.must_reset(fixture(currency=currency))
    me = svc.client("ada").me()
    assert me["currency"] == currency and me["minor_units"] == units


def test_a_thousand_users_with_distinct_passwords_reset_within_ten_seconds(svc):
    users = [user(f"u{i:04d}", i, password=f"distinct-password-{i:04d}") for i in range(1000)]
    start = time.monotonic()
    resp = svc.reset(fixture(users), track=False)
    took = time.monotonic() - start
    assert resp.status_code == 204, resp.text[:300]
    assert took < 10, f"1000-user reset took {took:.1f}s (limit 10s)"
    for i in (0, 499, 999):
        body = expect(svc.login(f"u{i:04d}@example.com", f"distinct-password-{i:04d}"), 200)
        assert body["user_id"] == f"u_u{i:04d}"
        assert svc.api(body["token"]).get("/me").json()["balance"] == i
    expect_error(svc.login("u0001@example.com", "distinct-password-0002"), 401, "unauthenticated")


@pytest.mark.item(2)
def test_seeded_payments_follow_the_feed_rule_and_representation(svc):
    fx = fixture(standard_users(), payments=[
        {"id": "p_pub", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
         "note": "coffee", "visibility": "public"},
        {"id": "p_priv", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 70,
         "note": "secret", "visibility": "private"},
        {"id": "p_def", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 1},
        {"id": "p_req", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 9,
         "request_id": "rq_old"},
    ])
    svc.must_reset(fx)
    feeds = {h: {p["payment_id"]: p for p in svc.client(h).feed()} for h in ("ada", "bob", "cy", "dee")}
    assert set(feeds["dee"]) == {"p_pub", "p_def", "p_req"}
    assert set(feeds["ada"]) == {"p_pub", "p_def", "p_req"}
    assert set(feeds["bob"]) == {"p_pub", "p_priv", "p_def", "p_req"}
    assert set(feeds["cy"]) == {"p_pub", "p_priv", "p_def", "p_req"}
    check_payment(feeds["bob"]["p_pub"], from_user_id="u_ada", from_handle="ada", to_user_id="u_bob",
                  to_handle="bob", amount=500, currency="EUR", note="coffee", visibility="public",
                  request_id=None, settlement_id=None)
    check_payment(feeds["cy"]["p_priv"], visibility="private", note="secret")
    check_payment(feeds["ada"]["p_def"], note="", visibility="public")
    check_payment(feeds["ada"]["p_req"], request_id="rq_old")
    # Seeded payments are not replayed against balances.
    assert svc.client("ada").balance() == 10_000 and svc.client("bob").balance() == 2_500


@pytest.mark.item(2)
def test_fixture_settlement_id_is_shown_unchanged(svc):
    """PLAN 3.11 (D34): a fixture payment's settlement_id is shown; one without shows null."""
    svc.must_reset(fixture(standard_users(), payments=[
        {"id": "p_m", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, "settlement_id": "st_old"},
        {"id": "p_n", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 6, "settlement_id": None},
        {"id": "p_o", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 7}]))
    for h in ("ada", "bob", "cy"):
        feed = {p["payment_id"]: p for p in svc.client(h).feed()}
        assert feed["p_m"]["settlement_id"] == "st_old"
        assert feed["p_n"]["settlement_id"] is None and feed["p_o"]["settlement_id"] is None


@pytest.mark.item(2)
def test_fixture_order_is_creation_order(svc):
    """D15: seeded records share the reset time; fixture order is creation order (newest first)."""
    pays = [{"id": f"p_{i}", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": i + 1}
            for i in range(5)]
    svc.must_reset(fixture(standard_users(), payments=pays))
    assert [p["payment_id"] for p in svc.client("ada").feed()] == ["p_4", "p_3", "p_2", "p_1", "p_0"]


@pytest.mark.item(3)
def test_seeded_requests_are_listed_for_both_parties_only(svc):
    fx = fixture(standard_users(), requests=[
        {"id": "rq_a", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
         "note": "taxi", "status": "pending"},
        {"id": "rq_b", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 3,
         "status": "paid", "payment_id": "p_x"},
        {"id": "rq_c", "requester_id": "u_cy", "payer_id": "u_bob", "amount": 4},
    ])
    svc.must_reset(fx)
    lists = {h: {r["request_id"]: r for r in svc.client(h).requests()} for h in ("ada", "bob", "cy", "dee")}
    assert set(lists["ada"]) == {"rq_a", "rq_b"}
    assert set(lists["bob"]) == {"rq_a", "rq_c"}
    assert set(lists["cy"]) == {"rq_b", "rq_c"}
    assert lists["dee"] == {}
    check_request(lists["ada"]["rq_a"], requester_id="u_bob", requester_handle="bob", payer_id="u_ada",
                  payer_handle="ada", amount=1200, currency="EUR", note="taxi", status="pending",
                  payment_id=None)
    check_request(lists["cy"]["rq_b"], status="paid", payment_id="p_x")
    check_request(lists["bob"]["rq_c"], status="pending", note="")


@pytest.mark.item(2)
def test_reset_clears_idempotency_records(world):
    key = new_key()
    expect(world.ada.pay("bob", 100, key=key), 201)
    world.svc.must_reset(world.fixture)
    ada = world.svc.client("ada")
    expect(ada.pay("bob", 100, key=key), 201)
    assert ada.balance() == 9_900


@pytest.mark.item(2)
def test_plan_timestamp_form(world):
    """PLAN 3.7 (D14): UTC, exactly three fractional digits, +00:00."""
    p = expect(world.ada.pay("bob", 1), 201)
    assert PLAN_TS.match(p["created_at"]), p["created_at"]
