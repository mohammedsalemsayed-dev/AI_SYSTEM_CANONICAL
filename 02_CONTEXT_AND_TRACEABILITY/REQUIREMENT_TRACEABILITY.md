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
| Hybrid local/cloud workstation | Complete Spec §§1–4 | Router / provider abstraction | `RunPlan`, `ModelRunRecord` | G (static table until B produces data) | Benchmark, Integration | FOUNDATION |
| 8 GB VRAM-aware operation | Complete Spec hardware/routing | Hardware scheduler / modes | `HardwareSnapshot`, `RunPlan` | G | Resource | FOUNDATION |
| Specialized independent agents | Complete Spec agent/decision sections | Orchestrator + role contracts | `AgentMessage`, `RunPlan` | E | Integration, Failure | FOUNDATION |
| Intent / prompt compilation | Complete Spec §8 / D14 | Interpreter + immutable request | `OriginalRequest`, `TaskContract` | B | Unit, Integration | FOUNDATION (slice: Interpreter + no-verifiable-T0 guard) |
| Meaningful progress / loop detection | D3 / D4 / contracts | Progress observer | `ProgressEvent`, `Observation` | D | Unit, Failure, Recovery | FOUNDATION |
| Workspace + capability security | Security section / D12 | Policy / capability / execution boundary | `ActionProposal`, `PolicyDecision`, `CapabilityGrant` | C | Security | FOUNDATION ONLY |
| Approval levels | broader requirements + security | Approval service | `PolicyDecision` (`REQUIRE_APPROVAL`) | C | Security | NOT YET IMPLEMENTED |
| Recovery / idempotency / reconciliation | Recovery architecture | Checkpoints / reconciliation | `Checkpoint`, `ReconcileDecision` | D | Recovery | FOUNDATION |
| Hierarchical memory | Memory section / D6 | Memory / retrieval / context builder | `ProjectMemory` (working/project/experience/system) | F | Unit, Integration | NOT YET IMPLEMENTED |
| Experience repository | D5 + memory/learning | Experience lifecycle / evaluation | `ExperienceRecord` (+ `guardrail_result`, `shadow_replay_log`) | F | Integration, Benchmark | FOUNDATION |
| Learn from validated cloud outputs | D8 | benchmark / experience ingestion | `ExperienceRecord`, `ModelRunRecord` | F → I | Benchmark | NOT YET IMPLEMENTED |
| Autonomous internet research | D16 / research requirements | Research pipeline / evidence graph | `EvidenceRecord` (`trust_level=retrieved_web`), `Claim` | CD-research (after E) | Security, Integration | NOT YET IMPLEMENTED |
| Whole-repository understanding | broader requirements | repo index / dependency / change impact | `RepoIndex` | CD-repo-intel (after C) | Integration | NOT YET IMPLEMENTED |
| AI coding autonomy levels | broader requirements | capability / approval profiles | `CapabilityGrant`, `PolicyDecision` | C | Security | NOT YET IMPLEMENTED |
| Git integration | broader requirements | Git adapter / change lifecycle | `ArtifactVersion` | CD-git (after C) | Integration, Recovery | NOT YET IMPLEMENTED |
| Automated code review | broader requirements | build / test / static / AI / security / perf review | `VerificationRecord`, `EvidenceRecord` | E (Critic + Verifier roles) | Integration, Security | NOT YET IMPLEMENTED |
| Windows / Android / Godot / Unreal | product requirements | declared tool adapters / expert modes | adapter packages | CD-engines (after CD-repo-intel) | Integration, Resource | NOT YET IMPLEMENTED |
| Research / RAG knowledge base | research requirements | ingestion / index / retrieval | `EvidenceRecord`, embeddings (derived) | CD-rag (after CD-research) | Integration | NOT YET IMPLEMENTED |
| DOCX / PDF generation | product requirements | document adapters | `ArtifactVersion` (`task_class=authoring`) | CD-docx (after F) | Integration | NOT YET IMPLEMENTED |
| Presentation generation | product requirements | presentation pipeline | `ArtifactVersion` (`task_class=authoring`) | CD-pptx (after F) | Integration | NOT YET IMPLEMENTED |
| Futuristic desktop UI | D10 / UI | Tauri / React app | event-log derived views (§11.2) | H (parallel from B) | Integration | FOUNDATION |
| Agent questions / ambiguity | D11 | `WAITING_FOR_USER` protocol | `ClarificationRequest`, `TaskContract.ambiguity` | B | Unit, Integration | FOUNDATION |
| Hardware / power protection | D15 | telemetry / admission modes | `HardwareSnapshot` | G | Resource | FOUNDATION ONLY |
| Model benchmarking | D17 | benchmark DB / evaluator / router | `ModelRunRecord` ↔ `VerificationRecord` | G | Benchmark | NOT YET IMPLEMENTED |
| Controlled self-improvement | architecture roadmap | offline evaluation / canary / regression | `ExperienceRecord.guardrail_result` | I | Benchmark, Failure | NOT YET IMPLEMENTED |
| Test gates | acceptance strategy | unit / integration / failure / security / recovery / resource / benchmark | `VerificationRecord` (tiers T0–T3) | A → I (all) | all | FOUNDATION ONLY |
| End-to-end independent verification | Complete Spec completion + DESIGN_TIGHTENING §5 | Verification ladder T0–T3 | `VerificationRecord` | B (T0/T2), E (independent Verifier) | Integration, Security | FOUNDATION (slice: T0 tier — fresh checkout + apply diff + pytest) |
| Budget / cost-latency control | DESIGN_TIGHTENING §11.1 | budget tracker + scheduler admission | `TaskContract.budget` | D | Resource, Failure | NOT YET IMPLEMENTED |
| Prompt-injection defense | ACCEPTANCE security + DESIGN_TIGHTENING §12 | trust levels + injection corpus | `EvidenceRecord.trust_level` | CD-research | Security | NOT YET IMPLEMENTED |
| Task taxonomy (`task_class`) | DESIGN_TIGHTENING §6 | Interpreter classification rubric | `TaskContract.task_class` | B | Unit | FOUNDATION (slice: 9-class enum assigned at interpretation) |
| Canonical event log + derived views | Master Spec 4.3 / DESIGN_TIGHTENING §1, §11.2 | append-only log + folds | all records (creation events) | A | Recovery, Integration | FOUNDATION (slice: SQLite append-only log + snapshot projection, replay-tested) |

## Status definitions

- **FOUNDATION** — a contract or scaffold exists; not production-complete.
- **FOUNDATION ONLY** — a placeholder exists but the enforcing mechanism is not built.
- **NOT YET COMPLETE** — partially specified in code; contract not fully satisfied.
- **NOT YET IMPLEMENTED** — requirement remains active and must not be treated as removed.

Absence from the current code is **not** removal. A requirement listed here stays active
until a newer explicit decision in the Complete Claude-Code Spec supersedes it.
