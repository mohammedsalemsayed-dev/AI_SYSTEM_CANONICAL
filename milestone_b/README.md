# Milestone B slice — working tree

Live implementation of [../MILESTONE_B_PLAN.md](../MILESTONE_B_PLAN.md). Kept separate
from `03_IMPLEMENTATION_FOUNDATION/prior_foundation/` (reference scaffold, not edited).

## Quick start

```bash
cd milestone_b
python -m pip install -e ".[dev]"    # pydantic + pytest
python -m pytest                      # 47 tests
python -m app.cli.demo               # offline end-to-end run, no API key
```

## Status

| Plan day | Deliverable | State |
|---|---|---|
| 1 | Event log + projections + state gates + contract validation | **done** |
| 2 | LLM seam (`ScriptedLLM` + `AnthropicLLM`) + Interpreter | **done** |
| 3 | Planner + workspace listing | **done** |
| 4–5 | Builder seam (`ScriptedBuilder` + `AgentSDKBuilder`) + workspace-copy/diff | **done** |
| 6 | Verifier T0 (fresh copy, apply diff, run pytest) | **done** |
| 7 | Orchestrator (full §1 flow) + CLI + offline demo | **done** |
| 8 | Integration happy path + failure paths | **done** |
| 9 | Light recovery (`resume`, interrupted-task, reopen) | **done** |
| 10 | premise test + `SLICE_FINDINGS.md` | **done — 10/10 tasks correct on the Pro subscription; see [SLICE_FINDINGS.md](SLICE_FINDINGS.md)** |

### Milestone C ([../MILESTONE_C_PLAN.md](../MILESTONE_C_PLAN.md)) — security and authority

See [MILESTONE_C_NOTES.md](MILESTONE_C_NOTES.md) for what is real vs. pending.

| Plan day | Deliverable | State |
|---|---|---|
| 1–2 | Capability registry + issuance + grant scope math; `CAPABILITY_GRANT` logged | **done** |
| 3–4 | Policy Engine (7 ordered rules) replaces `AllowAllPolicy` | **done** |
| 5 | Structural taint boundary + side-effecting check | **done** |
| 6 | Egress broker (per-task allowlist, default deny) | **done** |
| 7–9 | Tier-A sandbox: `SandboxRunner`, `DockerSandbox`, fallback, verifier wired | **done — Docker 29.5 installed, image built, real containers run** |
| 10 | Approval flow: `REQUIRE_APPROVAL` → `WAITING_FOR_USER` → `resume(approval=…)` | **done** |
| 11 | Secret isolation: `SecretStore` + `scrub_env`, both backends scrub | **done** |
| 12 | Audit: new event kinds + projection fields | **done** |
| 13–14 | Security gate: injection corpus + traversal battery + objective-preservation + no-network | **done** |
| 15 | Wire-up, status update, notes | **done** |

### Milestone D ([../MILESTONE_D_PLAN.md](../MILESTONE_D_PLAN.md)) — recovery and progress

See [MILESTONE_D_NOTES.md](MILESTONE_D_NOTES.md). All 13 days done.

| Days | Deliverable | State |
|---|---|---|
| 1–2 | meaningful-progress scoring (6 hard signals, novel-motion guard) | **done** |
| 3–4 | structural loop detection (action / error / diff-thrash) | **done** |
| 5–7 | patience, per-step measurement, multi-step `_execute`, escalation ladder | **done** |
| 8 | task budget (wall-clock / steps / cost; 80% soft, 100% pause) | **done** |
| 9–12 | checkpoints, idempotency, restart reconciliation (RESUME/REPAIR/ESCALATE/NOOP) in `resume()` | **done** |
| 13 | wire-up, checkpoint emission, status + notes | **done** |

180 tests green (`python -m pytest`): 128 unit, 24 integration, 28 security.
Sandbox setup: `docker build -t slice-sandbox:pytest app/services/sandbox/images/pytest-runner`

### Milestone E ([../MILESTONE_E_PLAN.md](../MILESTONE_E_PLAN.md)) — multi-agent coordination

See [MILESTONE_E_NOTES.md](MILESTONE_E_NOTES.md). All 14 days built.

| Days | Deliverable | State |
|---|---|---|
| 1–3 | Critic role + structured messaging | **done** |
| — | Critic reframe (T0-first, can't false-reject) | **done** |
| 4–5 | `AgentMessage` on every inter-role hand-off | **done** |
| 6–8 | Independent T2 ensemble verifier + disagreement protocol | **done** |
| 9–11 | Researcher role + ladder `critic` / `research` rungs made real | **done** |
| 12 | Composition rule + `RolePerformance` shadow tracking | **done** |
| 13–14 | Single-vs-multi benchmark harness | **built; not yet run (needs subscription)** |

219 tests green: ~155 unit, ~36 integration, 28 security.
Multi-agent is opt-in: `Orchestrator(..., critic=Critic(llm))`, `orch.verifier_t2 = VerifierT2(llm)`,
`orch.researcher = Researcher(llm, broker)`. Benchmark to promote the Critic to default:
`python -m tests.benchmark.run_multiagent_bench tests/premise/tasks.real.json`

### Milestone F ([../MILESTONE_F_PLAN.md](../MILESTONE_F_PLAN.md)) — memory and experience

See [MILESTONE_F_NOTES.md](MILESTONE_F_NOTES.md). All 14 days built.

| Days | Deliverable | State |
|---|---|---|
| 1–2 | `memory/store.py` (SQLite, tiers, supersession) + `memory/retrieve.py` (trust-filtered) | **done** |
| 3–4 | `memory/context.py` `build_context()` wired into interpret + plan | **done** |
| 5–6 | `experience/signature.py` + `experience/lifecycle.py` (every §8 gate) | **done** |
| 7–8 | `experience/store.py` capture on COMPLETED → OBSERVED/CANDIDATE; events | **done** |
| 9–10 | shadow-replay gate + guardrail fixture + stub offline eval + `VALIDATED→PROMOTED` | **done** |
| 11–12 | advisory retrieval at PLANNING; `MONITORED→STALE` / `any→QUARANTINED` + rollback hook | **done** |
| 13 | `RolePerformanceStore` persisted to system memory | **done** |
| 14 | regression + notes + status/index | **done** |

254 tests green. Memory + experience are opt-in: `orch.memory = MemoryStore()`,
`orch.experience = ExperienceStore()`; `RolePerformanceStore(memory=orch.memory)` for
cross-run role performance.

## Day 10 handoff

The premise test needs real providers:

```bash
python -m pip install -e ".[llm]"          # anthropic + claude-agent-sdk
export SLICE_LLM_MODEL=<current-model-id>   # consult the claude-api skill
# ensure Anthropic credentials / Agent SDK auth are in the environment
python -m tests.premise.run_real_tasks tests/premise/tasks.example.json
```

Edit `tasks.example.json` to point at 10 small git repos of yours with a known
fix each. The harness writes `SLICE_FINDINGS.md` (state / T0 verdict / wall-clock
/ tokens / unaided-T0 per task) and dumps each diff to `findings_artifacts/<id>/`
for you to score `diff_correct` by hand. Then read the result per
MILESTONE_B_PLAN.md §7.

## Layout

```
app/
  core/state.py                 State, ALLOWED, gate_reason(), transition_ok()
  schemas/contracts.py          all canonical records + validate_contract()
  events/log.py                 EventLog (append-only, stdlib sqlite3), EventKind, Event
  events/projections.py         TaskSnapshot + project_task()
  llm/
    base.py                     LLM protocol + LLMResponse
    parse.py                    tolerant JSON-object extraction
    fake.py                     ScriptedLLM (default for tests/offline)
    anthropic_client.py         AnthropicLLM (lazy import; real runs)
  services/
    workspace/listing.py        list_workspace(), is_git_repo()
    interpret/interpreter.py    request -> TaskContract (1 call)
    plan/planner.py             contract -> Plan (1 call)
    build/
      base.py                   Builder protocol + BuildOutput
      workspace_copy.py         copy_workspace(), diff_workspace(), apply_diff()
      fake.py                   ScriptedBuilder (default for tests/offline)
      agent_sdk.py              AgentSDKBuilder (lazy import; Choice-B executor)
    verify/verifier_t0.py       T0: fresh copy + apply diff + run pytest
    policy/stub.py              AllowAllPolicy (the policy-engine seam)
  orchestration/orchestrator.py run() + resume(), drives the §1 flow
  cli/
    run_task.py                 real-provider CLI
    demo.py                     offline end-to-end demo
tests/
  unit/                         event replay, state gates, contract validation
  integration/                  happy path, failure paths, light recovery
  premise/run_real_tasks.py     Day 10 harness (needs credentials)
```

## Deviations from MILESTONE_B_PLAN.md

- **Event log uses stdlib `sqlite3`, not SQLAlchemy core.** Zero third-party dep beyond
  pydantic for the offline path. `EventLog` is the seam for a later Postgres swap.
- **Working tree is `milestone_b/`**, same package layout, rooted here to stay separate
  from the reference scaffold. Not listed in the package `MANIFEST.json`.
- **Real `AnthropicLLM` / `AgentSDKBuilder` are present but not exercised by the suite** —
  tests run entirely on `ScriptedLLM` / `ScriptedBuilder`. Live behaviour is verified on
  Day 10.

## Named seams (stubs to be replaced in later milestones)

| Seam | File | Filled in |
|---|---|---|
| Model router / local tier | hardcoded provider; `get_llm` | Milestone G / §7 |
| Sandbox tiers | `workspace_copy` temp dir | §14.6, Milestone C day 7–9 (blocked on backend) |
| Policy engine | `services/policy/engine.py` — **real** (7 ordered rules) | hardening in later milestones |
| Capability issuance | `services/capability/` — **real** (registry + scoped grants) | granular per-op proposals in Milestone E |
| Structural taint | `services/taint/` — **real** (boundary + side-effecting check) | first real exercise in Milestone E |
| Egress broker | `services/egress/broker.py` — **real** (allowlist, default deny) | wired to a research step in Milestone E |
| Approvals | `REQUIRE_APPROVAL` fails closed | Milestone C day 10 |
| Progress / loop detection | none | Milestone D / §14.4 |
| Recovery / reconciliation | `resume()` fails cleanly | Milestone D |
| Experience repository | `services/experience/` + `services/memory/` — **real** (memory tiers, trust-filtered retrieval, context builder, full §8 lifecycle, advisory retrieval, catastrophic rollback) | real held-out offline eval in Milestone I; vector retrieval in CD-rag |
| Multi-agent (critic, verifier ensemble) | single builder + deterministic T0 | Milestone E / §9 |
| Verification T1–T3 | T0 only | §5, §14.1 |
