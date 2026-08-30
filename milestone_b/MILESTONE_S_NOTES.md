# Milestone S notes — what is real, what remains

Status against [../MILESTONE_S_PLAN.md](../MILESTONE_S_PLAN.md). **445 tests green.**
All 10 days built. Removes "tool adapter ecosystem" from the
`IMPLEMENTATION_STATUS.md` "still requiring real implementation" list.

## Real after Milestone S

| Area | Module | Notes |
|---|---|---|
| Contract | `app/services/tools/base.py` | `ToolOp{op, summary, capability, args_hint, output_trust, side_effecting}`, `ToolManifest{name, summary, ops}`, `ToolResult{ok, op, output, trust, error, meta}`, `DispatchContext{task_id, grant, workspace, trust, taint_sources}`, and a `runtime_checkable` `ToolAdapter` Protocol (`name`, `manifest()`, `invoke(op, args, ctx)`). |
| Registry | `app/services/tools/registry.py::ToolRegistry` | `register` (chainable) / `get` / `all` / `find(qualified_op) -> (adapter, ToolOp) | None` (splits on the first `.`). `manifest_block()` emits one `- <op> — <summary> [<cap>]( (side-effecting))?` line per op, header `TOOLS — available operations …`, capped at `MANIFEST_OP_CAP = 40`. |
| Dispatcher | `app/services/tools/dispatch.py::ToolDispatcher` | `run(qualified_op, args, ctx) -> (ToolResult, PolicyDecision | None)`. Builds an `ActionProposal` (`operation = primary_operation(op.capability)`, `required_capability = op.capability`, `workspace_scope` from the grant, `trust`/`taint_sources` from the ctx) and calls the **existing** `PolicyEngine.decide(proposal, _MIN_CONTRACT, ctx.grant)` — it adds **no new gate**. `find` miss → `ToolResult(ok=False, error="unknown tool op"), None`. Non-ALLOW → `ToolResult(ok=False, error="policy <D> [<rule>]: <reason>"), decision`. An adapter that raises inside `invoke` → `ToolResult(ok=False, error=repr(exc)), decision`. On ALLOW the result's `trust` is stamped from `op.output_trust` (never laundered to `workspace`). |
| Git adapter | `app/services/tools/adapters/git_tool.py::GitToolAdapter` | Wraps `GitAdapter`. `git.status` / `git.log` / `git.blame` / `git.diff` / `git.changed_files` need `vcs.read`; `git.branch` needs `vcs.branch`, `git.commit` needs `vcs.commit` (both `side_effecting`). No fetch/pull/push/remote op exists — local VCS only. Backend errors (`GitError`/`KeyError`/`ValueError`/`TypeError`) → `ToolResult(ok=False)`. |
| FS adapter | `app/services/tools/adapters/fs_tool.py::FsToolAdapter` | `fs.read` / `fs.list` need `fs.read`; `fs.write` needs `fs.write` (`side_effecting`). `_resolve()` does `(root / rel).resolve()` then `relative_to(root)` — a path escaping the workspace → `ToolResult(ok=False)`, never a traversal. Reads truncate at `READ_CAP_BYTES = 256 KiB` (`meta.truncated`). `fs.list` skips `.git`. |
| Egress adapter | `app/services/tools/adapters/egress_tool.py::EgressToolAdapter` | `net.fetch` needs `net.fetch`, `output_trust="retrieved_web"`, `side_effecting`. Wraps `EgressBroker.fetch`; `EgressDenied`/`EgressError` → `ToolResult(ok=False, trust="retrieved_web")`. Text capped at 8 000 chars. The policy layer's `egress-not-allowed` rule blocks an off-allowlist host **before** the broker; the broker's own allowlist is the second line. |
| ~~Engine adapter~~ | ~~`engine_tool.py::EngineToolAdapter`~~ | **REMOVED 2026-08-30** with the rest of the engine-adapter layer. |
| Orchestrator wiring | `orchestrator.tools` / `_tool()` | `self.tools = None` opt-in (`ToolRegistry`). At `INTERPRETING`, when set, `registry.manifest_block()` is prepended to the listing the Interpreter + Planner see. `_tool(op, args, ctx)` lazily builds one `ToolDispatcher(self.tools, self.policy)`, dispatches, logs a `POLICY_DECISION` event on a non-ALLOW decision, then always logs a `TOOL` event `{op, ok, trust, error[:200], meta}`, and returns the `ToolResult`. **This milestone does not reroute `_execute` / the Builder through the dispatcher** — it ships the framework, the manifest context, and the helper. |
| Events | `+ TOOL` (`op`, `ok`, `trust`, `error`, `meta`). |

## Scope / security posture

- The dispatcher is **behind the §5-C boundary**: it reuses `PolicyEngine.decide` and the
  caller's `CapabilityGrant` verbatim. It introduces no capability, no bypass, and no new
  approval path — a denied op is an ordinary `PolicyDecision`, surfaced as `ToolResult(ok=False)`.
- **Trust is preserved, never laundered.** `net.fetch` output stays `retrieved_web`; a
  side-effecting op invoked with `trust="retrieved_web"` + taint sources is denied by the
  existing `tainted-side-effect` rule (unit-tested here). §12's hard rule holds: retrieved
  content cannot originate a side effect through a tool.
- FS ops are workspace-scoped by `relative_to` containment; git ops have no network surface;
  egress ops are default-deny at two layers.
- `self.tools` unset ⇒ planning context and the event stream are byte-identical to
  Milestone R (integration-tested).

## Not yet real / deferred

- **Builder routed through the dispatcher** — `_execute` still calls the Builder directly.
  Routing every file edit through `fs.write` (and every repo read through `git.*`) so the
  policy engine sees each one is the natural follow-up; the seam is now in place.
- **A real tool ecosystem** — only git / fs / egress adapters ship (plus a shell tool and a
  generic MCP client; the `engine` adapter was removed 2026-08-30). HTTP-API tools,
  a shell/exec tool, language-server / linter / formatter tools, cloud SDK tools, etc. are
  each an additive `ToolAdapter` — no framework change.
- **LLM-driven tool selection** — the manifest is injected into the planning context, but no
  agent yet *chooses* an op from it and calls `_tool`. That needs a prompt/parse contract
  (op + JSON args) and a loop, which is agent work, not framework work.
- **Per-op argument schemas / validation** — `args_hint` is a human string; a real JSON
  Schema per op (with `strict` validation before dispatch) is a later hardening.
- **Streaming / long-running tool ops** — `invoke` is synchronous and returns one
  `ToolResult`; a progress-yielding variant is a desktop-shell concern.

## Deferred past S (unchanged)

Milestone A hardening (Postgres models + migrations / Redis + queue strategy); a real local
model adapter; the complete desktop shell / native Tauri build; the live-harness runs.
These need external infrastructure or a running toolchain not available in this environment.
