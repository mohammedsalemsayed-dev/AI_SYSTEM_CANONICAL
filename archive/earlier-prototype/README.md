# Autonomous Hardware-Aware Multi-Agent AI System — FINAL

> **Cross-reference**
> - Role: Package overview — authority order, build target, non-negotiable invariants.
> - Authority: Consolidated from the authoritative source documents; those govern on conflict.
> - Upstream (consumes): Complete Claude-Code Spec, Master Blueprint.
> - Downstream (depended on by): every file under `docs/`.
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../../DESIGN_TIGHTENING.md) — §2 component interfaces, §3 record relational model.

This is the canonical, cumulative implementation package. It replaces the fragmented V7–V11 packaging model.

## Authority order
1. docs/00_MASTER_SPEC.md
2. docs/architecture/END_TO_END_ARCHITECTURE.md
3. docs/contracts/CORE_CONTRACTS.md
4. docs/decision_history/ACTIVE_DECISIONS.md
5. docs/implementation/IMPLEMENTATION_PLAN.md
6. subsystem specifications and tests

Newer active decisions supersede older alternatives. Do not weaken deterministic boundaries with prompts.

## Build target
Python/FastAPI modular monolith + PostgreSQL + Redis/event transport + isolated execution adapters + Tauri/React/TypeScript desktop UI.

## First proof
User request → interpretation → Task Contract → plan → specialized agents where useful → policy/capability checks → isolated workspace execution → evidence/tests → independent verification → artifact/result/events/checkpoint.

## Non-negotiable invariants
- LLMs propose; deterministic services enforce.
- Workspace folders alone are not a security boundary.
- Completion is evidence-based, not confidence-based.
- Meaningful progress is required to avoid loops; fixed timeouts are only signals.
- Retries must be idempotent where side effects exist.
- Recovery reconciles actual state.
- Experience learning is Candidate → Validated → Promoted → Monitored → Stale/Quarantined.
- Local/cloud selection is empirical and hardware-aware.
- Hardware health and power use are first-class scheduling inputs.
- Independent agents may disagree; consensus is not proof.
- The UI is an application, not a terminal.
