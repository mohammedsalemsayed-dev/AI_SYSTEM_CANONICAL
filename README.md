# Autonomous Hardware-Aware Multi-Agent AI System

Design package + working implementation foundation for a modular-monolith desktop AI
workstation: specialized agents reason and challenge each other while deterministic services
own state, permissions, execution boundaries, verification, recovery, memory trust,
controlled learning, hardware protection, and model routing.

- **Start here:** [`00_START_HERE/README_FOR_CLAUDE_CODE.md`](00_START_HERE/README_FOR_CLAUDE_CODE.md) (read order + authority rules)
- **Architecture wiring:** [`DESIGN_TIGHTENING.md`](DESIGN_TIGHTENING.md) (16 sections; §13 is the document map)
- **Requirement → milestone → status:** [`02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md`](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md)
- **Honest built-vs-active boundary:** [`02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md`](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md)
- **Running code:** [`milestone_b/`](milestone_b/README.md) — the live build (see its README for per-milestone detail and run instructions)

> The authoritative documents describe the **complete** target system. The code is a
> foundation built through integrated vertical slices — every deferred subsystem is present
> as a **named seam** (interface + stub), never silently dropped. "Foundation" ≠ "complete."

## Milestone status

Build order and dependencies: [`DESIGN_TIGHTENING.md`](DESIGN_TIGHTENING.md) §10.

| Milestone | Scope | Status |
|---|---|---|
| **A** Foundation | state machine, event log, contracts | scaffolded (prior foundation) |
| **B** Vertical slice | `request → contract → plan → edit → T0 verify → result` on one task class | **built** — driven Builder (Claude Agent SDK), event-sourced core, Docker T0 sandbox |
| **C** Security & authority | capability registry, scoped grants, 7-rule policy engine, sandbox tiers, approvals | **built** |
| **D** Recovery & progress | checkpoints, idempotency, reconciliation, 6 hard-progress signals, loop detector, escalation ladder | **built** |
| **E** Multi-agent | Critic (T0-first, can't false-reject), independent T2 ensemble verifier, disagreement protocol, Researcher, composition rule, RolePerformance | **built** |
| **F** Memory & experience | hierarchical memory (working/project/experience/system), trust-filtered retrieval, context builder, full `OBSERVED→…→STALE/QUARANTINED` lifecycle, advisory retrieval at planning, catastrophic rollback | **built** |
| **G** Routing & hardware | provider registry, static §7.1 table + escalation triggers, `RouteStatsStore` + ≥20-run eligibility + data-driven blend, hardware modes + `EMERGENCY` pause, real `stronger_model` ladder rung | **built** |
| **I** Optimization | frozen guardrail suite, fail-closed regression gate, held-out `OfflineEval` gating promotion, experience & routing canary rollback, `rebuild_metrics` (§11.2) | **built** |
| **H** Desktop shell | 6 §11.2 read-model folds, loopback HTTP/JSON API, SSE event stream, wired no-build frontend, opt-in gated task submit | **built** |
| **H** Tauri packaging | Tauri v2 native shell (Rust sidecar supervision) + PyInstaller `nexus-server` sidecar + one-command build | **scaffolded** — not `cargo build`-verified here; needs a Rust + PyInstaller build host |

**314 tests** green (`milestone_b/`, offline-deterministic; one runtime dependency: `pydantic`).

### Needs an external resource (built, not run here)

| Harness | Command | Needs |
|---|---|---|
| Premise test | `python -m tests.premise.run_real_tasks …` | Claude Pro subscription (`claude` CLI login) |
| Single-vs-multi benchmark | `python -m tests.benchmark.run_multiagent_bench …` | subscription — gates the Critic promote-to-default decision |
| Model eligibility seeder | `python -m tests.benchmark.seed_model …` | subscription |
| Guardrail regression runner | `python -m tests.regression.run_guardrail` (`--offline` works now) | subscription for the real-model run |
| Native installers | `python desktop/build.py` | Rust toolchain + PyInstaller + platform build tools (+ signing certs) |

## Quick start (the running slice)

```bash
cd milestone_b
python -m pytest tests/unit tests/security tests/integration tests/regression   # 314 green
python -m app.cli.demo                                                          # offline end-to-end
python -m app.ui.run_ui --db slice.db --port 8770                               # desktop shell -> http://127.0.0.1:8770
```

## Non-negotiable rules

- The Complete Claude-Code Spec is the primary authoritative source; summaries never replace it.
- Do not silently drop a requirement because it is not yet implemented.
- Do not confuse "planned" or "foundation" with "complete."
- Do not bypass security or verification for convenience.
