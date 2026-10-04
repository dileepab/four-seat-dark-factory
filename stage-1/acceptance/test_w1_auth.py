"""W1.5-W1.7, W1.9 — signup, login, tokens, GET /me (§4 handles, §6, §8 GET /me; PLAN 3.8, D11-D13, D30).

Invariants I13 (tokens), I14 (handles), I10 (envelope), I11 (no 5xx under 50 logins).
"""
from __future__ import annotations

import re

import pytest

from support import (AUTH_KEYS, check_id, check_me, expect, expect_error, fixture, new_key,
                     no_failures, tally, user)

pytestmark = pytest.mark.item(1)

W2, W3, W4, W5 = (pytest.mark.item(n) for n in (2, 3, 4, 5))
PW = "correct horse"


def signup(world, email, password=PW, display_name="New"):
    return world.svc.signup(email, password, display_name)


# ---------------------------------------------------------------- signup

def test_signup_returns_201_with_exactly_user_id_display_name_token(world):
    body = expect(signup(world, "new.user@example.com", display_name="New User"), 201)
    assert set(body) == AUTH_KEYS
    check_id(body["user_id"], "user_id")
    assert body["display_name"] == "New User"
    assert isinstance(body["token"], str) and body["token"]


def test_new_user_me_has_derived_handle_zero_balance_and_service_currency(world):
    body = expect(signup(world, "new.user@example.com", display_name="  Ünïcode 😀  "), 201)
    me = check_me(world.svc.api(body["token"]).me())
    assert me == {"user_id": body["user_id"], "display_name": "  Ünïcode 😀  ", "handle": "new_user",
                  "balance": 0, "currency": "EUR", "minor_units": 2}


def test_new_user_in_a_jpy_service_holds_zero_yen(svc):
    svc.must_reset(fixture(currency="JPY"))
    body = expect(svc.signup("yen@example.com", PW, "Yen"), 201)
    me = svc.api(body["token"]).me()
    assert (me["balance"], me["currency"], me["minor_units"]) == (0, "JPY", 0)


@pytest.mark.parametrize("email,handle", [
    ("Dee.Ann+tag@example.com", "dee_ann_tag"),
    ("a" * 30 + "@example.com", "a" * 20),
    ("MiXeD_Case9@example.com", "mixed_case9"),
    ("ÄBC@example.com", "_bc"),
    ("😀smile@example.com", "_smile"),
    ("😀" * 25 + "@example.com", "_" * 20),
    ("x@y", "x"),
    ("first-last@example.com", "first_last"),
    ("o'brien@example.com", "o_brien"),
    ("12345@example.com", "12345"),
])
def test_handle_is_derived_from_the_local_part(world, email, handle):
    body = expect(signup(world, email), 201)
    assert world.svc.api(body["token"]).me()["handle"] == handle


def test_signup_ignores_a_handle_and_a_balance_in_the_body(world):
    r = world.svc.api().post("/auth/signup", json={"email": "sneaky@example.com", "password": PW,
                                                   "display_name": "S", "handle": "boss",
                                                   "balance": 999999, "user_id": "u_ada"})
    body = expect(r, 201)
    me = world.svc.api(body["token"]).me()
    assert me["handle"] == "sneaky" and me["balance"] == 0 and me["user_id"] != "u_ada"


def test_taken_derived_handle_is_409_and_creates_no_account(world):
    expect_error(signup(world, "ADA@other.example.org"), 409, "handle_taken")
    expect_error(world.svc.login("ADA@other.example.org", PW), 401, "unauthenticated")
    expect_error(signup(world, "ada@other.example.org"), 409, "handle_taken")


def test_truncation_collision_is_handle_taken(world):
    expect(signup(world, "b" * 25 + "@example.com"), 201)
    expect_error(signup(world, "b" * 30 + "@example.net"), 409, "handle_taken")


@pytest.mark.parametrize("email", ["ada@example.com", "ADA@EXAMPLE.COM", "Ada@Example.Com"])
def test_registered_email_is_email_taken_case_insensitively(world, email):
    expect_error(signup(world, email), 409, "email_taken")


def test_signed_up_email_is_taken_case_insensitively(world):
    expect(signup(world, "Zoe@Example.com"), 201)
    expect_error(signup(world, "zoe@example.com"), 409, "email_taken")


@pytest.mark.parametrize("password,status", [
    ("1234567", 422), ("12345678", 201), ("😀" * 7, 422), ("😀" * 8, 201),
    ("p" * 1024, 201), ("p" * 1025, 422), ("", 422), ("       ", 422),
])
def test_password_length_in_code_points(world, password, status):
    r = signup(world, "pwlen@example.com", password=password)
    if status == 201:
        expect(r, 201)
        expect(world.svc.login("pwlen@example.com", password), 200)
    else:
        expect_error(r, 422, "validation_failed")


@pytest.mark.parametrize("email", [
    "plain", "@example.com", "local@", "a@@example.com", "a@b@example.com", "a b@example.com",
    "a@exa mple.com", "tab\t@example.com", "nl\n@example.com", "", " ", "a" * 250 + "@example.com",
])
def test_email_must_be_local_at_domain(world, email):
    expect_error(signup(world, email), 422, "validation_failed")


@pytest.mark.parametrize("email", ["first.last+tag@sub.example.co.uk", "x@y", "UPPER@EXAMPLE.ORG"])
def test_valid_email_forms_are_accepted(world, email):
    expect(signup(world, email), 201)


@pytest.mark.parametrize("name,status", [("", 422), ("D" * 100, 201), ("D" * 101, 422),
                                         ("😀" * 100, 201), ("😀" * 101, 422), (" ", 201)])
def test_display_name_length_in_code_points(world, name, status):
    r = signup(world, "dn@example.com", display_name=name)
    if status == 201:
        assert expect(r, 201)["display_name"] == name
    else:
        expect_error(r, 422, "validation_failed")


@pytest.mark.parametrize("field", ["email", "password", "display_name"])
def test_missing_signup_field_is_422(world, field):
    body = {"email": "m@example.com", "password": PW, "display_name": "M"}
    body.pop(field)
    expect_error(world.svc.api().post("/auth/signup", json=body), 422, "validation_failed")


@pytest.mark.parametrize("field", ["email", "password", "display_name"])
@pytest.mark.parametrize("value", [5, None, True, [], {}, ["m@example.com"]], ids=repr)
def test_wrong_type_signup_field_is_400(world, field, value):
    body = {"email": "m@example.com", "password": PW, "display_name": "M"}
    body[field] = value
    expect_error(world.svc.api().post("/auth/signup", json=body), 400, "malformed_request")


def test_signup_type_error_outranks_missing_fields(world):
    expect_error(world.svc.api().post("/auth/signup", json={"email": 5}), 400, "malformed_request")


def test_signup_validation_outranks_email_taken(world):
    r = world.svc.api().post("/auth/signup", json={"email": "ada@example.com", "password": "short",
                                                   "display_name": "A"})
    expect_error(r, 422, "validation_failed")


def test_signup_ignores_an_invalid_authorization_header(world):
    r = world.svc.api().post("/auth/signup", json={"email": "h@example.com", "password": PW,
                                                   "display_name": "H"},
                             headers={"Authorization": "Bearer garbage"})
    expect(r, 201)


# ---------------------------------------------------------------- login

def test_login_returns_200_with_user_id_display_name_token(world):
    body = expect(world.svc.login("bob@example.com", "pw-bob-Correct-Horse-9"), 200)
    assert set(body) == AUTH_KEYS
    assert body["user_id"] == "u_bob" and body["display_name"] == "Bob"


def test_login_after_signup_returns_the_same_user(world):
    s = expect(signup(world, "lin@example.com", display_name="Lin"), 201)
    body = expect(world.svc.login("lin@example.com", PW), 200)
    assert body["user_id"] == s["user_id"] and body["display_name"] == "Lin"
    assert body["token"] != s["token"]


def test_every_issued_token_stays_valid(world):
    tokens = [expect(world.svc.login("cy@example.com", "pw-cy-Correct-Horse-9"), 200)["token"]
              for _ in range(4)]
    tokens.append(world.cy.token)
    assert len(set(tokens)) == len(tokens), "each login issues a new token"
    for t in tokens:
        assert world.svc.api(t).me()["user_id"] == "u_cy"


def test_tokens_are_long_random_base64url(world):
    """PLAN 3.8: at least 256 random bits, base64url."""
    t = expect(world.svc.login("ada@example.com", "pw-ada-Correct-Horse-9"), 200)["token"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43,}", t), t


@pytest.mark.parametrize("email,password", [
    ("ada@example.com", "wrong password"),
    ("ada@example.com", "PW-ADA-CORRECT-HORSE-9"),
    ("ada@example.com", "pw-ada-Correct-Horse-9 "),
    ("ada@example.com", "x"),
    ("nobody@example.com", "pw-ada-Correct-Horse-9"),
])
def test_wrong_password_or_unknown_email_is_401(world, email, password):
    expect_error(world.svc.login(email, password), 401, "unauthenticated")


def test_login_email_is_case_insensitive(world):
    expect(world.svc.login("ADA@Example.COM", "pw-ada-Correct-Horse-9"), 200)


def test_login_with_a_malformed_email_is_422(world):
    expect_error(world.svc.login("not-an-email", "whatever1"), 422, "validation_failed")


@pytest.mark.parametrize("field", ["email", "password"])
def test_login_missing_field_is_422(world, field):
    body = {"email": "ada@example.com", "password": "pw-ada-Correct-Horse-9"}
    body.pop(field)
    expect_error(world.svc.api().post("/auth/login", json=body), 422, "validation_failed")


@pytest.mark.parametrize("field", ["email", "password"])
@pytest.mark.parametrize("value", [5, None, [], {}], ids=repr)
def test_login_wrong_type_is_400(world, field, value):
    body = {"email": "ada@example.com", "password": "pw-ada-Correct-Horse-9"}
    body[field] = value
    expect_error(world.svc.api().post("/auth/login", json=body), 400, "malformed_request")


def test_login_ignores_an_invalid_authorization_header(world):
    r = world.svc.api().post("/auth/login", json={"email": "ada@example.com",
                                                  "password": "pw-ada-Correct-Horse-9"},
                             headers={"Authorization": "Basic Zm9vOmJhcg=="})
    expect(r, 200)


# ---------------------------------------------------------------- bearer tokens (W1.6)

ENDPOINTS = [
    pytest.param("GET", "/me", id="me"),
    pytest.param("POST", "/payments", marks=W2, id="payments"),
    pytest.param("GET", "/activity", marks=W2, id="activity"),
    pytest.param("POST", "/requests", marks=W3, id="requests-post"),
    pytest.param("GET", "/requests", marks=W3, id="requests-get"),
    pytest.param("POST", "/requests/rq_seed/pay", marks=W3, id="pay"),
    pytest.param("POST", "/requests/rq_seed/decline", marks=W3, id="decline"),
    pytest.param("POST", "/requests/rq_seed/cancel", marks=W3, id="cancel"),
    pytest.param("POST", "/splits", marks=W3, id="splits"),
    pytest.param("POST", "/settlements", marks=W4, id="settlements"),
]

BAD_AUTH = {
    "missing": None,
    "basic scheme": "Basic Zm9vOmJhcg==",
    "bearer without token": "Bearer",   # "Bearer " is the same header once HTTP trims trailing space
    "unknown token": "Bearer " + "A" * 43,
    "token scheme": "Token {tok}",
    "no scheme": "{tok}",
    "token with a space": "Bearer {tok} extra",
}


@pytest.fixture
def seeded(svc):
    fx = fixture(operators=["u_ada"], requests=[
        {"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 100}])
    svc.must_reset(fx)
    return svc


@pytest.mark.parametrize("method,path", ENDPOINTS)
@pytest.mark.parametrize("variant", list(BAD_AUTH))
def test_bad_or_missing_bearer_is_401(seeded, method, path, variant):
    tok = seeded.client("ada").token
    header = BAD_AUTH[variant]
    headers = {"Authorization": header.format(tok=tok) if header else None}
    r = seeded.api().request(method, path, json={"to_handle": "bob", "amount": 1}, key=new_key(),
                             headers=headers, token=None)
    expect_error(r, 401, "unauthenticated")
    assert seeded.client("ada").balance() == 10_000


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_401_outranks_missing_key_and_unparseable_body(seeded, method, path):
    r = seeded.api().request(method, path, content=b"{nope", token=None)
    expect_error(r, 401, "unauthenticated")


@pytest.mark.parametrize("scheme", ["bearer", "BEARER", "Bearer  "])
def test_bearer_scheme_is_case_insensitive_and_spaces_are_tolerated(world, scheme):
    r = world.svc.api().get("/me", token=None,
                            headers={"Authorization": f"{scheme} {world.ada.token}"})
    assert expect(r, 200)["handle"] == "ada"


# ---------------------------------------------------------------- GET /me (W1.7)

def test_me_for_every_seeded_user(world):
    for u in world.fixture["users"]:
        me = check_me(world.svc.client(u["handle"]).me())
        assert me == {"user_id": u["id"], "display_name": u["display_name"], "handle": u["handle"],
                      "balance": u["balance"], "currency": "EUR", "minor_units": 2}


# ---------------------------------------------------------------- concurrency (W1.9)

def test_fifty_concurrent_logins(world):
    clients = [world.svc.api() for _ in range(50)]
    out = world.svc.burst(lambda i: clients[i].post(
        "/auth/login", json={"email": "ada@example.com", "password": "pw-ada-Correct-Horse-9"}), 50)
    no_failures(out)
    assert tally(out) == {200: 50}, tally(out)
    tokens = {r.json()["token"] for r in out}
    assert len(tokens) == 50
    for t in list(tokens)[:5]:
        assert world.svc.api(t).me()["handle"] == "ada"


def test_ten_concurrent_signups_with_one_email(world):
    clients = [world.svc.api() for _ in range(10)]
    out = world.svc.burst(lambda i: clients[i].post(
        "/auth/signup", json={"email": "race@example.com", "password": PW, "display_name": f"R{i}"}), 10)
    no_failures(out)
    assert tally(out) == {201: 1, 409: 9}, tally(out)
    assert all(r.json()["error"]["code"] == "email_taken" for r in out if r.status_code == 409)
    expect(world.svc.login("race@example.com", PW), 200)


def test_ten_concurrent_signups_with_case_variants_of_one_email(world):
    emails = ["race@example.com", "RACE@example.com", "Race@Example.com", "rAcE@example.com",
              "race@EXAMPLE.com", "RACE@EXAMPLE.COM", "raCe@example.com", "racE@example.com",
              "Race@example.com", "rACE@example.com"]
    clients = [world.svc.api() for _ in range(10)]
    out = world.svc.burst(lambda i: clients[i].post(
        "/auth/signup", json={"email": emails[i], "password": PW, "display_name": "R"}), 10)
    no_failures(out)
    assert tally(out) == {201: 1, 409: 9}, tally(out)
    assert all(r.json()["error"]["code"] == "email_taken" for r in out if r.status_code == 409)


def test_concurrent_signups_deriving_one_handle(world):
    emails = [f"sam@domain{i}.example" for i in range(10)]
    clients = [world.svc.api() for _ in range(10)]
    out = world.svc.burst(lambda i: clients[i].post(
        "/auth/signup", json={"email": emails[i], "password": PW, "display_name": "Sam"}), 10)
    no_failures(out)
    assert tally(out) == {201: 1, 409: 9}, tally(out)
    assert all(r.json()["error"]["code"] == "handle_taken" for r in out if r.status_code == 409)
    logins = [world.svc.login(e, PW).status_code for e in emails]
    assert sorted(logins) == [200] + [401] * 9, logins
