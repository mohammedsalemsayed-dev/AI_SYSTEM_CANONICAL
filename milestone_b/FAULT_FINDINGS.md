# Fault-injection findings

14/14 (kind × point) pairs satisfy all three invariants (safe terminal / workspace untouched / clean reconcile).

| injection point | fault | result | detail |
|---|---|---|---|
| llm | `llm_refusal` | PASS | FAILED |
| llm | `llm_timeout` | PASS | FAILED |
| llm | `llm_garbage` | PASS | FAILED |
| sandbox | `sandbox_unavailable` | PASS | FAILED |
| sandbox | `sandbox_timeout` | PASS | FAILED |
| sandbox | `sandbox_error` | PASS | FAILED |
| sandbox | `sandbox_crash` | PASS | FAILED |
| builder | `partial_diff` | PASS | FAILED |
| builder | `empty_diff` | PASS | FAILED |
| builder | `builder_exception` | PASS | FAILED |
| interrupt | `PLAN` | PASS | COMPLETED |
| interrupt | `CHECKPOINT` | PASS | COMPLETED |
| interrupt | `ARTIFACT` | PASS | COMPLETED |
| interrupt | `VERIFICATION` | PASS | FAILED |
