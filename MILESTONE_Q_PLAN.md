# Milestone Q — Fault Injection & Recovery Hardening Plan

> **Cross-reference**
> - Role: Build plan for a fault-injection toolkit and a systematic fault suite that proves every induced failure leads to a *safe terminal* and a clean `reconcile()` / `resume()`.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §4 (control loops / escalation), §5 (verification — T0 authoritative), §9-D1/§14 (recovery), §11.1 (budget), §12 (a refusal / hostile input is a fault to survive, not a crash); [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md) "still requiring real implementation → comprehensive test gates and fault injection".
> - Downstream: raises confidence in every milestone that runs through the orchestrator loop.
> - Predecessors: D (checkpoints / reconcile / resume — the machinery under test), B (the loop). Continues the `milestone_b/` tree.

---

## 1. Purpose

The recovery machinery (checkpoints, `reconcile()` RESUME/REPAIR/ESCALATE/NOOP, `resume()`)
is unit-tested on hand-built logs and exercised by a few integration tests, but nothing
**systematically induces** the real failure modes — a crashing sandbox, a model refusal, a
diff that half-applies, an interrupt between the artifact write and verification — and
asserts the whole stack lands safely.

Milestone Q adds:

- a **fault-injection toolkit** — thin wrappers over the injectable dependencies (LLM,
  sandbox runner, builder, egress opener) that raise / delay / corrupt on a schedule; a
  production build attaches none;
- a **fault suite** — one test per fault × injection point asserting the three invariants
  below;
- a **matrix runner** — `tests/fault/run_fault_suite.py` → `FAULT_FINDINGS.md`;
- whatever **orchestrator hardening** the suite exposes (any path that reaches a corrupted
  `COMPLETED`, leaves the user workspace mutated, or makes `reconcile()` return nonsense is a
  bug to fix here).

The three invariants every fault must satisfy:

1. **Safe terminal** — the task ends `FAILED` / `WAITING_FOR_USER` / `CANCELLED`, never a
   `COMPLETED` whose `verified` is not backed by a real passing T0. A `COMPLETED` implies a
   `VerificationRecord` with `overall == "pass"`.
2. **Workspace untouched** — the user's original workspace is byte-identical after the run
   (all work happens in temp copies); no partial diff is applied to it.
3. **Clean recovery** — `reconcile()` on the resulting log returns a sensible decision and
   `resume()` either completes, fails cleanly, or pauses — it never double-applies an
   effect, never crashes, and never resurrects a terminal task.

## 2. In scope

| Concern | Milestone Q implementation |
|---|---|
| Fault model | `faults/model.py`: `Fault{kind, on_call: int = 1, sticky: bool = False, detail: str = ""}`. `kind ∈ {llm_refusal, llm_timeout, llm_garbage, sandbox_unavailable, sandbox_timeout, sandbox_error, sandbox_crash, partial_diff, empty_diff, builder_exception, egress_flap, policy_exception, interrupt}`. `FaultPlan` = an ordered list; `should_fire(kind, call_n) -> Fault | None`. |
| LLM wrapper | `faults/wrappers.py::FlakyLLM(inner, plan)` — on the Nth `complete()` for a matching `kind`: `llm_refusal` → raise `RefusalError`; `llm_timeout` → raise `TimeoutError`; `llm_garbage` → return `LLMResponse(text="not json {{{")`. Otherwise delegate. |
| Sandbox wrapper | `FlakyRunner(inner, plan)` — `sandbox_unavailable` → raise `SandboxUnavailable`; `sandbox_timeout` → return `SandboxResult(timed_out=True)`; `sandbox_error` → `SandboxResult(error="injected")`; `sandbox_crash` → raise `RuntimeError`. |
| Builder wrapper | `FlakyBuilder(inner, plan)` — `partial_diff` → return a `BuildOutput` whose `diff` references a hunk that will not apply cleanly; `empty_diff` → `diff=""`; `builder_exception` → raise. |
| Egress wrapper | `flaky_opener(inner, plan)` — `egress_flap` → raise `URLError` on the Nth fetch. |
| Interrupt injection | `faults/interrupt.py::InterruptAfter(kind_of_event)` — a `log.append` hook that raises `_Interrupted` right after the first event of a named kind (`ARTIFACT`, `VERIFICATION`, `CHECKPOINT`), simulating a kill mid-run. The test then builds a fresh `Orchestrator` over the same log and calls `resume()`. |
| Fault suite | `tests/fault/test_*.py` — grouped by target: `test_fault_llm`, `test_fault_sandbox`, `test_fault_build`, `test_fault_interrupt`, `test_fault_egress`. Each case: inject → run → assert the 3 invariants (a shared `assert_safe(result, log, workspace_before)` helper). |
| Invariant helper | `tests/fault/conftest.py::assert_safe(...)` — checks terminal safety, workspace hash equality, `reconcile()` sanity, and (for interrupt cases) a `resume()` that satisfies the same. |
| Matrix runner | `tests/fault/run_fault_suite.py` — runs every `(kind, injection_point)` pair over a canonical task, tallies pass/fail on the 3 invariants, writes `milestone_b/FAULT_FINDINGS.md`. Offline (scripted providers) — runs in CI. |
| Hardening | any orchestrator / verifier / state-machine fix the suite forces (e.g. a fault path that skipped a `_transition` gate, or left a temp dir). Tracked in the notes. |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Real process-kill / OS-level chaos | the interrupt hook simulates it at the log boundary; a real `SIGKILL` harness needs the subscription + a supervisor |
| Network partition / disk-full / OOM | later — the wrappers cover the *observable* failure (exception / timeout / error result), which is what the orchestrator sees |
| Fuzzing the model outputs beyond "garbage JSON" | `llm_garbage` is one shape; a structured fuzzer is later |
| Fault injection into the desktop-shell server | H's server is read-only; low value |
| Concurrency / race faults | the slice is single-task-at-a-time; parallel-task faults are future |

## 4. Component layout

```
app/services/faults/
  model.py       Fault, FaultPlan, should_fire
  wrappers.py    FlakyLLM, FlakyRunner, FlakyBuilder, flaky_opener
  interrupt.py   InterruptAfter (log-append hook) + _Interrupted
tests/fault/
  conftest.py    assert_safe(); a canonical scripted orchestrator factory
  test_fault_llm.py  test_fault_sandbox.py  test_fault_build.py
  test_fault_interrupt.py  test_fault_egress.py
  run_fault_suite.py   matrix -> FAULT_FINDINGS.md
milestone_b/FAULT_FINDINGS.md   (generated)
```

## 5. Work breakdown (~10 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `faults/model.py` + `faults/wrappers.py` (`FlakyLLM`, `FlakyRunner`). Unit-level self-tests: a plan fires exactly on `on_call`, `sticky` keeps firing, a non-matching call delegates untouched. |
| 3 | `faults/wrappers.py` (`FlakyBuilder`, `flaky_opener`) + `faults/interrupt.py`. Self-tests. |
| 4 | `tests/fault/conftest.py` — `assert_safe()` (terminal safety + workspace hash + `reconcile()` sanity) + the scripted orchestrator factory (real `SubprocessSandbox`, scripted LLM/builder, a git `sample_repo`). |
| 5 | `test_fault_llm.py` — refusal at interpret / plan / (critic, if wired); timeout; garbage JSON. Assert `assert_safe`. Fix any orchestrator path that crashes instead of failing cleanly. |
| 6 | `test_fault_sandbox.py` — unavailable / timeout / error / crash during T0 verify and during per-step measurement. Assert `assert_safe` (must end `FAILED`, workspace clean). |
| 7 | `test_fault_build.py` — `partial_diff` (must be caught by `apply_diff` → `FAILED`, workspace clean), `empty_diff` (already handled — regression-lock it), `builder_exception`. |
| 8 | `test_fault_interrupt.py` — interrupt right after `ARTIFACT`, after `VERIFICATION`, after `CHECKPOINT`; then `resume()` on a fresh `Orchestrator`; assert `reconcile()` picked the right branch and `resume()` satisfies the invariants and does not double-apply. |
| 9 | `test_fault_egress.py` (research path, `egress_flap`) + `run_fault_suite.py` → `FAULT_FINDINGS.md`; run it, record results. |
| 10 | Regression; `milestone_b/MILESTONE_Q_NOTES.md` (incl. every hardening fix); update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the top-level [README.md](README.md); rehash `MANIFEST.json`; commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — `should_fire` fires exactly on `on_call` and (when `sticky`) after; each wrapper
  raises / returns the documented failure for its `kind` and delegates otherwise;
  `InterruptAfter` raises `_Interrupted` after the first matching event and not before.
- **Integration / Failure** — for **every** `kind` at **every** applicable injection point,
  `assert_safe` holds: the task ends in a safe terminal (a `COMPLETED` always has a passing
  `VerificationRecord`), the user workspace hash is unchanged, and `reconcile()` returns a
  non-`ESCALATE`-only-by-accident decision that `resume()` can act on. No injected fault
  produces an unhandled exception out of `orch.run()` / `orch.resume()`.
- **Recovery** — every interrupt case: a fresh `Orchestrator` over the interrupted log
  `resume()`s to a safe terminal; an interrupt *after* a completed `VERIFICATION`+`RESULT`
  is a `NOOP` (task already done); an interrupt *before* verification never yields a
  `COMPLETED`; nothing is applied twice (idempotency-key check).
- **Security (§12)** — an `llm_refusal` on a research/KB path ends the task without emitting
  a side effect or elevating trust; a fault never bypasses the policy engine or the taint
  rule.
- **Benchmark** — `run_fault_suite.py` runs offline and `FAULT_FINDINGS.md` shows every
  `(kind, point)` pair PASS on all three invariants (or a documented, ticketed exception).

## 7. Tunable starting values

- `on_call` default = **1** (fail the first matching call).
- `llm_timeout` / `sandbox_timeout` are modelled as an immediate raised `TimeoutError` /
  `timed_out=True` result — no real sleep (keeps the suite fast).
- Interrupt points: `ARTIFACT`, `VERIFICATION`, `CHECKPOINT`, `PLAN` (extendable).
- Suite task: the `sample_repo` calc bug (deterministic, one-file, has a T0).

## 8. Risks

- **The suite finds real bugs** — expected and good; each fix lands in this milestone and is
  listed in the notes. If a fix is large it gets a ticket and a documented xfail, not a
  silent skip.
- **Wrappers drift from the real failure shape** — a `FlakyRunner` that raises the wrong
  exception type would test the wrong path. Mitigate: the wrappers raise the *actual*
  exception classes the real backends raise (`SandboxUnavailable`, `RefusalError`, `URLError`),
  imported from their modules.
- **Interrupt simulation is not a real kill** — it stops at the log boundary, so state held
  only in memory (not yet logged) is lost, which is the realistic case; a true `SIGKILL`
  harness is deferred but the boundary is the same one `reconcile()` reasons about.
- **Combinatorial blow-up** — kinds × points is bounded (~13 × ~4) and each case is a fast
  scripted run; the matrix runner caps at the documented set.

## 9. Deliverables

- `app/services/faults/` — `model.py`, `wrappers.py`, `interrupt.py`.
- `tests/fault/` — the suite + `conftest.py` + `run_fault_suite.py`; `FAULT_FINDINGS.md`.
- Any orchestrator / verifier hardening the suite forced.
- Test suite: the current 396 green, plus the fault suite (~25–35 cases).
- `milestone_b/MILESTONE_Q_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the
  top-level [README.md](README.md) updated: "comprehensive test gates and fault injection"
  moves off the "still requiring real implementation" list; a "Fault injection" row goes
  FOUNDATION.
