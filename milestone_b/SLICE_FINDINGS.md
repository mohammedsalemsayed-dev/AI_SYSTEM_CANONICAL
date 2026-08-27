# Slice Findings — Milestone B premise test

Ran 10 seeded tasks through the real loop:
**AgentSDKLLM** (Interpreter + Planner, Claude Pro subscription via the Agent SDK) →
**AgentSDKBuilder** (Builder) → **VerifierT0** running pytest in the **Docker Tier-A sandbox**.
No API key, no per-token spend.

| id | final state | T0 verify | wall-clock s | unaided T0 criterion | diff_correct |
|---|---|---|---|---|---|
| 01-pagination-off-by-one | COMPLETED | pass | 21.8 | yes | **yes** — removed the `+ 1` |
| 02-boundary-operator | COMPLETED | pass | 19.2 | yes | **yes** — `>` → `>=` |
| 03-missing-empty-guard | COMPLETED | pass | 24.9 | yes | **yes** — `if not xs: return 0.0` |
| 04-int-vs-float-division | COMPLETED | pass | 24.9 | yes | **yes** — `//` → `/` |
| 05-mutable-default-arg | COMPLETED | pass | 21.6 | yes | **yes** — `tags=None` + guard (idiomatic) |
| 06-wrong-dict-key | COMPLETED | pass | 20.6 | yes | **yes** — `'town'` → `'city'` |
| 07-inverted-boolean | COMPLETED | pass | 22.6 | yes | **yes** — dropped the `not` |
| 08-missing-normalization | COMPLETED | pass | 21.6 | yes | **yes** — exact-match fast path + `strip().lower()` scan (a bit verbose, correct) |
| 09-accumulator-init | COMPLETED | pass | 18.9 | yes | **yes** — `total = 0` → `1` |
| 10-returns-first-not-all | COMPLETED | pass | 40.2 | yes | **yes** — accumulate into a list |

- final state COMPLETED: **10 / 10**
- T0 verify == pass: **10 / 10**
- interpreter produced a usable T0 criterion unaided: **10 / 10**
- **diff_correct: 10 / 10** (scored by inspection; all minimal or near-minimal, idiomatic)
- median wall-clock: ~22 s / task
- token cost: not reported on subscription auth (`usage` is null); `0` in the raw table

## Verdict (MILESTONE_B_PLAN.md §7)

**diff_correct = 100% with a clean T0 gate → the premise holds.** The loop —
request → contract → plan → edit → sandboxed verify → result — works end to end with a
real model and the real control plane. Proceed to Milestone D; Milestone C (security /
authority) is already built and validated.

## Caveats — what this run does *not* prove

- **Bugs are small and single-function.** Each is a 1–5 line fix in one file with an
  existing failing test. It says nothing about multi-file changes, refactors, or bugs
  needing repo-wide understanding.
- **Every request named its failing test.** Realistic for a bug report, but the Interpreter
  was not tested on vaguer asks (those correctly went to WAITING_FOR_USER in an earlier run
  until the request named the test).
- **Seeded, not real.** These repos were generated for this test. A second pass on 3–5 of
  your own repos with real bugs is the honest confirmation before leaning on the result.
- **Subscription rate limits** were not hit at 10 tasks × ~22 s, but a heavier run
  (multi-file, longer Builder loops) could throttle.

## Reproduce

```bash
cd milestone_b
python -m tests.premise.make_seeded_repos          # regenerate premise_repos/ + tasks.seeded.json
python -m tests.premise.run_real_tasks tests/premise/tasks.seeded.json
```
Needs a logged-in `claude` CLI (`claude -p "PONG"` must work). `SLICE_LLM=anthropic` +
`ANTHROPIC_API_KEY` in `milestone_b/.env.local` switches to the billed API path.
