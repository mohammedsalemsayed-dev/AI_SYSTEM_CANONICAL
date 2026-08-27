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

Day 10 (10 real tasks + `SLICE_FINDINGS.md`) needs Anthropic credentials / Agent SDK auth
and is not yet run.
