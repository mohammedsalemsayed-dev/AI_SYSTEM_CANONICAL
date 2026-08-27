# Core Contracts

> **Cross-reference**
> - Role: Canonical record schemas (TaskContract, ActionProposal, EvidenceRecord, ProgressEvent, ExperienceRecord, ModelRunRecord).
> - Authority: Authoritative.
> - Upstream (consumes): [00_MASTER_SPEC.md](../00_MASTER_SPEC.md), [END_TO_END_ARCHITECTURE.md](../architecture/END_TO_END_ARCHITECTURE.md).
> - Downstream (depended on by): `apps/backend/app/schemas/contracts.py`, every service.
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../../../../DESIGN_TIGHTENING.md) — §3 relational model and added records (`OriginalRequest`, `RunPlan`, `Plan`/`PlanStep`, `PolicyDecision`, `CapabilityGrant`, `Observation`, `VerificationRecord`, `Checkpoint`, `ClarificationRequest`).

## TaskContract
Required fields:
task_id, original_request, objective, deliverables, constraints, workspace_id, risk_level, ambiguity, assumptions, success_criteria, required_evidence, task_class, resource_sensitivity.

## ActionProposal
action_id, task_id, operation, arguments, required_capability, workspace_scope, expected_effect, idempotency_key, estimated_resource_cost, rollback_or_recovery_hint.

## EvidenceRecord
evidence_id, task_id, kind, source, timestamp, trust_level, validation_state, scope, version, artifact_ref, claim_refs.

## ProgressEvent
sequence, timestamp, objective_delta, evidence_refs, strategy_id, artifact_delta, test_delta, resource_snapshot.

Progress cannot be advanced merely because an agent emitted another message.

## ExperienceRecord
situation, strategy, actions, outcome, evidence, cost, resource_usage, success_score, validation_state, scope, version, promotion_history, monitoring_metrics.

## ModelRunRecord
provider, model, task_class, route_reason, latency, success, verification_result, resource_use, estimated_cost, failure_mode.
