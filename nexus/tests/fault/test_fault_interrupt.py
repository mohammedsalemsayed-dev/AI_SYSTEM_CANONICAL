"""Fault suite: a kill mid-run leaves a consistent log; a fresh Orchestrator
`resume()`s to a safe terminal without double-applying (MILESTONE_Q_PLAN.md §6)."""

from __future__ import annotations

import pytest

from app.events.log import EventKind, EventLog
from app.services.faults.interrupt import InterruptAfter, _Interrupted
from tests.conftest import FIXED_CALC
from tests.fault.conftest import assert_safe, scripted_orchestrator, workspace_hash
from tests.integration.conftest import interpreter_reply, planner_reply


@pytest.mark.parametrize(
    "target", [EventKind.PLAN, EventKind.CHECKPOINT, EventKind.ARTIFACT, EventKind.VERIFICATION]
)
def test_interrupt_then_resume(sample_repo: str, tmp_path, target: str) -> None:
    before = workspace_hash(sample_repo)
    db = str(tmp_path / "ev.db")

    # run 1 — killed right after the first `target` event
    log1 = EventLog(db)
    hooked = InterruptAfter(log1, target)
    orch1 = scripted_orchestrator(
        hooked,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    with pytest.raises(_Interrupted):
        orch1.run("fix the add function", sample_repo)
    task_ids = log1.task_ids()
    assert len(task_ids) == 1
    tid = task_ids[0]
    log1.close()

    assert workspace_hash(sample_repo) == before  # nothing applied to the user's copy yet

    # run 2 — a fresh Orchestrator over the same log resumes
    log2 = EventLog(db)
    orch2 = scripted_orchestrator(
        log2,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    result = orch2.resume(tid)

    assert_safe(result, log2, before, sample_repo)
    # a RECONCILE event was written on resume
    assert any(e.kind == EventKind.RECONCILE for e in log2.read(tid))
    # exactly one terminal RESULT
    results = [e for e in log2.read(tid) if e.kind == EventKind.RESULT]
    assert len(results) == 1
    log2.close()


def test_interrupt_after_result_is_noop(sample_repo: str, tmp_path) -> None:
    before = workspace_hash(sample_repo)
    db = str(tmp_path / "ev.db")
    log1 = EventLog(db)
    orch1 = scripted_orchestrator(
        log1,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    r1 = orch1.run("fix the add function", sample_repo)
    assert r1.state == "COMPLETED"
    tid = r1.task_id
    log1.close()

    # resuming an already-terminal task is a NOOP that returns the recorded result
    log2 = EventLog(db)
    orch2 = scripted_orchestrator(
        log2, llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    r2 = orch2.resume(tid)
    assert r2.state == "COMPLETED" and r2.task_id == tid
    assert_safe(r2, log2, before, sample_repo)
    log2.close()
