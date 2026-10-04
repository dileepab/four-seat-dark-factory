"""Shared helpers for the stage-2 acceptance suite.

Owned by the verifier. Written from the specifications
(`/Users/Dileepa/df-spec/pocketful/spec/stage-1.md` and `stage-2.md`) and
`stage-2/PLAN.md` only, never from the implementation. Everything here talks to the
service over HTTP.

Invariant tracking: a `Service` remembers the total seeded by the last accepted
reset (or carried by the last accepted import) and every account it knows. After
each test the `svc` fixture asserts, over those accounts, I1 (the `total`s sum to the
seeded total), I2 (no negative `total`, `available` or `held`; `held <= total`) and I30
(`balance == total`, `available == total - held`, `held` = the open outgoing
remainders). `Service.burst` asserts I2 on reads taken *during* a burst and I1 right
after it.
"""
from __future__ import annotations

import copy
import json as _json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

REQUEST_TIMEOUT = 5.0     # §2: per-request timeout
RESET_TIMEOUT = 10.0      # §2 and §10: reset, export and import
MAX_AMOUNT = 1_000_000_000
TWO_53 = 2 ** 53
MAX_TRACKED_FOR_CHECK = 80   # accounts summed after each test; larger worlds opt out

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
AUTHZ_KEYS = {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
              "amount", "captured_amount", "remaining_amount", "currency", "note", "visibility",
              "status", "expires_at", "payment_id", "payment_ids", "created_at"}
AUTHZ_STATUSES = {"open", "captured", "voided", "expired"}

# §3.4: RFC 3339 with an explicit numeric offset.
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$")
# PLAN 3.7 (D14): exactly YYYY-MM-DDTHH:MM:SS.sss+00:00.
PLAN_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$")
HANDLE = re.compile(r"^[a-z0-9_]{1,20}$")


def is_int(v: Any) -> bool:
    return type(v) is int


def check_id(v: Any, what: str = "id") -> None:
    assert isinstance(v, str) and 1 <= len(v) <= 64, f"{what} must be a string of 1..64 characters: {v!r}"


def ts(v: Any) -> datetime:
    assert isinstance(v, str) and RFC3339.match(v), f"timestamp is not RFC 3339 with an offset: {v!r}"
    return datetime.fromisoformat(v)


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


def check_authorization(a: dict, **want) -> dict:
    """PLAN 3.6: exactly the authorization fields, with the remainder rules of I33."""
    assert isinstance(a, dict) and set(a) == AUTHZ_KEYS, \
        f"authorization keys: {sorted(a) if isinstance(a, dict) else a!r}"
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
    times = [ts(i[field]) for i in items]
    assert times == sorted(times, reverse=True), \
        f"list is not newest first by {field}: {[i[field] for i in items]}"


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


class Service:
    """One running service, plus what the suite expects its state to be."""

    def __init__(self, base_url: str, name: str = "A"):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.total: int | None = None
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
        return Snapshot(body, resp.text, self.total, copy.deepcopy(self.accounts))

    def import_raw(self, body: Any = _UNSET, *, content: bytes | None = None) -> httpx.Response:
        if content is None:
            content = _json.dumps(body, ensure_ascii=False).encode("utf-8")
        return httpx.post(f"{self.base_url}/_test/import", content=content,
                          headers={"Content-Type": "application/json"}, timeout=RESET_TIMEOUT)

    def import_(self, snap: Snapshot) -> httpx.Response:
        resp = self.import_raw(snap.body)
        if resp.status_code == 204:
            self._by_handle.clear()
            self.accounts = copy.deepcopy(snap.accounts)
            self.total = snap.total
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
