"""Breadth classification (MILESTONE_J_PLAN.md §2, §6).

Reconciles the Interpreter's `code_edit_local` / `code_edit_broad` guess with the
*measured* blast radius. Advisory only — it never mutates `task_class` after
PLANNING; the Planner and the router read it.
"""

from __future__ import annotations

from app.schemas.contracts import BreadthAdvice, ImpactReport

_BROAD_FLAGS = {"wide-change", "risk-path", "public-api"}


def classify_breadth(interpreter_hint: str, impact: ImpactReport) -> BreadthAdvice:
    hint_broad = interpreter_hint == "code_edit_broad"
    flag_hits = _BROAD_FLAGS & set(impact.risk_flags)

    if hint_broad or flag_hits:
        reasons = []
        if hint_broad:
            reasons.append("interpreter classified it as code_edit_broad")
        if "wide-change" in flag_hits:
            reasons.append(f"{len(impact.dependent_modules)} dependent modules")
        if "risk-path" in flag_hits:
            reasons.append("touches a security-relevant path")
        if "public-api" in flag_hits:
            reasons.append("changes a widely-imported symbol")
        return BreadthAdvice(
            level="broad",
            why="; ".join(reasons),
            escalate_review=bool(flag_hits) or hint_broad,
        )

    return BreadthAdvice(
        level="local",
        why=f"{len(impact.dependent_modules)} dependent modules, no risk flags",
        escalate_review=False,
    )
