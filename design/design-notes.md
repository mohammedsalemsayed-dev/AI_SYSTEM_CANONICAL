# Design Tightening

Supplement to the authoritative spec. Purpose: **connect the components that are currently
described in isolation, and make concrete the parts that are currently vague.** Nothing in
the authoritative design is removed or narrowed. Every requirement stays active; this
document adds the wiring and the missing detail.

Subordinate to the Complete Claude-Code Spec. More specific than the context/traceability
files where they overlap. Numbers given here are starting values to recalibrate from data,
not constants to hard-code.

Contents:

1. End-to-end object flow (how a request threads through every component)
2. Component interfaces (the orchestrator seams)
3. Record relational model (how the six core records reference each other)
4. The three control loops and how they interact (router / escalation ladder / hardware modes)
5. Verification mechanism
6. Task taxonomy (`task_class`)
7. Routing and the benchmark loop
8. Experience promotion gates
9. Multi-agent composition — when each role is added
10. Build order and dependency graph (full scope, sequenced by prerequisite)
11. Budget, observability, memory retention
12. Prompt-injection / hostile-content model
13. Document map
14. Resolution of the hard problems
15. Delivery approach — Choice A vs Choice B
16. Prior art (what already exists as of 2026)

---

## 1. End-to-end object flow

Each stage receives canonical objects and emits canonical objects. Every emitted object is
written to the event log **before** the state transition it enables. This is the spine that
ties `state.py`, `contracts.py`, `orchestrator.py`, and every service together.

| Stage | Component | Receives | Emits | State on success | Gate to leave the state |
|---|---|---|---|---|---|
| capture | Conversation / API | user message | `OriginalRequest{id, text, ts, attachments}` — immutable | `CREATED` | request non-empty |
| interpret | Interpreter | OriginalRequest + Project memory | `TaskContract` (draft) | `INTERPRETING` | contract has objective, >=1 success criterion, `task_class`, `required_evidence` |
| ambiguity | Interpreter | draft contract | finalized contract **or** `ClarificationRequest{questions[], why, options[]}` | `PLANNING` or `WAITING_FOR_USER` | `ambiguity` empty **or** user answered |
| compose | Orchestrator + Router | TaskContract | `RunPlan{roles[], route{model per role}, budget}` | (stays `PLANNING`) | Builder role present + a viable route exists |
| plan | Planner | TaskContract + RepoIndex | `Plan{steps[]:{id, intent, expected_artifact_delta, required_capability}}` | `PLANNING` | every step names a capability and an expected effect |
| preflight | Policy Engine + Capabilities | each step as `ActionProposal` | `PolicyDecision{ALLOW\|DENY\|REQUIRE_APPROVAL\|REQUIRE_VERIFICATION\|ESCALATE}` + `CapabilityGrant{scope, ttl}` | `EXECUTING` on first ALLOW | no step is DENY; required approvals obtained |
| execute | Builder + Execution adapter | ALLOWed `ActionProposal` + grant | `Observation{stdout, exit, artifact_refs[], events[]}` + `ArtifactVersion` | `EXECUTING` | — |
| progress | Progress service | Observation stream | `ProgressEvent{objective_delta, artifact_delta, test_delta, classification}` | `EXECUTING` or `STALLED` | classification not in {`STALLED`, `LOOP_RISK`} |
| verify | Verifier | TaskContract + artifacts + evidence | `VerificationRecord{tier, criteria[]:{verdict, evidence_ref}}` | `VERIFYING` | overall verdict = pass |
| settle | Orchestrator | VerificationRecord | `TaskResult` + one `ModelRunRecord` per role + optional `ExperienceCandidate` | `COMPLETED` / `FAILED` | — |
| checkpoint | Recovery service | every transition + artifact boundary | `Checkpoint{canonical_state, artifact_manifest, uncertain_external_actions[]}` | — | — |

**State transition function** (ties `state.py` to the rest): `transition(task, target)` succeeds
only if `target in ALLOWED[current]` **and** the gate predicate for `target` (column 6) holds.
Today `state.py` checks only the first condition.

---

## 2. Component interfaces

`orchestrator.py` takes `interpreter, planner, builder, verifier, policy, events` with no
declared protocol. The protocol:

```
Interpreter.compile(request: OriginalRequest, project_mem: ProjectMemory) -> TaskContract
Planner.plan(contract: TaskContract, repo: RepoIndex)                     -> Plan
Router.compose(contract: TaskContract, stats: RouteStats, hw: HardwareSnapshot) -> RunPlan
Policy.decide(proposal: ActionProposal, contract: TaskContract)          -> PolicyDecision
Capabilities.issue(step: PlanStep, contract: TaskContract)               -> CapabilityGrant   # scoped + TTL
Builder.execute(step: PlanStep, grant: CapabilityGrant, ws: Workspace)   -> Observation
Progress.observe(task_id, obs: Observation)                              -> ProgressEvent
Verifier.verify(contract: TaskContract, artifacts, evidence)            -> VerificationRecord
Recovery.reconcile(cp: Checkpoint, world: FilesystemState)              -> ReconcileDecision
Experience.observe(task_id, result: TaskResult)                         -> ExperienceCandidate | None
Events.emit(task_id, kind, payload)                                     -> None              # append-only; the one sink
```

**Rules that keep the design coherent:**

- Every component takes canonical objects + the event log. No component calls another
  component directly — only the Orchestrator wires them.
- Agents hold **no references to each other** (preserves independent viewpoints, D9). Agent
  A never sees agent B's conclusion until B's result is a canonical record.
- `Events.emit` is the only write path to canonical history. All records below are created
  by emitting an event.

---

## 3. Record relational model

`CORE_CONTRACTS.md` lists six records with no relationships. The graph:

```
OriginalRequest 1──1 TaskContract          (task_id; contract.original_request is a frozen copy)
TaskContract    1──* Plan                  (replan on recovery / strategy change; Plan.supersedes links them)
Plan            1──* PlanStep 1──1 ActionProposal 1──* Observation
Observation     1──* EvidenceRecord        (kind: test_result | build_output | artifact_diff | web_claim | measurement)
EvidenceRecord  *──* Claim                 (claim_refs; a Claim's trust_level = min trust of its evidence inputs)
ProgressEvent.evidence_refs        ──> EvidenceRecord
VerificationRecord.criteria[].evidence_ref ──> EvidenceRecord
ModelRunRecord.verification_result ──> VerificationRecord   (the link that makes a run "scored" — see §7)
ExperienceRecord.evidence         ──> { VerificationRecord, ProgressEvent[], ModelRunRecord[] }
Checkpoint.artifact_manifest[]    ──> ArtifactVersion
```

All IDs are ULIDs. Every record carries `task_id` and `ts`. The event log is the ordered
union of all record-creation events; every derived view (§11) is a fold over it.

---

## 4. The three control loops

Router, escalation ladder, and hardware modes all answer "what runs next" and currently read
as unrelated. They compose in a fixed order, evaluated each step:

1. **Hardware mode — admission filter, evaluated first.**
   `hardware/policy.py` produces a mode; the mode constrains composition and routing:
   - `NORMAL` / `EFFICIENT`: no constraint.
   - `CONSERVATION`: agent composition forced to single-agent; optional critic pass dropped;
     concurrency 1.
   - `PROTECTIVE` / `EMERGENCY`: new **local-model** steps paused; GPU-heavy steps **prefer
     cloud** (cloud offloads local heat — the earlier "prefer local under protective" was
     backwards); only already-running steps finish.
   This is the missing edge between `hardware/policy.py` and the orchestrator.

2. **Escalation ladder — decides *whether* to change approach.**
   Triggered by a `ProgressEvent` classified `STALLED` / `LOOP_RISK`, or a verify failure.
   Fixed order: `inspect -> change strategy -> critic pass -> targeted research -> stronger
   model -> user question`.

3. **Router — decides *which model*, for the (possibly new) approach.**
   `Router.compose(...)` is re-invoked only when the ladder says "change strategy" or
   "stronger model". Its choice is then clamped by the hardware admission filter and by
   `budget.remaining` (§11).

---

## 5. Verification mechanism

A **verification ladder**. The Verifier uses the strongest tier the task supports and records
which one.

| Tier | Name | What it is |
|---|---|---|
| T0 | Deterministic oracle | Contract names an executable check: tests pass, build succeeds, schema/format validates, diff applies, output matches a fixture. Run in a clean environment. |
| T1 | Differential / property | Behaviour preserved for refactors (corpus green before and after); invariants / round-trip properties for transforms. |
| T2 | Reconstructed-spec | Verifier gets **only** TaskContract + artifact + evidence refs, independently derives pass/fail per success criterion, cites the evidence location for each. |
| T3 | Human gate | No T0–T2 check exists and `risk_level` >= medium, **or** T2 Verifier and Builder disagree after one discriminating test. |

**Rules:**

- `COMPLETED` is reachable only at the highest tier the `required_evidence` supports.
- **"No oracle" is a contract defect, not a pass.** If the Interpreter cannot express any
  verifiable evidence, it adds success criteria during `INTERPRETING` or sets
  `risk_level: high` and routes the result to T3.
- `required_evidence` names the tier and the concrete check, e.g.
  `["T0: pytest tests/auth green", "T2: no new public API surface"]`.

**Verifier independence:** separate model context, separate sandbox instance; sees
`original_request`, `TaskContract`, artifact refs, evidence refs; does **not** see the
Builder's reasoning, self-assessment, or agent chat. Emits
`VerificationRecord{tier, criteria[]:{id, verdict, evidence_ref}, overall, discriminating_tests_run[], residual_uncertainty}`.

**Coding tasks — the standard path:** Builder authors/extends a test per acceptance
criterion; Verifier judges **adequacy** (test fails on a deliberately mutated variant;
exercises the boundary; no incidental assertions); Verifier runs the **full suite in a fresh
checkout**.

---

## 6. Task taxonomy

`task_class` — assigned by the Interpreter during `INTERPRETING`, recorded on the
`TaskContract`, **immutable after `PLANNING`** (a material reclassification is a new
contract, handled like an objective change).

| class | meaning | mutates files | external I/O | deliverable |
|---|---|---|---|---|
| `qa_explain` | read-only question about code / docs / repo | no | no | answer |
| `code_edit_local` | bounded change, few files, has tests | yes | no | diff + tests |
| `code_edit_broad` | cross-cutting change / refactor | yes (many) | no | diff + tests |
| `debug` | diagnose + fix a reported failure | usually | no | diff + repro |
| `research_web` | gather + synthesise external sources | no | yes (fetch) | synthesis + sources |
| `doc_analysis` | reason over supplied documents | no | no | analysis |
| `authoring` | produce a DOCX / PPTX / report artifact | writes artifact | no | document |
| `planning_arch` | design / architecture reasoning | no | no | plan |
| `ops` | build / test / package / release actions | build outputs | maybe | artifacts + logs |

Rubric for assignment: does it mutate files; how broad; external I/O; deliverable type.

---

## 7. Routing and the benchmark loop

### 7.1 Bootstrap (no benchmark data yet) — static table

| task_class | default route | escalate to cloud when |
|---|---|---|
| `qa_explain` | local-small | user asks, or repo context exceeds local window |
| `code_edit_local` | local-coder | 2 failed verify cycles |
| `code_edit_broad` | local-coder + cloud review of the plan | plan touches > N modules or security-relevant paths |
| `debug` | local-coder | 2 failed hypotheses, no new evidence |
| `research_web` | local-reasoner (synthesis) | contradiction unresolved after cross-check |
| `doc_analysis` | local-reasoner | document exceeds local window |
| `authoring` | local-reasoner draft + cloud review pass | user marks high-stakes |
| `planning_arch` | cloud-frontier (this *is* the "second opinion" case) | — |
| `ops` | local-small (drives deterministic tools) | — |

### 7.2 Data-driven (once `ModelRunRecord`s accumulate)

- A `ModelRunRecord` is written automatically on every completed task.
- It **counts toward routing stats only if** `verification_result` is a `VerificationRecord`
  at tier >= T1 (the §3 link). Unverified runs are logged, not scored.
- Per `(task_class, model)`: verified success rate, median + p90 latency, median resource
  cost, estimated cost — trailing 90 days or last 50 runs, whichever is smaller.
- A model is **eligible** for a class only after >= 20 verified runs. Below that, the static
  table governs and the router explores deliberately (epsilon = 0.15).
- Score weights are **fit** (logistic regression: features -> verified success, quarterly),
  not hand-tuned. Nothing ships with magic-number weights unless tagged `provisional`.
- The active benchmark harness exists only to seed the 20-run threshold for a **new** model
  offline, by replaying a frozen task set with known T0 oracles.

---

## 8. Experience promotion gates

"Situation signature" = `{task_class, salient constraint tags, tool set used}`. Numbers are
starting values.

| Transition | Gate |
|---|---|
| `OBSERVED -> CANDIDATE` | Task completed at verify tier >= T1 and this `(signature, strategy)` pair is not already represented. Automatic. |
| `CANDIDATE -> VALIDATED` | Strategy replayed in **shadow mode** on >= 5 *distinct* tasks matching the signature, >= 80% verified success, median resource cost <= 1.2x the no-experience baseline for that class. >= 3 of the 5 from a different calendar week. |
| `VALIDATED -> PROMOTED` | Offline eval on a held-out set of >= 10 tasks for the signature: success >= baseline **and** the fixed ~30-task guardrail set does not drop > 2 percentage points aggregate. One human approval if the strategy touches security / policy / execution scope. |
| `PROMOTED -> MONITORED` | Automatic on promotion. Every later live use is an evaluation sample. |
| `MONITORED -> STALE` | Trailing-20-use verified success < 70%, OR < 3 uses in 60 days, OR a tool / model / path convention it names no longer exists. |
| any `-> QUARANTINED` | One catastrophic outcome (security check bypassed, data loss, verifier/human contradiction on a claimed success), OR trailing-5 success < 40%. Immediate; blocks the strategy from being suggested. |

- **Baseline** = the no-experience rolling stats from §7.2 for that `task_class`. Experience
  must beat baseline on success without being > 20% worse on cost. Measured improvement is
  rewarded, not novelty.
- **Rollback** (`PROMOTED -> QUARANTINED`) fires automatically on the catastrophic
  condition, no debounce. Exit from quarantine = manual review + re-entry at `CANDIDATE`.
- `ExperienceRecord` gains `guardrail_result` and `shadow_replay_log`.

---

## 9. Multi-agent composition — when each role is added

The design keeps all roles. This section says the **default composition** and the evidence
that promotes an optional role to default — so "use specialization only where it adds
measurable value" (D1) becomes an actual decision procedure, not a judgement call per task.

**Default runtime:** single agent (interpret -> plan -> build) + **one optional critic pass**
(fresh context; sees contract + artifact, not the build narrative) before verification.

| Role | Why it may add value | Promoted to default when… | If not promoted |
|---|---|---|---|
| Critic (one-shot) | catches spec violations / edge cases the Builder is blind to | on the guardrail set: verified success +>= 5 pts, OR >= 1 real defect caught per 10 tasks | critique folded into Builder self-review |
| Independent Verifier | separation prevents grading own homework | disagrees with Builder self-assessment on >= 5% of tasks AND those disagreements are majority-correct | Verifier = deterministic oracle only |
| Researcher (separate) | dedicated retrieval / eval context beats inline | `research_web` + `doc_analysis` verified success +>= 5 pts over inline | inline tool calls by the single agent |
| Planner (separate) | explicit plan artifact improves broad edits, enables preflight | `code_edit_broad` rework rate drops >= 20% | single agent emits a plan section |
| No-peek independent reasoning | parallel independent answers reduce anchoring | on triggering tasks, final verified success > sequential critic pass | sequential critic pass |
| Recovery / Reconciliation | crash consistency | always on — deterministic service, not an LLM role | — |
| Router / Scheduler | model + resource choice | always on — deterministic service | — |

**Protocol:** a role ships behind a flag, runs shadow or A/B for its first **50 eligible
tasks**, promotes to default only if its row's criterion is met, re-evaluated quarterly
against the guardrail set. A role that fails stays available for opt-in and for
escalation-ladder invocation.

**Orchestrator composition rule:** start from `{single agent}`; add a role if (a) its
criterion was historically met for this `task_class`, or (b) the task explicitly requests it
("second opinion"), or (c) an escalation-ladder step invoked it, or (d) hardware mode has not
forced single-agent (§4).

---

## 10. Build order and dependency graph

**Full scope is preserved.** Every capability in the authoritative docs gets built; this is
the order that guarantees each piece has its prerequisites. "Later" means "after its
dependency," never "maybe never."

### 10.1 Core milestones (from IMPLEMENTATION_PLAN, with dependency edges)

```
A Foundation      state machine + persistence + event log + contracts      → blocks everything
B Vertical slice  interpret→plan→build→verify→result on ONE class           → proves §1; blocks C–I
                  (start with code_edit_local)
C Security        capabilities, approvals, policy engine, sandbox           → needs A,B; blocks real code_edit_*, ops
D Recovery        checkpoints, idempotency, progress service, loop detect   → needs A,B; blocks long autonomous runs
E Multi-agent     Researcher, Critic, Verifier as roles; structured msgs    → needs B,D; each role gated by §9
F Memory/exp      scoped memory, retrieval, experience lifecycle            → needs E (verified runs to learn from); gates in §8
G Routing/HW      provider registry, benchmark DB, hardware modes           → needs B (ModelRunRecord data); static table until then
H Desktop shell   Tauri/React, event streaming, panels                      → needs A (event log); parallel from B onward
I Optimization    offline eval, canary, regression protection               → needs F,G
```

### 10.2 Capability domains (each is a tool-adapter package behind the §5-C boundary)

| Domain | Prerequisite | Unlocks |
|---|---|---|
| Repo intelligence + Git adapter | C | `code_edit_broad`, "what could this change break" |
| Research pipeline + evidence graph | E | `research_web` |
| RAG / knowledge base | research pipeline | source-grounded answers over the user's library |
| DOCX / PDF + PPTX pipelines | F (uses retrieval) | `authoring` |
| Godot / Unreal / Android adapters + expert modes | repo intelligence | engine-aware coding, expert prompt profiles |
| Automated model selection | G with >= 20 verified runs / class | data-driven routing replaces the static table |

### 10.3 Non-goals (already stated in the authoritative docs; restated, not newly narrowed)

- Single local user; no multi-tenant auth.
- No autonomous deploy / publish / spend — human approval always required (pasted spec 11, 12).
- Tools get least privilege, installed selectively (pasted spec 21).

Nothing else is a non-goal.

---

## 11. Budget, observability, memory retention

### 11.1 Cost / latency budget

- `TaskContract` gains `budget: {wall_clock_s, model_cost_usd, local_gpu_s}`. Interpreter
  fills defaults by `task_class`; user may override.
- Orchestrator tracks spend. At **80%** of any dimension it forces an escalation-ladder
  decision point (usually a user question). At **100%** it transitions to `WAITING_FOR_USER`
  with a spend summary. It never silently exceeds budget.
- Scheduler admission rejects any `ActionProposal` whose `estimated_resource_cost` would
  exceed the remaining budget.

### 11.2 Observability (all derived, all rebuildable from the event log)

- Per-task timeline: states, actions, evidence, spend.
- Per-model rolling stats: feeds §7.2 routing.
- System-health strip: the UI element.
- One structured log line per action, `correlation_id = task_id + action_id`.
- Metrics that must be visible: success rate by `task_class`, rework rate, verify-tier
  distribution, escalation frequency, budget-exhaustion rate, quarantine events.

### 11.3 Memory retention / eviction

| Memory | Lifetime / eviction |
|---|---|
| Working | Lives for the task; discarded on terminal state except entries promoted to Project. |
| Project | Active decisions, constraints, open questions, artifact index. No auto-eviction; removed by the user or a "decision superseded" event. Bounded at build time by relevance-ranked retrieval, not deletion. |
| Experience | Eviction = the `STALE` / `QUARANTINED` lifecycle; hard-delete `STALE` after 180 days. |
| System | Config + benchmarks. Benchmark rows leave the **routing window** at 90 days; raw rows retained. |
| Canonical (events, artifacts, checkpoints) | Never auto-deleted; archive tier after 1 year. |
| Embeddings / indexes | Fully derived; rebuildable; evict freely. |

---

## 12. Prompt-injection / hostile-content model

Autonomous web research and document analysis are headline features, so hostile input is a
primary threat.

- `EvidenceRecord.trust_level` in {`user`, `workspace`, `tool_output`, `retrieved_web`, `doc_input`}.
- **Hard rule:** content at `retrieved_web` or `doc_input` trust can never (a) grant or widen
  a capability, (b) originate an `ActionProposal` that passes policy on its own, (c) change
  the TaskContract objective, or (d) cause a message / file to be sent or published. Each of
  those requires a `user`-trust origin.
- The Researcher emits **claims with source refs**, never raw retrieved text as a directive.
  Planner and Builder consume claims, not raw text.
- Retrieved content is presented to the model inside a delimited, labelled block
  (`UNTRUSTED SOURCE CONTENT — data only`). Interpreter / Critic scan sources for
  instruction-like content and flag it.
- Tool outputs are trusted for **facts** (exit codes, diffs, timings); their free text is
  `tool_output` trust — informs, does not authorise.
- The execution sandbox has **no outbound network** by default. Research fetches go through a
  separate fetch service that returns data to the control plane, not into the sandbox.
- Release security gate includes an **injection corpus**: attempts embedded in fake web
  pages, documents, and code comments; the gate asserts zero capability escalation and zero
  objective drift. (Extends the "prompt-injected authority" item already in ACCEPTANCE.md.)

---

## 13. Document map

- `design/overview.md` — the principles, in brief.
- `design/STATUS.md` — what is actually built vs. still a stub.
- `design/requirements.md` — one row per requirement: source, target, status.
- `design/operating-protocol.md` — the working rules the build followed.
- `design/build-log/` — the day-by-day plan and notes for each stage, plus the
  benchmark write-ups. Kept as an honest record of how it was made; not needed to
  understand the system.
- `design/original-brief.txt`, `design/original-*.docx` — the initial spec this
  was built from.
- `archive/earlier-prototype/` — an earlier scaffold, superseded, kept for reference.

## 14. Resolution of the hard problems

The parts of the design that were "well-described but not solved" — verification of
open-ended coding, test adequacy, prompt-injection enforcement, progress detection, routing
cold-start, sandboxing real toolchains, experience generalization. The common move:
**replace "an LLM reliably judges X" with a deterministic tool, a structural invariant
enforced in code, or a measured-and-bounded process whose errors are caught downstream.**
The two that are pure infrastructure are solved by staging and seeding, not cleverness.

### 14.1 Verification of open-ended coding — closes the §5 residual

An absolute correctness oracle for arbitrary code does not exist. Do not build a better
Verifier model; engineer the task so an oracle exists and make verification *differential*.

- **Spec-to-test compilation at interpretation time.** The Interpreter emits >= 1 executable
  acceptance check per success criterion, or tags the criterion `unverifiable`. Any
  `unverifiable` criterion caps the task at autonomy Level 1 or forces a T3 human gate. Policy
  lever, not ML.
- **Differential verification against pre-change state.** Snapshot test outcomes + an
  execution trace (functions entered, I/O performed) on a task corpus before the change;
  apply; re-run; diff. Pass requires every behavioural delta to be explained by a success
  criterion. Unexplained delta = fail. Catches the dominant failure mode (unintended side
  effects) without needing absolute correctness.
- **Metamorphic relations** keyed by `task_class` (refactor => behaviour identical on the fuzz
  corpus; add-cache => cold == warm; parser change => format-then-parse round-trips). ~20
  relations cover most coding work.
- **Ensemble disagreement gate.** Verify in 3 independent contexts (varied seed/prompt, >= 1
  stronger model). Unanimous pass at tier >= T1 => pass; any disagreement => discriminating
  test or T3. Reduces false-confident pass, which is the failure that matters.
- **Continuous audit sampling.** 10% of `COMPLETED` tasks get human review regardless of
  tier, feeding a per-`task_class` Verifier-precision metric. Precision below threshold
  auto-drops that class's max autonomy.
- **Permanent T3 gate** for high-blast-radius paths (auth, migrations, money, concurrency,
  deploy) via a `risk_class` tag on globs, regardless of tier.

Residual: novel logic errors that pass all tests and leave no trace delta — contained by the
audit sample and the `risk_class` gate. Cost ~4 weeks (metamorphic library + trace-diff
harness); the autonomy cap is nearly free.

### 14.2 Test adequacy — closes the §5 "coding tasks" residual

Use deterministic tools, not the Verifier model.

- **Mutation engine scoped to the diff:** `mutmut` / `cosmic-ray` (Python), Stryker (JS/TS),
  PIT (JVM), mutating only the changed hunk + touched functions. Gate: new/changed tests kill
  >= 70% of mutants in the changed region (calibrate).
- **Coverage-delta pre-filter:** change must not reduce branch coverage of touched files; new
  code clears a coverage floor.
- **Model's residual role:** propose extra edge-case tests, which the mutation/coverage gates
  then validate. Model suggests; tools decide.

Residual: equivalent mutants, operator gaps — covered by the coverage + metamorphic + audit
seams. Cost ~2 weeks for a common adapter over 2–3 engines.

### 14.3 Prompt-injection enforcement — closes the §12 residual

- **Structural taint, not semantic taint.** Any model call with any untrusted content in
  context produces entirely untrusted output; no laundering. Trust rises only via an explicit
  logged human/deterministic step. Tag at the context-assembly boundary.
- **Freeze capabilities before untrusted content exists.** Planner derives steps and
  `required_capability` from the trusted TaskContract; Researcher / fetch runs after. Make it
  a hard invariant with a test (extends §1 ordering).
- **Policy Engine static check:**
  `any(arg.taint == untrusted) and operation in SIDE_EFFECTING => DENY`. Untrusted content may
  flow only into read / analyse / summarise operations that yield data artifacts.
- **Per-task egress allowlist**, default deny, enforced by the fetch broker; retrieved content
  returned raw and tagged untrusted.
- **The injection-scanning classifier stays as defence-in-depth** (flag + log); the system is
  safe even if it never fires, because of the structural rules.
- **Regression corpus** of ~200 payloads in fake pages / docs / comments / filenames / error
  text; CI asserts zero escalation and zero objective mutation; every incident is added.

Residual: a task that legitimately needs untrusted content to drive a side-effecting action —
explicit human-approved exception, never a general relaxation. Cost ~2 weeks
(taint + static check) + ~1 week (broker); highest security ROI in the project.

### 14.4 Progress / loop detection — closes the §1 progress-gate residual

Make it fully deterministic.

- **Progress credited only from hard signals:** test pass-count up, new passing test,
  build / lint / type-error count down, coverage up, a plan step's own acceptance check
  flipping green, first touch of a target file. `objective_delta` and `strategy_change` are
  removed as score inputs — they become critic/human context only.
- **Loop detection on action structure:** hash each action `(operation, normalized target,
  normalized args)`; flag same hash >= 3 of last 5, same normalized error signature >= 3,
  successive-diff edit-distance below threshold N times, budget fraction exceeded with
  non-increasing pass-count.
- **Novel-motion guard:** artifact delta with no test / behaviour delta for K steps =>
  `SLOW_PROGRESS`; another K => `STALLED`.
- **Mechanical escalation** drives the existing ladder.

Residual: legitimately slow debugging — per-`task_class` patience budget the user can extend,
plus a "no measurable progress for T, continue?" prompt instead of auto-kill. Cost ~1.5 weeks.

### 14.5 Routing cold-start — closes the §7 bootstrap residual

- **Seed offline:** a fixed 60–100 task suite with T0 oracles spanning `task_class`, run
  against every candidate model at install / upgrade — instant >= 20 verified runs per class.
- **Bayesian router:** each `(task_class, model)` has a Beta posterior seeded from the offline
  suite + rough published benchmarks; route by Thompson sampling (this replaces epsilon-greedy
  and the hand-tuned linear score).
- **Partial pooling:** hierarchical model so a model's `code_edit_broad` performance informs
  the `code_edit_local` prior; keeps estimates sane at low n.
- **Organic verified runs weighted 3x vs. offline**; refresh the suite quarterly from
  audit-sampled real tasks.

Cost ~3 weeks, dominated by suite curation; the router itself is ~1 week.

### 14.6 Sandboxing real toolchains — closes the §5-C / §10 CD-engines residual

Tiered isolation matched to task risk.

- **Tier A — ephemeral Linux container** (most backend / tooling / `code_edit_*` / tests):
  rootless Podman, network default-deny except the per-task egress allowlist, read-only repo
  mount + writable overlay, CPU / mem / pids / disk quotas, seccomp, dropped caps, size-capped
  artifact channel. Warm pool => < 5s to first action. Covers ~70% of tasks.
- **Tier B — Windows tasks** (.NET / WinUI / MSVC): Windows Sandbox `.wsb` or a throwaway
  Hyper-V VM restored from snapshot per task; host firewall scoped to the VM vNIC; warm pool
  hides the 10–30s spin.
- **Tier C — heavy engine builds** (Unreal, Android NDK, GPU): a dedicated snapshotted build
  box with GPU passthrough, not torn down per task. Two-phase: a hydrate pre-flight with a
  broader allowlist for dependency resolution, then network cut for the build. No secrets
  mounted; egress logged; results re-verified on a clean snapshot.
- **`capability` + `risk_class(paths)` -> minimum tier**, deterministic policy; tasks may
  request higher, never lower.
- **Secrets never enter any tier.** Signing / publishing runs in a separate human-approved
  broker step with the secret injected into that one call only.

Residual: Tier C is a genuine weak point — mitigation is the game-studio-CI norm: a VM you
would wipe without hesitation, nothing sensitive on it, publish / deploy behind a human.
Cost: A ~3 weeks (unblocks Milestones B–F), B ~2 weeks, C ~1 week setup + ongoing ops. Build
A now, B when Windows work starts, C when a real engine project appears.

### 14.7 Experience generalization — closes the §8 signature residual

- **Retrieve, don't classify.** Embed each experience as
  `(objective + constraints + task_class + tools + key plan steps)`; at planning time k-NN
  retrieve nearest priors with a hard `task_class` filter. No "salient tag" granularity dial.
- **Similarity threshold tau gates use** (start 0.85); below tau the Planner never sees it.
- **Advisory only.** A retrieved experience enters the Planner's context as a hint; the
  Planner still writes a fresh plan. A bad generalization costs tokens, not an execution.
- **Per-experience tau learning:** track outcomes in similarity bands
  (0.85–0.9, 0.9–0.95, 0.95+); if an experience only helps at >= 0.95, raise its personal tau.
- **Validation via retrieval, not exact match:** need 5 tasks where this experience was
  retrieved above tau with a recorded (shadow-mode) outcome.
- **Store negative experiences** and retrieve them the same way.

Cost ~2 weeks, mostly reuse of the RAG embedding store.

### 14.8 Order of work

| # | Fix | ~weeks | Slot rationale |
|---|---|---|---|
| 1 | Structural taint + policy static check + egress broker (14.3) | 3 | Highest security ROI; unblocks safe research / RAG |
| 2 | Tier-A sandbox (14.6) | 3 | Unblocks Milestones B–F |
| 3 | Spec->test + differential / metamorphic verify + audit sampling (14.1) | 4 | Linchpin — routing and experience both need verified outcomes |
| 4 | Mutation + coverage gates (14.2) | 2 | Cheap, off-the-shelf; makes 14.1's tests trustworthy |
| 5 | Deterministic progress / loop classifier (14.4) | 1.5 | Bookkeeping over the event log |
| 6 | Offline benchmark suite + Bayesian router (14.5) | 3 | Depends on 14.1 |
| 7 | Retrieval-based experience (14.7) | 2 | Lowest risk; depends on embedding store |

~18–19 focused weeks. None requires a research breakthrough — it requires choosing
determinism over model judgement at each decision point and staging the infrastructure so the
hard environments come last.

---

## 15. Delivery approach — Choice A vs Choice B

The authoritative design describes *what* to build. It does not say whether every subsystem is
built from scratch or composed from existing engines. Two approaches:

### 15.1 Choice A — full rebuild

Build every subsystem in-house: orchestrator, interpreter / planner / critic / verifier, the
policy + capability engine, the **agentic coding executor** (repo indexing, multi-file edits,
build / test running), git lifecycle, code review, sandbox tiers, tool adapters, research /
RAG, experience repository, hardware scheduler, local / cloud router, desktop shell.

- **Gain:** total control; no external agent dependency; the design's coherence is fully
  realized because nothing is borrowed.
- **Cost:** the commodity ~70% (repo intelligence + agentic editing) is most of Milestones
  B / C / E plus the repo-intel and git domains. Realistically 12+ months solo before it
  matches current tools on that 70%, then it must be kept current indefinitely.
- **Risk:** most effort reimplements what funded teams ship weekly, and that part decays
  relative to the frontier; long window where a user is better served by an existing tool;
  the keystone assumption (small local model quality on 8 GB VRAM) stays untested longest.
- **Choose when:** ownership / learning is itself the goal, or a hard constraint forbids any
  external agent engine.

### 15.2 Choice B — driver architecture (recommended)

Own the parts that define the product; **drive** existing engines for the commodity parts.

**The standalone app owns:**
desktop shell + main conversation + progressive-disclosure panels; the orchestrator and
multi-agent composition; the deterministic control plane (policy, capability, verification
ladder §5, recovery, budget §11.1); the research / RAG / evidence library; hardware-aware
scheduling + the local / cloud router (§4, §7); the experience repository (§8); memory and
traceability.

**It shells out to:**

| Concern | Driven engine | Boundary |
|---|---|---|
| Builder / Executor — repo edits, file ops, builds, tests | Claude Agent SDK (headless) or equivalent | receives a scoped `PlanStep` + `CapabilityGrant` + `Workspace`; returns `Observation` + `ArtifactVersion`; every action still passes the Policy Engine (§2) |
| Local-model tier | Ollama / llama.cpp | invoked by the router as one route among cloud routes |
| Document / presentation output | doc libraries (Docling, python-docx, python-pptx) | `task_class=authoring` artifacts |
| Document understanding / RAG ingestion | RAGFlow / LlamaIndex / Haystack | produces `EvidenceRecord`s at `retrieved`/`doc_input` trust |

**Effect on the milestones (§10):** B / C / E shrink from "build an agentic coding engine" to
"integrate and govern one." The `CD-engines` domains become adapter + prompt-profile work on
top of the SDK, not new executors. `CD-rag` becomes integration, not construction.

- **Gain:** still a comprehensive standalone product with your UX, agents, and control plane;
  the commodity 70% arrives maintained by someone else; effort concentrates on the
  differentiated 30% (control plane, research library, routing, experience loop).
- **Cost / risk:** dependency on the SDK's shape and lifecycle; impedance-matching between its
  execution model and the policy plane; inherits its provider assumptions.
- **Choose when:** the goal is a shipping product that is genuinely better on the
  differentiators, with interim value along the way, and cloud execution is acceptable.

### 15.3 Guard against the thin end of B

The failure mode of B is drifting into "a prettier chat window over Claude Code." The test:
**if the driven executor were removed, most of the differentiated design should still stand,
needing only another executor plugged in.** Keep the control plane and the research /
experience subsystems as the centre of gravity — not the conversation UI.

### 15.4 Both approaches start the same way

Build the dumb vertical slice first (§10 milestone B): one hardcoded model, `pytest` as the
only verification (T0 only), a subprocess in a temp directory instead of a sandbox, no
router, no experience, no progress detection. Get `request -> contract -> plan -> edit ->
test -> result` running end to end on one real `code_edit_local` task with real persistence.
Under Choice B the slice stands up faster because the Builder already exists — you are testing
*your* orchestration + control plane + routing against a real task within weeks, which is the
unknown that most needs retiring.

---

## 16. Prior art (as of 2026)

Every pillar of this design has been built before, often several times. The specific
combination — one consumer-desktop product unifying governed multi-agent coding +
hardware-aware local / cloud routing + a first-class research / RAG library + gated experience
learning + a "challenge my decisions" stance, built around an 8 GB-VRAM constraint — was not
found as a single existing product. Nearest whole-product analogues: Augment Code's
*Intent* / *Agent Teams*, and *Archon* for the harness half.

| Pillar of this design | Existing work to reuse or learn from | Implication |
|---|---|---|
| Multi-agent coding workstation, desktop, hybrid local/cloud | Augment Code *Intent* / *Agent Teams*; Orkas; OpenAI *Codex app* (local / worktree / cloud modes); Hermes / OpenClaw | The product category exists; study *Intent* as the closest reference. |
| Deterministic control plane / harness with validation gates, approvals, git worktrees | **Archon** (harness builder: agent steps + scripts + validation gates + approvals + isolated worktrees); n8n+Temporal-style local workflow engines | Evaluate Archon as reference or base before building §2 / §5 / §11 from scratch. |
| Hybrid cloud-orchestration + on-prem execution for sensitive data | Recognised enterprise pattern (vendor-hosted orchestration, in-network execution agent) | Your local/cloud split is a known architecture, not novel. |
| Experience repository / gated self-improvement | AI2Agent *Knowledge Repository*; Investigate-Consolidate-Exploit; Contextual Experience Replay; ExpWeaver; "self-improvement as a proposal process gated by checks" | §8 is a known pattern — copy an existing design rather than invent. |
| Hardware-aware GPU thermal / VRAM / power scheduling | "Agentic CPU-GPU Scheduling for Heterogeneous AI Workloads" (arXiv); thermal-reward schedulers; Hermes local/cloud routing; nvidia-smi power capping | §4 hardware modes: borrow from the research; the packaged "NORMAL→EMERGENCY" ladder is the thin original part. |
| Research / RAG / document understanding | RAGFlow, Docling (IBM), LlamaIndex, Haystack, Dify; CAJAL (local agent → publication-ready papers with verified citations) | Do not build. Integrate. |
| Wrapping the Claude Agent SDK as executor under custom orchestration | Explicitly a recognised 2026 pattern; multiple Claude Code orchestrators exist; SDK ships hooks / guardrails / session resumption and expects an external coordination layer | Choice B (§15.2) is a well-trodden path, not an experiment. |

**Takeaway:** this is not a green field. The differentiated contribution is the *integration*
plus two or three specific angles (8 GB-first, challenge-my-decisions, unified research +
creation surface). That is a reasonable basis for a project — and it is a direct argument for
Choice B, since the mature parts are already available to drive.

### 16.1 Sources

- 9 Best AI Coding Agent Desktop Apps in 2026 — augmentcode.com/tools/best-ai-coding-agent-desktop-apps
- Cloud vs Local Multi-Agent AI Platforms — augmentcode.com/tools/cloud-vs-local-multi-agent-ai-platforms
- Local-first AI agent orchestration — managed-code.com/blog-post/local-first-ai-agent-orchestration
- AI Agent Automation: The Local-First Workflow Engine — blog.brightcoding.dev (2026-05-02)
- Local vs Cloud AI Coding Agents — clawtab.cc/articles/local-vs-cloud-ai-coding-agents
- Self-Improving AI Agents: 9 Open-Source Frameworks — turingpost.com/p/agentselfimprovement
- AI2Agent (arXiv 2503.23948); Investigate-Consolidate-Exploit (arXiv 2401.13996); Rethinking Experience Utilization (arXiv 2605.07164)
- Agentic CPU-GPU Scheduling for Heterogeneous AI Workloads (arXiv 2607.22242)
- The GPU Guide to Running Private AI Agents Locally in 2026 — contabo.com/blog/running-private-ai-agents-locally
- 15 Best Open-Source RAG Frameworks in 2026 — firecrawl.dev/blog/best-open-source-rag-frameworks
- Claude Agent SDK: Agent Loops, Tool Calls, and Multi-Step Workflows — augmentcode.com/guides/claude-agent-sdk-agent-loops-tool-calls
- Claude Agent SDK Complete Guide — hidekazu-konishi.com/entry/claude_agent_sdk_complete_guide.html
