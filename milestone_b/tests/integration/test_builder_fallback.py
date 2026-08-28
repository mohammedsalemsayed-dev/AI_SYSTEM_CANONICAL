"""Acceptance (Integration): local-first Builder -> escalate to a stronger
Builder once if the diff fails verification (run_task --local-builder path)."""

from __future__ import annotations

from app.events.log import EventKind, EventLog
from app.services.build.fake import ScriptedBuilder
from tests.conftest import FIXED_CALC, WRONG_CALC
from tests.integration.conftest import build_orchestrator, interpreter_reply, planner_reply


def _orch(log: EventLog, primary_edit: dict, fallback_edit: dict | None):
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply(),
                     # a second plan is requested on the STALLED->RECOVERING retry
                     interpreter_reply(), planner_reply()],
        builder_edits=primary_edit,
    )
    if fallback_edit is not None:
        orch.fallback_builder = ScriptedBuilder(fallback_edit)
    return orch


def test_local_fail_escalates_and_the_fallback_completes(sample_repo: str) -> None:
    log = EventLog()
    orch = _orch(log, {"calc.py": WRONG_CALC}, {"calc.py": FIXED_CALC})
    r = orch.run("fix add", sample_repo)
    assert r.state == "COMPLETED" and r.verified is True

    ev = log.read(r.task_id)
    esc = [e for e in ev if e.kind == EventKind.ESCALATION
           and e.payload.get("reason") == "verification failed"]
    assert esc and esc[0].payload["to_builder"] == "fake"
    verds = [e.payload["overall"] for e in ev if e.kind == EventKind.VERIFICATION]
    assert verds == ["fail", "pass"]  # first attempt failed, fallback passed


def test_no_fallback_still_just_fails(sample_repo: str) -> None:
    log = EventLog()
    orch = _orch(log, {"calc.py": WRONG_CALC}, None)
    r = orch.run("fix add", sample_repo)
    assert r.state == "FAILED"
    assert not [e for e in log.read(r.task_id) if e.kind == EventKind.ESCALATION
                and e.payload.get("reason") == "verification failed"]


def test_local_pass_never_escalates(sample_repo: str) -> None:
    log = EventLog()
    orch = _orch(log, {"calc.py": FIXED_CALC}, {"calc.py": FIXED_CALC})
    r = orch.run("fix add", sample_repo)
    assert r.state == "COMPLETED"
    ev = log.read(r.task_id)
    assert not [e for e in ev if e.kind == EventKind.ESCALATION
                and e.payload.get("reason") == "verification failed"]
    assert [e.payload["overall"] for e in ev if e.kind == EventKind.VERIFICATION] == ["pass"]


def test_fallback_also_fails_ends_failed_no_loop(sample_repo: str) -> None:
    log = EventLog()
    orch = _orch(log, {"calc.py": WRONG_CALC}, {"calc.py": WRONG_CALC})
    r = orch.run("fix add", sample_repo)
    assert r.state == "FAILED"
    # exactly one escalation — the retry is bounded, no ping-pong
    esc = [e for e in log.read(r.task_id) if e.kind == EventKind.ESCALATION
           and e.payload.get("reason") == "verification failed"]
    assert len(esc) == 1
