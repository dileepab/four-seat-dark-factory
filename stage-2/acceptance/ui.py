"""Browser helpers for the stage-2 acceptance suite (W12.3, W12.4).

Every element is found by its `data-testid` alone (PLAN 3.14, D57). Faults are injected
with `page.route`. The I46 checks measure the rendered page: horizontal scroll, visible
labels, visible keyboard focus, text contrast and the contrast of input borders, button
boundaries and the focus indicator.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from playwright.sync_api import Page, Request, Route, expect

API_PREFIXES = ("/me", "/activity", "/payments", "/requests", "/splits", "/settlements", "/authorizations",
                "/auth/")


def sel(testid: str) -> str:
    return f"[data-testid='{testid}']"


def money(minor: int, minor_units: int = 2, currency: str = "EUR") -> str:
    """I39: `100.00 EUR`; `1200 JPY` when minor_units is 0."""
    if minor_units == 0:
        return f"{minor} {currency}"
    text = str(minor).rjust(minor_units + 1, "0")
    return f"{text[:-minor_units]}.{text[-minor_units:]} {currency}"


def decimal(minor: int, minor_units: int = 2) -> str:
    """The decimal a person types: `20.00`, or `2000` for minor_units 0."""
    return money(minor, minor_units, "X")[:-2]


class Recorded:
    def __init__(self, req: Request):
        u = urlsplit(req.url)
        self.method = req.method
        self.url = req.url
        self.path = u.path
        self.query = u.query
        self.headers = req.headers
        self.body_text = req.post_data
        self.resource = req.resource_type

    @property
    def body(self) -> Any:
        return json.loads(self.body_text) if self.body_text else None

    @property
    def key(self) -> str | None:
        return self.headers.get("idempotency-key")

    def __repr__(self) -> str:
        return f"{self.method} {self.path} key={self.key} body={self.body_text}"


class Held:
    """Requests intercepted and kept unanswered until the test releases them."""

    def __init__(self):
        self.routes: list[tuple[Route, Any]] = []

    def release(self) -> None:
        for route, resp in self.routes:
            try:
                if resp is None:
                    route.continue_()
                else:
                    route.fulfill(response=resp)
            except Exception:
                pass     # the page may have given up on it already (client timeout)
        self.routes.clear()


class UI:
    def __init__(self, page: Page, svc, shots_dir: Path | None = None):
        self.page = page
        self.svc = svc
        self.shots_dir = shots_dir
        self.width = getattr(page, "width_id", "w")
        self.calls: list[Recorded] = []
        self.all_urls: list[str] = []
        page.on("request", self._record)

    # -- recording
    def _record(self, req: Request) -> None:
        self.all_urls.append(req.url)
        if req.resource_type in ("fetch", "xhr"):
            self.calls.append(Recorded(req))

    def writes(self, path_re: str = r".*", method: str = "POST") -> list[Recorded]:
        return [c for c in self.calls if c.method == method and re.fullmatch(path_re, c.path)]

    def reads(self, path: str) -> list[Recorded]:
        return [c for c in self.calls if c.method == "GET" and c.path == path]

    # -- elements
    def el(self, testid: str):
        return self.page.locator(sel(testid))

    def text(self, testid: str) -> str:
        return (self.el(testid).text_content() or "").strip()

    def absent(self, testid: str) -> None:
        expect(self.el(testid)).to_have_count(0)

    def visible(self, testid: str) -> None:
        expect(self.el(testid)).to_be_visible()

    def amount_is(self, testid: str, minor: int, minor_units: int = 2, currency: str = "EUR") -> None:
        loc = self.el(testid)
        expect(loc).to_have_attribute("data-amount", str(minor))
        expect(loc).to_have_text(money(minor, minor_units, currency))

    def fill(self, testid: str, value: str) -> None:
        self.el(testid).fill(value)

    def click(self, testid: str) -> None:
        self.el(testid).click()

    # -- session
    def log_in(self, handle: str, *, route: str | None = None) -> None:
        acct = self.svc.accounts[handle]
        self.page.goto("/login")
        self.fill("login-email", acct.email)
        self.fill("login-password", acct.password)
        self.click("login-submit")
        expect(self.el("current-user")).to_be_visible()
        if route is not None:
            self.goto(route)

    def goto(self, route: str, anchor: str | None = None):
        resp = self.page.goto(route)
        if anchor:
            expect(self.el(anchor)).to_be_attached()
        return resp

    def wallet(self, total: int, available: int | None = None, held: int = 0, minor_units: int = 2,
               currency: str = "EUR") -> None:
        """W10.1: wallet-available (headline), wallet-balance (total) and wallet-held (absent at 0)."""
        self.amount_is("wallet-available", total - held if available is None else available, minor_units, currency)
        self.amount_is("wallet-balance", total, minor_units, currency)
        if held:
            self.amount_is("wallet-held", held, minor_units, currency)
        else:
            self.absent("wallet-held")

    def pay_form(self, handle: str, amount: str, note: str | None = None, visibility: str | None = None) -> None:
        self.fill("pay-handle", handle)
        self.fill("pay-amount", amount)
        if note is not None:
            self.fill("pay-note", note)
        if visibility is not None:
            self.el("pay-visibility").select_option(visibility)

    # -- fault injection
    def hold(self, path_re: str, method: str = "GET", *, fetch_first: bool = False,
             count: int | None = None) -> Held:
        """Keep matching requests unanswered. With fetch_first the server answers first (it commits)."""
        held = Held()
        remaining = [count]

        def handler(route: Route) -> None:
            req = route.request
            if req.method != method or not re.fullmatch(path_re, urlsplit(req.url).path) or remaining[0] == 0:
                route.fallback()
                return
            if remaining[0] is not None:
                remaining[0] -= 1
            resp = route.fetch() if fetch_first else None
            held.routes.append((route, resp))

        self.page.route("**/*", handler)
        return held

    def fault(self, path_re: str, method: str, how: str, *, count: int = 1) -> list:
        """Break the next `count` matching requests.

        how: "abort-before" (the server never sees it), "abort-after" (the server commits, the
        response is lost), "503" (no commit, a 5xx), "500-after" (commit, then a 5xx), "html-after"
        (commit, then a 2xx body that is not JSON).
        """
        done: list = []

        def handler(route: Route) -> None:
            req = route.request
            if req.method != method or not re.fullmatch(path_re, urlsplit(req.url).path) or len(done) >= count:
                route.fallback()
                return
            done.append(req.url)
            if how == "abort-before":
                route.abort("failed")
            elif how == "abort-after":
                route.fetch()
                route.abort("failed")
            elif how == "503":
                route.fulfill(status=503, content_type="application/json",
                              body='{"error": {"code": "unavailable", "message": "try later"}}')
            elif how == "500-after":
                route.fetch()
                route.fulfill(status=500, content_type="text/plain", body="internal error")
            elif how == "html-after":
                route.fetch()
                route.fulfill(status=201, content_type="text/html", body="<html>proxy page</html>")
            else:
                raise AssertionError(how)

        self.page.route("**/*", handler)
        return done

    # -- screenshots (W12.4)
    def shot(self, screen: str, state: str) -> None:
        if self.shots_dir is None:
            return
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(self.shots_dir / f"{screen}-{state}-{self.width}.png"), full_page=True)

    # -- I46
    def check_layout(self, where: str) -> None:
        """No horizontal scroll, visible labels, text contrast, input and button boundaries."""
        report = self.page.evaluate(A11Y_JS)
        problems = []
        if report["scrollWidth"] > report["innerWidth"]:
            problems.append(f"horizontal scroll: scrollWidth {report['scrollWidth']} > innerWidth {report['innerWidth']}")
        problems += report["problems"]
        assert not problems, f"I46 at {self.width} on {where}:\n  " + "\n  ".join(problems[:15])

    def check_focus(self, where: str, presses: int = 40) -> list[str]:
        """Tab through the page; every focused element shows an outline of 2px+ at 3:1 (I46)."""
        self.page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); window.scrollTo(0, 0); }")
        seen, problems = [], []
        for _ in range(presses):
            self.page.keyboard.press("Tab")
            info = self.page.evaluate(FOCUS_JS)
            if info is None:
                continue
            if info["id"] in seen:
                break
            seen.append(info["id"])
            if info["problem"]:
                problems.append(f"{info['id']}: {info['problem']}")
        assert not problems, f"I46 focus at {self.width} on {where}:\n  " + "\n  ".join(problems[:15])
        return seen

    def same_origin_only(self, base_url: str) -> None:
        """I48: nothing from another origin."""
        origin = base_url.rstrip("/")
        foreign = [u for u in self.all_urls if not (u.startswith(origin + "/") or u == origin or u.startswith("data:"))]
        assert not foreign, f"I48: requests to another origin: {foreign[:5]}"


# Colour maths shared by the I46 checks: WCAG relative luminance and contrast, with
# alpha composited over the nearest opaque background.
_COLOUR_JS = r"""
const parse = (c) => {
  const m = c.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
  return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1};
};
const over = (top, bottom) => {
  const a = top.a + bottom.a * (1 - top.a);
  if (a === 0) return {r: 0, g: 0, b: 0, a: 0};
  const mix = (x, y) => (x * top.a + y * bottom.a * (1 - top.a)) / a;
  return {r: mix(top.r, bottom.r), g: mix(top.g, bottom.g), b: mix(top.b, bottom.b), a};
};
const lum = (c) => {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
};
const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
// The colour behind `el` (not including el's own background unless self is true); null if an image is involved.
const behind = (el, self) => {
  const layers = [];
  for (let n = self ? el : el.parentElement; n; n = n.parentElement) {
    const s = getComputedStyle(n);
    if (s.backgroundImage && s.backgroundImage !== 'none') return null;
    const c = parse(s.backgroundColor);
    if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
  }
  let acc = {r: 255, g: 255, b: 255, a: 1};
  for (let i = layers.length - 1; i >= 0; i--) acc = over(layers[i], acc);
  return acc;
};
const shown = (el) => {
  const s = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity) > 0 && r.width > 0 && r.height > 0;
};
const name = (el) => el.getAttribute('data-testid') || (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')) +
  ' "' + (el.textContent || '').trim().slice(0, 30) + '"';
"""

A11Y_JS = "() => {" + _COLOUR_JS + r"""
  const problems = [];
  // Labels: every input and select has a visible associated label.
  for (const el of document.querySelectorAll('input, select, textarea')) {
    if (el.type === 'hidden' || !shown(el)) continue;
    const labels = Array.from(el.labels || []).filter(l => {
      const r = l.getBoundingClientRect();
      return shown(l) && r.width >= 2 && r.height >= 2 && l.textContent.trim().length > 0;
    });
    if (!labels.length) problems.push('no visible <label> for ' + name(el));
  }
  // Text contrast: 4.5:1, or 3:1 for large text.
  for (const el of document.querySelectorAll('body *')) {
    if (!shown(el) || el.closest('[disabled], [aria-disabled="true"]')) continue;
    const own = Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) continue;
    const s = getComputedStyle(el);
    const bg = behind(el, true);
    const fg0 = parse(s.color);
    if (!bg || !fg0) continue;
    const fg = over(fg0, bg);
    const size = parseFloat(s.fontSize), weight = parseInt(s.fontWeight, 10) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const need = large ? 3 : 4.5;
    const got = ratio(fg, bg);
    if (got + 0.01 < need) problems.push('text contrast ' + got.toFixed(2) + ' < ' + need + ' for ' + name(el));
  }
  // Input borders and button boundaries: 3:1 against what is behind them.
  for (const el of document.querySelectorAll('input, select, textarea, button')) {
    if (el.type === 'hidden' || !shown(el) || el.disabled) continue;
    const s = getComputedStyle(el);
    const back = behind(el, false);
    if (!back) continue;
    const own = parse(s.backgroundColor);
    const fill = own && own.a > 0 ? over(own, back) : null;
    const bw = parseFloat(s.borderTopWidth) + parseFloat(s.borderBottomWidth) + parseFloat(s.borderLeftWidth) + parseFloat(s.borderRightWidth);
    const bc = parse(s.borderTopColor);
    const border = bw > 0 && s.borderTopStyle !== 'none' && bc && bc.a > 0 ? over(bc, back) : null;
    const ok = (border && ratio(border, back) >= 3) || (fill && ratio(fill, back) >= 3);
    const isButton = el.tagName === 'BUTTON';
    if (isButton && !border && !(fill && ratio(fill, back) > 1.05)) continue;   // a text-only button has no boundary
    if (!ok) problems.push((isButton ? 'button boundary' : 'input border') + ' below 3:1 for ' + name(el));
  }
  return {scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth, problems};
}"""

FOCUS_JS = "() => {" + _COLOUR_JS + r"""
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const s = getComputedStyle(el);
  const back = behind(el, false) || {r: 255, g: 255, b: 255, a: 1};
  let problem = '';
  const ow = parseFloat(s.outlineWidth) || 0;
  const oc = parse(s.outlineColor);
  const hasOutline = s.outlineStyle !== 'none' && ow >= 2 && oc && oc.a > 0;
  const shadow = s.boxShadow && s.boxShadow !== 'none';
  if (!hasOutline && !shadow) problem = 'no visible focus indicator (outline ' + s.outlineStyle + ' ' + s.outlineWidth + ')';
  else if (hasOutline && ratio(over(oc, back), back) < 3) problem = 'focus outline contrast ' + ratio(over(oc, back), back).toFixed(2) + ' < 3';
  const id = el.getAttribute('data-testid') || (el.tagName.toLowerCase() + ':' + (el.textContent || el.getAttribute('href') || '').trim().slice(0, 30));
  return {id, problem};
}"""
