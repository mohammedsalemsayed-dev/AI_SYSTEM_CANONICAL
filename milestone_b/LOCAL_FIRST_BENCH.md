# Premise run — local-first with cloud escalation

Full pipeline per task: Interpreter + Planner + Builder = `local:qwen3:8b`; Verifier = T0 in Docker; fallback = `agent_sdk` (one retry on T0 fail).

- **solved on-device (local only): 8/10**
- solved after escalation to cloud: 2/10
- failed (neither): 0/10
- end-to-end success (local + escalated): **10/10**

| task | outcome | final state | verifications | wall_s |
|---|---|---|---|---|
| 01-pagination-off-by-one | local | COMPLETED | ['pass'] | 12.0 |
| 02-boundary-operator | local | COMPLETED | ['pass'] | 11.3 |
| 03-missing-empty-guard | local | COMPLETED | ['pass'] | 12.3 |
| 04-int-vs-float-division | local | COMPLETED | ['pass'] | 11.3 |
| 05-mutable-default-arg | local | COMPLETED | ['pass'] | 15.3 |
| 06-wrong-dict-key | local | COMPLETED | ['pass'] | 11.5 |
| 07-inverted-boolean | local | COMPLETED | ['pass'] | 11.4 |
| 08-missing-normalization | escalated | COMPLETED | ['pass'] | 54.1 |
| 09-accumulator-init | local | COMPLETED | ['pass'] | 11.4 |
| 10-returns-first-not-all | escalated | COMPLETED | ['pass'] | 32.6 |
