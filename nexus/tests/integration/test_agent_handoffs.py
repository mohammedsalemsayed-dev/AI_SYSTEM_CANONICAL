"""Acceptance (Integration): every inter-role hand-off is an AgentMessage on the
log (MILESTONE_E_PLAN.md §6)."""

from __future__ import annotations

from app.events.log import EventKind, EventLog
from tests.conftest import FIXED_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def test_handoff_chain_is_on_the_log(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    result = orch.run("fix add", sample_repo)
    assert result.state == "COMPLETED"

    msgs = [
        e.payload for e in log.read(result.task_id)
        if e.kind == EventKind.AGENT_MESSAGE
    ]
    senders = [m["sender"] for m in msgs]
    assert senders == ["interpreter", "planner", "builder", "verifier"]
    assert [m["intent"] for m in msgs] == ["HANDOFF", "HANDOFF", "HANDOFF", "STATUS"]
    # the interpreter hand-off carries the compiled objective
    assert any("objective:" in c for c in msgs[0]["claims"])
    # the planner hand-off carries the step intents
    assert msgs[1]["claims"]  # non-empty
    # the verifier reports the T0 outcome
    assert "T0 pass" in msgs[3]["claims"]
    log.close()
