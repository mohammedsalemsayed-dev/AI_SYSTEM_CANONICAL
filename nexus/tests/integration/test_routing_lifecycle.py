"""Acceptance (Integration): a routed task records a ROUTE decision + scored
`MODEL_RUN`s that persist to system memory; the `stronger_model` ladder rung
re-routes a stalled task; an EMERGENCY hardware mode pauses to WAITING_FOR_USER
(MILESTONE_G_PLAN.md §6)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.events.log import EventKind, EventLog
from app.schemas.contracts import HardwareSnapshot, ProviderSpec
from app.services.hardware.monitor import StaticHardwareMonitor
from app.services.memory.store import MemoryStore
from app.services.routing.registry import ProviderRegistry
from app.services.routing.router import Router
from app.services.routing.stats import RouteStatsStore
from tests.conftest import FIXED_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def _two_cloud_registry() -> ProviderRegistry:
    return ProviderRegistry([
        ProviderSpec(id="agent_sdk", provider="agent_sdk", model="claude-sonnet-5",
                     quality_prior=0.80, latency_prior_s=12, privacy_score=0.4, available=True),
        ProviderSpec(id="frontier", provider="anthropic", model="claude-opus-5",
                     quality_prior=0.93, latency_prior_s=9, privacy_score=0.4, available=True),
    ])


def test_routed_task_records_route_and_persists_stats(sample_repo: str) -> None:
    log = EventLog()
    mem = MemoryStore()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.memory = mem
    orch.router = Router(_two_cloud_registry(), seed=0, epsilon=0.0)

    r = orch.run("fix the add function", sample_repo)
    assert r.state == "COMPLETED"

    routes = [e for e in log.read(r.task_id) if e.kind == EventKind.ROUTE]
    assert routes and routes[0].payload["provider_id"] == "agent_sdk"
    assert routes[0].payload["task_class"] == "code_edit_local"

    stats = RouteStatsStore(mem)
    # the run was verified at T0 -> not scored; nothing ingested
    assert stats.count("code_edit_local", "claude-sonnet-5") == 0
    mem.close()
    log.close()


def test_stats_scored_only_at_t1_plus_and_visible_to_fresh_orchestrator() -> None:
    from app.schemas.contracts import ModelRunRecord

    mem = MemoryStore()
    stats = RouteStatsStore(mem)
    for i in range(20):
        stats.ingest(
            ModelRunRecord(task_id="t", role="builder", provider="anthropic",
                           model="claude-opus-5", latency_s=6.0),
            task_class="debug", verification_tier="T2", verification_pass=(i != 0),
        )
    assert RouteStatsStore(mem).eligible("debug", "claude-opus-5")
    agg = RouteStatsStore(mem).aggregate("debug", "claude-opus-5")
    assert agg["n"] == 20 and 0.9 < agg["success_rate"] < 1.0

    reg = _two_cloud_registry()
    router = Router(reg, RouteStatsStore(mem), seed=0, epsilon=0.0)
    d = router.route("debug", "builder")
    assert d.provider_id == "frontier" and d.data_driven
    mem.close()


# --- stronger_model rung ------------------------------------------- #
def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=x@x", "-c", "user.name=x", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def bug_repo(tmp_path: Path) -> str:
    repo = tmp_path / "bug"
    repo.mkdir()
    (repo / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8", newline="\n")
    (repo / "test_m.py").write_text(
        "from m import f\n\n\ndef test_f():\n    assert f() == 2\n",
        encoding="utf-8", newline="\n",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "bug")
    return str(repo)


def test_stronger_model_rung_reroutes_a_stalled_task(bug_repo: str) -> None:
    def bad_edit(ws: str) -> None:
        (Path(ws) / "m.py").write_text("def f():\n    return 999\n", newline="\n")

    plan = json.dumps({"steps": [
        {"intent": "retry", "expected_artifact_delta": "edit m.py", "required_capability": "fs.write"}
    ] * 3})
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[
            interpreter_reply(objective="make f() == 2",
                              required_evidence=["T0: pytest test_m.py::test_f passes"]),
            *([plan] * 8),
        ],
        builder_edits=bad_edit,
    )
    orch.router = Router(_two_cloud_registry(), seed=0, epsilon=0.0)

    result = orch.run("fix f", bug_repo)
    assert result.state == "WAITING_FOR_USER"

    rungs = [e.payload["rung"] for e in log.read(result.task_id) if e.kind == EventKind.ESCALATION]
    assert "stronger_model" in rungs
    routes = [e.payload for e in log.read(result.task_id) if e.kind == EventKind.ROUTE]
    assert any(p["escalated"] and p["provider_id"] == "frontier" for p in routes)
    log.close()


# --- hardware pause ---------------------------------------------- #
def test_emergency_hardware_mode_pauses(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.router = Router(_two_cloud_registry(), seed=0, epsilon=0.0)
    orch.hardware = StaticHardwareMonitor(HardwareSnapshot(gpu_temp_c=93.0))

    r = orch.run("fix the add function", sample_repo)
    assert r.state == "WAITING_FOR_USER"
    hw = [e for e in log.read(r.task_id) if e.kind == EventKind.HARDWARE]
    assert hw and hw[0].payload["mode"] == "EMERGENCY"
    routes = [e for e in log.read(r.task_id) if e.kind == EventKind.ROUTE]
    assert routes and routes[0].payload["provider_id"] == ""
    log.close()


def test_router_unset_is_unchanged_behaviour(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    r = orch.run("fix the add function", sample_repo)
    assert r.state == "COMPLETED"
    assert not [e for e in log.read(r.task_id) if e.kind == EventKind.ROUTE]
    log.close()
