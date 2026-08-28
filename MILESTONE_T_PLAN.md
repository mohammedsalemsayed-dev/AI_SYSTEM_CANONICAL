# Milestone T — Tool-Use Execution Plan

> **Cross-reference**
> - Role: Build plan for a bounded, deterministic **tool-use loop** on top of the Milestone S dispatch spine — a model that is shown the tool manifest, emits one `{op, args}` per turn, and has each call run through the existing §5-C boundary — plus a `ShellToolAdapter` so the loop has a real side-effecting op to exercise.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [MILESTONE_S_PLAN.md](MILESTONE_S_PLAN.md) (the `ToolAdapter` / `ToolRegistry` / `ToolDispatcher` spine + `_tool()` helper), [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §5-C (tools behind the capability boundary), §1 (`ActionProposal` → `PolicyDecision` per action), §12 (a tool output carries its trust; retrieved/doc content can never originate a side effect), §14.4 (bounded loops / meaningful-progress); [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md) — S's deferred "LLM-driven tool selection" + "a real tool ecosystem".
> - Downstream: the `ops` task class becomes a first-class deliverable flow; any future agent role can drive tools through the same loop.
> - Predecessors: C (policy engine / capability grant / sandbox), S (dispatch spine). Continues the `milestone_b/` tree.

---

## 1. Purpose

Milestone S wired the tool framework but left it **inert**: `manifest_block()` is injected
into the planning context, `_tool()` can dispatch, but nothing *chooses* an op and calls it.
S's own notes name this the top deferred item ("LLM-driven op selection from the manifest —
needs a prompt/parse contract and a loop") and "a real tool ecosystem" (only read-mostly
adapters shipped).

Milestone T closes both, minimally:

- a **`ShellToolAdapter`** — op `shell.exec`, capability `shell.run` (the token already
  exists, `SIDE_EFFECTING_OPS`, "sandboxed only"), runs through the existing `SandboxRunner`
  seam, output trust `tool_output`;
- a **`ToolLoop`** — `run(objective, ctx, manifest_block) -> ToolLoopResult`. Each turn:
  prompt the model with the objective + the manifest + the transcript so far; parse one JSON
  object — `{"op": "...", "args": {...}}` **or** `{"done": true, "summary": "..."}`; dispatch
  the op through `ToolDispatcher`; append the result to the transcript. Stop on `done`, on
  `max_iters`, or on two consecutive unparseable replies. No wall-clock, no randomness — the
  transcript is a pure function of the scripted replies + the workspace;
- **orchestrator wiring** — `self.tool_loop = None` opt-in. An `ops` task with the loop wired
  runs `_run_tool_task` (PLANNING → EXECUTING → VERIFYING → COMPLETED, one synthetic step, a
  `T0` pass `VerificationRecord` describing the completion check) instead of
  plan→build→verify. A `TOOL_LOOP` summary event; one `TOOL` event per dispatched op (via
  the existing `_tool` path).

Guiding rules:
- **No new boundary.** Every op the loop runs goes through S's `ToolDispatcher` → the C
  `PolicyEngine` + the caller's `CapabilityGrant`. The loop adds no gate; a denial is a
  transcript turn, not an exception.
- **Bounded and deterministic.** `max_iters` hard cap (default 6); a parse-failure budget
  (2); no time or random input. Same replies + same workspace ⇒ byte-identical transcript.
- **Additive / opt-in.** `self.tool_loop` unset ⇒ an `ops` task behaves exactly as after S
  (falls through to the normal pipeline). No existing test changes.
- **Trust in, trust out.** `ctx.trust` / `ctx.taint_sources` flow into every proposal, so a
  loop seeded from `retrieved_web` input cannot run a side-effecting op — the existing
  `tainted-side-effect` rule fires inside the dispatcher.
- **Least privilege.** The loop is handed one `DispatchContext` with one `CapabilityGrant`;
  it can call only ops that grant authorises. `shell.exec` needs an explicit `shell.run`
  grant or every call is denied.

## 2. In scope

| Concern | Milestone T implementation |
|---|---|
| Shell adapter | `tools/adapters/shell_tool.py`: `ShellToolAdapter(runner: SandboxRunner | None)` (defaults to `SubprocessSandbox`). Op `shell.exec` → capability `shell.run`, `output_trust="tool_output"`, `side_effecting=True`. `invoke("shell.exec", {"command": [str, ...], "timeout_s"?: int}, ctx)`: reject a non-list / empty command → `ToolResult(ok=False)`; build `SandboxSpec(workdir=ctx.workspace, command=cmd, timeout_s=min(timeout_s, 120), allow_non_isolated=True)`; return `ToolResult(ok=res.ok, output={exit_code, stdout[:8k], stderr[:8k], timed_out}, meta={backend})`. Catch `(SandboxRefused, SandboxUnavailable, OSError, ValueError)` → `ToolResult(ok=False, error=repr)`. |
| Loop | `tools/loop.py`: `ToolLoop(dispatcher, llm, *, max_iters=6, parse_budget=2)`. `run(objective, ctx, manifest_block) -> ToolLoopResult{ok, done, iterations, summary, transcript: list[dict], denials: int}`. Prompt = system (role + rules) + user (objective, manifest, JSON-turn schema, transcript-so-far). Parse via `app.llm.parse.parse_json_object`. A turn is `{op, args}` → dispatch; `{done, summary}` → stop `ok=done`. Unparseable → append an `error` turn, decrement the parse budget; budget exhausted → stop `ok=False`. `max_iters` reached → stop `ok=False, summary="iteration cap"`. |
| Turn record | each transcript entry: `{kind: "call"|"result"|"error"|"done", op?, args?, ok?, trust?, output_excerpt?, error?}`. `output_excerpt` is `str(output)[:600]`. |
| Orchestrator wiring | `self.tool_loop = None` opt-in (a `ToolLoop` **or** a zero-arg factory returning one, so the dispatcher can be built from `self.tools` + `self.policy` lazily). `_drive`: `if contract.task_class == "ops" and self.tool_loop is not None: return self._run_tool_task(...)`. `_run_tool_task`: synth `Plan` (1 step, `required_capability` = the loop's declared need or `"shell.run"`), build a `DispatchContext` with a grant for that capability, run the loop, log `TOOL_LOOP` `{objective, iterations, ok, denials}` + an `OBSERVATION`, store the transcript as an artifact at `trust="tool_output"`, `VerificationRecord(tier="T0", overall="pass")` whose criterion states "tool loop finished within N iterations, all ops policy-checked, K denial(s) surfaced". |
| Events | `TOOL_LOOP` (objective, iterations, ok, denials). Per-op `TOOL` events come from the existing `_tool` path. |

## 3. Out of scope (deferred)

| Deferred | Why / when |
|---|---|
| Routing the *Builder* (code_edit_*) through the loop | the Builder has its own measured plan/step/progress machinery (§14.4); folding it in is a separate, larger milestone |
| Parallel / multi-tool turns | one op per turn keeps the transcript and the policy trail linear and auditable |
| A real function-calling wire format (Anthropic tool-use blocks) | the JSON-object turn is the seam; swapping in native tool-use is an `llm`-adapter change, not a loop change |
| Per-op retries / self-repair heuristics | the loop surfaces a denial/failure as a turn; deciding what to do with it is the model's job within `max_iters` |
| New adapters beyond `shell` | each is still a `ToolAdapter` — cheap now; not this milestone |
| Streaming a long-running `shell.exec` | `invoke` returns one `ToolResult`; a progress-yielding variant is a desktop-shell concern |

## 4. Component layout

```
app/services/tools/
  loop.py                 ToolLoop + ToolLoopResult
  adapters/shell_tool.py  ShellToolAdapter (shell.exec, sandboxed)
app/events/log.py                    + TOOL_LOOP
app/orchestration/orchestrator.py    opt-in self.tool_loop; ops -> _run_tool_task
tests/
  unit/         test_shell_tool, test_tool_loop
  integration/  test_tool_task
```

## 5. Work breakdown (~10 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `shell_tool.py`. Unit: `shell.exec` with a `shell.run` grant runs a trivial command → `ok`, `exit_code == 0`, `trust == "tool_output"`; without the grant → `ok=False` + a `PolicyDecision` (no exception); a non-list command → `ok=False`; a `timed_out` result maps to `ok=False`. |
| 3–5 | `loop.py` — prompt build, `parse_json_object` turn parsing, dispatch, transcript, the three stop conditions. Unit (scripted LLM): a 2-op-then-`done` script → `ok`, `iterations == 3`, transcript has 2 `result` turns + 1 `done`; a script that never says `done` → stops at `max_iters`, `ok=False`; two junk replies → stops on the parse budget; a `{op, args}` the grant forbids → a `result` turn `ok=False`, `denials == 1`, loop continues. |
| 6–7 | Orchestrator — `self.tool_loop` opt-in; `ops` dispatch; `_run_tool_task` (state path, `TOOL_LOOP` event, artifact, `T0` pass record). |
| 8–9 | Integration — a wired orchestrator runs an `ops` task ("list the repo, then read a file"): task `COMPLETED`, a `TOOL_LOOP` event, ≥ 2 `TOOL` events, the transcript artifact is stored at `trust="tool_output"`. A second run whose script asks for `shell.exec` **without** a `shell.run` grant → task still `COMPLETED`, `TOOL_LOOP.denials >= 1`, a `POLICY_DECISION` logged, the workspace untouched. `self.tool_loop` unset → an `ops` task path + events byte-identical to Milestone S. |
| 10 | Regression; `milestone_b/MILESTONE_T_NOTES.md`; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the top-level [README.md](README.md); rehash `MANIFEST.json`; commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — `ShellToolAdapter`: a granted `shell.exec` of a trivial command → `ok`,
  `trust="tool_output"`; ungranted → `ok=False` + `PolicyDecision`, no raise; bad args →
  `ok=False`. `ToolLoop`: the 2-ops-then-`done` script produces the expected transcript and
  `iterations`; no-`done` hits `max_iters` (`ok=False`); the junk-reply script stops on the
  parse budget; a forbidden op is a `result` turn `ok=False` with `denials` incremented and
  the loop continues.
- **Integration** — a wired orchestrator completes an `ops` task via `_run_tool_task`: a
  `TOOL_LOOP` event, ≥ 2 `TOOL` events, a `tool_output`-trust transcript artifact, a `T0`
  pass `VerificationRecord`. The ungranted-`shell.exec` script still `COMPLETED`s with
  `denials >= 1` and a `POLICY_DECISION`; the workspace is byte-unchanged. `self.tool_loop`
  unset → `ops` path + events identical to Milestone S.
- **Failure** — an adapter that raises inside `invoke` → a `result` turn `ok=False`, the loop
  continues; an LLM that always returns prose → the loop stops on the parse budget with a
  `TOOL_LOOP` `ok=False`, the task `FAILED` cleanly (no exception escapes).
- **Security (§5-C / §12)** — every op the loop runs goes through the existing
  `ToolDispatcher` → `PolicyEngine` + grant; a loop whose `ctx.trust="retrieved_web"` +
  taint sources is DENIED any `side_effecting` op by the existing `tainted-side-effect` rule;
  `shell.exec` without a `shell.run` grant is always denied; the transcript artifact is
  stamped `tool_output`, never `workspace`.
- **Recovery** — `reconcile()` + `resume()` unaffected; `ToolLoop` holds no task state
  between `run()` calls.
- **Benchmark** — n/a.

## 7. Tunable starting values

- `ToolLoop.max_iters`: **6**. `parse_budget`: **2**.
- `shell.exec` `timeout_s`: caller value clamped to **≤ 120 s**; default **30 s**.
- Shell stdout/stderr cap in the result: **8 KiB** each. `output_excerpt` in the transcript:
  **600** chars.
- `_run_tool_task` synthetic step capability: the `ToolLoop`'s declared need, else
  `"shell.run"`.
- Loop LLM = `getattr(self.interpreter, "llm", None) or getattr(self.planner, "llm", None)`
  (same pattern as `_run_doc_analysis`).

## 8. Risks

- **A wrong `shell.exec` command is a real side effect on this host** — the fallback sandbox
  is *not* isolation. Mitigated: `shell.run` is a distinct capability token that a grant must
  name explicitly; `_run_tool_task` only grants what the synthetic step declares; the
  integration tests that involve `shell` run trivial, read-only commands (`python -c "print"`).
  The Docker backend is the real isolation and is already the wired default where available.
- **Loop non-termination / cost** — bounded by `max_iters` + the parse budget + the
  task budget tracker is unchanged at the task level. No retry-in-a-sleep.
- **Prompt-injection via a tool result** — a `shell.exec` / `net.fetch` output is appended to
  the transcript the model sees next turn. Mitigated: the result's trust is carried; a
  subsequent side-effecting op proposed while `ctx.trust` is tainted is denied by the C
  rule. The loop never *raises* the context's trust.
- **Determinism regressions** — any wall-clock or hash-order leak into the transcript breaks
  reproducibility. Mitigated: the loop takes no time/random input; a unit test asserts two
  runs of the same script yield identical transcripts.

## 9. Deliverables

- `app/services/tools/loop.py` (`ToolLoop`, `ToolLoopResult`) + `adapters/shell_tool.py`
  (`ShellToolAdapter`).
- `TOOL_LOOP` event kind.
- Orchestrator: opt-in `self.tool_loop`; `ops` → `_run_tool_task` deliverable flow.
- Test suite: the current 445 green, plus unit (shell adapter / loop) and integration
  (tool task / denial path / unset-is-identical).
- `milestone_b/MILESTONE_T_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the
  top-level [README.md](README.md) updated: S's "LLM-driven tool selection" deferral is
  resolved; `ops` becomes a first-class flow.
