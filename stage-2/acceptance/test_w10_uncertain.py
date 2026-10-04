"""W10.3, W10.7 — uncertain outcomes and the upgrade, in the browser (stage-2 "Competing clients and
uncertain outcomes", "Existing clients after an upgrade"; PLAN 3.14 writes, D42, D43). I41, I42, I43, I47."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from support import expect as expect_status
from support import fixture, standard_users, user
from test_w5_export_import import build_rich_state
from ui import money

pytestmark = pytest.mark.item(10)


def open_wallet(ui, handle="ada"):
    ui.log_in(handle, route="/")
    expect(ui.el("wallet-available")).to_be_visible()


def payments_with_note(client, note):
    return [p for p in client.feed() if p["note"] == note]


@pytest.mark.parametrize("how,committed", [("abort-after", True), ("abort-before", False), ("503", False),
                                           ("500-after", True), ("html-after", True)])
def test_lost_payment_shows_pay_uncertain_and_an_unchanged_retry_pays_once(world, ui, how, committed):
    open_wallet(ui)
    ui.fault("/payments", "POST", how)
    ui.pay_form("bob", "15.00", note=f"lost {how}")
    ui.click("pay-submit")
    expect(ui.el("pay-uncertain")).to_be_visible()
    assert ui.text("pay-uncertain"), "pay-uncertain has text"
    ui.absent("pay-error")
    ui.absent("pay-success")
    assert world.ada.balance() == (8_500 if committed else 10_000)
    if committed:
        ui.wallet(8_500)                        # the data is re-read after an unknown outcome too
    if how == "abort-after":
        ui.shot("wallet", "pay-uncertain")
    assert (ui.el("pay-handle").input_value(), ui.el("pay-amount").input_value()) == ("bob", "15.00")
    ui.click("pay-submit")
    expect(ui.el("pay-success")).to_be_visible()
    ui.absent("pay-uncertain")
    ui.absent("pay-error")
    ui.wallet(8_500)
    sent = ui.writes("/payments")
    assert len(sent) == 2 and sent[0].key == sent[1].key and sent[0].body == sent[1].body, sent
    found = payments_with_note(world.ada, f"lost {how}")
    assert len(found) == 1, "the money moved exactly once"
    expect(ui.el(f"activity-item-{found[0]['payment_id']}")).to_be_visible()


def test_response_held_past_six_seconds_is_uncertain(world, ui):
    open_wallet(ui)
    held = ui.hold("/payments", "POST", fetch_first=True, count=1)
    ui.pay_form("bob", "15.00", note="slow")
    ui.click("pay-submit")
    ui.page.wait_for_timeout(5_000)
    ui.absent("pay-error")
    expect(ui.el("pay-uncertain")).to_be_visible(timeout=4_000)
    held.release()
    ui.absent("pay-error")
    ui.click("pay-submit")
    expect(ui.el("pay-success")).to_be_visible()
    ui.absent("pay-uncertain")
    ui.wallet(8_500)
    assert len(payments_with_note(world.ada, "slow")) == 1


def test_uncertain_then_refused_retry_shows_pay_error_and_keeps_the_form(world, ui):
    """A retry can be refused for real: the uncertain element gives way to the error element."""
    open_wallet(ui, "cy")
    ui.fault("/payments", "POST", "abort-before")
    ui.pay_form("ada", "4.00", note="maybe")
    ui.click("pay-submit")
    expect(ui.el("pay-uncertain")).to_be_visible()
    expect_status(world.cy.pay("dee", 400), 201)              # another client spends the money
    ui.click("pay-submit")
    expect(ui.el("pay-error")).to_be_visible()
    ui.absent("pay-uncertain")
    ui.wallet(100)
    assert ui.el("pay-note").input_value() == "maybe"


def test_request_form_lost_response_is_uncertain_and_retry_creates_one(world, ui):
    open_wallet(ui)
    ui.fault("/requests", "POST", "abort-after")
    ui.fill("request-handle", "bob")
    ui.fill("request-amount", "2.50")
    ui.click("request-submit")
    expect(ui.el("request-uncertain")).to_be_visible()
    ui.absent("request-error")
    ui.click("request-submit")
    expect(ui.el("request-success")).to_be_visible()
    ui.absent("request-uncertain")
    assert len(world.bob.requests()) == 1
    sent = ui.writes("/requests")
    assert sent[0].key == sent[1].key and sent[0].body == sent[1].body


# ---------------------------------------------------------------- W10.7 upgrade

def test_signed_in_page_survives_an_export_and_import_without_a_reload(world, ui):
    open_wallet(ui)
    navigations = []
    ui.page.on("framenavigated", lambda f: navigations.append(f.url) if f == ui.page.main_frame else None)
    snap = world.svc.export()
    expect_status(world.bob.pay("ada", 100), 201)
    expect(ui.el("current-user")).to_be_visible()
    expect_status(world.svc.import_(snap), 204)
    ui.click("wallet-refresh")
    ui.wallet(10_000)
    expect(ui.el("current-user")).to_be_visible()
    ui.pay_form("bob", "1.00")
    ui.click("pay-submit")
    ui.wallet(9_900)
    assert navigations == [], f"no page load is needed: {navigations}"


def test_payment_lost_before_the_export_is_recovered_after_the_import(world, ui):
    open_wallet(ui)
    ui.fault("/payments", "POST", "abort-after")
    ui.pay_form("bob", "15.00", note="across the upgrade")
    ui.click("pay-submit")
    expect(ui.el("pay-uncertain")).to_be_visible()
    snap = world.svc.export()                             # holds the payment and its key
    world.svc.must_reset(fixture([user("other", 1)]))     # the service is replaced...
    expect_status(world.svc.import_(snap), 204)           # ...and the state migrated back in
    ui.click("pay-submit")                                # the same key and body
    expect(ui.el("pay-success")).to_be_visible()
    ui.absent("pay-uncertain")
    ui.absent("pay-error")
    ui.wallet(8_500)
    assert len(payments_with_note(world.svc.client("ada"), "across the upgrade")) == 1
    sent = ui.writes("/payments")
    assert sent[0].key == sent[1].key and sent[0].body == sent[1].body


def test_pending_request_from_a_stage_1_export_is_payable_from_the_request_screen(prev, svc, ui):
    rich = build_rich_state(prev)
    raw = prev.api().get("/_test/export", timeout=10).content
    assert svc.import_raw(content=raw).status_code == 204
    import copy
    svc.accounts, svc.total = copy.deepcopy(prev.accounts), prev.total
    svc._by_handle.clear()
    ui.log_in("ada", route="/requests")
    rid = rich["pending"]
    expect(ui.el(f"request-item-{rid}")).to_have_attribute("data-status", "pending")
    expect(ui.el(f"request-amount-{rid}")).to_have_text(money(300))
    ui.click(f"request-pay-{rid}")
    expect(ui.el(f"request-item-{rid}")).to_have_attribute("data-status", "paid")
    ui.absent(f"request-pay-{rid}")
    assert [r for r in svc.client("ada").requests() if r["request_id"] == rid][0]["status"] == "paid"
