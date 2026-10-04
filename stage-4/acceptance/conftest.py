"""Pytest wiring for the stage-4 acceptance suite (verifier-owned).

Options:
  --base-url URL          the service under test (required)
  --second-base-url URL   a second, independent instance of the same image; used by
                          the import-into-another-container checks (I26, W5.2, W8.2)
  --previous-base-url URL a service built from the frozen stage-1/ folder; used by the
                          upgrade checks (I37, W8.3, W10.7, W17.3)
  --previous2-base-url URL a service built from the frozen stage-2/ folder; used by the
                          stage-2 upgrade checks (I65, W17.3, W21.3)
  --previous3-base-url URL a service built from the frozen stage-3/ folder; used by the
                          stage-3 upgrade checks (I65, W21.3)
  --stage-dir DIR         the stage folder; needed by the container checks (W1.1, W1.2, W9.1)
  --container-prefix P    docker name prefix for containers the container checks start
  --spare-port N          first of three free host ports for the container checks
  --shots DIR             where the browser checks save one screenshot per named UI state
  --upto N                run only checks for work items up to WN (default 21: everything).
                          The stage-1 to stage-3 regression checks carry items 1 to 18 and
                          always run. From --upto 14 on, every test's teardown also checks
                          I67, I1 in historical views and, for a consistent seeded history, I2 at
                          every instant of the tracked accounts' history (sampled); from --upto 19
                          on, also I68 and I69 over every refund of the tracked accounts.

Every test carries `item(n)`: the work item whose behaviour it needs. A verdict on
Wn runs with `--upto n`.

Browser checks take the `page` fixture, which runs each of them twice: at 375x812
and at 1280x800 (W12.3).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support import Service, fixture, standard_users  # noqa: E402

VIEWPORTS = {"w375": {"width": 375, "height": 812}, "w1280": {"width": 1280, "height": 800}}


def pytest_addoption(parser):
    g = parser.getgroup("pocketful stage-4 acceptance")
    g.addoption("--base-url", default=None)
    g.addoption("--second-base-url", default=None)
    g.addoption("--previous-base-url", default=None)
    g.addoption("--previous2-base-url", default=None)
    g.addoption("--previous3-base-url", default=None)
    g.addoption("--stage-dir", default=None)
    g.addoption("--container-prefix", default="pf-verifier-acc")
    g.addoption("--spare-port", type=int, default=18210)
    g.addoption("--shots", default=None)
    g.addoption("--upto", type=int, default=21)


def pytest_configure(config):
    config.addinivalue_line("markers", "item(n): the highest work item (W1..W21) this check needs")
    Service.history_checks = config.getoption("--upto") >= 14
    Service.statement_checks = config.getoption("--upto") >= 15
    Service.refund_checks = config.getoption("--upto") >= 19
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
        pytest.fail("--base-url is required (stage-4/acceptance/run.sh supplies it)")
    return url.rstrip("/")


@pytest.fixture
def svc(base_url):
    """The service under test. Teardown asserts I1, I2 and I30 over every tracked account (from --upto 14,
    I67 and I1 and I2 in historical views; from --upto 19, I68 and I69)."""
    s = Service(base_url, "A")
    yield s
    try:
        s.assert_invariants(" after the test")
        s.assert_history_invariants(" after the test")
        s.assert_refund_invariants(" after the test")
    finally:
        s.close()


@pytest.fixture
def svc_b(request):
    url = request.config.getoption("--second-base-url")
    if not url:
        pytest.fail("--second-base-url is required for the second-container checks "
                    "(stage-4/acceptance/run.sh starts both containers)")
    s = Service(url, "B")
    yield s
    try:
        s.assert_invariants(" after the test")
        s.assert_history_invariants(" after the test")
        s.assert_refund_invariants(" after the test")
    finally:
        s.close()


@pytest.fixture
def prev(request):
    """The frozen stage-1 service: the source of the upgrade checks. Stage-1 /me has no holds."""
    url = request.config.getoption("--previous-base-url")
    if not url:
        pytest.fail("--previous-base-url is required for the upgrade checks "
                    "(stage-4/acceptance/run.sh builds the frozen stage-1/ and starts it)")
    s = Service(url, "stage-1")
    yield s
    s.close()


@pytest.fixture
def prev2(request):
    """The frozen stage-2 service: the source of the stage-2 upgrade checks (W17.3, W21.3)."""
    url = request.config.getoption("--previous2-base-url")
    if not url:
        pytest.fail("--previous2-base-url is required for the stage-2 upgrade checks "
                    "(stage-4/acceptance/run.sh builds the frozen stage-2/ and starts it)")
    s = Service(url, "stage-2")
    yield s
    s.close()


@pytest.fixture
def prev3(request):
    """The frozen stage-3 service: the source of the stage-3 upgrade checks (W21.3)."""
    url = request.config.getoption("--previous3-base-url")
    if not url:
        pytest.fail("--previous3-base-url is required for the stage-3 upgrade checks "
                    "(stage-4/acceptance/run.sh builds the frozen stage-3/ and starts it)")
    s = Service(url, "stage-3")
    yield s
    s.close()


@pytest.fixture
def world(svc):
    """Ada 10000, Bob 2500, Cy 500 and Dee 0, all signed in; Ada is a settlement operator."""
    fx = fixture(standard_users(), operators=["u_ada"])
    svc.must_reset(fx)
    return SimpleNamespace(svc=svc, fixture=fx, total=svc.total,
                           ada=svc.client("ada"), bob=svc.client("bob"),
                           cy=svc.client("cy"), dee=svc.client("dee"))


# ---------------------------------------------------------------- browser (W12.3)

@pytest.fixture(scope="session")
def browser(base_url):
    """One full Chromium for the run (Playwright from the harness venv)."""
    from playwright.sync_api import sync_playwright
    parts = urlsplit(base_url)
    with sync_playwright() as driver:
        instance = driver.chromium.launch(
            channel="chromium",
            args=[f"--unsafely-treat-insecure-origin-as-secure={parts.scheme}://{parts.netloc}"])
        yield instance
        instance.close()


@pytest.fixture(params=list(VIEWPORTS), ids=list(VIEWPORTS))
def page(request, browser, base_url):
    """A fresh context (no shared session) at one of the two widths."""
    context = browser.new_context(base_url=base_url, viewport=VIEWPORTS[request.param])
    context.set_default_timeout(10_000)
    tab = context.new_page()
    tab.width_id = request.param
    yield tab
    context.close()


@pytest.fixture
def ui(page, svc, request):
    from ui import UI
    shots = request.config.getoption("--shots")
    return UI(page, svc, shots_dir=Path(shots) if shots else None)
