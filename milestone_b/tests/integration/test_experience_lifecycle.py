"""Acceptance (Integration): a verified completion captures an experience; a
later task with a matching signature receives it as an advisory PROPOSAL at
planning (MILESTONE_F_PLAN.md §7, DESIGN_TIGHTENING §8, §14.7)."""

from __future__ import annotations

from app.events.log import EventKind, EventLog
from app.services.experience.store import ExperienceStore
from tests.conftest import FIXED_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def test_completion_captures_experience_as_candidate(sample_repo: str) -> None:
    log = EventLog()
    exp = ExperienceStore()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.experience = exp

    r = orch.run("fix the add function", sample_repo)
    assert r.state == "COMPLETED"

    ev = [e for e in log.read(r.task_id) if e.kind == EventKind.EXPERIENCE]
    assert ev, "an EXPERIENCE event should be logged on completion"
    stored = exp.all()
    assert len(stored) == 1
    # first sighting of this (signature, strategy) auto-advances past OBSERVED
    assert stored[0].validation_state == "CANDIDATE"
    assert stored[0].actions == ["calc.py"]
    exp.close()
    log.close()


def test_matching_experience_is_offered_at_planning(sample_repo: str) -> None:
    log = EventLog()
    exp = ExperienceStore()

    # task 1 — capture, then hand-promote so it is retrievable
    orch1 = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch1.experience = exp
    r1 = orch1.run("fix the add function", sample_repo)
    assert r1.state == "COMPLETED"
    captured = exp.all()[0]
    exp.advance(captured.id, "VALIDATED", note="test hand-promote")

    # task 2 — same task_class + tags, so the signature matches
    orch2 = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch2.experience = exp
    r2 = orch2.run("fix the add function once more", sample_repo)

    msgs = [
        e for e in log.read(r2.task_id)
        if e.kind == EventKind.AGENT_MESSAGE
        and e.payload.get("sender") == "experience"
    ]
    assert msgs, "planner should have received an experience PROPOSAL"
    assert msgs[0].payload["intent"] == "PROPOSAL"
    assert captured.id in msgs[0].payload["evidence_refs"]

    # retrieval counts as a use
    used = exp.get(captured.id)
    assert used.monitoring_metrics.get("trailing_n", 0) >= 1
    exp.close()
    log.close()


def test_no_experience_store_is_a_no_op(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    # orch.experience stays None
    r = orch.run("fix the add function", sample_repo)
    assert r.state == "COMPLETED"
    assert not [e for e in log.read(r.task_id) if e.kind == EventKind.EXPERIENCE]
    log.close()
