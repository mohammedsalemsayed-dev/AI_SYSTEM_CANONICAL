# Implementation Status — Honest Boundary

> **Cross-reference**
> - Role: Honest built-vs-active boundary for the code foundation.
> - Authority: Status record; mirrors the `status` column of the connective index.
> - Upstream (consumes): [REQUIREMENT_TRACEABILITY.md](REQUIREMENT_TRACEABILITY.md).
> - Downstream (depended on by): coding-agent milestone selection.
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../DESIGN_TIGHTENING.md) — §10 build order and dependency graph.

The authoritative documents describe the complete target system.

The code foundation included in this package is intentionally marked as a foundation. It is NOT a claim that the complete target system is already implemented.

Implemented/scaffolded concepts:
- state-machine foundation;
- TaskContract / ActionProposal / AgentMessage foundations;
- workspace path guard;
- basic meaningful-progress detector;
- experience state lifecycle;
- basic hardware mode policy;
- simple route scoring foundation;
- recovery reconciliation skeleton;
- orchestrator skeleton;
- basic FastAPI health endpoints;
- basic futuristic React UI;
- initial invariant tests.

Still requiring real implementation:
- persistent PostgreSQL models/migrations;
- durable event log and projections;
- Redis/queue strategy where justified;
- real local/cloud provider adapters;
- empirical benchmark harness and registry;
- capability issuance/expiry and policy engine;
- approvals and authentication/authorization;
- secrets management;
- hardened OS/container sandbox execution;
- real artifact/version tracking;
- checkpoints and crash recovery integration;
- structured multi-agent runtime;
- research/retrieval/source evaluation;
- repository intelligence and Git adapter;
- tool adapter ecosystem;
- RAG/indexing;
- document/presentation pipelines;
- full telemetry and target-machine calibration;
- WebSocket/event streaming;
- complete desktop shell integration;
- comprehensive test gates and fault injection.

A coding agent must not "simplify away" these items because they are absent from the initial scaffold.

## Milestone B slice — `milestone_b/` (Days 1–9 built; Day 10 pending)

A running vertical slice: `request -> TaskContract -> Plan -> edit (driven builder) ->
T0 verify -> result`, over an append-only SQLite event log with snapshot projections.
47 tests green (35 unit, 12 integration). Offline demo: `python -m app.cli.demo`.

Now real (slice scope only — see `milestone_b/README.md` for the named seams that remain
stubbed):
- append-only event log + deterministic replay/projections;
- state machine **with transition-gate predicates** (DESIGN_TIGHTENING §1);
- Interpreter (request -> contract) with the "no verifiable T0 -> WAITING_FOR_USER" rule;
- `task_class` taxonomy applied at interpretation;
- Planner (contract -> plan);
- Builder seam — `ScriptedBuilder` (tests) and `AgentSDKBuilder` (Choice-B executor);
- Verifier **T0 tier** — fresh checkout, apply diff, run the named pytest target;
- policy-decision + capability-grant **seam** (stub: allow + log);
- workspace-copy isolation (temp dir; not a hardened sandbox);
- `resume()` light recovery (interrupted task fails cleanly, workspace untouched).

Day 10 (premise test) — **done, premise holds**. Real loop = Agent SDK for
Interpreter/Planner/Builder on a Claude Pro subscription + VerifierT0 in the Docker Tier-A
sandbox. Two runs: 10 seeded single-function bugs (10/10 correct) and 5 real `more-itertools`
bug-fix commits (4/5 correct; the 1 miss was a behaviourally-right fix with the wrong exact
assert message, **caught by T0**, never marked COMPLETED). Combined **14/15 diffs correct,
zero false positives, 15/15 unaided T0 criterion**. Per MILESTONE_B_PLAN.md §7 the premise
holds. Surfaced weakness: the Builder doesn't reliably read the failing test before editing
(§14.1 prompt-tuning, not a blocker). See `milestone_b/SLICE_FINDINGS.md`.

## Milestone C — security and authority (`milestone_b/`, days 1–15; sandbox runtime pending)

132 tests green + 1 skipped. See `milestone_b/MILESTONE_C_NOTES.md`.

Now real (slice scope):
- capability registry + per-step scoped `CapabilityGrant` issuance (frozen from the Plan);
- deterministic Policy Engine (7 ordered rules) replacing the allow-all stub;
- structural taint (single tagging site + single side-effecting check);
- egress broker (per-task allowlist, default deny, tagged results);
- approval flow — `REQUIRE_APPROVAL` -> `WAITING_FOR_USER` -> `resume(approval=...)`;
- secret isolation — `SecretStore` + `scrub_env`, both sandbox backends scrub;
- audit event kinds + projection fields;
- Security gate — 26-case injection/abuse corpus + path-traversal battery + end-to-end
  objective-preservation.

Pending: the Tier-A sandbox is coded (`DockerSandbox`, arg-verified) but has not run a real
container — needs Docker Desktop installed, `slice-sandbox:pytest` built, and the
`--selftest` passing. Until then a dev-only non-isolating subprocess fallback is used and
refuses runs marked `allow_non_isolated=False`.

## Milestone D — recovery and progress (`milestone_b/`, days 1–13)

180 tests green. See `milestone_b/MILESTONE_D_NOTES.md`.

Now real (slice scope):
- deterministic meaningful-progress scoring (six hard signals; novel-motion guard);
- structural loop detection (repeated action / error / diff-thrash; progress clears history);
- per-task_class patience;
- the escalation ladder (inspect / change_strategy / ask_user real; critic / research /
  stronger_model stubbed to E and G);
- multi-step `_execute` with per-step T0 measurement and ladder hand-off;
- task budget (`wall_clock_s` / `steps` / cost) with 80% soft event and 100% pause;
- checkpoints, idempotency-key tracking;
- restart reconciliation — `reconcile()` → RESUME / REPAIR / ESCALATE / NOOP, wired into
  `resume()` (replaces the old "interrupted → FAIL"); RESUME steers the state machine back to
  EXECUTING and re-runs, workspace untouched.

Stubbed: ladder rungs critic/research/stronger_model; coverage/lint/type-error signals
(defined, unpopulated); REPAIR escalates rather than auto-re-interpreting; cost dimension
unmetered on the subscription path.

## Milestone E — multi-agent coordination (`milestone_b/`, days 1–14)

219 tests green. See `milestone_b/MILESTONE_E_NOTES.md`.

Now real (slice scope):
- **Critic** — one-shot pass, fresh context (contract + diff + target test, not the build
  narrative). T0 runs first; the Critic can never turn a T0-passing diff into a failure
  (a `reject` there is a logged `DISAGREEMENT`); a `reject` on a T0-fail drives one bounded
  retry with findings. Opt-in until the benchmark promotes it.
- **Structured `AgentMessage`** on every inter-role hand-off.
- **Independent T2 ensemble verifier** — model reconstructed-spec check from contract + diff
  alone, N contexts; advisory (T0 authoritative); escalates a T0-pass/T2-fail only when
  `risk_level ≥ medium` or a risky path.
- **Disagreement protocol** — name claims → discriminating test (T0) → synthesise → escalate
  if consequential.
- **Researcher** — query plan → egress-broker fetch (default deny) → claims + `EvidenceRecord`s
  at `retrieved_web` trust; wired to the D ladder `research` rung (fills that stub); the
  `critic` ladder rung is also real now.
- **Composition rule** + in-memory **RolePerformance** shadow tracking; `COMPOSITION` event.
- **Single-vs-multi benchmark** harness (`tests/benchmark/run_multiagent_bench.py`) — not yet
  run; needs the subscription; the Critic promote-to-default decision is gated on it.

Deferred: dedicated `research_web` orchestration (CD-research); real live egress fetch;
persistent RolePerformance (Milestone F); stronger-model ladder rung (Milestone G).
