# Milestone M — Authoring Pipelines Plan

> **Cross-reference**
> - Role: Build plan for the fourth §10.2 capability domain — the `authoring` task class: outline → grounded draft → review → render, with DOCX/PPTX as a renderer seam.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §6 (`authoring` = "produce a DOCX / PPTX / report artifact"), §7.1 (route: local-reasoner draft + cloud review pass; escalate when the user marks it high-stakes), §10.2 (capability domain 4: *DOCX / PDF + PPTX pipelines → `authoring`*, "prereq: F, uses retrieval"), §12 (grounded content keeps its source trust), §16 (prior art: *Document / presentation output — python-docx, python-pptx, Docling* — integrate the renderers).
> - Downstream: none — `authoring` is a leaf deliverable class.
> - Predecessors: F (memory/experience for the draft context), L (the knowledge base the draft is grounded in), K (claims + synthesis reuse). Continues the `milestone_b/` tree.

---

## 1. Purpose

`authoring` has no home: no document model, no outline/draft/review flow, no renderer. A
report or deck request would fall through the code-edit path.

Per §16 the *renderers* (python-docx / python-pptx) are integrations, not builds. So
Milestone M builds the domain's control plane plus stdlib renderers that work now:

- a **`DocumentModel`** — a section tree of typed blocks (heading / paragraph / list / table
  / quote / code / figure-ref) with attached citations, and a `SlideDeck` view for `PPTX`;
- an **outline → draft → review** flow — `outline(brief)` (retrieval-grounded headings) →
  `draft(model)` (fill each section from KB claims + the brief, citations attached) →
  `review(model)` (advisory issues: unsupported claim, missing citation, thin section,
  structure);
- a **`Renderer` protocol** with **Markdown + HTML** renderers (stdlib); **DOCX / PPTX /
  PDF** renderers are the documented seam (`python-docx` / `python-pptx` / a PDF lib);
- **orchestrator wiring** — an `authoring` task runs the pipeline and returns the rendered
  document (Markdown by default) as its artifact, plus the review issues.

Guiding rules:
- **§12** — a draft grounded in KB / research keeps the source trust on each `Citation`
  (`doc_input` / `retrieved_web`); the rendered artifact is `workspace` trust but every
  factual passage traces to a cited claim. The pipeline performs **no filesystem write** —
  the artifact is the rendered string; an explicit `fs.write`-scoped step writes it to disk.
- **§7.1** — `authoring` gets a review pass by design; `review()` is that pass (advisory,
  never blocks — the user decides). High-stakes → the router escalates the review to cloud.
- **§16 / no new deps** — stdlib + `pydantic`. Markdown/HTML renderers ship; DOCX/PPTX are
  `Renderer` implementations to drop in.
- **F reuse** — `draft()` takes the memory context block (active decisions / constraints) so
  a report reflects project reality, not just the brief.

## 2. In scope

| Concern | Milestone M implementation |
|---|---|
| Document model | `authoring/model.py`: `Block{kind: heading|paragraph|list|table|quote|code|figure, level, text, items[], rows[], lang, citations[]}`, `Section{title, level, blocks[], children[]}`, `DocumentModel{title, kind: report|doc|deck, sections[], meta, all_citations()}`. `SlideDeck` = a `DocumentModel` flattened to `Slide{title, bullets[], notes, citations[]}` (one slide per H2). Pure data + a `walk()` iterator. |
| Outline | `authoring/outline.py`: `outline(brief, llm, *, kb=None, memory_ctx="") -> DocumentModel` — one LLM call returns a heading tree (`{sections: [{title, level, gist}]}`); if a KB is attached, each `gist` is checked against a retrieval so the outline only promises what the library can support (flag `unsupported-section`). |
| Draft | `authoring/draft.py`: `draft(model, llm, *, kb=None, memory_ctx="") -> DocumentModel` — per section: retrieve `DRAFT_TOPK` KB chunks, extract claims (reuse `kb.answer.add_chunk_to_graph` / claims-only), one LLM call to write the section body **from the claims + the brief + the memory context** (delimited, claims-only), attach `Citation`s. A section with no supporting claims is written as a stub + flagged `unsupported-section`. |
| Review | `authoring/review.py`: `review(model, llm) -> list[Issue]` — structural checks (empty section, heading-only, no citations in a factual section, duplicate titles) + one LLM pass over the section texts + their citation ids for `unsupported-claim` / `overclaim` / `inconsistent`. `Issue{kind, section, detail, severity}`. Advisory. |
| Renderers | `authoring/render.py`: `Renderer` protocol (`render(model) -> RenderedDoc{mime, text_or_bytes, ext}`). `MarkdownRenderer` (headings, lists, tables, blockquotes, fenced code, a `## References` section from `all_citations()`), `HtmlRenderer` (semantic HTML, `<section>`/`<h*>`/`<table>`, a references `<ol>`). `DocxRenderer` / `PptxRenderer` / `PdfRenderer` are **stub classes** that raise `RendererUnavailable("pip install python-docx")` — the seam. |
| Pipeline | `authoring/pipeline.py`: `AuthoringPipeline(llm, *, kb=None, renderer=None)`. `run(task_id, brief, *, kind="report", memory_ctx="") -> AuthoringResult{model, rendered: RenderedDoc, issues, citations, flags}`. outline → draft → review → render (Markdown unless a renderer is passed). |
| Schema / events | `+ AuthoringResult` is a dataclass in `pipeline.py`; `DocumentModel` etc. are pydantic in `authoring/model.py`. `AUTHORING` event kind. |
| Orchestrator wiring | `self.authoring = None` opt-in. `contract.task_class == "authoring"` + it is set → run the pipeline (same `PLANNING → EXECUTING → OBSERVATION → VERIFYING → COMPLETED` shape as K/L; verification criterion = "outline+draft+review complete, N issues reported"). The `RenderedDoc.text` is the artifact; `AUTHORING` (outline / draft / review) + `SYNTHESIS` (the rendered doc + issues) events. The `memory_ctx` comes from `self.memory` if set. Unset → `authoring` unchanged. |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Real DOCX / PPTX / PDF bytes | `Renderer` seam — drop in `python-docx` / `python-pptx` / `reportlab` (§16) |
| Templates, themes, corporate styles | later — the model is style-agnostic; a renderer applies style |
| Charts / generated figures | later — `figure` blocks carry a ref + caption, not pixels |
| Track-changes / collaborative editing | never in the slice |
| Iterative revise loop (review → redraft → re-review) | later — M does one pass; the ladder could drive more |
| Bibliography formats (APA/MLA/Chicago) | later — references are `[n] title — source` |

## 4. Component layout

```
app/services/authoring/
  model.py      DocumentModel / Section / Block / Citation / SlideDeck
  outline.py    outline(brief, llm, kb=, memory_ctx=) -> DocumentModel
  draft.py      draft(model, llm, kb=, memory_ctx=) -> DocumentModel
  review.py     review(model, llm) -> [Issue]
  render.py     Renderer protocol; MarkdownRenderer, HtmlRenderer; Docx/Pptx/Pdf stubs
  pipeline.py   AuthoringPipeline.run(...) -> AuthoringResult
app/events/log.py                    + AUTHORING
app/orchestration/orchestrator.py    opt-in self.authoring; authoring -> pipeline
tests/
  unit/         test_doc_model, test_authoring_outline, test_authoring_draft,
                test_authoring_review, test_markdown_render
  integration/  test_authoring_task (end to end), test_authoring_grounded_in_kb
```

## 5. Work breakdown (~14 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `authoring/model.py` — `Block` / `Section` / `DocumentModel` / `SlideDeck` + `walk()` + `all_citations()`. Unit tests (round-trip, deck flattening). |
| 3–4 | `authoring/render.py` — `MarkdownRenderer` (all block kinds + a References section) + `HtmlRenderer`; `Docx/Pptx/Pdf` stubs raising `RendererUnavailable`. Unit tests: a model with each block kind renders to expected Markdown; references list every citation once. |
| 5–7 | `authoring/outline.py` — heading tree from the brief; KB-supported check + `unsupported-section` flag. Scripted-LLM unit tests. |
| 8–10 | `authoring/draft.py` — per-section KB retrieval + claims-only body generation + citation attach; unsupported section → stub + flag. Unit tests with a seeded KB + scripted LLM: a drafted section carries citations pointing at KB uris; a section with no support is flagged. |
| 11 | `authoring/review.py` — structural + LLM issue detection. Unit tests for each `Issue.kind`. |
| 12 | `authoring/pipeline.py` — `AuthoringPipeline.run()` wiring outline→draft→review→render. Integration test (scripted LLM, seeded KB) → `AuthoringResult` with a Markdown `rendered` doc + issues. |
| 13 | Orchestrator wiring — `self.authoring` opt-in; `authoring` branch; `AUTHORING` events; `RenderedDoc.text` as artifact; `memory_ctx` from `self.memory`. Integration: an `authoring` task reaches `COMPLETED` with a rendered report artifact; issues on the log. |
| 14 | Regression; `milestone_b/MILESTONE_M_NOTES.md`; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the top-level [README.md](README.md); rehash `MANIFEST.json`; commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — `DocumentModel.walk()` yields sections depth-first and `all_citations()` de-dupes;
  `SlideDeck` makes one slide per H2 with its bullets; `MarkdownRenderer` emits every block
  kind correctly and a `## References` section listing each citation once; `HtmlRenderer`
  produces well-formed nested `<section>`s; `outline()` returns a heading tree and flags a
  section the KB cannot support; `draft()` fills a section from KB claims with `Citation`s
  pointing at the KB uris and flags an unsupported section; `review()` returns the right
  `Issue.kind` for an empty section / a factual section with no citation / an LLM-flagged
  overclaim; the DOCX renderer stub raises `RendererUnavailable`, not a crash.
- **Integration** — `AuthoringPipeline.run` over a scripted LLM + a seeded KB returns an
  `AuthoringResult` whose `rendered.mime == "text/markdown"`, whose body cites KB uris, and
  whose `issues` list is populated for a deliberately thin brief; through the orchestrator an
  `authoring` task reaches `COMPLETED` with the rendered doc as `artifact_ref` and
  `AUTHORING` + `SYNTHESIS` events. Authoring unset → `authoring` unchanged.
- **Failure** — an empty brief → a `DocumentModel` with a title-only section and an
  `empty-brief` flag, not a crash; a KB miss for every section → all sections stubbed +
  flagged, the doc still renders; passing an unknown renderer name falls back to Markdown.
- **Security (§12)** — KB / research claims used in the draft keep their `doc_input` /
  `retrieved_web` trust on the `Citation`; the pipeline writes no file and makes no network
  call; a KB chunk with a planted directive contributes a flagged citation and does not
  change the outline or the brief.
- **Recovery** — `reconcile()` + `resume()` work with the authoring path; an interrupted run
  re-runs cleanly (no side effects).
- **Benchmark** — n/a (no oracle for prose quality; the review pass + citation coverage is
  the quality gate).

## 7. Tunable starting values

- `outline`: 3–8 top-level sections, ≤ 2 nesting levels.
- `draft`: `DRAFT_TOPK = 5` KB chunks/section, extraction on the top 4; section body target
  ~180 words.
- `review`: a "factual section" = one with ≥ 2 sentences and no `code`/`figure`-only content.
- deck: one slide per H2; ≤ 6 bullets/slide, bullets from the section's paragraph leads.
- References numbered in first-citation order.

## 8. Risks

- **Prose quality is model-bound** — M cannot make a bad model write well. Mitigate: the
  value is the *structure* (grounded, cited, reviewed), and `review()` surfaces the weak
  spots for the user.
- **Grounding gaps** — a brief may ask for sections the KB / brief cannot support. Handled
  explicitly: `unsupported-section` flag + a visible stub, never a hallucinated section.
- **Renderer seam vs. real output** — the slice emits Markdown/HTML; a user who needs a
  `.docx` must drop in `python-docx`. Documented; the model is renderer-agnostic so the swap
  is additive.
- **One-pass flow** — no revise loop. Acceptable for the slice; the escalation ladder is the
  place to add "review found blocking issues → redraft".
- **Citation trust leakage** — a rendered doc is `workspace` trust; if a consumer treated it
  as authoritative for an action it would bypass §12. Mitigate: `AuthoringResult.citations`
  keeps per-claim trust, and the orchestrator logs the doc as an artifact, not as evidence.

## 9. Deliverables

- `app/services/authoring/` — `model.py`, `outline.py`, `draft.py`, `review.py`,
  `render.py`, `pipeline.py`.
- `AUTHORING` event kind; `Renderer` protocol + Markdown/HTML renderers + DOCX/PPTX/PDF stubs.
- Orchestrator: opt-in `AuthoringPipeline`; `authoring` runs it and returns a rendered doc.
- Test suite: the current 357 green, plus unit (model / outline / draft / review / render)
  and integration (`authoring` task / KB-grounded draft).
- `milestone_b/MILESTONE_M_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the
  top-level [README.md](README.md) updated: "DOCX / PDF generation" moves to FOUNDATION for
  the model + outline/draft/review flow + Markdown/HTML renderers; DOCX/PPTX are the
  documented renderer integration.
