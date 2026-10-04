"""W13 — UI presentation fixes (stage-2 "UI": "status, direction, privacy and money movement should be
understandable without interpreting raw API data"; "The required flows must remain clear and usable at a
375 CSS-pixel viewport"; PLAN 3.14, W13.1, W13.2). W13.3 is checked in review, not here."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from support import expect as expect_status
from support import fixture, seeded_auth, standard_users
from ui import money, sel

pytestmark = pytest.mark.item(13)

# The computed colour of the element that holds an element's first piece of text (the colour it is drawn in).
TEXT_COLOUR_JS = """el => {
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode())
    if (n.textContent.trim()) return getComputedStyle(n.parentElement).color;
  return getComputedStyle(el).color;
}"""

# How many lines an element's text takes, where its text box sits, and whether an ancestor clips it.
LINES_JS = """el => {
  const range = document.createRange();
  range.selectNodeContents(el);
  const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0)
    .sort((a, b) => a.top - b.top);
  let lines = 0, bottom = -Infinity;
  for (const r of rects) if (r.top >= bottom - 1) { lines += 1; bottom = r.bottom; } else bottom = Math.max(bottom, r.bottom);
  const box = range.getBoundingClientRect();
  const clipped = [];
  for (let a = el.parentElement; a; a = a.parentElement) {
    const s = getComputedStyle(a);
    if (s.overflowX !== 'visible' && a !== document.documentElement && a !== document.body) {
      const ab = a.getBoundingClientRect();
      if (box.left < ab.left - 1 || box.right > ab.right + 1)
        clipped.push(`${a.tagName.toLowerCase()}[data-testid=${a.getAttribute('data-testid')}]`);
    }
  }
  return {lines, left: box.left, right: box.right, vw: document.documentElement.clientWidth,
          text: el.textContent, clipped};
}"""


def colour(ui, testid: str) -> str:
    return ui.page.eval_on_selector(sel(testid), TEXT_COLOUR_JS)


@pytest.fixture
def directions(svc):
    """Ada would pay rq_in (incoming) and would receive rq_out (outgoing); bob has paid her; bob holds for her."""
    svc.must_reset(fixture(standard_users(), authorizations=[seeded_auth("a_for_ada", "bob", "ada", 450)], requests=[
        {"id": "rq_in", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1_200, "note": "ada pays",
         "status": "pending"},
        {"id": "rq_out", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 345, "note": "ada receives",
         "status": "pending"}]))
    received = expect_status(svc.client("bob").pay("ada", 250, note="to ada"), 201)
    return received["payment_id"]


def test_an_amount_the_viewer_would_pay_is_not_coloured_as_money_received(directions, ui):
    """W13.1: on /requests the incoming (to pay) amount is not drawn in the colour of a received payment in the
    feed, nor in that of a hold held for the viewer; request amounts stay exactly the formatted amount."""
    ui.log_in("ada")
    expect(ui.el(f"activity-amount-{directions}")).to_have_text(money(250))
    received = colour(ui, f"activity-amount-{directions}")
    ui.goto("/authorizations", "authorization-list")
    expect(ui.el("authorization-amount-a_for_ada")).to_have_text(money(450))
    held_for_ada = colour(ui, "authorization-amount-a_for_ada")
    ui.goto("/requests", "incoming-list")
    expect(ui.el("request-amount-rq_in")).to_have_text(money(1_200))
    expect(ui.el("request-amount-rq_out")).to_have_text(money(345))
    to_pay = colour(ui, "request-amount-rq_in")
    assert to_pay != received, f"the amount ada would pay is drawn in {to_pay}, the colour of a received payment"
    assert to_pay != held_for_ada, f"the amount ada would pay is drawn in {to_pay}, the colour of a hold held for her"


@pytest.mark.parametrize("page", ["w375"], indirect=True)
def test_expiry_text_stays_on_one_line_at_375(svc, ui):
    """W13.2: at 375x812 each authorization-expires-{id} is one line, wholly inside the viewport and not cut off,
    and the page does not scroll horizontally."""
    svc.must_reset(fixture(standard_users(), authorizations=[
        seeded_auth("a_long", "ada", "bob", 2_000, expires_at="2099-06-15T10:20:30.123456+05:30"),
        seeded_auth("a_in", "bob", "ada", 450, note="a note long enough to wrap at three hundred and seventy-five"),
        seeded_auth("a_cap", "ada", "cy", 300, status="captured", captured_amount=120),
        seeded_auth("a_exp", "ada", "dee", 60, status="expired")]))
    issued = expect_status(svc.client("bob").authorize("ada", 900), 201)
    ui.log_in("ada", route="/authorizations")
    expect(ui.el("authorization-list")).to_be_attached()
    ids = ["a_long", "a_in", "a_cap", "a_exp", issued["authorization_id"]]
    expect(ui.el("authorization-expires-a_long")).to_have_text("2099-06-15T10:20:30.123456+05:30")
    expect(ui.el(f"authorization-expires-{issued['authorization_id']}")).to_have_text(issued["expires_at"])
    for aid in ids:
        got = ui.page.eval_on_selector(sel(f"authorization-expires-{aid}"), LINES_JS)
        assert got["lines"] == 1, f"authorization-expires-{aid} ({got['text']!r}) takes {got['lines']} lines at 375"
        assert got["left"] >= 0 and got["right"] <= got["vw"] + 0.5, \
            f"authorization-expires-{aid} runs outside the viewport: {got['left']:.1f}..{got['right']:.1f} of {got['vw']}"
        assert not got["clipped"], f"authorization-expires-{aid} is cut off by {got['clipped']}"
    sw, iw = ui.page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    assert sw <= iw, f"horizontal scroll at 375 on /authorizations: scrollWidth {sw} > innerWidth {iw}"
