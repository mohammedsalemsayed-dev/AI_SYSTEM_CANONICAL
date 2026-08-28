"""Acceptance (Unit): the per-changed-file policy pass (MILESTONE_V_PLAN.md §6).

The step proposal only ever carried the workspace root, so the §14.1 risk-class
gate never saw the files a build touched. `_per_file_policy` re-runs the *same*
PolicyEngine + step grant once per changed file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.events.log import EventKind, EventLog
from app.orchestration.orchestrator import ApprovalPause, BuildError
from app.schemas.contracts import PlanStep, TaskContract
from app.services.capability.issue import issue_grant
from tests.integration.conftest import build_orchestrator


def _orch(log: EventLog):
    return build_orchestrator(log, llm_replies=["{}", "{}"], builder_edits={})


def _contract() -> TaskContract:
    return TaskContract(
        task_id="t", original_request="x", objective="x", task_class="code_edit_local",
        success_criteria=["x"], required_evidence=["T0: pytest test_x.py passes"],
    )


def _step(cap: str = "fs.write") -> PlanStep:
    return PlanStep(id="s1", intent="edit", expected_artifact_delta="edit files",
                    required_capability=cap)


def _run(orch, log, ws: str, changed: list[str], *, cap="fs.write", approved=None):
    step = _step(cap)
    grant = issue_grant("t", step, workspace_root=ws)
    orch._per_file_policy("t", _contract(), step, ws, grant, changed,
                          approved or set(), "act_step")
    return [e for e in log.read("t") if e.kind == EventKind.POLICY_DECISION]


def test_benign_paths_all_allow_no_pause(tmp_path: Path) -> None:
    log = EventLog()
    decs = _run(_orch(log), log, str(tmp_path), ["calc.py", "util/helpers.py"])
    assert len(decs) == 2
    assert all(d.payload["decision"] == "ALLOW" and d.payload["scope"] == "per-file"
               for d in decs)
    assert [d.payload["path"] for d in decs] == ["calc.py", "util/helpers.py"]


def test_risk_class_path_pauses_for_approval(tmp_path: Path) -> None:
    log = EventLog()
    with pytest.raises(ApprovalPause) as ei:
        _run(_orch(log), log, str(tmp_path), ["calc.py", "app/auth/login.py"])
    assert "app/auth/login.py" in str(ei.value)
    decs = [e for e in log.read("t") if e.kind == EventKind.POLICY_DECISION]
    assert decs[-1].payload["decision"] == "REQUIRE_APPROVAL"
    assert decs[-1].payload["path"] == "app/auth/login.py"


def test_risk_class_path_passes_when_step_pre_approved(tmp_path: Path) -> None:
    log = EventLog()
    decs = _run(_orch(log), log, str(tmp_path), ["db/migrations/0002_add.py"],
                approved={"s1"})
    assert decs[0].payload["decision"] == "REQUIRE_APPROVAL"  # still recorded
    # but no ApprovalPause was raised (the call returned)


def test_write_under_read_only_grant_is_denied(tmp_path: Path) -> None:
    log = EventLog()
    with pytest.raises(BuildError) as ei:
        _run(_orch(log), log, str(tmp_path), ["calc.py"], cap="fs.read")
    assert "operation-not-granted" in str(ei.value)


def test_path_escaping_scope_is_denied(tmp_path: Path) -> None:
    log = EventLog()
    with pytest.raises(BuildError) as ei:
        _run(_orch(log), log, str(tmp_path), ["../../../etc/passwd"])
    assert "out-of-scope" in str(ei.value) or "escape" in str(ei.value).lower()
