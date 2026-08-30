# Milestone E notes — what is real, what remains

Status against [../MILESTONE_E_PLAN.md](../MILESTONE_E_PLAN.md). **219 tests green.**
All 14 days built.

## Real after Milestone E

| Area | Module | Notes |
|---|---|---|
| Critic role | `app/services/agents/critic.py` | one-shot pass; fresh context sees contract + diff + target test, NOT the build narrative. `accept` / `revise` / `reject`. Advisory path fails open. |
| Critic wiring | `orchestrator._critic_pass` | **T0 runs first.** T0 fails + `reject` → one bounded Builder retry with findings. T0 passes + `reject` → logged `DISAGREEMENT`, task still completes (T0 authoritative). A correct diff can never be turned into a failure. Prompt has the "don't reject for style / non-minimal-but-correct" guardrail. Opt-in via `critic=` / `--critic`. |
| Structured messaging | `app/services/agents/messages.py` | `AGENT_MESSAGE` event at every hand-off: interpreter→planner→builder→verifier(+critic+verifier_t2+researcher). 8 typed intents. |
| Independent T2 verifier | `app/services/verify/verifier_t2.py` | model reconstructed-spec check from contract + diff alone; N independent contexts; unanimous pass → pass, split → fail + flag. |
| T2 wiring | `orchestrator._t2_pass` | advisory: T0 stays authoritative. `disagreement.resolve()` escalates to the user only when T0 passes, T2 fails, AND `risk_level ≥ medium` or a risky path. Otherwise logs `DISAGREEMENT` and completes. Projections keep T0 as `snap.verification` (gates COMPLETED); T1–T3 → `snap.advisory_verifications`. |
| Disagreement protocol | `app/services/agents/disagreement.py` | name conflicting claims → discriminating test (= deterministic T0) → synthesise with uncertainty → escalate if materially consequential. |
| Researcher role | `app/services/agents/researcher.py` | question → query plan → fetch **through the C egress broker** (default deny) → claim extraction from UNTRUSTED text → `EvidenceRecord`s + `Claim`s at `retrieved_web` trust. |
| Ladder rungs made real | `orchestrator._run_ladder` | `critic` rung: run the Critic on the stalled diff; a `reject` drives a re-plan carrying the findings. `research` rung: run the Researcher; claims feed the next re-plan's note. `inspect` / `change_strategy` / `ask_user` unchanged. |
| Composition rule | `app/services/agents/composition.py` | start from `{builder}`; add a role on explicit request, request phrasing ("second opinion", "research…"), ladder invocation, or a met `RolePerformance` §9 criterion. `COMPOSITION` event per task. |
| RolePerformance | `app/services/agents/performance.py` | in-memory per-`(role, task_class)` accumulation; `meets_promotion_criterion` = success delta ≥ 0.05 OR ≥ 1 defect / 10 tasks (needs ≥ 5 samples). |
| Single-vs-multi benchmark | `tests/benchmark/run_multiagent_bench.py` | runs each task `{builder}` vs `{builder + critic}` on the subscription; writes `MULTIAGENT_FINDINGS.md` with the promote/don't-promote call. |
| Event kinds | `AGENT_MESSAGE`, `CRITIC`, `DISAGREEMENT`, `ROLE_PERF`, `EVIDENCE`, `COMPOSITION` | |

## Not yet run / deferred

- **The single-vs-multi benchmark has not been run** — it needs your subscription
  (`python -m tests.benchmark.run_multiagent_bench tests/premise/tasks.real.json`). Until it
  runs, the Critic stays **opt-in**; `MULTIAGENT_FINDINGS.md` isn't generated yet. The
  promote-to-default decision is data-gated on that run.
- **Dedicated `research_web` / `doc_analysis` task orchestration** — the Researcher exists and
  is wired to the escalation ladder, but a task whose *whole point* is research still flows
  through the normal edit→verify path. A research-first orchestration is CD-research.
- **Real egress fetch** — the broker has still never fetched a live URL on this machine; the
  Researcher's integration test uses an injected opener. First real fetch will also be the
  broker's first real test.
- **`RolePerformance` is in-memory** — resets per process. Persistence is Milestone F
  territory (it belongs with the experience store).
- **No-peek parallel independent reasoning** — deferred; the ensemble-disagreement data
  should show first whether anchoring is the bottleneck.

## Deferred past E (unchanged)

Stronger-model routing (the ladder `stronger_model` rung) — Milestone G; experience
repository — Milestone F; RAG / vector KB — CD-rag.
