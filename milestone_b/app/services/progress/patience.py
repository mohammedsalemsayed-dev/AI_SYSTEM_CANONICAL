"""Per-task_class patience — how many no-hard-signal steps before the
novel-motion guard escalates (MILESTONE_D_PLAN.md §2, §7). User-extendable."""

from __future__ import annotations

_PATIENCE_BY_CLASS: dict[str, int] = {
    "debug": 6,
    "code_edit_broad": 5,
    "research_web": 4,
    "planning_arch": 4,
    "doc_analysis": 4,
    "authoring": 4,
    "code_edit_local": 3,
    "qa_explain": 2,
    "ops": 3,
}
DEFAULT = 3


def patience_for(task_class: str, *, extra: int = 0) -> int:
    return _PATIENCE_BY_CLASS.get(task_class, DEFAULT) + max(0, extra)
