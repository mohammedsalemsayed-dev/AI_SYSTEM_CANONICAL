"""Hardware telemetry seam (MILESTONE_G_PLAN.md §2, §3; MILESTONE_R_PLAN.md §2).

`HardwareMonitor` is the base seam (static `NORMAL`). `StaticHardwareMonitor`
pins a caller snapshot for tests. `LiveHardwareMonitor` (Milestone R) reads real
CPU / RAM / disk / best-effort GPU via `hardware/telemetry.py`, cached for a
short interval so a burst of `sample()` calls is one probe.
"""

from __future__ import annotations

import time

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


class LiveHardwareMonitor(HardwareMonitor):
    """Real telemetry, cached for `min_interval_s`. Never raises — a probe
    failure yields a `source="live-degraded"` snapshot."""

    def __init__(self, min_interval_s: float = 2.0, *, disk_path: str = ".") -> None:
        self.min_interval_s = min_interval_s
        self._disk_path = disk_path
        self._cached: HardwareSnapshot | None = None
        self._at = 0.0

    def sample(self) -> HardwareSnapshot:
        now = time.monotonic()
        if self._cached is None or now - self._at >= self.min_interval_s:
            from app.services.hardware.telemetry import read_telemetry

            try:
                self._cached = read_telemetry(self._disk_path)
            except Exception:  # noqa: BLE001 — defence in depth; read_telemetry already guards
                self._cached = HardwareSnapshot(source="live-degraded")
            self._at = now
        return self._cached
