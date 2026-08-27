# Master Specification

> **Cross-reference**
> - Role: Frozen architecture and principles (consolidated from the Complete Claude-Code Spec).
> - Authority: Authoritative. The `.docx` Complete Spec is the primary source it consolidates.
> - Upstream (consumes): Complete Claude-Code Spec, Master Blueprint.
> - Downstream (depended on by): [END_TO_END_ARCHITECTURE.md](architecture/END_TO_END_ARCHITECTURE.md), [CORE_CONTRACTS.md](contracts/CORE_CONTRACTS.md), [IMPLEMENTATION_PLAN.md](implementation/IMPLEMENTATION_PLAN.md), all subsystem docs.
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../../../DESIGN_TIGHTENING.md) — §1 object flow, §4 control loops, §5 verification, §6 task taxonomy, §7 routing, §9 agent composition, §12 injection model.

## Product
A desktop AI workstation and technical partner capable of software engineering, repository understanding, research, document work, Windows/Android development, Godot/Unreal work, local AI experimentation, and controlled execution.

The system should understand intent, surface assumptions, challenge poor approaches, ask focused questions when ambiguity materially changes the outcome, and preserve the user's original objective.

## Target hardware
Primary target: NVIDIA RTX 5060 8 GB VRAM, 24 GB DDR5 RAM, Intel Core i5-14400F. The architecture must not assume a large-VRAM workstation. Heavy CPU/RAM offload is not automatically preferable to a smaller fast local model.

## Core architecture
Modular monolith. Specialized agents are used only when decomposition, diversity, independent review, or expertise adds measurable value.

Core initial roles:
- Interpreter / Intent Compiler
- Planner
- Researcher
- Builder / Executor
- Critic
- Independent Verifier
- Recovery / Reconciliation
- Router / Resource Scheduler

Roles are not mandatory for every task. The orchestrator selects the minimum useful composition.

## Hybrid model policy
Use local models for routine and private work when quality is sufficient. Escalate strategically to cloud/frontier capability when expected benefit outweighs latency, privacy, cost, resource, or power disadvantages.

Never permanently hard-code a model name as architecture. Maintain benchmark records for coding, reasoning, tool use, repository understanding, long-context retrieval, latency/throughput, VRAM/RAM, quantization, success rate, failure modes, and energy/resource behavior.

Cloud-assisted work may produce experience candidates, benchmark records, and reusable validated strategies. Do not attempt to copy unavailable hidden reasoning.

## Ambiguity protocol
1. Resolve from project context if possible.
2. Resolve from evidence if possible.
3. Make an explicit low-risk assumption if reasonable.
4. Otherwise ask the user a focused question and enter WAITING_FOR_USER.

Questions should explain why the ambiguity matters and offer options when practical.

## Security
The control plane owns authority. Models never directly gain unrestricted host authority.

Use:
- scoped capabilities;
- workspace restrictions;
- action validation;
- approval requirements for consequential operations;
- secret isolation;
- audit/event history;
- idempotency;
- isolated execution;
- explicit external/network permissions.

Coding agents may be limited to an assigned workspace, but a folder restriction alone is insufficient; enforcement must occur at execution/tool boundaries.

## Completion
A task is complete only when its contract is satisfied and required verification evidence exists. A model statement such as "done" is not completion evidence.

## Progress and loop prevention
Measure objective delta rather than imposing a simplistic timeout on every operation.

Positive signals include improved tests, reduced errors, completed plan steps, artifact advancement, new evidence, removed blockers, or a meaningful strategy change.

Loop signals include repeated action patterns, repeated error signatures, no objective delta, shrinking strategy diversity, and increasing resource cost.

Escalation should generally prefer:
inspect → change strategy → independent critic → targeted research → stronger model → focused user question.

## Memory
Use hierarchical memory. Preserve canonical artifacts and raw records externally. Build compact working context from task summaries, active decisions, constraints, open questions, evidence indexes, and scoped retrieval.

Never allow one lossy summary to become the only source of truth.

## Experience repository
OBSERVED → CANDIDATE → VALIDATED → PROMOTED → MONITORED → STALE / QUARANTINED.

Promotion requires evaluation evidence. Promoted experience remains monitored and may be withdrawn.

## Research
Question → query plan → retrieval → source evaluation → claim extraction → cross-checking → contradiction/uncertainty analysis → evidence storage → synthesis.

Separate sourced facts, supported inference, uncertainty, conflict, and recommendation. Agent agreement is not proof.

## Hardware and power
Monitor available CPU, RAM, GPU utilization/temperature, VRAM, disk pressure/activity, and accessible power data.

Operating modes:
NORMAL → EFFICIENT → CONSERVATION → PROTECTIVE → EMERGENCY.

React to trends, not only emergency thresholds. Rising thermal/resource pressure combined with poor progress should reduce concurrency or route differently before a hard emergency.

## UI
A proper futuristic desktop application: one natural main conversation, visible active task/progress, distinct agent presence, compact system health, and progressive disclosure for task graph, artifacts, evidence, memory, approvals, event timeline, routing, and hardware.

Do not expose hidden chain-of-thought. Show concise decision summaries, assumptions, actions, evidence, and verification results.
