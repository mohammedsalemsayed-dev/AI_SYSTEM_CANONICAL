"""AgentSDKBuilder: the SDK's `cwd=` option does not set the agent's working
directory (observed on claude_agent_sdk 0.2.145 — the agent wrote to a stale
baked-in path and nothing landed in the workspace). The builder must chdir the
process into the workspace for the call and restore it afterwards, and it must
run headless (bypassPermissions) with write access to the workspace."""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.schemas.contracts import PlanStep, TaskContract


def _fake_sdk(monkeypatch, on_run):
    """Install a fake `claude_agent_sdk` module. `on_run(cwd, options)` is called
    with the process cwd seen inside the async loop and the ClaudeAgentOptions."""
    mod = types.ModuleType("claude_agent_sdk")

    class ClaudeAgentOptions:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    async def query(*, prompt, options):  # noqa: ARG001
        on_run(os.getcwd(), options)
        if False:
            yield None  # make it an async generator

    mod.ClaudeAgentOptions = ClaudeAgentOptions
    mod.query = query
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", mod)


_C = TaskContract(
    task_id="t", original_request="fix", objective="fix calc()",
    task_class="code_edit_local", success_criteria=["ok"],
    required_evidence=["T0: pytest test_calc.py::test_x passes"],
)
_STEP = PlanStep(intent="fix it", expected_artifact_delta="edit", required_capability="fs.write")


def test_chdirs_into_workspace_and_restores(tmp_path: Path, monkeypatch):
    from app.services.build.agent_sdk import AgentSDKBuilder

    ws = tmp_path / "ws"
    ws.mkdir()
    subprocess.run(["git", "-C", str(ws), "init", "-q"], check=True)
    (ws / "calc.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(ws), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(ws), "-c", "user.email=a@a", "-c", "user.name=a",
                    "commit", "-qm", "b"], check=True)

    seen = {}
    _fake_sdk(monkeypatch, lambda cwd, opts: seen.update(cwd=cwd, opts=opts))
    before = os.getcwd()

    out = AgentSDKBuilder().execute(task_id="t", step=_STEP, contract=_C, workspace=str(ws))

    assert out is not None
    assert os.getcwd() == before                                  # restored
    assert os.path.realpath(seen["cwd"]) == os.path.realpath(str(ws))  # ran in the workspace
    assert seen["opts"].permission_mode == "bypassPermissions"
    assert str(ws) in [str(d) for d in seen["opts"].add_dirs]


def test_restores_cwd_even_when_the_sdk_raises(tmp_path: Path, monkeypatch):
    from app.services.build.agent_sdk import AgentSDKBuilder

    ws = tmp_path / "ws2"
    ws.mkdir()

    def boom(cwd, opts):  # noqa: ARG001
        raise RuntimeError("sdk kaboom")

    _fake_sdk(monkeypatch, boom)
    before = os.getcwd()
    out = AgentSDKBuilder().execute(task_id="t", step=_STEP, contract=_C, workspace=str(ws))
    assert os.getcwd() == before
    assert out.exit_code == 1 and "agent sdk error" in (out.error or "")
