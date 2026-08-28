"""Acceptance (Integration): the Critic pass runs after T0 and is positioned so
it can never false-reject a T0-passing diff (MILESTONE_E_PLAN.md §6; research:
over-rejection is the real risk)."""

from __future__ import annotations

import json
from pathlib import Path

from app.events.log import EventKind, EventLog
from app.llm.fake import ScriptedLLM
from app.services.agents.critic import Critic
from tests.conftest import FIXED_CALC, WRONG_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def _orch_with_critic(log, llm_replies, builder_edits, critic_replies):
    orch = build_orchestrator(log, llm_replies=llm_replies, builder_edits=builder_edits)
    orch.critic = Critic(ScriptedLLM(critic_replies))
    return orch


def test_critic_accept_lets_the_task_complete(sample_repo: str) -> None:
    log = EventLog()
    orch = _orch_with_critic(
        log,
        [interpreter_reply(), planner_reply()],
        {"calc.py": FIXED_CALC},
        [json.dumps({"verdict": "accept", "findings": []})],
    )
    result = orch.run("fix add", sample_repo)

    assert result.state == "COMPLETED"
    kinds = [e.kind for e in log.read(result.task_id)]
    assert EventKind.CRITIC in kinds and EventKind.AGENT_MESSAGE in kinds
    log.close()


def test_critic_reject_of_a_T0_passing_diff_is_logged_not_retried(sample_repo: str) -> None:
    calls = {"n": 0}

    def edits(ws: str) -> None:
        calls["n"] += 1
        (Path(ws) / "calc.py").write_text(FIXED_CALC, newline="\n")  # always correct

    log = EventLog()
    orch = _orch_with_critic(
        log,
        [interpreter_reply(), planner_reply()],
        edits,
        [json.dumps({"verdict": "reject", "summary": "I'd do it differently",
                     "findings": [{"claim": "style nit"}]})],
    )
    result = orch.run("fix add", sample_repo)

    # T0 passed, so the task completes despite the critic; the disagreement is on the log
    assert result.state == "COMPLETED"
    assert calls["n"] == 1  # NO retry of a correct diff
    kinds = [e.kind for e in log.read(result.task_id)]
    assert EventKind.DISAGREEMENT in kinds
    log.close()


def test_critic_findings_feed_a_retry_when_T0_fails(sample_repo: str) -> None:
    calls = {"n": 0}

    def edits(ws: str) -> None:
        calls["n"] += 1
        content = WRONG_CALC if calls["n"] == 1 else FIXED_CALC
        (Path(ws) / "calc.py").write_text(content, newline="\n")

    log = EventLog()
    orch = _orch_with_critic(
        log,
        [interpreter_reply(), planner_reply()],
        edits,
        [json.dumps({"verdict": "reject",
                     "findings": [{"severity": "blocking", "claim": "add() still returns a * b"}]})],
    )
    result = orch.run("fix add", sample_repo)

    assert result.state == "COMPLETED"
    assert calls["n"] == 2  # T0 failed, critic findings drove one retry that passed
    handoff = [
        e.payload for e in log.read(result.task_id)
        if e.kind == EventKind.AGENT_MESSAGE and e.payload["intent"] == "HANDOFF"
    ]
    assert handoff and handoff[0]["requested_action"] == "revise"
    log.close()


def test_one_critic_retry_only(sample_repo: str) -> None:
    def always_wrong(ws: str) -> None:
        (Path(ws) / "calc.py").write_text(WRONG_CALC, newline="\n")

    log = EventLog()
    orch = _orch_with_critic(
        log,
        [interpreter_reply(), planner_reply()],
        always_wrong,
        [json.dumps({"verdict": "reject", "findings": [{"claim": "wrong"}]})],
    )
    result = orch.run("fix add", sample_repo)

    assert result.state == "FAILED"
    crits = [e for e in log.read(result.task_id) if e.kind == EventKind.CRITIC]
    assert len(crits) == 2  # one per verify round; retry bounded at critic_round=1
    log.close()


def test_no_critic_is_the_default_single_agent_path(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    assert orch.critic is None
    result = orch.run("fix add", sample_repo)
    assert result.state == "COMPLETED"
    assert EventKind.CRITIC not in [e.kind for e in log.read(result.task_id)]
    log.close()
