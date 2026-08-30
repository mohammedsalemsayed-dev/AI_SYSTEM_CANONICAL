"""Fault suite: sandbox failures during T0 verification lead to a safe terminal
with the workspace untouched (MILESTONE_Q_PLAN.md §6)."""

from __future__ import annotations

import pytest

from app.events.log import EventLog
from app.services.faults.model import Fault, FaultPlan
from app.services.faults.wrappers import FlakyRunner
from app.services.sandbox.subprocess_backend import SubprocessSandbox
from tests.conftest import FIXED_CALC
from tests.fault.conftest import assert_safe, scripted_orchestrator, workspace_hash
from tests.integration.conftest import interpreter_reply, planner_reply


@pytest.mark.parametrize(
    "kind", ["sandbox_unavailable", "sandbox_timeout", "sandbox_error", "sandbox_crash"]
)
def test_sandbox_fault_during_verify(sample_repo: str, kind: str) -> None:
    before = workspace_hash(sample_repo)
    log = EventLog()
    runner = FlakyRunner(SubprocessSandbox(), FaultPlan.of(Fault(kind, on_call=1, sticky=True)))
    orch = scripted_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
        sandbox=runner,
    )
    result = orch.run("fix the add function", sample_repo)

    assert_safe(result, log, before, sample_repo)
    # a sandbox that never works -> the task cannot be verified -> not COMPLETED
    assert result.state != "COMPLETED"
    log.close()
