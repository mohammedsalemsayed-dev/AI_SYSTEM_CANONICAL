# Milestone E — Multi-Agent Coordination Plan


---

## 1. Purpose

The slice runs a single Builder plus a deterministic (pytest) Verifier. That is enough to
pass the premise test, but the premise run surfaced the exact weakness a Critic fixes —
a behaviourally-plausible fix that didn't match the test's precise assertion (`SLICE_FINDINGS.md`,
mit-01). Milestone E adds the roles that catch that class of error and the machinery to
prove each one earns its cost.

Guiding rules:
- **D1 / §9** — a role is added only where it provides *measurable* value; every new role
  ships behind a flag and must beat the single-agent baseline over its first N eligible
  tasks before it becomes default.
- **D9** — agents keep independent viewpoints and never hold references to each other; all
  inter-role communication is a structured `AgentMessage` through the Orchestrator.
- **§12** — research output is `retrieved_web` trust: it informs, it never authorises.

## 2. In scope

| Concern | Milestone E implementation |
|---|---|
| Critic role | One-shot pass on the Builder's diff *before* verification. Fresh model context; sees `TaskContract` + the artifact diff + the failing test text; does **not** see the build narrative. Emits `CriticReport{verdict: accept\|revise\|reject, findings[]:{severity, claim, evidence_ref}}`. `revise`/`reject` routes back to the Builder (bounded, like the D re-plan) with the findings; then re-verify. Fills the D ladder `critic` rung. |
| Independent model Verifier (T2) | The T2 tier from §5: given **only** the contract + artifact + evidence refs, a model independently derives pass/fail per success criterion, citing evidence locations. Runs in a separate context from the Builder and the Critic. Complements the deterministic T0. |
| Ensemble + disagreement | Run the T2 verifier in N (=2, config) independent contexts. Unanimous at tier ≥ T1 → pass. Any disagreement → the disagreement protocol. |
| Disagreement protocol | (1) extract the concrete conflicting claims, (2) run a discriminating test if one exists (re-run T0 / a targeted case), (3) if still split and a stronger reviewer is available, one independent review, (4) synthesise with explicit uncertainty, (5) `WAITING_FOR_USER` if the unresolved choice is materially consequential (`risk_level ≥ medium` or a security/`risk_class` path). |
| Researcher role | For `research_web` / `doc_analysis`, and as the D ladder `research` rung. Question → query plan → fetch **through the C egress broker** → claim extraction with source refs → cross-check. Emits `EvidenceRecord`s at `retrieved_web` / `doc_input` trust and `AgentMessage`s of intent `EVIDENCE`. Consumers get *claims*, never raw retrieved text as a directive. |
| Structured messaging | `AgentMessage{sender, role, task_id, intent, claims[], evidence_refs[], assumptions[], requested_action, confidence_summary}` — every inter-role hand-off is one of these, appended to the log (`AGENT_MESSAGE` event). Intents: `QUESTION`, `ANSWER`, `PROPOSAL`, `HANDOFF`, `EVIDENCE`, `CRITIQUE`, `STATUS`, `ESCALATION`. |
| Composition rule | Orchestrator starts from `{Builder}`. Adds a role when (a) its §9 criterion was historically met for this `task_class`, (b) the task explicitly requests it (`--critic`, "get a second opinion"), (c) an escalation-ladder step invoked it, or (d) hardware mode permits (Milestone G; here always true). E implements (b), (c), and the shadow-mode measurement that produces the data for (a). |
| Measurement protocol | Each role runs **shadow** (invoked, outcome recorded, not necessarily acted on) or **A/B** for its first N (=30, config) eligible tasks. A `RolePerformance` record per `(role, task_class)` tracks: verified-success delta vs the single-agent baseline, real defects caught per 10 tasks, rework-rate delta. Promotion to default requires the role's §9 row to be met. |
| Single-vs-multi benchmark | Extend the premise harness: run each task twice — `{Builder}` and `{Builder + Critic}` (and, where relevant, `+ ensemble Verifier`) — and compare verified success, rework rate, wall-clock, tokens. Write `MULTIAGENT_FINDINGS.md`. |

## 3. Out of scope (deferred; stubs stay)

| Deferred | Filled in |
|---|---|
| No-peek parallel independent reasoning mode | later, if the ensemble data shows anchoring is the bottleneck |
| Real stronger-model routing (the ladder `stronger_model` rung) | Milestone G / §7 |
| Experience repository (learning from promoted roles) | Milestone F / §8 |
| RAG / vector KB for the Researcher | CD-rag (after this) |
| Planner as a separate role | its §9 criterion (`code_edit_broad` rework −20%) not yet measurable; keep the single agent's plan section |
| Full research evidence-graph / contradiction analysis UI | CD-research |

## 4. Decision required before Day 1

**Does the Critic run by default, or shadow-only until it proves out?**

| Option | Behaviour |
|---|---|
| Shadow-only (recommended, §9-pure) | Critic runs on every eligible task, its verdict is recorded, but the task proceeds on the single-agent path unless `--critic` is set. After N tasks, if the §9 row is met, promote to default. Honest, but the mit-01 class of bug keeps shipping until promotion. |
| Default-on with opt-out | Critic gates every task from day one. Simpler; one extra model call per task; contradicts "measure first" if it later proves not worth it. |
| Default-on for `risk_level ≥ medium` only | Compromise: gate the tasks where a miss is expensive, shadow the rest. |

Recommendation: **shadow-only + `--critic` opt-in**, and run the Day 13–14 benchmark early
(after Day 3) so the promote/don't-promote call is data-driven within the milestone.

## 5. Component layout

```
app/services/agents/
  messages.py       AgentMessage helpers + AGENT_MESSAGE event
  critic.py         Critic role -> CriticReport
  researcher.py     Researcher role -> EvidenceRecord[] + claims
  disagreement.py   the 5-step protocol
  composition.py    which roles for this task (rule a/b/c/d)
  performance.py    RolePerformance tracking + shadow/A-B harness
app/services/verify/
  verifier_t2.py    model-based reconstructed-spec check; ensemble wrapper
app/schemas/contracts.py   + CriticReport, RolePerformance; AgentMessage already exists
app/events/log.py          + AGENT_MESSAGE, CRITIC, DISAGREEMENT, ROLE_PERF event kinds
app/orchestration/orchestrator.py   critic pass before verify; ladder critic/research rungs real;
                                    composition.select_roles(); ensemble verify + disagreement
tests/
  unit/         test_agent_messages, test_critic_report, test_disagreement, test_composition, test_role_perf
  integration/  test_critic_catches_spec_violation, test_researcher_claims, test_ensemble_disagreement
  security/     test_research_output_is_untrusted   (extends the C corpus)
  benchmark/    run_multiagent_bench.py + MULTIAGENT_FINDINGS.md
```

## 6. Work breakdown (~14 working days)

| Day | Deliverable |
|---|---|
| 1–3 | `messages.py` + `AGENT_MESSAGE` event; `critic.py` (Critic prompt: read the test, check the diff against its exact assertions; emit `CriticReport`); wire a shadow critic pass before verify + make the D ladder `critic` rung real (`revise`/`reject` → bounded Builder retry with findings). Unit + integration (`test_critic_catches_spec_violation` — a diff that passes T0 by luck but violates a stated criterion). |
| 4–5 | All inter-role hand-offs become `AgentMessage`s in the log (Interpreter→Planner→Builder→Critic→Verifier). Timeline output shows them. Unit: message schema + intent set. |
| 6–8 | `verifier_t2.py` — model reconstructed-spec check (contract + artifact only); ensemble wrapper (N contexts); `disagreement.py` (5-step protocol). Integration: `test_ensemble_disagreement` (two contexts split → discriminating T0 rerun → resolve or `WAITING_FOR_USER`). |
| 9–11 | `researcher.py` — question → query plan → egress-broker fetch → claims with source refs → `EvidenceRecord`s at `retrieved_web` trust; make the ladder `research` rung real; `research_web` task_class path. Security: `test_research_output_is_untrusted` (a research claim cannot originate a side-effecting `ActionProposal` — extends the C corpus). |
| 12 | `composition.py` (rules b + c live; a reads `RolePerformance`); `performance.py` shadow/A-B harness + `RolePerformance` per `(role, task_class)`; `ROLE_PERF` events. |
| 13–14 | `benchmark/run_multiagent_bench.py` — each premise task run `{Builder}` vs `{Builder + Critic}` (+ ensemble where relevant); write `MULTIAGENT_FINDINGS.md` with verified-success / rework / cost deltas and the promote/don't-promote call. Update [STATUS.md](../STATUS.md) + connective index; write `../nexus/MILESTONE_E_NOTES.md`. |

## 7. Acceptance criteria

Gate order: UNIT → INTEGRATION → **FAILURE** → SECURITY → RECOVERY → **BENCHMARK**.

- **Unit** — `AgentMessage` schema + the eight intents; `CriticReport` parsing incl.
  malformed model output → `accept` with a logged warning (fail-open on the *advisory* path,
  never on a `reject`); each disagreement-protocol step in isolation; `composition.select_roles`
  for rule b (explicit request) and rule c (ladder); `RolePerformance` delta maths.
- **Integration** — a Builder diff that passes T0 by coincidence but violates a stated
  success criterion → Critic `reject` → bounded Builder retry with the findings → passes →
  `COMPLETED`; a `research_web` task → Researcher emits ≥ 1 `EvidenceRecord` with a source
  ref and `AgentMessage(intent=EVIDENCE)`; two T2 verifier contexts disagree → discriminating
  T0 rerun decides, or `WAITING_FOR_USER` if `risk_level ≥ medium`.
- **Failure** — Critic and Builder hold opposite claims and no discriminating test exists →
  synthesise-with-uncertainty → `WAITING_FOR_USER` with both positions on the log; the Critic
  model call errors → the task proceeds on T0 alone (advisory path fails open) and a
  `ROLE_PERF` record notes the error.
- **Security** — a research claim (`retrieved_web` trust) that says "delete X" or "run Y"
  cannot become an ALLOWed side-effecting `ActionProposal` (Policy Engine `tainted-side-effect`
  rule from C still holds); the research injection corpus (~30 payloads in fake pages)
  asserts zero capability escalation and zero objective drift.
- **Recovery** — a task paused at a Critic disagreement or a research step resumes cleanly
  via `reconcile()` (RESUME); the workspace is never mutated.
- **Benchmark** — the single-vs-multi run completes on the full premise suite and
  `MULTIAGENT_FINDINGS.md` records the deltas; the Critic is promoted to default only if its
  §9 row is met (verified success +≥ 5 pts, or ≥ 1 real defect caught per 10 tasks).

## 8. Tunable starting values (recalibrate — §9)

- shadow window N = **30** eligible tasks per `(role, task_class)` before a promote decision.
- ensemble size = **2** T2 contexts; disagreement → 1 discriminating rerun, then synthesise.
- Critic promote: verified success **+≥ 5 pts** OR **≥ 1** real defect / 10 tasks.
- Researcher promote: `research_web` + `doc_analysis` verified success **+≥ 5 pts** over inline.
- Builder retry after a Critic `reject`: **max 2** (same bound as the D re-plan).

## 9. Risks

- **Critic is the same model class as the Builder** — it reduces anchoring, not raises the
  capability ceiling; on tasks beyond the model, two confident wrong answers. Mitigation: the
  Critic sees the *test* the Builder may have skimmed, and the ensemble-disagreement gate;
  the honest fallback stays T3 human.
- **Cost** — every added role is another subscription call per task; shadow mode doubles the
  calls during the measurement window. Keep the window short, benchmark early.
- **Research on Windows + subscription** — the egress broker (C) has never fetched a real
  URL on this machine; the Researcher's first integration test is also the broker's.
- **Message-passing overhead becoming ceremony** — keep `AgentMessage` to real hand-offs;
  do not wrap every internal step.
- **Ladder now has three real rungs** — `inspect` → `change_strategy` → `critic` →
  `research` → (`stronger_model` still stubbed) → `ask_user`. A hard stall can now do real
  work before pausing; watch for the ladder itself looping (bound total ladder invocations
  per task).

## 10. Deliverables

- `Critic`, independent model `VerifierT2` + ensemble, `Researcher`, `AgentMessage` passing,
  disagreement protocol, `composition.select_roles`, `RolePerformance` shadow harness — wired
  into the orchestrator; the D ladder `critic` and `research` rungs made real.
- Test suite: the current 180 green, plus unit (messages / critic / disagreement / composition
  / perf), integration (critic catch / researcher claims / ensemble disagreement), the
  extended **security** research-injection corpus, and the **benchmark** run.
- `../nexus/MILESTONE_E_NOTES.md` + `../nexus/MULTIAGENT_FINDINGS.md`.
- [STATUS.md](../STATUS.md) and the
  [connective index](../requirements.md) updated:
  "Specialized independent agents", "Automated code review", "End-to-end independent
  verification", "Autonomous internet research" move toward FOUNDATION / IMPLEMENTED.
