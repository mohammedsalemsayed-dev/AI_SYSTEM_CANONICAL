"""Acceptance (Unit): AgentMessage schema + the eight intents
(MILESTONE_E_PLAN.md §7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.events.log import EventKind, EventLog
from app.schemas.contracts import AgentMessage
from app.services.agents.messages import emit_message

_INTENTS = {
    "QUESTION", "ANSWER", "PROPOSAL", "HANDOFF",
    "EVIDENCE", "CRITIQUE", "STATUS", "ESCALATION",
}


def test_all_eight_intents_accepted() -> None:
    for intent in _INTENTS:
        m = AgentMessage(sender="x", role="x", task_id="t", intent=intent)
        assert m.intent == intent
        assert m.id.startswith("msg_")


def test_unknown_intent_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentMessage(sender="x", role="x", task_id="t", intent="GOSSIP")


def test_emit_message_appends_agent_message_event() -> None:
    log = EventLog()
    msg = emit_message(
        log, "t",
        sender="critic", role="critic", intent="CRITIQUE",
        claims=["diff misses the boundary case"],
        confidence_summary="verdict=reject",
    )
    events = log.read("t")
    assert len(events) == 1
    assert events[0].kind == EventKind.AGENT_MESSAGE
    assert events[0].payload["intent"] == "CRITIQUE"
    assert events[0].payload["id"] == msg.id
    log.close()


def test_defaults_are_empty_lists() -> None:
    m = AgentMessage(sender="s", role="r", task_id="t", intent="STATUS")
    assert m.claims == [] and m.evidence_refs == [] and m.assumptions == []
    assert m.requested_action is None
