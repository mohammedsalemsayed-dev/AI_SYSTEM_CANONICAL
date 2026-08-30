"""Acceptance (Integration): project memory recorded on one task feeds the next
task's context; a superseded decision drops out (MILESTONE_F_PLAN.md §6)."""

from __future__ import annotations

from pathlib import Path

from app.events.log import EventKind, EventLog
from app.schemas.contracts import MemoryRecord
from app.services.memory.store import MemoryStore
from tests.conftest import FIXED_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def test_completion_writes_artifact_index_and_next_task_sees_it(sample_repo: str) -> None:
    log = EventLog()
    mem = MemoryStore()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply(), interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.memory = mem

    r1 = orch.run("fix the add function", sample_repo)
    assert r1.state == "COMPLETED"
    idx = [m for m in mem.all(tier="project") if m.kind == "artifact_index"]
    assert idx and "calc.py" in idx[0].content

    # second task: the interpreter's listing should now carry PROJECT MEMORY
    r2 = orch.run("adjust calc again", sample_repo)
    mem_events = [e for e in log.read(r2.task_id) if e.kind == EventKind.MEMORY and e.payload.get("used") == "context"]
    assert mem_events  # context was built and injected
    mem.close()
    log.close()


def test_superseded_decision_is_not_in_context(sample_repo: str) -> None:
    from app.services.memory.context import build_context

    mem = MemoryStore()
    old = mem.put(MemoryRecord(tier="project", kind="decision", content="use sqlite for storage"))
    ctx1 = build_context(mem, "storage choice")
    assert "use sqlite for storage" in ctx1

    mem.supersede(old.id, MemoryRecord(tier="project", kind="decision",
                                       content="use postgres for storage"))
    ctx2 = build_context(mem, "storage choice")
    assert "sqlite" not in ctx2 and "postgres" in ctx2
    mem.close()
