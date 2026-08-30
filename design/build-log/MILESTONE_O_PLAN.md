# Milestone O — Automated Model Selection Plan


---

## 1. Purpose

Milestone G shipped the data-driven router with **`PROVISIONAL_WEIGHTS`** — hand-tuned and
explicitly tagged for replacement. It also shipped `RouteStatsStore` with a ≥ 20-scored-run
eligibility threshold. What is missing is §7.2's actual mechanism:

- a **fitted weight model** — logistic regression over per-`(task_class, model)` features
  (quality prior, latency, cost, resource, privacy, local) with the label = verified
  success — replacing the provisional constants;
- a **selection controller** — per `task_class`, decide when the eligible models + a fitted
  weight set + a passing regression check justify flipping that class from the static table
  to data-driven, and persist that decision;
- **router integration** — the `Router` uses the fitted weights for a class in data-driven
  mode, the provisional weights otherwise;
- an **offline fitter** — a script that reads a populated `RouteStatsStore` and writes a
  `WeightSet` (not run here — needs a real scored-run corpus, like the Milestone G seeder).

Guiding rules:
- **§7.2** — weights are fit, not tuned; a fitted `WeightSet` carries its training-set size,
  fit date, and validation accuracy. A refit is due quarterly or when a class crosses a new
  eligibility tier.
- **§8** — a class only flips to data-driven if the guardrail regression check
  (`eval/regression.py`) passes on the candidate routing; a flip that would regress the
  guardrail is refused and logged.
- **Reversible** — `demote(task_class)` puts a class back on the static table immediately
  (an operator action or an automatic response to a canary rollback, Milestone I).
- **No behaviour change when unused** — `selection` unset → the router keeps using
  `PROVISIONAL_WEIGHTS`, exactly as after Milestone G.
- **stdlib only** — the logistic fit is a small hand-written gradient descent; no numpy.

## 2. In scope

| Concern | Milestone O implementation |
|---|---|
| Feature vector | `routing/features.py`: `feature_row(spec: ProviderSpec, agg: dict) -> dict` — `quality` (verified-success rate if eligible else `quality_prior`), `latency` (median/60 if eligible else `latency_prior_s/60`), `cost` (`cost_prior_usd`), `resource` (`resource_cost`), `privacy` (`privacy_score`), `local` (0/1), `bias` (1.0). Stable key order. |
| Training set | `routing/weightfit.py::training_rows(stats, registry) -> list[(features, label)]` — one row per scored `model_run` in `RouteStatsStore` (features from the row's aggregates-at-time + the registry spec; label = `passed`). Bounded to the stats window. |
| Logistic fit | `routing/weightfit.py::fit_weights(rows, *, l2=1e-3, iters=800, lr=0.2, seed=0) -> WeightSet` — batch gradient descent on the sigmoid log-loss with L2; deterministic (no shuffle). `WeightSet{weights: dict, n_train, fitted_ts, val_accuracy, feature_order}`. `predict(weightset, features) -> float` (0..1). `score(weightset, features) -> float` (the router's ranking scalar = the logit). |
| Selection controller | `routing/selection.py`: `ModelSelectionController(memory, stats, registry)`. Persists per `task_class` to system memory: `selection_mode` (`static` \| `data_driven`) and the current `weight_set`. `evaluate(task_class, *, regression_check=None) -> Decision` — data-driven iff (≥ `MIN_ELIGIBLE_MODELS` eligible) AND (a `WeightSet` with `n_train ≥ MIN_TRAIN` and `val_accuracy ≥ MIN_VAL_ACC` exists) AND (`regression_check` passes, if supplied). `promote()` / `demote(task_class, reason)` with a `SELECTION` event. `mode(task_class) -> str`, `weights_for(task_class) -> WeightSet | None`. |
| Router integration | `routing/router.py`: `Router(..., selection=None)`. In `_score`, when `selection` is set and `selection.mode(task_class) == "data_driven"` and a `WeightSet` is available, rank with `weightfit.score(weightset, feature_row(...))`; otherwise the existing `PROVISIONAL_WEIGHTS` path (untouched). |
| Offline fitter | `tests/benchmark/fit_weights.py` — `python -m tests.benchmark.fit_weights --memory route_stats.db [--min-per-class 20]`: build `training_rows` from a populated `RouteStatsStore`, `fit_weights`, print per-class `val_accuracy` + the weights, and (with `--write`) persist a `WeightSet` per class via `ModelSelectionController`. **Not run** — needs a real scored-run corpus. |
| Schemas / events | `+ WeightSet` (pydantic) in `contracts.py`; `SELECTION` event kind (`task_class`, mode, n_train, val_accuracy, reason). |
| Canary tie-in (Milestone I) | `orchestrator._settle_route_canary` — on a `ROLLBACK` for a data-driven challenger, also call `selection.demote(task_class, "canary rollback")` so the class reverts to the static table, not just freezes the one model. |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Actually fitting on real data | needs a scored-run corpus (subscription) — the offline fitter is built, not run |
| Non-linear models (trees, small MLPs) | logistic regression is §7.2's stated method; a richer model is a later swap behind `WeightSet` |
| Per-role weight sets (interpreter vs builder) | one weight set per `task_class` in the slice; per-role is additive |
| Automatic quarterly refit scheduling | needs the desktop-shell scheduler; O ships the fitter + the "refit due" flag |
| Feature engineering beyond the six priors | later — `feature_row` is the extension point |
| Confidence intervals / A-B significance on the flip | Milestone I's canary is the runtime guard; a formal test is later |

## 4. Component layout

```
app/services/routing/
  features.py    feature_row(spec, agg) -> ordered dict
  weightfit.py   training_rows(); fit_weights() -> WeightSet; predict(); score()
  selection.py   ModelSelectionController — mode/promote/demote per task_class, persisted
  router.py      + selection= ; _score consults the fitted WeightSet when data-driven
app/schemas/contracts.py            + WeightSet
app/events/log.py                   + SELECTION
app/orchestration/orchestrator.py   opt-in self.selection; wire into routing + the canary demote
tests/benchmark/fit_weights.py      offline fitter (not run)
tests/
  unit/         test_features, test_weightfit, test_model_selection
  integration/  test_data_driven_switchover
```

## 5. Work breakdown (~10 working days)

| Day | Deliverable |
|---|---|
| 1 | `routing/features.py` — `feature_row`; stable order. Unit tests: eligible vs. not changes `quality`/`latency`; `local` is 0/1. |
| 2–4 | `routing/weightfit.py` — `fit_weights` (logistic GD + L2), `predict`, `score`, `WeightSet`. Unit tests: converges on a linearly-separable synthetic set (`val_accuracy` ≥ 0.95); deterministic across runs with the same seed; degrades gracefully on < a handful of rows (returns a low-confidence `WeightSet`, not a crash). |
| 5–6 | `routing/selection.py` — `ModelSelectionController`; persistence to system memory; `evaluate` / `promote` / `demote`; `SELECTION` events. Unit tests: stays `static` below `MIN_ELIGIBLE_MODELS` / `MIN_TRAIN` / `MIN_VAL_ACC`; flips to `data_driven` when all hold and a supplied regression check passes; `demote` reverts and logs. |
| 7 | `routing/router.py` — `selection=` param; `_score` uses `weightfit.score` for a data-driven class, else `PROVISIONAL_WEIGHTS`. Unit test: same candidates, different pick under a contrived weight set. |
| 8 | Orchestrator wiring — `self.selection` opt-in; consulted in `_route_and_check_hardware`; `_settle_route_canary` rollback also `demote`s the class. Integration: with a seeded `RouteStatsStore` (≥ 20 scored runs for 2 models) + a fitted `WeightSet`, a `code_edit_local` task routes data-driven and a `SELECTION` event records the mode; a forced canary rollback demotes it back to static. |
| 9 | `tests/benchmark/fit_weights.py` — offline fitter reading a `RouteStatsStore`; `--write` persists per-class `WeightSet`s. Documented, **not run**. |
| 10 | Regression; `../nexus/MILESTONE_O_NOTES.md`; update [STATUS.md](../STATUS.md), the [connective index](../requirements.md), and the top-level [README.md](../../README.md); commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — `feature_row` returns the six features + bias in a stable order and reflects
  eligibility; `fit_weights` reaches `val_accuracy ≥ 0.95` on a separable synthetic set, is
  bit-identical across two runs with the same seed, and returns a usable low-confidence
  `WeightSet` (not an exception) on 3 rows; `predict` is in `[0, 1]`;
  `ModelSelectionController.evaluate` returns `static` unless eligible-count, train-count,
  val-accuracy, and the regression check all pass, and `demote` flips it back and logs a
  `SELECTION` event; the `Router` picks a different model under a data-driven weight set than
  under `PROVISIONAL_WEIGHTS` for a constructed case.
- **Integration** — with a `RouteStatsStore` seeded to eligibility for two models on
  `code_edit_local` and a persisted `WeightSet`, a task routes via the fitted weights and a
  `SELECTION` event says `data_driven`; triggering a route-canary `ROLLBACK` demotes the
  class and the next task routes `static` again. `selection` unset → routing is byte-identical
  to Milestone N.
- **Failure** — a class with a fitted `WeightSet` but only 1 eligible model stays `static`
  (can't compare); a corrupt / unparseable persisted `WeightSet` is ignored (fall back to
  static), not fatal; `fit_weights` on all-same-label rows returns a `WeightSet` flagged
  `degenerate` and the controller refuses to promote on it.
- **Security** — model selection changes *which provider* runs, never the policy / capability
  / taint path; the billed `anthropic` provider is still never chosen unless explicitly
  enabled; a `WeightSet` is config, not executable.
- **Recovery** — `reconcile()` + `resume()` unaffected; the persisted mode + weight set
  survive a fresh `Orchestrator` over the same system memory; an interrupted fit writes
  nothing.
- **Benchmark** — `fit_weights.py` exists and is documented; a real fit needs the scored-run
  corpus and is deferred to a subscription session.

## 7. Tunable starting values

- `MIN_ELIGIBLE_MODELS` = **2** (need something to choose between).
- `MIN_TRAIN` = **40** rows, `MIN_VAL_ACC` = **0.65** (better than a coin, on a held-out
  20%).
- `fit_weights`: `l2 = 1e-3`, `iters = 800`, `lr = 0.2`, `seed = 0`, 80/20 train/val split
  by row index.
- Refit due after **90 days** or when a class's eligible-model set changes.
- Canary rollback → immediate `demote`; re-promotion requires a fresh `evaluate` pass.

## 8. Risks

- **No real data** — every class starts `static`; O is "the fitter + the switch" until a
  corpus exists. That is the intended shape (§7.2 says the harness exists to seed the
  threshold); the offline fitter is the tool.
- **Logistic regression is simple** — it may underfit a non-linear quality/cost trade-off.
  Accepted: it is §7.2's stated method, it is interpretable (you can read the weights), and
  the `WeightSet` seam allows a richer model later.
- **Overfitting on a thin corpus** — `MIN_TRAIN` + the held-out `val_accuracy` gate + L2
  guard against promoting a fluke; the canary + regression check are the runtime backstop.
- **Flip thrash** — a class oscillating static↔data-driven. Mitigated: re-promotion needs a
  fresh full `evaluate` (not automatic after a demote), and the guardrail check must pass
  each time.
- **Weights drift silently** — a `WeightSet` carries `fitted_ts`; a "refit due" flag surfaces
  staleness. Automatic refit scheduling is deferred but the signal is there.

## 9. Deliverables

- `app/services/routing/` — `features.py`, `weightfit.py`, `selection.py`; `router.py`
  `selection=` integration.
- `WeightSet` schema; `SELECTION` event kind.
- Orchestrator: opt-in `ModelSelectionController` consulted in routing; canary rollback →
  `demote`.
- `tests/benchmark/fit_weights.py` (offline; not run).
- Test suite: the current 376 green, plus unit (features / weightfit / selection) and
  integration (data-driven switchover + canary demote).
- `../nexus/MILESTONE_O_NOTES.md`.
- [STATUS.md](../STATUS.md), the
  [connective index](../requirements.md), and the
  top-level [README.md](../../README.md) updated: "Model benchmarking" / "Automated code review"
  routing rows note the fitted-weight selection path; `PROVISIONAL_WEIGHTS` is now the
  fallback, not the only option. **All six §10.2 capability domains are then FOUNDATION.**
