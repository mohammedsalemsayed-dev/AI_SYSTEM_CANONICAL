# Milestone D notes — what is real, what remains

Status against [../MILESTONE_D_PLAN.md](../MILESTONE_D_PLAN.md). **180 tests green**
(128 unit, 24 integration, 28 security).

## Real after Milestone D

| Area | Module | Notes |
|---|---|---|
| Meaningful-progress scoring | `app/services/progress/signals.py`, `service.py` | six hard signals (tests_passed_up, new_passing_test, errors_down, coverage_up, acceptance_flip, new_target_file_touched); baseline unscored; novel-motion guard (K → SLOW_PROGRESS, 2K → STALLED; no motion stalls faster) |
| Loop detection | `app/services/progress/loop.py` | `action_hash` (arg-order independent, numbers/paths normalized), `normalize_error` (exception + deepest frame), `diff_similarity`. Flags: repeated_action, repeated_error, diff_thrash. A hard-progress step clears the history (false-positive guard) |
| Per-task_class patience | `app/services/progress/patience.py` | debug 6, code_edit_broad 5, code_edit_local 3, … user-extendable |
| Step measurement | `app/services/progress/measure.py` | parse pytest summary counts → `StepMeasurement` |
| Escalation ladder | `app/services/escalation/ladder.py` | inspect → change_strategy → critic → research → stronger_model → ask_user. `inspect` + stubs log-and-advance; `change_strategy` re-plans (bounded, max 2); `ask_user` → `WAITING_FOR_USER` |
| Multi-step execution | `orchestrator._execute` | per-step T0 measurement (multi-step plans only — perf), `ProgressService` + `LoopDetector` per step, `PROGRESS` event with `effective_class`; `STALLED`/`LOOP_RISK` → ladder; re-plan restarts with fresh progress/loop state |
| Budget | `app/services/budget/tracker.py` + `TaskContract.budget` | `wall_clock_s` / `steps` / `model_cost_usd` (cost unmetered on subscription). 80% → `BUDGET` soft event; 100% → `WAITING_FOR_USER` with a spend summary; `would_exceed()` admission before each step |
| Checkpoints | `app/services/recovery/checkpoint.py` | folded from the log at each EXECUTING/VERIFYING/STALLED/RECOVERING transition: state, changed-path manifest, step count, completed idempotency keys, uncertain external actions |
| Idempotency | `app/services/recovery/idempotency.py` | keys of proposals with a successful observation; feeds reconcile |
| Restart reconciliation | `app/services/recovery/reconcile.py` + `orchestrator._reconcile_and_resume` | RESUME (contract + plan present → steer to EXECUTING, re-run; workspace untouched), REPAIR (no contract/plan → `WAITING_FOR_USER`), ESCALATE (uncertain external action → `WAITING_FOR_USER`), NOOP (terminal / already waiting). Replaces the old "interrupted → FAIL". |
| State machine | `app/core/state.py` | added `EXECUTING ⇄ WAITING_FOR_USER` (Milestone C) and `VERIFYING → WAITING_FOR_USER` (D); `open_clarification` gate so a stall/reconcile pause is a valid WFU transition |
| Event kinds | `PROGRESS`, `CHECKPOINT`, `RECONCILE`, `BUDGET`, `ESCALATION` | all flow through the append-only log |

## Stubbed — filled by later milestones

- **Ladder rungs `critic` / `research` / `stronger_model`** log an `ESCALATION` and advance.
  Until Milestone E (critic, research) and G (stronger model), a hard stall that survives one
  re-plan ends at `ask_user` → `WAITING_FOR_USER`. That is the correct safe behaviour; it just
  means D cannot demonstrate fully-autonomous recovery from a hard stall.
- **Coverage / lint / type-error signals** are defined in `StepMeasurement` but nothing
  populates `coverage_pct` / `error_count` yet — only pytest pass/fail counts are wired.
- **`REPAIR`** (interrupted before a contract) escalates to the user rather than
  auto-re-interpreting — the state machine has no `INTERPRETING → INTERPRETING` and a safe
  auto-repair needs more than the slice has.
- **Budget `model_cost_usd`** is unmetered on the Agent SDK / subscription path; only
  `wall_clock_s` and `steps` bind there.
- **Per-step measurement** is skipped for single-step plans (a single step can't stall and
  the final verify covers it) — a deliberate perf trade, not a capability gap.

## Deferred past D (unchanged from the plan)

Real multi-agent runtime (E); model router / local tier (G); Tier-B/C sandboxes; full
telemetry / resource sampling; PostgreSQL/Redis; desktop shell.
