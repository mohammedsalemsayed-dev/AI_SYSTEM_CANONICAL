"""Turn a step's raw output into a `StepMeasurement` (MILESTONE_D_PLAN.md §2).

Deterministic parsing only — pytest summary counts, changed paths, a normalized
error signature.
"""

from __future__ import annotations

import re

from app.services.progress.loop import normalize_error
from app.services.progress.signals import StepMeasurement

_PASSED = re.compile(r"(\d+) passed")
_FAILED = re.compile(r"(\d+) failed")
_ERRORS = re.compile(r"(\d+) errors?")


def parse_pytest_counts(output: str) -> tuple[int | None, int | None]:
    """Return (passed, failed+errors) or (None, None) if no summary line found."""
    passed = failed = 0
    found = False
    if (m := _PASSED.search(output)):
        passed, found = int(m.group(1)), True
    if (m := _FAILED.search(output)):
        failed, found = failed + int(m.group(1)), True
    if (m := _ERRORS.search(output)):
        failed, found = failed + int(m.group(1)), True
    return (passed, failed) if found else (None, None)


def measure_step(
    step_index: int,
    *,
    pytest_output: str,
    changed_paths: list[str],
    diff_text: str,
    stderr: str = "",
) -> StepMeasurement:
    passed, failed = parse_pytest_counts(pytest_output)
    total = None if passed is None else passed + (failed or 0)
    acceptance = None if passed is None else (failed == 0 and passed > 0)
    err_sig = None
    if failed:
        err_sig = normalize_error(stderr or pytest_output)
    return StepMeasurement(
        step_index=step_index,
        tests_passed=passed,
        tests_total=total,
        acceptance_met=acceptance,
        changed_paths=list(changed_paths),
        diff_text=diff_text,
        error_signature=err_sig,
    )
