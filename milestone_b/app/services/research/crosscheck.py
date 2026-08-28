"""Cross-check (MILESTONE_K_PLAN.md §2).

Find claims that make opposing assertions about the same subject, propose
follow-up queries to disambiguate, and resolve a contradiction when a
primary-source claim or a clear majority backs one side.
"""

from __future__ import annotations

from app.llm.base import LLM
from app.llm.parse import parse_json_object
from app.schemas.contracts import ContradictionRecord
from app.services.research.evidence_graph import EvidenceGraph

MAX_CROSSCHECK = 2

_DETECT_SYSTEM = """You are given a numbered list of factual claims extracted from sources.
Identify pairs that DIRECTLY CONTRADICT each other (opposing assertions about the same
subject). Do not flag claims that are merely different or about different things.
Reply with ONLY JSON: {"contradictions": [{"a": <number>, "b": <number>, "subject": string}]}."""


def detect(claim_ids: list[str], claim_texts: list[str], llm: LLM) -> list[tuple[str, str, str]]:
    """Return (claim_id_a, claim_id_b, subject) triples."""
    if len(claim_ids) < 2:
        return []
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(claim_texts))
    try:
        resp = llm.complete(system=_DETECT_SYSTEM, prompt=f"CLAIMS:\n{numbered}\n\nReturn the JSON.")
        raw = parse_json_object(resp.text).get("contradictions", [])
    except Exception:
        return []
    out: list[tuple[str, str, str]] = []
    for c in raw:
        try:
            ai, bi = int(c["a"]) - 1, int(c["b"]) - 1
        except (KeyError, ValueError, TypeError):
            continue
        if 0 <= ai < len(claim_ids) and 0 <= bi < len(claim_ids) and ai != bi:
            out.append((claim_ids[ai], claim_ids[bi], str(c.get("subject", "")).strip()))
    return out


_FOLLOWUP_SYSTEM = """Given two contradicting claims, propose 1-2 specific URLs (official docs
or primary sources) that would settle which is correct. Reply with ONLY JSON:
{"urls": [string, ...]}."""


def follow_up_queries(subject: str, text_a: str, text_b: str, llm: LLM) -> list[str]:
    try:
        resp = llm.complete(
            system=_FOLLOWUP_SYSTEM,
            prompt=f"SUBJECT: {subject}\nCLAIM A: {text_a}\nCLAIM B: {text_b}\n\nReturn the JSON.",
        )
        return [str(u).strip() for u in parse_json_object(resp.text).get("urls", []) if str(u).strip()][:2]
    except Exception:
        return []


def resolve(graph: EvidenceGraph, rec: ContradictionRecord) -> ContradictionRecord:
    """Close a contradiction when a primary source backs one side, or when >= 2/3
    of the claims about the subject agree with one side and no primary source
    backs the other."""
    a, b = rec.claim_a, rec.claim_b
    pa, pb = graph.is_primary(a), graph.is_primary(b)
    if pa and not pb:
        rec.resolved, rec.resolution = True, f"primary source backs claim {a}"
    elif pb and not pa:
        rec.resolved, rec.resolution = True, f"primary source backs claim {b}"
    else:
        agree_a = 1 + len(graph.relations_of(a, "agrees"))
        agree_b = 1 + len(graph.relations_of(b, "agrees"))
        total = agree_a + agree_b
        if total and agree_a / total >= 2 / 3 and not pb:
            rec.resolved, rec.resolution = True, f"{agree_a}/{total} claims support {a}"
        elif total and agree_b / total >= 2 / 3 and not pa:
            rec.resolved, rec.resolution = True, f"{agree_b}/{total} claims support {b}"
    return rec
