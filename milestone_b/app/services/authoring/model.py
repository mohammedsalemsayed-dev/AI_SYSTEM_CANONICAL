"""Document model (MILESTONE_M_PLAN.md §2).

A section tree of typed blocks with attached citations. Renderer-agnostic; a
`SlideDeck` view flattens it for PPTX.
"""

from __future__ import annotations

from typing import Any, Iterator, Literal

from pydantic import BaseModel, Field

BlockKind = Literal["heading", "paragraph", "list", "table", "quote", "code", "figure"]
DocKind = Literal["report", "doc", "deck"]


class Citation(BaseModel):
    id: str
    label: str = ""          # "[1] Title — source"
    source: str = ""         # uri / url
    trust: str = "workspace"  # doc_input | retrieved_web | workspace | user


class Block(BaseModel):
    kind: BlockKind = "paragraph"
    level: int = 0                                   # heading level, or list nesting
    text: str = ""
    items: list[str] = Field(default_factory=list)   # list block
    rows: list[list[str]] = Field(default_factory=list)  # table (row 0 = header)
    lang: str = ""                                   # code block
    caption: str = ""                                # figure block
    citation_ids: list[str] = Field(default_factory=list)


class Section(BaseModel):
    title: str
    level: int = 1
    gist: str = ""
    blocks: list[Block] = Field(default_factory=list)
    children: list["Section"] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)

    def walk(self) -> Iterator["Section"]:
        yield self
        for c in self.children:
            yield from c.walk()

    def text_body(self) -> str:
        return "\n".join(
            b.text for b in self.blocks if b.kind in ("paragraph", "quote")
        )

    def is_factual(self) -> bool:
        body = self.text_body()
        return body.count(".") >= 2 and any(
            b.kind in ("paragraph", "quote") for b in self.blocks
        )


class DocumentModel(BaseModel):
    id: str = Field(default_factory=lambda: f"doc_{id(object()):x}")
    title: str = ""
    kind: DocKind = "report"
    sections: list[Section] = Field(default_factory=list)
    citations: dict[str, Citation] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)

    def walk(self) -> Iterator[Section]:
        for s in self.sections:
            yield from s.walk()

    def add_citation(self, cit: Citation) -> None:
        self.citations.setdefault(cit.id, cit)

    def all_citations(self) -> list[Citation]:
        """Citations in first-reference order."""
        seen: list[str] = []
        for sec in self.walk():
            for b in sec.blocks:
                for cid in b.citation_ids:
                    if cid not in seen and cid in self.citations:
                        seen.append(cid)
        return [self.citations[c] for c in seen]

    def numbered_citations(self) -> dict[str, int]:
        return {c.id: i + 1 for i, c in enumerate(self.all_citations())}


class Slide(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    notes: str = ""
    citation_ids: list[str] = Field(default_factory=list)


class SlideDeck(BaseModel):
    title: str = ""
    slides: list[Slide] = Field(default_factory=list)

    @classmethod
    def from_document(cls, doc: DocumentModel, *, max_bullets: int = 6) -> "SlideDeck":
        deck = cls(title=doc.title)
        for top in doc.sections:
            for sec in ([top] + top.children if top.children else [top]):
                bullets: list[str] = []
                cids: list[str] = []
                for b in sec.blocks:
                    if b.kind == "list":
                        bullets += b.items
                    elif b.kind == "paragraph" and b.text:
                        bullets.append(b.text.split(". ")[0].strip().rstrip("."))
                    cids += b.citation_ids
                deck.slides.append(Slide(
                    title=sec.title, bullets=bullets[:max_bullets],
                    notes=sec.text_body(), citation_ids=list(dict.fromkeys(cids)),
                ))
        return deck


Section.model_rebuild()
