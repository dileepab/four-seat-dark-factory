"""W11.1 — the requests screen `/requests` (stage-2 "Requests", "Competing clients"; PLAN 3.14, D55, D60).
I39, I41-I45."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from support import expect as expect_status
from support import fixture, seeded_auth, standard_users
from ui import money, sel

pytestmark = pytest.mark.item(11)


def open_requests(ui, handle="ada"):
    ui.log_in(handle, route="/requests")
    expect(ui.el("incoming-list")).to_be_attached()
    expect(ui.el("outgoing-list")).to_be_attached()


def children(ui, container) -> list[str]:
    return [t for t in ui.page.eval_on_selector_all(f"{sel(container)} > *",
                                                    "els => els.map(e => e.getAttribute('data-testid'))")
            if t and t.startswith("request-item-")]


@pytest.fixture
def every_status(svc):
    """Ada pays on rq_in_*, asks on rq_out_*, one request in each status for each direction."""
    reqs = []
    for st in ("pending", "paid", "declined", "cancelled"):
        reqs.append({"id": f"rq_in_{st}", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1_200,
                     "note": f"in {st}", "status": st, **({"payment_id": "p_x"} if st == "paid" else {})})
        reqs.append({"id": f"rq_out_{st}", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 345,
                     "note": f"out {st}", "status": st})
    svc.must_reset(fixture(standard_users(), requests=reqs))
    return svc


def test_lists_hold_every_status_with_the_right_actions(every_status, ui):
    open_requests(ui)
    for st in ("pending", "paid", "declined", "cancelled"):
        expect(ui.el(f"request-item-rq_in_{st}")).to_have_attribute("data-status", st)
        expect(ui.el(f"request-item-rq_out_{st}")).to_have_attribute("data-status", st)
        expect(ui.el(f"request-amount-rq_in_{st}")).to_have_text(money(1_200))
        expect(ui.el(f"request-amount-rq_out_{st}")).to_have_text(money(345))
        ui.absent(f"request-cancel-rq_in_{st}")
        ui.absent(f"request-pay-rq_out_{st}")
        ui.absent(f"request-decline-rq_out_{st}")
        if st != "pending":
            ui.absent(f"request-pay-rq_in_{st}")
            ui.absent(f"request-decline-rq_in_{st}")
            ui.absent(f"request-cancel-rq_out_{st}")
    expect(ui.el("request-pay-rq_in_pending")).to_be_visible()
    expect(ui.el("request-decline-rq_in_pending")).to_be_visible()
    expect(ui.el("request-cancel-rq_out_pending")).to_be_visible()
    ui.absent("empty-requests")
    assert set(children(ui, "incoming-list")) == {f"request-item-rq_in_{s}" for s in
                                                  ("pending", "paid", "declined", "cancelled")}
    assert set(children(ui, "outgoing-list")) == {f"request-item-rq_out_{s}" for s in
                                                  ("pending", "paid", "declined", "cancelled")}
    ui.shot("requests", "loaded")


def test_items_are_direct_children_newest_first(world, ui):
    made = [expect_status(world.bob.ask("ada", 100 + i), 201)["request_id"] for i in range(3)]
    out = [expect_status(world.ada.ask("cy", 10 + i), 201)["request_id"] for i in range(2)]
    open_requests(ui)
    expect(ui.el(f"request-item-{made[-1]}")).to_be_visible()
    assert children(ui, "incoming-list") == [f"request-item-{r['request_id']}" for r in world.ada.requests(direction="incoming")]
    assert children(ui, "outgoing-list") == [f"request-item-{r['request_id']}" for r in world.ada.requests(direction="outgoing")]
    assert set(children(ui, "outgoing-list")) == {f"request-item-{r}" for r in out}


def test_empty_requests_only_when_both_lists_are_empty(world, ui):
    open_requests(ui)
    expect(ui.el("empty-requests")).to_be_visible()
    ui.shot("requests", "empty")
    rq = expect_status(world.bob.ask("ada", 5), 201)["request_id"]
    ui.page.reload()
    expect(ui.el(f"request-item-{rq}")).to_be_visible()
    ui.absent("empty-requests")


def test_pay_updates_the_item_without_a_reload_and_sends_an_empty_body(world, ui):
    rid = expect_status(world.bob.ask("ada", 1_200), 201)["request_id"]
    open_requests(ui)
    ui.click(f"request-pay-{rid}")
    expect(ui.el(f"request-item-{rid}")).to_have_attribute("data-status", "paid")
    ui.absent(f"request-pay-{rid}")
    ui.absent(f"request-decline-{rid}")
    sent = ui.writes(f"/requests/{rid}/pay")
    assert len(sent) == 1 and sent[0].body == {} and sent[0].key, "D60: the body is {} with a key"
    assert world.ada.balance() == 8_800
    ui.shot("requests", "success")


def test_decline_and_cancel_update_the_items(world, ui):
    rin = expect_status(world.bob.ask("ada", 100), 201)["request_id"]
    rout = expect_status(world.ada.ask("cy", 100), 201)["request_id"]
    open_requests(ui)
    ui.click(f"request-decline-{rin}")
    expect(ui.el(f"request-item-{rin}")).to_have_attribute("data-status", "declined")
    ui.click(f"request-cancel-{rout}")
    expect(ui.el(f"request-item-{rout}")).to_have_attribute("data-status", "cancelled")
    ui.absent(f"request-cancel-{rout}")
    ui.absent("request-error")


def test_paying_without_available_funds_shows_request_error(world, ui):
    rid = expect_status(world.ada.ask("cy", 400), 201)["request_id"]
    expect_status(world.cy.authorize("dee", 200), 201)                 # total covers it, available does not
    open_requests(ui, "cy")
    ui.click(f"request-pay-{rid}")
    expect(ui.el("request-error")).to_be_visible()
    expect(ui.el(f"request-item-{rid}")).to_have_attribute("data-status", "pending")
    assert world.cy.money() == (500, 300, 200)
    ui.shot("requests", "refused")


def test_request_cancelled_elsewhere_loses_its_stale_pay_button(world, ui):
    rid = expect_status(world.bob.ask("ada", 100), 201)["request_id"]
    open_requests(ui)
    expect(ui.el(f"request-pay-{rid}")).to_be_visible()
    expect_status(world.bob.cancel(rid), 200)
    ui.click(f"request-pay-{rid}")
    expect(ui.el("request-error")).to_be_visible()
    expect(ui.el(f"request-item-{rid}")).to_have_attribute("data-status", "cancelled")
    ui.absent(f"request-pay-{rid}")
    assert world.ada.balance() == 10_000


def test_lost_pay_response_is_uncertain_and_the_retry_reuses_the_key(world, ui):
    rid = expect_status(world.bob.ask("ada", 700), 201)["request_id"]
    other = expect_status(world.cy.ask("ada", 50), 201)["request_id"]
    open_requests(ui)
    ui.fault(f"/requests/{rid}/pay", "POST", "abort-before")
    ui.click(f"request-pay-{rid}")
    expect(ui.el("request-uncertain")).to_be_visible()
    ui.absent("request-error")
    ui.shot("requests", "uncertain")
    ui.click(f"request-pay-{rid}")
    expect(ui.el(f"request-item-{rid}")).to_have_attribute("data-status", "paid")
    ui.absent("request-uncertain")
    sent = ui.writes(f"/requests/{rid}/pay")
    assert len(sent) == 2 and sent[0].key == sent[1].key and sent[0].body == sent[1].body == {}
    ui.click(f"request-pay-{other}")
    expect(ui.el(f"request-item-{other}")).to_have_attribute("data-status", "paid")
    assert ui.writes(f"/requests/{other}/pay")[0].key != sent[0].key, "one key per request"
    assert world.ada.balance() == 10_000 - 750


def test_pay_lost_after_commit_then_retried_moves_money_once(world, ui):
    rid = expect_status(world.bob.ask("ada", 700), 201)["request_id"]
    open_requests(ui)
    ui.fault(f"/requests/{rid}/pay", "POST", "abort-after")
    ui.click(f"request-pay-{rid}")
    expect(ui.el("request-uncertain")).to_be_visible()
    expect(ui.el(f"request-item-{rid}")).to_have_attribute("data-status", "paid")   # the list is re-read
    assert world.ada.balance() == 9_300


def test_lost_decline_is_uncertain_and_the_list_is_reread(world, ui):
    rid = expect_status(world.bob.ask("ada", 100), 201)["request_id"]
    open_requests(ui)
    ui.fault(f"/requests/{rid}/decline", "POST", "abort-after")
    ui.click(f"request-decline-{rid}")
    expect(ui.el("request-uncertain")).to_be_visible()
    ui.absent("request-error")
    expect(ui.el(f"request-item-{rid}")).to_have_attribute("data-status", "declined")


def test_seeded_hold_blocks_a_request_payment_in_the_ui(svc, ui):
    svc.must_reset(fixture(standard_users(), authorizations=[seeded_auth("a_1", "cy", "bob", 450)],
                           requests=[{"id": "rq_1", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 100}]))
    open_requests(ui, "cy")
    ui.click("request-pay-rq_1")
    expect(ui.el("request-error")).to_be_visible()
    expect(ui.el("request-item-rq_1")).to_have_attribute("data-status", "pending")
