"""Acceptance (Unit): ProgressService classification over a step history
(MILESTONE_D_PLAN.md §6, §7)."""

from __future__ import annotations

from app.services.progress.service import ProgressService
from app.services.progress.signals import StepMeasurement


def step(i, **kw) -> StepMeasurement:
    return StepMeasurement(step_index=i, **kw)


def test_progress_signal_gives_healthy_and_resets_run() -> None:
    svc = ProgressService("t", patience_steps=2)
    svc.observe(step(0, tests_passed=0, tests_total=2))
    e1 = svc.observe(step(1, tests_passed=0, tests_total=2, changed_paths=["a.py"]))
    assert e1.classification == "HEALTHY_PROGRESS"  # file touch is a signal
    e2 = svc.observe(step(2, tests_passed=1, tests_total=2, changed_paths=["a.py"]))
    assert e2.classification == "HEALTHY_PROGRESS"
    assert "tests_passed_up" in e2.signals
    assert e2.no_progress_run == 0


def test_novel_motion_slow_then_stalled() -> None:
    svc = ProgressService("t", patience_steps=2)
    svc.observe(step(0, tests_passed=0))
    # steps that keep editing the same file, no test/behaviour delta
    cls = []
    for i in range(1, 7):
        cls.append(svc.observe(step(i, changed_paths=["a.py"], diff_text="x")).classification)
    # K=2: runs 1,2 -> HEALTHY; 3,4 (>=K) -> SLOW; 5,6 (>=2K) -> STALLED
    assert cls == [
        "HEALTHY_PROGRESS",
        "HEALTHY_PROGRESS",
        "SLOW_PROGRESS",
        "SLOW_PROGRESS",
        "STALLED",
        "STALLED",
    ]


def test_no_motion_stalls_faster() -> None:
    svc = ProgressService("t", patience_steps=3)
    svc.observe(step(0))
    e1 = svc.observe(step(1))  # nothing changed at all
    e2 = svc.observe(step(2))
    e3 = svc.observe(step(3))
    assert e1.classification == "SLOW_PROGRESS"
    assert e2.classification == "SLOW_PROGRESS"
    assert e3.classification == "STALLED"  # run >= K with no motion


def test_recovery_after_progress_resets_the_clock() -> None:
    svc = ProgressService("t", patience_steps=2)
    svc.observe(step(0, error_count=5))
    svc.observe(step(1, error_count=5, changed_paths=["a.py"], diff_text="x"))
    svc.observe(step(2, error_count=5, changed_paths=["a.py"], diff_text="x"))
    slow = svc.observe(step(3, error_count=5, changed_paths=["a.py"], diff_text="x"))
    assert slow.classification == "SLOW_PROGRESS"
    good = svc.observe(step(4, error_count=2, changed_paths=["a.py"]))  # errors_down
    assert good.classification == "HEALTHY_PROGRESS"
    assert good.no_progress_run == 0
    nxt = svc.observe(step(5, error_count=2, changed_paths=["a.py"], diff_text="x"))
    assert nxt.classification == "HEALTHY_PROGRESS"


def test_loop_flag_overrides() -> None:
    svc = ProgressService("t")
    svc.observe(step(0))
    e = svc.observe(step(1, tests_passed=99), loop_flag=True)
    assert e.classification == "LOOP_RISK"


def test_resource_flag_overrides() -> None:
    svc = ProgressService("t")
    svc.observe(step(0))
    e = svc.observe(step(1), resource_flag=True)
    assert e.classification == "RESOURCE_LIMITED"


def test_event_carries_task_id_and_detail() -> None:
    svc = ProgressService("task_xyz")
    e = svc.observe(step(0, error_count=3))
    svc_e = svc.observe(step(1, error_count=1))
    assert svc_e.task_id == "task_xyz"
    assert "errors_down" in svc_e.detail
