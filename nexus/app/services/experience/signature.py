"""Situation signature (MILESTONE_F_PLAN.md §2, design-notes §14.7).

`{task_class, sorted salient-constraint tags, tool set}`. Without embeddings,
retrieval matches on this signature: same task_class + overlapping tags. Kept
deliberately coarse — experiences are advisory, so a loose match costs planner
tokens, not an execution.
"""

from __future__ import annotations

import re

from app.schemas.contracts import TaskContract

# markers that meaningfully change how a task is approached
_SALIENT = (
    "auth", "security", "boundary", "off-by-one", "null", "empty", "none",
    "cache", "caching", "concurrency", "async", "migration", "regex", "parser",
    "encoding", "unicode", "float", "division", "overflow", "recursion",
    "pagination", "sort", "dict", "mutable", "default", "iterator", "generator",
    "timeout", "retry", "validation", "serialize", "json", "datetime",
)
_WORD = re.compile(r"[a-z][a-z0-9_-]{2,}")


def salient_tags(contract: TaskContract) -> set[str]:
    text = " ".join(
        [contract.objective, *contract.constraints, *contract.success_criteria]
    ).lower()
    words = set(_WORD.findall(text))
    tags = {m for m in _SALIENT if m in text}
    # a couple of derived tags
    if "not " in text or "empty" in text or "none" in text:
        tags.add("empty")
    return tags & words | tags  # keep explicit markers even if not tokenized cleanly


def situation_signature(contract: TaskContract, tools_used: list[str] | None = None) -> str:
    tags = ",".join(sorted(salient_tags(contract))) or "-"
    tools = ",".join(sorted(set(tools_used or []))) or "-"
    return f"{contract.task_class}|tags={tags}|tools={tools}"


def signatures_match(a: str, b: str, *, min_tag_overlap: int = 1) -> bool:
    """Same task_class and either has no tags or they overlap by >= min."""
    pa, pb = _parse(a), _parse(b)
    if pa["class"] != pb["class"]:
        return False
    ta, tb = pa["tags"], pb["tags"]
    if not ta or not tb:
        return True
    return len(ta & tb) >= min_tag_overlap


def _parse(sig: str) -> dict:
    parts = sig.split("|")
    cls = parts[0] if parts else ""
    tags: set[str] = set()
    for p in parts[1:]:
        if p.startswith("tags="):
            raw = p[len("tags="):]
            tags = set() if raw == "-" else set(raw.split(","))
    return {"class": cls, "tags": tags}
