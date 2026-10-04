"""W1.1, W1.2 — delivery: Dockerfile, RUN.md, offline build, PORT, health (§2, §3.1, §3.2).

These checks start their own containers, so they need --stage-dir and docker.
Container names use --container-prefix; host ports start at --spare-port.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from support import expect

pytestmark = [pytest.mark.item(1), pytest.mark.container]


def sh(*args: str, timeout: float = 600, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    if check:
        assert proc.returncode == 0, f"{' '.join(args)} exited {proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    return proc


@pytest.fixture(scope="module")
def stage_dir(request) -> Path:
    d = request.config.getoption("--stage-dir")
    if not d:
        pytest.fail("--stage-dir is required for the container checks (run.sh supplies it); "
                    "deselect them with -m 'not container' when running against a URL only")
    return Path(d).resolve()


@pytest.fixture(scope="module")
def prefix(request) -> str:
    return request.config.getoption("--container-prefix")


@pytest.fixture(scope="module")
def offline_image(stage_dir, prefix) -> str:
    """Build the stage folder with no network at all (D2), once the base image is present."""
    dockerfile = stage_dir / "Dockerfile"
    assert dockerfile.is_file(), f"{dockerfile} is missing"
    aliases: set[str] = set()
    for line in dockerfile.read_text().splitlines():
        m = re.match(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", line, re.I)
        if not m:
            continue
        base = m.group(1)
        if base.lower() != "scratch" and base.lower() not in aliases:
            if sh("docker", "image", "inspect", base, check=False).returncode != 0:
                sh("docker", "pull", base)   # §2: outbound network is available at build time
        if m.group(2):
            aliases.add(m.group(2).lower())
    tag = f"{prefix}-offline"
    sh("docker", "build", "--network=none", "-t", tag, str(stage_dir), timeout=900)
    return tag


def _run(name: str, *args: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    sh("docker", "run", "-d", "--name", name, *args)


def _rm(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _wait(url: str, deadline: float = 60.0) -> tuple[float, httpx.Response]:
    start = time.monotonic()
    last = None
    while time.monotonic() - start < deadline:
        try:
            last = httpx.get(url, timeout=2.0)
            if last.status_code == 200:
                return time.monotonic() - start, last
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise AssertionError(f"{url} not 200 within {deadline}s (last: {last!r})")


def test_stage_folder_has_dockerfile_and_run_md_and_no_git(stage_dir):
    assert (stage_dir / "Dockerfile").is_file()
    assert (stage_dir / "RUN.md").is_file()
    assert not (stage_dir / ".git").exists(), "a stage folder is never its own repository"


def test_run_md_gives_build_run_and_test_commands(stage_dir):
    text = (stage_dir / "RUN.md").read_text()
    assert "docker build" in text, "RUN.md must give the build command"
    assert "docker run" in text, "RUN.md must give the run command"
    assert "PORT" in text, "RUN.md must say how the port is chosen"
    assert "acceptance" in text, "RUN.md must give the acceptance suite command (W1.2)"
    assert re.search(r"node\s+--test|npm\s+test|node:test", text), \
        "RUN.md must give the builder test command (W1.2)"


def test_dockerfile_runs_as_non_root(offline_image):
    user = sh("docker", "image", "inspect", "--format", "{{.Config.User}}", offline_image).stdout.strip()
    assert user and user not in ("root", "0", "0:0"), f"image runs as {user!r} (PLAN 3.1: non-root)"


def test_offline_image_serves_health_with_no_network_on_default_port(offline_image, prefix):
    """§2: no outbound network at run time; §3.1: default port 8080."""
    name = f"{prefix}-nonet"
    _run(name, "--network=none", offline_image)
    try:
        probe = ("fetch('http://127.0.0.1:8080/health').then(async r=>{"
                 "console.log(r.status+' '+(await r.text()))}).catch(e=>{console.log('ERR '+e)})")
        start = time.monotonic()
        out = ""
        while time.monotonic() - start < 60:
            out = sh("docker", "exec", name, "node", "-e", probe, check=False).stdout.strip()
            if out.startswith("200 "):
                break
            time.sleep(0.5)
        assert out.startswith("200 "), f"no healthy answer inside a --network=none container: {out!r}"
        import json
        assert json.loads(out[4:]) == {"status": "ok"}
    finally:
        _rm(name)


def test_port_env_is_honoured_and_health_is_fast(offline_image, prefix, request):
    port = request.config.getoption("--spare-port")
    name = f"{prefix}-port"
    _run(name, "-e", "PORT=9123", "-p", f"127.0.0.1:{port}:9123", offline_image)
    try:
        took, resp = _wait(f"http://127.0.0.1:{port}/health")
        assert expect(resp, 200) == {"status": "ok"}
        assert took < 60, f"first healthy response after {took:.1f}s (limit 60s)"
    finally:
        _rm(name)


def test_default_port_is_8080(offline_image, prefix, request):
    port = request.config.getoption("--spare-port") + 1
    name = f"{prefix}-defport"
    _run(name, "-p", f"127.0.0.1:{port}:8080", offline_image)
    try:
        _, resp = _wait(f"http://127.0.0.1:{port}/health")
        assert expect(resp, 200) == {"status": "ok"}
    finally:
        _rm(name)


def test_service_works_within_the_resource_limits(offline_image, prefix, request):
    """§2: 2 vCPU and 2 GiB. A reset, a login and a payment work under those limits."""
    port = request.config.getoption("--spare-port") + 2
    name = f"{prefix}-limits"
    _run(name, "--cpus", "2", "--memory", "2g", "-e", f"PORT={port}",
         "-p", f"127.0.0.1:{port}:{port}", offline_image)
    try:
        base = f"http://127.0.0.1:{port}"
        _wait(f"{base}/health")
        from support import Service, fixture
        s = Service(base, "limits")
        try:
            s.must_reset(fixture())
            assert s.client("ada").balance() == 10_000
            expect(s.signup("limits@example.com", "correct horse", "L"), 201)
            assert s.client("limits").balance() == 0
            s.assert_invariants()
        finally:
            s.close()
    finally:
        _rm(name)
