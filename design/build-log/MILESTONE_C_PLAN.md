# Milestone C — Security and Authority Plan


---

## 1. Purpose

The slice ([MILESTONE_B_PLAN.md](MILESTONE_B_PLAN.md)) proved the loop composes. It runs
every action through `AllowAllPolicy` and executes task code (pytest, build steps) as an
unsandboxed host subprocess. Milestone C makes the control plane real, so a write-capable
agent can run against an actual repository — with untrusted content in the loop — without
the model being able to widen its own authority or reach the host.

C fills the seams named in [../nexus/README.md](../../nexus/README.md): the policy +
capability engine, the sandbox tier, and (new) structural taint, an egress broker, secret
isolation, and the Security acceptance gate.

Guiding rule ([design-notes.md](../design-notes.md) §4, §14.3): **the LLM proposes;
deterministic code decides.** No policy decision is a model call. Capabilities are frozen
from the (trusted) Plan *before* any untrusted content is fetched.

## 2. In scope

The [design-notes.md](../design-notes.md) §1 flow, with the `preflight` and `execute`
stages made real:

| Concern | Milestone C implementation |
|---|---|
| Capabilities | A capability registry maps tokens (`fs.read`, `fs.write`, `shell.run`, `net.fetch`, `secret.use`) to an operation set + default constraints. The Orchestrator issues one `CapabilityGrant{scope_path, operations[], network_allowlist[], ttl_s}` per plan step from `step.required_capability`, **before** execution. |
| Policy Engine | Deterministic rule set over `(ActionProposal, TaskContract, CapabilityGrant, taint)` -> `PolicyDecision`. Rules: operation ∉ grant -> DENY; target path ⊄ grant scope -> DENY (traversal); any tainted arg + side-effecting op -> DENY (§14.3); side-effecting op on a `risk_class` path -> REQUIRE_APPROVAL; `net.*` to a host ∉ allowlist -> DENY; else ALLOW. Replaces `AllowAllPolicy`; the orchestrator call site is unchanged. |
| Structural taint | Trust tag at the context-assembly boundary: any model call with non-`user` content in context yields entirely `untrusted` output; no laundering (§14.3). Args derived from `untrusted` output carry the tag. Trust rises only via a logged human/deterministic step. |
| Egress broker | Per-task allowlist derived from the Plan; default deny. `net.fetch` goes through the broker, which enforces the allowlist and returns raw bytes tagged `retrieved` / `untrusted`. Nothing else in execution has network. |
| Tier-A sandbox | `SandboxedRunner.run(cmd, workdir, network=False, cpu/mem/pids/disk limits, wall timeout)`. All **task-code execution** — the Verifier's pytest run and any `shell.run` step — happens inside it. File edits by the Builder stay on the host workspace copy (editing is not execution); every command the Builder wants to run is routed through the runner. |
| Approvals | `REQUIRE_APPROVAL` -> emit `APPROVAL_REQUEST`, transition to `WAITING_FOR_USER`. `resume(task_id, approval="approve"|"deny")` continues or fails. Reuses the existing state. |
| Secret isolation | An env-backed `SecretStore`. Secrets never enter the sandbox environment (scrubbed). A `secret.use` operation runs in a host-side broker step, human-approved, with the value injected into that one call only. |
| Audit | New event kinds: `CAPABILITY_GRANT`, `CAPABILITY_DENY`, `APPROVAL_REQUEST`, `APPROVAL_DECISION`, `EGRESS_BLOCKED`, `TAINT_BLOCKED`. All flow through the existing append-only log. |
| Security acceptance gate | An injection corpus (~30 payloads embedded in file contents, commit messages, filenames, error text) + a path-traversal battery. Asserts: zero capability escalation, zero objective mutation, zero side-effecting action on a tainted argument. |

## 3. Out of scope (still deferred; named seams kept)

| Deferred | Filled in |
|---|---|
| Tier-B (Windows) and Tier-C (engine build) sandboxes | §14.6; when Windows / engine work starts |
| Progress / loop detection | Milestone D / §14.4 |
| Recovery reconciliation (beyond `resume`) | Milestone D |
| Experience repository | Milestone F / §14.7 |
| Multi-agent runtime (critic, verifier ensemble) | Milestone E / §9 |
| Verification tiers T1–T3 | §5, §14.1 |
| Model router / local tier | Milestone G / §7 |
| PostgreSQL / Redis | Milestone A hardening |
| Desktop shell, approvals UI (CLI-only here) | Milestone H |
| Full policy DSL, capability-refresh, OS-user isolation, TLS egress interception, distributed secret manager | later, on demonstrated need (D18) |

## 4. Decision required before Day 7 — sandbox backend

Tier-A ([design-notes.md](../design-notes.md) §14.6) is "rootless Linux container".
The dev machine is Windows. Options, `SandboxedRunner` is the seam so the choice is swappable:

| Backend | Isolation | Cost | Notes |
|---|---|---|---|
| **Docker / Podman + pinned `python:3.12-slim`** (recommended) | Strong: namespaces, `--network none`, `--read-only` + tmpfs, cgroup limits, seccomp | Docker Desktop or `podman machine` (WSL2/Hyper-V) must be installed | Warm a container pool for < 5s start |
| WSL2 throwaway distro instance | Medium: separate kernel-user space, no cgroup polish | WSL2 only | Lighter than containers; weaker resource control |
| Hardened subprocess (rlimits wrapper, `PATH`/env scrub, deny-all `HTTP(S)_PROXY`) | **None — not isolation** | zero | **Dev only.** Never for `SLICE_LLM=anthropic` runs or tainted input. A stopgap for Days 1–6, which do not need a container. |

Recommendation: build Days 1–6 (capability / policy / taint / egress) on the hardened-subprocess
fallback, decide Docker vs Podman by Day 7, implement the real backend Days 7–9.

## 5. Component layout

Continues the `../nexus/` tree:

```
app/services/
  capability/
    registry.py        token -> operation set + default constraints
    issue.py           CapabilityGrant issuance from a PlanStep
  policy/
    engine.py          PolicyEngine (replaces stub.AllowAllPolicy)
    rules.py           one function per rule, each unit-tested
  taint/
    boundary.py        trust tagging at context assembly
    check.py           side-effecting-on-tainted static check
  egress/
    broker.py          per-task allowlist; net.fetch adapter
  sandbox/
    runner.py          SandboxedRunner protocol + BuildOutput-style result
    docker_backend.py  recommended backend (lazy import)
    subprocess_backend.py  hardened-subprocess fallback (dev only)
  secrets/
    store.py           env-backed SecretStore; scrub helper
app/schemas/contracts.py   + taint field on ActionProposal; ApprovalRequest/Decision
app/events/log.py          + new EventKind constants
tests/
  unit/         test_capability_*, test_policy_rules, test_taint_check, test_egress
  integration/  test_sandbox_isolation, test_approval_flow, test_secret_scrub
  security/     test_injection_corpus, test_path_traversal   (the Security gate)
  security/corpus/   ~30 payload fixtures
```

## 6. Work breakdown (~15 working days, one person)

| Day | Deliverable |
|---|---|
| 1–2 | Capability registry + `CapabilityGrant` issuance from the Plan; scope/TTL/operation-set. Orchestrator issues grants pre-execution and logs `CAPABILITY_GRANT`. Unit tests. |
| 3–4 | Policy Engine rule set (capability, path-traversal, tainted-side-effect, egress, `risk_class`->approval), each rule a unit-tested function. Replace `AllowAllPolicy`; keep the call site. `PolicyDecision.reason` is specific. |
| 5 | Structural taint: `taint` on `ActionProposal` args; context-assembly boundary marks `untrusted`; the side-effecting static check. Synthetic untrusted-input fixture. Unit tests. |
| 6 | Egress broker: per-task allowlist from the Plan, default deny, `net.fetch` returns raw + `untrusted`; `EGRESS_BLOCKED` events. Unit tests against a localhost stub server. |
| 7–9 | `SandboxedRunner` + chosen backend (Docker/Podman) + hardened-subprocess fallback. Route the Verifier T0 pytest run and `shell.run` through it: `--network none`, read-only rootfs + tmpfs, cpu/mem/pids/disk limits, wall timeout, env scrub, cleanup. Integration test: pytest runs sandboxed, host network unreachable, container removed. |
| 10 | Approvals: `REQUIRE_APPROVAL` -> `APPROVAL_REQUEST` + `WAITING_FOR_USER`; `resume(task_id, approval=...)`. Integration test both branches. |
| 11 | `SecretStore` (env-backed) + sandbox env scrub + `secret.use` host broker step (human-approved). Test asserts no secret reaches the sandbox env. |
| 12 | Audit: new event kinds wired; projections carry `capabilities`, `approvals`, `taint_blocks`. Timeline output updated. |
| 13–14 | Security gate: injection corpus (~30 payloads in file contents / commit messages / filenames / stderr) + path-traversal battery. Harness asserts zero escalation, zero objective mutation, zero side-effecting op on a tainted arg. Every failure found becomes a permanent corpus entry. |
| 15 | Full regression pass; wire everything into the orchestrator; update [STATUS.md](../STATUS.md) + the connective index; write `../nexus/MILESTONE_C_NOTES.md` (what is real, seams remaining). |

## 7. Acceptance criteria

Gate order ([ACCEPTANCE.md](../../archive/earlier-prototype/docs/testing/ACCEPTANCE.md)):
UNIT -> INTEGRATION -> FAILURE -> **SECURITY** -> RECOVERY. C is where SECURITY gets teeth.

- **Unit** — each policy rule in isolation (allow + every deny reason); capability scope math
  (in-scope, sibling-dir escape, `..` traversal, absolute path); `CapabilityGrant` TTL expiry;
  taint static check (tainted + side-effecting -> DENY; tainted + read-only -> ALLOW);
  egress allowlist match/miss.
- **Integration** — happy path still green with the real engine; a task needing `fs.write`
  outside its grant scope -> DENY -> `FAILED` with the reason on the log; pytest runs inside
  the sandbox with no network and is cleaned up; `REQUIRE_APPROVAL` -> `WAITING_FOR_USER` ->
  `resume(approve)` completes, `resume(deny)` fails.
- **Failure** — sandbox backend unavailable -> task `FAILED` with a clear message, never a
  silent host-subprocess fallthrough for a real/tainted run; egress broker down -> `net.fetch`
  fails closed.
- **Security** — the injection corpus: for every payload, assert final `objective` ==
  interpreted objective (no drift), no `CapabilityGrant` beyond what the Plan issued, no
  `POLICY_DECISION: ALLOW` for a side-effecting op with a tainted arg; path-traversal battery:
  every `..` / absolute / symlink escape is DENIED; secret scrub: sandbox `env` contains no
  key from the `SecretStore`.
- **Recovery** — `resume` on a task interrupted after a `CAPABILITY_GRANT` but before
  execution re-issues nothing and fails cleanly; the workspace is untouched.

## 8. Risks

- **Sandbox on Windows** — Docker/Podman may not be installed or permitted. Mitigation: the
  §4 decision, the `SandboxedRunner` seam, and the explicit rule that the subprocess fallback
  is refused for real / tainted runs.
- **Agent SDK inside vs outside the sandbox** — the Builder (Agent SDK) edits files on the
  host copy; only its command execution is sandboxed. If a future builder needs full
  in-sandbox operation, `SandboxedRunner` must also host the SDK — noted, not built here.
- **Taint plumbing with no real untrusted source yet** — C builds and tests the mechanism
  against a synthetic fixture; Milestone E is its first real exercise. Risk of the mechanism
  drifting from E's needs — keep the boundary point (context assembly) the single tagging site.
- **Approval UX in a headless CLI** — `WAITING_FOR_USER` + `resume(approval=...)` is
  deliberately minimal; a real UI is Milestone H.
- **Scope creep into a policy DSL** — resist (D18). Rules stay as unit-tested Python functions
  until a measured need for configurability appears.

## 9. Deliverables

- `PolicyEngine`, capability registry + issuance, structural taint + static check, egress
  broker, `SandboxedRunner` (chosen backend + fallback), `SecretStore`, approval flow — all
  wired into the orchestrator behind the seams B already exposed.
- Test suite: existing 47 still green, plus unit (policy/capability/taint/egress),
  integration (sandbox/approval/secret), and the **Security gate** (injection corpus +
  path-traversal battery).
- `../nexus/MILESTONE_C_NOTES.md` — what is real after C, what remains stubbed.
- [STATUS.md](../STATUS.md) and the
  [connective index](../requirements.md) updated:
  "Workspace + capability security", "Approval levels", "AI coding autonomy levels",
  "Prompt-injection defense" move toward FOUNDATION / IMPLEMENTED as earned.
