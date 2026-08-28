"""Retriever protocol + the lexical implementation (MILESTONE_L_PLAN.md §2).

A real embedding store / RAG framework implements `Retriever` and replaces
`LexicalRetriever` with no change above this line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.services.kb.store import KnowledgeBase


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    uri: str
    title: str
    heading: str
    text: str
    score: float
    flags: list[str]


@runtime_checkable
class Retriever(Protocol):
    def retrieve(self, query: str, k: int = 8) -> list[RetrievedChunk]: ...


class LexicalRetriever:
    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    def retrieve(self, query: str, k: int = 8) -> list[RetrievedChunk]:
        hits = self.kb.index().search(query, k=k)
        out: list[RetrievedChunk] = []
        for cid, score in hits:
            m = self.kb.chunk_meta(cid)
            if not m:
                continue
            out.append(RetrievedChunk(
                chunk_id=cid, doc_id=m["doc_id"], uri=m["uri"], title=m["title"],
                heading=m["heading"], text=m["text"], score=round(score, 4),
                flags=m["flags"],
            ))
        return out
