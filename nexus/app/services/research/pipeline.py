"""Research pipeline (MILESTONE_K_PLAN.md §2, §5).

decompose -> research each sub-question through the Milestone E Researcher ->
assemble the evidence graph -> cross-check unresolved contradictions with bounded
follow-up rounds -> synthesize a cited answer. Verification for research is the
cross-check + the mandatory uncertainty statement, not a T0 oracle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.base import LLM
from app.schemas.contracts import Claim, EvidenceRecord, ModelRunRecord, ResearchAnswer
from app.services.agents.researcher import Researcher
from app.services.research import crosscheck, decompose, injection
from app.services.research.evidence_graph import EvidenceGraph
from app.services.research.synthesize import synthesize


@dataclass
class ResearchRound:
    sub_question: str
    urls: list[str]
    n_claims: int
    flags: list[str] = field(default_factory=list)


@dataclass
class ResearchResult:
    answer: ResearchAnswer
    graph: EvidenceGraph
    rounds: list[ResearchRound]
    flags: list[str]
    model_runs: list[ModelRunRecord]


KB_TOPK = 4


class ResearchPipeline:
    def __init__(
        self,
        researcher: Researcher,
        llm: LLM,
        *,
        official_hosts: list[str] | None = None,
        kb=None,
        kb_retriever=None,
    ) -> None:
        self.researcher = researcher
        self.llm = llm
        self.official_hosts = official_hosts or []
        self.kb = kb
        self.kb_retriever = kb_retriever

    def run(self, task_id: str, question: str) -> ResearchResult:
        graph = EvidenceGraph(official_hosts=self.official_hosts)
        rounds: list[ResearchRound] = []
        flags: list[str] = []
        runs: list[ModelRunRecord] = []

        for subq in decompose.decompose(question, self.llm):
            kb_urls = self._kb_sources(task_id, graph, subq, flags)
            ev, claims, run = self.researcher.research(task_id, subq)
            runs.append(run)
            rflags = self._ingest(graph, ev, claims, answers=subq)
            flags += rflags
            rounds.append(ResearchRound(
                sub_question=subq, urls=[e.source for e in ev] + kb_urls,
                n_claims=len(claims), flags=rflags,
            ))

        self._crosscheck(task_id, graph, flags)

        answer = synthesize(question, graph, flags, self.llm, task_id=task_id)
        return ResearchResult(answer=answer, graph=graph, rounds=rounds,
                              flags=sorted(set(flags)), model_runs=runs)

    # -- internals -------------------------------------- #
    def _kb_sources(self, task_id, graph, subq, flags: list[str]) -> list[str]:
        if self.kb is None and self.kb_retriever is None:
            return []
        from app.services.kb.answer import add_chunk_to_graph
        from app.services.kb.retrieve import LexicalRetriever

        r = self.kb_retriever or LexicalRetriever(self.kb)
        uris: list[str] = []
        for rc in r.retrieve(subq, k=KB_TOPK):
            flags += add_chunk_to_graph(graph, rc, self.llm, answers=subq, task_id=task_id)
            uris.append(rc.uri)
        return uris

    def _ingest(self, graph, ev_list, claims, *, answers) -> list[str]:
        flags: list[str] = []
        for ev in ev_list:
            graph.add_source(ev)
            hits = injection.scan(ev.content_excerpt)
            if hits:
                flags += [f"{h}@{graph.host_of(ev.id) or ev.source}" for h in hits]
        for c in claims:
            graph.add_claim(c, answers=answers)
        return flags

    def _crosscheck(self, task_id, graph: EvidenceGraph, flags: list[str]) -> None:
        claim_items = list(graph.claims.items())
        if len(claim_items) < 2:
            return
        ids = [cid for cid, _ in claim_items]
        texts = [c.text for _, c in claim_items]
        pairs = crosscheck.detect(ids, texts, self.llm)
        for a, b, _subject in pairs:
            graph.relate(a, b, "contradicts")

        for _round in range(crosscheck.MAX_CROSSCHECK):
            open_contras = graph.contradictions(unresolved_only=True)
            if not open_contras:
                break
            progressed = False
            for rec in open_contras:
                ca, cb = graph.claims.get(rec.claim_a), graph.claims.get(rec.claim_b)
                if not (ca and cb):
                    continue
                urls = crosscheck.follow_up_queries(rec.subject, ca.text, cb.text, self.llm)
                if not urls:
                    continue
                # reuse the Researcher's fetch+extract on the disambiguating URLs
                # by asking it the subject question (it will query-plan its own,
                # but a targeted subject is close enough for the slice)
                ev, claims, run = self.researcher.research(task_id, rec.subject)
                if ev or claims:
                    progressed = True
                    self._ingest(graph, ev, claims, answers=rec.subject)
                    # link any new claim that agrees textually with a side
                    for c in claims:
                        if _overlap(c.text, ca.text) > _overlap(c.text, cb.text):
                            graph.relate(c.id, ca.id, "agrees")
                        elif _overlap(c.text, cb.text) > 0:
                            graph.relate(c.id, cb.id, "agrees")
            if not progressed:
                break

        # final resolution pass
        for rec in graph.contradictions(unresolved_only=True):
            crosscheck.resolve(graph, rec)


def _overlap(a: str, b: str) -> int:
    wa = {w for w in a.lower().split() if len(w) > 3}
    wb = {w for w in b.lower().split() if len(w) > 3}
    return len(wa & wb)
