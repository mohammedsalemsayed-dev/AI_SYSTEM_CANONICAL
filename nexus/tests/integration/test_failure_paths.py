"""Acceptance (Failure): a bad diff fails verification (never COMPLETED); an
unverifiable / ambiguous request goes to WAITING_FOR_USER without a guess; a
builder error fails the task with the error on the event log."""

from __future__ import annotations

from app.events.log import EventKind, EventLog
from app.events.projections import project_task
from tests.conftest import FIXED_CALC, WRONG_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def test_wrong_fix_fails_verification_not_completed(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": WRONG_CALC},  # a * b -> test_add still fails
    )
    result = orch.run("fix the add function", sample_repo)

    assert result.state == "FAILED"
    assert result.verified is False

    snap = project_task(log.read(result.task_id))
    assert snap.verification is not None and snap.verification.overall == "fail"
    states = [e.payload["state"] for e in log.read(result.task_id) if e.kind == EventKind.STATE]
    assert "COMPLETED" not in states
    assert states[-1] == "FAILED"
    log.close()


def test_ambiguous_request_waits_for_user(sample_repo: str) -> None:
    log = EventLog()
    # only ONE llm reply queued: if the planner were reached it would IndexError
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(ambiguity=["which function should change?"])],
        builder_edits={"calc.py": FIXED_CALC},
    )
    result = orch.run("make it better", sample_repo)

    assert result.state == "WAITING_FOR_USER"
    kinds = [e.kind for e in log.read(result.task_id)]
    assert EventKind.CLARIFICATION in kinds
    assert EventKind.PLAN not in kinds
    assert EventKind.ARTIFACT not in kinds
    log.close()


def test_unverifiable_contract_waits_for_user(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        # no pytest T0 target and no ambiguity flagged by the model
        llm_replies=[interpreter_reply(required_evidence=["check that it works"])],
        builder_edits={"calc.py": FIXED_CALC},
    )
    result = orch.run("fix add", sample_repo)

    assert result.state == "WAITING_FOR_USER"
    snap = project_task(log.read(result.task_id))
    assert snap.contract is not None and snap.contract.ambiguity  # surfaced from problems
    log.close()


def test_builder_error_fails_task(sample_repo: str) -> None:
    def _boom(_workspace: str) -> None:
        raise RuntimeError("builder blew up")

    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits=_boom,
    )
    result = orch.run("fix the add function", sample_repo)

    assert result.state == "FAILED"
    kinds = [e.kind for e in log.read(result.task_id)]
    assert EventKind.ERROR in kinds
    assert EventKind.VERIFICATION not in kinds
    states = [e.payload["state"] for e in log.read(result.task_id) if e.kind == EventKind.STATE]
    assert "COMPLETED" not in states and states[-1] == "FAILED"
    log.close()


def test_builder_noop_fails_verification(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={},  # writes nothing -> empty diff
    )
    result = orch.run("fix the add function", sample_repo)

    assert result.state == "FAILED"
    snap = project_task(log.read(result.task_id))
    assert snap.verification is not None
    assert "no change" in snap.verification.residual_uncertainty
    log.close()
