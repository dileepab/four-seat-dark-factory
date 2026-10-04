"""Shared helpers for the stage-3 acceptance suite.

Owned by the verifier. Written from the specifications
(`/Users/Dileepa/df-spec/pocketful/spec/stage-1.md`, `stage-2.md` and `stage-3.md`) and
`stage-3/PLAN.md` only, never from the implementation. Everything here talks to the
service over HTTP.

Invariant tracking: a `Service` remembers the total seeded by the last accepted
reset (or carried by the last accepted import) and every account it knows. After
each test the `svc` fixture asserts, over those accounts, I1 (the `total`s sum to the
seeded total), I2 (no negative `total`, `available` or `held`; `held <= total`) and I30
(`balance == total`, `available == total - held`, `held` = the open outgoing
remainders). `Service.burst` asserts I2 on reads taken *during* a burst and I1 right
after it.

Stage 3 (`Service.history_checks`, on for `--upto 14` and later): after each test the
`svc` fixture also asserts I1 in historical views (the `total`s at `as_of`/`known_at`
instants sum to the seeded total) and, for a consistent seeded history, I2 and I60 at
every instant at which a tracked account's payments take effect or its holds change
(`Service.assert_history_invariants`). Exact instants (PLAN 3.4) are handled by
`instant` and `fmt_instant`, which never round.
"""
from __future__ import annotations

import calendar
import copy
import json as _json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from typing import Any, Callable

import httpx

REQUEST_TIMEOUT = 5.0     # §2: per-request timeout
RESET_TIMEOUT = 10.0      # §2 and §10: reset, export and import
MAX_AMOUNT = 1_000_000_000
TWO_53 = 2 ** 53
MAX_TRACKED_FOR_CHECK = 80   # accounts summed after each test; larger worlds opt out
MAX_TRACKED_FOR_HISTORY = 8  # accounts whose history is walked after each test (stage 3)
HISTORY_SAMPLE = 12          # instants checked per teardown, spread over the whole history

_UNSET = object()


def new_key() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------- HTTP client

class Api:
    """A small httpx wrapper that carries one bearer token.

    `json=` is serialised with `ensure_ascii=False`, so non-ASCII text travels as
    raw UTF-8 (what "byte for byte" in §8 is about). `json=None` sends the JSON
    literal `null`; omit `json` to send no body. `content=` sends raw bytes.
    `headers` entries override the defaults; a value of None removes a header.
    """

    def __init__(self, base_url: str, token: str | None = None,
                 timeout: float = REQUEST_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, path: str, *, json: Any = _UNSET,
                content: bytes | str | None = None, key: str | None = None,
                token: Any = _UNSET, headers: dict | None = None,
                params: Any = None, timeout: float | None = None) -> httpx.Response:
        hdrs: dict[str, Any] = {}
        tok = self.token if token is _UNSET else token
        if tok is not None:
            hdrs["Authorization"] = f"Bearer {tok}"
        if key is not None:
            hdrs["Idempotency-Key"] = key
        if json is not _UNSET:
            content = _json.dumps(json, ensure_ascii=False).encode("utf-8")
        if content is not None:
            hdrs["Content-Type"] = "application/json"
        if headers:
            hdrs.update(headers)
        hdrs = {k: v for k, v in hdrs.items() if v is not None}
        kwargs: dict[str, Any] = {"headers": hdrs}
        if content is not None:
            kwargs["content"] = content.encode("utf-8") if isinstance(content, str) else content
        if params is not None:
            kwargs["params"] = params
        if timeout is not None:
            kwargs["timeout"] = timeout
        return self._client.request(method, path, **kwargs)

    def get(self, path: str, **kw) -> httpx.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> httpx.Response:
        return self.request("POST", path, **kw)

    # convenience wrappers for the wallet API
    def me(self) -> dict:
        return expect(self.get("/me"), 200)

    def balance(self) -> int:
        return self.me()["balance"]

    def pay(self, to_handle: str, amount: Any, *, key: str | None = None, **extra) -> httpx.Response:
        body = {"to_handle": to_handle, "amount": amount, **extra}
        return self.post("/payments", json=body, key=key or new_key())

    def ask(self, payer_handle: str, amount: Any, *, key: str | None = None, **extra) -> httpx.Response:
        body = {"payer_handle": payer_handle, "amount": amount, **extra}
        return self.post("/requests", json=body, key=key or new_key())

    def pay_request(self, request_id: str, body: Any = None, *, key: str | None = None) -> httpx.Response:
        return self.post(f"/requests/{request_id}/pay", json={} if body is None else body,
                         key=key or new_key())

    def decline(self, request_id: str) -> httpx.Response:
        return self.post(f"/requests/{request_id}/decline")

    def cancel(self, request_id: str) -> httpx.Response:
        return self.post(f"/requests/{request_id}/cancel")

    def split(self, amount: Any, handles: Any, *, key: str | None = None, **extra) -> httpx.Response:
        body = {"amount": amount, "participant_handles": handles, **extra}
        return self.post("/splits", json=body, key=key or new_key())

    def settle(self, transfers: Any, *, key: str | None = None, **extra) -> httpx.Response:
        return self.post("/settlements", json={"transfers": transfers, **extra},
                         key=key or new_key())

    def feed(self, **params) -> list[dict]:
        """Every payment visible to this caller, newest first, following pages."""
        return _all_pages(self, "/activity", "payments", params)

    def requests(self, **params) -> list[dict]:
        return _all_pages(self, "/requests", "requests", params)

    # stage 2: authorizations
    def authorize(self, to_handle: str, amount: Any, *, key: str | None = None, **extra) -> httpx.Response:
        body = {"to_handle": to_handle, "amount": amount, **extra}
        return self.post("/authorizations", json=body, key=key or new_key())

    def capture(self, authorization_id: str, body: Any = None, *, key: str | None = None) -> httpx.Response:
        """POST /authorizations/{id}/capture; the body defaults to `{}` (capture the remainder)."""
        return self.post(f"/authorizations/{authorization_id}/capture",
                         json={} if body is None else body, key=key or new_key())

    def void(self, authorization_id: str) -> httpx.Response:
        return self.post(f"/authorizations/{authorization_id}/void")

    def auths(self, **params) -> list[dict]:
        """Every authorization visible to this caller, newest first, following pages."""
        return _all_pages(self, "/authorizations", "authorizations", params)

    def auth(self, authorization_id: str) -> dict:
        """One authorization as GET /authorizations shows it to this caller."""
        found = [a for a in self.auths() if a["authorization_id"] == authorization_id]
        assert len(found) == 1, f"{authorization_id} appears {len(found)} times in the caller's list"
        return found[0]

    def money(self) -> tuple[int, int, int]:
        """(total, available, held) from GET /me."""
        m = self.me()
        return m["total"], m["available"], m["held"]

    # stage 3: history, statements, corrections
    def me_at(self, as_of: str | None = None, known_at: str | None = None) -> dict:
        """GET /me?as_of=&known_at= (each only when given), checked per PLAN 3.6 and I60."""
        params = {k: v for k, v in (("as_of", as_of), ("known_at", known_at)) if v is not None}
        m = expect(self.get("/me", params=params), 200)
        return check_me_view(m, as_of=as_of, known_at=known_at)

    def total_at(self, as_of: str | None = None, known_at: str | None = None) -> int:
        return self.me_at(as_of, known_at)["total"]

    def money_at(self, as_of: str | None = None, known_at: str | None = None) -> tuple[int, int, int]:
        m = self.me_at(as_of, known_at)
        return m["total"], m["available"], m["held"]

    def statement(self, **params) -> httpx.Response:
        """GET /statement with the given query parameters (None values are dropped)."""
        return self.get("/statement", params={k: v for k, v in params.items() if v is not None})

    def statement_page(self, snapshot: str, **params) -> httpx.Response:
        return self.statement(snapshot=snapshot, **params)

    def correct(self, payment_id: str, expected_revision: Any = _UNSET, amount: Any = _UNSET,
                effective_at: Any = _UNSET, reason: Any = "corrected", *, key: str | None = None,
                body: Any = _UNSET, **kw) -> httpx.Response:
        """POST /payments/{id}/corrections. Fields left _UNSET are omitted; `body` overrides them all."""
        if body is _UNSET:
            body = {k: v for k, v in (("expected_revision", expected_revision), ("amount", amount),
                                      ("effective_at", effective_at), ("reason", reason)) if v is not _UNSET}
        return self.post(f"/payments/{payment_id}/corrections", json=body, key=key or new_key(), **kw)

    def revisions_resp(self, payment_id: str) -> httpx.Response:
        return self.get(f"/payments/{payment_id}/revisions")

    def revisions(self, payment_id: str) -> list[dict]:
        """GET /payments/{id}/revisions, checked per PLAN 3.6 and I56."""
        body = expect(self.revisions_resp(payment_id), 200)
        assert isinstance(body, dict) and set(body) == {"revisions"}, f"revisions list keys: {body!r}"
        revs = body["revisions"]
        assert isinstance(revs, list) and revs, f"every payment has revision 1: {body!r}"
        for i, r in enumerate(revs, start=1):
            check_revision(r, payment_id=payment_id, revision=i)
        assert revs[0]["reason"] == "" and revs[0]["effective_at"] == revs[0]["recorded_at"], \
            f"I56: revision 1 has reason \"\" and effective_at == recorded_at: {revs[0]}"
        for a, b in zip(revs, revs[1:]):
            assert instant(a["recorded_at"]) < instant(b["recorded_at"]), \
                f"I56: a payment's recorded_at values strictly increase: {a} then {b}"
        return revs

    def service_now(self, payer_handle: str) -> str:
        """A time mark issued by the service (W18.5): the created_at of a new request to payer_handle.

        It creates a pending request and moves no money.
        """
        return expect(self.ask(payer_handle, 1, note="time mark"), 201)["created_at"]


def _all_pages(client: Api, path: str, field: str, params: dict) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        page = expect(client.get(path, params={**params, "limit": 200, "offset": offset}), 200)
        assert set(page) == {field, "has_more"}, f"{path} keys: {sorted(page)}"
        out.extend(page[field])
        if not page["has_more"]:
            return out
        assert page[field], f"{path}: has_more is true on an empty page"
        offset += len(page[field])


# ---------------------------------------------------------------- assertions

def describe(resp: httpx.Response) -> str:
    body = resp.text
    if len(body) > 500:
        body = body[:500] + "..."
    return f"{resp.request.method} {resp.request.url} -> {resp.status_code} {body!r}"


def _assert_json_content_type(resp: httpx.Response) -> None:
    ctype = resp.headers.get("content-type", "").replace(" ", "").lower()
    assert ctype == "application/json;charset=utf-8", \
        f"Content-Type must be application/json; charset=utf-8, got {ctype!r}. {describe(resp)}"


def expect(resp: httpx.Response, status: int) -> Any:
    """Assert the status, the JSON content type and return the parsed body (None on 204)."""
    assert resp.status_code == status, f"expected {status}. {describe(resp)}"
    if status == 204:
        assert resp.content == b"", f"204 must have no body. {describe(resp)}"
        return None
    _assert_json_content_type(resp)
    try:
        return resp.json()
    except ValueError:
        raise AssertionError(f"body is not JSON. {describe(resp)}") from None


def error_code(resp: httpx.Response) -> str | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return body["error"].get("code")
    return None


def expect_error(resp: httpx.Response, status: int, code: str) -> dict:
    """Assert status, code and the exact §5 envelope (I10)."""
    actual = error_code(resp)
    assert resp.status_code == status and actual == code, \
        f"expected {status} {code}, got {resp.status_code} {actual}. {describe(resp)}"
    _assert_json_content_type(resp)
    body = resp.json()
    assert set(body) == {"error"}, f"envelope has extra top-level keys. {describe(resp)}"
    assert set(body["error"]) == {"code", "message"}, \
        f"error object must hold exactly code and message. {describe(resp)}"
    assert isinstance(body["error"]["message"], str), f"message must be a string. {describe(resp)}"
    return body


def no_5xx(resp: Any) -> None:
    assert not isinstance(resp, Exception), f"transport error: {resp!r}"
    assert resp.status_code < 500, f"5xx is never allowed. {describe(resp)}"
    if resp.status_code >= 400:
        assert error_code(resp), f"every 4xx carries the envelope. {describe(resp)}"


def tally(results: list) -> dict:
    out: dict = {}
    for r in results:
        k = getattr(r, "status_code", repr(r)[:80])
        out[k] = out.get(k, 0) + 1
    return out


def no_failures(results: list) -> None:
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, f"transport errors or timeouts (> {REQUEST_TIMEOUT}s): {tally(results)}; first: {errors[0]!r}"
    bad = [r for r in results if r.status_code >= 500]
    assert not bad, f"5xx under load: {tally(results)}; first: {describe(bad[0])}"


# ---------------------------------------------------------------- representations

ME_KEYS = {"user_id", "display_name", "handle", "balance", "total", "available", "held",
           "currency", "minor_units"}
AUTH_KEYS = {"user_id", "display_name", "token"}
PAYMENT_KEYS = {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                "amount", "currency", "note", "visibility", "request_id",
                "settlement_id", "authorization_id", "created_at"}
# D54: a replayed stage-1 body is returned verbatim, so it has no authorization_id.
STAGE1_PAYMENT_KEYS = PAYMENT_KEYS - {"authorization_id"}
REQUEST_KEYS = {"request_id", "requester_id", "requester_handle", "payer_id",
                "payer_handle", "amount", "currency", "note", "status", "payment_id",
                "created_at"}
SPLIT_KEYS = {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"}
SETTLEMENT_KEYS = {"settlement_id", "committed_at", "payments"}
STATUSES = {"pending", "paid", "declined", "cancelled"}
# PLAN 3.6 (S3): stage 2's authorization fields plus closed_at (I61).
STAGE2_AUTHZ_KEYS = {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                     "amount", "captured_amount", "remaining_amount", "currency", "note", "visibility",
                     "status", "expires_at", "payment_id", "payment_ids", "created_at"}
AUTHZ_KEYS = STAGE2_AUTHZ_KEYS | {"closed_at"}
AUTHZ_STATUSES = {"open", "captured", "voided", "expired"}
# PLAN 3.6 (S3): revisions, statements and their entries.
REVISION_KEYS = {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"}
STATEMENT_KEYS = {"opening_balance", "entries", "closing_balance", "has_more", "snapshot"}
ENTRY_KEYS = {"payment", "delta", "balance_after", "revision", "effective_at", "recorded_at"}

# PLAN 3.4 (S3, D66): the instant grammar. Every timestamp the service shows is one of these
# (a seeded or client-supplied one exactly as written; an issued one in PLAN_TS form).
RFC3339 = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?([Zz]|[+-][0-9]{2}:[0-9]{2})$")
_INSTANT = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?"
                      r"(?:([Zz])|([+-])([0-9]{2}):([0-9]{2}))$")
# PLAN 3.7 (D14): exactly YYYY-MM-DDTHH:MM:SS.sss+00:00.
PLAN_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$")
HANDLE = re.compile(r"^[a-z0-9_]{1,20}$")


def is_int(v: Any) -> bool:
    return type(v) is int


def check_id(v: Any, what: str = "id") -> None:
    assert isinstance(v, str) and 1 <= len(v) <= 64, f"{what} must be a string of 1..64 characters: {v!r}"


def ts(v: Any) -> datetime:
    """A timestamp as a datetime (fractions beyond microseconds dropped; use `instant` to compare)."""
    exact = instant(v)
    whole = exact.numerator // exact.denominator
    micro = (exact - whole) * 1_000_000
    return datetime.fromtimestamp(whole, timezone.utc) + timedelta(microseconds=int(micro))


def instant(v: Any) -> Fraction:
    """PLAN 3.4: the exact instant of a valid string, as seconds since the epoch (never rounded)."""
    assert isinstance(v, str) and len(v) <= 64, f"an instant is a string of at most 64 characters: {v!r}"
    m = _INSTANT.match(v)
    assert m, f"timestamp is not an RFC 3339 instant with an offset (PLAN 3.4): {v!r}"
    y, mo, d, h, mi, s = (int(g) for g in m.groups()[:6])
    frac, z, sign, oh, om = m.groups()[6:]
    datetime(y, mo, d, h, mi, s)   # raises for an impossible date or time
    secs = calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0))
    if not z:
        assert int(oh) <= 23 and int(om) <= 59, f"offset out of range: {v!r}"
        off = int(oh) * 3600 + int(om) * 60
        secs -= off if sign == "+" else -off
    return Fraction(secs) + (Fraction(int(frac), 10 ** len(frac)) if frac else 0)


def fmt_instant(value: Fraction | str, *, digits: int = 6, offset: str = "+00:00", t: str = "T") -> str:
    """The exact instant `value` written with `digits` fraction digits (0: none) at `offset`.

    `offset` is "Z", "z" or "+hh:mm"/"-hh:mm"; `t` the date-time separator. The value must be
    representable exactly with `digits` digits: nothing is rounded.
    """
    if isinstance(value, str):
        value = instant(value)
    if offset in ("Z", "z"):
        off = 0
    else:
        sign = 1 if offset[0] == "+" else -1
        off = sign * (int(offset[1:3]) * 3600 + int(offset[4:6]) * 60)
    local = value + off
    whole = local.numerator // local.denominator
    frac = (local - whole) * 10 ** digits
    assert frac.denominator == 1, f"{value} is not exact at {digits} fraction digits"
    base = datetime.fromtimestamp(whole, timezone.utc).strftime(f"%Y-%m-%d{t}%H:%M:%S")
    return base + (f".{int(frac):0{digits}d}" if digits else "") + offset


def shifted(v: str, micros: int = 0, *, seconds: float = 0, **fmt) -> str:
    """The instant v moved by `micros` microseconds (and `seconds`), in fmt_instant form."""
    return fmt_instant(instant(v) + Fraction(micros, 1_000_000) + Fraction(seconds), **fmt)


EPOCH = "1970-01-01T00:00:00Z"
FAR_FUTURE = "9999-12-31T23:59:59.999999999Z"


def check_revision(r: dict, **want) -> dict:
    """PLAN 3.6: exactly the revision fields."""
    assert isinstance(r, dict) and set(r) == REVISION_KEYS, \
        f"revision keys: {sorted(r) if isinstance(r, dict) else r!r}"
    check_id(r["payment_id"], "payment_id")
    assert is_int(r["revision"]) and r["revision"] >= 1, r
    assert is_int(r["amount"]) and 0 <= r["amount"] <= MAX_AMOUNT, r
    instant(r["effective_at"])
    assert PLAN_TS.match(r["recorded_at"]) or r["revision"] == 1, \
        f"a correction's recorded_at is issued by the service (PLAN 3.4 form): {r}"
    instant(r["recorded_at"])
    assert isinstance(r["reason"], str), r
    if r["revision"] > 1:
        assert 1 <= len(r["reason"]) <= 200, f"a correction's reason has 1..200 code points: {r}"
        assert instant(r["effective_at"]) <= instant(r["recorded_at"]), \
            f"D81: a correction takes effect no later than now, and now is no later than its recorded_at: {r}"
    for k, v in want.items():
        assert r[k] == v, f"revision {k}: expected {v!r}, got {r[k]!r} in {r}"
    return r


def check_me_view(m: dict, *, as_of: str | None = None, known_at: str | None = None) -> dict:
    """PLAN 3.6: Me plus `as_of`/`known_at` exactly as sent, only when sent; I60's identities."""
    want = set(ME_KEYS) | ({"as_of"} if as_of is not None else set()) | \
        ({"known_at"} if known_at is not None else set())
    assert set(m) == want, f"GET /me keys with as_of={as_of!r} known_at={known_at!r}: {sorted(m)}"
    if as_of is not None:
        assert m["as_of"] == as_of, f"I52: as_of must be echoed exactly: sent {as_of!r}, got {m['as_of']!r}"
    if known_at is not None:
        assert m["known_at"] == known_at, \
            f"I59: known_at must be echoed exactly: sent {known_at!r}, got {m['known_at']!r}"
    for k in ("balance", "total", "available", "held"):
        assert is_int(m[k]), f"{k} must be an integer: {m}"
    assert m["balance"] == m["total"], f"I60: balance must equal total in every view: {m}"
    assert m["available"] == m["total"] - m["held"], f"I60: available must be total - held in every view: {m}"
    assert m["held"] >= 0, f"I60: held is never negative: {m}"
    return m


def check_me(m: dict) -> dict:
    assert set(m) == ME_KEYS, f"GET /me keys: {sorted(m)}"
    check_id(m["user_id"], "user_id")
    assert isinstance(m["display_name"], str)
    assert isinstance(m["handle"], str) and HANDLE.match(m["handle"]), m
    check_money(m)
    assert isinstance(m["currency"], str)
    assert m["minor_units"] in (0, 2, 3) and is_int(m["minor_units"]), m
    return m


def check_money(m: dict) -> dict:
    """I2 and I30 on one GET /me body."""
    for k in ("balance", "total", "available", "held"):
        assert is_int(m[k]) and m[k] >= 0, f"I2: {k} must be a non-negative integer: {m}"
    assert m["balance"] == m["total"], f"I30: balance must equal total: {m}"
    assert m["available"] == m["total"] - m["held"], f"I30: available must be total - held: {m}"
    assert m["held"] <= m["total"], f"I2: held must not exceed total: {m}"
    return m


def check_payment(p: dict, **want) -> dict:
    assert isinstance(p, dict) and set(p) == PAYMENT_KEYS, f"payment keys: {sorted(p) if isinstance(p, dict) else p!r}"
    check_id(p["payment_id"], "payment_id")
    check_id(p["from_user_id"], "from_user_id")
    check_id(p["to_user_id"], "to_user_id")
    assert p["from_user_id"] != p["to_user_id"], p
    assert isinstance(p["from_handle"], str) and isinstance(p["to_handle"], str)
    assert is_int(p["amount"]) and 0 <= p["amount"] <= MAX_AMOUNT, p
    assert isinstance(p["currency"], str)
    assert isinstance(p["note"], str)
    assert p["visibility"] in ("public", "private"), p
    if p["request_id"] is not None:
        check_id(p["request_id"], "request_id")
    if p["settlement_id"] is not None:
        check_id(p["settlement_id"], "settlement_id")
    if p["authorization_id"] is not None:
        check_id(p["authorization_id"], "authorization_id")
    ts(p["created_at"])
    for k, v in want.items():
        assert p[k] == v, f"payment {k}: expected {v!r}, got {p[k]!r} in {p}"
    return p


def check_authorization(a: dict, *, keys: set = AUTHZ_KEYS, **want) -> dict:
    """PLAN 3.6: exactly the authorization fields, with the remainder rules of I33 and I61's closed_at.

    `keys=STAGE2_AUTHZ_KEYS` checks a stored stage-2 replay body, which has no closed_at (D54).
    """
    assert isinstance(a, dict) and set(a) == keys, \
        f"authorization keys: {sorted(a) if isinstance(a, dict) else a!r}"
    if "closed_at" in keys:
        if a["status"] == "open":
            assert a["closed_at"] is None, f"I61: closed_at is null while open: {a}"
        else:
            instant(a["closed_at"])
    check_id(a["authorization_id"], "authorization_id")
    check_id(a["from_user_id"], "from_user_id")
    check_id(a["to_user_id"], "to_user_id")
    assert a["from_user_id"] != a["to_user_id"], a
    assert isinstance(a["from_handle"], str) and isinstance(a["to_handle"], str)
    for k in ("amount", "captured_amount", "remaining_amount"):
        assert is_int(a[k]) and 0 <= a[k] <= MAX_AMOUNT, f"{k}: {a}"
    assert a["captured_amount"] <= a["amount"], f"I32: captured above amount: {a}"
    assert a["status"] in AUTHZ_STATUSES, a
    if a["status"] == "open":
        assert a["remaining_amount"] == a["amount"] - a["captured_amount"], f"I33 while open: {a}"
    else:
        assert a["remaining_amount"] == 0, f"I33: a closed authorization holds nothing: {a}"
    assert isinstance(a["currency"], str) and isinstance(a["note"], str)
    assert a["visibility"] in ("public", "private"), a
    assert isinstance(a["expires_at"], str), a
    assert isinstance(a["payment_ids"], list), a
    for pid in a["payment_ids"]:
        check_id(pid, "payment_ids entry")
    assert a["payment_id"] == (a["payment_ids"][-1] if a["payment_ids"] else None), \
        f"payment_id must be the last of payment_ids: {a}"
    ts(a["created_at"])
    instant(a["expires_at"])
    for k, v in want.items():
        assert a[k] == v, f"authorization {k}: expected {v!r}, got {a[k]!r} in {a}"
    return a


def check_request(r: dict, **want) -> dict:
    assert isinstance(r, dict) and set(r) == REQUEST_KEYS, f"request keys: {sorted(r) if isinstance(r, dict) else r!r}"
    check_id(r["request_id"], "request_id")
    check_id(r["requester_id"], "requester_id")
    check_id(r["payer_id"], "payer_id")
    assert r["requester_id"] != r["payer_id"], r
    assert is_int(r["amount"]) and 0 <= r["amount"] <= MAX_AMOUNT, r
    assert isinstance(r["note"], str)
    assert r["status"] in STATUSES, r
    if r["payment_id"] is not None:
        check_id(r["payment_id"], "payment_id")
    ts(r["created_at"])
    for k, v in want.items():
        assert r[k] == v, f"request {k}: expected {v!r}, got {r[k]!r} in {r}"
    return r


def by_id(items: list[dict], field: str) -> dict[str, dict]:
    out = {}
    for it in items:
        assert it[field] not in out, f"duplicate {field} {it[field]} in a list"
        out[it[field]] = it
    return out


def assert_newest_first(items: list[dict], field: str = "created_at") -> None:
    """I29 (amended): newest first, compared as exact instants."""
    times = [instant(i[field]) for i in items]
    assert times == sorted(times, reverse=True), \
        f"list is not newest first by {field}: {[i[field] for i in items]}"


# ---------------------------------------------------------------- statements (stage 3)

def check_entry(e: dict, user_id: str) -> dict:
    """PLAN 3.6 and I54 on one statement entry of `user_id`'s statement."""
    assert isinstance(e, dict) and set(e) == ENTRY_KEYS, \
        f"entry keys: {sorted(e) if isinstance(e, dict) else e!r}"
    p = check_payment(e["payment"])
    for k in ("delta", "balance_after", "revision"):
        assert is_int(e[k]), f"entry {k} must be an integer: {e}"
    assert e["revision"] >= 1, e
    instant(e["effective_at"])
    instant(e["recorded_at"])
    if p["from_user_id"] == user_id:
        assert e["delta"] == -p["amount"], f"I54: a sent payment's delta is minus its selected amount: {e}"
    elif p["to_user_id"] == user_id:
        assert e["delta"] == p["amount"], f"I54: a received payment's delta is its selected amount: {e}"
    else:
        raise AssertionError(f"I54: a statement holds only the caller's payments: {e}")
    if e["revision"] == 1:
        assert e["effective_at"] == e["recorded_at"] == p["created_at"], \
            f"I56: revision 1 takes effect and is recorded at the payment's created_at: {e}"
    return e


def check_statement_page(body: Any, user_id: str, *, known_at: str | None = None,
                         snapshot: str | None = None) -> dict:
    """PLAN 3.6: the statement fields (`known_at` only when the first read sent it)."""
    want = STATEMENT_KEYS | ({"known_at"} if known_at is not None else set())
    assert isinstance(body, dict) and set(body) == want, \
        f"statement keys (known_at={known_at!r}): {sorted(body) if isinstance(body, dict) else body!r}"
    if known_at is not None:
        assert body["known_at"] == known_at, f"I59: known_at echoed exactly: sent {known_at!r}, got {body['known_at']!r}"
    assert is_int(body["opening_balance"]) and is_int(body["closing_balance"]), body
    assert type(body["has_more"]) is bool, body
    assert isinstance(body["snapshot"], str) and body["snapshot"], f"a statement carries a snapshot token: {body}"
    if snapshot is not None:
        assert body["snapshot"] == snapshot, \
            f"D72: a snapshot page carries the first page's fields, its token included: {body['snapshot']!r}"
    assert isinstance(body["entries"], list), body
    for e in body["entries"]:
        check_entry(e, user_id)
    return body


def check_window(entries: list[dict], opening: int, closing: int, *, frm: str | None = None,
                 to: str | None = None) -> None:
    """I54 over a full window: running balances, the identity, order and the half-open bounds."""
    running = opening
    for i, e in enumerate(entries):
        running += e["delta"]
        assert e["balance_after"] == running, \
            f"I54: entry {i} balance_after {e['balance_after']} != running {running}: {e}"
    assert closing == running, f"I54: opening {opening} + deltas {running - opening} != closing {closing}"
    keys = [(instant(e["effective_at"]), e["payment"]["payment_id"]) for e in entries]
    assert keys == sorted(keys) and len(set(keys)) == len(keys), \
        f"I54: entries are ordered by effective_at, then payment_id: {[(e['effective_at'], e['payment']['payment_id']) for e in entries]}"
    assert len({e["payment"]["payment_id"] for e in entries}) == len(entries), "a payment appears at most once"
    for e in entries:
        if frm is not None:
            assert instant(e["effective_at"]) >= instant(frm), f"I54: an entry before from={frm}: {e}"
        if to is not None:
            assert instant(e["effective_at"]) < instant(to), f"I54: an entry at or after to={to}: {e}"


@dataclass
class Statement:
    first: dict             # the first page, as returned
    entries: list[dict]     # the full window, read through the snapshot
    opening: int
    closing: int
    snapshot: str

    def deltas(self) -> list[int]:
        return [e["delta"] for e in self.entries]

    def ids(self) -> list[str]:
        return [e["payment"]["payment_id"] for e in self.entries]


def page_snapshot(c: "Api", user_id: str, token: str, *, known_at: str | None = None,
                  page_limit: int = 200) -> tuple[list[dict], int, int]:
    """Every entry of a snapshot, page by page; every page shows the same window balances (I54)."""
    entries: list[dict] = []
    balances = None
    offset = 0
    while True:
        page = expect(c.statement_page(token, limit=page_limit, offset=offset), 200)
        check_statement_page(page, user_id, known_at=known_at, snapshot=token)
        pair = (page["opening_balance"], page["closing_balance"])
        assert balances in (None, pair), f"I54: paging changed the window balances: {balances} then {pair}"
        balances = pair
        entries.extend(page["entries"])
        if not page["has_more"]:
            return entries, pair[0], pair[1]
        assert len(page["entries"]) == page_limit, f"has_more with a short page: {page}"
        offset += page_limit


def read_statement(c: "Api", user_id: str, **params) -> Statement:
    """A first GET /statement plus every page of its snapshot, checked against I54 and I55."""
    first = expect(c.statement(**params), 200)
    known_at = params.get("known_at")
    check_statement_page(first, user_id, known_at=known_at)
    entries, opening, closing = page_snapshot(c, user_id, first["snapshot"], known_at=known_at)
    assert (first["opening_balance"], first["closing_balance"]) == (opening, closing), \
        "I55: the snapshot pages the first result's balances"
    lim = int(params.get("limit", 50))
    off = int(params.get("offset", 0))
    assert first["entries"] == entries[off:off + lim], "I55: the first page is a slice of its snapshot"
    assert first["has_more"] == (len(entries) > off + lim), \
        f"I54: has_more is exact: {first['has_more']} with {len(entries)} entries, offset {off}, limit {lim}"
    check_window(entries, opening, closing, frm=params.get("from"), to=params.get("to"))
    return Statement(first, entries, opening, closing, first["snapshot"])


def history_is_consistent(fx: dict) -> bool:
    """Whether a fixture's seeded history keeps every wallet at or above 0 at every instant (I2, D69).

    The seeded payments are replayed from the opening balances in time order, the ones without
    `created_at` (the reset's time) last; seeded open holds with their own `created_at` are not
    modelled, so such a fixture counts as unknown (False).
    """
    if any(a.get("created_at") is not None and a.get("status", "open") == "open"
           for a in fx.get("authorizations") or []):
        return False
    bal = {u["id"]: u["balance"] for u in fx["users"]}
    pays = fx.get("payments") or []
    for p in pays:
        bal[p["from_user_id"]] += p["amount"]
        bal[p["to_user_id"]] -= p["amount"]
    if min(bal.values(), default=0) < 0:
        return False
    timed = sorted({instant(p["created_at"]) for p in pays if p.get("created_at") is not None})
    for t in timed + [None]:
        for p in pays:
            at = instant(p["created_at"]) if p.get("created_at") is not None else None
            if at == t:
                bal[p["from_user_id"]] -= p["amount"]
                bal[p["to_user_id"]] += p["amount"]
        if min(bal.values(), default=0) < 0:
            return False
    return True


# ---------------------------------------------------------------- fixtures

CURRENCIES = {"EUR": 2, "JPY": 0, "BHD": 3}


def user(handle: str, balance: int, *, uid: str | None = None, email: str | None = None,
         password: str | None = None, display_name: str | None = None) -> dict:
    return {
        "id": uid or f"u_{handle}",
        "email": email or f"{handle}@example.com",
        # A distinct password per user, so a plaintext search of an export is meaningful.
        "password": password or f"pw-{handle}-Correct-Horse-9",
        "display_name": display_name if display_name is not None else handle.title(),
        "handle": handle,
        "balance": balance,
    }


def standard_users() -> list[dict]:
    return [user("ada", 10_000), user("bob", 2_500), user("cy", 500), user("dee", 0)]


def fixture(users: list[dict] | None = None, *, currency: str = "EUR",
            minor_units: int | None = None, payments: list[dict] | None = None,
            requests: list[dict] | None = None, operators: list[str] | None = None,
            authorizations: list[dict] | None = None, ttl: Any = _UNSET) -> dict:
    fx: dict[str, Any] = {
        "currency": currency,
        "minor_units": CURRENCIES.get(currency, 2) if minor_units is None else minor_units,
        "users": standard_users() if users is None else users,
        "payments": payments or [],
        "requests": requests or [],
    }
    if operators is not None:
        fx["settlement_operator_ids"] = operators
    if authorizations is not None:
        fx["authorizations"] = authorizations
    if ttl is not _UNSET:
        fx["authorization_ttl_seconds"] = ttl
    return fx


def iso(dt: datetime) -> str:
    """A UTC instant in the plan's timestamp form."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}+00:00"


def hours_from_now(h: float) -> str:
    """An RFC 3339 instant h hours from the wall clock (negative: in the past)."""
    return iso(datetime.now(timezone.utc) + timedelta(hours=h))


def seeded_auth(aid: str, frm: str, to: str, amount: int, *, hours: float = 2.0, **extra) -> dict:
    """A fixture authorization; `hours` from now to expires_at (seeds are at least an hour away)."""
    return {"id": aid, "from_user_id": f"u_{frm}", "to_user_id": f"u_{to}", "amount": amount,
            "expires_at": hours_from_now(hours), **extra}


def equal_split(amount: int, n: int) -> list[int]:
    base, r = divmod(amount, n)
    return [base + (1 if i < r else 0) for i in range(n)]


# ---------------------------------------------------------------- service model

@dataclass
class Account:
    handle: str
    email: str
    password: str
    user_id: str | None = None
    token: str | None = None


@dataclass
class Snapshot:
    body: Any
    text: str
    total: int | None
    accounts: dict[str, Account]
    consistent: bool = False   # the source's seeded history was consistent (history_is_consistent)


class Service:
    """One running service, plus what the suite expects its state to be."""

    history_checks = False   # set by conftest: --upto 14 or later
    statement_checks = False # set by conftest: --upto 15 or later (GET /statement exists)

    def __init__(self, base_url: str, name: str = "A"):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.total: int | None = None
        self.consistent = False
        self.accounts: dict[str, Account] = {}
        self._clients: list[Api] = []
        self._by_handle: dict[str, Api] = {}

    # -- clients
    def api(self, token: str | None = None, timeout: float = REQUEST_TIMEOUT) -> Api:
        c = Api(self.base_url, token=token, timeout=timeout)
        self._clients.append(c)
        return c

    def close(self) -> None:
        for c in self._clients:
            c.close()
        self._clients.clear()
        self._by_handle.clear()

    def login(self, email: str, password: str) -> httpx.Response:
        return self.api().post("/auth/login", json={"email": email, "password": password})

    def client(self, handle: str) -> Api:
        """A client for a tracked account, logging in if it has no token yet."""
        acct = self.accounts[handle]
        if acct.token is None:
            body = expect(self.login(acct.email, acct.password), 200)
            acct.token = body["token"]
            acct.user_id = body["user_id"]
        c = self._by_handle.get(handle)
        if c is None or c.token != acct.token:
            c = self.api(acct.token)
            self._by_handle[handle] = c
        return c

    def fresh_client(self, handle: str) -> Api:
        """Another client for the same account and token (its own connection)."""
        self.client(handle)
        return self.api(self.accounts[handle].token)

    # -- state control
    def reset(self, fx: dict, *, track: bool = True) -> httpx.Response:
        resp = httpx.post(f"{self.base_url}/_test/reset", json=fx, timeout=RESET_TIMEOUT)
        if resp.status_code == 204:
            self._by_handle.clear()
            self.accounts = {u["handle"]: Account(u["handle"], u["email"], u["password"], u["id"])
                             for u in fx["users"]}
            self.total = sum(u["balance"] for u in fx["users"]) if track else None
            self.consistent = history_is_consistent(fx)
        return resp

    def must_reset(self, fx: dict, **kw) -> None:
        expect(self.reset(fx, **kw), 204)

    def signup(self, email: str, password: str, display_name: str = "New User") -> httpx.Response:
        resp = self.api().post("/auth/signup", json={"email": email, "password": password,
                                                      "display_name": display_name})
        if resp.status_code == 201:
            body = resp.json()
            me = expect(self.api(body["token"]).get("/me"), 200)
            self.accounts[me["handle"]] = Account(me["handle"], email, password,
                                                  body["user_id"], body["token"])
        return resp

    def export(self) -> Snapshot:
        resp = httpx.get(f"{self.base_url}/_test/export", timeout=RESET_TIMEOUT)
        body = expect(resp, 200)
        return Snapshot(body, resp.text, self.total, copy.deepcopy(self.accounts), self.consistent)

    def import_raw(self, body: Any = _UNSET, *, content: bytes | None = None) -> httpx.Response:
        if content is None:
            content = _json.dumps(body, ensure_ascii=False).encode("utf-8")
        resp = httpx.post(f"{self.base_url}/_test/import", content=content,
                          headers={"Content-Type": "application/json"}, timeout=RESET_TIMEOUT)
        if resp.status_code == 204:
            self.consistent = False   # unknown until import_ says otherwise
        return resp

    def import_(self, snap: Snapshot) -> httpx.Response:
        resp = self.import_raw(snap.body)
        if resp.status_code == 204:
            self._by_handle.clear()
            self.accounts = copy.deepcopy(snap.accounts)
            self.total = snap.total
            self.consistent = snap.consistent
        return resp

    # -- invariants
    def balances(self) -> dict[str, int]:
        return {h: self.client(h).balance() for h in self.accounts}

    def held_matches_open_holds(self, handle: str, where: str = "") -> None:
        """I30: held = the remainders of the caller's open outgoing authorizations.

        An authorization can expire between the reads, so the list is read before and
        after GET /me and compared only when both lists agree.
        """
        c = self.client(handle)
        for _ in range(4):
            first = c.auths(direction="outgoing", status="open")
            me = c.me()
            second = c.auths(direction="outgoing", status="open")
            if first == second:
                held = sum(a["remaining_amount"] for a in first)
                assert me["held"] == held, \
                    f"I30 violated{where} on {self.name}: {handle} held {me['held']} != open remainders {held}"
                return
        raise AssertionError(f"open outgoing authorizations of {handle} kept changing{where}")

    def assert_invariants(self, where: str = "", *, holds: bool = True) -> None:
        """I1, I2 and I30 over every tracked account."""
        if self.total is None or len(self.accounts) > MAX_TRACKED_FOR_CHECK:
            return
        mes = {h: self.client(h).me() for h in self.accounts}
        for h, m in mes.items():
            try:
                check_money(m)
            except AssertionError as exc:
                raise AssertionError(f"{exc}{where} on {self.name} for {h}") from None
        totals = {h: m["total"] for h, m in mes.items()}
        assert sum(totals.values()) == self.total, \
            f"I1 violated{where} on {self.name}: sum {sum(totals.values())} != seeded {self.total}; {totals}"
        if holds:
            for h in self.accounts:
                self.held_matches_open_holds(h, where)

    def history_instants(self) -> list[str]:
        """Every instant at which a tracked account's payments take effect or its holds change."""
        seen: dict[Fraction, str] = {}
        for h in self.accounts:
            c = self.client(h)
            acct = self.accounts[h]
            if self.statement_checks:      # effective times under the latest revisions
                first = expect(c.statement(limit=200), 200)
                entries, _, _ = page_snapshot(c, acct.user_id, first["snapshot"])
                for e in entries:
                    seen.setdefault(instant(e["effective_at"]), e["effective_at"])
            else:                          # before W15 (and W16) every payment takes effect at created_at
                for p in c.feed():
                    if h in (p["from_handle"], p["to_handle"]):
                        seen.setdefault(instant(p["created_at"]), p["created_at"])
            for a in c.auths(direction="outgoing"):
                for k in ("created_at", "closed_at", "expires_at"):
                    if a.get(k):
                        seen.setdefault(instant(a[k]), a[k])
        return [seen[k] for k in sorted(seen)]

    def assert_history_invariants(self, where: str = "") -> None:
        """Stage 3: I67 (the present view equals GET /me); I1 in historical views; I2 and I60 at every
        history instant (sampled) when the seeded history is consistent (I2 amended, I58)."""
        if not self.history_checks or self.total is None or len(self.accounts) > MAX_TRACKED_FOR_HISTORY:
            return
        for h in self.accounts:            # I67: the present view agrees with GET /me (W18.7 c)
            c = self.client(h)
            for _ in range(4):
                first, view, second = c.me(), c.me_at(None, FAR_FUTURE), c.me()
                money = [(m["balance"], m["total"], m["available"], m["held"]) for m in (first, view, second)]
                if money[0] == money[2]:   # a hold expiring between the reads is not compared
                    assert money[1] == money[0], \
                        f"I67 violated{where} on {self.name}: {h} GET /me {money[0]} != known_at far future {money[1]}"
                    break
        views = [(EPOCH, None), (None, EPOCH), (FAR_FUTURE, None), (FAR_FUTURE, EPOCH)]
        points = self.history_instants()
        if len(points) > HISTORY_SAMPLE:
            step = (len(points) - 1) / (HISTORY_SAMPLE - 1)
            points = [points[round(i * step)] for i in range(HISTORY_SAMPLE)]
        views += [(t, None) for t in points]
        views += [(None, t) for t in points[:: max(1, len(points) // 3)]]
        for as_of, known_at in views:
            mes = {h: self.client(h).me_at(as_of, known_at) for h in self.accounts}
            totals = {h: m["total"] for h, m in mes.items()}
            assert sum(totals.values()) == self.total, \
                f"I1 violated{where} on {self.name} at as_of={as_of} known_at={known_at}: " \
                f"sum {sum(totals.values())} != {self.total}; {totals}"
            if self.consistent and known_at is None:
                for h, m in mes.items():
                    assert m["total"] >= 0 and m["available"] >= 0, \
                        f"I2/I58 violated{where} on {self.name}: {h} at as_of={as_of}: {m}"

    def burst(self, fn: Callable[[int], Any], n: int, *, watch: bool = True,
              timeout: float = 60.0) -> list:
        """Run fn(0..n-1) released together by a barrier (batches of at most 50).

        While the burst runs, a watcher reads every tracked balance in a loop and
        records any negative read (I2 during the burst). After it, conservation is
        asserted (I1). Exceptions are returned in place, not raised.
        """
        if n > 50:
            out: list = []
            for start in range(0, n, 50):
                out.extend(self.burst(lambda i, s=start: fn(s + i), min(50, n - start),
                                      watch=watch, timeout=timeout))
            return out
        watched = []
        if watch and self.total is not None and len(self.accounts) <= MAX_TRACKED_FOR_CHECK:
            watched = [(h, self.client(h).token) for h in self.accounts]
        seen_negative: list = []
        watch_errors: list = []
        stop = threading.Event()

        def watcher():
            clients = [(h, Api(self.base_url, t)) for h, t in watched]
            try:
                while not stop.is_set():
                    for h, c in clients:
                        try:
                            r = c.get("/me")
                            if r.status_code == 200:
                                m = r.json()
                                bad = [k for k in ("balance", "total", "available", "held")
                                       if not isinstance(m.get(k), int) or m[k] < 0]
                                if bad or m["held"] > m["total"] or m["balance"] != m["total"] \
                                        or m["available"] != m["total"] - m["held"]:
                                    seen_negative.append((h, {k: m.get(k) for k in
                                                              ("total", "available", "held", "balance")}))
                            else:
                                watch_errors.append(describe(r))
                        except Exception as exc:  # recorded, then asserted
                            watch_errors.append(repr(exc))
            finally:
                for _, c in clients:
                    c.close()

        barrier = threading.Barrier(n)

        def worker(i: int):
            try:
                barrier.wait(timeout=timeout)
            except threading.BrokenBarrierError:
                pass
            try:
                return fn(i)
            except Exception as exc:
                return exc

        th = threading.Thread(target=watcher, daemon=True) if watched else None
        if th:
            th.start()
        with ThreadPoolExecutor(max_workers=n) as pool:
            results = list(pool.map(worker, range(n)))
        stop.set()
        if th:
            th.join(timeout=30)
        assert not seen_negative, f"I2/I30 violated during a burst: {seen_negative[:5]}"
        assert not watch_errors, f"balance reads failed during a burst: {watch_errors[:3]}"
        if watched:
            self.assert_invariants(" after a burst")
        return results


def wait_healthy(base_url: str, deadline_s: float = 60.0) -> float:
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        try:
            r = httpx.get(f"{base_url}/health", timeout=2.0)
            if r.status_code == 200:
                return time.monotonic() - start
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise AssertionError(f"{base_url}/health not 200 within {deadline_s}s")


# ---------------------------------------------------------------- raw HTTP

def raw_exchange(sock, request: bytes, timeout: float = REQUEST_TIMEOUT) -> tuple[int, dict, bytes]:
    """Send one HTTP/1.1 request on an open socket and read one complete response."""
    sock.settimeout(timeout)
    sock.sendall(request)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(65536)
        if not chunk:
            raise AssertionError(f"connection closed before a response: {data[:200]!r}")
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers = {}
    for line in lines[1:]:
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", "0"))
    while len(rest) < length:
        chunk = sock.recv(65536)
        if not chunk:
            break
        rest += chunk
    return status, headers, rest[:length]


def raw_request(base_url: str, method: str, path: str, *, token: str | None = None,
                body: bytes = b"", extra: str = "") -> tuple[int, dict, bytes]:
    """One request with the path sent exactly as given (no client-side re-encoding)."""
    import socket
    from urllib.parse import urlsplit
    u = urlsplit(base_url)
    auth = f"Authorization: Bearer {token}\r\n" if token else ""
    req = (f"{method} {path} HTTP/1.1\r\nHost: {u.hostname}\r\n{auth}{extra}"
           f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode("latin-1") + body
    with socket.create_connection((u.hostname, u.port or 80), timeout=REQUEST_TIMEOUT) as s:
        return raw_exchange(s, req)
