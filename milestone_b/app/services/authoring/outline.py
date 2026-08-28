"""Outline (MILESTONE_M_PLAN.md §2).

A heading tree from the brief. If a KB is attached, each section's gist is checked
against a retrieval so the outline only promises what the library can support.
"""

from __future__ import annotations

from app.llm.base import LLM
from app.llm.parse import parse_json_object
from app.services.authoring.model import DocumentModel, Section

MIN_SECTIONS = 3
MAX_SECTIONS = 8
SUPPORT_MIN_SCORE = 0.1

_SYSTEM = """You produce a document outline from a brief. Return 3-8 top-level sections,
each optionally with 1-3 sub-sections. Reply with ONLY JSON:
{"title": string,
 "sections": [{"title": string, "gist": string,
               "children": [{"title": string, "gist": string}]}]}"""


def outline(
    brief: str,
    llm: LLM,
    *,
    kb=None,
    memory_ctx: str = "",
    kind: str = "report",
) -> DocumentModel:
    doc = DocumentModel(kind=kind if kind in ("report", "doc", "deck") else "report")
    if not brief.strip():
        doc.title = "Untitled"
        doc.sections = [Section(title="Overview", level=1)]
        doc.flags.append("empty-brief")
        return doc

    prompt = f"BRIEF:\n{brief}\n"
    if memory_ctx:
        prompt += f"\nPROJECT CONTEXT (constraints/decisions to honour):\n{memory_ctx}\n"
    prompt += "\nReturn the JSON."
    try:
        parsed = parse_json_object(llm.complete(system=_SYSTEM, prompt=prompt).text)
    except Exception:
        parsed = {}

    doc.title = str(parsed.get("title") or brief.strip().split("\n")[0][:80] or "Untitled")
    raw = parsed.get("sections") or []
    for s in raw[:MAX_SECTIONS]:
        sec = _mk_section(s, level=1)
        sec.children = [_mk_section(c, level=2) for c in (s.get("children") or [])[:3]]
        doc.sections.append(sec)
    if len(doc.sections) < MIN_SECTIONS:
        doc.sections += [
            Section(title=t, level=1)
            for t in ("Introduction", "Details", "Conclusion")[: MIN_SECTIONS - len(doc.sections)]
        ]

    if kb is not None:
        _flag_unsupported(doc, kb)
    return doc


def _mk_section(s: dict, *, level: int) -> Section:
    return Section(title=str(s.get("title") or "Section").strip(),
                   level=level, gist=str(s.get("gist") or "").strip())


def _flag_unsupported(doc: DocumentModel, kb) -> None:
    from app.services.kb.retrieve import LexicalRetriever

    r = LexicalRetriever(kb)
    for sec in doc.walk():
        probe = f"{sec.title} {sec.gist}".strip()
        hits = r.retrieve(probe, k=3)
        if not hits or hits[0].score < SUPPORT_MIN_SCORE:
            sec.flags.append("unsupported-section")
            doc.flags.append(f"unsupported-section:{sec.title}")
