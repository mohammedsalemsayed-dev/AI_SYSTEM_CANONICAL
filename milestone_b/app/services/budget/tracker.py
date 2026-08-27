"""Cost / latency budget (DESIGN_TIGHTENING §11.1, MILESTONE_D_PLAN.md §2).

Dimensions: `wall_clock_s`, `steps`, `model_cost_usd`. The Interpreter fills
defaults per task_class; the user may override. On the subscription path
`model_cost_usd` is unmetered, so `steps` and `wall_clock_s` do the work.

At 80% of any dimension the orchestrator emits a BUDGET decision point; at 100%
it pauses the task (WAITING_FOR_USER) with a spend summary. Admission rejects a
step that would push a dimension past 100%.
"""

from __future__ import annotations

import time

_DEFAULTS: dict[str, dict[str, float]] = {
    "code_edit_local": {"wall_clock_s": 300, "steps": 8, "model_cost_usd": 0.50},
    "code_edit_broad": {"wall_clock_s": 1200, "steps": 16, "model_cost_usd": 2.00},
    "debug": {"wall_clock_s": 900, "steps": 12, "model_cost_usd": 1.50},
    "research_web": {"wall_clock_s": 900, "steps": 12, "model_cost_usd": 1.50},
    "authoring": {"wall_clock_s": 900, "steps": 10, "model_cost_usd": 1.00},
    "qa_explain": {"wall_clock_s": 120, "steps": 3, "model_cost_usd": 0.20},
    "planning_arch": {"wall_clock_s": 600, "steps": 4, "model_cost_usd": 2.00},
    "doc_analysis": {"wall_clock_s": 300, "steps": 4, "model_cost_usd": 0.50},
    "ops": {"wall_clock_s": 600, "steps": 8, "model_cost_usd": 0.50},
}
_FALLBACK = {"wall_clock_s": 300, "steps": 8, "model_cost_usd": 0.50}

SOFT = 0.8
HARD = 1.0


def default_budget(task_class: str) -> dict[str, float]:
    return dict(_DEFAULTS.get(task_class, _FALLBACK))


class BudgetTracker:
    def __init__(self, budget: dict[str, float] | None, task_class: str = "") -> None:
        self.limits = dict(budget) if budget else default_budget(task_class)
        self._start = time.monotonic()
        self.steps = 0
        self.model_cost_usd = 0.0

    def add_step(self) -> None:
        self.steps += 1

    def add_cost(self, usd: float) -> None:
        self.model_cost_usd += max(0.0, usd)

    def spent(self) -> dict[str, float]:
        return {
            "wall_clock_s": round(time.monotonic() - self._start, 1),
            "steps": float(self.steps),
            "model_cost_usd": round(self.model_cost_usd, 4),
        }

    def fractions(self) -> dict[str, float]:
        spent = self.spent()
        out: dict[str, float] = {}
        for dim, limit in self.limits.items():
            if limit and limit > 0:
                out[dim] = spent.get(dim, 0.0) / limit
        return out

    def peak_fraction(self) -> float:
        fr = self.fractions()
        return max(fr.values()) if fr else 0.0

    def over_soft(self) -> bool:
        return self.peak_fraction() >= SOFT

    def over_hard(self) -> bool:
        return self.peak_fraction() >= HARD

    def would_exceed(self, *, extra_steps: int = 1) -> bool:
        spent = self.spent()
        for dim, limit in self.limits.items():
            if not limit:
                continue
            projected = spent.get(dim, 0.0) + (extra_steps if dim == "steps" else 0.0)
            if projected > limit:
                return True
        return False

    def summary(self) -> str:
        parts = []
        spent = self.spent()
        for dim, limit in self.limits.items():
            parts.append(f"{dim} {spent.get(dim, 0.0):g}/{limit:g}")
        return ", ".join(parts)
