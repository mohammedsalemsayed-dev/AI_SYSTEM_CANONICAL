"""Acceptance (Integration): the T2 ensemble is advisory — T0 stays
authoritative; a risky T0-pass / T2-fail split escalates to the user
(MILESTONE_E_PLAN.md §6)."""

from __future__ import annotations

import json

from app.events.log import EventKind, EventLog
from app.llm.fake import ScriptedLLM
from app.services.verify.verifier_t2 import VerifierT2
from tests.conftest import FIXED_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def _t2(*overalls: str) -> VerifierT2:
    replies = [
        json.dumps({"criteria": [{"criterion": "c", "verdict": o, "note": ""}], "overall": o})
        for o in overalls
    ]
    return VerifierT2(ScriptedLLM(replies), contexts=len(overalls))


def test_t2_agrees_task_completes(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log, [interpreter_reply(), planner_reply()], {"calc.py": FIXED_CALC}
    )
    orch.verifier_t2 = _t2("pass", "pass")
    result = orch.run("fix add", sample_repo)

    assert result.state == "COMPLETED"
    tiers = [
        e.payload["tier"] for e in log.read(result.task_id)
        if e.kind == EventKind.VERIFICATION
    ]
    assert tiers == ["T0", "T2"]
    assert EventKind.DISAGREEMENT not in [e.kind for e in log.read(result.task_id)]
    log.close()


def test_low_risk_t2_disagreement_is_logged_task_still_completes(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log, [interpreter_reply(), planner_reply()], {"calc.py": FIXED_CALC}
    )
    orch.verifier_t2 = _t2("fail", "fail")  # T2 says fail, T0 will pass, risk_level low
    result = orch.run("fix add", sample_repo)

    assert result.state == "COMPLETED"  # T0 authoritative on a low-risk task
    dis = [e.payload for e in log.read(result.task_id) if e.kind == EventKind.DISAGREEMENT]
    assert dis and dis[0]["resolution"] == "t0_authoritative"
    log.close()


def test_risky_t2_disagreement_escalates(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        [interpreter_reply(risk_level="high"), planner_reply()],
        {"calc.py": FIXED_CALC},
    )
    orch.verifier_t2 = _t2("fail", "fail")
    result = orch.run("fix add in the auth module", sample_repo)

    assert result.state == "WAITING_FOR_USER"
    dis = [e.payload for e in log.read(result.task_id) if e.kind == EventKind.DISAGREEMENT]
    assert dis and dis[0]["resolution"] == "escalate"
    assert EventKind.CLARIFICATION in [e.kind for e in log.read(result.task_id)]
    log.close()
