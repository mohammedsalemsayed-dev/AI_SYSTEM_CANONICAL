"""Acceptance (Recovery, light): after an interruption the event log shows the
pre-interruption state, `resume` fails the task cleanly, and the user's workspace
was never mutated. Full reconciliation is Milestone D."""

from __future__ import annotations

from pathlib import Path

from app.core.state import State
from app.events.log import EventKind, EventLog
from app.schemas.contracts import Plan, PlanStep, TaskContract, TaskResult
from app.orchestration.orchestrator import Orchestrator
from tests.conftest import FIXED_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def _crashed_task(log: EventLog, task_id: str, workspace: str) -> None:
    """Events for a task that was killed mid-EXECUTING."""
    log.append(task_id, EventKind.REQUEST, {"text": "fix add", "workspace_path": workspace})
    log.append(task_id, EventKind.STATE, {"state": State.INTERPRETING})
    log.append(
        task_id,
        EventKind.CONTRACT,
        TaskContract(
            task_id=task_id,
            original_request="fix add",
            objective="make add return a + b",
            success_criteria=["add(2,3) == 5"],
            required_evidence=["T0: pytest test_calc.py::test_add passes"],
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
                    intent="fix add",
                    expected_artifact_delta="edit calc.py",
                    required_capability="fs.write",
                )
            ],
        ),
    )
    log.append(task_id, EventKind.STATE, {"state": State.EXECUTING})
    # <- process dies here


def test_resume_fails_interrupted_task_and_preserves_history(sample_repo: str) -> None:
    before = (Path(sample_repo) / "calc.py").read_text(encoding="utf-8")
    log = EventLog()
    _crashed_task(log, "task_crash", sample_repo)

    orch = Orchestrator(log, None, None, None, None, None)
    result = orch.resume("task_crash")

    assert result.state == "FAILED"
    states = [e.payload["state"] for e in log.read("task_crash") if e.kind == EventKind.STATE]
    assert states == ["INTERPRETING", "PLANNING", "EXECUTING", "FAILED"]
    errors = [e.payload["error"] for e in log.read("task_crash") if e.kind == EventKind.ERROR]
    assert any("interrupted" in msg for msg in errors)

    after = (Path(sample_repo) / "calc.py").read_text(encoding="utf-8")
    assert after == before  # workspace never mutated
    log.close()


def test_resume_of_terminal_task_is_a_noop(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    first = orch.run("fix the add function", sample_repo)
    assert first.state == "COMPLETED"

    n_events = len(log.read(first.task_id))
    again = orch.resume(first.task_id)
    assert again.state == "COMPLETED"
    assert again.verified is True
    assert len(log.read(first.task_id)) == n_events  # nothing appended
    log.close()


def test_event_log_survives_reopen_mid_task(sample_repo: str, tmp_path) -> None:
    db = tmp_path / "ev.db"
    log = EventLog(db)
    _crashed_task(log, "task_crash", sample_repo)
    log.close()

    reopened = EventLog(db)
    orch = Orchestrator(reopened, None, None, None, None, None)
    result = orch.resume("task_crash")
    assert result.state == "FAILED"
    reopened.close()
