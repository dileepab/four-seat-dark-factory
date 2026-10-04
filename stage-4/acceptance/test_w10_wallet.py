"""W10.1, W10.2, W10.4, W10.5, W10.6 — the wallet screen `/` (stage-2 "Balance and pay",
"Activity feed", "Competing clients"; PLAN 3.14, D42, D44, D45, D56, D63). I39-I45."""
from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from support import expect as expect_status
from support import fixture, seeded_auth, standard_users, user
from ui import money, sel

pytestmark = pytest.mark.item(10)

KEY = re.compile(r"^[0-9a-f]{32}$")


def open_wallet(ui, handle="ada"):
    ui.log_in(handle, route="/")
    expect(ui.el("wallet-available")).to_be_visible()


def submit_pay(ui):
    ui.click("pay-submit")


def no_post_after(ui, path, n_before):
    ui.page.wait_for_timeout(400)
    sent = ui.writes(path)
    assert len(sent) == n_before, f"the form sent a request it should have refused: {sent[n_before:]}"


# ---------------------------------------------------------------- W10.1 wallet numbers

def test_wallet_numbers_with_no_holds(world, ui):
    open_wallet(ui)
    ui.wallet(10_000)
    ui.shot("wallet", "loaded")


def test_seeded_open_holds_show_right_after_reset(svc, ui):
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_1", "ada", "bob", 2_000), seeded_auth("a_2", "ada", "cy", 345),
        seeded_auth("a_3", "ada", "bob", 999, status="voided")]))
    open_wallet(ui)
    ui.wallet(10_000, held=2_345)
    ui.shot("wallet", "held")


@pytest.mark.parametrize("currency,units,balance,text", [
    ("EUR", 2, 5, "0.05 EUR"), ("EUR", 2, 0, "0.00 EUR"), ("EUR", 2, 123_456_789, "1234567.89 EUR"),
    ("JPY", 0, 1_200, "1200 JPY"), ("JPY", 0, 0, "0 JPY"), ("BHD", 3, 10_005, "10.005 BHD"), ("BHD", 3, 7, "0.007 BHD")])
def test_wallet_formats_every_currency_exactly(svc, ui, currency, units, balance, text):
    svc.must_reset(fixture([user("ada", balance), user("bob", 1)], currency=currency))
    open_wallet(ui)
    expect(ui.el("wallet-balance")).to_have_text(text)
    expect(ui.el("wallet-available")).to_have_text(text)
    expect(ui.el("wallet-balance")).to_have_attribute("data-amount", str(balance))
    assert ui.text("wallet-balance") == text


def test_available_is_the_headline_number(svc, ui):
    svc.must_reset(fixture(standard_users(), authorizations=[seeded_auth("a_1", "ada", "bob", 2_000)],
                           payments=[{"id": "p_1", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 900}]))
    open_wallet(ui)
    expect(ui.el("wallet-held")).to_be_visible()
    sizes = ui.page.evaluate("""() => {
        const px = (el) => parseFloat(getComputedStyle(el).fontSize);
        const out = {};
        for (const el of document.querySelectorAll('[data-testid]')) {
            if (/\\d(\\.\\d+)? [A-Z]{3}$/.test(el.textContent.trim()) && el.getClientRects().length)
                out[el.getAttribute('data-testid')] = px(el);
        }
        return out;
    }""")
    head = sizes.pop("wallet-available")
    assert sizes and all(head > v for v in sizes.values()), f"wallet-available must be the largest money figure: {head} vs {sizes}"


# ---------------------------------------------------------------- W10.2 pay form

@pytest.mark.parametrize("typed,minor", [("15", 1500), ("15.00", 1500), ("15.5", 1550), (" 15.5 ", 1550),
                                         ("0.01", 1), ("100", 10_000)])
def test_typed_decimal_becomes_minor_units(world, ui, typed, minor):
    open_wallet(ui)
    ui.pay_form("bob", typed)
    submit_pay(ui)
    ui.wallet(10_000 - minor)
    sent = ui.writes("/payments")
    assert len(sent) == 1 and sent[0].body["amount"] == minor and sent[0].body["to_handle"] == "bob"
    assert type(sent[0].body["amount"]) is int


@pytest.mark.parametrize("currency,typed,minor", [("JPY", "15", 15), ("JPY", "1200", 1_200),
                                                  ("BHD", "1.005", 1_005), ("BHD", "2.5", 2_500), ("BHD", "3", 3_000)])
def test_decimal_rules_follow_minor_units(svc, ui, currency, typed, minor):
    svc.must_reset(fixture([user("ada", 100_000), user("bob", 0)], currency=currency))
    open_wallet(ui)
    ui.pay_form("bob", typed)
    submit_pay(ui)
    expect(ui.el("wallet-balance")).to_have_attribute("data-amount", str(100_000 - minor))
    assert ui.writes("/payments")[0].body["amount"] == minor


INVALID = ["abc", "15.005", "1e3", "-1", "1,5", "", "   ", "0", "0.00", "10000000.01", "99999999999", ".5", "5.",
           "1 000", "+5", "1.2.3", "１５"]


@pytest.mark.parametrize("typed", INVALID, ids=repr)
def test_invalid_amount_shows_pay_error_and_sends_nothing(world, ui, typed):
    open_wallet(ui)
    ui.absent("pay-error")
    ui.pay_form("bob", typed)
    expect(ui.el("pay-submit")).to_be_enabled()
    submit_pay(ui)
    expect(ui.el("pay-error")).to_be_visible()
    assert ui.text("pay-error")
    no_post_after(ui, "/payments", 0)
    ui.wallet(10_000)
    assert ui.el("pay-amount").input_value() == typed, "inputs are kept"


@pytest.mark.parametrize("currency,typed", [("JPY", "15.0"), ("JPY", "1.5"), ("BHD", "1.0005")])
def test_more_places_than_minor_units_is_refused(svc, ui, currency, typed):
    svc.must_reset(fixture([user("ada", 100_000), user("bob", 0)], currency=currency))
    open_wallet(ui)
    ui.pay_form("bob", typed)
    submit_pay(ui)
    expect(ui.el("pay-error")).to_be_visible()
    no_post_after(ui, "/payments", 0)


def test_note_limits_count_code_points(world, ui):
    open_wallet(ui)
    assert ui.el("pay-note").get_attribute("maxlength") is None
    ui.pay_form("bob", "1", note="😀" * 201)
    submit_pay(ui)
    expect(ui.el("pay-error")).to_be_visible()
    no_post_after(ui, "/payments", 0)
    ui.fill("pay-note", "😀" * 200)
    submit_pay(ui)
    ui.wallet(9_900)
    assert ui.writes("/payments")[0].body["note"] == "😀" * 200
    ui.absent("pay-error")


def test_amount_inputs_are_text_with_decimal_keyboard(world, ui):
    open_wallet(ui)
    for tid in ("pay-amount", "request-amount"):
        assert ui.el(tid).get_attribute("type") in (None, "text")
        assert ui.el(tid).get_attribute("inputmode") == "decimal"


def test_visibility_select_and_default(world, ui):
    open_wallet(ui)
    values = ui.page.eval_on_selector(sel("pay-visibility"), "s => Array.from(s.options).map(o => o.value)")
    assert sorted(values) == ["private", "public"]
    assert ui.el("pay-visibility").input_value() == "public"
    ui.pay_form("bob", "2.00", note="secret", visibility="private")
    submit_pay(ui)
    ui.wallet(9_800)
    pid = world.ada.feed()[0]["payment_id"]
    expect(ui.el(f"activity-item-{pid}")).to_have_attribute("data-visibility", "private")
    assert ui.writes("/payments")[0].body["visibility"] == "private"


@pytest.mark.parametrize("typed", ["@bob", "  bob ", " @bob"])
def test_handle_is_trimmed_and_one_at_sign_removed(world, ui, typed):
    open_wallet(ui)
    ui.pay_form(typed, "1")
    submit_pay(ui)
    ui.wallet(9_900)
    assert ui.writes("/payments")[0].body["to_handle"] == "bob"


@pytest.mark.parametrize("handle", ["nobody", "ada"])
def test_unknown_or_own_handle_shows_pay_error(world, ui, handle):
    open_wallet(ui)
    ui.pay_form(handle, "1.00")
    submit_pay(ui)
    expect(ui.el("pay-error")).to_be_visible()
    assert not re.fullmatch(r"[a-z_]+", ui.text("pay-error")), "a human message, not a code"
    ui.wallet(10_000)
    ui.shot("wallet", "pay-refused")


def test_insufficient_available_shows_pay_error_when_total_would_cover_it(world, ui):
    expect_status(world.ada.authorize("bob", 9_000), 201)
    open_wallet(ui)
    ui.wallet(10_000, held=9_000)
    ui.pay_form("cy", "15.00")
    submit_pay(ui)
    expect(ui.el("pay-error")).to_be_visible()
    ui.wallet(10_000, held=9_000)


def test_refusal_rereads_the_wallet_and_feed_and_keeps_every_input(world, ui):
    open_wallet(ui)
    ui.wallet(10_000)
    spent = expect_status(world.ada.pay("cy", 9_000, note="elsewhere"), 201)   # another client spends it
    ui.pay_form("bob", "20.00", note="dinner", visibility="private")
    submit_pay(ui)
    expect(ui.el("pay-error")).to_be_visible()
    ui.wallet(1_000)
    expect(ui.el(f"activity-item-{spent['payment_id']}")).to_be_visible()
    assert ui.el("pay-handle").input_value() == "bob"
    assert ui.el("pay-amount").input_value() == "20.00"
    assert ui.el("pay-note").input_value() == "dinner"
    assert ui.el("pay-visibility").input_value() == "private"


def test_success_updates_numbers_and_feed_without_a_reload_and_keeps_values(world, ui):
    open_wallet(ui)
    navigations = []
    ui.page.on("framenavigated", lambda f: navigations.append(f.url) if f == ui.page.main_frame else None)
    ui.pay_form("bob", "15.00", note="dinner")
    submit_pay(ui)
    ui.wallet(8_500)
    expect(ui.el("pay-success")).to_be_visible()
    ui.absent("pay-error")
    ui.absent("pay-uncertain")
    pid = world.ada.feed()[0]["payment_id"]
    expect(ui.el(f"activity-amount-{pid}")).to_have_text(money(1_500))
    assert (ui.el("pay-handle").input_value(), ui.el("pay-amount").input_value(), ui.el("pay-note").input_value()) == \
        ("bob", "15.00", "dinner")
    ui.shot("wallet", "pay-success")
    ui.fill("pay-note", "dinner!")
    ui.absent("pay-success")


def test_unchanged_resubmission_replays_with_the_same_key_and_body(world, ui):
    open_wallet(ui)
    ui.pay_form("bob", "15.00", note="once")
    submit_pay(ui)
    ui.wallet(8_500)
    submit_pay(ui)
    expect(ui.el("pay-success")).to_be_visible()
    ui.page.wait_for_timeout(500)
    ui.absent("pay-error")
    ui.wallet(8_500)
    sent = ui.writes("/payments")
    assert len(sent) == 2 and sent[0].key == sent[1].key and sent[0].body == sent[1].body, sent
    assert KEY.match(sent[0].key), f"PLAN 3.14: the key is 128 random bits in hex: {sent[0].key!r}"
    assert len([p for p in world.ada.feed() if p["note"] == "once"]) == 1


@pytest.mark.parametrize("field,value", [("pay-amount", "16.00"), ("pay-note", "again"), ("pay-handle", "cy")])
def test_changing_any_field_makes_a_new_payment(world, ui, field, value):
    open_wallet(ui)
    ui.pay_form("bob", "15.00", note="first")
    submit_pay(ui)
    ui.wallet(8_500)
    ui.fill(field, value)
    submit_pay(ui)
    expect(ui.el("pay-success")).to_be_visible()
    sent = ui.writes("/payments")
    assert len(sent) == 2 and sent[0].key != sent[1].key, sent
    assert len(world.ada.feed()) == 2


def test_changing_visibility_makes_a_new_payment(world, ui):
    open_wallet(ui)
    ui.pay_form("bob", "1.00")
    submit_pay(ui)
    ui.wallet(9_900)
    ui.el("pay-visibility").select_option("private")
    submit_pay(ui)
    ui.wallet(9_800)
    sent = ui.writes("/payments")
    assert sent[0].key != sent[1].key


def test_data_is_reread_only_after_the_write_answered(world, ui):
    """I43: no read of /me or /activity starts while the payment is in flight."""
    open_wallet(ui)
    ui.page.wait_for_load_state("networkidle")
    held = ui.hold("/payments", "POST", fetch_first=True)
    ui.pay_form("bob", "3.00")
    submit_pay(ui)
    ui.page.wait_for_timeout(1_200)
    assert held.routes, "the payment was not sent"
    post_at = max(i for i, c in enumerate(ui.calls) if c.method == "POST" and c.path == "/payments")
    early = [c for c in ui.calls[post_at + 1:] if c.method == "GET" and c.path in ("/me", "/activity")]
    held.release()
    ui.wallet(9_700)
    assert not early, f"data was re-read before the payment answered: {early}"
    expect(ui.el("pay-submit")).to_be_enabled()


# ---------------------------------------------------------------- W10.4 request form

def test_request_form_creates_a_request_with_the_decimal_rules(world, ui):
    open_wallet(ui)
    ui.fill("request-handle", "@bob")
    ui.fill("request-amount", "12.5")
    ui.fill("request-note", "taxi")
    ui.click("request-submit")
    expect(ui.el("request-success")).to_be_visible()
    ui.absent("request-error")
    sent = ui.writes("/requests")
    assert len(sent) == 1 and sent[0].body == {"payer_handle": "bob", "amount": 1_250, "note": "taxi"}
    rq = world.bob.requests()
    assert len(rq) == 1 and rq[0]["amount"] == 1_250 and rq[0]["requester_handle"] == "ada"
    ui.shot("wallet", "request-success")


@pytest.mark.parametrize("handle,amount,server", [("nobody", "1", True), ("ada", "1", True), ("bob", "1.234", False),
                                                  ("bob", "abc", False), ("bob", "0", False)])
def test_request_form_refusals_show_request_error(world, ui, handle, amount, server):
    open_wallet(ui)
    ui.fill("request-handle", handle)
    ui.fill("request-amount", amount)
    ui.click("request-submit")
    expect(ui.el("request-error")).to_be_visible()
    ui.absent("request-success")
    if not server:
        no_post_after(ui, "/requests", 0)
    assert world.bob.requests() == []


def test_request_form_unchanged_resubmission_creates_one_request(world, ui):
    open_wallet(ui)
    ui.fill("request-handle", "bob")
    ui.fill("request-amount", "3")
    ui.click("request-submit")
    expect(ui.el("request-success")).to_be_visible()
    ui.click("request-submit")
    ui.page.wait_for_timeout(500)
    ui.absent("request-error")
    sent = ui.writes("/requests")
    assert len(sent) == 2 and sent[0].key == sent[1].key and sent[0].body == sent[1].body
    assert len(world.bob.requests()) == 1
    ui.fill("request-amount", "4")
    ui.click("request-submit")
    expect(ui.el("request-success")).to_be_visible()
    ui.page.wait_for_timeout(300)
    assert len(world.bob.requests()) == 2


# ---------------------------------------------------------------- W10.5 activity feed

def feed_children(ui) -> list[str]:
    return ui.page.eval_on_selector_all(f"{sel('activity-list')} > *",
                                        "els => els.map(e => e.getAttribute('data-testid'))")


def test_feed_items_carry_their_parts(world, ui):
    pub = expect_status(world.bob.pay("ada", 2_500, note="dinner"), 201)
    priv = expect_status(world.ada.pay("cy", 7, note="", visibility="private"), 201)
    open_wallet(ui)
    for p, vis in ((pub, "public"), (priv, "private")):
        pid = p["payment_id"]
        expect(ui.el(f"activity-item-{pid}")).to_have_attribute("data-visibility", vis)
        parties = ui.text(f"activity-parties-{pid}")
        assert p["from_handle"] in parties and p["to_handle"] in parties
        expect(ui.el(f"activity-amount-{pid}")).to_have_text(money(p["amount"]))
        assert ui.text(f"activity-amount-{pid}") == money(p["amount"])
    expect(ui.el(f"activity-note-{pub['payment_id']}")).to_have_text("dinner")
    expect(ui.el(f"activity-note-{priv['payment_id']}")).to_be_attached()
    assert ui.el(f"activity-note-{priv['payment_id']}").text_content() == ""
    ui.absent("empty-activity")


def test_feed_items_are_direct_children_in_api_order(world, ui):
    made = [expect_status(world.ada.pay("bob", 10 + i), 201) for i in range(4)]
    made.append(expect_status(world.bob.pay("cy", 3, visibility="private"), 201))       # hidden from ada
    open_wallet(ui)
    expect(ui.el(f"activity-item-{made[3]['payment_id']}")).to_be_visible()
    order = [t for t in feed_children(ui) if t and t.startswith("activity-item-")]
    assert order == [f"activity-item-{p['payment_id']}" for p in world.ada.feed()]
    assert f"activity-item-{made[4]['payment_id']}" not in order


def test_empty_activity_replaces_the_list(world, ui):
    expect_status(world.bob.pay("cy", 1, visibility="private"), 201)
    open_wallet(ui, "dee")
    expect(ui.el("empty-activity")).to_be_visible()
    ui.absent("activity-list")
    ui.shot("wallet", "empty")


def test_capture_payments_show_by_the_ordinary_rule(world, ui):
    a = expect_status(world.bob.authorize("ada", 400, note="deposit", visibility="private"), 201)
    p = expect_status(world.ada.capture(a["authorization_id"]), 201)
    open_wallet(ui)
    expect(ui.el(f"activity-item-{p['payment_id']}")).to_have_attribute("data-visibility", "private")
    expect(ui.el(f"activity-note-{p['payment_id']}")).to_have_text("deposit")
    ui.wallet(10_400)


def test_more_than_one_page_of_payments_renders_every_item_once(svc, ui):
    """D64 (plan 45fe2dc): every visible payment, read from the bare path and then page by page."""
    pays = [{"id": f"p_{i:03d}", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": i + 1,
             "note": f"n{i}"} for i in range(205)]
    pays.append({"id": "p_hidden", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 1, "visibility": "private"})
    svc.must_reset(fixture(standard_users(), payments=pays))
    open_wallet(ui)
    expect(ui.el("activity-item-p_000")).to_be_attached()
    order = [t for t in feed_children(ui) if t and t.startswith("activity-item-")]
    assert order == [f"activity-item-p_{i:03d}" for i in reversed(range(205))], \
        f"{len(order)} items; every visible payment once, newest first"
    first = ui.reads("/activity")[0]
    assert first.query == "", f"D64: the first feed read is the bare path, got ?{first.query}"
    assert ui.reads("/me")[0].query == ""


def test_a_payment_made_between_page_reads_leaves_every_item_once(svc, ui):
    """W10.5, D64 (plan d29e313; critic U06): pages shift under a write made between two page reads; each
    payment is still shown once."""
    n = 250
    pays = [{"id": f"p_{i:03d}", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": i + 1, "note": f"n{i}"}
            for i in range(n)]
    svc.must_reset(fixture(standard_users(), payments=pays))
    ui.log_in("ada")
    bob = svc.client("bob")
    made = []

    def between_pages(route):
        url = urlsplit(route.request.url)
        if route.request.method == "GET" and url.path == "/activity" and "offset=" in url.query and not made:
            made.append(expect_status(bob.pay("ada", 7, note="between pages"), 201))
        route.fallback()

    ui.page.route("**/*", between_pages)
    ui.goto("/")
    expect(ui.el("activity-item-p_000")).to_be_attached()
    assert made, "the feed was read in one page; this probe cannot run"
    ids = [t for t in feed_children(ui) if t and t.startswith("activity-item-")]
    dupes = sorted({t for t in ids if ids.count(t) > 1})
    assert not dupes, f"shown more than once: {dupes}"
    missing = sorted({f"activity-item-p_{i:03d}" for i in range(n)} - set(ids))
    assert not missing, f"missing: {missing[:5]}"


LISTS = {"/": ("/activity", ["activity-list"], "activity-item-", "empty-activity"),
         "/requests": ("/requests", ["incoming-list", "outgoing-list"], "request-item-", "empty-requests"),
         "/authorizations": ("/authorizations", ["authorization-list"], "authorization-item-", "empty-authorizations")}


@pytest.mark.parametrize("screen", ["/", pytest.param("/requests", marks=pytest.mark.item(11)),
                                    pytest.param("/authorizations", marks=pytest.mark.item(11))])
def test_a_failed_later_page_is_a_load_error_never_a_short_list(svc, ui, screen):
    """W10.5, 3.14 load-error, D64 (plan d29e313; critic U30): a load whose later page fails is a failed load."""
    n = 250
    if screen == "/":
        fx = fixture(standard_users(), payments=[
            {"id": f"p_{i:03d}", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": i + 1} for i in range(n)])
    elif screen == "/requests":
        fx = fixture(standard_users(), requests=[
            {"id": f"rq_{i:03d}", "requester_id": "u_bob", "payer_id": "u_ada", "amount": i + 1, "status": "pending"}
            for i in range(n)])
    else:
        fx = fixture(standard_users(), authorizations=[
            seeded_auth(f"a_{i:03d}", "bob", "ada", i + 1, status="voided") for i in range(n)])
    svc.must_reset(fx)
    path, containers, prefix, empty = LISTS[screen]
    ui.log_in("ada")
    ui.fault(path, "GET", "abort-before", query="offset=", count=50)
    ui.goto(screen)
    expect(ui.el("load-error")).to_be_visible()
    assert any("offset=" in r.query for r in ui.reads(path)), "no later page was read; this probe cannot run"
    shown = sum(ui.page.eval_on_selector_all(f"{sel(c)} > *", "(els, p) => els.filter(e => "
                                             "(e.getAttribute('data-testid') || '').startsWith(p)).length", prefix)
                for c in containers if ui.el(c).count())
    assert shown in (0, n), f"{shown} of {n} items shown as if the list were complete"
    ui.absent(empty)


# ---------------------------------------------------------------- W10.6 refresh

# ---------------------------------------------------------------- W10.6 refresh

def test_refresh_shows_another_clients_payment_and_keeps_the_form(world, ui):
    open_wallet(ui)
    ui.pay_form("cy", "4.20", note="draft")
    p = expect_status(world.bob.pay("ada", 300), 201)
    ui.click("wallet-refresh")
    ui.wallet(10_300)
    expect(ui.el(f"activity-item-{p['payment_id']}")).to_be_visible()
    assert (ui.el("pay-handle").input_value(), ui.el("pay-amount").input_value(), ui.el("pay-note").input_value()) == \
        ("cy", "4.20", "draft")


def test_refresh_shows_new_holds(world, ui):
    open_wallet(ui)
    expect_status(world.ada.authorize("bob", 1_234), 201)
    ui.click("wallet-refresh")
    ui.wallet(10_000, held=1_234)


def test_latest_refresh_wins_when_the_earlier_one_answers_last(world, ui):
    """D63: wallet-refresh stays clickable while its load is pending; the newer load wins."""
    open_wallet(ui)
    ui.page.wait_for_load_state("networkidle")
    first = expect_status(world.bob.pay("ada", 300), 201)            # what the first refresh will read
    held_me = ui.hold("/me", "GET", fetch_first=True, count=1)
    held_feed = ui.hold("/activity", "GET", fetch_first=True, count=1)
    ui.click("wallet-refresh")
    ui.page.wait_for_timeout(600)
    assert held_me.routes and held_feed.routes, "the first refresh did not read /me and /activity"
    second = expect_status(world.bob.pay("ada", 200), 201)
    expect(ui.el("wallet-refresh")).to_be_enabled()
    ui.click("wallet-refresh")
    ui.wallet(10_500)
    expect(ui.el(f"activity-item-{second['payment_id']}")).to_be_visible()
    held_me.release()
    held_feed.release()
    ui.page.wait_for_timeout(800)
    ui.wallet(10_500)
    expect(ui.el(f"activity-item-{second['payment_id']}")).to_be_visible()
    expect(ui.el(f"activity-item-{first['payment_id']}")).to_be_visible()


def test_a_write_reload_beats_a_slow_earlier_refresh(world, ui):
    open_wallet(ui)
    ui.page.wait_for_load_state("networkidle")
    held = ui.hold("/me", "GET", fetch_first=True, count=1)
    ui.click("wallet-refresh")
    ui.page.wait_for_timeout(600)
    assert held.routes
    ui.pay_form("bob", "1.00")
    submit_pay(ui)
    ui.wallet(9_900)
    held.release()
    ui.page.wait_for_timeout(800)
    ui.wallet(9_900)


def test_a_stale_refresh_that_times_out_after_a_later_one_was_shown_leaves_no_load_error(world, ui):
    """W10.5, I44 (plan d29e313; critic U05): a load's failure applies only if no later load of it was applied."""
    open_wallet(ui)
    ui.page.wait_for_load_state("networkidle")
    held = ui.hold("/me", "GET", count=1)              # never answered: the page gives up on it at 4 s
    clicked = time.monotonic()
    ui.click("wallet-refresh")
    ui.page.wait_for_timeout(500)
    assert held.routes, "the first refresh did not read /me"
    expect_status(world.bob.pay("ada", 300), 201)
    ui.click("wallet-refresh")
    ui.wallet(10_300)                                  # the later refresh is shown
    ui.page.wait_for_timeout(max(0, (5.2 - (time.monotonic() - clicked)) * 1_000))   # past the first load's 4 s
    ui.absent("load-error")
    ui.wallet(10_300)
    held.release()
