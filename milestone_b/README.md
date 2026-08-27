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
| 10 | 10 real tasks + `SLICE_FINDINGS.md` | **blocked — needs your credentials** |

### Milestone C ([../MILESTONE_C_PLAN.md](../MILESTONE_C_PLAN.md)) — security and authority

See [MILESTONE_C_NOTES.md](MILESTONE_C_NOTES.md) for what is real vs. pending.

| Plan day | Deliverable | State |
|---|---|---|
| 1–2 | Capability registry + issuance + grant scope math; `CAPABILITY_GRANT` logged | **done** |
| 3–4 | Policy Engine (7 ordered rules) replaces `AllowAllPolicy` | **done** |
| 5 | Structural taint boundary + side-effecting check | **done** |
| 6 | Egress broker (per-task allowlist, default deny) | **done** |
| 7–9 | Tier-A sandbox: `SandboxRunner`, `DockerSandbox` (arg-verified), fallback, verifier wired | **code done; container not yet run — install Docker Desktop, then `docker build` + `--selftest`** |
| 10 | Approval flow: `REQUIRE_APPROVAL` → `WAITING_FOR_USER` → `resume(approval=…)` | **done** |
| 11 | Secret isolation: `SecretStore` + `scrub_env`, both backends scrub | **done** |
| 12 | Audit: new event kinds + projection fields | **done** |
| 13–14 | Security gate: 26-case injection corpus + traversal battery + objective-preservation | **done (1 test skipped — needs Docker)** |
| 15 | Wire-up, status update, notes | **done** |

132 tests green + 1 skipped (`python -m pytest`): 87 unit, 18 integration, 27 security.

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
| Experience repository | none | Milestone F / §14.7 |
| Multi-agent (critic, verifier ensemble) | single builder + deterministic T0 | Milestone E / §9 |
| Verification T1–T3 | T0 only | §5, §14.1 |
