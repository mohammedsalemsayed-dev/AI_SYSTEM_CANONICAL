# Milestone U notes — what is real, what remains

Status against [../MILESTONE_U_PLAN.md](../MILESTONE_U_PLAN.md). **463 tests green.**
All 8 days built. The Milestone T tool-use loop now carries the §14.4 structural
progress guard that the `_execute` (code-edit) path has had since Milestone D.

## Real after Milestone U

| Area | Module | Notes |
|---|---|---|
| Detector wiring | `app/services/tools/loop.py::ToolLoop` | `__init__(..., detect_loops: bool = True, loop_detector: LoopDetector | None = None)`. A **fresh `LoopDetector` per `run()`** (the loop still holds no cross-call state) + an `_ok_hashes` set for the made-progress bit. `action_hash` / `normalize_error` / `LoopDetector` are imported unchanged from `app.services.progress.loop` — no new detection logic. |
| Per-turn record | — | After each dispatch: `made_progress = result.ok and action_hash(op, "", args) not in ok_hashes` (then the hash is remembered). `detector.record(act_hash=…, error_signature=normalize_error(result.error or op) if not result.ok else None, diff_text=output_excerpt, made_progress=…)`. A turn that runs a **new** op successfully clears the detector history (D's false-positive guard); a repeated failing op accumulates `repeated_action` + `repeated_error`. Non-empty `report.flags` are attached to the `result` transcript turn as `loop_flags`. |
| Early stop | — | `if detect_loops and report.loop_risk:` → append a `{"kind": "loop_risk", "flags": […]}` turn and return `ToolLoopResult(ok=False, done=False, iterations=it, summary="loop risk: <flags>", …, loop_risk=True, loop_flags=[…])` — **before** `max_iters`. |
| Result type | `ToolLoopResult` | `+ loop_risk: bool = False`, `+ loop_flags: list[str] = []`. |
| Escalation | `orchestrator._run_tool_task` | On `result.loop_risk`: log a `CLARIFICATION` (`ClarificationRequest`, `why="tool loop is looping without progress"`, question names the flags) → `_transition(WAITING_FOR_USER)` → `_finish(state=WAITING_FOR_USER)`. This mirrors the `_execute` `StalledEscalation` path exactly — a repeating no-progress loop asks the user, it never silently retries or mutates the objective (§1). The plain `ok=False` (iteration cap / parse budget) branch still → `FAILED`, unchanged. |
| Observability | `orchestrator._run_tool_task` | One `PROGRESS` summary event per task — `{phase: "tool_loop", turns, ok_calls, repeats, loop_flags, classification: "LOOP_RISK" | "done" | "incomplete"}`. `TOOL_LOOP` payload gains `loop_risk` + `loop_flags`. No per-turn `PROGRESS` spam. |
| Events | none new — reuses `PROGRESS`, `CLARIFICATION`, `TOOL_LOOP`. |

## Scope / security posture

- **Reuse, not reinvention.** D's `LoopDetector` (thresholds: 3 identical action hashes in a
  window of 5; 3 identical error signatures; 3 near-identical successive outputs) is used
  as-is. The tool loop is no longer the one execution path with no progress guard.
- **Escalate, don't guess.** A loop-risk stop goes straight to `WAITING_FOR_USER` with a
  clarification question. No retry, no stronger-model rung, no objective change (§1 / §12).
- **Deterministic.** The detector does no model call and no I/O; the loop still takes no
  wall-clock / random input. A unit test pins that the full `ToolLoopResult` (flags included)
  is identical across two runs of the same script.
- **Opt-out.** `detect_loops=False` restores the exact Milestone T iteration-cap behaviour
  (unit-tested). Detection is on by default; since T is itself opt-in, nothing shipped
  regresses. Disabling detection cannot make the loop unbounded — `max_iters` still applies.

## Not yet real / deferred

- **An escalation *ladder* for the tool loop** — D's `Ladder` (re-plan + re-measure) is
  `_execute`-shaped; adapting it to a tool transcript (retry with a stronger model / a critic
  before asking the user) is its own milestone. U goes straight to the user — the safe floor.
- **`ProgressService` patience / `STALLED` classification** — the tool loop has no pytest
  oracle to measure objective/test deltas; `made_progress` here is the coarse "a new op
  succeeded" bit. A richer per-turn progress model is later.
- **Feeding unparseable / op-less turns to the detector** — already bounded by `parse_budget`.
- **Threshold tuning for tool-loop cadence** — ships D's constants; recalibrate from real
  transcripts (D §7).

## Deferred past U (unchanged)

Routing the Builder (`code_edit_*`) through the tool loop; parallel tool turns; native
tool-use blocks; adapters beyond `shell`. Milestone A hardening (Postgres / Redis); a real
local model backend; secrets management; the native Tauri build; subscription-gated harness
runs.
