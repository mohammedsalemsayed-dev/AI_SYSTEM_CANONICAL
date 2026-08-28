# Implementation Status — Honest Boundary

> **Cross-reference**
> - Role: Honest built-vs-active boundary for the code foundation.
> - Authority: Status record; mirrors the `status` column of the connective index.
> - Upstream (consumes): [REQUIREMENT_TRACEABILITY.md](REQUIREMENT_TRACEABILITY.md).
> - Downstream (depended on by): coding-agent milestone selection.
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../DESIGN_TIGHTENING.md) — §10 build order and dependency graph.

The authoritative documents describe the complete target system.

The code foundation included in this package is intentionally marked as a foundation. It is NOT a claim that the complete target system is already implemented.

Implemented/scaffolded concepts:
- state-machine foundation;
- TaskContract / ActionProposal / AgentMessage foundations;
- workspace path guard;
- basic meaningful-progress detector;
- experience state lifecycle;
- basic hardware mode policy;
- simple route scoring foundation;
- recovery reconciliation skeleton;
- orchestrator skeleton;
- basic FastAPI health endpoints;
- basic futuristic React UI;
- initial invariant tests.

Still requiring real implementation:
- persistent PostgreSQL models/migrations;
- durable event log and projections;
- Redis/queue strategy where justified;
- real local/cloud provider adapters;
- empirical benchmark harness and registry;
- capability issuance/expiry and policy engine;
- approvals and authentication/authorization;
- secrets management;
- hardened OS/container sandbox execution;
- real artifact/version tracking;
- checkpoints and crash recovery integration;
- structured multi-agent runtime;
- research/retrieval/source evaluation;
- repository intelligence and Git adapter;
- tool adapter ecosystem;
- RAG/indexing;
- document/presentation pipelines;
- full telemetry and target-machine calibration;
- WebSocket/event streaming;
- complete desktop shell integration;
- comprehensive test gates and fault injection.

A coding agent must not "simplify away" these items because they are absent from the initial scaffold.

## Milestone B slice — `milestone_b/` (Days 1–9 built; Day 10 pending)

A running vertical slice: `request -> TaskContract -> Plan -> edit (driven builder) ->
T0 verify -> result`, over an append-only SQLite event log with snapshot projections.
47 tests green (35 unit, 12 integration). Offline demo: `python -m app.cli.demo`.

Now real (slice scope only — see `milestone_b/README.md` for the named seams that remain
stubbed):
- append-only event log + deterministic replay/projections;
- state machine **with transition-gate predicates** (DESIGN_TIGHTENING §1);
- Interpreter (request -> contract) with the "no verifiable T0 -> WAITING_FOR_USER" rule;
- `task_class` taxonomy applied at interpretation;
- Planner (contract -> plan);
- Builder seam — `ScriptedBuilder` (tests) and `AgentSDKBuilder` (Choice-B executor);
- Verifier **T0 tier** — fresh checkout, apply diff, run the named pytest target;
- policy-decision + capability-grant **seam** (stub: allow + log);
- workspace-copy isolation (temp dir; not a hardened sandbox);
- `resume()` light recovery (interrupted task fails cleanly, workspace untouched).

Day 10 (premise test) — **done, premise holds**. Real loop = Agent SDK for
Interpreter/Planner/Builder on a Claude Pro subscription + VerifierT0 in the Docker Tier-A
sandbox. Two runs: 10 seeded single-function bugs (10/10 correct) and 5 real `more-itertools`
bug-fix commits (4/5 correct; the 1 miss was a behaviourally-right fix with the wrong exact
assert message, **caught by T0**, never marked COMPLETED). Combined **14/15 diffs correct,
zero false positives, 15/15 unaided T0 criterion**. Per MILESTONE_B_PLAN.md §7 the premise
holds. Surfaced weakness: the Builder doesn't reliably read the failing test before editing
(§14.1 prompt-tuning, not a blocker). See `milestone_b/SLICE_FINDINGS.md`.

## Milestone C — security and authority (`milestone_b/`, days 1–15; sandbox runtime pending)

132 tests green + 1 skipped. See `milestone_b/MILESTONE_C_NOTES.md`.

Now real (slice scope):
- capability registry + per-step scoped `CapabilityGrant` issuance (frozen from the Plan);
- deterministic Policy Engine (7 ordered rules) replacing the allow-all stub;
- structural taint (single tagging site + single side-effecting check);
- egress broker (per-task allowlist, default deny, tagged results);
- approval flow — `REQUIRE_APPROVAL` -> `WAITING_FOR_USER` -> `resume(approval=...)`;
- secret isolation — `SecretStore` + `scrub_env`, both sandbox backends scrub;
- audit event kinds + projection fields;
- Security gate — 26-case injection/abuse corpus + path-traversal battery + end-to-end
  objective-preservation.

Pending: the Tier-A sandbox is coded (`DockerSandbox`, arg-verified) but has not run a real
container — needs Docker Desktop installed, `slice-sandbox:pytest` built, and the
`--selftest` passing. Until then a dev-only non-isolating subprocess fallback is used and
refuses runs marked `allow_non_isolated=False`.

## Milestone D — recovery and progress (`milestone_b/`, days 1–13)

180 tests green. See `milestone_b/MILESTONE_D_NOTES.md`.

Now real (slice scope):
- deterministic meaningful-progress scoring (six hard signals; novel-motion guard);
- structural loop detection (repeated action / error / diff-thrash; progress clears history);
- per-task_class patience;
- the escalation ladder (inspect / change_strategy / ask_user real; critic / research /
  stronger_model stubbed to E and G);
- multi-step `_execute` with per-step T0 measurement and ladder hand-off;
- task budget (`wall_clock_s` / `steps` / cost) with 80% soft event and 100% pause;
- checkpoints, idempotency-key tracking;
- restart reconciliation — `reconcile()` → RESUME / REPAIR / ESCALATE / NOOP, wired into
  `resume()` (replaces the old "interrupted → FAIL"); RESUME steers the state machine back to
  EXECUTING and re-runs, workspace untouched.

Stubbed: ladder rungs critic/research/stronger_model; coverage/lint/type-error signals
(defined, unpopulated); REPAIR escalates rather than auto-re-interpreting; cost dimension
unmetered on the subscription path.

## Milestone E — multi-agent coordination (`milestone_b/`, days 1–14)

219 tests green. See `milestone_b/MILESTONE_E_NOTES.md`.

Now real (slice scope):
- **Critic** — one-shot pass, fresh context (contract + diff + target test, not the build
  narrative). T0 runs first; the Critic can never turn a T0-passing diff into a failure
  (a `reject` there is a logged `DISAGREEMENT`); a `reject` on a T0-fail drives one bounded
  retry with findings. Opt-in until the benchmark promotes it.
- **Structured `AgentMessage`** on every inter-role hand-off.
- **Independent T2 ensemble verifier** — model reconstructed-spec check from contract + diff
  alone, N contexts; advisory (T0 authoritative); escalates a T0-pass/T2-fail only when
  `risk_level ≥ medium` or a risky path.
- **Disagreement protocol** — name claims → discriminating test (T0) → synthesise → escalate
  if consequential.
- **Researcher** — query plan → egress-broker fetch (default deny) → claims + `EvidenceRecord`s
  at `retrieved_web` trust; wired to the D ladder `research` rung (fills that stub); the
  `critic` ladder rung is also real now.
- **Composition rule** + in-memory **RolePerformance** shadow tracking; `COMPOSITION` event.
- **Single-vs-multi benchmark** harness (`tests/benchmark/run_multiagent_bench.py`) — not yet
  run; needs the subscription; the Critic promote-to-default decision is gated on it.

Deferred: dedicated `research_web` orchestration (CD-research); real live egress fetch;
persistent RolePerformance (Milestone F); stronger-model ladder rung (Milestone G).

## Milestone F — memory and experience (`milestone_b/`, days 1–14)

254 tests green. All 14 days built. See `milestone_b/MILESTONE_F_NOTES.md`.

Now real (slice scope):
- **Hierarchical memory** — `app/services/memory/store.py` SQLite `memory` table
  (`working` / `project` / `experience` / `system` tiers); append-mostly, supersession by
  id, no deletion. `retrieve()` is keyword + recency + tier + **trust-filtered**
  (`trust_min="workspace"` never returns `retrieved_web` / `doc_input`); never returns
  `QUARANTINED` experience, `STALE` only when flagged.
- **Context builder** — `memory/context.py` `build_context()` assembles the
  Interpreter/Planner working context (active decisions / constraints / open questions /
  artifact index / scoped retrieval hits), replacing the empty `ProjectMemory`. A
  superseded decision drops out of later context. `MEMORY` events on read and write.
- **Situation signature** — `experience/signature.py` `{task_class, sorted salient tags,
  tool set}`; retrieval matches on class + tag overlap (the §14.7 similarity idea without
  embeddings). Stable for the same contract.
- **Experience lifecycle** — `experience/lifecycle.py` `OBSERVED → CANDIDATE → VALIDATED →
  PROMOTED → MONITORED → STALE / QUARANTINED` as an `ALLOWED` map + one numeric §8 gate per
  transition. `experience/store.py` `ExperienceStore` (SQLite): `capture()` on a T0-pass
  completion → `OBSERVED`, auto-`CANDIDATE` if the `(signature, strategy)` pair is new;
  `try_validate()` (shadow-replay gate), `try_promote()` (stub offline eval + security
  human-approval branch, auto-`MONITORED`), `record_use()` / `sweep_stale()` /
  auto-quarantine.
- **Stub offline eval** — `experience/eval.py`: `GUARDRAIL_SET` fixture, deterministic
  `run_offline_eval`, `promote_decision` folding the §8 numeric gate with the
  security/policy/execution-scope human-approval branch. Real held-out harness is Milestone I.
- **Orchestrator wiring** — `_experience_advice()` retrieves matching `PROMOTED` / `MONITORED`
  experiences at PLANNING and emits an advisory `AgentMessage(sender="experience",
  intent="PROPOSAL")`; the Planner still writes a fresh plan. `_capture_experience()` on a
  T0-pass completion. `flag_catastrophic()` — automatic experience rollback (`any →
  QUARANTINED`, no debounce) on a narrow signal set; auto-fires when T2 contradicts a
  T0-passing result.
- **Persistent RolePerformance** — `RolePerformanceStore(memory=…)` persists per
  `(role, task_class)` to system memory (`MemoryStore.record_role_perf` /
  `latest_role_perf`); a fresh store over the same DB hydrates the accumulated numbers, so
  the composition rule reads performance across runs.
- **Event kinds** — `MEMORY`, `EXPERIENCE`, `EXPERIENCE_TRANSITION`.

Deferred: embedding / vector retrieval (CD-rag); the real held-out offline-eval harness
(Milestone I); benchmark rows in system memory (Milestone G); shadow-replay in practice may
never reach 5 matching tasks on a single-user machine — `CANDIDATE` is an acceptable
terminal state and experiences stay advisory regardless.

## Milestone G — routing and hardware (`milestone_b/`, days 1–14)

271 tests green. All 14 days built. See `milestone_b/MILESTONE_G_NOTES.md`.

Now real (slice scope):
- **Provider registry** — `ProviderSpec` + `ProviderRegistry`; default seed has `agent_sdk`
  (subscription, cloud, the only `available` entry), `anthropic` (billed, opt-in), and three
  local tiers declared `available=False` (the local backend adapter is a named seam).
- **Static routing table (§7.1)** — one `RoutePolicy` per `task_class` + `escalation_reason()`
  predicates for the "escalate to cloud when …" column; `planning_arch` is always cloud.
- **Routing stats (§7.2)** — `RouteStatsStore` over the system memory tier; a run is scored
  only with a T1+ verification link; trailing 90 d / last 50; a model is eligible for a class
  at ≥ 20 scored runs.
- **Router** — static default → escalation / hardware-local override → data-driven score
  (`PROVISIONAL_WEIGHTS`, tagged; displaces the static pick only past a stability margin) →
  ε = 0.15 seeded exploration below eligibility.
- **Hardware modes** — `NORMAL…EMERGENCY` policy (`decide()`), a static-snapshot monitor seam;
  the router pauses on EMERGENCY and biases local on CONSERVATION+.
- **`stronger_model` ladder rung made real** — re-routes a stalled task to the best untried
  cloud provider and drives a re-plan; non-actionable on the default single-cloud registry.
- **Orchestrator wiring** — `router` / `route_stats` / `hardware` opt-in; `ROUTE` + `HARDWARE`
  events; `MODEL_RUN`s tagged and ingested on a verified completion; a fresh `Orchestrator`
  over the same system memory reuses the accumulated stats. Router unset → unchanged.
- **Offline eligibility seeder** — `tests/benchmark/seed_model.py` (not run; needs the
  subscription).
- **Event kinds** — `ROUTE`, `HARDWARE`.

Deferred: local model backend adapters (registry rows exist, unavailable); per-task role-LLM
swap from the chosen `ProviderSpec`; real hardware telemetry; logistic-regression weight fit
+ canary (Milestone I).

## Milestone I — optimization (`milestone_b/`, days 1–14)

290 tests green. All 14 days built. See `milestone_b/MILESTONE_I_NOTES.md`.

Now real (slice scope):
- **Frozen guardrail suite** — `eval/guardrail.py` + a 12-task JSON fixture (each a
  self-contained module + T0 test with a known oracle); `GuardrailSuite.run(run_one)` with an
  injected runner, deterministic order, crash = fail. Target ~30.
- **Regression gate** — `eval/regression.py`: `check_regression()` passes iff aggregate drop
  ≤ 2 pp **and** no previously-passing guardrail task now fails. `RegressionBaseline` on the
  system memory tier; `certify()` fails closed with no baseline.
- **Offline eval** — `eval/offline_eval.py`: `OfflineEval.evaluate()` replays a held-out set
  with vs. without the change, then the guardrail gate; `decision="promote"` only at
  `heldout_n ≥ 10` + non-negative delta + guardrail held; security-scope subjects still need
  human approval. `ExperienceStore.try_promote(report=)` consumes a real `EvalReport`.
- **Canary** — `eval/canary.py` `CanaryController` (deterministic fractional cohort,
  HOLD/PROMOTE/ROLLBACK). Orchestrator (opt-in `canary_enabled`): a freshly-promoted
  experience's canary cohort underperforming → auto-`QUARANTINED` + `CANARY` event; a
  data-driven routing challenger underperforming → `route_freeze` in system memory + the
  router skips it.
- **Derived metrics** — `eval/metrics.py` `rebuild_metrics()` folds the event log into the
  §11.2 set (success by class, rework rate, verify-tier mix, escalation freq, budget-exhaust
  rate, quarantine count). Pure function, no store.
- **Standalone runner** — `tests/regression/run_guardrail.py` (real orchestrator; `--offline`
  scripted smoke path verified; real-model run not run here).
- **Event kinds** — `EVAL`, `CANARY`, `REGRESSION`.

Deferred: the real held-out numbers (need the subscription); guardrail suite growth to ~30;
wiring `OfflineEval` into an orchestrator-driven promotion job; logistic-regression weight
fit; scheduled/continuous guardrail runs (need Milestone H).

## Milestone H — desktop shell (`milestone_b/`, days 1–14)

306 tests green. All 14 days built. See `milestone_b/MILESTONE_H_NOTES.md`.

Now real (slice scope):
- **Read models** — `app/ui/readmodels.py`: six pure folds of the event log — task list,
  per-task timeline (rows + state transitions + spend + verification), agents panel (latest
  `AgentMessage` per role), system-health strip (hardware mode / budget posture / canary
  count / quarantine count), metrics panel (wraps `rebuild_metrics`), routing tallies. No
  state; unmapped event kinds degrade to a generic row.
- **Event feed** — `app/ui/events.py` `EventFeed` tails the append-only `events` table by
  `seq`; `sse_frame()` formats Server-Sent-Events.
- **HTTP + SSE server** — `app/ui/server.py`: stdlib `http.server`, loopback-only, no runtime
  dependency. `GET /api/*` serve the read models as JSON; `GET /api/stream` tails the log as
  SSE; `GET /` + assets serve the frontend. `POST /api/tasks` returns 405 unless a `runner`
  is wired (`--allow-submit`), and a submitted task still passes every gate.
- **Frontend** — `app/ui/web/{index.html,app.js,style.css}`: one self-contained vanilla-JS
  page, no build step; subscribes to the stream and renders every panel; reconnects on drop.
  Replaces the prior static mock. Verified live against a seeded DB.
- **Entrypoint** — `app/ui/run_ui.py` (`--db`, `--port`, `--allow-submit`).

**Tauri packaging** (`milestone_b/desktop/`, MILESTONE_H_TAURI_PLAN.md) — scaffolded:
`app/ui/paths.py` (frozen-aware `web_dir` / `default_db_path`), `app/ui/sidecar_main.py`
(PyInstaller entry, tested as a subprocess), and a complete Tauri v2 project — `Cargo.toml`,
`tauri.conf.json`, `capabilities/default.json` (shell-execute scoped to the sidecar only),
`src/main.rs` (spawn sidecar → TCP-poll → navigate → kill-on-exit), `build_sidecar.py`
(PyInstaller), `build.py` (one command, fails fast on a missing prerequisite), `gen_icons.py`
+ committed icons, `dist/splash.html`, `README.md`. The Rust side is written to the Tauri v2
API but **not `cargo build`-verified** here (no Rust toolchain); the Python half is tested.
`build.py` exits 2 with the missing prerequisites in this environment (asserted).

Deferred: producing the signed native binary (needs Rust + PyInstaller + platform build
tools + certs); a framework rewrite; SSE poll → push; async submit jobs; auto-update / tray /
single-instance; live-diff / evidence-graph / experience-browser panels (each = one fold +
one route).

## Milestone J — repo intelligence & Git adapter (`milestone_b/`, days 1–14)

333 tests green. All 14 days built. First §10.2 capability domain. See
`milestone_b/MILESTONE_J_NOTES.md`.

Now real (slice scope):
- **Git adapter** — `app/services/repo/git_adapter.py` `GitAdapter`: deterministic wrapper
  over the `git` CLI. Read (status / branch / head / clean / tracked / log / blame / show /
  diff / changed-files) always available; `create_branch` / `commit` gated on a
  `write_allowed` predicate. One `_run_git` (arg-list, 20 s timeout, `GitError`).
  **No `fetch`/`pull`/`push`/`remote` method exists.**
- **Symbol index** — `app/services/repo/index.py` `RepoIndex`: per-file `FileFacts`
  (defs + imports) via Python `ast`, regex fallback for other languages (flagged
  `approximate`). Broken files skipped, not fatal. Bounded, derived, rebuilt per `HEAD`.
- **Module graph** — `app/services/repo/graph.py` `ModuleGraph`: internal import edges;
  `dependencies` / `dependents` (transitive, cycle-safe); `reachable_dependents` = blast
  radius; `fan_in`.
- **Impact analysis** — `app/services/repo/impact.py` `analyze()` → `ImpactReport`:
  changed → dependent modules (prod only), `tests_affected` (fan-in-ranked, capped),
  `risk_flags` (`risk-path` / `public-api` / `wide-change` / `symbol-removed` /
  `signature-changed`). Import reachability is a superset heuristic; T0 stays authoritative.
- **Breadth classification** — `app/services/repo/breadth.py` `classify_breadth()` →
  `BreadthAdvice{local|broad, …}`; advisory, never mutates `task_class`.
- **Facade + wiring** — `RepoIntelligence` (lazy, `head_sha`-cached); `orch.repo` opt-in:
  `REPO CONTEXT` block for the Interpreter + Planner (`REPO` event); post-build
  `ImpactReport` (`IMPACT` event + a `repo`-sender `AgentMessage`); the impact's affected
  tests are passed to `VerifierT0.verify(extra_targets=)` and run alongside the named target
  (widen the check; the named target still gates COMPLETED). Repo unset → unchanged.
- **Capability tokens** — `vcs.read`, `vcs.write` (`vcs.branch` / `vcs.commit` are
  side-effecting → taint + risk-class gated).
- **Event kinds** — `REPO`, `IMPACT`.

Deferred: tree-sitter multi-language parsing (Python-first now); a `vcs.write`-driven
work-on-a-branch flow (adapter ready, no step requests it; **no push/PR ever**);
persistent cross-process index; a dedicated `code_edit_broad` orchestration.

## Milestone K — research pipeline & evidence graph (`milestone_b/`, days 1–14)

344 tests green. All 14 days built. Second §10.2 capability domain. See
`milestone_b/MILESTONE_K_NOTES.md`.

Now real (slice scope):
- **Evidence graph** — `app/services/research/evidence_graph.py`: sources + claims + edges
  (support / agrees / contradicts / answers); `contradictions()`, `is_primary()` (doc kind
  or official host outranks a generic page; a contradiction auto-resolves when one side has
  a primary source).
- **Injection scan** — `research/injection.py` `scan()`: pattern flags for override /
  role-injection / system-marker / tool-directive / exfiltration. A signal on the answer,
  not a content gate.
- **Decompose / cross-check / synthesis** — `research/{decompose,crosscheck,synthesize}.py`:
  question → 2–5 sub-questions; contradicting-claim detection + bounded (≤ 2) follow-up
  rounds + resolution; **claims-only** synthesis → `ResearchAnswer{sections+citation_ids,
  contested, citations, uncertainty}` at `retrieved_web` trust (the synthesis prompt carries
  no raw source text — unit-asserted).
- **Pipeline** — `research/pipeline.py` `ResearchPipeline.run()` ties it together over the
  Milestone E Researcher + egress broker.
- **Orchestrator** — `orch.research` opt-in; a `research_web` task runs the pipeline instead
  of plan→build→verify (`PLANNING`→`EXECUTING`→`OBSERVATION`→`VERIFYING`→`COMPLETED`), the
  `ResearchAnswer` as its artifact; `RESEARCH` + `SYNTHESIS` events.
- **Contract gate** — `validate_contract` is now task-class-aware: only the code-editing
  classes require a pytest T0 target.
- **§12** — source text never reaches a decision prompt; every research node is
  `retrieved_web` trust so it cannot originate a side effect; a planted "ignore previous
  instructions … exfiltrate" page is flagged and changes nothing (integration-asserted).
- **Event kinds** — `RESEARCH`, `SYNTHESIS`.

Deferred: real live egress fetch; HTML/PDF readability extraction; multi-hop provenance;
learned source reputation.

## Milestone L — RAG / knowledge base (`milestone_b/`, days 1–14)

357 tests green. All 14 days built. Third §10.2 capability domain. See
`milestone_b/MILESTONE_L_NOTES.md`.

Now real (slice scope):
- **KnowledgeBase** — `app/services/kb/store.py`: SQLite documents + chunks; `ingest_text` /
  `ingest_file` / `ingest_dir` (text suffixes only, size + binary guards, sha-idempotent);
  every ingest runs the injection scan → `document.flags`. The retrieval index is derived
  (`rebuild_index()` from the chunk table, §11.3).
- **Chunking** — `kb/chunk.py`: heading-aware sliding window with overlap; deterministic.
- **Lexical retrieval** — `kb/lexical.py` `LexicalIndex` (Okapi BM25) as the stdlib fallback
  behind the `kb/retrieve.py` `Retriever` protocol — **a real embedding store / RAG framework
  slots in here** (§16: "do not build, integrate").
- **KB answer** — `kb/answer.py`: retrieve → per-chunk claim extraction (delimited
  `DOCUMENT CONTEXT`) → claims-only `research.synthesize` → `KBAnswer{sections+citations,
  uncertainty}` at `doc_input` trust; a no-match states the gap.
- **Research hook** — `ResearchPipeline(kb=)` adds `doc_input` KB sources per sub-question,
  so an answer blends library + web with per-source trust visible.
- **Orchestrator** — `orch.kb` opt-in; a `doc_analysis` task runs the KB answer path
  (`PLANNING`→`EXECUTING`→`KB`+`SYNTHESIS`→`OBSERVATION`→`VERIFYING`→`COMPLETED`); `KBAnswer`
  as artifact.
- **§12** — chunk text never reaches a decision prompt; every KB node is `doc_input` trust so
  it cannot originate a side effect; a planted-directive document is flagged and changes
  nothing.
- **Event kind** — `KB`.

Deferred: a real embedding / RAG framework behind `Retriever`; OCR + office-format parsing;
cross-encoder rerank; incremental re-index.

## Milestone M — authoring pipelines (`milestone_b/`, days 1–14)

369 tests green. All 14 days built. Fourth §10.2 capability domain. See
`milestone_b/MILESTONE_M_NOTES.md`.

Now real (slice scope):
- **Document model** — `app/services/authoring/model.py`: `DocumentModel` / `Section` /
  `Block` (7 kinds) / `Citation`; `all_citations()` in first-reference order; `SlideDeck`
  (one slide per H2).
- **Renderers** — `authoring/render.py`: `Renderer` protocol; `MarkdownRenderer` +
  `HtmlRenderer` ship (references section, escaping, tables/code/lists); `Docx/Pptx/Pdf`
  renderers are stubs raising `RendererUnavailable` — the §16 integration seam.
- **outline → draft → review** — `authoring/{outline,draft,review}.py`: retrieval-grounded
  heading tree (KB-unsupported sections flagged); per-section claims-only body from KB claims
  + brief + memory context, `doc_input`-trust citations attached; a review pass (structural
  + LLM) → `Issue[]` (§7.1's review pass).
- **Pipeline** — `authoring/pipeline.py` `AuthoringPipeline.run()` → `AuthoringResult`; no
  filesystem write (the artifact is the rendered string).
- **Orchestrator** — `orch.authoring` opt-in; an `authoring` task runs the pipeline
  (`PLANNING`→`EXECUTING`→`AUTHORING`+`SYNTHESIS`→`OBSERVATION`→`VERIFYING`→`COMPLETED`);
  `deck` kind if the brief says "slide"/"deck"; a `blocking` review issue →
  `WAITING_FOR_USER`.
- **§12** — grounded claims keep their trust on each `Citation`; no write, no network; the
  rendered doc is a `workspace` artifact, not evidence.
- **Event kind** — `AUTHORING`.

Deferred: real DOCX/PPTX/PDF renderers behind `Renderer`; a revise loop; templates/themes;
generated figures. Next §10.2 domains: engine adapters + expert modes (needs J), automated
model selection (needs G + ≥ 20 verified runs).
