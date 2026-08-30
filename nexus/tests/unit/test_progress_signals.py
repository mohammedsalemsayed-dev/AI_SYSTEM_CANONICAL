"""Acceptance (Unit): each hard-progress signal in isolation
(MILESTONE_D_PLAN.md §6)."""

from __future__ import annotations

from app.services.progress.signals import (
    StepMeasurement,
    hard_progress,
    sig_acceptance_flip,
    sig_coverage_up,
    sig_errors_down,
    sig_new_passing_test,
    sig_tests_passed_up,
)


def m(**kw) -> StepMeasurement:
    kw.setdefault("step_index", 0)
    return StepMeasurement(**kw)


def test_tests_passed_up() -> None:
    assert sig_tests_passed_up(m(tests_passed=2), m(tests_passed=3))
    assert not sig_tests_passed_up(m(tests_passed=3), m(tests_passed=3))
    assert not sig_tests_passed_up(m(tests_passed=None), m(tests_passed=3))


def test_new_passing_test_needs_both_totals_and_passes_up() -> None:
    assert sig_new_passing_test(
        m(tests_passed=2, tests_total=5), m(tests_passed=3, tests_total=6)
    )
    # total grew but nothing new passes -> not a signal
    assert not sig_new_passing_test(
        m(tests_passed=3, tests_total=5), m(tests_passed=3, tests_total=6)
    )


def test_errors_down() -> None:
    assert sig_errors_down(m(error_count=4), m(error_count=1))
    assert not sig_errors_down(m(error_count=1), m(error_count=4))
    assert not sig_errors_down(m(error_count=None), m(error_count=1))


def test_coverage_up() -> None:
    assert sig_coverage_up(m(coverage_pct=80.0), m(coverage_pct=82.5))
    assert not sig_coverage_up(m(coverage_pct=80.0), m(coverage_pct=80.0))


def test_acceptance_flip_only_false_to_true() -> None:
    assert sig_acceptance_flip(m(acceptance_met=False), m(acceptance_met=True))
    assert sig_acceptance_flip(m(acceptance_met=None), m(acceptance_met=True))
    assert not sig_acceptance_flip(m(acceptance_met=True), m(acceptance_met=True))
    assert not sig_acceptance_flip(m(acceptance_met=True), m(acceptance_met=False))


def test_new_target_file_touched() -> None:
    fired = hard_progress(
        m(step_index=0),
        m(step_index=1, changed_paths=["src/a.py"]),
        prior_touched={"src/b.py"},
    )
    assert "new_target_file_touched" in fired
    fired2 = hard_progress(
        m(step_index=0),
        m(step_index=1, changed_paths=["src/b.py"]),
        prior_touched={"src/b.py"},
    )
    assert "new_target_file_touched" not in fired2


def test_hard_progress_with_no_prev_only_reports_file_touch() -> None:
    fired = hard_progress(None, m(step_index=0, tests_passed=3, changed_paths=["x.py"]))
    assert fired == ["new_target_file_touched"]


def test_hard_progress_collects_all_that_fire() -> None:
    prev = m(step_index=0, tests_passed=1, tests_total=3, error_count=5, coverage_pct=50.0)
    cur = m(
        step_index=1,
        tests_passed=3,
        tests_total=4,
        error_count=2,
        coverage_pct=60.0,
        acceptance_met=True,
        changed_paths=["new.py"],
    )
    fired = set(hard_progress(prev, cur, prior_touched=set()))
    assert fired == {
        "tests_passed_up",
        "new_passing_test",
        "errors_down",
        "coverage_up",
        "acceptance_flip",
        "new_target_file_touched",
    }
