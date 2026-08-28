# Milestone I notes — what is real, what remains

Status against [../MILESTONE_I_PLAN.md](../MILESTONE_I_PLAN.md). **290 tests green.**
All 14 days built.

## Real after Milestone I

| Area | Module | Notes |
|---|---|---|
| Frozen guardrail suite | `app/services/eval/guardrail.py` + `fixtures/guardrail_suite.json` | 12 canonical tasks (off-by-one, empty-input, null-guard, pagination, cache-key, parser, float-round, mutable-default, iterator-exhaustion, regex-anchor, timezone, division-guard) — each a self-contained module + a T0 test with a known oracle (`bug` / `fix`). `GuardrailSuite.run(run_one)` takes an injected callable (a real orchestrator run, or a fake), runs in fixture order, and a crashing task counts as failed. `materialize()` writes the broken module + test into a dir. Target size ~30; adding tasks is a fixture edit. |
| Regression gate | `app/services/eval/regression.py` | `check_regression(candidate, baseline) -> RegressionResult`: passes iff aggregate pass-rate drop ≤ `MAX_GUARDRAIL_DROP_PP` (2.0, shared with §8) **and** no previously-passing guardrail task now fails. Reports `drop_pp`, `newly_failing`, `recovered`. `RegressionBaseline` stores/reads the baseline `SuiteResult` on the **system** memory tier; `certify()` **fails closed** with no baseline; `is_stale()` at 30 days. |
| Offline eval | `app/services/eval/offline_eval.py` | `OfflineEval(run_with, run_without, certify_guardrail=, run_guardrail=)`. `evaluate(subject, heldout_ids)` replays the held-out set with vs. without the change, then runs the guardrail gate. `decision == "promote"` only when `heldout_n ≥ 10` **and** `delta ≥ 0` **and** the guardrail holds. Security/policy/execution-scope subjects still need `human_approved`. All run callables injected → deterministic and unit-tested; production wires them to real runs. |
| `try_promote` rewire | `app/services/experience/store.py` | `ExperienceStore.try_promote(exp_id, *, human_approved=, report=None)`. With a real `EvalReport` the decision **is** that report (folds `heldout_n` + guardrail drop into the record). Without one, the `experience/eval.py` stub still runs, so the state machine is always exercised offline. |
| Canary controller | `app/services/eval/canary.py` | `CanaryController(baseline_success, *, fraction=0.20, min_samples=10, max_drop_pp=15, seed=)`. `sample(key)` — deterministic fractional cohort membership (sha256 of `seed:key`), stable per key. `record(verified) -> "HOLD" | "PROMOTE" | "ROLLBACK"`; terminal once decided. `ROLLBACK` when `min_samples` reached and observed success is `max_drop_pp` below baseline. |
| Experience canary | `orchestrator._settle_experience_canaries` | Opt-in (`canary_enabled`). On every terminal outcome, for each experience proposed to the task that is `PROMOTED` / `MONITORED`: get-or-create a per-experience `CanaryController` (persisted on the orchestrator instance), `sample(task_id)`, `record(verified)`, log a `CANARY` event. A `ROLLBACK` verdict quarantines the experience (reuses the F catastrophic path) and logs an `EXPERIENCE_TRANSITION` with `trigger="canary_rollback"`. |
| Routing canary | `orchestrator._settle_route_canary` + `RouteStatsStore.freeze` / `is_frozen` | When a task was routed by the **data-driven** path, its outcome feeds a per-`(task_class, model)` `CanaryController`. `ROLLBACK` writes a `route_freeze` record to system memory and a `REGRESSION` event; `Router._data_driven_pick` then skips that model, so the class falls back to the incumbent / static default. |
| Derived metrics | `app/services/eval/metrics.py` | `rebuild_metrics(log, task_ids) -> Metrics` — a pure fold over the event log producing the §11.2 set: success rate by `task_class`, rework rate (≥ 1 escalation or > 1 plan), verify-tier distribution, escalation frequency, budget-exhaustion rate, quarantine events. No store; if it and the log disagree, the log wins. |
| Standalone runner | `tests/regression/run_guardrail.py` | Runs the suite through a real `Orchestrator` (`--offline` = scripted providers + `SubprocessSandbox`, no model calls), records or certifies against the stored baseline, exits non-zero on a regression. Offline path verified here (12/12, fails-closed with no baseline). The real-model run is **not** run in the suite. |
| Events | `EVAL`, `CANARY`, `REGRESSION` | on `app/events/log.py`. |

## Not yet real / deferred

- **The real held-out numbers need the subscription** — `OfflineEval`'s decision logic and
  wiring are proven deterministically; actual held-out success rates require real model runs
  (`run_guardrail.py` without `--offline`). Same shape as the Milestone E benchmark and the
  Milestone G seeder: an un-run harness, not a cut.
- **Guardrail suite is 12, not ~30** — a 2 pp aggregate gate is coarse at n=12 (one task
  ≈ 8 pp). The *newly-failing-task* half of the gate is the sharper signal and is exact.
  Growing the suite is a fixture edit.
- **Offline eval is not wired into the orchestrator's own promotion path** — nothing in the
  orchestrator calls `try_promote` yet; experiences advance through the lifecycle via the
  store API / the F canary path. `OfflineEval` + `try_promote(report=)` is the mechanism a
  promotion job (or a future scheduled task) uses.
- **Logistic-regression weight fit (§7.2)** — still deferred; needs a real run corpus. I
  ships the regression gate such a change would pass through, not the fit.
- **Continuous / scheduled guardrail runs** — need the desktop shell (H) + a scheduler; I
  ships the runnable check.
- **Canary statistical significance** — a fixed 15 pp drop threshold over `min_samples`,
  documented as a starting value; no significance test.

## Deferred past I (unchanged)

Embedding / vector retrieval — CD-rag; local model backend adapters — capability-domain
work (§10.2); desktop shell + event streaming — Milestone H; multi-machine anything —
never (single-user non-goal).
