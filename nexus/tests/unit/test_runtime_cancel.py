"""Cooperative cancellation: the Stop flag, the LLM/Builder proxies that honour
it, and the /api/cancel route on the desktop server."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app import runtime_cancel
from app.runtime_cancel import RunCancelled
from app.ui.runner import _CancelBuilder, _CancelLLM, request_cancel


@pytest.fixture(autouse=True)
def _reset():
    runtime_cancel.arm()
    yield
    runtime_cancel.arm()


class _LLM:
    def __init__(self):
        self.calls = 0

    def complete(self, *, system, prompt):
        self.calls += 1
        return "ok"


class _Builder:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def execute(self, **kw):
        self.calls += 1
        return "built"


def test_check_is_a_noop_until_requested():
    runtime_cancel.check()  # armed / not requested -> no raise
    runtime_cancel.request()
    with pytest.raises(RunCancelled):
        runtime_cancel.check()
    runtime_cancel.arm()
    runtime_cancel.check()  # arm() clears it again


def test_cancel_llm_proxy_blocks_the_next_call():
    inner = _LLM()
    llm = _CancelLLM(inner)
    assert llm.complete(system="s", prompt="p") == "ok"
    assert inner.calls == 1
    runtime_cancel.request()
    with pytest.raises(RunCancelled):
        llm.complete(system="s", prompt="p")
    assert inner.calls == 1  # inner was never reached


def test_cancel_builder_proxy_blocks_execute_and_passes_attrs():
    inner = _Builder()
    b = _CancelBuilder(inner)
    assert b.name == "fake"
    assert b.execute(task_id="t") == "built"
    runtime_cancel.request()
    with pytest.raises(RunCancelled):
        b.execute(task_id="t")
    assert inner.calls == 1


def test_local_builder_loop_aborts_on_cancel(tmp_path: Path):
    from app.schemas.contracts import PlanStep, TaskContract
    from app.services.build.local_builder import LocalBuilder

    runtime_cancel.request()
    b = LocalBuilder(model="qwen3:8b")
    step = PlanStep(intent="x", expected_artifact_delta="y", required_capability="fs.write")
    c = TaskContract(
        task_id="t", original_request="fix", objective="fix",
        task_class="code_edit_local", success_criteria=["ok"],
        required_evidence=["T0: pytest test_x.py passes"],
    )
    with pytest.raises(RunCancelled):
        b.execute(task_id="t", step=step, contract=c, workspace=str(tmp_path))


def test_request_cancel_is_a_noop_when_nothing_is_running():
    assert request_cancel() == {"cancelling": False, "running": False}
    assert not runtime_cancel.is_set()


def test_api_cancel_route(tmp_path: Path):
    from app.events.log import EventLog
    from app.ui.server import UIServer

    EventLog(str(tmp_path / "ev.db")).close()

    def fake_runner(*a, **k):
        return {"accepted": True}

    srv = UIServer(("127.0.0.1", 0), db_path=str(tmp_path / "ev.db"), runner=fake_runner)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        req = urllib.request.Request(base + "/api/cancel", data=b"{}",
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
            assert json.loads(r.read()) == {"cancelling": False, "running": False}
    finally:
        srv.shutdown()
