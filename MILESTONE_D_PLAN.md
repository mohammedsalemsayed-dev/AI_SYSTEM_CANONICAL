# Milestone D — Recovery and Progress Plan

> **Cross-reference**
> - Role: Build plan for progress/loop detection, checkpoints, idempotency, budget, and restart reconciliation — the machinery that makes long autonomous runs safe.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [IMPLEMENTATION_PLAN.md](03_IMPLEMENTATION_FOUNDATION/prior_foundation/docs/implementation/IMPLEMENTATION_PLAN.md) milestone D; [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §1 (progress gate), §4 (escalation ladder), §11.1 (budget), §14.4 (deterministic progress/loop classifier); [ACCEPTANCE.md](03_IMPLEMENTATION_FOUNDATION/prior_foundation/docs/testing/ACCEPTANCE.md) Recovery + Failure gates.
> - Downstream (depended on by): Milestone E (multi-agent needs a stall signal to trigger a critic); any task that runs more than a few steps.
> - Predecessors: [MILESTONE_B_PLAN.md](MILESTONE_B_PLAN.md) (the loop), [MILESTONE_C_PLAN.md](MILESTONE_C_PLAN.md) (security). Continues the `milestone_b/` tree.

---

## 1. Purpose

The slice runs single-step plans and, on any hiccup, fails the task. That is safe but useless
for real work, where a task takes many steps and the model sometimes thrashes. Milestone D
adds the deterministic machinery to (a) tell real progress from motion, (b) catch loops
early, (c) survive an interruption and reconcile with reality on restart, and (d) stop
before a runaway spend.

Guiding rule ([DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §14.4): **progress is credited
only from hard signals; loop detection is structural; neither asks a model.**

## 2. In scope

| Concern | Milestone D implementation |
|---|---|
| Meaningful-progress scoring | `ProgressService.observe(step_result) -> ProgressEvent`. Credit progress **only** from: test pass-count up, a new passing test, build/lint/type-error count down, coverage up, a plan step's own acceptance check flipping green, first touch of a not-yet-touched target file. `objective_delta` / `strategy_change` are context, not score. |
| Loop detection | Hash each action `(operation, normalized target, normalized args)`. Flags: same hash ≥ 3 of last 5; same normalized error signature (first error line + top frame) ≥ 3; successive-diff edit-distance below threshold N times (line thrash); budget fraction exceeded with non-increasing pass-count. |
| Novel-motion guard | Artifact delta with no test/behaviour delta for K steps → `SLOW_PROGRESS`; another K → `STALLED`. |
| Classification | `HEALTHY_PROGRESS` / `SLOW_PROGRESS` / `STALLED` / `LOOP_RISK` / `RESOURCE_LIMITED`, all from the signals above. Emitted as a `ProgressEvent` after every step. |
| Escalation ladder | On `STALLED` / `LOOP_RISK`: drive the fixed ladder mechanically — inspect → change strategy (force a fresh `Plan`, planner told what was tried) → critic pass → targeted research → stronger model → user question. Milestone D wires the ladder and implements *inspect* + *change strategy* + *user question*; critic/research/stronger-model are stubs that advance to the next rung (real ones are E and G). |
| Checkpoints | `Checkpoint{canonical_state, artifact_manifest[], uncertain_external_actions[], step_index}` appended at each state transition and artifact boundary. The event log already orders everything; the checkpoint is the explicit resumable marker. |
| Idempotency | `ActionProposal.idempotency_key` already exists. A key with a recorded successful `Observation` is not re-executed on resume — the prior observation is reused. |
| Restart reconciliation | `Recovery.reconcile(checkpoint, world) -> {decision: RESUME|REPAIR|ESCALATE, ...}`. Inspects canonical state + the real filesystem (do the artifacts exist? do their hashes match?), detects uncertain external effects, and resumes / repairs / escalates. Wired into `Orchestrator.resume()` (which currently only fails interrupted tasks). |
| Budget | `TaskContract.budget = {wall_clock_s, model_cost_usd, local_gpu_s}` (Interpreter fills defaults per `task_class`, user overrides). Orchestrator tracks spend; at 80% of any dimension → forced escalation-ladder decision point; at 100% → `WAITING_FOR_USER` with a spend summary. Scheduler admission rejects a step whose estimated cost exceeds the remainder. |
| Patience budget | Per-`task_class` "no measurable progress for T" tolerance, user-extendable, before `STALLED` auto-escalates — so legitimately slow debugging is not killed. |
| Multi-step tasks | The slice's `_execute` gains a real multi-step loop: per step run progress + loop checks, and on `STALLED`/`LOOP_RISK` hand off to the ladder instead of failing. |

## 3. Out of scope (deferred; stubs advance the ladder)

| Deferred | Filled in |
|---|---|
| Real critic pass in the ladder | Milestone E / §9 |
| Real targeted research in the ladder | Milestone E |
| Real stronger-model routing in the ladder | Milestone G / §7 |
| Full telemetry / resource sampling on the target machine | Milestone G |
| Tier-B/C sandboxes | §14.6 |
| PostgreSQL/Redis, desktop shell | Milestone A hardening / H |

## 4. Component layout

Continues the `milestone_b/` tree:

```
app/services/
  progress/
    signals.py      hard-signal extraction from a step result
    service.py      ProgressService -> ProgressEvent + classification
    loop.py         action hashing, error-signature, edit-distance, loop flags
  recovery/
    checkpoint.py   Checkpoint record + write points
    reconcile.py    reconcile(checkpoint, world) -> RESUME | REPAIR | ESCALATE
    idempotency.py  key -> prior Observation lookup
  budget/
    tracker.py      spend accounting; 80% / 100% gates; admission check
  escalation/
    ladder.py       the fixed ladder; inspect / change-strategy / ask-user real, rest stub
app/schemas/contracts.py   + TaskContract.budget, ProgressEvent, Checkpoint, ReconcileDecision
app/events/log.py          + PROGRESS, CHECKPOINT, RECONCILE, BUDGET, ESCALATION event kinds
app/orchestration/orchestrator.py   multi-step _execute; progress/loop checks; ladder hand-off; reconcile in resume()
tests/
  unit/         test_progress_signals, test_loop_detection, test_checkpoint, test_idempotency, test_budget, test_reconcile
  integration/  test_multistep_task, test_loop_caught, test_budget_exhaustion, test_ladder_handoff
  recovery/     test_kill_and_resume, test_partial_artifact, test_uncertain_external_action
```

## 5. Work breakdown (~13 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `progress/signals.py` + `service.py`: hard-signal extraction, `ProgressEvent`, classification (`HEALTHY_PROGRESS`…`RESOURCE_LIMITED`). Unit tests per signal and per class. |
| 3–4 | `progress/loop.py`: action hashing, normalized error signature, successive-diff edit-distance, the four loop flags. Unit tests incl. false-positive guards (real progress with repeated ops must NOT flag). |
| 5 | Novel-motion guard + per-`task_class` patience budget. Unit tests. |
| 6–7 | Multi-step `_execute`: per-step progress + loop check; emit `PROGRESS`; on `STALLED`/`LOOP_RISK` call the ladder. `escalation/ladder.py` with inspect / change-strategy (re-plan) / ask-user real; critic/research/stronger-model stubs. Integration: a task needing 2 file edits completes; a deliberately looping `ScriptedBuilder` is caught and `STALLED`. |
| 8 | `budget/tracker.py`: `TaskContract.budget`, spend accounting, 80% decision point, 100% → `WAITING_FOR_USER`, admission check. Integration: budget exhaustion pauses the task with a spend summary. |
| 9–10 | `recovery/checkpoint.py` (record + write points) + `recovery/idempotency.py` (key → prior Observation). Unit: checkpoint replay; a re-run step with a completed key is a no-op. |
| 11–12 | `recovery/reconcile.py`: inspect canonical state + real filesystem (artifact existence + hash), classify uncertain external effects, decide RESUME/REPAIR/ESCALATE. Rewrite `Orchestrator.resume()` to run reconciliation and continue/repair instead of always failing. Recovery tests: kill mid-step → resume completes; missing artifact → REPAIR; recorded-but-unconfirmed external action → ESCALATE (`REVIEW`). |
| 13 | Regression pass; wire it all; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md) + the connective index; write `milestone_b/MILESTONE_D_NOTES.md`. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → **FAILURE** → SECURITY → **RECOVERY** → RESOURCE.

- **Unit** — each progress signal in isolation; each loop flag fires on its pattern and does
  **not** fire on genuine progress that happens to repeat an operation; classification given a
  synthetic step history; checkpoint round-trips through the event log; an idempotency key with
  a recorded `Observation` short-circuits; budget math (80%/100%/admission); each reconcile
  decision (RESUME with matching hashes, REPAIR with a missing artifact, ESCALATE with an
  uncertain external action).
- **Integration** — a 2-file-edit task completes with `HEALTHY_PROGRESS` throughout; a
  `ScriptedBuilder` that re-emits the same no-op diff is classified `LOOP_RISK` within the
  flag threshold and handed to the ladder (which, with stubs, reaches "ask user" →
  `WAITING_FOR_USER`); budget exhaustion → `WAITING_FOR_USER` with a spend summary, never a
  silent overrun.
- **Failure** — a step that fails with the same normalized error 3× → `LOOP_RISK` → ladder;
  the ladder's "change strategy" rung forces a new `Plan` and the planner is told what was
  tried.
- **Recovery** — process killed after `CAPABILITY_GRANT` but before the `Observation`:
  `resume()` reconciles (no artifact yet → RESUME from that step), re-issues nothing, and the
  task completes; killed after a partial artifact write → REPAIR (redo the step, idempotency
  makes it safe); a checkpoint listing an `uncertain_external_action` → ESCALATE →
  `WAITING_FOR_USER`. The user's original workspace is never mutated in any case.

## 7. Tunable starting values (recalibrate from data — DESIGN_TIGHTENING §14.4)

- loop: same action hash **≥ 3 of last 5**; same error signature **≥ 3**; edit-distance
  thrash **≥ 3** times; novel-motion K = **3** steps to `SLOW_PROGRESS`, **+3** to `STALLED`.
- budget defaults per `task_class`: `code_edit_local` 300 s / $0.50; `code_edit_broad`
  1200 s / $2.00; `debug` 900 s / $1.50 (subscription runs: wall-clock only, cost unmetered).
- patience: `debug` 20 min without a hard signal before auto-escalate; others 10 min.

## 8. Risks

- **Loop false positives** — a legitimate retry-with-a-real-fix repeats an operation. Mitigated
  by keying loop flags on *no hard-signal progress* alongside the structural repeat, and by the
  false-positive unit tests.
- **Reconciliation on Windows** — artifact hashing + partial-write detection must handle
  CRLF and locked files (already bit us in B and C). Use byte hashing, tolerate `PermissionError`.
- **Ladder with stubs** — until Milestone E, `STALLED` mostly ends at "ask user". That is the
  correct safe behaviour, but it means D can't fully demonstrate autonomous recovery from a
  hard stall — note it, don't paper over it.
- **Budget on subscription** — `model_cost_usd` is unmetered on the Agent SDK path; only
  `wall_clock_s` is enforceable there. Keep the cost dimension for the API path.

## 9. Deliverables

- `ProgressService`, loop detector, `escalation/ladder.py`, `budget/tracker.py`,
  `recovery/{checkpoint,idempotency,reconcile}.py`, multi-step `_execute`, reconciling
  `resume()` — wired into the orchestrator.
- Test suite: existing 133 green, plus unit (progress/loop/checkpoint/idempotency/budget/
  reconcile), integration (multi-step/loop/budget/ladder), and the **Recovery gate**
  (kill-and-resume, partial artifact, uncertain external action).
- `milestone_b/MILESTONE_D_NOTES.md` — what is real after D, what remains stubbed.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md) and the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md) updated:
  "Meaningful progress / loop detection", "Recovery / idempotency / reconciliation",
  "Budget / cost-latency control" move toward FOUNDATION / IMPLEMENTED.
