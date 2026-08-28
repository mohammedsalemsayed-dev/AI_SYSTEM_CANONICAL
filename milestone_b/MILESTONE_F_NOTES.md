# Milestone F notes — what is real, what remains

Status against [../MILESTONE_F_PLAN.md](../MILESTONE_F_PLAN.md). **254 tests green.**
All 14 days built.

## Real after Milestone F

| Area | Module | Notes |
|---|---|---|
| Memory store | `app/services/memory/store.py` | SQLite `memory` table, sibling to the event log. `MemoryRecord{id, task_id, tier, kind, content, scope, trust, version, ts, superseded_by}`. Append-mostly; `supersede(old_id, new)` chains by id, never deletes. Tiers `working` / `project` / `experience` / `system`. `drop_stale_experience_pointers()` for the 180-day hard-delete. |
| Scoped retrieval | `app/services/memory/retrieve.py` | `retrieve(store, query, *, tiers, task_class, trust_min="workspace", k=8, include_stale=False)` — keyword + recency + tier + trust filter, no embeddings (that is CD-rag). `_TRUST_RANK` orders `user > workspace > tool_output > retrieved_web > doc_input`; `trust_min="workspace"` can never return `retrieved_web` / `doc_input`. `QUARANTINED` experience is always excluded; `STALE` only with `include_stale=True`. |
| Context builder | `app/services/memory/context.py` | `build_context(store, request_text, task_class=None)` → a `PROJECT MEMORY` block: `ACTIVE DECISIONS` / `CONSTRAINTS` / `OPEN QUESTIONS` / `ARTIFACT INDEX` / `POSSIBLY RELEVANT`. Prepended to the workspace listing before both `interpreter.compile` and `planner.plan`. A superseded decision is gone from the next task's context. `MEMORY` event on read (`used: context`) and write (`used: write`). |
| Situation signature | `app/services/experience/signature.py` | `situation_signature(contract, tools_used)` → `"{task_class}\|tags={sorted salient tags}\|tools={sorted}"`. `salient_tags` scans objective + constraints + success criteria for ~40 markers (auth, boundary, off-by-one, null, cache, migration, parser, float, division, pagination, mutable, iterator, …). `signatures_match(a, b, min_tag_overlap=1)` = same `task_class` + tag overlap (or either side untagged). Deliberately coarse — a loose match costs planner tokens, not an execution. |
| Experience lifecycle | `app/services/experience/lifecycle.py` | `ALLOWED` transition map + one numeric gate function per §8 edge: `gate_observed_to_candidate` (verify tier ≥ T1, `(signature, strategy)` new), `gate_candidate_to_validated` (≥ 5 shadow tasks, ≥ 80% verified, median cost ≤ 1.2×, ≥ 3 distinct weeks), `gate_validated_to_promoted` (≥ 10 held-out, guardrail drop ≤ 2 pp), `should_go_stale` (trailing-20 < 70%, or < 3 uses/60 d, or dependency gone), `should_quarantine` (1 catastrophic, or trailing-5 < 40%). Every constant is a §8 starting value to recalibrate from data. |
| Experience store | `app/services/experience/store.py` | `ExperienceStore` over SQLite `experience`. `capture(signature, strategy, actions, evidence_refs, success_score, verify_tier)` → `OBSERVED`, auto-`CANDIDATE` when the pair is new and the gate passes. `retrieve(signature, states=("PROMOTED","MONITORED"))` — signature match, skips `QUARANTINED`. `try_validate()` / `try_promote(human_approved=)` run the gates; `try_promote` folds the stub eval, applies the security human-approval branch, and auto-advances `PROMOTED → MONITORED`. `record_use(verified=, catastrophic=)` updates trailing metrics and auto-quarantines / auto-stales. `add_shadow_result()`, `sweep_stale()`. |
| Stub offline eval | `app/services/experience/eval.py` | `GUARDRAIL_SET` — ~8 canonical guardrail tasks (a fixture; Milestone I brings real ones). `run_offline_eval(exp)` — deterministic: held-out count and guardrail drop derived from the experience's own shadow history. `promote_decision(exp, human_approved=)` — numeric §8 gate + `touches_security()` human-approval branch (auth / policy / capability / sandbox / egress / secret markers). |
| Orchestrator — advice | `orchestrator._experience_advice` | At `PLANNING`: `situation_signature` → `experience.retrieve(sig)` → for each hit `record_use(verified=True)` and emit `AgentMessage(sender="experience", role="experience", intent="PROPOSAL")` with the strategies + record ids as `evidence_refs`. The Planner still writes its own `PLAN`. No-op when `experience` is unset. |
| Orchestrator — capture | `orchestrator._capture_experience` | On a T0-pass `COMPLETED` (independent of the project-memory hook): strategy = the plan's step intents, actions = changed paths, evidence = the `VerificationRecord` id. Logs an `EXPERIENCE` event. |
| Orchestrator — rollback | `orchestrator.flag_catastrophic(task_id, reason)` | `any → QUARANTINED`, no debounce. Quarantines every experience surfaced for the task (read back from the `experience` `AgentMessage` `evidence_refs`), logging an `EXPERIENCE_TRANSITION` per hit. Auto-fires from `_t2_pass` when T2 contradicts a T0-passing result. Manual call is the hook for the other narrow signals (security bypass, data loss). |
| Persistent RolePerformance | `app/services/agents/performance.py` | `RolePerformanceStore(memory=…)` — `record()` persists the `RolePerformance` snapshot to system memory per `(role, task_class)` via `MemoryStore.record_role_perf`; `_get()` hydrates from `latest_role_perf` on first touch. A fresh store over the same DB sees the accumulated samples, so the composition rule reads performance across process runs. Backwards compatible: `memory=None` keeps the in-process behaviour. |
| Event kinds | `MEMORY`, `EXPERIENCE`, `EXPERIENCE_TRANSITION` | on `app/events/log.py`. |

## Not yet real / deferred

- **Embedding / vector retrieval** — retrieval is keyword + recency + tier + trust only.
  Similarity is the coarse signature match. Vector KB is CD-rag.
- **Real held-out offline eval** — `experience/eval.py` is a deterministic stub reading a
  fixture guardrail set; it derives held-out count and guardrail drop from the experience's
  own shadow log. The real harness (≥ 10 genuinely held-out tasks, ~30-task guardrail suite)
  is Milestone I. The `VALIDATED → PROMOTED` state machine is complete and tested against the
  stub.
- **Shadow-replay volume** — on a single-user machine a signature may never collect 5
  matching tasks within the window. `CANDIDATE` is an acceptable terminal state; the value is
  still "here's a hint," and experiences are advisory regardless of lifecycle state.
- **Benchmark rows in system memory** — the `system` tier and `record_role_perf` exist;
  routing / benchmark stats that live there are Milestone G.
- **Catastrophic auto-detection breadth** — only the T2-contradicts-T0-pass signal auto-fires
  `flag_catastrophic`. Security-bypass and data-loss detection still call it manually; wiring
  those to policy / sandbox outcomes is later work.
- **The single-vs-multi benchmark** (Milestone E) is still un-run and still gates the Critic
  promote-to-default decision — unchanged by F.

## Deferred past F (unchanged)

Stronger-model routing / hardware calibration — Milestone G; real offline-eval + canary +
regression harness — Milestone I; RAG / vector KB — CD-rag; cross-machine / shared memory —
never (single-user non-goal); learning from cloud hidden reasoning — never (D8, observable
outputs only).
