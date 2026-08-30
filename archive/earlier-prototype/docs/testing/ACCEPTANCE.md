# Acceptance and Release Gates

> **Cross-reference**
> - Role: Required test categories and the gate order to ACCEPT.
> - Authority: Authoritative acceptance strategy.
> - Upstream (consumes): [00_MASTER_SPEC.md](../00_MASTER_SPEC.md).
> - Downstream (depended on by): the acceptance-category column of [REQUIREMENT_TRACEABILITY.md](../../../../02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md).
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../../../../DESIGN_TIGHTENING.md) — §5 verification ladder T0–T3 defines what "verified" means per category; §12 injection corpus extends the Security gate.

Required categories:
- Unit: state transitions, schemas, policy, capabilities, progress, retrieval.
- Integration: request-to-result, DB, providers, workspace, execution, artifacts/events.
- Security: path traversal, unauthorized workspace access, prompt-injected authority, malicious arguments, secrets, expiry, approval bypass.
- Recovery: crashes before/during/after action, partial artifacts, uncertain effects, restart reconciliation.
- Failure: unavailable model/tool/database/cloud, local OOM/resource pressure, repeated repair failure, verifier disagreement.
- Resource: CPU/RAM/VRAM/thermal/power behavior on target hardware.
- Benchmark: success, quality, latency, resource usage, failure modes.

Gate:
UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → RESOURCE/HARDWARE → BENCHMARK → ACCEPT.

A discovered incident becomes a regression test.
