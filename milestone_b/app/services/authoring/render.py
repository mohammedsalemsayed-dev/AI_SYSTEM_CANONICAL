"""Renderers (MILESTONE_M_PLAN.md §2, §16).

Markdown + HTML ship (stdlib). DOCX / PPTX / PDF are `Renderer` stubs — drop in
`python-docx` / `python-pptx` / a PDF lib behind the same protocol.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.services.authoring.model import DocumentModel, Section


class RendererUnavailable(RuntimeError):
    pass


@dataclass
class RenderedDoc:
    mime: str
    text: str
    ext: str


@runtime_checkable
class Renderer(Protocol):
    def render(self, doc: DocumentModel) -> RenderedDoc: ...


class MarkdownRenderer:
    def render(self, doc: DocumentModel) -> RenderedDoc:
        nums = doc.numbered_citations()
        out: list[str] = []
        if doc.title:
            out.append(f"# {doc.title}\n")
        for sec in doc.sections:
            self._section(sec, out, nums, base=2)
        cits = doc.all_citations()
        if cits:
            out.append("\n## References\n")
            for i, c in enumerate(cits, 1):
                label = c.label or (f"{c.source}" if c.source else c.id)
                out.append(f"{i}. {label}" + (f" ({c.trust})" if c.trust not in ("workspace", "user") else ""))
        return RenderedDoc("text/markdown", "\n".join(out).rstrip() + "\n", "md")

    def _section(self, sec: Section, out: list[str], nums: dict[str, int], *, base: int) -> None:
        out.append(f"\n{'#' * min(base, 6)} {sec.title}\n")
        for b in sec.blocks:
            self._block(b, out, nums)
        for child in sec.children:
            self._section(child, out, nums, base=base + 1)

    def _block(self, b, out: list[str], nums: dict[str, int]) -> None:
        cite = self._cite(b.citation_ids, nums)
        if b.kind == "heading":
            out.append(f"{'#' * min(max(b.level, 1), 6)} {b.text}")
        elif b.kind == "paragraph":
            out.append((b.text + cite).strip())
        elif b.kind == "quote":
            out.append(f"> {b.text}{cite}")
        elif b.kind == "list":
            out.extend(f"- {it}" for it in b.items)
            if cite:
                out.append(f"  {cite.strip()}")
        elif b.kind == "code":
            out.append(f"```{b.lang}\n{b.text}\n```")
        elif b.kind == "table" and b.rows:
            head, *body = b.rows
            out.append("| " + " | ".join(head) + " |")
            out.append("| " + " | ".join("---" for _ in head) + " |")
            out.extend("| " + " | ".join(r) + " |" for r in body)
        elif b.kind == "figure":
            out.append(f"_Figure: {b.caption or b.text}_{cite}")
        out.append("")

    @staticmethod
    def _cite(ids: list[str], nums: dict[str, int]) -> str:
        ns = sorted({nums[i] for i in ids if i in nums})
        return f" [{', '.join(str(n) for n in ns)}]" if ns else ""


class HtmlRenderer:
    def render(self, doc: DocumentModel) -> RenderedDoc:
        nums = doc.numbered_citations()
        e = html.escape
        out = ["<article>"]
        if doc.title:
            out.append(f"<h1>{e(doc.title)}</h1>")
        for sec in doc.sections:
            self._section(sec, out, nums, e, level=2)
        cits = doc.all_citations()
        if cits:
            out.append('<section class="references"><h2>References</h2><ol>')
            for c in cits:
                out.append(f"<li>{e(c.label or c.source or c.id)}</li>")
            out.append("</ol></section>")
        out.append("</article>")
        return RenderedDoc("text/html", "\n".join(out), "html")

    def _section(self, sec, out, nums, e, *, level: int) -> None:
        out.append("<section>")
        out.append(f"<h{min(level, 6)}>{e(sec.title)}</h{min(level, 6)}>")
        for b in sec.blocks:
            self._block(b, out, nums, e)
        for child in sec.children:
            self._section(child, out, nums, e, level=level + 1)
        out.append("</section>")

    def _block(self, b, out, nums, e) -> None:
        cite = self._cite(b.citation_ids, nums)
        if b.kind == "paragraph":
            out.append(f"<p>{e(b.text)}{cite}</p>")
        elif b.kind == "quote":
            out.append(f"<blockquote>{e(b.text)}{cite}</blockquote>")
        elif b.kind == "list":
            out.append("<ul>" + "".join(f"<li>{e(it)}</li>" for it in b.items) + "</ul>")
        elif b.kind == "code":
            out.append(f"<pre><code>{e(b.text)}</code></pre>")
        elif b.kind == "table" and b.rows:
            head, *body = b.rows
            out.append("<table><thead><tr>" + "".join(f"<th>{e(c)}</th>" for c in head) + "</tr></thead><tbody>")
            out.extend("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in body)
            out.append("</tbody></table>")
        elif b.kind == "figure":
            out.append(f'<figure><figcaption>{e(b.caption or b.text)}</figcaption></figure>')

    @staticmethod
    def _cite(ids, nums) -> str:
        ns = sorted({nums[i] for i in ids if i in nums})
        return f' <sup>[{", ".join(str(n) for n in ns)}]</sup>' if ns else ""


class _StubRenderer:
    _hint = ""

    def render(self, doc: DocumentModel) -> RenderedDoc:  # noqa: ARG002
        raise RendererUnavailable(self._hint)


class DocxRenderer(_StubRenderer):
    _hint = "DOCX rendering needs python-docx: `pip install python-docx` and implement DocxRenderer"


class PptxRenderer(_StubRenderer):
    _hint = "PPTX rendering needs python-pptx: `pip install python-pptx` and implement PptxRenderer"


class PdfRenderer(_StubRenderer):
    _hint = "PDF rendering needs a PDF library (reportlab / weasyprint) and a PdfRenderer impl"


_BY_NAME = {
    "markdown": MarkdownRenderer, "md": MarkdownRenderer,
    "html": HtmlRenderer,
    "docx": DocxRenderer, "pptx": PptxRenderer, "pdf": PdfRenderer,
}


def get_renderer(name: str) -> Renderer:
    return _BY_NAME.get(name.lower(), MarkdownRenderer)()
