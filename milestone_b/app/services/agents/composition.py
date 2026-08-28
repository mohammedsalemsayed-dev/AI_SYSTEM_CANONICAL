"""Which roles run for this task (MILESTONE_E_PLAN.md §2, D1).

Start from {builder}. Add a role when:
  (a) its RolePerformance §9 criterion was met for this task_class, OR
  (b) the task explicitly requests it, OR
  (c) an escalation-ladder step invoked it, OR
  (d) hardware mode permits (Milestone G; here always true).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.contracts import TaskContract
from app.services.agents.performance import RolePerformanceStore

_EXPLICIT_MARKERS = {
    "critic": ("second opinion", "review it", "double check", "critique"),
    "researcher": ("look up", "research", "find out", "check the docs"),
}


@dataclass
class Composition:
    roles: set[str] = field(default_factory=lambda: {"builder"})
    reasons: dict[str, str] = field(default_factory=dict)


def select_roles(
    contract: TaskContract,
    *,
    explicit: set[str] | None = None,
    ladder_invoked: set[str] | None = None,
    role_perf: RolePerformanceStore | None = None,
) -> Composition:
    comp = Composition()
    explicit = explicit or set()
    ladder_invoked = ladder_invoked or set()
    req = (contract.original_request or "").lower()

    for role in ("critic", "researcher"):
        if role in explicit:
            comp.roles.add(role)
            comp.reasons[role] = "explicitly requested"
        elif any(m in req for m in _EXPLICIT_MARKERS[role]):
            comp.roles.add(role)
            comp.reasons[role] = "request phrasing"
        elif role in ladder_invoked:
            comp.roles.add(role)
            comp.reasons[role] = "escalation ladder"
        elif role_perf is not None and role_perf.meets_promotion_criterion(
            role, contract.task_class
        ):
            comp.roles.add(role)
            comp.reasons[role] = "promoted (beats baseline for this task_class)"

    return comp
