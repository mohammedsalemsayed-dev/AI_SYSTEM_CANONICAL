# Milestone I — Optimization Plan

> **Cross-reference**
> - Role: Build plan for the real offline-evaluation harness, the canary cohort mechanism, and regression protection over a frozen guardrail suite.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [IMPLEMENTATION_PLAN.md](03_IMPLEMENTATION_FOUNDATION/prior_foundation/docs/implementation/IMPLEMENTATION_PLAN.md) milestone I; [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §8 (`VALIDATED → PROMOTED` gate, guardrail set), §9 (role promotion on the guardrail set), §11.2 (observability metrics), §10.1 (build order — I needs F, G).
> - Downstream (depended on by): every future promotion — experience `VALIDATED → PROMOTED`, a role earning "default", a model / routing-weight change — is gated through this milestone's regression check.
> - Predecessors: F (experience lifecycle + the `try_promote` stub this replaces), G (routing stats + the model-eligibility path a routing canary guards). Continues the `milestone_b/` tree.

---

## 1. Purpose

Three promotion paths now exist with only a stub or a manual gate behind them:

- **Experience `VALIDATED → PROMOTED`** — `experience/eval.py` is a deterministic stub that
  derives its numbers from the experience's own shadow log. There is no real held-out replay
  and no real guardrail comparison.
- **A role earning "default"** (Critic, §9) — decided by a benchmark that has to be run by
  hand and is not gated on anything.
- **A model / routing-weight change** (G) — the data-driven router will silently start
  preferring a newly-eligible model with no staged rollout and no abort path.

Milestone I adds the shared machinery all three need:

1. a **frozen guardrail suite** — a stable set of canonical tasks with known T0 oracles,
   run the same way every time;
2. **regression protection** — a stored baseline + a gate that blocks any promotion whose
   guardrail aggregate drops > 2 pp or that makes a previously-passing guardrail task fail;
3. a **real offline eval** — replay a held-out task subset with vs. without the change and
   compare verified success, then run the guardrail gate;
4. a **canary controller** — a promoted change is exercised on a small fraction of live
   matching tasks first, scored against the pre-promotion baseline, and rolled back
   automatically on a significant drop;
5. **derived metrics** (§11.2) — success rate by `task_class`, rework rate, verify-tier
   distribution, escalation frequency, budget-exhaustion rate, quarantine events — folded
   from the event log, so drift is visible.

Guiding rules:
- **§8** — promotion needs *evaluation evidence*; measured improvement is rewarded, not
  novelty. The guardrail set is fixed; a change that regresses it does not ship.
- **§11.2** — every metric is derived and rebuildable from the event log; nothing here is a
  new source of truth.
- **D6** — canonical evidence stays recoverable; the eval writes reports, it never rewrites
  history.
- **Offline-first** — the harness runs deterministically on scripted providers for the test
  suite; the live guardrail run (real models) is a documented, un-run harness like the
  Milestone E benchmark and the Milestone G seeder.

## 2. In scope

| Concern | Milestone I implementation |
|---|---|
| Guardrail suite | `eval/guardrail.py`: `GuardrailSuite` loads a frozen fixture (`eval/fixtures/guardrail_suite.json` — ~12 tiny self-contained tasks in the slice; the target is ~30). `run(run_one)` where `run_one(task) -> bool` is injected (a real orchestrator run, or a fake). `SuiteResult{n, passed, pass_rate, failures[]}`, stable task ordering. |
| Regression baseline | `eval/regression.py`: `RegressionBaseline` over the **system** memory tier (`kind="regression_baseline"`). `set_baseline(SuiteResult)`, `latest()`. `check_regression(candidate, baseline) -> RegressionResult{passed, drop_pp, newly_failing[], recovered[]}`. Gate: `drop_pp <= MAX_GUARDRAIL_DROP_PP` (2.0, shared with §8) **and** `newly_failing == []`. |
| Offline eval | `eval/offline_eval.py`: `OfflineEval(run_with, run_without)` replays a held-out task list twice — with the candidate change applied (an experience's strategy injected as an advisory note; a routing weight set; a role enabled) and without — and returns `EvalReport{heldout_n, with_success, without_success, delta, guardrail: RegressionResult, decision, why}`. `decision` is `promote` only when `delta >= 0` **and** `guardrail.passed`. Security/policy/execution-scope changes still carry the §8 human-approval branch. |
| `try_promote` rewire | `ExperienceStore.try_promote` accepts an optional real `EvalReport`; when given, it uses that instead of the `experience/eval.py` stub. The stub stays as the offline default so the state machine is always exercised. |
| Canary controller | `eval/canary.py`: `CanaryController(baseline_success, *, fraction=0.2, min_samples=10, max_drop_pp=15, seed=None)`. `sample(key) -> bool` (seeded fractional cohort), `record(verified)`, `verdict() -> "PROMOTE" | "HOLD" | "ROLLBACK"`. Rolls back when `min_samples` reached and observed success is `max_drop_pp` below baseline. |
| Experience canary | Orchestrator: a freshly `PROMOTED` experience's first `min_samples` matching live uses form a canary cohort; a `ROLLBACK` verdict auto-quarantines it (reuses the F rollback path) and logs `CANARY`. |
| Routing canary | Orchestrator/router: when the data-driven router first switches a `(task_class)` to a new model, only `fraction` of tasks route to the challenger until the canary clears; a `ROLLBACK` freezes the class back to the incumbent and records it. |
| Derived metrics | `eval/metrics.py`: `rebuild_metrics(log, task_ids) -> Metrics{success_rate_by_class, rework_rate, verify_tier_distribution, escalation_frequency, budget_exhaustion_rate, quarantine_events}`. Pure fold over the event log; no persistence. |
| Standalone guardrail runner | `tests/regression/run_guardrail.py` — build the real orchestrator (subscription), run the suite, compare to the stored baseline, exit non-zero on a regression. `--offline` runs the same flow on scripted providers as a smoke path. **Not run** against real models here. |
| Events | `EVAL`, `CANARY`, `REGRESSION` event kinds. |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| The full ~30-task guardrail suite with realistic repos | later curation — I ships ~12 + the loader; adding tasks is data, not code |
| Logistic-regression weight *fit* for the router (§7.2) | still deferred past I unless data exists — I ships the regression gate that a fitted-weights change would pass through; the fit itself needs a real run corpus |
| Continuous / scheduled guardrail runs | needs the desktop shell (H) + a scheduler; I ships the runnable check |
| Statistical significance testing on canary cohorts | later — I uses a fixed drop threshold, documented as a starting value |
| Per-metric alerting / dashboards | Milestone H (UI) consumes `rebuild_metrics` output |

## 4. Component layout

```
app/services/eval/
  guardrail.py     GuardrailSuite + SuiteResult; frozen fixture loader
  regression.py    RegressionBaseline (system memory) + check_regression()
  offline_eval.py  OfflineEval.evaluate(...) -> EvalReport
  canary.py        CanaryController; verdict PROMOTE / HOLD / ROLLBACK
  metrics.py       rebuild_metrics(log, task_ids) -> Metrics  (§11.2 fold)
  fixtures/guardrail_suite.json
app/schemas/contracts.py   + SuiteResult, RegressionResult, EvalReport, CanaryVerdict, Metrics
app/events/log.py          + EVAL, CANARY, REGRESSION
app/services/experience/store.py   try_promote accepts a real EvalReport
app/orchestration/orchestrator.py  experience + routing canary cohorts; regression gate
                                   before a promotion takes effect
tests/regression/run_guardrail.py  standalone runner (subscription; --offline smoke)
tests/
  unit/         test_guardrail_suite, test_regression_gate, test_offline_eval,
                test_canary, test_metrics
  integration/  test_experience_canary_rollback, test_promotion_blocked_by_regression
```

## 5. Work breakdown (~14 working days)

| Day | Deliverable |
|---|---|
| 1–3 | `eval/guardrail.py` + `eval/fixtures/guardrail_suite.json` (~12 canonical tasks: off-by-one, empty-input, null-guard, pagination, cache-key, parser, float-round, mutable-default, iterator-exhaustion, regex-anchor, timezone, division-guard). `SuiteResult`. Unit tests with an injected `run_one`. |
| 4–5 | `eval/regression.py` — `RegressionBaseline` over system memory; `check_regression()` (drop ≤ 2 pp AND no newly-failing task). Unit tests for both gate sides + the recovered-task case. |
| 6–8 | `eval/offline_eval.py` — `OfflineEval.evaluate()` (with vs. without, held-out delta, then the guardrail gate) → `EvalReport`. Rewire `ExperienceStore.try_promote` to take a real `EvalReport`. Unit + integration: an experience that improves held-out success and holds the guardrail line is promoted; one that regresses the guardrail is not. |
| 9–11 | `eval/canary.py` — `CanaryController`. Orchestrator: freshly-`PROMOTED` experience → canary cohort → `ROLLBACK` auto-quarantines + logs `CANARY`; routing challenger → fractional cohort → `ROLLBACK` freezes back to the incumbent. Integration tests for both. |
| 12 | `eval/metrics.py` — `rebuild_metrics()` folding the event log into the §11.2 metric set. Unit test over a hand-built log. |
| 13 | `tests/regression/run_guardrail.py` — real-orchestrator runner + `--offline` smoke path; wire `EVAL` / `REGRESSION` events. Documented, **not run** against real models. |
| 14 | Regression; `milestone_b/MILESTONE_I_NOTES.md`; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md) + the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md); rehash `MANIFEST.json`. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — `GuardrailSuite.run` returns a stable-ordered `SuiteResult` and counts
  pass/fail from the injected runner; `check_regression` passes at ≤ 2 pp drop with no new
  failure and fails otherwise (new failure, or drop > 2 pp); `OfflineEval` returns
  `decision="promote"` only when held-out delta ≥ 0 **and** the guardrail gate passes;
  `CanaryController` returns `ROLLBACK` once `min_samples` is reached and observed success is
  `max_drop_pp` below baseline, `PROMOTE` when it holds, `HOLD` before `min_samples`;
  `rebuild_metrics` reproduces each §11.2 metric from a hand-built log.
- **Integration** — an experience whose replay improves held-out success and holds the
  guardrail line advances `VALIDATED → PROMOTED`; one that would drop a guardrail task stays
  `VALIDATED` and a `REGRESSION` event records why; a `PROMOTED` experience whose canary
  cohort underperforms is auto-`QUARANTINED` with a `CANARY` event; router unset / eval
  unset → behaviour identical to Milestone G.
- **Failure** — a promotion attempt with a stale or missing baseline is refused (no
  baseline → cannot certify → not promoted), not allowed through by default.
- **Security** — an experience whose strategy touches security / policy / execution scope
  still requires the §8 human approval even with a passing `EvalReport`; the guardrail runner
  never grants a capability or sends anything outward.
- **Recovery** — `reconcile()` + `resume()` work with the eval / baseline tables present; an
  interrupted guardrail run leaves the stored baseline untouched.
- **Benchmark** — `run_guardrail.py` exists, runs in `--offline` mode, and is documented;
  the real-model run is deferred to a session with the subscription.

## 7. Tunable starting values (recalibrate from data)

- Guardrail regression tolerance: **≤ 2.0 pp** aggregate drop (shared with §8), **and** zero
  newly-failing guardrail tasks.
- Offline eval held-out size: **≥ 10** tasks matching the signature (§8).
- Canary cohort fraction: **0.20**; minimum samples before a verdict: **10**; rollback drop:
  **15 pp** below the pre-promotion baseline.
- Baseline staleness: re-run the guardrail baseline when the suite fixture changes or every
  **30 days**, whichever first.
- Slice guardrail suite size: **~12** (target ~30).

## 8. Risks

- **Guardrail suite too small** — 12 tasks makes a 2 pp gate coarse (one task ≈ 8 pp).
  Mitigate: the gate also fails on *any* newly-failing task, which is the sharper signal;
  growing the suite is a fixture edit.
- **Offline eval needs the subscription for real signal** — the deterministic path proves the
  wiring and the decision logic; the actual held-out numbers need a real run. Same shape as
  the E benchmark and G seeder — an un-run harness, not a cut.
- **Canary on a single-user machine** — matching tasks may trickle in slowly, so a canary
  verdict can take a long time. That is acceptable: the change sits at `PROMOTED` but
  canary-gated, still advisory, and rolls back automatically if it does misbehave.
- **Metrics mistaken for truth** — `rebuild_metrics` is a derived view; if it and the log
  disagree, the log wins. Keep it a pure function with no store.
- **Baseline drift** — a baseline captured on a bad day sets a low bar. Mitigate: baseline
  re-run on fixture change / 30 days, and the baseline itself is an event, not a silent
  overwrite.

## 9. Deliverables

- `GuardrailSuite` + frozen fixture; `RegressionBaseline` + `check_regression`;
  `OfflineEval` → `EvalReport` with `try_promote` rewired to consume it; `CanaryController`
  with experience + routing canary cohorts wired into the orchestrator; `rebuild_metrics`
  for the §11.2 set.
- `EVAL` / `CANARY` / `REGRESSION` events.
- `tests/regression/run_guardrail.py` (standalone; `--offline` smoke; real run deferred).
- Test suite: the current 271 green, plus unit (guardrail / regression / offline-eval /
  canary / metrics) and integration (experience canary rollback / promotion blocked by
  regression).
- `milestone_b/MILESTONE_I_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md) and the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md) updated:
  "Controlled self-improvement", "Model benchmarking" (regression side), and the
  experience/model promotion rows move toward FOUNDATION.
