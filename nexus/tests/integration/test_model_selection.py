"""Acceptance (Integration): a task_class with eligible models + a fitted
WeightSet routes data-driven; a route-canary rollback demotes it back to static
(MILESTONE_O_PLAN.md §6)."""

from __future__ import annotations

from app.events.log import EventKind, EventLog
from app.schemas.contracts import ModelRunRecord, ProviderSpec, WeightSet
from app.services.memory.store import MemoryStore
from app.services.routing.features import FEATURE_ORDER
from app.services.routing.registry import ProviderRegistry
from app.services.routing.router import Router
from app.services.routing.selection import MIN_TRAIN, ModelSelectionController
from app.services.routing.stats import RouteStatsStore
from tests.conftest import FIXED_CALC
from tests.integration.conftest import build_orchestrator, interpreter_reply, planner_reply


def _two_models() -> ProviderRegistry:
    return ProviderRegistry([
        ProviderSpec(id="agent_sdk", provider="agent_sdk", model="claude-sonnet-5",
                     quality_prior=0.80, available=True),
        ProviderSpec(id="frontier", provider="anthropic", model="claude-opus-5",
                     quality_prior=0.93, available=True),
    ])


def _seed_eligibility(stats: RouteStatsStore, models: list[str], tc: str, n: int = 22) -> None:
    for model in models:
        for i in range(n):
            stats.ingest(
                ModelRunRecord(task_id="s", role="builder", provider="p", model=model, latency_s=5.0),
                task_class=tc, verification_tier="T1",
                verification_pass=(model == "claude-opus-5" or i % 3 != 0),
            )


def test_data_driven_switchover_and_canary_demote(sample_repo: str) -> None:
    log = EventLog()
    mem = MemoryStore()
    reg = _two_models()
    stats = RouteStatsStore(mem)
    _seed_eligibility(stats, ["claude-sonnet-5", "claude-opus-5"], "code_edit_local")

    ctrl = ModelSelectionController(mem, stats, reg)
    ws = WeightSet(task_class="code_edit_local",
                   weights={**dict.fromkeys(FEATURE_ORDER, 0.0), "quality": 6.0, "bias": -2.0},
                   feature_order=list(FEATURE_ORDER), n_train=MIN_TRAIN + 10, val_accuracy=0.82)
    ctrl.set_weights(ws)

    orch = build_orchestrator(
        log, llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.memory = mem
    orch.router = Router(reg, stats, seed=0, epsilon=0.0)
    orch.route_stats = stats
    orch.selection = ctrl

    r1 = orch.run("fix the add function", sample_repo)
    assert r1.state == "COMPLETED"
    sel = [e for e in log.read(r1.task_id) if e.kind == EventKind.SELECTION]
    assert sel and sel[0].payload["mode"] == "data_driven"
    # a fresh controller over the same memory still sees data_driven
    assert ModelSelectionController(mem, stats, reg).mode("code_edit_local") == "data_driven"

    # force a route-canary rollback -> the class is demoted
    orch.canary_enabled = True
    orch.canary_fraction = 1.0
    orch.canary_min_samples = 1
    orch._route_canaries.clear()
    # a challenger ROUTE + a failed settle
    from app.schemas.contracts import RouteDecision
    tid = "canary-task"
    log.append(tid, EventKind.CONTRACT, {"task_class": "code_edit_local"})
    log.append(tid, EventKind.ROUTE, RouteDecision(
        task_class="code_edit_local", provider_id="frontier", data_driven=True,
    ).model_dump(mode="json"))

    class _C:
        task_class = "code_edit_local"

    orch._settle_route_canary(tid, _C(), verified=False)
    assert ctrl.mode("code_edit_local") == "static"
    demote = [e for e in log.read(tid) if e.kind == EventKind.SELECTION and e.payload["mode"] == "static"]
    assert demote
    mem.close()
    log.close()


def test_selection_unset_routes_exactly_as_before(sample_repo: str) -> None:
    log = EventLog()
    mem = MemoryStore()
    reg = _two_models()
    stats = RouteStatsStore(mem)
    orch = build_orchestrator(
        log, llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.memory = mem
    orch.router = Router(reg, stats, seed=0, epsilon=0.0)
    r = orch.run("fix the add function", sample_repo)
    assert r.state == "COMPLETED"
    assert not [e for e in log.read(r.task_id) if e.kind == EventKind.SELECTION]
    mem.close()
    log.close()
