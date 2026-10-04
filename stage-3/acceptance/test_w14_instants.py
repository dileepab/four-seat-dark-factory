"""W14.4, W14.5 — the instant grammar on `GET /me?as_of=&known_at=` (stage-3 "`GET /me` as of an
instant", "Effective time, recorded time, and corrections"; PLAN 3.2 (D79), 3.4 (D66), 3.6, 3.9).
I52, I53, I59.

The same VALID and INVALID lists drive the statement, correction and reset checks (W15, W16, W14.1).
"""
from __future__ import annotations

import json

import pytest

from support import (EPOCH, FAR_FUTURE, ME_KEYS, check_me, check_me_view, expect, expect_error, raw_request)

pytestmark = pytest.mark.item(14)

_64 = "2026-01-01T00:00:00." + "0" * 43 + "Z"
assert len(_64) == 64

# PLAN 3.4: accepted, compared exactly, echoed verbatim.
VALID = [
    "2026-01-01T00:00:00Z", "2026-01-01T00:00:00z", "2026-01-01t00:00:00Z", "2026-01-01t00:00:00z",
    "2026-01-01T05:30:00+05:30", "2025-12-31T19:00:00-05:00", "2026-01-01T00:00:00-00:00",
    "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+23:59", "2026-01-01T00:00:00-23:59",
    "2026-01-01T00:00:00.5Z", "2026-01-01T00:00:00.123+00:00", "2026-01-01T00:00:00.123456Z",
    "2026-01-01T00:00:00.123456789012Z", "2024-02-29T23:59:59.999999+00:00", "2000-02-29T00:00:00Z",
    "1970-01-01T00:00:00Z", "9999-12-31T23:59:59Z", _64,
]

# PLAN 3.4 / I53: everything else is 422 validation_failed.
INVALID = {
    "empty": "",
    "bare date": "2026-01-01",
    "naive time": "2026-01-01T00:00:00",
    "naive with fraction": "2026-01-01T00:00:00.123",
    "space separator": "2026-01-01 00:00:00Z",
    "no seconds": "2026-01-01T00:00Z",
    "February 30": "2026-02-30T00:00:00Z",
    "February 29 in 2025": "2025-02-29T00:00:00Z",
    "February 29 in 1900": "1900-02-29T00:00:00Z",
    "April 31": "2026-04-31T00:00:00Z",
    "month 13": "2026-13-01T00:00:00Z",
    "month 00": "2026-00-10T00:00:00Z",
    "day 00": "2026-01-00T00:00:00Z",
    "hour 24": "2026-01-01T24:00:00Z",
    "minute 60": "2026-01-01T23:60:00Z",
    "leap second": "2026-12-31T23:59:60Z",
    "offset +24:00": "2026-01-01T00:00:00+24:00",
    "offset minutes 60": "2026-01-01T00:00:00+05:60",
    "offset without colon": "2026-01-01T00:00:00+0530",
    "offset hours only": "2026-01-01T00:00:00+05",
    "dot without digits": "2026-01-01T00:00:00.Z",
    "comma fraction": "2026-01-01T00:00:00,5Z",
    "two-digit year": "26-01-01T00:00:00Z",
    "one-digit month": "2026-1-01T00:00:00Z",
    "signed year": "+2026-01-01T00:00:00Z",
    "leading space": " 2026-01-01T00:00:00Z",
    "trailing space": "2026-01-01T00:00:00Z ",
    "UTC suffix": "2026-01-01T00:00:00UTC",
    "two zones": "2026-01-01T00:00:00+05:30Z",
    "double Z": "2026-01-01T00:00:00ZZ",
    "epoch number": "1767225600",
    "word": "now",
    "fullwidth digits": "２０２６-01-01T00:00:00Z",
    "65 characters": _64[:-1] + "0Z",
    "trailing newline": "2026-01-01T00:00:00Z\n",
}
assert len(INVALID["65 characters"]) == 65


@pytest.fixture
def ada(world):
    return world.ada


@pytest.mark.parametrize("value", VALID)
def test_valid_as_of_is_echoed_exactly(ada, value):
    m = expect(ada.get("/me", params={"as_of": value}), 200)
    check_me_view(m, as_of=value)


@pytest.mark.parametrize("value", VALID)
def test_valid_known_at_is_echoed_exactly(ada, value):
    m = expect(ada.get("/me", params={"known_at": value}), 200)
    check_me_view(m, known_at=value)


@pytest.mark.parametrize("value", INVALID.values(), ids=INVALID.keys())
def test_invalid_as_of_is_422(ada, value):
    expect_error(ada.get("/me", params={"as_of": value}), 422, "validation_failed")


@pytest.mark.parametrize("value", INVALID.values(), ids=INVALID.keys())
def test_invalid_known_at_is_422(ada, value):
    expect_error(ada.get("/me", params={"known_at": value}), 422, "validation_failed")


@pytest.mark.parametrize("good, bad", [("as_of", "known_at"), ("known_at", "as_of")])
def test_one_invalid_parameter_fails_the_read(ada, good, bad):
    expect_error(ada.get("/me", params={good: "2026-01-01T00:00:00Z", bad: "2026-01-01"}), 422,
                 "validation_failed")


def test_both_parameters_are_echoed(ada):
    m = expect(ada.get("/me", params={"as_of": "2026-01-01T00:00:00.5z", "known_at": "2026-06-01t00:00:00-00:00"}),
               200)
    check_me_view(m, as_of="2026-01-01T00:00:00.5z", known_at="2026-06-01t00:00:00-00:00")


def test_without_temporal_parameters_me_is_the_stage_2_shape(ada):
    """I52: no as_of and no known_at field; current values (T9)."""
    m = check_me(expect(ada.get("/me"), 200))
    assert set(m) == ME_KEYS and "as_of" not in m and "known_at" not in m
    assert (m["total"], m["available"], m["held"]) == (10_000, 10_000, 0)


def test_unknown_parameters_are_ignored(ada):
    m = check_me(expect(ada.get("/me", params={"asof": "x", "as_of_": "y", "AS_OF": "z"}), 200))
    assert set(m) == ME_KEYS


def test_a_token_is_checked_before_the_instant(world):
    """PLAN 3.9: 401 first."""
    anon = world.svc.api()
    expect_error(anon.get("/me", params={"as_of": "not an instant"}), 401, "unauthenticated")
    expect_error(anon.get("/me", params={"known_at": ""}), 401, "unauthenticated")


@pytest.mark.parametrize("param", ["as_of", "known_at"])
def test_a_literal_plus_is_a_plus_sign(world, param):
    """D79: a raw `+` in the query is the offset sign, not a space; `%2B` works too."""
    for raw, sent in (("2026-01-01T05:30:00+05:30", "2026-01-01T05:30:00+05:30"),
                      ("2026-01-01T05:30:00%2B05:30", "2026-01-01T05:30:00+05:30"),
                      ("2026-01-01T05%3A30%3A00%2b05%3a30", "2026-01-01T05:30:00+05:30")):
        status, _, body = raw_request(world.svc.base_url, "GET", f"/me?{param}={raw}", token=world.ada.token)
        assert status == 200, f"{param}={raw}: {status} {body[:200]!r}"
        m = json.loads(body)
        check_me_view(m, **{param: sent})


@pytest.mark.parametrize("param", ["as_of", "known_at"])
def test_the_first_of_a_repeated_parameter_counts(world, param):
    """D25: the first occurrence is used."""
    status, _, body = raw_request(world.svc.base_url, "GET",
                                  f"/me?{param}=2026-01-01T00:00:00Z&{param}=nonsense", token=world.ada.token)
    assert status == 200, body[:200]
    assert json.loads(body)[param] == "2026-01-01T00:00:00Z"
    status, _, body = raw_request(world.svc.base_url, "GET",
                                  f"/me?{param}=nonsense&{param}=2026-01-01T00:00:00Z", token=world.ada.token)
    assert status == 422 and json.loads(body)["error"]["code"] == "validation_failed", body[:200]


def test_an_encoded_space_is_not_an_offset_sign(world):
    """D79: a space (`%20`) can never be part of an instant."""
    status, _, body = raw_request(world.svc.base_url, "GET", "/me?as_of=2026-01-01T05:30:00%2005:30",
                                  token=world.ada.token)
    assert status == 422, body[:200]


def test_far_past_and_far_future_views(ada):
    """T41: both instants may be in the future; as_of before everything is the opening balance."""
    assert ada.me_at(EPOCH)["total"] == 10_000          # a fixture with no seeded payments opens at its balance
    assert ada.me_at(FAR_FUTURE)["total"] == 10_000
    assert ada.me_at(None, FAR_FUTURE)["total"] == 10_000
    assert ada.me_at(FAR_FUTURE, FAR_FUTURE)["total"] == 10_000


@pytest.mark.parametrize("param", ["as_of", "known_at"])
@pytest.mark.parametrize("raw", ["%ZZ", "%", "%2", "2026-01-01T00:00:00%ZZ", "%FF"])
def test_a_broken_percent_escape_is_422_not_absent(world, param, raw):
    """3.2, 3.4, I53 (critic Q04): a value that cannot be percent-decoded is present and invalid, never absent."""
    status, _, body = raw_request(world.svc.base_url, "GET", f"/me?{param}={raw}", token=world.ada.token)
    assert status == 422 and json.loads(body)["error"]["code"] == "validation_failed", (status, body[:200])
