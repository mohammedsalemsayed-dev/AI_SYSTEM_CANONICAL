# Premise run — local-first with cloud escalation (FULL stack)

Full pipeline per task: Interpreter + Planner + Builder = `local:qwen3:8b`; Verifier = T0 in Docker; fallback = `agent_sdk` (one retry on T0 fail); plus Router + Critic + T2 verifier + memory/experience.

- **solved on-device (local only): 1/5**
- solved after escalation to cloud: 3/5
- failed (neither): 1/5
- end-to-end success (local + escalated): **4/5**

| task | outcome | final state | verifications | wall_s |
|---|---|---|---|---|
| mit-01-chunked-negative | escalated | COMPLETED | ['pass', 'pass'] | 118.3 |
| mit-02-interleave-evenly-empty | escalated | COMPLETED | ['pass', 'pass'] | 119.7 |
| mit-03-numeric-range-reversed-empty | escalated | COMPLETED | ['pass', 'pass'] | 258.3 |
| mit-04-product-index-iterator | failed | WAITING_FOR_USER | ['pass', 'fail'] | 175.5 |
| mit-05-running-min-max-stability | local | COMPLETED | ['pass', 'pass'] | 350.2 |

`verifications` = [T0 (deterministic, authoritative), T2 (local-model ensemble, advisory)]. A `['pass','fail']` row = T0 passed and the local T2 verifier raised a concern that was logged as a DISAGREEMENT but did not block — T2 on an 8B model is noisy and is advisory by design.

## Read

Real library bugs (more-itertools, `more.py` ~4k lines) are a completely
different test from the one-line seeded bugs:

| | seeded (toy) | real (more-itertools) |
|---|---|---|
| local only | 8–10 / 10 | **1 / 5** |
| + cloud escalation | 10 / 10 | **4 / 5** |
| failed | 0 | 1 / 5 |
| time/task | ~12–26 s | **2–6 min** |

- **`qwen3:8b` on 8 GB is a triage layer, not a solo coder** for real work — it
  lands a big-file fix on its own ~1 in 5. The local-first→escalate architecture
  is what makes the system usable: 3/5 were rescued by the cloud retry.
- **`mit-04` is a genuine failure** — local AND cloud produced a diff T0 accepted
  but the (now cloud) T2 verifier rejected; the disagreement escalated to
  `WAITING_FOR_USER` instead of shipping. That is the design working: an
  independent cloud judge that dissents stops the task for a human.
- T2-on-cloud now materially affects outcomes (it can pause a task). Its
  false-positive rate needs tuning before it gates anything hard.
