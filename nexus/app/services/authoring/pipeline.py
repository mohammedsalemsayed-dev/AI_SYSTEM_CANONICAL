"""Authoring pipeline (MILESTONE_M_PLAN.md §2).

outline -> grounded draft -> review -> render. Markdown unless a renderer is
passed. Performs no filesystem write — the artifact is the rendered string.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.base import LLM
from app.services.authoring.draft import draft as _draft
from app.services.authoring.model import DocumentModel
from app.services.authoring.outline import outline as _outline
from app.services.authoring.render import MarkdownRenderer, RenderedDoc, Renderer, get_renderer
from app.services.authoring.review import Issue, review as _review


@dataclass
class AuthoringResult:
    model: DocumentModel
    rendered: RenderedDoc
    issues: list[Issue]
    citations: list[dict]
    flags: list[str] = field(default_factory=list)


class AuthoringPipeline:
    def __init__(self, llm: LLM, *, kb=None, renderer: Renderer | str | None = None) -> None:
        self.llm = llm
        self.kb = kb
        if isinstance(renderer, str):
            renderer = get_renderer(renderer)
        self.renderer: Renderer = renderer or MarkdownRenderer()

    def run(
        self, task_id: str, brief: str, *, kind: str = "report", memory_ctx: str = ""
    ) -> AuthoringResult:
        model = _outline(brief, self.llm, kb=self.kb, memory_ctx=memory_ctx, kind=kind)
        model = _draft(model, self.llm, brief=brief, kb=self.kb, memory_ctx=memory_ctx)
        issues = _review(model, self.llm)
        rendered = self.renderer.render(model)
        citations = [
            {"id": c.id, "source": c.source, "trust": c.trust, "label": c.label}
            for c in model.all_citations()
        ]
        return AuthoringResult(
            model=model, rendered=rendered, issues=issues,
            citations=citations, flags=sorted(set(model.flags)),
        )
