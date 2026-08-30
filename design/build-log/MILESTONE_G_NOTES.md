# Milestone G notes — what is real, what remains

Status against [../MILESTONE_G_PLAN.md](../MILESTONE_G_PLAN.md). **271 tests green.**
All 14 days built.

## Real after Milestone G

| Area | Module | Notes |
|---|---|---|
| Provider registry | `app/services/routing/registry.py` | `ProviderSpec{id, provider, model, local, context_window, quality_prior, latency_prior_s, cost_prior_usd, resource_cost, privacy_score, available, notes}`. Default seed: `agent_sdk` (subscription, cloud, **available**, `cost_prior_usd=0`), `anthropic` (API, billed, `available=False`), `local-small` / `local-coder` / `local-reasoner` (`available=False` — the local backend adapter is a named seam). `ProviderRegistry` deep-copies the seed so callers never mutate it. |
| Static routing table | `app/services/routing/table.py` | `STATIC_TABLE` — one `RoutePolicy{prefer, cloud_review_plan, always_cloud, local_window}` per §6 `task_class`. `policy_for()` + `escalation_reason()` encodes the §7.1 "escalate to cloud when …" column as predicates over `attempt` / `context_tokens` / `risk_level` / `modules_touched` / `high_stakes` / `contradiction_unresolved` / `user_requested_cloud`. `planning_arch` is always cloud by design. |
| Routing stats | `app/services/routing/stats.py` | `RouteStatsStore` over the **system** memory tier. `ingest()` returns `False` and stores nothing unless the run's `verification_tier` is `T1`/`T2`/`T3` (§7.2 — unverified runs are logged elsewhere, not scored). Per `(task_class, model)`: verified-success rate, median + p90 latency, median resource / cost, over the trailing **90 days or last 50** scored runs. `eligible()` at **≥ 20** scored runs; `eligible_models()` / `aggregate()`. |
| Router | `app/services/routing/router.py` | `Router.route(task_class, role, *, attempt, hardware_mode, context_tokens, risk_level, tried, …) -> RouteDecision`. Order: EMERGENCY → pause (`provider_id=""`); static default (first available id in `prefer`, skipping `tried`); escalation trigger or hardware-local-bias → override; ≥ 1 eligible model → score eligible candidates with `PROVISIONAL_WEIGHTS` blended with measured stats and displace the static pick only by ≥ `STABILITY_MARGIN` (0.05); else with prob. `EPSILON` (0.15, seeded RNG) explore another candidate. Every weight is tagged `provisional` — Milestone I fits them. |
| Hardware modes | `app/services/hardware/modes.py` | `HardwareMode` `NORMAL→EFFICIENT→CONSERVATION→PROTECTIVE→EMERGENCY`; `decide(snapshot, progress_good)` ported + extended from the prior foundation. `biases_local()` (CONSERVATION+), `should_pause()` (EMERGENCY). Thresholds are §7 starting values. |
| Hardware monitor seam | `app/services/hardware/monitor.py` | `HardwareMonitor.sample()` → static `NORMAL` snapshot on this machine (real GPU temp / VRAM / power sampling deferred). `StaticHardwareMonitor(snapshot)` for tests and for a manual "quiet mode" pin. |
| Orchestrator wiring | `orchestrator._route_and_check_hardware` / `_hardware_mode` / `_ingest_route_stats` / `_stronger_model_route` | `router` / `route_stats` / `hardware` are opt-in fields. At PLANNING: sample the hardware mode (log `HARDWARE` if ≠ NORMAL), `router.route(...)`, log a `ROUTE` event; a paused decision → `WAITING_FOR_USER`. On a verified completion: reconstruct every `MODEL_RUN`, tag it with the chosen provider, and `route_stats.ingest(...)` (T1+ only). Router unset → behaviour identical to Milestone F. |
| `stronger_model` ladder rung | `orchestrator._run_ladder` + `Ladder(has_stronger_model=)` | On the `stronger_model` rung: re-route to the best **untried** cloud provider (`attempt=99`, `user_requested_cloud=True`), log a `ROUTE` with `escalated=true`, and drive a `_replan` carrying the escalation note. Non-actionable (advance to `ask_user`) when no untried stronger provider exists — which is the case on the default single-cloud registry. |
| Offline eligibility seeder | `tests/benchmark/seed_model.py` | Replays a frozen premise task set with T0 oracles against one named model and writes scored `ModelRunRecord`s to a `MemoryStore`, then prints the per-class aggregates + eligibility. **Not run** (real model calls) — mirrors the Milestone E benchmark. |
| Events | `ROUTE` (the full `RouteDecision`), `HARDWARE` (mode + source). |

## Not yet real / deferred

- **No local model backend** — the local registry rows are `available=False`, so on this
  machine every route resolves to `agent_sdk`. The value delivered is the decision structure
  + stats recorder + hardware policy + the real `stronger_model` rung; a llama.cpp / Ollama
  adapter slots in behind the registry with **no router change**.
- **Routing does not yet swap the role LLM** — the orchestrator's Interpreter / Planner /
  Builder are constructed once and hold their own LLM. G records *which* provider should run
  and accumulates the stats to justify it; per-task LLM construction from the chosen
  `ProviderSpec` is a small follow-up once a second provider is actually runnable.
- **Real hardware telemetry** — `HardwareMonitor` returns a static snapshot; the mode policy
  and the `EMERGENCY` pause are exercised only with an injected snapshot (unit + integration).
- **Provisional score weights** — hand-tuned; `PROVISIONAL_WEIGHTS` is tagged so Milestone I
  replaces it with a logistic-regression fit. The `STABILITY_MARGIN` guards against a
  mis-rank displacing a good static default.
- **No live data on a fresh install** — every `(task_class, model)` starts below the 20-run
  threshold, so routing is "static table + stats recorder" until traffic (or `seed_model.py`)
  accrues.
- **`seed_model.py` has not been run** — needs the subscription.

## Deferred past G (unchanged)

Logistic-regression weight fit + canary + regression-gated model promotion — Milestone I;
local model adapters + engine-aware expert modes — capability-domain work (§10.2);
multi-machine routing — never (single-user non-goal).
