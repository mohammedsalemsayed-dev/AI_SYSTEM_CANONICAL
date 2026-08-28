# Premise run — local-first with cloud escalation (FULL stack)

Full pipeline per task: Interpreter + Planner + Builder = `local:qwen3:8b`; Verifier = T0 in Docker; fallback = `agent_sdk` (one retry on T0 fail); plus Router + Critic + T2 verifier + memory/experience.

- **solved on-device (local only): 10/10**
- solved after escalation to cloud: 0/10
- failed (neither): 0/10
- end-to-end success (local + escalated): **10/10**

| task | outcome | final state | verifications | wall_s |
|---|---|---|---|---|
| 01-pagination-off-by-one | local | COMPLETED | ['pass', 'pass'] | 27.8 |
| 02-boundary-operator | local | COMPLETED | ['pass', 'fail'] | 22.7 |
| 03-missing-empty-guard | local | COMPLETED | ['pass', 'fail'] | 23.6 |
| 04-int-vs-float-division | local | COMPLETED | ['pass', 'pass'] | 28.6 |
| 05-mutable-default-arg | local | COMPLETED | ['pass', 'pass'] | 28.4 |
| 06-wrong-dict-key | local | COMPLETED | ['pass', 'fail'] | 24.4 |
| 07-inverted-boolean | local | COMPLETED | ['pass', 'fail'] | 28.1 |
| 08-missing-normalization | local | COMPLETED | ['pass', 'pass'] | 25.1 |
| 09-accumulator-init | local | COMPLETED | ['pass', 'fail'] | 23.6 |
| 10-returns-first-not-all | local | COMPLETED | ['pass', 'pass'] | 28.1 |
