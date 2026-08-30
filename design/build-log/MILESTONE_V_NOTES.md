# Milestone V notes — what is real, what remains

Status against [../MILESTONE_V_PLAN.md](../MILESTONE_V_PLAN.md). **471 tests green.**
All 7 days built. Closes a real §14.1 gap: the risk-class human-approval gate
(`*auth*`, `*/migrations/*`, `*secret*`, `*/payments/*`, `*.pem`, …) now applies to the
**files a build changes**, not just to the workspace root the step proposal carried.

## The gap

`_run_step` builds one `ActionProposal` per plan step with
`arguments={"path": ws, "intent": …}` — the workspace **root**. So `_paths_in()` returns
only `ws`, and `rule_risk_class_needs_approval` compares `ws` against the risk globs and
**never matches**. A `code_edit_local` task that rewrites `app/auth/login.py` or a DB
migration was applied to the deliverable with no `APPROVAL_DECISION`, contradicting §14.1.
`rule_path_out_of_scope` and `rule_operation_not_granted` were likewise blind to the actual
files.

## Real after Milestone V

| Area | Module | Notes |
|---|---|---|
| Opt-in flag | `Orchestrator.per_file_policy: bool = False` | Off → `_run_step` is byte-identical to Milestone U (an integration test pins this — a migration edit still sails through). A deployment that wants §14.1 fully enforced sets it `True`; **the notes recommend it.** |
| Per-file pass | `orchestrator._per_file_policy(task_id, contract, step, ws, grant, changed_paths, approved_steps, step_action_id)` | For each **relative** path in `out.changed_paths`: build `ActionProposal(operation="file.write", arguments={"path": rel}, required_capability="fs.write", workspace_scope=ws, idempotency_key=f"{task_id}:{step.id}:{rel}")` and call the **existing** `self.policy.decide(p, contract, grant)` with the step's own `CapabilityGrant`. Log every result as `POLICY_DECISION` with `{"scope": "per-file", "path": rel}`. `ALLOW` → continue; `REQUIRE_APPROVAL` → collect; `DENY`/other → log `TAINT_BLOCKED` if `rule == "tainted-side-effect"`, then `raise BuildError`. After the loop, if any collected and `step.id not in approved_steps` → `raise ApprovalPause(step_action_id, step.id, "<n> changed file(s) need approval (<rels>): <first reason>")`. |
| Call site | `_run_step`, right after `out = self.builder.execute(...)` | Guarded by `self.per_file_policy and out.exit_code == 0 and not out.error and out.changed_paths`, and runs **before** the `ArtifactVersion` / `ARTIFACT` / `OBSERVATION` logging — a pause or deny leaves no artifact for a step that never really landed. The builder works on the discardable workspace **copy**, so the changed files are thrown away with it. |
| Approval key | — | The `ApprovalPause` carries the **step proposal's** `action_id` (not a synthetic one), so `_step_id_for_action` resolves it to `step.id`, the `APPROVAL_DECISION` records `step_id`, and `resume(approval="approve")` re-runs the per-file pass with `step.id in approved_steps` → the `REQUIRE_APPROVAL`s are waved through and the task `COMPLETED`s. |
| Events | none new — reuses `POLICY_DECISION` (with a `scope`/`path` marker), `TAINT_BLOCKED`, `APPROVAL_REQUEST`/`APPROVAL_DECISION`. |

## Scope / security posture

- **No new rule, no new gate.** V calls `PolicyEngine.decide` with the step's grant, once per
  file, exactly as `_run_step` already does once per step. The risk globs are
  `PolicyEngine.DEFAULT_RISK_GLOBS` unchanged.
- **§14.1 now holds for builds.** An edit to an auth / migration / secret / payments path is
  not applied to a real deliverable without a human `APPROVAL_DECISION` (integration-tested:
  pause → approve → `COMPLETED`; the aborted step writes no `ARTIFACT`).
- **Defense in depth.** `rule_path_out_of_scope` and `rule_operation_not_granted` now also
  see each file — a write under a `fs.read`-only step, or a path escaping the grant scope, is
  a per-file `DENY` → `BuildError`.
- **Relative paths.** V feeds the relative changed path, so the temp-copy directory can't
  accidentally match a risk glob (e.g. a fixture dir named `authTest/`).
- **Deterministic.** No model call; a resumed approved step re-runs the pass identically.
  The flag is config — no new persistent state; `reconcile()` unaffected.

## Not yet real / deferred

- **Routing each write through `FsToolAdapter` / `ToolDispatcher` as it happens** — needs the
  Builder to *declare* writes instead of performing them (an interface change across
  `ScriptedBuilder` / `AgentSDKBuilder` / every test). V gets the security property — every
  file seen by the engine — without that rewrite; the write is checked from `changed_paths`
  after the fact, on the discardable copy, before anything is verified or promoted.
  Because the Builder is not step-scoped, a recovery / escalation re-plan that leads with an
  `fs.read` "inspect" step gets the plan's writes attributed to that read step. `_run_step`
  compensates: when the current step's grant lacks `file.write`, the per-file pass runs
  against `_plan_file_grant` — a grant over the union of the *current plan's* step
  capabilities (logged as its own `CAPABILITY_GRANT`, `step_id="plan"`). Risk-class,
  path-scope and taint checks are unchanged; a plan with no write step anywhere still DENYs.
- **Per-file approval granularity** — approval is step-scoped: approving the step approves
  all its files. A follow-up can thread a `{step_id: {path}}` set.
- **Content inspection** (secret scanning, license headers, diff linting) — a verifier-tier
  concern, not the policy engine.
- **`per_file_policy` default `True`** — left `False` so the slice's existing tests keep
  their coarse-check assumption; flip it in a deployment that wants §14.1 fully on.
- **Read-model decision counts** — the per-file `POLICY_DECISION` events carry
  `scope="per-file"`; a read model that counts decisions should filter on it.

## Deferred past V (unchanged)

Routing the Builder / the tool loop through a single dispatch path; parallel tool turns;
adapters beyond `shell`; an escalation ladder for the tool loop. Milestone A hardening
(Postgres / Redis); a real local model backend; secrets management; the native Tauri build;
subscription-gated harness runs.
