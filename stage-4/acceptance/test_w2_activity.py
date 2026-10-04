"""W2.5, W3.7 — GET /activity (§4 feed contract, §8 GET /activity; PLAN 3.7, D25, D26). I5, I7, I29."""
from __future__ import annotations

import pytest

from support import (assert_newest_first, check_payment, expect, expect_error, fixture, new_key,
                     standard_users, ts, user)

pytestmark = pytest.mark.item(2)


def ids(items):
    return [p["payment_id"] for p in items]


@pytest.fixture
def mixed(world):
    """Four payments covering every sender/receiver/visibility combination."""
    p = {
        "ab_pub": expect(world.ada.pay("bob", 10, visibility="public"), 201),
        "ab_priv": expect(world.ada.pay("bob", 11, visibility="private"), 201),
        "bc_priv": expect(world.bob.pay("cy", 12, visibility="private"), 201),
        "ca_pub": expect(world.cy.pay("ada", 13), 201),
    }
    return world, p


def test_feed_rule_for_sender_receiver_and_third_parties(mixed):
    world, p = mixed
    pid = {k: v["payment_id"] for k, v in p.items()}
    expected = {
        "ada": {"ab_pub", "ab_priv", "ca_pub"},
        "bob": {"ab_pub", "ab_priv", "bc_priv", "ca_pub"},
        "cy": {"ab_pub", "bc_priv", "ca_pub"},
        "dee": {"ab_pub", "ca_pub"},
    }
    for h, keys in expected.items():
        got = set(ids(world.svc.client(h).feed()))
        assert got == {pid[k] for k in keys}, f"{h} sees {got}"


def test_feed_items_equal_their_receipts_for_everyone_who_sees_them(mixed):
    world, p = mixed
    for h in ("ada", "bob", "cy", "dee"):
        for item in world.svc.client(h).feed():
            receipt = next(v for v in p.values() if v["payment_id"] == item["payment_id"])
            assert item == receipt
            check_payment(item)


def test_private_payment_is_visible_to_both_parties_with_one_visibility(mixed):
    world, p = mixed
    pid = p["ab_priv"]["payment_id"]
    for c in (world.ada, world.bob):
        item = next(i for i in c.feed() if i["payment_id"] == pid)
        assert item["visibility"] == "private"


def test_new_user_sees_only_public_payments(mixed):
    world, p = mixed
    expect(world.svc.signup("watcher@example.com", "correct horse", "W"), 201)
    got = set(ids(world.svc.client("watcher").feed()))
    assert got == {p["ab_pub"]["payment_id"], p["ca_pub"]["payment_id"]}


def test_feed_is_newest_first_in_creation_order(world):
    made = [expect(world.ada.pay("bob", i + 1), 201)["payment_id"] for i in range(6)]
    feed = world.ada.feed()
    assert_newest_first(feed)
    assert ids(feed) == list(reversed(made)), "PLAN 3.7: ties go to creation order, later first"


def test_timestamps_never_decrease_in_creation_order(world):
    made = [expect(world.ada.pay("bob", 1), 201) for _ in range(10)]
    times = [ts(p["created_at"]) for p in made]
    assert times == sorted(times)


def test_paging_with_limit_offset_and_has_more(world):
    made = [expect(world.ada.pay("bob", i + 1), 201)["payment_id"] for i in range(7)]
    newest = list(reversed(made))
    pages = []
    for offset in (0, 3, 6):
        page = expect(world.ada.get("/activity", params={"limit": 3, "offset": offset}), 200)
        assert set(page) == {"payments", "has_more"}
        pages.append(page)
    assert ids(pages[0]["payments"]) == newest[0:3] and pages[0]["has_more"] is True
    assert ids(pages[1]["payments"]) == newest[3:6] and pages[1]["has_more"] is True
    assert ids(pages[2]["payments"]) == newest[6:7] and pages[2]["has_more"] is False
    exact = expect(world.ada.get("/activity", params={"limit": 7}), 200)
    assert len(exact["payments"]) == 7 and exact["has_more"] is False
    end = expect(world.ada.get("/activity", params={"offset": 7}), 200)
    assert end == {"payments": [], "has_more": False}


def test_default_limit_is_50(svc):
    pays = [{"id": f"p_{i:03d}", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1}
            for i in range(55)]
    svc.must_reset(fixture(standard_users(), payments=pays))
    page = expect(svc.client("ada").get("/activity"), 200)
    assert len(page["payments"]) == 50 and page["has_more"] is True
    page = expect(svc.client("ada").get("/activity", params={"limit": 200}), 200)
    assert len(page["payments"]) == 55 and page["has_more"] is False


def test_empty_feed(svc):
    svc.must_reset(fixture([user("ann", 1), user("ben", 2)]))
    assert expect(svc.client("ann").get("/activity"), 200) == {"payments": [], "has_more": False}


@pytest.mark.parametrize("params", [
    {"limit": "0"}, {"limit": "201"}, {"limit": "-1"}, {"limit": "abc"}, {"limit": "1e1"},
    {"limit": "4.0"}, {"limit": "+4"}, {"limit": ""}, {"limit": " 4"}, {"limit": "٣"},
    {"limit": "0x10"}, {"offset": "-1"}, {"offset": "1.0"}, {"offset": "abc"}, {"offset": ""},
    {"offset": "+0"}, {"offset": "1e2"},
])
def test_invalid_paging_parameters_are_422(world, params):
    expect_error(world.ada.get("/activity", params=params), 422, "validation_failed")


@pytest.mark.parametrize("params", [{"limit": "1"}, {"limit": "200"}, {"limit": "007"},
                                    {"offset": "0"}, {"offset": "100000000000000000000"}])
def test_valid_paging_edges(world, params):
    page = expect(world.ada.get("/activity", params=params), 200)
    assert set(page) == {"payments", "has_more"}


def test_huge_offset_is_an_empty_page(world):
    expect(world.ada.pay("bob", 1), 201)
    page = expect(world.ada.get("/activity", params={"offset": "100000000000000000000"}), 200)
    assert page == {"payments": [], "has_more": False}


@pytest.mark.parametrize("params", [{"direction": "sideways"}, {"status": "bogus"},
                                    {"direction": "incoming", "status": "paid"}, {"foo": "bar"}])
def test_activity_ignores_other_parameters(world, params):
    expect(world.ada.pay("bob", 1), 201)
    page = expect(world.ada.get("/activity", params=params), 200)
    assert len(page["payments"]) == 1


@pytest.mark.item(3)
def test_requests_and_splits_never_appear_in_the_feed(world):
    before = ids(world.ada.feed())
    rq = expect(world.bob.ask("ada", 100), 201)
    expect(world.ada.split(300, ["ada", "bob", "cy"]), 201)
    expect(world.cy.ask("bob", 5, visibility="public"), 201)
    for c in (world.ada, world.bob, world.cy, world.dee):
        for item in c.feed():
            assert set(item) == set(check_payment(item))
    assert ids(world.ada.feed()) == before
    paid = expect(world.ada.pay_request(rq["request_id"]), 201)
    feed = world.ada.feed()
    assert ids(feed)[0] == paid["payment_id"] and feed[0]["request_id"] == rq["request_id"]
