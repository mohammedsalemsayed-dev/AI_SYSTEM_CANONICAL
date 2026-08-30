"""Acceptance (Unit): `validate_contract` enforces the INTERPRETING gate —
objective + >=1 success criterion + a required_evidence entry naming a runnable
pytest T0 target (design-notes sections 1 and 5)."""

from __future__ import annotations

import pytest

from app.schemas.contracts import TaskContract, validate_contract


def _contract(**overrides) -> TaskContract:
    base = dict(
        task_id="t1",
        original_request="fix the bug",
        objective="make tests/test_math.py::test_add pass",
        success_criteria=["test_add passes"],
        required_evidence=["T0: pytest tests/test_math.py::test_add passes"],
    )
    base.update(overrides)
    return TaskContract(**base)


def test_valid_contract_has_no_problems() -> None:
    assert validate_contract(_contract()) == []


def test_empty_objective_is_a_problem() -> None:
    problems = validate_contract(_contract(objective="   "))
    assert any("objective" in p for p in problems)


def test_missing_success_criteria_is_a_problem() -> None:
    problems = validate_contract(_contract(success_criteria=[]))
    assert any("success_criteria" in p for p in problems)


def test_missing_required_evidence_is_a_problem() -> None:
    problems = validate_contract(_contract(required_evidence=[]))
    assert any("required_evidence" in p for p in problems)


@pytest.mark.parametrize(
    "evidence",
    [
        ["make it work"],
        ["T0: run the tests"],            # says T0 but no `pytest <target>`
        ["pytest tests/test_x.py"],       # runnable target but not marked T0
        ["verify manually that it passes"],
    ],
)
def test_evidence_without_a_pytest_t0_target_is_a_problem(evidence) -> None:
    problems = validate_contract(_contract(required_evidence=evidence))
    assert any("no runnable T0 target" in p for p in problems)


@pytest.mark.parametrize(
    "evidence",
    [
        ["T0: pytest tests/test_math.py::test_add passes"],
        ["t0 - pytest tests/ passes"],
        ["Other note", "T0: pytest -k test_add tests/test_math.py"],
    ],
)
def test_evidence_with_a_pytest_t0_target_passes(evidence) -> None:
    assert validate_contract(_contract(required_evidence=evidence)) == []


@pytest.mark.parametrize(
    "evidence",
    [
        ["T0: android gradle :app:testDebugUnitTest passes"],
        ["T0: gradle test passes"],
    ],
)
def test_gradle_t0_targets_are_accepted(evidence) -> None:
    # the desktop runner swaps in AndroidVerifier for a Gradle project — its
    # evidence lines must not be rejected as unverifiable
    assert validate_contract(_contract(required_evidence=evidence)) == []


def test_multiple_problems_are_all_reported() -> None:
    problems = validate_contract(
        _contract(objective="", success_criteria=[], required_evidence=[])
    )
    assert len(problems) == 3
