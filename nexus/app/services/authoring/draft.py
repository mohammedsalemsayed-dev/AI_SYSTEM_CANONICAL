"""Draft (MILESTONE_M_PLAN.md §2, §12).

Fill each section body from KB claims + the brief + the project memory context.
Claims-only: the section-writing prompt sees claim text + citation ids, never raw
chunk text. A section with no supporting claim is stubbed and flagged.
"""

from __future__ import annotations

import re

from app.llm.base import LLM
from app.llm.parse import parse_json_object
from app.schemas.contracts import EvidenceRecord
from app.services.authoring.model import Block, Citation, DocumentModel, Section

DRAFT_TOPK = 5
EXTRACT_TOP = 4

# small models sometimes drop the raw claim id into the prose ("as noted in
# clm_8baa76c658b4"); scrub those — the numbered citation is added by the renderer.
_CLAIM_ID_RE = re.compile(
    r"[,;]?\s*\(?\s*(?:as\s+)?(?:noted|shown|stated|per|see|from|in)?\s*(?:in|by)?\s*"
    r"\b(?:clm|claim|cit|src|ev)_[0-9a-f]{6,}\b\s*\)?",
    re.IGNORECASE,
)


def _scrub(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _CLAIM_ID_RE.sub("", text)).strip()

_SYSTEM = """You write one section of a document from a set of CLAIMS (each with an id) plus
the brief. Rules: use only the claims and the brief; cite the claim ids each sentence rests
on; ~150-200 words; no invented facts. Reply with ONLY JSON:
{"paragraphs": [{"text": string, "citation_ids": [string, ...]}]}"""

_FREE_SYSTEM = """You write one section of a {kind} titled "{title}". Write real, substantive
content from your own knowledge and the brief — no placeholders, no "to be written".
For a deck: 3-5 crisp bullet points. For a report/doc: 2-4 full sentences (~120-180 words).
Reply with ONLY JSON:
{{"paragraphs": [string, ...], "bullets": [string, ...]}}"""


def draft(
    model: DocumentModel,
    llm: LLM,
    *,
    brief: str = "",
    kb=None,
    memory_ctx: str = "",
) -> DocumentModel:
    retriever = None
    if kb is not None:
        from app.services.kb.retrieve import LexicalRetriever

        retriever = LexicalRetriever(kb)

    for sec in model.walk():
        claims = _section_claims(sec, retriever, llm, model)
        if claims:
            _write_section(sec, claims, brief, memory_ctx, llm)
        elif retriever is not None:
            # a KB is attached but this section has no support — that IS a finding
            sec.blocks.append(Block(kind="paragraph",
                                    text=f"_(No supporting material found for “{sec.title}”.)_"))
            if "unsupported-section" not in sec.flags:
                sec.flags.append("unsupported-section")
        else:
            # no KB: write the section from the model's own knowledge + the brief
            _write_section_free(sec, model, brief, memory_ctx, llm)
    return model


def _write_section_free(sec: Section, model: DocumentModel, brief: str,
                        memory_ctx: str, llm: LLM) -> None:
    sysmsg = _FREE_SYSTEM.format(kind=model.kind, title=model.title or "document")
    prompt = f"SECTION: {sec.title}\nGIST: {sec.gist}\nBRIEF: {brief[:600]}\n"
    if memory_ctx:
        prompt += f"PROJECT CONTEXT:\n{memory_ctx[:800]}\n"
    prompt += "\nReturn the JSON."
    paras: list[str] = []
    bullets: list[str] = []
    try:
        parsed = parse_json_object(llm.complete(system=sysmsg, prompt=prompt).text)
        paras = [str(x).strip() for x in (parsed.get("paragraphs") or []) if str(x).strip()]
        bullets = [str(x).strip() for x in (parsed.get("bullets") or []) if str(x).strip()]
    except Exception:  # noqa: BLE001
        pass
    if model.kind == "deck" and (bullets or paras):
        # a deck slide is bullets; if the model only gave prose, split it to points
        pts = bullets or [s.strip() for s in " ".join(paras).replace("\n", " ").split(". ") if s.strip()]
        sec.blocks.append(Block(kind="list", items=[p.rstrip(".") + "" for p in pts[:6]]))
    elif paras or bullets:
        for p in paras:
            sec.blocks.append(Block(kind="paragraph", text=p))
        if bullets:
            sec.blocks.append(Block(kind="list", items=bullets[:6]))
    else:
        sec.blocks.append(Block(kind="paragraph",
                                text=f"{sec.gist or sec.title}."))
        sec.flags.append("thin-section")


def _section_claims(sec: Section, retriever, llm: LLM, model: DocumentModel) -> list[dict]:
    if retriever is None:
        return []
    from app.services.research.evidence_graph import EvidenceGraph
    from app.services.kb.answer import add_chunk_to_graph

    graph = EvidenceGraph()
    probe = f"{sec.title} {sec.gist}".strip()
    for i, rc in enumerate(retriever.retrieve(probe, k=DRAFT_TOPK)):
        if i < EXTRACT_TOP:
            add_chunk_to_graph(graph, rc, llm, answers=sec.title, task_id="")
        else:
            graph.add_source(EvidenceRecord(kind="doc", source=rc.uri,
                                            trust_level="doc_input", content_excerpt=rc.text[:400]))
    out = []
    for c in graph.claims.values():
        cit = Citation(id=c.id, source=_src(graph, c), trust="doc_input",
                       label=f"{_src(graph, c)}")
        model.add_citation(cit)
        out.append({"id": c.id, "text": c.text})
    return out


def _src(graph, claim) -> str:
    s = graph.sources_for(claim.id)
    return s[0].source if s else ""


def _write_section(sec: Section, claims: list[dict], brief: str, memory_ctx: str, llm: LLM) -> None:
    payload = "\n".join(f"- [{c['id']}] {c['text']}" for c in claims)
    prompt = f"SECTION: {sec.title}\nGIST: {sec.gist}\nBRIEF: {brief[:500]}\n"
    if memory_ctx:
        prompt += f"PROJECT CONTEXT:\n{memory_ctx}\n"
    prompt += f"\nCLAIMS:\n{payload}\n\nReturn the JSON."
    try:
        parsed = parse_json_object(llm.complete(system=_SYSTEM, prompt=prompt).text)
        paras = parsed.get("paragraphs") or []
    except Exception:
        paras = [{"text": c["text"], "citation_ids": [c["id"]]} for c in claims]

    valid_ids = {c["id"] for c in claims}
    all_ids = [c["id"] for c in claims]
    for p in paras:
        txt = _scrub(str(p.get("text", "")))
        if not txt:
            continue
        cids = [str(x) for x in p.get("citation_ids", []) if str(x) in valid_ids]
        # a drafted paragraph was written from this section's claims — if the
        # model omitted refs, ground it on all of them rather than leaving it bare
        sec.blocks.append(Block(kind="paragraph", text=txt, citation_ids=cids or all_ids))
    if not sec.blocks:
        sec.blocks.append(Block(kind="paragraph", text=claims[0]["text"],
                                citation_ids=[claims[0]["id"]]))
