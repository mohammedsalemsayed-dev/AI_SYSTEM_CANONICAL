# Milestone V — Per-File Policy Checks on Builder Output Plan


---

## 1. Purpose

`_run_step` builds exactly one `ActionProposal` per plan step:

```python
ActionProposal(operation=primary_operation(step.required_capability),
               arguments={"path": ws, "intent": step.intent}, ...)
```

`_paths_in(proposal)` therefore returns just `ws` — the workspace **root**. So:

- `rule_risk_class_needs_approval` compares `ws` against `*auth*` / `*/migrations/*` /
  `*secret*` / `*/payments/*` / `*.pem` … and never matches — **a build that rewrites
  `app/auth/login.py` or a DB migration is never sent for approval**, contradicting §14.1;
- `rule_path_out_of_scope` only ever sees the root (always in scope);
- `rule_operation_not_granted` can't notice that a `required_capability="fs.read"` step
  somehow wrote files.

Milestone V adds, **after the builder runs and before the step's artifact is recorded**, one
`file.write` `ActionProposal` per path in `out.changed_paths`, each run through the **same**
`PolicyEngine.decide` against the **same** step grant:

- an ALLOW is just a logged `POLICY_DECISION` (`scope: "per-file"`);
- a `REQUIRE_APPROVAL` (risk-class file) with the step not yet user-approved → the existing
  `ApprovalPause` → the task waits for the user, naming the file(s);
- a `DENY` (out of scope / tainted / operation not granted) → `BuildError`, the step fails.

The builder works on the discardable workspace **copy**, so a per-file DENY/pause happens
before anything is verified, committed, or promoted — the changed files are thrown away with
the copy.

Guiding rules:
- **Reuse the engine.** No new rule, no new gate. V calls `self.policy.decide` with the
  step's `CapabilityGrant`, once per file, exactly as `_run_step` already does once per step.
- **Additive / opt-in.** `self.per_file_policy = False` by default → `_run_step` is
  byte-identical to Milestone U. On → the per-file pass runs and can pause/deny.
- **Match paths the way the rules expect.** Feed the **relative** changed path (e.g.
  `app/auth/login.py`) as `arguments["path"]` so the risk globs match cleanly and
  `covers_path` still resolves it under the grant scope.
- **Approval is step-scoped** (as today): approving the step approves all its files. Per-file
  approval granularity is deferred.

## 2. In scope

| Concern | Milestone V implementation |
|---|---|
| Opt-in flag | `Orchestrator.per_file_policy: bool = False`. |
| Per-file pass | `_per_file_policy(task_id, contract, step, ws, grant, changed_paths, approved_steps)` — for each relative `rel` in `changed_paths`: `ActionProposal(operation="file.write", arguments={"path": rel}, required_capability="fs.write", workspace_scope=ws, idempotency_key=f"{task_id}:{step.id}:{rel}")`; `d = self.policy.decide(p, contract, grant)`; log `POLICY_DECISION` with `{"scope": "per-file", "path": rel}`. `ALLOW` → continue; `REQUIRE_APPROVAL` → collect; `DENY`/other → log `TAINT_BLOCKED` when `rule == "tainted-side-effect"`, then `raise BuildError`. After the loop: if any collected and `step.id not in approved_steps` → `raise ApprovalPause(f"{task_id}:{step.id}:files", step.id, "<n> changed file(s) need approval (<rels>): <first reason>")`. |
| Call site | `_run_step`: immediately after `out = self.builder.execute(...)`, `if self.per_file_policy and out.exit_code == 0 and not out.error and out.changed_paths: self._per_file_policy(...)` — before the `ArtifactVersion` / `ARTIFACT` / `OBSERVATION` logging, so a pause/deny leaves no artifact for a step that never really happened. |
| Events | none new — reuses `POLICY_DECISION` (with a `scope` marker) + `TAINT_BLOCKED`. |
| Approval flow | unchanged — `ApprovalPause` → `_drive`'s handler → `WAITING_FOR_USER`; on resume with the step approved, the per-file pass re-runs and the `REQUIRE_APPROVAL`s are now waved through because `step.id in approved_steps`. |

## 3. Out of scope (deferred)

| Deferred | Why / when |
|---|---|
| Routing each builder write through `FsToolAdapter` / `ToolDispatcher` *as it happens* | needs the Builder to *declare* writes instead of performing them — an interface change across `ScriptedBuilder` / `AgentSDKBuilder` / every test. V gets the security property (every file seen by the engine) without that rewrite. |
| Per-file approval granularity | approval stays step-scoped; a follow-up can thread a `{step_id: {path}}` set. |
| Pre-write prevention (checking before the copy is modified) | the builder is a black box that writes then reports; V checks the reported set. The copy is discardable, so post-write + fail-before-verify is a real enforcement point. |
| Content inspection of the diff (secret scanning, license headers) | a different concern (a verifier tier), not the policy engine. |
| Applying the per-file pass to the tool loop's `fs.write` | the tool loop already dispatches each `fs.write` individually through the engine (Milestone S) — it is already per-file. |

## 4. Component layout

```
app/orchestration/orchestrator.py   + self.per_file_policy; _per_file_policy(); call in _run_step
tests/
  unit/         test_per_file_policy.py   (the helper in isolation)
  integration/  test_policy_enforcement.py (+ a risk-class code-edit pauses; a plain one doesn't)
```

## 5. Work breakdown (~7 working days)

| Day | Deliverable |
|---|---|
| 1–3 | `_per_file_policy` + the `per_file_policy` flag + the `_run_step` call. Unit: a changed `app/auth/x.py` → one `REQUIRE_APPROVAL` `POLICY_DECISION` + an `ApprovalPause`; the same with `step.id` in `approved_steps` → no pause, an `ALLOW` per file; a changed path under a `fs.read`-only grant → `BuildError` (`operation-not-granted`); a plain `calc.py` change → all `ALLOW`, no pause. |
| 4–6 | Integration over the real orchestrator: `per_file_policy=True`, a scripted builder that edits `app/migrations/0002.py` → the task ends `WAITING_FOR_USER` with an `APPROVAL_REQUEST` / clarification and one per-file `POLICY_DECISION`; resume-with-approval → `COMPLETED`. A scripted builder that edits `calc.py` only → `COMPLETED`, per-file `POLICY_DECISION`s all `ALLOW`. `per_file_policy=False` (default) → the run + event stream are byte-identical to Milestone U. |
| 7 | Regression; `../nexus/MILESTONE_V_NOTES.md`; update [STATUS.md](../STATUS.md), the [connective index](../requirements.md), and the top-level [README.md](../../README.md); commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — `_per_file_policy` emits one `POLICY_DECISION` per changed path with
  `scope="per-file"`; a risk-class path → `ApprovalPause` unless the step is pre-approved; an
  out-of-grant `file.write` → `BuildError`; a benign path set → no raise, all `ALLOW`.
- **Integration** — with `per_file_policy=True`, a build touching a `*/migrations/*` file →
  `WAITING_FOR_USER`; approve + resume → `COMPLETED`. A build touching only ordinary files →
  `COMPLETED` unchanged. `per_file_policy=False` → byte-identical to Milestone U.
- **Failure** — a per-file DENY raises `BuildError`, caught by the existing `_drive` handler
  (task → `WAITING_FOR_USER` / `FAILED` as today); the discardable copy is cleaned up; no
  `ARTIFACT` event is written for the aborted step.
- **Security (§14.1)** — a code edit to an auth / migration / secret / payments path is not
  applied to a real deliverable without a human `APPROVAL_DECISION`; the check is the
  **existing** engine + grant, run per file; taint and scope rules also now apply per file.
- **Recovery** — resume of an approved step re-runs the per-file pass deterministically and
  proceeds; `reconcile()` unaffected (no new persistent state — the flag is config).
- **Benchmark** — n/a.

## 7. Tunable starting values

- `per_file_policy` default: **False**.
- Risk globs: unchanged — `PolicyEngine.DEFAULT_RISK_GLOBS` (or the orchestrator's
  `self.policy.risk_globs`).
- `arguments["path"]` = the **relative** changed path from `out.changed_paths`.
- Per-file proposal `operation` = `"file.write"`, `required_capability` = `"fs.write"`.

## 8. Risks

- **A large refactor touches hundreds of files → hundreds of approval prompts.** Mitigated:
  only risk-class matches prompt; a normal refactor of ordinary files produces silent
  `ALLOW`s. If a change really does touch many auth files, one pause covers the whole step
  (step-scoped approval).
- **Risk-glob false positive on the temp-copy path.** Mitigated: V feeds the *relative*
  changed path, not the absolute copy path, so `/tmp/…/authTest/` can't accidentally match
  `*auth*`.
- **Double logging of `POLICY_DECISION`.** The step-level decision and the per-file decisions
  are both `POLICY_DECISION` events; the per-file ones carry `scope="per-file"` + `path` so a
  reader can tell them apart. Read models that count decisions may need to filter — noted in
  the milestone notes.
- **Opt-in means it is off by default.** Deliberate: the slice's existing tests assume the
  coarse check. A deployment that wants §14.1 fully enforced sets `per_file_policy=True`; the
  notes recommend it.

## 9. Deliverables

- `orchestrator.py` — `self.per_file_policy`; `_per_file_policy()`; the `_run_step` call.
- Test suite: the current 463 green, plus the per-file unit cases and the risk-class
  integration cases.
- `../nexus/MILESTONE_V_NOTES.md`.
- [STATUS.md](../STATUS.md), the
  [connective index](../requirements.md), and the
  top-level [README.md](../../README.md) updated: the §14.1 risk-class gate now applies to the
  files a build changes, not just the step.
