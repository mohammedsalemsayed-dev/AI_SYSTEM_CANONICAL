# Milestone C notes — what is real, what remains

Status against [../MILESTONE_C_PLAN.md](../MILESTONE_C_PLAN.md). **133 tests green, 0 skipped**
(87 unit, 18 integration, 28 security). Docker Desktop 29.5 installed; the Tier-A sandbox
runs real containers and the "no host reach" test passes.

## Real after Milestone C

| Area | Module | Notes |
|---|---|---|
| Capability registry | `app/services/capability/registry.py` | tokens `fs.read/write/delete`, `shell.run`, `net.fetch`, `secret.use` -> operation sets; `SIDE_EFFECTING_OPS` |
| Capability issuance | `app/services/capability/issue.py` | one scoped `CapabilityGrant` per plan step, issued before execution; unknown token -> clean task failure |
| Grant scope math | `CapabilityGrant` methods | `covers_path` (traversal / sibling / absolute rejected), `is_expired`, `allows_operation`, `allows_host` |
| Policy Engine | `app/services/policy/engine.py` + `rules.py` | 7 ordered deterministic rules: capability-expired, operation-not-granted, path-out-of-scope, tainted-side-effect, egress-not-allowed, risk-class-approval, default-allow. Replaces `AllowAllPolicy` at the same call site. |
| Structural taint | `app/services/taint/boundary.py` + `check.py` | single tagging site (`assemble`), single side-effecting check (`blocks_side_effect`); `ActionProposal.trust` / `is_tainted` |
| Egress broker | `app/services/egress/broker.py` | per-task allowlist, default deny, results tagged `retrieved_web`, blocks recorded |
| Approvals | orchestrator `resume(task_id, approval=...)` | `REQUIRE_APPROVAL` -> `APPROVAL_REQUEST` + `WAITING_FOR_USER`; `approve` resumes execution, `deny` fails; state machine gained `EXECUTING <-> WAITING_FOR_USER` |
| Secret isolation | `app/services/secrets/store.py` | env-backed `SecretStore` (`SLICE_SECRET_*`); `scrub_env` strips secret-shaped keys and exact-value matches; both sandbox backends scrub before launch |
| Audit | new `EventKind`s + projection fields | `CAPABILITY_GRANT/DENY`, `APPROVAL_REQUEST/DECISION`, `EGRESS_BLOCKED`, `TAINT_BLOCKED`; snapshot carries `capability_grants`, `policy_decisions`, `taint_blocks`, `pending_approval`, `approved_steps` |
| Security gate | `tests/security/` | 26-case injection/abuse corpus + path-traversal battery + end-to-end objective-preservation; UNIT->INTEGRATION->FAILURE->**SECURITY**->RECOVERY |
| Sandbox seam | `app/services/sandbox/` | `SandboxRunner` protocol; `DockerSandbox` (real, arg-verified by unit test); `SubprocessSandbox` dev-only fallback that refuses `allow_non_isolated=False`; `select_runner(require_isolation=)`; Verifier T0 routes pytest through it |

## Tier-A sandbox — validated

Docker Desktop is installed and the runner image built:

```bash
cd milestone_b
docker build -t slice-sandbox:pytest app/services/sandbox/images/pytest-runner
python -m app.services.sandbox.docker_backend --selftest        # -> "sandbox ok"
```

`select_runner(require_isolation=...)` now returns `DockerSandbox`; the Verifier T0 pytest
run executes in a container with `--network none`, read-only rootfs + tmpfs, cgroup cpu/mem/
pid limits, all caps dropped, `no-new-privileges`. `test_sandboxed_pytest_has_no_network`
confirms a sandboxed test cannot reach `example.com`.

Remaining niceties (not blockers):
- CLI real-run guard: pass `require_isolation=True` to `VerifierT0` for `SLICE_LLM=anthropic`
  / tainted runs so the non-isolating fallback is refused if Docker is ever down.
- The image rebuilds are manual; a `make sandbox-image` or a check-on-startup would help.

## Deferred past Milestone C (unchanged from the plan)

Tier-B (Windows) and Tier-C (engine) sandboxes; progress/loop detection (Milestone D);
recovery reconciliation beyond `resume`; experience repository (F); multi-agent runtime (E);
verification tiers T1-T3; model router / local tier (G); PostgreSQL/Redis; desktop shell
and an approvals UI; granular per-operation `ActionProposal`s (the current one is coarse —
one proposal per step under the step's capability).
