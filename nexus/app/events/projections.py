"""Fold the event stream for one task into a `TaskSnapshot`.

The snapshot is the derived view the orchestrator and the state-machine gate
predicates read. It is always rebuildable from the event log; it holds no
authority of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.state import State
from app.events.log import Event, EventKind
from app.schemas.contracts import (
    Observation,
    Plan,
    TaskContract,
    VerificationRecord,
    validate_contract,
)


@dataclass
class TaskSnapshot:
    task_id: str
    state: State = State.CREATED
    request_text: str | None = None
    workspace_path: str | None = None
    contract: TaskContract | None = None
    plan: Plan | None = None
    observations: list[Observation] = field(default_factory=list)
    verification: VerificationRecord | None = None
    result: dict[str, Any] | None = None
    last_error: str | None = None
    pending_approval: str | None = None  # action_id awaiting an approval decision
    approved_steps: set[str] = field(default_factory=set)
    open_clarification: bool = False  # a CLARIFICATION is awaiting a user answer
    capability_grants: list[dict[str, Any]] = field(default_factory=list)
    policy_decisions: list[dict[str, Any]] = field(default_factory=list)
    taint_blocks: list[dict[str, Any]] = field(default_factory=list)
    advisory_verifications: list[VerificationRecord] = field(default_factory=list)

    @property
    def contract_problems(self) -> list[str]:
        if self.contract is None:
            return ["no contract"]
        return validate_contract(self.contract)


def project_task(events: list[Event]) -> TaskSnapshot:
    if not events:
        raise ValueError("cannot project a task from an empty event list")

    snap = TaskSnapshot(task_id=events[0].task_id)
    for event in events:
        payload = event.payload
        kind = event.kind

        if kind == EventKind.REQUEST:
            snap.request_text = payload.get("text")
            snap.workspace_path = payload.get("workspace_path")
        elif kind == EventKind.STATE:
            snap.state = State(payload["state"])
            if snap.state in (State.INTERPRETING, State.EXECUTING):
                snap.open_clarification = False  # resuming clears the question
        elif kind == EventKind.CLARIFICATION:
            snap.open_clarification = True
        elif kind == EventKind.CONTRACT:
            snap.contract = TaskContract.model_validate(payload)
        elif kind == EventKind.PLAN:
            snap.plan = Plan.model_validate(payload)
        elif kind == EventKind.OBSERVATION:
            snap.observations.append(Observation.model_validate(payload))
        elif kind == EventKind.VERIFICATION:
            record = VerificationRecord.model_validate(payload)
            if record.tier == "T0":
                snap.verification = record  # the authoritative one — gates COMPLETED
            else:
                snap.advisory_verifications.append(record)  # T1–T3 ensemble, advisory
        elif kind == EventKind.RESULT:
            snap.result = payload
        elif kind == EventKind.ERROR:
            snap.last_error = payload.get("error")
        elif kind == EventKind.APPROVAL_REQUEST:
            snap.pending_approval = payload.get("action_id")
        elif kind == EventKind.APPROVAL_DECISION:
            snap.pending_approval = None
            if payload.get("approved") and payload.get("step_id"):
                snap.approved_steps.add(payload["step_id"])
        elif kind == EventKind.CAPABILITY_GRANT:
            snap.capability_grants.append(payload)
        elif kind == EventKind.POLICY_DECISION:
            snap.policy_decisions.append(payload)
        elif kind == EventKind.TAINT_BLOCKED:
            snap.taint_blocks.append(payload)
        # ACTION_PROPOSAL, POLICY_DECISION, ARTIFACT, MODEL_RUN, CLARIFICATION:
        # recorded in the log for audit; not needed in the snapshot for the slice.

    return snap
