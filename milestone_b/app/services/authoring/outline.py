"""Outline (MILESTONE_M_PLAN.md §2).

A heading tree from the brief. If a KB is attached, each section's gist is checked
against a retrieval so the outline only promises what the library can support.
"""

from __future__ import annotations

import re

from app.llm.base import LLM
from app.llm.parse import parse_json_object
from app.services.authoring.model import DocumentModel, Section

MIN_SECTIONS = 3
MAX_SECTIONS = 8
SUPPORT_MIN_SCORE = 0.1

_SYSTEM = """You produce a document outline (report, doc, or slide deck) from a brief.

- "title": a clean, specific title for the deliverable — NOT a restatement of the
  instruction. ("The Benefits of Unit Testing", not "Create a PowerPoint about ...").
- "sections": 4-7 top-level sections (for a deck, each is one slide topic). Each has
  a short "gist" (one line of what the section covers). 0-3 "children" for a report.

Reply with ONLY this JSON, no prose:
{"title": string,
 "sections": [{"title": string, "gist": string,
               "children": [{"title": string, "gist": string}]}]}

Example for "make a deck about unit testing benefits":
{"title":"Why Unit Testing Pays Off",
 "sections":[
   {"title":"What Unit Testing Is","gist":"small isolated checks on individual functions","children":[]},
   {"title":"Catching Bugs Early","gist":"failures surface at the smallest scope, cheapest to fix","children":[]},
   {"title":"Safer Refactoring","gist":"a green suite is a licence to change code with confidence","children":[]},
   {"title":"Living Documentation","gist":"tests show intended behaviour by example","children":[]},
   {"title":"Faster Feedback","gist":"seconds, not a manual click-through","children":[]}]}"""


_LEAD_RE = re.compile(
    r"^\s*(please\s+)?(can you\s+)?(make|create|build|write|draft|generate|produce|prepare|put together)\s+"
    r"(me\s+)?(a|an|the)\s+(short\s+|quick\s+|brief\s+|simple\s+)?"
    r"(word\s+doc(ument)?|powerpoint|power\s?point|ppt(x)?|presentation|slide\s?deck|deck|report|doc(ument)?|pdf|essay|memo|proposal)\s*"
    r"(presentation\s+)?(about|on|for|covering|explaining|regarding|re:?)\s+",
    re.IGNORECASE,
)


def _clean_title(brief: str) -> str:
    """Best-effort title from a brief when the model didn't give one:
    strip the "make me a deck about ..." shell, trim trailing slide counts."""
    t = _LEAD_RE.sub("", brief.strip().split("\n")[0])
    t = re.sub(r"[,;]?\s*(with|in)\s+\d+\s*[-–]?\s*\d*\s*(slides?|pages?|sections?).*$", "", t, flags=re.IGNORECASE)
    t = t.strip(" .\"'")
    if not t:
        return "Untitled"
    return (t[:1].upper() + t[1:])[:90]


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

    raw_title = str(parsed.get("title") or "").strip()
    # reject a "title" that just echoes the instruction
    if not raw_title or _LEAD_RE.search(raw_title) or raw_title.lower() in brief.lower()[:len(raw_title) + 8]:
        raw_title = _clean_title(brief)
    doc.title = raw_title or "Untitled"
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
