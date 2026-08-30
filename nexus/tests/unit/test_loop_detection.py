"""Acceptance (Unit): structural loop detection + false-positive guards
(MILESTONE_D_PLAN.md §6)."""

from __future__ import annotations

from app.services.progress.loop import (
    LoopDetector,
    action_hash,
    diff_similarity,
    normalize_error,
)


# --- hashing / normalization ---------------------------------------- #
def test_action_hash_stable_and_arg_order_independent() -> None:
    h1 = action_hash("file.write", "/ws/a.py", {"b": 1, "a": 2})
    h2 = action_hash("file.write", "/ws/a.py", {"a": 2, "b": 1})
    assert h1 == h2
    assert h1 != action_hash("file.write", "/ws/b.py", {"a": 2, "b": 1})


def test_action_hash_normalizes_numbers_and_paths_in_args() -> None:
    h1 = action_hash("shell.run", "x", {"cmd": "pytest tests/test_a.py::t_1"})
    h2 = action_hash("shell.run", "x", {"cmd": "pytest tests/test_a.py::t_2"})
    assert h1 == h2  # digit normalized to N


def test_normalize_error_same_exception_same_signature() -> None:
    a = 'Traceback:\n  File "x.py", line 10, in f\nValueError: bad value 3'
    b = 'Traceback:\n  File "x.py", line 88, in f\nValueError: bad value 9'
    assert normalize_error(a) == normalize_error(b)


def test_normalize_error_different_exception_differs() -> None:
    a = "ValueError: nope"
    b = "KeyError: 'nope'"
    assert normalize_error(a) != normalize_error(b)
    assert normalize_error("") is None


def test_diff_similarity() -> None:
    d1 = "@@ -1 +1 @@\n-a\n+b\n"
    assert diff_similarity(d1, d1) == 1.0
    assert diff_similarity(d1, "totally different\ncontent here\n") < 0.5


# --- detector ----------------------------------------------------- #
def _rec(det, h="h", err=None, diff="", progress=False):
    return det.record(act_hash=h, error_signature=err, diff_text=diff, made_progress=progress)


def test_repeated_action_flag() -> None:
    det = LoopDetector(repeat_threshold=3, repeat_window=5)
    assert not _rec(det, "a").loop_risk
    assert not _rec(det, "a").loop_risk
    r = _rec(det, "a")
    assert r.loop_risk and "repeated_action" in r.flags


def test_repeated_action_needs_them_within_window() -> None:
    det = LoopDetector(repeat_threshold=3, repeat_window=3)
    _rec(det, "a"); _rec(det, "b"); _rec(det, "c")  # 'a' now out of the window
    _rec(det, "a"); _rec(det, "a")
    r = det.report()
    assert not r.loop_risk  # only 2 'a' in the last 3


def test_repeated_error_flag() -> None:
    det = LoopDetector(error_threshold=3)
    err = 'File "x.py", line 1, in f\nAssertionError: 1 == 2'
    _rec(det, "a", err=err, diff="d1")
    _rec(det, "b", err=err, diff="d2")
    r = _rec(det, "c", err=err, diff="d3")
    assert r.loop_risk and "repeated_error" in r.flags


def test_error_streak_broken_by_a_clean_step() -> None:
    det = LoopDetector(error_threshold=3)
    err = "ValueError: x"
    _rec(det, "a", err=err)
    _rec(det, "b", err=None)  # a step with no error clears the streak
    _rec(det, "c", err=err)
    _rec(det, "d", err=err)
    assert not det.report().loop_risk


def test_diff_thrash_flag_on_repeated_identical_diff() -> None:
    det = LoopDetector(thrash_threshold=3, thrash_similarity=0.9)
    base = "@@ -1 +1 @@\n-a = 1\n+a = 2\n"
    _rec(det, "h1", diff=base)
    _rec(det, "h2", diff=base)
    r = _rec(det, "h3", diff=base)
    assert r.loop_risk and "diff_thrash" in r.flags


def test_diff_thrash_on_mostly_identical_diff() -> None:
    det = LoopDetector(thrash_threshold=3, thrash_similarity=0.85)
    d = "\n".join(f"line {i}" for i in range(20))
    _rec(det, "h1", diff=d)
    _rec(det, "h2", diff=d.replace("line 3", "line 3x"))  # 1/20 lines differ
    r = _rec(det, "h3", diff=d.replace("line 7", "line 7x"))
    assert r.loop_risk and "diff_thrash" in r.flags


def test_no_thrash_when_diffs_diverge() -> None:
    det = LoopDetector(thrash_threshold=3)
    _rec(det, "h1", diff="a\nb\nc\n")
    _rec(det, "h2", diff="completely\ndifferent\nnow\n")
    r = _rec(det, "h3", diff="third\nunrelated\npatch\n")
    assert not r.loop_risk


def test_progress_clears_everything_no_false_positive() -> None:
    det = LoopDetector(repeat_threshold=3)
    _rec(det, "a"); _rec(det, "a")
    # the 3rd identical action, but this step made hard progress
    r = _rec(det, "a", progress=True)
    assert not r.loop_risk
    # and the history is cleared, so it takes 3 more to re-trigger
    _rec(det, "a"); _rec(det, "a")
    assert not det.report().loop_risk
