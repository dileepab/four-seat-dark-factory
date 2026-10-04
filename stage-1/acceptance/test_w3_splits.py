"""W3.6 — POST /splits (§8, §9; PLAN 3.10, D20). I1, I21."""
from __future__ import annotations

import pytest

from support import (SPLIT_KEYS, check_request, equal_split, expect, expect_error, fixture, new_key,
                     standard_users, ts, user)

pytestmark = pytest.mark.item(3)

FIVE = [user("ada", 10_000), user("bob", 2_500), user("cy", 500), user("dee", 0), user("eve", 0)]


@pytest.fixture
def five(svc):
    svc.must_reset(fixture(FIVE))
    return svc


def check_split(s: dict, caller: str, amount: int, handles: list[str], note: str = "") -> None:
    assert set(s) == SPLIT_KEYS, sorted(s)
    assert s["amount"] == amount and s["currency"] == "EUR" and s["note"] == note
    ts(s["created_at"])
    shares = equal_split(amount, len(handles))
    assert s["shares"] == [{"handle": h, "amount": a} for h, a in zip(handles, shares)]
    others = [(h, a) for h, a in zip(handles, shares) if h != caller]
    assert len(s["requests"]) == len(others)
    for r, (h, a) in zip(s["requests"], others):
        check_request(r, requester_handle=caller, payer_handle=h, amount=a, note=note,
                      status="pending", payment_id=None, currency="EUR")


@pytest.mark.parametrize("amount,n,shares", [
    (1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
    (999, 3, [333, 333, 333]), (5, 5, [1, 1, 1, 1, 1]),
])
def test_specification_rounding_table(five, amount, n, shares):
    handles = ["ada", "bob", "cy", "dee", "eve"][:n]
    s = expect(five.client("ada").split(amount, handles, note="t"), 201)
    assert [x["amount"] for x in s["shares"]] == shares
    check_split(s, "ada", amount, handles, "t")


def test_extra_unit_follows_handle_order(five):
    ada = five.client("ada")
    a = expect(ada.split(1000, ["ada", "bob", "cy"]), 201)
    b = expect(ada.split(1000, ["cy", "bob", "ada"]), 201)
    assert a["shares"][0] == {"handle": "ada", "amount": 334}
    assert b["shares"][0] == {"handle": "cy", "amount": 334}
    assert [r["amount"] for r in b["requests"]] == [334, 333]


def test_caller_may_be_omitted(five):
    s = expect(five.client("ada").split(1000, ["bob", "cy"]), 201)
    check_split(s, "ada", 1000, ["bob", "cy"])


def test_caller_in_the_middle_keeps_order(five):
    s = expect(five.client("ada").split(7, ["bob", "ada", "cy", "dee"]), 201)
    check_split(s, "ada", 7, ["bob", "ada", "cy", "dee"])
    assert [r["payer_handle"] for r in s["requests"]] == ["bob", "cy", "dee"]


def test_caller_only_split_creates_no_requests(five):
    s = expect(five.client("ada").split(500, ["ada"]), 201)
    assert s["shares"] == [{"handle": "ada", "amount": 500}] and s["requests"] == []


def test_zero_shares_still_produce_requests(five):
    s = expect(five.client("ada").split(2, ["ada", "bob", "cy", "dee"]), 201)
    assert [x["amount"] for x in s["shares"]] == [1, 1, 0, 0]
    assert [(r["payer_handle"], r["amount"]) for r in s["requests"]] == [("bob", 1), ("cy", 0), ("dee", 0)]


def test_split_requests_are_listed_for_their_two_parties_only(five):
    s = expect(five.client("ada").split(300, ["ada", "bob", "cy"]), 201)
    rq_bob, rq_cy = (r["request_id"] for r in s["requests"])
    bob_ids = {r["request_id"] for r in five.client("bob").requests()}
    assert rq_bob in bob_ids and rq_cy not in bob_ids
    ada_list = {r["request_id"]: r for r in five.client("ada").requests()}
    assert ada_list[rq_bob] == s["requests"][0] and ada_list[rq_cy] == s["requests"][1]
    assert five.client("dee").requests() == []


def test_split_and_its_requests_share_one_created_at(five):
    s = expect(five.client("ada").split(300, ["ada", "bob", "cy"]), 201)
    assert {r["created_at"] for r in s["requests"]} == {s["created_at"]}


def test_split_checks_nobody_balance(five):
    dee = five.client("dee")
    s = expect(dee.split(1_000_000_000, ["dee", "eve", "cy"]), 201)
    assert [x["amount"] for x in s["shares"]] == [333_333_334, 333_333_333, 333_333_333]
    assert dee.balance() == 0


def test_paying_every_share_conserves_money(five):
    ada = five.client("ada")
    s = expect(ada.split(1001, ["ada", "bob", "cy"]), 201)
    for r in s["requests"]:
        expect(five.client(r["payer_handle"]).pay_request(r["request_id"]), 201)
    assert [x["amount"] for x in s["shares"]] == [334, 334, 333]
    assert ada.balance() == 10_000 + 334 + 333
    five.assert_invariants()


def test_many_splits_are_independent_and_conserve(five):
    ada = five.client("ada")
    for amount in (1, 2, 10, 300, 299, 7):
        s = expect(ada.split(amount, ["bob", "cy", "ada"]), 201)
        assert [x["amount"] for x in s["shares"]] == equal_split(amount, 3)
        for r in s["requests"]:
            expect(five.client(r["payer_handle"]).pay_request(r["request_id"]), 201)
    five.assert_invariants()


@pytest.mark.parametrize("amount", [0, -5, 1.5, 1_000_000_001, "10", True, None], ids=repr)
def test_invalid_split_amount_is_422(world, amount):
    expect_error(world.ada.split(amount, ["ada", "bob"]), 422, "validation_failed")


@pytest.mark.parametrize("handles", [[], ["bob", "bob"], ["ada", "ada"], ["bob", "cy", "bob"]], ids=repr)
def test_empty_or_duplicate_participants_are_422(world, handles):
    expect_error(world.ada.split(100, handles), 422, "validation_failed")


def test_missing_participants_is_422(world):
    expect_error(world.ada.post("/splits", json={"amount": 100}, key=new_key()), 422, "validation_failed")


def test_missing_amount_is_422(world):
    expect_error(world.ada.post("/splits", json={"participant_handles": ["bob"]}, key=new_key()),
                 422, "validation_failed")


@pytest.mark.parametrize("handles", ["bob", 5, None, {"a": "bob"}, [1], [None], ["bob", 5], [["bob"]]], ids=repr)
def test_non_array_or_non_string_participants_are_400(world, handles):
    expect_error(world.ada.split(100, handles), 400, "malformed_request")


def test_more_than_200_participants_is_422(world):
    expect_error(world.ada.split(1000, [f"h{i}" for i in range(201)]), 422, "validation_failed")


def test_a_thousand_participants_is_422_not_a_crash(world):
    expect_error(world.ada.split(1000, [f"h{i}" for i in range(1000)]), 422, "validation_failed")


def test_two_hundred_participants_is_allowed(svc):
    users = [user("ada", 0)] + [user(f"p{i:03d}", 0) for i in range(199)]
    svc.reset(fixture(users), track=False)
    handles = [u["handle"] for u in users]
    s = expect(svc.client("ada").split(1000, handles), 201)
    assert len(s["shares"]) == 200 and len(s["requests"]) == 199
    assert sum(x["amount"] for x in s["shares"]) == 1000


def test_first_unknown_handle_is_404(world):
    expect_error(world.ada.split(100, ["bob", "nobody", "cy"]), 404, "not_found")
    expect_error(world.ada.split(100, ["bob", "BOB"]), 404, "not_found")


def test_split_precedence(world):
    expect_error(world.ada.split(0, ["nobody"]), 422, "validation_failed")
    expect_error(world.ada.split(100, ["nobody", "nobody"]), 422, "validation_failed")
    expect_error(world.ada.split(0, "bob"), 400, "malformed_request")


@pytest.mark.parametrize("note,status", [("a" * 200, 201), ("a" * 201, 422), (None, 422), (5, 422)])
def test_split_note_rules(world, note, status):
    r = world.ada.split(100, ["ada", "bob"], note=note)
    if status == 201:
        s = expect(r, 201)
        assert s["note"] == note and s["requests"][0]["note"] == note
    else:
        expect_error(r, 422, "validation_failed")


def test_split_note_defaults_to_empty(world):
    s = expect(world.ada.post("/splits", json={"amount": 10, "participant_handles": ["bob"]}, key=new_key()), 201)
    assert s["note"] == "" and s["requests"][0]["note"] == ""


def test_failed_split_creates_nothing(world):
    before = world.bob.requests()
    expect_error(world.ada.split(100, ["bob", "nobody"]), 404, "not_found")
    assert world.bob.requests() == before


@pytest.mark.parametrize("currency,amount,shares", [("JPY", 10, [4, 3, 3]), ("BHD", 1000, [334, 333, 333])])
def test_splits_in_other_currencies(svc, currency, amount, shares):
    svc.must_reset(fixture(standard_users(), currency=currency))
    s = expect(svc.client("ada").split(amount, ["ada", "bob", "cy"]), 201)
    assert [x["amount"] for x in s["shares"]] == shares and s["currency"] == currency
