"""Acceptance (Unit): the shell read models are pure folds of the event log
(MILESTONE_H_PLAN.md §6)."""

from __future__ import annotations

from app.events.log import EventKind, EventLog
from app.schemas.contracts import (
    AgentMessage,
    ModelRunRecord,
    TaskContract,
    TaskResult,
    VerificationRecord,
)
from app.ui import readmodels


def _seed(log: EventLog, task_id: str = "t1", *, state: str = "COMPLETED") -> None:
    c = TaskContract(
        task_id=task_id, original_request="fix add", objective="make add return a + b",
        task_class="code_edit_local", success_criteria=["add(2,3)==5"],
        required_evidence=["T0: pytest test_calc.py::test_add passes"],
    )
    log.append(task_id, EventKind.REQUEST, {"text": "fix add", "workspace_path": "/ws"})
    log.append(task_id, EventKind.STATE, {"state": "INTERPRETING"})
    log.append(task_id, EventKind.CONTRACT, c.model_dump(mode="json"))
    log.append(task_id, EventKind.STATE, {"state": "PLANNING"})
    log.append(task_id, EventKind.AGENT_MESSAGE, AgentMessage(
        sender="planner", role="planner", task_id=task_id, intent="HANDOFF",
        claims=["fix add() to return a + b"],
    ).model_dump(mode="json"))
    log.append(task_id, EventKind.MODEL_RUN, ModelRunRecord(
        task_id=task_id, role="planner", provider="agent_sdk", model="claude-sonnet-5",
        input_tokens=120, output_tokens=40,
    ).model_dump(mode="json"))
    log.append(task_id, EventKind.STATE, {"state": "EXECUTING"})
    log.append(task_id, EventKind.STATE, {"state": "VERIFYING"})
    log.append(task_id, EventKind.VERIFICATION, VerificationRecord(
        task_id=task_id, tier="T0", overall="pass", verdict="pass",
    ).model_dump(mode="json"))
    log.append(task_id, EventKind.STATE, {"state": state})
    log.append(task_id, EventKind.RESULT, TaskResult(
        task_id=task_id, state=state, verified=(state == "COMPLETED"), summary="completed",
    ).model_dump(mode="json"))


def test_task_list_shape_and_newest_first() -> None:
    log = EventLog()
    _seed(log, "t1")
    _seed(log, "t2", state="FAILED")
    tl = readmodels.task_list(log)
    assert tl["count"] == 2
    assert tl["tasks"][0]["task_id"] == "t2"  # newest first
    row = tl["tasks"][1]
    assert row["state"] == "COMPLETED" and row["task_class"] == "code_edit_local"
    assert row["verified"] is True and row["objective"].startswith("make add")
    log.close()


def test_timeline_orders_by_seq_with_transitions_and_spend() -> None:
    log = EventLog()
    _seed(log)
    tl = readmodels.task_timeline(log, "t1")
    assert [e["seq"] for e in tl["events"]] == sorted(e["seq"] for e in tl["events"])
    tos = [t["to"] for t in tl["transitions"]]
    assert tos == ["INTERPRETING", "PLANNING", "EXECUTING", "VERIFYING", "COMPLETED"]
    assert tl["transitions"][1]["from"] == "INTERPRETING"
    assert tl["spend"]["model_runs"] == 1 and tl["spend"]["input_tokens"] == 120
    assert tl["verification"] == {"tier": "T0", "overall": "pass"}


def test_timeline_missing_task_is_none() -> None:
    assert readmodels.task_timeline(EventLog(), "nope") is None


def test_agents_panel_reports_last_message_per_role() -> None:
    log = EventLog()
    _seed(log)
    log.append("t1", EventKind.AGENT_MESSAGE, AgentMessage(
        sender="planner", role="planner", task_id="t1", intent="STATUS",
        claims=["second message"],
    ).model_dump(mode="json"))
    panel = readmodels.agents_panel(log, "t1")
    by_role = {r["role"]: r for r in panel["roles"]}
    assert by_role["planner"]["active"] and by_role["planner"]["claims"] == ["second message"]
    assert by_role["planner"]["intent"] == "STATUS"  # latest wins
    assert not by_role["critic"]["active"]


def test_system_health_reflects_hardware_canary_quarantine() -> None:
    log = EventLog()
    _seed(log)
    log.append("t1", EventKind.HARDWARE, {"mode": "CONSERVATION", "source": "static"})
    log.append("t1", EventKind.CANARY, {"kind": "experience", "subject": "exp_1", "verdict": "HOLD"})
    log.append("t1", EventKind.CANARY, {"kind": "experience", "subject": "exp_2", "verdict": "ROLLBACK"})
    log.append("t1", EventKind.EXPERIENCE_TRANSITION, {"id": "exp_2", "state": "QUARANTINED", "trigger": "canary_rollback"})
    h = readmodels.system_health(log)
    assert h["hardware_mode"] == "CONSERVATION"
    assert h["canaries_active"] == 1 and h["canaries_rolled_back"] == 1
    assert h["quarantine_events"] == 1 and h["tasks_tracked"] == 1


def test_metrics_and_routes_panels() -> None:
    log = EventLog()
    _seed(log)
    log.append("t1", EventKind.ROUTE, {
        "task_class": "code_edit_local", "provider_id": "agent_sdk",
        "reason": "static default", "escalated": False, "data_driven": False,
    })
    m = readmodels.metrics_panel(log)
    assert m["success_rate_by_class"]["code_edit_local"] == 1.0 and m["tasks"] == 1
    r = readmodels.routes_panel(log)
    assert r["by_class"]["code_edit_local"]["agent_sdk"] == 1
    assert r["recent"][0]["provider_id"] == "agent_sdk"


def test_readmodels_are_pure() -> None:
    log = EventLog()
    _seed(log)
    a = readmodels.task_timeline(log, "t1")
    b = readmodels.task_timeline(log, "t1")
    assert a == b
