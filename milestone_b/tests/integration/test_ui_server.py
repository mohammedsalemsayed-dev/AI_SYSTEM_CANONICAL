"""Acceptance (Integration): the desktop-shell server serves the read models over
a real socket, streams events as SSE, and gates task submission
(MILESTONE_H_PLAN.md §6)."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app.events.log import EventKind, EventLog
from app.schemas.contracts import TaskContract, TaskResult
from app.ui.server import UIServer


def _urlopen(req, *, timeout: float = 5, tries: int = 4):
    """urlopen that retries a *connection-level* failure — a freshly started
    background http.server can drop the first connection or two under load. An
    HTTPError (the server actually replied) is raised immediately, never retried."""
    last: Exception | None = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except (ConnectionError, OSError) as exc:  # ConnectionAbortedError, reset, refused
            last = exc
            time.sleep(0.15 * (i + 1))
    raise last  # type: ignore[misc]


def _seed(db: str) -> None:
    log = EventLog(db)
    c = TaskContract(
        task_id="t1", original_request="fix add", objective="make add return a + b",
        task_class="code_edit_local", success_criteria=["x"],
        required_evidence=["T0: pytest test_calc.py::test_add passes"],
    )
    log.append("t1", EventKind.REQUEST, {"text": "fix add", "workspace_path": "/ws"})
    log.append("t1", EventKind.STATE, {"state": "INTERPRETING"})
    log.append("t1", EventKind.CONTRACT, c.model_dump(mode="json"))
    log.append("t1", EventKind.STATE, {"state": "COMPLETED"})
    log.append("t1", EventKind.RESULT, TaskResult(
        task_id="t1", state="COMPLETED", verified=True, summary="done",
    ).model_dump(mode="json"))
    log.close()


@pytest.fixture
def server(tmp_path: Path):
    db = str(tmp_path / "ev.db")
    _seed(db)
    srv = UIServer(("127.0.0.1", 0), db_path=db)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base, db, srv
    srv.shutdown()


def _get(url: str):
    with _urlopen(url) as r:
        return r.status, json.loads(r.read())


def test_get_routes_return_expected_shapes(server) -> None:
    base, _db, _srv = server
    assert _get(base + "/api/health")[1]["status"] == "ok"

    st, tasks = _get(base + "/api/tasks")
    assert st == 200 and tasks["tasks"][0]["task_id"] == "t1"

    st, tl = _get(base + "/api/tasks/t1")
    assert st == 200 and tl["state"] == "COMPLETED" and tl["events"]

    st, agents = _get(base + "/api/tasks/t1/agents")
    assert st == 200 and {r["role"] for r in agents["roles"]} >= {"planner", "builder"}

    assert _get(base + "/api/system")[1]["hardware_mode"] == "NORMAL"
    assert _get(base + "/api/metrics")[1]["tasks"] == 1
    assert "by_class" in _get(base + "/api/routes")[1]


def test_unknown_task_and_route_are_404(server) -> None:
    base, _db, _srv = server
    for path in ("/api/tasks/nope", "/api/tasks/nope/agents", "/api/bogus"):
        with pytest.raises(urllib.error.HTTPError) as ei:
            _urlopen(base + path)
        assert ei.value.code == 404


def test_static_index_and_assets_served(server) -> None:
    base, _db, _srv = server
    with _urlopen(base + "/") as r:
        html = r.read().decode()
    assert r.headers["Content-Type"] == "text/html"
    assert "/app.js" in html and "/style.css" in html
    with _urlopen(base + "/app.js") as r:
        js = r.read().decode()
    assert "EventSource" in js and "/api/stream" in js


def test_sse_stream_delivers_new_events(server) -> None:
    base, db, _srv = server
    req = urllib.request.Request(base + "/api/stream")
    stream = _urlopen(req)

    # a writer on the same DB file appends after the stream is open
    def write_later():
        time.sleep(0.4)
        log = EventLog(db)
        log.append("t2", EventKind.STATE, {"state": "PLANNING"})
        log.append("t2", EventKind.HARDWARE, {"mode": "EFFICIENT"})
        log.close()

    threading.Thread(target=write_later, daemon=True).start()

    seen = []
    deadline = time.time() + 6
    while time.time() < deadline and len(seen) < 2:
        line = stream.readline().decode()
        if line.startswith("event: "):
            seen.append(line.strip().split(" ", 1)[1])
    stream.close()
    assert "STATE" in seen and "HARDWARE" in seen


def test_submit_disabled_by_default_then_enabled(tmp_path: Path) -> None:
    db = str(tmp_path / "ev.db")
    _seed(db)

    ro = UIServer(("127.0.0.1", 0), db_path=db)
    threading.Thread(target=ro.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{ro.server_address[1]}"
    body = json.dumps({"request": "do x", "workspace": "/ws"}).encode()
    req = urllib.request.Request(base + "/api/tasks", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as ei:
        _urlopen(req)
    assert ei.value.code == 405
    ro.shutdown()

    calls = []

    def fake_runner(request: str, workspace: str):
        calls.append((request, workspace))
        return TaskResult(task_id="tX", state="COMPLETED", verified=True, summary="ok")

    rw = UIServer(("127.0.0.1", 0), db_path=db, runner=fake_runner)
    threading.Thread(target=rw.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{rw.server_address[1]}"
    req = urllib.request.Request(base + "/api/tasks", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with _urlopen(req) as r:
        assert r.status == 201
        assert json.loads(r.read())["submitted"]["state"] == "COMPLETED"
    assert calls == [("do x", "/ws")]
    rw.shutdown()
