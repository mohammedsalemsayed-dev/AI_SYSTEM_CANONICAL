"""Acceptance (Recovery): restart reconciliation drives resume()
(MILESTONE_D_PLAN.md §6). The user's workspace is never mutated in any case."""

from __future__ import annotations

from pathlib import Path

from app.core.state import State
from app.events.log import EventKind, EventLog
from app.orchestration.orchestrator import Orchestrator
from app.schemas.contracts import Plan, PlanStep, TaskContract
from tests.conftest import FIXED_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def _crashed_mid_execute(log: EventLog, task_id: str, workspace: str) -> None:
    """Events for a task killed after PLAN, in EXECUTING, no observation yet."""
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


def test_reconcile_resume_completes_an_interrupted_task(sample_repo: str) -> None:
    before = (Path(sample_repo) / "calc.py").read_text(encoding="utf-8")
    log = EventLog()
    _crashed_mid_execute(log, "task_crash", sample_repo)

    # a real builder wired in for the resume
    orch = build_orchestrator(
        log, llm_replies=[], builder_edits={"calc.py": FIXED_CALC}
    )
    result = orch.resume("task_crash")

    assert result.state == "COMPLETED"
    kinds = [e.kind for e in log.read("task_crash")]
    assert EventKind.RECONCILE in kinds
    recon = next(e.payload for e in log.read("task_crash") if e.kind == EventKind.RECONCILE)
    assert recon["decision"] == "RESUME"
    assert (Path(sample_repo) / "calc.py").read_text(encoding="utf-8") == before
    log.close()


def test_reconcile_repair_when_interrupted_before_a_plan(sample_repo: str) -> None:
    log = EventLog()
    log.append("t", EventKind.REQUEST, {"text": "x", "workspace_path": sample_repo})
    log.append("t", EventKind.STATE, {"state": State.INTERPRETING})
    # crashed here — no CONTRACT, no PLAN

    orch = build_orchestrator(log, llm_replies=[], builder_edits={})
    result = orch.resume("t")

    assert result.state == "WAITING_FOR_USER"
    recon = next(e.payload for e in log.read("t") if e.kind == EventKind.RECONCILE)
    assert recon["decision"] == "REPAIR"
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
    assert again.state == "COMPLETED" and again.verified is True
    assert len(log.read(first.task_id)) == n_events  # nothing appended
    log.close()


def test_event_log_survives_reopen_then_reconcile(sample_repo: str, tmp_path) -> None:
    db = tmp_path / "ev.db"
    log = EventLog(db)
    _crashed_mid_execute(log, "task_crash", sample_repo)
    log.close()

    reopened = EventLog(db)
    orch = build_orchestrator(
        reopened, llm_replies=[], builder_edits={"calc.py": FIXED_CALC}
    )
    result = orch.resume("task_crash")
    assert result.state == "COMPLETED"
    reopened.close()
