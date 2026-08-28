"""Question decomposition (MILESTONE_K_PLAN.md §2).

Split a research question into a small set of independently-answerable
sub-questions. One bounded LLM call; a trivial question passes through as a
single sub-question.
"""

from __future__ import annotations

from app.llm.base import LLM
from app.llm.parse import parse_json_object

MAX_SUBQ = 5

_SYSTEM = """You break a research question into 2-5 specific, independently answerable
sub-questions. If the question is already narrow, return it unchanged as the only item.
Reply with ONLY JSON: {"sub_questions": [string, ...]}."""


def decompose(question: str, llm: LLM) -> list[str]:
    q = question.strip()
    if not q:
        return []
    try:
        resp = llm.complete(system=_SYSTEM, prompt=f"QUESTION:\n{q}\n\nReturn the JSON.")
        subs = [str(s).strip() for s in parse_json_object(resp.text).get("sub_questions", [])]
        subs = [s for s in subs if s][:MAX_SUBQ]
    except Exception:
        subs = []
    return subs or [q]
