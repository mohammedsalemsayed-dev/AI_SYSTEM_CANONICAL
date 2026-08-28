# Requirement Traceability — Connective Index

> **Cross-reference**
> - Role: The single index where every requirement is connected to its source, its architecture target, the contracts it touches, its build milestone, its acceptance gate, and its status.
> - Authority: Reconciliation aid; does not override an explicit final decision in the Complete Claude-Code Spec.
> - Upstream (consumes): all authoritative documents.
> - Downstream (depended on by): [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md), [ACCEPTANCE.md](../03_IMPLEMENTATION_FOUNDATION/prior_foundation/docs/testing/ACCEPTANCE.md), [IMPLEMENTATION_PLAN.md](../03_IMPLEMENTATION_FOUNDATION/prior_foundation/docs/implementation/IMPLEMENTATION_PLAN.md).
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../DESIGN_TIGHTENING.md) — §13 defines this index, §10 defines the milestones, §5 defines the verification tiers named in the acceptance column.

This matrix prevents requirements from disappearing during implementation, and connects each
one to the rest of the design. Every row links: **authoritative source → architecture target
→ contracts touched → milestone (DESIGN_TIGHTENING §10) → acceptance category
([ACCEPTANCE.md](../03_IMPLEMENTATION_FOUNDATION/prior_foundation/docs/testing/ACCEPTANCE.md)) → status**.

Milestone codes (see [DESIGN_TIGHTENING.md](../DESIGN_TIGHTENING.md) §10):
A Foundation · B Vertical slice · C Security/authority · D Recovery/progress ·
E Multi-agent · F Memory/experience · G Routing/hardware · H Desktop shell ·
I Controlled optimization · **CD-x** capability domain (built after its prerequisite).

Contract names: those in
[CORE_CONTRACTS.md](../03_IMPLEMENTATION_FOUNDATION/prior_foundation/docs/contracts/CORE_CONTRACTS.md)
plus the records added in [DESIGN_TIGHTENING.md](../DESIGN_TIGHTENING.md) §3
(`OriginalRequest`, `RunPlan`, `Plan`/`PlanStep`, `PolicyDecision`, `CapabilityGrant`,
`Observation`, `VerificationRecord`, `Checkpoint`, `ClarificationRequest`).

| Requirement domain | Authoritative source | Architecture target | Contracts touched | Milestone (§10) | Acceptance category | Status |
|---|---|---|---|---|---|---|
| Hybrid local/cloud workstation | Complete Spec §§1–4 | Router / provider abstraction | `ProviderSpec`, `RouteDecision`, `ModelRunRecord` | G (static table until B produces data) | Benchmark, Integration | FOUNDATION (slice: provider registry + static §7.1 table + escalation triggers + data-driven blend once eligible + ε-exploration; local backend adapter is a named seam) |
| 8 GB VRAM-aware operation | Complete Spec hardware/routing | Hardware scheduler / modes | `HardwareSnapshot`, `HardwareMode` | G | Resource | FOUNDATION (slice: `NORMAL…EMERGENCY` mode policy + monitor seam; router pauses on EMERGENCY, biases local on CONSERVATION+; real telemetry deferred) |
| Specialized independent agents | Complete Spec agent/decision sections | Orchestrator + role contracts | `AgentMessage`, `CriticReport`, `RolePerformance` | E | Integration, Failure | FOUNDATION (slice: Critic + independent T2 ensemble + Researcher + structured AgentMessage + composition rule) |
| Intent / prompt compilation | Complete Spec §8 / D14 | Interpreter + immutable request | `OriginalRequest`, `TaskContract` | B | Unit, Integration | FOUNDATION (slice: Interpreter + no-verifiable-T0 guard) |
| Meaningful progress / loop detection | D3 / D4 / contracts + DESIGN_TIGHTENING §14.4 | Progress observer + loop detector | `ProgressEvent`, `Observation` | D | Unit, Failure, Recovery | FOUNDATION (slice: 6 hard signals + novel-motion guard + structural loop detector + escalation ladder) |
| Workspace + capability security | Security section / D12 | Policy / capability / execution boundary | `ActionProposal`, `PolicyDecision`, `CapabilityGrant` | C | Security | FOUNDATION (slice: capability registry + scoped grants + 7-rule Policy Engine; sandbox runtime pending Docker) |
| Approval levels | broader requirements + security | Approval service | `PolicyDecision` (`REQUIRE_APPROVAL`), `ApprovalRequest/Decision` | C | Security | FOUNDATION (slice: `REQUIRE_APPROVAL` -> `WAITING_FOR_USER` -> `resume(approval=...)`) |
| Recovery / idempotency / reconciliation | Recovery architecture | Checkpoints / reconciliation | `Checkpoint`, `ReconcileDecision` | D | Recovery | FOUNDATION (slice: reconcile() RESUME/REPAIR/ESCALATE/NOOP wired into resume(); checkpoints + idempotency-key tracking) |
| Hierarchical memory | Memory section / D6 | Memory / retrieval / context builder | `MemoryRecord` (working/project/experience/system) | F | Unit, Integration | FOUNDATION (slice: SQLite memory store + supersession + trust-filtered scoped retrieval + `build_context` feeding Interpreter/Planner; persistent RolePerformance in system memory) |
| Experience repository | D5 + memory/learning | Experience lifecycle / evaluation | `ExperienceRecord` (+ `guardrail_result`, `shadow_replay_log`) | F | Integration, Benchmark | FOUNDATION (slice: situation signature + full OBSERVED→…→STALE/QUARANTINED gate machine + capture on COMPLETED + advisory retrieval at PLANNING + automatic catastrophic rollback) |
| Learn from validated cloud outputs | D8 | benchmark / experience ingestion | `ExperienceRecord`, `EvalReport`, `ModelRunRecord` | F, I | Benchmark | FOUNDATION (slice: validated-promotion path + real held-out `OfflineEval` + frozen guardrail regression gate feeding `try_promote`; canary rollback on a bad promotion; real held-out numbers need the subscription) |
| Autonomous internet research | D16 / research requirements | Research pipeline / evidence graph | `EvidenceRecord`, `Claim`, `ResearchAnswer` (`retrieved_web` trust) | E (Researcher) + K (pipeline) | Security, Integration | FOUNDATION (slice: decompose → per-subq Researcher → evidence graph (support/agree/contradict edges) → bounded cross-check → claims-only synthesis → cited `ResearchAnswer` w/ mandatory uncertainty; `research_web` is a first-class deliverable flow; injection scan flags hostile sources; every node `retrieved_web` trust) |
| Whole-repository understanding | broader requirements | repo index / dependency / change impact | `RepoIndex`, `ImpactReport` | J (§10.2 domain 1, after C) | Integration | FOUNDATION (slice: `ast` symbol index + import dependency graph + blast-radius `ImpactReport` — dependent modules, affected tests, risk flags; Planner repo-context; impact-selected tests widen T0; breadth advisory; Python-first, tree-sitter deferred) |
| AI coding autonomy levels | broader requirements | capability / approval profiles | `CapabilityGrant`, `PolicyDecision` | C | Security | NOT YET IMPLEMENTED |
| Git integration | broader requirements | Git adapter / change lifecycle | `GitStatus`, `ArtifactVersion` | J (after C) | Integration, Recovery | FOUNDATION (slice: deterministic `GitAdapter` — status/log/blame/diff/changed-files read + `vcs.write`-gated local branch/commit; no network subcommand exists; `vcs.read`/`vcs.write` capability tokens) |
| Automated code review | broader requirements | build / test / static / AI / security / perf review | `VerificationRecord`, `CriticReport` | E (Critic + Verifier roles) | Integration, Security | FOUNDATION (slice: Critic pass + T2 ensemble + disagreement protocol; T0 authoritative) |
| Windows / Android / Godot / Unreal | product requirements | declared tool adapters / expert modes | adapter packages | CD-engines (after CD-repo-intel) | Integration, Resource | NOT YET IMPLEMENTED |
| Research / RAG knowledge base | research requirements | ingestion / index / retrieval | `KBAnswer`, `EvidenceRecord` (`doc_input`), `Retriever` protocol | L (after K) | Integration | FOUNDATION (slice: `KnowledgeBase` SQLite ingest + heading-aware chunking + BM25 lexical retrieval behind a `Retriever` protocol + claims-only KB answer at `doc_input` trust; `doc_analysis` is a first-class flow; a real embedding/RAG framework is the documented integration point behind `Retriever` — §16) |
| DOCX / PDF generation | product requirements | document adapters | `ArtifactVersion` (`task_class=authoring`) | CD-docx (after F) | Integration | NOT YET IMPLEMENTED |
| Presentation generation | product requirements | presentation pipeline | `ArtifactVersion` (`task_class=authoring`) | CD-pptx (after F) | Integration | NOT YET IMPLEMENTED |
| Futuristic desktop UI | D10 / UI | Tauri / React app | event-log derived views (§11.2) | H (parallel from B) | Integration | FOUNDATION (slice: 6 §11.2 read-model folds + loopback HTTP/JSON API + SSE event stream + a wired no-build frontend; opt-in gated task submit; Tauri v2 native-shell scaffold — sidecar entry + `src/main.rs` + config + one-command build — complete but not `cargo build`-verified here; needs a Rust/PyInstaller build host) |
| Agent questions / ambiguity | D11 | `WAITING_FOR_USER` protocol | `ClarificationRequest`, `TaskContract.ambiguity` | B | Unit, Integration | FOUNDATION |
| Hardware / power protection | D15 | telemetry / admission modes | `HardwareSnapshot`, `HardwareMode` | G | Resource | FOUNDATION (slice: mode policy + `EMERGENCY` pause + local bias wired into the router; monitor is a static-snapshot seam) |
| Model benchmarking | D17 | benchmark DB / evaluator / router | `ModelRunRecord` ↔ `VerificationRecord` | G, I | Benchmark | FOUNDATION (slice: `RouteStatsStore` in system memory, T1+-only scoring, windowed aggregates + ≥ 20-run eligibility feeding the data-driven router; guardrail suite + regression gate + routing canary in I; offline seeders built, not run) |
| Controlled self-improvement | architecture roadmap | offline evaluation / canary / regression | `EvalReport`, `RegressionResult`, `ExperienceRecord.guardrail_result` | I | Benchmark, Failure | FOUNDATION (slice: frozen guardrail suite + fail-closed regression gate + held-out `OfflineEval` gating `try_promote` + experience & routing canary rollback + `rebuild_metrics`; real held-out numbers need the subscription) |
| Test gates | acceptance strategy | unit / integration / failure / security / recovery / resource / benchmark | `VerificationRecord` (tiers T0–T3) | A → I (all) | all | FOUNDATION ONLY |
| End-to-end independent verification | Complete Spec completion + DESIGN_TIGHTENING §5 | Verification ladder T0–T3 | `VerificationRecord` | B (T0), E (T2 ensemble) | Integration, Security | FOUNDATION (slice: T0 deterministic + T2 model ensemble, advisory; disagreement protocol) |
| Budget / cost-latency control | DESIGN_TIGHTENING §11.1 | budget tracker + scheduler admission | `TaskContract.budget` | D | Resource, Failure | FOUNDATION (slice: wall_clock_s / steps / cost dims; 80% soft event, 100% pause; per-step admission) |
| Prompt-injection defense | ACCEPTANCE security + DESIGN_TIGHTENING §12 | trust levels + injection corpus | `ActionProposal.trust`, `EvidenceRecord.trust_level` | C, CD-research | Security | FOUNDATION (slice: structural taint + `tainted-side-effect` rule + 26-case corpus + traversal battery) |
| Task taxonomy (`task_class`) | DESIGN_TIGHTENING §6 | Interpreter classification rubric | `TaskContract.task_class` | B | Unit | FOUNDATION (slice: 9-class enum assigned at interpretation) |
| Canonical event log + derived views | Master Spec 4.3 / DESIGN_TIGHTENING §1, §11.2 | append-only log + folds | all records (creation events) | A | Recovery, Integration | FOUNDATION (slice: SQLite append-only log + snapshot projection, replay-tested) |

## Status definitions

- **FOUNDATION** — a contract or scaffold exists; not production-complete.
- **FOUNDATION ONLY** — a placeholder exists but the enforcing mechanism is not built.
- **NOT YET COMPLETE** — partially specified in code; contract not fully satisfied.
- **NOT YET IMPLEMENTED** — requirement remains active and must not be treated as removed.

Absence from the current code is **not** removal. A requirement listed here stays active
until a newer explicit decision in the Complete Claude-Code Spec supersedes it.
