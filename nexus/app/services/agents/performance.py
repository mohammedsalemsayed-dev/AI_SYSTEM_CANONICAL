"""RolePerformance shadow tracking (MILESTONE_E_PLAN.md §2, design-notes §9).

Accumulates per-(role, task_class) outcome deltas from shadow / A-B runs so the
composition rule can decide whether a role has earned "default". In-memory for
the slice; the numbers are the §9 promotion criteria.
"""

from __future__ import annotations

from app.schemas.contracts import RolePerformance

# §9 promotion criteria (starting values)
CRITIC_SUCCESS_DELTA = 0.05  # verified success +>= 5 pts
CRITIC_DEFECT_RATE = 0.10  # OR >= 1 real defect caught per 10 tasks
SHADOW_WINDOW = 30  # samples before a promote decision is trusted


class RolePerformanceStore:
    """Per-`(role, task_class)` shadow outcomes. In-process by default; pass a
    `MemoryStore` (Milestone F day 13) to persist to system memory so the
    composition rule reads accumulated performance across runs."""

    def __init__(self, memory=None) -> None:
        self._by_key: dict[tuple[str, str], RolePerformance] = {}
        self._memory = memory

    def _get(self, role: str, task_class: str) -> RolePerformance:
        key = (role, task_class)
        if key not in self._by_key:
            hydrated = None
            if self._memory is not None:
                payload = self._memory.latest_role_perf(role, task_class)
                if payload is not None:
                    hydrated = RolePerformance.model_validate(payload)
            self._by_key[key] = hydrated or RolePerformance(role=role, task_class=task_class)
        return self._by_key[key]

    def _persist(self, rp: RolePerformance) -> None:
        if self._memory is not None:
            self._memory.record_role_perf(
                rp.role, rp.task_class, rp.model_dump(mode="json")
            )

    def record(
        self,
        role: str,
        task_class: str,
        *,
        baseline_pass: bool,
        with_role_pass: bool,
        defect_caught: bool = False,
        rework_delta: float = 0.0,
    ) -> RolePerformance:
        rp = self._get(role, task_class)
        n = rp.samples
        rp.baseline_success = (rp.baseline_success * n + (1.0 if baseline_pass else 0.0)) / (n + 1)
        rp.with_role_success = (rp.with_role_success * n + (1.0 if with_role_pass else 0.0)) / (n + 1)
        rp.rework_delta = (rp.rework_delta * n + rework_delta) / (n + 1)
        rp.defects_caught += int(defect_caught)
        rp.samples = n + 1
        self._persist(rp)
        return rp

    def get(self, role: str, task_class: str) -> RolePerformance | None:
        return self._by_key.get((role, task_class))

    def meets_promotion_criterion(self, role: str, task_class: str) -> bool:
        rp = self._by_key.get((role, task_class))
        if rp is None or rp.samples < 5:  # need at least a few samples
            return False
        success_delta = rp.with_role_success - rp.baseline_success
        defect_rate = rp.defects_caught / rp.samples
        return success_delta >= CRITIC_SUCCESS_DELTA or defect_rate >= CRITIC_DEFECT_RATE

    def snapshot(self) -> list[RolePerformance]:
        return list(self._by_key.values())
