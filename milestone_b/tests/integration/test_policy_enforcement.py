"""Acceptance (Integration): the Orchestrator enforces the Policy Engine and
capability issuance end to end (MILESTONE_C_PLAN.md section 7)."""

from __future__ import annotations

from app.events.log import EventKind, EventLog
from app.events.projections import project_task
from app.services.policy.engine import PolicyEngine
from tests.conftest import FIXED_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def test_capability_grant_is_logged_on_happy_path(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    result = orch.run("fix add", sample_repo)
    assert result.state == "COMPLETED"

    grants = [e.payload for e in log.read(result.task_id) if e.kind == EventKind.CAPABILITY_GRANT]
    assert len(grants) == 1
    assert grants[0]["token"] == "fs.write"
    assert "file.write" in grants[0]["operations"]
    log.close()


def test_unknown_capability_token_fails_task(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply(capability="fs.root")],
        builder_edits={"calc.py": FIXED_CALC},
    )
    result = orch.run("fix add", sample_repo)

    assert result.state == "FAILED"
    errors = [e.payload["error"] for e in log.read(result.task_id) if e.kind == EventKind.ERROR]
    assert any("unknown capability" in msg for msg in errors)
    kinds = [e.kind for e in log.read(result.task_id)]
    assert EventKind.ARTIFACT not in kinds  # builder never ran
    log.close()


def test_require_approval_blocks_until_day_10(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
        policy=PolicyEngine(risk_globs=["*"]),  # force REQUIRE_APPROVAL on any write
    )
    result = orch.run("fix add", sample_repo)

    assert result.state == "FAILED"
    kinds = [e.kind for e in log.read(result.task_id)]
    assert EventKind.APPROVAL_REQUEST in kinds
    assert EventKind.ARTIFACT not in kinds
    snap = project_task(log.read(result.task_id))
    assert "approval required" in (snap.last_error or "")
    log.close()
