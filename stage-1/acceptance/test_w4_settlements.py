"""W4 — POST /settlements (§11; PLAN 3.5, 3.10, D18, D19, D27). I1, I2, I15-I19, I22, I23, I24."""
from __future__ import annotations

import pytest

from support import (SETTLEMENT_KEYS, TWO_53, check_payment, expect, expect_error, fixture, new_key,
                     no_failures, standard_users, tally, user)

pytestmark = pytest.mark.item(4)


def t(frm, to, amount, **extra):
    return {"from_handle": frm, "to_handle": to, "amount": amount, **extra}


def balances(world):
    return {h: world.svc.client(h).balance() for h in ("ada", "bob", "cy", "dee")}


def all_payment_ids(world):
    return sorted(p["payment_id"] for p in world.bob.feed()) + sorted(p["payment_id"] for p in world.dee.feed())


# ---------------------------------------------------------------- permission (D18)

def test_no_token_is_401(world):
    r = world.svc.api().post("/settlements", json={"transfers": [t("ada", "bob", 1)]}, key=new_key())
    expect_error(r, 401, "unauthenticated")


@pytest.mark.parametrize("variant", ["valid", "no key", "bad body", "unparseable", "long key"])
def test_non_operator_is_403_before_key_and_body(world, variant):
    before = balances(world)
    body = {"transfers": [t("bob", "cy", 1)]}
    if variant == "valid":
        r = world.bob.post("/settlements", json=body, key=new_key())
    elif variant == "no key":
        r = world.bob.post("/settlements", json=body)
    elif variant == "bad body":
        r = world.bob.post("/settlements", json={"transfers": "x"}, key=new_key())
    elif variant == "unparseable":
        r = world.bob.post("/settlements", content=b"{nope", key=new_key())
    else:
        r = world.bob.post("/settlements", json=body, key="k" * 300)
    expect_error(r, 403, "forbidden")
    assert balances(world) == before


def test_operator_without_key_is_400(world):
    expect_error(world.ada.post("/settlements", json={"transfers": [t("ada", "bob", 1)]}),
                 400, "missing_idempotency_key")


def test_operator_list_comes_from_the_fixture(svc):
    svc.must_reset(fixture(standard_users(), operators=["u_cy", "u_dee"]))
    expect(svc.client("cy").settle([t("ada", "bob", 5)]), 201)
    expect(svc.client("dee").settle([t("bob", "ada", 5)]), 201)
    expect_error(svc.client("ada").settle([t("ada", "bob", 5)]), 403, "forbidden")


def test_no_operators_by_default(svc):
    fx = fixture(standard_users())
    fx.pop("settlement_operator_ids", None)
    svc.must_reset(fx)
    expect_error(svc.client("ada").settle([t("ada", "bob", 5)]), 403, "forbidden")


def test_signed_up_user_is_not_an_operator(world):
    expect(world.svc.signup("newop@example.com", "correct horse", "N"), 201)
    expect_error(world.svc.client("newop").settle([t("ada", "bob", 5)]), 403, "forbidden")


# ---------------------------------------------------------------- success

def test_settlement_201_shape_and_members(world):
    s = expect(world.ada.settle([t("ada", "bob", 100), t("bob", "cy", 50, note="n", visibility="private")]), 201)
    assert set(s) == SETTLEMENT_KEYS
    assert isinstance(s["settlement_id"], str) and 1 <= len(s["settlement_id"]) <= 64
    p1, p2 = s["payments"]
    check_payment(p1, from_handle="ada", to_handle="bob", from_user_id="u_ada", to_user_id="u_bob",
                  amount=100, note="", visibility="public", request_id=None,
                  settlement_id=s["settlement_id"], created_at=s["committed_at"], currency="EUR")
    check_payment(p2, from_handle="bob", to_handle="cy", amount=50, note="n", visibility="private",
                  request_id=None, settlement_id=s["settlement_id"], created_at=s["committed_at"])
    assert p1["payment_id"] != p2["payment_id"]
    assert balances(world) == {"ada": 9_900, "bob": 2_550, "cy": 550, "dee": 0}


def test_operator_can_move_money_between_two_other_wallets(world):
    expect(world.ada.settle([t("bob", "dee", 300)]), 201)
    assert world.bob.balance() == 2_200 and world.dee.balance() == 300


def test_net_affordability_chain_through_an_empty_wallet(world):
    """Dee holds 0: sending 100 is affordable because 100 arrives in the same settlement."""
    s = expect(world.ada.settle([t("dee", "bob", 100), t("ada", "dee", 100)]), 201)
    assert [p["from_handle"] for p in s["payments"]] == ["dee", "ada"]
    assert world.dee.balance() == 0 and world.bob.balance() == 2_600


def test_exactly_zero_after_netting_is_affordable(world):
    expect(world.ada.settle([t("cy", "dee", 500)]), 201)
    assert world.cy.balance() == 0


def test_same_pair_twice_gives_two_payments(world):
    s = expect(world.ada.settle([t("ada", "bob", 1), t("ada", "bob", 1)]), 201)
    assert len({p["payment_id"] for p in s["payments"]}) == 2


def test_thirty_two_transfers_are_allowed(world):
    s = expect(world.ada.settle([t("ada", "bob", 1)] * 32), 201)
    assert len(s["payments"]) == 32 and world.bob.balance() == 2_532


def test_unknown_fields_are_ignored(world):
    s = expect(world.ada.settle([t("ada", "bob", 3, extra=1, settlement_id="st_x", request_id="r")],
                                committed_at="1999-01-01T00:00:00+00:00", extra=[1]), 201)
    assert s["payments"][0]["request_id"] is None and s["payments"][0]["settlement_id"] == s["settlement_id"]
    assert not s["committed_at"].startswith("1999")


def test_ordinary_payments_have_null_settlement_id(world):
    p = expect(world.ada.pay("bob", 1), 201)
    expect(world.ada.settle([t("ada", "bob", 2)]), 201)
    assert p["settlement_id"] is None
    feed = {i["payment_id"]: i for i in world.bob.feed()}
    assert feed[p["payment_id"]]["settlement_id"] is None


def test_members_follow_the_ordinary_feed_rule(world):
    s = expect(world.ada.settle([t("bob", "cy", 5, visibility="private"), t("cy", "dee", 1)]), 201)
    priv, pub = s["payments"]
    ada_ids = {i["payment_id"] for i in world.ada.feed()}
    assert priv["payment_id"] not in ada_ids, "the operator gains no view of private members"
    assert pub["payment_id"] in ada_ids
    for c in (world.bob, world.cy):
        item = next(i for i in c.feed() if i["payment_id"] == priv["payment_id"])
        assert item == priv
    assert priv["payment_id"] not in {i["payment_id"] for i in world.dee.feed()}
    assert next(i for i in world.dee.feed() if i["payment_id"] == pub["payment_id"]) == pub


def test_members_are_listed_in_input_order_newest_first(world):
    s = expect(world.ada.settle([t("ada", "bob", 1), t("ada", "bob", 2), t("ada", "bob", 3)]), 201)
    feed = [i["payment_id"] for i in world.bob.feed()][:3]
    assert feed == [p["payment_id"] for p in reversed(s["payments"])], "PLAN 3.7: later creation first"


# ---------------------------------------------------------------- validation (D27)

@pytest.mark.parametrize("body", [
    {}, {"transfers": None}, {"transfers": "x"}, {"transfers": {}}, {"transfers": 5},
    {"transfers": []}, {"transfers": [t("ada", "bob", 1)] * 33},
    {"transfers": [5]}, {"transfers": ["x"]}, {"transfers": [None]}, {"transfers": [[]]},
    {"transfers": [t("ada", "bob", 1), 7]},
], ids=lambda b: repr(b)[:40])
def test_malformed_batch_shape_is_422(world, body):
    before = balances(world)
    expect_error(world.ada.post("/settlements", json=body, key=new_key()), 422, "validation_failed")
    assert balances(world) == before


@pytest.mark.parametrize("entry", [
    {"to_handle": "bob", "amount": 1}, {"from_handle": "ada", "amount": 1},
    {"from_handle": "ada", "to_handle": "bob"},
    t(5, "bob", 1), t("ada", None, 1), t(["ada"], "bob", 1),
    t("ada", "bob", 0), t("ada", "bob", -1), t("ada", "bob", 1.5), t("ada", "bob", "1"),
    t("ada", "bob", True), t("ada", "bob", 1_000_000_001), t("ada", "bob", None),
    t("ada", "bob", 1, note="a" * 201), t("ada", "bob", 1, note=None), t("ada", "bob", 1, note=5),
    t("ada", "bob", 1, visibility="secret"), t("ada", "bob", 1, visibility=None),
], ids=lambda e: repr(e)[:50])
def test_invalid_entry_is_422(world, entry):
    expect_error(world.ada.settle([t("ada", "cy", 1), entry]), 422, "validation_failed")
    assert world.cy.balance() == 500


def test_unknown_handles_are_404(world):
    expect_error(world.ada.settle([t("nobody", "bob", 1)]), 404, "not_found")
    expect_error(world.ada.settle([t("ada", "nobody", 1)]), 404, "not_found")
    expect_error(world.ada.settle([t("ada", "BOB", 1)]), 404, "not_found")


def test_self_transfer_is_self_payment(world):
    expect_error(world.ada.settle([t("bob", "bob", 1)]), 422, "self_payment")


@pytest.mark.parametrize("transfers,status,code", [
    ([t("nobody", "bob", 1), t("ada", "bob", 0)], 404, "not_found"),
    ([t("ada", "bob", 0), t("nobody", "bob", 1)], 422, "validation_failed"),
    ([t("bob", "bob", 1), t("nobody", "bob", 1)], 422, "self_payment"),
    ([t("nobody", "bob", 1), t("bob", "bob", 1)], 404, "not_found"),
    ([t("nobody", "ghost", 1)], 404, "not_found"),
    ([t("nobody", "nobody", 0)], 422, "validation_failed"),
    ([t("nobody", "nobody", 1)], 404, "not_found"),
    ([t("dee", "bob", 10 ** 6), t("ada", "nobody", 1)], 404, "not_found"),
    ([t("dee", "bob", 10 ** 6), t("cy", "cy", 1)], 422, "self_payment"),
    ([t("dee", "bob", 10 ** 6), t("cy", "bob", 1, visibility="x")], 422, "validation_failed"),
], ids=[f"case{i}" for i in range(10)])
def test_entry_errors_in_input_order_before_funds(world, transfers, status, code):
    expect_error(world.ada.settle(transfers), status, code)


# ---------------------------------------------------------------- funds and atomicity (I22)

@pytest.mark.parametrize("transfers", [
    [t("dee", "bob", 1)],
    [t("ada", "bob", 100), t("dee", "bob", 1)],
    [t("ada", "dee", 100), t("dee", "bob", 101)],
    [t("cy", "dee", 300), t("cy", "bob", 201)],
    [t("ada", "bob", 1_000_000_000)],
], ids=["empty-sender", "second-unaffordable", "chain-short-by-one", "two-outgoing", "too-much"])
def test_unaffordable_settlement_is_409_and_changes_nothing(world, transfers):
    before = balances(world)
    feeds = all_payment_ids(world)
    key = new_key()
    expect_error(world.ada.settle(transfers, key=key), 409, "insufficient_funds")
    assert balances(world) == before
    assert all_payment_ids(world) == feeds
    s = expect(world.ada.settle([t("ada", "bob", 1)], key=key), 201)   # the key was not claimed
    assert len(s["payments"]) == 1


def test_failed_validation_claims_no_key(world):
    key = new_key()
    expect_error(world.ada.settle([t("nobody", "bob", 1)], key=key), 404, "not_found")
    expect(world.ada.settle([t("ada", "bob", 1)], key=key), 201)


def test_settlement_past_2_53_is_422_and_changes_nothing(svc):
    svc.must_reset(fixture([user("ada", 1_000), user("bob", TWO_53 - 5), user("cy", 0)], operators=["u_ada"]))
    ada = svc.client("ada")
    expect_error(ada.settle([t("ada", "bob", 3), t("ada", "bob", 3)]), 422, "validation_failed")
    assert ada.balance() == 1_000
    expect(ada.settle([t("ada", "bob", 3), t("bob", "cy", 1), t("ada", "bob", 3)]), 201)
    assert svc.client("bob").balance() == TWO_53 - 5 + 6 - 1


# ---------------------------------------------------------------- replay and concurrency

def test_replay_returns_the_complete_original(world):
    key = new_key()
    body = [t("ada", "bob", 100), t("bob", "cy", 50)]
    s = expect(world.ada.settle(body, key=key), 201)
    expect(world.cy.pay("dee", 10), 201)
    after = balances(world)
    assert expect(world.ada.settle(body, key=key), 200) == s
    assert balances(world) == after


def test_concurrent_settlements_and_payments_conserve(svc):
    users = [user(f"s{i}", 100) for i in range(8)]
    svc.must_reset(fixture(users, operators=["u_s0"]))
    ops = [svc.fresh_client("s0") for _ in range(25)]
    payers = {u["handle"]: svc.fresh_client(u["handle"]) for u in users}

    def go(i):
        if i % 2 == 0:
            a, b, c = f"s{i % 8}", f"s{(i + 3) % 8}", f"s{(i + 5) % 8}"
            return ops[i // 2].settle([t(a, b, 30), t(b, c, 45)])
        return payers[f"s{i % 8}"].pay(f"s{(i + 1) % 8}", 20)

    out = svc.burst(go, 50)
    no_failures(out)
    assert set(tally(out)) <= {201, 409}, tally(out)
    for r in out:
        if r.status_code == 201 and "committed_at" in r.json():
            s = r.json()
            assert all(p["settlement_id"] == s["settlement_id"] and p["created_at"] == s["committed_at"]
                       for p in s["payments"])
