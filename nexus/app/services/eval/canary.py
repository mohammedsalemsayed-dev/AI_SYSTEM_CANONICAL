"""Canary cohorts (MILESTONE_I_PLAN.md §2, design-notes §8).

A promoted change (an experience, or the router switching a class to a new model)
is exercised on a small fraction of live matching tasks first, scored against the
pre-promotion baseline. A significant drop over the first `min_samples` uses is an
automatic rollback: the experience is QUARANTINED, or the routing class is frozen
back to the incumbent.
"""

from __future__ import annotations

import hashlib

from app.schemas.contracts import CanaryVerdict

FRACTION = 0.20
MIN_SAMPLES = 10
ROLLBACK_DROP_PP = 15.0


class CanaryController:
    def __init__(
        self,
        baseline_success: float,
        *,
        fraction: float = FRACTION,
        min_samples: int = MIN_SAMPLES,
        max_drop_pp: float = ROLLBACK_DROP_PP,
        seed: int | None = None,
    ) -> None:
        self.baseline_success = baseline_success
        self.fraction = fraction
        self.min_samples = min_samples
        self.max_drop_pp = max_drop_pp
        self._seed = seed or 0
        self.n = 0
        self.passed = 0
        self.done = False  # set once a terminal verdict is returned

    # -- cohort selection ---------------------------------------- #
    def sample(self, key: str) -> bool:
        """Deterministic fractional membership: the same key always lands the
        same way for a given seed, so a task is consistently in or out."""
        if self.done:
            return False
        h = hashlib.sha256(f"{self._seed}:{key}".encode()).digest()
        frac = int.from_bytes(h[:8], "big") / 2**64
        return frac < self.fraction

    # -- accounting -------------------------------------------- #
    def record(self, verified: bool) -> CanaryVerdict:
        if self.done:
            return "PROMOTE" if self._rate() * 100 >= self.baseline_success * 100 - self.max_drop_pp else "ROLLBACK"
        self.n += 1
        self.passed += int(bool(verified))
        v = self.verdict()
        if v in ("PROMOTE", "ROLLBACK"):
            self.done = True
        return v

    def verdict(self) -> CanaryVerdict:
        if self.n < self.min_samples:
            return "HOLD"
        drop_pp = (self.baseline_success - self._rate()) * 100.0
        return "ROLLBACK" if drop_pp > self.max_drop_pp else "PROMOTE"

    def _rate(self) -> float:
        return self.passed / self.n if self.n else 1.0

    def snapshot(self) -> dict:
        return {
            "n": self.n, "passed": self.passed, "rate": round(self._rate(), 3),
            "baseline": round(self.baseline_success, 3), "verdict": self.verdict(),
            "done": self.done,
        }
