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


def _approval_orch(log: EventLog):
    return build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
        policy=PolicyEngine(risk_globs=["*"]),  # force REQUIRE_APPROVAL on any write
    )


def test_require_approval_pauses_at_waiting_for_user(sample_repo: str) -> None:
    log = EventLog()
    result = _approval_orch(log).run("fix add", sample_repo)

    assert result.state == "WAITING_FOR_USER"
    kinds = [e.kind for e in log.read(result.task_id)]
    assert EventKind.APPROVAL_REQUEST in kinds
    assert EventKind.ARTIFACT not in kinds  # builder has not run
    snap = project_task(log.read(result.task_id))
    assert snap.pending_approval is not None
    log.close()


def test_resume_approve_completes_the_task(sample_repo: str) -> None:
    log = EventLog()
    orch = _approval_orch(log)
    paused = orch.run("fix add", sample_repo)
    assert paused.state == "WAITING_FOR_USER"

    done = orch.resume(paused.task_id, approval="approve")
    assert done.state == "COMPLETED"
    assert done.verified is True
    kinds = [e.kind for e in log.read(paused.task_id)]
    assert EventKind.APPROVAL_DECISION in kinds
    assert EventKind.ARTIFACT in kinds  # builder ran after approval
    log.close()


def test_resume_deny_fails_the_task(sample_repo: str) -> None:
    log = EventLog()
    orch = _approval_orch(log)
    paused = orch.run("fix add", sample_repo)

    denied = orch.resume(paused.task_id, approval="deny")
    assert denied.state == "FAILED"
    snap = project_task(log.read(paused.task_id))
    assert snap.pending_approval is None
    errors = [e.payload["error"] for e in log.read(paused.task_id) if e.kind == EventKind.ERROR]
    assert any("denied" in m for m in errors)
    kinds = [e.kind for e in log.read(paused.task_id)]
    assert EventKind.ARTIFACT not in kinds  # builder never ran
    log.close()


def test_resume_without_decision_stays_waiting(sample_repo: str) -> None:
    log = EventLog()
    orch = _approval_orch(log)
    paused = orch.run("fix add", sample_repo)
    still = orch.resume(paused.task_id)  # no approval arg
    assert still.state == "WAITING_FOR_USER"
    log.close()


# --- Milestone V: per-changed-file policy ----------------------- #
def _perfile_orch(log: EventLog, edits: dict[str, str]):
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits=edits,
        policy=PolicyEngine(),  # DEFAULT risk globs — do NOT match the workspace root
    )
    orch.per_file_policy = True
    return orch


def test_per_file_policy_catches_a_risk_class_file_the_step_check_missed(sample_repo: str) -> None:
    log = EventLog()
    orch = _perfile_orch(log, {"calc.py": FIXED_CALC, "db/migrations/0002_add.py": "# m\n"})
    paused = orch.run("fix add", sample_repo)
    assert paused.state == "WAITING_FOR_USER"

    ev = log.read(paused.task_id)
    per_file = [e for e in ev if e.kind == EventKind.POLICY_DECISION
                and e.payload.get("scope") == "per-file"]
    assert any(e.payload["path"] == "db/migrations/0002_add.py"
               and e.payload["decision"] == "REQUIRE_APPROVAL" for e in per_file)
    assert EventKind.ARTIFACT not in [e.kind for e in ev]  # aborted before the artifact

    done = orch.resume(paused.task_id, approval="approve")
    assert done.state == "COMPLETED" and done.verified is True
    log.close()


def test_per_file_policy_is_silent_for_ordinary_files(sample_repo: str) -> None:
    log = EventLog()
    orch = _perfile_orch(log, {"calc.py": FIXED_CALC})
    r = orch.run("fix add", sample_repo)
    assert r.state == "COMPLETED"
    per_file = [e for e in log.read(r.task_id) if e.kind == EventKind.POLICY_DECISION
                and e.payload.get("scope") == "per-file"]
    assert per_file and all(e.payload["decision"] == "ALLOW" for e in per_file)
    log.close()


def test_per_file_policy_off_by_default_is_byte_identical(sample_repo: str) -> None:
    log_a, log_b = EventLog(), EventLog()
    edits = {"calc.py": FIXED_CALC, "db/migrations/0002_add.py": "# m\n"}
    off = build_orchestrator(log_a, llm_replies=[interpreter_reply(), planner_reply()],
                             builder_edits=dict(edits))
    r = off.run("fix add", sample_repo)
    assert r.state == "COMPLETED"  # the migration edit sails through — the gap V closes
    assert not [e for e in log_a.read(r.task_id) if e.kind == EventKind.POLICY_DECISION
                and e.payload.get("scope") == "per-file"]
    log_a.close()
    log_b.close()
