"""W20.1-W20.9 — `POST /correction-batches` (stage-4 "Batch corrections"; PLAN 3.3-3.7, 3.9, D95-D100). I1, I2,
I15-I19, I56-I58, I62, I69, I72-I76.

The idempotency scenarios of the tenth path run in test_w2_idempotency.py (`Batches`); concurrency in
test_w20_concurrency.py. Every instant comes from the service (W18.5) or is a seeded past instant.
"""
from __future__ import annotations

import pytest

from support import (BATCH_REVISION_KEYS, EPOCH, FAR_FUTURE, REVISION_KEYS, TWO_53, batch_item as item, check_batch,
                     expect, expect_error, fixture, fmt_instant, instant, new_key, page_snapshot, read_statement,
                     shifted, standard_users, user)
from test_w14_history import seeded
from test_w16_corrections import FIELD_ERRORS, _DROP
from test_w19_refunds import state, uid

pytestmark = pytest.mark.item(20)


@pytest.fixture
def three(world):
    """Ada paid bob 100 (p1); bob paid cy 50, privately (p2); cy paid dee 20 (p3). Ada is the operator."""
    w = world
    w.p1 = expect(w.ada.pay("bob", 100, note="one"), 201)
    w.p2 = expect(w.bob.pay("cy", 50, note="two", visibility="private"), 201)
    w.p3 = expect(w.cy.pay("dee", 20, note="three"), 201)
    w.pids = [w.p1["payment_id"], w.p2["payment_id"], w.p3["payment_id"]]
    return w


def money(w) -> tuple:
    return tuple(w.svc.client(h).money()[0] for h in ("ada", "bob", "cy", "dee"))


# ---------------------------------------------------------------- W20.1 the batch result

def test_a_batch_returns_one_revision_per_item_in_input_order(three):
    """I72, F34-F36: 201 {correction_batch_id, recorded_at, revisions}; each revision n + 1 with the batch's id and
    recorded_at, strictly later than each payment's previous recorded_at; every difference moved."""
    w = three
    items = [item(w.p3, 1, 10, reason="r3"), item(w.p1, 1, 80, reason="r1"), item(w.p2, 1, 40, reason="r2")]
    b = check_batch(expect(w.ada.batch(items), 201), 3)
    assert [r["payment_id"] for r in b["revisions"]] == [w.p3["payment_id"], w.p1["payment_id"], w.p2["payment_id"]]
    for r, it in zip(b["revisions"], items):
        assert (r["revision"], r["amount"], r["effective_at"], r["reason"]) == \
            (2, it["amount"], it["effective_at"], it["reason"]), r
    for p in (w.p1, w.p2, w.p3):
        assert instant(b["recorded_at"]) > instant(p["created_at"]), "D100"
    # before: ada 9900, bob 2550, cy 530, dee 20; p3 -10 (cy +10, dee -10), p1 -20 (ada +20, bob -20), p2 -10 (bob +10, cy -10)
    assert money(w) == (9_920, 2_540, 530, 10), "I57: every item's difference between that payment's two wallets"
    for p, c in ((w.p1, w.ada), (w.p2, w.bob), (w.p3, w.dee)):
        revs = c.revisions(p["payment_id"])
        assert [set(r) for r in revs] == [REVISION_KEYS, BATCH_REVISION_KEYS], "D97"
        assert revs[1] == [r for r in b["revisions"] if r["payment_id"] == p["payment_id"]][0]


@pytest.mark.parametrize("effective_at", ["2026-01-01t00:00:00.123456789z", "2026-01-01T05:30:00+05:30",
                                          "2026-01-01T00:00:00-00:00", "2025-12-31T23:59:59.5-23:59"])
def test_effective_at_is_kept_exactly_as_sent(three, effective_at):
    b = expect(three.ada.batch([item(three.p1, 1, 100, effective_at)]), 201)
    assert b["revisions"][0]["effective_at"] == effective_at
    assert three.bob.revisions(three.p1["payment_id"])[1]["effective_at"] == effective_at


def test_a_batch_appends_revision_n_plus_1_and_other_revisions_keep_six_fields(three):
    """I56 (amended), D97."""
    w = three
    r2 = expect(w.ada.correct(w.p1["payment_id"], 1, 90, w.p1["created_at"]), 201)
    b = check_batch(expect(w.ada.batch([item(w.p1, 2, 70), item(w.p3, 1, 15)]), 201), 2)
    assert [r["revision"] for r in b["revisions"]] == [3, 2]
    revs = w.bob.revisions(w.p1["payment_id"])
    assert [set(r) for r in revs] == [REVISION_KEYS, REVISION_KEYS, BATCH_REVISION_KEYS]
    assert revs[1] == r2 and revs[2] == b["revisions"][0]
    r4 = expect(w.ada.correct(w.p1["payment_id"], 3, 60, w.p1["created_at"]), 201)
    assert set(r4) == REVISION_KEYS and instant(r4["recorded_at"]) > instant(b["recorded_at"])
    assert [r["revision"] for r in w.ada.revisions(w.p1["payment_id"])] == [1, 2, 3, 4]


def test_every_batch_has_its_own_id_and_a_later_recorded_at(three):
    w = three
    b1 = check_batch(expect(w.ada.batch([item(w.p1, 1, 99)]), 201), 1)
    b2 = check_batch(expect(w.ada.batch([item(w.p2, 1, 49)]), 201), 1)
    b3 = check_batch(expect(w.ada.batch([item(w.p1, 2, 98), item(w.p2, 2, 48)]), 201), 2)
    assert len({b["correction_batch_id"] for b in (b1, b2, b3)}) == 3
    assert instant(b1["recorded_at"]) < instant(b2["recorded_at"]) < instant(b3["recorded_at"])


# ---------------------------------------------------------------- W20.2 rights

def test_a_batch_needs_a_token(three):
    w = three
    body = {"corrections": [item(w.p1, 1, 90)]}
    for c in (w.svc.api(), w.svc.api("not-a-token")):
        expect_error(c.batch(body=body), 401, "unauthenticated")
        expect_error(c.post("/correction-batches", content=b"{nope"), 401, "unauthenticated")


def test_a_non_operator_is_403_before_the_key_and_the_body(three):
    """D95: as POST /settlements, 403 comes before the key and the body."""
    w = three
    before = state(w.svc, w.pids)
    body = {"corrections": [item(w.p1, 1, 90)]}
    for c in (w.bob, w.cy):
        expect_error(c.batch(body=body), 403, "forbidden")
        expect_error(c.post("/correction-batches", json=body), 403, "forbidden")                  # no key
        expect_error(c.post("/correction-batches", json=body, key="k" * 256), 403, "forbidden")
        expect_error(c.post("/correction-batches", content=b"{nope", key=new_key()), 403, "forbidden")
        expect_error(c.batch(body={"corrections": []}), 403, "forbidden")
    expect_error(w.bob.batch([item(w.p2, 1, 40)]), 403, "forbidden")      # bob sent p2 and is still no operator
    assert state(w.svc, w.pids) == before


def test_an_operator_may_correct_payments_between_other_users(three):
    """D96: any parties, private payments included; reading the revisions stays with the parties."""
    w = three
    b = expect(w.ada.batch([item(w.p2, 1, 45), item(w.p3, 1, 25)]), 201)
    assert w.bob.revisions(w.p2["payment_id"])[-1] == b["revisions"][0]
    assert w.dee.revisions(w.p3["payment_id"])[-1] == b["revisions"][1]
    expect_error(w.ada.revisions_resp(w.p2["payment_id"]), 404, "not_found")
    assert w.p2["payment_id"] not in [p["payment_id"] for p in w.ada.feed()]
    assert money(w) == (9_900, 2_555, 520, 25)


def test_an_operator_may_correct_request_settlement_and_seeded_payments(svc):
    svc.must_reset(fixture(standard_users(), operators=["u_ada"],
                           payments=[seeded("p_s", "bob", "cy", 40, "2026-01-01T00:00:00Z")]))
    ada, bob, cy = svc.client("ada"), svc.client("bob"), svc.client("cy")
    rq = expect(cy.ask("bob", 30), 201)["request_id"]
    rp = expect(bob.pay_request(rq), 201)
    st = expect(ada.settle([{"from_handle": "bob", "to_handle": "dee", "amount": 20},
                            {"from_handle": "cy", "to_handle": "dee", "amount": 10}]), 201)
    m, at = st["payments"], st["committed_at"]
    check_batch(expect(ada.batch([item(rp, 1, 25), item("p_s", 1, 35, "2026-01-01T00:00:00Z"),
                                  item(m[0], 1, 15, at), item(m[1], 1, 5, at)]), 201), 4)
    assert [svc.client(h).money()[0] for h in ("ada", "bob", "cy", "dee")] == [10_000, 2_465, 515, 20]


# ---------------------------------------------------------------- W20.4 shape

def _shape_cases(w) -> dict:
    p1 = w.p1
    unknown = item("p_nope", 1, 0, p1["created_at"])
    return {
        "corrections missing": {},
        "corrections null": {"corrections": None},
        "corrections an object": {"corrections": unknown},
        "corrections a string": {"corrections": "p_nope"},
        "corrections a number": {"corrections": 1},
        "corrections true": {"corrections": True},
        "corrections empty": {"corrections": []},
        "33 items": {"corrections": [item(f"p_nope_{i}", 1, 0, p1["created_at"]) for i in range(33)]},
        "an element a number": {"corrections": [unknown, 5]},
        "an element null": {"corrections": [unknown, None]},
        "an element an array": {"corrections": [unknown, [p1["payment_id"]]]},
        "an element a string": {"corrections": [unknown, p1["payment_id"]]},
        "two items with one payment_id": {"corrections": [item(p1, 1, 90), item(p1, 1, 80)]},
        "two unknown items with one payment_id": {"corrections": [unknown, dict(unknown, amount=1)]},
    }


SHAPES = ["corrections missing", "corrections null", "corrections an object", "corrections a string",
          "corrections a number", "corrections true", "corrections empty", "33 items", "an element a number",
          "an element null", "an element an array", "an element a string", "two items with one payment_id",
          "two unknown items with one payment_id"]


@pytest.mark.parametrize("case", SHAPES)
def test_a_bad_shape_is_422_before_any_item(three, case):
    """F22, D95: checked over every element before any item, so an unknown payment in item 1 does not answer."""
    w = three
    before = state(w.svc, w.pids)
    k = new_key()
    expect_error(w.ada.batch(body=_shape_cases(w)[case], key=k), 422, "validation_failed")
    assert state(w.svc, w.pids) == before
    expect(w.ada.batch([item(w.p1, 1, 90)], key=k), 201)


@pytest.mark.parametrize("raw, status, code", [
    (b"{nope", 400, "malformed_request"), (b"[]", 400, "malformed_request"), (b'"x"', 400, "malformed_request"),
    (b"", 400, "malformed_request"), (b"null", 400, "malformed_request"), (b"{}", 422, "validation_failed")])
def test_body_shape(three, raw, status, code):
    expect_error(three.ada.post("/correction-batches", content=raw, key=new_key()), status, code)


def test_the_common_steps(three):
    """PLAN 3.9 steps 1-7 for the operator: key, body, claimed key, shape."""
    w = three
    expect_error(w.ada.post("/correction-batches", content=b"{nope"), 400, "missing_idempotency_key")
    expect_error(w.ada.post("/correction-batches", content=b"{nope", key="k" * 256), 422, "validation_failed")
    expect_error(w.ada.post("/correction-batches", content=b"{nope", key=new_key()), 400, "malformed_request")
    k = new_key()
    b = expect(w.ada.batch([item(w.p1, 1, 90)], key=k), 201)
    expect_error(w.ada.batch([], key=k), 409, "idempotency_key_reuse")
    assert expect(w.ada.batch([item(w.p1, 1, 90)], key=k), 200) == b
    expect_error(w.ada.get("/correction-batches"), 404, "not_found")
    expect_error(w.ada.post("/correction-batches/x", json={"corrections": []}, key=new_key()), 404, "not_found")


def test_thirty_two_items_are_accepted(world):
    """W20.4 (critic plan review 8)."""
    pays = [expect(world.ada.pay("bob", 10), 201) for _ in range(32)]
    b = check_batch(expect(world.ada.batch([item(p, 1, 9) for p in pays]), 201), 32)
    assert [r["payment_id"] for r in b["revisions"]] == [p["payment_id"] for p in pays]
    assert world.ada.balance() == 10_000 - 32 * 9


def test_unknown_top_level_fields_are_ignored(three):
    w = three
    b = check_batch(expect(w.ada.batch(body={"corrections": [item(w.p1, 1, 90)], "correction_batch_id": "cb_mine",
                                             "recorded_at": EPOCH, "atomic": False}), 201), 1)
    assert b["correction_batch_id"] != "cb_mine" and b["recorded_at"] != EPOCH


# ---------------------------------------------------------------- W20.5 items in input order

def _item(p, **over) -> dict:
    b = item(p, 1, 60, reason="fix")
    for k, v in over.items():
        if v is _DROP:
            b.pop(k)
        else:
            b[k] = v
    return b


ITEM_ERRORS = {**FIELD_ERRORS,
               "payment_id missing": {"payment_id": _DROP}, "payment_id null": {"payment_id": None},
               "payment_id number": {"payment_id": 5}, "payment_id true": {"payment_id": True},
               "payment_id array": {"payment_id": ["p"]}, "payment_id object": {"payment_id": {"id": "p"}}}


@pytest.mark.parametrize("over", ITEM_ERRORS.values(), ids=ITEM_ERRORS.keys())
def test_invalid_item_fields_are_422_and_change_nothing(three, over):
    """F23: every item has the ordinary correction fields and validation."""
    w = three
    before = state(w.svc, w.pids)
    k = new_key()
    expect_error(w.ada.batch([_item(w.p1, **over)], key=k), 422, "validation_failed")
    expect_error(w.ada.batch([item(w.p2, 1, 40), _item(w.p1, **over)]), 422, "validation_failed")
    assert state(w.svc, w.pids) == before
    expect(w.ada.batch([_item(w.p1)], key=k), 201)


def test_an_effective_at_later_than_now_is_422(three):
    """F37, D81."""
    w = three
    mark = w.ada.service_now("cy")
    before = state(w.svc, w.pids)
    for ahead in (1, 3600):
        expect_error(w.ada.batch([item(w.p1, 1, 60, shifted(mark, seconds=ahead, digits=3))]), 422, "validation_failed")
    expect_error(w.ada.batch([item(w.p2, 1, 40), item(w.p1, 1, 60, FAR_FUTURE)]), 422, "validation_failed")
    assert state(w.svc, w.pids) == before
    expect(w.ada.batch([item(w.p1, 1, 60, mark)]), 201)


def test_no_clock_tolerance_on_effective_at(three):
    """D81 (critic plan review 6): 200 ms after a fresh service time mark is later than now. A slow host that accepts
    it must still have recorded it at or after its effective_at."""
    w = three
    for n in range(3):
        mark = w.ada.service_now("cy")
        at = shifted(mark, 200_000, digits=3)
        rev = len(w.bob.revisions(w.p1["payment_id"]))
        r = w.ada.batch([item(w.p1, rev, 50 + n, at)])
        if r.status_code == 201:
            assert instant(r.json()["recorded_at"]) >= instant(at), f"D81: accepted before its effective_at: {r.json()}"
        else:
            expect_error(r, 422, "validation_failed")


def test_item_resource_errors(three):
    """F24, F17, F18: unknown 404, a capture or a refund 422 linked_payment_immutable, stale 409, below the refunded
    total 422 refund_exceeds_payment (one unit below; equal is allowed)."""
    w = three
    a = expect(w.ada.authorize("bob", 100), 201)
    cap = expect(w.bob.capture(a["authorization_id"], {"amount": 50}), 201)
    ref = expect(w.dee.refund(w.p3["payment_id"], 5), 201)
    expect(w.ada.correct(w.p1["payment_id"], 1, 90, w.p1["created_at"]), 201)
    before = state(w.svc, w.pids + [cap["payment_id"], ref["payment_id"]])
    expect_error(w.ada.batch([item(w.p2, 1, 40), item("p_nope", 1, 0, w.p2["created_at"])]), 404, "not_found")
    for linked in (cap, ref):
        for amount in (linked["amount"], 0):
            expect_error(w.ada.batch([item(linked, 1, amount)]), 422, "linked_payment_immutable")
    expect_error(w.ada.batch([item(w.p2, 1, 40), item(w.p1, 1, 80)]), 409, "stale_revision")
    expect_error(w.ada.batch([item(w.p1, 3, 80)]), 409, "stale_revision")
    expect_error(w.ada.batch([item(w.p3, 1, 4)]), 422, "refund_exceeds_payment")
    assert state(w.svc, w.pids + [cap["payment_id"], ref["payment_id"]]) == before
    expect(w.ada.batch([item(w.p1, 2, 80), item(w.p3, 1, 5)]), 201)


def test_the_first_failing_item_decides(three):
    """F30, D95: item errors in input order; within an item, fields, then 404, linked, stale, the refunded total."""
    w = three
    expect(w.ada.correct(w.p1["payment_id"], 1, 90, w.p1["created_at"]), 201)       # p1 is at revision 2
    a = expect(w.ada.authorize("bob", 100), 201)
    cap = expect(w.bob.capture(a["authorization_id"], {"amount": 50}), 201)
    expect(w.dee.refund(w.p3["payment_id"], 5), 201)                               # p3 refunded 5
    bad_field = item(w.p2, 1, -1)
    unknown = item("p_nope", 1, 10, w.p2["created_at"])
    stale = item(w.p1, 1, 80)
    linked = item(cap, 1, 10)
    below = item(w.p3, 1, 4)
    ok = item(w.p2, 1, 45)
    cases = [
        ([unknown, bad_field], 404, "not_found"),
        ([bad_field, unknown], 422, "validation_failed"),
        ([ok, stale], 409, "stale_revision"),
        ([stale, linked], 409, "stale_revision"),
        ([linked, stale], 422, "linked_payment_immutable"),
        ([below, unknown], 422, "refund_exceeds_payment"),
        ([unknown, below], 404, "not_found"),
        ([ok, below, stale], 422, "refund_exceeds_payment"),
        ([item("p_nope", 1, -1, w.p2["created_at"])], 422, "validation_failed"),
        ([item(cap, 7, 10)], 422, "linked_payment_immutable"),
        ([item(w.p3, 2, 4)], 409, "stale_revision"),
    ]
    before = state(w.svc, w.pids)
    for items, status, code in cases:
        expect_error(w.ada.batch(items), status, code)
    assert state(w.svc, w.pids) == before


def test_unknown_item_fields_are_ignored(three):
    """F29."""
    w = three
    it = {**item(w.p1, 1, 70), "revision": 9, "recorded_at": EPOCH, "correction_batch_id": "cb_mine",
          "to_user_id": "u_cy", "visibility": "public", "settlement_id": "s_x"}
    b = check_batch(expect(w.ada.batch([it]), 201), 1)
    r = b["revisions"][0]
    assert (r["revision"], r["amount"]) == (2, 70) and r["recorded_at"] != EPOCH and r["correction_batch_id"] != "cb_mine"
    assert [p for p in w.bob.feed() if p["payment_id"] == w.p1["payment_id"]] == [w.p1], "parties never change"


def test_a_batch_lowering_a_payment_to_its_refunded_total_leaves_nothing_to_refund(three):
    """W19.3 (critic plan review 7)."""
    w = three
    expect(w.bob.refund(w.p1["payment_id"], 30), 201)
    expect_error(w.ada.batch([item(w.p1, 1, 29)]), 422, "refund_exceeds_payment")
    expect(w.ada.batch([item(w.p1, 1, 30)]), 201)
    expect_error(w.bob.refund(w.p1["payment_id"], 1), 422, "refund_exceeds_payment")
    assert money(w)[:2] == (10_000, 2_450)


# ---------------------------------------------------------------- W20.6 settlements

@pytest.fixture
def settled(world):
    """Ada settled ada->cy 100, bob->dee 50 and cy->bob 30 (st), and paid dee 10 (q)."""
    w = world
    w.transfers = [{"from_handle": "ada", "to_handle": "cy", "amount": 100},
                   {"from_handle": "bob", "to_handle": "dee", "amount": 50},
                   {"from_handle": "cy", "to_handle": "bob", "amount": 30}]
    w.st_key, w.q_key = new_key(), new_key()
    w.st = expect(w.ada.settle(w.transfers, key=w.st_key), 201)
    w.m, w.at = w.st["payments"], w.st["committed_at"]
    w.q = expect(w.ada.pay("dee", 10, key=w.q_key), 201)
    w.pids = [x["payment_id"] for x in w.m] + [w.q["payment_id"]]
    return w


def whole(w, amounts=None, at=None) -> list[dict]:
    amounts = amounts or [x["amount"] for x in w.m]
    return [item(x, 1, a, at or w.at) for x, a in zip(w.m, amounts)]


def test_some_but_not_all_members_is_incomplete_settlement(settled):
    """F26, I73."""
    w = settled
    before = state(w.svc, w.pids)
    m = w.m
    for subset in ([m[0]], [m[0], m[1]], [m[2], m[0]]):
        expect_error(w.ada.batch([item(x, 1, x["amount"] - 1, w.at) for x in subset]), 422, "incomplete_settlement")
    expect_error(w.ada.batch([item(w.q, 1, 5), item(m[1], 1, 40, w.at)]), 422, "incomplete_settlement")
    assert state(w.svc, w.pids) == before


def test_members_need_one_effective_instant(settled):
    """F27, I73, D98: 1 µs apart is 422 validation_failed."""
    w = settled
    before = state(w.svc, w.pids)
    expect_error(w.ada.batch(whole(w)[:2] + [item(w.m[2], 1, 30, shifted(w.at, -1))]), 422, "validation_failed")
    expect_error(w.ada.batch([item(w.m[0], 1, 100, "2026-01-01T00:00:00Z")] + whole(w)[1:]), 422, "validation_failed")
    assert state(w.svc, w.pids) == before


def test_one_instant_in_any_spelling_is_accepted(settled):
    """D98: Z, +05:30 and more fraction digits; each revision keeps its own spelling."""
    w = settled
    spell = [w.at, fmt_instant(w.at, digits=6, offset="Z"), fmt_instant(w.at, digits=9, offset="+05:30", t="t")]
    b = check_batch(expect(w.ada.batch([item(x, 1, x["amount"] - 5, s) for x, s in zip(w.m, spell)]), 201), 3)
    assert [r["effective_at"] for r in b["revisions"]] == spell
    assert money(w) == (10_000 - 100 - 10 + 5, 2_500 - 50 + 30 + 5 - 5, 500 + 100 - 30 - 5 + 5, 50 + 10 - 5)


def test_member_instants_that_differ_only_in_trailing_zeros_are_one_instant(settled):
    """W20.6 (critic plan review 4)."""
    w = settled
    spell = ["2026-01-01T00:00:00.5Z", "2026-01-01T00:00:00.500Z", "2026-01-01T05:30:00.500000+05:30"]
    b = expect(w.ada.batch([item(x, 1, x["amount"], s) for x, s in zip(w.m, spell)]), 201)
    assert [r["effective_at"] for r in b["revisions"]] == spell
    late = ["2026-01-01T00:00:00.5Z", "2026-01-01T00:00:00.500001Z", "2026-01-01T00:00:00.5Z"]
    expect_error(w.ada.batch([item(x, 2, x["amount"], s) for x, s in zip(w.m, late)]), 422, "validation_failed")


def test_a_whole_settlement_with_ordinary_payments(settled):
    w = settled
    b = check_batch(expect(w.ada.batch([item(w.q, 1, 0)] + whole(w, [0, 0, 0])), 201), 4)
    assert b["revisions"][0]["payment_id"] == w.q["payment_id"]
    assert money(w) == (10_000, 2_500, 500, 0)


def test_single_corrections_of_members_stay_immutable(settled):
    """F28, I62."""
    w = settled
    expect_error(w.ada.correct(w.m[0]["payment_id"], 1, 90, w.at), 422, "linked_payment_immutable")
    expect_error(w.bob.correct(w.m[1]["payment_id"], 1, 40, w.at), 422, "linked_payment_immutable")
    expect(w.ada.batch(whole(w, [90, 40, 30])), 201)
    expect_error(w.ada.correct(w.m[0]["payment_id"], 2, 80, w.at), 422, "linked_payment_immutable")
    expect(w.ada.correct(w.q["payment_id"], 1, 5, w.q["created_at"]), 201)


def test_completeness_is_checked_before_the_shared_instant(settled):
    w = settled
    expect_error(w.ada.batch([item(w.m[0], 1, 90, w.at), item(w.m[1], 1, 50, shifted(w.at, -1))]), 422,
                 "incomplete_settlement")


def test_two_settlements_in_one_batch(settled):
    w = settled
    st2 = expect(w.ada.settle([{"from_handle": "dee", "to_handle": "ada", "amount": 5},
                               {"from_handle": "ada", "to_handle": "bob", "amount": 7}]), 201)
    n, at2 = st2["payments"], st2["committed_at"]
    expect_error(w.ada.batch(whole(w) + [item(n[0], 1, 5, at2)]), 422, "incomplete_settlement")
    check_batch(expect(w.ada.batch(whole(w) + [item(n[0], 1, 4, at2), item(n[1], 1, 7, at2)]), 201), 5)


def test_members_of_a_seeded_settlement(svc):
    """D98: members are the payments with one settlement_id, seeded ones included; a one-member settlement."""
    svc.must_reset(fixture(standard_users(), operators=["u_ada"], payments=[
        seeded("p_m1", "ada", "bob", 100, "2026-01-01T00:00:00Z", settlement_id="s_seed"),
        seeded("p_m2", "bob", "cy", 40, "2026-01-01T00:00:00Z", settlement_id="s_seed"),
        seeded("p_one", "cy", "dee", 10, "2026-01-01T00:00:00Z", settlement_id="s_two")]))
    ada = svc.client("ada")
    expect_error(ada.batch([item("p_m1", 1, 90, "2026-01-01T00:00:00Z")]), 422, "incomplete_settlement")
    expect(ada.batch([item("p_m1", 1, 90, "2026-01-01T00:00:00Z"), item("p_m2", 1, 40, "2026-01-01T05:30:00+05:30")]),
           201)
    # dee holds 0, so lowering p_one would debit dee: the funds rule holds for a one-member settlement (I74, D99)
    expect_error(ada.batch([item("p_one", 1, 5, "2026-01-01T00:00:00Z")]), 409, "insufficient_funds")
    expect(ada.batch([item("p_one", 1, 15, "2026-01-01T00:00:00Z")]), 201)            # cy pays 5 more


def test_a_refund_of_a_member_is_not_a_member(settled):
    """F41, I75: the refund is not part of the settlement, so the batch names exactly the members."""
    w = settled
    r = expect(w.cy.refund(w.m[0]["payment_id"], 40), 201)
    expect_error(w.ada.batch(whole(w) + [item(r, 1, 40)]), 422, "linked_payment_immutable")
    expect_error(w.ada.batch(whole(w, [39, 50, 30])), 422, "refund_exceeds_payment")
    check_batch(expect(w.ada.batch(whole(w, [40, 50, 30])), 201), 3)


# ---------------------------------------------------------------- W20.7 funds and history

def test_affordability_is_the_combined_effect(world):
    """F32, I74, D99: dee cannot afford the second item alone, but the first one pays for it."""
    p1 = expect(world.ada.pay("dee", 500), 201)
    p2 = expect(world.dee.pay("ada", 500), 201)                   # dee holds 0
    expect_error(world.dee.correct(p2["payment_id"], 1, 1_000, p2["created_at"]), 409, "insufficient_funds")
    b = check_batch(expect(world.ada.batch([item(p2, 1, 1_000), item(p1, 1, 1_000)]), 201), 2)
    assert world.dee.money() == (0, 0, 0) and world.ada.money() == (10_000, 10_000, 0)
    assert b["revisions"][0]["payment_id"] == p2["payment_id"]


def test_available_at_exactly_zero_is_accepted_and_one_unit_more_is_refused(world):
    """W20.7 (critic plan review 3): without holds."""
    p1 = expect(world.ada.pay("dee", 500), 201)
    p2 = expect(world.dee.pay("cy", 300), 201)                    # dee 200
    before = state(world.svc, [p1["payment_id"], p2["payment_id"]])
    expect_error(world.ada.batch([item(p2, 1, 600), item(p1, 1, 599)]), 409, "insufficient_funds")
    assert state(world.svc, [p1["payment_id"], p2["payment_id"]]) == before
    expect(world.ada.batch([item(p2, 1, 600), item(p1, 1, 600)]), 201)
    assert world.dee.money() == (0, 0, 0)


def test_held_funds_count_in_the_combined_effect(world):
    """F32, I74 (critic plan review 3): an open hold makes the difference between 0 and one unit below."""
    p1 = expect(world.ada.pay("dee", 1_000), 201)
    expect(world.dee.authorize("cy", 500), 201)
    p2 = expect(world.dee.pay("cy", 400), 201)                    # dee: total 600, held 500, available 100
    before = state(world.svc, [p1["payment_id"], p2["payment_id"]])
    expect_error(world.ada.batch([item(p2, 1, 600), item(p1, 1, 1_099)]), 409, "insufficient_funds")
    assert state(world.svc, [p1["payment_id"], p2["payment_id"]]) == before
    expect(world.ada.batch([item(p2, 1, 600), item(p1, 1, 1_100)]), 201)
    assert world.dee.money() == (500, 0, 500)


def test_the_2_53_guard(svc):
    svc.must_reset(fixture([user("ada", 1_000), user("bob", TWO_53 - 10)], operators=["u_ada"]))
    ada, bob = svc.client("ada"), svc.client("bob")
    p = expect(ada.pay("bob", 5), 201)                            # bob: 2^53 - 5
    expect_error(ada.batch([item(p, 1, 11)]), 422, "validation_failed")
    expect(ada.batch([item(p, 1, 10)]), 201)
    assert bob.balance() == TWO_53


def test_the_combined_funds_come_before_the_guard(svc):
    """PLAN 3.9 batch steps 11 and 12 (W22.7): the first item credits ada above 2^53 and the second debits dee below
    0, so a check that judged one item at a time would answer the guard. The funds answer: 409."""
    svc.must_reset(fixture([user("ada", TWO_53 - 300), user("bob", 1_000), user("cy", 1_000), user("dee", 0)],
                           operators=["u_ada"]))
    ada, cy, dee = svc.client("ada"), svc.client("cy"), svc.client("dee")
    p1 = expect(ada.pay("bob", 100), 201)                         # ada 2^53 - 400, bob 1100
    expect(cy.pay("ada", 390), 201)                               # ada 2^53 - 10, cy 610
    p2 = expect(cy.pay("dee", 100), 201)                          # cy 510, dee 100
    expect(dee.pay("bob", 60), 201)                               # dee 40, bob 1160
    pids = [p1["payment_id"], p2["payment_id"]]
    before = state(svc, pids)
    expect_error(ada.batch([item(p1, 1, 0), item(p2, 1, 0)]), 409, "insufficient_funds")     # ada +100, dee -100
    expect_error(ada.batch([item(p1, 1, 89), item(p2, 1, 60)]), 422, "validation_failed")    # the guard alone
    expect_error(ada.batch([item(p1, 1, 90), item(p2, 1, 59)]), 409, "insufficient_funds")   # the funds alone
    assert state(svc, pids) == before
    check_batch(expect(ada.batch([item(p1, 1, 90), item(p2, 1, 60)]), 201), 2)
    assert ada.balance() == TWO_53 and dee.balance() == 0


def test_the_guard_comes_before_history(svc):
    """PLAN 3.9 batch steps 12 and 13 (W22.7): the first item, backdated before dee's money arrived, takes dee below 0
    then; the second takes bob above 2^53. Both are affordable now. The guard answers: 422."""
    svc.must_reset(fixture([user("ada", 1_000), user("bob", TWO_53 - 15), user("cy", 1_000), user("dee", 0)],
                           operators=["u_ada"]))
    ada, bob, cy, dee = svc.client("ada"), svc.client("bob"), svc.client("cy"), svc.client("dee")
    t1 = expect(cy.pay("dee", 500), 201)["created_at"]            # dee 500
    ph = expect(dee.pay("cy", 50), 201)                           # dee 450
    pg = expect(ada.pay("bob", 5), 201)                           # bob 2^53 - 10
    pids, early = [ph["payment_id"], pg["payment_id"]], shifted(t1, -1)
    before = state(svc, pids)
    expect_error(ada.batch([item(ph, 1, 60, early), item(pg, 1, 100)]), 422, "validation_failed")   # both fail
    expect_error(ada.batch([item(ph, 1, 60, early), item(pg, 1, 15)]), 409, "historical_overdraft")  # history alone
    expect_error(ada.batch([item(ph, 1, 60), item(pg, 1, 16)]), 422, "validation_failed")           # the guard alone
    assert state(svc, pids) == before
    check_batch(expect(ada.batch([item(ph, 1, 60), item(pg, 1, 15)]), 201), 2)
    assert dee.balance() == 440 and bob.balance() == TWO_53


# Seeded history (consistent): dee opens with 300, pays cy 200 at t1, gets 500 from ada at t2, pays bob 100 at t3.
T1, T2, T3 = "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"


def combined_fixture() -> dict:
    return fixture([user("ada", 10_000), user("bob", 2_500), user("cy", 500), user("dee", 500)], operators=["u_ada"],
                   payments=[seeded("h_1", "dee", "cy", 200, T1), seeded("h_2", "ada", "dee", 500, T2),
                             seeded("h_3", "dee", "bob", 100, T3)])


def test_history_is_checked_with_every_new_revision_together(svc):
    """F30, I58 (amended): each item alone keeps dee at or above 0 at t1; together they take her to -50."""
    a = item("h_1", 1, 250, T1)
    b = item("h_3", 1, 100, T1)
    for alone in (a, b):
        svc.must_reset(combined_fixture())
        expect(svc.client("ada").batch([alone]), 201)
    svc.must_reset(combined_fixture())
    before = state(svc, ["h_1", "h_3"])
    expect_error(svc.client("ada").batch([a, b]), 409, "historical_overdraft")
    assert state(svc, ["h_1", "h_3"]) == before


def test_a_dip_between_two_items_instants_is_historical_overdraft(svc):
    """W20.7 (critic plan review 5): dee's payment to bob moves before her credit from ada, and the credit stays
    at t2; dee is at -100 only between the two instants."""
    svc.must_reset(combined_fixture())
    ada = svc.client("ada")
    shift = "2026-01-01T12:00:00Z"
    expect_error(ada.batch([item("h_3", 1, 200, shift), item("h_2", 1, 500, T2)]), 409, "historical_overdraft")
    expect(ada.batch([item("h_3", 1, 100, shift), item("h_2", 1, 500, T2)]), 201)
    assert svc.client("dee").total_at(shift) == 0


def test_a_debit_created_first_combines_with_a_credit_created_after_it(svc):
    """W20.7 (critic plan review 5, as K12): one instant combines both movements."""
    svc.must_reset(fixture([user("ada", 10_000), user("bob", 2_500), user("cy", 500), user("dee", 300)],
                           operators=["u_ada"]))
    dee, ada = svc.client("dee"), svc.client("ada")
    debit = expect(dee.pay("cy", 300), 201)
    credit = expect(ada.pay("dee", 500), 201)
    t = credit["created_at"]
    b = expect(ada.batch([item(debit, 1, 500, t)]), 201)
    assert b["revisions"][0]["effective_at"] == t
    assert dee.total_at(t) == 300 and dee.total_at(shifted(t, -1)) == 300
    assert dee.money() == (300, 300, 0)


def test_a_past_hold_counts_in_the_batch_history_check(svc):
    """I58 with section 3.8: available at a past instant, while a since-voided hold was open."""
    svc.must_reset(combined_fixture())
    dee = svc.client("dee")
    a = expect(dee.authorize("cy", 300), 201)
    expect(dee.void(a["authorization_id"]), 200)
    t = a["created_at"]
    expect_error(svc.client("ada").batch([item("h_3", 1, 450, t)]), 409, "historical_overdraft")
    expect(svc.client("ada").batch([item("h_3", 1, 300, t)]), 201)
    assert dee.money() == (300, 300, 0)


def test_the_order_after_the_items(settled):
    """F30, D95: completeness, then the shared instant, then current funds, then history."""
    w = settled
    unaffordable = item(w.q, 1, 1_000_000_000)
    expect_error(w.ada.batch([unaffordable, item(w.m[0], 1, 100, w.at)]), 422, "incomplete_settlement")
    expect_error(w.ada.batch([unaffordable] + whole(w)[:2] + [item(w.m[2], 1, 30, shifted(w.at, -1))]), 422,
                 "validation_failed")
    expect_error(w.ada.batch([unaffordable] + whole(w)), 409, "insufficient_funds")
    p1 = expect(w.ada.pay("dee", 500), 201)
    p2 = expect(w.dee.pay("cy", 560), 201)                        # dee holds 0
    # Moving p1 after p2 and lowering it is both unaffordable now and an overdraft in the past: funds answer.
    later = w.ada.service_now("bob")
    expect_error(w.ada.batch([item(p1, 1, 400, later)]), 409, "insufficient_funds")
    expect_error(w.ada.batch([item(p1, 1, 500, later)]), 409, "historical_overdraft")
    assert p2["amount"] == 560


# ---------------------------------------------------------------- W20.8 a rejected batch changes nothing

def test_a_rejected_batch_changes_nothing_and_claims_no_key(three):
    """F33, I72: balances, revisions, statements, snapshots, and the key."""
    w = three
    me = uid(w.svc, "bob")
    snap = read_statement(w.bob, me)
    before = state(w.svc, w.pids)
    k = new_key()
    for items, status in (([item(w.p1, 1, 10 ** 9)], 409), ([item(w.p1, 2, 50)], 409),
                          ([item(w.p1, 1, 50), item("p_nope", 1, 0, w.p1["created_at"])], 404), ([], 422)):
        assert w.ada.batch(items, key=k).status_code == status
    assert state(w.svc, w.pids) == before
    assert page_snapshot(w.bob, me, snap.snapshot)[0] == snap.entries
    b = expect(w.ada.batch([item(w.p1, 1, 50)], key=k), 201)
    assert expect(w.ada.batch([item(w.p1, 1, 50)], key=k), 200) == b


# ---------------------------------------------------------------- W20.9 originals and history

def test_originals_replays_and_settlement_responses_stay(settled):
    """F38, I75."""
    w = settled
    feeds = {h: w.svc.client(h).feed() for h in ("ada", "bob", "cy", "dee")}
    expect(w.ada.batch([item(w.q, 1, 0)] + whole(w, [0, 0, 0])), 201)
    assert expect(w.ada.settle(w.transfers, key=w.st_key), 200) == w.st
    assert expect(w.ada.pay("dee", 10, key=w.q_key), 200) == w.q
    assert {h: w.svc.client(h).feed() for h in feeds} == feeds, "the feed shows the original payments"


def test_new_statements_use_the_batch_and_old_snapshots_do_not(three):
    """F39, I76, W20.9: known_at 1 µs before the batch's recorded_at shows the previous revisions, at it the new."""
    w = three
    me = uid(w.svc, "bob")
    snap = read_statement(w.bob, me)
    b = expect(w.ada.batch([item(w.p1, 1, 0), item(w.p2, 1, 30, T1)]), 201)
    rec = b["recorded_at"]
    st = read_statement(w.bob, me)
    assert st.ids() == [w.p2["payment_id"], w.p1["payment_id"]]
    assert [(e["revision"], e["delta"], e["effective_at"]) for e in st.entries] == \
        [(2, -30, T1), (2, 0, w.p1["created_at"])], "a payment corrected to 0 is one entry with delta 0"
    old = read_statement(w.bob, me, known_at=shifted(rec, -1))
    assert [(e["payment"]["payment_id"], e["revision"], e["delta"]) for e in old.entries] == \
        [(w.p1["payment_id"], 1, 100), (w.p2["payment_id"], 1, -50)]
    at = read_statement(w.bob, me, known_at=rec)
    assert at.entries == st.entries
    assert w.bob.me_at(None, shifted(rec, -1))["total"] == 2_550 and w.bob.me_at(None, rec)["total"] == 2_470
    assert w.bob.total_at(T1) == 2_470 and w.bob.total_at(shifted(T1, -1)) == 2_500
    assert page_snapshot(w.bob, me, snap.snapshot)[0] == snap.entries, "an older snapshot pages unchanged"
    assert w.bob.money() == (2_470, 2_470, 0)
