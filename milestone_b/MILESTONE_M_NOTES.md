# Milestone M notes — what is real, what remains

Status against [../MILESTONE_M_PLAN.md](../MILESTONE_M_PLAN.md). **369 tests green.**
All 14 days built. Fourth §10.2 capability domain.

## Real after Milestone M

| Area | Module | Notes |
|---|---|---|
| Document model | `app/services/authoring/model.py` | `Block{kind: heading/paragraph/list/table/quote/code/figure, text, items, rows, lang, caption, citation_ids}`, `Section{title, level, gist, blocks, children, flags}` (`walk()`, `is_factual()`), `DocumentModel{title, kind, sections, citations, meta, flags}` (`walk()`, `all_citations()` in first-reference order, `numbered_citations()`). `SlideDeck.from_document()` = one `Slide` per H2 with its bullets + speaker notes. |
| Renderers | `app/services/authoring/render.py` | `Renderer` protocol (`render(doc) -> RenderedDoc{mime, text, ext}`). `MarkdownRenderer` (every block kind + a `## References` section listing each citation once, numbered) and `HtmlRenderer` (nested `<section>`/`<h*>`, escaped, references `<ol>`) ship. `DocxRenderer` / `PptxRenderer` / `PdfRenderer` are **stubs raising `RendererUnavailable`** with the pip hint — the §16 integration seam. `get_renderer(name)` falls back to Markdown. |
| Outline | `app/services/authoring/outline.py` | `outline(brief, llm, kb=, memory_ctx=, kind=)` → a `DocumentModel` heading tree (one LLM call, `{title, sections:[{title,gist,children}]}`), 3–8 top-level, ≤ 2 levels. With a KB attached, a section whose title+gist has no retrieval support is flagged `unsupported-section` (on the section and the doc). Empty brief → a single "Overview" section + `empty-brief` flag. |
| Draft | `app/services/authoring/draft.py` | `draft(model, llm, brief=, kb=, memory_ctx=)` — per section: retrieve `DRAFT_TOPK=5` KB chunks → claim extraction on the top 4 (reuse `kb.answer.add_chunk_to_graph`, delimited `DOCUMENT CONTEXT`) → **one claims-only LLM call** (`{paragraphs:[{text, citation_ids}]}`) writes the body from claim text + brief + memory context → `Block`s with `Citation`s at `doc_input` trust. A drafted paragraph with no model-supplied refs is grounded on all the section's claims. A section with no supporting claim → a visible stub + `unsupported-section`. |
| Review | `app/services/authoring/review.py` | `review(model, llm) -> [Issue{kind, section, detail, severity}]`. Structural: `empty-section`, `heading-only`, `missing-citation` (factual section, no cites), `duplicate-title`, `unsupported-section`. Plus one LLM pass over drafted section texts + their citation ids for `unsupported-claim` / `overclaim` / `inconsistent`. Advisory — never blocks (except a `blocking`-severity issue → `WAITING_FOR_USER`, see wiring). This **is** the §7.1 "review pass". |
| Pipeline | `app/services/authoring/pipeline.py` | `AuthoringPipeline(llm, kb=, renderer=)`. `run(task_id, brief, kind="report", memory_ctx="")` → outline → draft → review → render → `AuthoringResult{model, rendered, issues, citations, flags}`. Markdown unless a `Renderer` (or name) is passed. **No filesystem write** — the artifact is the rendered string. |
| Orchestrator wiring | `orchestrator._run_authoring` | `self.authoring` opt-in. `contract.task_class == "authoring"` + set → the pipeline instead of plan→build→verify (`PLANNING`→`EXECUTING`→`AUTHORING`+`SYNTHESIS`→`OBSERVATION`→`VERIFYING`→`COMPLETED`). `kind` is `deck` if the brief mentions "slide"/"deck", else `report`. `memory_ctx` comes from `self.memory`. Verification criterion = "outline+draft+review complete, N issues (K blocking)"; a blocking issue → `WAITING_FOR_USER`. The rendered doc text is the `SYNTHESIS` payload; `model.id` is `artifact_ref`. Authoring unset → `authoring` unchanged. |
| Event kind | `AUTHORING` (title, kind, section count, issues, flags). |

## Security posture (§12)

- KB / research claims used in the draft keep `doc_input` / `retrieved_web` trust on each
  `Citation`; the section-writing prompt sees claim text + ids, never raw chunk text.
- The pipeline performs no filesystem write and no network call. The rendered document is a
  `workspace`-trust artifact logged as `SYNTHESIS`, **not** as evidence — a consumer cannot
  treat it as an authoritative origin for a side-effecting action.
- A KB chunk with a planted directive contributes a flagged `Citation` and does not change
  the outline or the brief (the KB's own injection flag rides through).

## Not yet real / deferred

- **Markdown/HTML only** — `.docx` / `.pptx` / `.pdf` need `python-docx` / `python-pptx` /
  a PDF lib dropped in behind `Renderer` (§16). The model is renderer-agnostic; the swap is
  additive.
- **One-pass flow** — outline → draft → review, no revise loop. A "review found blocking
  issues → redraft → re-review" cycle belongs on the escalation ladder.
- **Templates / themes / corporate styles** — the model carries no style; a renderer applies it.
- **Charts / generated figures** — `figure` blocks carry a ref + caption, not pixels.
- **Bibliography formats** (APA/MLA/Chicago) — references are `[n] source`.
- **Prose quality is model-bound** — M provides the grounded, cited, reviewed *structure*;
  `review()` surfaces the weak spots.

## Deferred past M (unchanged)

Engine adapters + expert modes (§10.2 domain 5, needs J — next); automated model selection
(§10.2 domain 6, needs G + ≥ 20 verified runs); real DOCX/PPTX/PDF renderers; a revise loop;
document templates.
