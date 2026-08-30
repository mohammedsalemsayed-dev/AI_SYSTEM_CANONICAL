"""Cooperative cancellation for an in-flight desktop run.

A single process-wide flag. The UI's Stop button sets it (`request()`), the
runner clears it before each run (`arm()`), and the long-running pieces —
the local LLM proxy and the LocalBuilder tool loop — call `check()` at their
turn boundaries and raise `RunCancelled`, which the orchestrator's top-level
handler settles as a failed/cancelled task.

Leaf module: no imports from the rest of the app, so anything may import it.
"""

from __future__ import annotations

import threading


class RunCancelled(RuntimeError):
    """Raised at a cancellation checkpoint when the user asked to stop."""


_ev = threading.Event()


def arm() -> None:
    """Clear the flag — called at the start of every run."""
    _ev.clear()


def request() -> None:
    """Set the flag — called by the Stop button handler."""
    _ev.set()


def is_set() -> bool:
    return _ev.is_set()


def check() -> None:
    """Raise RunCancelled if a stop was requested. Cheap; call it freely."""
    if _ev.is_set():
        raise RunCancelled("run cancelled by user")
