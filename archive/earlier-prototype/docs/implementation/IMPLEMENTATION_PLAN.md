# Implementation Plan

> **Cross-reference**
> - Role: Milestones A–I as one cumulative repository proven through vertical slices.
> - Authority: Authoritative implementation order.
> - Upstream (consumes): [00_MASTER_SPEC.md](../00_MASTER_SPEC.md).
> - Downstream (depended on by): [IMPLEMENTATION_STATUS.md](../../../../02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the milestone column of [REQUIREMENT_TRACEABILITY.md](../../../../02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md).
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../../../../DESIGN_TIGHTENING.md) — §10 adds the dependency edges between A–I and the capability-domain packages (CD-*), with full scope preserved.

Implement the architecture as one cumulative repository, but prove it through vertical slices.

## Milestone A — Foundation
Configuration, schemas, canonical state machine, PostgreSQL persistence, event model, tests, API health.

## Milestone B — Real vertical slice
Request → TaskContract → planner → builder → isolated workspace → evidence → independent verifier → result.

## Milestone C — Security and authority
Capabilities, approvals, secret isolation, action validation, audit, path traversal tests, execution adapters.

## Milestone D — Recovery and progress
Checkpoints, idempotency, meaningful-progress scoring, loop detection, reconciliation after restart.

## Milestone E — Multi-agent coordination
Researcher, Critic, Verifier, structured messages, disagreement handling, benchmark single vs multi-agent.

## Milestone F — Memory and experience
Scoped memory, retrieval filters, context builder, trust states, experience lifecycle, quarantine.

## Milestone G — Routing and hardware
Provider registry, benchmark DB, local/cloud routing, scheduler admission, hardware modes, degraded operation.

## Milestone H — Desktop experience
Tauri + React + TypeScript UI, real-time events, agent activity, approvals, task/evidence/memory/hardware panels.

## Milestone I — Controlled optimization
Offline evaluation, prompt/context experiments, routing experiments, agent composition experiments, canary tests, regression protection.

Do not mark a milestone complete because a demo looks good. Use observable acceptance criteria.
