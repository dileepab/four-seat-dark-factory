"""W9.1 — HTML routes, content negotiation, headers and assets over HTTP (stage-2 route table;
PLAN 3.2, 3.8, 3.14, D39, D40, D59). I11, I45, I48, I49."""
from __future__ import annotations

import re
import subprocess
import time
from urllib.parse import urljoin, urlsplit

import httpx
import pytest

from support import expect, expect_error, raw_request

pytestmark = pytest.mark.item(9)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
HTML_ACCEPTS = ["text/html", "TEXT/HTML", "text/html;q=0.5", "application/json, text/html",
                " text/html ; charset=utf-8 ", "text/html;q=0.001", BROWSER_ACCEPT]
NOT_HTML_ACCEPTS = [None, "", "*/*", "application/json", "text/*", "text/html;q=0", "text/html; q=0.000",
                    "text/htmlx", "application/xhtml+xml", "text/plain, application/json;q=0.5"]
CONTENT_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}


def get(base, path, accept=None, token=None, method="GET"):
    """A request whose Accept header is exactly `accept` (absent when None)."""
    if accept is None:
        status, headers, body = raw_request(base, method, path, token=token)
        return status, headers, body
    extra = f"Accept: {accept}\r\n"
    return raw_request(base, method, path, token=token, extra=extra)


def assert_html(status, headers, body, want=200):
    assert status == want, (status, body[:200])
    assert headers.get("content-type", "").replace(" ", "").lower() == "text/html;charset=utf-8", headers
    assert headers.get("cache-control") == "no-store", headers
    assert headers.get("x-content-type-options") == "nosniff", headers
    assert headers.get("referrer-policy") == "no-referrer", headers
    assert headers.get("content-security-policy") == CSP, headers.get("content-security-policy")
    text = body.decode("utf-8")
    assert re.search(r"<html[^>]*\blang=[\"']?en\b", text, re.I), "PLAN 3.15: <html lang=\"en\">"
    assert re.search(r"<link[^>]*\brel=[\"']?[^\"'>]*\bicon\b", text, re.I), \
        "PLAN 3.14: the shell suppresses the favicon request"
    return text


def assert_json(status, headers, body):
    assert headers.get("content-type", "").replace(" ", "").lower() == "application/json;charset=utf-8", \
        (status, headers, body[:200])
    import json
    return status, json.loads(body)


@pytest.mark.parametrize("path", ["/", "/split", "/signup", "/login"])
@pytest.mark.parametrize("accept", [None, "application/json", "*/*", "text/html"])
def test_page_routes_serve_the_shell_whatever_the_accept(world, path, accept):
    assert_html(*get(world.svc.base_url, path, accept))


@pytest.mark.parametrize("path", ["/requests", "/authorizations", "/requests?status=bogus&limit=0",
                                  "/authorizations?direction=x"])
@pytest.mark.parametrize("accept", HTML_ACCEPTS)
@pytest.mark.parametrize("signed_in", [False, True], ids=["anonymous", "token"])
def test_shared_paths_serve_the_shell_when_accept_lists_text_html(world, path, accept, signed_in):
    assert_html(*get(world.svc.base_url, path, accept, token=world.ada.token if signed_in else None))


@pytest.mark.parametrize("path,field", [("/requests", "requests"), ("/authorizations", "authorizations")])
@pytest.mark.parametrize("accept", NOT_HTML_ACCEPTS)
def test_shared_paths_answer_json_otherwise(world, path, field, accept):
    status, body = assert_json(*get(world.svc.base_url, path, accept, token=world.ada.token))
    assert status == 200 and set(body) == {field, "has_more"}
    status, body = assert_json(*get(world.svc.base_url, path, accept))
    assert status == 401 and body["error"]["code"] == "unauthenticated"


def test_post_on_shared_paths_is_always_the_api(world):
    r = world.ada.post("/requests", json={"payer_handle": "bob", "amount": 5}, key="k-html-1",
                       headers={"Accept": "text/html"})
    assert expect(r, 201)["payer_handle"] == "bob"
    r = world.ada.post("/authorizations", json={"to_handle": "bob", "amount": 5}, key="k-html-2",
                       headers={"Accept": BROWSER_ACCEPT})
    assert expect(r, 201)["to_handle"] == "bob"
    expect_error(world.svc.api().post("/requests", json={}, headers={"Accept": "text/html"}), 401, "unauthenticated")


def test_html_routes_never_read_authorization(world):
    for path in ("/", "/login", "/requests"):
        assert_html(*get(world.svc.base_url, path, "text/html", token="junk-token"))


@pytest.mark.parametrize("path", ["/nope", "/requests/rq_x", "/payments/x", "/me/x", "/assetsx", "/split/x"])
def test_unknown_get_path_is_json_404_or_the_html_not_found_screen(world, path):
    base = world.svc.base_url
    status, body = assert_json(*get(base, path, None))
    assert status == 404 and body["error"]["code"] == "not_found"
    status, body = assert_json(*get(base, path, "application/json"))
    assert status == 404 and body["error"]["code"] == "not_found"
    assert_html(*get(base, path, "text/html"), want=404)


@pytest.mark.parametrize("method,path", [("POST", "/"), ("POST", "/login"), ("PUT", "/split"), ("DELETE", "/signup"),
                                         ("POST", "/assets/x.js")])
def test_other_methods_on_page_routes_are_404_envelopes(world, method, path):
    expect_error(world.ada.request(method, path), 404, "not_found")


def _asset_urls(base) -> list[str]:
    status, headers, body = get(base, "/", "text/html")
    text = body.decode()
    urls = set(re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", text))
    out = []
    for u in urls:
        if u.startswith("data:") or u.startswith("#"):
            continue
        full = urljoin(base + "/", u)
        assert urlsplit(full).netloc == urlsplit(base).netloc, f"I48: the shell references another origin: {u}"
        if urlsplit(full).path.startswith("/assets/"):
            out.append(urlsplit(full).path)
    assert out, "the shell references no /assets/ file"
    return sorted(out)


def test_assets_have_the_right_types_and_nosniff(world):
    base = world.svc.base_url
    seen = set()
    queue = _asset_urls(base)
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        r = httpx.get(base + path, timeout=5)
        assert r.status_code == 200, (path, r.status_code)
        ext = re.search(r"\.[a-z]+$", path)
        assert ext and ext.group(0) in CONTENT_TYPES, f"unexpected asset type {path}"
        ctype = r.headers["content-type"].split(";")[0].strip().lower()
        assert ctype == CONTENT_TYPES[ext.group(0)], (path, r.headers["content-type"])
        assert r.headers.get("x-content-type-options") == "nosniff", path
        if ctype == "text/javascript":     # follow static imports of ES modules
            for spec in re.findall(r"""(?:import|from)\s*["']([^"']+)["']""", r.text):
                full = urlsplit(urljoin(base + path, spec))
                assert full.netloc == urlsplit(base).netloc, f"I48: {path} imports another origin: {spec}"
                queue.append(full.path)
        if ctype == "text/css":
            for ref in re.findall(r"url\(\s*['\"]?([^'\")]+)", r.text):
                assert ref.startswith("data:") or urlsplit(urljoin(base + path, ref)).netloc == urlsplit(base).netloc, \
                    f"I48: {path} loads {ref}"
                assert "@import" not in r.text or "http" not in r.text
    assert any(p.endswith(".css") for p in seen) and any(p.endswith(".js") for p in seen), seen


@pytest.mark.parametrize("path", ["/assets/nope.js", "/assets/", "/assets/..%2Fpackage.json",
                                  "/assets/%2e%2e/Dockerfile", "/assets/../src/main.ts", "/assets/x/../../RUN.md"])
def test_unknown_assets_are_404(world, path):
    status, headers, body = raw_request(world.svc.base_url, "GET", path)
    assert status == 404, (path, status, body[:200])
    assert b"FROM node" not in body and b"docker" not in body.lower()


@pytest.mark.container
def test_pages_and_assets_load_in_a_container_with_no_network(request, world):
    """W9.1: the UI files are in the image; nothing is fetched at run time (D2, D39)."""
    from pathlib import Path
    stage_dir = request.config.getoption("--stage-dir")
    if not stage_dir:
        pytest.fail("--stage-dir is required for the container checks")
    prefix = request.config.getoption("--container-prefix")
    tag, name = f"{prefix}-offline", f"{prefix}-uinonet"
    build = subprocess.run(["docker", "build", "--network=none", "-q", "-t", tag, str(Path(stage_dir))],
                           capture_output=True, text=True, timeout=900)
    assert build.returncode == 0, build.stderr[-2000:]
    paths = ["/", "/login", "/signup", "/split"] + _asset_urls(world.svc.base_url)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    run = subprocess.run(["docker", "run", "-d", "--name", name, "--network=none", tag], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    try:
        probe = ("const ps=%s;(async()=>{for(const p of ps){try{const r=await fetch('http://127.0.0.1:8080'+p,"
                 "{headers:{accept:'text/html'}});console.log(r.status+' '+p)}catch(e){console.log('ERR '+p)}}})()"
                 % repr(paths).replace("'", '"'))
        deadline = time.monotonic() + 60
        out = ""
        while time.monotonic() < deadline:
            out = subprocess.run(["docker", "exec", name, "node", "-e", probe], capture_output=True, text=True).stdout
            if out.startswith("200 "):
                break
            time.sleep(0.5)
        lines = out.strip().splitlines()
        assert len(lines) == len(paths) and all(line.startswith("200 ") for line in lines), out
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.mark.container
def test_run_md_tells_a_stranger_how_to_build_run_and_test_stage_2(request):
    """W9.6 (plan 45fe2dc)."""
    from pathlib import Path
    stage_dir = request.config.getoption("--stage-dir")
    if not stage_dir:
        pytest.fail("--stage-dir is required for the container checks")
    text = (Path(stage_dir) / "RUN.md").read_text()
    for needle, why in [("docker build", "the build command"), ("docker run", "the run command"),
                        ("stage-2", "the stage-2 paths"), ("npm test", "the builder tests"),
                        ("acceptance", "the acceptance suite"), ("Playwright", "the browser prerequisite"),
                        ("stage-1", "the frozen stage-1 build the upgrade checks use"),
                        ("--stage 2", "the supplied checks"), ("/authorizations", "the UI routes"),
                        ("/split", "the UI routes"), ("/login", "the UI routes")]:
        assert needle in text, f"RUN.md does not mention {needle!r} ({why})"
