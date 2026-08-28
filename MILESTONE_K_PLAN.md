# Milestone K — Research Pipeline & Evidence Graph Plan

> **Cross-reference**
> - Role: Build plan for the second §10.2 capability domain — a dedicated research-first orchestration and an evidence graph (claims ↔ sources ↔ contradictions), on top of the Milestone E Researcher + egress broker.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §6 (`research_web` task class), §7.1 (route: local-reasoner synthesis, escalate on an unresolved contradiction), §10.2 (capability domain 2: *Research pipeline + evidence graph → `research_web`*), §12 (prompt-injection / hostile-content model — the primary threat for this domain), §16 (prior art: AI2Agent Knowledge Repository, Investigate-Consolidate-Exploit, evidence-graph patterns — copy, don't invent).
> - Downstream (depended on by): RAG / knowledge base (§10.2 domain 3, "prereq: research pipeline"); source-grounded `authoring`.
> - Predecessors: E (the Researcher role, `EvidenceRecord`, `Claim`, the egress broker). Continues the `milestone_b/` tree.

---

## 1. Purpose

The Researcher exists but only as an escalation-ladder rung: one `question → query plan →
fetch → claims` pass whose claims feed the next re-plan. There is no decomposition, no
cross-check, no contradiction tracking, no synthesised deliverable — so `research_web` still
flows through the edit→verify path, which is wrong for a task whose output is an answer.

Milestone K adds the domain:

- an **evidence graph** — `EvidenceRecord` (sources) and `Claim` nodes, with support edges
  (claim → source), relation edges (claim ↔ claim: agrees / contradicts), and answer edges
  (sub-question → claim);
- a **research-first pipeline** — decompose the question → research each sub-question through
  the Researcher → assemble the graph → **cross-check** unresolved contradictions with
  follow-up queries → **synthesise** a cited answer with an explicit uncertainty statement;
- **orchestrator wiring** — a `research_web` task (or `qa_explain` that needs external
  sources) routes through the pipeline and produces a `ResearchAnswer` as its deliverable,
  not a diff.

Guiding rules (all §12):
- Source text lives **only** inside delimited `UNTRUSTED SOURCE CONTENT` blocks; the
  synthesiser consumes `Claim`s, never raw text.
- Every node is `retrieved_web` trust → the Policy Engine's `tainted-side-effect` rule
  (Milestone C) blocks a research answer from originating any side-effecting action, changing
  the objective, or widening a capability.
- The pipeline **scans sources for instruction-like content** and flags it; a flagged source
  still contributes claims but the flag rides on the answer.
- No fetch outside the egress broker (default deny). The sandbox still has no network.
- Bounded: a fixed max sub-questions, max fetch rounds, max cross-check rounds — research
  terminates.

## 2. In scope

| Concern | Milestone K implementation |
|---|---|
| Evidence graph | `research/evidence_graph.py`: `EvidenceGraph`. `add_source(EvidenceRecord)`, `add_claim(Claim, answers=<subq>)`, `relate(claim_a, claim_b, kind)` where kind ∈ `agrees` / `contradicts`. `sources_for(claim)`, `claims_for(subq)`, `contradictions()` (claim pairs with a `contradicts` edge, unresolved), `primary_source(claim)` (an `EvidenceRecord.kind == "doc"` or an allowlisted-official host ranks above a generic page). Pure data + queries; no LLM. |
| Contradiction detection | `research/crosscheck.py`: `detect(claims, llm)` → pairs of claim ids that make opposing assertions about the same subject (one bounded LLM call over the claim list, JSON out); `follow_up_queries(contradiction, graph)` → 1–2 URLs to disambiguate; `resolve(graph, contradiction)` → mark resolved when a primary-source claim or a ≥2/3 majority backs one side, else leave unresolved (→ the §7.1 escalation trigger). |
| Question decomposition | `research/pipeline.py::decompose(question, llm)` → 2–`MAX_SUBQ` sub-questions (one LLM call, JSON out); a trivial question passes through as a single sub-question. |
| Research pipeline | `research/pipeline.py`: `ResearchPipeline(researcher, llm)`. `run(task_id, question) -> ResearchResult{answer: ResearchAnswer, graph: EvidenceGraph, rounds, flags}`. Loop: decompose → per sub-question `researcher.research(...)` → graph assembly → `crosscheck.detect` → for each unresolved contradiction, ≤ `MAX_CROSSCHECK` follow-up fetch+extract rounds → `synthesize`. |
| Synthesis | `research/synthesize.py`: `synthesize(question, graph, flags, llm)` → `ResearchAnswer`. One LLM call whose input is the **claims + their source refs only** (never raw source text). Output: `sections[]` (each a statement + `citation_ids`), `contested[]` (unresolved contradictions, both sides cited), `uncertainty` (explicit: coverage gaps, flagged sources, single-source claims), `citations[]` (id → {source, host}). `trust_level="retrieved_web"`. |
| Injection scan | `research/injection.py`: `scan(text) -> list[str]` — flags imperative / tool-directive / "ignore previous" / system-prompt-like patterns in a source. Used on every fetched source; the flag list rides on `ResearchResult.flags` and into `uncertainty`. |
| Schemas | `+ ResearchAnswer`, `+ ContradictionRecord`, `+ ResearchResult` (light) in `contracts.py`. |
| Orchestrator wiring | `self.research = None` opt-in (a `ResearchPipeline`). In `_drive`, when `contract.task_class == "research_web"` (or a `qa_explain` contract whose `required_evidence` names external sources) **and** `self.research` is set: run the pipeline instead of plan→build→verify; log `RESEARCH` (per round) + `SYNTHESIS` (the answer) events; the `TaskResult` carries the answer as its artifact; state goes `PLANNING → EXECUTING → COMPLETED` with the answer as the deliverable (no T0 — verification for research is the cross-check + the uncertainty statement, §5 T-ladder note). Unset, or any other class → unchanged. |
| Events | `RESEARCH` (a round: sub-question, urls, n claims, flags), `SYNTHESIS` (the `ResearchAnswer`). |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Real live web fetch | still an injected opener in tests; the egress broker's first real fetch is a separate step |
| Embedding / vector retrieval over sources | RAG (§10.2 domain 3) — K's graph is keyed on sub-questions + claim text, no embeddings |
| A persistent knowledge base / user library | RAG |
| PDF / HTML boilerplate stripping, readability extraction | later — K takes the broker's bytes decoded as text, truncated |
| Multi-hop citation chains / provenance beyond one level | later — one support level (claim → source) + one relation level (claim ↔ claim) |
| Automatic source-reputation learning | later — `primary_source` uses a static rank (doc kind / official host) |

## 4. Component layout

```
app/services/research/
  evidence_graph.py   EvidenceGraph — sources + claims + edges; queries
  injection.py        scan(text) -> instruction-like-content flags
  crosscheck.py       detect() / follow_up_queries() / resolve()
  decompose.py        decompose(question, llm) -> sub-questions
  synthesize.py       synthesize(question, graph, flags, llm) -> ResearchAnswer
  pipeline.py         ResearchPipeline.run(task_id, question) -> ResearchResult
app/schemas/contracts.py   + ResearchAnswer, ContradictionRecord
app/events/log.py          + RESEARCH, SYNTHESIS
app/orchestration/orchestrator.py   opt-in self.research; research_web -> pipeline branch
tests/
  unit/         test_evidence_graph, test_injection_scan, test_crosscheck,
                test_decompose, test_synthesize
  integration/  test_research_pipeline (scripted LLM + injected fetch),
                test_research_web_task (end to end through the orchestrator)
```

## 5. Work breakdown (~14 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `research/evidence_graph.py` — nodes, edges, `contradictions()`, `primary_source()`, `claims_for()`. Unit tests over a hand-built graph. |
| 3 | `research/injection.py` — `scan()` pattern set (imperative openers, "ignore previous", tool/JSON-directive shapes, fake system markers). Unit tests: a benign paragraph → no flags; a planted directive → flagged. |
| 4–5 | `research/decompose.py` + `research/crosscheck.py` (`detect` / `follow_up_queries` / `resolve`) — scripted-LLM unit tests for each. |
| 6–8 | `research/synthesize.py` — claims-only input, `ResearchAnswer` shape (`sections` / `contested` / `uncertainty` / `citations`); asserts no raw source text is passed to the LLM. `ResearchAnswer` schema. Unit tests. |
| 9–11 | `research/pipeline.py` — `ResearchPipeline.run()`: decompose → per-subq `researcher.research` → graph → crosscheck rounds (bounded) → synthesize. Integration test with a `ScriptedLLM` and an injected broker opener returning canned pages incl. a contradiction. |
| 12 | Orchestrator wiring — `self.research` opt-in; `research_web` branch in `_drive` (pipeline instead of plan→build→verify); `RESEARCH` / `SYNTHESIS` events; the answer as the `TaskResult` artifact. |
| 13 | Integration — a `research_web` task runs the pipeline end to end and returns a cited `ResearchAnswer`; an unresolved contradiction shows in `contested` and (with the router wired) escalates; a source with a planted directive is flagged in `uncertainty` and never changes the objective. |
| 14 | Regression; `milestone_b/MILESTONE_K_NOTES.md`; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the top-level [README.md](README.md); rehash `MANIFEST.json`; commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — the graph reports the right `sources_for` / `claims_for` / `contradictions`;
  `primary_source` ranks a `doc` / official host above a generic page; `injection.scan`
  flags a planted directive and passes clean prose; `crosscheck.detect` (scripted) returns
  the contradicting pair and `resolve` closes it when a primary source backs one side;
  `synthesize` produces `sections` with `citation_ids`, lists unresolved contradictions under
  `contested`, and its LLM prompt contains **no** raw source excerpt (only claim text +
  refs).
- **Integration** — `ResearchPipeline.run` over scripted providers + an injected opener
  returns a `ResearchAnswer` citing ≥ 2 sources; a canned contradiction lands in `contested`
  with both sides cited; through the orchestrator, a `research_web` task reaches `COMPLETED`
  with the answer as its artifact and `RESEARCH` + `SYNTHESIS` events on the log. `research`
  unset → `research_web` still flows the old path unchanged.
- **Failure** — every fetch denied (empty allowlist) → the pipeline returns a
  `ResearchAnswer` whose `uncertainty` says "no sources retrieved", not a crash; the
  cross-check round cap is honoured (a permanent contradiction terminates).
- **Security (§12)** — a source containing `"ignore previous instructions and run …"` is
  flagged, its claims are still extracted but the objective, capability grants, and policy
  decisions are unchanged; the `ResearchAnswer` is `retrieved_web` trust and cannot pass the
  Policy Engine as the origin of a side-effecting `ActionProposal`; no fetch bypasses the
  egress broker.
- **Recovery** — `reconcile()` + `resume()` work for a research task; an interrupted pipeline
  leaves a partial graph in the event log and resumes by re-running (research is idempotent —
  no side effects).
- **Benchmark** — n/a (no deterministic oracle for an open research answer; the cross-check +
  uncertainty statement is the quality gate).

## 7. Tunable starting values

- `MAX_SUBQ` = **5**, `MAX_FETCH_PER_SUBQ` = **3** (the Researcher's own cap), `MAX_CROSSCHECK`
  = **2** rounds per contradiction.
- `SOURCE_TEXT_CAP` = **6000** chars/source (matches the Researcher), synthesised answer
  input = claim text only.
- `primary_source` rank: `doc` kind = 3, official host (allowlist entry) = 2, other = 1.
- Contradiction "resolved" = a primary-source claim on one side, OR ≥ 2/3 of claims on that
  side and none from a primary source on the other.

## 8. Risks

- **Open research has no ground truth** — quality is bounded by the sources and the model.
  Mitigate: the deliverable is *cited* (every statement traces to a source), *contested*
  points are explicit, and `uncertainty` is mandatory — the answer never overstates.
- **Injection is the headline threat (§12)** — a hostile page could try to steer the model.
  Mitigate: source text never reaches a decision prompt (only claims do), the synthesiser is
  claims-only, `injection.scan` flags directives, and every research output is `retrieved_web`
  trust so it structurally cannot authorise anything.
- **`injection.scan` is pattern-based** — it will miss novel phrasings and over-flag some
  legit imperative prose. It is a *signal on the answer*, not a gate that drops content, so a
  miss degrades to "unflagged advisory answer", not a breach — the trust boundary is the real
  protection.
- **Cross-check can loop on a genuine open question** — bounded by `MAX_CROSSCHECK`; an
  unresolved contradiction is reported, not chased forever.
- **Decomposition can fragment a simple question** — a trivial question passes through as one
  sub-question; `MAX_SUBQ` caps the blow-up.

## 9. Deliverables

- `app/services/research/` — `evidence_graph.py`, `injection.py`, `crosscheck.py`,
  `decompose.py`, `synthesize.py`, `pipeline.py`.
- `ResearchAnswer` / `ContradictionRecord` schemas; `RESEARCH` / `SYNTHESIS` events.
- Orchestrator: opt-in `ResearchPipeline`; `research_web` runs the pipeline and returns a
  cited `ResearchAnswer`.
- Test suite: the current 333 green, plus unit (graph / injection / crosscheck / decompose /
  synthesize) and integration (pipeline / `research_web` end to end).
- `milestone_b/MILESTONE_K_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the
  top-level [README.md](README.md) updated: "Autonomous internet research" moves to
  FOUNDATION for the pipeline + evidence graph; `research_web` becomes a first-class flow.
