"""W17.3 — upgrade: unchanged exports from the frozen stage-1 and stage-2 builds import into stage 3
(stage-3 "Settlement history"; stage-1 §10; PLAN 3.6, 3.7, 3.11, D54, D69, D71, D75, D76). I37, I62, I65.

`prev` is built from the frozen stage-1/ folder and `prev2` from the frozen stage-2/ folder. Each
state is built there, exported, and posted byte for byte to the stage-3 service.
"""
from __future__ import annotations

import copy

import httpx
import pytest

from support import (EPOCH, FAR_FUTURE, RESET_TIMEOUT, STAGE2_AUTHZ_KEYS, check_authorization, expect, expect_error,
                     fixture, instant, new_key, read_statement, shifted, standard_users)
from test_w8_export_import import HANDLES as HANDLES2, SENTINEL_AMOUNT, SENTINEL_CAPTURE, build_holds
from test_w8_upgrade import upgrade

pytestmark = pytest.mark.item(17)


def own_payments(feed: list[dict], handle: str) -> list[dict]:
    return [p for p in feed if handle in (p["from_handle"], p["to_handle"])]


def net(feed: list[dict], handle: str) -> int:
    return sum(p["amount"] if p["to_handle"] == handle else -p["amount"] for p in own_payments(feed, handle))


def check_lifted_history(svc, before: dict, handles: list[str]) -> None:
    """I65: every payment is revision 1 at its created_at; opening = imported balance - net of all payments."""
    for h in handles:
        c = svc.client(h)
        feed = c.feed()
        bal = before[h]["me"]["balance"]
        opening = bal - net(feed, h)
        assert c.me_at(EPOCH)["total"] == opening, f"I65: {h}'s opening balance"
        for p in own_payments(feed, h):
            revs = c.revisions(p["payment_id"])
            assert revs == [{"payment_id": p["payment_id"], "revision": 1, "amount": p["amount"],
                             "effective_at": p["created_at"], "recorded_at": p["created_at"], "reason": ""}], revs
        st = read_statement(c, svc.accounts[h].user_id)
        assert (st.opening, st.closing) == (opening, bal), f"{h}: the statement walks from the opening to the balance"
        assert sorted(st.ids()) == sorted(p["payment_id"] for p in own_payments(feed, h))
        if own_payments(feed, h):
            first = min(instant(p["created_at"]) for p in own_payments(feed, h))
            early = [p["created_at"] for p in own_payments(feed, h) if instant(p["created_at"]) == first][0]
            assert c.me_at(shifted(early, -1))["total"] == opening


# ---------------------------------------------------------------- from stage 1

def test_stage_1_payments_become_revision_1_with_opening_balances(prev, svc):
    rich = upgrade(prev, svc)
    check_lifted_history(svc, rich["before"], rich["handles"])


def test_stage_1_payments_can_be_corrected_and_members_cannot(prev, svc):
    rich = upgrade(prev, svc)
    ada = svc.client("ada")
    feed = ada.feed()
    plain = [p for p in feed if p["from_handle"] == "ada" and p["settlement_id"] is None and p["request_id"] is None][0]
    member = [p for p in feed if p["from_handle"] == "ada" and p["settlement_id"] is not None][0]
    before = (ada.balance(), svc.client(plain["to_handle"]).balance())
    r = expect(ada.correct(plain["payment_id"], 1, plain["amount"] - 1, plain["created_at"]), 201)
    assert r["revision"] == 2
    assert (ada.balance(), svc.client(plain["to_handle"]).balance()) == (before[0] + 1, before[1] - 1)
    expect_error(ada.correct(member["payment_id"], 1, 1, member["created_at"]), 422, "linked_payment_immutable")
    assert rich["handles"]


def test_a_stage_1_upgrade_exports_as_schema_3_and_round_trips(prev, svc, svc_b):
    rich = upgrade(prev, svc)
    p = [x for x in svc.client("ada").feed() if x["from_handle"] == "ada" and x["settlement_id"] is None][0]
    key = new_key()
    r = expect(svc.client("ada").correct(p["payment_id"], 1, p["amount"] + 2, p["created_at"], key=key), 201)
    snap = svc.export()
    assert snap.body["state"]["schema"] == 3
    expect(svc_b.import_(snap), 204)
    assert expect(svc_b.client("ada").correct(p["payment_id"], 1, p["amount"] + 2, p["created_at"], key=key), 200) == r
    for h in rich["handles"]:
        assert svc_b.client(h).me_at(EPOCH) == svc.client(h).me_at(EPOCH)


# ---------------------------------------------------------------- from stage 2

def stage2_upgrade(prev2, target) -> dict:
    """Build every authorization state on the frozen stage-2 build, add a pending request, export it
    unchanged and import those exact bytes into stage 3."""
    rich = build_holds(prev2)
    pending = expect(prev2.client("bob").ask("ada", 30, note="pending"), 201)
    rich["pending"] = pending["request_id"]
    rich["before"] = {h: {"me": prev2.client(h).me(), "feed": prev2.client(h).feed(),
                          "requests": prev2.client(h).requests(), "auths": prev2.client(h).auths()} for h in HANDLES2}
    resp = httpx.get(f"{prev2.base_url}/_test/export", timeout=RESET_TIMEOUT)
    raw = expect(resp, 200)
    assert raw["state"]["schema"] == 2, "precondition: the frozen stage-2 build exports schema 2"
    got = target.import_raw(content=resp.content)
    assert got.status_code == 204, f"a stage-2 export must import into stage 3: {got.status_code} {got.text[:300]}"
    target.accounts = copy.deepcopy(prev2.accounts)
    target._by_handle.clear()
    target.total = prev2.total
    return rich


def test_stage_2_state_reads_back_with_closed_at(prev2, svc):
    rich = stage2_upgrade(prev2, svc)
    for h in HANDLES2:
        c = svc.client(h)
        old = rich["before"][h]
        assert c.me() == old["me"]
        assert c.feed() == old["feed"]
        assert c.requests() == old["requests"]
        auths = c.auths()
        assert [{k: v for k, v in a.items() if k != "closed_at"} for a in auths] == old["auths"], \
            "PLAN 3.6: the only change to an authorization is the new closed_at"
        for a in auths:
            check_authorization(a)
    check_lifted_history(svc, rich["before"], HANDLES2)


def test_stage_2_holds_keep_their_history(prev2, svc):
    """I65: creation, captures and close, with closed_at from the stage-2 state (D71)."""
    rich = stage2_upgrade(prev2, svc)
    a = rich["auths"]
    ada, zed = svc.client("ada"), svc.client("zed")
    by_id = {x["authorization_id"]: x for h in ("ada", "zed", "bob", "cy") for x in svc.client(h).auths()}
    caps = {p["authorization_id"]: p for h in HANDLES2 for p in svc.client(h).feed() if p["authorization_id"]}

    assert by_id[a["open"]["authorization_id"]]["closed_at"] is None
    assert by_id[a["partial"]["authorization_id"]]["closed_at"] is None, "open after a nonfinal capture"
    for name in ("captured", "full"):
        x = by_id[a[name]["authorization_id"]]
        assert x["closed_at"] == caps[x["authorization_id"]]["created_at"], \
            f"I61: a closing capture's time is closed_at after the upgrade: {x}"
    v = by_id[a["voided"]["authorization_id"]]
    assert instant(a["voided"]["created_at"]) <= instant(v["closed_at"]) <= \
        instant(a["voided_partial"]["created_at"]), f"the void's time lies between the neighbouring writes: {v}"
    seed_open = by_id["a_seed_open"]
    for aid in ("a_seed_exp", "a_seed_cap"):
        assert by_id[aid]["closed_at"] == seed_open["created_at"], \
            f"I61: a seeded closed hold closes at the stage-2 reset's timestamp: {by_id[aid]}"
    assert by_id["a_seed_past"]["closed_at"] == by_id["a_seed_past"]["expires_at"]

    # The frozen stage-2 build issues never-decreasing timestamps, so a hold and its capture or void can
    # share a millisecond; "just before" is checked only when the creation is earlier.
    # Ada's open hold of 1000 counts from its creation (checked when no other hold event of hers shares it).
    c = a["open"]["created_at"]
    others = {instant(t) for x in ada.auths(direction="outgoing") if x["authorization_id"] != a["open"]["authorization_id"]
              for t in (x["created_at"], x["closed_at"]) if t}
    if instant(c) not in others:
        assert ada.money_at(shifted(c, -1))[2] + 1_000 == ada.money_at(c)[2]
    # Zed's partial hold: 500 from the seeded open hold, plus the partial hold less the capture at its time.
    pc = caps[a["partial"]["authorization_id"]]["created_at"]
    at_cap = zed.money_at(pc)
    assert at_cap[2] == 500 + SENTINEL_AMOUNT - SENTINEL_CAPTURE, f"zed at the capture: {at_cap}"
    if instant(a["partial"]["created_at"]) < instant(pc):
        before_cap = zed.money_at(shifted(pc, -1))
        assert before_cap[2] == 500 + SENTINEL_AMOUNT and before_cap[0] - at_cap[0] == SENTINEL_CAPTURE, before_cap
    # Ada's voided hold of 60 holds nothing from the void's closed_at on.
    vx = v["closed_at"]
    held_after = ada.money_at(vx)[2]
    assert held_after == 1_000, "at the void only ada's open hold of 1000 is held"
    if instant(a["voided"]["created_at"]) < instant(vx):
        assert ada.money_at(shifted(vx, -1))[2] - held_after == 60, "the void releases at its time"


def test_stage_2_replays_return_their_stored_bodies(prev2, svc):
    """D54: a replayed stage-2 authorization body has no closed_at."""
    rich = stage2_upgrade(prev2, svc)
    for rp in rich["replays"]:
        r = svc.client(rp["who"]).post(rp["path"], json=rp["body"], key=rp["key"])
        assert expect(r, 200) == rp["resp"], rp["path"]
        if rp["path"] == "/authorizations":
            assert set(rp["resp"]) == STAGE2_AUTHZ_KEYS


def test_stage_2_captures_are_immutable_and_payments_correctable(prev2, svc):
    rich = stage2_upgrade(prev2, svc)
    zed, ada = svc.client("zed"), svc.client("ada")
    cap = [p for p in zed.feed() if p["authorization_id"] == rich["auths"]["partial"]["authorization_id"]][0]
    expect_error(zed.correct(cap["payment_id"], 1, 1, cap["created_at"]), 422, "linked_payment_immutable")
    seeded_link = [p for p in zed.feed() if p["payment_id"] == "p_seed"][0]
    expect_error(zed.correct("p_seed", 1, 1, seeded_link["created_at"]), 422, "linked_payment_immutable")
    plain = [p for p in ada.feed() if p["from_handle"] == "ada" and p["authorization_id"] is None
             and p["settlement_id"] is None][0]
    expect(ada.correct(plain["payment_id"], 1, plain["amount"] + 1, plain["created_at"]), 201)


def test_stage_2_tokens_logins_requests_and_keys_work(prev2, svc):
    rich = stage2_upgrade(prev2, svc)
    for h, acct in prev2.accounts.items():
        expect(svc.api(acct.token).get("/me"), 200)
        expect(svc.login(acct.email, acct.password), 200)
    expect(svc.client("ada").pay_request(rich["pending"]), 201)
    expect(svc.client("bob").capture(rich["auths"]["open"]["authorization_id"], {"amount": 5}, key=rich["failed_key"]),
           201)


def test_stage_2_partly_captured_hold_and_display_only_links(prev2, svc):
    """W18.7 (a), D84, I67 on the stage-2 import path: a seeded open hold with a captured_amount, a seeded
    payment naming it, its payment_ids naming that payment, and an API nonfinal capture on stage 2."""
    prev2.must_reset(fixture(standard_users()))
    far = shifted(prev2.client("ada").service_now("bob"), seconds=7200, digits=3)
    prev2.must_reset(fixture(standard_users(), payments=[
        {"id": "p_link", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 50, "authorization_id": "a_part"}],
        authorizations=[{"id": "a_part", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1_000,
                         "expires_at": far, "created_at": "2026-03-01T00:00:00Z", "captured_amount": 400,
                         "payment_id": "p_link", "payment_ids": ["p_link"]}]))
    cp = expect(prev2.client("bob").capture("a_part", {"amount": 100, "final": False}), 201)
    assert prev2.client("ada").money() == (9_900, 9_400, 500), "precondition on the stage-2 build"
    resp = httpx.get(f"{prev2.base_url}/_test/export", timeout=RESET_TIMEOUT)
    assert expect(resp, 200)["state"]["schema"] == 2
    assert svc.import_raw(content=resp.content).status_code == 204
    svc.accounts, svc.total = copy.deepcopy(prev2.accounts), prev2.total
    svc._by_handle.clear()
    ada, bob = svc.client("ada"), svc.client("bob")
    a = check_authorization(ada.auth("a_part"), status="open", captured_amount=500, remaining_amount=500, closed_at=None)
    c, x = a["created_at"], cp["created_at"]
    assert ada.money() == (9_900, 9_400, 500)
    assert ada.money_at(shifted(c, -1)) == (10_050, 10_050, 0)
    if instant(c) < instant(x):
        assert ada.money_at(c) == (10_000, 9_400, 600), \
            "D84: amount - captured_amount is held from creation, and the display-only link reduces nothing"
        assert ada.money_at(shifted(x, -1)) == (10_000, 9_400, 600)
    assert ada.money_at(x) == (9_900, 9_400, 500), "the API capture reduces the hold at its time"
    for h in ("ada", "bob", "cy", "dee"):
        m = svc.client(h).money()
        assert svc.client(h).money_at(None, FAR_FUTURE) == m and svc.client(h).money_at(x) == m, f"I67 for {h}"
    expect(bob.capture("a_part", {"amount": 200, "final": False}), 201)
    assert ada.money() == (9_700, 9_400, 300)
