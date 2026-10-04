"""W9.2-W9.4 — signup, login, logout, session, navigation and safe rendering in the browser
(stage-2 "Signup and login", route table; PLAN 3.14 session and header, D41, D59). I45, I47, I48."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from support import Account, fixture, standard_users, user
from ui import sel

pytestmark = pytest.mark.item(9)

ROUTES = {"/": "nav-wallet", "/requests": "nav-requests", "/split": "nav-split", "/authorizations": "nav-authorizations"}


# ---------------------------------------------------------------- signup (W9.2)

def test_signup_shows_the_display_name_and_the_exact_derived_handle(world, ui):
    page = ui.page
    page.goto("/signup")
    ui.absent("auth-error")
    ui.fill("signup-email", "dee.ann@example.com")
    ui.fill("signup-password", "correct horse")
    ui.fill("signup-display-name", "Dee Ann")
    with page.expect_response(lambda r: r.url.endswith("/auth/signup")) as info:
        ui.click("signup-submit")
    token = info.value.json()["token"]
    expect(ui.el("current-user")).to_be_visible()
    expect(ui.el("current-user")).to_contain_text("Dee Ann")
    expect(ui.el("current-handle")).to_have_text("dee_ann")
    assert ui.text("current-handle") == "dee_ann", "no @ and no other words in current-handle"
    expect(page).to_have_url(re.compile(r"/$"))
    stored = page.evaluate("() => Object.keys(localStorage).map(k => localStorage.getItem(k))")
    assert any(token in (v or "") for v in stored), "D41: the token is kept in localStorage"
    ui.absent("auth-error")
    world.svc.accounts["dee_ann"] = Account("dee_ann", "dee.ann@example.com", "correct horse")
    ui.shot("signup", "success")


@pytest.mark.parametrize("email,password,display,why", [
    ("ada@example.com", "correct horse", "Again", "email taken"),
    ("ada@elsewhere.example", "correct horse", "Other Ada", "handle taken"),
    ("not-an-email", "correct horse", "X", "invalid email"),
    ("short@example.com", "short", "X", "short password"),
    ("nodisplay@example.com", "correct horse", "", "empty display name"),
])
def test_refused_signup_shows_auth_error_with_a_human_message(world, ui, email, password, display, why):
    page = ui.page
    page.goto("/signup")
    ui.fill("signup-email", email)
    ui.fill("signup-password", password)
    ui.fill("signup-display-name", display)
    ui.click("signup-submit")
    expect(ui.el("auth-error")).to_be_visible()
    msg = ui.text("auth-error")
    assert msg and not re.fullmatch(r"[a-z_]+", msg), f"{why}: an error code alone is not a message: {msg!r}"
    ui.absent("current-user")
    assert page.locator(sel("signup-email")).input_value() == email, "inputs are kept"
    if why == "email taken":
        ui.shot("signup", "refused")


# ---------------------------------------------------------------- login and logout (W9.3)

@pytest.mark.parametrize("email,password", [("ada@example.com", "wrong password"), ("ghost@example.com", "whatever pw")])
def test_bad_login_shows_auth_error(world, ui, email, password):
    ui.page.goto("/login")
    ui.absent("auth-error")
    ui.shot("login", "empty")
    ui.fill("login-email", email)
    ui.fill("login-password", password)
    ui.click("login-submit")
    expect(ui.el("auth-error")).to_be_visible()
    assert ui.text("auth-error") and not re.fullmatch(r"[a-z_]+", ui.text("auth-error"))
    ui.absent("current-user")
    ui.shot("login", "refused")


def test_login_shows_the_signed_in_header_on_every_route(world, ui):
    ui.log_in("ada")
    expect(ui.page).to_have_url(re.compile(r"/$"))
    for route, nav in ROUTES.items():
        ui.page.goto(route)
        expect(ui.el("current-user")).to_be_visible()
        expect(ui.el("current-user")).to_contain_text("Ada")
        expect(ui.el("current-handle")).to_have_text("ada")
        expect(ui.el("logout-button")).to_be_visible()
        for r, n in ROUTES.items():
            expect(ui.el(n)).to_be_visible()
            expect(ui.el(n)).to_have_attribute("href", r)
        expect(ui.el(nav)).to_have_attribute("aria-current", "page")
        for other in set(ROUTES.values()) - {nav}:
            assert ui.el(other).get_attribute("aria-current") != "page", f"{other} marked current on {route}"


def test_navigation_links_move_between_screens_and_keep_the_session(world, ui):
    ui.log_in("ada")
    for route, nav in [("/requests", "nav-requests"), ("/split", "nav-split"),
                       ("/authorizations", "nav-authorizations"), ("/", "nav-wallet")]:
        ui.click(nav)
        expect(ui.page).to_have_url(re.compile(re.escape(route) + "$"))
        expect(ui.el("current-handle")).to_have_text("ada")
    ui.page.reload()
    expect(ui.el("current-handle")).to_have_text("ada")


def test_logout_clears_the_session(world, ui):
    ui.log_in("ada")
    ui.click("logout-button")
    expect(ui.el("current-user")).to_have_count(0)
    expect(ui.el("login-submit")).to_be_visible()
    for route in ROUTES:
        ui.page.goto(route)
        expect(ui.el("login-submit")).to_be_visible()
        ui.absent("current-user")
    stored = ui.page.evaluate("() => Object.keys(localStorage).map(k => localStorage.getItem(k)).join(' ')")
    assert world.ada.token not in stored


@pytest.mark.parametrize("route", list(ROUTES))
def test_signed_out_routes_show_the_login_screen(world, ui, route):
    ui.page.goto(route)
    expect(ui.el("login-submit")).to_be_visible()
    ui.absent("current-user")
    for nav in ROUTES.values():
        ui.absent(nav)


def test_login_and_signup_render_their_forms_while_signed_in(world, ui):
    ui.log_in("ada")
    ui.page.goto("/login")
    expect(ui.el("login-submit")).to_be_visible()
    ui.page.goto("/signup")
    expect(ui.el("signup-submit")).to_be_visible()
    expect(ui.el("current-user")).to_be_visible()


def test_a_401_clears_the_session_and_shows_login_without_auth_error(world, ui):
    ui.log_in("ada", route="/")
    expect(ui.el("wallet-balance")).to_be_visible()
    world.svc.must_reset(fixture(standard_users(), operators=["u_ada"]))     # every token is now unknown
    ui.click("wallet-refresh")
    expect(ui.el("login-submit")).to_be_visible()
    ui.absent("current-user")
    ui.absent("auth-error")
    ui.shot("login", "session-ended")


def test_every_api_call_carries_the_bearer_token_and_accepts_json(world, ui):
    ui.log_in("ada")
    for route in ROUTES:
        ui.page.goto(route)
        expect(ui.el("current-user")).to_be_visible()
    ui.page.wait_for_load_state("networkidle")
    api = [c for c in ui.calls if not c.path.startswith("/auth/")]
    assert api, "the pages made no API calls"
    for c in api:
        assert re.fullmatch(r"Bearer \S+", c.headers.get("authorization", "")), c
        assert "application/json" in c.headers.get("accept", ""), f"PLAN 3.14: every API call sends Accept: application/json {c}"
        assert "text/html" not in c.headers.get("accept", ""), c


def test_not_found_screen_keeps_the_navigation(world, ui):
    ui.log_in("ada")
    resp = ui.page.goto("/no/such/page")
    assert resp.status == 404
    expect(ui.el("nav-wallet")).to_be_visible()
    expect(ui.el("current-user")).to_be_visible()
    ui.shot("not-found", "signed-in")
    ui.click("nav-wallet")
    expect(ui.page).to_have_url(re.compile(r"/$"))


def test_nothing_is_loaded_from_another_origin_and_no_favicon_request(world, ui, base_url):
    ui.log_in("ada")
    for route in list(ROUTES) + ["/signup", "/login", "/nope"]:
        ui.page.goto(route)
    ui.page.wait_for_load_state("networkidle")
    ui.same_origin_only(base_url)
    assert not [u for u in ui.all_urls if u.endswith("/favicon.ico")], "PLAN 3.14: no favicon request"


# ---------------------------------------------------------------- safe rendering (I48)

HOSTILE = "<img src=x onerror=\"window.__pwned=1\"><script>window.__pwned=2</script>&amp; \"q\""


@pytest.mark.item(10)
def test_display_names_and_notes_render_as_text(svc, ui):
    svc.must_reset(fixture([user("ada", 10_000, display_name=HOSTILE), user("bob", 2_500, display_name="Bob")],
                           payments=[{"id": "p_x", "from_user_id": "u_bob", "to_user_id": "u_ada",
                                      "amount": 5, "note": HOSTILE}]))
    ui.log_in("ada", route="/")
    expect(ui.el("current-user")).to_contain_text(HOSTILE)
    expect(ui.el("activity-note-p_x")).to_have_text(HOSTILE)
    assert ui.page.evaluate("() => window.__pwned") is None
    assert ui.page.locator("img[src='x']").count() == 0


# ---------------------------------------------------------------- I46 on the signed-out screens

@pytest.mark.parametrize("route,anchor", [("/login", "login-submit"), ("/signup", "signup-submit")])
def test_signed_out_screens_pass_the_layout_checks(world, ui, route, anchor):
    ui.page.goto(route)
    expect(ui.el(anchor)).to_be_visible()
    ui.check_layout(route)
    ui.check_focus(route)
    ui.shot(route.strip("/"), "form")


def test_forms_submit_with_enter(world, ui):
    ui.page.goto("/login")
    ui.fill("login-email", "ada@example.com")
    ui.fill("login-password", world.svc.accounts["ada"].password)
    ui.el("login-password").press("Enter")
    expect(ui.el("current-user")).to_be_visible()
