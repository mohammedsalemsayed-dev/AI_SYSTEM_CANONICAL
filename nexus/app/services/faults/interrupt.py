"""Interrupt injection (MILESTONE_Q_PLAN.md §2).

Wrap an `EventLog` so that the first `append` of a named kind is written and then
`_Interrupted` is raised — simulating a process kill right after that event. The
test then builds a fresh `Orchestrator` over the same (file-backed) log and calls
`resume()`.
"""

from __future__ import annotations


class _Interrupted(BaseException):
    """Raised by the interrupt hook after a targeted event is persisted.

    Inherits `BaseException` (like `KeyboardInterrupt`) so the orchestrator's
    `except Exception` graceful-failure handler does NOT catch it — this
    simulates a hard process kill, leaving a partial log for `reconcile()`.
    """


class InterruptAfter:
    """A drop-in wrapper for `EventLog` that raises `_Interrupted` right after the
    first `append(kind == target_kind, ...)` (the event IS persisted first)."""

    def __init__(self, log, target_kind: str, *, nth: int = 1) -> None:
        self._log = log
        self._target = target_kind
        self._nth = nth
        self._seen = 0
        self.armed = True

    def append(self, task_id: str, kind: str, payload):
        ev = self._log.append(task_id, kind, payload)
        if self.armed and kind == self._target:
            self._seen += 1
            if self._seen >= self._nth:
                self.armed = False
                raise _Interrupted(f"killed right after {kind}")
        return ev

    def __getattr__(self, name):
        return getattr(self._log, name)
