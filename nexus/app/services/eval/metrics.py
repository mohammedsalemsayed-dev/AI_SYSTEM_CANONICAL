"""Derived metrics (MILESTONE_I_PLAN.md §2, design-notes §11.2).

Every metric here is folded from the event log and nothing else — no store, no
new source of truth. If this view and the log disagree, the log wins. The
desktop shell (Milestone H) consumes this output; the regression machinery uses
it to see drift.
"""

from __future__ import annotations

from app.events.log import EventKind, EventLog
from app.schemas.contracts import Metrics


def rebuild_metrics(log: EventLog, task_ids: list[str]) -> Metrics:
    per_class_total: dict[str, int] = {}
    per_class_ok: dict[str, int] = {}
    tiers: dict[str, int] = {}
    escalations = 0
    reworked = 0
    budget_exhausted = 0
    quarantines = 0
    n = 0

    for tid in task_ids:
        events = log.read(tid)
        if not events:
            continue
        n += 1

        task_class = next(
            (e.payload.get("task_class", "") for e in events if e.kind == EventKind.CONTRACT),
            "",
        ) or "unknown"
        result = next(
            (e.payload for e in reversed(events) if e.kind == EventKind.RESULT), {}
        )
        per_class_total[task_class] = per_class_total.get(task_class, 0) + 1
        if result.get("state") == "COMPLETED":
            per_class_ok[task_class] = per_class_ok.get(task_class, 0) + 1

        plan_count = 0
        task_escalations = 0
        hit_hard_budget = False
        for e in events:
            if e.kind == EventKind.VERIFICATION:
                t = e.payload.get("tier", "T0")
                tiers[t] = tiers.get(t, 0) + 1
            elif e.kind == EventKind.PLAN:
                plan_count += 1
            elif e.kind == EventKind.ESCALATION:
                task_escalations += 1
            elif e.kind == EventKind.BUDGET and e.payload.get("level") == "hard":
                hit_hard_budget = True
            elif e.kind == EventKind.EXPERIENCE_TRANSITION and e.payload.get("state") == "QUARANTINED":
                quarantines += 1

        escalations += task_escalations
        if task_escalations > 0 or plan_count > 1:
            reworked += 1
        if hit_hard_budget:
            budget_exhausted += 1

    return Metrics(
        success_rate_by_class={
            c: round(per_class_ok.get(c, 0) / per_class_total[c], 4)
            for c in per_class_total
        },
        rework_rate=round(reworked / n, 4) if n else 0.0,
        verify_tier_distribution=tiers,
        escalation_frequency=round(escalations / n, 4) if n else 0.0,
        budget_exhaustion_rate=round(budget_exhausted / n, 4) if n else 0.0,
        quarantine_events=quarantines,
        tasks=n,
    )
