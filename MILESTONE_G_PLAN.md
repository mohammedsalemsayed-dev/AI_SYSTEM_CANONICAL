# Milestone G — Routing and Hardware Plan

> **Cross-reference**
> - Role: Build plan for the provider registry, the static → data-driven routing loop, hardware-mode policy, and the `stronger_model` escalation rung.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [IMPLEMENTATION_PLAN.md](03_IMPLEMENTATION_FOUNDATION/prior_foundation/docs/implementation/IMPLEMENTATION_PLAN.md) milestone G; [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §6 (task taxonomy), §7 (routing + benchmark loop), §10.1–§10.2 (build order), §11 (budget/observability); prior-foundation `services/routing/router.py` + `services/hardware/policy.py`.
> - Downstream (depended on by): Milestone I (logistic-regression weight fit + canary reads routing stats); "Automated model selection" capability domain (§10.2) unlocks at ≥ 20 verified runs/class.
> - Predecessors: B (produces `ModelRunRecord` data), F (system-memory tier for the benchmark DB). Continues the `milestone_b/` tree.

---

## 1. Purpose

The slice routes every role to one hardcoded provider (`get_llm("agent_sdk")`). There is no
notion of a cheaper local tier, no record of which model is actually good at which
`task_class`, no back-off when the machine is hot, and the `stronger_model` rung on the
escalation ladder is a log-and-advance stub. Milestone G adds:

- a **provider registry** — the set of routable `(provider, model)` targets with capability
  and cost priors;
- the **static routing table** from §7.1 with its escalation triggers;
- the **data-driven loop** from §7.2 — `ModelRunRecord`s accumulate in system memory, a
  model becomes *eligible* for a class after ≥ 20 verified runs, and routing then blends
  measured success/latency/cost with the static default;
- **hardware modes** — `NORMAL → EFFICIENT → CONSERVATION → PROTECTIVE → EMERGENCY` — read by
  the router to bias toward local / pause work;
- the real **`stronger_model`** ladder rung — re-route a stalled role to the best eligible
  cloud model and re-run.

Guiding rules:
- **§7.2** — a run counts toward routing stats **only if** its `verification_result` links a
  `VerificationRecord` at tier ≥ T1. Unverified runs are logged, not scored.
- **§7.2** — no magic-number score weights ship un-tagged. Milestone G ships **`provisional`**
  hand-tuned weights; the logistic-regression fit is Milestone I.
- **§7.1** — until a model is eligible, the static table governs and the router explores
  deliberately (ε = 0.15).
- **§10** — full scope is preserved. Local model tiers are **declared** in the registry now
  and marked unavailable; the local-backend adapter is a named seam, not a cut.
- **Non-goal (unchanged)** — no autonomous spend; the subscription path stays default and
  the `anthropic` billed path stays opt-in.

## 2. In scope

| Concern | Milestone G implementation |
|---|---|
| Provider registry | `ProviderSpec{id, provider, model, local, context_window, quality_prior, latency_prior_s, cost_prior_usd, resource_cost, privacy_score, available, notes}`. Seeded with `agent_sdk` (subscription Claude, cloud, default), `anthropic` (API, cloud, opt-in), `scripted` (tests). Local tiers (`local-small`, `local-coder`, `local-reasoner`) declared with `available=False` — the local adapter is a Milestone-G+ seam. |
| Static routing table (§7.1) | `table.py`: per `task_class` → default route + the escalation-trigger predicates ("2 failed verify cycles", "repo context exceeds local window", "plan touches > N modules or security paths", "user marks high-stakes"). `planning_arch` routes to cloud-frontier by design. |
| Routing stats (§7.2) | `RouteStatsStore` over the **system** memory tier (Milestone F). Per `(task_class, model)`: verified-success rate, median + p90 latency, median resource cost, est. cost — trailing **90 days or last 50 runs**, whichever is smaller. Ingest is gated on a linked T1+ `VerificationRecord`. |
| Eligibility + exploration | A model is **eligible** for a class after ≥ **20** verified runs. Below that: static table + ε = **0.15** deliberate exploration among available candidates. |
| Data-driven route | Once ≥ 1 model is eligible for the class, `Router` scores eligible candidates (`provisional` weights: `+quality, +privacy, −latency, −cost, −resource_cost`, local bonus under CONSERVATION/PROTECTIVE) and takes the best unless the static default scores within a margin (stability guard). |
| Hardware modes | `hardware/modes.py`: `HardwareMode` + `decide(snapshot, progress_good)` (ported + extended from prior foundation). `hardware/monitor.py`: `HardwareMonitor` seam returning a static `NORMAL` snapshot on this machine — real GPU/RAM/thermal telemetry is deferred (named seam). Router reads the mode; `EMERGENCY` → pause to `WAITING_FOR_USER`; `PROTECTIVE`/`CONSERVATION` → force local-eligible or the cheapest cloud model. |
| `stronger_model` rung | `orchestrator._run_ladder`: on the `stronger_model` rung, re-route the failing role to the highest-`quality_prior` **eligible** cloud provider not already tried, re-run the step, log a `ROUTE` event. Actionable only when such a target exists. |
| Offline benchmark seeder | `tests/benchmark/seed_model.py` — replay a frozen task set with known T0 oracles against a named model, write **scored** `ModelRunRecord`s so a new model reaches the 20-run eligibility threshold without waiting for live traffic. (Not run here — needs the subscription.) |
| Orchestrator wiring | `Router` is an opt-in field. When set: each role's provider is chosen per task via `router.route(...)`; the chosen `ProviderSpec` builds the role LLM; `MODEL_RUN` records carry `provider` / `model`; on a verified completion the stats store ingests every role run. Router unset → today's single shared LLM, unchanged. |
| Events | `ROUTE` (chosen provider + reason + escalated flag), `HARDWARE` (mode transition). |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Local model backend / adapter (llama.cpp, Ollama, …) | Milestone G+ / capability-domain work — registry entries exist, marked unavailable |
| Real hardware telemetry (GPU temp, VRAM, power) | later — `HardwareMonitor` returns a static snapshot; the policy + wiring are real |
| Logistic-regression weight fit | Milestone I — G ships `provisional` hand-tuned weights, tagged |
| Canary / regression-gated model promotion | Milestone I |
| Per-token cost accounting for the subscription path | never meaningfully — subscription is rate-limited, not billed; `cost_prior_usd = 0` for `agent_sdk` |
| Multi-machine / distributed routing | never (single-user non-goal) |

## 4. Component layout

```
app/services/routing/
  registry.py     ProviderRegistry, ProviderSpec; default seed
  table.py        static §7.1 table + escalation-trigger predicates
  stats.py        RouteStatsStore over system memory; windowed aggregates; eligibility
  router.py       Router.route(task_class, role, *, attempt, hardware_mode,
                  context_tokens, risk_level, tried) -> RouteDecision
app/services/hardware/
  modes.py        HardwareMode + decide(snapshot, progress_good)
  monitor.py      HardwareMonitor seam (static NORMAL snapshot)
app/schemas/contracts.py   + ProviderSpec, RouteDecision, HardwareSnapshot
app/events/log.py          + ROUTE, HARDWARE
app/orchestration/orchestrator.py   Router opt-in; per-role selection; stats ingest;
                                    stronger_model rung; EMERGENCY pause
tests/benchmark/seed_model.py       offline eligibility seeding (not run)
tests/
  unit/         test_provider_registry, test_routing_table, test_route_stats,
                test_router, test_hardware_modes
  integration/  test_routing_records_and_persists, test_stronger_model_rung,
                test_hardware_pause
```

## 5. Work breakdown (~14 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `routing/registry.py` (`ProviderSpec`, `ProviderRegistry`, default seed with local tiers unavailable) + `routing/table.py` (static §7.1 table + escalation-trigger predicates). Unit tests: every `task_class` has a default; each trigger fires on its condition. |
| 3–4 | `hardware/modes.py` (`HardwareMode` + `decide()`), `hardware/monitor.py` (static-snapshot seam). Unit tests: each threshold band; `progress_good` interaction. |
| 5–6 | `routing/stats.py` — `RouteStatsStore` over the system memory tier; ingest gated on a linked T1+ `VerificationRecord`; trailing 90 d / last 50 aggregates; `eligible(task_class, model)` at ≥ 20 verified runs. Unit tests incl. the "unverified run is logged not scored" rule. |
| 7–8 | `routing/router.py` — `Router.route(...)`: static default; ε = 0.15 exploration below eligibility; data-driven score (provisional weights, tagged) once ≥ 1 model eligible, with a static-default stability margin; hardware-mode bias. Unit + a first integration test with a scripted registry. |
| 9–10 | Orchestrator wiring: `Router` opt-in; per-role provider selection; `MODEL_RUN` carries `provider`/`model`; stats ingest on verified completion; `ROUTE` + `HARDWARE` events. Integration: a routing decision is recorded; a fresh `Orchestrator` over the same system memory reuses the accumulated stats. |
| 11–12 | `stronger_model` ladder rung made real — re-route the stalled role to the best untried eligible cloud model, re-run the step. Failure test: a stalled task escalates through `change_strategy` → … → `stronger_model` and the re-run uses a different provider. `EMERGENCY` hardware mode → `WAITING_FOR_USER`. |
| 13 | `tests/benchmark/seed_model.py` — replay a frozen T0-oracle task set against a named model, write scored `ModelRunRecord`s to reach eligibility offline. Documented, **not run** (needs the subscription), mirroring the Milestone E benchmark. |
| 14 | Regression; `milestone_b/MILESTONE_G_NOTES.md`; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md) + the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md); rehash `MANIFEST.json`. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — every `task_class` resolves to a default route; each escalation trigger fires
  only on its condition; `decide()` returns the right `HardwareMode` at each threshold band;
  `RouteStatsStore` ignores a run with no T1+ verification link, aggregates within the
  window, and reports `eligible` only at ≥ 20 verified runs; `Router` returns the static
  default below eligibility (modulo ε exploration, which is seed-controlled in tests) and the
  higher-scoring eligible model above it.
- **Integration** — with a `Router` wired over a scripted 2-provider registry, a completed
  task logs a `ROUTE` event and a `MODEL_RUN` carrying `provider`/`model`; the verified run
  is ingested; a fresh `Orchestrator` over the same `MemoryStore` sees the accumulated
  `(task_class, model)` stats. Router unset → behaviour identical to Milestone F.
- **Failure** — a task that stalls past the earlier rungs reaches `stronger_model`, the
  re-run is routed to a different (higher-quality, eligible) provider, and a `ROUTE` event
  records `escalated=true`; if no such target exists the rung is non-actionable and the
  ladder advances to `ask_user`.
- **Security** — routing never changes the policy/capability path; a `code_edit_broad` whose
  plan touches a security-relevant path escalates to cloud **review** but the diff still
  goes through the same T0 + policy gates; the `anthropic` billed provider is never selected
  unless explicitly enabled.
- **Recovery** — `reconcile()` + `resume()` work with the routing tables present; an
  interrupted task ingests no routing stats (ingest is verified-completion-only).
- **Benchmark** — `seed_model.py` exists and is documented; running it is deferred to a
  session with the subscription.

## 7. Tunable starting values (§7; recalibrate from data)

- Eligibility threshold: **≥ 20** verified runs per `(task_class, model)`.
- Exploration: **ε = 0.15** below eligibility.
- Stats window: **90 days** or **last 50** runs, whichever is smaller.
- Static-default stability margin: a data-driven winner must beat the static default's score
  by **≥ 0.05** to displace it.
- `provisional` score weights: `+4·quality +2·privacy −1.5·latency −2·cost −2·resource_cost`,
  `+1` local bonus under CONSERVATION/PROTECTIVE (ported from the prior foundation; tagged
  `provisional`).
- Hardware thresholds (°C / RAM % / GPU %): EMERGENCY ≥ 90; PROTECTIVE ≥ 85;
  CONSERVATION ≥ 80 or RAM ≥ 92 or (GPU ≥ 95 and not progress_good); EFFICIENT GPU ≥ 75 or
  RAM ≥ 80.
- `code_edit_broad` "broad" threshold: plan touches **> 3** modules or any risk-glob path.

## 8. Risks

- **No live data on a fresh install** — every class starts below eligibility, so G is "static
  table + a stats recorder" until traffic accrues. That is the intended shape; the seeder
  exists to bootstrap a *new model*, not the whole table.
- **No local backend yet** — the local rows in the registry are unavailable, so on this
  machine every route resolves to a cloud model. The value delivered now is the *decision
  structure* + stats + hardware policy + the `stronger_model` rung; the local adapter slots
  in behind the registry without touching the router.
- **Provisional weights** — hand-tuned weights can misrank; mitigate by keeping the
  static-default stability margin and by tagging every weight `provisional` so Milestone I
  knows to replace them.
- **Hardware snapshot is static** — the policy and the pause path are real but never trigger
  on this machine until real telemetry lands. The `EMERGENCY` pause is unit- and
  integration-tested with an injected snapshot.
- **ε exploration in tests** — must be seedable/disable-able so routing tests are
  deterministic.

## 9. Deliverables

- `ProviderRegistry` + static routing table + `RouteStatsStore` (system memory) + `Router`
  with the static → data-driven blend and hardware-mode bias; `HardwareMode` policy + a
  monitor seam; the real `stronger_model` ladder rung; `EMERGENCY` → pause.
- `MODEL_RUN` records carrying `provider`/`model`; `ROUTE` and `HARDWARE` events.
- `tests/benchmark/seed_model.py` (offline eligibility seeding; not run).
- Test suite: the current 254 green, plus unit (registry / table / stats / router /
  hardware) and integration (routing recorded + persisted / `stronger_model` rung /
  hardware pause).
- `milestone_b/MILESTONE_G_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md) and the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md) updated:
  "Hardware-aware routing", "Model/provider registry", "Benchmark-driven selection" move
  toward FOUNDATION.
