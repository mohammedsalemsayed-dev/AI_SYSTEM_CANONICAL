"""Acceptance (Integration): the `nexus-server` sidecar entrypoint serves the
shell and gates task submission (MILESTONE_H_TAURI_PLAN.md §6)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


def _wait(url: str, tries: int = 60) -> bool:
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.25)
    return False


@pytest.fixture
def sidecar(tmp_path: Path):
    env = dict(os.environ)
    env.pop("NEXUS_ALLOW_SUBMIT", None)
    db = str(tmp_path / "events.db")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.ui.sidecar_main", "--db", db, "--port", "8791"],
        cwd=_REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    ok = _wait("http://127.0.0.1:8791/api/health")
    if not ok:
        proc.kill()
        pytest.fail("sidecar did not come up: " + (proc.stdout.read() if proc.stdout else ""))
    yield "http://127.0.0.1:8791", db
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_sidecar_serves_health_and_frontend(sidecar) -> None:
    base, _db = sidecar
    with urllib.request.urlopen(base + "/api/health", timeout=3) as r:
        assert json.loads(r.read())["status"] == "ok"
    with urllib.request.urlopen(base + "/", timeout=3) as r:
        assert r.headers["Content-Type"] == "text/html"
        assert b"/app.js" in r.read()
    with urllib.request.urlopen(base + "/api/tasks", timeout=3) as r:
        assert "tasks" in json.loads(r.read())


def test_sidecar_submit_is_off_by_default(sidecar) -> None:
    base, _db = sidecar
    body = json.dumps({"request": "x", "workspace": "/ws"}).encode()
    req = urllib.request.Request(base + "/api/tasks", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=3)
    assert ei.value.code == 405


def test_build_script_reports_missing_toolchain() -> None:
    # run with a stripped PATH so a prerequisite (cargo/npm) is *definitely*
    # missing regardless of the host — build.py must fail cleanly, not crash or
    # start an actual build.
    minimal = os.pathsep.join(
        p for p in (str(Path(sys.executable).parent),
                    r"C:\Windows\System32", r"C:\Windows", "/usr/bin", "/bin")
        if Path(p).exists()
    )
    r = subprocess.run(
        [sys.executable, str(_REPO / "desktop" / "build.py")],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "PATH": minimal},
    )
    assert r.returncode == 2, (r.stdout + r.stderr)[:800]
    assert "missing prerequisite" in r.stderr
