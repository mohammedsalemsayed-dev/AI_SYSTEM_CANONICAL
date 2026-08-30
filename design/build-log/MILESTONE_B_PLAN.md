# Milestone B — Vertical Slice Plan


---

## 1. Purpose

Prove — with running code, in ~2 weeks — that `request -> contract -> plan -> edit -> test ->
result` works end to end on a real task, with real persistence, and that the pieces compose.

The slice is deliberately **dumb**: one hardcoded model, T0-only verification, a temp-directory
copy instead of a sandbox, no router, no experience, no progress detection, no multi-agent, no
desktop UI. Every omitted subsystem is present as a **named seam** (an interface with a stub
behind it) so hardening is substitution, not rework.

This is the **Choice B** slice ([design-notes.md](../design-notes.md) §15.2): the
Builder is a driven engine (Claude Agent SDK, headless), not a hand-built agentic editor.
Under Choice A, step 4–5 below expands from ~2 days to weeks — which is why the slice is
B-shaped.

## 2. In scope

The minimum of [design-notes.md](../design-notes.md) §1:

| Stage | Slice implementation |
|---|---|
| capture | CLI takes a request string + a workspace path (must be a git repo). Emits `OriginalRequest`. |
| interpret | One LLM call -> `TaskContract` with `objective`, >=1 `success_criteria`, `task_class`, and `required_evidence` that **must name a runnable pytest target** (`"T0: pytest <path> passes"`). No T0 target derivable -> `ambiguity` set -> `WAITING_FOR_USER`, stop. |
| compose | Skipped. Model ids hardcoded; single Builder role. |
| plan | One LLM call -> `Plan{steps[]}` from the contract + a flat file listing (`git ls-files`). Each step: `intent`, `expected_artifact_delta`, `required_capability` (free string). Usually one step. |
| preflight | `policy.decide()` seam — stub returns `ALLOW`, logs the proposal. `capabilities.issue()` seam — stub returns an unrestricted grant scoped to the workspace path. |
| execute | Copy workspace to a temp dir. Drive the Agent SDK headless there with `step.intent` + `contract.objective`. Capture `git diff` + changed paths + stdout -> `Observation` + `ArtifactVersion`. |
| verify | Fresh copy of the original workspace, apply the diff, run the pytest target from `required_evidence`, parse exit code + summary -> `VerificationRecord{tier: T0, criteria[], overall}`. Deterministic; no model. |
| settle | `overall == pass` -> `COMPLETED`, else `FAILED`. Emit `TaskResult`. Write a `ModelRunRecord` per LLM call (latency + token counts only; not scored). |
| checkpoint | Every transition and the Observation are events in the log; that is the only checkpoint mechanism in the slice. |

State machine: reuse `core/state.py`; add the **gate predicates** from §1 (minimal forms).
Event log is the spine: one append-only table; the task snapshot is a fold over it.

## 3. Out of scope (named seams, stubbed)

| Deferred subsystem | Seam in the slice | Filled in |
|---|---|---|
| Model router / local tier | `llm/client.py` with hardcoded ids; Agent SDK default model | Milestone G / §7 |
| Sandbox tiers | `subprocess` in a `tempfile` copy | §14.6, Milestone C |
| Policy + capability engine | `services/policy/stub.py` — allow + log | Milestone C / §14.3 |
| Approvals | none (stub allows) | Milestone C |
| Progress / loop detection | none | Milestone D / §14.4 |
| Recovery / reconciliation | event log only; restart discards temp copies, task is idempotent by `task_id` | Milestone D |
| Experience repository | none | Milestone F / §14.7 |
| Memory beyond the task | Interpreter gets empty project memory | Milestone F |
| Multi-agent (critic, verifier ensemble) | single Builder; single deterministic T0 verifier | Milestone E / §9 |
| Verification T1–T3 | T0 only | §5, §14.1 |
| Budget enforcement | token counts logged, not enforced | §11.1 |
| PostgreSQL / Redis | SQLite via SQLAlchemy core | Milestone A hardening |
| WebSocket / streaming / desktop UI | CLI prints the timeline at the end | Milestone H |

## 4. Component layout

Fits the existing `apps/backend/app/` tree:

```
apps/backend/app/
  core/state.py                  # + gate predicates (extend existing)
  schemas/contracts.py           # + OriginalRequest, Plan/PlanStep, Observation,
                                 #   ArtifactVersion, VerificationRecord, TaskResult,
                                 #   ModelRunRecord (extend existing)
  events/log.py                  # append-only event log over SQLite
  events/projections.py          # fold events -> task snapshot
  llm/client.py                  # thin LLM wrapper, one hardcoded model, token/latency capture
  services/interpret/interpreter.py
  services/plan/planner.py
  services/build/builder_sdk.py   # drives Claude Agent SDK headless in a temp copy
  services/verify/verifier_t0.py
  services/policy/stub.py         # allow + log (the seam)
  orchestration/orchestrator.py   # flesh out the existing skeleton to the §1 flow
  api/main.py                     # keep /health /ready; optional POST /tasks
  cli/run_task.py                 # entry point
tests/
  unit/test_state_gates.py
  unit/test_contract_validation.py
  unit/test_event_replay.py
  integration/test_happy_path.py
  integration/test_failure_paths.py
  fixtures/sample_repo/           # tiny git repo: one module + one failing test
```

## 5. Work breakdown (~10 working days, one person)

| Day | Deliverable |
|---|---|
| 1 | Event log + projections over SQLite; `state.py` gate predicates; contract schemas extended. Unit tests: event replay reconstructs task state; each gate predicate. |
| 2 | `llm/client.py`; Interpreter; contract-validation gate (reject a contract with no T0 target). Unit test: vague request -> `WAITING_FOR_USER`. |
| 3 | Planner + `git ls-files` context; `Plan` schema; emit plan events. |
| 4–5 | Builder driving the Agent SDK in a temp copy; capture diff + changed paths + stdout -> `Observation` + `ArtifactVersion`; `policy.stub` + `capabilities.stub` seams wired in preflight. |
| 6 | Verifier T0: fresh copy, apply diff, run the named pytest target, parse -> `VerificationRecord`. |
| 7 | Orchestrator: full §1 flow with event emission and transitions; `cli/run_task.py` prints the timeline. |
| 8 | Integration happy path on `fixtures/sample_repo` (pytest red -> green -> `COMPLETED`); failure paths (pytest stays red -> `FAILED` not `COMPLETED`; ambiguous request -> `WAITING_FOR_USER`). |
| 9 | Light recovery test: kill mid-Builder, restart, event log shows last state, task restartable by `task_id`, temp copies discarded. Polish timeline output. |
| 10 | Run on 10 real small tasks in your own repos; collect premise metrics; write `SLICE_FINDINGS.md`. |

## 6. Acceptance criteria

Minimal cut of [ACCEPTANCE.md](../../archive/earlier-prototype/docs/testing/ACCEPTANCE.md):

- **Unit** — state-transition gate predicates; `TaskContract` validation rejects a contract
  with no T0 evidence; event-log append + replay reconstructs task state exactly.
- **Integration** — a real `code_edit_local` task on a small git repo: Builder produces a
  diff, the named pytest target goes red -> green, task reaches `COMPLETED` with a
  `VerificationRecord{tier: T0, overall: pass}` and a complete event timeline.
- **Failure** — (a) Builder's change leaves pytest red -> task reaches `FAILED`, never
  `COMPLETED`; (b) request with no derivable verifiable criterion -> `WAITING_FOR_USER`, no
  guess; (c) Agent SDK errors / times out -> `FAILED` with the error in an event, temp copy
  cleaned up.
- **Recovery (light)** — process killed during `EXECUTING`; on restart the event log shows
  `EXECUTING` as last state and the task can be re-run under the same `task_id` without
  double-applying (idempotent). Full reconciliation is Milestone D.

## 7. The premise test (what the slice is actually for)

On the 10 real tasks, record per task: diff correct (y/n, human judgement), T0 verdict
correct (did pytest gate it the way a human would), wall-clock, token cost, and whether the
Interpreter produced a usable T0 criterion unaided.

Read the results:

- **Diff correct in >= ~70%** with a clean T0 gate -> the premise holds; proceed to Milestone
  C and start pulling from §14, beginning with the security seam (§14.3) and Tier-A sandbox
  (§14.6).
- **Diff correct in ~50–70%** -> the executor is fine; the weakness is upstream. Invest in
  interpretation + planning + verification (§14.1) before C.
- **Diff correct in < ~50% even with a cloud Builder** -> the problem is the design of the
  loop, not the model. Reassess scope before building more infrastructure.

The same run also produces the first real `ModelRunRecord`s — the seed the §7 router needs and
cannot get any other way.

## 8. Slice-specific risks

- **Agent SDK config** — needs an API key / provider setup in the environment; document it in
  the slice README.
- **Workspace must be a git repo** — enforced at the CLI; diffing and fresh-copy verification
  depend on it.
- **pytest target resolution** — `required_evidence` must name the exact test path/node id;
  the Interpreter prompt states this explicitly.
- **Python-only** — the slice verifies via pytest; non-Python target repos are out of scope
  for B and that is acceptable.

## 9. Deliverables

- Running CLI slice (`run_task.py "<request>" --workspace <path>`).
- Passing unit + integration + failure + light-recovery tests.
- `SLICE_FINDINGS.md` — the 10-task premise metrics and the read from §7.
- [STATUS.md](../STATUS.md) and the
  [connective index](../requirements.md) updated: event
  log, intent compilation, end-to-end verification (T0), and the vertical slice move to
  FOUNDATION / IMPLEMENTED as earned.
