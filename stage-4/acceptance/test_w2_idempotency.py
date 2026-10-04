"""W2.3 (and the same rules on W3/W4/W7 paths) — idempotency (§7; PLAN 3.5 step 4-6, 3.9, D17;
stage-2 PLAN 3.9, D61).

I15 replay, I16 key reuse, I17 concurrent first use, I18 failures claim nothing, I19 key scope.
Every scenario runs on each of the eight idempotent write paths (stage 3 adds
`POST /payments/{id}/corrections`, W16.2); each path carries the work item that introduces it.
"""
from __future__ import annotations

import json

import pytest

from support import expect, expect_error, fixture, new_key, no_failures, standard_users, tally


class Op:
    """One idempotent write path, as seen by its caller."""
    name = ""
    caller = "ada"

    def setup(self, world) -> dict:
        return {}

    def path(self, ctx) -> str:
        raise NotImplementedError

    def body(self, ctx) -> dict:
        raise NotImplementedError

    def alt_body(self, ctx) -> dict:
        raise NotImplementedError

    def bad_body(self, ctx) -> dict:
        raise NotImplementedError

    def float_body(self, ctx) -> str:
        """The same JSON value as body(), written with different number forms."""
        raise NotImplementedError

    def mutate(self, world, ctx, first: dict) -> None:
        """Change the resource or balances after the first call."""
        expect(world.bob.pay("cy", 1), 201)


class Payments(Op):
    name = "payments"

    def path(self, ctx): return "/payments"
    def body(self, ctx): return {"to_handle": "bob", "amount": 100, "note": "n"}
    def alt_body(self, ctx): return {"to_handle": "bob", "amount": 101, "note": "n"}
    def bad_body(self, ctx): return {"to_handle": "bob", "amount": 0}
    def float_body(self, ctx): return '{"note": "n", "amount": 1e2, "to_handle": "bob"}'


class Requests(Op):
    name = "requests"
    caller = "bob"

    def path(self, ctx): return "/requests"
    def body(self, ctx): return {"payer_handle": "ada", "amount": 100, "note": "n"}
    def alt_body(self, ctx): return {"payer_handle": "ada", "amount": 100, "note": "m"}
    def bad_body(self, ctx): return {"payer_handle": "ada", "amount": 0}
    def float_body(self, ctx): return '{"note":"n","amount":100.0,"payer_handle":"ada"}'

    def mutate(self, world, ctx, first):
        expect(world.bob.cancel(first["request_id"]), 200)


class Pay(Op):
    name = "pay"

    def setup(self, world):
        return {"rq": expect(world.bob.ask("ada", 100, note="for pay"), 201)["request_id"]}

    def path(self, ctx): return f"/requests/{ctx['rq']}/pay"
    def body(self, ctx): return {"visibility": "private"}
    def alt_body(self, ctx): return {"visibility": "public"}
    def bad_body(self, ctx): return {"visibility": "bogus"}
    def float_body(self, ctx): return '{ "visibility" : "private" }'

    def mutate(self, world, ctx, first):
        pass   # the request is already paid: a replay must not be 409 request_not_pending


class Splits(Op):
    name = "splits"

    def path(self, ctx): return "/splits"
    def body(self, ctx): return {"amount": 300, "participant_handles": ["ada", "bob", "cy"], "note": "s"}
    def alt_body(self, ctx): return {"amount": 300, "participant_handles": ["ada", "cy", "bob"], "note": "s"}
    def bad_body(self, ctx): return {"amount": 0, "participant_handles": ["ada", "bob"]}
    def float_body(self, ctx): return '{"participant_handles":["ada","bob","cy"],"note":"s","amount":3E2}'

    def mutate(self, world, ctx, first):
        rq = first["requests"][0]["request_id"]
        expect(world.bob.pay_request(rq), 201)


class Settlements(Op):
    name = "settlements"

    def path(self, ctx): return "/settlements"
    def body(self, ctx):
        return {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
                              {"from_handle": "bob", "to_handle": "cy", "amount": 50}]}
    def alt_body(self, ctx):
        return {"transfers": [{"from_handle": "bob", "to_handle": "cy", "amount": 50},
                              {"from_handle": "ada", "to_handle": "bob", "amount": 100}]}
    def bad_body(self, ctx): return {"transfers": []}
    def float_body(self, ctx):
        return ('{"transfers":[{"amount":100.0,"to_handle":"bob","from_handle":"ada"},'
                '{"from_handle":"bob","to_handle":"cy","amount":5e1}]}')


class Authorizations(Op):
    name = "authorizations"

    def path(self, ctx): return "/authorizations"
    def body(self, ctx): return {"to_handle": "bob", "amount": 100, "note": "n", "visibility": "private"}
    def alt_body(self, ctx): return {"to_handle": "bob", "amount": 100, "note": "n"}
    def bad_body(self, ctx): return {"to_handle": "bob", "amount": 0}
    def float_body(self, ctx): return '{"visibility":"private","note":"n","amount":1.0e2,"to_handle":"bob"}'

    def mutate(self, world, ctx, first):
        expect(world.bob.capture(first["authorization_id"], {"amount": 40}), 201)


class Capture(Op):
    name = "capture"
    caller = "bob"

    def setup(self, world):
        return {"aid": expect(world.ada.authorize("bob", 1_000, note="for capture"), 201)["authorization_id"]}

    def path(self, ctx): return f"/authorizations/{ctx['aid']}/capture"
    def body(self, ctx): return {"amount": 300, "final": False}
    def alt_body(self, ctx): return {"amount": 300}
    def bad_body(self, ctx): return {"amount": 0}
    def float_body(self, ctx): return '{ "final" : false , "amount" : 3E2 }'

    def mutate(self, world, ctx, first):
        expect(world.ada.void(ctx["aid"]), 200)


class Corrections(Op):
    """Stage 3, the eighth path (W16.2): ada corrects her payment to bob."""
    name = "corrections"

    def setup(self, world):
        p = expect(world.ada.pay("bob", 100), 201)
        return {"pid": p["payment_id"], "at": p["created_at"]}

    def path(self, ctx): return f"/payments/{ctx['pid']}/corrections"
    def body(self, ctx): return {"expected_revision": 1, "amount": 60, "effective_at": ctx["at"], "reason": "fix"}
    def alt_body(self, ctx): return {"expected_revision": 1, "amount": 61, "effective_at": ctx["at"], "reason": "fix"}
    def bad_body(self, ctx): return {"expected_revision": 1, "amount": 60, "effective_at": ctx["at"], "reason": ""}

    def float_body(self, ctx):
        return '{"reason": "fix", "effective_at": "%s", "amount": 6E1, "expected_revision": 1.0}' % ctx["at"]

    def mutate(self, world, ctx, first):
        expect(world.ada.correct(ctx["pid"], 2, 70, ctx["at"]), 201)


OPS = [
    pytest.param(Payments(), marks=pytest.mark.item(2), id="payments"),
    pytest.param(Requests(), marks=pytest.mark.item(3), id="requests"),
    pytest.param(Pay(), marks=pytest.mark.item(3), id="pay"),
    pytest.param(Splits(), marks=pytest.mark.item(3), id="splits"),
    pytest.param(Settlements(), marks=pytest.mark.item(4), id="settlements"),
    pytest.param(Authorizations(), marks=pytest.mark.item(7), id="authorizations"),
    pytest.param(Capture(), marks=pytest.mark.item(7), id="capture"),
    pytest.param(Corrections(), marks=pytest.mark.item(16), id="corrections"),
]

pytestmark = pytest.mark.item(2)


def snapshot(world, op) -> dict:
    """Everything a duplicate could change: balances, feeds and (from W3) request lists."""
    snap = {h: world.svc.client(h).balance() for h in ("ada", "bob", "cy", "dee")}
    snap["feed"] = sorted(p["payment_id"] for p in world.ada.feed())
    snap["feed_bob"] = sorted(p["payment_id"] for p in world.bob.feed())
    if op.name in ("authorizations", "capture"):
        for h in ("ada", "bob"):
            snap[f"money_{h}"] = world.svc.client(h).money()
            snap[f"auth_{h}"] = sorted((a["authorization_id"], a["status"], a["captured_amount"])
                                       for a in world.svc.client(h).auths())
    elif op.name == "corrections":
        snap["revisions"] = {p["payment_id"]: [(r["revision"], r["amount"]) for r in world.ada.revisions(p["payment_id"])]
                             for p in world.ada.feed() if p["from_handle"] == "ada"}
    elif op.name != "payments":
        for h in ("ada", "bob", "cy"):
            snap[f"req_{h}"] = sorted((r["request_id"], r["status"]) for r in world.svc.client(h).requests())
    return snap


def call(world, op, ctx, key, body=None, client=None, raw=None):
    c = client or world.svc.client(op.caller)
    if raw is not None:
        return c.post(op.path(ctx), content=raw.encode(), key=key)
    return c.post(op.path(ctx), json=op.body(ctx) if body is None else body, key=key)


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("header", [None, ""], ids=["absent", "empty"])
def test_missing_key_is_400_and_changes_nothing(world, op, header):
    ctx = op.setup(world)
    before = snapshot(world, op)
    c = world.svc.client(op.caller)
    headers = {"Idempotency-Key": header} if header is not None else None
    expect_error(c.post(op.path(ctx), json=op.body(ctx), headers=headers), 400, "missing_idempotency_key")
    assert snapshot(world, op) == before


@pytest.mark.parametrize("op", OPS)
def test_key_over_255_characters_is_422(world, op):
    ctx = op.setup(world)
    before = snapshot(world, op)
    expect_error(call(world, op, ctx, "k" * 256), 422, "validation_failed")
    assert snapshot(world, op) == before


@pytest.mark.parametrize("op", OPS)
def test_replay_is_200_with_the_original_body_and_no_effect(world, op):
    ctx = op.setup(world)
    key = new_key()
    first = expect(call(world, op, ctx, key), 201)
    after_first = snapshot(world, op)
    for _ in range(3):
        assert expect(call(world, op, ctx, key), 200) == first
    assert snapshot(world, op) == after_first


@pytest.mark.parametrize("op", OPS)
def test_replay_with_reordered_keys_and_whitespace_is_a_replay(world, op):
    ctx = op.setup(world)
    key = new_key()
    first = expect(call(world, op, ctx, key), 201)
    body = op.body(ctx)
    raw = json.dumps(dict(reversed(list(body.items()))), indent=3, ensure_ascii=False)
    assert expect(call(world, op, ctx, key, raw=raw), 200) == first


@pytest.mark.parametrize("op", OPS)
def test_numerically_equal_numbers_are_the_same_body(world, op):
    """PLAN 3.9: numbers compare by value (100, 100.0 and 1e2 are equal)."""
    ctx = op.setup(world)
    key = new_key()
    first = expect(call(world, op, ctx, key), 201)
    after_first = snapshot(world, op)
    assert expect(call(world, op, ctx, key, raw=op.float_body(ctx)), 200) == first
    assert snapshot(world, op) == after_first


@pytest.mark.parametrize("op", OPS)
def test_replay_by_another_token_of_the_same_user(world, op):
    ctx = op.setup(world)
    key = new_key()
    first = expect(call(world, op, ctx, key), 201)
    acct = world.svc.accounts[op.caller]
    token = expect(world.svc.login(acct.email, acct.password), 200)["token"]
    assert expect(call(world, op, ctx, key, client=world.svc.api(token)), 200) == first


@pytest.mark.parametrize("op", OPS)
def test_same_key_different_body_is_409_and_changes_nothing(world, op):
    ctx = op.setup(world)
    key = new_key()
    expect(call(world, op, ctx, key), 201)
    after_first = snapshot(world, op)
    expect_error(call(world, op, ctx, key, body=op.alt_body(ctx)), 409, "idempotency_key_reuse")
    assert snapshot(world, op) == after_first


@pytest.mark.parametrize("op", OPS)
def test_claimed_key_outranks_an_invalid_new_body(world, op):
    """§7: a claimed key is resolved before field validation."""
    ctx = op.setup(world)
    key = new_key()
    expect(call(world, op, ctx, key), 201)
    expect_error(call(world, op, ctx, key, body=op.bad_body(ctx)), 409, "idempotency_key_reuse")


@pytest.mark.parametrize("op", OPS)
def test_unparseable_body_with_a_claimed_key_is_400(world, op):
    """§7: the key is resolved only after the body parses as a JSON object."""
    ctx = op.setup(world)
    key = new_key()
    expect(call(world, op, ctx, key), 201)
    expect_error(call(world, op, ctx, key, raw="{nope"), 400, "malformed_request")
    expect_error(call(world, op, ctx, key, raw="[]"), 400, "malformed_request")


@pytest.mark.parametrize("op", OPS)
def test_key_that_failed_with_4xx_is_a_first_use_later(world, op):
    ctx = op.setup(world)
    key = new_key()
    before = snapshot(world, op)
    expect_error(call(world, op, ctx, key, body=op.bad_body(ctx)), 422, "validation_failed")
    assert snapshot(world, op) == before
    first = expect(call(world, op, ctx, key), 201)
    assert expect(call(world, op, ctx, key), 200) == first


@pytest.mark.parametrize("op", OPS)
def test_replay_after_the_resource_changed_returns_the_original(world, op):
    ctx = op.setup(world)
    key = new_key()
    first = expect(call(world, op, ctx, key), 201)
    op.mutate(world, ctx, first)
    after = snapshot(world, op)
    assert expect(call(world, op, ctx, key), 200) == first
    assert snapshot(world, op) == after


@pytest.mark.parametrize("op", OPS)
def test_fifty_concurrent_identical_first_uses(world, op):
    ctx = op.setup(world)
    before = snapshot(world, op)
    key = new_key()
    clients = [world.svc.fresh_client(op.caller) for _ in range(50)]
    out = world.svc.burst(lambda i: call(world, op, ctx, key, client=clients[i]), 50)
    no_failures(out)
    assert tally(out) == {200: 49, 201: 1}, tally(out)
    bodies = [r.json() for r in out]
    assert all(b == bodies[0] for b in bodies), "every duplicate returns the same body"
    once = snapshot(world, op)
    assert once != before, "the operation took effect"
    assert expect(call(world, op, ctx, key), 200) == bodies[0]
    assert snapshot(world, op) == once


@pytest.mark.parametrize("op", OPS)
def test_concurrent_same_key_with_two_bodies_has_one_winner(world, op):
    ctx = op.setup(world)
    key = new_key()
    clients = [world.svc.fresh_client(op.caller) for _ in range(40)]
    bodies = [op.body(ctx), op.alt_body(ctx)]
    out = world.svc.burst(lambda i: call(world, op, ctx, key, body=bodies[i % 2], client=clients[i]), 40)
    no_failures(out)
    wins = [i for i, r in enumerate(out) if r.status_code == 201]
    assert len(wins) == 1, tally(out)
    w = wins[0]
    for i, r in enumerate(out):
        if i == w:
            continue
        if i % 2 == w % 2:
            assert r.status_code == 200 and r.json() == out[w].json(), (i, r.status_code)
        else:
            expect_error(r, 409, "idempotency_key_reuse")


# ---------------------------------------------------------------- scope (I19)

@pytest.mark.item(2)
def test_keys_are_scoped_per_user_on_payments(world):
    key = new_key()
    a = expect(world.ada.pay("cy", 100, key=key), 201)
    b = expect(world.bob.pay("cy", 100, key=key), 201)
    assert a["payment_id"] != b["payment_id"]
    assert world.cy.balance() == 700


@pytest.mark.item(3)
def test_same_key_on_every_path_is_independent(world):
    key = new_key()
    rq1 = expect(world.bob.ask("ada", 10, key=key), 201)["request_id"]
    rq2 = expect(world.cy.ask("ada", 20), 201)["request_id"]
    expect(world.ada.pay("bob", 5, key=key), 201)
    expect(world.ada.ask("bob", 5, key=key), 201)
    p1 = expect(world.ada.pay_request(rq1, key=key), 201)
    p2 = expect(world.ada.pay_request(rq2, key=key), 201)
    assert p1["request_id"] == rq1 and p2["request_id"] == rq2
    expect(world.ada.split(30, ["ada", "bob"], key=key), 201)


@pytest.mark.item(4)
def test_settlement_key_is_independent_of_other_paths_and_users(svc):
    svc.must_reset(fixture(standard_users(), operators=["u_ada", "u_bob"]))
    ada, bob = svc.client("ada"), svc.client("bob")
    key = new_key()
    expect(ada.pay("cy", 1, key=key), 201)
    t = [{"from_handle": "ada", "to_handle": "dee", "amount": 10}]
    s1 = expect(ada.settle(t, key=key), 201)
    s2 = expect(bob.settle(t, key=key), 201)
    assert s1["settlement_id"] != s2["settlement_id"]
    assert svc.client("dee").balance() == 20


@pytest.mark.item(2)
def test_query_string_is_not_part_of_the_key_path(world):
    """PLAN 3.9: the canonical path has no query string."""
    key = new_key()
    first = expect(world.ada.post("/payments?x=1", json={"to_handle": "bob", "amount": 9}, key=key), 201)
    assert expect(world.ada.post("/payments?y=2", json={"to_handle": "bob", "amount": 9}, key=key), 200) == first
    assert world.ada.balance() == 9_991


@pytest.mark.item(2)
def test_key_refused_for_funds_pays_once_after_funding(world):
    key = new_key()
    expect_error(world.cy.pay("dee", 800, key=key), 409, "insufficient_funds")
    expect(world.ada.pay("cy", 300), 201)
    first = expect(world.cy.pay("dee", 800, key=key), 201)
    assert expect(world.cy.pay("dee", 800, key=key), 200) == first
    assert world.cy.balance() == 0 and world.dee.balance() == 800


@pytest.mark.item(2)
@pytest.mark.parametrize("key", ["x", "a b c", "with:colon/slash?query=1&x", "~!@#$%^&*()_+{}|<>"])
def test_printable_keys_work(world, key):
    first = expect(world.ada.pay("bob", 3, key=key), 201)
    assert expect(world.ada.pay("bob", 3, key=key), 200) == first


@pytest.mark.item(7)
def test_same_key_on_the_seven_paths_is_independent(world):
    ada, bob = world.ada, world.bob
    key = new_key()
    rq = expect(bob.ask("ada", 10, key=key), 201)["request_id"]
    expect(ada.pay("bob", 5, key=key), 201)
    expect(ada.ask("bob", 5, key=key), 201)
    expect(ada.pay_request(rq, key=key), 201)
    expect(ada.split(30, ["ada", "bob"], key=key), 201)
    expect(ada.settle([{"from_handle": "ada", "to_handle": "dee", "amount": 1}], key=key), 201)
    a1 = expect(ada.authorize("bob", 100, key=key), 201)["authorization_id"]
    a2 = expect(ada.authorize("bob", 100, key=new_key()), 201)["authorization_id"]
    p1 = expect(bob.capture(a1, {}, key=key), 201)
    p2 = expect(bob.capture(a2, {}, key=key), 201)
    assert p1["authorization_id"] == a1 and p2["authorization_id"] == a2
    expect(bob.authorize("ada", 100, key=key), 201)
    assert ada.money() == (10_000 - 5 - 10 - 1 - 200, 10_000 - 5 - 10 - 1 - 200, 0)
