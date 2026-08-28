"""Acceptance (Benchmark, offline): the standalone guardrail runner records a
baseline and gates against it (MILESTONE_I_PLAN.md §6)."""

from __future__ import annotations

from pathlib import Path

from tests.regression import run_guardrail


def test_runner_sets_baseline_then_certifies(tmp_path: Path, monkeypatch) -> None:
    # stub the per-task run so this stays a plumbing test, not 12 sandbox runs
    monkeypatch.setattr(run_guardrail, "_offline_run_one", lambda task: task.id != "pagination")
    db = str(tmp_path / "gr.db")

    assert run_guardrail.main(["--offline", "--memory", db]) == 1  # no baseline -> fail closed
    assert run_guardrail.main(["--offline", "--set-baseline", "--memory", db]) == 0
    assert run_guardrail.main(["--offline", "--memory", db]) == 0  # matches baseline now


def test_runner_flags_a_new_failure(tmp_path: Path, monkeypatch) -> None:
    db = str(tmp_path / "gr.db")
    monkeypatch.setattr(run_guardrail, "_offline_run_one", lambda task: True)
    assert run_guardrail.main(["--offline", "--set-baseline", "--memory", db]) == 0
    # now a task regresses
    monkeypatch.setattr(run_guardrail, "_offline_run_one", lambda task: task.id != "parser")
    assert run_guardrail.main(["--offline", "--memory", db]) == 1
