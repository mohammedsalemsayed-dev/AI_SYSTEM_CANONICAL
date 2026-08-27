"""Acceptance (Unit): the event log appends, reads back in order, isolates tasks,
persists across a reopen, and replays into an exact task snapshot."""

from __future__ import annotations

from app.core.state import State
from app.events.log import EventKind, EventLog
from app.events.projections import project_task
from app.schemas.contracts import (
    Observation,
    Plan,
    PlanStep,
    TaskContract,
    VerificationRecord,
)


def _happy_path_events(log: EventLog, task_id: str) -> None:
    log.append(task_id, EventKind.REQUEST, {"text": "make the failing test pass", "workspace_path": "/w"})
    log.append(task_id, EventKind.STATE, {"state": State.INTERPRETING})
    log.append(
        task_id,
        EventKind.CONTRACT,
        TaskContract(
            task_id=task_id,
            original_request="make the failing test pass",
            objective="make tests/test_math.py::test_add pass",
            success_criteria=["test_add passes"],
            required_evidence=["T0: pytest tests/test_math.py::test_add passes"],
        ),
    )
    log.append(task_id, EventKind.STATE, {"state": State.PLANNING})
    log.append(
        task_id,
        EventKind.PLAN,
        Plan(
            task_id=task_id,
            steps=[
                PlanStep(
                    intent="fix add()",
                    expected_artifact_delta="edit src/math.py",
                    required_capability="fs.write",
                )
            ],
        ),
    )
    log.append(task_id, EventKind.STATE, {"state": State.EXECUTING})
    log.append(
        task_id,
        EventKind.OBSERVATION,
        Observation(task_id=task_id, step_id="step_x", exit_code=0, stdout="patched"),
    )
    log.append(task_id, EventKind.STATE, {"state": State.VERIFYING})
    log.append(
        task_id,
        EventKind.VERIFICATION,
        VerificationRecord(task_id=task_id, tier="T0", overall="pass"),
    )
    log.append(task_id, EventKind.STATE, {"state": State.COMPLETED})
    log.append(task_id, EventKind.RESULT, {"task_id": task_id, "state": "COMPLETED", "verified": True})


def test_append_and_read_in_order() -> None:
    log = EventLog()
    _happy_path_events(log, "task_a")

    events = log.read("task_a")
    assert [e.seq for e in events] == sorted(e.seq for e in events)
    assert len(events) == 11
    assert events[0].kind == EventKind.REQUEST
    assert events[-1].kind == EventKind.RESULT
    log.close()


def test_tasks_are_isolated() -> None:
    log = EventLog()
    _happy_path_events(log, "task_a")
    log.append("task_b", EventKind.REQUEST, {"text": "other", "workspace_path": "/w2"})
    log.append("task_b", EventKind.STATE, {"state": State.INTERPRETING})

    assert len(log.read("task_a")) == 11
    assert len(log.read("task_b")) == 2
    assert log.task_ids() == ["task_a", "task_b"]
    log.close()


def test_persists_across_reopen(tmp_path) -> None:
    db = tmp_path / "events.db"
    log = EventLog(db)
    _happy_path_events(log, "task_a")
    log.close()

    reopened = EventLog(db)
    events = reopened.read("task_a")
    assert len(events) == 11
    assert events[-1].payload["verified"] is True
    reopened.close()


def test_replay_reconstructs_snapshot() -> None:
    log = EventLog()
    _happy_path_events(log, "task_a")

    snap = project_task(log.read("task_a"))
    assert snap.task_id == "task_a"
    assert snap.state is State.COMPLETED
    assert snap.request_text == "make the failing test pass"
    assert snap.workspace_path == "/w"
    assert snap.contract is not None and snap.contract.objective.startswith("make tests/")
    assert snap.plan is not None and len(snap.plan.steps) == 1
    assert len(snap.observations) == 1 and snap.observations[0].exit_code == 0
    assert snap.verification is not None and snap.verification.overall == "pass"
    assert snap.result is not None and snap.result["verified"] is True
    log.close()


def test_replay_is_deterministic() -> None:
    log = EventLog()
    _happy_path_events(log, "task_a")
    events = log.read("task_a")

    first = project_task(events)
    second = project_task(events)
    assert first.state is second.state
    assert first.contract == second.contract
    assert first.plan == second.plan
    log.close()
