"""Lexical (BM25) index — the stdlib retrieval fallback (MILESTONE_L_PLAN.md §2).

Pure and rebuildable: `build(chunks)` from the chunk table, `search(query, k)`
returns `[(chunk_id, score)]`. A real embedding / RAG-framework backend
implements the same `Retriever` protocol (see `retrieve.py`) and replaces this.
"""

from __future__ import annotations

import math
import re

K1 = 1.5
B = 0.75

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset("""
a an the of to in on at for and or but is are was were be been being this that these those
it its as by with from into out over under again then than so such not no nor can will just
""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class LexicalIndex:
    def __init__(self) -> None:
        self._postings: dict[str, dict[str, int]] = {}   # term -> {chunk_id: tf}
        self._len: dict[str, int] = {}                   # chunk_id -> token count
        self._avg_len: float = 0.0
        self._n: int = 0

    @classmethod
    def build(cls, chunks: list[tuple[str, str]]) -> "LexicalIndex":
        """`chunks` = [(chunk_id, text)]."""
        idx = cls()
        for cid, text in chunks:
            toks = tokenize(text)
            idx._len[cid] = len(toks)
            for t in toks:
                idx._postings.setdefault(t, {})
                idx._postings[t][cid] = idx._postings[t].get(cid, 0) + 1
        idx._n = len(idx._len)
        idx._avg_len = (sum(idx._len.values()) / idx._n) if idx._n else 0.0
        return idx

    def search(self, query: str, k: int = 8) -> list[tuple[str, float]]:
        q_terms = tokenize(query)
        if not q_terms or self._n == 0:
            return []
        scores: dict[str, float] = {}
        for term in set(q_terms):
            postings = self._postings.get(term)
            if not postings:
                continue
            df = len(postings)
            idf = math.log(1 + (self._n - df + 0.5) / (df + 0.5))
            for cid, tf in postings.items():
                dl = self._len.get(cid, 0)
                denom = tf + K1 * (1 - B + B * dl / (self._avg_len or 1))
                scores[cid] = scores.get(cid, 0.0) + idf * (tf * (K1 + 1) / (denom or 1))
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:k]
