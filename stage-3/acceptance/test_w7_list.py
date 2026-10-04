"""W7.5 — GET /authorizations (stage-2 "API"; PLAN 3.2, 3.5, 3.6, 3.7, 3.10, D40). I29, I35, I49."""
from __future__ import annotations

import json

import pytest

from support import (AUTHZ_KEYS, assert_newest_first, check_authorization, expect, expect_error, fixture,
                     raw_request, seeded_auth, standard_users)

pytestmark = pytest.mark.item(7)


def ids(items) -> list[str]:
    return [a["authorization_id"] for a in items]


@pytest.fixture
def mixed(world):
    """Ada pays out two holds and receives one; each status once; Cy and Dee hold one between them."""
    ada, bob, cy, dee = world.ada, world.bob, world.cy, world.dee
    a = {}
    a["open_out"] = expect(ada.authorize("bob", 100), 201)["authorization_id"]
    a["captured_out"] = expect(ada.authorize("cy", 200), 201)["authorization_id"]
    expect(cy.capture(a["captured_out"]), 201)
    a["voided_in"] = expect(bob.authorize("ada", 300), 201)["authorization_id"]
    expect(bob.void(a["voided_in"]), 200)
    a["open_in"] = expect(cy.authorize("ada", 40), 201)["authorization_id"]
    a["others"] = expect(cy.authorize("dee", 50), 201)["authorization_id"]
    world.a = a
    return world


def test_only_the_callers_authorizations(mixed):
    a = mixed.a
    assert set(ids(mixed.ada.auths())) == {a["open_out"], a["captured_out"], a["voided_in"], a["open_in"]}
    assert set(ids(mixed.dee.auths())) == {a["others"]}
    assert set(ids(mixed.cy.auths())) == {a["captured_out"], a["open_in"], a["others"]}
    expect(mixed.svc.signup("lonely@example.com", "correct horse", "L"), 201)
    assert mixed.svc.client("lonely").auths() == []


def test_list_is_newest_first_and_every_item_has_the_shape(mixed):
    items = mixed.ada.auths()
    assert ids(items) == [mixed.a["open_in"], mixed.a["voided_in"], mixed.a["captured_out"], mixed.a["open_out"]]
    assert_newest_first(items)
    for it in items:
        check_authorization(it)


@pytest.mark.parametrize("direction,expected", [
    ("outgoing", {"open_out", "captured_out"}), ("incoming", {"voided_in", "open_in"})])
def test_direction_filter(mixed, direction, expected):
    assert set(ids(mixed.ada.auths(direction=direction))) == {mixed.a[k] for k in expected}


@pytest.mark.parametrize("status,expected", [
    ("open", {"open_out", "open_in"}), ("captured", {"captured_out"}), ("voided", {"voided_in"}),
    ("expired", set())])
def test_status_filter(mixed, status, expected):
    got = mixed.ada.auths(status=status)
    assert set(ids(got)) == {mixed.a[k] for k in expected}
    assert all(x["status"] == status for x in got)


@pytest.mark.parametrize("direction,status,expected", [
    ("outgoing", "open", {"open_out"}), ("incoming", "open", {"open_in"}),
    ("incoming", "captured", set()), ("outgoing", "voided", set()), ("incoming", "voided", {"voided_in"})])
def test_direction_and_status_together(mixed, direction, status, expected):
    assert set(ids(mixed.ada.auths(direction=direction, status=status))) == {mixed.a[k] for k in expected}


def test_the_list_shows_the_same_representation_as_create_and_void(world):
    a = expect(world.ada.authorize("bob", 100, note="x"), 201)
    assert world.ada.auth(a["authorization_id"]) == a
    v = expect(world.ada.void(a["authorization_id"]), 200)
    assert world.bob.auth(a["authorization_id"]) == v


def test_paging(world):
    made = [expect(world.ada.authorize("bob", i + 1), 201)["authorization_id"] for i in range(7)]
    newest = list(reversed(made))
    p1 = expect(world.ada.get("/authorizations", params={"limit": 3}), 200)
    assert set(p1) == {"authorizations", "has_more"}
    assert ids(p1["authorizations"]) == newest[:3] and p1["has_more"] is True
    p2 = expect(world.ada.get("/authorizations", params={"limit": 3, "offset": 3}), 200)
    assert ids(p2["authorizations"]) == newest[3:6] and p2["has_more"] is True
    p3 = expect(world.ada.get("/authorizations", params={"limit": 3, "offset": 6}), 200)
    assert ids(p3["authorizations"]) == newest[6:] and p3["has_more"] is False
    p4 = expect(world.ada.get("/authorizations", params={"offset": 7}), 200)
    assert p4 == {"authorizations": [], "has_more": False}
    p5 = expect(world.ada.get("/authorizations", params={"limit": 7}), 200)
    assert p5["has_more"] is False and len(p5["authorizations"]) == 7
    p6 = expect(world.ada.get("/authorizations", params={"limit": 200, "offset": 0}), 200)
    assert ids(p6["authorizations"]) == newest


def test_default_limit_is_50(world):
    for i in range(52):
        expect(world.ada.authorize("bob", 1), 201)
    page = expect(world.ada.get("/authorizations"), 200)
    assert len(page["authorizations"]) == 50 and page["has_more"] is True


@pytest.mark.parametrize("params", [
    {"direction": "OUTGOING"}, {"direction": ""}, {"direction": "both"}, {"direction": "out"},
    {"status": "Open"}, {"status": ""}, {"status": "pending"}, {"status": "closed"},
    {"limit": "0"}, {"limit": "201"}, {"limit": "-1"}, {"limit": "abc"}, {"limit": "1e2"},
    {"limit": "4.0"}, {"limit": "+4"}, {"limit": ""}, {"offset": "-1"}, {"offset": "x"},
    {"offset": "1.0"}, {"offset": ""},
], ids=lambda p: "&".join(f"{k}={v}" for k, v in p.items()))
def test_invalid_query_values_are_422(world, params):
    expect_error(world.ada.get("/authorizations", params=params), 422, "validation_failed")


def test_unknown_query_parameters_are_ignored_and_the_first_repeat_counts(mixed):
    assert ids(expect(mixed.ada.get("/authorizations", params={"colour": "red"}), 200)["authorizations"]) == \
        ids(mixed.ada.auths())
    r = expect(mixed.ada.get("/authorizations?status=voided&status=open"), 200)
    assert ids(r["authorizations"]) == [mixed.a["voided_in"]]


def test_requires_a_token(world):
    expect_error(world.svc.api().get("/authorizations"), 401, "unauthenticated")
    expect_error(world.svc.api().get("/authorizations", params={"status": "bogus"}), 401, "unauthenticated")


@pytest.mark.parametrize("accept", [None, "application/json", "*/*", "", "text/*", "text/html;q=0",
                                    "application/json, text/html;q=0", "text/htmlx", "application/xhtml+xml"])
def test_json_unless_accept_lists_text_html(mixed, accept):
    """D40: JSON for API clients; the HTML shell only when Accept lists text/html."""
    if accept is None:     # httpx always adds an Accept header; send none at all
        status, headers, raw = raw_request(mixed.svc.base_url, "GET", "/authorizations", token=mixed.ada.token)
        assert status == 200 and headers["content-type"].replace(" ", "").lower() == "application/json;charset=utf-8"
        body = json.loads(raw)
    else:
        body = expect(mixed.ada.get("/authorizations", headers={"Accept": accept}), 200)
    assert set(body) == {"authorizations", "has_more"} and len(body["authorizations"]) == 4


def test_seeded_authorizations_take_fixture_order_as_creation_order(svc):
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth(f"a_{i}", "ada", "bob", 10 + i) for i in range(5)]))
    items = svc.client("bob").auths()
    assert ids(items) == ["a_4", "a_3", "a_2", "a_1", "a_0"]
    assert len({x["created_at"] for x in items}) == 1, "seeded authorizations share the reset's timestamp"
    for x in items:
        assert set(x) == AUTHZ_KEYS


def test_created_after_seeded_comes_first(svc):
    svc.must_reset(fixture(standard_users(), authorizations=[seeded_auth("a_seed", "ada", "bob", 10)]))
    new = expect(svc.client("ada").authorize("bob", 5), 201)["authorization_id"]
    assert ids(svc.client("bob").auths()) == [new, "a_seed"]
