# Milestone U — Loop Detection for the Tool-Use Loop Plan

> **Cross-reference**
> - Role: Apply the Milestone D structural loop detector + a meaningful-progress signal to the Milestone T tool-use loop, so a model that keeps calling the same failing op is caught and **escalated to the user** early, not left to burn the blunt iteration cap and then fail silently.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [MILESTONE_T_PLAN.md](MILESTONE_T_PLAN.md) (`ToolLoop` + `_run_tool_task`), [MILESTONE_D_PLAN.md](MILESTONE_D_PLAN.md) / [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §14.4 (`LoopDetector` — `repeated_action` / `repeated_error` / `diff_thrash` flags + the made-progress false-positive guard), §1 (a stalled step is an escalation, not a silent failure).
> - Downstream: any future agent loop reuses `LoopDetector` the same way; the tool loop stops being the one execution path with no progress guard.
> - Predecessors: D (`LoopDetector`, `action_hash`, `normalize_error`), T (`ToolLoop`). Continues the `milestone_b/` tree.

---

## 1. Purpose

Milestone T's loop has exactly one bound: `max_iters` (plus a parse budget). A model that
proposes the same broken `fs.read` six times in a row does six full policy round-trips and
then the task simply `FAILED`s with `summary="iteration cap"` — no signal that it was
*looping*, no early exit, no escalation. The `_execute` (code-edit) path has had structural
loop detection since Milestone D; the tool loop should too.

Milestone U wires D's `LoopDetector` into `ToolLoop`:

- **per dispatched turn**, feed the detector `action_hash(op, "", args)`, the normalised error
  signature (when the op failed), the output excerpt as the "diff", and a **made-progress**
  bit — `True` when the op succeeded with an action hash not seen succeeding before. A turn
  that makes progress clears the detector history (D's false-positive guard);
- on `loop_risk` (any of `repeated_action` / `repeated_error` / `diff_thrash`), **stop the
  loop early** with a distinct outcome — `ToolLoopResult.loop_risk = True`, `loop_flags`, and
  a `{"kind": "loop_risk"}` transcript turn;
- in the orchestrator, a `loop_risk` stop **escalates to `WAITING_FOR_USER`** with a
  `ClarificationRequest` (exactly the `StalledEscalation` pattern from `_execute`), not a
  bare `FAILED`. A plain `ok=False` (iteration cap / parse budget) still `FAILED`s as before.

Guiding rules:
- **Reuse, don't reinvent.** `LoopDetector`, `action_hash`, `normalize_error` are imported
  from `app.services.progress.loop` unchanged. No new detection logic.
- **Opt-out, not opt-in.** Detection is on by default (`ToolLoop(detect_loops=True)`); a
  caller can disable it. This is a *tightening* of T, and T is itself opt-in, so no shipped
  behaviour regresses — but a unit test pins "same script, detection off ⇒ old behaviour".
- **Deterministic.** The detector does no model call and no I/O; the loop still takes no
  wall-clock / random input. Same script + workspace ⇒ same outcome incl. the loop flags.
- **Escalate, don't guess.** A loop-risk stop asks the user how to proceed; it never silently
  retries or mutates the objective (§1, §12).

## 2. In scope

| Concern | Milestone U implementation |
|---|---|
| Detector wiring | `ToolLoop.__init__(..., loop_detector: LoopDetector | None = None, detect_loops: bool = True)`. A per-`run()` detector instance (or a fresh one when none passed) + an `_ok_hashes: set[str]` for the made-progress bit. |
| Per-turn record | after `self.dispatcher.run(...)`: `made_progress = result.ok and act_hash not in ok_hashes` (then add the hash); `lr = detector.record(act_hash=action_hash(op, "", args), error_signature=normalize_error(result.error) if not result.ok else None, diff_text=(output_excerpt or ""), made_progress=made_progress)`. Attach `lr.flags` to the `result` turn as `loop_flags` when non-empty. |
| Early stop | `if detect_loops and lr.loop_risk:` append `{"kind": "loop_risk", "flags": lr.flags}` and return `ToolLoopResult(ok=False, done=False, iterations=it, summary="loop risk: " + ",".join(lr.flags), transcript, denials, decisions, loop_risk=True, loop_flags=lr.flags)`. |
| Result type | `ToolLoopResult` gains `loop_risk: bool = False`, `loop_flags: list[str] = []`. |
| Orchestrator | `_run_tool_task`: `TOOL_LOOP` payload gains `loop_flags`. A `PROGRESS` event per dispatched turn is **not** added (keep the log lean); instead one `PROGRESS` summary event `{turns, ok_calls, repeats: len(transcript)-distinct, loop_flags}` on completion. On `result.loop_risk`: log a `CLARIFICATION` (`ClarificationRequest`, why="tool loop is repeating without progress"), `_transition(WAITING_FOR_USER)`, `_finish(state=WAITING_FOR_USER, summary="tool loop looping: <flags>")`. The existing `ok=False` → `FAILED` branch is unchanged for iteration-cap / parse-budget. |
| Events | none new — reuse `PROGRESS` + `CLARIFICATION` + `TOOL_LOOP`. |

## 3. Out of scope (deferred)

| Deferred | Why / when |
|---|---|
| An escalation *ladder* for the tool loop (retry with a stronger model / a critic before asking the user) | D's `Ladder` is `_execute`-shaped (re-plan + re-measure); adapting it to a tool transcript is its own milestone. U goes straight to the user, which is the safe floor. |
| `ProgressService` patience / `STALLED` classification in the tool loop | the tool loop has no pytest oracle to measure objective/test deltas against; `made_progress` here is the coarse "a new op succeeded" bit. A richer per-turn progress model is later. |
| Feeding unparseable / op-less turns to the detector | already bounded by `parse_budget`; mixing the two budgets adds no safety. |
| Tuning `REPEAT_WINDOW` / thresholds for tool-loop cadence | ship D's constants; recalibrate from real transcripts (same as D §7). |

## 4. Component layout

```
app/services/tools/loop.py            + loop_detector wiring; ToolLoopResult.loop_risk/loop_flags
app/orchestration/orchestrator.py     _run_tool_task: loop_risk -> WAITING_FOR_USER + CLARIFICATION;
                                      PROGRESS summary event; loop_flags in TOOL_LOOP
tests/
  unit/         test_tool_loop.py  (+ loop-detection cases)
  integration/  test_tool_task.py  (+ the escalation case)
```

## 5. Work breakdown (~8 working days)

| Day | Deliverable |
|---|---|
| 1–3 | `ToolLoop` — detector instance per `run()`, the `_ok_hashes` made-progress bit, the per-turn `record()` call, `loop_flags` on the `result` turn, the early-stop return. `ToolLoopResult.loop_risk` / `loop_flags`. Unit: a script that repeats one failing `fs.read` trips `repeated_action` + `repeated_error` before `max_iters`; a script that makes distinct progress each turn never trips; `detect_loops=False` restores the iteration-cap behaviour; the outcome (incl. flags) is identical across two runs of the same script. |
| 4–6 | Orchestrator — `_run_tool_task`: `loop_risk` → `CLARIFICATION` + `WAITING_FOR_USER` (mirror `StalledEscalation`); `PROGRESS` summary event; `loop_flags` in `TOOL_LOOP`. Integration: a wired `ops` task whose script loops a failing op ends `WAITING_FOR_USER` with a `CLARIFICATION` event and a stored transcript; a healthy `ops` task is unaffected; `iteration cap` / parse-budget still `FAILED`s. |
| 7–8 | Regression; `milestone_b/MILESTONE_U_NOTES.md`; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the top-level [README.md](README.md); rehash `MANIFEST.json`; commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — a repeated failing op trips `loop_risk` with `repeated_action` and/or
  `repeated_error` at `iterations < max_iters`; a per-turn-progress script never trips and
  still reaches `done`; `detect_loops=False` reproduces the T iteration-cap result; the full
  `ToolLoopResult` (flags included) is byte-identical across two runs of one script.
- **Integration** — a wired `ops` task that loops a failing op → `WAITING_FOR_USER`, a
  `CLARIFICATION` event whose question names the flags, a `tool_output` transcript artifact
  still stored, a `PROGRESS` summary event. A healthy `ops` task → `COMPLETED`, no
  `CLARIFICATION`. An `ops` task that hits the iteration cap without repeating → `FAILED`
  (unchanged).
- **Failure** — the detector never raises; an adapter exception is still a `result` turn and
  also feeds the detector (a repeated raising op is a loop). Disabling detection cannot make
  the loop unbounded — `max_iters` still applies.
- **Security (§1 / §12)** — a loop-risk stop escalates to the user; it never re-runs an op,
  changes the objective, or widens a capability. Every op still passes the S dispatcher.
- **Recovery** — `ToolLoop` still holds no state between `run()` calls; the detector instance
  is per-`run()`. `reconcile()` / `resume()` unaffected.
- **Benchmark** — n/a.

## 7. Tunable starting values

- Detector constants: D's defaults (`REPEAT_WINDOW=5`, `REPEAT_THRESHOLD=3`,
  `ERROR_THRESHOLD=3`, `THRASH_THRESHOLD=3`, `THRASH_SIMILARITY=0.9`).
- Made-progress bit: `result.ok and action_hash not in ok_hashes` (a new op that works).
- `detect_loops` default: **True**.
- `diff_text` for the detector = the transcript `output_excerpt` (≤ 600 chars).

## 8. Risks

- **False positive on legitimate repetition** — e.g. `fs.read` of the same file twice for a
  good reason. Mitigated: D's threshold is **3** identical hashes in a window of 5, and any
  *successful* new op clears the history; two reads of one file that both succeed set the
  made-progress bit and never accumulate. The escalation is to the user, who can say
  "continue".
- **`output_excerpt` as the thrash signal is weak** — tool outputs are not diffs. Mitigated:
  `diff_thrash` is the least-load-bearing flag; `repeated_action` + `repeated_error` carry the
  detection and are exact.
- **A caller passing a shared `LoopDetector`** — would leak history across `run()` calls.
  Mitigated: the parameter exists for testing; `_run_tool_task` never passes one, so each
  task gets a fresh detector.

## 9. Deliverables

- `app/services/tools/loop.py` — `LoopDetector` wired into `ToolLoop`;
  `ToolLoopResult.loop_risk` / `loop_flags`.
- Orchestrator `_run_tool_task` — `loop_risk` → `WAITING_FOR_USER` + `CLARIFICATION`;
  `PROGRESS` summary; `loop_flags` in `TOOL_LOOP`.
- Test suite: the current 458 green, plus the loop-detection unit cases and the escalation
  integration case.
- `milestone_b/MILESTONE_U_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the
  top-level [README.md](README.md) updated: the tool loop now has the §14.4 progress guard.
