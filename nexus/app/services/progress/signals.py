"""Hard progress signals (design-notes 14.4, MILESTONE_D_PLAN.md 2).

Progress is credited ONLY from objective, measurable deltas between the state
after two steps. `objective_delta` / `strategy_change` are context for the
critic/human, never a score input, so they do not appear here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepMeasurement:
    """The measurable state after a step. Any field may be None if not measured."""

    step_index: int
    tests_passed: int | None = None
    tests_total: int | None = None
    error_count: int | None = None  # build / lint / type errors
    coverage_pct: float | None = None
    acceptance_met: bool | None = None  # the step's own acceptance check
    changed_paths: list[str] = field(default_factory=list)
    diff_text: str = ""
    error_signature: str | None = None  # normalized; used by the loop detector (day 3-4)

    @property
    def moved(self) -> bool:
        return bool(self.changed_paths or self.diff_text.strip())


# --- individual signal predicates ------------------------------------ #
def sig_tests_passed_up(prev: StepMeasurement, cur: StepMeasurement) -> bool:
    return (
        prev.tests_passed is not None
        and cur.tests_passed is not None
        and cur.tests_passed > prev.tests_passed
    )


def sig_new_passing_test(prev: StepMeasurement, cur: StepMeasurement) -> bool:
    return (
        prev.tests_total is not None
        and cur.tests_total is not None
        and cur.tests_total > prev.tests_total
        and (cur.tests_passed or 0) > (prev.tests_passed or 0)
    )


def sig_errors_down(prev: StepMeasurement, cur: StepMeasurement) -> bool:
    return (
        prev.error_count is not None
        and cur.error_count is not None
        and cur.error_count < prev.error_count
    )


def sig_coverage_up(prev: StepMeasurement, cur: StepMeasurement) -> bool:
    return (
        prev.coverage_pct is not None
        and cur.coverage_pct is not None
        and cur.coverage_pct > prev.coverage_pct + 1e-9
    )


def sig_acceptance_flip(prev: StepMeasurement, cur: StepMeasurement) -> bool:
    return not bool(prev.acceptance_met) and bool(cur.acceptance_met)


def sig_new_target_file_touched(
    prev_paths: set[str], cur: StepMeasurement
) -> bool:
    return any(p not in prev_paths for p in cur.changed_paths)


_PAIR_SIGNALS = {
    "tests_passed_up": sig_tests_passed_up,
    "new_passing_test": sig_new_passing_test,
    "errors_down": sig_errors_down,
    "coverage_up": sig_coverage_up,
    "acceptance_flip": sig_acceptance_flip,
}


def hard_progress(
    prev: StepMeasurement | None,
    cur: StepMeasurement,
    prior_touched: set[str] | None = None,
) -> list[str]:
    """Return the names of every hard-progress signal that fired for `cur`."""
    fired: list[str] = []
    if prev is not None:
        for name, fn in _PAIR_SIGNALS.items():
            if fn(prev, cur):
                fired.append(name)
    if sig_new_target_file_touched(prior_touched or set(), cur):
        fired.append("new_target_file_touched")
    return fired
