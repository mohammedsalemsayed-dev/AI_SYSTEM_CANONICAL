# Milestone T notes — what is real, what remains

Status against [../MILESTONE_T_PLAN.md](../MILESTONE_T_PLAN.md). **458 tests green.**
All 10 days built. Resolves Milestone S's top deferral ("LLM-driven op selection from the
manifest — needs a prompt/parse contract and a loop") and makes `ops` a first-class
deliverable flow.

## Real after Milestone T

| Area | Module | Notes |
|---|---|---|
| Shell adapter | `app/services/tools/adapters/shell_tool.py::ShellToolAdapter` | Op `shell.exec` → capability `shell.run` (token already existed, in `SIDE_EFFECTING_OPS`, "sandboxed only"), `output_trust="tool_output"`, `side_effecting=True`. Delegates to the existing `SandboxRunner` seam (`SubprocessSandbox` default). `invoke` rejects a non-list / empty / non-string command → `ToolResult(ok=False)`; clamps `timeout_s` to ≤ 120 s (default 30); caps stdout/stderr at 8 KiB each; a non-zero exit or a `timed_out` result is `ok=False`; `(SandboxRefused, SandboxUnavailable, OSError, ValueError)` → `ToolResult(ok=False, trust="tool_output")`. |
| Tool-use loop | `app/services/tools/loop.py::ToolLoop` | `run(objective, ctx, manifest_block) -> ToolLoopResult{ok, done, iterations, summary, transcript, denials, decisions}`. Each turn: prompt the LLM with the objective + the manifest + the rendered transcript; parse ONE JSON object via `app.llm.parse.parse_json_object` — `{"op","args"}` → dispatch through the **Milestone S `ToolDispatcher`** (= the existing Policy Engine + the caller's grant); `{"done":true,"summary"}` → stop `ok=True`. Three stop conditions: `done`, `max_iters` (default 6) → `ok=False, summary="iteration cap"`, and a `parse_budget` (default 2) of unparseable / op-less replies → `ok=False`. A policy-denied op is a `result` turn `ok=False` with `denials`/`decisions` incremented — **the loop keeps going**. Holds no state between calls; takes no wall-clock or random input, so the same script + workspace ⇒ a byte-identical transcript (unit-asserted). |
| Transcript turn | — | `{kind: "call"|"result"|"error"|"done", op?, args?, ok?, trust?, output_excerpt?(≤600), error?(≤600)}`. |
| Orchestrator flow | `orchestrator._run_tool_task` | `self.tool_loop = None` opt-in — a `ToolLoop` **or** a zero-arg factory (so the dispatcher can be built lazily from `self.tools` + `self.policy`). `_drive`: `task_class == "ops" and self.tool_loop is not None` → `_run_tool_task`. PLANNING → EXECUTING (1 synthetic step) → runs the loop **on a workspace copy** (`copy_workspace` / `cleanup` — a side-effecting op never touches the user's tree) → logs `POLICY_DECISION` per denial + `TOOL` per dispatched op + one `TOOL_LOOP` summary + an `OBSERVATION` + a `tool_output`-trust transcript artifact → VERIFYING → COMPLETED with a `T0` pass `VerificationRecord` (criterion: "loop finished in N iterations within the cap, all K ops dispatched through the Policy Engine, D denial(s) surfaced"). Loop `ok=False` → EXECUTING → **FAILED** cleanly (no exception escapes), transcript still stored. |
| Grant | `orchestrator._tool_task_grant` | One `CapabilityGrant` (`token="tool.loop"`, `scope_path` = the workspace copy) whose `operations` = the union of every **non-side-effecting** registered op's capability, plus any token named in the optional `self.tool_task_capabilities` list (e.g. `"shell.run"`). Least privilege: a side-effecting op the caller did not opt into is simply never authorised, so the dispatcher denies it and the loop records the denial. Logged as `CAPABILITY_GRANT`. |
| Events | `+ TOOL_LOOP` (objective, iterations, ok, done, denials, summary, turns). Per-op `TOOL` + per-denial `POLICY_DECISION` reuse the existing kinds. |

## Scope / security posture

- **No new boundary.** Every op the loop runs goes through S's `ToolDispatcher` → the C
  `PolicyEngine` + the caller's `CapabilityGrant`. The loop adds no gate; a denial is a
  transcript turn and a logged `POLICY_DECISION`, never an exception.
- **§12 holds at the loop layer.** `ctx.trust` / `ctx.taint_sources` flow into every
  proposal, so a loop whose context is `retrieved_web` + tainted is DENIED any
  `side_effecting` op by the existing `tainted-side-effect` rule (unit-tested).
  `shell.exec` output is stamped `tool_output`; the transcript artifact is `tool_output`,
  never laundered to `workspace`.
- **Workspace-untouched.** The loop operates on `copy_workspace(...)`; the integration
  denial test asserts the real tree is byte-unchanged after the run.
- **Bounded.** `max_iters` + `parse_budget` + the task-level budget tracker (unchanged). No
  retry-in-a-sleep, no time input.
- `self.tool_loop` unset → an `ops` task flows through the ordinary plan→build path exactly
  as after Milestone S (integration-tested).

## Not yet real / deferred

- **The Builder (`code_edit_*`) is not routed through the loop** — it keeps its own measured
  plan/step/progress machinery (§14.4). Folding code edits into the tool loop is a separate,
  larger milestone.
- **One op per turn** — no parallel / batched tool calls. Keeps the transcript and the
  policy trail linear and auditable.
- **JSON-object turns, not native tool-use blocks** — swapping in Anthropic tool-use is an
  `llm`-adapter change behind the same loop.
- **No per-op retry / self-repair heuristics** — the loop surfaces a denial or failure as a
  turn; what to do about it is the model's job within `max_iters`.
- **`shell.exec` real isolation** — the fallback sandbox is not isolation; the Docker backend
  is the real one and is already the wired default where available. `shell.run` stays a
  distinct, explicitly-granted token.
- **Streaming a long-running `shell.exec`** — `invoke` returns one `ToolResult`.
- **New adapters beyond `shell`** — each is still a `ToolAdapter`; cheap, not this milestone.

## Deferred past T (unchanged)

Milestone A hardening (Postgres models + migrations / Redis + queue strategy); a real local
model backend; secrets management; the native Tauri build; the subscription-gated live
harness runs.
