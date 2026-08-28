"""Acceptance (Unit): provider registry, static routing table, route stats,
router blend, hardware modes (MILESTONE_G_PLAN.md §6)."""

from __future__ import annotations

from app.schemas.contracts import HardwareSnapshot, ModelRunRecord, ProviderSpec
from app.services.hardware.modes import biases_local, decide, should_pause
from app.services.memory.store import MemoryStore
from app.services.routing.registry import DEFAULT_PROVIDERS, ProviderRegistry
from app.services.routing.router import STABILITY_MARGIN, Router
from app.services.routing.stats import ELIGIBLE_MIN_RUNS, RouteStatsStore
from app.services.routing.table import (
    STATIC_TABLE,
    escalation_reason,
    policy_for,
)

_TASK_CLASSES = [
    "qa_explain", "code_edit_local", "code_edit_broad", "debug", "research_web",
    "doc_analysis", "authoring", "planning_arch", "ops",
]


# --- registry ---------------------------------------------------- #
def test_default_seed_has_cloud_default_and_unavailable_local() -> None:
    reg = ProviderRegistry()
    assert reg.require("agent_sdk").available
    assert not reg.require("anthropic").available  # billed, opt-in
    assert all(not s.available for s in reg.all() if s.local)
    assert {s.id for s in reg.available()} == {"agent_sdk"}


def test_registry_set_available_and_filter() -> None:
    reg = ProviderRegistry()
    reg.set_available("local-coder", True)
    assert [s.id for s in reg.available(local=True)] == ["local-coder"]
    assert "agent_sdk" in {s.id for s in reg.available(cloud=True)}


# --- static table --------------------------------------------- #
def test_every_task_class_has_a_policy_with_a_default() -> None:
    for tc in _TASK_CLASSES:
        pol = policy_for(tc)
        assert pol.prefer and isinstance(pol.prefer[0], str)
    assert set(STATIC_TABLE) == set(_TASK_CLASSES)


def test_escalation_triggers_fire_only_on_their_condition() -> None:
    assert escalation_reason("code_edit_local", attempt=1) is None
    assert escalation_reason("code_edit_local", attempt=2) is not None
    assert escalation_reason("debug", attempt=2) is not None
    assert escalation_reason("qa_explain", context_tokens=999_999) is not None
    assert escalation_reason("code_edit_broad", modules_touched=5) is not None
    assert escalation_reason("code_edit_broad", risk_level="high") is not None
    assert escalation_reason("code_edit_broad", modules_touched=1, risk_level="low") is None
    assert escalation_reason("authoring", high_stakes=True) is not None
    assert escalation_reason("research_web", contradiction_unresolved=True) is not None
    assert escalation_reason("planning_arch") is not None  # always cloud
    assert escalation_reason("ops") is None


# --- hardware modes ------------------------------------------- #
def test_hardware_mode_thresholds() -> None:
    assert decide(HardwareSnapshot(gpu_temp_c=91)) == "EMERGENCY"
    assert decide(HardwareSnapshot(gpu_temp_c=86)) == "PROTECTIVE"
    assert decide(HardwareSnapshot(gpu_temp_c=81)) == "CONSERVATION"
    assert decide(HardwareSnapshot(ram_percent=93)) == "CONSERVATION"
    assert decide(HardwareSnapshot(gpu_percent=96), progress_good=False) == "CONSERVATION"
    assert decide(HardwareSnapshot(gpu_percent=96), progress_good=True) == "EFFICIENT"
    assert decide(HardwareSnapshot(gpu_percent=50, ram_percent=50)) == "NORMAL"
    assert should_pause("EMERGENCY") and not should_pause("PROTECTIVE")
    assert biases_local("CONSERVATION") and not biases_local("EFFICIENT")


# --- route stats -------------------------------------------- #
def _run(model="m1", latency=5.0) -> ModelRunRecord:
    return ModelRunRecord(task_id="t", role="builder", provider="p", model=model, latency_s=latency)


def test_unverified_run_is_not_scored() -> None:
    mem = MemoryStore()
    st = RouteStatsStore(mem)
    assert st.ingest(_run(), task_class="code_edit_local",
                     verification_tier="T0", verification_pass=True) is False
    assert st.ingest(_run(), task_class="code_edit_local",
                     verification_tier=None, verification_pass=True) is False
    assert st.count("code_edit_local", "m1") == 0
    mem.close()


def test_eligibility_and_aggregate() -> None:
    mem = MemoryStore()
    st = RouteStatsStore(mem)
    for i in range(ELIGIBLE_MIN_RUNS - 1):
        st.ingest(_run(latency=4.0), task_class="debug", verification_tier="T1",
                  verification_pass=(i % 5 != 0))
    assert not st.eligible("debug", "m1")
    st.ingest(_run(latency=4.0), task_class="debug", verification_tier="T2", verification_pass=True)
    assert st.eligible("debug", "m1")
    agg = st.aggregate("debug", "m1")
    assert agg["n"] == ELIGIBLE_MIN_RUNS
    assert 0.0 < agg["success_rate"] <= 1.0
    assert agg["latency_median"] == 4.0
    assert "m1" in st.eligible_models("debug")
    mem.close()


# --- router ------------------------------------------------- #
def test_router_static_default_and_escalation() -> None:
    r = Router(seed=1)
    assert r.route("code_edit_local").provider_id == "agent_sdk"
    d = r.route("code_edit_local", attempt=2)
    assert d.escalated and d.provider_id == "agent_sdk"
    assert not r.route("code_edit_local").provider_id == ""  # sanity


def test_router_emergency_pause_returns_no_provider() -> None:
    r = Router(seed=1)
    d = r.route("code_edit_local", hardware_mode="EMERGENCY")
    assert d.provider_id == "" and "paused" in d.reason


def test_router_prefers_local_under_conservation_when_available() -> None:
    reg = ProviderRegistry()
    reg.set_available("local-coder", True)
    r = Router(reg, seed=1)
    d = r.route("code_edit_local", hardware_mode="CONSERVATION")
    assert d.provider_id == "local-coder" and "local" in d.reason


def test_router_data_driven_override_when_eligible() -> None:
    # two cloud providers available; the challenger has a strong measured record
    specs = [
        ProviderSpec(id="a", provider="x", model="a", quality_prior=0.80,
                     latency_prior_s=10, privacy_score=0.4, available=True),
        ProviderSpec(id="b", provider="y", model="b", quality_prior=0.50,
                     latency_prior_s=10, privacy_score=0.4, available=True),
    ]
    reg = ProviderRegistry(specs)
    mem = MemoryStore()
    st = RouteStatsStore(mem)
    for _ in range(ELIGIBLE_MIN_RUNS):
        st.ingest(ModelRunRecord(task_id="t", role="builder", provider="y", model="b", latency_s=3.0),
                  task_class="debug", verification_tier="T1", verification_pass=True)
    r = Router(reg, st, seed=1, epsilon=0.0)
    d = r.route("debug")
    assert d.provider_id == "b" and d.data_driven
    mem.close()


def test_router_epsilon_exploration_is_seeded() -> None:
    specs = [
        ProviderSpec(id="a", provider="x", model="a", quality_prior=0.8, available=True),
        ProviderSpec(id="b", provider="y", model="b", quality_prior=0.5, available=True),
    ]
    r_explore = Router(ProviderRegistry(specs), stats=_AlwaysIneligible(), seed=2, epsilon=1.0)
    d = r_explore.route("debug")
    assert d.explored and d.provider_id in {"a", "b"}
    r_none = Router(ProviderRegistry(specs), stats=_AlwaysIneligible(), seed=2, epsilon=0.0)
    assert not r_none.route("debug").explored


class _AlwaysIneligible:
    def eligible(self, *_a, **_k) -> bool:
        return False

    def aggregate(self, *_a, **_k) -> dict:
        return {"n": 0, "success_rate": 0.0, "latency_median": 0.0,
                "latency_p90": 0.0, "resource_median": 0.0, "cost_median": 0.0}
