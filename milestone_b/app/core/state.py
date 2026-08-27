"""Canonical task state machine + the transition gate predicates.

`ALLOWED` is ported verbatim from the prior foundation. `gate_reason` adds the
"gate to leave the state" column from DESIGN_TIGHTENING.md section 1: a transition
is valid only if the target is in `ALLOWED[current]` *and* the gate predicate for
the target holds. `transition_ok` checks both.

The gate predicates read a duck-typed snapshot object (see
`app.events.projections.TaskSnapshot`); only attribute access is used so this
module has no import dependency on projections.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class State(StrEnum):
    CREATED = "CREATED"
    INTERPRETING = "INTERPRETING"
    PLANNING = "PLANNING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    STALLED = "STALLED"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ALLOWED: dict[State, set[State]] = {
    State.CREATED: {State.INTERPRETING, State.CANCELLED},
    State.INTERPRETING: {State.PLANNING, State.WAITING_FOR_USER, State.FAILED, State.CANCELLED},
    State.PLANNING: {State.EXECUTING, State.WAITING_FOR_USER, State.FAILED, State.CANCELLED},
    State.WAITING_FOR_USER: {State.INTERPRETING, State.EXECUTING, State.FAILED, State.CANCELLED},
    State.EXECUTING: {
        State.VERIFYING,
        State.WAITING_FOR_USER,
        State.STALLED,
        State.FAILED,
        State.CANCELLED,
    },
    State.VERIFYING: {State.COMPLETED, State.STALLED, State.FAILED, State.CANCELLED},
    State.STALLED: {State.RECOVERING, State.WAITING_FOR_USER, State.FAILED, State.CANCELLED},
    State.RECOVERING: {
        State.EXECUTING,
        State.VERIFYING,
        State.WAITING_FOR_USER,
        State.FAILED,
        State.CANCELLED,
    },
    State.COMPLETED: set(),
    State.FAILED: set(),
    State.CANCELLED: set(),
}


class _Snapshot(Protocol):
    state: State

    @property
    def contract(self): ...
    @property
    def contract_problems(self) -> list[str]: ...
    @property
    def plan(self): ...
    @property
    def observations(self) -> list: ...
    @property
    def verification(self): ...


def gate_reason(target: State, snap: _Snapshot) -> tuple[bool, str]:
    """Does the gate for entering `target` hold, given the current snapshot?

    Slice scope: INTERPRETING, FAILED, CANCELLED, STALLED and RECOVERING carry no
    extra gate (no progress detection / recovery logic yet — those arrive in
    Milestone D). The request-non-empty check for INTERPRETING happens at capture.
    """
    if target is State.PLANNING:
        if snap.contract is None:
            return False, "no contract"
        if snap.contract_problems:
            return False, "contract invalid: " + "; ".join(snap.contract_problems)
        if snap.contract.ambiguity:
            return False, "contract has open ambiguity"
        return True, ""

    if target is State.WAITING_FOR_USER:
        has_reason = bool(
            getattr(snap, "pending_approval", None)
            or getattr(snap, "open_clarification", False)
            or (
                snap.contract is not None
                and (snap.contract.ambiguity or snap.contract_problems)
            )
        )
        return has_reason, "" if has_reason else "nothing to ask the user"

    if target is State.EXECUTING:
        if snap.plan is None or not snap.plan.steps:
            return False, "no plan steps"
        for step in snap.plan.steps:
            if not step.required_capability or not step.expected_artifact_delta:
                return False, f"plan step {step.id} missing capability or expected effect"
        return True, ""

    if target is State.VERIFYING:
        ok = len(snap.observations) > 0
        return ok, "" if ok else "no observation from the builder"

    if target is State.COMPLETED:
        if snap.verification is None:
            return False, "no verification record"
        if snap.verification.overall != "pass":
            return False, "verification did not pass"
        return True, ""

    return True, ""


def transition_ok(current: State, target: State, snap: _Snapshot) -> tuple[bool, str]:
    if target not in ALLOWED[current]:
        return False, f"{current} -> {target} is not an allowed transition"
    return gate_reason(target, snap)
