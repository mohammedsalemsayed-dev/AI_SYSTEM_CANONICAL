"""Structured inter-role messaging (MILESTONE_E_PLAN.md §2, D9).

Every hand-off between roles is an `AgentMessage` appended to the log as an
`AGENT_MESSAGE` event. Agents never hold references to each other — the
Orchestrator emits these on their behalf.
"""

from __future__ import annotations

from app.events.log import EventKind, EventLog
from app.schemas.contracts import AgentMessage


def emit_message(
    log: EventLog,
    task_id: str,
    *,
    sender: str,
    role: str,
    intent: str,
    claims: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    assumptions: list[str] | None = None,
    requested_action: str | None = None,
    confidence_summary: str | None = None,
) -> AgentMessage:
    msg = AgentMessage(
        sender=sender,
        role=role,
        task_id=task_id,
        intent=intent,
        claims=claims or [],
        evidence_refs=evidence_refs or [],
        assumptions=assumptions or [],
        requested_action=requested_action,
        confidence_summary=confidence_summary,
    )
    log.append(task_id, EventKind.AGENT_MESSAGE, msg.model_dump(mode="json"))
    return msg
