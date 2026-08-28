# Autonomous Hardware-Aware Multi-Agent AI System

Design package + working implementation foundation for a modular-monolith desktop AI
workstation: specialized agents reason and challenge each other while deterministic services
own state, permissions, execution boundaries, verification, recovery, memory trust,
controlled learning, hardware protection, and model routing.

- **Start here:** [`00_START_HERE/README_FOR_CLAUDE_CODE.md`](00_START_HERE/README_FOR_CLAUDE_CODE.md) (read order + authority rules)
- **Architecture wiring:** [`DESIGN_TIGHTENING.md`](DESIGN_TIGHTENING.md) (16 sections; §13 is the document map)
- **Requirement → milestone → status:** [`02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md`](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md)
- **Honest built-vs-active boundary:** [`02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md`](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md)
- **Running code:** [`milestone_b/`](milestone_b/README.md) — the live build (see its README for per-milestone detail and run instructions)

> The authoritative documents describe the **complete** target system. The code is a
> foundation built through integrated vertical slices — every deferred subsystem is present
> as a **named seam** (interface + stub), never silently dropped. "Foundation" ≠ "complete."

## Milestone status

Build order and dependencies: [`DESIGN_TIGHTENING.md`](DESIGN_TIGHTENING.md) §10.

| Milestone | Scope | Status |
|---|---|---|
| **A** Foundation | state machine, event log, contracts | scaffolded (prior foundation) |
| **B** Vertical slice | `request → contract → plan → edit → T0 verify → result` on one task class | **built** — driven Builder (Claude Agent SDK), event-sourced core, Docker T0 sandbox |
| **C** Security & authority | capability registry, scoped grants, 7-rule policy engine, sandbox tiers, approvals | **built** |
| **D** Recovery & progress | checkpoints, idempotency, reconciliation, 6 hard-progress signals, loop detector, escalation ladder | **built** |
| **E** Multi-agent | Critic (T0-first, can't false-reject), independent T2 ensemble verifier, disagreement protocol, Researcher, composition rule, RolePerformance | **built** |
| **F** Memory & experience | hierarchical memory (working/project/experience/system), trust-filtered retrieval, context builder, full `OBSERVED→…→STALE/QUARANTINED` lifecycle, advisory retrieval at planning, catastrophic rollback | **built** |
| **G** Routing & hardware | provider registry, static §7.1 table + escalation triggers, `RouteStatsStore` + ≥20-run eligibility + data-driven blend, hardware modes + `EMERGENCY` pause, real `stronger_model` ladder rung | **built** |
| **I** Optimization | frozen guardrail suite, fail-closed regression gate, held-out `OfflineEval` gating promotion, experience & routing canary rollback, `rebuild_metrics` (§11.2) | **built** |
| **H** Desktop shell | 6 §11.2 read-model folds, loopback HTTP/JSON API, SSE event stream, wired no-build frontend, opt-in gated task submit | **built** |
| **H** Tauri packaging | Tauri v2 native shell (Rust sidecar supervision) + PyInstaller `nexus-server` sidecar + one-command build | **scaffolded** — not `cargo build`-verified here; needs a Rust + PyInstaller build host |
| **J** Repo intelligence & Git adapter (§10.2 domain 1) | deterministic Git adapter, `ast` symbol index, import dependency graph, blast-radius `ImpactReport` (dependent modules + affected tests + risk flags), breadth advisory; impact-selected tests widen T0 | **built** |
| **K** Research pipeline & evidence graph (§10.2 domain 2) | question decomposition, per-sub-question Researcher, evidence graph (support/agree/contradict edges), bounded cross-check, claims-only synthesis → cited `ResearchAnswer` with mandatory uncertainty; `research_web` is a first-class flow; hostile-source injection scan | **built** |
| **L** RAG / knowledge base (§10.2 domain 3) | `KnowledgeBase` ingest + heading-aware chunking + BM25 lexical retrieval behind a `Retriever` protocol; claims-only KB answer at `doc_input` trust; `doc_analysis` is a first-class flow; research pipeline can blend library + web. A real embedding/RAG framework is the integration point behind `Retriever` (§16) | **built** |
| **M** Authoring pipelines (§10.2 domain 4) | `DocumentModel` + `SlideDeck`; outline → KB-grounded draft (cited, `doc_input` trust) → review pass → Markdown/HTML render; `authoring` is a first-class flow. DOCX/PPTX/PDF are `Renderer` stubs — drop in python-docx / python-pptx (§16) | **built** |
| **N** Engine adapters & expert modes (§10.2 domain 5) | Godot / Unreal / Android / generic project detection + `EngineInfo` (globs, build/test cmd, conventions) + expert prompt profiles injected at planning; engine-native build/test execution is the §5-C tier-C seam | **built** |
| **O** Automated model selection (§10.2 domain 6) | logistic-regression `WeightSet` fit over routing features + `ModelSelectionController` flipping a `task_class` static↔data-driven, gated by the guardrail regression check and demoted on a canary rollback; `PROVISIONAL_WEIGHTS` is now the fallback. A real fit needs a scored-run corpus (offline fitter built, not run) | **built** |
| **P** Artifact & version tracking | content-addressed `ArtifactStore` (sha-256 deduped blobs) + per-objective version chain with parent lineage + `diff_versions` + mark-never-delete archival (§11.3); the 4 deliverable paths store diff / research / KB / document artifacts at their own trust; `GET /api/artifacts/{id}` in the shell | **built** |
| **Q** Fault injection & recovery hardening | `app/services/faults/` wrappers (raise real backend exceptions) + a hard-kill log hook; `tests/fault/` 20 cases + a matrix runner (`FAULT_FINDINGS.md`, 14/14) proving safe-terminal / workspace-untouched / clean-`reconcile()` under 13 induced failure modes; forced the `EgressBroker → EgressError` fix | **built** |
| **R** Telemetry & target-machine calibration | live `HardwareMonitor` reading real RAM/CPU/disk + `nvidia-smi` GPU/VRAM (stdlib + `ctypes`, never raises); one-time `calibrate()` → `HardwareProfile` persisted to system memory; the profile scales the wall-clock budget; hardware sampling now runs every task independent of routing | **built** |
| **S** Tool adapter framework (§5-C / §10.2 spine) | one `ToolAdapter` Protocol + `ToolRegistry` over the scattered §10.2 tool packages; `manifest_block()` injected at planning + `ToolDispatcher` routing every op through the **existing** Policy Engine + caller `CapabilityGrant` (no new gate); git / fs / net(egress) / engine adapters; manifest `output_trust` stamped on the result so `retrieved_web` is never laundered; a tainted side-effecting op is denied by the existing rule. Routing the Builder through the dispatcher + a real tool ecosystem are the documented next steps | **built** |

**445 tests** green (`milestone_b/`, offline-deterministic; one runtime dependency: `pydantic`). **All six §10.2 capability domains are FOUNDATION, now behind one §5-C tool-dispatch spine.**

### Needs an external resource (built, not run here)

| Harness | Command | Needs |
|---|---|---|
| Premise test | `python -m tests.premise.run_real_tasks …` | Claude Pro subscription (`claude` CLI login) |
| Single-vs-multi benchmark | `python -m tests.benchmark.run_multiagent_bench …` | subscription — gates the Critic promote-to-default decision |
| Model eligibility seeder | `python -m tests.benchmark.seed_model …` | subscription |
| Guardrail regression runner | `python -m tests.regression.run_guardrail` (`--offline` works now) | subscription for the real-model run |
| Routing-weight fitter | `python -m tests.benchmark.fit_weights --write` | a populated `RouteStatsStore` (run the seeder first, on the subscription) |
| Native installers | `python desktop/build.py` | Rust toolchain + PyInstaller + platform build tools (+ signing certs) |

## Quick start (the running slice)

```bash
cd milestone_b
python -m pytest tests/unit tests/security tests/integration tests/regression tests/fault   # 445 green
python -m app.cli.demo                                                          # offline end-to-end
python -m app.ui.run_ui --db slice.db --port 8770                               # desktop shell -> http://127.0.0.1:8770
```

## Non-negotiable rules

- The Complete Claude-Code Spec is the primary authoritative source; summaries never replace it.
- Do not silently drop a requirement because it is not yet implemented.
- Do not confuse "planned" or "foundation" with "complete."
- Do not bypass security or verification for convenience.
