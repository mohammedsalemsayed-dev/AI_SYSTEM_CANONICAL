"""Acceptance (Unit): composition rule + RolePerformance shadow tracking
(MILESTONE_E_PLAN.md §7)."""

from __future__ import annotations

from app.schemas.contracts import TaskContract
from app.services.agents.composition import select_roles
from app.services.agents.performance import RolePerformanceStore


def _c(request: str = "fix the bug", task_class: str = "code_edit_local") -> TaskContract:
    return TaskContract(
        task_id="t", original_request=request, objective="o", task_class=task_class,
        success_criteria=["x"], required_evidence=["T0: pytest a.py passes"],
    )


def test_default_composition_is_builder_only() -> None:
    comp = select_roles(_c())
    assert comp.roles == {"builder"}


def test_explicit_request_adds_critic() -> None:
    comp = select_roles(_c(), explicit={"critic"})
    assert "critic" in comp.roles and comp.reasons["critic"] == "explicitly requested"


def test_request_phrasing_adds_a_role() -> None:
    comp = select_roles(_c("fix this and get a second opinion"))
    assert "critic" in comp.roles and comp.reasons["critic"] == "request phrasing"
    comp2 = select_roles(_c("research the right approach then implement"))
    assert "researcher" in comp2.roles


def test_ladder_invocation_adds_a_role() -> None:
    comp = select_roles(_c(), ladder_invoked={"researcher"})
    assert "researcher" in comp.roles and comp.reasons["researcher"] == "escalation ladder"


def test_promoted_role_added_from_performance() -> None:
    store = RolePerformanceStore()
    for _ in range(10):
        store.record("critic", "code_edit_local", baseline_pass=False, with_role_pass=True)
    assert store.meets_promotion_criterion("critic", "code_edit_local")
    comp = select_roles(_c(), role_perf=store)
    assert "critic" in comp.roles
    assert "promoted" in comp.reasons["critic"]


def test_performance_delta_below_bar_not_promoted() -> None:
    store = RolePerformanceStore()
    for _ in range(10):
        store.record("critic", "code_edit_local", baseline_pass=True, with_role_pass=True)
    assert not store.meets_promotion_criterion("critic", "code_edit_local")


def test_defect_rate_promotes() -> None:
    store = RolePerformanceStore()
    for i in range(10):
        store.record(
            "critic", "debug",
            baseline_pass=True, with_role_pass=True,
            defect_caught=(i < 2),  # 2 defects in 10 -> rate 0.2 >= 0.1
        )
    assert store.meets_promotion_criterion("critic", "debug")


def test_too_few_samples_not_promoted() -> None:
    store = RolePerformanceStore()
    store.record("critic", "debug", baseline_pass=False, with_role_pass=True)
    assert not store.meets_promotion_criterion("critic", "debug")
