"""W11.4, W9.4, W12.4 — every screen in every named state at both widths: the I46 layout checks
(and the scroll check at 1024x768 too), keyboard focus, and one screenshot per state (PLAN 3.14
`loading`, `load-error`, `load-retry`; 3.15).

Screenshots are named <screen>-<state>-<width>.png under --shots.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from support import expect as expect_status
from support import fixture, seeded_auth, standard_users, user

pytestmark = pytest.mark.item(11)

SCREENS = {"/": ("wallet", "wallet-available"), "/requests": ("requests", "incoming-list"),
           "/split": ("split", "split-submit"), "/authorizations": ("authorizations", "authorization-list")}


def state(ui, screen, name):
    ui.check_layout(f"{screen} {name}")
    ui.check_scroll_at(1024, 768, f"{screen} {name}")
    ui.shot(screen, name)


@pytest.mark.parametrize("route", list(SCREENS))
def test_loading_and_load_error_states(world, ui, route):
    screen, anchor = SCREENS[route]
    ui.log_in("ada")
    held = ui.hold("/me", "GET")
    ui.page.goto(route)
    expect(ui.el("loading")).to_be_visible()
    state(ui, screen, "loading")
    held.release()
    ui.page.unroute_all(behavior="ignoreErrors")
    expect(ui.el(anchor)).to_be_attached()
    ui.absent("loading")
    ui.absent("load-error")

    ui.fault("/me", "GET", "503", count=1_000)
    ui.page.goto(route)
    expect(ui.el("load-error")).to_be_visible()
    expect(ui.el("load-retry")).to_be_visible()
    ui.absent("loading")
    state(ui, screen, "load-error")
    ui.page.unroute_all(behavior="ignoreErrors")
    expect(ui.el("load-retry")).to_be_enabled()
    ui.click("load-retry")
    expect(ui.el(anchor)).to_be_attached()
    ui.absent("load-error")
    expect(ui.el("current-user")).to_be_visible()


@pytest.mark.parametrize("route", list(SCREENS))
def test_loaded_screen_layout_and_keyboard_focus(svc, ui, route):
    svc.must_reset(fixture(standard_users(), operators=["u_ada"],
                           payments=[{"id": "p_1", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1_250,
                                      "note": "a long note " * 15, "visibility": "private"},
                                     {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 99}],
                           requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 300,
                                      "note": "taxi"},
                                     {"id": "rq_2", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 40}],
                           authorizations=[seeded_auth("a_1", "ada", "bob", 2_000, note="deposit"),
                                           seeded_auth("a_2", "bob", "ada", 450)]))
    screen, anchor = SCREENS[route]
    ui.log_in("ada", route=route)
    expect(ui.el(anchor)).to_be_attached()
    if route == "/split":
        ui.fill("split-amount", "10.00")
        ui.fill("split-handles", "ada,bob,cy")
        expect(ui.el("split-preview")).to_be_visible()
    ui.page.wait_for_load_state("networkidle")
    state(ui, screen, "loaded" if route != "/split" else "preview")
    seen = ui.check_focus(route)
    for nav in ("nav-wallet", "nav-requests", "nav-split", "nav-authorizations", "logout-button"):
        assert nav in seen, f"{nav} is not reachable by keyboard on {route}: {seen}"


def test_wallet_states(world, ui):
    ui.log_in("dee", route="/")
    expect(ui.el("empty-activity")).to_be_visible()
    state(ui, "wallet", "empty")
    ui.pay_form("ada", "1.00")
    ui.click("pay-submit")
    expect(ui.el("pay-error")).to_be_visible()
    state(ui, "wallet", "pay-refused")
    expect_status(world.ada.pay("dee", 500), 201)
    ui.click("wallet-refresh")
    ui.fault("/payments", "POST", "abort-after")
    ui.pay_form("ada", "2.00", note="maybe")
    ui.click("pay-submit")
    expect(ui.el("pay-uncertain")).to_be_visible()
    state(ui, "wallet", "pay-uncertain")
    ui.click("pay-submit")
    expect(ui.el("pay-success")).to_be_visible()
    state(ui, "wallet", "pay-success")
    ui.fill("request-handle", "nobody")
    ui.fill("request-amount", "1")
    ui.click("request-submit")
    expect(ui.el("request-error")).to_be_visible()
    state(ui, "wallet", "request-refused")
    ui.fill("request-handle", "ada")
    ui.fault("/requests", "POST", "abort-before")
    ui.click("request-submit")
    expect(ui.el("request-uncertain")).to_be_visible()
    state(ui, "wallet", "request-uncertain")
    ui.click("request-submit")
    expect(ui.el("request-success")).to_be_visible()
    state(ui, "wallet", "request-success")


def test_requests_states(world, ui):
    ui.log_in("dee", route="/requests")
    expect(ui.el("empty-requests")).to_be_visible()
    state(ui, "requests", "empty")
    r1 = expect_status(world.ada.ask("dee", 100), 201)["request_id"]
    r2 = expect_status(world.bob.ask("dee", 5), 201)["request_id"]
    r3 = expect_status(world.dee.ask("cy", 7, note="lunch"), 201)["request_id"]
    ui.page.reload()
    expect(ui.el(f"request-item-{r3}")).to_be_visible()
    state(ui, "requests", "loaded")
    ui.click(f"request-pay-{r1}")
    expect(ui.el("request-error")).to_be_visible()
    state(ui, "requests", "refused")
    ui.fault(f"/requests/{r2}/pay", "POST", "abort-before")      # a lost payment: the money-action text (3.15)
    ui.click(f"request-pay-{r2}")
    expect(ui.el("request-uncertain")).to_be_visible()
    state(ui, "requests", "pay-uncertain")
    ui.fault(f"/requests/{r2}/decline", "POST", "abort-before")  # a lost decline: may keep a neutral text
    ui.click(f"request-decline-{r2}")
    expect(ui.el("request-uncertain")).to_be_visible()
    state(ui, "requests", "uncertain")
    ui.click(f"request-cancel-{r3}")
    expect(ui.el(f"request-item-{r3}")).to_have_attribute("data-status", "cancelled")
    state(ui, "requests", "success")


def test_split_states(world, ui):
    ui.log_in("ada", route="/split")
    expect(ui.el("split-submit")).to_be_visible()
    state(ui, "split", "empty")
    ui.fill("split-amount", "10.005")
    ui.fill("split-handles", "ada,bob")
    ui.click("split-submit")
    expect(ui.el("split-error")).to_be_visible()
    state(ui, "split", "refused")
    ui.fill("split-amount", "10.00")
    ui.fault("/splits", "POST", "abort-before")
    ui.click("split-submit")
    expect(ui.el("split-uncertain")).to_be_visible()
    state(ui, "split", "uncertain")
    ui.click("split-submit")
    expect(ui.el("split-success")).to_be_visible()
    state(ui, "split", "success")


def test_authorizations_states(world, ui):
    ui.log_in("cy", route="/authorizations")
    expect(ui.el("empty-authorizations")).to_be_visible()
    state(ui, "authorizations", "empty")
    ui.fill("authorize-handle", "ada")
    ui.fill("authorize-amount", "9.00")
    ui.click("authorize-submit")
    expect(ui.el("authorize-error")).to_be_visible()
    state(ui, "authorizations", "authorize-refused")
    ui.fill("authorize-amount", "2.00")
    ui.fault("/authorizations", "POST", "abort-before")
    ui.click("authorize-submit")
    expect(ui.el("authorize-uncertain")).to_be_visible()
    state(ui, "authorizations", "authorize-uncertain")
    ui.click("authorize-submit")
    expect(ui.el("authorize-success")).to_be_visible()
    expect(ui.el("wallet-held")).to_be_visible()
    state(ui, "authorizations", "authorize-success")
    a = expect_status(world.bob.authorize("cy", 300), 201)["authorization_id"]
    ui.page.reload()
    expect(ui.el(f"authorization-capture-{a}")).to_be_visible()
    ui.fill(f"authorization-capture-amount-{a}", "4.00")
    ui.click(f"authorization-capture-{a}")
    expect(ui.el("authorization-error")).to_be_visible()
    state(ui, "authorizations", "capture-refused")
    ui.fault(f"/authorizations/{a}/capture", "POST", "abort-before")
    ui.fill(f"authorization-capture-amount-{a}", "1.00")
    ui.click(f"authorization-capture-{a}")
    expect(ui.el("authorization-uncertain")).to_be_visible()
    state(ui, "authorizations", "capture-uncertain")
    ui.click(f"authorization-capture-{a}")
    expect(ui.el(f"authorization-item-{a}")).to_have_attribute("data-status", "captured")
    state(ui, "authorizations", "capture-success")


LONG_A, LONG_B = "w" * 20, "m" * 20                 # the longest handles (20 code points)
LONG_NOTE = "W" * 200                                # the longest note, with no break opportunity


@pytest.mark.parametrize("page", ["w375"], indirect=True)
def test_the_longest_names_handles_and_notes_pass_the_layout_checks_at_375(svc, ui):
    """W11.4, I46 (plan d29e313; critic U40): a 200-character note without spaces, 100-character display names
    and 20-character handles on every screen."""
    users = [user(LONG_A, 10 ** 12, display_name="W" * 100), user(LONG_B, 10 ** 12, display_name="M" * 100)]
    pays = [{"id": "p_1", "from_user_id": f"u_{LONG_B}", "to_user_id": f"u_{LONG_A}", "amount": 123_456_789,
             "note": LONG_NOTE},
            {"id": "p_2", "from_user_id": f"u_{LONG_A}", "to_user_id": f"u_{LONG_B}", "amount": 1, "note": LONG_NOTE,
             "visibility": "private"}]
    reqs = [{"id": "rq_1", "requester_id": f"u_{LONG_B}", "payer_id": f"u_{LONG_A}", "amount": 999_999_999,
             "note": LONG_NOTE, "status": "pending"},
            {"id": "rq_2", "requester_id": f"u_{LONG_A}", "payer_id": f"u_{LONG_B}", "amount": 5, "note": LONG_NOTE,
             "status": "pending"}]
    auths = [seeded_auth("a_1", LONG_B, LONG_A, 999_999_999, note=LONG_NOTE),
             seeded_auth("a_2", LONG_A, LONG_B, 7, note=LONG_NOTE)]
    svc.must_reset(fixture(users, payments=pays, requests=reqs, authorizations=auths))
    ui.log_in(LONG_A)
    for route, anchor in (("/", "activity-item-p_1"), ("/requests", "request-item-rq_1"),
                          ("/authorizations", "authorization-item-a_1"), ("/split", "split-submit")):
        ui.goto(route, anchor)
        expect(ui.el("current-user")).to_be_visible()
        ui.page.wait_for_timeout(200)
        ui.check_layout(f"{route} with the longest names, handles and notes")
