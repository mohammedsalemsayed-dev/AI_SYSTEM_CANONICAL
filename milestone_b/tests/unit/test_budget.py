"""Acceptance (Unit): budget accounting, soft/hard gates, admission
(MILESTONE_D_PLAN.md §6)."""

from __future__ import annotations

from app.services.budget.tracker import BudgetTracker, default_budget


def test_default_budget_per_class() -> None:
    assert default_budget("code_edit_local")["steps"] == 8
    assert default_budget("code_edit_broad")["steps"] == 16
    assert default_budget("unknown-class")["steps"] == 8  # fallback


def test_step_accounting_and_fractions() -> None:
    b = BudgetTracker({"steps": 4, "wall_clock_s": 10_000, "model_cost_usd": 0}, "")
    for _ in range(3):
        b.add_step()
    assert b.spent()["steps"] == 3.0
    assert b.fractions()["steps"] == 0.75
    assert b.over_soft() is False  # peak still 0.75 < 0.8? -> 0.75
    b.add_step()
    assert b.over_soft() is True and b.over_hard() is True


def test_soft_at_80_percent() -> None:
    b = BudgetTracker({"steps": 5}, "")
    for _ in range(4):
        b.add_step()
    assert b.peak_fraction() == 0.8
    assert b.over_soft() and not b.over_hard()


def test_admission_rejects_a_step_that_would_exceed() -> None:
    b = BudgetTracker({"steps": 2}, "")
    b.add_step()
    b.add_step()
    assert b.would_exceed(extra_steps=1) is True


def test_cost_dimension_ignored_when_zero_limit() -> None:
    b = BudgetTracker({"steps": 10, "model_cost_usd": 0}, "")
    b.add_cost(999.0)
    assert "model_cost_usd" not in b.fractions()  # zero limit -> not tracked
    assert b.peak_fraction() < 0.1


def test_summary_string() -> None:
    b = BudgetTracker({"steps": 4, "wall_clock_s": 100}, "")
    b.add_step()
    s = b.summary()
    assert "steps 1/4" in s and "wall_clock_s" in s
