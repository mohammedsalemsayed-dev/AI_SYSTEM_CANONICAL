"""Fault suite: builder failures (partial diff / empty diff / exception) lead to a
safe terminal with the workspace untouched (MILESTONE_Q_PLAN.md §6)."""

from __future__ import annotations

import pytest

from app.events.log import EventLog
from app.services.build.fake import ScriptedBuilder
from app.services.faults.model import Fault, FaultPlan
from app.services.faults.wrappers import FlakyBuilder
from tests.conftest import FIXED_CALC
from tests.fault.conftest import assert_safe, scripted_orchestrator, workspace_hash
from tests.integration.conftest import interpreter_reply, planner_reply


@pytest.mark.parametrize("kind", ["partial_diff", "empty_diff", "builder_exception"])
def test_builder_fault(sample_repo: str, kind: str) -> None:
    before = workspace_hash(sample_repo)
    log = EventLog()
    inner = ScriptedBuilder({"calc.py": FIXED_CALC})
    builder = FlakyBuilder(inner, FaultPlan.of(Fault(kind, on_call=1, sticky=True)))
    orch = scripted_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={},
        builder=builder,
    )
    result = orch.run("fix the add function", sample_repo)

    assert_safe(result, log, before, sample_repo)
    # none of these produce a real fix -> never a verified COMPLETED
    assert result.state != "COMPLETED"
    log.close()
