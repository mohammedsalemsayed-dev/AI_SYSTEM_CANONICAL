# Milestone S — Tool Adapter Framework Plan

> **Cross-reference**
> - Role: Build plan for a uniform `ToolAdapter` protocol + registry + capability-mapped dispatch, giving the scattered §10.2 tool packages (git, egress, engines, sandbox, fs) one spine the Planner can enumerate and the orchestrator can dispatch through the §5-C boundary.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §5-C (every tool sits behind the capability boundary), §10.2 ("each capability domain is a tool-adapter package behind the §5-C boundary"), §1 (`ActionProposal` → `PolicyDecision` is the dispatch point), §12 (a tool's output carries its trust); [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md) "still requiring real implementation → tool adapter ecosystem".
> - Downstream: any future adapter (Slack, Jira, a package manager, a formatter) registers once and is enumerable + policy-gated for free.
> - Predecessors: C (capability registry / policy engine — the boundary), J (git adapter), N (engines). Continues the `milestone_b/` tree.

---

## 1. Purpose

The tool packages exist — `GitAdapter` (J), `EgressBroker` (C), the engine adapters (N), the
sandbox runners (C), the workspace lister — but each has its own shape, its own call site,
and no shared registry. The Planner is not told "here are the tools you can use"; the
orchestrator dispatches each by hand. "Tool adapter ecosystem" is on the "still requiring"
list because there is no *ecosystem* — just parts.

Milestone S adds the spine:

- a **`ToolAdapter` protocol** — `name`, `manifest()` (what it does, its ops, the capability
  each op needs, arg schema hints, the trust of its output), `invoke(op, args, ctx)`;
- a **`ToolRegistry`** — register / list / get; `manifest_block()` for the Planner context;
- **capability-mapped dispatch** — `ToolDispatcher.run(op, args, ctx)` turns a tool op into
  an `ActionProposal`, runs it past the **existing** Policy Engine + capability grant, then
  invokes the adapter and tags the result with the manifest trust; a denial is a
  `PolicyDecision`, not an exception;
- **adapters for what exists** — `GitToolAdapter`, `FsToolAdapter` (read/list/write via the
  workspace copy), `EgressToolAdapter`, `EngineToolAdapter` (detect / info — read only) —
  each a thin wrapper, no logic moved;
- **orchestrator wiring** — an opt-in `self.tools` registry; its `manifest_block()` is
  prepended to the Planner listing so plans can name real tools; a `TOOL` event per
  dispatch.

Guiding rules:
- **No new boundary** — dispatch goes through the C policy engine + capability grant that
  already exist. `ToolDispatcher` is a formatter + a call, not a second gate.
- **Thin wrappers** — an adapter *delegates* to the real service. No behaviour moves; every
  existing test stays green.
- **Additive / opt-in** — `self.tools` unset → the orchestrator behaves exactly as after R.
  Adapters are constructed with their real dependency (a `GitAdapter`, a broker, …).
- **Trust from the manifest** — `EgressToolAdapter` output is `retrieved_web`; `FsToolAdapter`
  read is `workspace`; the dispatcher stamps it so §12 holds at the tool layer too.
- **Least privilege** — a tool op declares exactly one capability token; the dispatcher
  requires a matching grant in `ctx`.

## 2. In scope

| Concern | Milestone S implementation |
|---|---|
| Adapter contract | `tools/base.py`: `ToolAdapter` protocol (`name`, `manifest() -> ToolManifest`, `invoke(op, args, ctx) -> ToolResult`). `ToolManifest{name, summary, ops: [ToolOp{op, summary, capability, args_hint, output_trust, side_effecting}]}`. `ToolResult{ok, op, output, trust, error, meta}`. |
| Registry | `tools/registry.py`: `ToolRegistry` — `register(adapter)`, `get(name)`, `all()`, `find(op) -> (adapter, ToolOp) | None`, `manifest_block()` (a compact `TOOLS` context string: `git.status — repo status [vcs.read]`, one line per op). |
| Dispatcher | `tools/dispatch.py`: `ToolDispatcher(registry, policy, risk_globs=)`. `run(qualified_op, args, ctx: DispatchContext) -> ToolResult` — resolve `find(op)`; build an `ActionProposal` (`operation = op.capability`'s primary op, `arguments = args`, `trust`/`taint_sources` from `ctx`); run the **existing** `PolicyEngine` against `ctx.grant`; on a non-`ALLOW` decision return `ToolResult(ok=False, error=<decision>)` + a `POLICY_DECISION`; on `ALLOW` call `adapter.invoke(op, args, ctx)` and stamp `result.trust = op.output_trust`. `DispatchContext{task_id, grant, workspace, trust, taint_sources}`. |
| Git adapter | `tools/adapters/git_tool.py`: wraps a `GitAdapter`. Ops: `git.status` / `git.log` / `git.blame` / `git.diff` / `git.changed_files` (→ `vcs.read`, output `workspace`), `git.branch` / `git.commit` (→ `vcs.branch` / `vcs.commit`, side-effecting). |
| Fs adapter | `tools/adapters/fs_tool.py`: operates on a workspace copy. Ops: `fs.read` (file text, `fs.read`, `workspace`), `fs.list` (`fs.read`), `fs.write` (`fs.write`, side-effecting, path-scoped). |
| Egress adapter | `tools/adapters/egress_tool.py`: wraps an `EgressBroker`. Op: `net.fetch` (→ `net.fetch`, output `retrieved_web`, side-effecting per §14.3). Returns the bytes as text + the source. |
| Engine adapter | `tools/adapters/engine_tool.py`: wraps an `EngineRegistry`. Ops: `engine.detect` / `engine.info` (→ `vcs.read`, output `workspace`, read-only — no toolchain run). |
| Orchestrator wiring | `self.tools = None` opt-in (a `ToolRegistry`). At `INTERPRETING`: prepend `registry.manifest_block()` to the listing the Interpreter + Planner see. `self.tool_dispatch` (a `ToolDispatcher`, auto-built from `self.tools` + `self.policy`) available to future steps; a `_tool(op, args, ctx)` helper logs a `TOOL` event `{op, ok, trust, capability, error}`. This milestone does **not** rewrite `_execute` to route the Builder through the dispatcher — that is a larger change; it ships the framework + the manifest context + the helper, and one integration test drives a dispatch end to end. |
| Events | `TOOL` (op, ok, trust, capability, error). |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Routing the Builder's every file write through the dispatcher | a later refactor — the Builder already goes through policy via `ActionProposal`; unifying the two call paths is its own milestone |
| A tool-call loop / function-calling protocol for the model | later — the Planner names tools in prose now; a structured tool-call schema is additive |
| New external adapters (Slack, Jira, package managers, formatters, a debugger) | each is a `ToolAdapter` subclass — the point of the framework is that they are now cheap |
| Per-tool rate limits / quotas | later — the budget tracker is task-level |
| Tool result caching | later |
| Dynamic tool discovery / plugins from disk | never in the slice (least privilege, §10.3) |

## 4. Component layout

```
app/services/tools/
  base.py       ToolAdapter protocol; ToolManifest / ToolOp / ToolResult / DispatchContext
  registry.py   ToolRegistry — register/get/all/find/manifest_block
  dispatch.py   ToolDispatcher — ActionProposal -> PolicyEngine -> invoke -> trust-stamp
  adapters/
    git_tool.py  fs_tool.py  egress_tool.py  engine_tool.py
app/events/log.py                    + TOOL
app/orchestration/orchestrator.py    opt-in self.tools; manifest context at INTERPRETING;
                                     self.tool_dispatch + _tool() helper
tests/
  unit/         test_tool_registry, test_tool_dispatch, test_tool_adapters
  integration/  test_tool_manifest_at_planning, test_dispatch_through_policy
```

## 5. Work breakdown (~10 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `tools/base.py` (protocol + value types) + `tools/registry.py`. Unit: register/get/all; `find("git.status")` resolves; `manifest_block()` lists every op once with its capability. |
| 3–4 | `tools/dispatch.py` — build the `ActionProposal`, call the existing `PolicyEngine`, invoke, trust-stamp. Unit: an op with a matching grant + benign args → `ok`, `trust` = the manifest's; a missing grant → `ok=False` with the `PolicyDecision`, no exception; a tainted arg on a side-effecting op → DENY (reuses the C rule). |
| 5 | `git_tool.py` — wrap `GitAdapter`; read ops + gated write ops. Unit over a temp repo: `git.status` returns a dict, `git.commit` denied without a `vcs.write` grant. |
| 6 | `fs_tool.py` (workspace-copy read/list/write, path-scoped) + `egress_tool.py` (wrap the broker, `net.fetch` → `retrieved_web`). Unit: `fs.read` of a seeded file; `fs.write` outside scope → DENY; `net.fetch` off-allowlist → the broker's `EgressDenied` surfaced as `ToolResult(ok=False)`. |
| 7 | `engine_tool.py` (detect/info, read-only). Unit over a Godot fixture. |
| 8 | Orchestrator wiring — `self.tools` opt-in; `manifest_block()` prepended at `INTERPRETING`; `self.tool_dispatch` auto-built; `_tool()` helper + `TOOL` event. Integration: a Godot-fixture task's Planner prompt contains a `TOOLS` block naming `git.status` / `engine.info`. |
| 9 | Integration — `_tool("git.status", {}, ctx)` through a wired orchestrator logs a `TOOL` event with `trust="workspace"`; `_tool("git.commit", …, ctx-without-vcs.write)` logs a `TOOL` event `ok=False` and a `POLICY_DECISION`, task unaffected. `self.tools` unset → planning context byte-identical to Milestone R. |
| 10 | Regression; `milestone_b/MILESTONE_S_NOTES.md`; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the top-level [README.md](README.md); rehash `MANIFEST.json`; commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — `ToolRegistry` register/get/all/find works and `manifest_block()` names every
  op with its capability once; `ToolDispatcher.run` returns `ok` with the manifest's
  `output_trust` on an allowed op, `ok=False` + the `PolicyDecision` on a denied one (no
  exception), and DENIES a tainted arg on a side-effecting op; each adapter's read ops
  return the expected shape and its write ops are refused without the matching grant.
- **Integration** — with `orch.tools` wired, the Planner prompt contains a `TOOLS` block;
  `_tool("git.status", …)` logs a `TOOL` event (`ok`, `trust="workspace"`);
  `_tool("git.commit", …)` without a `vcs.write` grant logs `TOOL` `ok=False` + a
  `POLICY_DECISION` and the task still `COMPLETED`s its real work. `orch.tools` unset →
  planning context and events are byte-identical to Milestone R.
- **Failure** — an unknown op → `ToolResult(ok=False, error="unknown tool op")`, not an
  exception; an adapter that raises inside `invoke` → `ToolResult(ok=False, error=repr)`, the
  dispatcher does not propagate.
- **Security (§5-C / §12)** — every dispatch goes through the **existing** `PolicyEngine` +
  capability grant (the dispatcher adds no bypass); `EgressToolAdapter` output is stamped
  `retrieved_web` and a `net.fetch` with a tainted arg is DENIED; a `fs.write` outside the
  workspace scope is DENIED; no adapter is loaded from disk / discovered dynamically.
- **Recovery** — `reconcile()` + `resume()` unaffected; the registry holds no task state.
- **Benchmark** — n/a.

## 7. Tunable starting values

- `manifest_block()` cap: **40** ops (well above the ~14 shipped).
- `fs_tool` read cap: **256 KiB**/file (larger → truncated + a flag in `meta`).
- Qualified op format: `"<adapter>.<verb>"` (e.g. `git.status`, `fs.read`).
- `DispatchContext.trust` defaults to `"workspace"`; a research/KB step passes
  `retrieved_web` / `doc_input` so the taint rule can see it.

## 8. Risks

- **Two paths to a side effect** — the Builder still writes files via its own
  `ActionProposal` path; the dispatcher is a *parallel* path for explicit tool ops. Until a
  later refactor unifies them, a reviewer must know both exist. Mitigated: both go through
  the *same* `PolicyEngine`, so the security property holds; only the plumbing is doubled.
- **Manifest drift** — an adapter whose `manifest()` lies about its capability could
  under-declare. Mitigated: the dispatcher builds the `ActionProposal.operation` from the
  declared capability, so an under-declared op simply gets a *weaker* grant check and is more
  likely to be denied, not less — fail-safe.
- **Prose tool naming** — the Planner names tools in text, not a schema, so a typo yields "no
  such op" rather than a wrong call. Acceptable for the slice; a structured tool-call
  protocol is the additive next step.
- **Scope creep into a plugin system** — explicitly out (§10.3 least privilege): adapters are
  registered in code with their real dependency, never discovered.

## 9. Deliverables

- `app/services/tools/` — `base.py`, `registry.py`, `dispatch.py`, `adapters/` (git / fs /
  egress / engine).
- `TOOL` event kind.
- Orchestrator: opt-in `ToolRegistry`; manifest context at `INTERPRETING`; `tool_dispatch` +
  `_tool()` helper.
- Test suite: the current 435 green, plus unit (registry / dispatch / adapters) and
  integration (manifest at planning / dispatch through policy).
- `milestone_b/MILESTONE_S_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the
  top-level [README.md](README.md) updated: "tool adapter ecosystem" moves off the "still
  requiring real implementation" list to FOUNDATION.
