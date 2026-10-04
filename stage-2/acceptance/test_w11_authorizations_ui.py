"""W11.3 — the holds screen `/authorizations` (stage-2 "UI"; PLAN 3.14, D46, D47, D55). I39-I45."""
from __future__ import annotations

import time

import pytest
from playwright.sync_api import expect

from support import expect as expect_status
from support import fixture, seeded_auth, standard_users, ts, user
from ui import money, sel

pytestmark = pytest.mark.item(11)


def open_auths(ui, handle="ada"):
    ui.log_in(handle, route="/authorizations")
    expect(ui.el("authorization-list")).to_be_attached()
    expect(ui.el("wallet-available")).to_be_visible()


def items(ui) -> list[str]:
    return [t for t in ui.page.eval_on_selector_all(f"{sel('authorization-list')} > *",
                                                    "els => els.map(e => e.getAttribute('data-testid'))")
            if t and t.startswith("authorization-item-")]


def authorize(ui, handle, amount, note=None, visibility=None):
    ui.fill("authorize-handle", handle)
    ui.fill("authorize-amount", amount)
    if note is not None:
        ui.fill("authorize-note", note)
    if visibility is not None:
        ui.el("authorize-visibility").select_option(visibility)
    ui.click("authorize-submit")


# ---------------------------------------------------------------- the list

def test_seeded_holds_show_right_after_reset(svc, ui):
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_out", "ada", "bob", 2_000, expires_at="2099-06-15T10:20:30.123456+05:30"),
        seeded_auth("a_in", "bob", "ada", 450),
        seeded_auth("a_cap", "ada", "cy", 300, status="captured", captured_amount=120),
        seeded_auth("a_void", "cy", "ada", 70, status="voided"),
        seeded_auth("a_exp", "ada", "dee", 60, status="expired")]))
    open_auths(ui)
    ui.wallet(10_000, held=2_000)
    expect(ui.el("authorization-item-a_out")).to_have_attribute("data-status", "open")
    expect(ui.el("authorization-expires-a_out")).to_have_text("2099-06-15T10:20:30.123456+05:30")
    for aid, status, amount in (("a_in", "open", 450), ("a_cap", "captured", 300), ("a_void", "voided", 70),
                                ("a_exp", "expired", 60), ("a_out", "open", 2_000)):
        expect(ui.el(f"authorization-item-{aid}")).to_have_attribute("data-status", status)
        expect(ui.el(f"authorization-amount-{aid}")).to_have_text(money(amount))
    expect(ui.el("authorization-captured-a_cap")).to_have_text(money(120))
    for aid in ("a_out", "a_in", "a_void", "a_exp"):
        ui.absent(f"authorization-captured-{aid}")
    expect(ui.el("authorization-capture-amount-a_in")).to_have_value("4.50")
    expect(ui.el("authorization-capture-a_in")).to_be_visible()
    expect(ui.el("authorization-void-a_out")).to_be_visible()
    for aid in ("a_out", "a_cap", "a_void", "a_exp"):
        ui.absent(f"authorization-capture-{aid}")
        ui.absent(f"authorization-capture-amount-{aid}")
    for aid in ("a_in", "a_cap", "a_void", "a_exp"):
        ui.absent(f"authorization-void-{aid}")
    assert items(ui) == [f"authorization-item-{a['authorization_id']}" for a in svc.client("ada").auths()]
    ui.absent("empty-authorizations")
    ui.shot("authorizations", "loaded")


def test_expires_text_is_the_api_string(world, ui):
    a = expect_status(world.bob.authorize("ada", 900), 201)
    open_auths(ui)
    expect(ui.el(f"authorization-expires-{a['authorization_id']}")).to_have_text(a["expires_at"])


def test_capture_input_is_prefilled_with_the_remainder(world, ui):
    a = expect_status(world.bob.authorize("ada", 2_000), 201)["authorization_id"]
    expect_status(world.ada.capture(a, {"amount": 700, "final": False}), 201)
    open_auths(ui)
    expect(ui.el(f"authorization-capture-amount-{a}")).to_have_value("13.00")
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "open")
    ui.absent(f"authorization-captured-{a}")


def test_capture_input_in_jpy_has_no_decimal_point(svc, ui):
    svc.must_reset(fixture(standard_users(), currency="JPY", authorizations=[seeded_auth("a_1", "bob", "ada", 2_000)]))
    open_auths(ui)
    expect(ui.el("authorization-capture-amount-a_1")).to_have_value("2000")
    expect(ui.el("authorization-amount-a_1")).to_have_text("2000 JPY")


def test_empty_authorizations_keeps_the_container(world, ui):
    open_auths(ui)
    expect(ui.el("empty-authorizations")).to_be_visible()
    expect(ui.el("authorization-list")).to_be_attached()
    ui.shot("authorizations", "empty")


# ---------------------------------------------------------------- the authorize form

def test_authorize_form_creates_a_hold_and_updates_the_wallet(world, ui):
    open_auths(ui)
    authorize(ui, "@bob", "20", note="deposit", visibility="private")
    expect(ui.el("authorize-success")).to_be_visible()
    ui.wallet(10_000, held=2_000)
    a = world.ada.auths()[0]
    assert (a["amount"], a["to_handle"], a["note"], a["visibility"]) == (2_000, "bob", "deposit", "private")
    expect(ui.el(f"authorization-item-{a['authorization_id']}")).to_have_attribute("data-status", "open")
    sent = ui.writes("/authorizations")
    assert len(sent) == 1 and sent[0].body["amount"] == 2_000 and sent[0].body["to_handle"] == "bob"
    ui.shot("authorizations", "success")


@pytest.mark.parametrize("handle,amount,server", [("bob", "6.00", True), ("nobody", "1", True), ("cy", "1", True),
                                                  ("bob", "1.005", False), ("bob", "abc", False), ("bob", "", False)])
def test_authorize_refusals_show_authorize_error(world, ui, handle, amount, server):
    open_auths(ui, "cy")
    authorize(ui, handle, amount)
    expect(ui.el("authorize-error")).to_be_visible()
    ui.absent("authorize-success")
    ui.page.wait_for_timeout(300)
    assert len(ui.writes("/authorizations")) == (1 if server else 0)
    assert world.cy.auths() == []
    if handle == "bob" and amount == "6.00":
        ui.shot("authorizations", "refused")


def test_authorize_unchanged_resubmission_creates_one_hold(world, ui):
    open_auths(ui)
    authorize(ui, "bob", "1.00")
    expect(ui.el("authorize-success")).to_be_visible()
    ui.click("authorize-submit")
    ui.page.wait_for_timeout(500)
    ui.absent("authorize-error")
    assert len(world.ada.auths()) == 1
    sent = ui.writes("/authorizations")
    assert sent[0].key == sent[1].key and sent[0].body == sent[1].body


# ---------------------------------------------------------------- capture and void

def test_full_capture_updates_the_item_and_the_wallet(world, ui):
    a = expect_status(world.bob.authorize("ada", 2_000), 201)["authorization_id"]
    open_auths(ui)
    ui.wallet(10_000)
    ui.click(f"authorization-capture-{a}")
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "captured")
    expect(ui.el(f"authorization-captured-{a}")).to_have_text(money(2_000))
    ui.absent(f"authorization-capture-{a}")
    ui.absent(f"authorization-capture-amount-{a}")
    ui.wallet(12_000)
    sent = ui.writes(f"/authorizations/{a}/capture")
    assert len(sent) == 1 and sent[0].body == {"amount": 2_000}, "D47: the amount, and no final"
    assert world.bob.money() == (500, 500, 0)


def test_partial_capture_is_final_and_releases_the_rest(world, ui):
    a = expect_status(world.bob.authorize("ada", 2_000), 201)["authorization_id"]
    open_auths(ui)
    ui.fill(f"authorization-capture-amount-{a}", "5.00")
    ui.click(f"authorization-capture-{a}")
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "captured")
    expect(ui.el(f"authorization-captured-{a}")).to_have_text(money(500))
    ui.wallet(10_500)
    assert world.bob.money() == (2_000, 2_000, 0)


def test_void_updates_the_item_and_the_wallet(world, ui):
    a = expect_status(world.ada.authorize("bob", 2_000), 201)["authorization_id"]
    open_auths(ui)
    ui.wallet(10_000, held=2_000)
    ui.click(f"authorization-void-{a}")
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "voided")
    ui.absent(f"authorization-void-{a}")
    ui.wallet(10_000)


def test_capture_refused_because_voided_elsewhere(world, ui):
    a = expect_status(world.bob.authorize("ada", 300), 201)["authorization_id"]
    open_auths(ui)
    expect_status(world.bob.void(a), 200)
    ui.click(f"authorization-capture-{a}")
    expect(ui.el("authorization-error")).to_be_visible()
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "voided")
    ui.absent(f"authorization-capture-{a}")


def test_capture_above_the_remainder_is_refused(world, ui):
    a = expect_status(world.bob.authorize("ada", 300), 201)["authorization_id"]
    open_auths(ui)
    ui.fill(f"authorization-capture-amount-{a}", "3.01")
    ui.click(f"authorization-capture-{a}")
    expect(ui.el("authorization-error")).to_be_visible()
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "open")
    assert world.bob.money() == (2_500, 2_200, 300)


@pytest.mark.parametrize("typed", ["abc", "1.234", "0", ""])
def test_invalid_capture_input_shows_authorization_error_and_sends_nothing(world, ui, typed):
    a = expect_status(world.bob.authorize("ada", 300), 201)["authorization_id"]
    open_auths(ui)
    ui.fill(f"authorization-capture-amount-{a}", typed)
    ui.click(f"authorization-capture-{a}")
    expect(ui.el("authorization-error")).to_be_visible()
    ui.page.wait_for_timeout(300)
    assert ui.writes(f"/authorizations/{a}/capture") == []


def test_a_refused_capture_refills_the_input_with_the_new_remainder(svc, ui):
    """W11.3 (plan d29e313; critic U23): another client changed the remainder; the refusal's re-read re-fills
    the input, and the next unchanged click captures the new remainder."""
    svc.must_reset(fixture(standard_users(), authorizations=[seeded_auth("a_r", "ada", "bob", 1_000)]))
    ui.log_in("bob", route="/authorizations")
    box = ui.el("authorization-capture-amount-a_r")
    expect(box).to_have_value("10.00")
    expect_status(svc.client("bob").capture("a_r", {"amount": 400, "final": False}), 201)   # bob's other device
    ui.click("authorization-capture-a_r")              # 10.00, more than the 6.00 left: refused
    expect(ui.el("authorization-error")).to_be_visible()
    expect(box).to_have_value("6.00")
    ui.click("authorization-capture-a_r")
    expect(ui.el("authorization-item-a_r")).to_have_attribute("data-status", "captured")
    assert svc.client("ada").money() == (9_000, 9_000, 0)
    sent = ui.writes("/authorizations/a_r/capture")
    assert [c.body for c in sent] == [{"amount": 1_000}, {"amount": 600}], [c.body for c in sent]
    assert sent[0].key != sent[1].key, "a different body is a new key (D42)"

def test_capture_of_an_expired_hold_is_refused(svc, ui):
    svc.must_reset(fixture(standard_users(), ttl=3))
    a = expect_status(svc.client("bob").authorize("ada", 300), 201)
    open_auths(ui)
    expect(ui.el(f"authorization-capture-{a['authorization_id']}")).to_be_visible()
    time.sleep(max(0.0, ts(a["expires_at"]).timestamp() + 0.6 - time.time()))
    ui.click(f"authorization-capture-{a['authorization_id']}")
    expect(ui.el("authorization-error")).to_be_visible()
    expect(ui.el(f"authorization-item-{a['authorization_id']}")).to_have_attribute("data-status", "expired")
    assert svc.client("bob").money() == (2_500, 2_500, 0)


def test_capture_lost_after_commit_shows_the_confirmed_state(world, ui):
    """Plan 45fe2dc: the re-read shows the capture took effect, so the uncertain element gives way."""
    a = expect_status(world.bob.authorize("ada", 300), 201)["authorization_id"]
    open_auths(ui)
    ui.fault(f"/authorizations/{a}/capture", "POST", "abort-after")
    ui.click(f"authorization-capture-{a}")
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "captured")
    expect(ui.el(f"authorization-captured-{a}")).to_have_text(money(300))
    ui.absent("authorization-uncertain")
    ui.absent("authorization-error")
    assert len(ui.writes(f"/authorizations/{a}/capture")) == 1
    assert world.ada.balance() == 10_300
    ui.wallet(10_300)


def test_lost_capture_before_commit_is_retried_with_the_same_key(world, ui):
    a = expect_status(world.bob.authorize("ada", 300), 201)["authorization_id"]
    open_auths(ui)
    ui.fault(f"/authorizations/{a}/capture", "POST", "abort-before")
    ui.click(f"authorization-capture-{a}")
    expect(ui.el("authorization-uncertain")).to_be_visible()
    ui.click(f"authorization-capture-{a}")
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "captured")
    ui.absent("authorization-uncertain")
    sent = ui.writes(f"/authorizations/{a}/capture")
    assert len(sent) == 2 and sent[0].key == sent[1].key and sent[0].body == sent[1].body
    assert world.ada.balance() == 10_300


def test_void_lost_after_commit_shows_the_confirmed_state(world, ui):
    a = expect_status(world.ada.authorize("bob", 300), 201)["authorization_id"]
    open_auths(ui)
    ui.fault(f"/authorizations/{a}/void", "POST", "abort-after")
    ui.click(f"authorization-void-{a}")
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "voided")
    ui.absent("authorization-uncertain")
    ui.wallet(10_000)


def test_void_lost_before_commit_stays_uncertain(world, ui):
    a = expect_status(world.ada.authorize("bob", 300), 201)["authorization_id"]
    open_auths(ui)
    ui.fault(f"/authorizations/{a}/void", "POST", "abort-before")
    ui.click(f"authorization-void-{a}")
    expect(ui.el("authorization-uncertain")).to_be_visible()
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "open")
    ui.absent("authorization-error")
    ui.click(f"authorization-void-{a}")
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "voided")
    ui.absent("authorization-uncertain")


@pytest.mark.parametrize("how", ["abort-after", "empty-after"])
def test_authorize_lost_response_is_uncertain_and_retry_creates_one(world, ui, how):
    """W11.3, W10.3 (plan d29e313: an empty 201 after commit is unknown too); the re-read shows the hold."""
    open_auths(ui)
    ui.fault("/authorizations", "POST", how)
    authorize(ui, "bob", "2.00")
    expect(ui.el("authorize-uncertain")).to_be_visible()
    ui.absent("authorize-error")
    ui.absent("authorize-success")
    ui.wallet(10_000, held=200)                       # re-read after the unknown outcome
    ui.click("authorize-submit")
    expect(ui.el("authorize-success")).to_be_visible()
    ui.absent("authorize-uncertain")
    assert len(world.ada.auths()) == 1
    ui.wallet(10_000, held=200)
    sent = ui.writes("/authorizations")
    assert len(sent) == 2 and sent[0].key == sent[1].key and sent[0].body == sent[1].body
    assert not ui.page_errors, f"uncaught errors in the page: {ui.page_errors}"


def test_bhd_amounts(svc, ui):
    svc.must_reset(fixture([user("ada", 50_000), user("bob", 0)], currency="BHD",
                           authorizations=[seeded_auth("a_1", "ada", "bob", 12_345)]))
    open_auths(ui)
    expect(ui.el("authorization-amount-a_1")).to_have_text("12.345 BHD")
    ui.wallet(50_000, held=12_345, minor_units=3, currency="BHD")


def test_more_than_one_page_of_authorizations_renders_every_item_once(svc, ui):
    """D64 (plan 45fe2dc)."""
    auths = [seeded_auth(f"a_{i:03d}", "ada" if i % 2 else "bob", "bob" if i % 2 else "ada", 1) for i in range(205)]
    svc.must_reset(fixture(standard_users(), authorizations=auths))
    open_auths(ui)
    expect(ui.el("authorization-item-a_000")).to_be_attached()
    assert items(ui) == [f"authorization-item-a_{i:03d}" for i in reversed(range(205))]
    first = ui.reads("/authorizations")[0]
    assert first.query == "", f"D64: the first read is the bare path, got ?{first.query}"
    ui.wallet(10_000, held=102)


def test_the_authorize_form_on_the_wallet_screen(world, ui):
    """D46 (plan 45fe2dc): the same form on `/` creates a hold and updates the wallet numbers there."""
    ui.log_in("ada", route="/")
    expect(ui.el("wallet-available")).to_be_visible()
    authorize(ui, "bob", "12.34", note="deposit")
    expect(ui.el("authorize-success")).to_be_visible()
    ui.wallet(10_000, held=1_234)
    assert [a["amount"] for a in world.ada.auths()] == [1_234]
    authorize(ui, "bob", "999")
    expect(ui.el("authorize-error")).to_be_visible()
    ui.wallet(10_000, held=1_234)
