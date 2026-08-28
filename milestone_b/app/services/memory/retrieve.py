"""Scoped, trust-filtered retrieval (MILESTONE_F_PLAN.md §2, §12, §14.7).

Keyword + recency + tier + trust filter. No embeddings — that is CD-rag.
`QUARANTINED` experience is never returned; `STALE` only with `include_stale=True`.
"""

from __future__ import annotations

import re

from app.schemas.contracts import MemoryRecord
from app.services.memory.store import MemoryStore

_TRUST_RANK = {
    "user": 0, "workspace": 1, "tool_output": 2, "retrieved_web": 3, "doc_input": 3,
}
_WORD = re.compile(r"[a-z0-9_]{3,}")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _score(record: MemoryRecord, query_tokens: set[str], task_class: str | None) -> float:
    ctoks = _tokens(record.content)
    overlap = len(query_tokens & ctoks)
    if not overlap and record.kind not in ("decision", "constraint", "open_question"):
        return 0.0
    score = float(overlap)
    if task_class and record.scope in (task_class, "global"):
        score += 0.5
    # decisions / constraints are always relevant context, lightly boosted
    if record.kind in ("decision", "constraint", "open_question"):
        score += 1.0
    return score


def retrieve(
    store: MemoryStore,
    query: str,
    *,
    tiers: tuple[str, ...] = ("project", "experience", "system"),
    task_class: str | None = None,
    trust_min: str = "workspace",
    k: int = 8,
    include_stale: bool = False,
) -> list[MemoryRecord]:
    max_rank = _TRUST_RANK.get(trust_min, 1)
    qtoks = _tokens(query)
    hits: list[tuple[float, MemoryRecord]] = []

    for tier in tiers:
        for rec in store.all(tier=tier):
            if _TRUST_RANK.get(rec.trust, 1) > max_rank:
                continue  # too untrusted for this retrieval
            if rec.kind == "experience_state":
                state = rec.content.split(":", 1)[0]
                if state == "QUARANTINED":
                    continue
                if state == "STALE" and not include_stale:
                    continue
            s = _score(rec, qtoks, task_class)
            if s > 0:
                # tiny recency tiebreak
                hits.append((s + rec.ts * 1e-12, rec))

    hits.sort(key=lambda h: h[0], reverse=True)
    return [r for _, r in hits[:k]]
