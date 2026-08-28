"""Fault suite: LLM failures (refusal / timeout / garbage) at interpret + plan
lead to a safe terminal (MILESTONE_Q_PLAN.md §6)."""

from __future__ import annotations

import pytest

from app.events.log import EventLog
from app.llm.fake import ScriptedLLM
from app.services.faults.model import Fault, FaultPlan
from app.services.faults.wrappers import FlakyLLM
from tests.conftest import FIXED_CALC
from tests.fault.conftest import assert_safe, scripted_orchestrator, workspace_hash
from tests.integration.conftest import interpreter_reply, planner_reply


@pytest.mark.parametrize("kind", ["llm_refusal", "llm_timeout", "llm_garbage"])
@pytest.mark.parametrize("on_call", [1, 2])  # 1 = interpret, 2 = plan
def test_llm_fault_at_interpret_or_plan(sample_repo: str, kind: str, on_call: int) -> None:
    before = workspace_hash(sample_repo)
    log = EventLog()
    inner = ScriptedLLM([interpreter_reply(), planner_reply()])
    llm = FlakyLLM(inner, FaultPlan.of(Fault(kind, on_call=on_call)))
    orch = scripted_orchestrator(
        log, llm_replies=[], builder_edits={"calc.py": FIXED_CALC}, llm=llm,
    )
    result = orch.run("fix the add function", sample_repo)
    assert_safe(result, log, before, sample_repo)
    assert result.state != "COMPLETED" or result.verified
    log.close()
