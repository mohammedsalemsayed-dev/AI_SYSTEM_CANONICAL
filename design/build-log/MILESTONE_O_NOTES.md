# Milestone O notes — what is real, what remains

Status against [../MILESTONE_O_PLAN.md](../MILESTONE_O_PLAN.md). **384 tests green.**
All 10 days built. Sixth and final §10.2 capability domain — **all six are now FOUNDATION.**

## Real after Milestone O

| Area | Module | Notes |
|---|---|---|
| Feature vector | `app/services/routing/features.py` | `feature_row(spec, agg)` → an ordered dict `{quality, latency, cost, resource, privacy, local, bias}`; when `agg` has runs, measured success-rate + median-latency replace the priors. `FEATURE_ORDER` fixed. |
| Logistic fit | `app/services/routing/weightfit.py` | `training_rows(stats, registry)` = one `(features, passed)` per scored `model_run`. `fit_weights(rows, l2=1e-3, iters=800, lr=0.2, seed=0)` — stdlib batch gradient descent on the sigmoid log-loss + L2, deterministic (index split, no shuffle) → `WeightSet{weights, feature_order, n_train, val_accuracy, fitted_ts, degenerate}`. `predict()` ∈ [0,1]; `score()` = the raw logit (the router's ranking scalar). < 3 rows or one label → a `degenerate` `WeightSet`, not an exception. Verified: converges to `val_accuracy ≥ 0.95` on a linearly-separable synthetic set; bit-identical across runs. |
| Selection controller | `app/services/routing/selection.py` | `ModelSelectionController(memory, stats, registry)`. Persists per `task_class` to system memory: `selection_mode` (`static` \| `data_driven`) + the current `weight_set`. `evaluate(task_class, regression_check=)` → `data_driven` iff `≥ MIN_ELIGIBLE_MODELS (2)` eligible **and** a non-degenerate `WeightSet` with `n_train ≥ MIN_TRAIN (40)` and `val_accuracy ≥ MIN_VAL_ACC (0.65)` **and** (if supplied) a passing guardrail regression check (`eval/regression.py`). `promote()` persists + logs `SELECTION`; `demote(reason)` reverts + logs. A corrupt persisted `WeightSet` → ignored (fall back to static). |
| Router integration | `app/services/routing/router.py` | `Router(..., selection=None)`. In `_score`: when `selection.mode(task_class) == "data_driven"` and a non-degenerate `WeightSet` exists, rank candidates with `weightfit.score(ws, feature_row(...))`; otherwise the existing `PROVISIONAL_WEIGHTS` path is **untouched**. `PROVISIONAL_WEIGHTS` is now the fallback, not the only option. |
| Orchestrator wiring | `orchestrator._route_and_check_hardware` / `_settle_route_canary` | `self.selection` opt-in. Before routing: `self.router.selection = self.selection`; `selection.promote(task_class, regression_check=<guardrail baseline certify>, log=…)` — a `SELECTION` event records the mode + why. On a route-canary `ROLLBACK` (Milestone I): `route_stats.freeze(...)` **and** `selection.demote(task_class, "route canary rollback")` — the whole class reverts to the static table, not just the one model; re-promotion needs a fresh `evaluate`. Selection unset → routing byte-identical to Milestone N. |
| Offline fitter | `tests/benchmark/fit_weights.py` | Reads a populated `RouteStatsStore`, fits a `WeightSet` per `task_class`, prints per-class `val_accuracy` + weights; `--write` persists them via `ModelSelectionController`. **Not run** — needs a real scored-run corpus (produce one with `seed_model.py` on the subscription). |
| Schema / events | `+ WeightSet` (carries `n_train`, `val_accuracy`, `fitted_ts`, `degenerate`); `SELECTION` event kind. |

## Scope / security posture

- Model selection changes **which provider runs**, never the policy / capability / taint /
  T-ladder path. The billed `anthropic` provider is still never chosen unless explicitly
  enabled.
- A `WeightSet` is config data, not executable; it is persisted as a system-memory record
  and validated on read.
- The switchover is gated three ways: the eligibility count, the fit-quality gate
  (`n_train` + held-out `val_accuracy` + non-degenerate), and the Milestone I guardrail
  regression check. The runtime backstop is the Milestone I route canary, which now demotes
  the class on rollback.
- Reversible and non-thrashing: `demote()` is immediate; re-promotion requires a fresh full
  `evaluate()` pass (not automatic).

## Not yet real / deferred

- **No real fit** — every `task_class` starts `static`; O ships the fitter + the switch. A
  real `WeightSet` needs a scored-run corpus (the offline fitter is the tool; it is not run
  here). This is the intended shape — §7.2 says the harness exists to seed the threshold.
- **Logistic regression only** — §7.2's stated method; interpretable (you can read the
  weights). A richer model (trees, a small MLP) is a swap behind `WeightSet`.
- **One weight set per `task_class`** — per-role sets (interpreter vs. builder) are additive.
- **No automatic quarterly refit** — `WeightSet.fitted_ts` carries the age; a scheduler
  (desktop shell) drives the refit later. A "refit due" check is a small follow-up.
- **Feature set is the six §7.2 priors** — `feature_row` is the extension point.

## Deferred past O (unchanged)

All six §10.2 capability domains are now FOUNDATION (repo-intel, research, RAG, authoring,
engines, model-selection). Remaining project work: run the live harnesses on the
subscription (premise test, multi-agent benchmark, `seed_model.py`, `fit_weights.py`,
`run_guardrail.py`); the Tauri native build; real renderer/RAG/engine-toolchain
integrations behind their seams; Milestone A hardening (Postgres / Redis / full telemetry).
