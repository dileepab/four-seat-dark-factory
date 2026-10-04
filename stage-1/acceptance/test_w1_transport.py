"""W1.3 — transport, parsing, envelope, routes (§3.2, §3.4, §5; PLAN 3.2, 3.3, D3, D7-D10, D25, D28).

I10 (envelope) and I11 (no 5xx, no dropped connection) are asserted on every case.
"""
from __future__ import annotations

import socket
from urllib.parse import urlsplit

import httpx
import pytest

import json
import time

from support import Api, expect, expect_error, new_key, no_5xx, raw_exchange, raw_request

pytestmark = pytest.mark.item(1)

W2 = pytest.mark.item(2)
W3 = pytest.mark.item(3)
W4 = pytest.mark.item(4)
W5 = pytest.mark.item(5)


# ---------------------------------------------------------------- health

def test_health_is_200_status_ok(svc):
    assert expect(svc.api().get("/health"), 200) == {"status": "ok"}


def test_health_ignores_an_invalid_authorization_header(svc):
    r = svc.api().get("/health", headers={"Authorization": "Bearer not-a-token"})
    assert expect(r, 200) == {"status": "ok"}


# ---------------------------------------------------------------- routes (D3)

@pytest.mark.parametrize("method,path", [
    ("GET", "/nope"),
    ("POST", "/nope"),
    ("GET", "/"),
    ("DELETE", "/me"),
    ("PUT", "/me"),
    ("POST", "/me"),
    ("GET", "/auth/login"),
    ("GET", "/auth/signup"),
    ("GET", "/_test/reset"),
    ("PATCH", "/health"),
    pytest.param("GET", "/payments", marks=W2),
    pytest.param("DELETE", "/payments", marks=W2),
    pytest.param("OPTIONS", "/payments", marks=W2),
    pytest.param("POST", "/activity", marks=W2),
    pytest.param("GET", "/requests/rq_x/pay", marks=W3),
    pytest.param("GET", "/splits", marks=W3),
    pytest.param("GET", "/settlements", marks=W4),
    pytest.param("POST", "/_test/export", marks=W5),
    pytest.param("GET", "/_test/import", marks=W5),
])
def test_unknown_route_or_method_is_404_with_envelope(world, method, path):
    expect_error(world.ada.request(method, path), 404, "not_found")


def test_unknown_route_is_404_even_without_a_token(svc):
    """PLAN 3.5 step 1: the route is resolved before authentication."""
    expect_error(svc.api().get("/definitely/not/here"), 404, "not_found")


@pytest.mark.parametrize("method,path", [
    ("GET", "/me%E0%A4%A"),
    ("GET", "/%ZZ"),
    ("GET", "/%"),
    ("POST", "/auth/%E0%A4%A"),
    pytest.param("POST", "/requests/%E0%A4%A/pay", marks=W3),
    pytest.param("POST", "/requests/%ZZ/decline", marks=W3),
    pytest.param("POST", "/requests/%E0%A4%A/cancel", marks=W3),
])
def test_path_that_does_not_percent_decode_is_404(world, method, path):
    """PLAN 3.2 (D33): never a 5xx."""
    status, headers, body = raw_request(world.svc.base_url, method, path, token=world.ada.token,
                                        body=b"{}", extra=f"Idempotency-Key: {new_key()}\r\n")
    assert status == 404, (status, body[:200])
    assert json.loads(body)["error"]["code"] == "not_found"


def test_idle_keep_alive_connection_is_reused_after_six_seconds(svc):
    """PLAN 3.13 (D35): a connection idle for 6 s still gets its next response."""
    import socket
    from urllib.parse import urlsplit
    u = urlsplit(svc.base_url)
    req = f"GET /health HTTP/1.1\r\nHost: {u.hostname}\r\nConnection: keep-alive\r\n\r\n".encode()
    with socket.create_connection((u.hostname, u.port), timeout=10) as s:
        assert raw_exchange(s, req)[0] == 200
        time.sleep(6)
        status, _, body = raw_exchange(s, req)
    assert status == 200 and json.loads(body) == {"status": "ok"}


def test_pooled_client_survives_a_six_second_idle(svc):
    with httpx.Client(base_url=svc.base_url, timeout=5,
                      limits=httpx.Limits(keepalive_expiry=60)) as c:
        assert c.get("/health").status_code == 200
        time.sleep(6)
        assert c.get("/health").status_code == 200


def test_unknown_query_parameters_are_ignored(world):
    me = expect(world.ada.get("/me", params={"foo": "bar", "limit": "x"}), 200)
    assert me["handle"] == "ada"


# ---------------------------------------------------------------- body parsing (D7, D9, D10)

BAD_BODIES = {
    "invalid json": b"{nope",
    "truncated": b'{"email": "a@example.com"',
    "empty": b"",
    "whitespace": b"   \n\t ",
    "array": b"[]",
    "string": b'"hello"',
    "number": b"42",
    "null": b"null",
    "true": b"true",
    "trailing garbage": b'{"email": "a@example.com"} x',
    "invalid utf8": b'{"email": "a\xff@example.com", "password": "correct horse", "display_name": "X"}',
    "unpaired surrogate": b'{"email": "z@example.com", "password": "correct horse", "display_name": "\\ud800"}',
    "unpaired surrogate in a key": b'{"email": "z@example.com", "password": "correct horse", "display_name": "Z", "\\udc00": 1}',
    "lone low surrogate": b'{"email": "z@example.com", "password": "correct horse", "display_name": "a\\udfffb"}',
    "nan literal": b'{"amount": NaN}',
    "single quotes": b"{'email': 'a@example.com'}",
    "deep nesting": b'{"x": ' + b"[" * 200 + b"]" * 200 + b"}",
}


@pytest.mark.parametrize("name", list(BAD_BODIES))
def test_unparseable_signup_body_is_400(svc, name):
    expect_error(svc.api().post("/auth/signup", content=BAD_BODIES[name]), 400, "malformed_request")


@pytest.mark.parametrize("name", list(BAD_BODIES))
def test_unparseable_login_body_is_400(world, name):
    expect_error(world.svc.api().post("/auth/login", content=BAD_BODIES[name]), 400, "malformed_request")


@pytest.mark.parametrize("name", list(BAD_BODIES))
@pytest.mark.parametrize("path", [
    pytest.param("/payments", marks=W2),
    pytest.param("/requests", marks=W3),
    pytest.param("/splits", marks=W3),
    pytest.param("/settlements", marks=W4),
])
def test_unparseable_body_on_write_paths_is_400(world, path, name):
    expect_error(world.ada.post(path, content=BAD_BODIES[name], key=new_key()), 400, "malformed_request")


@pytest.mark.item(3)
@pytest.mark.parametrize("name", list(BAD_BODIES))
def test_unparseable_body_on_pay_is_400(world, name):
    rq = expect(world.bob.ask("ada", 100), 201)
    expect_error(world.ada.post(f"/requests/{rq['request_id']}/pay", content=BAD_BODIES[name],
                                key=new_key()), 400, "malformed_request")


@pytest.mark.parametrize("name", ["invalid json", "array", "empty", "invalid utf8", "deep nesting"])
def test_unparseable_reset_body_is_400_and_changes_nothing(world, name):
    expect_error(world.svc.api().post("/_test/reset", content=BAD_BODIES[name]), 400, "malformed_request")
    assert world.ada.balance() == 10_000


def test_moderate_nesting_in_an_unknown_field_is_accepted(world):
    """D9 rejects nesting deeper than 64; ten levels inside an unknown field are ignored."""
    body = (b'{"email": "nest@example.com", "password": "correct horse", "display_name": "N", '
            b'"extra": ' + b"[" * 10 + b"]" * 10 + b"}")
    expect(world.svc.api().post("/auth/signup", content=body), 201)


def test_request_content_type_is_not_checked(world):
    r = world.svc.api().post("/auth/signup", content=b'{"email": "ct@example.com", "password": "correct horse", "display_name": "C"}',
                       headers={"Content-Type": "text/plain"})
    expect(r, 201)


def test_chunked_request_body_is_read(world):
    def gen():
        yield b'{"email": "chunk@example.com", '
        yield b'"password": "correct horse", "display_name": "Chunk"}'
    with httpx.Client(base_url=world.svc.base_url, timeout=5) as c:
        r = c.post("/auth/signup", content=gen(), headers={"Content-Type": "application/json"})
    expect(r, 201)


# ---------------------------------------------------------------- size limits (D8, D28)

MIB = 1024 * 1024


def _signup_with_padding(n_bytes: int) -> bytes:
    head = b'{"email": "big@example.com", "password": "correct horse", "display_name": "Big", "pad": "'
    tail = b'"}'
    return head + b"a" * (n_bytes - len(head) - len(tail)) + tail


def test_body_just_under_one_mib_is_accepted(world):
    expect(world.svc.api().post("/auth/signup", content=_signup_with_padding(MIB - 4096)), 201)


def test_body_of_exactly_one_mib_is_accepted(world):
    """PLAN 3.2 (D8): the limit is 1 MiB; only a larger body is 422."""
    body = _signup_with_padding(MIB)
    assert len(body) == MIB
    expect(world.svc.api().post("/auth/signup", content=body), 201)


def test_body_of_one_mib_plus_one_byte_is_422(world):
    expect_error(world.svc.api().post("/auth/signup", content=_signup_with_padding(MIB + 1)),
                 422, "validation_failed")


def test_body_over_one_mib_is_422_and_answered(world):
    expect_error(world.svc.api().post("/auth/signup", content=_signup_with_padding(MIB + 4096)),
                 422, "validation_failed")


def test_five_mib_body_is_answered_not_dropped(world):
    """D8: the server drains the body, so the client always reads the 422."""
    expect_error(world.svc.api().post("/auth/signup", content=_signup_with_padding(5 * MIB)),
                 422, "validation_failed")
    assert expect(world.svc.api().get("/health"), 200) == {"status": "ok"}


@pytest.mark.item(2)
def test_payment_body_over_one_mib_is_422_and_moves_nothing(world):
    body = b'{"to_handle": "bob", "amount": 100, "pad": "' + b"a" * (MIB + 10) + b'"}'
    expect_error(world.ada.post("/payments", content=body, key=new_key()), 422, "validation_failed")
    assert world.ada.balance() == 10_000


def test_reset_accepts_a_body_well_over_one_mib(svc):
    """The reset limit is 64 MiB (D8): a 3 MiB fixture is fine."""
    from support import fixture
    fx = fixture()
    fx["padding"] = "x" * (3 * MIB)
    svc.must_reset(fx)
    assert svc.client("ada").balance() == 10_000


def test_header_of_300_kib_is_accepted(world):
    r = world.ada.get("/me", headers={"X-Padding": "a" * (300 * 1024)})
    expect(r, 200)


def test_oversized_header_block_is_422_with_envelope(world):
    """D28: blocks up to 1 MiB are accepted; a 2 MiB block is refused with the envelope."""
    r = world.ada.get("/me", headers={"X-Padding": "a" * (2 * MIB)})
    expect_error(r, 422, "validation_failed")


def test_garbage_request_line_gets_400_envelope(svc):
    """D28: when the HTTP layer rejects a request, the answer still carries the envelope."""
    u = urlsplit(svc.base_url)
    with socket.create_connection((u.hostname, u.port or 80), timeout=5) as s:
        s.sendall(b"THIS IS NOT HTTP\r\n\r\n")
        data = b""
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
                if b"\r\n\r\n" in data and b'"error"' in data:
                    break
        except socket.timeout:
            pass
    head, _, body = data.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 400"), f"expected a 400 answer, got {data[:200]!r}"
    assert b'"malformed_request"' in body, f"400 without the envelope: {data[:300]!r}"


# ---------------------------------------------------------------- query parameters (D25)

@pytest.mark.item(2)
def test_repeated_query_parameter_uses_the_first(world):
    for _ in range(3):
        expect(world.ada.pay("bob", 1), 201)
    page = expect(world.ada.get("/activity?limit=1&limit=500"), 200)
    assert len(page["payments"]) == 1 and page["has_more"] is True
    expect_error(world.ada.get("/activity?limit=500&limit=1"), 422, "validation_failed")


# ---------------------------------------------------------------- robustness (I11)

WEIRD_VALUES = [None, True, 0, -1, 1.5, 1e308, "", " ", "x" * 5000, [], {}, ["a"], {"a": 1},
                "\u0000", "😀" * 50, "‮", 2 ** 64, -(2 ** 64)]


@pytest.mark.parametrize("field", ["email", "password", "display_name"])
@pytest.mark.parametrize("value", WEIRD_VALUES, ids=lambda v: repr(v)[:20])
def test_signup_never_5xx_on_weird_values(world, field, value):
    body = {"email": "w@example.com", "password": "correct horse", "display_name": "W"}
    body[field] = value
    r = world.svc.api().post("/auth/signup", json=body)
    no_5xx(r)
    assert r.status_code in (201, 400, 409, 422), r.status_code
