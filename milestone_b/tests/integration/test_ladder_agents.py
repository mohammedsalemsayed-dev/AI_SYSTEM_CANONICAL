"""Acceptance (Integration): the D escalation ladder's `critic` and `research`
rungs are real when the agents are wired (MILESTONE_E_PLAN.md §6)."""

from __future__ import annotations

import json
from pathlib import Path

from app.events.log import EventKind, EventLog
from app.llm.fake import ScriptedLLM
from app.services.agents.critic import Critic
from app.services.agents.researcher import Researcher
from app.services.egress.broker import EgressBroker
from tests.integration.conftest import build_orchestrator, interpreter_reply
from tests.integration.test_progress_and_ladder import _plan, two_file_repo  # noqa: F401


def test_ladder_research_rung_logs_evidence(two_file_repo: str) -> None:
    def noop(ws: str) -> None:
        (Path(ws) / "mod_a.py").write_text("def a():\n    return 1\n", newline="\n")

    steps = _plan(*["retry"] * 4)
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[
            interpreter_reply(
                objective="make a()+b() == 22",
                required_evidence=["T0: pytest test_both.py::test_sum passes"],
            ),
            steps, steps, steps,
        ],
        builder_edits=noop,
    )
    orch.critic = Critic(ScriptedLLM([json.dumps({"verdict": "accept", "findings": []})] * 4))
    calls: list[str] = []

    def opener(url, timeout):
        calls.append(url)
        return b"Return a() + b(); the sum must be 22."

    orch.researcher = Researcher(
        ScriptedLLM([
            json.dumps({"urls": ["https://docs.example/x"]}),
            json.dumps({"claims": [{"text": "the two functions must sum to 22", "supported": True}]}),
        ] * 3),
        EgressBroker(allowlist=["docs.example"], opener=opener),
    )
    result = orch.run("fix the sum", two_file_repo)

    kinds = [e.kind for e in log.read(result.task_id)]
    rungs = [e.payload["rung"] for e in log.read(result.task_id) if e.kind == EventKind.ESCALATION]
    # the ladder reached the research rung and it did real work
    assert "research" in rungs
    assert EventKind.EVIDENCE in kinds
    assert calls  # the broker was actually hit
    ev_msgs = [
        e.payload for e in log.read(result.task_id)
        if e.kind == EventKind.AGENT_MESSAGE and e.payload["intent"] == "EVIDENCE"
    ]
    assert ev_msgs and ev_msgs[0]["sender"] == "researcher"
    log.close()


def test_composition_event_lists_active_roles(two_file_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(objective="x",
                                       required_evidence=["T0: pytest test_both.py::test_sum passes"]),
                     _plan("one")],
        builder_edits=lambda ws: (Path(ws) / "mod_a.py").write_text("def a():\n    return 2\n", newline="\n"),
    )
    orch.critic = Critic(ScriptedLLM([json.dumps({"verdict": "accept", "findings": []})]))
    orch.run("fix", two_file_repo)

    comp = next(e.payload for e in log.read(log.task_ids()[0]) if e.kind == EventKind.COMPOSITION)
    assert "builder" in comp["active_roles"] and "critic" in comp["active_roles"]
    log.close()
