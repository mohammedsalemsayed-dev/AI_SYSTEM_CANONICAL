# End-to-End Architecture

> **Cross-reference**
> - Role: Request lifecycle, canonical state machine, authority separation, recovery path.
> - Authority: Authoritative.
> - Upstream (consumes): [00_MASTER_SPEC.md](../00_MASTER_SPEC.md).
> - Downstream (depended on by): [CORE_CONTRACTS.md](../contracts/CORE_CONTRACTS.md), orchestrator implementation.
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../../../../DESIGN_TIGHTENING.md) — §1 expands the lifecycle into a per-stage object flow with transition gates, §2 component interfaces, §4 the three control loops.

## Request lifecycle
User request
→ immutable original request
→ Interpreter / Intent Compiler
→ Task Contract
→ ambiguity decision
→ Router selects resources and agent composition
→ Planner
→ policy/capability preflight
→ execution/research/build actions
→ evidence and artifact collection
→ independent verification
→ completed / failed / stalled / waiting for user
→ experience candidate + benchmark/event records where applicable.

## Canonical state machine
CREATED
→ INTERPRETING
→ PLANNING or WAITING_FOR_USER
→ EXECUTING
→ VERIFYING
→ COMPLETED

Alternative paths:
EXECUTING/VERIFYING → STALLED → RECOVERING → EXECUTING/VERIFYING/WAITING_FOR_USER/FAILED
Any active state → CANCELLED where policy permits.

## Authority separation
LLM: proposes plan, messages, tool requests, hypotheses.
Control plane: validates schema, policy, capability, budget, workspace, idempotency, scheduling.
Execution adapter: performs only authorized operations.
Verifier: evaluates artifact/evidence independently where required.
Persistence: records canonical state/events/checkpoints.

## Agent communication
Messages are structured:
sender, role, task_id, intent, claims, evidence_refs, assumptions, requested_action, confidence_summary.

Agents may communicate naturally in the UI, but internal authority does not derive from conversational confidence.

Disagreement handling:
1. identify concrete conflicting claims;
2. retrieve evidence or run a discriminating test;
3. obtain independent review if useful;
4. synthesize with uncertainty if unresolved;
5. ask user if the unresolved choice is materially consequential.

## Execution boundary
Task → ActionProposal → schema validation → policy → capability → approval if needed → scheduler/admission → idempotency check → isolated execution → artifact/event → verification.

## Recovery
Persist checkpoints around meaningful boundaries. After restart:
inspect canonical state → inspect filesystem/tool reality → reconcile → detect uncertain external effects → use idempotency/completion checks → resume/repair/escalate.
