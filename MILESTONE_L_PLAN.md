# Milestone L — RAG / Knowledge Base Plan

> **Cross-reference**
> - Role: Build plan for the third §10.2 capability domain — a knowledge-base ingestion/index/retrieval layer over the user's document library, producing source-grounded answers behind the §5-C boundary.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §6 (`doc_analysis` task class), §7.1 (route: local-reasoner, escalate when the document exceeds the local window), §10.2 (capability domain 3: *RAG / knowledge base → source-grounded answers over the user's library*, "prereq: research pipeline"), §11.3 (embeddings/indexes are fully derived, rebuildable, evictable), §12 (`doc_input` trust — same hard rule as `retrieved_web`), §16 (prior art: **"Research / RAG / document understanding — Do not build. Integrate."** — RAGFlow / Docling / LlamaIndex / Haystack).
> - Downstream (depended on by): source-grounded `authoring` (§10.2 DOCX/PPTX, "uses retrieval"); a KB-augmented research pipeline.
> - Predecessors: K (the research pipeline + claims-only synthesis + injection scan this reuses). Continues the `milestone_b/` tree.

---

## 1. Purpose

`doc_analysis` — "reason over supplied documents" — has no home. There is no way to put a
document library in front of the system, no chunking, no retrieval, no citation path back to
the user's own files.

§16 is explicit that the long-term move is to **integrate** an existing RAG framework, not
build one. So Milestone L builds exactly the control-plane half that such a framework plugs
into, plus a working stdlib fallback:

- a **`KnowledgeBase`** — SQLite documents + chunks, `ingest_text` / `ingest_file`, a
  derived index that rebuilds from the chunks;
- a **retriever interface** with a **lexical (BM25) fallback** that works now — a real
  embedding/vector backend (or a whole framework) slots in behind the same `Retriever`
  protocol;
- a **KB answer path** — retrieve chunks → claims-only synthesis (reuse Milestone K) → a
  cited `KBAnswer` whose citations point at the user's files;
- **orchestrator wiring** — a `doc_analysis` task (or `qa_explain` with a KB attached) runs
  the KB answer path; the research pipeline can additionally pull KB chunks as `doc_input`
  sources.

Guiding rules:
- **§12** — KB content is `doc_input` trust: it can never grant/widen a capability, originate
  a passing `ActionProposal`, change the objective, or cause a send/publish. Ingested
  documents are injection-scanned (reuse `research/injection.py`); a flagged doc still
  contributes chunks, the flag rides on the answer.
- **§11.3** — the index is derived: `rebuild_index()` reconstructs it from the chunk table;
  it may be dropped and rebuilt freely; nothing depends on it as a source of truth.
- **§16 / no new deps** — stdlib + `pydantic` only. The lexical index is the slice's
  retriever; the `Retriever` protocol is the integration seam for RAGFlow / LlamaIndex /
  an embedding store.
- **Claims-only synthesis** — the answer LLM sees retrieved chunk *text* only inside a
  delimited `DOCUMENT CONTEXT` block and is instructed it is data; the `KBAnswer` is
  `doc_input` trust.

## 2. In scope

| Concern | Milestone L implementation |
|---|---|
| Knowledge base | `kb/store.py`: `KnowledgeBase(path=":memory:")`. SQLite `document{id, uri, title, sha, bytes, ts, flags}` + `chunk{id, doc_id, ord, text, heading}`. `ingest_text(text, *, uri, title=)`, `ingest_file(path)` (utf-8 with errors="replace"; `.md/.txt/.rst/.py/.json/...` + `.pdf` only if it decodes to text — no OCR), `remove(doc_id)`, `documents()`, `chunks(doc_id=None)`, `rebuild_index()`. On ingest: chunk, `injection.scan` the raw text → `document.flags`. |
| Chunking | `kb/chunk.py`: `chunk(text, *, target_chars=1000, overlap=150, headings=True)` — split on blank lines / Markdown headings, pack to ~`target_chars` with `overlap`, carry the nearest heading onto each chunk. Deterministic. |
| Lexical index | `kb/lexical.py`: `LexicalIndex.build(chunks)` — tokenize (lowercase, split on non-alphanumeric, drop a small stopword set), inverted index `term -> {chunk_id: tf}`, doc lengths. `search(query, k=8)` — Okapi BM25 (`k1=1.5`, `b=0.75`), returns `[(chunk_id, score)]`. Pure, rebuildable. |
| Retriever | `kb/retrieve.py`: `Retriever` protocol (`retrieve(query, k) -> list[RetrievedChunk]`). `LexicalRetriever(kb)` wraps `LexicalIndex`. `RetrievedChunk{chunk_id, doc_id, uri, heading, text, score}`. A real embedding/framework backend implements the same protocol. |
| KB answer | `kb/answer.py`: `answer(kb, question, llm, *, retriever=None, k=8) -> KBAnswer`. Retrieve → build `EvidenceRecord`s at `doc_input` trust (source = the file uri) → reuse `research.synthesize` over **claims derived from the chunks** (one extraction call per top chunk, claims-only downstream) → `KBAnswer{question, sections+citation_ids, citations (uri + heading), uncertainty, flags, trust_level="doc_input"}`. No retrieval hit → `uncertainty` says "nothing in the library matches". |
| Research hook | `research/pipeline.py`: `ResearchPipeline(..., kb=None)` — when a KB is attached, each sub-question also retrieves `KB_TOPK` chunks, added to the evidence graph as `doc_input` sources before the web fetch, so a synthesis can blend library + web with per-source trust visible. |
| Schemas | `+ KBAnswer`, `+ RetrievedChunk` (light dataclass in `kb/retrieve.py`; `KBAnswer` a pydantic model in `contracts.py`). |
| Orchestrator wiring | `self.kb = None` opt-in. In `_drive`: `contract.task_class == "doc_analysis"` (or `qa_explain` with `self.kb` set and the objective referencing the library) → run the KB answer path (same `PLANNING → EXECUTING → OBSERVATION → VERIFYING → COMPLETED` shape as Milestone K research; verification = "retrieval + claims-only synthesis complete, uncertainty stated"); `KB` event(s); the `KBAnswer` is the artifact. Unset → unchanged. |
| Events | `KB` (ingest: uri, chunks, flags / retrieve: query, hits, top score). |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Real embeddings / vector store / a full RAG framework | the `Retriever` protocol is the seam — integrate RAGFlow / LlamaIndex / an embedding store later (§16) |
| OCR, layout-aware PDF, DOCX/XLSX parsing | later — L ingests text that decodes cleanly; binary office formats wait for the authoring domain's parsers |
| Cross-encoder / LLM rerank of retrieved chunks | later — BM25 top-k only |
| Incremental re-index / file watching | `rebuild_index()` is full-rebuild; a watcher is a desktop-shell concern |
| Multi-modal (images, tables as data) | never in the slice |
| Per-user library management UI | Milestone H panel later — L exposes `documents()` / `remove()` |

## 4. Component layout

```
app/services/kb/
  store.py      KnowledgeBase — SQLite document + chunk tables; ingest / rebuild
  chunk.py      chunk(text, ...) -> [ (heading, text) ]
  lexical.py    LexicalIndex — inverted index + BM25
  retrieve.py   Retriever protocol; LexicalRetriever; RetrievedChunk
  answer.py     answer(kb, question, llm, retriever=, k=) -> KBAnswer
app/schemas/contracts.py   + KBAnswer
app/events/log.py          + KB
app/services/research/pipeline.py   + optional kb= (doc_input sources into the graph)
app/orchestration/orchestrator.py   opt-in self.kb; doc_analysis -> KB answer path
tests/
  unit/         test_kb_chunk, test_kb_lexical, test_kb_store, test_kb_answer
  integration/  test_doc_analysis_task, test_kb_augments_research
```

## 5. Work breakdown (~14 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `kb/chunk.py` — heading-aware sliding-window chunking; deterministic. Unit tests (short text = 1 chunk; long text = overlapping chunks; headings carried). |
| 3–5 | `kb/lexical.py` — tokenizer + stopwords + inverted index + BM25 `search`. Unit tests: exact-term retrieval ranks the right chunk; a rebuild from the same chunks is identical; an empty query returns nothing. |
| 6–7 | `kb/store.py` — `KnowledgeBase` SQLite schema; `ingest_text` / `ingest_file` (chunk + `injection.scan` → `document.flags`); `documents()` / `chunks()` / `remove()` / `rebuild_index()`. Unit tests: ingest → chunks persisted; a flagged doc records the flag; `rebuild_index()` after a `remove()` reflects it. |
| 8 | `kb/retrieve.py` — `Retriever` protocol + `LexicalRetriever`; `RetrievedChunk`. Unit test: retrieval returns chunks with uri + heading + score, descending. |
| 9–11 | `kb/answer.py` — retrieve → `doc_input` `EvidenceRecord`s → claim extraction per top chunk → `research.synthesize` → `KBAnswer`. `KBAnswer` schema. Unit + a first integration with a scripted LLM and a seeded KB. Assert citations point at file uris and `trust_level == "doc_input"`. |
| 12 | `research/pipeline.py` `kb=` hook — sub-question KB retrieval adds `doc_input` sources to the evidence graph; a blended answer shows both trust levels in `citations`. |
| 13 | Orchestrator wiring — `self.kb` opt-in; `doc_analysis` branch runs the KB answer path; `KB` events; `KBAnswer` as artifact. Integration: a `doc_analysis` task over a 3-document KB returns a cited `KBAnswer`; a query with no match states the gap. |
| 14 | Regression; `milestone_b/MILESTONE_L_NOTES.md`; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the top-level [README.md](README.md); rehash `MANIFEST.json`; commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — `chunk()` is deterministic and carries headings; `LexicalIndex.search` ranks a
  chunk containing the query terms above one that does not, and a rebuild from the same
  chunks scores identically; `KnowledgeBase.ingest_*` persists chunks and records an
  injection flag for a planted-directive document; `rebuild_index()` reflects a prior
  `remove()`; `answer()` returns a `KBAnswer` whose `citations` carry the file uris and
  whose `trust_level == "doc_input"`, and whose synthesis input is claims/refs — not raw
  chunk text beyond the delimited context.
- **Integration** — a `doc_analysis` task over a seeded KB reaches `COMPLETED` with a
  `KBAnswer` artifact and `KB` + `SYNTHESIS` events; a question with no lexical overlap
  yields a `KBAnswer` whose `uncertainty` says nothing in the library matches; with `kb=`
  set, `ResearchPipeline.run` adds `doc_input` sources and the answer's `citations` include
  a file uri. KB unset → `doc_analysis` unchanged.
- **Failure** — ingesting a binary/undecodable file is skipped (recorded), not fatal; an
  empty KB answers with an explicit "empty library" uncertainty; a `rebuild_index()` mid-use
  does not corrupt an in-flight `retrieve` (index is swapped atomically).
- **Security (§12)** — every `KBAnswer` and every KB-derived `EvidenceRecord` is `doc_input`
  trust → the Policy Engine blocks it as the origin of a side-effecting `ActionProposal`; a
  document containing "ignore previous instructions / run this" is flagged, still
  contributes chunks, and changes no objective / grant / policy decision; the KB answer path
  performs no filesystem write and no network call.
- **Recovery** — `reconcile()` + `resume()` work with the KB tables present; the index is
  rebuilt on resume (derived); an interrupted ingest leaves the already-written chunks and
  is safe to re-run (`ingest_file` is idempotent on `sha`).
- **Benchmark** — n/a (no oracle for an open KB answer; retrieval + claims-only synthesis +
  the uncertainty statement is the quality gate).

## 7. Tunable starting values

- `chunk`: `target_chars = 1000`, `overlap = 150`, split on Markdown headings + blank lines.
- `LexicalIndex`: BM25 `k1 = 1.5`, `b = 0.75`; stopword set ~40 common English words.
- `retrieve` default `k = 8`; `answer` uses the top `k` chunks, extraction on the top `min(k, 6)`.
- `research` KB hook: `KB_TOPK = 4` chunks per sub-question.
- `ingest_file` size cap `2 MiB`; binary detection = > 10% non-text bytes in the first 8 KiB.

## 8. Risks

- **Lexical retrieval is weak vs embeddings** — BM25 misses paraphrase and synonymy. Accepted
  for the slice: it is a *working* fallback and the `Retriever` protocol is the real
  deliverable; §16 says integrate a framework here, and that swap is one class.
- **Chunking loses structure** — a sliding window can split a table or a code block. Mitigated
  by heading carry-over and overlap; layout-aware parsing is deferred with the office
  formats.
- **`doc_input` is as hostile as `retrieved_web`** — a user's own library can still contain a
  planted file (downloaded PDF, pasted note). Same mitigation as Milestone K: chunk text
  never reaches a decision prompt, the answer is `doc_input` trust, and `injection.scan`
  flags it.
- **Index memory on a large library** — the inverted index is in-process, O(terms). Bounded
  by the file-size cap and a document count the user controls; a persistent / mmap index is
  deferred (and would come free with a real backend).
- **"Do not build" tension (§16)** — L deliberately builds only the seam + a fallback, not a
  RAG engine. The risk is over-investing in the lexical path; mitigate by keeping
  `lexical.py` small and the protocol clean.

## 9. Deliverables

- `app/services/kb/` — `store.py`, `chunk.py`, `lexical.py`, `retrieve.py`, `answer.py`.
- `KBAnswer` schema; `KB` event kind.
- `ResearchPipeline(kb=)` hook; orchestrator `doc_analysis` → KB answer path.
- Test suite: the current 344 green, plus unit (chunk / lexical / store / answer) and
  integration (`doc_analysis` task / KB-augmented research).
- `milestone_b/MILESTONE_L_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the
  top-level [README.md](README.md) updated: "Research / RAG knowledge base" moves to
  FOUNDATION for the ingest/index/retrieve/answer seam with a lexical fallback; a real
  framework is the documented integration point.
