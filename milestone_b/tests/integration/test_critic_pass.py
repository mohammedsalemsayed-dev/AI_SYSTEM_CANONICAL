"""Acceptance (Integration): the Critic pass rejects a bad diff, hands findings
back to the Builder, and the retry completes (MILESTONE_E_PLAN.md §6)."""

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
    assert EventKind.CRITIC in kinds
    assert EventKind.AGENT_MESSAGE in kinds
    log.close()


def test_critic_reject_triggers_a_builder_retry_that_passes(sample_repo: str) -> None:
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
        [json.dumps({
            "verdict": "reject",
            "summary": "does not make the test pass",
            "findings": [{"severity": "blocking", "claim": "add() still returns a * b"}],
        })],
    )
    result = orch.run("fix add", sample_repo)

    assert result.state == "COMPLETED"
    assert calls["n"] == 2  # first edit rejected, second edit after critic handoff
    crit = next(e.payload for e in log.read(result.task_id) if e.kind == EventKind.CRITIC)
    assert crit["verdict"] == "reject"
    handoff = [
        e.payload for e in log.read(result.task_id)
        if e.kind == EventKind.AGENT_MESSAGE and e.payload["intent"] == "HANDOFF"
    ]
    assert handoff and handoff[0]["requested_action"] == "revise"
    log.close()


def test_critic_reject_but_retry_still_bad_fails_verification(sample_repo: str) -> None:
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

    # one critic round only; the retry is still wrong -> T0 fails -> FAILED
    assert result.state == "FAILED"
    crits = [e for e in log.read(result.task_id) if e.kind == EventKind.CRITIC]
    assert len(crits) == 1  # critic_round bound respected
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
