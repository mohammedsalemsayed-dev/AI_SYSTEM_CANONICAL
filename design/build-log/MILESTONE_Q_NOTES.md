# Milestone Q notes — what is real, what remains

Status against [../MILESTONE_Q_PLAN.md](../MILESTONE_Q_PLAN.md). **423 tests green.**
All 10 days built. Removes "comprehensive test gates and fault injection" from the
`STATUS.md` "still requiring real implementation" list.

## Real after Milestone Q

| Area | Module | Notes |
|---|---|---|
| Fault model | `app/services/faults/model.py` | `Fault{kind, on_call=1, sticky=False}` over 13 kinds; `FaultPlan.should_fire(kind)` advances a per-kind counter and returns the `Fault` to raise on the Nth (or every `sticky`) matching call. Unknown kind → `ValueError`. |
| Wrappers | `app/services/faults/wrappers.py` | `FlakyLLM` (`llm_refusal` → `RefusalError`, `llm_timeout` → `TimeoutError`, `llm_garbage` → non-JSON reply), `FlakyRunner` (`sandbox_unavailable` → `SandboxUnavailable`, `sandbox_crash` → `RuntimeError`, `sandbox_timeout` → `SandboxResult(timed_out=True)`, `sandbox_error` → `SandboxResult(error=…)`), `FlakyBuilder` (`partial_diff` → a hunk that will not apply, `empty_diff`, `builder_exception`), `flaky_opener` (`egress_flap` → `URLError`). Each raises the **actual** exception class the real backend raises, and delegates untouched otherwise. |
| Interrupt injection | `app/services/faults/interrupt.py` | `InterruptAfter(log, event_kind)` — an `EventLog` wrapper that persists the first `append` of the target kind and then raises `_Interrupted`. `_Interrupted` inherits **`BaseException`** (like `KeyboardInterrupt`), so the orchestrator's `except Exception` graceful-failure handler does *not* catch it — simulating a hard process kill that leaves a partial log for `reconcile()`. |
| Fault suite | `tests/fault/` | `test_fault_llm` (3 kinds × interpret/plan), `test_fault_sandbox` (4), `test_fault_build` (3), `test_fault_interrupt` (4 event points + a "resume-after-RESULT is a NOOP" case), `test_fault_egress` (2). Shared `assert_safe(result, log, workspace_before, root)` checks the three invariants: **safe terminal** (a `COMPLETED` always has a passing `VerificationRecord`), **workspace untouched** (`workspace_hash` unchanged), **clean reconcile** (`reconcile()` returns a sane decision; a terminal task reconciles to `NOOP`). 20 suite tests, all pass. |
| Matrix runner | `tests/fault/run_fault_suite.py` | Runs every `(kind × injection point)` over a canonical calc-bug task, checks all three invariants, writes `../nexus/FAULT_FINDINGS.md`. Offline (scripted providers). **14/14 pairs PASS.** |

## Hardening the suite forced

- **`EgressBroker.fetch` swallowed no transport error.** A raw `URLError` / timeout from the
  opener propagated straight through `Researcher.research` and crashed `ResearchPipeline.run`
  — an unhandled exception out of `orch.run()` on the `research_web` path. **Fix:** added
  `EgressError` (allowed URL, transport failed — distinct from `EgressDenied` = policy);
  `fetch()` now wraps the opener and raises `EgressError` on any failure, recording the URL
  in `blocked`. `Researcher` catches `(EgressDenied, EgressError)` and continues, so a flaky
  network degrades to "fewer sources → explicit uncertainty", never a crash.
  (`app/services/egress/broker.py`, `app/services/agents/researcher.py`.)

Everything else already held: LLM refusal/timeout/garbage, every sandbox failure shape, a
non-applying diff, an empty diff, a builder exception, and a hard kill after
`PLAN`/`CHECKPOINT`/`ARTIFACT`/`VERIFICATION` all land in a safe terminal with the user
workspace byte-identical and a clean `reconcile()` + `resume()`.

## Observations from `FAULT_FINDINGS.md`

- Every service fault (llm / sandbox / builder) → `FAILED`. Never a corrupted `COMPLETED`,
  never a partially-applied user workspace.
- Interrupt after `PLAN` / `CHECKPOINT` / `ARTIFACT` → `resume()` re-drives execution and the
  task **completes** with a real passing T0 (the `RESUME` branch of `reconcile()`).
- Interrupt after `VERIFICATION` (but before the `COMPLETED` transition + `RESULT`) →
  `resume()` lands `FAILED` cleanly in the matrix run (re-drive without the mid-run
  in-memory state); the pytest case accepts either `COMPLETED` or a safe `FAILED`. Both
  satisfy the invariants.
- No injected fault produced an unhandled exception out of `orch.run()` / `orch.resume()`
  after the egress fix.

## Not yet real / deferred

- **Real OS-level chaos** — the interrupt hook stops at the log boundary; a true `SIGKILL`
  harness with a process supervisor is deferred (needs the subscription + a runner). The
  boundary is the same one `reconcile()` reasons about, so the coverage is representative.
- **Disk-full / OOM / clock-skew** — the wrappers cover the *observable* failure the
  orchestrator sees (exception / timeout / error result); the specific resource-exhaustion
  triggers are later.
- **Model-output fuzzing** beyond `llm_garbage` — one malformed-JSON shape; a structured
  fuzzer is later.
- **Concurrency / race faults** — the slice runs one task at a time.
- **Fault injection into the desktop-shell server** — read-only, low value.

## Deferred past Q (unchanged)

Milestone A hardening (Postgres / Redis / full telemetry); the live-harness runs and the
Tauri native build (subscription / toolchain); real renderer / RAG / engine-toolchain
integrations behind their seams.
