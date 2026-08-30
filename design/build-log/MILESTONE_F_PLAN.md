# Milestone F — Memory and Experience Plan


---

## 1. Purpose

The slice throws away everything it learns. The Interpreter gets an empty project memory;
`RolePerformance` from Milestone E resets per process; a strategy that worked last week is
re-derived from scratch. Milestone F adds durable, trust-filtered memory and the **controlled**
experience lifecycle — successful behaviour becomes reusable only through validated promotion,
never blind self-learning (D5).

Guiding rules:
- **D6** — canonical evidence stays recoverable; a lossy summary never becomes the only truth.
- **D5 / §8** — OBSERVED → CANDIDATE → VALIDATED → PROMOTED → MONITORED → STALE / QUARANTINED,
  each transition a numeric gate; promotion needs evaluation evidence; promoted experience
  stays monitored and can be withdrawn.
- **§14.7** — retrieve by similarity, don't classify; experiences are **advisory** hints to
  the Planner, never auto-applied.
- **§12** — retrieval is trust-filtered; `retrieved_web` / `doc_input` memory informs, never
  authorises.

## 2. In scope

| Concern | Milestone F implementation |
|---|---|
| Memory store | SQLite `memory` table (sibling to the event log). `MemoryRecord{id, task_id, tier, kind, content, scope, trust, version, ts, superseded_by}`. Append-mostly; supersession by id, not deletion. |
| Tiers + retention (§7.4) | **working** — lives for the task, dropped on terminal state except entries promoted to project; **project** — active decisions / constraints / open questions / artifact index, no auto-eviction, removed by the user or a "decision superseded" event; **experience** — the lifecycle below, hard-delete `STALE` after 180 days; **system** — config + `RolePerformance` + (later) benchmark stats, benchmark rows leave the routing window at 90 days but are retained. |
| Scoped retrieval | `retrieve(query, *, tiers, task_class=None, trust_min="workspace", k=8)` — keyword + recency + tier + trust filter (no embeddings yet — that is CD-rag). Never returns `QUARANTINED` experience; `STALE` only with an explicit flag. |
| Context builder | `build_context(task)` assembles the Interpreter/Planner working context: task summary, active project decisions, constraints, open questions, an evidence index, and scoped retrieval hits. Replaces the empty `ProjectMemory` the Interpreter currently gets. |
| Situation signature | `{task_class, sorted salient-constraint tags, tool set}`. Retrieval matches on `task_class` + tag overlap (the §14.7 similarity idea without embeddings). |
| ExperienceRecord | `{id, situation_signature, strategy, actions, outcome, evidence_refs, success_score, validation_state, scope, version, promotion_history[], monitoring_metrics{}}`. |
| Lifecycle gates (§8) | `OBSERVED→CANDIDATE`: task COMPLETED at verify tier ≥ T1, `(signature, strategy)` new. `CANDIDATE→VALIDATED`: replayed **shadow** on ≥ 5 distinct matching tasks, ≥ 80% verified success, median cost ≤ 1.2× baseline, ≥ 3 from different weeks. `VALIDATED→PROMOTED`: offline eval on ≥ 10 held-out, guardrail set (~30 canonical tasks) drop ≤ 2 pp, human approval if it touches security / policy / execution scope. `PROMOTED→MONITORED`: automatic. `MONITORED→STALE`: trailing-20 success < 70% OR < 3 uses in 60 days OR a named dependency gone. `any→QUARANTINED`: one catastrophic outcome OR trailing-5 < 40% — immediate, blocks suggestion, no debounce. |
| Experience capture | On a task reaching COMPLETED with verify tier ≥ T1, record an `OBSERVED` experience (signature + the plan's strategy + the diff/actions + the VerificationRecord as evidence); auto-advance to `CANDIDATE` if new. |
| Experience retrieval | At PLANNING: retrieve `PROMOTED` (and, flagged, `VALIDATED`) experiences whose signature matches; pass to the Planner as an advisory `AgentMessage(intent=PROPOSAL, sender=experience)`. The Planner still writes a fresh plan. Store `shadow_replay_log` outcomes. |
| Quarantine rollback | On a catastrophic outcome (security check bypassed, data loss, verifier/human contradiction on a claimed success), the strategy's experience is `QUARANTINED` automatically; exit requires manual review + re-entry at `CANDIDATE`. |
| RolePerformance persistence | Milestone E's in-memory `RolePerformanceStore` moves to system memory; the composition rule reads it across runs. |
| Events | `MEMORY`, `EXPERIENCE`, `EXPERIENCE_TRANSITION` event kinds; every lifecycle change is on the log. |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Embedding retrieval / vector store | CD-rag |
| Real offline-eval harness for `VALIDATED→PROMOTED` | Milestone I (F ships the gate + a stub eval that reads a fixture task set) |
| Benchmark DB rows in system memory | Milestone G (F ships the table; G fills it) |
| Cross-machine / shared memory | never (single-user, D-non-goal) |
| Learning from cloud hidden reasoning | never (D8 — only observable outputs) |

## 4. Component layout

```
app/services/memory/
  store.py        MemoryStore over SQLite; MemoryRecord
  retrieve.py     scoped, trust-filtered retrieval
  context.py      build_context(task) -> working context for Interpreter/Planner
app/services/experience/
  signature.py    situation_signature(contract, tools_used)
  lifecycle.py    ExperienceState + transition gates (numeric)
  store.py        ExperienceStore; capture / retrieve / advance
app/schemas/contracts.py   + MemoryRecord, ExperienceRecord (extend the prior stub)
app/events/log.py          + MEMORY / EXPERIENCE / EXPERIENCE_TRANSITION
app/orchestration/orchestrator.py   context builder feeds interpret+plan; experience capture on
                                    COMPLETED; experience retrieval at PLANNING; quarantine hook
tests/
  unit/         test_memory_store, test_retrieval, test_context_builder, test_signature,
                test_experience_gates, test_quarantine
  integration/  test_experience_capture, test_experience_advisory_at_planning,
                test_role_perf_persists
```

## 5. Work breakdown (~14 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `memory/store.py` (SQLite `memory` table, `MemoryRecord`, tiers, supersession) + `memory/retrieve.py` (keyword + recency + tier + trust filter; excludes `QUARANTINED`). Unit tests. |
| 3–4 | `memory/context.py` `build_context()`; wire into the orchestrator so the Interpreter and Planner get project decisions + constraints + retrieval hits instead of an empty memory. Integration: a project decision recorded on one task shows up in the next task's context. |
| 5–6 | `experience/signature.py`; `experience/lifecycle.py` — `ExperienceState` + every §8 transition gate as a unit-tested function. `ExperienceRecord` schema. |
| 7–8 | `experience/store.py` capture: on COMPLETED + verify tier ≥ T1, write `OBSERVED` → auto-`CANDIDATE` if new. `EXPERIENCE` / `EXPERIENCE_TRANSITION` events. Integration test. |
| 9–10 | Shadow-replay accounting + `CANDIDATE→VALIDATED` gate; a guardrail fixture set; stub offline eval + `VALIDATED→PROMOTED` gate (human-approval branch for security-touching strategies). |
| 11–12 | Experience retrieval at PLANNING → advisory `AgentMessage(sender="experience", intent="PROPOSAL")`; `shadow_replay_log`. `MONITORED→STALE` and `any→QUARANTINED` transitions + the automatic catastrophic-outcome rollback hook in the orchestrator. |
| 13 | Move `RolePerformanceStore` to system memory (persist per `(role, task_class)`); composition rule reads it across runs. |
| 14 | Regression; wire-up; `../nexus/MILESTONE_F_NOTES.md`; update [STATUS.md](../STATUS.md) + the connective index. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — memory store append + supersession + tier filter; retrieval excludes
  `QUARANTINED`, includes `STALE` only when flagged, respects `trust_min`; `build_context`
  shape; `situation_signature` stability (same contract → same signature; different
  `task_class` → different); each §8 gate (pass and fail sides); a catastrophic outcome →
  `QUARANTINED` immediately.
- **Integration** — a project "decision superseded" event removes the entry from later
  context; a task completing at T0 writes an `OBSERVED`→`CANDIDATE` experience; a matching
  later task at PLANNING gets an advisory experience `AgentMessage` and the Planner still
  emits its own `PLAN`; `RolePerformance` recorded in one process is visible in a fresh
  `Orchestrator` over the same DB.
- **Failure** — a `CANDIDATE` that fails the shadow-replay gate (< 80% or > 1.2× cost) does
  **not** advance; a `PROMOTED` experience whose trailing-5 success drops < 40% is
  `QUARANTINED` and no longer retrieved.
- **Security** — a memory entry at `retrieved_web` trust cannot raise a proposal's effective
  trust; retrieval with `trust_min="workspace"` never returns `retrieved_web` / `doc_input`
  entries.
- **Recovery** — `reconcile()` + `resume()` still work with the memory tables present; an
  interrupted task writes no experience (capture is COMPLETED-only).

## 7. Tunable starting values (§8; recalibrate from data)

- `OBSERVED→CANDIDATE`: verify tier ≥ **T1**.
- `CANDIDATE→VALIDATED`: **≥ 5** distinct shadow tasks, **≥ 80%** verified success,
  cost **≤ 1.2×** baseline, **≥ 3** from different weeks.
- `VALIDATED→PROMOTED`: **≥ 10** held-out, guardrail drop **≤ 2 pp**.
- `MONITORED→STALE`: trailing-**20** < **70%**, or < **3** uses / **60 d**.
- `any→QUARANTINED`: **1** catastrophic outcome, or trailing-**5** < **40%**.
- `STALE` hard-delete after **180 d**; benchmark rows leave the routing window at **90 d**.

## 8. Risks

- **Situation signature granularity** — too coarse promotes strategies that fail on siblings;
  too fine never gets 5 matching tasks. Without embeddings this is a real limitation; mitigate
  by keeping experiences **advisory only** (a bad match costs planner tokens, not an
  execution) and by tracking per-experience outcome bands.
- **Shadow replay needs volume** — on a single-user machine you may never get 5 matching
  tasks in a signature within the window; `CANDIDATE` may be as far as most experiences get.
  That is acceptable — the value is still "here's a hint", and promotion is a bonus.
- **Offline eval is a stub** — `VALIDATED→PROMOTED` can't be fully exercised until Milestone I;
  F ships the gate and a fixture-backed stub so the state machine is complete and tested.
- **Memory as ceremony** — keep project memory to real decisions / constraints / open
  questions; do not log every internal step into it.
- **Quarantine false trigger** — a single flaky "catastrophic" reading permanently benches a
  good strategy. Mitigate: the catastrophic conditions are narrow (security bypass, data
  loss, verified-success contradiction), and exit-from-quarantine is a manual review, not a
  dead end.

## 9. Deliverables

- `MemoryStore` + scoped retrieval + `build_context`; `ExperienceStore` + signature +
  lifecycle with all §8 gates; experience capture on COMPLETED, advisory retrieval at
  PLANNING, automatic quarantine rollback; `RolePerformance` persisted to system memory.
- Test suite: the current 219 green, plus unit (store / retrieval / context / signature /
  gates / quarantine) and integration (capture / advisory / persistence / superseded
  decision).
- `../nexus/MILESTONE_F_NOTES.md`.
- [STATUS.md](../STATUS.md) and the
  [connective index](../requirements.md) updated:
  "Hierarchical memory", "Experience repository", "Learn from validated cloud outputs" move
  toward FOUNDATION.
