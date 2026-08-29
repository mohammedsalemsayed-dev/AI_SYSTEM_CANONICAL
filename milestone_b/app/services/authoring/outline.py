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
MAX_SECTIONS = 14
SUPPORT_MIN_SCORE = 0.1

# "an 8-slide deck", "a 5 page report", "10 slides", "three sections"
_COUNT_RE = re.compile(
    r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"[\s-]*(slide|page|section|chapter|part)s?\b",
    re.IGNORECASE,
)
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_CONTEXT_RE = re.compile(r"\[(?:Session context|This is an?)[^\]]*\][^\n]*\n?", re.IGNORECASE)


def _strip_context(brief: str) -> str:
    """Drop the orchestrator's [Session context …] / [This is a … project] preamble
    so it can't leak into the title or section topics."""
    return _CONTEXT_RE.sub("", brief or "").strip()


def _wanted_count(brief: str) -> int | None:
    m = _COUNT_RE.search(brief or "")
    if not m:
        return None
    tok = m.group(1).lower()
    n = int(tok) if tok.isdigit() else _WORDNUM.get(tok)
    return max(MIN_SECTIONS, min(MAX_SECTIONS, n)) if n else None

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
    r"^\s*(please\s+)?(can you\s+)?"
    r"(make|create|build|write|draft|generate|produce|prepare|put together|export|give me)\s+"
    r"(me\s+)?(a|an|the)\s+(short\s+|quick\s+|brief\s+|simple\s+|one[\s-]page\s+)?"
    r"(?:(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)[\s-]*"
    r"(?:slide|page|section|part)s?\s+)?"
    r"(word\s+doc(ument)?|word\s+report|powerpoint|power\s?point|ppt(x)?|presentation|"
    r"slide\s?deck|deck|report|doc(ument)?|pdf(\s+brief)?|brief|essay|memo|proposal)\s*"
    r"(presentation\s+)?(about|on|for|covering|explaining|regarding|re:?|summaris(?:e|ing)|summariz(?:e|ing))\s+",
    re.IGNORECASE,
)


def _clean_title(brief: str) -> str:
    """Best-effort title from a brief when the model didn't give one:
    strip the "make me a deck about ..." shell, trim trailing slide counts and
    instruction tails ("using a dark theme, based on spec.md, building on ...")."""
    t = _strip_context(brief).split("\n")[0].strip()
    t = _LEAD_RE.sub("", t)
    t = re.sub(r"[,;]?\s*(with|in)\s+\d+\s*[-–]?\s*\d*\s*(slides?|pages?|sections?).*$", "", t, flags=re.IGNORECASE)
    # drop trailing instruction clauses that aren't part of the topic
    t = re.split(
        r"[,;]?\s+(?:using|with|in|as|via)\s+(?:a\s+|an\s+|the\s+)?(?:[\w-]+\s+){1,3}"
        r"(?:theme|style|format|template|palette|aesthetic|look|vibe)\b",
        t, maxsplit=1, flags=re.IGNORECASE,
    )[0]
    t = re.split(r"[,;]?\s+(?:based on|building on|drawing on|per|according to|from the)\b",
                 t, maxsplit=1, flags=re.IGNORECASE)[0]
    t = re.split(r"[,;]?\s+and\s+(?:building|drawing|based)\b", t, maxsplit=1, flags=re.IGNORECASE)[0]
    # trailing ", corporate theme" / "- minimalist style"
    t = re.sub(r"[,;]?\s*[-–]?\s*(?:[\w-]+\s+){1,2}(?:theme|style|palette|aesthetic)\s*$", "", t, flags=re.IGNORECASE)
    t = t.strip(" .\"'-–")
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
    brief = _strip_context(brief)
    if not brief.strip():
        doc.title = "Untitled"
        doc.sections = [Section(title="Overview", level=1)]
        doc.flags.append("empty-brief")
        return doc

    want = _wanted_count(brief)                 # "8-slide deck" -> 8, else None
    target = want or (5 if doc.kind == "deck" else 4)

    def _ask(extra: str = "") -> dict:
        prompt = f"BRIEF:\n{brief}\n"
        if memory_ctx:
            prompt += f"\nPROJECT CONTEXT (constraints/decisions to honour):\n{memory_ctx}\n"
        prompt += (
            f"\nProduce EXACTLY {target} top-level sections, each with a non-empty one-line "
            f"\"gist\". {extra}\nReturn the JSON."
        )
        try:
            return parse_json_object(llm.complete(system=_SYSTEM, prompt=prompt).text)
        except Exception:  # noqa: BLE001
            return {}

    parsed = _ask()
    secs = [s for s in (parsed.get("sections") or []) if str(s.get("title") or "").strip()]
    # one retry if the model under-delivered or left gists blank
    if len(secs) < max(MIN_SECTIONS, target - 1) or sum(1 for s in secs if str(s.get("gist") or "").strip()) < len(secs) // 2:
        parsed2 = _ask("Your last outline was too short or had empty gists — do not repeat that.")
        secs2 = [s for s in (parsed2.get("sections") or []) if str(s.get("title") or "").strip()]
        if len(secs2) > len(secs):
            parsed, secs = parsed2, secs2

    raw_title = str(parsed.get("title") or "").strip()
    if not raw_title or _LEAD_RE.search(raw_title) or raw_title.lower() in brief.lower()[:len(raw_title) + 8]:
        raw_title = _clean_title(brief)
    doc.title = raw_title or "Untitled"

    for s in secs[:MAX_SECTIONS]:
        sec = _mk_section(s, level=1)
        # a blank gist -> synthesise one so the drafter has a handle
        if not sec.gist:
            sec.gist = f"key points about {sec.title.lower()}"
        sec.children = [_mk_section(c, level=2) for c in (s.get("children") or [])[:3]]
        doc.sections.append(sec)

    # pad up to the target with topic-shaped stubs (not generic Intro/Details)
    if len(doc.sections) < max(MIN_SECTIONS, target):
        topic = re.sub(r"^(the\s+)?", "", doc.title, flags=re.IGNORECASE)
        fillers = [
            ("Background", f"context and why {topic.lower()} matters"),
            ("Key Points", f"the core of {topic.lower()}"),
            ("Practical Steps", "what to do with this"),
            ("Common Pitfalls", "mistakes to avoid"),
            ("Impact", "what changes as a result"),
            ("Next Steps", "where to go from here"),
            ("Summary", f"the takeaways on {topic.lower()}"),
        ]
        for t, g in fillers:
            if len(doc.sections) >= max(MIN_SECTIONS, target):
                break
            if t.lower() not in {x.title.lower() for x in doc.sections}:
                doc.sections.append(Section(title=t, level=1, gist=g))

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
