"""Synthesis (MILESTONE_K_PLAN.md §2, §12).

Turn the evidence graph into a cited `ResearchAnswer`. The LLM sees **claim text
and source refs only** — never raw retrieved text. Every statement carries
citation ids; unresolved contradictions go under `contested`; `uncertainty` is
mandatory.
"""

from __future__ import annotations

from app.llm.base import LLM
from app.llm.parse import parse_json_object
from app.schemas.contracts import ResearchAnswer
from app.services.research.evidence_graph import EvidenceGraph

_SYSTEM = """You synthesize a research answer from a list of CLAIMS, each with an id and
source ids. Rules:
- Use ONLY the claims provided. Do not add facts.
- Every statement must cite the claim/source ids it rests on.
- Note where support is thin (one source) or where claims conflict.
Reply with ONLY JSON:
{"sections": [{"statement": string, "citation_ids": [string, ...]}],
 "uncertainty": string}"""


def _citation_index(graph: EvidenceGraph) -> list[dict]:
    out = []
    for sid, ev in graph.sources.items():
        out.append({"id": sid, "source": ev.source, "host": graph.host_of(sid), "kind": ev.kind})
    return out


def synthesize(
    question: str,
    graph: EvidenceGraph,
    flags: list[str],
    llm: LLM,
    *,
    task_id: str = "",
) -> ResearchAnswer:
    claims = list(graph.claims.values())
    citations = _citation_index(graph)

    contested = []
    for rec in graph.contradictions(unresolved_only=True):
        ca, cb = graph.claims.get(rec.claim_a), graph.claims.get(rec.claim_b)
        contested.append({
            "subject": rec.subject,
            "a": ca.text if ca else "", "a_cites": ca.source_refs if ca else [],
            "b": cb.text if cb else "", "b_cites": cb.source_refs if cb else [],
        })

    if not claims:
        return ResearchAnswer(
            task_id=task_id, question=question, sections=[], contested=contested,
            citations=citations, flags=sorted(set(flags)),
            uncertainty="no sources retrieved; no claims could be extracted.",
        )

    # claims-only payload — NO raw source text
    payload = "\n".join(
        f"- [{c.id}] {c.text}  (sources: {', '.join(c.source_refs) or 'none'})"
        for c in claims
    )
    sections: list[dict] = []
    uncertainty = ""
    try:
        resp = llm.complete(
            system=_SYSTEM,
            prompt=f"QUESTION: {question}\n\nCLAIMS:\n{payload}\n\nReturn the JSON.",
        )
        parsed = parse_json_object(resp.text)
        for s in parsed.get("sections", []):
            st = str(s.get("statement", "")).strip()
            if st:
                sections.append({"statement": st,
                                 "citation_ids": [str(x) for x in s.get("citation_ids", [])]})
        uncertainty = str(parsed.get("uncertainty", "")).strip()
    except Exception:
        sections = [{"statement": c.text, "citation_ids": list(c.source_refs)} for c in claims]
        uncertainty = "synthesis model unavailable; claims listed verbatim."

    single_source = [c.id for c in claims if len(c.source_refs) <= 1]
    notes = []
    if single_source:
        notes.append(f"{len(single_source)} claim(s) rest on a single source")
    if contested:
        notes.append(f"{len(contested)} unresolved contradiction(s)")
    if flags:
        notes.append(f"source(s) flagged for instruction-like content: {', '.join(sorted(set(flags)))}")
    if notes:
        uncertainty = (uncertainty + " " if uncertainty else "") + "; ".join(notes) + "."

    return ResearchAnswer(
        task_id=task_id, question=question, sections=sections, contested=contested,
        citations=citations, uncertainty=uncertainty or "none noted.",
        flags=sorted(set(flags)),
    )
