"""Evidence graph (MILESTONE_K_PLAN.md §2).

Nodes: `EvidenceRecord` (sources) and `Claim`. Edges:
  * support   claim -> source        (a claim's `source_refs`)
  * relation  claim <-> claim        (`agrees` / `contradicts`)
  * answers   sub-question -> claim
Pure data + queries; no LLM.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.schemas.contracts import Claim, ContradictionRecord, EvidenceRecord

_PRIMARY_KIND_RANK = {"doc": 3, "measurement": 3}


class EvidenceGraph:
    def __init__(self, *, official_hosts: list[str] | None = None) -> None:
        self.sources: dict[str, EvidenceRecord] = {}
        self.claims: dict[str, Claim] = {}
        self._answers: dict[str, list[str]] = {}   # sub-question -> [claim id]
        self._relations: list[tuple[str, str, str]] = []  # (a, b, kind)
        self._official = {h.strip().lower() for h in (official_hosts or []) if h.strip()}

    # -- build ------------------------------------------------ #
    def add_source(self, ev: EvidenceRecord) -> None:
        self.sources[ev.id] = ev

    def add_claim(self, claim: Claim, *, answers: str | None = None) -> None:
        self.claims[claim.id] = claim
        if answers is not None:
            self._answers.setdefault(answers, []).append(claim.id)

    def relate(self, claim_a: str, claim_b: str, kind: str) -> None:
        if kind not in ("agrees", "contradicts"):
            raise ValueError(f"unknown relation {kind!r}")
        key = (claim_a, claim_b, kind)
        if key not in self._relations and (claim_b, claim_a, kind) not in self._relations:
            self._relations.append(key)

    # -- queries ------------------------------------------- #
    def sources_for(self, claim_id: str) -> list[EvidenceRecord]:
        c = self.claims.get(claim_id)
        return [self.sources[r] for r in (c.source_refs if c else []) if r in self.sources]

    def claims_for(self, sub_question: str) -> list[Claim]:
        return [self.claims[cid] for cid in self._answers.get(sub_question, []) if cid in self.claims]

    def sub_questions(self) -> list[str]:
        return list(self._answers)

    def relations_of(self, claim_id: str, kind: str | None = None) -> list[tuple[str, str, str]]:
        return [
            r for r in self._relations
            if claim_id in (r[0], r[1]) and (kind is None or r[2] == kind)
        ]

    def contradictions(self, *, unresolved_only: bool = True) -> list[ContradictionRecord]:
        out: list[ContradictionRecord] = []
        for a, b, kind in self._relations:
            if kind != "contradicts":
                continue
            rec = ContradictionRecord(claim_a=a, claim_b=b, subject=self._subject(a, b))
            resolution = self._auto_resolution(a, b)
            if resolution:
                rec.resolved, rec.resolution = True, resolution
            if rec.resolved and unresolved_only:
                continue
            out.append(rec)
        return out

    def host_of(self, source_id: str) -> str:
        ev = self.sources.get(source_id)
        return urlparse(ev.source).netloc.lower() if ev and ev.source else ""

    def is_primary(self, claim_id: str) -> bool:
        for ev in self.sources_for(claim_id):
            if _PRIMARY_KIND_RANK.get(ev.kind, 0) >= 3:
                return True
            if any(h and h in self.host_of(ev.id) for h in self._official):
                return True
        return False

    def rank(self, claim_id: str) -> int:
        best = 1
        for ev in self.sources_for(claim_id):
            best = max(best, _PRIMARY_KIND_RANK.get(ev.kind, 0))
            if any(h and h in self.host_of(ev.id) for h in self._official):
                best = max(best, 2)
        return best

    # -- internals -------------------------------------- #
    def _subject(self, a: str, b: str) -> str:
        ca, cb = self.claims.get(a), self.claims.get(b)
        ta = (ca.text if ca else "").split(".")[0]
        return ta[:120] or (cb.text[:120] if cb else "")

    def _auto_resolution(self, a: str, b: str) -> str:
        pa, pb = self.is_primary(a), self.is_primary(b)
        if pa and not pb:
            return f"primary source backs claim {a}"
        if pb and not pa:
            return f"primary source backs claim {b}"
        return ""
