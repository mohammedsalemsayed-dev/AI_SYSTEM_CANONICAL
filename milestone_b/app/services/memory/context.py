"""Context builder (MILESTONE_F_PLAN.md §2).

Assembles the working context handed to the Interpreter and Planner: active
project decisions, constraints, open questions, an artifact index, and scoped
retrieval hits for the request. Replaces the empty project memory the slice
used to pass.
"""

from __future__ import annotations

from app.services.memory.retrieve import retrieve
from app.services.memory.store import MemoryStore

_KIND_HEADER = {
    "decision": "ACTIVE DECISIONS",
    "constraint": "CONSTRAINTS",
    "open_question": "OPEN QUESTIONS",
    "artifact_index": "ARTIFACT INDEX",
}


def build_context(
    store: MemoryStore | None,
    request_text: str,
    *,
    task_class: str | None = None,
    max_hits: int = 6,
) -> str:
    if store is None:
        return ""

    sections: list[str] = []

    project = store.all(tier="project")
    for kind, header in _KIND_HEADER.items():
        items = [m.content for m in project if m.kind == kind]
        if items:
            sections.append(header + ":\n" + "\n".join(f"- {c}" for c in items))

    hits = retrieve(
        store, request_text,
        tiers=("project", "experience", "system"),
        task_class=task_class, k=max_hits,
    )
    # drop hits already shown as decisions/constraints
    shown = {m.content for m in project}
    extra = [h for h in hits if h.content not in shown]
    if extra:
        sections.append(
            "POSSIBLY RELEVANT (from memory):\n"
            + "\n".join(f"- [{h.tier}/{h.kind}] {h.content}" for h in extra)
        )

    if not sections:
        return ""
    return "PROJECT MEMORY\n" + "\n\n".join(sections)
