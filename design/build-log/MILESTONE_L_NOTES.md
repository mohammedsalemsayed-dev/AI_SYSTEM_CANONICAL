# Milestone L notes — what is real, what remains

Status against [../MILESTONE_L_PLAN.md](../MILESTONE_L_PLAN.md). **357 tests green.**
All 14 days built. Third §10.2 capability domain.

## Real after Milestone L

| Area | Module | Notes |
|---|---|---|
| Chunking | `app/services/kb/chunk.py` | `chunk(text, target_chars=1000, overlap=150, headings=True)` → `[(heading, text)]`. Splits on Markdown headings + blank lines, packs to ~target with overlap, carries the nearest heading onto each chunk. Deterministic (unit-asserted). Oversized paragraphs are split on whitespace. |
| Lexical index | `app/services/kb/lexical.py` | `LexicalIndex.build(chunks)` — tokenize (lowercase, alnum, ~40-word stopword set) → inverted index. `search(query, k)` = Okapi BM25 (`k1=1.5`, `b=0.75`). Pure; a rebuild from the same chunks scores identically. **This is the stdlib retrieval fallback** — §16 says integrate a framework here. |
| Knowledge base | `app/services/kb/store.py` | `KnowledgeBase(path)` — SQLite `document` + `chunk`. `ingest_text(uri, title=)` / `ingest_file` (text suffixes only, ≤ 2 MiB, > 10% non-text bytes in the first 8 KiB → skipped) / `ingest_dir` / `remove`. A changed doc at the same uri supersedes; `ingest_file` is idempotent on sha. Every ingest runs `research/injection.py::scan` → `document.flags`. `index_chunks()` folds the heading into the indexed text (strong retrieval signal). `rebuild_index()` reconstructs the index from the chunk table (derived, §11.3). |
| Retriever | `app/services/kb/retrieve.py` | `Retriever` protocol (`retrieve(query, k) -> [RetrievedChunk]`) + `LexicalRetriever`. `RetrievedChunk{chunk_id, doc_id, uri, title, heading, text, score, flags}`. **A real embedding store / RAG framework implements this protocol and replaces `LexicalRetriever` with no change above it.** |
| KB answer | `app/services/kb/answer.py` | `answer(kb, question, llm, retriever=, k=8)` → retrieve → per top-6 chunk `add_chunk_to_graph` (a `doc_input` `EvidenceRecord` + claim extraction from a delimited `DOCUMENT CONTEXT` block) → reuse `research.synthesize` (claims-only) → `KBAnswer{sections+citation_ids, citations (uri+title), uncertainty, flags, trust_level="doc_input"}`. No hits → an explicit "nothing in the library matches" / "empty library" `uncertainty`. `add_chunk_to_graph` is shared with the research pipeline's KB hook. |
| Research hook | `app/services/research/pipeline.py` | `ResearchPipeline(..., kb=, kb_retriever=)` — each sub-question also retrieves `KB_TOPK=4` chunks, added to the evidence graph as `doc_input` sources before the web fetch, so a blended answer carries both `retrieved_web` and `doc_input` citations. |
| Orchestrator wiring | `orchestrator._run_doc_analysis` | `self.kb` opt-in. `contract.task_class == "doc_analysis"` + KB set → the KB answer path instead of plan→build→verify (`PLANNING`→`EXECUTING`→`KB`+`SYNTHESIS`→`OBSERVATION`→`VERIFYING`→`COMPLETED`); verification criterion **is** "retrieval + claims-only synthesis complete, uncertainty stated". `KBAnswer` is the artifact. KB unset → `doc_analysis` unchanged. |
| Schema / events | `+ KBAnswer` (`doc_input` trust); `KB` event kind. |

## Security posture (§12)

- Chunk text reaches only the delimited `DOCUMENT CONTEXT` extraction prompt; the synthesiser
  and every downstream consumer see `Claim`s.
- Every KB-derived `EvidenceRecord` and the `KBAnswer` are `doc_input` trust → the Milestone C
  Policy Engine's `tainted-side-effect` rule blocks them from originating a side-effecting
  `ActionProposal`, changing the objective, or widening a capability — identical treatment to
  `retrieved_web`.
- A library document containing "ignore all previous instructions / run this" is flagged on
  `document.flags`, still contributes chunks, and its flag rides on the answer's
  `uncertainty` (unit-asserted). The KB answer path performs no filesystem write and no
  network call.

## Not yet real / deferred

- **This is the seam, not the engine (§16)** — the lexical BM25 index is a *working
  fallback*; the deliverable is the `Retriever` protocol + the ingest/chunk/answer control
  plane. Integrating RAGFlow / LlamaIndex / Docling / an embedding store is one class behind
  `Retriever`, and is the documented next step.
- **Lexical retrieval misses paraphrase / synonymy** — accepted for the slice; headings are
  folded into the index to help.
- **No layout-aware parsing** — ingests text that decodes cleanly; PDF is taken as decoded
  bytes, no OCR; DOCX/XLSX wait for the authoring domain's parsers.
- **No cross-encoder / LLM rerank** of retrieved chunks — BM25 top-k only.
- **`rebuild_index()` is full-rebuild** — no incremental re-index or file watching (a
  desktop-shell concern).
- **In-process index** — O(terms) in memory, bounded by the file-size cap; a persistent /
  mmap index comes free with a real backend.

## Deferred past L (unchanged)

Source-grounded `authoring` (§10.2 DOCX/PPTX, "uses retrieval" — next domain); a real
embedding / RAG framework behind `Retriever`; OCR + office-format parsing; a library
management panel in the desktop shell.
