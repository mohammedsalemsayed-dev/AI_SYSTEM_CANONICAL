"""Acceptance (Unit): the sandboxed shell tool adapter (MILESTONE_T_PLAN.md §6)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.schemas.contracts import CapabilityGrant
from app.services.capability.registry import spec_for
from app.services.policy.engine import PolicyEngine
from app.services.sandbox.runner import SandboxResult, SandboxSpec
from app.services.tools.adapters.shell_tool import ShellToolAdapter
from app.services.tools.base import DispatchContext
from app.services.tools.dispatch import ToolDispatcher
from app.services.tools.registry import ToolRegistry


def _grant(token: str, root: str) -> CapabilityGrant:
    return CapabilityGrant(task_id="t", step_id="s", token=token, scope_path=root,
                           operations=sorted(spec_for(token).operations))


@pytest.fixture
def disp(tmp_path: Path) -> ToolDispatcher:
    reg = ToolRegistry().register(ShellToolAdapter())
    return ToolDispatcher(reg, PolicyEngine())


def test_granted_exec_runs_and_is_tool_output_trust(disp: ToolDispatcher, tmp_path: Path) -> None:
    ctx = DispatchContext(task_id="t", grant=_grant("shell.run", str(tmp_path)),
                          workspace=str(tmp_path))
    res, dec = disp.run("shell.exec", {"command": [sys.executable, "-c", "print('hi')"]}, ctx)
    assert dec.decision == "ALLOW"
    assert res.ok and res.trust == "tool_output"
    assert res.output["exit_code"] == 0 and "hi" in res.output["stdout"]


def test_missing_grant_is_a_policy_denial_not_an_exception(disp: ToolDispatcher, tmp_path: Path) -> None:
    ctx = DispatchContext(task_id="t", grant=_grant("fs.read", str(tmp_path)),
                          workspace=str(tmp_path))
    res, dec = disp.run("shell.exec", {"command": [sys.executable, "-c", "print(1)"]}, ctx)
    assert not res.ok and dec.decision == "DENY"


def test_bad_args_are_a_result_not_a_raise(disp: ToolDispatcher, tmp_path: Path) -> None:
    ctx = DispatchContext(task_id="t", grant=_grant("shell.run", str(tmp_path)),
                          workspace=str(tmp_path))
    assert not disp.run("shell.exec", {"command": "echo hi"}, ctx)[0].ok
    assert not disp.run("shell.exec", {"command": []}, ctx)[0].ok
    assert not disp.run("shell.exec", {}, ctx)[0].ok


def test_nonzero_and_timeout_map_to_not_ok(tmp_path: Path) -> None:
    class _FakeRunner:
        name = "fake"
        isolation = "none"

        def __init__(self, result: SandboxResult) -> None:
            self._r = result
            self.seen: SandboxSpec | None = None

        def available(self) -> bool:
            return True

        def run(self, spec: SandboxSpec) -> SandboxResult:
            self.seen = spec
            return self._r

    runner = _FakeRunner(SandboxResult(exit_code=2, stderr="boom", backend="fake"))
    reg = ToolRegistry().register(ShellToolAdapter(runner))
    d = ToolDispatcher(reg, PolicyEngine())
    ctx = DispatchContext(task_id="t", grant=_grant("shell.run", str(tmp_path)),
                          workspace=str(tmp_path))
    res = d.run("shell.exec", {"command": ["x"], "timeout_s": 999}, ctx)[0]
    assert not res.ok and res.output["exit_code"] == 2
    assert runner.seen.timeout_s == 120  # clamped
    assert runner.seen.workdir == str(tmp_path)

    runner2 = _FakeRunner(SandboxResult(exit_code=124, timed_out=True, backend="fake",
                                        error="timed out after 120s"))
    d2 = ToolDispatcher(ToolRegistry().register(ShellToolAdapter(runner2)), PolicyEngine())
    res2 = d2.run("shell.exec", {"command": ["x"]}, ctx)[0]
    assert not res2.ok and res2.output["timed_out"] is True
