"""Acceptance (Integration): a real code_edit_local task goes red -> green and
reaches COMPLETED with a T0 VerificationRecord and a full event timeline."""

from __future__ import annotations

from pathlib import Path

from app.events.log import EventKind, EventLog
from app.events.projections import project_task
from tests.conftest import FIXED_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def test_red_to_green_completes(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )

    result = orch.run("fix the add function", sample_repo)

    assert result.state == "COMPLETED"
    assert result.verified is True
    assert result.verification_ref is not None

    snap = project_task(log.read(result.task_id))
    assert snap.state.value == "COMPLETED"
    assert snap.verification is not None
    assert snap.verification.tier == "T0"
    assert snap.verification.overall == "pass"
    assert snap.plan is not None and len(snap.plan.steps) == 1
    assert len(snap.observations) == 1 and snap.observations[0].exit_code == 0
    log.close()


def test_event_timeline_is_complete_and_ordered(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    result = orch.run("fix the add function", sample_repo)

    kinds = [e.kind for e in log.read(result.task_id)]
    for expected in (
        EventKind.REQUEST,
        EventKind.CONTRACT,
        EventKind.PLAN,
        EventKind.ACTION_PROPOSAL,
        EventKind.POLICY_DECISION,
        EventKind.ARTIFACT,
        EventKind.OBSERVATION,
        EventKind.VERIFICATION,
        EventKind.RESULT,
    ):
        assert expected in kinds, f"missing {expected}"

    states = [e.payload["state"] for e in log.read(result.task_id) if e.kind == EventKind.STATE]
    assert states == ["INTERPRETING", "PLANNING", "EXECUTING", "VERIFYING", "COMPLETED"]
    log.close()


def test_original_workspace_is_untouched(sample_repo: str) -> None:
    before = (Path(sample_repo) / "calc.py").read_text(encoding="utf-8")
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.run("fix the add function", sample_repo)

    after = (Path(sample_repo) / "calc.py").read_text(encoding="utf-8")
    assert after == before  # builder worked only on a throwaway copy
    assert "a - b" in after
    log.close()


def test_model_runs_recorded_for_interpreter_and_planner(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    result = orch.run("fix the add function", sample_repo)

    runs = [e.payload for e in log.read(result.task_id) if e.kind == EventKind.MODEL_RUN]
    roles = {r["role"] for r in runs}
    assert roles == {"interpreter", "planner"}
    assert all(r["verification_result"] is None for r in runs)  # unscored in the slice
    log.close()
