"""Restart reconciliation (MILESTONE_D_PLAN.md §2, §6).

After an interruption, decide how to continue from the event log alone. The
user's workspace is never mutated (all work happens in temp copies), so RESUME
is safe whenever a contract and plan exist.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.core.state import State
from app.events.projections import project_task
from app.services.recovery.checkpoint import build_checkpoint

_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


class ReconcileDecision(BaseModel):
    decision: Literal["RESUME", "REPAIR", "ESCALATE", "NOOP"]
    from_state: str
    detail: str


def reconcile(events: list) -> ReconcileDecision:
    snap = project_task(events)
    state = snap.state.value

    if state in _TERMINAL:
        return ReconcileDecision(decision="NOOP", from_state=state, detail="already terminal")
    if snap.state is State.WAITING_FOR_USER:
        return ReconcileDecision(
            decision="NOOP", from_state=state, detail="awaiting user input"
        )

    cp = build_checkpoint(events)
    if cp.uncertain_external_actions:
        return ReconcileDecision(
            decision="ESCALATE",
            from_state=state,
            detail=f"{len(cp.uncertain_external_actions)} uncertain external action(s)",
        )
    if snap.contract is None:
        return ReconcileDecision(
            decision="REPAIR", from_state=state, detail="interrupted before a contract"
        )
    if snap.plan is None:
        return ReconcileDecision(
            decision="REPAIR", from_state=state, detail="interrupted before a plan"
        )
    return ReconcileDecision(
        decision="RESUME",
        from_state=state,
        detail=f"contract + plan present, {cp.step_index} step(s) done; workspace untouched",
    )
