"""Pytest wiring for the stage-1 acceptance suite (verifier-owned).

Options:
  --base-url URL          the service under test (required)
  --second-base-url URL   a second, independent instance of the same image; used by
                          the import-into-another-container checks (I26, W5.2)
  --stage-dir DIR         the stage folder; needed by the container checks (W1.1, W1.2)
  --container-prefix P    docker name prefix for containers the container checks start
  --spare-port N          first of two free host ports for the container checks
  --upto N                run only checks for work items W1..WN (default 5: everything)

Every test carries `item(n)`: the work item whose behaviour it needs. A verdict on
Wn runs with `--upto n`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support import Service, fixture, standard_users  # noqa: E402


def pytest_addoption(parser):
    g = parser.getgroup("pocketful stage-1 acceptance")
    g.addoption("--base-url", default=None)
    g.addoption("--second-base-url", default=None)
    g.addoption("--stage-dir", default=None)
    g.addoption("--container-prefix", default="pf-verifier-acc")
    g.addoption("--spare-port", type=int, default=18210)
    g.addoption("--upto", type=int, default=5)


def pytest_configure(config):
    config.addinivalue_line("markers", "item(n): the highest work item (W1..W5) this check needs")
    config.addinivalue_line("markers", "container: starts its own containers with docker")


def pytest_collection_modifyitems(config, items):
    upto = config.getoption("--upto")
    keep, drop = [], []
    for it in items:
        levels = [m.args[0] for m in it.iter_markers("item")]
        (keep if max(levels or [1]) <= upto else drop).append(it)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


@pytest.fixture(scope="session")
def base_url(request) -> str:
    url = request.config.getoption("--base-url")
    if not url:
        pytest.fail("--base-url is required (stage-1/acceptance/run.sh supplies it)")
    return url.rstrip("/")


@pytest.fixture
def svc(base_url):
    """The service under test. Teardown asserts I1 and I2 over every tracked account."""
    s = Service(base_url, "A")
    yield s
    try:
        s.assert_invariants(" after the test")
    finally:
        s.close()


@pytest.fixture
def svc_b(request):
    url = request.config.getoption("--second-base-url")
    if not url:
        pytest.fail("--second-base-url is required for the second-container checks "
                    "(stage-1/acceptance/run.sh starts both containers)")
    s = Service(url, "B")
    yield s
    try:
        s.assert_invariants(" after the test")
    finally:
        s.close()


@pytest.fixture
def world(svc):
    """Ada 10000, Bob 2500, Cy 500 and Dee 0, all signed in; Ada is a settlement operator."""
    fx = fixture(standard_users(), operators=["u_ada"])
    svc.must_reset(fx)
    return SimpleNamespace(svc=svc, fixture=fx, total=svc.total,
                           ada=svc.client("ada"), bob=svc.client("bob"),
                           cy=svc.client("cy"), dee=svc.client("dee"))
