"""Hardware telemetry seam (MILESTONE_G_PLAN.md §2, §3).

Real GPU temperature / VRAM / power sampling is deferred. On this machine the
monitor returns a static `NORMAL` snapshot, so the mode policy and the router's
pause / bias paths are exercised only with an injected snapshot (tests do this).
The interface is what later telemetry plugs into — nothing above this changes.
"""

from __future__ import annotations

from app.schemas.contracts import HardwareSnapshot


class HardwareMonitor:
    """Base seam: always-idle static snapshot."""

    def sample(self) -> HardwareSnapshot:
        return HardwareSnapshot(source="static")


class StaticHardwareMonitor(HardwareMonitor):
    """A monitor pinned to a caller-supplied snapshot — for tests and for
    forcing a mode (e.g. a user 'quiet mode' toggle) until real telemetry lands.
    """

    def __init__(self, snapshot: HardwareSnapshot) -> None:
        self._snapshot = snapshot

    def sample(self) -> HardwareSnapshot:
        return self._snapshot
