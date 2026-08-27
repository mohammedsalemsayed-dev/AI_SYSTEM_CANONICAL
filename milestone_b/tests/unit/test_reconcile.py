"""Acceptance (Unit): checkpoint + idempotency + reconcile decisions
(MILESTONE_D_PLAN.md §6)."""

from __future__ import annotations

from app.core.state import State
from app.events.log import EventKind, EventLog
from app.schemas.contracts import (
    ActionProposal,
    Observation,
    Plan,
    PlanStep,
    TaskContract,
)
from app.services.recovery.checkpoint import build_checkpoint
from app.services.recovery.idempotency import completed_idempotency_keys
from app.services.recovery.reconcile import reconcile


def _log_with(*events) -> list:
    log = EventLog()
    for kind, payload in events:
        log.append("t", kind, payload)
    return log.read("t")


def _contract() -> TaskContract:
    return TaskContract(
        task_id="t", original_request="r", objective="o",
        success_criteria=["x"], required_evidence=["T0: pytest a.py passes"],
    )


def _plan() -> Plan:
    return Plan(task_id="t", steps=[PlanStep(intent="i", expected_artifact_delta="d", required_capability="fs.write")])


def test_noop_when_terminal() -> None:
    ev = _log_with(
        (EventKind.REQUEST, {"text": "x", "workspace_path": "/w"}),
        (EventKind.STATE, {"state": State.COMPLETED}),
    )
    assert reconcile(ev).decision == "NOOP"


def test_noop_when_waiting_for_user() -> None:
    ev = _log_with(
        (EventKind.REQUEST, {"text": "x", "workspace_path": "/w"}),
        (EventKind.STATE, {"state": State.WAITING_FOR_USER}),
    )
    assert reconcile(ev).decision == "NOOP"


def test_repair_when_no_contract() -> None:
    ev = _log_with(
        (EventKind.REQUEST, {"text": "x", "workspace_path": "/w"}),
        (EventKind.STATE, {"state": State.INTERPRETING}),
    )
    d = reconcile(ev)
    assert d.decision == "REPAIR" and "contract" in d.detail


def test_resume_when_contract_and_plan_present() -> None:
    ev = _log_with(
        (EventKind.REQUEST, {"text": "x", "workspace_path": "/w"}),
        (EventKind.STATE, {"state": State.INTERPRETING}),
        (EventKind.CONTRACT, _contract().model_dump(mode="json")),
        (EventKind.STATE, {"state": State.PLANNING}),
        (EventKind.PLAN, _plan().model_dump(mode="json")),
        (EventKind.STATE, {"state": State.EXECUTING}),
    )
    d = reconcile(ev)
    assert d.decision == "RESUME" and d.from_state == "EXECUTING"


def test_escalate_on_uncertain_external_action() -> None:
    prop = ActionProposal(
        task_id="t", step_id="s1", operation="net.fetch",
        arguments={"url": "https://x"}, required_capability="net.fetch",
        workspace_scope="/w", expected_effect="e", idempotency_key="t:s1",
    )
    ev = _log_with(
        (EventKind.REQUEST, {"text": "x", "workspace_path": "/w"}),
        (EventKind.STATE, {"state": State.INTERPRETING}),
        (EventKind.CONTRACT, _contract().model_dump(mode="json")),
        (EventKind.STATE, {"state": State.PLANNING}),
        (EventKind.PLAN, _plan().model_dump(mode="json")),
        (EventKind.STATE, {"state": State.EXECUTING}),
        (EventKind.ACTION_PROPOSAL, prop.model_dump(mode="json")),
        # no OBSERVATION for that proposal -> uncertain
    )
    assert reconcile(ev).decision == "ESCALATE"


def test_completed_idempotency_keys() -> None:
    prop = ActionProposal(
        task_id="t", step_id="s1", operation="file.write", arguments={},
        required_capability="fs.write", workspace_scope="/w", expected_effect="e",
        idempotency_key="t:s1",
    )
    ev = _log_with(
        (EventKind.ACTION_PROPOSAL, prop.model_dump(mode="json")),
        (EventKind.OBSERVATION, Observation(task_id="t", step_id="s1", exit_code=0).model_dump(mode="json")),
    )
    assert completed_idempotency_keys(ev) == {"t:s1"}

    ev_fail = _log_with(
        (EventKind.ACTION_PROPOSAL, prop.model_dump(mode="json")),
        (EventKind.OBSERVATION, Observation(task_id="t", step_id="s1", exit_code=1, error="boom").model_dump(mode="json")),
    )
    assert completed_idempotency_keys(ev_fail) == set()


def test_checkpoint_folds_state_and_paths() -> None:
    ev = _log_with(
        (EventKind.REQUEST, {"text": "x", "workspace_path": "/w"}),
        (EventKind.STATE, {"state": State.EXECUTING}),
        (EventKind.ARTIFACT, {"task_id": "t", "changed_paths": ["a.py", "b.py"], "diff": "", "bytes": 0, "id": "art1"}),
        (EventKind.OBSERVATION, Observation(task_id="t", step_id="s1", exit_code=0).model_dump(mode="json")),
    )
    cp = build_checkpoint(ev)
    assert cp.canonical_state == "EXECUTING"
    assert cp.changed_paths == ["a.py", "b.py"]
    assert cp.step_index == 1
