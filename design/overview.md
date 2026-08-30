# Overview — principles

> The list below is the *original* ambition. What actually got built is narrower,
> and the game-engine / expert-mode parts were built and then removed. The current,
> honest statement of what the tool does is the root [README.md](../README.md) —
> that wins over this list wherever they disagree.

The goal was a hybrid local/cloud coding-and-research assistant, not a chatbot or a
terminal wrapper.

Original ambition (not all of it realised):
- serious software engineering;
- whole-repository understanding;
- controlled AI coding;
- ~~Windows, Android, Godot and Unreal work~~ — game-engine support was removed;
  Android/Gradle survives only as a `gradlew` JVM-unit-test verification target;
- autonomous internet research and source-based reasoning;
- document analysis and knowledge/RAG workflows;
- professional DOCX/PDF generation;
- presentation generation;
- local AI experimentation;
- ~~specialized expert modes~~ — removed with the engine-adapter layer;
- controlled execution, review, verification and recovery.

## Core architectural philosophy
1. LLMs propose and reason; deterministic components enforce.
2. Specialized agents exist only where specialization provides measurable value.
3. Independent agreement is useful but never proof.
4. Completion requires evidence and verification.
5. Progress is objective change, not repeated agent narration.
6. Long tasks are allowed; loops and non-progress are escalated.
7. Successful behavior becomes reusable only through controlled experience validation.
8. Canonical records remain recoverable; summaries are derived.
9. Local models are preferred when sufficient; cloud models are strategic escalation.
10. Hardware health, sustained load and power/resource use affect scheduling.
11. Workspace scope is necessary but insufficient: execution authority must be enforced separately.
12. The UI is a futuristic desktop application with natural collaboration and progressive disclosure.

## Active agent philosophy
Initial useful roles:
Interpreter/Intent Compiler, Planner, Researcher, Builder/Executor, Critic, Independent Verifier, Recovery/Reconciliation, Router/Resource Scheduler.

Do not run every role on every task. Select the minimum composition that adds value.

Creative work is allowed through diverse generation → critique → preserve promising options → constraint/evidence validation → selection or user question.

## Intent preservation
The original request remains immutable and traceable.
The interpretation layer may infer task type, goals, constraints, ambiguity, preferences, risks and deliverables and compile role-specific context, but may not silently change the objective.

## Security path
Agent
→ ActionProposal
→ schema validation
→ deterministic policy decision
→ capability check
→ argument/path sanitization
→ workspace/environment resolution
→ execution adapter
→ observation
→ verification

Never execute arbitrary model text directly as host commands.

## Progress/recovery path
Observe artifact/test/error/evidence/objective deltas, action similarity, strategy diversity, elapsed time, resource cost and hardware state.
Classify HEALTHY_PROGRESS, SLOW_PROGRESS, STALLED, LOOP_RISK or RESOURCE_LIMITED.
Recovery inspects persisted state and actual external state, reconciles uncertainty, and resumes only when safe.

## Memory and learning
Working / Project / Experience / System memory.
Retrieval is scoped and trust-filtered.
Experience lifecycle:
OBSERVED → CANDIDATE → VALIDATED → PROMOTED → MONITORED → STALE or QUARANTINED.

Cloud-assisted outputs may become candidates when task/result/evidence/privacy/evaluation/generalization requirements are met. Hidden reasoning is not assumed available.

## Hardware modes
NORMAL → EFFICIENT → CONSERVATION → PROTECTIVE → EMERGENCY.
Intervene based on trends and progress/resource interaction, not temperature alone.

## Implementation discipline
Modular monolith, explicit ownership, narrow contracts, event history, checkpoints, idempotency and measurable tests.
Do not extract microservices without measured need.
