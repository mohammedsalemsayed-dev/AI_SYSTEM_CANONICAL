"""Routing stats over the system memory tier (design-notes §7.2).

A `ModelRunRecord` is ingested here **only if** its verification link is a
`VerificationRecord` at tier >= T1 — unverified runs are logged elsewhere, not
scored. Among scored runs, per `(task_class, model)`:

  * verified-success rate (fraction whose verification `overall == "pass"`),
  * median + p90 latency, median resource cost, median estimated cost,

over the trailing 90 days OR the last 50 scored runs, whichever is smaller. A
model is *eligible* for a class at >= 20 scored runs; below that the static table
governs and the router explores.
"""

from __future__ import annotations

import json
import time

from app.schemas.contracts import MemoryRecord, ModelRunRecord

WINDOW_DAYS = 90
WINDOW_RUNS = 50
ELIGIBLE_MIN_RUNS = 20
_SCORED_TIERS = ("T1", "T2", "T3")


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[len(s) // 2]


def _p90(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))]


class RouteStatsStore:
    def __init__(self, memory) -> None:
        self._memory = memory

    # -- ingest ------------------------------------------------------ #
    def ingest(
        self,
        run: ModelRunRecord,
        *,
        task_class: str,
        verification_tier: str | None,
        verification_pass: bool,
    ) -> bool:
        """Return True if the run was scored (T1+ verification link), else False."""
        if verification_tier not in _SCORED_TIERS:
            return False
        model = run.model or run.provider
        payload = {
            "task_class": task_class,
            "model": model,
            "provider": run.provider,
            "role": run.role,
            "latency_s": run.latency_s,
            "cost_usd": 0.0,
            "resource_cost": 0.0,
            "passed": bool(verification_pass),
            "tier": verification_tier,
            "ts": time.time(),
        }
        self._memory.put(
            MemoryRecord(
                tier="system", kind="model_run",
                scope=f"{task_class}:{model}", trust="workspace",
                content=json.dumps(payload),
            )
        )
        return True

    # -- read ------------------------------------------------------- #
    def _scored_runs(self, task_class: str, model: str) -> list[dict]:
        scope = f"{task_class}:{model}"
        rows = [
            json.loads(m.content)
            for m in self._memory.all(tier="system")
            if m.kind == "model_run" and m.scope == scope
        ]
        cutoff = time.time() - WINDOW_DAYS * 86400
        rows = [r for r in rows if r.get("ts", 0) >= cutoff]
        rows.sort(key=lambda r: r.get("ts", 0))
        return rows[-WINDOW_RUNS:]

    def count(self, task_class: str, model: str) -> int:
        return len(self._scored_runs(task_class, model))

    def eligible(self, task_class: str, model: str) -> bool:
        return self.count(task_class, model) >= ELIGIBLE_MIN_RUNS

    def aggregate(self, task_class: str, model: str) -> dict:
        runs = self._scored_runs(task_class, model)
        n = len(runs)
        if n == 0:
            return {"n": 0, "success_rate": 0.0, "latency_median": 0.0,
                    "latency_p90": 0.0, "resource_median": 0.0, "cost_median": 0.0}
        return {
            "n": n,
            "success_rate": sum(1 for r in runs if r.get("passed")) / n,
            "latency_median": _median([r.get("latency_s", 0.0) for r in runs]),
            "latency_p90": _p90([r.get("latency_s", 0.0) for r in runs]),
            "resource_median": _median([r.get("resource_cost", 0.0) for r in runs]),
            "cost_median": _median([r.get("cost_usd", 0.0) for r in runs]),
        }

    # -- canary freeze (Milestone I) ---------------------------- #
    def freeze(self, task_class: str, model: str, *, reason: str = "") -> None:
        self._memory.put(
            MemoryRecord(
                tier="system", kind="route_freeze", scope=f"{task_class}:{model}",
                trust="workspace", content=json.dumps({"reason": reason, "ts": time.time()}),
            )
        )

    def is_frozen(self, task_class: str, model: str) -> bool:
        scope = f"{task_class}:{model}"
        return any(
            m.kind == "route_freeze" and m.scope == scope
            for m in self._memory.all(tier="system")
        )

    def eligible_models(self, task_class: str) -> list[str]:
        seen: set[str] = set()
        for m in self._memory.all(tier="system"):
            if m.kind != "model_run" or not m.scope.startswith(f"{task_class}:"):
                continue
            seen.add(m.scope.split(":", 1)[1])
        return [mdl for mdl in sorted(seen) if self.eligible(task_class, mdl)]
